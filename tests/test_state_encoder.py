"""
tests/test_state_encoder.py

Unit tests for ml/encoder/state_encoder.py

Coverage:
  - Global feature vector shape and value ranges
  - Step 4: total_power real value used at index 7 when present
  - Step 4: creatures*3 heuristic used at index 7 when total_power absent/zero
  - Step 4: lands real value used at index 13 when present
  - Step 4: creatures real value used at index 6 when present
  - Mana normalisation and clamping
  - Phase one-hot encoding (indices 9-12 per player block)
  - is_active_player binary (index 8)
  - Life normalisation (index 0)
  - Turn feature (index 28)
  - Full encode() output shape (6177,) and dtype
  - _empty_player() has all Step 4 keys
  - Legacy JSONL snapshot (no Step 4 keys) still encodes without error

No NPZ file required — MockCardEmbeddingIndex returns zero vectors.
"""
from __future__ import annotations

import numpy as np
import pytest

from ml.config.scope import STATE_DIMS, GAME_SCOPE


# ---------------------------------------------------------------------------
# Mock card embedding index (no file I/O)
# ---------------------------------------------------------------------------

class MockCardEmbeddingIndex:
    _loaded = True
    _zero_vec = np.zeros(STATE_DIMS.card_embedding_dim, dtype=np.float32)

    def get_embedding(self, name: str) -> np.ndarray:
        return self._zero_vec

    def mean_pool_zone(self, card_names) -> np.ndarray:
        return self._zero_vec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_encoder():
    from ml.encoder.state_encoder import StateEncoder
    return StateEncoder(MockCardEmbeddingIndex())


def _two_player_decision(**p0_overrides) -> dict:
    """Minimal two-player snapshot. p0_overrides patch player 0's fields."""
    p0 = {
        "seat": 0,
        "life": 40,
        "cmdr_dmg": 0,
        "mana": 0,
        "cmdr_tax": 0,
        "creatures": 0,
        "total_power": 0,
        "total_toughness": 0,
        "artifacts": 0,
        "enchantments": 0,
        "lands": 0,
        "hand": [],
        "battlefield": [],
        "graveyard": [],
        "command_zone": [],
    }
    p0.update(p0_overrides)
    p1 = {
        "seat": 1,
        "life": 40,
        "cmdr_dmg": 0,
        "mana": 0,
        "cmdr_tax": 0,
        "creatures": 0,
        "total_power": 0,
        "total_toughness": 0,
        "artifacts": 0,
        "enchantments": 0,
        "lands": 0,
        "hand": [],
        "battlefield": [],
        "graveyard": [],
        "command_zone": [],
    }
    return {
        "turn": 1,
        "phase": "main_1",
        "active_seat": 0,
        "players": [p0, p1],
        "archetype": "midrange",
    }


def _global_vec(**p0_overrides) -> np.ndarray:
    enc = _make_encoder()
    decision = _two_player_decision(**p0_overrides)
    players = decision["players"]
    return enc._encode_global(decision, players)


# Per-player block is 14 features; player 0 starts at index 0.
# Layout:
#   0  life
#   1  cmdr_dmg
#   2  mana
#   3  cmdr_tax
#   4  hand_size
#   5  graveyard_size
#   6  creatures
#   7  total_power
#   8  is_active
#   9-12 phase one-hot
#   13 lands
# Player 1 block starts at index 14.
# Index 28: turn.

P0_LIFE        = 0
P0_CMDR_DMG    = 1
P0_MANA        = 2
P0_CMDR_TAX    = 3
P0_HAND        = 4
P0_GRAVEYARD   = 5
P0_CREATURES   = 6
P0_TOTAL_POWER = 7
P0_IS_ACTIVE   = 8
P0_PHASE_START = 9   # indices 9-12
P0_LANDS       = 13
P1_LIFE        = 14
IDX_TURN       = 28


# ===========================================================================
# Tests
# ===========================================================================

class TestGlobalFeatureDimensions:
    def test_shape_is_29(self):
        vec = _global_vec()
        assert vec.shape == (29,), f"Expected (29,), got {vec.shape}"

    def test_all_values_in_0_1(self):
        vec = _global_vec(life=37, creatures=5, total_power=15, lands=7, mana=8)
        assert np.all(vec >= 0.0), f"Negative value: {vec[vec < 0]}"
        assert np.all(vec <= 1.0), f"Value > 1: {vec[vec > 1]}"

    def test_dtype_float32(self):
        vec = _global_vec()
        assert vec.dtype == np.float32


class TestTotalPowerRealValue:
    """Index 7 uses real total_power when p['total_power'] > 0."""

    def test_real_total_power_used(self):
        # 4 creatures, real power 19 — NOT 4*3=12
        vec = _global_vec(creatures=4, total_power=19)
        expected = min(19 / 100.0, 1.0)
        assert abs(vec[P0_TOTAL_POWER] - expected) < 1e-5, (
            f"Expected {expected:.4f} (real), got {vec[P0_TOTAL_POWER]:.4f}"
        )

    def test_real_power_differs_from_heuristic(self):
        # Confirm that 19 != 4*3=12, so the two paths produce different values
        vec_real = _global_vec(creatures=4, total_power=19)
        vec_heuristic = _global_vec(creatures=4, total_power=0)
        assert vec_real[P0_TOTAL_POWER] != vec_heuristic[P0_TOTAL_POWER]

    def test_large_power_clamped_to_1(self):
        vec = _global_vec(creatures=30, total_power=200)
        assert vec[P0_TOTAL_POWER] == pytest.approx(1.0)

    def test_zero_power_with_zero_creatures_is_zero(self):
        vec = _global_vec(creatures=0, total_power=0)
        assert vec[P0_TOTAL_POWER] == pytest.approx(0.0)

    def test_power_normalisation(self):
        for raw in [10, 50, 100]:
            vec = _global_vec(creatures=1, total_power=raw)
            expected = min(raw / 100.0, 1.0)
            assert abs(vec[P0_TOTAL_POWER] - expected) < 1e-5, (
                f"power={raw}: expected {expected}, got {vec[P0_TOTAL_POWER]}"
            )


class TestTotalPowerHeuristic:
    """Index 7 falls back to creatures*3 when total_power is absent or zero."""

    def test_heuristic_used_when_total_power_zero(self):
        vec = _global_vec(creatures=5, total_power=0)
        expected = min((5 * 3) / 100.0, 1.0)
        assert abs(vec[P0_TOTAL_POWER] - expected) < 1e-5, (
            f"Expected heuristic {expected:.4f}, got {vec[P0_TOTAL_POWER]:.4f}"
        )

    def test_heuristic_with_zero_creatures(self):
        vec = _global_vec(creatures=0, total_power=0)
        assert vec[P0_TOTAL_POWER] == pytest.approx(0.0)

    def test_heuristic_clamped(self):
        # 40 creatures * 3 = 120, clamped to 100 → 1.0
        vec = _global_vec(creatures=40, total_power=0)
        assert vec[P0_TOTAL_POWER] == pytest.approx(1.0)


class TestLandCount:
    def test_real_land_count_used(self):
        vec = _global_vec(lands=8)
        expected = min(8 / 15.0, 1.0)
        assert abs(vec[P0_LANDS] - expected) < 1e-5

    def test_zero_lands_default(self):
        vec = _global_vec(lands=0)
        assert vec[P0_LANDS] == pytest.approx(0.0)

    def test_lands_clamped_at_15(self):
        vec = _global_vec(lands=15)
        assert vec[P0_LANDS] == pytest.approx(1.0)

    def test_lands_over_15_clamped(self):
        vec = _global_vec(lands=30)
        assert vec[P0_LANDS] == pytest.approx(1.0)

    @pytest.mark.parametrize("n", [1, 4, 7, 10, 14])
    def test_land_normalisation(self, n):
        vec = _global_vec(lands=n)
        assert abs(vec[P0_LANDS] - n / 15.0) < 1e-5


class TestCreatureCount:
    def test_real_creature_count_at_index_6(self):
        vec = _global_vec(creatures=7)
        expected = min(7 / 30.0, 1.0)
        assert abs(vec[P0_CREATURES] - expected) < 1e-5

    def test_zero_creatures(self):
        vec = _global_vec(creatures=0)
        assert vec[P0_CREATURES] == pytest.approx(0.0)

    def test_creatures_clamped(self):
        vec = _global_vec(creatures=60)
        assert vec[P0_CREATURES] == pytest.approx(1.0)


class TestManaFeature:
    def test_mana_normalised(self):
        vec = _global_vec(mana=10)
        assert abs(vec[P0_MANA] - 10 / 20.0) < 1e-5

    def test_mana_clamped(self):
        vec = _global_vec(mana=100)
        assert vec[P0_MANA] == pytest.approx(1.0)

    def test_zero_mana(self):
        vec = _global_vec(mana=0)
        assert vec[P0_MANA] == pytest.approx(0.0)


class TestLifeNormalisation:
    def test_full_life(self):
        vec = _global_vec(life=40)
        assert abs(vec[P0_LIFE] - 1.0) < 1e-5

    def test_zero_life(self):
        vec = _global_vec(life=0)
        assert abs(vec[P0_LIFE] - 0.0) < 1e-5

    def test_partial_life(self):
        vec = _global_vec(life=20)
        assert abs(vec[P0_LIFE] - 0.5) < 1e-5

    def test_life_not_clamped_above_40(self):
        # Life gain can push above 40; encoder should still normalise
        vec = _global_vec(life=60)
        assert abs(vec[P0_LIFE] - 60 / 40.0) < 1e-5


class TestIsActivePlayer:
    def test_active_player_is_1(self):
        vec = _global_vec()   # p0 seat=0, active_seat=0
        assert vec[P0_IS_ACTIVE] == pytest.approx(1.0)

    def test_inactive_player_is_0(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["active_seat"] = 1   # p1 is active
        vec = enc._encode_global(decision, decision["players"])
        assert vec[P0_IS_ACTIVE] == pytest.approx(0.0)
        assert vec[P1_LIFE + (P0_IS_ACTIVE - P0_LIFE)] == pytest.approx(1.0)


class TestPhaseOneHot:
    @pytest.mark.parametrize("phase,expected_idx", [
        ("main_1", 0),
        ("combat",  1),
        ("main_2",  2),
        ("end",     3),
    ])
    def test_correct_bit_set(self, phase, expected_idx):
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["phase"] = phase
        vec = enc._encode_global(decision, decision["players"])
        phase_bits = vec[P0_PHASE_START:P0_PHASE_START + 4]
        assert phase_bits[expected_idx] == pytest.approx(1.0), (
            f"Phase '{phase}': bit {expected_idx} should be 1, got {phase_bits}"
        )

    def test_exactly_one_bit_set(self):
        for phase in ("main_1", "combat", "main_2", "end"):
            vec = _global_vec()
            enc = _make_encoder()
            decision = _two_player_decision()
            decision["phase"] = phase
            vec = enc._encode_global(decision, decision["players"])
            phase_bits = vec[P0_PHASE_START:P0_PHASE_START + 4]
            assert sum(phase_bits) == pytest.approx(1.0), (
                f"Phase '{phase}': expected exactly 1 hot, got {phase_bits}"
            )

    def test_unknown_phase_defaults_to_main1(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["phase"] = "UNKNOWN_PHASE"
        vec = enc._encode_global(decision, decision["players"])
        assert vec[P0_PHASE_START] == pytest.approx(1.0)


class TestTurnFeature:
    def test_turn_1_normalised(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["turn"] = 1
        vec = enc._encode_global(decision, decision["players"])
        assert abs(vec[IDX_TURN] - 1 / GAME_SCOPE.max_turns) < 1e-5

    def test_turn_clamped(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["turn"] = GAME_SCOPE.max_turns * 10
        vec = enc._encode_global(decision, decision["players"])
        assert vec[IDX_TURN] == pytest.approx(1.0)

    def test_turn_in_0_1(self):
        for t in [1, 5, 10, 20]:
            enc = _make_encoder()
            decision = _two_player_decision()
            decision["turn"] = t
            vec = enc._encode_global(decision, decision["players"])
            assert 0.0 <= vec[IDX_TURN] <= 1.0


class TestFullEncode:
    def test_output_shape_6177(self):
        enc = _make_encoder()
        decision = _two_player_decision(creatures=3, total_power=9, lands=5)
        vec = enc.encode(decision, playstyle="midrange")
        assert vec.shape == (STATE_DIMS.total_state_dim,), (
            f"Expected ({STATE_DIMS.total_state_dim},), got {vec.shape}"
        )

    def test_output_dtype_float32(self):
        enc = _make_encoder()
        vec = enc.encode(_two_player_decision(), playstyle="aggro")
        assert vec.dtype == np.float32

    def test_all_values_finite(self):
        enc = _make_encoder()
        vec = enc.encode(_two_player_decision(life=37, creatures=5, total_power=19,
                                               lands=7, mana=8), playstyle="control")
        assert np.all(np.isfinite(vec)), "Non-finite values in state vector"

    def test_different_playstyles_differ(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        v_aggro = enc.encode(decision, playstyle="aggro")
        v_control = enc.encode(decision, playstyle="control")
        # Playstyle one-hot is at the end — the two vectors must differ there
        assert not np.allclose(v_aggro[-4:], v_control[-4:])

    def test_real_power_vs_heuristic_differs_in_full_vector(self):
        """Confirm index 7 differs between real-power and heuristic snapshots."""
        enc = _make_encoder()
        v_real = enc.encode(_two_player_decision(creatures=4, total_power=19))
        v_heur = enc.encode(_two_player_decision(creatures=4, total_power=0))
        assert v_real[P0_TOTAL_POWER] != v_heur[P0_TOTAL_POWER]


class TestEmptyPlayer:
    def test_has_all_step4_keys(self):
        enc = _make_encoder()
        p = enc._empty_player(0)
        for key in ("total_power", "total_toughness", "artifacts", "enchantments", "lands"):
            assert key in p, f"Missing key '{key}' in _empty_player()"

    def test_step4_values_default_zero(self):
        enc = _make_encoder()
        p = enc._empty_player(0)
        for key in ("total_power", "total_toughness", "artifacts", "enchantments", "lands"):
            assert p[key] == 0, f"Expected 0 for '{key}', got {p[key]}"

    def test_encode_with_padded_player_succeeds(self):
        """Encoding a 1-player snapshot pads to 2 — should not raise."""
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["players"] = decision["players"][:1]  # strip to 1 player
        vec = enc.encode(decision)
        assert vec.shape == (STATE_DIMS.total_state_dim,)


class TestLegacySnapshot:
    """Old JSONL snapshots without Step 4 keys still encode without error."""

    def test_missing_total_power_key(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        for p in decision["players"]:
            p.pop("total_power", None)
        vec = enc.encode(decision)
        assert vec.shape == (STATE_DIMS.total_state_dim,)

    def test_missing_lands_key(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        for p in decision["players"]:
            p.pop("lands", None)
        vec = enc.encode(decision)
        assert vec[P0_LANDS] == pytest.approx(0.0)

    def test_missing_all_step4_keys(self):
        enc = _make_encoder()
        decision = _two_player_decision()
        for p in decision["players"]:
            for key in ("total_power", "total_toughness", "artifacts",
                        "enchantments", "lands"):
                p.pop(key, None)
        vec = enc.encode(decision)
        assert vec.shape == (STATE_DIMS.total_state_dim,)
        assert np.all(np.isfinite(vec))

    def test_heuristic_applied_for_legacy_total_power(self):
        """Legacy snapshot: creatures=6, no total_power → index 7 = 6*3/100 = 0.18"""
        enc = _make_encoder()
        decision = _two_player_decision()
        decision["players"][0]["creatures"] = 6
        decision["players"][0].pop("total_power", None)
        vec = enc.encode(decision)
        expected = min(6 * 3 / 100.0, 1.0)
        assert abs(vec[P0_TOTAL_POWER] - expected) < 1e-5
