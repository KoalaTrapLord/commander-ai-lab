"""Tests for DeckBuilderAdapter — the bridge between Ollama pipeline and legacy API."""
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from src.commander_ai_lab.deck_builder.adapter import DeckBuilderAdapter
from src.commander_ai_lab.deck_builder.core.models import (
    BuildResult,
    CardEntry,
    CommanderDeck,
    DeckRatios,
)


def _fake_build_result():
    """Return a minimal BuildResult for mocking build_deck."""
    cmdr = CardEntry(name="Atraxa", color_identity=["W", "U", "B", "G"])
    basics = ["Plains", "Island", "Swamp", "Mountain", "Forest"]
    cards = [
        CardEntry(name=basics[i % 5], quantity=1, category="lands", color_identity={"W", "U", "B", "G"})
        for i in range(99)
    ]
    deck = CommanderDeck(commander=cmdr, cards=cards)
    return BuildResult(
        deck=deck,
        warnings=["test warning"],
        sources_consulted=["scryfall", "edhrec"],
        build_time_seconds=1.23,
    )


class TestDeckBuilderAdapter:
    def test_init_defaults(self):
        adapter = DeckBuilderAdapter()
        assert adapter.model == "gpt-oss:20b"
        assert adapter.db_conn_factory is None

    @patch("src.commander_ai_lab.deck_builder.adapter.build_deck")
    def test_generate_deck_returns_expected_shape(self, mock_build):
        mock_build.return_value = _fake_build_result()
        adapter = DeckBuilderAdapter()
        result = adapter.generate_deck("Atraxa", strategy="superfriends")

        assert "commander" in result
        assert result["commander"]["name"] == "Atraxa"
        assert "cards" in result
        assert "stats" in result
        assert result["model"] == "gpt-oss:20b"
        assert result["build_time_seconds"] == 1.23
        assert "scryfall" in result["reasoning"]["sources"]

    @patch("src.commander_ai_lab.deck_builder.adapter.build_deck")
    def test_generate_deck_fills_to_100(self, mock_build):
        mock_build.return_value = _fake_build_result()
        adapter = DeckBuilderAdapter()
        result = adapter.generate_deck("Atraxa")
        total = sum(c.get("count", 1) for c in result["cards"])
        assert total == 100  # 99 cards + commander fills to 100

    @patch("src.commander_ai_lab.deck_builder.adapter.build_deck")
    def test_ownership_without_db(self, mock_build):
        mock_build.return_value = _fake_build_result()
        adapter = DeckBuilderAdapter(db_conn_factory=None)
        result = adapter.generate_deck("Atraxa")
        for card in result["cards"]:
            assert card["owned"] is False
            assert card["from_collection"] is False


class TestRunSubstitution:
    def test_no_op_returns_namespace(self):
        adapter = DeckBuilderAdapter()
        cards = [
            {"name": "Sol Ring", "owned": True},
            {"name": "Mana Crypt", "owned": False},
        ]
        result = adapter.run_substitution(cards, commander="Atraxa")
        assert isinstance(result, SimpleNamespace)
        assert result.owned_count == 1
        assert result.substituted_count == 0
        assert result.missing_count == 1


class TestHelpers:
    def test_fill_basic_lands_adds_missing(self):
        cards = [{"name": "Sol Ring", "count": 1, "category": "ramp"}]
        filled = DeckBuilderAdapter._fill_basic_lands(cards, ["W", "U"], target_total=5)
        total = sum(c.get("count", 1) for c in filled)
        assert total == 5

    def test_fill_basic_lands_no_excess(self):
        cards = [{"name": f"Card{i}", "count": 1} for i in range(100)]
        filled = DeckBuilderAdapter._fill_basic_lands(cards, ["W"], target_total=100)
        assert len(filled) == 100

    def test_compute_stats(self):
        cards = [
            {"name": "Sol Ring", "count": 1, "category": "ramp", "cmc": 1},
            {"name": "Plains", "count": 36, "category": "lands", "cmc": 0},
        ]
        stats = DeckBuilderAdapter._compute_stats(cards)
        assert stats["total_cards"] == 37
        assert stats["land_count"] == 36
        assert stats["average_cmc"] == 1.0
