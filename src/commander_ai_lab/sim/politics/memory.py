"""
Commander AI Lab — Targeting Memory (Phase 6)
==============================================
Per-game record of every targeting decision: who cast spells/abilities
targeting whom, who attacked whom, who blocked whose creatures, and
who broke deals.

The memory feeds threat assessments in ThreatAssessor and politics
decisions in PoliticsEngine, letting AI personas hold grudges,
reciprocate kindness, or shift focus as the game progresses.

Decay model:
  Events older than MEMORY_DECAY_TURNS have their weight halved per turn
  beyond that threshold, so recent aggression matters more than old actions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


MEMORY_DECAY_TURNS = 4   # turns before weight decay kicks in
DECAY_FACTOR       = 0.5  # per-turn weight multiplier after decay threshold


class ActionType(Enum):
    TARGETED_SPELL      = auto()   # single-target spell/ability
    ATTACKED            = auto()   # declared attacker against
    BLOCKED             = auto()   # blocked a creature of
    DEALT_COMBAT_DAMAGE = auto()   # connected combat damage to
    REMOVED_PERMANENT   = auto()   # destroyed / exiled permanent of
    COUNTERED_SPELL     = auto()   # countered a spell of
    STOLE_PERMANENT     = auto()   # gained control of permanent of
    HELPED              = auto()   # beneficial action toward (negative aggression)
    BROKE_DEAL          = auto()   # violated an accepted deal with
    HONORED_DEAL        = auto()   # complied with an accepted deal with


# Aggression weights per action type (positive = hostile, negative = friendly)
ACTION_WEIGHTS: dict[ActionType, float] = {
    ActionType.TARGETED_SPELL:      1.0,
    ActionType.ATTACKED:            1.5,
    ActionType.BLOCKED:             0.5,
    ActionType.DEALT_COMBAT_DAMAGE: 2.0,
    ActionType.REMOVED_PERMANENT:   2.5,
    ActionType.COUNTERED_SPELL:     2.0,
    ActionType.STOLE_PERMANENT:     3.0,
    ActionType.HELPED:             -1.5,
    ActionType.BROKE_DEAL:          4.0,
    ActionType.HONORED_DEAL:       -1.0,
}


@dataclass
class MemoryEvent:
    turn:        int
    actor:       int          # seat doing the action
    target:      int          # seat being acted upon
    action_type: ActionType
    detail:      str = ""     # e.g. card name
    weight:      float = 1.0  # base weight (modified by decay at query time)


class TargetingMemory:
    """
    Tracks all inter-player targeting events for the duration of a game.

    Usage::

        mem = TargetingMemory(num_players=4)
        mem.record(turn=3, actor=1, target=0,
                   action_type=ActionType.ATTACKED, detail="declared attacker")
        score = mem.aggression_score(actor=1, target=0, current_turn=5)
        ranking = mem.most_aggressive_toward(viewer=0, current_turn=5)
    """

    def __init__(self, num_players: int = 4) -> None:
        self.num_players = num_players
        self._events: list[MemoryEvent] = []
        # Pre-computed cache (invalidated on each record())
        self._cache: dict[tuple, float] = {}
        self._cache_turn: int = -1

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        turn: int,
        actor: int,
        target: int,
        action_type: ActionType,
        detail: str = "",
        weight_multiplier: float = 1.0,
    ) -> None:
        """
        Record a new targeting event.

        Args:
            weight_multiplier: Extra multiplier (e.g. 2.0 for a Wrath effect
                               that hits everyone).
        """
        base_w = ACTION_WEIGHTS.get(action_type, 1.0) * weight_multiplier
        self._events.append(MemoryEvent(
            turn=turn,
            actor=actor,
            target=target,
            action_type=action_type,
            detail=detail,
            weight=base_w,
        ))
        self._cache_turn = -1   # invalidate cache

    def record_attack(self, turn: int, attacker: int, defender: int) -> None:
        self.record(turn, attacker, defender, ActionType.ATTACKED)

    def record_damage(self, turn: int, dealer: int, receiver: int, amount: int) -> None:
        self.record(turn, dealer, receiver, ActionType.DEALT_COMBAT_DAMAGE,
                    detail=f"{amount} damage", weight_multiplier=min(amount / 5.0, 3.0))

    def record_deal_broken(self, turn: int, breaker: int, victim: int) -> None:
        self.record(turn, breaker, victim, ActionType.BROKE_DEAL)

    def record_help(self, turn: int, helper: int, beneficiary: int) -> None:
        self.record(turn, helper, beneficiary, ActionType.HELPED)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def aggression_score(
        self,
        actor: int,
        target: int,
        current_turn: int,
    ) -> float:
        """
        Return the total weighted aggression score from actor toward target.
        Higher = more hostile. Can be negative if actor has been very helpful.
        Applies temporal decay for events older than MEMORY_DECAY_TURNS.
        """
        total = 0.0
        for ev in self._events:
            if ev.actor != actor or ev.target != target:
                continue
            age   = current_turn - ev.turn
            decay = 1.0 if age <= MEMORY_DECAY_TURNS else (
                DECAY_FACTOR ** (age - MEMORY_DECAY_TURNS)
            )
            total += ev.weight * decay
        return round(total, 3)

    def mutual_aggression(
        self,
        seat_a: int,
        seat_b: int,
        current_turn: int,
    ) -> float:
        """Combined aggression in both directions between two seats."""
        return (
            self.aggression_score(seat_a, seat_b, current_turn)
            + self.aggression_score(seat_b, seat_a, current_turn)
        )

    def most_aggressive_toward(
        self,
        viewer: int,
        current_turn: int,
    ) -> list[tuple[int, float]]:
        """
        Return seats ranked by their aggression toward `viewer`, descending.
        Returns list of (seat, score) excluding viewer's own seat.
        """
        scores = [
            (s, self.aggression_score(s, viewer, current_turn))
            for s in range(self.num_players)
            if s != viewer
        ]
        return sorted(scores, key=lambda x: x[1], reverse=True)

    def biggest_threat_overall(
        self,
        viewer: int,
        current_turn: int,
    ) -> Optional[int]:
        """
        Return the seat that has been most aggressive toward `viewer`.
        Returns None if no events recorded yet.
        """
        ranking = self.most_aggressive_toward(viewer, current_turn)
        if not ranking:
            return None
        seat, score = ranking[0]
        return seat if score > 0 else None

    def recent_actions(
        self,
        last_n_turns: int,
        current_turn: int,
        actor: Optional[int] = None,
        target: Optional[int] = None,
    ) -> list[MemoryEvent]:
        """
        Return events from the last N turns, optionally filtered.
        """
        cutoff = current_turn - last_n_turns
        return [
            ev for ev in self._events
            if ev.turn >= cutoff
            and (actor  is None or ev.actor  == actor)
            and (target is None or ev.target == target)
        ]

    def action_counts(
        self,
        actor: int,
        target: int,
    ) -> dict[ActionType, int]:
        """Count each action type from actor toward target."""
        counts: dict[ActionType, int] = defaultdict(int)
        for ev in self._events:
            if ev.actor == actor and ev.target == target:
                counts[ev.action_type] += 1
        return dict(counts)

    def total_damage_dealt(
        self,
        dealer: int,
        receiver: int,
    ) -> float:
        """Sum weight-scaled damage events from dealer to receiver."""
        return sum(
            ev.weight
            for ev in self._events
            if ev.actor  == dealer
            and ev.target == receiver
            and ev.action_type == ActionType.DEALT_COMBAT_DAMAGE
        )

    def summary(
        self,
        current_turn: int,
    ) -> dict[tuple[int, int], float]:
        """
        Return a full NxN aggression matrix as {(actor, target): score}.
        """
        result = {}
        for a in range(self.num_players):
            for t in range(self.num_players):
                if a == t:
                    continue
                s = self.aggression_score(a, t, current_turn)
                if s != 0:
                    result[(a, t)] = s
        return result
