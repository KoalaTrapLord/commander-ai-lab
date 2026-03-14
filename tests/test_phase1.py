"""
Phase 1 Unit Tests — Game State, Prompt Builder, State Logger
=============================================================
Run with: pytest tests/test_phase1.py -v
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from commander_ai_lab.sim.models import Card, Player, SimState
from commander_ai_lab.sim.game_state import (
    CommanderGameState,
    CommanderPlayer,
    ManaPool,
    StackItem,
)
from commander_ai_lab.sim.prompt_builder import (
    state_to_prompt,
    legal_moves_to_prompt,
    build_full_prompt,
)
from commander_ai_lab.sim.state_logger import StateLogger, MAX_SNAPSHOTS


# ── Fixtures ──────────────────────────────────────────────────

def _make_card(name: str, type_line: str = "Creature", cmc: int = 3) -> Card:
    c = Card(name=name, type_line=type_line, cmc=cmc)
    c.power = "3"
    c.toughness = "3"
    return c


def _make_game_state(num_players: int = 2) -> CommanderGameState:
    """Build a minimal CommanderGameState for testing."""
    sim = SimState()
    sim.init_battlefields(num_players)
    for i in range(num_players):
        p = Player(name=f"Player{i}", life=40, owner_id=i)
        p.hand = [_make_card(f"Card{j}") for j in range(4)]
        p.library = [_make_card(f"Lib{j}") for j in range(20)]
        sim.players.append(p)
        sim.add_to_battlefield(i, _make_card(f"Creature{i}"))

    gs = CommanderGameState.from_sim_state(sim)
    gs.turn = 3
    gs.current_phase = "main1"
    gs.active_player_seat = 0
    gs.priority_seat = 0

    # Give player 0 a commander
    commander = _make_card("Atraxa, Praetors' Voice", "Legendary Creature")
    commander.is_commander = True
    gs.commander_players[0].commander_zone.append(commander)
    return gs


# ── ManaPool Tests ────────────────────────────────────────────

class TestManaPool:
    def test_total(self):
        mp = ManaPool(W=2, U=1, G=3)
        assert mp.total() == 6

    def test_empty(self):
        mp = ManaPool(W=2, U=3)
        mp.empty()
        assert mp.total() == 0

    def test_serialization(self):
        mp = ManaPool(W=1, R=2, C=1)
        d = mp.to_dict()
        assert d["W"] == 1
        assert d["total"] == 4
        mp2 = ManaPool.from_dict(d)
        assert mp2.R == 2


# ── CommanderPlayer Tests ─────────────────────────────────────

class TestCommanderPlayer:
    def test_commander_tax(self):
        cp = CommanderPlayer(base=Player(name="Test"))
        assert cp.commander_tax() == 0
        cp.commander_cast_count = 2
        assert cp.commander_tax() == 4

    def test_commander_damage_death(self):
        cp = CommanderPlayer(base=Player(name="Test"))
        cp.commander_damage_received = {0: 20, 1: 5}
        assert not cp.is_dead_to_commander_damage()
        cp.commander_damage_received[0] = 21
        assert cp.is_dead_to_commander_damage()

    def test_to_dict_json_serializable(self):
        cp = CommanderPlayer(base=Player(name="Test", life=35))
        cp.commander_zone.append(_make_card("Krenko", "Legendary Creature"))
        d = cp.to_dict()
        # Must be JSON-serializable
        json.dumps(d)
        assert d["life"] == 35
        assert d["commanderZone"] == ["Krenko"]


# ── CommanderGameState Tests ──────────────────────────────────

class TestCommanderGameState:
    def test_from_sim_state(self):
        gs = _make_game_state(4)
        assert len(gs.commander_players) == 4
        assert gs.commander_players[0].name == "Player0"

    def test_to_json_is_valid(self):
        gs = _make_game_state(2)
        raw = gs.to_json()
        parsed = json.loads(raw)
        assert parsed["turn"] == 3
        assert len(parsed["players"]) == 2

    def test_commander_damage_tracking(self):
        gs = _make_game_state(2)
        gs.deal_commander_damage(from_seat=0, to_seat=1, amount=10)
        assert gs.get_commander_damage(0, 1) == 10
        assert gs.commander_players[1].life == 30

    def test_stack_operations(self):
        gs = _make_game_state(2)
        item = StackItem(item_type="spell", card_name="Counterspell",
                         controller_seat=1, description="Counter target spell")
        gs.stack.append(item)
        assert not gs.stack_is_empty()
        assert gs.stack[0].card_name == "Counterspell"


# ── Prompt Builder Tests ──────────────────────────────────────

class TestPromptBuilder:
    def test_state_to_prompt_contains_player_info(self):
        gs = _make_game_state(2)
        prompt = state_to_prompt(gs, viewer_seat=0)
        assert "Player0" in prompt
        assert "Player1" in prompt
        assert "Turn: 3" in prompt
        assert "Main Phase 1" in prompt

    def test_viewer_hand_shown_opponent_hidden(self):
        gs = _make_game_state(2)
        prompt = state_to_prompt(gs, viewer_seat=0)
        # Viewer's hand should list cards; opponent's should say hidden
        assert "Card0" in prompt
        assert "hidden" in prompt

    def test_commander_shown_in_prompt(self):
        gs = _make_game_state(2)
        prompt = state_to_prompt(gs, viewer_seat=0)
        assert "Atraxa" in prompt

    def test_legal_moves_numbered(self):
        moves = [
            {"id": 1, "category": "cast_spell", "description": "Cast Lightning Bolt"},
            {"id": 2, "category": "pass_priority", "description": "Pass priority"},
        ]
        result = legal_moves_to_prompt(moves)
        assert "1." in result
        assert "2." in result
        assert "Cast Spell" in result

    def test_empty_moves_returns_pass_message(self):
        result = legal_moves_to_prompt([])
        assert "pass priority" in result.lower()

    def test_build_full_prompt_under_token_estimate(self):
        gs = _make_game_state(4)
        moves = [
            {"id": i, "category": "cast_spell",
             "description": f"Cast Spell {i}"} for i in range(10)
        ]
        prompt = build_full_prompt(gs, viewer_seat=0, moves=moves,
                                   personality="You are an aggressive player.")
        # Rough token estimate: 1 token ~= 4 chars
        estimated_tokens = len(prompt) / 4
        assert estimated_tokens < 3000, f"Prompt too long: ~{estimated_tokens:.0f} tokens"


# ── State Logger Tests ────────────────────────────────────────

class TestStateLogger:
    def test_save_and_load(self, tmp_path):
        gs = _make_game_state(2)
        moves = [{"id": 1, "category": "pass_priority", "description": "Pass"}]
        prompt = build_full_prompt(gs, 0, moves)

        logger = StateLogger(log_dir=tmp_path)
        path = logger.save(gs, prompt, chosen_move_id=1, seat=0)

        assert path.exists()
        data = logger.load(path)
        assert data["meta"]["turn"] == 3
        assert data["meta"]["chosenMoveId"] == 1
        assert data["prompt"] == prompt
        assert "gameState" in data

    def test_rotation_enforces_max(self, tmp_path):
        gs = _make_game_state(2)
        logger = StateLogger(log_dir=tmp_path)

        # Write MAX_SNAPSHOTS + 5 files
        for i in range(MAX_SNAPSHOTS + 5):
            gs.turn = i
            logger.save(gs, f"prompt {i}", chosen_move_id=0, seat=0)

        assert logger.count() <= MAX_SNAPSHOTS

    def test_load_latest(self, tmp_path):
        gs = _make_game_state(2)
        logger = StateLogger(log_dir=tmp_path)
        gs.turn = 99
        logger.save(gs, "latest prompt", chosen_move_id=2, seat=1)
        latest = logger.load_latest()
        assert latest is not None
        assert latest["meta"]["turn"] == 99

    def test_clear_all(self, tmp_path):
        gs = _make_game_state(2)
        logger = StateLogger(log_dir=tmp_path)
        for _ in range(5):
            logger.save(gs, "prompt", chosen_move_id=0, seat=0)
        deleted = logger.clear_all()
        assert deleted == 5
        assert logger.count() == 0

    def test_fallback_flag_recorded(self, tmp_path):
        gs = _make_game_state(2)
        logger = StateLogger(log_dir=tmp_path)
        path = logger.save(gs, "prompt", chosen_move_id=None,
                           seat=0, fallback_used=True)
        data = logger.load(path)
        assert data["meta"]["fallbackUsed"] is True
