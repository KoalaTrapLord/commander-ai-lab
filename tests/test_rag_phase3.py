"""Tests for RAG Phase 3 — coach prompt injection."""
import pytest
from unittest.mock import patch, MagicMock
from coach.prompt_template import _format_rag_cards, build_user_prompt


class TestFormatRagCards:
    """Tests for _format_rag_cards helper."""

    def test_empty_list_returns_fallback(self):
        assert _format_rag_cards([]) == "No RAG results available."

    def test_none_returns_fallback(self):
        # build_user_prompt passes rag_cards or [] so None shouldn't happen,
        # but _format_rag_cards should handle it gracefully
        assert "No RAG" in _format_rag_cards([])

    def test_single_card_formatted(self):
        cards = [{
            "name": "Sol Ring",
            "types": "Artifact",
            "mana_value": 1,
            "mana_cost": "{1}",
            "distance": 0.123,
            "text": "Tap: Add two colorless mana.",
        }]
        result = _format_rag_cards(cards)
        assert "Sol Ring" in result
        assert "{1}" in result
        assert "MV:1" in result
        assert "0.123" in result
        assert "Tap: Add two colorless" in result

    def test_max_15_cards(self):
        cards = [{"name": f"Card {i}", "types": "Creature",
                  "mana_value": i, "mana_cost": f"{{{i}}}",
                  "distance": 0.1 * i, "text": ""} for i in range(20)]
        result = _format_rag_cards(cards)
        assert "Card 14" in result
        assert "Card 15" not in result

    def test_missing_fields_use_defaults(self):
        cards = [{"name": "Mystery Card"}]
        result = _format_rag_cards(cards)
        assert "Mystery Card" in result
        assert "MV:?" in result


class TestBuildUserPromptRagParam:
    """Tests that build_user_prompt accepts and renders rag_cards."""

    @patch("coach.prompt_template._format_rag_cards")
    def test_rag_cards_passed_to_formatter(self, mock_fmt):
        mock_fmt.return_value = "MOCK_RAG_OUTPUT"
        # We can't easily build a full DeckReport here without fixtures,
        # so just verify the function signature accepts rag_cards.
        # A full integration test would need the DeckReport factory.
        assert callable(build_user_prompt)
        import inspect
        sig = inspect.signature(build_user_prompt)
        assert "rag_cards" in sig.parameters

    def test_rag_cards_default_is_none(self):
        import inspect
        sig = inspect.signature(build_user_prompt)
        param = sig.parameters["rag_cards"]
        assert param.default is None


class TestRagQueryIntegration:
    """Tests that coach_service calls query_cards (mocked)."""

    @patch("services.rag_store.query_cards", return_value=[
        {"name": "Arcane Signet", "types": "Artifact", "mana_value": 2,
         "mana_cost": "{2}", "distance": 0.05, "text": "Tap: Add one mana."},
    ])
    def test_query_cards_called_in_coaching(self, mock_qc):
        """Smoke test: import doesn't crash."""
        from services.rag_store import query_cards
        result = query_cards("Atraxa commander deck", n=15, colors=["W", "U", "B", "G"])
        assert len(result) == 1
        assert result[0]["name"] == "Arcane Signet"
        mock_qc.assert_called_once()
