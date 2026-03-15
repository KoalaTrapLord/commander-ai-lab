"""
Commander AI Lab — Politics Engine (Phase 6)
=============================================
Orchestrates all AI-to-AI (and AI-to-human) political interactions:

  1. Deal proposal generation
     - Each AI evaluates threat scores + targeting memory to decide
       whether to propose a deal this turn.
     - Proposal templates vary by AI personality.

  2. Deal evaluation & response
     - Receiving AI evaluates whether the deal is in their interest.
     - Factors: current threat level from proposer, board state, personality.

  3. Deal enforcement monitoring
     - At each phase transition, PoliticsEngine checks active deals.
     - If a participant acts against a deal, it is marked BROKEN and
       the breach is recorded in TargetingMemory with a heavy penalty.

  4. Spite targeting
     - After a deal is broken, the wronged seat gets a spite_targets set
       that biases combat and spell targeting toward the breaker.
     - Spite decays over SPITE_DECAY_TURNS turns.

  5. Call-to-arms
     - When a seat's threat score crosses CALL_TO_ARMS_THRESHOLD, any AI
       can broadcast a call-to-arms to the table via PoliticsCommsChannel.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from commander_ai_lab.sim.politics.deals  import Deal, DealType, DealResponse
from commander_ai_lab.sim.politics.memory import TargetingMemory, ActionType
from commander_ai_lab.sim.politics.comms  import (
    PoliticsCommsChannel, ThreatBroadcast, BroadcastType,
)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
DEAL_PROPOSAL_COOLDOWN    = 2    # turns between proposals per seat
SPITE_DECAY_TURNS         = 3    # turns spite bonus persists
CALL_TO_ARMS_THRESHOLD    = 0.75 # threat score that triggers a call-to-arms
DEAL_ACCEPT_BASE_PROB     = 0.55 # base probability AI accepts a deal
PERSONALITY_DEAL_BIAS: dict[str, float] = {
    "aggressive": -0.20,   # less likely to accept deals
    "control":     0.10,
    "combo":       0.15,
    "timmy":      -0.10,
    "spike":       0.05,
    "johnny":      0.20,
}


# ---------------------------------------------------------------------------
# Proposal templates per deal type and personality
# ---------------------------------------------------------------------------
_PROPOSAL_TEMPLATES: dict[DealType, list[str]] = {
    DealType.NON_AGGRESSION: [
        "How about we leave each other alone for a couple of turns?",
        "I'll stay off your back if you stay off mine.",
        "Non-aggression pact? I have bigger fish to fry.",
    ],
    DealType.ATTACK_TOGETHER: [
        "Let's both swing at P{target} — they're way ahead.",
        "If we team up on P{target} this turn we can knock them out.",
        "P{target} is the biggest threat. Join me?",
    ],
    DealType.SPARE_THIS_TURN: [
        "Leave me out of combat this turn and I won't touch you.",
        "I'm tapped out — please spare me until my upkeep.",
        "One turn of peace is all I ask.",
    ],
    DealType.FREE_FOR_ALL: [
        "Table, we need to focus P{target} RIGHT NOW.",
        "P{target} is going to win if we don't all attack them.",
        "Everyone pile on P{target} — deal?",
    ],
}


@dataclass
class SpiteEntry:
    target_seat:  int
    intensity:    float   # 0.0–1.0 targeting bias added
    expires_turn: int


class PoliticsEngine:
    """
    Central coordinator for the Phase 6 politics system.

    Parameters
    ----------
    num_players :   Number of seats (2–4).
    memory :        Shared TargetingMemory instance.
    comms :         Shared PoliticsCommsChannel instance.
    personalities : Dict mapping seat index → personality string.
    threat_fn :     Callable(viewer_seat) → dict{seat: float} —
                    returns current threat scores from ThreatAssessor.
    """

    def __init__(
        self,
        num_players: int,
        memory: TargetingMemory,
        comms: PoliticsCommsChannel,
        personalities: dict[int, str],
        threat_fn: Optional[Callable[[int], dict[int, float]]] = None,
    ) -> None:
        self.num_players   = num_players
        self.memory        = memory
        self.comms         = comms
        self.personalities = personalities
        self._threat_fn    = threat_fn or (lambda s: {})

        # Active deals: deal_id -> Deal
        self._deals: dict[int, Deal] = {}
        # Spite registry: seat -> list[SpiteEntry]
        self._spite: dict[int, list[SpiteEntry]] = {i: [] for i in range(num_players)}
        # Last proposal turn per seat
        self._last_proposal_turn: dict[int, int] = {i: -999 for i in range(num_players)}
        # Call-to-arms cooldown per seat
        self._last_call_turn: dict[int, int] = {i: -999 for i in range(num_players)}

    # ------------------------------------------------------------------
    # Main per-turn hook (called at start of each main phase)
    # ------------------------------------------------------------------

    async def on_turn_start(
        self,
        active_seat: int,
        current_turn: int,
        game_state,
    ) -> None:
        """
        Called at the start of the active seat's main phase.
        Runs: deal expiry, spite decay, proposal generation, call-to-arms.
        """
        self._expire_deals(current_turn)
        self._decay_spite(current_turn)
        await self._maybe_propose_deal(active_seat, current_turn, game_state)
        await self._maybe_call_to_arms(active_seat, current_turn)

    # ------------------------------------------------------------------
    # Deal lifecycle
    # ------------------------------------------------------------------

    async def propose_deal(
        self,
        proposer: int,
        target: int,
        deal_type: DealType,
        current_turn: int,
        subject_seat: Optional[int] = None,
        duration_turns: int = 2,
    ) -> Deal:
        """
        Create and broadcast a deal proposal.
        The target AI evaluates and responds automatically.
        """
        flavor = self._generate_flavor(proposer, deal_type, subject_seat)
        deal   = Deal(
            proposer=proposer,
            target=target,
            deal_type=deal_type,
            flavor_text=flavor,
            duration_turns=duration_turns,
            subject_seat=subject_seat,
            turn_proposed=current_turn,
            turn_expires=current_turn + 1,
        )
        self._deals[deal.deal_id] = deal
        self._last_proposal_turn[proposer] = current_turn

        # Broadcast proposal to table
        await self.comms.broadcast(ThreatBroadcast(
            speaker=proposer,
            audience=target,
            broadcast_type=BroadcastType.OFFER,
            text=flavor,
            turn=current_turn,
            condition_seat=subject_seat,
        ))

        # Auto-evaluate if target is an AI seat
        response = self._evaluate_deal(deal, current_turn)
        deal.response  = response
        deal.responder = target

        resp_text = self._response_flavor(target, deal, response)
        await self.comms.broadcast(ThreatBroadcast(
            speaker=target,
            audience=proposer,
            broadcast_type=(
                BroadcastType.OFFER if response == DealResponse.ACCEPTED
                else BroadcastType.THREAT
            ),
            text=resp_text,
            turn=current_turn,
        ))

        return deal

    def check_deal_violation(
        self,
        actor: int,
        action_target: int,
        action_type: ActionType,
        current_turn: int,
    ) -> list[Deal]:
        """
        Check whether an action by `actor` toward `action_target` breaks
        any active deals. Returns list of broken deals.
        """
        broken = []
        for deal in self._deals.values():
            if deal.response != DealResponse.ACCEPTED:
                continue
            if not deal.is_active(current_turn):
                continue

            violated = False
            if deal.deal_type == DealType.NON_AGGRESSION:
                if actor in (deal.proposer, deal.target) and action_target in (deal.proposer, deal.target):
                    hostile = action_type in (
                        ActionType.ATTACKED, ActionType.TARGETED_SPELL,
                        ActionType.REMOVED_PERMANENT, ActionType.COUNTERED_SPELL,
                    )
                    violated = hostile

            elif deal.deal_type == DealType.SPARE_THIS_TURN:
                if actor == deal.target and action_target == deal.proposer:
                    violated = action_type == ActionType.ATTACKED

            if violated:
                deal.mark_broken()
                victim = deal.proposer if actor == deal.target else deal.target
                self.memory.record_deal_broken(current_turn, actor, victim)
                self._add_spite(victim, actor, current_turn)
                broken.append(deal)

        return broken

    def get_active_deals(
        self,
        seat: int,
        current_turn: int,
    ) -> list[Deal]:
        """Return all active deals involving `seat`."""
        return [
            d for d in self._deals.values()
            if d.is_active(current_turn)
            and seat in (d.proposer, d.target)
        ]

    # ------------------------------------------------------------------
    # Spite system
    # ------------------------------------------------------------------

    def get_spite_bias(
        self,
        viewer: int,
        target: int,
        current_turn: int,
    ) -> float:
        """
        Return the spite-targeting bias that `viewer` has toward `target`.
        Range: 0.0 (no spite) – 1.0 (maximum spite bias).
        """
        total = 0.0
        for entry in self._spite.get(viewer, []):
            if entry.target_seat == target and entry.expires_turn >= current_turn:
                total += entry.intensity
        return min(total, 1.0)

    def adjusted_threat_score(
        self,
        viewer: int,
        target: int,
        current_turn: int,
    ) -> float:
        """
        Return threat score for `target` from `viewer`'s perspective,
        blended with spite bias and memory aggression.
        """
        base_threats = self._threat_fn(viewer)
        base = base_threats.get(target, 0.0)
        spite = self.get_spite_bias(viewer, target, current_turn)
        mem   = min(self.memory.aggression_score(target, viewer, current_turn) / 10.0, 0.3)
        return min(base + spite * 0.3 + mem, 1.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _maybe_propose_deal(
        self,
        active_seat: int,
        current_turn: int,
        game_state,
    ) -> None:
        """Decide whether to propose a deal this turn."""
        cooldown = self._last_proposal_turn.get(active_seat, -999)
        if current_turn - cooldown < DEAL_PROPOSAL_COOLDOWN:
            return

        threats = self._threat_fn(active_seat)
        if not threats:
            return

        top_threat_seat = max(threats, key=threats.get)
        top_score       = threats[top_threat_seat]

        # Propose a non-aggression to the second-most-threatening seat
        seats_sorted = sorted(
            [s for s in threats if s != active_seat],
            key=lambda s: threats.get(s, 0),
        )
        if len(seats_sorted) < 2:
            return

        partner_seat = seats_sorted[0]   # least threatening — most likely to agree
        p = random.random()
        if p > 0.40:  # 60% chance to try
            return

        if top_score > CALL_TO_ARMS_THRESHOLD:
            await self.propose_deal(
                proposer=active_seat,
                target=partner_seat,
                deal_type=DealType.ATTACK_TOGETHER,
                current_turn=current_turn,
                subject_seat=top_threat_seat,
            )
        else:
            await self.propose_deal(
                proposer=active_seat,
                target=partner_seat,
                deal_type=DealType.NON_AGGRESSION,
                current_turn=current_turn,
            )

    async def _maybe_call_to_arms(
        self,
        active_seat: int,
        current_turn: int,
    ) -> None:
        """Broadcast a call-to-arms if any threat exceeds threshold."""
        cooldown = self._last_call_turn.get(active_seat, -999)
        if current_turn - cooldown < 3:
            return

        threats = self._threat_fn(active_seat)
        for seat, score in threats.items():
            if seat == active_seat:
                continue
            if score >= CALL_TO_ARMS_THRESHOLD:
                template = random.choice(_PROPOSAL_TEMPLATES[DealType.FREE_FOR_ALL])
                text = template.format(target=seat)
                await self.comms.broadcast(ThreatBroadcast(
                    speaker=active_seat,
                    audience=-1,
                    broadcast_type=BroadcastType.CALL_TO_ARMS,
                    text=text,
                    turn=current_turn,
                    condition_seat=seat,
                ))
                self._last_call_turn[active_seat] = current_turn
                break

    def _evaluate_deal(
        self,
        deal: Deal,
        current_turn: int,
    ) -> DealResponse:
        """AI auto-evaluation of a deal proposal."""
        target = deal.target
        if target < 0:   # broadcast deal — accept probabilistically
            return DealResponse.ACCEPTED if random.random() < 0.5 else DealResponse.REJECTED

        personality = self.personalities.get(target, "spike")
        bias = PERSONALITY_DEAL_BIAS.get(personality, 0.0)
        prob = DEAL_ACCEPT_BASE_PROB + bias

        # Bonus: accept more if proposer has been targeting you heavily
        aggression = self.memory.aggression_score(
            deal.proposer, target, current_turn
        )
        if aggression > 5.0:
            prob -= 0.20   # suspicious of sudden peace offer
        elif aggression < 1.0:
            prob += 0.10   # no recent hostility — trust higher

        # Bonus: accept attack-together if target is actually threatening
        if deal.deal_type == DealType.ATTACK_TOGETHER and deal.subject_seat is not None:
            threats = self._threat_fn(target)
            subject_score = threats.get(deal.subject_seat, 0.0)
            prob += subject_score * 0.3

        return DealResponse.ACCEPTED if random.random() < prob else DealResponse.REJECTED

    def _expire_deals(
        self,
        current_turn: int,
    ) -> None:
        for deal in self._deals.values():
            if deal.is_pending(current_turn) is False and deal.response == DealResponse.PENDING:
                deal.expire()

    def _decay_spite(
        self,
        current_turn: int,
    ) -> None:
        for seat in self._spite:
            self._spite[seat] = [
                e for e in self._spite[seat]
                if e.expires_turn >= current_turn
            ]

    def _add_spite(
        self,
        wronged_seat: int,
        target_seat: int,
        current_turn: int,
        intensity: float = 0.6,
    ) -> None:
        self._spite[wronged_seat].append(SpiteEntry(
            target_seat=target_seat,
            intensity=intensity,
            expires_turn=current_turn + SPITE_DECAY_TURNS,
        ))

    @staticmethod
    def _generate_flavor(
        proposer: int,
        deal_type: DealType,
        subject_seat: Optional[int],
    ) -> str:
        templates = _PROPOSAL_TEMPLATES.get(deal_type, ["Let's make a deal."])
        text = random.choice(templates)
        if subject_seat is not None:
            text = text.format(target=f"P{subject_seat}")
        return text

    @staticmethod
    def _response_flavor(
        responder: int,
        deal: Deal,
        response: DealResponse,
    ) -> str:
        if response == DealResponse.ACCEPTED:
            options = [
                "Deal. Don't make me regret this.",
                "Fine, I'll hold off.",
                "Agreed. For now.",
            ]
        else:
            options = [
                "No deal. I'll handle things myself.",
                "I don't trust you.",
                "Pass. You're next anyway.",
            ]
        return random.choice(options)
