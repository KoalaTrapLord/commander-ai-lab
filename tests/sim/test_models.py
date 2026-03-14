"""Tests for commander_ai_lab.sim.models."""
import pytest
from commander_ai_lab.sim.models import (
    Card, Player, PlayerStats, PlayerResult, GameResult, SimState
)


# ── Card ────────────────────────────────────────────────────

class TestCardGetPower:
    def test_from_power_field(self):
        c = Card(name="Test", power="3", toughness="2", pt="3/2")
        assert c.get_power() == 3

    def test_from_pt_field(self):
        c = Card(name="Test", pt="4/5")
        assert c.get_power() == 4

    def test_no_pt_returns_zero(self):
        c = Card(name="Test")
        assert c.get_power() == 0

    def test_non_numeric_returns_zero(self):
        c = Card(name="Test", power="*", pt="*/2")
        assert c.get_power() == 0


class TestCardGetToughness:
    def test_from_toughness_field(self):
        c = Card(name="Test", power="2", toughness="5", pt="2/5")
        assert c.get_toughness() == 5

    def test_from_pt_field(self):
        c = Card(name="Test", pt="2/7")
        assert c.get_toughness() == 7

    def test_no_pt_returns_zero(self):
        c = Card(name="Test")
        assert c.get_toughness() == 0


class TestCardHasKeyword:
    def test_in_keywords_list(self):
        c = Card(name="Test", keywords=["Flying", "Haste"])
        assert c.has_keyword("flying") is True
        assert c.has_keyword("haste") is True

    def test_in_oracle_text(self):
        c = Card(name="Test", oracle_text="This creature has flying and deathtouch.")
        assert c.has_keyword("flying") is True
        assert c.has_keyword("deathtouch") is True

    def test_missing_keyword(self):
        c = Card(name="Test", oracle_text="Draw a card.", keywords=[])
        assert c.has_keyword("flying") is False

    def test_case_insensitive(self):
        c = Card(name="Test", keywords=["FLYING"])
        assert c.has_keyword("Flying") is True


class TestCardIsLand:
    def test_basic_land(self):
        c = Card(name="Forest", type_line="Basic Land — Forest")
        assert c.is_land() is True

    def test_nonbasic_land(self):
        c = Card(name="Command Tower", type_line="Land")
        assert c.is_land() is True

    def test_creature_not_land(self):
        c = Card(name="Grizzly Bears", type_line="Creature — Bear")
        assert c.is_land() is False

    def test_no_type_line(self):
        c = Card(name="Unknown")
        assert c.is_land() is False


class TestCardIsCreature:
    def test_creature(self):
        c = Card(name="Grizzly Bears", type_line="Creature — Bear")
        assert c.is_creature() is True

    def test_legendary_creature(self):
        c = Card(name="Korvold", type_line="Legendary Creature — Dragon Noble")
        assert c.is_creature() is True

    def test_instant_not_creature(self):
        c = Card(name="Murder", type_line="Instant")
        assert c.is_creature() is False

    def test_land_not_creature(self):
        c = Card(name="Forest", type_line="Basic Land — Forest")
        assert c.is_creature() is False


class TestCardClone:
    def test_clone_is_equal(self, basic_creature):
        clone = basic_creature.clone()
        assert clone.name == basic_creature.name
        assert clone.cmc == basic_creature.cmc

    def test_clone_is_independent(self, basic_creature):
        clone = basic_creature.clone()
        clone.name = "Changed"
        assert basic_creature.name == "Grizzly Bears"


# ── PlayerStats ─────────────────────────────────────────────

class TestPlayerStats:
    def test_to_dict_keys(self):
        stats = PlayerStats(cards_drawn=7, damage_dealt=10)
        d = stats.to_dict()
        assert "cardsDrawn" in d
        assert "damageDealt" in d
        assert d["cardsDrawn"] == 7
        assert d["damageDealt"] == 10

    def test_default_values(self):
        stats = PlayerStats()
        assert stats.cards_drawn == 7
        assert stats.lands_played == 0


# ── PlayerResult & GameResult ────────────────────────────────

class TestPlayerResult:
    def test_to_dict_winner(self):
        pr = PlayerResult(seat_index=0, name="Alice", life=40, finish_position=1)
        d = pr.to_dict()
        assert d["isWinner"] is True
        assert d["seatIndex"] == 0
        assert d["name"] == "Alice"

    def test_to_dict_loser(self):
        pr = PlayerResult(seat_index=1, name="Bob", life=0, eliminated=True, finish_position=2)
        d = pr.to_dict()
        assert d["isWinner"] is False
        assert d["eliminated"] is True


class TestGameResult:
    def _make_result(self):
        p0 = PlayerResult(seat_index=0, name="Alice", life=35, finish_position=1, stats=PlayerStats(damage_dealt=20))
        p1 = PlayerResult(seat_index=1, name="Bob", life=0, eliminated=True, finish_position=2, stats=PlayerStats())
        return GameResult(winner_seat=0, turns=12, players=[p0, p1])

    def test_winner_property(self):
        gr = self._make_result()
        assert gr.winner == 0

    def test_player_a_name(self):
        gr = self._make_result()
        assert gr.player_a_name == "Alice"

    def test_player_b_name(self):
        gr = self._make_result()
        assert gr.player_b_name == "Bob"

    def test_player_a_eliminated(self):
        gr = self._make_result()
        assert gr.player_a_eliminated is False

    def test_player_b_eliminated(self):
        gr = self._make_result()
        assert gr.player_b_eliminated is True

    def test_to_dict_has_legacy_keys(self):
        gr = self._make_result()
        d = gr.to_dict()
        assert "winner" in d
        assert "turns" in d
        assert "playerResults" in d
        assert len(d["playerResults"]) == 2


# ── SimState ─────────────────────────────────────────────────

class TestSimState:
    def test_init_battlefields(self):
        state = SimState()
        state.init_battlefields(4)
        assert len(state.battlefields) == 4

    def test_add_and_get_battlefield(self):
        state = SimState()
        c = Card(name="Test", id=1)
        state.add_to_battlefield(0, c)
        bf = state.get_battlefield(0)
        assert len(bf) == 1
        assert bf[0].name == "Test"

    def test_remove_from_battlefield(self):
        state = SimState()
        c = Card(name="Test", id=42)
        state.add_to_battlefield(0, c)
        removed = state.remove_from_battlefield(42)
        assert removed is not None
        assert removed.name == "Test"
        assert len(state.get_battlefield(0)) == 0

    def test_remove_nonexistent_returns_none(self):
        state = SimState()
        assert state.remove_from_battlefield(999) is None

    def test_all_battlefield_cards(self):
        state = SimState()
        state.add_to_battlefield(0, Card(name="A", id=1))
        state.add_to_battlefield(1, Card(name="B", id=2))
        state.add_to_battlefield(1, Card(name="C", id=3))
        all_cards = state.all_battlefield_cards()
        assert len(all_cards) == 3
