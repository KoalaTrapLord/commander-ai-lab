"""
Commander AI Lab — Lobby REST + WebSocket Router (Phase 8)
==========================================================
Mounts at /api/v1/lobby and /ws/lobby

REST endpoints:
  POST   /api/v1/lobby/rooms                 — create room
  GET    /api/v1/lobby/rooms                 — list open rooms
  GET    /api/v1/lobby/rooms/{room_id}       — room details
  POST   /api/v1/lobby/rooms/{room_id}/join  — join room
  POST   /api/v1/lobby/rooms/{room_id}/ready — mark ready
  POST   /api/v1/lobby/rooms/{room_id}/launch— launch game

WebSocket:
  ws://host/ws/lobby/{room_id}?name=PlayerName[&password=X][&spectate=1]
  Receives: lobby_state updates (slots, ready status, chat)
  Sends:    {type: ready} | {type: chat, text: ...} | {type: ping}
"""

from __future__ import annotations

import json
import secrets
import asyncio
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from commander_ai_lab.multiplayer.lobby   import LobbyManager, RoomState
from commander_ai_lab.multiplayer.chat    import ChatChannel
from commander_ai_lab.multiplayer.spectator import SpectatorManager


router   = APIRouter(prefix="/api/v1/lobby", tags=["lobby"])
ws_router = APIRouter(tags=["lobby-ws"])

# Module-level singletons (re-created on app startup)
_lobby:     Optional[LobbyManager]    = None
_spectators: Optional[SpectatorManager] = None
_chats:     dict[str, ChatChannel]    = {}   # room_id -> ChatChannel
# WebSocket registry: room_id -> {connection_id: WebSocket}
_ws_rooms:  dict[str, dict[str, WebSocket]] = {}


def get_lobby() -> LobbyManager:
    global _lobby
    if _lobby is None:
        _lobby = LobbyManager(on_launch=_on_room_launch)
    return _lobby


def get_spectators() -> SpectatorManager:
    global _spectators
    if _spectators is None:
        _spectators = SpectatorManager()
    return _spectators


async def _on_room_launch(room_id: str, room) -> None:
    """Broadcast 'game_launched' event to all lobby WebSockets in the room."""
    await _broadcast_lobby_state(room_id)


async def _broadcast_lobby_state(room_id: str) -> None:
    lobby = get_lobby()
    room  = lobby.get_room(room_id)
    if room is None:
        return
    payload = json.dumps({"type": "lobby_state", "data": room.to_dict()})
    for ws in list(_ws_rooms.get(room_id, {}).values()):
        try:
            await ws.send_text(payload)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# REST — Pydantic models
# ---------------------------------------------------------------------------

class CreateRoomRequest(BaseModel):
    room_name:   str
    host_name:   str
    max_players: int = 4
    ai_slots:    list[dict] = []
    password:    Optional[str] = None


class JoinRoomRequest(BaseModel):
    player_name: str
    password:    Optional[str] = None


class ReadyRequest(BaseModel):
    seat: int
    ready: bool = True


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.post("/rooms", status_code=201)
async def create_room(req: CreateRoomRequest):
    lobby   = get_lobby()
    room_id = await lobby.create_room(
        room_name=req.room_name,
        host_name=req.host_name,
        max_players=req.max_players,
        ai_slots=req.ai_slots,
        password=req.password,
    )
    _chats[room_id]    = ChatChannel(room_id=room_id)
    _ws_rooms[room_id] = {}
    room = lobby.get_room(room_id)
    return {"room_id": room_id, "room": room.to_dict()}


@router.get("/rooms")
async def list_rooms():
    return {"rooms": get_lobby().list_open_rooms()}


@router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    room = get_lobby().get_room(room_id)
    if room is None:
        raise HTTPException(404, detail="Room not found")
    return room.to_dict()


@router.post("/rooms/{room_id}/join")
async def join_room(room_id: str, req: JoinRoomRequest):
    try:
        seat = await get_lobby().join_room(
            room_id, req.player_name, req.password
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    await _broadcast_lobby_state(room_id)
    return {"seat": seat}


@router.post("/rooms/{room_id}/ready")
async def set_ready(room_id: str, req: ReadyRequest):
    try:
        state = await get_lobby().set_ready(room_id, req.seat, req.ready)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    await _broadcast_lobby_state(room_id)
    return {"state": state.name}


@router.post("/rooms/{room_id}/launch")
async def launch_room(room_id: str):
    try:
        room = await get_lobby().launch_game(room_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"state": room.state.name, "room_id": room_id}


# ---------------------------------------------------------------------------
# WebSocket — Lobby room
# ---------------------------------------------------------------------------

@ws_router.websocket("/ws/lobby/{room_id}")
async def lobby_ws(
    websocket: WebSocket,
    room_id: str,
    name: str = "Spectator",
    password: Optional[str] = None,
    spectate: int = 0,
):
    lobby    = get_lobby()
    room     = lobby.get_room(room_id)
    if room is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    conn_id = secrets.token_hex(4)
    _ws_rooms.setdefault(room_id, {})[conn_id] = websocket

    # Register spectator if requested or room is in-progress
    is_spectator = bool(spectate) or room.state in (
        RoomState.IN_PROGRESS, RoomState.FINISHED
    )
    if is_spectator:
        get_spectators().add(room_id, conn_id, websocket.send_text)

    chat = _chats.get(room_id)

    # Send initial lobby state
    await websocket.send_text(json.dumps({
        "type": "lobby_state",
        "data": room.to_dict(),
    }))

    # Send chat history
    if chat:
        await websocket.send_text(json.dumps({
            "type": "chat_history",
            "data": chat.history(last_n=50),
        }))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "detail": "bad json"}))
                continue

            mtype = msg.get("type", "")

            if mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif mtype == "chat":
                text = str(msg.get("text", ""))[:400]
                if chat:
                    await chat.send(sender=name, text=text)
                await _broadcast_lobby_state(room_id)

            elif mtype == "ready":
                seat = msg.get("seat")
                if seat is not None:
                    try:
                        await lobby.set_ready(room_id, seat)
                        await _broadcast_lobby_state(room_id)
                    except ValueError as e:
                        await websocket.send_text(
                            json.dumps({"type": "error", "detail": str(e)})
                        )

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "detail": f"unknown message type: {mtype}",
                }))

    except WebSocketDisconnect:
        pass
    finally:
        _ws_rooms.get(room_id, {}).pop(conn_id, None)
        get_spectators().remove(room_id, conn_id)
