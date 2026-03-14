"""
Phase 2 Unit Tests — AIOpponent, Personality Prompts
=====================================================
Run with: pytest tests/test_phase2.py -v

Note: LLM connectivity is NOT required. All tests run fully offline
using the heuristic fallback path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from commander_ai_lab.sim.models import Card, Player, SimState
from commander_ai_lab.sim.game_state import CommanderGameState
from commander_ai_lab.sim.personality_prompts import (
    AGGRO_TIMMY, CONTROL_SPIKE, COMBO_JOHNNY, POLITICAL_NEGOTIATOR,
    get_personality, list_personalities, PERSONALITIES,
)
from commander_ai_lab.sim.ai_opponent import AIOpponent, create_four_player_ai_roster


# ── Helpers ────────────────────────────────────────────────────────────

def _make_card(name: str, type_line: str = "Creature", cmc: int = 3) -> Card:
    c = Card(name=name, type_line=type_line, cmc=cmc)
    c.power = "3"
    c.toughness = "3"
    return c


def _make_game_state(num_players: int = 4) -> CommanderGameState:
    sim = SimState()
    sim.init_battlefields(num_players)
    for i in range(num_players):
        p = Player(name=f"Player{i}", life=40, owner_id=i)
        p.hand = [_make_card(f"Card{j}") for j in range(4)]
        p.library = [_make_card(f"Lib{j}") for j in range(20)]
        sim.players.append(p)
    gs = CommanderGameState.from_sim_state(sim)
    gs.turn = 5
    gs.current_phase = "main1"
    gs.active_player_seat = 0
    gs.priority_seat = 0
    return gs


def _make_moves(n: int = 5) -> list[dict]:
    categories = ["play_land", "cast_spell", "attack", "pass_priority", "activate_ability"]
    return [
        {"id": i + 1, "category": categories[i % len(categories)],
         "description": f"Action {i + 1}"}
        for i in range(n)
    ]


def _offline_ai(seat: int = 0, personality=None, tmp_path: Path | None = None) -> AIOpponent:
    """Create an AIOpponent with LLM disconnected (offline/fallback mode)."""
    ai = AIOpponent(
        name=f"TestAI_{seat}",
        seat=seat,
        personality=personality or AGGRO_TIMMY,
        log_dir=str(tmp_path) if tmp_path else tempfile.mkdtemp(),
    )
    ai.brain._connected = False  # Force offline / heuristic mode
    return ai


# ── Personality Tests ────────────────────────────────────────────────

class TestPersonalityPrompts:
    def test_all_four_personalities_exist(self):
        assert len(PERSONALITIES) == 4
        for key in ("aggro_timmy", "control_spike", "combo_johnny", "political_negotiator"):
            assert key in PERSONALITIES

    def test_get_personality_returns_correct(self):
        p = get_personality("combo_johnny")
        assert p.key == "combo_johnny"
        assert "combo" in p.system_prompt.lower()

    def test_get_personality_raises_on_unknown(self):
        with pytest.raises(KeyError):
            get_personality("does_not_exist")

    def test_list_personalities(self):
        keys = list_personalities()
        assert len(keys) == 4

    def test_system_prompts_are_nonempty(self):
        for p in PERSONALITIES.values():
            assert len(p.system_prompt) > 100

    def test_narration_styles_defined(self):
        for p in PERSONALITIES.values():
            assert p.narration_style

    def test_prompt_under_token_budget(self):
        # Each personality system_prompt alone must stay under ~2000 tokens (~8000 chars)
        for p in PERSONALITIES.values():
            assert len(p.system_prompt) < 8000, f"{p.key} system_prompt too long"


# ── AIOpponent Construction Tests ───────────────────────────────────

class TestAIOpponentConstruction:
    def test_instantiation(self, tmp_path):
        ai = _offline_ai(seat=2, personality=CONTROL_SPIKE, tmp_path=tmp_path)
        assert ai.name == "TestAI_2"
        assert ai.seat == 2
        assert ai.personality.key == "control_spike"
        assert ai.brain is not None
        assert ai.state_logger is not None

    def test_four_player_roster(self, tmp_path):
        roster = create_four_player_ai_roster(log_dir=str(tmp_path))
        assert len(roster) == 4
        seats = [ai.seat for ai in roster]
        assert seats == [0, 1, 2, 3]
        personalities = [ai.personality.key for ai in roster]
        assert len(set(personalities)) == 4  # all different

    def test_four_player_roster_custom_names(self, tmp_path):
        names = ["Alice", "Bob", "Carol", "Dave"]
        roster = create_four_player_ai_roster(names=names, log_dir=str(tmp_path))
        for ai, name in zip(roster, names):
            assert ai.name == name

    def test_new_game_resets_state(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        ai.decide_action(gs, moves)
        assert ai._total_decisions == 1
        ai.new_game()
        assert ai._total_decisions == 0
        assert len(ai.memory_log) == 0


# ── decide_action Tests (offline / heuristic) ────────────────────────

class TestDecideAction:
    def test_returns_valid_move_id(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        result = ai.decide_action(gs, moves)
        valid_ids = {m["id"] for m in moves}
        assert result in valid_ids

    def test_prefers_play_land(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = [
            {"id": 1, "category": "pass_priority", "description": "Pass"},
            {"id": 2, "category": "play_land", "description": "Play Forest"},
            {"id": 3, "category": "cast_spell", "description": "Cast Llanowar Elves"},
        ]
        result = ai.decide_action(gs, moves)
        assert result == 2  # play_land has highest priority

    def test_empty_moves_returns_none(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        result = ai.decide_action(gs, [])
        assert result is None

    def test_fallback_used_flag_logged(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        ai.decide_action(gs, moves)
        assert ai._total_fallbacks == 1  # LLM disconnected → always fallback

    def test_memory_log_populated(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        ai.decide_action(gs, moves)
        assert len(ai.memory_log) == 1
        entry = ai.memory_log[0]
        assert entry.turn == 5
        assert entry.fallback_used is True

    def test_snapshot_saved_to_disk(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        ai.decide_action(gs, moves)
        snaps = ai.state_logger.list_snapshots()
        assert len(snaps) == 1

    def test_multiple_decisions_accumulate(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        for _ in range(5):
            ai.decide_action(gs, moves)
        assert ai._total_decisions == 5


# ── narrate_play Tests ────────────────────────────────────────────────

class TestNarratePlay:
    def test_returns_string(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        moves = _make_moves()
        result = ai.narrate_play(1, moves)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_under_30_words(self, tmp_path):
        for personality in PERSONALITIES.values():
            ai = _offline_ai(personality=personality, tmp_path=tmp_path)
            moves = _make_moves()
            narration = ai.narrate_play(1, moves)
            assert len(narration.split()) <= 30, (
                f"Narration too long for {personality.key}: '{narration}'"
            )

    def test_narration_backfilled_to_memory(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        ai.decide_action(gs, moves)
        narration = ai.narrate_play(1, moves)
        assert ai.memory_log[-1].narration == narration

    def test_none_move_id(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        result = ai.narrate_play(None, [])
        assert isinstance(result, str)


# ── parse_move_id Tests ────────────────────────────────────────────────

class TestParseMoveId:
    def setup_method(self):
        self.ai = _offline_ai()
        self.moves = _make_moves(5)  # ids 1–5

    def test_plain_number(self):
        assert self.ai._parse_move_id("3", self.moves) == 3

    def test_number_in_sentence(self):
        assert self.ai._parse_move_id("I choose action 2 as my move.", self.moves) == 2

    def test_json_response(self):
        assert self.ai._parse_move_id('{"id": 4}', self.moves) == 4

    def test_invalid_number_returns_none(self):
        assert self.ai._parse_move_id("99", self.moves) is None

    def test_no_number_returns_none(self):
        assert self.ai._parse_move_id("I pass.", self.moves) is None

    def test_think_block_stripped(self):
        raw = "<think>Let me consider...</think>\n2"
        assert self.ai._parse_move_id(raw, self.moves) == 2


# ── Stats Tests ────────────────────────────────────────────────────────────

class TestStats:
    def test_get_stats_structure(self, tmp_path):
        ai = _offline_ai(tmp_path=tmp_path)
        gs = _make_game_state()
        moves = _make_moves()
        ai.decide_action(gs, moves)
        stats = ai.get_stats()
        assert stats["name"] == "TestAI_0"
        assert stats["total_decisions"] == 1
        assert stats["total_fallbacks"] == 1
        assert stats["fallback_rate"] == 1.0
        assert "llm_stats" in stats
