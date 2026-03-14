"""
routes/lab.py
=============
Simulator endpoints:
  POST /api/lab/start
  POST /api/lab/start-deepseek
  GET  /api/lab/status
  GET  /api/lab/result
  GET  /api/lab/decks
  GET  /api/lab/history
  GET  /api/lab/profiles
  GET  /api/lab/profiles/{name}
  GET  /api/lab/analytics/{deck_name}
  GET  /api/lab/trends/{deck_name}
  GET  /api/lab/log
  GET  /api/lab/debug-log

All heavy logic (run_batch_subprocess, _run_deepseek_batch_thread,
build_java_command, parse_dck_file, AI_PROFILES dict) lives in
lab_api.py until the full extraction is complete; this router
delegate-calls those functions via routes.shared.get().
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request as FARequest
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routes.shared import get as _get

router = APIRouter(prefix="/api/lab", tags=["simulator"])


# ---------------------------------------------------------------------------
# Local lightweight models (don't need shared state to define)
# ---------------------------------------------------------------------------

class StartResponse(BaseModel):
    batchId: str
    status: str = "started"
    message: str = ""


class StatusResponse(BaseModel):
    batchId: str = ""
    running: bool = False
    completed: int = 0
    total: int = 0
    threads: int = 0
    elapsedMs: int = 0
    error: Optional[str] = None
    simsPerSec: float = 0.0
    run_id: str = ""
    games_completed: int = 0
    total_games: int = 0
    current_decks: list = []


# ---------------------------------------------------------------------------
# Simulator endpoints
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartResponse)
async def start_batch(req: FARequest, background_tasks: BackgroundTasks):
    """Delegate to lab_api.start_batch (registered via shared registry)."""
    fn = _get("start_batch")
    return await fn(req, background_tasks)


@router.post("/start-deepseek")
async def start_batch_deepseek(request: FARequest, background_tasks: BackgroundTasks):
    fn = _get("start_batch_deepseek")
    return await fn(request, background_tasks)


@router.get("/status", response_model=StatusResponse)
async def get_status(batchId: Optional[str] = None):
    fn = _get("get_status")
    return await fn(batchId=batchId)


@router.get("/result")
async def get_result(batchId: Optional[str] = None):
    fn = _get("get_result")
    return await fn(batchId=batchId)


@router.get("/decks")
async def list_decks():
    fn = _get("list_decks")
    return await fn()


@router.get("/history")
async def list_history():
    fn = _get("list_history")
    return await fn()


@router.get("/profiles")
async def list_profiles():
    fn = _get("list_profiles")
    return await fn()


@router.get("/profiles/{name}")
async def get_profile(name: str):
    fn = _get("get_profile")
    return await fn(name)


@router.get("/analytics/{deck_name}")
async def analyze_deck(deck_name: str):
    fn = _get("analyze_deck")
    return await fn(deck_name)


@router.get("/trends/{deck_name}")
async def get_deck_trends(deck_name: str):
    fn = _get("get_deck_trends")
    return await fn(deck_name)


@router.get("/log")
async def get_log(batchId: str):
    fn = _get("get_log")
    return await fn(batchId=batchId)


@router.get("/debug-log")
async def get_debug_log():
    fn = _get("get_debug_log")
    return await fn()
