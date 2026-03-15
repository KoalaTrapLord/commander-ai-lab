"""
Commander AI Lab — WebSocket Connection Manager (Phase 5)
==========================================================
Manages active WebSocket connections grouped by game_id.
Handles:
  - connect / disconnect lifecycle
  - broadcast to all connections in a game room
  - per-seat send (used for private hand data)
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Optional

from fastapi import WebSocket


class ConnectionManager:
    """
    Thread-safe (asyncio) WebSocket connection registry.

    Connections are keyed by game_id. Each connection also records its seat
    so the server can send private data (e.g. hand cards) to a specific player.
    """

    def __init__(self) -> None:
        # game_id -> list of (WebSocket, seat)
        self._rooms: dict[str, list[tuple[WebSocket, int]]] = defaultdict(list)

    async def connect(
        self,
        ws: WebSocket,
        game_id: str,
        seat: int,
    ) -> None:
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        self._rooms[game_id].append((ws, seat))

    def disconnect(
        self,
        ws: WebSocket,
        game_id: str,
    ) -> None:
        """Remove a disconnected WebSocket from its room."""
        self._rooms[game_id] = [
            (w, s) for w, s in self._rooms[game_id] if w is not ws
        ]
        if not self._rooms[game_id]:
            del self._rooms[game_id]

    async def broadcast(
        self,
        game_id: str,
        message: dict,
    ) -> None:
        """
        Send a JSON message to all connections in a game room.
        Dead connections are silently removed.
        """
        payload  = json.dumps(message)
        dead: list[WebSocket] = []

        for ws, seat in list(self._rooms.get(game_id, [])):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, game_id)

    async def send_to_seat(
        self,
        game_id: str,
        seat: int,
        message: dict,
    ) -> None:
        """
        Send a JSON message only to connections with a matching seat.
        Used for private hand updates.
        """
        payload = json.dumps(message)
        for ws, s in list(self._rooms.get(game_id, [])):
            if s == seat:
                try:
                    await ws.send_text(payload)
                except Exception:
                    self.disconnect(ws, game_id)

    def connection_count(self, game_id: str) -> int:
        return len(self._rooms.get(game_id, []))

    def seats_connected(self, game_id: str) -> list[int]:
        return [s for _, s in self._rooms.get(game_id, [])]
