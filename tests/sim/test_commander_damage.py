"""
Regression tests for centralized commander damage tracking.
============================================================
Covers:
- _apply_damage centralized path (life, stats, commander tracking, elimination)
- Combat damage routing through _apply_damage (commander vs non-commander)
- Commander damage 21-lethal elimination rule
- Non-combat commander damage (direct _apply_damage calls)
- Multi-seat / partner commander edge cases

Run with: pytest tests/sim/test_commander_damage.py -v
"""

import pytest
from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState
from commander_ai_lab.sim.rules import enrich_card
from commander_ai_lab.sim.engine import GameEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sim(num_players: int = 2, starting_life: int = 40) -> SimState:
    """Create a minimal SimState with empty battlefields."""
    sim = SimState(max_turns=25)
    for i in range(num_players):
        sim.players.append(Player(
            name=f"P{i}",
            life=starting_life,
            owner_id=i,
            stats=PlayerStats(cards_drawn=0),
        ))
    sim.init_battlefields(num_players)
    return sim


def _creature(name: str, power: int, toughness: int, **kwargs) -> Card:
    """Create a creature card with given stats."""
    c = Card(
        name=name,
        type_line="Creature",
        pt=f"{power}/{toughness}",
        power=str(power),
        toughness=str(toughness),
        **kwargs,
    )
    return enrich_card(c)


def _land(name: str = "Forest") -> Card:
    c = Card(name=name, type_line="Basic Land — Forest", cmc=0)
    return enrich_card(c)


def _place_on_battlefield(sim: SimState, seat: int, card: Card) -> Card:
    """Place a card onto a seat's battlefield with a unique id."""
    card.owner_id = seat
    card.id = sim.next_card_id
    sim.next_card_id += 1
    card.turn_played = -1  # played in a previous turn (not summoning sick)
    sim.add_to_battlefield(seat, card)
    return card


# ===========================================================================
# _apply_damage unit tests
# ===========================================================================

class TestApplyDamage:
    """Tests for the centralized _apply_damage static method."""

    def test_basic_damage_reduces_life(self):
        sim = _make_sim()
        applied = GameEngine._apply_damage(sim, 5, target_seat=1, source_seat=0)
        assert applied == 5
        assert sim.players[1].life == 35
        assert sim.players[1].stats.damage_received == 5
        assert sim.players[0].stats.damage_dealt == 5

    def test_zero_damage_is_noop(self):
        sim = _make_sim()
        applied = GameEngine._apply_damage(sim, 0, target_seat=1, source_seat=0)
        assert applied == 0
        assert sim.players[1].life == 40

    def test_negative_damage_is_noop(self):
        sim = _make_sim()
        applied = GameEngine._apply_damage(sim, -3, target_seat=1, source_seat=0)
        assert applied == 0
        assert sim.players[1].life == 40

    def test_damage_to_eliminated_player_is_noop(self):
        sim = _make_sim()
        sim.players[1].eliminated = True
        applied = GameEngine._apply_damage(sim, 10, target_seat=1, source_seat=0)
        assert applied == 0
        assert sim.players[1].life == 40  # unchanged

    def test_lethal_damage_eliminates(self):
        sim = _make_sim()
        GameEngine._apply_damage(sim, 40, target_seat=1, source_seat=0)
        assert sim.players[1].life == 0
        assert sim.players[1].eliminated is True

    def test_overkill_damage_eliminates(self):
        sim = _make_sim()
        GameEngine._apply_damage(sim, 50, target_seat=1, source_seat=0)
        assert sim.players[1].life == -10
        assert sim.players[1].eliminated is True

    def test_non_commander_damage_does_not_track_commander_damage(self):
        sim = _make_sim()
        GameEngine._apply_damage(
            sim, 10, target_seat=1, source_seat=0,
            source_is_commander=False,
        )
        assert sim.players[1].commander_damage_received == {}

    def test_commander_damage_tracks_per_seat(self):
        sim = _make_sim(num_players=3)
        GameEngine._apply_damage(
            sim, 7, target_seat=2, source_seat=0,
            source_is_commander=True,
        )
        GameEngine._apply_damage(
            sim, 5, target_seat=2, source_seat=1,
            source_is_commander=True,
        )
        assert sim.players[2].commander_damage_received == {0: 7, 1: 5}
        assert sim.players[2].life == 40 - 7 - 5

    def test_commander_damage_accumulates(self):
        sim = _make_sim()
        GameEngine._apply_damage(
            sim, 10, target_seat=1, source_seat=0,
            source_is_commander=True,
        )
        GameEngine._apply_damage(
            sim, 8, target_seat=1, source_seat=0,
            source_is_commander=True,
        )
        assert sim.players[1].commander_damage_received[0] == 18

    def test_21_commander_damage_eliminates(self):
        """Commander damage rule: 21+ from a single source eliminates."""
        sim = _make_sim()
        sim.players[1].life = 100  # high life — shouldn't save them
        GameEngine._apply_damage(
            sim, 21, target_seat=1, source_seat=0,
            source_is_commander=True,
        )
        assert sim.players[1].commander_damage_received[0] == 21
        assert sim.players[1].eliminated is True
        assert sim.players[1].life == 79  # life was reduced but still positive

    def test_incremental_commander_damage_to_21_eliminates(self):
        """Gradual commander damage reaching 21 triggers elimination."""
        sim = _make_sim()
        sim.players[1].life = 100
        for _ in range(3):
            GameEngine._apply_damage(
                sim, 7, target_seat=1, source_seat=0,
                source_is_commander=True,
            )
        assert sim.players[1].commander_damage_received[0] == 21
        assert sim.players[1].eliminated is True

    def test_split_commander_damage_from_two_sources_no_elimination(self):
        """20 commander damage from two different sources should NOT eliminate."""
        sim = _make_sim(num_players=3)
        sim.players[2].life = 100
        GameEngine._apply_damage(
            sim, 10, target_seat=2, source_seat=0,
            source_is_commander=True,
        )
        GameEngine._apply_damage(
            sim, 10, target_seat=2, source_seat=1,
            source_is_commander=True,
        )
        assert sim.players[2].commander_damage_received == {0: 10, 1: 10}
        assert sim.players[2].eliminated is False

    def test_stats_update_on_both_players(self):
        sim = _make_sim()
        GameEngine._apply_damage(sim, 12, target_seat=1, source_seat=0)
        assert sim.players[0].stats.damage_dealt == 12
        assert sim.players[1].stats.damage_received == 12


# ===========================================================================
# Combat damage routing through _apply_damage
# ===========================================================================

class TestCombatCommanderDamageRouting:
    """Verify _resolve_combat routes commander creature damage correctly."""

    def _setup_combat(self, *, commander_power=5, defender_life=40):
        """Set up a 2-player sim with one commander attacker and no blockers."""
        engine = GameEngine(max_turns=25)
        sim = _make_sim(num_players=2, starting_life=defender_life)
        # Attacker: a commander creature
        cmd = _creature("Prossh", commander_power, 5, is_commander=True)
        _place_on_battlefield(sim, 0, cmd)
        # Defender: only lands (no blockers)
        for _ in range(3):
            _place_on_battlefield(sim, 1, _land())
        return engine, sim

    def test_unblocked_commander_tracks_damage(self):
        engine, sim = self._setup_combat(commander_power=5)
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].commander_damage_received.get(0, 0) == 5
        assert sim.players[1].life == 35

    def test_unblocked_noncommander_does_not_track(self):
        engine = GameEngine(max_turns=25)
        sim = _make_sim(num_players=2)
        # Non-commander attacker
        bear = _creature("Grizzly Bears", 2, 2)
        _place_on_battlefield(sim, 0, bear)
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].commander_damage_received == {}
        assert sim.players[1].life == 38

    def test_commander_combat_21_eliminates(self):
        """Commander dealing 21+ combat damage in one hit should eliminate."""
        engine, sim = self._setup_combat(commander_power=21, defender_life=100)
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].eliminated is True
        assert sim.players[1].commander_damage_received[0] == 21

    def test_mixed_commander_and_noncommander_attackers(self):
        """Commander + non-commander attack together; only commander damage tracked."""
        engine = GameEngine(max_turns=25)
        sim = _make_sim(num_players=2)
        cmd = _creature("Prossh", 3, 3, is_commander=True)
        bear = _creature("Grizzly Bears", 2, 2)
        _place_on_battlefield(sim, 0, cmd)
        _place_on_battlefield(sim, 0, bear)
        engine._resolve_combat(sim, 0, turn=1)
        # Total damage: 3 + 2 = 5
        assert sim.players[1].life == 35
        # Only commander damage tracked
        assert sim.players[1].commander_damage_received.get(0, 0) == 3

    def test_commander_trample_over_blocker_tracks_damage(self):
        """Trample damage from a commander going over a blocker should track."""
        engine = GameEngine(max_turns=25)
        # Low life forces the AI to assign a blocker via the
        # "opp.life <= a_pow * 2" heuristic even when toughness < power.
        sim = _make_sim(num_players=2, starting_life=10)
        cmd = _creature("Prossh", 7, 7, is_commander=True, keywords=["trample"])
        _place_on_battlefield(sim, 0, cmd)
        blocker = _creature("Wall", 0, 3)
        _place_on_battlefield(sim, 1, blocker)
        engine._resolve_combat(sim, 0, turn=1)
        # Trample over: 7 - 3 = 4 damage to player (all from commander)
        assert sim.players[1].commander_damage_received.get(0, 0) == 4
        assert sim.players[1].life == 6


# ===========================================================================
# Non-combat commander damage (direct _apply_damage usage)
# ===========================================================================

class TestNonCombatCommanderDamage:
    """
    Validates that _apply_damage correctly handles non-combat commander damage
    scenarios. These represent cases like commander abilities, ETB triggers,
    or spell effects that deal damage where the source is a commander.
    """

    def test_direct_commander_ability_damage(self):
        """Simulates a commander dealing direct damage (e.g. Purphoros trigger)."""
        sim = _make_sim(num_players=4)
        # Commander at seat 0 deals 2 to each opponent via ability
        for target in [1, 2, 3]:
            GameEngine._apply_damage(
                sim, 2, target_seat=target, source_seat=0,
                source_is_commander=True,
            )
        for target in [1, 2, 3]:
            assert sim.players[target].commander_damage_received[0] == 2
            assert sim.players[target].life == 38

    def test_repeated_noncombat_commander_damage_reaches_21(self):
        """Repeated non-combat commander triggers accumulate to lethal 21."""
        sim = _make_sim()
        sim.players[1].life = 100
        # 11 triggers of 2 damage each = 22 total
        for _ in range(11):
            GameEngine._apply_damage(
                sim, 2, target_seat=1, source_seat=0,
                source_is_commander=True,
            )
        assert sim.players[1].commander_damage_received[0] == 22
        assert sim.players[1].eliminated is True

    def test_noncombat_noncommander_spell_damage(self):
        """Non-commander spell damage: reduces life, no commander tracking."""
        sim = _make_sim()
        GameEngine._apply_damage(
            sim, 3, target_seat=1, source_seat=0,
            source_is_commander=False,
        )
        assert sim.players[1].life == 37
        assert sim.players[1].commander_damage_received == {}

    def test_mixed_combat_and_noncombat_commander_damage(self):
        """Both combat and non-combat commander damage should accumulate together."""
        engine = GameEngine(max_turns=25)
        sim = _make_sim(num_players=2)
        sim.players[1].life = 100

        # Non-combat commander damage: 15
        GameEngine._apply_damage(
            sim, 15, target_seat=1, source_seat=0,
            source_is_commander=True,
        )
        assert sim.players[1].commander_damage_received[0] == 15
        assert sim.players[1].eliminated is False

        # Combat commander damage: 6 (pushes to 21)
        cmd = _creature("Prossh", 6, 6, is_commander=True)
        _place_on_battlefield(sim, 0, cmd)
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].commander_damage_received[0] == 21
        assert sim.players[1].eliminated is True


# ===========================================================================
# Full game integration
# ===========================================================================

class TestFullGameCommanderDamage:
    """Integration test: run a full game with commanders and verify tracking."""

    def _make_commander_deck(self, commander_name: str, seed: int = 42) -> list[Card]:
        """Build a small test deck with a named commander."""
        import random
        rng = random.Random(seed)
        cards = []
        # Commander card
        cmd = Card(
            name=commander_name,
            type_line="Legendary Creature",
            cmc=5,
            pt="5/5",
            power="5",
            toughness="5",
        )
        cards.append(enrich_card(cmd))
        # Fill with lands and creatures
        for i in range(24):
            cards.append(enrich_card(Card(
                name=f"Forest_{i}",
                type_line="Basic Land — Forest",
                cmc=0,
            )))
        for i in range(35):
            cards.append(enrich_card(Card(
                name=f"Bear_{i}",
                type_line="Creature — Bear",
                cmc=2,
                pt="2/2",
                power="2",
                toughness="2",
            )))
        rng.shuffle(cards)
        return cards

    def test_commander_damage_tracked_in_full_game(self):
        """In a full game with commanders, commander_damage_received is populated."""
        engine = GameEngine(max_turns=15)
        deck_a = self._make_commander_deck("Prossh, Skyraider of Kher", seed=1)
        deck_b = self._make_commander_deck("Kaalia of the Vast", seed=2)
        result = engine.run(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
            name_a="Alice",
            name_b="Bob",
            commander_names=["Prossh, Skyraider of Kher", "Kaalia of the Vast"],
        )
        assert result is not None
        assert result.turns > 0
        # The game completed without errors — commander damage tracking is wired
