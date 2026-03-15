"""
Commander AI Lab — Deal Data Classes (Phase 6)
===============================================
Deals are time-limited, seat-to-seat agreements that the politics engine
can propose, counter, accept, or reject.  They are stored in the
PoliticsEngine and checked at each phase transition.

Deal types:
  NON_AGGRESSION   — neither party attacks the other for N turns
  ATTACK_TOGETHER  — both parties attack a named third seat this turn
  SPARE_THIS_TURN  — proposer asks to be left alone during one combat
  TRADE_RESOURCES  — abstract resource exchange (e.g. card draw for removal)
  FREE_FOR_ALL     — proposer calls for everyone to focus a specific seat
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class DealType(Enum):
    NON_AGGRESSION  = auto()
    ATTACK_TOGETHER = auto()
    SPARE_THIS_TURN = auto()
    TRADE_RESOURCES = auto()
    FREE_FOR_ALL    = auto()


class DealResponse(Enum):
    PENDING  = auto()
    ACCEPTED = auto()
    REJECTED = auto()
    COUNTERED = auto()
    EXPIRED  = auto()
    BROKEN   = auto()


@dataclass
class Deal:
    """
    A deal proposed from one seat to another (or broadcast to all).

    Attributes:
        deal_id:       Unique identifier (auto-assigned by PoliticsEngine).
        proposer:      Seat index of the proposing player.
        target:        Seat index of the deal target (-1 = all players).
        deal_type:     Type of deal.
        duration_turns: How many turns the deal stays active once accepted.
        subject_seat:  For ATTACK_TOGETHER / FREE_FOR_ALL, the seat to focus.
        flavor_text:   Natural-language proposal text (spoken by AI).
        turn_proposed: Game turn when proposed.
        turn_expires:  Turn after which this deal auto-expires if not resolved.
        response:      Current deal status.
        responder:     Seat that responded (may differ from target if broadcast).
        counter_deal:  A counter-proposal (if COUNTERED).
    """
    proposer:       int
    target:         int
    deal_type:      DealType
    flavor_text:    str          = ""
    duration_turns: int          = 2
    subject_seat:   Optional[int] = None
    turn_proposed:  int          = 0
    turn_expires:   int          = 2
    response:       DealResponse = DealResponse.PENDING
    responder:      Optional[int] = None
    counter_deal:   Optional[Deal] = None
    deal_id:        int          = field(default_factory=lambda: Deal._next_id())

    _id_counter: int = field(default=0, init=False, repr=False, compare=False)

    @staticmethod
    def _next_id() -> int:
        Deal.__dict__  # trigger class body
        if not hasattr(Deal, '_counter'):
            Deal._counter = 0
        Deal._counter += 1
        return Deal._counter

    def is_active(self, current_turn: int) -> bool:
        """True if deal is accepted and not yet expired."""
        return (
            self.response == DealResponse.ACCEPTED
            and current_turn <= self.turn_proposed + self.duration_turns
        )

    def is_pending(self, current_turn: int) -> bool:
        return (
            self.response == DealResponse.PENDING
            and current_turn <= self.turn_expires
        )

    def expire(self) -> None:
        if self.response == DealResponse.PENDING:
            self.response = DealResponse.EXPIRED

    def mark_broken(self) -> None:
        self.response = DealResponse.BROKEN
