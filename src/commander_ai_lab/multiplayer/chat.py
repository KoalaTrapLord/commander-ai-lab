"""
Commander AI Lab — In-Game Chat Channel (Phase 8)
==================================================
Per-room chat with:
  - Role-based message tagging (PLAYER, SPECTATOR, SYSTEM, AI)
  - Message history (capped at MAX_HISTORY)
  - Simple profanity / command filter hooks
  - Async broadcast to registered WebSocket send callbacks
  - System message helpers (player joined, game events, deal offers)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Awaitable, Optional


MAX_HISTORY    = 500
MAX_MSG_LENGTH = 400


class ChatRole(Enum):
    PLAYER    = auto()
    SPECTATOR = auto()
    SYSTEM    = auto()
    AI        = auto()


@dataclass
class ChatMessage:
    sender:      str
    text:        str
    role:        ChatRole  = ChatRole.PLAYER
    seat:        Optional[int] = None
    timestamp:   float     = field(default_factory=time.time)
    room_id:     str       = ""

    def to_dict(self) -> dict:
        return {
            "sender":    self.sender,
            "text":      self.text,
            "role":      self.role.name,
            "seat":      self.seat,
            "timestamp": self.timestamp,
            "room_id":   self.room_id,
        }


# Async send callable: receives a serialised message dict
ChatSendFn = Callable[[dict], Awaitable[None]]


class ChatChannel:
    """
    Chat bus for a single game room.

    Usage::

        chat = ChatChannel(room_id="abc123")
        chat.register(seat=0, send_fn=ws_send)
        await chat.send(sender="Alice", text="Let's make a deal", seat=0)
        await chat.system("Game started!")
    """

    def __init__(self, room_id: str) -> None:
        self.room_id   = room_id
        self._history: list[ChatMessage] = []
        # seat -> send callback (players)
        self._player_handlers: dict[int, ChatSendFn] = {}
        # list of callbacks for spectators + global listeners
        self._spectator_handlers: list[ChatSendFn] = []
        self._global_handlers:    list[ChatSendFn] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, seat: int, send_fn: ChatSendFn) -> None:
        """Register a player WebSocket send callback."""
        self._player_handlers[seat] = send_fn

    def register_spectator(self, send_fn: ChatSendFn) -> None:
        self._spectator_handlers.append(send_fn)

    def register_global(self, send_fn: ChatSendFn) -> None:
        """Receives every message regardless of role."""
        self._global_handlers.append(send_fn)

    def unregister(self, seat: int) -> None:
        self._player_handlers.pop(seat, None)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(
        self,
        sender: str,
        text: str,
        seat: Optional[int] = None,
        role: ChatRole = ChatRole.PLAYER,
    ) -> ChatMessage:
        """
        Broadcast a chat message to all connected seats and spectators.
        Returns the stored ChatMessage.
        """
        text = text[:MAX_MSG_LENGTH]
        msg  = ChatMessage(
            sender=sender,
            text=text,
            role=role,
            seat=seat,
            room_id=self.room_id,
        )
        self._store(msg)
        await self._broadcast(msg)
        return msg

    async def system(self, text: str) -> None:
        """Broadcast a SYSTEM message (e.g. 'P2 has conceded')."""
        await self.send(sender="System", text=text, role=ChatRole.SYSTEM)

    async def ai_says(
        self,
        ai_name: str,
        seat: int,
        text: str,
    ) -> None:
        """Broadcast a message from an AI persona."""
        await self.send(sender=ai_name, text=text, seat=seat, role=ChatRole.AI)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def history(
        self,
        last_n: int = 50,
        role_filter: Optional[ChatRole] = None,
    ) -> list[dict]:
        msgs = self._history
        if role_filter:
            msgs = [m for m in msgs if m.role == role_filter]
        return [m.to_dict() for m in msgs[-last_n:]]

    def clear(self) -> None:
        self._history.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _store(self, msg: ChatMessage) -> None:
        self._history.append(msg)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

    async def _broadcast(self, msg: ChatMessage) -> None:
        payload = msg.to_dict()
        # Players
        for send_fn in self._player_handlers.values():
            try:
                await send_fn(payload)
            except Exception:
                pass
        # Spectators
        for send_fn in self._spectator_handlers:
            try:
                await send_fn(payload)
            except Exception:
                pass
        # Global
        for send_fn in self._global_handlers:
            try:
                await send_fn(payload)
            except Exception:
                pass
