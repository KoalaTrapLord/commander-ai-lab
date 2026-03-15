"""
Commander AI Lab — Lobby Manager (Phase 8)
==========================================
Manages game rooms from creation through launch:

  RoomState  WAITING → READY → IN_PROGRESS → FINISHED

Flow:
  1. Host calls LobbyManager.create_room() → returns room_id
  2. Players join via LobbyManager.join_room(room_id, player_name)
  3. Each player calls set_ready(room_id, seat) when prepared
  4. When all human slots are ready, room transitions to READY
  5. Host calls launch_game(room_id) → fires on_launch callback
  6. Room moves to IN_PROGRESS; late-joins become spectators

AI slots are pre-filled and always considered ready.
"""

from __future__ import annotations

import secrets
import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, Awaitable


MAX_PLAYERS   = 4
MAX_SPECTATORS = 20
ROOM_ID_BYTES  = 6


class RoomState(Enum):
    WAITING     = auto()
    READY       = auto()
    IN_PROGRESS = auto()
    FINISHED    = auto()


@dataclass
class LobbySlot:
    seat:        int
    player_name: Optional[str]  = None
    is_ai:       bool           = False
    ai_personality: Optional[str] = None
    is_host:     bool           = False
    is_ready:    bool           = False
    connection_id: Optional[str] = None   # WebSocket connection tag

    @property
    def is_filled(self) -> bool:
        return self.player_name is not None or self.is_ai

    def to_dict(self) -> dict:
        return {
            "seat":           self.seat,
            "player_name":    self.player_name,
            "is_ai":          self.is_ai,
            "ai_personality": self.ai_personality,
            "is_host":        self.is_host,
            "is_ready":       self.is_ready,
        }


# Callback fired when a room is launched: async fn(room_id, room)
LaunchCallback = Callable[[str, "LobbyRoom"], Awaitable[None]]


@dataclass
class LobbyRoom:
    room_id:    str
    room_name:  str
    max_players: int                       = MAX_PLAYERS
    state:      RoomState                  = RoomState.WAITING
    slots:      list[LobbySlot]            = field(default_factory=list)
    spectators: list[str]                  = field(default_factory=list)  # connection_ids
    password:   Optional[str]              = None
    chat:       Optional[object]           = None   # ChatChannel injected post-construction
    created_at: float                      = field(default_factory=lambda: __import__('time').time())
    launched_at: Optional[float]           = None

    def __post_init__(self):
        if not self.slots:
            self.slots = [LobbySlot(seat=i) for i in range(self.max_players)]

    # ------------------------------------------------------------------
    # Slot helpers
    # ------------------------------------------------------------------

    def open_seats(self) -> list[int]:
        return [s.seat for s in self.slots if not s.is_filled]

    def human_seats(self) -> list[int]:
        return [s.seat for s in self.slots if s.is_filled and not s.is_ai]

    def all_humans_ready(self) -> bool:
        humans = [s for s in self.slots if s.is_filled and not s.is_ai]
        return bool(humans) and all(s.is_ready for s in humans)

    def all_seats_filled(self) -> bool:
        return all(s.is_filled for s in self.slots)

    def get_slot(self, seat: int) -> Optional[LobbySlot]:
        return next((s for s in self.slots if s.seat == seat), None)

    def to_dict(self) -> dict:
        return {
            "room_id":    self.room_id,
            "room_name":  self.room_name,
            "state":      self.state.name,
            "slots":      [s.to_dict() for s in self.slots],
            "spectators": len(self.spectators),
            "has_password": self.password is not None,
        }


class LobbyManager:
    """
    Singleton-style registry of all active lobby rooms.

    Usage::

        mgr  = LobbyManager()
        rid  = await mgr.create_room("Friday Night Commander", host_name="Alice")
        seat = await mgr.join_room(rid, "Bob")
        await mgr.set_ready(rid, seat)
        await mgr.launch_game(rid)
    """

    def __init__(
        self,
        on_launch: Optional[LaunchCallback] = None,
    ) -> None:
        self._rooms: dict[str, LobbyRoom] = {}
        self._on_launch = on_launch

    # ------------------------------------------------------------------
    # Room lifecycle
    # ------------------------------------------------------------------

    async def create_room(
        self,
        room_name: str,
        host_name: str,
        max_players: int = MAX_PLAYERS,
        ai_slots: Optional[list[dict]] = None,   # [{seat:int, personality:str}, ...]
        password: Optional[str] = None,
    ) -> str:
        """
        Create a new lobby room. Returns room_id.
        Host occupies seat 0. AI slots are pre-filled.
        """
        room_id = secrets.token_hex(ROOM_ID_BYTES)
        room    = LobbyRoom(
            room_id=room_id,
            room_name=room_name,
            max_players=max_players,
            password=password,
        )
        # Fill host into seat 0
        room.slots[0].player_name = host_name
        room.slots[0].is_host     = True
        room.slots[0].is_ready    = False

        # Fill AI slots
        for ai in (ai_slots or []):
            seat = ai.get("seat")
            if seat is None or seat >= max_players:
                continue
            slot = room.get_slot(seat)
            if slot and not slot.is_filled:
                slot.is_ai         = True
                slot.player_name   = f"AI-{ai.get('personality','spike').title()}"
                slot.ai_personality = ai.get("personality", "spike")
                slot.is_ready      = True   # AI always ready

        self._rooms[room_id] = room
        return room_id

    async def join_room(
        self,
        room_id: str,
        player_name: str,
        password: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> int:
        """
        Join an existing room. Returns the assigned seat number.
        Raises ValueError on invalid room / wrong password / full room.
        """
        room = self._get_room(room_id)
        if room.state != RoomState.WAITING:
            raise ValueError("Room is not accepting new players.")
        if room.password and room.password != password:
            raise ValueError("Incorrect room password.")
        open_seats = room.open_seats()
        if not open_seats:
            raise ValueError("Room is full.")
        seat = open_seats[0]
        slot = room.get_slot(seat)
        slot.player_name  = player_name
        slot.connection_id = connection_id
        return seat

    async def add_spectator(
        self,
        room_id: str,
        connection_id: str,
    ) -> None:
        """Add a spectator connection to a room."""
        room = self._get_room(room_id)
        if len(room.spectators) >= MAX_SPECTATORS:
            raise ValueError("Spectator limit reached.")
        if connection_id not in room.spectators:
            room.spectators.append(connection_id)

    async def set_ready(
        self,
        room_id: str,
        seat: int,
        ready: bool = True,
    ) -> RoomState:
        """Mark a seat as ready. Returns the new room state."""
        room = self._get_room(room_id)
        slot = room.get_slot(seat)
        if slot is None:
            raise ValueError(f"Seat {seat} not found.")
        slot.is_ready = ready
        if room.all_humans_ready() and room.all_seats_filled():
            room.state = RoomState.READY
        else:
            room.state = RoomState.WAITING
        return room.state

    async def launch_game(
        self,
        room_id: str,
    ) -> LobbyRoom:
        """Launch the game. Room must be in READY state."""
        room = self._get_room(room_id)
        if room.state != RoomState.READY:
            raise ValueError(f"Room not ready (state={room.state.name}).")
        room.state       = RoomState.IN_PROGRESS
        room.launched_at = __import__('time').time()
        if self._on_launch:
            await self._on_launch(room_id, room)
        return room

    async def finish_room(
        self,
        room_id: str,
    ) -> None:
        room = self._get_room(room_id)
        room.state = RoomState.FINISHED

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_room(self, room_id: str) -> Optional[LobbyRoom]:
        return self._rooms.get(room_id)

    def list_open_rooms(self) -> list[dict]:
        return [
            r.to_dict() for r in self._rooms.values()
            if r.state == RoomState.WAITING
        ]

    def list_all_rooms(self) -> list[dict]:
        return [r.to_dict() for r in self._rooms.values()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_room(self, room_id: str) -> LobbyRoom:
        room = self._rooms.get(room_id)
        if room is None:
            raise ValueError(f"Room '{room_id}' not found.")
        return room
