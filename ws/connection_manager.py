"""WebSocket connection manager for game-state streaming.

Manages per-game-session WebSocket connections so the server can
push state deltas to every connected Unity client in real time.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("ws.connection_manager")


@dataclass
class ClientInfo:
    """Metadata for a single connected WebSocket client."""
    ws: WebSocket
    client_id: str
    game_id: str
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    messages_sent: int = 0


class ConnectionManager:
    """Manages WebSocket connections grouped by game_id.

    Usage:
        manager = ConnectionManager()
        await manager.connect(websocket, game_id, client_id)
        await manager.broadcast_to_game(game_id, payload)
        manager.disconnect(websocket, game_id)
    """

    def __init__(self, heartbeat_interval: float = 30.0):
        # game_id -> set of ClientInfo
        self._games: Dict[str, Dict[str, ClientInfo]] = {}
        self._heartbeat_interval = heartbeat_interval
        self._lock = asyncio.Lock()

    # ── Connect / Disconnect ───────────────────────────────

    async def connect(
        self, ws: WebSocket, game_id: str, client_id: str
    ) -> ClientInfo:
        """Accept and register a WebSocket connection."""
        await ws.accept()
        client = ClientInfo(ws=ws, client_id=client_id, game_id=game_id)
        async with self._lock:
            if game_id not in self._games:
                self._games[game_id] = {}
            self._games[game_id][client_id] = client
        log.info(
            "WS connected: client=%s game=%s (total=%d)",
            client_id, game_id, len(self._games[game_id]),
        )
        return client

    async def disconnect(self, game_id: str, client_id: str) -> None:
        """Remove a client from the game session."""
        async with self._lock:
            game = self._games.get(game_id)
            if game and client_id in game:
                del game[client_id]
                if not game:
                    del self._games[game_id]
        log.info("WS disconnected: client=%s game=%s", client_id, game_id)

    # ── Broadcasting ───────────────────────────────────────

    async def broadcast_to_game(
        self, game_id: str, payload: dict
    ) -> int:
        """Send a JSON payload to every client in a game session.

        Returns the number of clients that received the message.
        Silently removes clients whose connections are broken.
        """
        async with self._lock:
            game = self._games.get(game_id)
            if not game:
                return 0
            clients = list(game.values())

        sent = 0
        dead: List[str] = []
        for client in clients:
            try:
                await client.ws.send_json(payload)
                client.messages_sent += 1
                sent += 1
            except Exception:
                dead.append(client.client_id)

        # Clean up broken connections
        if dead:
            async with self._lock:
                game = self._games.get(game_id)
                if game:
                    for cid in dead:
                        game.pop(cid, None)
                    if not game:
                        del self._games[game_id]
            log.warning(
                "Removed %d dead connection(s) from game %s",
                len(dead), game_id,
            )
        return sent

    async def send_to_client(
        self, game_id: str, client_id: str, payload: dict
    ) -> bool:
        """Send a JSON payload to a specific client."""
        async with self._lock:
            game = self._games.get(game_id)
            if not game:
                return False
            client = game.get(client_id)
            if not client:
                return False
        try:
            await client.ws.send_json(payload)
            client.messages_sent += 1
            return True
        except Exception:
            await self.disconnect(game_id, client_id)
            return False

    # ── Queries ────────────────────────────────────────────

    def get_game_clients(self, game_id: str) -> List[str]:
        """Return client IDs connected to a game."""
        game = self._games.get(game_id, {})
        return list(game.keys())

    def active_games(self) -> List[str]:
        """Return all game IDs with active connections."""
        return list(self._games.keys())

    @property
    def total_connections(self) -> int:
        return sum(len(g) for g in self._games.values())

    def stats(self) -> dict:
        """Return connection statistics."""
        return {
            "active_games": len(self._games),
            "total_connections": self.total_connections,
            "games": {
                gid: {
                    "clients": len(clients),
                    "client_ids": list(clients.keys()),
                }
                for gid, clients in self._games.items()
            },
        }


# Module-level singleton
game_manager = ConnectionManager()
