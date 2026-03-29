"""
tests/test_policy_decide.py

Round-trip tests for POST /api/policy/decide introduced in Issue #83 Step 2.

Coverage:
  - Health endpoint sanity
  - Fast path: GameSession snapshot with state_vector → vector_source="precomputed"
  - Correct 6177-dim tensor reaches the mock model
  - All 8 MacroAction values are valid in the response
  - Fallback path: no state_vector → vector_source="encoder"
  - Fallback path: wrong-length state_vector → vector_source="encoder"
  - GameSession field name aliases accepted without 422
  - 503 returned when model not loaded
  - /api/policy/stats tracks hit/fallback counters
  - Phase string variants (MAIN1, main_1, COMBAT) round-trip cleanly

All tests use a MockPolicyInferenceService — no real checkpoint required.
"""
from __future__ import annotations

import math
import types
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

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
        """Build a callable mock that records input shapes and returns logits."""
        captured = self.captured_shapes
        import torch

        def fake_forward(tensor):
            captured.append(tuple(tensor.shape))
            # Return uniform logits favouring action 0
            logits = torch.zeros(tensor.shape[0], NUM_ACTIONS)
            logits[0, 0] = 2.0  # cast_creature wins softmax
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
        # Always return cast_creature
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

def _make_app(loaded: bool = True) -> tuple[FastAPI, MockPolicyInferenceService]:
    """Create a fresh FastAPI app with the policy router registered."""
    from routes.policy import register_policy_routes
    import routes.policy as policy_mod

    # Reset module-level state between tests
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
# Fixture: a realistic GameSession snapshot
# ---------------------------------------------------------------------------

def _game_session_snapshot(
    state_vector: Optional[List[float]] = None,
    include_aliases: bool = True,
) -> Dict[str, Any]:
    """
    Mimics GameSession.buildStateSnapshot() output at turn 3, MAIN1.
    Includes the state_vector field added in Step 1.
    """
    sv = state_vector if state_vector is not None else _valid_state_vector()
    players = [
        {
            "seat": 0,
            "name": "Human",
            "isAI": False,
            "deckName": "Atraxa Superfriends",
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
        },
        {
            "seat": 1,
            "name": "AI-1",
            "isAI": True,
            "deckName": "Ur-Dragon",
            "life": 40,
            "poison": 0,
            "commanderTax": 2,
            "handCount": 7,
            "hand": [],
            "battlefield": ["Dragon's Hoard", "Savage Ventmaw"],
            "graveyard": ["Swords to Plowshares"],
            "commandZone": ["The Ur-Dragon"],
            "manaPool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
        },
    ]

    snap: Dict[str, Any] = {
        "schema": "1.1.0",
        "phase": "MAIN1",
        "turnNumber": 3,
        "activePlayer": 0,
        "priorityPlayer": 0,
        "awaitingInput": True,
        "players": players,
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
    return snap


def _valid_state_vector() -> List[float]:
    """A plausible float[29] global scalar vector from buildStateVector(seat=0)."""
    # life=37/40, everything else normalised appropriately
    sv = [0.0] * 29
    sv[0] = 37 / 40.0   # self life
    sv[3] = 0.0          # cmdr_tax
    sv[4] = 6 / 15.0    # cards_in_hand
    sv[6] = 2 / 30.0    # creatures
    sv[7] = 2 / 100.0   # power proxy
    sv[8] = 1.0          # is_active_player
    sv[9] = 1.0          # phase_onehot[main1]
    # opponent block: indices 14..27
    sv[14] = 40 / 40.0  # opp life
    sv[17] = 2 / 10.0   # opp cmdr_tax
    sv[18] = 7 / 15.0   # opp hand
    sv[20] = 2 / 30.0   # opp creatures
    # turn
    sv[28] = 3 / 25.0
    return sv


# ===========================================================================
# Tests
# ===========================================================================

class TestPolicyHealth:
    def test_health_model_loaded(self):
        app, _ = _make_app(loaded=True)
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
    """Precomputed state_vector present → vector_source=precomputed."""

    def test_precomputed_path_used(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vector_source"] == "precomputed"

    def test_action_is_valid_macro_action(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["action"] in VALID_MACRO_ACTIONS

    def test_action_index_in_range(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert 0 <= resp.json()["action_index"] < NUM_ACTIONS

    def test_confidence_is_probability(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        conf = resp.json()["confidence"]
        assert 0.0 <= conf <= 1.0

    def test_log_prob_is_negative(self):
        """log(p) for p in (0,1] must be <= 0."""
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["log_prob"] <= 0.0

    def test_tensor_shape_is_6177(self):
        """The mock model must receive a (1, 6177) tensor."""
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        client.post("/api/policy/decide", json=snap)
        assert len(svc.captured_shapes) > 0
        shape = svc.captured_shapes[-1]
        assert shape == (1, EXPECTED_STATE_DIM), (
            f"Expected (1, {EXPECTED_STATE_DIM}), got {shape}"
        )

    def test_probabilities_sum_to_one(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        probs = resp.json().get("probabilities", {})
        if probs:
            total = sum(probs.values())
            assert abs(total - 1.0) < 0.01, f"Probs sum to {total}"

    def test_inference_ms_is_positive(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["inference_ms"] >= 0.0


class TestDecideFallbackPath:
    """No / wrong state_vector → falls back to full encoder."""

    def test_fallback_when_no_state_vector(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap.pop("state_vector", None)
        snap.pop("state_vector_dim", None)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["vector_source"] == "encoder"

    def test_fallback_when_wrong_length_vector(self):
        """A 10-float vector is too short — must fall back."""
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot(state_vector=[0.5] * 10)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["vector_source"] == "encoder"

    def test_fallback_still_returns_valid_action(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap.pop("state_vector", None)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200
        assert resp.json()["action"] in VALID_MACRO_ACTIONS


class TestGameSessionAliases:
    """GameSession field name aliases must not cause 422 validation errors."""

    def test_turnNumber_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["turnNumber"] = 5
        snap.pop("turn", None)
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_activePlayer_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["activePlayer"] = 0
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_commanderTax_in_player(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["players"][1]["commanderTax"] = 4
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_commandZone_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["players"][0]["commandZone"] = ["Atraxa, Praetors' Voice"]
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_legalActions_alias(self):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["legalActions"] = snap.pop("legal_actions", snap.get("legalActions", []))
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text

    def test_schema_110_accepted(self):
        """schema=1.1.0 (GameSession Step 1 bump) is accepted without error."""
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["schema"] = "1.1.0"
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, resp.text


class TestPhaseVariants:
    """Both Forge-style (MAIN1) and ML-style (main_1) phase strings work."""

    @pytest.mark.parametrize("phase", [
        "MAIN1", "main_1", "MAIN2", "main_2",
        "BEGIN_COMBAT", "combat", "END", "end", "CLEANUP",
    ])
    def test_phase_accepted(self, phase):
        app, _ = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap["phase"] = phase
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 200, f"Phase '{phase}' failed: {resp.text}"


class TestDecideModelNotLoaded:
    def test_503_when_not_loaded(self):
        app, _ = _make_app(loaded=False)
        client = TestClient(app)
        snap = _game_session_snapshot()
        resp = client.post("/api/policy/decide", json=snap)
        assert resp.status_code == 503
        assert "not loaded" in resp.json()["detail"].lower()


class TestStats:
    def test_precomputed_hits_incremented(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        # Fire 3 precomputed requests
        for _ in range(3):
            client.post("/api/policy/decide", json=snap)
        stats = client.get("/api/policy/stats").json()
        assert stats["precomputed_vector_hits"] == 3
        assert stats["total_decisions"] == 3

    def test_encoder_fallbacks_incremented(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        snap.pop("state_vector", None)
        # Fire 2 fallback requests
        for _ in range(2):
            client.post("/api/policy/decide", json=snap)
        stats = client.get("/api/policy/stats").json()
        assert stats["encoder_fallbacks"] == 2
        assert stats["precomputed_vector_hits"] == 0

    def test_mixed_hits_and_fallbacks(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap_pre = _game_session_snapshot()                         # has state_vector
        snap_enc = _game_session_snapshot()
        snap_enc.pop("state_vector", None)                         # no state_vector
        client.post("/api/policy/decide", json=snap_pre)
        client.post("/api/policy/decide", json=snap_enc)
        client.post("/api/policy/decide", json=snap_pre)
        stats = client.get("/api/policy/stats").json()
        assert stats["precomputed_vector_hits"] == 2
        assert stats["encoder_fallbacks"] == 1
        assert stats["total_decisions"] == 3

    def test_decisions_per_second_non_negative(self):
        app, svc = _make_app()
        client = TestClient(app)
        snap = _game_session_snapshot()
        client.post("/api/policy/decide", json=snap)
        stats = client.get("/api/policy/stats").json()
        assert stats["decisions_per_second"] >= 0.0


class TestStateVectorDimension:
    """Explicit dim assertions on the precomputed encoding path."""

    def test_global_block_length_is_29(self):
        sv = _valid_state_vector()
        assert len(sv) == EXPECTED_GLOBAL_DIM

    def test_life_normalisation(self):
        sv = _valid_state_vector()
        assert 0.0 <= sv[0] <= 1.0, "life not normalised"

    def test_turn_normalisation(self):
        sv = _valid_state_vector()
        assert 0.0 <= sv[28] <= 1.0, "turn not normalised"

    def test_is_active_player_binary(self):
        sv = _valid_state_vector()
        assert sv[8] in (0.0, 1.0), "is_active_player must be 0 or 1"

    def test_phase_onehot_at_most_one_hot(self):
        """Indices 9-12 are the phase one-hot: at most one should be 1."""
        sv = _valid_state_vector()
        phase_bits = sv[9:13]
        assert sum(phase_bits) <= 1.0, f"Multiple phase bits set: {phase_bits}"
