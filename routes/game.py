"""Live game session routes.

Endpoints:
  POST /api/game/start   — create a new live game session (called by LobbySetupModal)
  POST /api/game/action  — submit a human player action   (called by HumanActionBar)
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("routes.game")

router = APIRouter(tags=["game"])


# ───────────────────────────────────────────────────────────────
# Request / Response models
# ───────────────────────────────────────────────────────────────

class SeatConfig(BaseModel):
    seat_index: int = 0
    seat_type: str = "AI"          # "Human" | "AI Aggro" | "AI Control" | "AI Combo" | "AI Political"
    deck_name: str = ""
    player_name: str = ""


class StartGameRequest(BaseModel):
    seats: List[SeatConfig] = Field(default_factory=list)


class StartGameResponse(BaseModel):
    game_id: str
    status: str = "started"
    ws_url: str


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


# ───────────────────────────────────────────────────────────────
# In-memory session store  (replace with DB / Redis for persistence)
# ───────────────────────────────────────────────────────────────

# { game_id: { "seats": [...], "status": "active" | "ended", "pending_actions": [...] } }
_sessions: dict[str, dict] = {}


# ───────────────────────────────────────────────────────────────
# POST /api/game/start
# ───────────────────────────────────────────────────────────────

@router.post("/api/game/start", response_model=StartGameResponse)
async def start_game(req: StartGameRequest):
    """Create a new live game session.

    Called by Unity's LobbySetupModal after the player configures seats.
    Returns a game_id that Unity uses to connect to the WebSocket at
    /ws/game/{game_id}.

    TODO: Wire Forge engine launch here once the IPC layer is ready.
    For now, creates a session record and returns the game_id so Unity
    can connect and receive state pushes from the Forge IPC client.
    """
    if not req.seats:
        raise HTTPException(status_code=400, detail="At least one seat is required.")

    game_id = uuid.uuid4().hex

    _sessions[game_id] = {
        "game_id": game_id,
        "seats": [s.dict() for s in req.seats],
        "status": "active",
        "pending_actions": [],
    }

    log.info(
        "Game session created: game_id=%s seats=%d",
        game_id,
        len(req.seats),
    )

    return StartGameResponse(
        game_id=game_id,
        status="started",
        ws_url=f"/ws/game/{game_id}",
    )


# ───────────────────────────────────────────────────────────────
# POST /api/game/action
# ───────────────────────────────────────────────────────────────

@router.post("/api/game/action", response_model=GameActionResponse)
async def game_action(req: GameActionRequest):
    """Submit a human player action during a live game.

    Called by Unity's HumanActionBar when seat 0 (human) has priority.
    The action is queued in the session's pending_actions list, where
    the Forge IPC polling loop will pick it up.

    Valid actions:
      pass_priority     — pass priority to the next player
      end_turn          — end the current turn
      declare_attackers — declare attacking creatures
      declare_blockers  — declare blocking creatures
      select_target     — select a target (requires target_id)
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
        raise HTTPException(
            status_code=404,
            detail=f"Game session '{req.game_id}' not found.",
        )

    if session["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Game session '{req.game_id}' is not active (status={session['status']}).",
        )

    action_record = {
        "seat": req.seat,
        "action": req.action,
        "target_id": req.target_id,
        "extra": req.extra,
    }
    session["pending_actions"].append(action_record)

    log.info(
        "Action queued: game_id=%s seat=%d action=%s",
        req.game_id, req.seat, req.action,
    )

    return GameActionResponse(
        status="ok",
        game_id=req.game_id,
        action=req.action,
    )


# ───────────────────────────────────────────────────────────────
# GET /api/game/{game_id}/actions  (Forge IPC polling endpoint)
# ───────────────────────────────────────────────────────────────

@router.get("/api/game/{game_id}/actions")
async def poll_actions(game_id: str):
    """Drain and return all pending human actions for a game session.

    Called by the Forge IPC polling loop to consume human player decisions.
    Clears the queue on each call (consume-once semantics).
    """
    session = _sessions.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Game session '{game_id}' not found.")

    actions = session["pending_actions"].copy()
    session["pending_actions"].clear()
    return {"game_id": game_id, "actions": actions}


# ───────────────────────────────────────────────────────────────
# GET /api/game/sessions  (debug)
# ───────────────────────────────────────────────────────────────

@router.get("/api/game/sessions")
async def list_sessions():
    """List active game sessions (debug endpoint)."""
    return {
        "count": len(_sessions),
        "sessions": [
            {"game_id": gid, "status": s["status"], "seats": len(s["seats"])}
            for gid, s in _sessions.items()
        ],
    }
