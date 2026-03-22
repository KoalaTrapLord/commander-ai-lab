"""
Phase 5 Architecture Follow-Up — Unit Tests
============================================
Tests for the three approved decisions:
  1. Zone embedding boundary is explicit (docs + code + assertion)
  2. SQLite WAL-backed online learning store
  3. Forge-only default weights + mixed-mode presets

Run with: pytest tests/test_phase5_followup.py -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import numpy as np
import pytest


# ====================================================================
# Decision 1: Zone Embedding Boundary
# ====================================================================

class TestZoneEmbeddingBoundary:
    """Verify that the zone embedding contract is explicit and enforced."""

    def test_state_dims_total_zone_dim(self):
        from ml.config.scope import STATE_DIMS
        # 4 zones × 2 players × 768 = 6144
        assert STATE_DIMS.total_zone_dim == 4 * 2 * 768 == 6144

    def test_state_dims_total_state_dim(self):
        from ml.config.scope import STATE_DIMS
        # 29 global + 6144 zone + 4 playstyle = 6177
        assert STATE_DIMS.total_state_dim == 6177

    def test_zone_pool_dim_matches_card_embedding_dim(self):
        from ml.config.scope import STATE_DIMS
        # Zone pool output is same size as card embedding input
        assert STATE_DIMS.zone_pool_dim == STATE_DIMS.card_embedding_dim == 768

    def test_empty_zone_produces_zero_vector(self):
        """Empty zone must produce a zero vector of exactly zone_pool_dim."""
        from ml.config.scope import STATE_DIMS
        from ml.encoder.state_encoder import CardEmbeddingIndex

        idx = CardEmbeddingIndex()
        # Even without loading, mean_pool_zone returns a zero vec
        vec = idx.mean_pool_zone([])
        assert vec.shape == (STATE_DIMS.zone_pool_dim,)
        assert np.all(vec == 0.0)

    def test_encode_zones_shape_with_empty_players(self):
        """_encode_zones must always return exactly total_zone_dim floats."""
        from ml.config.scope import STATE_DIMS
        from ml.encoder.state_encoder import CardEmbeddingIndex, StateEncoder

        idx = CardEmbeddingIndex()
        enc = StateEncoder(idx)

        # Two players with empty zones
        players = [
            {"hand": [], "battlefield": [], "graveyard": [], "command_zone": []},
            {"hand": [], "battlefield": [], "graveyard": [], "command_zone": []},
        ]
        zone_vec = enc._encode_zones(players)
        assert zone_vec.shape == (STATE_DIMS.total_zone_dim,)
        # All zeros because all zones are empty
        assert np.all(zone_vec == 0.0)

    def test_full_encode_shape(self):
        """Full state vector must be exactly total_state_dim."""
        from ml.config.scope import STATE_DIMS
        from ml.encoder.state_encoder import CardEmbeddingIndex, StateEncoder

        idx = CardEmbeddingIndex()
        enc = StateEncoder(idx)

        decision = {
            "turn": 3,
            "phase": "main_1",
            "active_seat": 0,
            "players": [
                {
                    "seat": 0, "life": 40, "cmdr_dmg": 0, "mana": 4,
                    "cmdr_tax": 0, "creatures": 2, "lands": 4,
                    "hand": ["Island", "Counterspell"],
                    "battlefield": ["Tundra"],
                    "graveyard": [],
                    "command_zone": [],
                },
                {
                    "seat": 1, "life": 38, "cmdr_dmg": 0, "mana": 3,
                    "cmdr_tax": 0, "creatures": 1, "lands": 3,
                    "hand": [],
                    "battlefield": [],
                    "graveyard": [],
                    "command_zone": [],
                },
            ],
        }
        state = enc.encode(decision, playstyle="control")
        assert state.shape == (STATE_DIMS.total_state_dim,)
        assert state.dtype == np.float32

    def test_boundary_docstring_present(self):
        """StateDimensions must document the zone embedding boundary."""
        from ml.config.scope import StateDimensions
        assert "zone embedding boundary" in StateDimensions.__doc__.lower()


# ====================================================================
# Decision 2: SQLite WAL Online Learning Store
# ====================================================================

class TestOnlineLearningStore:
    """Verify the SQLite WAL-backed online learning store."""

    @pytest.fixture
    def store(self, tmp_path):
        from ml.serving.online_learning_store import OnlineLearningStore
        db_path = str(tmp_path / "test_online.db")
        s = OnlineLearningStore(db_path=db_path)
        s.init_db()
        return s

    def test_init_creates_db(self, store):
        assert os.path.exists(store.db_path)

    def test_wal_mode_enabled(self, store):
        conn = store._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_record_and_fetch(self, store):
        snapshot = {"turn": 1, "phase": "main_1", "players": []}
        row_id = store.record_decision(
            snapshot=snapshot,
            action_idx=3,
            confidence=0.85,
            playstyle="control",
            temperature=0.8,
            greedy=False,
        )
        assert row_id >= 1

        decisions = store.fetch_decisions()
        assert len(decisions) == 1
        d = decisions[0]
        assert d["action_idx"] == 3
        assert d["confidence"] == pytest.approx(0.85)
        assert d["playstyle"] == "control"
        assert d["temperature"] == pytest.approx(0.8)
        assert d["greedy"] == 0
        assert d["snapshot"]["turn"] == 1

    def test_count(self, store):
        assert store.count() == 0
        store.record_decision({"t": 1}, 0, 0.5)
        store.record_decision({"t": 2}, 1, 0.6)
        assert store.count() == 2
        assert store.count(only_unexported=True) == 2

    def test_mark_exported(self, store):
        store.record_decision({"t": 1}, 0, 0.5)
        store.record_decision({"t": 2}, 1, 0.6)
        store.record_decision({"t": 3}, 2, 0.7)

        # Mark first two as exported
        updated = store.mark_exported(up_to_rowid=2)
        assert updated == 2
        assert store.count(only_unexported=True) == 1

        # Fetch only unexported
        remaining = store.fetch_decisions(only_unexported=True)
        assert len(remaining) == 1
        assert remaining[0]["action_idx"] == 2

    def test_fetch_since_rowid(self, store):
        ids = []
        for i in range(5):
            ids.append(store.record_decision({"t": i}, i, 0.5))

        # Fetch only rows after id 3
        results = store.fetch_decisions(since_rowid=ids[2], only_unexported=False)
        assert len(results) == 2  # ids[3] and ids[4]
        assert results[0]["action_idx"] == 3

    def test_fetch_limit(self, store):
        for i in range(10):
            store.record_decision({"t": i}, i % 8, 0.5)
        results = store.fetch_decisions(limit=3)
        assert len(results) == 3

    def test_close_and_reopen(self, store):
        store.record_decision({"t": 1}, 0, 0.5)
        store.close()
        # Re-open by calling _get_conn again
        assert store.count() == 1

    def test_snapshot_stored_as_compact_json(self, store):
        """Snapshots should be stored as compact JSON (no extra whitespace)."""
        store.record_decision({"key": "value", "num": 42}, 0, 0.5)
        conn = store._get_conn()
        raw = conn.execute(
            "SELECT snapshot FROM online_decisions WHERE id=1"
        ).fetchone()[0]
        # Compact JSON has no spaces after separators
        assert " " not in raw
        assert json.loads(raw) == {"key": "value", "num": 42}


# ====================================================================
# Decision 3: Forge-Only Defaults + Mixed-Mode Presets
# ====================================================================

class TestForgeOnlyDefaults:
    """Verify default weights are Forge-only (ppo_weight=0.0)."""

    def test_distillation_defaults_forge_only(self):
        from ml.config.scope import DISTILLATION_DEFAULTS
        assert DISTILLATION_DEFAULTS.forge_weight == 1.0
        assert DISTILLATION_DEFAULTS.ppo_weight == 0.0

    def test_distillation_config_forge_only(self):
        from ml.training.distillation_loop import DistillationConfig
        cfg = DistillationConfig()
        assert cfg.forge_weight == 1.0
        assert cfg.ppo_weight == 0.0

    def test_dataset_config_forge_only(self):
        from ml.data.dataset_builder import DatasetConfig
        cfg = DatasetConfig()
        assert cfg.source_weights["forge"] == 1.0
        assert cfg.source_weights["ppo"] == 0.0


class TestMixedModePresets:
    """Verify mixed-mode weight presets exist and are correct."""

    def test_presets_dict_exists(self):
        from ml.config.scope import MIXED_MODE_PRESETS
        assert isinstance(MIXED_MODE_PRESETS, dict)
        assert len(MIXED_MODE_PRESETS) == 3

    def test_forge_only_preset(self):
        from ml.config.scope import MIXED_MODE_PRESETS
        p = MIXED_MODE_PRESETS["forge_only"]
        assert p["forge_weight"] == 1.0
        assert p["ppo_weight"] == 0.0

    def test_forge_90_10_preset(self):
        from ml.config.scope import MIXED_MODE_PRESETS
        p = MIXED_MODE_PRESETS["forge_90_10"]
        assert p["forge_weight"] == 1.0
        # ppo_weight ~0.11 gives approximately 10% PPO in the mix
        assert 0.1 <= p["ppo_weight"] <= 0.15

    def test_forge_80_20_preset(self):
        from ml.config.scope import MIXED_MODE_PRESETS
        p = MIXED_MODE_PRESETS["forge_80_20"]
        assert p["forge_weight"] == 1.0
        # ppo_weight ~0.25 gives approximately 20% PPO
        assert 0.2 <= p["ppo_weight"] <= 0.3

    def test_get_preset_weights_valid(self):
        from ml.config.scope import get_preset_weights
        w = get_preset_weights("forge_90_10")
        assert "forge_weight" in w
        assert "ppo_weight" in w

    def test_get_preset_weights_returns_copy(self):
        """get_preset_weights must return a copy, not the original dict."""
        from ml.config.scope import get_preset_weights, MIXED_MODE_PRESETS
        w = get_preset_weights("forge_only")
        w["forge_weight"] = 999
        assert MIXED_MODE_PRESETS["forge_only"]["forge_weight"] == 1.0

    def test_get_preset_weights_invalid(self):
        from ml.config.scope import get_preset_weights
        with pytest.raises(KeyError, match="Unknown preset"):
            get_preset_weights("nonexistent")

    def test_all_presets_have_both_keys(self):
        from ml.config.scope import MIXED_MODE_PRESETS
        for name, preset in MIXED_MODE_PRESETS.items():
            assert "forge_weight" in preset, f"Preset '{name}' missing forge_weight"
            assert "ppo_weight" in preset, f"Preset '{name}' missing ppo_weight"
