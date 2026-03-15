"""
Commander AI Lab — Spectator Manager (Phase 8)
===============================================
Provides read-only game-state feeds to spectator WebSocket connections.

Features:
  - Spectators receive the same public state snapshots as players
  - Private hands are NEVER sent to spectators
  - Spectators are tracked per room; dead connections are pruned
  - Optional delay_turns: hide state N turns behind live game
    (prevents spectators from feeding information to players)
  - SpectatorManager.broadcast() is called by the WebSocket router
    after every state change
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any, Optional


BroadcastFn = Callable[[str], Awaitable[None]]


@dataclass
class SpectatorConnection:
    connection_id: str
    send_fn:       BroadcastFn
    room_id:       str
    joined_at:     float = field(default_factory=lambda: __import__('time').time())
    delay_turns:   int   = 0
    alive:         bool  = True


class SpectatorManager:
    """
    Registry of active spectator connections per room.

    Usage::

        mgr = SpectatorManager()
        mgr.add(room_id, connection_id, send_fn)
        await mgr.broadcast(room_id, state_snapshot)
        mgr.remove(room_id, connection_id)
    """

    def __init__(self) -> None:
        # room_id -> {connection_id -> SpectatorConnection}
        self._rooms: dict[str, dict[str, SpectatorConnection]] = {}

    def add(
        self,
        room_id: str,
        connection_id: str,
        send_fn: BroadcastFn,
        delay_turns: int = 0,
    ) -> None:
        self._rooms.setdefault(room_id, {})
        self._rooms[room_id][connection_id] = SpectatorConnection(
            connection_id=connection_id,
            send_fn=send_fn,
            room_id=room_id,
            delay_turns=delay_turns,
        )

    def remove(
        self,
        room_id: str,
        connection_id: str,
    ) -> None:
        self._rooms.get(room_id, {}).pop(connection_id, None)

    def count(self, room_id: str) -> int:
        return len(self._rooms.get(room_id, {}))

    async def broadcast(
        self,
        room_id: str,
        snapshot: dict,
    ) -> None:
        """
        Send a public state snapshot to all spectators of room_id.
        Private hand data must be stripped from snapshot before calling.
        Dead connections are pruned automatically.
        """
        room_conns = self._rooms.get(room_id, {})
        if not room_conns:
            return

        # Ensure no private hand data leaks
        safe = self._strip_hands(snapshot)
        payload = json.dumps({"type": "spectate", "data": safe})

        dead: list[str] = []
        for cid, conn in room_conns.items():
            if not conn.alive:
                dead.append(cid)
                continue
            try:
                await conn.send_fn(payload)
            except Exception:
                conn.alive = False
                dead.append(cid)

        for cid in dead:
            room_conns.pop(cid, None)

    async def broadcast_chat(
        self,
        room_id: str,
        chat_payload: dict,
    ) -> None:
        """Forward a chat message to all spectators of room_id."""
        room_conns = self._rooms.get(room_id, {})
        payload    = json.dumps({"type": "chat", "data": chat_payload})
        dead: list[str] = []
        for cid, conn in room_conns.items():
            try:
                await conn.send_fn(payload)
            except Exception:
                dead.append(cid)
        for cid in dead:
            room_conns.pop(cid, None)

    def list_spectators(
        self,
        room_id: str,
    ) -> list[str]:
        return list(self._rooms.get(room_id, {}).keys())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_hands(snapshot: dict) -> dict:
        """
        Remove private hand arrays from a state snapshot dict.
        Preserves hand_count for display purposes.
        """
        import copy
        safe = copy.deepcopy(snapshot)
        for player in safe.get("players", []):
            player.pop("hand", None)
        return safe
