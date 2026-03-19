"""Tests for the Pydantic models used by the Ollama deck builder."""
import pytest
from pydantic import ValidationError

from src.commander_ai_lab.deck_builder.core.models import (
    BuildRequest,
    BuildResult,
    CardEntry,
    Color,
    CommanderDeck,
    DeckRatios,
    WUBRG,
)


# ── Color enum ───────────────────────────────────────────────────

class TestColor:
    def test_wubrg_set_has_five_colors(self):
        assert WUBRG == {"W", "U", "B", "R", "G"}

    def test_enum_values(self):
        assert Color.WHITE.value == "W"
        assert Color.BLUE.value == "U"
        assert Color.GREEN.value == "G"


# ── CardEntry ────────────────────────────────────────────────────

class TestCardEntry:
    def test_minimal_card(self):
        card = CardEntry(name="Sol Ring")
        assert card.name == "Sol Ring"
        assert card.quantity == 1
        assert card.category == "uncategorized"
        assert card.cmc == 0.0

    def test_color_identity_from_string(self):
        card = CardEntry(name="Counterspell", color_identity="UB")
        assert card.color_identity == {"U", "B"}

    def test_color_identity_from_list(self):
        card = CardEntry(name="Swords to Plowshares", color_identity=["W"])
        assert card.color_identity == {"W"}

    def test_invalid_colors_stripped(self):
        card = CardEntry(name="Test", color_identity=["W", "X", "Z"])
        assert card.color_identity == {"W"}

    def test_full_card(self):
        card = CardEntry(
            name="Rhystic Study",
            quantity=1,
            category="card_draw",
            color_identity=["U"],
            mana_cost="{2}{U}",
            cmc=3.0,
            type_line="Enchantment",
            scryfall_id="abc-123",
            edhrec_rank=5,
            source="edhrec",
        )
        assert card.source == "edhrec"
        assert card.edhrec_rank == 5


# ── DeckRatios ───────────────────────────────────────────────────

class TestDeckRatios:
    def test_default_sums_to_99(self):
        ratios = DeckRatios()
        total = (
            ratios.lands + ratios.ramp + ratios.card_draw
            + ratios.removal + ratios.protection + ratios.synergy
            + ratios.wincon + ratios.uncategorized
        )
        assert total == 99

    def test_bad_total_raises(self):
        with pytest.raises(ValidationError, match="must sum to 99"):
            DeckRatios(lands=50)

    def test_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            DeckRatios(lands=5)  # ge=30


# ── CommanderDeck ────────────────────────────────────────────────

def _make_99_cards(ci=None):
    """Helper: build a valid 99-card list of basic lands."""
    ci = ci or set()
    cards = []
    basics = ["Plains", "Island", "Swamp", "Mountain", "Forest"]
    for i in range(99):
        cards.append(CardEntry(
            name=basics[i % 5],
            quantity=1,
            category="lands",
            color_identity=ci,
        ))
    return cards


class TestCommanderDeck:
    def test_valid_deck(self):
        cmdr = CardEntry(name="Atraxa", color_identity=["W", "U", "B", "G"])
        deck = CommanderDeck(
            commander=cmdr,
            cards=_make_99_cards({"W", "U", "B", "G"}),
        )
        assert len(deck.cards) == 99

    def test_wrong_card_count_raises(self):
        cmdr = CardEntry(name="Atraxa", color_identity=["W", "U", "B", "G"])
        with pytest.raises(ValidationError, match="exactly 99 cards"):
            CommanderDeck(commander=cmdr, cards=_make_99_cards()[:50])

    def test_singleton_violation_raises(self):
        cmdr = CardEntry(name="Atraxa", color_identity=list(WUBRG))
        cards = _make_99_cards(WUBRG)[:97]
        cards.append(CardEntry(name="Sol Ring", color_identity=set()))
        cards.append(CardEntry(name="Sol Ring", color_identity=set()))
        with pytest.raises(ValidationError, match="Singleton violation"):
            CommanderDeck(commander=cmdr, cards=cards)

    def test_color_identity_violation_raises(self):
        cmdr = CardEntry(name="Mono White", color_identity=["W"])
        cards = _make_99_cards({"W"})[:98]
        cards.append(CardEntry(name="Counterspell", color_identity=["U"]))
        with pytest.raises(ValidationError, match="outside commander identity"):
            CommanderDeck(commander=cmdr, cards=cards)


# ── BuildRequest / BuildResult ───────────────────────────────────

class TestBuildRequest:
    def test_minimal(self):
        req = BuildRequest(commander_name="Atraxa")
        assert req.commander_name == "Atraxa"
        assert req.collection_only is False
        assert req.budget_limit is None

    def test_with_strategy(self):
        req = BuildRequest(
            commander_name="Atraxa",
            strategy_notes="superfriends planeswalker tribal",
        )
        assert "superfriends" in req.strategy_notes


class TestBuildResult:
    def test_minimal(self):
        cmdr = CardEntry(name="Atraxa", color_identity=["W", "U", "B", "G"])
        deck = CommanderDeck(
            commander=cmdr,
            cards=_make_99_cards({"W", "U", "B", "G"}),
        )
        result = BuildResult(deck=deck)
        assert result.build_time_seconds == 0.0
        assert result.warnings == []
        assert result.sources_consulted == []
