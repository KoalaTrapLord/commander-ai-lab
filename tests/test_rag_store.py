"""
tests/test_rag_store.py
=======================
Unit tests for services/rag_store.py.

All tests use mocked ChromaDB and Ollama dependencies — no external services
or network access required.
"""
from __future__ import annotations

import json
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

# ---------------------------------------------------------------------------
# Helpers to reset module-level singletons between tests
# ---------------------------------------------------------------------------

def _reset_rag_module():
    """Reset all module-level state in rag_store between tests."""
    import services.rag_store as rs
    rs._rag_ready = False
    rs._chroma_client = None
    rs._chroma_collection = None


@pytest.fixture(autouse=True)
def reset_rag_state():
    _reset_rag_module()
    yield
    _reset_rag_module()


# ---------------------------------------------------------------------------
# _build_document
# ---------------------------------------------------------------------------

class TestBuildDocument:
    def test_includes_all_four_fields(self):
        from services.rag_store import _build_document
        card = {
            "name": "Rampant Growth",
            "mana_cost": "{1}{G}",
            "type_line": "Sorcery",
            "oracle_text": "Search your library for a basic land card.",
        }
        doc = _build_document(card)
        assert "Rampant Growth" in doc
        assert "{1}{G}" in doc
        assert "Sorcery" in doc
        assert "Search your library" in doc

    def test_mana_cost_present_in_document(self):
        """Regression: mana_cost was previously missing (bug #128)."""
        from services.rag_store import _build_document
        card = {"name": "Lightning Bolt", "mana_cost": "{R}", "type_line": "Instant", "oracle_text": "Deal 3 damage."}
        doc = _build_document(card)
        assert "{R}" in doc

    def test_missing_mana_cost_skipped(self):
        from services.rag_store import _build_document
        card = {"name": "Plains", "mana_cost": "", "type_line": "Basic Land", "oracle_text": ""}
        doc = _build_document(card)
        # Should not produce " |  | " style empty fields
        assert "Plains" in doc
        assert doc.count(" |  | ") == 0

    def test_empty_card_returns_name_only(self):
        from services.rag_store import _build_document
        card = {"name": "Unnamed"}
        doc = _build_document(card)
        assert doc == "Unnamed"

    def test_pipe_delimiter_format(self):
        from services.rag_store import _build_document
        card = {"name": "A", "mana_cost": "B", "type_line": "C", "oracle_text": "D"}
        assert _build_document(card) == "A | B | C | D"


# ---------------------------------------------------------------------------
# _build_metadata
# ---------------------------------------------------------------------------

class TestBuildMetadata:
    def test_color_identity_json_string_parsed(self):
        from services.rag_store import _build_metadata
        card = {"name": "X", "color_identity": '["W", "U"]', "cmc": 3}
        meta = _build_metadata(card)
        assert meta["color_identity"] == "U,W"  # sorted

    def test_color_identity_list_input(self):
        from services.rag_store import _build_metadata
        card = {"name": "X", "color_identity": ["B", "G"], "cmc": 2}
        meta = _build_metadata(card)
        assert meta["color_identity"] == "B,G"

    def test_colorless_card(self):
        from services.rag_store import _build_metadata
        card = {"name": "Sol Ring", "color_identity": "[]", "cmc": 1}
        meta = _build_metadata(card)
        assert meta["color_identity"] == ""

    def test_malformed_color_identity_defaults_empty(self):
        from services.rag_store import _build_metadata
        card = {"name": "X", "color_identity": "not-json", "cmc": 0}
        meta = _build_metadata(card)
        assert meta["color_identity"] == ""

    def test_cmc_none_defaults_zero(self):
        from services.rag_store import _build_metadata
        card = {"name": "X", "cmc": None}
        meta = _build_metadata(card)
        assert meta["cmc"] == 0.0


# ---------------------------------------------------------------------------
# _read_build_meta / _write_build_meta
# ---------------------------------------------------------------------------

class TestBuildMeta:
    def test_write_then_read_roundtrip(self, tmp_path):
        import services.rag_store as rs
        original_dir = rs.RAG_CHROMA_DIR
        original_path = rs.BUILD_META_PATH
        try:
            rs.RAG_CHROMA_DIR = tmp_path
            rs.BUILD_META_PATH = tmp_path / "build_meta.json"
            rs._write_build_meta(card_count=12345)
            meta = rs._read_build_meta()
            assert meta["card_count"] == 12345
            assert abs(meta["built_at"] - time.time()) < 5
        finally:
            rs.RAG_CHROMA_DIR = original_dir
            rs.BUILD_META_PATH = original_path

    def test_read_missing_returns_empty_dict(self, tmp_path):
        import services.rag_store as rs
        original_path = rs.BUILD_META_PATH
        try:
            rs.BUILD_META_PATH = tmp_path / "nonexistent.json"
            assert rs._read_build_meta() == {}
        finally:
            rs.BUILD_META_PATH = original_path


# ---------------------------------------------------------------------------
# _collection_is_current
# ---------------------------------------------------------------------------

class TestCollectionIsCurrent:
    def _make_collection(self, count: int) -> MagicMock:
        col = MagicMock()
        col.count.return_value = count
        return col

    def test_empty_collection_returns_false(self):
        from services.rag_store import _collection_is_current
        col = self._make_collection(0)
        assert _collection_is_current(col, 1000) is False

    def test_current_collection_returns_true(self, tmp_path):
        import services.rag_store as rs
        original_path = rs.BUILD_META_PATH
        try:
            rs.BUILD_META_PATH = tmp_path / "build_meta.json"
            rs._write_build_meta(card_count=1000)
            col = self._make_collection(1000)
            assert rs._collection_is_current(col, 1000) is True
        finally:
            rs.BUILD_META_PATH = original_path

    def test_stale_by_age_returns_false(self, tmp_path):
        import services.rag_store as rs
        original_path = rs.BUILD_META_PATH
        try:
            rs.BUILD_META_PATH = tmp_path / "build_meta.json"
            # Write a built_at 15 days ago
            rs.BUILD_META_PATH.write_text(
                json.dumps({"built_at": time.time() - (15 * 86400), "card_count": 1000}),
                encoding="utf-8",
            )
            col = self._make_collection(1000)
            assert rs._collection_is_current(col, 1000) is False
        finally:
            rs.BUILD_META_PATH = original_path

    def test_count_mismatch_returns_false(self, tmp_path):
        import services.rag_store as rs
        original_path = rs.BUILD_META_PATH
        try:
            rs.BUILD_META_PATH = tmp_path / "build_meta.json"
            rs._write_build_meta(card_count=500)
            col = self._make_collection(500)   # chroma has 500
            assert rs._collection_is_current(col, 1000) is False  # bulk has 1000
        finally:
            rs.BUILD_META_PATH = original_path


# ---------------------------------------------------------------------------
# query_cards
# ---------------------------------------------------------------------------

class TestQueryCards:
    def test_returns_empty_when_not_ready(self):
        from services.rag_store import query_cards
        # _rag_ready is False (reset by fixture)
        result = query_cards("draw cards")
        assert result == []

    def test_color_filter_removes_off_color_cards(self):
        import services.rag_store as rs
        rs._rag_ready = True

        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["Wrath | {3}{W}{W} | Sorcery | Destroy all", "Dark Ritual | {B} | Instant | Add BBB"]],
            "metadatas": [[
                {"name": "Wrath", "type_line": "Sorcery", "color_identity": "W", "cmc": 5.0, "mana_cost": "{3}{W}{W}"},
                {"name": "Dark Ritual", "type_line": "Instant", "color_identity": "B", "cmc": 1.0, "mana_cost": "{B}"},
            ]],
            "distances": [[0.1, 0.2]],
        }
        rs._chroma_collection = mock_col

        results = rs.query_cards("mana acceleration", n_results=10, color_identity=["W"])
        names = [r["name"] for r in results]
        assert "Wrath" in names
        assert "Dark Ritual" not in names

    def test_distance_converted_to_score_in_route(self):
        """Verify distance field is present and in [0, 1] range."""
        import services.rag_store as rs
        rs._rag_ready = True

        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [["id1"]],
            "documents": [["Sol Ring | {1} | Artifact | Add two colorless mana."]],
            "metadatas": [[
                {"name": "Sol Ring", "type_line": "Artifact", "color_identity": "", "cmc": 1.0, "mana_cost": "{1}"},
            ]],
            "distances": [[0.15]],
        }
        rs._chroma_collection = mock_col

        results = rs.query_cards("mana rock", n_results=1)
        assert len(results) == 1
        assert results[0]["distance"] == 0.15
        assert results[0]["name"] == "Sol Ring"

    def test_empty_chroma_result_returns_empty_list(self):
        import services.rag_store as rs
        rs._rag_ready = True

        mock_col = MagicMock()
        mock_col.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        rs._chroma_collection = mock_col

        assert rs.query_cards("nothing") == []


# ---------------------------------------------------------------------------
# get_rag_stats
# ---------------------------------------------------------------------------

class TestGetRagStats:
    def test_returns_expected_keys(self):
        import services.rag_store as rs
        mock_col = MagicMock()
        mock_col.count.return_value = 42000
        rs._chroma_collection = mock_col

        stats = rs.get_rag_stats()
        for key in ["ready", "chroma_dir", "embedding_model", "ollama_url", "card_count", "built_at", "age_days"]:
            assert key in stats, f"Missing key: {key}"

    def test_card_count_from_collection(self):
        import services.rag_store as rs
        mock_col = MagicMock()
        mock_col.count.return_value = 55000
        rs._chroma_collection = mock_col

        stats = rs.get_rag_stats()
        assert stats["card_count"] == 55000

    def test_ready_false_when_not_initialized(self):
        from services.rag_store import get_rag_stats
        stats = get_rag_stats()
        assert stats["ready"] is False


# ---------------------------------------------------------------------------
# build_index (public API for POST /api/rag/build)
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_skips_rebuild_when_current(self, tmp_path):
        import services.rag_store as rs
        original_path = rs.BUILD_META_PATH
        original_dir = rs.RAG_CHROMA_DIR
        try:
            rs.BUILD_META_PATH = tmp_path / "build_meta.json"
            rs.RAG_CHROMA_DIR = tmp_path
            rs._write_build_meta(card_count=1000)

            mock_col = MagicMock()
            mock_col.count.return_value = 1000
            rs._chroma_collection = mock_col

            with patch("services.rag_store._get_collection", return_value=mock_col), \
                 patch("services.scryfall_bulk.get_stats", return_value={"card_count": 1000}):
                result = rs.build_index(force=False)

            assert result.get("skipped") is True
        finally:
            rs.BUILD_META_PATH = original_path
            rs.RAG_CHROMA_DIR = original_dir

    def test_force_triggers_rebuild(self, tmp_path):
        import services.rag_store as rs
        with patch("services.rag_store._build_collection_from_bulk") as mock_build:
            mock_build.return_value = {"indexed": 500, "failed": 0}
            result = rs.build_index(force=True, batch_size=250)
            mock_build.assert_called_once_with(batch_size=250)
            assert result["indexed"] == 500
            assert rs._rag_ready is True


# ---------------------------------------------------------------------------
# Failure tracking in _build_collection_from_bulk
# ---------------------------------------------------------------------------

class TestBuildCollectionFailureTracking:
    def test_high_failure_rate_raises_runtime_error(self, tmp_path):
        """If >1% of batches fail, a RuntimeError should be raised."""
        import services.rag_store as rs

        fake_rows = [
            {"name": f"Card {i}", "oracle_text": "text", "type_line": "Instant",
             "mana_cost": "{1}", "cmc": 1, "color_identity": "[]",
             "rarity": "common", "scryfall_id": f"id-{i}"}
            for i in range(200)
        ]

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [types.SimpleNamespace(**r) for r in fake_rows]
        mock_conn.execute.return_value = mock_cursor

        mock_collection = MagicMock()
        mock_collection.add.side_effect = Exception("Ollama timeout")

        mock_client = MagicMock()
        mock_client.create_collection.return_value = mock_collection

        original_dir = rs.RAG_CHROMA_DIR
        original_path = rs.BUILD_META_PATH
        try:
            rs.RAG_CHROMA_DIR = tmp_path
            rs.BUILD_META_PATH = tmp_path / "build_meta.json"
            with patch("services.scryfall_bulk.get_bulk_db", return_value=mock_conn), \
                 patch("services.rag_store._get_chromadb_client", return_value=mock_client), \
                 patch("services.rag_store._get_ollama_embedding_fn", return_value=MagicMock()), \
                 patch("services.rag_store._invalidate_collection_singleton"):
                with pytest.raises(RuntimeError, match="RAG build aborted"):
                    rs._build_collection_from_bulk(batch_size=50)
        finally:
            rs.RAG_CHROMA_DIR = original_dir
            rs.BUILD_META_PATH = original_path
