"""
Phase 3 Unit Tests — Turn Manager, Threat Assessor
===================================================
Run with: pytest tests/test_phase3.py -v

All tests run fully offline (no Ollama required). The turn manager is
tested using a mock game state with stub legal_moves / apply_move,
avoiding any dependency on the live rules engine.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import pytest

from commander_ai_lab.sim.threat_assessor import assess_threats, top_threat, ThreatScore
from commander_ai_lab.sim.turn_manager import (
    CommanderTurnManager,
    TurnManagerConfig,
    GameEvent,
    PHASES,
    ACTION_PHASES,
)
from commander_ai_lab.sim.ai_opponent import AIOpponent
from commander_ai_lab.sim.personality_prompts import AGGRO_TIMMY, CONTROL_SPIKE


# ── Stub Game State ────────────────────────────────────────────────────────

@dataclass
class _StubPlayer:
    name: str
    life: int = 40
    eliminated: bool = False
    hand: list = field(default_factory=list)
    library: list = field(default_factory=list)
    graveyard: list = field(default_factory=list)
    battlefield: list = field(default_factory=list)
    exile: list = field(default_factory=list)
    command_zone: list = field(default_factory=list)
    commander_zone: list = field(default_factory=list)
    commander_cast_count: int = 0
    commander_damage_received: dict = field(default_factory=dict)

    def commander_tax(self) -> int:
        return self.commander_cast_count * 2

    class mana_pool:
        """Stub mana pool."""
        W = U = B = R = G = C = 0
        def total(self) -> int: return 0
        def to_dict(self) -> dict: return {"W":0,"U":0,"B":0,"R":0,"G":0,"C":0,"total":0}

    mana_pool = mana_pool()


class _StubSimState:
    """Minimal SimState stub — delegates to player battlefields."""

    def __init__(self, players: list) -> None:
        self._players = players

    def get_battlefield(self, seat: int) -> list:
        if 0 <= seat < len(self._players):
            return self._players[seat].battlefield
        return []


class _StubGameState:
    """Minimal CommanderGameState-compatible stub."""

    def __init__(self, num_players: int = 4):
        self.players = [_StubPlayer(name=f"P{i}", life=40) for i in range(num_players)]
        self.commander_players = self.players  # prompt_builder iterates this
        self.turn = 0
        self.current_phase = "main1"
        self.active_player_seat = 0
        self.priority_seat = 0
        self.land_drop_used = False
        self._move_counter = 0
        self.stack: list = []
        self.sim_state = _StubSimState(self.players)

    def active_player(self):
        if 0 <= self.active_player_seat < len(self.players):
            return self.players[self.active_player_seat]
        return None

    def priority_player(self):
        if 0 <= self.priority_seat < len(self.players):
            return self.players[self.priority_seat]
        return None

    def battlefield(self, seat: int) -> list:
        """Return the battlefield for the given seat."""
        return self.players[seat].battlefield

    def stack_is_empty(self) -> bool:
        return len(self.stack) == 0

    def living_players(self) -> list:
        return [p for p in self.players if not p.eliminated]

    def get_legal_moves(self, seat: int) -> list[dict]:
        """Always return one pass move per seat."""
        return [
            {"id": 1, "category": "pass_priority", "description": "Pass"},
            {"id": 2, "category": "play_land",    "description": "Play Forest"},
        ]

    def apply_move(self, seat: int, move_id: int) -> None:
        self._move_counter += 1

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "current_phase": self.current_phase,
            "active_player_seat": self.active_player_seat,
            "players": [{"name": p.name, "life": p.life} for p in self.players],
        }


def _stub_gs(num_players: int = 4) -> _StubGameState:
    return _StubGameState(num_players=num_players)


def _offline_ai(seat: int, personality=None) -> AIOpponent:
    import tempfile
    ai = AIOpponent(
        name=f"AI_{seat}",
        seat=seat,
        personality=personality or AGGRO_TIMMY,
        log_dir=tempfile.mkdtemp(),
    )
    ai.brain._connected = False
    return ai


def _make_tm(
    num_players: int = 4,
    max_turns: int = 2,
    human_seats: set | None = None,
) -> CommanderTurnManager:
    gs = _stub_gs(num_players)
    ai_list = [_offline_ai(i) for i in range(num_players)]
    cfg = TurnManagerConfig(max_turns=max_turns, ai_decision_delay=0.0)
    return CommanderTurnManager(
        game_state=gs,
        ai_opponents=ai_list,
        human_seats=human_seats or set(),
        config=cfg,
    )


# ── ThreatAssessor Tests ────────────────────────────────────────────────────

class TestThreatAssessor:
    def _gs_with_creatures(self) -> _StubGameState:
        gs = _stub_gs(4)
        # Give seat 0 a big creature — use Card from sim.models for full API compat
        from commander_ai_lab.sim.models import Card
        gs.players[0].battlefield = [
            Card(name="Dragon", type_line="Creature — Dragon", pt="6/6", power="6", toughness="6"),
            Card(name="Forest", type_line="Basic Land — Forest"),
        ]
        gs.players[1].hand = [Card(name=f"Card{i}") for i in range(7)]
        return gs

    def test_returns_score_per_non_eliminated_player(self):
        gs = _stub_gs(4)
        scores = assess_threats(gs, viewer_seat=0)
        assert len(scores) == 4

    def test_eliminated_players_excluded(self):
        gs = _stub_gs(4)
        gs.players[2].eliminated = True
        scores = assess_threats(gs, viewer_seat=0)
        assert len(scores) == 3
        assert all(s.seat != 2 for s in scores)

    def test_high_power_creature_raises_threat(self):
        gs = self._gs_with_creatures()
        scores = assess_threats(gs, viewer_seat=1)
        seat0_score = next(s for s in scores if s.seat == 0)
        seat2_score = next(s for s in scores if s.seat == 2)
        assert seat0_score.total > seat2_score.total

    def test_scores_normalized_0_to_1(self):
        gs = self._gs_with_creatures()
        for score in assess_threats(gs, viewer_seat=0):
            assert 0.0 <= score.total <= 1.0

    def test_sorted_descending(self):
        gs = self._gs_with_creatures()
        scores = assess_threats(gs, viewer_seat=1)
        totals = [s.total for s in scores]
        assert totals == sorted(totals, reverse=True)

    def test_top_threat_excludes_self(self):
        gs = self._gs_with_creatures()
        threat = top_threat(gs, viewer_seat=0, exclude_self=True)
        assert threat is not None
        assert threat.seat != 0

    def test_top_threat_includes_self_when_asked(self):
        gs = self._gs_with_creatures()
        threat = top_threat(gs, viewer_seat=0, exclude_self=False)
        # seat 0 has biggest creature — should be top threat
        assert threat is not None
        assert threat.seat == 0

    def test_threat_score_has_raw_dict(self):
        gs = _stub_gs()
        for score in assess_threats(gs, viewer_seat=0):
            assert "total_power" in score.raw
            assert "life" in score.raw


# ── TurnManager Construction ────────────────────────────────────────────────

class TestTurnManagerConstruction:
    def test_ai_map_built_correctly(self):
        tm = _make_tm(num_players=4)
        assert len(tm._ai_map) == 4
        assert all(seat in tm._ai_map for seat in range(4))

    def test_turn_queue_initialized(self):
        tm = _make_tm(num_players=4)
        assert list(tm._turn_queue) == [0, 1, 2, 3]

    def test_human_seats_excluded_from_ai_map(self):
        gs = _stub_gs(4)
        ai_list = [_offline_ai(i) for i in range(1, 4)]  # seats 1-3 only
        cfg = TurnManagerConfig(max_turns=1, ai_decision_delay=0.0)
        tm = CommanderTurnManager(
            game_state=gs,
            ai_opponents=ai_list,
            human_seats={0},
            config=cfg,
        )
        assert 0 not in tm._ai_map
        assert 1 in tm._ai_map

    def test_two_player_game(self):
        tm = _make_tm(num_players=2)
        assert list(tm._turn_queue) == [0, 1]


# ── TurnManager async run_game ──────────────────────────────────────────────

class TestRunGame:
    def test_game_completes_within_max_turns(self):
        tm = _make_tm(num_players=4, max_turns=2)
        winner = asyncio.run(tm.run_game())
        # Stub has no elimination logic → game times out, winner by life
        assert tm.game_over is True

    def test_elimination_removes_from_queue(self):
        tm = _make_tm(num_players=4, max_turns=1)
        # Manually eliminate seat 2 before running
        tm.gs.players[2].eliminated = True
        asyncio.run(tm.run_game())
        assert 2 not in tm._turn_queue

    def test_events_fired(self):
        events: list[GameEvent] = []

        async def collect(ev: GameEvent):
            events.append(ev)

        gs = _stub_gs(2)
        ai_list = [_offline_ai(0), _offline_ai(1)]
        cfg = TurnManagerConfig(max_turns=1, ai_decision_delay=0.0)
        tm = CommanderTurnManager(
            game_state=gs,
            ai_opponents=ai_list,
            config=cfg,
            on_event=collect,
        )
        asyncio.run(tm.run_game())
        types = {e.event_type for e in events}
        assert "phase_change" in types

    def test_thinking_callbacks_fired(self):
        thinking_log: list[tuple] = []

        async def on_think(seat: int, is_thinking: bool):
            thinking_log.append((seat, is_thinking))

        gs = _stub_gs(2)
        ai_list = [_offline_ai(0), _offline_ai(1)]
        cfg = TurnManagerConfig(max_turns=1, ai_decision_delay=0.0)
        tm = CommanderTurnManager(
            game_state=gs, ai_opponents=ai_list, config=cfg, on_thinking=on_think
        )
        asyncio.run(tm.run_game())
        # Each AI turn should emit (seat, True) and (seat, False)
        assert len(thinking_log) > 0
        starts = [(s, t) for s, t in thinking_log if t]
        ends   = [(s, t) for s, t in thinking_log if not t]
        assert len(starts) == len(ends)

    def test_get_stats_structure(self):
        tm = _make_tm(num_players=2, max_turns=1)
        asyncio.run(tm.run_game())
        stats = tm.get_stats()
        assert "turn" in stats
        assert "total_actions" in stats
        assert "game_over" in stats


# ── APNAP Priority ──────────────────────────────────────────────────────────

class TestAPNAP:
    def test_phases_constant_has_all_required_phases(self):
        for phase in ("untap", "draw", "main1", "main2",
                      "declare_attackers", "cleanup"):
            assert phase in PHASES

    def test_action_phases_subset_of_phases(self):
        assert ACTION_PHASES.issubset(set(PHASES))

    def test_apnap_does_not_deadlock(self):
        """APNAP window should complete even if all AI pass immediately."""
        tm = _make_tm(num_players=4, max_turns=1)
        async def run():
            await tm._apnap_priority_window(
                active_seat=0, turn_num=1, phase="main1"
            )
        asyncio.run(run())  # Should not hang


# ── Threat Score Refresh ────────────────────────────────────────────────────

class TestThreatRefresh:
    def test_threat_cache_populated_after_main1(self):
        tm = _make_tm(num_players=4, max_turns=1)
        asyncio.run(tm.run_game())
        # After at least one main1 phase, cache should have entries
        assert len(tm._threat_cache) > 0

    def test_threat_scores_per_seat_are_lists(self):
        tm = _make_tm(num_players=4, max_turns=1)
        asyncio.run(tm.run_game())
        for seat, scores in tm._threat_cache.items():
            assert isinstance(scores, list)
            for s in scores:
                assert isinstance(s, ThreatScore)
