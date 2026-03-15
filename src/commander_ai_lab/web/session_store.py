"""
Commander AI Lab — Session Store (Phase 5)
==========================================
In-memory registry of live GameSession objects.

Each session wraps:
  - A CommanderGameState
  - A CommanderTurnManager (running in a background asyncio task)
  - A broadcast callback (set by the WebSocket router)

SessionStore is intentionally not thread-safe beyond asyncio coroutines —
all mutations happen in the async event loop.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional, Awaitable


# ---------------------------------------------------------------------------
# Stub game state / turn manager (replaced by real imports once available)
# ---------------------------------------------------------------------------

class _StubPlayer:
    def __init__(self, name: str, seat: int) -> None:
        self.name        = name
        self.seat        = seat
        self.life        = 40
        self.eliminated  = False
        self.hand        = []
        self.battlefield = []
        self.graveyard   = []
        self.exile       = []
        self.command_zone = []

    def to_dict(self, private: bool = False) -> dict:
        return {
            "name":        self.name,
            "seat":        self.seat,
            "life":        self.life,
            "eliminated":  self.eliminated,
            "hand_count":  len(self.hand),
            "hand":        self.hand if private else [],
            "battlefield": self.battlefield,
            "graveyard":   self.graveyard,
            "exile":       self.exile,
            "command_zone": self.command_zone,
        }


class _StubGameState:
    def __init__(self, player_names: list[str]) -> None:
        self.players = [_StubPlayer(n, i) for i, n in enumerate(player_names)]
        self.turn             = 1
        self.current_phase    = "main1"
        self.active_player_seat = 0
        self.stack            = []
        self.winner           = None
        self.game_over        = False

    def get_legal_moves(self, seat: int) -> list[dict]:
        return [
            {"id": 1, "category": "pass_priority", "description": "Pass priority"},
            {"id": 2, "category": "play_land",     "description": "Play a land"},
        ]

    def apply_move(self, seat: int, move_id: int) -> None:
        pass  # real logic wired in by CommanderTurnManager


# ---------------------------------------------------------------------------
# GameSession
# ---------------------------------------------------------------------------

class GameSession:
    """
    Wraps a single live Commander game.

    Lifecycle:
      1. Created by SessionStore.create_session()
      2. Turn manager runs as an asyncio background task
      3. WebSocket router attaches a broadcast callback
      4. Destroyed by SessionStore.remove_session()
    """

    def __init__(
        self,
        game_id: str,
        player_names: list[str],
        human_seat: int,
        ai_personalities: list[str],
    ) -> None:
        self.game_id          = game_id
        self.human_seat       = human_seat
        self._gs              = _StubGameState(player_names)
        self._pending_moves: dict[int, asyncio.Future] = {}   # seat -> Future
        self._broadcast: Optional[Callable] = None
        self._task: Optional[asyncio.Task]  = None

    # ------------------------------------------------------------------
    # Public API used by routers
    # ------------------------------------------------------------------

    def state_snapshot(self, private_seat: Optional[int] = None) -> dict:
        """Return serialisable game state dict."""
        return {
            "game_id":          self.game_id,
            "turn":             self._gs.turn,
            "current_phase":    self._gs.current_phase,
            "active_seat":      self._gs.active_player_seat,
            "game_over":        self._gs.game_over,
            "winner":           self._gs.winner,
            "stack_size":       len(self._gs.stack),
            "players": [
                p.to_dict(private=(p.seat == private_seat))
                for p in self._gs.players
            ],
        }

    def get_legal_moves(self, seat: int) -> list[dict]:
        return self._gs.get_legal_moves(seat)

    async def apply_human_move(
        self,
        seat: int,
        move_id: int,
    ) -> bool:
        """
        Inject a human move.
        Resolves the pending Future if the turn manager is waiting.
        """
        fut = self._pending_moves.get(seat)
        if fut and not fut.done():
            fut.set_result(move_id)
            return True
        # Fallback: apply directly (e.g. during testing)
        self._gs.apply_move(seat, move_id)
        return True

    async def concede(self, seat: int) -> None:
        """Mark a seat as eliminated."""
        if 0 <= seat < len(self._gs.players):
            self._gs.players[seat].eliminated = True
            self._gs.players[seat].life = 0
            if self._broadcast:
                await self._broadcast({
                    "type":        "elimination",
                    "seat":        seat,
                    "player_name": self._gs.players[seat].name,
                })

    def set_broadcast_callback(
        self,
        callback: Callable[[dict], Awaitable[None]],
    ) -> None:
        self._broadcast = callback

    def register_human_future(
        self,
        seat: int,
        future: asyncio.Future,
    ) -> None:
        """Called by turn manager when waiting for human input."""
        self._pending_moves[seat] = future


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------

class SessionStore:
    """
    Singleton-ish in-memory store for GameSession objects.
    One instance is shared between the API and WS routers via module globals.
    """
    _instance: Optional[SessionStore] = None

    def __new__(cls) -> SessionStore:
        # Simple module-level singleton
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: dict[str, GameSession] = {}
        return cls._instance

    async def create_session(
        self,
        player_names: list[str],
        human_seat: int = 0,
        ai_personalities: list[str] | None = None,
    ) -> GameSession:
        game_id = str(uuid.uuid4())[:8]
        session = GameSession(
            game_id=game_id,
            player_names=player_names,
            human_seat=human_seat,
            ai_personalities=ai_personalities or ["aggressive", "control", "combo"],
        )
        self._sessions[game_id] = session
        return session

    def get_session(self, game_id: str) -> Optional[GameSession]:
        return self._sessions.get(game_id)

    def list_session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def remove_session(self, game_id: str) -> bool:
        if game_id in self._sessions:
            del self._sessions[game_id]
            return True
        return False
