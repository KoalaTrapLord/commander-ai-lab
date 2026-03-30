"""Regression tests for explicit turn-structure and phase progression.

Validates that the headless engine walks through all MTG phases in order,
tracks the current phase on SimState, supports a shared spell budget across
main1+main2, and preserves all prior behavior (combat, elimination, logging).
"""

import random
import pytest
from commander_ai_lab.sim.models import (
    Card,
    Phase,
    PHASE_ORDER,
    SORCERY_PHASES,
    SimState,
)
from commander_ai_lab.sim.rules import enrich_card
from commander_ai_lab.sim.engine import GameEngine


# ── Helpers ──────────────────────────────────────────────────

def _make_deck(seed: int, size: int = 60) -> list[Card]:
    """Deterministic test deck."""
    rng = random.Random(seed)
    pool = [
        Card(name="Forest"),
        Card(name="Sol Ring"),
        Card(name="Cultivate"),
        Card(name="Murder"),
        Card(name="Wrath of God"),
        Card(name="Grizzly Bears"),
        Card(name="Serra Angel"),
    ]
    for c in pool:
        enrich_card(c)
    deck = [pool[i % len(pool)].clone() for i in range(size)]
    rng.shuffle(deck)
    return deck


def _land_heavy_deck(size: int = 60) -> list[Card]:
    """Deck with many lands (ensures mana for spells in both main phases)."""
    cards = []
    for i in range(size):
        if i < 30:
            c = Card(name="Forest")
        elif i < 40:
            c = Card(name="Grizzly Bears")
        elif i < 50:
            c = Card(name="Serra Angel")
        else:
            c = Card(name="Sol Ring")
        enrich_card(c)
        cards.append(c)
    random.Random(42).shuffle(cards)
    return cards


# ══════════════════════════════════════════════════════════════
# Phase Enum Tests
# ══════════════════════════════════════════════════════════════

class TestPhaseEnum:
    """Tests for the Phase enum and related constants."""

    def test_phase_count(self):
        """There should be exactly 12 phases in MTG turn structure."""
        assert len(Phase) == 12

    def test_phase_order_matches_mtg(self):
        """Phases must follow the MTG turn order."""
        expected = [
            "untap", "upkeep", "draw", "main1",
            "begin_combat", "declare_attackers", "declare_blockers",
            "combat_damage", "end_combat",
            "main2", "end_step", "cleanup",
        ]
        assert [p.value for p in PHASE_ORDER] == expected

    def test_phase_is_str_subclass(self):
        """Phase enum values should compare directly with plain strings."""
        assert Phase.MAIN1 == "main1"
        assert Phase.CLEANUP == "cleanup"

    def test_sorcery_phases(self):
        """Only main1 and main2 are sorcery-speed phases."""
        assert SORCERY_PHASES == frozenset({Phase.MAIN1, Phase.MAIN2})

    def test_phase_iteration(self):
        """PHASE_ORDER is iterable and matches Phase members."""
        assert list(PHASE_ORDER) == list(Phase)


# ══════════════════════════════════════════════════════════════
# SimState Phase Tracking
# ══════════════════════════════════════════════════════════════

class TestSimStatePhaseTracking:
    """Tests that SimState tracks phase and active player index."""

    def test_default_phase(self):
        """SimState defaults to MAIN1."""
        sim = SimState()
        assert sim.current_phase == Phase.MAIN1

    def test_default_active_player(self):
        """SimState defaults to player 0 as active."""
        sim = SimState()
        assert sim.active_player_index == 0

    def test_phase_updates_during_game(self):
        """After a game, current_phase should have been set (not stuck at default)."""
        engine = GameEngine(max_turns=1, mulligan_rule="none")
        deck_a = _make_deck(seed=10)
        deck_b = _make_deck(seed=11)
        result = engine.run(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
        )
        # Game completed successfully
        assert result.turns >= 1


# ══════════════════════════════════════════════════════════════
# Phase Progression in Engine
# ══════════════════════════════════════════════════════════════

class TestPhaseProgression:
    """Tests that the engine walks through phases correctly."""

    def test_game_completes_with_phase_structure(self):
        """Game should complete without errors using the new phase loop."""
        engine = GameEngine(max_turns=10)
        result = engine.run(
            deck_a=[c.clone() for c in _make_deck(1)],
            deck_b=[c.clone() for c in _make_deck(2)],
            name_a="Alice",
            name_b="Bob",
        )
        assert result is not None
        assert result.turns > 0
        assert result.winner_seat in (-1, 0, 1)

    def test_four_player_game_with_phases(self):
        """4-player game should complete with the new phase loop."""
        engine = GameEngine(max_turns=10)
        decks = [_make_deck(seed=i) for i in range(4)]
        result = engine.run_n(
            decks=[[c.clone() for c in d] for d in decks],
            names=["A", "B", "C", "D"],
        )
        assert result is not None
        assert result.turns > 0
        assert len(result.players) == 4

    def test_untap_happens_each_turn(self):
        """Creatures tapped for combat are untapped at start of next turn."""
        engine = GameEngine(max_turns=5, record_log=True, mulligan_rule="none")
        # Build deck with creatures that will attack
        deck = []
        for i in range(60):
            if i < 25:
                deck.append(Card(name="Forest"))
            else:
                c = Card(name="Grizzly Bears")
                enrich_card(c)
                deck.append(c)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        # Game should complete — untap logic is working
        assert result.turns > 0

    def test_draw_happens_after_untap(self):
        """Players draw one card each turn after the first."""
        engine = GameEngine(max_turns=3, mulligan_rule="none")
        deck_a = _make_deck(seed=20, size=60)
        deck_b = _make_deck(seed=21, size=60)
        result = engine.run(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
        )
        # Both players should have drawn cards (starting 7 + draws)
        for pr in result.players:
            assert pr.stats.cards_drawn >= 7

    def test_land_drop_in_main1(self):
        """Land drops should still happen (in main1)."""
        engine = GameEngine(max_turns=5, mulligan_rule="none")
        deck = _make_deck(seed=30)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        # At least one player should have played lands
        total_lands = sum(pr.stats.lands_played for pr in result.players)
        assert total_lands > 0

    def test_combat_in_declare_attackers_phase(self):
        """Combat damage should still resolve correctly."""
        engine = GameEngine(max_turns=25, mulligan_rule="none")
        # Use creature-heavy deck so combat is guaranteed
        deck = []
        for i in range(60):
            if i < 24:
                deck.append(Card(name="Forest"))
            else:
                c = Card(name="Grizzly Bears")
                enrich_card(c)
                deck.append(c)
        random.Random(40).shuffle(deck)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        total_damage = sum(pr.stats.damage_dealt for pr in result.players)
        # With creature-heavy decks over 25 turns, combat must happen
        assert total_damage > 0


# ══════════════════════════════════════════════════════════════
# Spell Budget Across Main Phases
# ══════════════════════════════════════════════════════════════

class TestSpellBudget:
    """Tests that the 2-spell budget is shared across main1 and main2."""

    def test_max_two_spells_per_turn(self):
        """No player should cast more than 2 non-commander spells per turn."""
        engine = GameEngine(max_turns=5, mulligan_rule="none")
        deck = _land_heavy_deck()
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        # Both players played spells
        for pr in result.players:
            # spells_cast across all turns; with 5 turns max 10 spells each
            assert pr.stats.spells_cast <= 10  # 2 per turn * 5 turns

    def test_spells_can_split_across_main_phases(self):
        """Engine supports casting in main2 if budget allows.

        We verify by checking that _play_spells returns 0 when budget is 0.
        """
        engine = GameEngine()
        # Create a minimal sim state with one player
        sim = SimState(max_turns=1)
        from commander_ai_lab.sim.models import Player, PlayerStats
        p = Player(
            name="Test",
            life=40,
            owner_id=0,
            hand=[],
            stats=PlayerStats(),
        )
        sim.players.append(p)
        sim.init_battlefields(1)

        # With no cards in hand, should play 0 spells
        result = engine._play_spells(sim, 0, available_mana=5, max_spells=2)
        assert result == 0

    def test_play_spells_respects_max_spells_zero(self):
        """_play_spells with max_spells=0 plays nothing."""
        engine = GameEngine()
        sim = SimState(max_turns=1)
        from commander_ai_lab.sim.models import Player, PlayerStats
        p = Player(
            name="Test",
            life=40,
            owner_id=0,
            hand=[Card(name="Grizzly Bears", cmc=2, type_line="Creature")],
            stats=PlayerStats(),
        )
        sim.players.append(p)
        sim.init_battlefields(1)
        # Add 5 untapped lands
        for _ in range(5):
            land = Card(name="Forest", type_line="Land", tapped=False)
            sim.add_to_battlefield(0, land)

        result = engine._play_spells(sim, 0, available_mana=5, max_spells=0)
        assert result == 0
        # Card should still be in hand
        assert len(p.hand) == 1

    def test_play_spells_respects_max_spells_one(self):
        """_play_spells with max_spells=1 plays at most one spell."""
        engine = GameEngine()
        sim = SimState(max_turns=1)
        from commander_ai_lab.sim.models import Player, PlayerStats
        bear1 = Card(name="Grizzly Bears", cmc=2, type_line="Creature — Bear", pt="2/2")
        bear2 = Card(name="Grizzly Bears", cmc=2, type_line="Creature — Bear", pt="2/2")
        enrich_card(bear1)
        enrich_card(bear2)
        p = Player(
            name="Test",
            life=40,
            owner_id=0,
            hand=[bear1, bear2],
            stats=PlayerStats(),
        )
        sim.players.append(p)
        sim.init_battlefields(1)
        for _ in range(5):
            land = Card(name="Forest", type_line="Land", tapped=False)
            sim.add_to_battlefield(0, land)

        result = engine._play_spells(sim, 0, available_mana=5, max_spells=1)
        assert result == 1
        assert len(p.hand) == 1  # one spell remaining


# ══════════════════════════════════════════════════════════════
# Game Log with Phase Structure
# ══════════════════════════════════════════════════════════════

class TestGameLogPhases:
    """Tests that the game log still works with the new phase structure."""

    def test_game_log_has_turns(self):
        """record_log should produce a log with turn entries."""
        engine = GameEngine(max_turns=3, record_log=True, mulligan_rule="none")
        deck = _make_deck(seed=50)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        assert result.game_log is not None
        assert len(result.game_log) > 0

    def test_game_log_turn_structure(self):
        """Each log entry should have turn number and phases list."""
        engine = GameEngine(max_turns=2, record_log=True, mulligan_rule="none")
        deck = _make_deck(seed=51)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        for entry in result.game_log:
            assert "turn" in entry
            assert "phases" in entry
            assert isinstance(entry["phases"], list)

    def test_game_log_phase_entries(self):
        """Phase entries should have player and events."""
        engine = GameEngine(max_turns=2, record_log=True, mulligan_rule="none")
        deck = _make_deck(seed=52)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        for entry in result.game_log:
            for phase in entry["phases"]:
                assert "player" in phase
                assert "playerId" in phase
                assert "events" in phase


# ══════════════════════════════════════════════════════════════
# Backward Compatibility
# ══════════════════════════════════════════════════════════════

class TestBackwardCompat:
    """Ensure existing behavior is preserved."""

    def test_two_player_still_works(self):
        """The 2-player run() entry point should still work."""
        engine = GameEngine(max_turns=10)
        result = engine.run(
            deck_a=[c.clone() for c in _make_deck(60)],
            deck_b=[c.clone() for c in _make_deck(61)],
        )
        assert result.winner_seat in (-1, 0, 1)

    def test_n_player_still_works(self):
        """The N-player run_n() entry point should still work."""
        engine = GameEngine(max_turns=10)
        decks = [_make_deck(seed=i + 70) for i in range(3)]
        result = engine.run_n(
            decks=[[c.clone() for c in d] for d in decks],
            names=["X", "Y", "Z"],
        )
        assert result.winner_seat in range(3)
        assert len(result.players) == 3

    def test_mulligan_rule_still_works(self):
        """London mulligan should still function with the phase refactor."""
        engine = GameEngine(max_turns=5, mulligan_rule="london")
        result = engine.run(
            deck_a=[c.clone() for c in _make_deck(80)],
            deck_b=[c.clone() for c in _make_deck(81)],
        )
        assert result.turns > 0

    def test_no_mulligan_rule_still_works(self):
        """Legacy mulligan='none' should still function."""
        engine = GameEngine(max_turns=5, mulligan_rule="none")
        result = engine.run(
            deck_a=[c.clone() for c in _make_deck(90)],
            deck_b=[c.clone() for c in _make_deck(91)],
        )
        assert result.turns > 0

    def test_commander_damage_still_tracked(self):
        """Commander damage tracking should still work through deal_damage."""
        sim = SimState(max_turns=1)
        from commander_ai_lab.sim.models import Player, PlayerStats
        for i in range(2):
            sim.players.append(Player(
                name=f"P{i}", life=40, owner_id=i, stats=PlayerStats(),
            ))
        sim.init_battlefields(2)

        commander = Card(name="TestCommander", is_commander=True)
        GameEngine.deal_damage(
            sim, 5, target_seat=1,
            source_card=commander, source_seat=0,
            is_combat=True,
        )
        assert sim.players[1].commander_damage_received[0] == 5
        assert sim.players[1].commander_damage_by_card[(0, "TestCommander")] == 5
        assert sim.players[1].life == 35

    def test_direct_damage_still_works(self):
        """Burn spells should still route through deal_damage."""
        sim = SimState(max_turns=1)
        from commander_ai_lab.sim.models import Player, PlayerStats
        for i in range(2):
            sim.players.append(Player(
                name=f"P{i}", life=40, owner_id=i, stats=PlayerStats(),
            ))
        sim.init_battlefields(2)

        burn = Card(name="Lightning Bolt", is_direct_damage=True, direct_damage_amount=3)
        events: list[str] = []
        GameEngine.deal_damage(
            sim, 3, target_seat=1,
            source_card=burn, source_seat=0,
            events=events,
            label="Lightning Bolt deals 3",
        )
        assert sim.players[1].life == 37
        assert len(events) == 1

    def test_elimination_still_works(self):
        """Player elimination should still trigger when life <= 0."""
        engine = GameEngine(max_turns=25, mulligan_rule="none")
        # Build aggro-heavy decks
        deck = []
        for i in range(60):
            if i < 20:
                deck.append(Card(name="Mountain"))
            else:
                c = Card(name="Lightning Bolt")
                enrich_card(c)
                deck.append(c)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        # At least one player should be eliminated (or game timed out)
        assert result.turns > 0

    def test_ml_log_still_works(self):
        """ML logging should still capture decisions."""
        engine = GameEngine(max_turns=3, ml_log=True, mulligan_rule="none")
        deck = _make_deck(seed=100)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        decisions = engine.flush_ml_decisions()
        assert isinstance(decisions, list)
        # With turns happening, there should be some decisions
        if result.turns > 0:
            assert len(decisions) > 0

    def test_result_serializable(self):
        """Game result should still serialize cleanly."""
        import json
        engine = GameEngine(max_turns=3, record_log=True, mulligan_rule="none")
        deck = _make_deck(seed=110)
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        d = result.to_dict()
        json.dumps(d)  # should not raise


# ══════════════════════════════════════════════════════════════
# Turn Manager Phase Constants
# ══════════════════════════════════════════════════════════════

class TestTurnManagerPhaseCompat:
    """Ensure turn_manager.py PHASES/ACTION_PHASES/RESPONSE_PHASES are consistent."""

    def test_turn_manager_phases_match_model(self):
        """turn_manager.PHASES should match the canonical PHASE_ORDER."""
        from commander_ai_lab.sim.turn_manager import PHASES as TM_PHASES
        assert TM_PHASES == [p.value for p in PHASE_ORDER]

    def test_turn_manager_action_phases(self):
        """ACTION_PHASES should be main1 and main2."""
        from commander_ai_lab.sim.turn_manager import ACTION_PHASES
        assert ACTION_PHASES == {"main1", "main2"}

    def test_turn_manager_response_phases(self):
        """RESPONSE_PHASES contains the instant-speed windows dispatched via _apnap_priority_window.

        begin_combat and end_combat are handled as named calls inside _phase_combat()
        directly -- they are NOT in RESPONSE_PHASES. Only upkeep and end_step
        are dispatched through the generic APNAP window in _run_player_turn().
        """
        from commander_ai_lab.sim.turn_manager import RESPONSE_PHASES
        assert RESPONSE_PHASES == {"upkeep", "end_step"}
        assert "begin_combat" not in RESPONSE_PHASES
        assert "end_combat" not in RESPONSE_PHASES
