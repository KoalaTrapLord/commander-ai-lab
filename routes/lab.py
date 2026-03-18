"""
routes/lab.py
=============
Batch simulation & lab management endpoints:
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
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request as FastAPIRequest
from fastapi.responses import JSONResponse

from routes.shared import (
    CFG,
    active_batches,
    BatchState,
    StartRequest,
    StartResponse,
    StatusResponse,
    AI_PROFILES,
    build_java_command,
    run_batch_subprocess,
    _run_deepseek_batch_thread,
    parse_dck_file,
    _get_db_conn,
    _load_deck_cards_by_name,
    _ml_logging_enabled,
    log,
    log_batch,
)

router = APIRouter(tags=["lab"])


def _sanitize_floats(obj):
    """Replace NaN/Infinity with None so JSONResponse (allow_nan=False) won't crash."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


@router.post("/api/lab/start", response_model=StartResponse)
async def start_batch(req: StartRequest, background_tasks: BackgroundTasks):
    """Start a new batch simulation run."""
    if len(req.decks) < 2 or len(req.decks) > 4:
        raise HTTPException(400, "2-4 decks required")
    if not all(req.decks):
        raise HTTPException(400, f"All {len(req.decks)} deck slots must be filled")
    if req.numGames < 1 or req.numGames > 10000:
        raise HTTPException(400, "numGames must be 1-10000")
    if req.threads < 1 or req.threads > 16:
        raise HTTPException(400, "threads must be 1-16")

    if not os.path.exists(CFG.forge_jar):
        raise HTTPException(500, f"Forge JAR not found: {CFG.forge_jar}")
    if not os.path.isdir(CFG.forge_dir):
        raise HTTPException(500, f"Forge dir not found: {CFG.forge_dir}")

    batch_id = str(uuid.uuid4())[:12]
    state = BatchState(batch_id, req.numGames, req.threads)
    active_batches[batch_id] = state

    os.makedirs(CFG.results_dir, exist_ok=True)
    output_path = os.path.join(CFG.results_dir, f"batch-{batch_id}.json")
    state.result_path = output_path

    background_tasks.add_task(
        run_batch_subprocess,
        state,
        req.decks,
        req.numGames,
        req.threads,
        req.seed,
        req.clock,
        output_path,
        req.useLearnedPolicy,
        req.policyStyle,
        req.policyGreedy,
        req.aiSimplified,
        req.aiThinkTimeMs,
        req.maxQueueDepth,
    )

    policy_msg = ""
    if req.useLearnedPolicy:
        policy_msg = f" [Learned Policy: {req.policyStyle}]"
    return StartResponse(
        batchId=batch_id,
        status="started",
        message=f"Running {req.numGames} games with {req.threads} threads{policy_msg}",
    )


@router.get("/api/lab/status", response_model=StatusResponse)
async def get_status(batchId: Optional[str] = None):
    # If no batchId given, find the most recent active (or last) batch
    state = None
    if batchId:
        state = active_batches.get(batchId)
    else:
        # Return the most recently active batch, or any batch
        for s in active_batches.values():
            if s.running:
                state = s
                break
        if state is None and active_batches:
            state = list(active_batches.values())[-1]
    if not state:
        return StatusResponse(
            batchId="", running=False, completed=0, total=0,
            threads=0, elapsedMs=0, error=None, simsPerSec=0.0,
            run_id="", games_completed=0, total_games=0, current_decks=[],
        )
    elapsed = int((datetime.now() - state.start_time).total_seconds() * 1000)
    deck_names = getattr(state, 'deck_names', []) if hasattr(state, 'deck_names') else []
    return StatusResponse(
        batchId=state.batch_id,
        running=state.running,
        completed=state.completed_games,
        total=state.total_games,
        threads=state.threads,
        elapsedMs=elapsed if state.running else state.elapsed_ms,
        error=state.error,
        simsPerSec=state.sims_per_sec,
        # React SPA fields
        run_id=state.batch_id,
        games_completed=state.completed_games,
        total_games=state.total_games,
        current_decks=deck_names,
    )


@router.get("/api/lab/result")
async def get_result(batchId: Optional[str] = None):
    state = None
    if batchId:
        state = active_batches.get(batchId)
    else:
        # Find most recent completed batch
        for s in reversed(list(active_batches.values())):
            if not s.running and s.result_path:
                state = s
                break
    if not state:
        raise HTTPException(404, "No batch result available")
    if state.running:
        raise HTTPException(409, "Batch still running")
    if state.error:
        raise HTTPException(500, state.error)
    if not state.result_path or not os.path.exists(state.result_path):
        raise HTTPException(500, "Result file not found")
    try:
        with open(state.result_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"Failed to read result file: {e}")
    data = _sanitize_floats(data)
    return JSONResponse(content=data)


@router.get("/api/lab/decks")
async def list_decks():
    decks = []
    seen_names = set()

    # 1. Forge .dck files from decks directory
    decks_dir = CFG.forge_decks_dir
    if decks_dir and os.path.isdir(decks_dir):
        for f in sorted(Path(decks_dir).glob("*.dck")):
            deck_name = f.stem
            decks.append({"name": deck_name, "filename": f.name, "source": "forge"})
            seen_names.add(deck_name.lower())

    # 2. Decks from the Deck Builder database
    try:
        conn = _get_db_conn()
        rows = conn.execute(
            "SELECT id, name, commander_name FROM decks ORDER BY id DESC"
        ).fetchall()
        for row in rows:
            db_name = row["name"]
            if db_name.lower() not in seen_names:
                decks.append({
                    "name": db_name,
                    "filename": "",
                    "source": "deckbuilder",
                    "deck_id": row["id"],
                    "commander": row["commander_name"] or "",
                })
                seen_names.add(db_name.lower())
    except Exception as e:
        log.warning(f"  WARNING: Failed to load DB decks for /api/lab/decks: {e}")

    return {"decks": decks}


@router.get("/api/lab/history")
async def list_history():
    results_dir = Path(CFG.results_dir)
    if not results_dir.exists():
        return {"results": []}
    results = []
    for f in sorted(results_dir.glob("batch-*.json"), reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            meta = data.get("metadata", {})
            decks = data.get("decks", [])
            results.append({
                "filename": f.name,
                "batchId": meta.get("batchId", ""),
                "timestamp": meta.get("timestamp", ""),
                "totalGames": meta.get("completedGames", 0),
                "threads": meta.get("threads", 1),
                "elapsedMs": meta.get("elapsedMs", 0),
                "decks": [{"name": d.get("deckName", ""), "source": d.get("source", "")} for d in decks],
            })
        except Exception:
            continue
    return {"results": results[:50]}


# ════════════════════════════════════════════════════════════
# AI Profiles
# ════════════════════════════════════════════════════════════

AI_PROFILES = {
    "default": {
        "name": "default",
        "description": "Balanced \u2014 Forge's default AI behavior",
        "aggression": 0.5, "cardAdvantage": 0.5, "removalPriority": 0.5,
        "boardPresence": 0.5, "comboPriority": 0.3, "patience": 0.5,
    },
    "aggro": {
        "name": "aggro",
        "description": "Aggressive \u2014 attacks early, prioritizes damage",
        "aggression": 0.9, "cardAdvantage": 0.3, "removalPriority": 0.3,
        "boardPresence": 0.8, "comboPriority": 0.1, "patience": 0.1,
    },
    "control": {
        "name": "control",
        "description": "Control \u2014 defensive, removal-heavy, card advantage",
        "aggression": 0.2, "cardAdvantage": 0.9, "removalPriority": 0.9,
        "boardPresence": 0.3, "comboPriority": 0.4, "patience": 0.9,
    },
    "combo": {
        "name": "combo",
        "description": "Combo \u2014 ramps, digs for pieces, assembles combos",
        "aggression": 0.2, "cardAdvantage": 0.8, "removalPriority": 0.4,
        "boardPresence": 0.3, "comboPriority": 0.95, "patience": 0.7,
    },
    "midrange": {
        "name": "midrange",
        "description": "Midrange \u2014 flexible, strong board presence, value-oriented",
        "aggression": 0.5, "cardAdvantage": 0.6, "removalPriority": 0.6,
        "boardPresence": 0.7, "comboPriority": 0.3, "patience": 0.5,
    },
}

@router.get("/api/lab/profiles")
async def list_profiles():
    return {"profiles": list(AI_PROFILES.values())}

@router.get("/api/lab/profiles/{name}")
async def get_profile(name: str):
    profile = AI_PROFILES.get(name.lower())
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found. Available: {list(AI_PROFILES.keys())}")
    return profile


@router.get("/api/lab/analytics/{deck_name}")
async def analyze_deck(deck_name: str):
    decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        raise HTTPException(500, f"Decks directory not found: {decks_dir}")
    deck_path = os.path.join(decks_dir, deck_name + ".dck")
    if not os.path.exists(deck_path):
        for f in os.listdir(decks_dir):
            if f.lower() == deck_name.lower() + ".dck":
                deck_path = os.path.join(decks_dir, f)
                break
        else:
            raise HTTPException(404, f"Deck not found: {deck_name}")
    try:
        analysis = parse_dck_file(deck_path)
        return analysis
    except Exception as e:
        raise HTTPException(500, f"Analysis failed: {str(e)}")


def parse_dck_file(deck_path: str) -> dict:
    cards = []
    commander = None
    section = "Main"
    deck_name = Path(deck_path).stem
    with open(deck_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if line.startswith("Name="):
                deck_name = line[5:].strip()
                continue
            m = re.match(r"^(\d+)\s+(.+?)(?:\|(.+))?$", line)
            if m:
                qty = int(m.group(1))
                name = m.group(2).strip()
                set_code = m.group(3).strip() if m.group(3) else ""
                cards.append({
                    "quantity": qty, "name": name, "set": set_code,
                    "section": section,
                    "is_commander": 1 if section == "Commander" else 0,
                })
                if section == "Commander":
                    commander = name
    total = sum(c["quantity"] for c in cards)
    return {
        "deckName": deck_name,
        "commanderName": commander,
        "totalCards": total,
        "cardCount": len(cards),
        "cards": cards[:200],
    }


@router.get("/api/lab/trends/{deck_name}")
async def get_deck_trends(deck_name: str):
    results_dir = Path(CFG.results_dir)
    if not results_dir.exists():
        return {"deckName": deck_name, "history": []}
    history = []
    for f in sorted(results_dir.glob("batch-*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            summary = data.get("summary", {})
            meta = data.get("metadata", {})
            per_deck = summary.get("perDeck", [])
            for ds in per_deck:
                if ds.get("deckName", "").lower() == deck_name.lower():
                    history.append({
                        "batchId": meta.get("batchId"),
                        "timestamp": meta.get("timestamp"),
                        "winRate": ds.get("winRate", 0),
                        "wins": ds.get("wins", 0),
                        "losses": ds.get("losses", 0),
                        "draws": ds.get("draws", 0),
                        "totalGames": meta.get("completedGames", 0),
                    })
                    break
        except Exception:
            continue
    return {"deckName": deck_name, "history": history}


@router.get("/api/lab/log")
async def get_log(batchId: str):
    state = active_batches.get(batchId)
    if not state:
        raise HTTPException(404, f"Batch {batchId} not found")
    return {"lines": state.log_lines[-200:]}


@router.get("/api/lab/debug-log")
async def get_debug_log():
    """Return the raw Forge subprocess debug log for diagnosing simulation issues."""
    # Check multiple possible locations for the debug log
    candidates = []
    if CFG.forge_dir:
        candidates.append(Path(CFG.forge_dir).parent / "forge-sim-debug.log")
        candidates.append(Path(CFG.forge_dir) / "forge-sim-debug.log")
    candidates.append(Path("forge-sim-debug.log"))

    for log_path in candidates:
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            # Return last 50KB to avoid huge responses
            if len(text) > 50000:
                text = "... (truncated) ...\n" + text[-50000:]
            return {"path": str(log_path), "content": text}

    return {"path": None, "content": "No debug log found. Run a simulation first."}



@router.post('/api/lab/start-deepseek')
async def start_batch_deepseek(request: FastAPIRequest, background_tasks: BackgroundTasks):
    """Start a batch simulation using the Python sim engine + DeepSeek LLM opponent."""
    body = await request.json()
    decks = body.get('decks', [])
    num_games = body.get('numGames', 30)
    # Note: threads not applicable for Python sim (single-threaded LLM calls)

    if not decks or len(decks) < 1:
        raise HTTPException(400, 'At least 1 deck required')
    if num_games < 1 or num_games > 500:
        raise HTTPException(400, 'numGames must be 1-500')

    # Filter empty deck slots
    decks = [d for d in decks if d]
    if not decks:
        raise HTTPException(400, 'No valid decks provided')

    batch_id = str(uuid.uuid4())[:12]
    state = BatchState(batch_id, num_games, 1)
    active_batches[batch_id] = state

    os.makedirs(CFG.results_dir, exist_ok=True)
    output_path = os.path.join(CFG.results_dir, f'batch-{batch_id}.json')
    state.result_path = output_path

    # Use threading instead of BackgroundTasks to avoid async issues with DB
    t = threading.Thread(
        target=_run_deepseek_batch_thread,
        args=(state, decks, num_games, output_path),
        daemon=True,
    )
    t.start()

    return JSONResponse({
        'batchId': batch_id,
        'status': 'started',
        'message': f'Running {num_games} games across {len(decks)} decks with DeepSeek AI',
        'engine': 'deepseek',
    })


# Global ML logging toggle (can be enabled via API)
_ml_logging_enabled = False

