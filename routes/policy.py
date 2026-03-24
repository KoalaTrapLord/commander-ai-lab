"""Commander AI Lab — Policy Decision Routes (Phase 2)
════════════════════════════════════════════════════

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

Refs: Issue #83 Phase 2.2
"""
import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("routes.policy")

router = APIRouter(prefix="/api/policy", tags=["policy"])


# ================================================================
# Request / Response Models
# ================================================================

class PlayerZoneState(BaseModel):
    """Per-player zone state from Forge."""
    seat: int = 0
    name: str = ""
    life: int = 40
    poison: int = 0
    cmdr_dmg: Dict[str, int] = Field(default_factory=dict)
    cmdr_tax: int = 0
    mana_available: int = 0
    mana_pool: Dict[str, int] = Field(default_factory=dict)
    # Full zone contents
    hand: List[str] = Field(default_factory=list)
    hand_count: int = 0
    battlefield: List[Dict] = Field(default_factory=list)
    graveyard: List[str] = Field(default_factory=list)
    exile: List[str] = Field(default_factory=list)
    command_zone: List[str] = Field(default_factory=list)
    library_count: int = 0


class DecideRequest(BaseModel):
    """Full Forge game state for live decision-making."""
    # Game metadata
    game_id: str = ""
    turn: int = 1
    phase: str = "main_1"
    active_player: int = 0
    priority_player: int = 0
    # Per-player state with full zones
    players: List[PlayerZoneState] = Field(default_factory=list)
    # Stack (spells/abilities currently resolving)
    stack: List[Dict] = Field(default_factory=list)
    # Legal actions from Forge
    legal_actions: List[Dict] = Field(default_factory=list)
    # Inference params
    playstyle: str = "midrange"
    greedy: bool = False
    temperature: float = 1.0
    # Optional commander info
    commander: str = ""
    deck_name: str = ""


class DecideResponse(BaseModel):
    """Action decision with metadata for online learning."""
    action: str
    action_index: int
    confidence: float
    log_prob: float = 0.0
    value: float = 0.0
    probabilities: Dict[str, float] = Field(default_factory=dict)
    inference_ms: float = 0.0
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
    """Accept full Forge game state, run policy inference, return action.

    This is the primary endpoint for live Forge IPC. The Java
    PolicyClient calls this at each decision point during a real
    Forge game.

    Returns the macro-action plus log_prob and value estimate
    needed for online PPO updates.
    """
    if _policy_service is None or not _policy_service._loaded:
        raise HTTPException(
            503,
            detail="Policy model not loaded"
        )

    t_start = time.time()
    _session_stats["total_decisions"] += 1

    # Convert request to snapshot dict for the encoder
    snapshot = req.dict(exclude={"temperature", "greedy", "playstyle"})

    # Map phase names from Forge conventions
    snapshot["phase"] = _map_forge_phase(req.phase)
    snapshot["active_seat"] = req.active_player

    result = _policy_service.predict(
        snapshot,
        playstyle=req.playstyle,
        temperature=req.temperature,
        greedy=req.greedy,
    )

    elapsed_ms = (time.time() - t_start) * 1000
    _session_stats["last_decision_ms"] = elapsed_ms

    if "error" in result:
        raise HTTPException(500, detail=result["error"])

    # Add log_prob and value estimate for online learning
    log_prob = 0.0
    value = 0.0
    try:
        import math
        conf = result.get("confidence", 0.5)
        log_prob = math.log(max(conf, 1e-8))
    except Exception:
        pass

    return DecideResponse(
        action=result["action"],
        action_index=result["action_index"],
        confidence=result["confidence"],
        log_prob=round(log_prob, 6),
        value=round(value, 6),
        probabilities=result.get("probabilities", {}),
        inference_ms=round(elapsed_ms, 2),
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
            logger.error("Failed to store tuples: %s", e)
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
    """Submit end-of-game reward for all tuples in a game.
    Propagates the terminal reward back through the game's trajectory.
    """
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
            logger.error("Failed to assign reward: %s", e)
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
# Helpers
# ================================================================

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
}


def _map_forge_phase(phase: str) -> str:
    """Map Forge phase string to ML GamePhase enum value."""
    return _FORGE_PHASE_MAP.get(phase.upper(), "main_1")
