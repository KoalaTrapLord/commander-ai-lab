"""WebSocket route for real-time game state streaming.

Endpoints:
  WS   /ws/game/{game_id}         — Stream state deltas to Unity
  POST /api/ws/game/{game_id}/push — Push a state update (called by Forge IPC)
  POST /api/ws/game/{game_id}/decision — Push AI decision event
  POST /api/ws/game/{game_id}/end  — Signal game over
  GET  /api/ws/stats               — Connection statistics

Unity connects to the WebSocket endpoint and receives:
  1. An initial full snapshot on first state push
  2. Subsequent delta-only messages as state changes
  3. Decision events when the AI acts
  4. A game_over event when the game ends
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ws.connection_manager import game_manager
from ws.game_state import get_tracker, remove_tracker

log = logging.getLogger("routes.ws_game")

router = APIRouter(tags=["websocket"])


# ────────────────────────────────────────────────────────────
# WebSocket endpoint  —  Unity connects here
# ────────────────────────────────────────────────────────────

@router.websocket("/ws/game/{game_id}")
async def game_ws(websocket: WebSocket, game_id: str):
    """WebSocket endpoint for Unity game-state streaming.

    Query params:
        client_id  —  optional unique identifier for this client

    The connection stays open for the duration of the game.
    The server pushes messages; the client can send:
        {"type": "ping"}            —  keep-alive
        {"type": "request_snapshot"} —  request a full re-sync
    """
    client_id = (
        websocket.query_params.get("client_id")
        or f"unity-{uuid.uuid4().hex[:8]}"
    )

    client = await game_manager.connect(websocket, game_id, client_id)

    # If the tracker already has a baseline, send the current state
    tracker = get_tracker(game_id)
    if tracker.has_baseline:
        snapshot_msg = tracker.update(tracker._last_snapshot)
        await websocket.send_json(snapshot_msg)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "request_snapshot":
                if tracker.has_baseline:
                    # Re-send current state as full snapshot
                    import copy
                    snap = copy.deepcopy(tracker._last_snapshot)
                    tracker._seq += 1
                    import time
                    await websocket.send_json({
                        "type": "snapshot",
                        "seq": tracker._seq,
                        "game_id": game_id,
                        "timestamp": time.time(),
                        "state": snap,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No game state available yet",
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("WS error game=%s client=%s: %s", game_id, client_id, e)
    finally:
        await game_manager.disconnect(game_id, client_id)


# ────────────────────────────────────────────────────────────
# REST endpoints  —  called by Forge IPC / policy server
# ────────────────────────────────────────────────────────────

class PushStateRequest(BaseModel):
    """Game state snapshot pushed from Forge."""
    game_id: str = ""
    turn: int = 0
    phase: str = ""
    active_player: int = 0
    players: list = Field(default_factory=list)
    stack: list = Field(default_factory=list)
    legal_actions: list = Field(default_factory=list)


class DecisionEvent(BaseModel):
    """AI decision event pushed after policy inference."""
    action: str
    action_index: int = 0
    confidence: float = 0.0
    probabilities: dict = Field(default_factory=dict)
    inference_ms: float = 0.0


class GameOverEvent(BaseModel):
    """Game-over event."""
    winner_seat: int = -1
    reason: str = ""
    turns_played: int = 0


@router.post("/api/ws/game/{game_id}/push")
async def push_game_state(game_id: str, req: PushStateRequest):
    """Push a game state update to all connected Unity clients.

    Called by the Forge IPC bridge or policy server after each
    state change. The delta engine diffs against the previous
    state and broadcasts only what changed.
    """
    tracker = get_tracker(game_id)
    snapshot = req.dict()
    delta_msg = tracker.update(snapshot)
    sent = await game_manager.broadcast_to_game(game_id, delta_msg)
    return {
        "status": "ok",
        "type": delta_msg["type"],
        "seq": delta_msg["seq"],
        "clients_notified": sent,
        "changes": len(delta_msg.get("changes", [])),
    }


@router.post("/api/ws/game/{game_id}/decision")
async def push_decision(game_id: str, event: DecisionEvent):
    """Push an AI decision event to connected Unity clients."""
    tracker = get_tracker(game_id)
    msg = tracker.make_decision_event(
        action=event.action,
        action_index=event.action_index,
        confidence=event.confidence,
        probabilities=event.probabilities,
        inference_ms=event.inference_ms,
    )
    sent = await game_manager.broadcast_to_game(game_id, msg)
    return {"status": "ok", "clients_notified": sent}


@router.post("/api/ws/game/{game_id}/end")
async def push_game_over(game_id: str, event: GameOverEvent):
    """Signal game over to all connected clients and clean up."""
    tracker = get_tracker(game_id)
    msg = tracker.make_game_over_event(
        winner_seat=event.winner_seat,
        reason=event.reason,
        turns_played=event.turns_played,
    )
    sent = await game_manager.broadcast_to_game(game_id, msg)
    remove_tracker(game_id)
    return {"status": "ok", "clients_notified": sent}


@router.get("/api/ws/stats")
async def ws_stats():
    """Return WebSocket connection statistics."""
    return game_manager.stats()
