"""
Phase 6 Unit Tests — Politics Engine & Targeting Memory
=======================================================
Run with: pytest tests/test_phase6.py -v
"""

from __future__ import annotations

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mem(n=4):
    from commander_ai_lab.sim.politics.memory import TargetingMemory
    return TargetingMemory(num_players=n)


def _engine(personalities=None):
    from commander_ai_lab.sim.politics.memory import TargetingMemory
    from commander_ai_lab.sim.politics.comms  import PoliticsCommsChannel
    from commander_ai_lab.sim.politics.engine import PoliticsEngine
    mem   = TargetingMemory(num_players=4)
    comms = PoliticsCommsChannel()
    perso = personalities or {0: "timmy", 1: "spike", 2: "johnny", 3: "aggressive"}
    return PoliticsEngine(
        num_players=4,
        memory=mem,
        comms=comms,
        personalities=perso,
        threat_fn=lambda s: {i: 0.3 for i in range(4) if i != s},
    ), mem, comms


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# TargetingMemory
# ---------------------------------------------------------------------------

class TestTargetingMemory:
    def test_initial_aggression_zero(self):
        mem = _mem()
        assert mem.aggression_score(0, 1, current_turn=1) == 0.0

    def test_record_increases_aggression(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record(turn=1, actor=1, target=0, action_type=ActionType.ATTACKED)
        assert mem.aggression_score(1, 0, current_turn=1) > 0

    def test_different_directions_independent(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record(1, 0, 1, ActionType.ATTACKED)
        assert mem.aggression_score(1, 0, current_turn=1) == 0.0
        assert mem.aggression_score(0, 1, current_turn=1) > 0

    def test_decay_reduces_score(self):
        from commander_ai_lab.sim.politics.memory import ActionType, MEMORY_DECAY_TURNS
        mem = _mem()
        mem.record(turn=1, actor=1, target=0, action_type=ActionType.ATTACKED)
        score_fresh = mem.aggression_score(1, 0, current_turn=2)
        score_old   = mem.aggression_score(1, 0, current_turn=2 + MEMORY_DECAY_TURNS + 3)
        assert score_old < score_fresh

    def test_help_reduces_score(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record(1, 1, 0, ActionType.ATTACKED)
        mem.record(2, 1, 0, ActionType.HELPED)
        score = mem.aggression_score(1, 0, current_turn=2)
        score_attack_only = 1.5  # weight of one ATTACKED event
        assert score < score_attack_only

    def test_most_aggressive_toward_sorted(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record(1, 1, 0, ActionType.ATTACKED)
        mem.record(1, 1, 0, ActionType.ATTACKED)
        mem.record(1, 2, 0, ActionType.TARGETED_SPELL)
        ranking = mem.most_aggressive_toward(viewer=0, current_turn=2)
        seats = [s for s, _ in ranking]
        assert seats[0] == 1   # seat 1 attacked twice

    def test_biggest_threat_none_when_empty(self):
        mem = _mem()
        assert mem.biggest_threat_overall(0, current_turn=1) is None

    def test_record_damage_scales_weight(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record_damage(1, 1, 0, amount=10)
        score = mem.aggression_score(1, 0, current_turn=1)
        assert score > 0

    def test_deal_broken_heavy_weight(self):
        from commander_ai_lab.sim.politics.memory import ActionType, ACTION_WEIGHTS
        assert ACTION_WEIGHTS[ActionType.BROKE_DEAL] >= 4.0

    def test_summary_returns_matrix(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem(4)
        mem.record(1, 0, 1, ActionType.ATTACKED)
        summary = mem.summary(current_turn=2)
        assert (0, 1) in summary

    def test_action_counts(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record(1, 0, 2, ActionType.ATTACKED)
        mem.record(2, 0, 2, ActionType.ATTACKED)
        counts = mem.action_counts(0, 2)
        assert counts.get(ActionType.ATTACKED) == 2

    def test_recent_actions_filter(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        mem = _mem()
        mem.record(1, 0, 1, ActionType.ATTACKED)
        mem.record(5, 0, 1, ActionType.TARGETED_SPELL)
        recent = mem.recent_actions(last_n_turns=2, current_turn=6)
        assert len(recent) == 1


# ---------------------------------------------------------------------------
# Deal data classes
# ---------------------------------------------------------------------------

class TestDeal:
    def test_is_active_accepted(self):
        from commander_ai_lab.sim.politics.deals import Deal, DealType, DealResponse
        d = Deal(proposer=0, target=1, deal_type=DealType.NON_AGGRESSION,
                 turn_proposed=3, duration_turns=2)
        d.response = DealResponse.ACCEPTED
        assert d.is_active(current_turn=4) is True
        assert d.is_active(current_turn=6) is False

    def test_is_pending(self):
        from commander_ai_lab.sim.politics.deals import Deal, DealType
        d = Deal(proposer=0, target=1, deal_type=DealType.NON_AGGRESSION,
                 turn_proposed=1, turn_expires=2)
        assert d.is_pending(current_turn=2) is True
        assert d.is_pending(current_turn=3) is False

    def test_expire(self):
        from commander_ai_lab.sim.politics.deals import Deal, DealType, DealResponse
        d = Deal(proposer=0, target=1, deal_type=DealType.NON_AGGRESSION)
        d.expire()
        assert d.response == DealResponse.EXPIRED

    def test_mark_broken(self):
        from commander_ai_lab.sim.politics.deals import Deal, DealType, DealResponse
        d = Deal(proposer=0, target=1, deal_type=DealType.NON_AGGRESSION)
        d.response = DealResponse.ACCEPTED
        d.mark_broken()
        assert d.response == DealResponse.BROKEN

    def test_unique_ids(self):
        from commander_ai_lab.sim.politics.deals import Deal, DealType
        d1 = Deal(0, 1, DealType.NON_AGGRESSION)
        d2 = Deal(1, 2, DealType.SPARE_THIS_TURN)
        assert d1.deal_id != d2.deal_id


# ---------------------------------------------------------------------------
# PoliticsCommsChannel
# ---------------------------------------------------------------------------

class TestPoliticsCommsChannel:
    def test_register_and_receive(self):
        from commander_ai_lab.sim.politics.comms import (
            PoliticsCommsChannel, ThreatBroadcast, BroadcastType,
        )
        channel  = PoliticsCommsChannel()
        received = []

        async def handler(msg): received.append(msg)
        channel.register_handler(seat=1, handler=handler)

        msg = ThreatBroadcast(speaker=0, audience=1,
                              broadcast_type=BroadcastType.THREAT,
                              text="Watch out", turn=1)
        _run(channel.broadcast(msg))
        assert len(received) == 1

    def test_global_handler_receives_all(self):
        from commander_ai_lab.sim.politics.comms import (
            PoliticsCommsChannel, ThreatBroadcast, BroadcastType,
        )
        channel  = PoliticsCommsChannel()
        received = []

        async def handler(msg): received.append(msg)
        channel.register_global_handler(handler)

        for audience in [1, 2, -1]:
            msg = ThreatBroadcast(speaker=0, audience=audience,
                                  broadcast_type=BroadcastType.TAUNT,
                                  text="Hello", turn=1)
            _run(channel.broadcast(msg))
        assert len(received) == 3

    def test_table_broadcast_skips_speaker(self):
        from commander_ai_lab.sim.politics.comms import (
            PoliticsCommsChannel, ThreatBroadcast, BroadcastType,
        )
        channel  = PoliticsCommsChannel()
        received_seats = []

        for seat in range(4):
            async def make_handler(s=seat):
                async def h(msg): received_seats.append(s)
                return h
            import asyncio
            h = asyncio.run(make_handler())
            channel.register_handler(seat=seat, handler=h)

        msg = ThreatBroadcast(speaker=0, audience=-1,
                              broadcast_type=BroadcastType.CALL_TO_ARMS,
                              text="Focus P2!", turn=2)
        _run(channel.broadcast(msg))
        assert 0 not in received_seats   # speaker does not receive own broadcast

    def test_recent_broadcasts(self):
        from commander_ai_lab.sim.politics.comms import (
            PoliticsCommsChannel, ThreatBroadcast, BroadcastType,
        )
        channel = PoliticsCommsChannel()
        for i in range(15):
            msg = ThreatBroadcast(0, -1, BroadcastType.TAUNT, f"msg{i}", turn=i)
            _run(channel.broadcast(msg))
        recent = channel.recent_broadcasts(last_n=5)
        assert len(recent) == 5


# ---------------------------------------------------------------------------
# PoliticsEngine
# ---------------------------------------------------------------------------

class TestPoliticsEngine:
    def test_propose_deal_creates_entry(self):
        from commander_ai_lab.sim.politics.deals import DealType
        engine, mem, comms = _engine()
        deal = _run(engine.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        assert deal.deal_id in engine._deals

    def test_deal_gets_response(self):
        from commander_ai_lab.sim.politics.deals import DealType, DealResponse
        engine, mem, comms = _engine()
        deal = _run(engine.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        assert deal.response in (DealResponse.ACCEPTED, DealResponse.REJECTED)

    def test_active_deals_returned(self):
        from commander_ai_lab.sim.politics.deals import DealType, DealResponse
        engine, mem, comms = _engine()
        deal = _run(engine.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        deal.response = DealResponse.ACCEPTED
        active = engine.get_active_deals(seat=0, current_turn=2)
        assert any(d.deal_id == deal.deal_id for d in active)

    def test_deal_violation_marks_broken(self):
        from commander_ai_lab.sim.politics.deals import DealType, DealResponse
        from commander_ai_lab.sim.politics.memory import ActionType
        engine, mem, comms = _engine()
        deal = _run(engine.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        deal.response = DealResponse.ACCEPTED
        broken = engine.check_deal_violation(
            actor=1, action_target=0,
            action_type=ActionType.ATTACKED,
            current_turn=3,
        )
        assert len(broken) == 1
        assert broken[0].response == DealResponse.BROKEN

    def test_spite_set_after_violation(self):
        from commander_ai_lab.sim.politics.deals import DealType, DealResponse
        from commander_ai_lab.sim.politics.memory import ActionType
        engine, mem, comms = _engine()
        deal = _run(engine.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        deal.response = DealResponse.ACCEPTED
        engine.check_deal_violation(1, 0, ActionType.ATTACKED, current_turn=3)
        spite = engine.get_spite_bias(viewer=0, target=1, current_turn=3)
        assert spite > 0

    def test_spite_decays_after_turns(self):
        from commander_ai_lab.sim.politics.deals import DealType, DealResponse
        from commander_ai_lab.sim.politics.memory import ActionType
        from commander_ai_lab.sim.politics.engine import SPITE_DECAY_TURNS
        engine, mem, comms = _engine()
        deal = _run(engine.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        deal.response = DealResponse.ACCEPTED
        engine.check_deal_violation(1, 0, ActionType.ATTACKED, current_turn=3)
        engine._decay_spite(current_turn=3 + SPITE_DECAY_TURNS + 1)
        spite = engine.get_spite_bias(viewer=0, target=1,
                                      current_turn=3 + SPITE_DECAY_TURNS + 1)
        assert spite == 0.0

    def test_adjusted_threat_includes_spite(self):
        from commander_ai_lab.sim.politics.deals import DealType, DealResponse
        from commander_ai_lab.sim.politics.memory import ActionType
        engine, mem, comms = _engine()
        base_score = engine.adjusted_threat_score(viewer=0, target=1, current_turn=2)
        # Add spite
        engine._add_spite(wronged_seat=0, target_seat=1, current_turn=2, intensity=0.6)
        spite_score = engine.adjusted_threat_score(viewer=0, target=1, current_turn=2)
        assert spite_score > base_score

    def test_no_deal_within_cooldown(self):
        from commander_ai_lab.sim.politics.engine import DEAL_PROPOSAL_COOLDOWN
        engine, mem, comms = _engine()
        engine._last_proposal_turn[0] = 5
        count_before = len(engine._deals)

        class _FakeGS:
            players = [type('P', (), {'eliminated': False, 'life': 40})() for _ in range(4)]

        _run(engine._maybe_propose_deal(0, current_turn=5 + DEAL_PROPOSAL_COOLDOWN - 1,
                                         game_state=_FakeGS()))
        assert len(engine._deals) == count_before

    def test_comms_log_populated_after_proposal(self):
        from commander_ai_lab.sim.politics.deals import DealType
        engine, mem, comms = _engine()
        _run(engine.propose_deal(0, 1, DealType.SPARE_THIS_TURN, current_turn=3))
        assert len(comms._log) >= 2   # proposal + response
