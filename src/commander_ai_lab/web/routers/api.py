"""
Commander AI Lab — REST API Router (Phase 5)
=============================================
Endpoints:
  POST  /api/v1/games                     Create a new game session
  GET   /api/v1/games/{game_id}           Get game state snapshot
  POST  /api/v1/games/{game_id}/move      Submit a human move
  GET   /api/v1/games/{game_id}/moves     List legal moves for human seat
  POST  /api/v1/games/{game_id}/concede   Concede for a seat
  DELETE /api/v1/games/{game_id}          Tear down a game session
  GET   /api/v1/games                     List active sessions
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

from commander_ai_lab.web.session_store import SessionStore, GameSession

router = APIRouter(tags=["game"])
_store = SessionStore()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateGameRequest(BaseModel):
    player_names: list[str] = Field(
        default=["Human", "AI-Timmy", "AI-Spike", "AI-Johnny"],
        description="Exactly 4 player names. Index 0 is always the human seat.",
    )
    human_seat: int = Field(default=0, ge=0, le=3)
    ai_personality: list[str] = Field(
        default=["aggressive", "control", "combo"],
        description="Personality for seats 1, 2, 3 respectively.",
    )


class MoveRequest(BaseModel):
    seat: int = Field(..., ge=0, le=3)
    move_id: int = Field(..., description="Move ID from /moves endpoint.")


class ConcedeRequest(BaseModel):
    seat: int = Field(..., ge=0, le=3)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/games", status_code=201)
async def create_game(req: CreateGameRequest) -> dict:
    """Create and start a new 4-player Commander game session."""
    if len(req.player_names) != 4:
        raise HTTPException(400, "Exactly 4 player names are required.")
    session = await _store.create_session(
        player_names=req.player_names,
        human_seat=req.human_seat,
        ai_personalities=req.ai_personality,
    )
    return {"game_id": session.game_id, "status": "started"}


@router.get("/games")
async def list_games() -> dict:
    """List all active game session IDs."""
    return {"games": _store.list_session_ids()}


@router.get("/games/{game_id}")
async def get_game(game_id: str) -> dict:
    """Return a JSON snapshot of the current game state."""
    session = _get_session(game_id)
    return session.state_snapshot()


@router.get("/games/{game_id}/moves")
async def get_legal_moves(game_id: str, seat: int = 0) -> dict:
    """Return legal moves for the given seat."""
    session = _get_session(game_id)
    moves = session.get_legal_moves(seat)
    return {"seat": seat, "moves": moves}


@router.post("/games/{game_id}/move")
async def submit_move(game_id: str, req: MoveRequest) -> dict:
    """Submit a human move. Returns updated game state snapshot."""
    session = _get_session(game_id)
    ok = await session.apply_human_move(seat=req.seat, move_id=req.move_id)
    if not ok:
        raise HTTPException(400, "Move is not legal or it is not your turn.")
    return {"accepted": True, "state": session.state_snapshot()}


@router.post("/games/{game_id}/concede")
async def concede(game_id: str, req: ConcedeRequest) -> dict:
    """Concede the game for the given seat."""
    session = _get_session(game_id)
    await session.concede(req.seat)
    return {"conceded": True, "seat": req.seat}


@router.delete("/games/{game_id}", status_code=204)
async def delete_game(game_id: str) -> None:
    """Tear down a game session."""
    if not _store.remove_session(game_id):
        raise HTTPException(404, f"Game {game_id!r} not found.")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_session(game_id: str) -> GameSession:
    session = _store.get_session(game_id)
    if session is None:
        raise HTTPException(404, f"Game {game_id!r} not found.")
    return session
