"""Commander AI Lab — Policy Decision Routes (Phase 2)
════════════════════════════════════════════════════════
Live Forge ↔ policy server IPC endpoints for online training.
These endpoints are purpose-built for the real-time decision loop
where Forge's Java side calls the Python policy server at each
game decision point.

Endpoints:
    POST /api/policy/decide   — Accept full Forge game state, return action + log_prob + value
    POST /api/policy/collect   — Accept batch of (state, action, reward) tuples
    POST /api/policy/reward    — Submit end-of-game reward
    GET  /api/policy/health    — Readiness check for the live IPC loop
    GET  /api/policy/stats     — Online learning session statistics

Refs: Issue #83 Phase 2.2, Step 4 (real Forge board stats)
"""
import logging
import math
import time
from typing import Dict, List, Optional

import numpy as np

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Unique logger name so log lines are attributable to this module specifically
logger = logging.getLogger("routes.policy.decide")

router = APIRouter(prefix="/api/policy", tags=["policy"])

# Expected length of the precomputed global scalar block from GameSession
_EXPECTED_STATE_VECTOR_LEN = 29


# ================================================================
# Request / Response Models
# ================================================================

class PlayerZoneState(BaseModel):
    """Per-player zone state from Forge / GameSession.

    Fields match DecisionSnapshot.PlayerSnapshot (Java) so the same JSON
    deserialises on both the live IPC path and the JSONL training path.
    All board-stat fields are optional with a default of 0 so older
    snapshots (pre-Step-4) continue to deserialise without errors.
    """
    seat: int = 0
    name: str = ""
    life: int = 40
    poison: int = 0
    # GameSession sends cmdr_dmg as a dict keyed by opponent seat str
    cmdr_dmg: Dict[str, int] = Field(default_factory=dict)

    # Commander tax / casts
    cmdr_tax: int = 0
    commanderTax: int = 0       # GameSession alias for cmdr_tax
    commanderCasts: int = 0

    # Mana
    mana_available: int = 0
    manaAvailable: int = 0      # DecisionSnapshot alias
    mana_pool: Dict[str, int] = Field(default_factory=dict)

    # Full zone contents
    hand: List[str] = Field(default_factory=list)
    hand_count: int = 0
    handCount: int = 0          # GameSession alias for hand_count
    battlefield: List = Field(default_factory=list)   # list[str] or list[dict]
    graveyard: List[str] = Field(default_factory=list)
    exile: List[str] = Field(default_factory=list)
    command_zone: List[str] = Field(default_factory=list)
    commandZone: List[str] = Field(default_factory=list)  # GameSession alias
    library_count: int = 0

    # ── Real Forge board stats (DecisionSnapshot.PlayerSnapshot) ──────────
    # These are pre-computed by Forge/DecisionExtractor and are more accurate
    # than inferring them from zone card-name lists.
    creaturesOnField: int = 0       # actual creature count on battlefield
    totalPowerOnBoard: int = 0      # sum of power of all creatures
    totalToughnessOnBoard: int = 0  # sum of toughness of all creatures
    artifactsOnField: int = 0       # artifact permanents
    enchantmentsOnField: int = 0    # enchantment permanents
    landCount: int = 0              # lands on battlefield

    # Legacy snake_case aliases (JSONL training path uses these)
    creatures_on_field: int = 0
    total_power_on_board: int = 0
    total_toughness_on_board: int = 0
    artifacts_on_field: int = 0
    enchantments_on_field: int = 0
    land_count: int = 0

    # ── Resolver helpers ──────────────────────────────────────────────────

    def resolved_hand(self) -> List[str]:
        return self.hand if self.hand else []

    def resolved_hand_count(self) -> int:
        if self.hand:
            return len(self.hand)
        return self.handCount or self.hand_count

    def resolved_cmdr_tax(self) -> int:
        return self.cmdr_tax or self.commanderTax

    def resolved_command_zone(self) -> List[str]:
        return self.command_zone if self.command_zone else self.commandZone

    def resolved_battlefield_names(self) -> List[str]:
        names = []
        for entry in self.battlefield:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                names.append(entry.get("name", entry.get("id", "unknown")))
        return names

    def resolved_mana(self) -> int:
        """Return mana from whichever alias is populated."""
        return self.manaAvailable or self.mana_available

    def resolved_creatures(self) -> int:
        """Real creature count from Forge; falls back to battlefield name count."""
        real = self.creaturesOnField or self.creatures_on_field
        if real > 0:
            return real
        # Fallback: count non-land names on battlefield (rough)
        return len(self.resolved_battlefield_names())

    def resolved_lands(self) -> int:
        """Real land count from Forge; falls back to 0."""
        return self.landCount or self.land_count

    def resolved_total_power(self) -> int:
        """Real total power from Forge; falls back to creatures * 3 heuristic."""
        real = self.totalPowerOnBoard or self.total_power_on_board
        if real > 0:
            return real
        return self.resolved_creatures() * 3  # legacy heuristic

    def resolved_total_toughness(self) -> int:
        return self.totalToughnessOnBoard or self.total_toughness_on_board

    def resolved_artifacts(self) -> int:
        return self.artifactsOnField or self.artifacts_on_field

    def resolved_enchantments(self) -> int:
        return self.enchantmentsOnField or self.enchantments_on_field


class DecideRequest(BaseModel):
    """Full game state for live decision-making.

    Accepts snapshots from both:
      - The legacy JSONL / batch path (players[] with flat scalar fields)
      - GameSession.buildStateSnapshot() (players[] with zone lists,
        plus a precomputed state_vector float[29] global block)

    When state_vector is present and length == 29, it is used directly
    as the global scalar block and zone embedding pooling runs over the
    players[] zone contents.  This avoids re-deriving scalars that Java
    already computed and normalised.
    """
    # Game metadata
    game_id: str = ""
    turn: int = 1
    turnNumber: int = 0          # GameSession alias for turn
    phase: str = "main_1"
    active_player: int = 0
    activePlayer: int = 0        # GameSession alias
    priority_player: int = 0
    # Per-player state with full zones
    players: List[PlayerZoneState] = Field(default_factory=list)
    # Stack (spells/abilities currently resolving)
    stack: List[Dict] = Field(default_factory=list)
    # Legal actions from Forge
    legal_actions: List[Dict] = Field(default_factory=list)
    legalActions: List[Dict] = Field(default_factory=list)  # GameSession alias
    # Inference params
    playstyle: str = "midrange"
    greedy: bool = False
    temperature: float = 1.0
    # Optional commander info
    commander: str = ""
    deck_name: str = ""
    # Precomputed global scalar vector from GameSession.buildStateVector()
    # float[29] matching STATE_DIMS.global_features in ml/config/scope.py
    state_vector: Optional[List[float]] = None
    state_vector_dim: Optional[int] = None
    # Schema version (GameSession 1.1.0+ includes state_vector)
    snapshot_schema: str = Field(default="1.0.0", alias="schema")

    model_config = {"populate_by_name": True}

    def resolved_turn(self) -> int:
        return self.turnNumber if self.turnNumber > 0 else self.turn

    def resolved_active_seat(self) -> int:
        return self.activePlayer if self.activePlayer > 0 else self.active_player

    def has_precomputed_vector(self) -> bool:
        """True when a valid precomputed state_vector is present."""
        return (
            self.state_vector is not None
            and len(self.state_vector) == _EXPECTED_STATE_VECTOR_LEN
        )


class DecideResponse(BaseModel):
    """Action decision with metadata for online learning."""
    action: str
    action_index: int
    confidence: float
    log_prob: float = 0.0
    value: float = 0.0
    probabilities: Dict[str, float] = Field(default_factory=dict)
    inference_ms: float = 0.0
    vector_source: str = "encoder"   # "precomputed" | "encoder"
    error: Optional[str] = None


class CollectRequest(BaseModel):
    """Batch of online learning tuples from live Forge games."""
    tuples: List[Dict] = Field(default_factory=list)
    count: int = 0


class RewardRequest(BaseModel):
    """End-of-game reward submission."""
    game_id: str
    reward: float
    winner_seat: int = -1
    turns_played: int = 0
    reason: str = ""  # e.g., "life", "commander_damage", "concede"


# ================================================================
# Module-level state (initialized by register_policy_routes)
# ================================================================

_policy_service = None
_online_store = None
_session_stats = {
    "total_decisions": 0,
    "total_tuples_collected": 0,
    "total_rewards_submitted": 0,
    "games_completed": 0,
    "session_start": 0.0,
    "last_decision_ms": 0.0,
    "precomputed_vector_hits": 0,
    "encoder_fallbacks": 0,
}


def register_policy_routes(app, policy_service, online_store=None):
    """Register the policy routes on the FastAPI app.

    Args:
        app: FastAPI application instance
        policy_service: PolicyInferenceService from ml.serving.policy_server
        online_store: Optional OnlineLearningStore for tuple collection
    """
    global _policy_service, _online_store
    _policy_service = policy_service
    _online_store = online_store
    _session_stats["session_start"] = time.time()
    app.include_router(router)
    logger.info("Policy routes registered (online_store=%s)",
                "enabled" if online_store else "disabled")


# ================================================================
# POST /api/policy/decide
# ================================================================

@router.post("/decide", response_model=DecideResponse)
async def decide(req: DecideRequest):
    """Accept full game state, run policy inference, return action.

    When the request includes a precomputed state_vector (float[29] from
    GameSession.buildStateVector()), that vector is used directly as the
    global scalar block and only zone embedding pooling is re-run.
    Otherwise falls back to the full StateEncoder.encode() path.

    This is the primary endpoint for live Forge IPC. The Java
    PolicyClient calls this at each decision point during a real
    Forge game.
    """
    if _policy_service is None or not _policy_service._loaded:
        raise HTTPException(503, detail="Policy model not loaded")

    t_start = time.time()
    _session_stats["total_decisions"] += 1

    playstyle = req.playstyle or "midrange"
    vector_source = "encoder"

    if req.has_precomputed_vector():
        try:
            state_vec = _encode_with_precomputed_global(
                precomputed_global=req.state_vector,
                players=req.players,
                playstyle=playstyle,
                policy_service=_policy_service,
            )
            vector_source = "precomputed"
            _session_stats["precomputed_vector_hits"] += 1
            logger.debug(
                "[decide] precomputed global block used (schema=%s, turn=%d)",
                req.snapshot_schema, req.resolved_turn(),
            )
        except Exception as e:
            logger.warning(
                "Precomputed vector encode failed — falling back to full encoder",
                exc_info=True,
            )
            state_vec = None
    else:
        state_vec = None

    if state_vec is None:
        _session_stats["encoder_fallbacks"] += 1
        snapshot = _build_encoder_snapshot(req)
        result = _policy_service.predict(
            snapshot,
            playstyle=playstyle,
            temperature=req.temperature,
            greedy=req.greedy,
        )
    else:
        result = _infer_from_vector(
            state_vec=state_vec,
            policy_service=_policy_service,
            temperature=req.temperature,
            greedy=req.greedy,
        )

    elapsed_ms = (time.time() - t_start) * 1000
    _session_stats["last_decision_ms"] = elapsed_ms

    if "error" in result:
        raise HTTPException(500, detail=result["error"])

    # ----------------------------------------------------------------
    # Probability diagnostic — logs top-5 actions on every decision.
    # Remove or downgrade to logger.debug once training looks healthy.
    # ----------------------------------------------------------------
    probs = result.get("probabilities", {})
    if probs:
        top5 = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:5]
        top5_str = ", ".join(f"{a}:{p:.3f}" for a, p in top5)
        logger.info(
            "[decide] turn=%d phase=%s → %s (conf=%.3f) | top5=[%s] | src=%s",
            req.resolved_turn(),
            req.phase,
            result["action"],
            result["confidence"],
            top5_str,
            vector_source,
        )

    log_prob = 0.0
    try:
        conf = result.get("confidence", 0.5)
        log_prob = math.log(max(conf, 1e-8))
    except Exception:
        pass

    return DecideResponse(
        action=result["action"],
        action_index=result["action_index"],
        confidence=result["confidence"],
        log_prob=round(log_prob, 6),
        value=0.0,
        probabilities=result.get("probabilities", {}),
        inference_ms=round(elapsed_ms, 2),
        vector_source=vector_source,
    )


# ================================================================
# POST /api/policy/collect
# ================================================================

@router.post("/collect")
async def collect_tuples(req: CollectRequest):
    """Accept a batch of (state, action, reward) tuples from live games
    for online PPO updates.
    """
    count = len(req.tuples)
    _session_stats["total_tuples_collected"] += count

    if _online_store is not None:
        try:
            _online_store.add_tuples(req.tuples)
        except Exception as e:
            logger.error("Failed to store tuples: %s", e, exc_info=True)
            raise HTTPException(500, detail=str(e))

    return {
        "accepted": count,
        "total_buffered": (
            _online_store.size() if _online_store else count
        ),
    }


# ================================================================
# POST /api/policy/reward
# ================================================================

@router.post("/reward")
async def submit_reward(req: RewardRequest):
    """Submit end-of-game reward for all tuples in a game."""
    _session_stats["total_rewards_submitted"] += 1
    _session_stats["games_completed"] += 1

    if _online_store is not None:
        try:
            _online_store.assign_reward(
                game_id=req.game_id,
                reward=req.reward,
                winner_seat=req.winner_seat,
            )
        except Exception as e:
            logger.error("Failed to assign reward: %s", e, exc_info=True)
            raise HTTPException(500, detail=str(e))

    return {
        "game_id": req.game_id,
        "reward": req.reward,
        "status": "accepted",
    }


# ================================================================
# GET /api/policy/health
# ================================================================

@router.get("/health")
async def policy_health():
    """Readiness check for the live Forge IPC loop."""
    model_loaded = (
        _policy_service is not None and _policy_service._loaded
    )
    return {
        "ready": model_loaded,
        "status": "ok" if model_loaded else "degraded",
        "model_loaded": model_loaded,
        "online_store": _online_store is not None,
    }


# ================================================================
# GET /api/policy/stats
# ================================================================

@router.get("/stats")
async def policy_stats():
    """Online learning session statistics."""
    uptime = time.time() - _session_stats["session_start"]
    return {
        **_session_stats,
        "uptime_seconds": round(uptime, 1),
        "decisions_per_second": (
            round(_session_stats["total_decisions"] / max(uptime, 1), 2)
        ),
        "online_store_size": (
            _online_store.size() if _online_store else 0
        ),
    }


# ================================================================
# Internal helpers
# ================================================================

def _encode_with_precomputed_global(
    precomputed_global: List[float],
    players: List[PlayerZoneState],
    playstyle: str,
    policy_service,
) -> np.ndarray:
    """Build a 6177-dim state vector using a precomputed global block.

    Uses the Java-computed float[29] global scalar vector directly and
    runs zone embedding pooling + playstyle one-hot on the Python side.

    Args:
        precomputed_global: float[29] from GameSession.buildStateVector()
        players: PlayerZoneState list from the request (for zone contents)
        playstyle: deck archetype string
        policy_service: PolicyInferenceService (for encoder access)

    Returns:
        np.ndarray of shape (6177,)
    """
    encoder = policy_service.encoder
    if encoder is None:
        raise RuntimeError("StateEncoder not initialised on policy service")

    # 1. Precomputed global block (29 floats)
    global_vec = np.array(precomputed_global, dtype=np.float32)

    # 2. Zone embeddings — pool card names from each player's zones
    player_dicts = [
        {
            "hand": p.resolved_hand(),
            "battlefield": p.resolved_battlefield_names(),
            "graveyard": p.graveyard,
            "command_zone": p.resolved_command_zone(),
        }
        for p in players[:2]
    ]
    while len(player_dicts) < 2:
        player_dicts.append({
            "hand": [], "battlefield": [], "graveyard": [], "command_zone": []
        })

    zone_vec = encoder._encode_zones(player_dicts)

    # 3. Playstyle one-hot (4 floats)
    style_vec = encoder._encode_playstyle(playstyle)

    state = np.concatenate([global_vec, zone_vec, style_vec])

    expected = encoder.dim.total_state_dim  # 6177
    if state.shape[0] != expected:
        raise ValueError(
            f"State dim mismatch after precomputed encode: "
            f"{state.shape[0]} != {expected}"
        )

    return state.astype(np.float32)


def _infer_from_vector(state_vec: np.ndarray, policy_service, temperature: float, greedy: bool) -> Dict:
    """Run policy network inference directly on a prebuilt state vector.

    Mirrors the core of PolicyInferenceService.predict() but accepts an
    ndarray instead of a snapshot dict, avoiding a second encode() call.

    Uses _unwrap_logits (same helper as predict()) to guard against
    tuple/dict returns from wrapped or swapped model variants before any
    arithmetic on the logits tensor.
    """
    import torch
    from ml.config.scope import NUM_ACTIONS, IDX_TO_ACTION
    from ml.serving.policy_server import _unwrap_logits

    t_start = time.time()
    try:
        state_tensor = torch.from_numpy(state_vec).unsqueeze(0).to(policy_service.device)

        with torch.no_grad():
            raw_output = policy_service.model(state_tensor)
            # Guard: unwrap tuple/dict returns (DataParallel, torch.compile,
            # PolicyValueNetwork swap) before temperature division / argmax.
            logits = _unwrap_logits(raw_output)

            if greedy:
                action_idx = logits.argmax(dim=-1).item()
                probs = torch.softmax(logits, dim=-1).cpu().numpy().flatten()
            else:
                scaled = logits / max(temperature, 0.01)
                probs = torch.softmax(scaled, dim=-1).cpu().numpy().flatten()
                action_idx = int(np.random.choice(NUM_ACTIONS, p=probs))

        elapsed_ms = (time.time() - t_start) * 1000
        action = IDX_TO_ACTION[action_idx]
        confidence = float(probs[action_idx])

        prob_map = {
            IDX_TO_ACTION[i].value: round(float(probs[i]), 4)
            for i in range(NUM_ACTIONS)
        }

        return {
            "action": action.value,
            "action_index": action_idx,
            "confidence": round(confidence, 4),
            "probabilities": prob_map,
            "inference_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000
        logger.error("Direct inference error in _infer_from_vector: %s", e, exc_info=True)
        return {"error": str(e), "inference_ms": round(elapsed_ms, 2)}


def _build_encoder_snapshot(req: DecideRequest) -> Dict:
    """Convert a DecideRequest to the flat snapshot dict expected by
    StateEncoder.encode() — normalises GameSession field name aliases
    and wires real Forge board stats (Step 4).

    Board stat priority (highest to lowest):
      1. Real Forge values from DecisionSnapshot.PlayerSnapshot fields
         (creaturesOnField, landCount, totalPowerOnBoard, etc.)
      2. Inferred from zone card-name lists (battlefield length)
      3. Hardcoded fallback (0)
    """
    players_out = []
    for p in req.players:
        bf_names = p.resolved_battlefield_names()
        players_out.append({
            "seat":        p.seat,
            "life":        p.life,
            "cmdr_dmg":    sum(p.cmdr_dmg.values()) if p.cmdr_dmg else 0,
            # Step 4: real mana from Forge instead of mana_available stub
            "mana":        p.resolved_mana(),
            "cmdr_tax":    p.resolved_cmdr_tax(),
            # Step 4: real board counts from Forge pre-computed stats
            "creatures":   p.resolved_creatures(),
            "lands":       p.resolved_lands(),
            # Step 4: real total power replaces the `creatures * 3` heuristic
            # in StateEncoder._encode_global() index 7
            "total_power": p.resolved_total_power(),
            "total_toughness": p.resolved_total_toughness(),
            "artifacts":   p.resolved_artifacts(),
            "enchantments": p.resolved_enchantments(),
            # Zone contents for embedding pooling (unchanged)
            "hand":         p.resolved_hand(),
            "battlefield":  bf_names,
            "graveyard":    p.graveyard,
            "command_zone": p.resolved_command_zone(),
        })

    return {
        "turn":        req.resolved_turn(),
        "phase":       _map_forge_phase(req.phase),
        "active_seat": req.resolved_active_seat(),
        "players":     players_out,
        "game_id":     req.game_id,
        "archetype":   req.playstyle,
    }


_FORGE_PHASE_MAP = {
    "UNTAP": "main_1",
    "UPKEEP": "main_1",
    "DRAW": "main_1",
    "MAIN1": "main_1",
    "BEGIN_COMBAT": "combat",
    "DECLARE_ATTACKERS": "combat",
    "DECLARE_BLOCKERS": "combat",
    "DAMAGE": "combat",
    "COMBAT_DAMAGE": "combat",
    "END_COMBAT": "combat",
    "MAIN2": "main_2",
    "END": "end",
    "END_STEP": "end",
    "CLEANUP": "end",
    # GameSession values already normalised
    "main_1": "main_1",
    "main_2": "main_2",
    "combat": "combat",
    "end": "end",
}


def _map_forge_phase(phase: str) -> str:
    """Map Forge/GameSession phase string to ML GamePhase enum value."""
    return _FORGE_PHASE_MAP.get(phase.upper() if phase else "MAIN1",
                                _FORGE_PHASE_MAP.get(phase, "main_1"))
