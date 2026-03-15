"""
Commander AI Lab — Private Hand Bus (Phase 8)
=============================================
Ensures each player only receives their own private hand data.

The game engine publishes full state snapshots (including all hands)
to the PrivateHandBus.  The bus strips all hands from the public
broadcast and sends each player only their own hand via a
dedicated per-seat WebSocket callback.

This design means:
  - The public state broadcast never contains card-in-hand data
  - Each player receives one extra message per state change: their own hand
  - Spectators never see any hand data (enforced in SpectatorManager)
  - AI opponent hands are never transmitted over the network

Usage::

    bus = PrivateHandBus()
    bus.register(seat=0, send_fn=player_ws_send)
    bus.register(seat=1, send_fn=ai_seat_noop)  # or skip entirely

    # After each state change:
    await bus.dispatch(full_state_snapshot, current_turn=5)
"""

from __future__ import annotations

import json
from typing import Callable, Awaitable, Optional


HandSendFn = Callable[[str], Awaitable[None]]


class PrivateHandBus:
    """
    Routes private hand data to the correct seat only.
    """

    def __init__(self) -> None:
        self._handlers: dict[int, HandSendFn] = {}
        self._human_seats: set[int] = set()

    def register(
        self,
        seat: int,
        send_fn: HandSendFn,
        is_human: bool = True,
    ) -> None:
        """
        Register a send callback for a seat.
        Only human seats should have real callbacks; AI seats are skipped.
        """
        self._handlers[seat] = send_fn
        if is_human:
            self._human_seats.add(seat)

    def unregister(self, seat: int) -> None:
        self._handlers.pop(seat, None)
        self._human_seats.discard(seat)

    async def dispatch(
        self,
        full_snapshot: dict,
        current_turn: int,
    ) -> dict:
        """
        Send each human seat their private hand, then return a
        scrubbed public snapshot (all hand arrays removed).

        Parameters
        ----------
        full_snapshot : Full game state dict including all players' hands.
        current_turn  : Current game turn (included in hand payload).

        Returns
        -------
        Public snapshot with all hand data stripped.
        """
        players = full_snapshot.get("players", [])

        for player in players:
            seat = player.get("seat")
            if seat not in self._human_seats:
                continue
            send_fn = self._handlers.get(seat)
            if send_fn is None:
                continue
            hand_payload = json.dumps({
                "type":  "hand",
                "seat":  seat,
                "turn":  current_turn,
                "cards": player.get("hand", []),
            })
            try:
                await send_fn(hand_payload)
            except Exception:
                pass

        # Strip all hands for public broadcast
        return self._strip_hands(full_snapshot)

    def registered_seats(self) -> list[int]:
        return sorted(self._handlers.keys())

    @staticmethod
    def _strip_hands(snapshot: dict) -> dict:
        import copy
        safe = copy.deepcopy(snapshot)
        for player in safe.get("players", []):
            player.pop("hand", None)
        return safe
