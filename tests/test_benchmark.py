"""
Commander AI Lab — AI Benchmarking Suite (Phase 7)
===================================================
Measures AI decision throughput and quality metrics:

  BenchThreatAssessor  — threat assessment calls per second
  BenchPoliticsEngine  — deal proposal + evaluation throughput
  BenchTargetingMemory — record + query throughput at scale
  BenchIntegrated      — end-to-end simulated turns / second

All tests use wall-clock timing via time.perf_counter().
Thresholds are conservative to pass on CI hardware.

Run with: pytest tests/test_benchmark.py -v -s
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

@dataclass
class _Player:
    name: str
    seat: int
    life: int = 40
    eliminated: bool = False
    hand: list = field(default_factory=list)
    battlefield: list = field(default_factory=list)
    graveyard: list = field(default_factory=list)
    exile: list = field(default_factory=list)
    command_zone: list = field(default_factory=list)
    library: list = field(default_factory=list)


class _GS:
    def __init__(self, n=4):
        self.players = [_Player(f"P{i}", i) for i in range(n)]
        self.turn = 1
        self.current_phase = "main1"
        self.active_player_seat = 0
        self.priority_seat = 0
        self.stack = []
        self.game_over = False
        self.winner = None

    def battlefield(self, seat: int) -> list:
        return self.players[seat].battlefield

    def stack_is_empty(self) -> bool:
        return len(self.stack) == 0

    def living_players(self) -> list:
        return [p for p in self.players if not p.eliminated]

    def get_legal_moves(self, seat):
        return [{"id": 1, "category": "pass_priority", "description": "Pass"}]

    def apply_move(self, seat, move_id):
        pass


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. ThreatAssessor throughput
# ---------------------------------------------------------------------------

class BenchThreatAssessor:
    ITERATIONS = 2000
    MIN_OPS_PER_SEC = 500

    def test_assess_threats_throughput(self):
        from commander_ai_lab.sim.threat_assessor import assess_threats
        gs = _GS()

        start = time.perf_counter()
        for _ in range(self.ITERATIONS):
            for seat in range(4):
                assess_threats(gs, viewer_seat=seat)
        elapsed = time.perf_counter() - start

        ops = self.ITERATIONS * 4
        ops_per_sec = ops / elapsed
        print(f"\nThreatAssessor: {ops_per_sec:.0f} assess_threats/s  ({elapsed*1000:.1f} ms total)")
        assert ops_per_sec >= self.MIN_OPS_PER_SEC, (
            f"assess_threats too slow: {ops_per_sec:.0f} ops/s < {self.MIN_OPS_PER_SEC}"
        )

    def test_top_threat_throughput(self):
        from commander_ai_lab.sim.threat_assessor import top_threat
        gs = _GS()

        start = time.perf_counter()
        for _ in range(self.ITERATIONS):
            top_threat(gs, viewer_seat=0)
        elapsed = time.perf_counter() - start

        ops_per_sec = self.ITERATIONS / elapsed
        print(f"\nThreatAssessor.top_threat: {ops_per_sec:.0f} ops/s")
        assert ops_per_sec >= self.MIN_OPS_PER_SEC


# ---------------------------------------------------------------------------
# 2. TargetingMemory throughput
# ---------------------------------------------------------------------------

class BenchTargetingMemory:
    RECORD_COUNT   = 10_000
    MIN_REC_PER_S  = 50_000
    MIN_QRY_PER_S  = 5_000

    def test_record_throughput(self):
        from commander_ai_lab.sim.politics.memory import TargetingMemory, ActionType
        mem = TargetingMemory(num_players=4)

        start = time.perf_counter()
        for i in range(self.RECORD_COUNT):
            actor  = i % 4
            target = (i + 1) % 4
            mem.record(turn=i // 4, actor=actor, target=target,
                       action_type=ActionType.ATTACKED)
        elapsed = time.perf_counter() - start

        rps = self.RECORD_COUNT / elapsed
        print(f"\nTargetingMemory.record: {rps:.0f} records/s")
        assert rps >= self.MIN_REC_PER_S

    def test_aggression_query_throughput(self):
        from commander_ai_lab.sim.politics.memory import TargetingMemory, ActionType
        mem = TargetingMemory(num_players=4)
        for i in range(1000):
            mem.record(i // 4, i % 4, (i+1) % 4, ActionType.ATTACKED)

        start = time.perf_counter()
        for turn in range(self.RECORD_COUNT // 10):
            mem.aggression_score(0, 1, current_turn=turn)
        elapsed = time.perf_counter() - start

        qps = (self.RECORD_COUNT // 10) / elapsed
        print(f"\nTargetingMemory.aggression_score: {qps:.0f} queries/s")
        assert qps >= self.MIN_QRY_PER_S

    def test_summary_matrix_correctness(self):
        from commander_ai_lab.sim.politics.memory import TargetingMemory, ActionType
        mem = TargetingMemory(num_players=4)
        mem.record(1, 0, 1, ActionType.ATTACKED)
        mem.record(1, 2, 3, ActionType.REMOVED_PERMANENT)
        summary = mem.summary(current_turn=2)
        assert (0, 1) in summary
        assert (2, 3) in summary
        assert summary[(0, 1)] > 0
        assert summary[(2, 3)] > 0


# ---------------------------------------------------------------------------
# 3. PoliticsEngine throughput
# ---------------------------------------------------------------------------

class BenchPoliticsEngine:
    PROPOSALS = 200
    MIN_PROPOSALS_PER_S = 100

    def test_deal_proposal_throughput(self):
        from commander_ai_lab.sim.politics.memory  import TargetingMemory
        from commander_ai_lab.sim.politics.comms   import PoliticsCommsChannel
        from commander_ai_lab.sim.politics.engine  import PoliticsEngine
        from commander_ai_lab.sim.politics.deals   import DealType

        mem = TargetingMemory(4)
        ch  = PoliticsCommsChannel()
        pe  = PoliticsEngine(
            4, mem, ch,
            {0:"timmy",1:"spike",2:"johnny",3:"aggressive"},
            lambda s: {i:0.3 for i in range(4) if i!=s},
        )

        async def run_proposals():
            start = time.perf_counter()
            for i in range(self.PROPOSALS):
                await pe.propose_deal(
                    proposer=i % 4,
                    target=(i + 1) % 4,
                    deal_type=DealType.NON_AGGRESSION,
                    current_turn=i,
                )
            return time.perf_counter() - start

        elapsed = _run(run_proposals())
        pps = self.PROPOSALS / elapsed
        print(f"\nPoliticsEngine.propose_deal: {pps:.0f} proposals/s")
        assert pps >= self.MIN_PROPOSALS_PER_S

    def test_check_violation_throughput(self):
        from commander_ai_lab.sim.politics.memory  import TargetingMemory, ActionType
        from commander_ai_lab.sim.politics.comms   import PoliticsCommsChannel
        from commander_ai_lab.sim.politics.engine  import PoliticsEngine
        from commander_ai_lab.sim.politics.deals   import DealType, DealResponse

        mem = TargetingMemory(4)
        ch  = PoliticsCommsChannel()
        pe  = PoliticsEngine(4, mem, ch,
                              {0:"timmy",1:"spike",2:"johnny",3:"aggressive"},
                              lambda s: {i:0.3 for i in range(4) if i!=s})

        # Pre-populate 50 active deals
        async def setup():
            for i in range(50):
                d = await pe.propose_deal(i%4, (i+1)%4, DealType.NON_AGGRESSION, current_turn=1)
                d.response = DealResponse.ACCEPTED
        _run(setup())

        start = time.perf_counter()
        for _ in range(1000):
            pe.check_deal_violation(1, 0, ActionType.ATTACKED, current_turn=2)
        elapsed = time.perf_counter() - start

        cps = 1000 / elapsed
        print(f"\nPoliticsEngine.check_deal_violation: {cps:.0f} checks/s")
        assert cps >= 500


# ---------------------------------------------------------------------------
# 4. Integrated simulated-turn throughput
# ---------------------------------------------------------------------------

class BenchIntegrated:
    SIMULATED_TURNS = 50
    MIN_TURNS_PER_S = 10

    def test_simulated_turn_throughput(self):
        """
        Simulate N full turns: threat assessment + politics check + memory record.
        Measures combined per-turn overhead of the AI subsystems.
        """
        from commander_ai_lab.sim.threat_assessor  import assess_threats
        from commander_ai_lab.sim.politics.memory  import TargetingMemory, ActionType
        from commander_ai_lab.sim.politics.comms   import PoliticsCommsChannel
        from commander_ai_lab.sim.politics.engine  import PoliticsEngine
        from commander_ai_lab.sim.politics.deals   import DealType

        gs  = _GS()

        def _threat_dict(viewer_seat: int) -> dict[int, float]:
            return {s.seat: s.total for s in assess_threats(gs, viewer_seat=viewer_seat)}

        mem = TargetingMemory(4)
        ch  = PoliticsCommsChannel()
        pe  = PoliticsEngine(
            4, mem, ch,
            {0:"timmy",1:"spike",2:"johnny",3:"aggressive"},
            _threat_dict,
        )

        async def simulate():
            start = time.perf_counter()
            for turn in range(self.SIMULATED_TURNS):
                active = turn % 4
                # Assess threats for all seats
                for seat in range(4):
                    assess_threats(gs, viewer_seat=seat)
                # Record a simulated attack
                attacker = active
                defender = (active + 1) % 4
                mem.record_attack(turn, attacker, defender)
                mem.record_damage(turn, attacker, defender, amount=5)
                # Politics: on_turn_start
                await pe.on_turn_start(
                    active_seat=active,
                    current_turn=turn,
                    game_state=gs,
                )
            return time.perf_counter() - start

        elapsed = _run(simulate())
        tps = self.SIMULATED_TURNS / elapsed
        print(f"\nIntegrated simulated turns: {tps:.1f} turns/s  ({elapsed*1000:.0f} ms total)")
        assert tps >= self.MIN_TURNS_PER_S


# ---------------------------------------------------------------------------
# 5. Memory scalability (large event log)
# ---------------------------------------------------------------------------

class BenchMemoryScale:
    def test_aggression_score_scales_linearly(self):
        """
        Verify O(n) query time doesn't blow up with 100k events.
        """
        from commander_ai_lab.sim.politics.memory import TargetingMemory, ActionType
        mem = TargetingMemory(4)
        N = 100_000
        for i in range(N):
            mem.record(i, i % 4, (i+1) % 4, ActionType.ATTACKED)

        start = time.perf_counter()
        mem.aggression_score(0, 1, current_turn=N)
        elapsed = time.perf_counter() - start

        print(f"\naggression_score with {N} events: {elapsed*1000:.2f} ms")
        assert elapsed < 1.0, f"Too slow with {N} events: {elapsed:.3f}s"
