"""Live game session routes.

Endpoints:
  POST /api/game/start   -- create and launch a live Forge game session
  POST /api/game/action  -- submit a human player action  (called by HumanActionBar)
  GET  /api/game/{game_id}/status   -- poll session status and last known game state
  GET  /api/game/{game_id}/actions  -- Forge IPC: drain pending human actions
  GET  /api/game/sessions           -- list active sessions (debug)

Forge IPC flow
--------------
  1. POST /api/game/start
       - Validates seats, resolves deck names
       - Picks a playstyle per AI seat from seat_type (e.g. "AI Aggro" -> "aggro")
       - Calls run_batch_subprocess(num_games=1, use_learned_policy=True, ...)
         which builds the Java command with --policy <style> --policyServer http://localhost:8080
         and spawns the Forge JAR in a background thread
       - Returns game_id + ws_url immediately (non-blocking)
  2. Forge JAR (once launched) calls POST /api/policy/decide on every AI decision
  3. Human actions are queued via POST /api/game/action and drained by
     GET /api/game/{game_id}/actions (polled by the Forge IPC loop inside the JAR)
  4. GET /api/game/{game_id}/status returns live log tail + completion state
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.state import BatchState
from services.forge_runner import run_batch_subprocess

log = logging.getLogger("routes.game")

router = APIRouter(tags=["game"])

# ---------------------------------------------------------------------------
# Playstyle mapping:  seat_type string -> policy playstyle token
# ---------------------------------------------------------------------------

_PLAYSTYLE_MAP: dict[str, str] = {
    "ai aggro":     "aggro",
    "ai control":   "control",
    "ai combo":     "combo",
    "ai political": "political",
    "ai midrange":  "midrange",
    "ai":           "midrange",   # bare "AI" seat -> midrange default
    "human":        None,         # human seats skipped for policy
}


def _seat_playstyle(seat_type: str) -> Optional[str]:
    """Map a SeatConfig.seat_type string to a policy playstyle token.

    Returns None for human seats (no policy needed).
    """
    return _PLAYSTYLE_MAP.get(seat_type.lower().strip(), "midrange")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SeatConfig(BaseModel):
    seat_index: int = 0
    seat_type: str = "AI"          # "Human" | "AI Aggro" | "AI Control" | "AI Combo" | "AI Political"
    deck_name: str = ""
    player_name: str = ""


class StartGameRequest(BaseModel):
    seats: List[SeatConfig] = Field(default_factory=list)
    clock: int = Field(default=6000, description="Per-game wall-clock limit in seconds (0 = unlimited)")
    use_learned_policy: bool = Field(default=True, description="Route AI decisions through /api/policy/decide")
    policy_greedy: bool = Field(default=False, description="Use greedy (argmax) action selection instead of sampling")


class StartGameResponse(BaseModel):
    game_id: str
    status: str = "started"
    ws_url: str
    policy_enabled: bool = False


class GameActionRequest(BaseModel):
    game_id: str
    seat: int = 0
    action: str                    # "pass_priority" | "end_turn" | "declare_attackers" |
                                   # "declare_blockers" | "select_target"
    target_id: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class GameActionResponse(BaseModel):
    status: str = "ok"
    game_id: str
    action: str


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

# { game_id: { "seats": [...], "status": "active"|"ended"|"error",
#              "batch_state": BatchState|None, "pending_actions": [...] } }
_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# POST /api/game/start
# ---------------------------------------------------------------------------

@router.post("/api/game/start", response_model=StartGameResponse)
async def start_game(req: StartGameRequest):
    """Create and launch a live Forge game session.

    Resolves deck names from the seat config, launches the Forge JAR
    as a background subprocess with --policy routing enabled (unless
    use_learned_policy=False), and returns a game_id immediately.

    The Forge JAR will begin calling POST /api/policy/decide for every
    AI seat decision as soon as it is up. Human actions are queued via
    POST /api/game/action and polled by the JAR via GET /api/game/{id}/actions.
    """
    if not req.seats:
        raise HTTPException(status_code=400, detail="At least one seat is required.")

    # Collect deck names from seats that have one, preserving seat order.
    decks = [s.deck_name for s in req.seats if s.deck_name.strip()]
    if not decks:
        raise HTTPException(status_code=400, detail="At least one seat must have a deck_name.")

    # Determine playstyle from the first AI seat (the JAR uses a single global
    # playstyle for its --policy flag; per-seat styles are a future extension).
    policy_style = "midrange"
    for seat in req.seats:
        ps = _seat_playstyle(seat.seat_type)
        if ps is not None:           # skip human seats
            policy_style = ps
            break

    game_id = uuid.uuid4().hex

    # Build a BatchState so the forge_runner watchdog and progress tracking
    # work the same way they do for overnight batch runs.
    state = BatchState(batch_id=game_id)

    _sessions[game_id] = {
        "game_id":         game_id,
        "seats":           [s.dict() for s in req.seats],
        "status":          "active",
        "pending_actions": [],
        "batch_state":     state,
    }

    log.info(
        "Game session created: game_id=%s seats=%d decks=%s policy=%s greedy=%s",
        game_id, len(req.seats), decks, policy_style if req.use_learned_policy else "off",
        req.policy_greedy,
    )

    # Launch Forge subprocess in the background (non-blocking).
    # num_games=1 -> single live game, threads=1, no seed.
    # clock is passed through from the request (default 6000s for live play).
    asyncio.create_task(
        _run_and_finalize(
            game_id=game_id,
            state=state,
            decks=decks,
            clock=req.clock,
            use_learned_policy=req.use_learned_policy,
            policy_style=policy_style,
            policy_greedy=req.policy_greedy,
        )
    )

    return StartGameResponse(
        game_id=game_id,
        status="started",
        ws_url=f"/ws/game/{game_id}",
        policy_enabled=req.use_learned_policy,
    )


async def _run_and_finalize(
    game_id: str,
    state: BatchState,
    decks: list,
    clock: int,
    use_learned_policy: bool,
    policy_style: str,
    policy_greedy: bool,
):
    """Background task: run Forge subprocess then mark session ended."""
    try:
        await run_batch_subprocess(
            state=state,
            decks=decks,
            num_games=1,
            threads=1,
            seed=None,
            clock=clock,
            output_path=f"results/live-{game_id}.json",
            use_learned_policy=use_learned_policy,
            policy_style=policy_style,
            policy_greedy=policy_greedy,
        )
    except Exception as exc:
        log.error("Game %s subprocess error: %s", game_id, exc)
        if game_id in _sessions:
            _sessions[game_id]["status"] = "error"
        return

    if game_id in _sessions:
        _sessions[game_id]["status"] = "ended" if not state.error else "error"
        log.info(
            "Game %s finished: status=%s error=%s",
            game_id, _sessions[game_id]["status"], state.error or "none",
        )


# ---------------------------------------------------------------------------
# POST /api/game/action
# ---------------------------------------------------------------------------

@router.post("/api/game/action", response_model=GameActionResponse)
async def game_action(req: GameActionRequest):
    """Submit a human player action during a live game.

    Called by Unity's HumanActionBar when the human seat has priority.
    The action is queued in the session; the Forge IPC polling loop
    drains it via GET /api/game/{game_id}/actions.
    """
    valid_actions = {
        "pass_priority", "end_turn",
        "declare_attackers", "declare_blockers",
        "select_target",
    }

    if req.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{req.action}'. Valid: {sorted(valid_actions)}",
        )

    if req.action == "select_target" and not req.target_id:
        raise HTTPException(
            status_code=400,
            detail="select_target requires a target_id.",
        )

    session = _sessions.get(req.game_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Game session '{req.game_id}' not found.")

    if session["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Game '{req.game_id}' is not active (status={session['status']}).",
        )

    session["pending_actions"].append({
        "seat":      req.seat,
        "action":    req.action,
        "target_id": req.target_id,
        "extra":     req.extra,
    })

    log.info("Action queued: game_id=%s seat=%d action=%s", req.game_id, req.seat, req.action)

    return GameActionResponse(status="ok", game_id=req.game_id, action=req.action)


# ---------------------------------------------------------------------------
# GET /api/game/{game_id}/status
# ---------------------------------------------------------------------------

@router.get("/api/game/{game_id}/status")
async def game_status(game_id: str):
    """Return live status, log tail, and completion info for a game session.

    Useful for polling from the frontend or a test script to track
    whether Forge has finished launching and started calling /decide.
    """
    session = _sessions.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Game session '{game_id}' not found.")

    state: Optional[BatchState] = session.get("batch_state")
    log_tail = []
    completed = 0
    total = 1
    error = None

    if state:
        log_tail  = state.log_lines[-20:]   # last 20 lines
        completed = state.completed_games
        total     = max(state.total_games, 1)
        error     = state.error

    return {
        "game_id":   game_id,
        "status":    session["status"],
        "seats":     session["seats"],
        "progress":  {"completed": completed, "total": total},
        "log_tail":  log_tail,
        "error":     error,
        "pending_actions": len(session["pending_actions"]),
    }


# ---------------------------------------------------------------------------
# GET /api/game/{game_id}/actions  (Forge IPC polling)
# ---------------------------------------------------------------------------

@router.get("/api/game/{game_id}/actions")
async def poll_actions(game_id: str):
    """Drain and return all pending human actions (consume-once).

    Called by the Forge IPC polling loop to consume human player decisions.
    """
    session = _sessions.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Game session '{game_id}' not found.")

    actions = session["pending_actions"].copy()
    session["pending_actions"].clear()
    return {"game_id": game_id, "actions": actions}


# ---------------------------------------------------------------------------
# GET /api/game/sessions  (debug)
# ---------------------------------------------------------------------------

@router.get("/api/game/sessions")
async def list_sessions():
    """List all tracked game sessions (debug)."""
    return {
        "count": len(_sessions),
        "sessions": [
            {
                "game_id": gid,
                "status":  s["status"],
                "seats":   len(s["seats"]),
                "pending": len(s["pending_actions"]),
            }
            for gid, s in _sessions.items()
        ],
    }
