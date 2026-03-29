"""
tests/test_policy_decide.py

Round-trip tests for POST /api/policy/decide (Issue #83 Steps 2 + 4).

Coverage:
  - Health endpoint sanity
  - Fast path: GameSession snapshot with state_vector → vector_source="precomputed"
  - Correct 6177-dim tensor reaches the mock model
  - All 8 MacroAction values are valid in the response
  - Fallback path: no state_vector → vector_source="encoder"
  - Fallback path: wrong-length state_vector → vector_source="encoder"
  - GameSession field name aliases accepted without 422
  - Step 4: real Forge board stats (creaturesOnField, landCount,
    totalPowerOnBoard, totalToughnessOnBoard, artifactsOnField,
    enchantmentsOnField) flow through without 422 and reach the encoder
  - Step 4: resolver fallbacks when Forge fields absent
  - 503 returned when model not loaded
  - /api/policy/stats tracks hit/fallback counters
  - Phase string variants (MAIN1, main_1, COMBAT) round-trip cleanly

All tests use a MockPolicyInferenceService — no real checkpoint required.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ml.config.scope import NUM_ACTIONS, IDX_TO_ACTION, STATE_DIMS

# ---------------------------------------------------------------------------
# Constants mirrored from routes/policy.py
# ---------------------------------------------------------------------------
EXPECTED_GLOBAL_DIM = 29
EXPECTED_STATE_DIM = STATE_DIMS.total_state_dim  # 6177
VALID_MACRO_ACTIONS = {a.value for a in IDX_TO_ACTION.values()}


# ---------------------------------------------------------------------------
# Mock policy service
# ---------------------------------------------------------------------------

class MockCardEmbeddingIndex:
    """Returns zero vectors for any card name — no NPZ file needed."""
    _loaded = True
    _zero_vec = np.zeros(STATE_DIMS.card_embedding_dim, dtype=np.float32)

    def get_embedding(self, name: str) -> np.ndarray:
        return self._zero_vec

    def mean_pool_zone(self, card_names: List[str]) -> np.ndarray:
        return self._zero_vec


class MockStateEncoder:
    """Real StateEncoder wired to MockCardEmbeddingIndex."""

    def __init__(self):
        from ml.encoder.state_encoder import StateEncoder
        self._inner = StateEncoder(MockCardEmbeddingIndex())
        self.dim = self._inner.dim

    def encode(self, decision: dict, playstyle: str = "midrange") -> np.ndarray:
        return self._inner.encode(decision, playstyle)

    def _encode_zones(self, players: list) -> np.ndarray:
        return self._inner._encode_zones(players)

    def _encode_playstyle(self, playstyle: str) -> np.ndarray:
        return self._inner._encode_playstyle(playstyle)


class MockPolicyInferenceService:
    """
    Stand-in for PolicyInferenceService.

    Records every tensor shape passed to the mock model so tests can
    assert on dimensions without loading a real checkpoint.

    Always returns action_index=0 (cast_creature) with confidence=0.9.
    """
    _loaded: bool = True
    device: str = "cpu"

    def __init__(self, loaded: bool = True):
        self._loaded = loaded
        self.encoder = MockStateEncoder()
        self.captured_shapes: List[tuple] = []
        self._build_mock_model()

    def _build_mock_model(self):
        captured = self.captured_shapes
        import torch

        def fake_forward(tensor):
            captured.append(tuple(tensor.shape))
            logits = torch.zeros(tensor.shape[0], NUM_ACTIONS)
            logits[0, 0] = 2.0
            return logits

        self.model = MagicMock(side_effect=fake_forward)

    def predict(self, decision_snapshot: Dict, playstyle: str = "midrange",
                temperature: float = 1.0, greedy: bool = False) -> Dict:
        if not self._loaded:
            return {"error": "Model not loaded", "detail": "mock"}
        import torch
        state_vec = self.encoder.encode(decision_snapshot, playstyle)
        state_tensor = torch.from_numpy(state_vec.astype(np.float32)).unsqueeze(0)
        self.captured_shapes.append(tuple(state_tensor.shape))
        return {
            "action": IDX_TO_ACTION[0].value,
            "action_index": 0,
            "confidence": 0.9,
            "probabilities": {IDX_TO_ACTION[i].value: (0.9 if i == 0 else 0.1 / (NUM_ACTIONS - 1))
                              for i in range(NUM_ACTIONS)},
            "inference_ms": 0.1,
        }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _make_app(loaded: bool = True):
    from routes.policy import register_policy_routes
    import routes.policy as policy_mod

    policy_mod._policy_service = None
    policy_mod._online_store = None
    policy_mod._session_stats = {
        "total_decisions": 0,
        "total_tuples_collected": 0,
        "total_rewards_submitted": 0,
        "games_completed": 0,
        "session_start": 0.0,
        "last_decision_ms": 0.0,
        "precomputed_vector_hits": 0,
        "encoder_fallbacks": 0,
    }

    app = FastAPI()
    svc = MockPolicyInferenceService(loaded=loaded)
    register_policy_routes(app, svc)
    return app, svc


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def _game_session_snapshot(
    state_vector: Optional[List[float]] = None,
    board_stats: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Builds a realistic GameSession.buildStateSnapshot() payload.

    board_stats: optional dict of Forge board stat overrides for players[0].
    e.g. {"creaturesOnField": 3, "landCount": 5, "totalPowerOnBoard": 9}
    """
    sv = state_vector if state_vector is not None else _valid_state_vector()

    p0: Dict[str, Any] = {
        "seat": 0,
        "name": "Human",
        "life": 37,
        "poison": 0,
        "commanderTax": 0,
        "handCount": 6,
        "hand": ["Doubling Season", "Deepglow Skate", "Sol Ring",
                 "Atraxa, Praetors' Voice", "Swamp", "Forest"],
        "battlefield": ["Sol Ring", "Atraxa, Praetors' Voice"],
        "graveyard": [],
        "commandZone": ["Atraxa, Praetors' Voice"],
        "manaPool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
        # Step 4: real Forge board stats
        "creaturesOnField": 1,
        "landCount": 4,
        "totalPowerOnBoard": 4,
        "totalToughnessOnBoard": 4,
        "artifactsOnField": 1,
        "enchantmentsOnField": 0,
        "manaAvailable": 4,
    }
    if board_stats:
        p0.update(board_stats)

    p1: Dict[str, Any] = {
        "seat": 1,
        "name": "AI-1",
        "life": 40,
        "poison": 0,
        "commanderTax": 2,
        "handCount": 7,
        "hand": [],
        "battlefield": ["Dragon's Hoard", "Savage Ventmaw"],
        "graveyard": ["Swords to Plowshares"],
        "commandZone": ["The Ur-Dragon"],
        "manaPool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
        "creaturesOnField": 1,
        "landCount": 5,
        "totalPowerOnBoard": 5,
        "totalToughnessOnBoard": 4,
        "artifactsOnField": 1,
        "enchantmentsOnField": 0,
        "manaAvailable": 5,
    }

    return {
        "schema": "1.1.0",
        "phase": "MAIN1",
        "turnNumber": 3,
        "activePlayer": 0,
        "priorityPlayer": 0,
        "awaitingInput": True,
        "players": [p0, p1],
        "stack": [],
        "legalActions": [
            {"type": "PASS_PRIORITY", "label": "Pass Priority"},
            {"type": "CAST_SPELL", "cardId": "Sol Ring", "label": "Cast Sol Ring"},
        ],
        "playstyle": "midrange",
        "greedy": False,
        "state_vector": sv,
        "state_vector_dim": len(sv),
    }


def _valid_state_vector() -> List[float]:
    """A plausible float[29] global scalar vector from buildStateVector(seat=0)."""
    sv = [0.0] * 29
    sv[0] = 37 / 40.0
    sv[3] = 0.0
    sv[4] = 6 / 15.0
    sv[6] = 2 / 30.0
    sv[7] = 2 / 100.0
    sv[8] = 1.0
    sv[9] = 1.0
    sv[14] = 40 / 40.0
    sv[17] = 2 / 10.0
    sv[18] = 7 / 15.0
    sv[20] = 2 / 30.0
    sv[28] = 3 / 25.0
    return sv


# ===========================================================================
# Tests
# ===========================================================================

class TestPolicyHealth:
    def test_health_model_loaded(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.get("/api/policy/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True
        assert data["status"] == "ok"
        assert data["model_loaded"] is True

    def test_health_model_not_loaded(self):
        app, _ = _make_app(loaded=False)
        client = TestClient(app)
        resp = client.get("/api/policy/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["status"] == "degraded"


class TestDecideFastPath:
    def test_precomputed_path_used(self):
        app, svc = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200, resp.text
        assert resp.json()["vector_source"] == "precomputed"

    def test_action_is_valid_macro_action(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200
        assert resp.json()["action"] in VALID_MACRO_ACTIONS

    def test_action_index_in_range(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200
        assert 0 <= resp.json()["action_index"] < NUM_ACTIONS

    def test_confidence_is_probability(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200
        assert 0.0 <= resp.json()["confidence"] <= 1.0

    def test_log_prob_is_negative(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200
        assert resp.json()["log_prob"] <= 0.0

    def test_tensor_shape_is_6177(self):
        app, svc = _make_app()
        client = TestClient(app)
        client.post("/api/policy/decide", json=_game_session_snapshot())
        assert len(svc.captured_shapes) > 0
        assert svc.captured_shapes[-1] == (1, EXPECTED_STATE_DIM), (
            f"Expected (1, {EXPECTED_STATE_DIM}), got {svc.captured_shapes[-1]}"
        )

    def test_probabilities_sum_to_one(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200
        probs = resp.json().get("probabilities", {})
        if probs:
            assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_inference_ms_is_positive(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 200
        assert resp.json()["inference_ms"] >= 0.0


class TestDecideFallbackPath:
    def test_fallback_when_no_state_vector(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap.pop("state_vector", None)
        snap.pop("state_vector_dim", None)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["vector_source"] == "encoder"

    def test_fallback_when_wrong_length_vector(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(state_vector=[0.5] * 10)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["vector_source"] == "encoder"

    def test_fallback_still_returns_valid_action(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap.pop("state_vector", None)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["action"] in VALID_MACRO_ACTIONS


class TestBoardStatsWiring:
    """Step 4: real Forge board stats flow through PlayerZoneState without 422."""

    def test_creatures_on_field_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"creaturesOnField": 5})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_land_count_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"landCount": 8})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_total_power_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"totalPowerOnBoard": 15})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_total_toughness_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"totalToughnessOnBoard": 12})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_artifacts_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"artifactsOnField": 3})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_enchantments_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"enchantmentsOnField": 2})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_mana_available_accepted(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={"manaAvailable": 7})
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_all_board_stats_together(self):
        """Full Forge board stat block round-trips cleanly."""
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={
            "creaturesOnField": 4,
            "landCount": 7,
            "totalPowerOnBoard": 16,
            "totalToughnessOnBoard": 14,
            "artifactsOnField": 2,
            "enchantmentsOnField": 1,
            "manaAvailable": 7,
        })
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text
        assert resp.json()["action"] in VALID_MACRO_ACTIONS

    def test_board_stats_reach_fallback_encoder(self):
        """Board stats survive through _build_encoder_snapshot on fallback path."""
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(board_stats={
            "creaturesOnField": 6,
            "landCount": 9,
            "totalPowerOnBoard": 24,
        })
        snap.pop("state_vector", None)  # force fallback encoder path
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text
        assert resp.json()["vector_source"] == "encoder"


class TestBoardStatsFallback:
    """Resolver fallbacks when Forge board stat fields are absent."""

    def test_creatures_inferred_from_battlefield_names(self):
        """When creaturesOnField=0, battlefield name count is the fallback."""
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(
            seat=0,
            battlefield=["Atraxa, Praetors' Voice", "Sol Ring"],
            creaturesOnField=0,
        )
        # Should fall back to len(battlefield names) = 2
        assert p.resolved_creatures() == 2

    def test_creatures_uses_real_value_when_present(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(
            seat=0,
            battlefield=["Atraxa, Praetors' Voice"],  # 1 name
            creaturesOnField=3,  # 3 actual creatures (tokens not in list)
        )
        assert p.resolved_creatures() == 3

    def test_lands_default_zero_when_absent(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(seat=0)
        assert p.resolved_lands() == 0

    def test_lands_uses_real_value(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(seat=0, landCount=6)
        assert p.resolved_lands() == 6

    def test_total_power_fallback_is_creatures_times_3(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(seat=0, creaturesOnField=4, totalPowerOnBoard=0)
        assert p.resolved_total_power() == 12  # 4 * 3

    def test_total_power_uses_real_value(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(seat=0, creaturesOnField=4, totalPowerOnBoard=19)
        assert p.resolved_total_power() == 19

    def test_mana_resolves_mana_available_alias(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(seat=0, manaAvailable=6)
        assert p.resolved_mana() == 6

    def test_mana_resolves_snake_case_alias(self):
        from routes.policy import PlayerZoneState
        p = PlayerZoneState(seat=0, mana_available=5)
        assert p.resolved_mana() == 5


class TestGameSessionAliases:
    def test_turnNumber_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["turnNumber"] = 5
        snap.pop("turn", None)
        assert client.post("/api/policy/decide", json=snap).status_code == 200

    def test_activePlayer_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["activePlayer"] = 0
        assert client.post("/api/policy/decide", json=snap).status_code == 200

    def test_commanderTax_in_player(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["players"][1]["commanderTax"] = 4
        assert client.post("/api/policy/decide", json=snap).status_code == 200

    def test_commandZone_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["players"][0]["commandZone"] = ["Atraxa, Praetors' Voice"]
        assert client.post("/api/policy/decide", json=snap).status_code == 200

    def test_legalActions_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["legalActions"] = snap.pop("legal_actions", snap.get("legalActions", []))
        assert client.post("/api/policy/decide", json=snap).status_code == 200

    def test_schema_110_accepted(self):
        """'schema' JSON key accepted via Field(alias='schema') on snapshot_schema."""
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["schema"] = "1.1.0"
        assert client.post("/api/policy/decide", json=snap).status_code == 200


class TestPhaseVariants:
    @pytest.mark.parametrize("phase", [
        "MAIN1", "main_1", "MAIN2", "main_2",
        "BEGIN_COMBAT", "combat", "END", "end", "CLEANUP",
    ])
    def test_phase_accepted(self, phase):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["phase"] = phase
        assert client.post("/api/policy/decide", json=snap).status_code == 200, phase


class TestDecideModelNotLoaded:
    def test_503_when_not_loaded(self):
        app, _ = _make_app(loaded=False)
        client = TestClient(app)
        resp = client.post("/api/policy/decide", json=_game_session_snapshot())
        assert resp.status_code == 503
        assert "not loaded" in resp.json()["detail"].lower()


class TestStats:
    def test_precomputed_hits_incremented(self):
        app, _ = _make_app()
        client = TestClient(app)
        for _ in range(3):
            client.post("/api/policy/decide", json=_game_session_snapshot())
        stats = client.get("/api/policy/stats").json()
        assert stats["precomputed_vector_hits"] == 3
        assert stats["total_decisions"] == 3

    def test_encoder_fallbacks_incremented(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap.pop("state_vector", None)
        for _ in range(2):
            client.post("/api/policy/decide", json=snap)
        stats = client.get("/api/policy/stats").json()
        assert stats["encoder_fallbacks"] == 2
        assert stats["precomputed_vector_hits"] == 0

    def test_mixed_hits_and_fallbacks(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap_pre = _game_session_snapshot()
        snap_enc = _game_session_snapshot()
        snap_enc.pop("state_vector", None)
        client.post("/api/policy/decide", json=snap_pre)
        client.post("/api/policy/decide", json=snap_enc)
        client.post("/api/policy/decide", json=snap_pre)
        stats = client.get("/api/policy/stats").json()
        assert stats["precomputed_vector_hits"] == 2
        assert stats["encoder_fallbacks"] == 1
        assert stats["total_decisions"] == 3

    def test_decisions_per_second_non_negative(self):
        app, _ = _make_app()
        client = TestClient(app)
        client.post("/api/policy/decide", json=_game_session_snapshot())
        stats = client.get("/api/policy/stats").json()
        assert stats["decisions_per_second"] >= 0.0


class TestStateVectorDimension:
    def test_global_block_length_is_29(self):
        assert len(_valid_state_vector()) == EXPECTED_GLOBAL_DIM

    def test_life_normalisation(self):
        sv = _valid_state_vector()
        assert 0.0 <= sv[0] <= 1.0

    def test_turn_normalisation(self):
        sv = _valid_state_vector()
        assert 0.0 <= sv[28] <= 1.0

    def test_is_active_player_binary(self):
        sv = _valid_state_vector()
        assert sv[8] in (0.0, 1.0)

    def test_phase_onehot_at_most_one_hot(self):
        sv = _valid_state_vector()
        assert sum(sv[9:13]) <= 1.0, f"Multiple phase bits: {sv[9:13]}"
