"""
Commander AI Lab — WebSocket Game Channel (Phase 5)
====================================================
Endpoint:  ws://host/ws/game/{game_id}?seat={0-3}

Message protocol (JSON):

  Client → Server:
    { "type": "move",      "seat": 0, "move_id": 7 }
    { "type": "concede",   "seat": 0 }
    { "type": "ping" }

  Server → Client (broadcast to all connections on the same game):
    { "type": "state",       "data": <GameStateSnapshot> }
    { "type": "event",       "seat": N, "event_type": "...", "narration": "...", "turn": N }
    { "type": "phase",       "phase": "main1", "active_seat": N, "turn": N }
    { "type": "thinking",    "seat": N, "is_thinking": bool }
    { "type": "elimination", "seat": N, "player_name": "..." }
    { "type": "game_over",   "winner": N, "reason": "..." }
    { "type": "pong" }
    { "type": "error",       "detail": "..." }
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from commander_ai_lab.web.session_store import SessionStore
from commander_ai_lab.web.connection_manager import ConnectionManager

router   = APIRouter(tags=["websocket"])
_store   = SessionStore()          # shares singleton with api.py via module-level instance
_manager = ConnectionManager()


@router.websocket("/ws/game/{game_id}")
async def game_websocket(
    websocket: WebSocket,
    game_id: str,
    seat: int = Query(default=0, ge=0, le=3),
) -> None:
    """
    WebSocket endpoint for a live game channel.

    Each connecting client identifies its seat via the `seat` query param.
    Multiple clients may observe the same game (spectators pass seat=-1 in practice
    but the validator clamps to 0-3; full spectator support is Phase 8).
    """
    session = _store.get_session(game_id)
    if session is None:
        await websocket.close(code=4004, reason=f"Game {game_id!r} not found")
        return

    await _manager.connect(websocket, game_id, seat)

    # Register broadcast callback on session so game events reach all clients
    session.set_broadcast_callback(
        lambda msg: _manager.broadcast(game_id, msg)
    )

    # Send initial full state snapshot
    await websocket.send_text(json.dumps({
        "type": "state",
        "data": session.state_snapshot(),
    }))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps(
                    {"type": "error", "detail": "Invalid JSON"}
                ))
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif msg_type == "move":
                move_seat = msg.get("seat", seat)
                move_id   = msg.get("move_id")
                if move_id is None:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "detail": "move_id is required"}
                    ))
                    continue
                ok = await session.apply_human_move(seat=move_seat, move_id=move_id)
                if not ok:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "detail": "Illegal move or not your turn"}
                    ))
                else:
                    # Broadcast updated state to all watchers
                    await _manager.broadcast(game_id, {
                        "type": "state",
                        "data": session.state_snapshot(),
                    })

            elif msg_type == "concede":
                await session.concede(seat)

            else:
                await websocket.send_text(json.dumps(
                    {"type": "error", "detail": f"Unknown message type: {msg_type!r}"}
                ))

    except WebSocketDisconnect:
        _manager.disconnect(websocket, game_id)
