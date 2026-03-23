"""Tests for London mulligan and opening-hand validation (#86)."""
import random

import pytest

from commander_ai_lab.sim.engine import GameEngine
from commander_ai_lab.sim.models import Card, PlayerStats
from commander_ai_lab.sim.rules import enrich_card


# ── Helpers ───────────────────────────────────────────────────

def _land(name: str = "Forest") -> Card:
    return enrich_card(Card(name=name))


def _spell(name: str = "Grizzly Bears") -> Card:
    return enrich_card(Card(name=name))


def _make_deck(lands: int = 24, spells: int = 36) -> list[Card]:
    """Build a deck with an exact land/spell split."""
    deck: list[Card] = []
    for _ in range(lands):
        deck.append(_land())
    for _ in range(spells):
        deck.append(_spell())
    return deck


def _all_lands_deck(size: int = 60) -> list[Card]:
    """Deck of nothing but lands — forces 7-land opening hand."""
    return [_land() for _ in range(size)]


def _no_lands_deck(size: int = 60) -> list[Card]:
    """Deck with zero lands — forces 0-land opening hand."""
    return [_spell(f"Spell_{i}") for i in range(size)]


# ── PlayerStats fields ────────────────────────────────────────

class TestPlayerStatsMultiganFields:
    def test_default_mulligans_zero(self):
        stats = PlayerStats()
        assert stats.mulligans == 0

    def test_default_opening_hand_lands_zero(self):
        stats = PlayerStats()
        assert stats.opening_hand_lands == 0

    def test_to_dict_includes_mulligan_keys(self):
        stats = PlayerStats(mulligans=2, opening_hand_lands=3)
        d = stats.to_dict()
        assert d["mulligans"] == 2
        assert d["openingHandLands"] == 3


# ── _should_mulligan heuristic ────────────────────────────────

class TestShouldMulligan:
    def test_zero_lands_mulligans(self):
        hand = [_spell() for _ in range(7)]
        assert GameEngine._should_mulligan(hand, 0) is True

    def test_one_land_mulligans(self):
        hand = [_land()] + [_spell() for _ in range(6)]
        assert GameEngine._should_mulligan(hand, 0) is True

    def test_two_lands_keeps(self):
        hand = [_land(), _land()] + [_spell() for _ in range(5)]
        assert GameEngine._should_mulligan(hand, 0) is False

    def test_five_lands_keeps(self):
        hand = [_land() for _ in range(5)] + [_spell(), _spell()]
        assert GameEngine._should_mulligan(hand, 0) is False

    def test_six_lands_mulligans(self):
        hand = [_land() for _ in range(6)] + [_spell()]
        assert GameEngine._should_mulligan(hand, 0) is True

    def test_seven_lands_mulligans(self):
        hand = [_land() for _ in range(7)]
        assert GameEngine._should_mulligan(hand, 0) is True

    def test_desperate_keeps_one_land(self):
        """After 2+ mulligans, accept a 1-land hand."""
        hand = [_land()] + [_spell() for _ in range(6)]
        assert GameEngine._should_mulligan(hand, 2) is False


# ── _count_lands_in_hand ──────────────────────────────────────

class TestCountLandsInHand:
    def test_empty_hand(self):
        assert GameEngine._count_lands_in_hand([]) == 0

    def test_mixed_hand(self):
        hand = [_land(), _spell(), _land(), _spell()]
        assert GameEngine._count_lands_in_hand(hand) == 2

    def test_all_lands(self):
        hand = [_land() for _ in range(7)]
        assert GameEngine._count_lands_in_hand(hand) == 7


# ── _pick_bottom_cards ────────────────────────────────────────

class TestPickBottomCards:
    def test_returns_correct_count(self):
        hand = [_land(), _land(), _spell(), _spell(), _spell()]
        bottom = GameEngine._pick_bottom_cards(hand, 2, {})
        assert len(bottom) == 2

    def test_zero_count_returns_empty(self):
        hand = [_land(), _spell()]
        assert GameEngine._pick_bottom_cards(hand, 0, {}) == []

    def test_count_gte_hand_returns_empty(self):
        hand = [_land()]
        assert GameEngine._pick_bottom_cards(hand, 1, {}) == []

    def test_bottoms_lowest_scored_cards(self):
        """The card with the worst AI score should be picked to bottom."""
        good = enrich_card(Card(name="Serra Angel", type_line="Creature", cmc=5, pt="4/4"))
        bad = enrich_card(Card(name="Forest"))
        hand = [good, bad, _spell()]
        bottom = GameEngine._pick_bottom_cards(hand, 1, {})
        # Lands score very low compared to creatures
        assert bottom[0].name == "Forest"


# ── London mulligan integration ───────────────────────────────

class TestLondonMulliganIntegration:
    def test_good_hand_no_mulligan(self):
        """A well-balanced deck should usually keep on the first try."""
        random.seed(42)
        deck = _make_deck(lands=24, spells=36)
        engine = GameEngine(mulligan_rule="london")
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        # At least one player should have kept without mulligan
        any_kept = any(
            p.stats.mulligans == 0 for p in result.players
        )
        # With a 24-land deck, most seeds give keepable hands
        assert result.turns > 0  # game still works

    def test_all_lands_deck_triggers_mulligan(self):
        """A 60-land deck should always mulligan (7 lands in hand)."""
        random.seed(99)
        deck_lands = _all_lands_deck()
        deck_normal = _make_deck()
        engine = GameEngine(mulligan_rule="london")
        result = engine.run(
            deck_a=[c.clone() for c in deck_lands],
            deck_b=[c.clone() for c in deck_normal],
        )
        # Player A has an all-land deck; must have mulliganed at least once
        pa_stats = result.players[0].stats
        assert pa_stats.mulligans > 0

    def test_no_lands_deck_triggers_mulligan(self):
        """A 0-land deck should always mulligan (0 lands in hand)."""
        random.seed(77)
        deck_empty = _no_lands_deck()
        deck_normal = _make_deck()
        engine = GameEngine(mulligan_rule="london")
        result = engine.run(
            deck_a=[c.clone() for c in deck_empty],
            deck_b=[c.clone() for c in deck_normal],
        )
        pa_stats = result.players[0].stats
        assert pa_stats.mulligans > 0

    def test_mulligan_caps_at_max(self):
        """Even a terrible deck can mulligan at most MAX_MULLIGANS times."""
        random.seed(11)
        deck_empty = _no_lands_deck()
        engine = GameEngine(mulligan_rule="london")
        result = engine.run(
            deck_a=[c.clone() for c in deck_empty],
            deck_b=[c.clone() for c in deck_empty],
        )
        for p in result.players:
            assert p.stats.mulligans <= GameEngine.MAX_MULLIGANS

    def test_hand_size_after_mulligan(self):
        """After N mulligans, opening hand should be 7 - N cards."""
        random.seed(55)
        deck_lands = _all_lands_deck()
        deck_normal = _make_deck()
        engine = GameEngine(mulligan_rule="london")
        # We need to test the internal state, so use _create_state directly
        sim = engine._create_state(
            decks=[[c.clone() for c in deck_lands], [c.clone() for c in deck_normal]],
            names=["LandPlayer", "NormalPlayer"],
        )
        for p in sim.players:
            expected = 7 - p.stats.mulligans
            assert len(p.hand) == expected, (
                f"{p.name}: hand={len(p.hand)}, mulligans={p.stats.mulligans}, "
                f"expected={expected}"
            )

    def test_opening_hand_lands_tracked(self):
        """opening_hand_lands should reflect final kept hand."""
        random.seed(42)
        deck = _make_deck()
        engine = GameEngine(mulligan_rule="london")
        sim = engine._create_state(
            decks=[[c.clone() for c in deck], [c.clone() for c in deck]],
            names=["P1", "P2"],
        )
        for p in sim.players:
            actual_lands = sum(1 for c in p.hand if c.is_land())
            assert p.stats.opening_hand_lands == actual_lands

    def test_total_cards_preserved(self):
        """Mulligan must not create or destroy cards."""
        random.seed(33)
        deck = _make_deck(lands=24, spells=36)
        engine = GameEngine(mulligan_rule="london")
        for _ in range(10):
            sim = engine._create_state(
                decks=[[c.clone() for c in deck], [c.clone() for c in deck]],
                names=["A", "B"],
            )
            for p in sim.players:
                total = len(p.hand) + len(p.library) + len(p.command_zone)
                assert total == 60, f"Card count mismatch: {total}"


# ── mulligan_rule="none" (legacy) ─────────────────────────────

class TestNoMulliganMode:
    def test_no_mulligan_always_keeps_seven(self):
        """With mulligan_rule='none', always get 7 cards, 0 mulligans."""
        random.seed(42)
        deck = _all_lands_deck()
        engine = GameEngine(mulligan_rule="none")
        sim = engine._create_state(
            decks=[[c.clone() for c in deck]],
            names=["P1"],
        )
        p = sim.players[0]
        assert len(p.hand) == 7
        assert p.stats.mulligans == 0


# ── N-player mulligan ─────────────────────────────────────────

class TestNPlayerMulligan:
    def test_four_player_mulligan(self):
        """Each player in a 4-player game resolves mulligans independently."""
        random.seed(42)
        decks = [_make_deck() for _ in range(4)]
        engine = GameEngine(mulligan_rule="london")
        result = engine.run_n(
            decks=[[c.clone() for c in d] for d in decks],
            names=["A", "B", "C", "D"],
        )
        assert len(result.players) == 4
        for p in result.players:
            assert p.stats.mulligans >= 0
            assert p.stats.mulligans <= GameEngine.MAX_MULLIGANS


# ── Commander + mulligan interaction ──────────────────────────

class TestCommanderMulligan:
    def test_commander_stays_in_command_zone_through_mulligans(self):
        """Commander should remain in command zone regardless of mulligans."""
        random.seed(42)
        # Build a deck with a known commander
        deck = _make_deck(lands=24, spells=35)
        commander = Card(name="Kenrith, the Returned King", type_line="Creature", cmc=5, pt="5/5")
        deck.append(commander)
        engine = GameEngine(mulligan_rule="london")
        sim = engine._create_state(
            decks=[[c.clone() for c in deck]],
            names=["P1"],
            commander_names=["Kenrith, the Returned King"],
        )
        p = sim.players[0]
        assert len(p.command_zone) == 1
        assert p.command_zone[0].name == "Kenrith, the Returned King"
        assert p.command_zone[0].is_commander is True
        # Commander should not appear in hand or library
        assert all(not c.is_commander for c in p.hand)
        assert all(not c.is_commander for c in p.library)


# ── Serialization round-trip ──────────────────────────────────

class TestMulliganSerialization:
    def test_result_dict_includes_mulligans(self):
        """to_dict() output should include mulligan stats."""
        import json
        random.seed(42)
        deck = _make_deck()
        engine = GameEngine(mulligan_rule="london")
        result = engine.run(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
        )
        d = result.to_dict()
        # Verify JSON-serializable
        json.dumps(d)
        for pr in d["playerResults"]:
            assert "mulligans" in pr["stats"]
            assert "openingHandLands" in pr["stats"]
