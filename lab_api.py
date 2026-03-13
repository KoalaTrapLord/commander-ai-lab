#!/usr/bin/env python3
"""
Commander AI Lab — FastAPI Backend v3
═════════════════════════════════════

v3 adds:
  POST /api/lab/import/url       — Import deck from Archidekt/EDHREC URL
  POST /api/lab/import/text      — Import deck from card list text
  GET  /api/lab/meta/commanders  — List available commanders in meta mapping
  GET  /api/lab/meta/search      — Search commanders by name
  POST /api/lab/meta/fetch       — Fetch EDHREC average deck for a commander
  POST /api/lab/start            — Extended: accepts imported deck profiles

Runs on port 8080 by default. Serves the web UI static files at /.
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Request as FastAPIRequest
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    print("ERROR: FastAPI not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

class Config:
    """Runtime configuration — set via CLI args or env vars."""
    forge_jar: str = ""
    forge_dir: str = ""
    forge_decks_dir: str = ""
    lab_jar: str = ""
    results_dir: str = "results"
    port: int = 8080
    ximilar_api_key: str = ""
    pplx_api_key: str = ""  # Perplexity API key for deck research/generation

CFG = Config()


# ══════════════════════════════════════════════════════════════
# Logging Setup
# ══════════════════════════════════════════════════════════════

_LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR = Path(os.environ.get("CAL_LOG_DIR", "logs"))
_LOG_MAX_BYTES = int(os.environ.get("CAL_LOG_MAX_MB", "25")) * 1024 * 1024
_LOG_BACKUP_COUNT = int(os.environ.get("CAL_LOG_BACKUP_COUNT", "5"))


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root 'commander_ai_lab' logger with console + rotating file."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("commander_ai_lab")
    root_logger.setLevel(level)

    # Avoid duplicate handlers if called again
    if root_logger.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)

    # Console handler — matches previous print() behaviour
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # Rotating file handler — 25 MB × 5 backups = 125 MB max
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "commander-ai-lab.log",
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


# Named loggers — import these where needed
log = logging.getLogger("commander_ai_lab.api")          # API endpoints, server lifecycle
log_batch = logging.getLogger("commander_ai_lab.batch")   # Batch sim (Java + DeepSeek)
log_sim = logging.getLogger("commander_ai_lab.sim")       # DeepSeek game simulation
log_coach = logging.getLogger("commander_ai_lab.coach")   # Coach + report generation
log_deckgen = logging.getLogger("commander_ai_lab.deckgen")  # Deck generation (all versions)
log_collect = logging.getLogger("commander_ai_lab.collection")  # Collection management
log_scan = logging.getLogger("commander_ai_lab.scanner")  # Card scanner
log_ml = logging.getLogger("commander_ai_lab.ml")         # ML training + inference
log_cache = logging.getLogger("commander_ai_lab.cache")   # Scryfall cache
log_pplx = logging.getLogger("commander_ai_lab.pplx")     # Perplexity API


# ══════════════════════════════════════════════════════════════
# App Setup
# ══════════════════════════════════════════════════════════════

app = FastAPI(title="Commander AI Lab API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════
# In-Memory State
# ══════════════════════════════════════════════════════════════

class BatchState:
    """Tracks a running or completed batch."""
    def __init__(self, batch_id: str, total_games: int, threads: int):
        self.batch_id = batch_id
        self.total_games = total_games
        self.threads = threads
        self.completed_games = 0
        self.running = True
        self.start_time = datetime.now()
        self.elapsed_ms = 0
        self.result_path: Optional[str] = None
        self.error: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self.log_lines: list = []
        # v24 (Issue #5): Real-time throughput tracking
        self.sims_per_sec: float = 0.0

active_batches: dict[str, BatchState] = {}

# Commander meta mapping (loaded at startup)
COMMANDER_META: dict = {}

# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class StartRequest(BaseModel):
    decks: list[str]           # Exactly 3 deck names
    numGames: int = 100
    threads: int = 4
    seed: Optional[int] = None
    clock: int = 120
    # v3: Optional source metadata per deck
    deckSources: Optional[list[Optional[dict]]] = None  # [{source, sourceUrl, commander, archetype}]
    # v8: Learned policy support
    useLearnedPolicy: bool = False
    policyStyle: str = "midrange"
    policyGreedy: bool = False
    # v24 (Issues #4/#5): Performance settings
    aiSimplified: bool = False         # Use faster AI profile
    aiThinkTimeMs: int = -1            # Cap AI think time (-1 unlimited)
    maxQueueDepth: int = -1            # Backpressure limit (-1 unlimited)

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
    # React SPA aliases (same data, expected field names)
    run_id: str = ""
    games_completed: int = 0
    total_games: int = 0
    current_decks: list = []

class DeckInfo(BaseModel):
    name: str
    filename: str

class ImportUrlRequest(BaseModel):
    url: str

class ImportTextRequest(BaseModel):
    text: str
    commander: Optional[str] = None

class MetaFetchRequest(BaseModel):
    commander: str


# ── Deck Builder Models ────────────────────────────────────────

class CreateDeckRequest(BaseModel):
    name: str
    commander_scryfall_id: Optional[str] = ""
    commander_name: Optional[str] = ""
    color_identity: Optional[list] = []
    strategy_tag: Optional[str] = ""


class UpdateDeckRequest(BaseModel):
    name: Optional[str] = None
    commander_scryfall_id: Optional[str] = None
    commander_name: Optional[str] = None
    color_identity: Optional[list] = None
    strategy_tag: Optional[str] = None


class AddDeckCardRequest(BaseModel):
    scryfall_id: str
    card_name: Optional[str] = ""
    quantity: Optional[int] = 1
    is_commander: Optional[int] = 0
    role_tag: Optional[str] = ""


class PatchDeckCardRequest(BaseModel):
    quantity: Optional[int] = None
    role_tag: Optional[str] = None


class BulkAddRequest(BaseModel):
    cards: list[dict]  # [{scryfall_id, quantity}]
    respect_ratios: Optional[bool] = False


class BulkAddRecommendedRequest(BaseModel):
    source: str = "collection"  # "collection" | "edhrec"
    only_owned: Optional[bool] = True
    respect_ratios: Optional[bool] = False
    types: Optional[list[str]] = None
    roles: Optional[list[str]] = None


# ── Auto Deck Generator Models ─────────────────────────────────────

class DeckGenerationSourceConfig(BaseModel):
    use_archidekt: bool = True
    use_edhrec: bool = True
    use_moxfield: bool = False
    use_mtggoldfish: bool = False
    archidekt_url: Optional[str] = ""
    moxfield_url: Optional[str] = ""
    mtggoldfish_url: Optional[str] = ""


class DeckGenerationRequest(BaseModel):
    commander_name: Optional[str] = ""
    commander_scryfall_id: Optional[str] = ""
    color_identity: Optional[list[str]] = None
    sources: Optional[DeckGenerationSourceConfig] = None
    target_land_count: int = 37
    target_instant_count: int = 10
    target_sorcery_count: int = 8
    target_artifact_count: int = 10
    target_enchantment_count: int = 8
    target_creature_count: int = 25
    target_planeswalker_count: int = 2
    only_cards_in_collection: bool = False
    allow_proxies: bool = True
    deck_name: Optional[str] = ""


class GeneratedDeckCard(BaseModel):
    scryfall_id: str = ""
    name: str = ""
    type_line: str = ""
    mana_cost: str = ""
    cmc: float = 0
    card_type: str = ""        # Land / Creature / Instant / etc.
    roles: list[str] = []
    source: str = "collection"  # collection / edhrec / archidekt / template
    quantity: int = 1
    image_url: str = ""
    owned_qty: int = 0
    is_proxy: bool = False


# ── V3 Deck Generation (Perplexity Structured Output) ────────
class DeckGenV3Request(BaseModel):
    commander_name: str = ""
    strategy: str = ""                          # e.g. "zombie tokens", "voltron"
    target_bracket: int = 3                     # 1-4 per Commander Rules Committee
    budget_usd: Optional[float] = None          # None = no budget
    budget_mode: str = "total"                  # "total" or "per_card"
    omit_cards: list[str] = []                  # Cards to exclude
    use_collection: bool = True                 # Cross-ref with collection DB
    run_substitution: bool = True               # Enable Smart Substitution Engine
    model: Optional[str] = None                 # Override: sonar, sonar-pro
    deck_name: Optional[str] = ""               # Custom deck name for commit


class DeckGenV3SubstituteRequest(BaseModel):
    """Request to manually pick a substitute for a card."""
    card_name: str
    substitute_name: str


# ══════════════════════════════════════════════════════════════
# v3: Deck Import & Meta Endpoints
# ══════════════════════════════════════════════════════════════

@app.post("/api/lab/import/url")
async def import_from_url(req: ImportUrlRequest):
    """Import a deck from Archidekt or EDHREC URL. Returns parsed DeckProfile + saves .dck file."""
    url = req.url.strip()
    try:
        profile = _import_from_url(url)
        dck_path = _save_profile_to_dck(profile)
        return {
            "success": True,
            "deckName": profile["name"],
            "commander": profile["commander"],
            "source": profile["source"],
            "sourceUrl": profile["sourceUrl"],
            "totalCards": profile["totalCards"],
            "dckFile": dck_path.stem,
            "colorIdentity": profile.get("colorIdentity", []),
            "archetype": profile.get("archetype"),
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/lab/import/text")
async def import_from_text(req: ImportTextRequest):
    """Import a deck from plain text card list."""
    try:
        profile = _parse_text_decklist(req.text, req.commander)
        dck_path = _save_profile_to_dck(profile)
        return {
            "success": True,
            "deckName": profile["name"],
            "commander": profile["commander"],
            "source": "Text Import",
            "totalCards": profile["totalCards"],
            "dckFile": dck_path.stem,
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/lab/meta/commanders")
async def list_meta_commanders():
    """List available commanders in the meta mapping."""
    commanders = []
    for name, entries in COMMANDER_META.items():
        entry = entries[0] if entries else {}
        commanders.append({
            "name": name,
            "archetype": entry.get("archetype", ""),
            "colorIdentity": entry.get("colorIdentity", []),
            "source": entry.get("source", "edhrec"),
        })
    return {"commanders": commanders}


@app.get("/api/lab/meta/search")
async def search_meta_commanders(q: str = ""):
    """Search commanders by partial name match."""
    query = q.lower()
    matches = []
    for name, entries in COMMANDER_META.items():
        if query in name.lower():
            entry = entries[0] if entries else {}
            matches.append({
                "name": name,
                "archetype": entry.get("archetype", ""),
                "colorIdentity": entry.get("colorIdentity", []),
            })
    return {"results": matches}


@app.post("/api/lab/meta/fetch")
async def fetch_meta_deck(req: MetaFetchRequest):
    """Fetch EDHREC average deck for a commander and save as .dck file."""
    try:
        profile = _fetch_edhrec_average(req.commander)
        dck_path = _save_profile_to_dck(profile)
        return {
            "success": True,
            "deckName": profile["name"],
            "commander": profile["commander"],
            "source": "EDHREC Average",
            "sourceUrl": profile.get("sourceUrl", ""),
            "totalCards": profile["totalCards"],
            "dckFile": dck_path.stem,
            "colorIdentity": profile.get("colorIdentity", []),
            "sampleSize": profile.get("sampleSize"),
        }
    except Exception as e:
        raise HTTPException(400, f"Failed to fetch meta deck for '{req.commander}': {str(e)}")


# ══════════════════════════════════════════════════════════════
# Existing Endpoints (v1/v2)
# ══════════════════════════════════════════════════════════════

@app.post("/api/lab/start", response_model=StartResponse)
async def start_batch(req: StartRequest, background_tasks: BackgroundTasks):
    """Start a new batch simulation run."""
    if len(req.decks) != 3:
        raise HTTPException(400, "Exactly 3 decks required")
    if not all(req.decks):
        raise HTTPException(400, "All 3 deck slots must be filled")
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


@app.get("/api/lab/status", response_model=StatusResponse)
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


@app.get("/api/lab/result")
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
    with open(state.result_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(content=data)


@app.get("/api/lab/decks")
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


@app.get("/api/lab/history")
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

@app.get("/api/lab/profiles")
async def list_profiles():
    return {"profiles": list(AI_PROFILES.values())}

@app.get("/api/lab/profiles/{name}")
async def get_profile(name: str):
    profile = AI_PROFILES.get(name.lower())
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found. Available: {list(AI_PROFILES.keys())}")
    return profile


@app.get("/api/lab/analytics/{deck_name}")
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
                cards.append({"quantity": qty, "name": name, "set": set_code, "section": section})
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


@app.get("/api/lab/trends/{deck_name}")
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


@app.get("/api/lab/log")
async def get_log(batchId: str):
    state = active_batches.get(batchId)
    if not state:
        raise HTTPException(404, f"Batch {batchId} not found")
    return {"lines": state.log_lines[-200:]}


@app.get("/api/lab/debug-log")
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


# ══════════════════════════════════════════════════════════════
# Precon Decks
# ══════════════════════════════════════════════════════════════

PRECON_DIR = Path(__file__).parent / "precon-decks"
PRECON_INDEX: list[dict] = []


def load_precon_index():
    global PRECON_INDEX
    idx_path = PRECON_DIR / "precon-index.json"
    if idx_path.exists():
        with open(idx_path, "r", encoding="utf-8") as f:
            PRECON_INDEX = json.load(f)
        log.info(f"  Precons:      {len(PRECON_INDEX)} precon decks loaded")
    else:
        PRECON_INDEX = []
        log.info(f"  Precons:      index not found at {idx_path}")


@app.get("/api/lab/precons")
async def list_precons():
    """List all available precon decks."""
    return {"precons": PRECON_INDEX}


@app.post("/api/lab/precons/install")
async def install_precon(req: dict):
    """Install a precon deck to the Forge decks directory.
    Body: {"fileName": "Elven_Empire.dck"}
    """
    file_name = req.get("fileName", "")
    if not file_name:
        raise HTTPException(400, "fileName is required")

    src = PRECON_DIR / file_name
    if not src.exists():
        raise HTTPException(404, f"Precon not found: {file_name}")

    decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        raise HTTPException(500, f"Forge decks directory not found: {decks_dir}")

    import shutil
    dst = Path(decks_dir) / file_name
    shutil.copy2(str(src), str(dst))

    deck_name = file_name.replace(".dck", "")
    return {
        "installed": True,
        "deckName": deck_name,
        "destination": str(dst),
        "message": f"Installed {deck_name} to Forge decks",
    }


@app.post("/api/lab/precons/install-batch")
async def install_precons_batch(req: dict):
    """Install multiple precon decks at once.
    Body: {"fileNames": ["Elven_Empire.dck", "Necron_Dynasties.dck"]}
    """
    file_names = req.get("fileNames", [])
    if not file_names:
        raise HTTPException(400, "fileNames list is required")

    decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        raise HTTPException(500, f"Forge decks directory not found: {decks_dir}")

    import shutil
    results = []
    for file_name in file_names:
        src = PRECON_DIR / file_name
        if not src.exists():
            results.append({"fileName": file_name, "installed": False, "error": "not found"})
            continue
        dst = Path(decks_dir) / file_name
        shutil.copy2(str(src), str(dst))
        deck_name = file_name.replace(".dck", "")
        results.append({"fileName": file_name, "installed": True, "deckName": deck_name})

    return {"results": results}


# ── Precon Auto-Download from GitHub ─────────────────────────

GITHUB_PRECON_URL = (
    "https://raw.githubusercontent.com/taw/magic-preconstructed-decks-data/"
    "master/decks_v2.json"
)
PRECON_CACHE_HOURS = 168  # re-download weekly


def _color_identity_from_cards(deck_data: dict) -> list[str]:
    """Extract approximate color identity from commander section."""
    # The data doesn't include color info directly, so we track what we can
    # from commander names — but we just leave it as a searchable field.
    return []


def _sanitize_filename(name: str) -> str:
    """Turn a deck name into a safe filename."""
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = safe.replace(' ', '_').replace("'", '').replace('!', '')
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe


def _deck_to_dck(deck_data: dict) -> str:
    """Convert a deck entry from decks_v2.json into .dck format."""
    lines = []
    lines.append("[metadata]")
    lines.append(f"Name={deck_data['name']}")

    # Commander section
    commanders = deck_data.get('commander', [])
    if commanders:
        lines.append("[Commander]")
        for card in commanders:
            count = card.get('count', 1)
            lines.append(f"{count} {card['name']}")

    # Main deck
    cards = deck_data.get('cards', [])
    if cards:
        lines.append("[Main]")
        for card in cards:
            count = card.get('count', 1)
            lines.append(f"{count} {card['name']}")

    # Sideboard (rare in Commander but include if present)
    sideboard = deck_data.get('sideboard', [])
    if sideboard:
        lines.append("[Sideboard]")
        for card in sideboard:
            count = card.get('count', 1)
            lines.append(f"{count} {card['name']}")

    return "\n".join(lines) + "\n"


def download_precon_database(force: bool = False) -> dict:
    """
    Download all Commander precon decks from GitHub, convert to .dck,
    and rebuild precon-index.json.  Skips if index is fresh (< PRECON_CACHE_HOURS old)
    unless force=True.

    Returns {"downloaded": int, "skipped": bool, "error": str|None}
    """
    global PRECON_INDEX
    idx_path = PRECON_DIR / "precon-index.json"

    # ── Cache check ──────────────────────────────────────────
    if not force and idx_path.exists():
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            # If we have a substantial number of decks and file is recent, skip
            if len(existing) > 50:
                age_hours = (time.time() - idx_path.stat().st_mtime) / 3600
                if age_hours < PRECON_CACHE_HOURS:
                    log.info(f"  Precons:      {len(existing)} decks cached "
                          f"({age_hours:.0f}h old, refresh after {PRECON_CACHE_HOURS}h)")
                    PRECON_INDEX = existing
                    return {"downloaded": 0, "skipped": True, "total": len(existing),
                            "error": None}
        except Exception:
            pass  # Fall through to download

    # ── Download ─────────────────────────────────────────────
    log.info("  Precons:      Downloading full precon database from GitHub...")
    try:
        req = Request(GITHUB_PRECON_URL, headers={"User-Agent": "CommanderAILab/3.0"})
        with urlopen(req, timeout=120) as resp:
            raw = resp.read()
        all_decks = json.loads(raw)
    except Exception as e:
        msg = f"Failed to download precon database: {e}"
        log.error(f"  Precons:      ERROR — {msg}")
        # Fall back to whatever we have locally
        if idx_path.exists():
            load_precon_index()
        return {"downloaded": 0, "skipped": False, "error": msg}

    # ── Filter to Commander precon decks ─────────────────────
    commander_decks = [
        d for d in all_decks
        if d.get('type') == 'Commander Deck'
        and (d.get('format') or '').lower() == 'commander'
    ]
    log.info(f"  Precons:      Found {len(commander_decks)} Commander precon decks")

    # ── Ensure precon-decks dir exists ───────────────────────
    PRECON_DIR.mkdir(parents=True, exist_ok=True)

    # ── Detect duplicate names and append set code for uniqueness ─
    from collections import Counter
    name_counts = Counter(_sanitize_filename(d['name']) for d in commander_decks)
    dup_names = {n for n, c in name_counts.items() if c > 1}

    # ── Convert and write .dck files + build index ───────────
    index = []
    written = 0
    for deck in sorted(commander_decks, key=lambda d: (d.get('release_date', ''), d.get('name', ''))):
        safe_name = _sanitize_filename(deck['name'])
        # Append set code for duplicate names (e.g. Anthology reprints)
        if safe_name in dup_names:
            sc = (deck.get('set_code') or 'unk').upper()
            safe_name = f"{safe_name}_{sc}"
        file_name = f"{safe_name}.dck"
        dck_path = PRECON_DIR / file_name

        # Extract commander names
        commanders = deck.get('commander', [])
        cmdr_names = [c['name'] for c in commanders] if commanders else []

        # Card count
        total_cards = sum(c.get('count', 1) for c in deck.get('cards', []))
        total_cards += sum(c.get('count', 1) for c in commanders)

        # Write .dck file
        dck_content = _deck_to_dck(deck)
        with open(dck_path, "w", encoding="utf-8") as f:
            f.write(dck_content)
        written += 1

        # Build index entry
        release = deck.get('release_date', '')
        year = int(release[:4]) if release and len(release) >= 4 else 0
        index.append({
            "name": deck['name'],
            "commander": cmdr_names[0] if cmdr_names else "Unknown",
            "commanders": cmdr_names,
            "colors": [],  # Color data not in source; UI can infer from cards
            "set": deck.get('set_name', ''),
            "setCode": deck.get('set_code', ''),
            "year": year,
            "releaseDate": release,
            "theme": "",
            "fileName": file_name,
            "cardCount": total_cards,
        })

    # ── Write index ──────────────────────────────────────────
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    PRECON_INDEX = index
    log.info(f"  Precons:      {written} .dck files written, index saved")
    return {"downloaded": written, "skipped": False, "total": written, "error": None}


@app.post("/api/lab/precons/refresh")
async def refresh_precons():
    """Force re-download of all Commander precon decks from GitHub."""
    result = download_precon_database(force=True)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return {
        "message": f"Downloaded {result['downloaded']} Commander precon decks",
        "total": result.get("total", 0),
    }


# ══════════════════════════════════════════════════════════════
# Deck Import Helpers (Python-side)
# ══════════════════════════════════════════════════════════════

_API_HEADERS = {"User-Agent": "CommanderAILab/3.0", "Accept": "application/json"}


def _http_get(url: str) -> str:
    req = Request(url, headers=_API_HEADERS)
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _import_from_url(url: str) -> dict:
    """Import deck from URL (Archidekt or EDHREC)."""
    url = url.strip()

    # Archidekt
    if "archidekt.com/decks/" in url:
        m = re.search(r"/decks/(\d+)", url)
        if not m:
            raise ValueError("Could not parse Archidekt deck ID from URL")
        return _fetch_archidekt_deck(m.group(1))

    # EDHREC average deck
    if "edhrec.com/average-decks/" in url:
        slug = re.search(r"/average-decks/([^/?#]+)", url).group(1)
        commander_name = slug.replace("-", " ")
        return _fetch_edhrec_average(commander_name)

    # EDHREC commander page
    if "edhrec.com/commanders/" in url:
        slug = re.search(r"/commanders/([^/?#]+)", url).group(1)
        commander_name = slug.replace("-", " ")
        return _fetch_edhrec_average(commander_name)

    raise ValueError(f"Unsupported URL: {url}. Supported: archidekt.com/decks/..., edhrec.com/average-decks/..., edhrec.com/commanders/...")


def _fetch_archidekt_deck(deck_id: str) -> dict:
    """Fetch deck from Archidekt API."""
    url = f"https://archidekt.com/api/decks/{deck_id}/"
    data = json.loads(_http_get(url))

    profile = {
        "name": data.get("name", f"Archidekt {deck_id}"),
        "commander": None,
        "source": "Archidekt",
        "sourceUrl": f"https://archidekt.com/decks/{deck_id}",
        "commanders": {},
        "mainboard": {},
        "colorIdentity": [],
        "totalCards": 0,
    }

    for card_entry in data.get("cards", []):
        qty = card_entry.get("quantity", 1)
        card = card_entry.get("card", {})
        oracle = card.get("oracleCard", {})
        card_name = oracle.get("name", "Unknown")

        categories = [c for c in card_entry.get("categories", [])]
        is_commander = any(c.lower() == "commander" for c in categories)

        if is_commander:
            profile["commanders"][card_name] = qty
            if not profile["commander"]:
                profile["commander"] = card_name
                if oracle.get("colorIdentity"):
                    profile["colorIdentity"] = oracle["colorIdentity"]
        else:
            profile["mainboard"][card_name] = qty

    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    if not profile["name"] or profile["name"] == f"Archidekt {deck_id}":
        profile["name"] = f"{profile['commander']} — Archidekt"

    return profile


def _fetch_edhrec_average(commander_name: str) -> dict:
    """Fetch EDHREC average deck for a commander."""
    slug = _to_edhrec_slug(commander_name)
    url = f"https://json.edhrec.com/pages/average-decks/{slug}.json"
    data = json.loads(_http_get(url))

    container = data.get("container", {})
    json_dict = container.get("json_dict", {})
    card_info = json_dict.get("card", {})
    real_name = card_info.get("name", commander_name.title())

    profile = {
        "name": f"{real_name} — EDHREC Average",
        "commander": real_name,
        "source": "EDHREC Average",
        "sourceUrl": f"https://edhrec.com/average-decks/{slug}",
        "commanders": {real_name: 1},
        "mainboard": {},
        "colorIdentity": card_info.get("color_identity", []),
        "sampleSize": data.get("num_decks_avg"),
        "totalCards": 0,
    }

    # Parse card lists
    for cl in json_dict.get("cardlists", []):
        for cv in cl.get("cardviews", []):
            card_name = cv.get("name", "")
            if card_name:
                profile["mainboard"][card_name] = 1

    # Fix basic land quantities from archidekt export data
    archidekt_data = data.get("archidekt", [])
    if archidekt_data:
        basic_names = []
        for cl in json_dict.get("cardlists", []):
            if cl.get("tag") == "basics":
                for cv in cl.get("cardviews", []):
                    basic_names.append(cv.get("name", ""))

        # Find high-quantity entries (basics)
        basic_quantities = []
        for entry in archidekt_data:
            if entry.get("q", 1) > 1:
                basic_quantities.append(entry["q"])

        for i, name in enumerate(basic_names):
            if i < len(basic_quantities):
                profile["mainboard"][name] = basic_quantities[i]

    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    return profile


def _parse_text_decklist(text: str, commander_override: str = None) -> dict:
    """Parse a plain text card list into a profile."""
    profile = {
        "name": "Text Import",
        "commander": None,
        "source": "Text Import",
        "sourceUrl": None,
        "commanders": {},
        "mainboard": {},
        "totalCards": 0,
    }

    section = "main"
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        if line.lower().startswith("commander") or line == "[Commander]":
            section = "commander"
            continue
        if line.lower().startswith("main") or line.lower().startswith("deck") or line == "[Main]":
            section = "main"
            continue
        if line.lower().startswith("sideboard") or line == "[Sideboard]":
            section = "sideboard"
            continue

        # Clean line
        clean = re.sub(r"\(\w+\)\s*\d*$", "", line).strip()
        clean = re.sub(r"\s*\*.*$", "", clean).strip()

        m = re.match(r"^(\d+)x?\s+(.+)$", clean)
        if m:
            qty = int(m.group(1))
            card_name = m.group(2).strip()
        else:
            qty = 1
            card_name = clean

        if not card_name:
            continue

        if section == "commander":
            profile["commanders"][card_name] = qty
            if not profile["commander"]:
                profile["commander"] = card_name
        elif section != "sideboard":
            profile["mainboard"][card_name] = qty

    if commander_override:
        profile["commander"] = commander_override
        if not profile["commanders"]:
            if commander_override in profile["mainboard"]:
                qty = profile["mainboard"].pop(commander_override)
                profile["commanders"][commander_override] = qty
            else:
                profile["commanders"][commander_override] = 1

    if profile["commander"]:
        profile["name"] = f"{profile['commander']} — Text Import"

    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    return profile


def _save_profile_to_dck(profile: dict) -> Path:
    """Convert a profile dict to .dck and save to Forge decks dir."""
    lines = ["[metadata]"]
    lines.append(f"Name={profile.get('name', 'Imported Deck')}")
    lines.append("")
    lines.append("[Commander]")
    for name, qty in profile.get("commanders", {}).items():
        lines.append(f"{qty} {name}")
    lines.append("")
    lines.append("[Main]")
    for name, qty in profile.get("mainboard", {}).items():
        lines.append(f"{qty} {name}")

    content = "\n".join(lines)

    # Save to Forge decks dir
    safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", profile.get("name", "imported")).replace(" ", "_").strip()
    if not safe_name:
        safe_name = "imported_deck"

    save_dir = CFG.forge_decks_dir
    if not save_dir or not os.path.isdir(save_dir):
        save_dir = os.path.join(os.path.dirname(__file__), "imported-decks")
        os.makedirs(save_dir, exist_ok=True)

    out_path = Path(save_dir) / f"{safe_name}.dck"
    out_path.write_text(content, encoding="utf-8")
    log_collect.info(f"  Saved .dck: {out_path}")
    return out_path


def _to_edhrec_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[',.]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


# ══════════════════════════════════════════════════════════════
# Background Task — Run the Java CLI subprocess
# ══════════════════════════════════════════════════════════════

async def run_batch_subprocess(
    state: BatchState,
    decks: list[str],
    num_games: int,
    threads: int,
    seed: Optional[int],
    clock: int,
    output_path: str,
    use_learned_policy: bool = False,
    policy_style: str = "midrange",
    policy_greedy: bool = False,
    ai_simplified: bool = False,
    ai_think_time_ms: int = -1,
    max_queue_depth: int = -1,
):
    try:
        # Compute policy server URL from our own port
        policy_server = f"http://localhost:{CFG.port}"
        cmd = build_java_command(
            decks, num_games, threads, seed, clock, output_path,
            use_learned_policy=use_learned_policy,
            policy_server=policy_server,
            policy_style=policy_style,
            policy_greedy=policy_greedy,
            ai_simplified=ai_simplified,
            ai_think_time_ms=ai_think_time_ms,
            max_queue_depth=max_queue_depth,
        )
        log_batch.info(f"Starting batch {state.batch_id}: {' '.join(cmd[:6])}...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: _run_process_blocking(state, cmd),
        )
    except Exception as e:
        state.error = str(e)
        state.running = False
        log_batch.error(f"Batch {state.batch_id} ERROR: {e}")


def _run_process_blocking(state: BatchState, cmd: list[str]):
    # Write debug log from Python side (doesn't depend on Java rebuild)
    debug_log_path = Path(CFG.forge_dir).parent / "forge-sim-debug.log" if CFG.forge_dir else Path("forge-sim-debug.log")
    try:
        with open(debug_log_path, "a", encoding="utf-8") as dbg:
            dbg.write(f"\n{'='*60}\n")
            dbg.write(f"Batch {state.batch_id} @ {datetime.now().isoformat()}\n")
            dbg.write(f"Command: {' '.join(cmd)}\n")
            dbg.write(f"Lab JAR: {CFG.lab_jar}\n")
            dbg.write(f"Forge JAR: {CFG.forge_jar}\n")
            dbg.write(f"Forge Dir: {CFG.forge_dir}\n")
            dbg.write(f"Lab JAR exists: {os.path.exists(CFG.lab_jar)}\n")
            dbg.write(f"Forge JAR exists: {os.path.exists(CFG.forge_jar)}\n")
            dbg.write(f"Forge Dir exists: {os.path.isdir(CFG.forge_dir)}\n")
            dbg.write(f"{'-'*60}\n")
        log_batch.warning(f"Debug log: {debug_log_path}")
    except Exception as e:
        log_batch.warning(f"Could not write debug log header: {e}")

    # Ensure Forge subprocesses use Java 17 (Forge crashes on Java 25+)
    env = os.environ.copy()
    java17 = get_java17()
    if java17 != 'java':
        java17_bin = os.path.dirname(java17)
        java17_home = os.path.dirname(java17_bin)
        env['JAVA_HOME'] = java17_home
        env['PATH'] = java17_bin + os.pathsep + env.get('PATH', '')
        log_batch.info(f'Using Java 17: {java17}')

    # NOTE: Do NOT set _JAVA_OPTIONS=-Djava.awt.headless=true here.
    # Forge sim mode needs AWT classes for card data initialization;
    # headless=true causes silent exit code 1 crash.

    # Per-game timeout: clock + 180s buffer for card DB init
    per_game_timeout = state.total_games * 240 + 300  # generous: 4min/game + 5min startup

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=None,
            bufsize=1,
            env=env,
        )
        state.process = proc

        # Python-side watchdog: kill if no progress for too long
        import threading
        last_activity = [time.time()]
        stall_limit = 300  # 5 minutes with no output = stalled

        def _watchdog():
            while proc.poll() is None:
                time.sleep(30)
                elapsed_since_activity = time.time() - last_activity[0]
                if elapsed_since_activity > stall_limit:
                    log_batch.warning(f'WATCHDOG: No output for {int(elapsed_since_activity)}s. Killing process.')
                    state.log_lines.append(f'[WATCHDOG] Process stalled ({int(elapsed_since_activity)}s with no output). Killed.')
                    proc.kill()
                    return

        wd_thread = threading.Thread(target=_watchdog, daemon=True)
        wd_thread.start()

        game_count = 0
        all_output_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            last_activity[0] = time.time()
            state.log_lines.append(line)
            all_output_lines.append(line)

            if line.startswith("[Game "):
                try:
                    parts = line.split("]")[0]
                    nums = parts.replace("[Game ", "").split("/")
                    current = int(nums[0])
                    game_count = current
                    state.completed_games = current
                except (ValueError, IndexError):
                    pass

            # v24 (Issue #5): Parse real-time sims/sec from Java output
            if '[PROGRESS]' in line or '[BATCH]' in line:
                import re
                sps_match = re.search(r'([\d.]+)\s+sims/sec', line)
                if sps_match:
                    try:
                        state.sims_per_sec = float(sps_match.group(1))
                    except ValueError:
                        pass

            log_batch.info(f"  [{state.batch_id}] {line}")

        proc.wait()

        elapsed = int((datetime.now() - state.start_time).total_seconds() * 1000)
        state.elapsed_ms = elapsed
        state.running = False

        # Write all captured output to debug log
        try:
            with open(debug_log_path, "a", encoding="utf-8") as dbg:
                dbg.write(f"Exit code: {proc.returncode}\n")
                dbg.write(f"Total lines: {len(all_output_lines)}\n")
                dbg.write(f"Elapsed: {elapsed}ms\n")
                dbg.write(f"-- FULL SUBPROCESS OUTPUT --\n")
                if all_output_lines:
                    for ol in all_output_lines:
                        dbg.write(ol + "\n")
                else:
                    dbg.write("<< NO OUTPUT >>\n")
                dbg.write(f"-- END OUTPUT --\n\n")
        except Exception as e:
            log_batch.warning(f"Could not write debug log output: {e}")

        if proc.returncode != 0:
            if proc.returncode == -9 or proc.returncode == 137:
                state.error = 'Forge process killed by watchdog (stalled with no output). Check forge-sim-debug.log for details.'
            else:
                state.error = f'Java process exited with code {proc.returncode}. Check forge-sim-debug.log for details.'
        else:
            state.completed_games = state.total_games
            log_batch.info(f"Batch {state.batch_id} completed in {elapsed}ms")

            # Auto-generate deck reports for the coach
            if state.result_path and os.path.exists(state.result_path):
                try:
                    from coach.report_generator import generate_single_deck_report
                    lab_root = Path(__file__).parent
                    reports_dir = str(lab_root / "deck-reports")
                    updated = generate_single_deck_report(state.result_path, reports_dir)
                    if updated:
                        log_batch.info(f"Deck reports updated: {', '.join(updated)}")
                except Exception as rpt_err:
                    log_batch.info(f"Deck report generation failed (non-fatal): {rpt_err}")

    except Exception as e:
        state.error = str(e)
        state.running = False
        try:
            with open(debug_log_path, "a", encoding="utf-8") as dbg:
                dbg.write(f"EXCEPTION: {e}\n")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# DeepSeek Batch Sim (Python engine + LLM opponent)
# ══════════════════════════════════════════════════════════════

def _load_deck_cards_by_name(deck_name: str) -> list[dict]:
    """Load card data for a deck by name. Checks DB first, then .dck files.
    Each card dict includes 'is_commander' flag (0 or 1) when available."""
    # 1. Try deck builder DB
    try:
        conn = _get_db_conn()
        row = conn.execute(
            "SELECT id, commander_name FROM decks WHERE name = ? COLLATE NOCASE", (deck_name,)
        ).fetchone()
        if row:
            deck_id = row["id"]
            db_commander_name = row["commander_name"] or ""
            cards = conn.execute("""
                SELECT dc.card_name, dc.quantity, dc.is_commander,
                       ce.type_line, ce.cmc, ce.power, ce.toughness,
                       ce.oracle_text, ce.keywords, ce.mana_cost,
                       ce.color_identity
                FROM deck_cards dc
                LEFT JOIN (
                    SELECT scryfall_id, type_line, cmc, power, toughness,
                           oracle_text, keywords, mana_cost, color_identity
                    FROM collection_entries GROUP BY scryfall_id
                ) ce ON ce.scryfall_id = dc.scryfall_id
                WHERE dc.deck_id = ?
            """, (deck_id,)).fetchall()
            result = []
            for r in cards:
                is_cmdr = r["is_commander"] or 0
                # Also detect by deck-level commander_name match
                if not is_cmdr and db_commander_name and r["card_name"].lower() == db_commander_name.lower():
                    is_cmdr = 1
                for _ in range(r["quantity"] or 1):
                    result.append({
                        'name': r["card_name"],
                        'type_line': r["type_line"] or '',
                        'cmc': r["cmc"] or 0,
                        'power': r["power"] or '',
                        'toughness': r["toughness"] or '',
                        'oracle_text': r["oracle_text"] or '',
                        'keywords': r["keywords"] or '',
                        'mana_cost': r["mana_cost"] or '',
                        'is_commander': is_cmdr,
                        'color_identity': r["color_identity"] or '',
                    })
            if result:
                return result
    except Exception as e:
        log_sim.error(f"DB lookup failed for '{deck_name}': {e}")

    # 2. Try .dck file
    if CFG.forge_decks_dir and os.path.isdir(CFG.forge_decks_dir):
        dck_path = Path(CFG.forge_decks_dir) / f"{deck_name}.dck"
        if dck_path.exists():
            cards = []
            in_cards = False  # True when inside [Main], [Deck], or [Commander]
            with open(dck_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    low = line.lower()
                    if low in ('[main]', '[deck]', '[commander]'):
                        in_cards = True
                        continue
                    if line.startswith('['):
                        in_cards = False
                        continue
                    if in_cards and line:
                        parts = line.split(' ', 1)
                        if len(parts) == 2:
                            try:
                                qty = int(parts[0])
                                name = parts[1].strip()
                                for _ in range(qty):
                                    cards.append({'name': name, 'type_line': '', 'cmc': 0})
                            except ValueError:
                                pass
            if cards:
                return cards

    return []


def _run_deepseek_batch_thread(
    state: BatchState,
    deck_names: list[str],
    num_games: int,
    output_path: str,
):
    """Run batch simulation using Python sim engine + DeepSeek AI opponent."""
    try:
        import sys as _s, os as _o, time as _t
        src_dir = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), 'src')
        if src_dir not in _s.path:
            _s.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine
        from commander_ai_lab.sim.rules import enrich_card

        state.log_lines.append('[DeepSeek Batch] Initializing DeepSeek brain...')
        brain = _get_deepseek_brain()
        if brain and not brain._connected:
            brain.check_connection()
        if not brain or not brain._connected:
            state.error = 'DeepSeek LLM not connected. Go to Simulator > DeepSeek and connect first.'
            state.running = False
            return

        state.log_lines.append(f'[DeepSeek Batch] Connected to {brain.config.model}')

        # Load all decks
        # ── Look up historical win rates from past batch results ──
        deck_win_rates = {}  # deck_name -> float (0-100)
        try:
            results_dir = CFG.results_dir
            if _o.path.isdir(results_dir):
                for fname in sorted(_o.listdir(results_dir), reverse=True):
                    if fname.startswith('batch-') and fname.endswith('.json'):
                        try:
                            with open(_o.path.join(results_dir, fname), 'r') as rf:
                                past = json.loads(rf.read())
                            for dd in past.get('decks', []):
                                dname = dd.get('deckName', '')
                                wr = dd.get('winRate')
                                if dname and wr is not None and dname not in deck_win_rates:
                                    deck_win_rates[dname] = float(wr)
                        except Exception:
                            pass
        except Exception:
            pass

        loaded_decks = {}
        deck_meta = {}  # deck_name -> {commander_name, color_identity, archetype}
        for dn in deck_names:
            raw_cards = _load_deck_cards_by_name(dn)
            if not raw_cards:
                state.log_lines.append(f'[DeepSeek Batch] WARNING: Could not load deck "{dn}", skipping.')
                continue

            # Detect commander and color identity from card data
            commander_name = ''
            color_identity_set = set()
            deck_objs = []
            for cd in raw_cards:
                c = Card(name=cd['name'])
                if cd.get('type_line'): c.type_line = cd['type_line']
                if cd.get('cmc'): c.cmc = float(cd['cmc'])
                if cd.get('power') and cd.get('toughness'):
                    c.power = str(cd['power'])
                    c.toughness = str(cd['toughness'])
                    c.pt = c.power + '/' + c.toughness
                if cd.get('oracle_text'): c.oracle_text = cd['oracle_text']
                if cd.get('mana_cost'): c.mana_cost = cd['mana_cost']
                if cd.get('keywords'):
                    kw = cd['keywords']
                    if isinstance(kw, str):
                        try: kw = json.loads(kw)
                        except Exception: kw = []
                    if isinstance(kw, list): c.keywords = kw
                # Set is_commander flag from DB data
                if cd.get('is_commander'):
                    c.is_commander = True
                    commander_name = cd['name']
                # Collect color identity
                ci_str = cd.get('color_identity', '')
                if ci_str:
                    try:
                        ci_parsed = json.loads(ci_str) if isinstance(ci_str, str) else ci_str
                        if isinstance(ci_parsed, list):
                            for color in ci_parsed:
                                color_identity_set.add(color)
                    except Exception:
                        pass
                enrich_card(c)
                deck_objs.append(c)

            # Infer archetype from deck composition
            creature_count = sum(1 for c in deck_objs if c.is_creature())
            removal_count = sum(1 for c in deck_objs if c.is_removal)
            ramp_count = sum(1 for c in deck_objs if c.is_ramp)
            avg_cmc = sum(c.cmc or 0 for c in deck_objs if not c.is_land()) / max(sum(1 for c in deck_objs if not c.is_land()), 1)
            oracle_all = ' '.join((c.oracle_text or '').lower() for c in deck_objs)
            has_combo_text = any(kw in oracle_all for kw in ['you win the game', 'infinite', 'extra turn'])

            if has_combo_text:
                archetype = 'combo'
            elif creature_count >= 30 and avg_cmc <= 2.8:
                archetype = 'aggro'
            elif removal_count >= 10 or (creature_count <= 18 and avg_cmc >= 3.2):
                archetype = 'control'
            else:
                archetype = 'midrange'

            color_identity_list = sorted(list(color_identity_set))
            deck_meta[dn] = {
                'commander_name': commander_name,
                'color_identity': color_identity_list,
                'archetype': archetype,
                'win_rate': deck_win_rates.get(dn),
            }

            loaded_decks[dn] = deck_objs
            cmdr_info = f' (Commander: {commander_name})' if commander_name else ''
            wr_info = f' [History: {deck_win_rates[dn]:.0f}% WR]' if dn in deck_win_rates else ''
            state.log_lines.append(f'[DeepSeek Batch] Loaded deck "{dn}" ({len(deck_objs)} cards, {archetype}){cmdr_info}{wr_info}')

        if not loaded_decks:
            state.error = 'No decks could be loaded.'
            state.running = False
            return

        # Build matchup schedule: each deck plays num_games vs DeepSeek AI
        deck_list = list(loaded_decks.keys())
        games_per_deck = max(1, num_games // len(deck_list))
        total_games = games_per_deck * len(deck_list)
        state.total_games = total_games

        state.log_lines.append(f'[DeepSeek Batch] Running {games_per_deck} games per deck × {len(deck_list)} decks = {total_games} total')

        engine = DeepSeekGameEngine(
            brain=brain,
            ai_player_index=0,  # AI pilots deck_a (user's deck) with full intelligence
            max_turns=25,
            record_log=True,
            ml_log=True,
        )

        start_time = _t.time()
        all_deck_results = []
        completed = 0

        for deck_name in deck_list:
            deck_a = loaded_decks[deck_name]
            # Generate a training opponent for each game
            from commander_ai_lab.lab.experiments import _generate_training_deck

            deck_stats = {
                'deckName': deck_name,
                'wins': 0, 'losses': 0, 'totalGames': games_per_deck,
                'totalTurns': 0, 'totalDamageDealt': 0, 'totalDamageReceived': 0,
                'totalSpellsCast': 0, 'totalCreaturesPlayed': 0,
                'games': [],
            }

            meta = deck_meta.get(deck_name, {})
            dk_archetype = meta.get('archetype', 'midrange')
            dk_commander = meta.get('commander_name', '')
            dk_colors = meta.get('color_identity', [])
            dk_win_rate = meta.get('win_rate')

            for g in range(games_per_deck):
                try:
                    deck_b = _generate_training_deck()
                    game_id = f'ds-{state.batch_id}-{deck_name[:12]}-g{g+1}'
                    result = engine.run(
                        deck_a, deck_b,
                        name_a=deck_name + ' (AI)',
                        name_b='Training Opponent',
                        game_id=game_id, archetype=dk_archetype,
                        commander_name=dk_commander,
                        color_identity=dk_colors,
                        win_rate=dk_win_rate,
                    )
                    gd = result.to_dict()
                    gd['gameNumber'] = g + 1
                    deck_stats['games'].append(gd)

                    if result.winner == 0:
                        deck_stats['wins'] += 1
                    else:
                        deck_stats['losses'] += 1
                    deck_stats['totalTurns'] += result.turns
                    if result.player_a_stats:
                        deck_stats['totalDamageDealt'] += result.player_a_stats.damage_dealt
                        deck_stats['totalDamageReceived'] += result.player_a_stats.damage_received
                        deck_stats['totalSpellsCast'] += result.player_a_stats.spells_cast
                        deck_stats['totalCreaturesPlayed'] += result.player_a_stats.creatures_played

                    state.log_lines.append(
                        f'[Game {completed + 1}/{total_games}] {deck_name} (AI-piloted) → '
                        f'{"WIN" if result.winner == 0 else "LOSS"} (turn {result.turns})'
                    )
                except Exception as ge:
                    state.log_lines.append(f'[Game {completed + 1}/{total_games}] ERROR: {ge}')
                    deck_stats['games'].append({'error': str(ge), 'gameNumber': g + 1})

                completed += 1
                state.completed_games = completed

            n = deck_stats['totalGames']
            deck_stats['winRate'] = round(deck_stats['wins'] / n * 100, 1) if n > 0 else 0.0
            deck_stats['avgTurns'] = round(deck_stats['totalTurns'] / n, 1) if n > 0 else 0.0
            deck_stats['avgDamageDealt'] = round(deck_stats['totalDamageDealt'] / n, 1) if n > 0 else 0.0
            deck_stats['avgDamageReceived'] = round(deck_stats['totalDamageReceived'] / n, 1) if n > 0 else 0.0
            deck_stats['avgSpellsCast'] = round(deck_stats['totalSpellsCast'] / n, 1) if n > 0 else 0.0
            deck_stats['avgCreaturesPlayed'] = round(deck_stats['totalCreaturesPlayed'] / n, 1) if n > 0 else 0.0
            # Include deck intelligence metadata
            deck_stats['archetype'] = dk_archetype
            deck_stats['commander'] = dk_commander
            deck_stats['colorIdentity'] = dk_colors
            if dk_win_rate is not None:
                deck_stats['priorWinRate'] = dk_win_rate
            all_deck_results.append(deck_stats)

        elapsed = _t.time() - start_time
        ds_stats = brain.get_stats() if brain else {}

        # Build result in compatible format
        batch_result = {
            'metadata': {
                'batchId': state.batch_id,
                'timestamp': datetime.now().isoformat(),
                'completedGames': completed,
                'threads': 1,
                'elapsedMs': int(elapsed * 1000),
                'engine': 'deepseek',
                'model': brain.config.model if brain else 'unknown',
            },
            'decks': all_deck_results,
            'deepseekStats': ds_stats,
        }

        # Write ML decision JSONL for the training pipeline
        ml_decisions = engine.flush_ml_decisions()
        if ml_decisions:
            ml_jsonl_path = os.path.join(CFG.results_dir, f'ml-decisions-ds-{state.batch_id}.jsonl')
            os.makedirs(os.path.dirname(ml_jsonl_path) or '.', exist_ok=True)
            with open(ml_jsonl_path, 'w', encoding='utf-8') as mf:
                for dec in ml_decisions:
                    mf.write(json.dumps(dec) + '\n')
            state.log_lines.append(f'[ML Data] Wrote {len(ml_decisions)} decision snapshots to {os.path.basename(ml_jsonl_path)}')
        else:
            state.log_lines.append('[ML Data] No decision snapshots captured (0 decisions)')

        # Save to results dir
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(batch_result, f, indent=2, default=str)

        state.result_path = output_path
        elapsed_ms = int(elapsed * 1000)
        state.elapsed_ms = elapsed_ms
        state.running = False
        state.completed_games = total_games

        state.log_lines.append(f'[DeepSeek Batch] Complete: {completed} games in {elapsed:.1f}s')
        for ds in all_deck_results:
            state.log_lines.append(f'  {ds["deckName"]}: {ds["wins"]}W-{ds["losses"]}L ({ds["winRate"]}% WR)')

        log_sim.info(f'Batch {state.batch_id} complete: {completed} games in {elapsed:.1f}s')

    except Exception as e:
        import traceback
        state.error = str(e)
        state.running = False
        state.log_lines.append(f'[DeepSeek Batch] FATAL: {e}')
        traceback.print_exc()


@app.post('/api/lab/start-deepseek')
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


def _find_java17() -> str:
    """Auto-detect Java 17 for Forge subprocesses. Forge crashes on Java 25+."""
    import glob as _glob
    # Check common Adoptium/Oracle locations on Windows
    search_dirs = [
        r'C:\Program Files\Eclipse Adoptium',
        r'C:\Program Files\Java',
    ]
    for d in search_dirs:
        if os.path.isdir(d):
            for child in os.listdir(d):
                if child.startswith('jdk-17'):
                    candidate = os.path.join(d, child, 'bin', 'java.exe')
                    if os.path.isfile(candidate):
                        return candidate
    return 'java'  # fallback to system java

_JAVA17_PATH = None  # cached result

def get_java17() -> str:
    global _JAVA17_PATH
    if _JAVA17_PATH is None:
        _JAVA17_PATH = _find_java17()
    return _JAVA17_PATH


def build_java_command(
    decks: list[str],
    num_games: int,
    threads: int,
    seed: Optional[int],
    clock: int,
    output_path: str,
    use_learned_policy: bool = False,
    policy_server: str = "http://localhost:8080",
    policy_style: str = "midrange",
    policy_greedy: bool = False,
    # v24 (Issues #4/#5): Performance flags
    ai_simplified: bool = False,
    ai_think_time_ms: int = -1,
    max_queue_depth: int = -1,
) -> list[str]:
    java17 = get_java17()
    cmd = [
        java17, "-jar", CFG.lab_jar,
        "--forge-jar", CFG.forge_jar,
        "--forge-dir", CFG.forge_dir,
        "--deck1", decks[0],
        "--deck2", decks[1],
        "--deck3", decks[2],
        "--games", str(num_games),
        "--threads", str(threads),
        "--clock", str(clock),
        "--output", output_path,
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    if _ml_logging_enabled:
        cmd.append("--ml-log")
    if use_learned_policy:
        cmd.append("--learned-policy")
        cmd.extend(["--policy-server", policy_server])
        cmd.extend(["--policy-style", policy_style])
        if policy_greedy:
            cmd.append("--policy-greedy")
    # v24 (Issues #4/#5): Performance flags
    if ai_simplified:
        cmd.append("--ai-simplified")
    if ai_think_time_ms > 0:
        cmd.extend(["--ai-think-time", str(ai_think_time_ms)])
    if max_queue_depth > 0:
        cmd.extend(["--max-queue", str(max_queue_depth)])
    return cmd


# ══════════════════════════════════════════════════════════════
# Collection Database Setup
# ══════════════════════════════════════════════════════════════

COLLECTION_DB_PATH = Path(__file__).parent / "collection.db"
_db_local = threading.local()


def _get_db_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        conn = sqlite3.connect(str(COLLECTION_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _db_local.conn = conn
    return _db_local.conn


def init_collection_db():
    """Initialize the collection SQLite database with tables and indexes."""
    conn = sqlite3.connect(str(COLLECTION_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS card_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type_line TEXT DEFAULT '',
            subtypes TEXT DEFAULT '',
            is_legendary INTEGER DEFAULT 0,
            is_basic INTEGER DEFAULT 0,
            color_identity TEXT DEFAULT '',
            cmc REAL DEFAULT 0,
            oracle_text TEXT DEFAULT '',
            keywords TEXT DEFAULT '',
            tcg_price REAL DEFAULT 0,
            salt_score REAL DEFAULT 0,
            is_game_changer INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            scryfall_id TEXT DEFAULT '',
            tcgplayer_id TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS collection_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type_line TEXT DEFAULT '',
            subtypes TEXT DEFAULT '',
            is_legendary INTEGER DEFAULT 0,
            is_basic INTEGER DEFAULT 0,
            color_identity TEXT DEFAULT '',
            cmc REAL DEFAULT 0,
            mana_cost TEXT DEFAULT '',
            oracle_text TEXT DEFAULT '',
            keywords TEXT DEFAULT '',
            power TEXT DEFAULT '',
            toughness TEXT DEFAULT '',
            rarity TEXT DEFAULT '',
            set_name TEXT DEFAULT '',
            edhrec_rank INTEGER DEFAULT 0,
            tcg_price REAL DEFAULT 0,
            salt_score REAL DEFAULT 0,
            is_game_changer INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            scryfall_id TEXT DEFAULT '',
            tcgplayer_id TEXT DEFAULT '',
            quantity INTEGER DEFAULT 1,
            finish TEXT DEFAULT 'NORMAL',
            condition TEXT DEFAULT '',
            language TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            set_code TEXT DEFAULT '',
            collector_number TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_ce_name ON collection_entries(name);
        CREATE INDEX IF NOT EXISTS idx_ce_color_identity ON collection_entries(color_identity);
        CREATE INDEX IF NOT EXISTS idx_ce_type_line ON collection_entries(type_line);
        CREATE INDEX IF NOT EXISTS idx_ce_is_legendary ON collection_entries(is_legendary);
        CREATE INDEX IF NOT EXISTS idx_ce_cmc ON collection_entries(cmc);
        CREATE INDEX IF NOT EXISTS idx_ce_category ON collection_entries(category);
        CREATE INDEX IF NOT EXISTS idx_ce_set_code ON collection_entries(set_code);
        CREATE INDEX IF NOT EXISTS idx_ce_collector_number ON collection_entries(collector_number);
        CREATE INDEX IF NOT EXISTS idx_ce_finish ON collection_entries(finish);

        CREATE INDEX IF NOT EXISTS idx_cr_name ON card_records(name);

        CREATE TABLE IF NOT EXISTS decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            commander_scryfall_id TEXT DEFAULT '',
            commander_name TEXT DEFAULT '',
            color_identity TEXT DEFAULT '[]',
            strategy_tag TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS deck_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            scryfall_id TEXT NOT NULL,
            card_name TEXT DEFAULT '',
            quantity INTEGER DEFAULT 1,
            is_commander INTEGER DEFAULT 0,
            role_tag TEXT DEFAULT '',
            FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_dc_deck_id ON deck_cards(deck_id);
        CREATE INDEX IF NOT EXISTS idx_dc_scryfall_id ON deck_cards(scryfall_id);
        CREATE INDEX IF NOT EXISTS idx_dk_commander ON decks(commander_scryfall_id);
    """)

    conn.commit()

    # ── Migration: add columns to existing DBs ─────────────────
    _migrate_columns = [
        ("mana_cost", "TEXT DEFAULT ''"),
        ("power", "TEXT DEFAULT ''"),
        ("toughness", "TEXT DEFAULT ''"),
        ("rarity", "TEXT DEFAULT ''"),
        ("set_name", "TEXT DEFAULT ''"),
        ("edhrec_rank", "INTEGER DEFAULT 0"),
    ]
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(collection_entries)").fetchall()}
    for col_name, col_def in _migrate_columns:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE collection_entries ADD COLUMN {col_name} {col_def}")
            log_collect.info(f"  Migration: added column '{col_name}' to collection_entries")
    conn.commit()
    conn.close()
    log_collect.info(f"  Collection DB: {COLLECTION_DB_PATH}")


# Fields stored as JSON strings in SQLite that should be returned as parsed arrays
_JSON_FIELDS = ("category", "color_identity", "subtypes", "keywords")


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict, parsing JSON array fields."""
    if row is None:
        return None
    d = dict(row)
    for f in _JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                d[f] = []
    return d


def _snake_to_camel(s: str) -> str:
    """Convert snake_case to camelCase."""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _add_image_url(card: dict) -> dict:
    """Add imageUrl field and camelCase aliases for JS consumption."""
    scryfall_id = card.get("scryfall_id", "")
    if scryfall_id:
        card["imageUrl"] = f"https://api.scryfall.com/cards/{scryfall_id}?format=image&version=normal"
    else:
        card["imageUrl"] = None
    # Add camelCase aliases for all snake_case keys
    for key in list(card.keys()):
        if "_" in key:
            camel = _snake_to_camel(key)
            if camel not in card:
                card[camel] = card[key]
    return card


def _build_collection_filters(
    q: Optional[str] = None,
    colors: Optional[str] = None,
    types: Optional[str] = None,
    isLegendary: Optional[bool] = None,
    isBasic: Optional[bool] = None,
    isGameChanger: Optional[bool] = None,
    highSalt: Optional[bool] = None,
    finish: Optional[str] = None,
    cmcMin: Optional[float] = None,
    cmcMax: Optional[float] = None,
    priceMin: Optional[float] = None,
    priceMax: Optional[float] = None,
    category: Optional[str] = None,
    rarity: Optional[str] = None,
    setCode: Optional[str] = None,
    powerMin: Optional[str] = None,
    powerMax: Optional[str] = None,
    toughMin: Optional[str] = None,
    toughMax: Optional[str] = None,
    keyword: Optional[str] = None,
    edhrecMin: Optional[int] = None,
    edhrecMax: Optional[int] = None,
    qtyMin: Optional[int] = None,
    qtyMax: Optional[int] = None,
) -> tuple:
    """Build WHERE clause and params for collection queries. Returns (where_str, params_list)."""
    conditions = []
    params = []

    if q:
        like_q = f"%{q}%"
        conditions.append("(name LIKE ? OR type_line LIKE ? OR oracle_text LIKE ?)")
        params.extend([like_q, like_q, like_q])

    if colors:
        color_list = [c.strip().upper() for c in colors.split(",") if c.strip()]
        for color in color_list:
            conditions.append("color_identity LIKE ?")
            params.append(f'%"{color}"%')

    if types:
        type_list = [t.strip() for t in types.split(",") if t.strip()]
        type_conditions = []
        for t in type_list:
            type_conditions.append("type_line LIKE ?")
            params.append(f"%{t}%")
        if type_conditions:
            conditions.append(f"({' OR '.join(type_conditions)})")

    if isLegendary is not None:
        conditions.append("is_legendary = ?")
        params.append(1 if isLegendary else 0)

    if isBasic is not None:
        conditions.append("is_basic = ?")
        params.append(1 if isBasic else 0)

    if isGameChanger is not None:
        conditions.append("is_game_changer = ?")
        params.append(1 if isGameChanger else 0)

    if highSalt:
        conditions.append("salt_score > 2.0")

    if finish:
        conditions.append("finish = ?")
        params.append(finish.upper())

    if cmcMin is not None:
        conditions.append("cmc >= ?")
        params.append(cmcMin)

    if cmcMax is not None:
        conditions.append("cmc <= ?")
        params.append(cmcMax)

    if priceMin is not None:
        conditions.append("tcg_price >= ?")
        params.append(priceMin)

    if priceMax is not None:
        conditions.append("tcg_price <= ?")
        params.append(priceMax)

    if category:
        cat_list = [c.strip() for c in category.split(",") if c.strip()]
        cat_conditions = []
        for c in cat_list:
            cat_conditions.append("category LIKE ?")
            params.append(f'%"{c}"%')
        if cat_conditions:
            conditions.append(f"({' OR '.join(cat_conditions)})")

    # ── New filters ──

    if rarity:
        rar_list = [r.strip().lower() for r in rarity.split(",") if r.strip()]
        if rar_list:
            placeholders = ",".join(["?"] * len(rar_list))
            conditions.append(f"LOWER(rarity) IN ({placeholders})")
            params.extend(rar_list)

    if setCode:
        set_list = [s.strip().upper() for s in setCode.split(",") if s.strip()]
        if set_list:
            placeholders = ",".join(["?"] * len(set_list))
            conditions.append(f"UPPER(set_code) IN ({placeholders})")
            params.extend(set_list)

    if powerMin is not None:
        conditions.append("CAST(power AS REAL) >= ?")
        params.append(float(powerMin))

    if powerMax is not None:
        conditions.append("CAST(power AS REAL) <= ?")
        params.append(float(powerMax))

    if toughMin is not None:
        conditions.append("CAST(toughness AS REAL) >= ?")
        params.append(float(toughMin))

    if toughMax is not None:
        conditions.append("CAST(toughness AS REAL) <= ?")
        params.append(float(toughMax))

    if keyword:
        kw_list = [k.strip() for k in keyword.split(",") if k.strip()]
        for kw in kw_list:
            conditions.append("keywords LIKE ?")
            params.append(f"%{kw}%")

    if edhrecMin is not None:
        conditions.append("edhrec_rank >= ?")
        params.append(edhrecMin)

    if edhrecMax is not None:
        conditions.append("edhrec_rank <= ?")
        params.append(edhrecMax)

    if qtyMin is not None:
        conditions.append("quantity >= ?")
        params.append(qtyMin)

    if qtyMax is not None:
        conditions.append("quantity <= ?")
        params.append(qtyMax)

    where_str = ""
    if conditions:
        where_str = "WHERE " + " AND ".join(conditions)

    return where_str, params


# ══════════════════════════════════════════════════════════════
# Collection CRUD Endpoints
# ══════════════════════════════════════════════════════════════

VALID_SORT_FIELDS = {"name", "cmc", "tcg_price", "salt_score", "category", "color_identity", "quantity", "type_line", "finish", "rarity", "set_code", "power", "toughness", "edhrec_rank"}


@app.get("/api/collection/export")
async def export_collection(
    format: str = "INTERNAL_CSV",
    q: Optional[str] = None,
    colors: Optional[str] = None,
    types: Optional[str] = None,
    isLegendary: Optional[bool] = None,
    isBasic: Optional[bool] = None,
    isGameChanger: Optional[bool] = None,
    highSalt: Optional[bool] = None,
    finish: Optional[str] = None,
    cmcMin: Optional[float] = None,
    cmcMax: Optional[float] = None,
    priceMin: Optional[float] = None,
    priceMax: Optional[float] = None,
    category: Optional[str] = None,
):
    """Export collection in various formats with optional filters."""
    where_str, params = _build_collection_filters(
        q=q, colors=colors, types=types, isLegendary=isLegendary,
        isBasic=isBasic, isGameChanger=isGameChanger, highSalt=highSalt,
        finish=finish, cmcMin=cmcMin, cmcMax=cmcMax,
        priceMin=priceMin, priceMax=priceMax, category=category,
    )

    sql = f"SELECT * FROM collection_entries {where_str} ORDER BY name ASC"
    conn = _get_db_conn()
    rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]

    fmt = format.upper()
    output = io.StringIO()

    if fmt == "INTERNAL_CSV":
        if rows:
            fieldnames = list(rows[0].keys())
        else:
            fieldnames = [
                "id", "name", "type_line", "subtypes", "is_legendary", "is_basic",
                "color_identity", "cmc", "oracle_text", "keywords", "tcg_price",
                "salt_score", "is_game_changer", "category", "scryfall_id", "tcgplayer_id",
                "quantity", "finish", "condition", "language", "notes", "tags",
                "set_code", "collector_number", "created_at", "updated_at",
            ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        filename = "collection_export.csv"
        media_type = "text/csv"

    elif fmt == "MOXFIELD_CSV":
        fieldnames = ["Count", "Name", "Edition", "Condition", "Language", "Foil", "Collector Number"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            finish_val = row.get("finish", "NORMAL").upper()
            foil_val = "foil" if finish_val == "FOIL" else ("etched" if finish_val == "ETCHED" else "")
            writer.writerow({
                "Count": row.get("quantity", 1),
                "Name": row.get("name", ""),
                "Edition": row.get("set_code", "").upper(),
                "Condition": row.get("condition", ""),
                "Language": row.get("language", ""),
                "Foil": foil_val,
                "Collector Number": row.get("collector_number", ""),
            })
        filename = "collection_moxfield.csv"
        media_type = "text/csv"

    elif fmt == "TEXT":
        lines = []
        for row in rows:
            qty = row.get("quantity", 1)
            name = row.get("name", "")
            set_code = row.get("set_code", "").upper()
            coll_num = row.get("collector_number", "")
            if set_code and coll_num:
                lines.append(f"{qty} {name} ({set_code}) {coll_num}")
            elif set_code:
                lines.append(f"{qty} {name} ({set_code})")
            else:
                lines.append(f"{qty} {name}")
        output.write("\n".join(lines))
        filename = "collection_export.txt"
        media_type = "text/plain"

    else:
        raise HTTPException(400, f"Unknown format: {format}. Use INTERNAL_CSV, MOXFIELD_CSV, or TEXT.")

    content = output.getvalue()

    def iter_content():
        yield content.encode("utf-8")

    return StreamingResponse(
        iter_content(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/collection/sets")
async def collection_sets():
    """Return distinct set codes + names in the collection (for filter autocomplete)."""
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT DISTINCT UPPER(set_code) as code, set_name as name FROM collection_entries WHERE set_code != '' ORDER BY set_name ASC"
    ).fetchall()
    result = []
    for r in rows:
        code = r["code"] if "code" in r.keys() else r[0]
        name = r["name"] if "name" in r.keys() else r[1]
        if code:
            result.append({"code": code, "name": name or code})
    return JSONResponse(result)


@app.get("/api/collection/keywords")
async def collection_keywords():
    """Return distinct keywords found in the collection."""
    conn = _get_db_conn()
    rows = conn.execute("SELECT keywords FROM collection_entries WHERE keywords != '' AND keywords != '[]'").fetchall()
    kw_set = set()
    for r in rows:
        try:
            kws = json.loads(r["keywords"]) if isinstance(r["keywords"], str) else r["keywords"]
            if isinstance(kws, list):
                for k in kws:
                    if k:
                        kw_set.add(k)
        except (json.JSONDecodeError, TypeError):
            pass
    return JSONResponse(sorted(kw_set))


@app.get("/api/collection")
async def list_collection(
    page: int = 1,
    pageSize: int = 50,
    q: Optional[str] = None,
    sortField: Optional[str] = None,
    sortDir: Optional[str] = None,
    colors: Optional[str] = None,
    types: Optional[str] = None,
    isLegendary: Optional[bool] = None,
    isBasic: Optional[bool] = None,
    isGameChanger: Optional[bool] = None,
    highSalt: Optional[bool] = None,
    finish: Optional[str] = None,
    cmcMin: Optional[float] = None,
    cmcMax: Optional[float] = None,
    priceMin: Optional[float] = None,
    priceMax: Optional[float] = None,
    category: Optional[str] = None,
    deck_id: Optional[int] = None,
    rarity: Optional[str] = None,
    setCode: Optional[str] = None,
    powerMin: Optional[str] = None,
    powerMax: Optional[str] = None,
    toughMin: Optional[str] = None,
    toughMax: Optional[str] = None,
    keyword: Optional[str] = None,
    edhrecMin: Optional[int] = None,
    edhrecMax: Optional[int] = None,
    qtyMin: Optional[int] = None,
    qtyMax: Optional[int] = None,
):
    """List collection entries with search, sort, and filter.
    Optional deck_id: when provided, includes in_deck_quantity for each result.
    """
    where_str, params = _build_collection_filters(
        q=q, colors=colors, types=types, isLegendary=isLegendary,
        isBasic=isBasic, isGameChanger=isGameChanger, highSalt=highSalt,
        finish=finish, cmcMin=cmcMin, cmcMax=cmcMax,
        priceMin=priceMin, priceMax=priceMax, category=category,
        rarity=rarity, setCode=setCode, powerMin=powerMin, powerMax=powerMax,
        toughMin=toughMin, toughMax=toughMax, keyword=keyword,
        edhrecMin=edhrecMin, edhrecMax=edhrecMax, qtyMin=qtyMin, qtyMax=qtyMax,
    )

    # Validate sort
    sort_field = sortField if sortField in VALID_SORT_FIELDS else "name"
    sort_dir = "DESC" if (sortDir or "").upper() == "DESC" else "ASC"

    conn = _get_db_conn()

    # Count total
    count_sql = f"SELECT COUNT(*) FROM collection_entries {where_str}"
    total = conn.execute(count_sql, params).fetchone()[0]

    # Paginate
    offset = (max(1, page) - 1) * pageSize
    data_sql = f"""
        SELECT * FROM collection_entries {where_str}
        ORDER BY {sort_field} {sort_dir}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(data_sql, params + [pageSize, offset]).fetchall()
    items = [_add_image_url(_row_to_dict(r)) for r in rows]

    # If deck_id provided, annotate each item with how many copies are already in that deck
    if deck_id is not None:
        # Build a map of scryfall_id -> quantity in deck
        deck_card_rows = conn.execute(
            "SELECT scryfall_id, SUM(quantity) as qty FROM deck_cards WHERE deck_id = ? GROUP BY scryfall_id",
            (deck_id,)
        ).fetchall()
        in_deck_map = {row["scryfall_id"]: row["qty"] for row in deck_card_rows}
        for item in items:
            item["in_deck_quantity"] = in_deck_map.get(item.get("scryfall_id", ""), 0)

    return {"items": items, "page": page, "pageSize": pageSize, "total": total}


@app.get("/api/collection/{cardId}")
async def get_collection_card(cardId: int):
    """Get a single collection entry by ID."""
    conn = _get_db_conn()
    row = conn.execute("SELECT * FROM collection_entries WHERE id = ?", (cardId,)).fetchone()
    if not row:
        raise HTTPException(404, f"Card with id {cardId} not found")
    return _add_image_url(_row_to_dict(row))


@app.patch("/api/collection/{cardId}")
async def update_collection_card(cardId: int, body: dict):
    """Update mutable fields of a collection entry."""
    conn = _get_db_conn()
    row = conn.execute("SELECT * FROM collection_entries WHERE id = ?", (cardId,)).fetchone()
    if not row:
        raise HTTPException(404, f"Card with id {cardId} not found")

    updates = {}
    if "category" in body:
        cat = body["category"]
        if isinstance(cat, list):
            updates["category"] = json.dumps(cat)
        else:
            updates["category"] = cat
    if "tags" in body:
        updates["tags"] = str(body["tags"])
    if "notes" in body:
        updates["notes"] = str(body["notes"])
    if "finish" in body:
        finish_val = str(body["finish"]).upper()
        if finish_val not in ("NORMAL", "FOIL", "ETCHED"):
            raise HTTPException(400, "finish must be NORMAL, FOIL, or ETCHED")
        updates["finish"] = finish_val

    if not updates:
        return _add_image_url(_row_to_dict(row))

    updates["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [cardId]
    conn.execute(f"UPDATE collection_entries SET {set_clause} WHERE id = ?", values)
    conn.commit()

    updated_row = conn.execute("SELECT * FROM collection_entries WHERE id = ?", (cardId,)).fetchone()
    return _add_image_url(_row_to_dict(updated_row))


# ══════════════════════════════════════════════════════════════
# Collection Import Helpers
# ══════════════════════════════════════════════════════════════

# ── Scryfall Response Cache ─────────────────────────────────
# SQLite-backed cache for Scryfall API responses.
# Keyed by (name, set_code, collector_number). Default TTL: 7 days.
# Scryfall data changes infrequently (set releases ~every 3 months).
# Eliminates redundant HTTP calls across imports and re-enrichments.

SCRYFALL_CACHE_DB_PATH = Path(__file__).parent / "scryfall_cache.db"
SCRYFALL_CACHE_TTL_SECONDS = int(os.environ.get("SCRYFALL_CACHE_TTL", 7 * 24 * 3600))  # 7 days


class _ScryfallCache:
    """
    Thread-safe SQLite cache for raw Scryfall JSON responses.

    Schema:
        cache_key  TEXT PRIMARY KEY  — "name|set|cn" normalised lowercase
        json_blob  TEXT              — raw Scryfall API JSON response
        fetched_at TEXT              — ISO-8601 UTC timestamp
    """

    def __init__(self, db_path: Path = None, ttl_seconds: int = None):
        self._db_path = db_path or SCRYFALL_CACHE_DB_PATH
        self._ttl = ttl_seconds or SCRYFALL_CACHE_TTL_SECONDS
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._hits = 0
        self._misses = 0
        self._init_db()

    # ── internal ────────────────────────────────────────────

    def _init_db(self):
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scryfall_cache (
                cache_key  TEXT PRIMARY KEY,
                json_blob  TEXT    NOT NULL,
                fetched_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    @staticmethod
    def _make_key(name: str, set_code: str, collector_number: str) -> str:
        return f"{name.strip().lower()}|{(set_code or '').strip().lower()}|{(collector_number or '').strip()}"

    # ── public API ──────────────────────────────────────────

    def get(self, name: str, set_code: str = "", collector_number: str = "") -> Optional[dict]:
        """Return cached Scryfall JSON dict, or None if missing / expired."""
        key = self._make_key(name, set_code, collector_number)
        with self._lock:
            row = self._conn.execute(
                "SELECT json_blob, fetched_at FROM scryfall_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if not row:
            self._misses += 1
            return None
        # TTL check
        try:
            fetched = datetime.fromisoformat(row[1])
            age = (datetime.utcnow() - fetched).total_seconds()
            if age > self._ttl:
                self._misses += 1
                return None
        except (ValueError, TypeError):
            self._misses += 1
            return None
        self._hits += 1
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            self._misses += 1
            return None

    def put(self, name: str, set_code: str, collector_number: str, card_data: dict):
        """Store a Scryfall response in the cache."""
        key = self._make_key(name, set_code, collector_number)
        blob = json.dumps(card_data, separators=(",", ":"))
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO scryfall_cache (cache_key, json_blob, fetched_at) "
                "VALUES (?, ?, datetime('now'))",
                (key, blob),
            )
            self._conn.commit()

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM scryfall_cache").fetchone()[0]
            oldest_row = self._conn.execute(
                "SELECT MIN(fetched_at) FROM scryfall_cache"
            ).fetchone()
            newest_row = self._conn.execute(
                "SELECT MAX(fetched_at) FROM scryfall_cache"
            ).fetchone()
            db_size_bytes = os.path.getsize(str(self._db_path)) if self._db_path.exists() else 0
        return {
            "total_entries": total,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(self._hits + self._misses, 1) * 100, 1),
            "ttl_seconds": self._ttl,
            "ttl_days": round(self._ttl / 86400, 1),
            "oldest_entry": oldest_row[0] if oldest_row else None,
            "newest_entry": newest_row[0] if newest_row else None,
            "db_size_kb": round(db_size_bytes / 1024, 1),
            "db_path": str(self._db_path),
        }

    def clear(self) -> int:
        """Delete all cached entries. Returns count of deleted rows."""
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM scryfall_cache").fetchone()[0]
            self._conn.execute("DELETE FROM scryfall_cache")
            self._conn.commit()
            self._conn.execute("VACUUM")  # must run outside transaction
            self._hits = 0
            self._misses = 0
        return count

    def evict_expired(self) -> int:
        """Remove entries older than TTL. Returns count of evicted rows."""
        cutoff = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "DELETE FROM scryfall_cache WHERE "
                "(julianday(?) - julianday(fetched_at)) * 86400 > ?",
                (cutoff, self._ttl),
            )
            deleted = self._conn.total_changes
            self._conn.commit()
        return deleted


_scryfall_cache = _ScryfallCache()


# Scryfall rate-limit semaphore (max 10 req/sec)
_scryfall_lock = threading.Lock()
_scryfall_last_call = 0.0


def _scryfall_rate_limit():
    """Enforce at most 10 Scryfall requests per second via simple sleep."""
    global _scryfall_last_call
    with _scryfall_lock:
        now = time.monotonic()
        elapsed = now - _scryfall_last_call
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        _scryfall_last_call = time.monotonic()


def _parse_finish(raw: str) -> str:
    """Normalize finish string to NORMAL|FOIL|ETCHED."""
    if not raw:
        return "NORMAL"
    r = raw.strip().lower()
    if r in ("etched", "foil etched", "foil_etched", "etched foil"):
        return "ETCHED"
    if r in ("yes", "foil", "true", "1"):
        return "FOIL"
    return "NORMAL"


def _parse_text_line(line: str) -> dict:
    """
    Parse a text import line into {name, quantity, set_code, collector_number}.
    Supports formats:
      - "3 Sol Ring (CMR) 123"
      - "1x Sol Ring (CMR)"
      - "Sol Ring [CMR:123]"
      - "1 Sol Ring"
    """
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return {}

    result = {"name": "", "quantity": 1, "set_code": "", "collector_number": ""}

    # Strip quantity prefix
    qty_match = re.match(r"^(\d+)x?\s+", line)
    if qty_match:
        result["quantity"] = int(qty_match.group(1))
        line = line[qty_match.end():]

    # Format: "Name [SET:CollNum]"
    bracket_match = re.search(r"\[([A-Za-z0-9]+):(\S+)\]\s*$", line)
    if bracket_match:
        result["set_code"] = bracket_match.group(1).lower()
        result["collector_number"] = bracket_match.group(2)
        line = line[:bracket_match.start()].strip()
        result["name"] = line
        return result

    # Format: "Name (SET) CollNum"
    paren_coll_match = re.search(r"\(([A-Za-z0-9]+)\)\s+(\S+)\s*$", line)
    if paren_coll_match:
        result["set_code"] = paren_coll_match.group(1).lower()
        result["collector_number"] = paren_coll_match.group(2)
        line = line[:paren_coll_match.start()].strip()
        result["name"] = line
        return result

    # Format: "Name (SET)"
    paren_match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", line)
    if paren_match:
        result["set_code"] = paren_match.group(1).lower()
        line = line[:paren_match.start()].strip()
        result["name"] = line
        return result

    result["name"] = line.strip()
    return result


def _auto_infer_mapping(headers: list) -> dict:
    """
    Auto-infer column → field mapping from header names.
    Returns dict of {header: field_key}.
    Field keys: name, quantity, set_code, collector_number, finish, condition, language, notes, tags
    """
    mapping = {}
    header_lower = {h: h.lower().strip() for h in headers}
    field_patterns = {
        "name": ["name", "card name", "card_name", "cardname", "title"],
        "quantity": ["quantity", "qty", "count", "amount", "number", "#"],
        "set_code": ["set", "set code", "set_code", "edition", "set_name", "edition code"],
        "collector_number": [
            "collector number", "collector_number", "collectornumber",
            "col #", "col#", "number", "card number",
        ],
        "finish": ["finish", "foil", "printing", "treatment"],
        "condition": ["condition", "cond", "grade"],
        "language": ["language", "lang", "locale"],
        "notes": ["notes", "note", "comments", "comment"],
        "tags": ["tags", "tag", "labels", "label"],
    }
    for header, lower_h in header_lower.items():
        for field, patterns in field_patterns.items():
            if lower_h in patterns:
                mapping[header] = field
                break
    return mapping


def _parse_csv_content(content: str, source: str, mapping: Optional[dict]) -> list:
    """
    Parse CSV/text content into a list of RawImportRow dicts.
    Returns list of dicts with keys: name, quantity, set_code, collector_number, finish, condition, language, notes, tags
    """
    rows = []
    source_upper = (source or "").upper()

    if source_upper == "TEXT":
        for line in content.splitlines():
            parsed = _parse_text_line(line)
            if parsed.get("name"):
                rows.append(parsed)
        return rows

    # CSV-based sources
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []

    # Build effective mapping
    if mapping:
        col_map = {h: mapping.get(h, "") for h in headers}
    else:
        col_map = _auto_infer_mapping(headers)

    # Normalize col_map field values to lowercase so both "NAME" (UI) and "name" (auto-infer) work
    col_map = {h: (v.lower() if isinstance(v, str) else v) for h, v in col_map.items()}

    for csv_row in reader:
        row = {
            "name": "",
            "quantity": 1,
            "set_code": "",
            "collector_number": "",
            "finish": "NORMAL",
            "condition": "",
            "language": "",
            "notes": "",
            "tags": "",
        }
        for header, field in col_map.items():
            val = csv_row.get(header, "").strip()
            if not val or field == "ignore" or not field:
                continue
            if field == "name":
                # Strip finish suffix like "(Foil Etched)"
                val = re.sub(r"\s*\(foil(?: etched)?\)\s*$", "", val, flags=re.IGNORECASE).strip()
                row["name"] = val
            elif field == "quantity":
                try:
                    row["quantity"] = int(float(val))
                except ValueError:
                    row["quantity"] = 1
            elif field in ("set_code", "set_code_secondary"):
                row["set_code"] = val.lower()
            elif field in ("collector_number", "collector_number_secondary"):
                row["collector_number"] = val
            elif field == "finish":
                row["finish"] = _parse_finish(val)
            elif field == "condition":
                row["condition"] = val
            elif field == "language":
                row["language"] = val
            elif field == "notes":
                row["notes"] = val
            elif field == "tags":
                row["tags"] = val

        if row["name"]:
            rows.append(row)

    return rows


def _fetch_scryfall_api(name: str, set_code: str = "", collector_number: str = "") -> dict:
    """
    Fetch raw card data from Scryfall API (with caching).
    Returns the raw Scryfall JSON dict, or a dict with '_error' on failure.
    Cache is checked first; live HTTP call only on miss.
    """
    from urllib.parse import quote

    # ── Cache check ──────────────────────────────────────
    cached = _scryfall_cache.get(name, set_code, collector_number)
    if cached is not None:
        return cached

    # ── Live fetch ───────────────────────────────────────
    card_data = None
    last_error = ""

    # Try set + collector number first
    if set_code and collector_number:
        _scryfall_rate_limit()
        try:
            url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
            req = Request(url, headers=_API_HEADERS)
            with urlopen(req, timeout=10) as resp:
                card_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = str(e)
            card_data = None

    # Fall back to exact name lookup
    if not card_data:
        _scryfall_rate_limit()
        try:
            encoded_name = quote(name)
            url = f"https://api.scryfall.com/cards/named?exact={encoded_name}"
            req = Request(url, headers=_API_HEADERS)
            with urlopen(req, timeout=10) as resp:
                card_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = str(e)
            return {"_error": f"Scryfall lookup failed for '{name}': {last_error}"}

    if not card_data or card_data.get("object") == "error":
        err_detail = card_data.get("details", "unknown error") if card_data else last_error
        return {"_error": f"Scryfall returned error for '{name}': {err_detail}"}

    # ── Cache the successful response ────────────────────
    _scryfall_cache.put(name, set_code, collector_number, card_data)
    # Also cache under the Scryfall-resolved name (handles spelling normalisation)
    resolved_name = card_data.get("name", "")
    if resolved_name and resolved_name.lower() != name.strip().lower():
        _scryfall_cache.put(resolved_name, set_code, collector_number, card_data)

    return card_data


def _enrich_from_scryfall(name: str, set_code: str = "", collector_number: str = "") -> dict:
    """
    Fetch card data from Scryfall (cached) and return enriched fields dict.
    Tries set+collectorNumber first, then exact name lookup.
    Returns empty dict on failure.
    """
    card_data = _fetch_scryfall_api(name, set_code, collector_number)

    if not card_data or "_error" in card_data:
        return card_data or {}

    # Extract fields
    type_line = card_data.get("type_line", "")
    color_identity = card_data.get("color_identity", [])
    keywords = card_data.get("keywords", [])

    # Parse subtypes (after em-dash or hyphen)
    subtypes = []
    for sep in [" \u2014 ", " - "]:
        if sep in type_line:
            parts = type_line.split(sep, 1)
            subtypes = [s.strip() for s in parts[1].split() if s.strip()]
            break

    is_legendary = 1 if "Legendary" in type_line else 0
    is_basic = 1 if "Basic" in type_line else 0

    # Get price
    prices = card_data.get("prices", {})
    tcg_price = 0.0
    try:
        price_val = prices.get("usd") or prices.get("usd_foil") or "0"
        tcg_price = float(price_val) if price_val else 0.0
    except (ValueError, TypeError):
        tcg_price = 0.0

    # Handle double-faced cards: oracle_text may be on card_faces
    oracle_text = card_data.get("oracle_text", "")
    if not oracle_text and card_data.get("card_faces"):
        face_texts = [f.get("oracle_text", "") for f in card_data["card_faces"]]
        oracle_text = "\n//\n".join(t for t in face_texts if t)

    # Power/toughness (may be on card_faces for DFCs)
    power = card_data.get("power", "")
    toughness = card_data.get("toughness", "")
    if not power and card_data.get("card_faces"):
        power = card_data["card_faces"][0].get("power", "")
        toughness = card_data["card_faces"][0].get("toughness", "")

    # Mana cost (may be on card_faces for DFCs)
    mana_cost = card_data.get("mana_cost", "")
    if not mana_cost and card_data.get("card_faces"):
        mana_cost = card_data["card_faces"][0].get("mana_cost", "")

    # Auto-detect functional categories
    auto_roles = _detect_card_roles(oracle_text, type_line, keywords)

    return {
        "name": card_data.get("name", name),
        "type_line": type_line,
        "subtypes": json.dumps(subtypes),
        "is_legendary": is_legendary,
        "is_basic": is_basic,
        "color_identity": json.dumps(color_identity),
        "cmc": card_data.get("cmc", 0.0),
        "mana_cost": mana_cost,
        "oracle_text": oracle_text,
        "keywords": json.dumps(keywords),
        "power": power or "",
        "toughness": toughness or "",
        "rarity": card_data.get("rarity", ""),
        "set_name": card_data.get("set_name", ""),
        "edhrec_rank": card_data.get("edhrec_rank", 0) or 0,
        "tcg_price": tcg_price,
        "salt_score": 0.0,
        "is_game_changer": 0,
        "category": json.dumps(auto_roles),
        "scryfall_id": card_data.get("id", ""),
        "tcgplayer_id": str(card_data.get("tcgplayer_id", "")),
    }


# ══════════════════════════════════════════════════════════════
# Collection Import Endpoint
# ══════════════════════════════════════════════════════════════

@app.post("/api/collection/import")
async def import_collection(body: dict):
    """
    Import cards into the collection from CSV, Moxfield, Archidekt, or plain text.

    Body:
      {
        "source": "CSV" | "MOXFIELD" | "ARCHIDEKT" | "TEXT",
        "mode": "MERGE" | "REPLACE",
        "content": "...csv or text content...",
        "mapping": { ... optional column mapping ... }
      }
    """
    source = str(body.get("source", "CSV")).upper()
    mode = str(body.get("mode", "MERGE")).upper()
    content = str(body.get("content", ""))
    mapping = body.get("mapping", {})

    if not content.strip():
        raise HTTPException(400, "content is required")

    imported_count = 0
    updated_count = 0
    failed_count = 0
    errors = []

    conn = _get_db_conn()

    # REPLACE mode: clear existing entries
    if mode == "REPLACE":
        conn.execute("DELETE FROM collection_entries")
        conn.commit()

    # Parse the content into raw rows
    try:
        raw_rows = _parse_csv_content(content, source, mapping if mapping else None)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse content: {str(e)}")

    for raw in raw_rows:
        name = raw.get("name", "").strip()
        if not name:
            continue

        quantity = int(raw.get("quantity", 1))
        set_code = raw.get("set_code", "").lower()
        collector_number = raw.get("collector_number", "")
        finish = _parse_finish(raw.get("finish", ""))
        condition = raw.get("condition", "")
        language = raw.get("language", "")
        notes = raw.get("notes", "")
        tags = raw.get("tags", "")

        # Scryfall enrichment
        try:
            enriched = _enrich_from_scryfall(name, set_code, collector_number)
        except Exception as e:
            errors.append(f"Scryfall error for '{name}': {str(e)}")
            failed_count += 1
            continue

        if not enriched or "_error" in enriched:
            err_msg = enriched.get("_error", f"Card not found on Scryfall: '{name}'") if enriched else f"Card not found on Scryfall: '{name}'"
            errors.append(err_msg)
            failed_count += 1
            continue

        # Use Scryfall-resolved name if available
        resolved_name = enriched.get("name", name)

        # Check for existing entry (identity key)
        existing = conn.execute(
            """SELECT id, quantity FROM collection_entries
               WHERE name = ? AND set_code = ? AND collector_number = ? AND finish = ?""",
            (resolved_name, set_code, collector_number, finish),
        ).fetchone()

        if existing and mode == "MERGE":
            # Update quantity
            new_qty = existing["quantity"] + quantity
            conn.execute(
                "UPDATE collection_entries SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
                (new_qty, existing["id"]),
            )
            conn.commit()
            updated_count += 1
        else:
            # Insert new row
            conn.execute(
                """INSERT INTO collection_entries
                   (name, type_line, subtypes, is_legendary, is_basic, color_identity,
                    cmc, mana_cost, oracle_text, keywords,
                    power, toughness, rarity, set_name, edhrec_rank,
                    tcg_price, salt_score, is_game_changer,
                    category, scryfall_id, tcgplayer_id,
                    quantity, finish, condition, language, notes, tags,
                    set_code, collector_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resolved_name,
                    enriched.get("type_line", ""),
                    enriched.get("subtypes", "[]"),
                    enriched.get("is_legendary", 0),
                    enriched.get("is_basic", 0),
                    enriched.get("color_identity", "[]"),
                    enriched.get("cmc", 0.0),
                    enriched.get("mana_cost", ""),
                    enriched.get("oracle_text", ""),
                    enriched.get("keywords", "[]"),
                    enriched.get("power", ""),
                    enriched.get("toughness", ""),
                    enriched.get("rarity", ""),
                    enriched.get("set_name", ""),
                    enriched.get("edhrec_rank", 0),
                    enriched.get("tcg_price", 0.0),
                    enriched.get("salt_score", 0.0),
                    enriched.get("is_game_changer", 0),
                    enriched.get("category", "[]"),
                    enriched.get("scryfall_id", ""),
                    enriched.get("tcgplayer_id", ""),
                    quantity,
                    finish,
                    condition,
                    language,
                    notes,
                    tags,
                    set_code,
                    collector_number,
                ),
            )
            conn.commit()
            imported_count += 1

    return {
        "importedCount": imported_count,
        "updatedCount": updated_count,
        "failedCount": failed_count,
        "errors": errors,
    }


# ══════════════════════════════════════════════════════════════
# Scryfall Cache Management Endpoints
# ══════════════════════════════════════════════════════════════


@app.get("/api/cache/scryfall")
async def scryfall_cache_stats():
    """Return Scryfall response cache statistics."""
    return _scryfall_cache.stats()


@app.delete("/api/cache/scryfall")
async def scryfall_cache_clear():
    """Clear all cached Scryfall responses."""
    deleted = _scryfall_cache.clear()
    return {"cleared": deleted, "message": f"Deleted {deleted} cached entries"}


@app.post("/api/cache/scryfall/evict")
async def scryfall_cache_evict_expired():
    """Remove only expired entries (older than TTL) from the cache."""
    evicted = _scryfall_cache.evict_expired()
    return {"evicted": evicted, "message": f"Evicted {evicted} expired entries"}


# ══════════════════════════════════════════════════════════════
# Deck Builder Helpers
# ══════════════════════════════════════════════════════════════

# Type classification priority order
_TYPE_PRIORITY = ["Land", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Creature"]

# Target ranges: {type: [min, max]}
_TYPE_TARGETS = {
    "Land": [36, 38],
    "Instant": [9, 11],
    "Sorcery": [7, 9],
    "Artifact": [9, 11],
    "Creature": [20, 30],
    "Enchantment": [5, 10],
    "Planeswalker": [0, 5],
}


def _classify_card_type(type_line: str) -> str:
    """Classify a card's primary type per priority order."""
    tl = type_line or ""
    for t in _TYPE_PRIORITY:
        if t in tl:
            return t
    return "Other"


def _detect_card_roles(oracle_text: str, type_line: str, keywords) -> list:
    """
    Detect functional roles from oracle text, type line, and keywords.
    Inspired by Archidekt auto-category system.
    Returns a list of role strings.
    """
    roles = []
    ot = (oracle_text or "").lower()
    tl = (type_line or "").lower()
    kw_raw = keywords or []
    if isinstance(kw_raw, str):
        try:
            kw_raw = json.loads(kw_raw)
        except Exception:
            kw_raw = []
    kw = " ".join(str(k).lower() for k in kw_raw)

    # ── Ramp ──────────────────────────────────────────────
    if (
        "add {" in ot
        or "add one mana" in ot
        or ("search your library for a" in ot and "land" in ot)
        or ("land" in tl and "enters" in ot and "add" in ot)
        or "treasure token" in ot
        or "add mana" in ot
    ):
        roles.append("Ramp")

    # ── Draw ──────────────────────────────────────────────
    if (
        "draw a card" in ot
        or "draw cards" in ot
        or "draws a card" in ot
        or "draw two cards" in ot
        or "draw three cards" in ot
        or re.search(r"draw \d+ cards?", ot)
        or "whenever" in ot and "draw" in ot
    ):
        roles.append("Draw")

    # ── Removal ───────────────────────────────────────────
    if (
        "destroy target" in ot
        or "exile target" in ot
        or re.search(r"deals? \d+ damage to (target|any target)", ot)
        or re.search(r"deals? x damage to (target|any target)", ot)
        or "target creature gets -" in ot
        or "fights target" in ot
    ):
        roles.append("Removal")

    # ── Board Wipe ────────────────────────────────────────
    if (
        "destroy all" in ot
        or "exile all" in ot
        or re.search(r"all creatures get -\d+/-\d+", ot)
        or re.search(r"each creature gets -\d+/-\d+", ot)
        or ("deals" in ot and "to each creature" in ot)
    ):
        roles.append("Board Wipe")

    # ── Anthem ────────────────────────────────────────────
    if (
        re.search(r"creatures? you control get \+", ot)
        or re.search(r"creatures? you control have", ot)
        or re.search(r"other creatures? you control get \+", ot)
        or re.search(r"each creature you control gets? \+", ot)
    ):
        roles.append("Anthem")

    # ── Protection ────────────────────────────────────────
    if (
        "hexproof" in ot or "hexproof" in kw
        or "indestructible" in ot or "indestructible" in kw
        or "shroud" in ot or "shroud" in kw
        or "ward" in ot or "ward" in kw
        or "protection from" in ot
        or "can't be the target" in ot
    ):
        roles.append("Protection")

    # ── Tutor ─────────────────────────────────────────────
    if "search your library" in ot:
        roles.append("Tutor")

    # ── Counter ───────────────────────────────────────────
    if "counter target" in ot:
        roles.append("Counter")

    # ── Token ─────────────────────────────────────────────
    if (
        re.search(r"create[sd]? .*token", ot)
        or "creature token" in ot
    ):
        roles.append("Token")

    # ── Sacrifice ─────────────────────────────────────────
    if (
        "sacrifice a " in ot
        or "sacrifice another" in ot
        or "when" in ot and "sacrifice" in ot and "dies" not in ot
        or "each player sacrifices" in ot
    ):
        roles.append("Sacrifice")

    # ── Recursion / Reanimate ─────────────────────────────
    if (
        "return" in ot and "from your graveyard" in ot
        or "return" in ot and "from a graveyard" in ot
        or "put" in ot and "from your graveyard" in ot and "onto the battlefield" in ot
        or "put" in ot and "from a graveyard" in ot and "onto the battlefield" in ot
    ):
        roles.append("Recursion")

    # ── Graveyard ─────────────────────────────────────────
    if (
        "graveyard" in ot
        and ("mill" in ot or "put" in ot and "into" in ot and "graveyard" in ot)
    ) or "mill" in kw:
        roles.append("Graveyard")

    # ── Lifegain ──────────────────────────────────────────
    if (
        "gain" in ot and "life" in ot
        or "lifelink" in ot or "lifelink" in kw
    ):
        roles.append("Lifegain")

    # ── Burn ──────────────────────────────────────────────
    if (
        re.search(r"deals? \d+ damage to (each|any|target) (opponent|player)", ot)
        or "each opponent loses" in ot and "life" in ot
        or "deals damage to each opponent" in ot
    ):
        roles.append("Burn")

    # ── Stax ──────────────────────────────────────────────
    if (
        "can't cast" in ot
        or "can't attack" in ot
        or "can't activate" in ot
        or "enters the battlefield tapped" in ot and "opponents" in ot
        or "each player can't" in ot
        or "players can't" in ot
        or "cost {" in ot and "more to cast" in ot
        or "cost more" in ot and "spells" in ot
    ):
        roles.append("Stax")

    # ── Evasion ───────────────────────────────────────────
    if (
        "flying" in kw
        or "trample" in kw
        or "menace" in kw
        or "shadow" in kw
        or "fear" in kw
        or "intimidate" in kw
        or "can't be blocked" in ot
        or "unblockable" in ot
    ):
        roles.append("Evasion")

    # ── Finisher ──────────────────────────────────────────
    if (
        "you win the game" in ot
        or "extra turn" in ot
        or "infinite" in ot
        or "loses the game" in ot
        or "damage equal to" in ot and ("number" in ot or "total" in ot)
    ):
        roles.append("Finisher")

    # ── Combo ─────────────────────────────────────────────
    if (
        "untap all" in ot
        or "copy" in ot and "spell" in ot
        or "take an extra" in ot
        or "double" in ot and ("damage" in ot or "counters" in ot or "tokens" in ot)
    ):
        roles.append("Combo")

    return roles


def _get_deck_or_404(deck_id: int):
    """Fetch a deck row or raise 404."""
    conn = _get_db_conn()
    row = conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Deck {deck_id} not found")
    d = dict(row)
    try:
        d["color_identity"] = json.loads(d.get("color_identity", "[]"))
    except Exception:
        d["color_identity"] = []
    return d


def _compute_deck_analysis(deck_id: int) -> dict:
    """
    Build the full analysis dict for a deck.
    Joins deck_cards with collection_entries via scryfall_id.
    """
    conn = _get_db_conn()

    rows = conn.execute(
        """
        SELECT dc.id, dc.scryfall_id, dc.card_name, dc.quantity, dc.is_commander, dc.role_tag,
               ce.type_line, ce.oracle_text, ce.keywords, ce.cmc, ce.color_identity
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, oracle_text, keywords, cmc, color_identity
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
        """,
        (deck_id,)
    ).fetchall()

    counts_by_type = {t: 0 for t in _TYPE_PRIORITY}
    counts_by_type["Other"] = 0
    mana_curve = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, "6+": 0}
    color_pips = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0}
    roles_count = {"Ramp": 0, "Draw": 0, "Removal": 0, "BoardWipe": 0,
                   "Protection": 0, "Tutor": 0, "Counter": 0}
    total_cards = 0

    for row in rows:
        qty = row["quantity"] or 1
        total_cards += qty
        type_line = row["type_line"] or ""
        oracle_text = row["oracle_text"] or ""
        keywords = row["keywords"] or "[]"
        cmc = float(row["cmc"] or 0)
        col_id_raw = row["color_identity"] or "[]"

        card_type = _classify_card_type(type_line)
        counts_by_type[card_type] = counts_by_type.get(card_type, 0) + qty

        # Mana curve (exclude lands)
        if card_type != "Land":
            cmc_int = int(cmc)
            if cmc_int >= 6:
                mana_curve["6+"] += qty
            else:
                mana_curve[cmc_int] = mana_curve.get(cmc_int, 0) + qty

        # Color pips from color_identity
        try:
            ci = json.loads(col_id_raw) if isinstance(col_id_raw, str) else col_id_raw
        except Exception:
            ci = []
        for c in ci:
            if c in color_pips:
                color_pips[c] += qty

        # Detect roles
        card_roles = _detect_card_roles(oracle_text, type_line, keywords)
        for role in card_roles:
            if role in roles_count:
                roles_count[role] += qty

    # Compute deltas: current - midpoint of target range
    deltas = {}
    for t, (lo, hi) in _TYPE_TARGETS.items():
        mid = (lo + hi) / 2
        current = counts_by_type.get(t, 0)
        delta = current - mid
        deltas[t] = round(delta, 1)

    return {
        "counts_by_type": counts_by_type,
        "targets": _TYPE_TARGETS,
        "deltas": deltas,
        "mana_curve": mana_curve,
        "color_pips": color_pips,
        "total_cards": total_cards,
        "roles": roles_count,
    }


# ══════════════════════════════════════════════════════════════
# Deck Builder Endpoints
# ══════════════════════════════════════════════════════════════

# ── 2.1 Deck CRUD ─────────────────────────────────────────────

@app.post("/api/decks")
async def create_deck(req: CreateDeckRequest):
    """Create a new deck."""
    conn = _get_db_conn()
    color_identity_json = json.dumps(req.color_identity or [])
    cur = conn.execute(
        """
        INSERT INTO decks (name, commander_scryfall_id, commander_name, color_identity, strategy_tag)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            req.name,
            req.commander_scryfall_id or "",
            req.commander_name or "",
            color_identity_json,
            req.strategy_tag or "",
        )
    )
    conn.commit()
    deck_id = cur.lastrowid
    return _get_deck_or_404(deck_id)


@app.get("/api/decks")
async def list_decks_db():
    """List all decks with card counts."""
    conn = _get_db_conn()
    rows = conn.execute(
        """
        SELECT d.*,
               COALESCE(SUM(dc.quantity), 0) AS total_cards,
               COUNT(dc.id) AS card_slots
        FROM decks d
        LEFT JOIN deck_cards dc ON dc.deck_id = d.id
        GROUP BY d.id
        ORDER BY d.updated_at DESC
        """
    ).fetchall()
    decks = []
    for row in rows:
        d = dict(row)
        try:
            d["color_identity"] = json.loads(d.get("color_identity", "[]"))
        except Exception:
            d["color_identity"] = []
        decks.append(d)
    return {"decks": decks}


@app.get("/api/decks/{deck_id}")
async def get_deck(deck_id: int):
    """Get full deck info with composition summary."""
    deck = _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    card_rows = conn.execute(
        "SELECT * FROM deck_cards WHERE deck_id = ? ORDER BY is_commander DESC, card_name ASC",
        (deck_id,)
    ).fetchall()
    deck["cards"] = [dict(r) for r in card_rows]
    deck["total_cards"] = sum(r["quantity"] for r in card_rows)
    deck["card_slots"] = len(card_rows)
    # Composition summary by type
    analysis = _compute_deck_analysis(deck_id)
    deck["composition"] = analysis["counts_by_type"]
    return deck


@app.put("/api/decks/{deck_id}")
async def update_deck(deck_id: int, req: UpdateDeckRequest):
    """Update deck metadata."""
    _get_deck_or_404(deck_id)  # ensure exists
    conn = _get_db_conn()

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.commander_scryfall_id is not None:
        updates["commander_scryfall_id"] = req.commander_scryfall_id
    if req.commander_name is not None:
        updates["commander_name"] = req.commander_name
    if req.color_identity is not None:
        updates["color_identity"] = json.dumps(req.color_identity)
    if req.strategy_tag is not None:
        updates["strategy_tag"] = req.strategy_tag

    if not updates:
        return _get_deck_or_404(deck_id)

    updates["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE decks SET {set_clause} WHERE id = ?", list(updates.values()) + [deck_id])
    conn.commit()
    return _get_deck_or_404(deck_id)


@app.delete("/api/decks/{deck_id}")
async def delete_deck(deck_id: int):
    """Delete a deck and all its cards (cascade)."""
    _get_deck_or_404(deck_id)  # ensure exists
    conn = _get_db_conn()
    conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
    conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    conn.commit()
    return {"deleted": True, "deck_id": deck_id}


@app.delete("/api/decks")
async def delete_all_decks():
    """Delete ALL decks and their cards."""
    conn = _get_db_conn()
    conn.execute("DELETE FROM deck_cards")
    count = conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
    conn.execute("DELETE FROM decks")
    conn.commit()
    return {"deleted": True, "count": count}


# ── 2.2 Deck Card Manipulation ───────────────────────────────

@app.get("/api/decks/{deck_id}/cards")
async def get_deck_cards(deck_id: int):
    """Get all cards in a deck with joined collection data."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    rows = conn.execute(
        """
        SELECT
            dc.id, dc.deck_id, dc.scryfall_id, dc.card_name, dc.quantity,
            dc.is_commander, dc.role_tag,
            ce.type_line, ce.cmc, ce.mana_cost, ce.color_identity, ce.oracle_text, ce.keywords,
            ce.tcg_price, ce.quantity AS owned_qty, ce.is_legendary,
            ce.salt_score, ce.is_game_changer
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, cmc, mana_cost, color_identity,
                   oracle_text, keywords, tcg_price, quantity, is_legendary,
                   salt_score, is_game_changer
            FROM collection_entries
            GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
        ORDER BY dc.is_commander DESC, dc.card_name ASC
        """,
        (deck_id,)
    ).fetchall()
    cards = []
    for row in rows:
        d = dict(row)
        # Parse JSON fields
        for f in ("color_identity", "keywords"):
            if isinstance(d.get(f), str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    d[f] = []
        d["image_url"] = (
            f"https://api.scryfall.com/cards/{d['scryfall_id']}?format=image&version=normal"
            if d.get("scryfall_id") else None
        )
        cards.append(d)
    return {"cards": cards, "total": len(cards)}


@app.post("/api/decks/{deck_id}/cards")
async def add_deck_card(deck_id: int, req: AddDeckCardRequest):
    """Add or update a card in the deck."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    # Look up card_name from collection_entries by scryfall_id, fall back to request
    ce_row = conn.execute(
        "SELECT name FROM collection_entries WHERE scryfall_id = ? LIMIT 1",
        (req.scryfall_id,)
    ).fetchone()
    card_name = ce_row["name"] if ce_row else (req.card_name or "")

    # Check if this scryfall_id is already in the deck
    existing = conn.execute(
        "SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
        (deck_id, req.scryfall_id)
    ).fetchone()

    if existing:
        new_qty = existing["quantity"] + (req.quantity or 1)
        conn.execute(
            "UPDATE deck_cards SET quantity = ?, role_tag = ?, is_commander = ? WHERE id = ?",
            (new_qty, req.role_tag or "", req.is_commander or 0, existing["id"])
        )
        conn.commit()
        row = conn.execute("SELECT * FROM deck_cards WHERE id = ?", (existing["id"],)).fetchone()
    else:
        cur = conn.execute(
            """
            INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander, role_tag)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deck_id, req.scryfall_id, card_name,
                req.quantity or 1,
                req.is_commander or 0,
                req.role_tag or ""
            )
        )
        conn.commit()
        row = conn.execute("SELECT * FROM deck_cards WHERE id = ?", (cur.lastrowid,)).fetchone()

    # Update deck updated_at
    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()
    return dict(row)


@app.delete("/api/decks/{deck_id}/cards/{card_id}")
async def remove_deck_card(deck_id: int, card_id: int):
    """Remove a card from a deck."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    row = conn.execute(
        "SELECT id FROM deck_cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Card slot {card_id} not found in deck {deck_id}")
    conn.execute("DELETE FROM deck_cards WHERE id = ?", (card_id,))
    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()
    return {"deleted": True, "card_id": card_id, "deck_id": deck_id}


@app.patch("/api/decks/{deck_id}/cards/{card_id}")
async def patch_deck_card(deck_id: int, card_id: int, req: PatchDeckCardRequest):
    """Update quantity or role_tag for a card in a deck."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    row = conn.execute(
        "SELECT * FROM deck_cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Card slot {card_id} not found in deck {deck_id}")

    updates = {}
    if req.quantity is not None:
        if req.quantity < 1:
            raise HTTPException(400, "quantity must be >= 1")
        updates["quantity"] = req.quantity
    if req.role_tag is not None:
        updates["role_tag"] = req.role_tag

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE deck_cards SET {set_clause} WHERE id = ?",
            list(updates.values()) + [card_id]
        )
        conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
        conn.commit()

    updated = conn.execute("SELECT * FROM deck_cards WHERE id = ?", (card_id,)).fetchone()
    return dict(updated)


# ── 2.3 Deck Analysis ────────────────────────────────────────────

@app.get("/api/decks/{deck_id}/analysis")
async def deck_analysis(deck_id: int):
    """Analyze deck composition — type counts, mana curve, color pips, roles, targets, deltas."""
    _get_deck_or_404(deck_id)
    return _compute_deck_analysis(deck_id)


# ── 2.5 Recommendations from Collection ───────────────────────

@app.get("/api/decks/{deck_id}/recommended-from-collection")
async def recommend_from_collection(deck_id: int, max_results: int = 20, roles: Optional[str] = None):
    """
    Recommend cards from the user's collection for a deck.
    Finds shortfalls, then scores owned cards by how well they fit.
    """
    deck = _get_deck_or_404(deck_id)
    deck_color_identity = deck.get("color_identity", [])
    conn = _get_db_conn()

    # Run analysis to find shortfalls
    analysis = _compute_deck_analysis(deck_id)
    deltas = analysis["deltas"]
    counts_by_type = analysis["counts_by_type"]

    # Find types that are below their target midpoint (shortfall)
    shortfall_types = set()
    for t, delta in deltas.items():
        lo, hi = _TYPE_TARGETS.get(t, [0, 0])
        if counts_by_type.get(t, 0) < lo:
            shortfall_types.add(t)

    # Get scryfall_ids already in deck to exclude
    in_deck_ids = set(
        r["scryfall_id"] for r in
        conn.execute("SELECT scryfall_id FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
    )

    # Parse role filter
    role_filter = [r.strip() for r in roles.split(",") if r.strip()] if roles else []

    # Query collection for candidate cards
    coll_rows = conn.execute(
        "SELECT * FROM collection_entries WHERE quantity > 0"
    ).fetchall()

    scored = []
    for row in coll_rows:
        card = _row_to_dict(row)
        card_id = card.get("scryfall_id", "")

        # Skip cards already in deck
        if card_id in in_deck_ids:
            continue

        # Color identity check: all card colors must be in deck colors
        card_ci = card.get("color_identity", [])
        if isinstance(card_ci, str):
            try:
                card_ci = json.loads(card_ci)
            except Exception:
                card_ci = []
        if deck_color_identity and card_ci:
            if not all(c in deck_color_identity for c in card_ci):
                continue

        type_line = card.get("type_line", "")
        oracle_text = card.get("oracle_text", "")
        keywords = card.get("keywords", [])
        card_type = _classify_card_type(type_line)
        card_roles = _detect_card_roles(oracle_text, type_line, keywords)

        # Role filter
        if role_filter and not any(r in card_roles for r in role_filter):
            continue

        # Scoring
        score = 0
        # +3 if card type is in shortfall
        if card_type in shortfall_types:
            score += 3
        # +2 per matching role
        for r in card_roles:
            if r in ("Ramp", "Draw", "Removal", "BoardWipe"):
                score += 2
            else:
                score += 1
        # +1 for lower CMC (curve fit)
        cmc = float(card.get("cmc", 0))
        if cmc <= 3:
            score += 1

        scored.append({
            "id": card.get("id"),
            "scryfall_id": card_id,
            "name": card.get("name"),
            "type_line": type_line,
            "card_type": card_type,
            "cmc": cmc,
            "color_identity": card_ci,
            "owned_qty": card.get("quantity", 0),
            "roles": card_roles,
            "score": score,
            "image_url": f"https://api.scryfall.com/cards/{card_id}?format=image&version=normal" if card_id else None,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Group by type
    grouped = {}
    for card in scored[:max_results]:
        ct = card["card_type"]
        grouped.setdefault(ct, []).append(card)

    return {
        "shortfall_types": list(shortfall_types),
        "role_filter": role_filter,
        "grouped": grouped,
        "total": len(scored[:max_results]),
    }


# ── 2.6 EDHREC-style Recommendations ────────────────────────

@app.get("/api/decks/{deck_id}/edh-recs")
async def deck_edh_recs(deck_id: int, only_owned: bool = False, max_results: int = 30):
    """
    Fetch EDHREC average deck recommendations for this deck's commander.
    Cross-references with collection for owned status.
    """
    deck = _get_deck_or_404(deck_id)
    commander_name = deck.get("commander_name", "")
    if not commander_name:
        raise HTTPException(400, "Deck has no commander_name set. Update the deck first.")

    # Cache check
    cache_key = f"edhrec:avg:{_to_edhrec_slug(commander_name)}"
    cached_profile = _edhrec_cache_get(cache_key)
    if cached_profile is None:
        try:
            cached_profile = _fetch_edhrec_average(commander_name)
            _edhrec_cache_set(cache_key, cached_profile)
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch EDHREC data for '{commander_name}': {str(e)}")

    edhrec_profile = cached_profile
    mainboard = edhrec_profile.get("mainboard", {})

    conn = _get_db_conn()

    # Get cards already in deck
    in_deck_names = set(
        r["card_name"].lower() for r in
        conn.execute("SELECT card_name FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
    )

    # Build collection lookup: name (lower) -> {owned, qty, scryfall_id}
    coll_rows = conn.execute(
        "SELECT name, quantity, scryfall_id FROM collection_entries"
    ).fetchall()
    coll_map = {}
    for r in coll_rows:
        key = r["name"].lower()
        existing = coll_map.get(key)
        if not existing or r["quantity"] > existing["qty"]:
            coll_map[key] = {"owned": True, "qty": r["quantity"], "scryfall_id": r["scryfall_id"]}

    # Also look up card details from collection_entries for type/role
    coll_details = {}
    for r in conn.execute("SELECT name, type_line, oracle_text, keywords, scryfall_id FROM collection_entries").fetchall():
        key = r["name"].lower()
        if key not in coll_details:
            coll_details[key] = dict(r)

    results = []
    for card_name in mainboard:
        name_lower = card_name.lower()
        # Skip cards already in deck
        if name_lower in in_deck_names:
            continue

        owned_info = coll_map.get(name_lower, {"owned": False, "qty": 0, "scryfall_id": ""})

        if only_owned and not owned_info["owned"]:
            continue

        # Get type/role from collection if available
        details = coll_details.get(name_lower, {})
        type_line = details.get("type_line", "")
        oracle_text = details.get("oracle_text", "")
        keywords = details.get("keywords", "[]")
        card_roles = _detect_card_roles(oracle_text, type_line, keywords)
        scryfall_id = owned_info.get("scryfall_id") or details.get("scryfall_id", "")

        results.append({
            "name": card_name,
            "type_line": type_line,
            "role": card_roles[0] if card_roles else "Other",
            "roles": card_roles,
            "inclusion_pct": None,  # EDHREC average doesn't expose % directly in this path
            "synergy_score": None,
            "owned": owned_info["owned"],
            "owned_qty": owned_info["qty"],
            "scryfall_id": scryfall_id,
            "image_url": f"https://api.scryfall.com/cards/{scryfall_id}?format=image&version=normal" if scryfall_id else None,
        })

    return {
        "commander": commander_name,
        "source": "EDHREC Average",
        "total": len(results[:max_results]),
        "recommendations": results[:max_results],
    }


# ── 2.7 Bulk Add Operations ────────────────────────────────

def _check_ratio_limit(deck_id: int, card_type: str, count_to_add: int = 1) -> bool:
    """
    Return True if adding count_to_add cards of card_type stays within target max.
    """
    analysis = _compute_deck_analysis(deck_id)
    current = analysis["counts_by_type"].get(card_type, 0)
    target_max = _TYPE_TARGETS.get(card_type, [0, 9999])[1]
    return (current + count_to_add) <= target_max


@app.post("/api/decks/{deck_id}/bulk-add")
async def bulk_add_cards(deck_id: int, req: BulkAddRequest):
    """
    Bulk-add cards to a deck by scryfall_id.
    If respect_ratios, skips cards of a type when the target max is already reached.
    """
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    added = 0
    skipped = 0
    details = []

    for card_entry in req.cards:
        scryfall_id = str(card_entry.get("scryfall_id", "")).strip()
        quantity = int(card_entry.get("quantity", 1))
        if not scryfall_id:
            skipped += 1
            details.append({"scryfall_id": scryfall_id, "status": "skipped", "reason": "missing scryfall_id"})
            continue

        # Look up card name and type from collection
        ce_row = conn.execute(
            "SELECT name, type_line, oracle_text, keywords FROM collection_entries WHERE scryfall_id = ? LIMIT 1",
            (scryfall_id,)
        ).fetchone()
        card_name = ce_row["name"] if ce_row else ""
        type_line = ce_row["type_line"] if ce_row else ""
        card_type = _classify_card_type(type_line)

        if req.respect_ratios and not _check_ratio_limit(deck_id, card_type, quantity):
            skipped += 1
            details.append({
                "scryfall_id": scryfall_id,
                "name": card_name,
                "card_type": card_type,
                "status": "skipped",
                "reason": f"Type '{card_type}' at or above target max",
            })
            continue

        # Upsert
        existing = conn.execute(
            "SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
            (deck_id, scryfall_id)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE deck_cards SET quantity = ? WHERE id = ?",
                (existing["quantity"] + quantity, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity) VALUES (?, ?, ?, ?)",
                (deck_id, scryfall_id, card_name, quantity)
            )
        conn.commit()
        added += 1
        details.append({"scryfall_id": scryfall_id, "name": card_name, "card_type": card_type, "status": "added", "quantity": quantity})

    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()

    analysis = _compute_deck_analysis(deck_id)
    return {"added": added, "skipped": skipped, "details": details, "analysis": analysis}


@app.post("/api/decks/{deck_id}/bulk-add-recommended")
async def bulk_add_recommended(deck_id: int, req: BulkAddRecommendedRequest):
    """
    Fetch recommendations from 'collection' or 'edhrec', filter, and bulk-add to deck.
    """
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    source = (req.source or "collection").lower()
    type_filter = [t.strip() for t in req.types] if req.types else []
    role_filter = [r.strip() for r in req.roles] if req.roles else []

    candidates = []

    if source == "collection":
        # Reuse the recommend_from_collection logic
        deck = _get_deck_or_404(deck_id)
        deck_color_identity = deck.get("color_identity", [])
        analysis = _compute_deck_analysis(deck_id)
        counts_by_type = analysis["counts_by_type"]
        shortfall_types = {t for t, (lo, _) in _TYPE_TARGETS.items() if counts_by_type.get(t, 0) < lo}

        in_deck_ids = set(
            r["scryfall_id"] for r in
            conn.execute("SELECT scryfall_id FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
        )
        coll_rows = conn.execute("SELECT * FROM collection_entries WHERE quantity > 0").fetchall()
        for row in coll_rows:
            card = _row_to_dict(row)
            cid = card.get("scryfall_id", "")
            if cid in in_deck_ids:
                continue
            card_ci = card.get("color_identity", [])
            if isinstance(card_ci, str):
                try:
                    card_ci = json.loads(card_ci)
                except Exception:
                    card_ci = []
            if deck_color_identity and card_ci:
                if not all(c in deck_color_identity for c in card_ci):
                    continue
            tl = card.get("type_line", "")
            ct = _classify_card_type(tl)
            card_roles = _detect_card_roles(card.get("oracle_text", ""), tl, card.get("keywords", []))
            if type_filter and ct not in type_filter:
                continue
            if role_filter and not any(r in card_roles for r in role_filter):
                continue
            candidates.append({"scryfall_id": cid, "card_type": ct, "quantity": 1})

    elif source == "edhrec":
        deck = _get_deck_or_404(deck_id)
        commander_name = deck.get("commander_name", "")
        if not commander_name:
            raise HTTPException(400, "Deck has no commander_name set")
        try:
            edhrec_profile = _fetch_edhrec_average(commander_name)
        except Exception as e:
            raise HTTPException(502, f"EDHREC fetch failed: {e}")
        mainboard = edhrec_profile.get("mainboard", {})
        in_deck_names = set(
            r["card_name"].lower() for r in
            conn.execute("SELECT card_name FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
        )
        coll_rows = conn.execute("SELECT name, scryfall_id, type_line, oracle_text, keywords, quantity FROM collection_entries").fetchall()
        coll_map = {r["name"].lower(): dict(r) for r in coll_rows}

        for card_name in mainboard:
            name_lower = card_name.lower()
            if name_lower in in_deck_names:
                continue
            coll_info = coll_map.get(name_lower)
            if req.only_owned and not coll_info:
                continue
            if not coll_info:
                continue  # can't add without scryfall_id
            scryfall_id = coll_info.get("scryfall_id", "")
            if not scryfall_id:
                continue
            tl = coll_info.get("type_line", "")
            ct = _classify_card_type(tl)
            card_roles = _detect_card_roles(coll_info.get("oracle_text", ""), tl, coll_info.get("keywords", []))
            if type_filter and ct not in type_filter:
                continue
            if role_filter and not any(r in card_roles for r in role_filter):
                continue
            candidates.append({"scryfall_id": scryfall_id, "card_type": ct, "quantity": 1})
    else:
        raise HTTPException(400, f"Unknown source '{source}'. Use 'collection' or 'edhrec'.")

    # Now bulk-add candidates
    added = 0
    skipped = 0
    details = []

    for c in candidates:
        scryfall_id = c["scryfall_id"]
        card_type = c["card_type"]
        quantity = c["quantity"]

        if req.respect_ratios and not _check_ratio_limit(deck_id, card_type, quantity):
            skipped += 1
            details.append({"scryfall_id": scryfall_id, "card_type": card_type, "status": "skipped", "reason": "ratio limit"})
            continue

        ce_row = conn.execute(
            "SELECT name FROM collection_entries WHERE scryfall_id = ? LIMIT 1", (scryfall_id,)
        ).fetchone()
        card_name = ce_row["name"] if ce_row else ""

        existing = conn.execute(
            "SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
            (deck_id, scryfall_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE deck_cards SET quantity = ? WHERE id = ?",
                (existing["quantity"] + quantity, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity) VALUES (?, ?, ?, ?)",
                (deck_id, scryfall_id, card_name, quantity)
            )
        conn.commit()
        added += 1
        details.append({"scryfall_id": scryfall_id, "name": card_name, "card_type": card_type, "status": "added"})

    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()

    analysis = _compute_deck_analysis(deck_id)
    return {"added": added, "skipped": skipped, "details": details, "analysis": analysis}


# ── 2.9 Simulation Export ───────────────────────────────────

@app.post("/api/decks/{deck_id}/export-to-sim")
async def export_deck_to_sim(deck_id: int):
    """
    Export a deck to Forge .dck format and save to the Forge decks directory.
    Returns the deck name for use in simulations.
    """
    deck = _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    card_rows = conn.execute(
        "SELECT card_name, quantity, is_commander FROM deck_cards WHERE deck_id = ? ORDER BY is_commander DESC, card_name ASC",
        (deck_id,)
    ).fetchall()

    if not card_rows:
        raise HTTPException(400, "Deck has no cards to export")

    # Build .dck content
    lines = ["[metadata]"]
    deck_name = deck.get("name", f"Deck {deck_id}")
    lines.append(f"Name={deck_name}")
    lines.append("")

    commanders = [r for r in card_rows if r["is_commander"]]
    mainboard = [r for r in card_rows if not r["is_commander"]]

    lines.append("[Commander]")
    for r in commanders:
        name = r["card_name"] or "Unknown"
        qty = r["quantity"] or 1
        lines.append(f"{qty} {name}")

    lines.append("")
    lines.append("[Main]")
    for r in mainboard:
        name = r["card_name"] or "Unknown"
        qty = r["quantity"] or 1
        lines.append(f"{qty} {name}")

    content = "\n".join(lines)

    # Determine save directory
    safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", deck_name).replace(" ", "_").strip()
    if not safe_name:
        safe_name = f"deck_{deck_id}"

    save_dir = CFG.forge_decks_dir
    if not save_dir or not os.path.isdir(save_dir):
        save_dir = os.path.join(os.path.dirname(__file__), "exported-decks")
        os.makedirs(save_dir, exist_ok=True)

    out_path = Path(save_dir) / f"{safe_name}.dck"
    out_path.write_text(content, encoding="utf-8")
    log_deckgen.info(f"  Exported deck {deck_id} to {out_path}")

    return {
        "success": True,
        "deckName": safe_name,
        "dckFile": str(out_path),
        "totalCards": sum(r["quantity"] for r in card_rows),
        "commanderCount": len(commanders),
        "mainboardCount": len(mainboard),
    }


# ══════════════════════════════════════════════════════════════
# Deck Import Endpoint
# ══════════════════════════════════════════════════════════════


def _parse_decklist_text(text: str) -> dict:
    """
    Parse a decklist from text. Supports:
      - Forge .dck format with [Commander], [Deck], [Main] sections
      - MTGA format: 1 Card Name
      - Plain: Card Name (assumed qty 1)
      - Lines starting with // or # are comments
    Returns { 'commanders': [{'name': str, 'qty': int}], 'cards': [{'name': str, 'qty': int}] }
    """
    commanders = []
    cards = []
    section = 'main'  # default section

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('//') or line.startswith('#'):
            continue

        # Section headers
        low = line.lower()
        if low.startswith('[commander'):
            section = 'commander'
            continue
        if low.startswith('[deck') or low.startswith('[main') or low.startswith('[mainboard'):
            section = 'main'
            continue
        if low.startswith('[sideboard') or low.startswith('[side') or low.startswith('[metadata'):
            section = 'skip'
            continue
        if low.startswith('['):
            # Unknown section, treat as main
            section = 'main'
            continue

        if section == 'skip':
            continue

        # Parse quantity + name
        m = re.match(r'^(\d+)\s*[xX]?\s+(.+)$', line)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip()
        else:
            qty = 1
            name = line

        # Strip set codes like "(M21)" or "(M21) 123" from MTGA exports
        name = re.sub(r'\s*\([A-Z0-9]+\)\s*\d*\s*$', '', name).strip()

        if not name:
            continue

        if section == 'commander':
            commanders.append({'name': name, 'qty': qty})
        else:
            cards.append({'name': name, 'qty': qty})

    return {'commanders': commanders, 'cards': cards}


@app.post('/api/decks/{deck_id}/import')
async def import_decklist(deck_id: int, request: FastAPIRequest):
    """
    Import a decklist into an existing deck. Parses text, looks up each card
    on Scryfall, and adds them to the deck.

    Body: { "text": "1 Sol Ring\n1 Cultivate..." , "clearFirst": false }
    """
    deck = _get_deck_or_404(deck_id)
    body = await request.json()
    text = body.get('text', '')
    clear_first = body.get('clearFirst', False)

    if not text.strip():
        return JSONResponse({'error': 'No decklist text provided'}, status_code=400)

    parsed = _parse_decklist_text(text)
    all_entries = []
    for c in parsed['commanders']:
        all_entries.append({**c, 'is_commander': True})
    for c in parsed['cards']:
        all_entries.append({**c, 'is_commander': False})

    if not all_entries:
        return JSONResponse({'error': 'No cards found in decklist'}, status_code=400)

    conn = _get_db_conn()

    # Optionally clear existing cards
    if clear_first:
        conn.execute('DELETE FROM deck_cards WHERE deck_id = ?', (deck_id,))
        conn.commit()

    added = 0
    failed = []
    results = []

    for entry in all_entries:
        name = entry['name']
        qty = entry['qty']
        is_cmd = entry['is_commander']

        # Look up on Scryfall
        sf = _scryfall_fuzzy_lookup(name)
        if not sf:
            failed.append(name)
            results.append({'name': name, 'status': 'not_found'})
            continue

        scryfall_id = sf.get('id', '')
        resolved_name = sf.get('name', name)

        # Check if already in deck
        existing = conn.execute(
            'SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?',
            (deck_id, scryfall_id)
        ).fetchone()

        if existing:
            conn.execute(
                'UPDATE deck_cards SET quantity = ?, is_commander = ? WHERE id = ?',
                (existing['quantity'] + qty, 1 if is_cmd else existing.get('is_commander', 0), existing['id'])
            )
        else:
            conn.execute(
                'INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander) VALUES (?, ?, ?, ?, ?)',
                (deck_id, scryfall_id, resolved_name, qty, 1 if is_cmd else 0)
            )
        conn.commit()
        added += 1
        results.append({'name': resolved_name, 'qty': qty, 'status': 'added', 'isCommander': is_cmd})

    # Update commander on deck record if we found one
    cmd_entries = [r for r in results if r.get('isCommander')]
    if cmd_entries:
        cmd_name = cmd_entries[0]['name']
        # Look up scryfall_id from the deck_cards we just inserted
        cmd_row = conn.execute(
            'SELECT scryfall_id FROM deck_cards WHERE deck_id = ? AND is_commander = 1 LIMIT 1',
            (deck_id,)
        ).fetchone()
        cmd_sf_id = cmd_row['scryfall_id'] if cmd_row else ''
        conn.execute(
            'UPDATE decks SET commander_name = ?, commander_scryfall_id = ?, updated_at = datetime(\'now\') WHERE id = ?',
            (cmd_name, cmd_sf_id, deck_id)
        )
    else:
        conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()

    return {
        'added': added,
        'failed': len(failed),
        'failedNames': failed,
        'total': len(all_entries),
        'results': results,
    }


@app.post('/api/decks/import-new')
async def import_decklist_new(request: FastAPIRequest):
    """
    Import a decklist as a brand-new deck. Creates the deck, then imports cards.

    Body: { "text": "...", "name": "My Deck" }
    """
    body = await request.json()
    text = body.get('text', '')
    deck_name = body.get('name', '').strip()

    if not text.strip():
        return JSONResponse({'error': 'No decklist text provided'}, status_code=400)

    parsed = _parse_decklist_text(text)
    all_entries = []
    for c in parsed['commanders']:
        all_entries.append({**c, 'is_commander': True})
    for c in parsed['cards']:
        all_entries.append({**c, 'is_commander': False})

    if not all_entries:
        return JSONResponse({'error': 'No cards found in decklist'}, status_code=400)

    # Auto-name from first commander if no name given
    if not deck_name:
        cmd = parsed['commanders'][0]['name'] if parsed['commanders'] else None
        deck_name = cmd or 'Imported Deck'

    conn = _get_db_conn()
    cur = conn.execute(
        "INSERT INTO decks (name, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))",
        (deck_name,)
    )
    conn.commit()
    new_deck_id = cur.lastrowid

    # Set commander on the deck if we have one
    first_cmd_scryfall = None
    first_cmd_name = None

    added = 0
    failed = []

    for entry in all_entries:
        name = entry['name']
        qty = entry['qty']
        is_cmd = entry['is_commander']

        sf = _scryfall_fuzzy_lookup(name)
        if not sf:
            failed.append(name)
            continue

        scryfall_id = sf.get('id', '')
        resolved_name = sf.get('name', name)

        if is_cmd and not first_cmd_scryfall:
            first_cmd_scryfall = scryfall_id
            first_cmd_name = resolved_name

        conn.execute(
            'INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander) VALUES (?, ?, ?, ?, ?)',
            (new_deck_id, scryfall_id, resolved_name, qty, 1 if is_cmd else 0)
        )
        conn.commit()
        added += 1

    # Update commander on deck record
    if first_cmd_scryfall:
        conn.execute(
            'UPDATE decks SET commander_name = ?, commander_scryfall_id = ? WHERE id = ?',
            (first_cmd_name, first_cmd_scryfall, new_deck_id)
        )
        conn.commit()

    return {
        'deckId': new_deck_id,
        'deckName': deck_name,
        'added': added,
        'failed': len(failed),
        'failedNames': failed,
        'total': len(all_entries),
    }


# ══════════════════════════════════════════════════════════════
# Card Scanner Endpoint
# ══════════════════════════════════════════════════════════════

def _scryfall_fuzzy_lookup(name: str) -> Optional[dict]:
    """
    Fuzzy-search Scryfall for a card name (used by the scanner pipeline).
    Returns the raw Scryfall JSON dict, or None on failure.
    """
    from urllib.parse import quote
    _scryfall_rate_limit()
    try:
        encoded = quote(name)
        url = f"https://api.scryfall.com/cards/named?fuzzy={encoded}"
        req = Request(url, headers=_API_HEADERS)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("object") == "error":
            return None
        return data
    except Exception:
        return None


@app.post("/api/collection/scan")
async def scan_card_image(request: FastAPIRequest):
    """
    Scan a card image and return recognized card name(s).

    Uses Ximilar Visual AI for card recognition.

    Accepts multipart/form-data with:
      - file: image file (JPEG/PNG)
      - mode: "single" (default) or "multi"

    Returns:
      { "results": [ { raw_ocr, matched_name, set_code, scryfall_id, confidence, image_uri, error, collector_number, rarity, tcgplayer_url }, ... ] }
    """
    try:
        from scanner.pipeline import scan_single, scan_multi
    except ImportError as e:
        raise HTTPException(500, f"Scanner module not available: {e}")

    # Try CFG first, then fall back to env var
    api_key = CFG.ximilar_api_key or os.environ.get("XIMILAR_API_KEY", "")
    if not api_key:
        raise HTTPException(500, "Card scanner not configured. Start the server with --ximilar-key YOUR_KEY or set XIMILAR_API_KEY env var.")

    # Parse multipart form
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        raise HTTPException(400, "No file uploaded. Send an image as 'file' in multipart/form-data.")

    mode = str(form.get("mode", "single")).lower()
    image_bytes = await upload.read()

    if len(image_bytes) == 0:
        raise HTTPException(400, "Uploaded file is empty")

    # Limit file size (20 MB)
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(400, "Image file too large (max 20 MB)")

    log_scan.info(f"  Processing {len(image_bytes)} bytes, mode={mode} (Ximilar AI)")

    if mode == "multi":
        results = scan_multi(image_bytes, _scryfall_fuzzy_lookup, ximilar_api_key=api_key)
    else:
        result = scan_single(image_bytes, _scryfall_fuzzy_lookup, ximilar_api_key=api_key)
        results = [result]

    return {
        "results": [r.to_dict() for r in results]
    }


@app.post("/api/collection/scan/add")
async def scan_add_cards(body: dict):
    """
    Add scanned cards to the collection.

    Body:
      {
        "cards": [
          { "name": "Lightning Bolt", "set_code": "m11", "quantity": 1 },
          ...
        ]
      }
    """
    cards = body.get("cards", [])
    if not cards:
        raise HTTPException(400, "No cards provided")

    conn = _get_db_conn()
    imported = 0
    updated = 0
    errors = []

    for card_req in cards:
        name = str(card_req.get("name", "")).strip()
        if not name:
            continue

        quantity = int(card_req.get("quantity", 1))
        set_code = str(card_req.get("set_code", "")).lower()
        collector_number = str(card_req.get("collector_number", ""))
        finish = "NORMAL"

        try:
            enriched = _enrich_from_scryfall(name, set_code, collector_number)
        except Exception as e:
            errors.append(f"Scryfall error for '{name}': {e}")
            continue

        if not enriched or "_error" in enriched:
            err_msg = enriched.get("_error", f"Not found: '{name}'") if enriched else f"Not found: '{name}'"
            errors.append(err_msg)
            continue

        resolved_name = enriched.get("name", name)

        # Check for existing entry
        existing = conn.execute(
            """SELECT id, quantity FROM collection_entries
               WHERE name = ? AND set_code = ? AND collector_number = ? AND finish = ?""",
            (resolved_name, set_code, collector_number, finish),
        ).fetchone()

        if existing:
            new_qty = existing["quantity"] + quantity
            conn.execute(
                "UPDATE collection_entries SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
                (new_qty, existing["id"]),
            )
            conn.commit()
            updated += 1
        else:
            conn.execute(
                """INSERT INTO collection_entries
                   (name, type_line, subtypes, is_legendary, is_basic, color_identity,
                    cmc, mana_cost, oracle_text, keywords,
                    power, toughness, rarity, set_name, edhrec_rank,
                    tcg_price, salt_score, is_game_changer,
                    category, scryfall_id, tcgplayer_id,
                    quantity, finish, condition, language, notes, tags,
                    set_code, collector_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resolved_name,
                    enriched.get("type_line", ""),
                    enriched.get("subtypes", "[]"),
                    enriched.get("is_legendary", 0),
                    enriched.get("is_basic", 0),
                    enriched.get("color_identity", "[]"),
                    enriched.get("cmc", 0.0),
                    enriched.get("mana_cost", ""),
                    enriched.get("oracle_text", ""),
                    enriched.get("keywords", "[]"),
                    enriched.get("power", ""),
                    enriched.get("toughness", ""),
                    enriched.get("rarity", ""),
                    enriched.get("set_name", ""),
                    enriched.get("edhrec_rank", 0),
                    enriched.get("tcg_price", 0.0),
                    enriched.get("salt_score", 0.0),
                    enriched.get("is_game_changer", 0),
                    enriched.get("category", "[]"),
                    enriched.get("scryfall_id", ""),
                    enriched.get("tcgplayer_id", ""),
                    quantity,
                    finish,
                    "",  # condition
                    "",  # language
                    "",  # notes
                    "",  # tags
                    set_code,
                    collector_number,
                ),
            )
            conn.commit()
            imported += 1

    return {
        "importedCount": imported,
        "updatedCount": updated,
        "failedCount": len(errors),
        "errors": errors,
    }


# ══════════════════════════════════════════════════════════════
# Re-enrich Collection from Scryfall
# ══════════════════════════════════════════════════════════════

@app.post("/api/collection/re-enrich")
async def re_enrich_collection():
    """
    Re-fetch Scryfall data for all collection entries to backfill
    missing fields (mana_cost, power, toughness, rarity, set_name, edhrec_rank).
    Also refreshes: type_line, oracle_text, keywords, cmc, color_identity, prices.
    Runs synchronously — may take a while for large collections.
    """
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT id, name, set_code, collector_number FROM collection_entries ORDER BY id"
    ).fetchall()

    total = len(rows)
    enriched_count = 0
    skipped_count = 0
    errors = []

    for row in rows:
        card_id = row["id"]
        name = row["name"]
        set_code = row["set_code"] or ""
        collector_number = row["collector_number"] or ""

        try:
            data = _enrich_from_scryfall(name, set_code, collector_number)
        except Exception as e:
            errors.append(f"Error for '{name}': {e}")
            skipped_count += 1
            continue

        if not data or "_error" in data:
            err_msg = data.get("_error", f"Not found: '{name}'") if data else f"Not found: '{name}'"
            errors.append(err_msg)
            skipped_count += 1
            continue

        conn.execute(
            """UPDATE collection_entries SET
                type_line = ?, subtypes = ?, is_legendary = ?, is_basic = ?,
                color_identity = ?, cmc = ?, mana_cost = ?,
                oracle_text = ?, keywords = ?,
                power = ?, toughness = ?,
                rarity = ?, set_name = ?, edhrec_rank = ?,
                tcg_price = ?, scryfall_id = ?, tcgplayer_id = ?,
                category = ?,
                updated_at = datetime('now')
            WHERE id = ?""",
            (
                data.get("type_line", ""),
                data.get("subtypes", "[]"),
                data.get("is_legendary", 0),
                data.get("is_basic", 0),
                data.get("color_identity", "[]"),
                data.get("cmc", 0.0),
                data.get("mana_cost", ""),
                data.get("oracle_text", ""),
                data.get("keywords", "[]"),
                data.get("power", ""),
                data.get("toughness", ""),
                data.get("rarity", ""),
                data.get("set_name", ""),
                data.get("edhrec_rank", 0),
                data.get("tcg_price", 0.0),
                data.get("scryfall_id", ""),
                data.get("tcgplayer_id", ""),
                data.get("category", "[]"),
                card_id,
            ),
        )
        conn.commit()
        enriched_count += 1

    return {
        "total": total,
        "enrichedCount": enriched_count,
        "skippedCount": skipped_count,
        "errors": errors[:50],  # cap error list
    }


# ══════════════════════════════════════════════════════════════
# Auto-Classify Collection
# ══════════════════════════════════════════════════════════════

@app.post("/api/collection/auto-classify")
async def auto_classify_collection():
    """
    Run auto-classification on all collection entries.
    Uses oracle_text, type_line, and keywords to detect functional roles
    (Ramp, Draw, Removal, Board Wipe, Anthem, Stax, etc.).
    Only updates cards whose current category is empty or '[]'.
    """
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT id, oracle_text, type_line, keywords, category FROM collection_entries ORDER BY id"
    ).fetchall()

    total = len(rows)
    classified_count = 0
    skipped_count = 0

    for row in rows:
        card_id = row["id"]
        existing_cats = row["category"] or "[]"

        # Parse existing categories
        try:
            cats = json.loads(existing_cats)
        except Exception:
            cats = []

        # Skip cards that already have manually-set categories
        if cats:
            skipped_count += 1
            continue

        oracle_text = row["oracle_text"] or ""
        type_line = row["type_line"] or ""
        keywords = row["keywords"] or "[]"

        roles = _detect_card_roles(oracle_text, type_line, keywords)

        if roles:
            conn.execute(
                "UPDATE collection_entries SET category = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(roles), card_id),
            )
            classified_count += 1

    conn.commit()

    return {
        "total": total,
        "classifiedCount": classified_count,
        "skippedCount": skipped_count,
        "message": f"Classified {classified_count} cards, skipped {skipped_count} (already had categories)",
    }


@app.post("/api/collection/auto-classify-all")
async def auto_classify_all_collection():
    """
    Force re-classify ALL collection entries, overwriting existing categories.
    """
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT id, oracle_text, type_line, keywords FROM collection_entries ORDER BY id"
    ).fetchall()

    total = len(rows)
    classified_count = 0

    for row in rows:
        card_id = row["id"]
        oracle_text = row["oracle_text"] or ""
        type_line = row["type_line"] or ""
        keywords = row["keywords"] or "[]"

        roles = _detect_card_roles(oracle_text, type_line, keywords)
        conn.execute(
            "UPDATE collection_entries SET category = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(roles), card_id),
        )
        classified_count += 1

    conn.commit()

    return {
        "total": total,
        "classifiedCount": classified_count,
        "message": f"Re-classified all {classified_count} cards",
    }


# ══════════════════════════════════════════════════════════════
# EDHREC Recommendations Cache + Endpoint
# ══════════════════════════════════════════════════════════════

# Simple in-memory cache: {cache_key: {"data": ..., "expires": float}}
_edhrec_cache: dict = {}
_EDHREC_TTL = 3600  # 1 hour


def _edhrec_cache_get(key: str):
    entry = _edhrec_cache.get(key)
    if entry and time.monotonic() < entry["expires"]:
        return entry["data"]
    return None


def _edhrec_cache_set(key: str, data):
    _edhrec_cache[key] = {"data": data, "expires": time.monotonic() + _EDHREC_TTL}


@app.get("/api/collection/{cardId}/edhrec")
async def get_card_edhrec(cardId: int):
    """
    Get EDHREC recommendations for a collection card.
    For legendary creatures (potential commanders): fetch commander synergy data.
    For other cards: fetch 'also played with' data.
    """
    conn = _get_db_conn()
    row = conn.execute("SELECT * FROM collection_entries WHERE id = ?", (cardId,)).fetchone()
    if not row:
        raise HTTPException(404, f"Card with id {cardId} not found")

    card = _row_to_dict(row)
    name = card["name"]
    type_line = card.get("type_line", "")
    is_legendary = card.get("is_legendary", 0)

    # Determine if it's a legendary creature (potential commander)
    is_commander = bool(
        is_legendary and
        re.search(r"\bCreature\b", type_line, re.IGNORECASE)
    )

    slug = _to_edhrec_slug(name)
    cache_key = f"edhrec:{'cmd' if is_commander else 'card'}:{slug}"

    cached = _edhrec_cache_get(cache_key)
    if cached:
        return cached

    recommendations = []
    links = {
        "edhrecPage": (
            f"https://edhrec.com/commanders/{slug}"
            if is_commander
            else f"https://edhrec.com/cards/{slug}"
        ),
        "archidektSearch": f"https://archidekt.com/search/cards?q={name.replace(' ', '+')}",
        "moxfieldSearch": f"https://www.moxfield.com/search?q={name.replace(' ', '+')}",
    }

    try:
        if is_commander:
            url = f"https://json.edhrec.com/pages/commanders/{slug}.json"
        else:
            url = f"https://json.edhrec.com/pages/cards/{slug}.json"

        req = Request(url, headers=_API_HEADERS)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if is_commander:
            # Extract top cards from cardlists
            container = data.get("container", {})
            json_dict = container.get("json_dict", {})
            for cardlist in json_dict.get("cardlists", []):
                tag = cardlist.get("tag", "")
                for cv in cardlist.get("cardviews", [])[:10]:
                    rec_name = cv.get("name", "")
                    if not rec_name:
                        continue
                    synergy = cv.get("synergy", 0.0)
                    recommendations.append({
                        "name": rec_name,
                        "synergy": synergy,
                        "role": tag or "Recommended",
                    })
        else:
            # Extract "also played with" cards
            container = data.get("container", {})
            json_dict = container.get("json_dict", {})
            for cardlist in json_dict.get("cardlists", []):
                tag = cardlist.get("tag", "")
                for cv in cardlist.get("cardviews", [])[:10]:
                    rec_name = cv.get("name", "")
                    if not rec_name:
                        continue
                    synergy = cv.get("synergy", 0.0)
                    recommendations.append({
                        "name": rec_name,
                        "synergy": synergy,
                        "role": tag or "Also Played With",
                    })

    except Exception as e:
        log_deckgen.error(f"  Error fetching data for '{name}': {e}")
        # Graceful degradation — return empty results

    result = {
        "recommendations": recommendations[:30],
        "links": links,
    }
    _edhrec_cache_set(cache_key, result)
    return result


# ══════════════════════════════════════════════════════════════
# Commander Meta Mapping (loaded at startup)
# ══════════════════════════════════════════════════════════════

BUILTIN_COMMANDERS = {
    "Edgar Markov": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["W","B","R"]}],
    "Atraxa, Praetors' Voice": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["W","U","B","G"]}],
    "Korvold, Fae-Cursed King": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["B","R","G"]}],
    "Muldrotha, the Gravetide": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["U","B","G"]}],
    "The Ur-Dragon": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["W","U","B","R","G"]}],
    "Yuriko, the Tiger's Shadow": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["U","B"]}],
    "Krenko, Mob Boss": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["R"]}],
    "Meren of Clan Nel Toth": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["B","G"]}],
    "Prossh, Skyraider of Kher": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["B","R","G"]}],
    "Kaalia of the Vast": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["W","B","R"]}],
    "Talrand, Sky Summoner": [{"source": "edhrec", "archetype": "control", "colorIdentity": ["U"]}],
    "Omnath, Locus of Creation": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["W","U","R","G"]}],
    "Teysa Karlov": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["W","B"]}],
    "Lathril, Blade of the Elves": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["B","G"]}],
    "Breya, Etherium Shaper": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["W","U","B","R"]}],
}


# ══════════════════════════════════════════════════════════════
# Python Simulator API
# ══════════════════════════════════════════════════════════════

import threading as _threading
import uuid as _uuid

# In-memory store for simulation runs
_sim_runs = {}  # sim_id -> { status, result, error }
_sim_lock = _threading.Lock()


def _run_sim_thread_v2(sim_id: str, card_data: list[dict], num_games: int, deck_name: str, record_logs: bool):
    """Background thread for simulations with full card data from the DB."""
    try:
        import sys, os
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.sim.rules import enrich_card
        from commander_ai_lab.lab.experiments import _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        # Build deck with real card data from DB
        deck_a = []
        for cd in card_data:
            c = Card(name=cd['name'])
            if cd.get('type_line'):
                c.type_line = cd['type_line']
            if cd.get('cmc'):
                c.cmc = float(cd['cmc'])
            if cd.get('power') and cd.get('toughness'):
                c.power = str(cd['power'])
                c.toughness = str(cd['toughness'])
                c.pt = c.power + '/' + c.toughness
            if cd.get('oracle_text'):
                c.oracle_text = cd['oracle_text']
            if cd.get('mana_cost'):
                c.mana_cost = cd['mana_cost']
            if cd.get('keywords'):
                kw = cd['keywords']
                if isinstance(kw, str):
                    try:
                        import json as _json
                        kw = _json.loads(kw)
                    except Exception:
                        kw = []
                if isinstance(kw, list):
                    c.keywords = kw
            # Enrich fills in flags like is_removal, is_ramp, is_board_wipe
            enrich_card(c)
            deck_a.append(c)

        deck_b = _generate_training_deck()

        engine = GameEngine(max_turns=25, record_log=record_logs)
        import time
        start = time.time()

        wins = 0
        losses = 0
        total_turns = 0
        total_damage_dealt = 0
        total_damage_received = 0
        total_spells_cast = 0
        total_creatures_played = 0
        total_removal_used = 0
        total_ramp_played = 0
        total_cards_drawn = 0
        total_max_board = 0
        game_results = []

        for i in range(num_games):
            result = engine.run(deck_a, deck_b, name_a=deck_name, name_b="Training Deck")

            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if result.winner == 0:
                wins += 1
            else:
                losses += 1

            total_turns += result.turns
            if result.player_a_stats:
                total_damage_dealt += result.player_a_stats.damage_dealt
                total_damage_received += result.player_a_stats.damage_received
                total_spells_cast += result.player_a_stats.spells_cast
                total_creatures_played += result.player_a_stats.creatures_played
                total_removal_used += result.player_a_stats.removal_used
                total_ramp_played += result.player_a_stats.ramp_played
                total_cards_drawn += result.player_a_stats.cards_drawn
                total_max_board += result.player_a_stats.max_board_size

            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games

        summary = {
            'deckName': deck_name,
            'opponentName': 'Training Deck',
            'totalGames': n,
            'wins': wins,
            'losses': losses,
            'winRate': round(wins / n * 100, 1) if n > 0 else 0.0,
            'avgTurns': round(total_turns / n, 1) if n > 0 else 0.0,
            'avgDamageDealt': round(total_damage_dealt / n, 1) if n > 0 else 0.0,
            'avgDamageReceived': round(total_damage_received / n, 1) if n > 0 else 0.0,
            'avgSpellsCast': round(total_spells_cast / n, 1) if n > 0 else 0.0,
            'avgCreaturesPlayed': round(total_creatures_played / n, 1) if n > 0 else 0.0,
            'avgRemovalUsed': round(total_removal_used / n, 1) if n > 0 else 0.0,
            'avgRampPlayed': round(total_ramp_played / n, 1) if n > 0 else 0.0,
            'avgCardsDrawn': round(total_cards_drawn / n, 1) if n > 0 else 0.0,
            'avgMaxBoardSize': round(total_max_board / n, 1) if n > 0 else 0.0,
            'elapsedSeconds': round(elapsed, 3),
        }

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'complete'
            _sim_runs[sim_id]['result'] = {
                'summary': summary,
                'games': game_results,
            }
    except Exception as e:
        import traceback
        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'error'
            _sim_runs[sim_id]['error'] = str(e)
        traceback.print_exc()


def _run_sim_thread(sim_id: str, decklist: list, num_games: int, deck_name: str, record_logs: bool):
    """Background thread for running Monte Carlo simulations."""
    try:
        import sys, os
        # Add src/ to path if needed for the simulator package
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.sim.rules import enrich_card, parse_decklist
        from commander_ai_lab.lab.experiments import build_deck, _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        deck_a = build_deck(decklist)
        deck_b = _generate_training_deck()

        engine = GameEngine(max_turns=25, record_log=record_logs)
        import time
        start = time.time()

        wins = 0
        losses = 0
        total_turns = 0
        total_damage_dealt = 0
        total_damage_received = 0
        total_spells_cast = 0
        total_creatures_played = 0
        total_removal_used = 0
        total_ramp_played = 0
        total_cards_drawn = 0
        total_max_board = 0
        game_results = []

        for i in range(num_games):
            result = engine.run(deck_a, deck_b, name_a=deck_name, name_b="Training Deck")

            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if result.winner == 0:
                wins += 1
            else:
                losses += 1

            total_turns += result.turns
            if result.player_a_stats:
                total_damage_dealt += result.player_a_stats.damage_dealt
                total_damage_received += result.player_a_stats.damage_received
                total_spells_cast += result.player_a_stats.spells_cast
                total_creatures_played += result.player_a_stats.creatures_played
                total_removal_used += result.player_a_stats.removal_used
                total_ramp_played += result.player_a_stats.ramp_played
                total_cards_drawn += result.player_a_stats.cards_drawn
                total_max_board += result.player_a_stats.max_board_size

            # Update progress
            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games

        summary = {
            'deckName': deck_name,
            'opponentName': 'Training Deck',
            'totalGames': n,
            'wins': wins,
            'losses': losses,
            'winRate': round(wins / n * 100, 1) if n > 0 else 0.0,
            'avgTurns': round(total_turns / n, 1) if n > 0 else 0.0,
            'avgDamageDealt': round(total_damage_dealt / n, 1) if n > 0 else 0.0,
            'avgDamageReceived': round(total_damage_received / n, 1) if n > 0 else 0.0,
            'avgSpellsCast': round(total_spells_cast / n, 1) if n > 0 else 0.0,
            'avgCreaturesPlayed': round(total_creatures_played / n, 1) if n > 0 else 0.0,
            'avgRemovalUsed': round(total_removal_used / n, 1) if n > 0 else 0.0,
            'avgRampPlayed': round(total_ramp_played / n, 1) if n > 0 else 0.0,
            'avgCardsDrawn': round(total_cards_drawn / n, 1) if n > 0 else 0.0,
            'avgMaxBoardSize': round(total_max_board / n, 1) if n > 0 else 0.0,
            'elapsedSeconds': round(elapsed, 3),
        }

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'complete'
            _sim_runs[sim_id]['result'] = {
                'summary': summary,
                'games': game_results,
            }
    except Exception as e:
        import traceback
        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'error'
            _sim_runs[sim_id]['error'] = str(e)
        traceback.print_exc()


@app.post('/api/sim/run')
async def sim_run(request: FastAPIRequest):
    """Start a Monte Carlo simulation with the Python engine."""
    body = await request.json()
    decklist = body.get('decklist', [])
    num_games = body.get('numGames', 10)
    deck_name = body.get('deckName', 'My Deck')
    record_logs = body.get('recordLogs', True)

    if not decklist:
        return JSONResponse({'error': 'decklist is required'}, status_code=400)
    if num_games < 1 or num_games > 1000:
        return JSONResponse({'error': 'numGames must be 1-1000'}, status_code=400)

    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued',
            'completed': 0,
            'total': num_games,
            'deckName': deck_name,
            'result': None,
            'error': None,
        }

    t = _threading.Thread(target=_run_sim_thread, args=(sim_id, decklist, num_games, deck_name, record_logs), daemon=True)
    t.start()

    return JSONResponse({'simId': sim_id, 'status': 'queued', 'total': num_games})


@app.get('/api/sim/status')
async def sim_status(simId: str):
    """Poll simulation progress."""
    with _sim_lock:
        run = _sim_runs.get(simId)
    if not run:
        return JSONResponse({'error': 'sim not found'}, status_code=404)
    return JSONResponse({
        'simId': simId,
        'status': run['status'],
        'completed': run['completed'],
        'total': run['total'],
        'deckName': run.get('deckName', ''),
        'error': run.get('error'),
    })


@app.get('/api/sim/result')
async def sim_result(simId: str):
    """Get completed simulation results."""
    with _sim_lock:
        run = _sim_runs.get(simId)
    if not run:
        return JSONResponse({'error': 'sim not found'}, status_code=404)
    if run['status'] != 'complete':
        return JSONResponse({'error': 'sim not complete', 'status': run['status']}, status_code=400)
    return JSONResponse(run['result'])


@app.post('/api/sim/run-from-deck')
async def sim_run_from_deck(request: FastAPIRequest):
    """Start simulation using a deck from the Deck Builder (by deck ID)."""
    body = await request.json()
    deck_id = body.get('deckId')
    num_games = body.get('numGames', 10)
    record_logs = body.get('recordLogs', True)

    if not deck_id:
        return JSONResponse({'error': 'deckId required'}, status_code=400)

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT name FROM decks WHERE id = ?', (deck_id,))
    row = cur.fetchone()
    if not row:
        return JSONResponse({'error': 'deck not found'}, status_code=404)
    deck_name = row[0]

    # Pull full card data from collection join so the sim engine has real types/stats
    cur.execute("""
        SELECT dc.card_name, dc.quantity,
               ce.type_line, ce.cmc, ce.power, ce.toughness,
               ce.oracle_text, ce.keywords, ce.mana_cost
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, cmc, power, toughness,
                   oracle_text, keywords, mana_cost
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
    """, (deck_id,))
    card_data = []
    for r in cur.fetchall():
        for _ in range(r[1] or 1):
            card_data.append({
                'name': r[0],
                'type_line': r[2] or '',
                'cmc': r[3] or 0,
                'power': r[4] or '',
                'toughness': r[5] or '',
                'oracle_text': r[6] or '',
                'keywords': r[7] or '',
                'mana_cost': r[8] or '',
            })
    if not card_data:
        return JSONResponse({'error': 'deck has no cards'}, status_code=400)

    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued',
            'completed': 0,
            'total': num_games,
            'deckName': deck_name,
            'result': None,
            'error': None,
        }

    t = _threading.Thread(target=_run_sim_thread_v2, args=(sim_id, card_data, num_games, deck_name, record_logs), daemon=True)
    t.start()

    return JSONResponse({'simId': sim_id, 'status': 'queued', 'total': num_games, 'deckName': deck_name})


# ══════════════════════════════════════════════════════════════
# DeepSeek AI Opponent Brain
# ══════════════════════════════════════════════════════════════

# Global DeepSeek brain instance (lazy-initialized)
_deepseek_brain = None
_deepseek_lock = _threading.Lock()

def _get_deepseek_brain():
    """Get or create the global DeepSeek brain instance."""
    global _deepseek_brain
    if _deepseek_brain is None:
        with _deepseek_lock:
            if _deepseek_brain is None:
                try:
                    import sys as _sys2, os as _os2
                    src_dir = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), 'src')
                    if src_dir not in _sys2.path:
                        _sys2.path.insert(0, src_dir)
                    from commander_ai_lab.sim.deepseek_brain import DeepSeekBrain, DeepSeekConfig
                    cfg = DeepSeekConfig()
                    # Allow env var overrides
                    if _os2.environ.get('DEEPSEEK_API_BASE'):
                        cfg.api_base = _os2.environ['DEEPSEEK_API_BASE']
                    if _os2.environ.get('DEEPSEEK_MODEL'):
                        cfg.model = _os2.environ['DEEPSEEK_MODEL']
                    cfg.log_dir = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), 'logs', 'decisions')
                    _deepseek_brain = DeepSeekBrain(cfg)
                except Exception as e:
                    log_sim.error(f'Failed to initialize brain: {e}')
                    return None
    return _deepseek_brain


@app.post('/api/deepseek/connect')
async def deepseek_connect(request: FastAPIRequest):
    """Test connection to the DeepSeek LLM endpoint and auto-detect model."""
    body = await request.json() if await request.body() else {}
    api_base = body.get('apiBase', None)
    model = body.get('model', None)

    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'DeepSeek brain failed to initialize'}, status_code=500)

    # Allow runtime reconfiguration
    if api_base:
        brain.config.api_base = api_base
    if model:
        brain.config.model = model

    connected = brain.check_connection()
    return JSONResponse({
        'connected': connected,
        'apiBase': brain.config.api_base,
        'model': brain.config.model,
        'stats': brain.get_stats(),
    })


@app.get('/api/deepseek/status')
async def deepseek_status():
    """Get DeepSeek brain status and performance stats."""
    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'connected': False, 'error': 'Brain not initialized'})
    return JSONResponse(brain.get_stats())


@app.post('/api/deepseek/configure')
async def deepseek_configure(request: FastAPIRequest):
    """Update DeepSeek configuration at runtime."""
    body = await request.json()
    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'Brain not initialized'}, status_code=500)

    if 'apiBase' in body:
        brain.config.api_base = body['apiBase']
    if 'model' in body:
        brain.config.model = body['model']
    if 'temperature' in body:
        brain.config.temperature = float(body['temperature'])
    if 'maxTokens' in body:
        brain.config.max_tokens = int(body['maxTokens'])
    if 'timeout' in body:
        brain.config.request_timeout = float(body['timeout'])
    if 'cacheEnabled' in body:
        brain.config.cache_enabled = bool(body['cacheEnabled'])
    if 'logDecisions' in body:
        brain.config.log_decisions = bool(body['logDecisions'])
    if 'fallbackOnTimeout' in body:
        brain.config.fallback_on_timeout = bool(body['fallbackOnTimeout'])

    # Re-test connection with new settings
    connected = brain.check_connection()

    return JSONResponse({
        'connected': connected,
        'config': {
            'apiBase': brain.config.api_base,
            'model': brain.config.model,
            'temperature': brain.config.temperature,
            'maxTokens': brain.config.max_tokens,
            'timeout': brain.config.request_timeout,
            'cacheEnabled': brain.config.cache_enabled,
            'logDecisions': brain.config.log_decisions,
            'fallbackOnTimeout': brain.config.fallback_on_timeout,
        },
    })


@app.get('/api/deepseek/logs')
async def deepseek_logs():
    """Get decision log stats and flush pending entries."""
    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'Brain not initialized'}, status_code=500)

    pending = len(brain._decision_log)
    flushed_path = None
    if pending > 0:
        try:
            flushed_path = brain.flush_log()
        except Exception as e:
            return JSONResponse({'error': f'Failed to flush: {e}'}, status_code=500)

    # List existing log files
    import glob as _glob
    log_dir = brain.config.log_dir
    log_files = []
    if log_dir and os.path.isdir(log_dir):
        for f in sorted(_glob.glob(os.path.join(log_dir, 'decisions_*.jsonl'))):
            stat = os.stat(f)
            log_files.append({
                'filename': os.path.basename(f),
                'size_bytes': stat.st_size,
                'modified': stat.st_mtime,
            })

    return JSONResponse({
        'flushed': pending,
        'flushedPath': flushed_path,
        'logFiles': log_files[-20:],  # last 20
    })


def _run_sim_thread_deepseek(sim_id: str, card_data: list[dict], num_games: int, deck_name: str, record_logs: bool):
    """Background thread for simulations using DeepSeek AI opponent."""
    try:
        import sys, os
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine
        from commander_ai_lab.sim.rules import enrich_card
        from commander_ai_lab.lab.experiments import _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        # Build player's deck with real card data
        deck_a = []
        for cd in card_data:
            c = Card(name=cd['name'])
            if cd.get('type_line'):
                c.type_line = cd['type_line']
            if cd.get('cmc'):
                c.cmc = float(cd['cmc'])
            if cd.get('power') and cd.get('toughness'):
                c.power = str(cd['power'])
                c.toughness = str(cd['toughness'])
                c.pt = c.power + '/' + c.toughness
            if cd.get('oracle_text'):
                c.oracle_text = cd['oracle_text']
            if cd.get('mana_cost'):
                c.mana_cost = cd['mana_cost']
            if cd.get('keywords'):
                kw = cd['keywords']
                if isinstance(kw, str):
                    try:
                        import json as _json
                        kw = _json.loads(kw)
                    except Exception:
                        kw = []
                if isinstance(kw, list):
                    c.keywords = kw
            enrich_card(c)
            deck_a.append(c)

        deck_b = _generate_training_deck()

        # Get DeepSeek brain
        brain = _get_deepseek_brain()
        if brain and not brain._connected:
            brain.check_connection()

        engine = DeepSeekGameEngine(
            brain=brain,
            ai_player_index=1,  # Training deck is player B (index 1)
            max_turns=25,
            record_log=record_logs,
        )

        import time
        start = time.time()

        wins = 0
        losses = 0
        total_turns = 0
        total_damage_dealt = 0
        total_damage_received = 0
        total_spells_cast = 0
        total_creatures_played = 0
        total_removal_used = 0
        total_ramp_played = 0
        total_cards_drawn = 0
        total_max_board = 0
        game_results = []

        for i in range(num_games):
            game_id = f'ds-sim-{sim_id[:8]}-g{i+1}'
            result = engine.run(deck_a, deck_b, name_a=deck_name, name_b='DeepSeek AI',
                               game_id=game_id, archetype='midrange')

            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if result.winner == 0:
                wins += 1
            else:
                losses += 1

            total_turns += result.turns
            if result.player_a_stats:
                total_damage_dealt += result.player_a_stats.damage_dealt
                total_damage_received += result.player_a_stats.damage_received
                total_spells_cast += result.player_a_stats.spells_cast
                total_creatures_played += result.player_a_stats.creatures_played
                total_removal_used += result.player_a_stats.removal_used
                total_ramp_played += result.player_a_stats.ramp_played
                total_cards_drawn += result.player_a_stats.cards_drawn
                total_max_board += result.player_a_stats.max_board_size

            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games

        # Write ML decision JSONL for training pipeline
        ml_decisions = engine.flush_ml_decisions()
        if ml_decisions:
            ml_jsonl_path = os.path.join('results', f'ml-decisions-sim-{sim_id[:8]}.jsonl')
            os.makedirs('results', exist_ok=True)
            with open(ml_jsonl_path, 'w', encoding='utf-8') as mf:
                import json as _mljson
                for dec in ml_decisions:
                    mf.write(_mljson.dumps(dec) + '\n')

        # Get DeepSeek stats for the summary
        ds_stats = brain.get_stats() if brain else {}

        summary = {
            'deckName': deck_name,
            'opponentName': 'DeepSeek AI',
            'opponentType': 'deepseek',
            'totalGames': n,
            'wins': wins,
            'losses': losses,
            'winRate': round(wins / n * 100, 1) if n > 0 else 0.0,
            'avgTurns': round(total_turns / n, 1) if n > 0 else 0.0,
            'avgDamageDealt': round(total_damage_dealt / n, 1) if n > 0 else 0.0,
            'avgDamageReceived': round(total_damage_received / n, 1) if n > 0 else 0.0,
            'avgSpellsCast': round(total_spells_cast / n, 1) if n > 0 else 0.0,
            'avgCreaturesPlayed': round(total_creatures_played / n, 1) if n > 0 else 0.0,
            'avgRemovalUsed': round(total_removal_used / n, 1) if n > 0 else 0.0,
            'avgRampPlayed': round(total_ramp_played / n, 1) if n > 0 else 0.0,
            'avgCardsDrawn': round(total_cards_drawn / n, 1) if n > 0 else 0.0,
            'avgMaxBoardSize': round(total_max_board / n, 1) if n > 0 else 0.0,
            'elapsedSeconds': round(elapsed, 3),
            'deepseekStats': ds_stats,
        }

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'complete'
            _sim_runs[sim_id]['result'] = {
                'summary': summary,
                'games': game_results,
            }
    except Exception as e:
        import traceback
        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'error'
            _sim_runs[sim_id]['error'] = str(e)
        traceback.print_exc()


@app.post('/api/sim/run-deepseek')
async def sim_run_deepseek(request: FastAPIRequest):
    """Start simulation using DeepSeek AI as the opponent brain."""
    body = await request.json()
    deck_id = body.get('deckId')
    num_games = body.get('numGames', 5)  # Default 5 (LLM is slower)
    record_logs = body.get('recordLogs', True)

    if not deck_id:
        return JSONResponse({'error': 'deckId required'}, status_code=400)
    if num_games < 1 or num_games > 50:
        return JSONResponse({'error': 'numGames must be 1-50 for DeepSeek mode'}, status_code=400)

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT name FROM decks WHERE id = ?', (deck_id,))
    row = cur.fetchone()
    if not row:
        return JSONResponse({'error': 'deck not found'}, status_code=404)
    deck_name = row[0]

    cur.execute("""
        SELECT dc.card_name, dc.quantity,
               ce.type_line, ce.cmc, ce.power, ce.toughness,
               ce.oracle_text, ce.keywords, ce.mana_cost
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, cmc, power, toughness,
                   oracle_text, keywords, mana_cost
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
    """, (deck_id,))
    card_data = []
    for r in cur.fetchall():
        for _ in range(r[1] or 1):
            card_data.append({
                'name': r[0],
                'type_line': r[2] or '',
                'cmc': r[3] or 0,
                'power': r[4] or '',
                'toughness': r[5] or '',
                'oracle_text': r[6] or '',
                'keywords': r[7] or '',
                'mana_cost': r[8] or '',
            })
    if not card_data:
        return JSONResponse({'error': 'deck has no cards'}, status_code=400)

    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued',
            'completed': 0,
            'total': num_games,
            'deckName': deck_name,
            'result': None,
            'error': None,
        }

    t = _threading.Thread(
        target=_run_sim_thread_deepseek,
        args=(sim_id, card_data, num_games, deck_name, record_logs),
        daemon=True,
    )
    t.start()

    return JSONResponse({
        'simId': sim_id,
        'status': 'queued',
        'total': num_games,
        'deckName': deck_name,
        'opponentType': 'deepseek',
    })


# ══════════════════════════════════════════════════════════════
# Auto Deck Generator
# ══════════════════════════════════════════════════════════════


def _resolve_commander(req: DeckGenerationRequest) -> dict:
    """
    Resolve commander info from a DeckGenerationRequest.
    Returns dict with: name, scryfall_id, color_identity, type_line, mana_cost, image_url
    """
    conn = _get_db_conn()

    # Try scryfall_id first
    if req.commander_scryfall_id:
        row = conn.execute(
            "SELECT name, type_line, color_identity, mana_cost, scryfall_id FROM collection_entries WHERE scryfall_id = ? LIMIT 1",
            (req.commander_scryfall_id,)
        ).fetchone()
        if row:
            ci = row["color_identity"]
            if isinstance(ci, str):
                try:
                    ci = json.loads(ci)
                except Exception:
                    ci = []
            return {
                "name": row["name"],
                "scryfall_id": row["scryfall_id"],
                "color_identity": ci,
                "type_line": row["type_line"],
                "mana_cost": row["mana_cost"] or "",
                "image_url": f"https://api.scryfall.com/cards/{row['scryfall_id']}?format=image&version=normal",
            }
        # Fallback to Scryfall API
        _scryfall_rate_limit()
        try:
            url = f"https://api.scryfall.com/cards/{req.commander_scryfall_id}"
            rq = Request(url, headers={"User-Agent": "CommanderAILab/1.0", "Accept": "application/json"})
            with urlopen(rq, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return _scryfall_to_commander(data)
        except Exception:
            pass

    # Try name search
    if req.commander_name:
        name_lower = req.commander_name.strip().lower()
        row = conn.execute(
            "SELECT name, type_line, color_identity, mana_cost, scryfall_id FROM collection_entries WHERE LOWER(name) = ? LIMIT 1",
            (name_lower,)
        ).fetchone()
        if row:
            ci = row["color_identity"]
            if isinstance(ci, str):
                try:
                    ci = json.loads(ci)
                except Exception:
                    ci = []
            return {
                "name": row["name"],
                "scryfall_id": row["scryfall_id"],
                "color_identity": ci,
                "type_line": row["type_line"],
                "mana_cost": row["mana_cost"] or "",
                "image_url": f"https://api.scryfall.com/cards/{row['scryfall_id']}?format=image&version=normal",
            }

        # Fallback to Scryfall fuzzy search
        _scryfall_rate_limit()
        try:
            import urllib.parse
            encoded = urllib.parse.quote(req.commander_name)
            url = f"https://api.scryfall.com/cards/named?fuzzy={encoded}"
            rq = Request(url, headers={"User-Agent": "CommanderAILab/1.0", "Accept": "application/json"})
            with urlopen(rq, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return _scryfall_to_commander(data)
        except Exception:
            pass

    return None


def _scryfall_to_commander(data: dict) -> dict:
    """Convert Scryfall API response to commander info dict."""
    ci = data.get("color_identity", [])
    image_uris = data.get("image_uris", {})
    if not image_uris and data.get("card_faces"):
        image_uris = data["card_faces"][0].get("image_uris", {})
    return {
        "name": data.get("name", ""),
        "scryfall_id": data.get("id", ""),
        "color_identity": ci,
        "type_line": data.get("type_line", ""),
        "mana_cost": data.get("mana_cost", ""),
        "image_url": image_uris.get("normal", ""),
    }


def _get_collection_for_colors(color_identity: list) -> list:
    """
    Fetch all collection cards compatible with the given color identity.
    Returns list of dicts with card details.
    """
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT * FROM collection_entries WHERE quantity > 0"
    ).fetchall()

    valid = []
    for row in rows:
        card = _row_to_dict(row)
        card_ci = card.get("color_identity", [])
        if isinstance(card_ci, str):
            try:
                card_ci = json.loads(card_ci)
            except Exception:
                card_ci = []

        # Color identity check: all card colors must be within commander's identity
        if color_identity and card_ci:
            if not all(c in color_identity for c in card_ci):
                continue

        # Skip if no scryfall_id
        if not card.get("scryfall_id"):
            continue

        card["color_identity"] = card_ci
        valid.append(card)

    return valid


def _generate_deck(req: DeckGenerationRequest) -> dict:
    """
    Core deck generation algorithm.

    1. Resolve commander
    2. Load collection filtered to color identity
    3. Call enabled source adapters (stubbed)
    4. Build candidate pool, score by role/type fit
    5. Fill slots per target ratios, preferring owned cards
    6. Return response dict
    """
    # 1. Resolve commander
    commander = _resolve_commander(req)
    if not commander:
        return {"error": "Commander not found. Please check the name or Scryfall ID."}

    color_identity = req.color_identity or commander.get("color_identity", [])
    log_deckgen.info(f"  Commander: {commander['name']}, CI: {color_identity}")

    # 2. Load collection
    collection = _get_collection_for_colors(color_identity)
    log_deckgen.info(f"  {len(collection)} cards in collection match color identity")

    # 3. Call source adapters (currently stubbed)
    template_cards = []  # list of (name, weight, source_name)
    sources = req.sources or DeckGenerationSourceConfig()

    try:
        if sources.use_archidekt:
            from deck_sources.archidekt_adapter import fetch_template_decks as archidekt_fetch
            for td in archidekt_fetch(commander["name"], color_identity, {"url": sources.archidekt_url}):
                for tc in td.cards:
                    template_cards.append((tc.name, tc.quantity, "archidekt"))
    except Exception as e:
        log_deckgen.error(f"  Archidekt adapter error: {e}")

    try:
        if sources.use_edhrec:
            from deck_sources.edhrec_adapter import fetch_template_decks as edhrec_fetch
            for td in edhrec_fetch(commander["name"], color_identity):
                for tc in td.cards:
                    template_cards.append((tc.name, tc.quantity, "edhrec"))
    except Exception as e:
        log_deckgen.error(f"  EDHREC adapter error: {e}")

    try:
        if sources.use_moxfield:
            from deck_sources.moxfield_adapter import fetch_template_decks as moxfield_fetch
            for td in moxfield_fetch(commander["name"], color_identity, {"url": sources.moxfield_url}):
                for tc in td.cards:
                    template_cards.append((tc.name, tc.quantity, "moxfield"))
    except Exception as e:
        log_deckgen.error(f"  Moxfield adapter error: {e}")

    try:
        if sources.use_mtggoldfish:
            from deck_sources.mtggoldfish_adapter import fetch_template_decks as mtggoldfish_fetch
            for td in mtggoldfish_fetch(commander["name"], color_identity, {"url": sources.mtggoldfish_url}):
                for tc in td.cards:
                    template_cards.append((tc.name, tc.quantity, "mtggoldfish"))
    except Exception as e:
        log_deckgen.error(f"  MTGGoldfish adapter error: {e}")

    # 4. Build candidate pool from collection, scored by type need
    #    Build a map: name_lower -> card dict (deduped)
    candidate_map = {}
    for card in collection:
        name = card.get("name", "")
        if not name:
            continue
        key = name.lower()
        # Skip the commander itself
        if key == commander["name"].lower():
            continue
        if key not in candidate_map:
            type_line = card.get("type_line", "")
            card_type = _classify_card_type(type_line)
            card_roles = _detect_card_roles(
                card.get("oracle_text", ""),
                type_line,
                card.get("keywords", [])
            )
            candidate_map[key] = {
                "scryfall_id": card.get("scryfall_id", ""),
                "name": name,
                "type_line": type_line,
                "mana_cost": card.get("mana_cost", ""),
                "cmc": float(card.get("cmc", 0)),
                "card_type": card_type,
                "roles": card_roles,
                "source": "collection",
                "quantity": 1,
                "owned_qty": int(card.get("quantity", 0)),
                "is_proxy": False,
                "edhrec_rank": int(card.get("edhrec_rank", 99999)),
                "image_url": f"https://api.scryfall.com/cards/{card.get('scryfall_id', '')}?format=image&version=normal"
                             if card.get("scryfall_id") else "",
            }
        else:
            # Merge quantities
            candidate_map[key]["owned_qty"] += int(card.get("quantity", 0))

    # Add template cards that aren't in collection (as potential proxies)
    for tname, tqty, tsource in template_cards:
        key = tname.lower()
        if key == commander["name"].lower():
            continue
        if key in candidate_map:
            # Boost priority for cards that appear in templates
            candidate_map[key]["_template_weight"] = candidate_map[key].get("_template_weight", 0) + tqty
            if candidate_map[key]["source"] == "collection":
                candidate_map[key]["source"] = f"collection+{tsource}"
        elif req.allow_proxies:
            candidate_map[key] = {
                "scryfall_id": "",
                "name": tname,
                "type_line": "",
                "mana_cost": "",
                "cmc": 0,
                "card_type": "Other",
                "roles": [],
                "source": tsource,
                "quantity": 1,
                "owned_qty": 0,
                "is_proxy": True,
                "edhrec_rank": 99999,
                "image_url": "",
                "_template_weight": tqty,
            }

    # 5. Fill slots per target ratios
    targets = {
        "Land": req.target_land_count,
        "Creature": req.target_creature_count,
        "Instant": req.target_instant_count,
        "Sorcery": req.target_sorcery_count,
        "Artifact": req.target_artifact_count,
        "Enchantment": req.target_enchantment_count,
        "Planeswalker": req.target_planeswalker_count,
    }

    # Group candidates by type
    by_type = {}
    for card in candidate_map.values():
        ct = card["card_type"]
        by_type.setdefault(ct, []).append(card)

    # Score and sort candidates within each type
    for ct, cards in by_type.items():
        for card in cards:
            score = 0
            # Prefer owned cards heavily
            if card["owned_qty"] > 0:
                score += 100
            # Prefer cards with functional roles
            for r in card.get("roles", []):
                if r in ("Ramp", "Draw", "Removal", "BoardWipe"):
                    score += 10
                else:
                    score += 3
            # Prefer lower EDHREC rank (more popular cards)
            edhrec_rank = card.get("edhrec_rank", 99999)
            if edhrec_rank < 500:
                score += 15
            elif edhrec_rank < 2000:
                score += 10
            elif edhrec_rank < 5000:
                score += 5
            # Prefer cards from templates
            score += card.get("_template_weight", 0) * 5
            # Prefer lower CMC (curve optimization)
            cmc = card.get("cmc", 0)
            if cmc <= 2:
                score += 5
            elif cmc <= 4:
                score += 3
            card["_score"] = score
        cards.sort(key=lambda x: x["_score"], reverse=True)

    # Pick cards for each slot type
    deck_cards = []
    used_names = set()  # track by name to avoid duplicates

    for card_type, target in targets.items():
        candidates = by_type.get(card_type, [])
        picked = 0
        for card in candidates:
            if picked >= target:
                break
            name_key = card["name"].lower()
            if name_key in used_names:
                continue
            # If only collection, skip proxies
            if req.only_cards_in_collection and card["owned_qty"] <= 0:
                continue
            used_names.add(name_key)
            deck_cards.append(card)
            picked += 1

    # Fill remaining slots up to 99 (commander is #100)
    total = sum(targets.values())
    if total < 99:
        remaining = 99 - len(deck_cards)
        # Fill with best remaining cards from any type
        all_remaining = []
        for ct, cards in by_type.items():
            for card in cards:
                if card["name"].lower() not in used_names:
                    if not req.only_cards_in_collection or card["owned_qty"] > 0:
                        all_remaining.append(card)
        all_remaining.sort(key=lambda x: x.get("_score", 0), reverse=True)
        for card in all_remaining[:remaining]:
            used_names.add(card["name"].lower())
            deck_cards.append(card)
    elif len(deck_cards) > 99:
        deck_cards = deck_cards[:99]

    # 6. Compute stats
    stats = {"total": len(deck_cards) + 1, "land": 0, "nonland": 0, "by_type": {}, "owned": 0, "proxy": 0}
    for card in deck_cards:
        ct = card.get("card_type", "Other")
        stats["by_type"][ct] = stats["by_type"].get(ct, 0) + 1
        if ct == "Land":
            stats["land"] += 1
        else:
            stats["nonland"] += 1
        if card.get("owned_qty", 0) > 0:
            stats["owned"] += 1
        else:
            stats["proxy"] += 1

    # Clean up internal scoring keys
    clean_cards = []
    for card in deck_cards:
        clean_cards.append({
            "scryfall_id": card.get("scryfall_id", ""),
            "name": card.get("name", ""),
            "type_line": card.get("type_line", ""),
            "mana_cost": card.get("mana_cost", ""),
            "cmc": card.get("cmc", 0),
            "card_type": card.get("card_type", "Other"),
            "roles": card.get("roles", []),
            "source": card.get("source", "collection"),
            "quantity": 1,
            "image_url": card.get("image_url", ""),
            "owned_qty": card.get("owned_qty", 0),
            "is_proxy": card.get("is_proxy", False),
        })

    log_deckgen.info(f"  Generated deck: {len(clean_cards)} cards + commander")
    log_deckgen.info(f"  Stats: {stats}")

    return {
        "commander": commander,
        "color_identity": color_identity,
        "cards": clean_cards,
        "stats": stats,
        "targets": targets,
    }


@app.get("/api/deck-generator/config")
async def deck_generator_config():
    """
    Return default ratios, supported sources, and limits.
    Used by the frontend to prefill the generator form.
    """
    return {
        "defaults": {
            "target_land_count": 37,
            "target_instant_count": 10,
            "target_sorcery_count": 8,
            "target_artifact_count": 10,
            "target_enchantment_count": 8,
            "target_creature_count": 25,
            "target_planeswalker_count": 2,
            "only_cards_in_collection": False,
            "allow_proxies": True,
        },
        "sources": [
            {"id": "archidekt", "name": "Archidekt", "enabled": True, "experimental": False},
            {"id": "edhrec", "name": "EDHREC", "enabled": True, "experimental": False},
            {"id": "moxfield", "name": "Moxfield", "enabled": False, "experimental": True},
            {"id": "mtggoldfish", "name": "MTGGoldfish", "enabled": False, "experimental": True},
        ],
        "limits": {
            "deck_size": 100,
            "max_external_templates": 5,
        },
    }


@app.post("/api/deck-generator/preview")
async def deck_generator_preview(req: DeckGenerationRequest):
    """
    Generate a deck preview without saving it.
    Returns the generated deck data for user review.
    """
    result = _generate_deck(req)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/deck-generator/commit")
async def deck_generator_commit(req: DeckGenerationRequest):
    """
    Generate a deck and save it to the Deck Builder.
    Returns the generated deck data plus deck_id and deck_name.
    """
    result = _generate_deck(req)
    if "error" in result:
        raise HTTPException(400, result["error"])

    commander = result["commander"]
    color_identity = result["color_identity"]
    cards = result["cards"]

    # Determine deck name
    deck_name = req.deck_name or f"Auto - {commander['name']} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # Create the deck in the database
    conn = _get_db_conn()
    color_identity_json = json.dumps(color_identity)
    cur = conn.execute(
        """
        INSERT INTO decks (name, commander_scryfall_id, commander_name, color_identity, strategy_tag)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            deck_name,
            commander.get("scryfall_id", ""),
            commander.get("name", ""),
            color_identity_json,
            "auto-generated",
        )
    )
    conn.commit()
    deck_id = cur.lastrowid

    # Insert commander as a deck card with is_commander=1
    conn.execute(
        "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander, role_tag) VALUES (?, ?, ?, 1, 1, 'Commander')",
        (deck_id, commander.get("scryfall_id", ""), commander.get("name", ""))
    )

    # Insert the 99 cards
    for card in cards:
        scryfall_id = card.get("scryfall_id", "")
        card_name = card.get("name", "")
        quantity = card.get("quantity", 1)
        if not scryfall_id and not card_name:
            continue
        conn.execute(
            "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander, role_tag) VALUES (?, ?, ?, ?, 0, ?)",
            (deck_id, scryfall_id, card_name, quantity, card.get("card_type", ""))
        )
    conn.commit()

    # Also export a .dck file to the Forge decks directory so it appears in the Sim Lab
    try:
        decks_dir = CFG.forge_decks_dir
        if decks_dir and os.path.isdir(decks_dir):
            safe_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', deck_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = f"AutoDeck_{deck_id}"
            dck_path = os.path.join(decks_dir, f"{safe_name}.dck")
            dck_lines = []
            dck_lines.append("[metadata]")
            dck_lines.append(f"Name={deck_name}")
            dck_lines.append("")
            dck_lines.append("[Commander]")
            dck_lines.append(f"1 {commander['name']}")
            dck_lines.append("")
            dck_lines.append("[Main]")
            for card in cards:
                card_name = card.get("name", "")
                if card_name:
                    dck_lines.append(f"{card.get('quantity', 1)} {card_name}")
            with open(dck_path, "w", encoding="utf-8") as f:
                f.write("\n".join(dck_lines))
            log_deckgen.info(f"  Exported .dck file: {dck_path}")
    except Exception as e:
        log_deckgen.warning(f"  Warning: Failed to export .dck file: {e}")

    log_deckgen.info(f"  Saved deck '{deck_name}' (ID: {deck_id}) with {len(cards)} cards + commander")

    result["deck_id"] = deck_id
    result["deck_name"] = deck_name
    return result


@app.get("/api/deck-generator/commander-search")
async def deck_generator_commander_search(q: str = ""):
    """
    Search for legendary creatures/planeswalkers to use as commander.
    First checks collection, then falls back to Scryfall.
    """
    if not q or len(q) < 2:
        return {"results": []}

    conn = _get_db_conn()
    q_lower = f"%{q.lower()}%"

    # Search collection first
    rows = conn.execute(
        """
        SELECT DISTINCT name, type_line, color_identity, mana_cost, scryfall_id
        FROM collection_entries
        WHERE LOWER(name) LIKE ? AND is_legendary = 1
          AND (type_line LIKE '%Creature%' OR type_line LIKE '%Planeswalker%')
        ORDER BY name ASC
        LIMIT 20
        """,
        (q_lower,)
    ).fetchall()

    results = []
    for r in rows:
        ci = r["color_identity"]
        if isinstance(ci, str):
            try:
                ci = json.loads(ci)
            except Exception:
                ci = []
        results.append({
            "name": r["name"],
            "type_line": r["type_line"],
            "color_identity": ci,
            "mana_cost": r["mana_cost"] or "",
            "scryfall_id": r["scryfall_id"],
            "in_collection": True,
            "image_url": f"https://api.scryfall.com/cards/{r['scryfall_id']}?format=image&version=normal"
                         if r["scryfall_id"] else "",
        })

    # If few results, supplement with Scryfall
    if len(results) < 5:
        try:
            import urllib.parse
            encoded = urllib.parse.quote(q)
            _scryfall_rate_limit()
            url = f"https://api.scryfall.com/cards/search?q={encoded}+t%3Alegendary+(t%3Acreature+OR+t%3Aplaneswalker)&order=edhrec&unique=cards"
            rq = Request(url, headers={"User-Agent": "CommanderAILab/1.0", "Accept": "application/json"})
            with urlopen(rq, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            existing_names = {r["name"].lower() for r in results}
            for card in data.get("data", [])[:10]:
                if card["name"].lower() in existing_names:
                    continue
                image_uris = card.get("image_uris", {})
                if not image_uris and card.get("card_faces"):
                    image_uris = card["card_faces"][0].get("image_uris", {})
                results.append({
                    "name": card["name"],
                    "type_line": card.get("type_line", ""),
                    "color_identity": card.get("color_identity", []),
                    "mana_cost": card.get("mana_cost", ""),
                    "scryfall_id": card.get("id", ""),
                    "in_collection": False,
                    "image_url": image_uris.get("normal", image_uris.get("small", "")),
                })
        except Exception as e:
            log_deckgen.error(f"  Scryfall search error: {e}")

    return {"results": results[:20]}


# ══════════════════════════════════════════════════════════════
# Perplexity API — AI Deck Research & Generation
# ══════════════════════════════════════════════════════════════


class DeckResearchRequest(BaseModel):
    deck_id: int  # Deck to research
    goal: Optional[str] = "Identify weaknesses and suggest upgrades"
    budget_usd: Optional[float] = None
    omit_cards: Optional[list[str]] = []
    use_collection: bool = True


class DeckGenerateAIRequest(BaseModel):
    commander: str
    budget_usd: Optional[float] = None
    budget_mode: str = "total"  # "total" or "per_card"
    omit_cards: Optional[list[str]] = []
    use_collection: bool = True


def _build_collection_summary(color_identity: list[str] | None = None) -> dict:
    """Build a compact collection summary for the AI, optionally filtered by color identity."""
    conn = _get_db_conn()

    # Base query: all collection entries with oracle text
    where = "WHERE quantity > 0"
    params = []

    # Filter by color identity if provided
    if color_identity:
        # Cards must only contain colors in the commander's identity (+ colorless)
        ci_set = set(c.upper() for c in color_identity)
        # We'll do a post-filter since color_identity is JSON in the DB
        pass  # filter in Python after fetch

    rows = conn.execute(f"""
        SELECT name, type_line, cmc, oracle_text, keywords, tcg_price, quantity,
               color_identity, category, is_game_changer, salt_score
        FROM collection_entries {where}
        ORDER BY edhrec_rank ASC, tcg_price DESC
    """, params).fetchall()

    # Color identity filter
    def card_fits_identity(card_ci_str, ci_set):
        if not ci_set:
            return True
        try:
            card_ci = json.loads(card_ci_str) if card_ci_str else []
            if not isinstance(card_ci, list):
                return True
            return all(c.upper() in ci_set for c in card_ci if c.upper() not in ('', 'C'))
        except Exception:
            return True

    # Role detection from type_line, oracle_text, and category
    def detect_role(row):
        tl = (row['type_line'] or '').lower()
        oracle = (row['oracle_text'] or '').lower()
        cat = (row['category'] or '').lower()
        kw = (row['keywords'] or '').lower()

        # Priority order
        if 'land' in tl:
            return 'lands'
        if any(w in cat for w in ['ramp', 'mana']):
            return 'ramp'
        if any(w in oracle for w in ['add {', 'add one mana', 'search your library for a basic land', 'search your library for a land']):
            return 'ramp'
        if 'mana' in cat or ('artifact' in tl and ('add' in oracle and '{' in oracle)):
            return 'ramp'
        if any(w in cat for w in ['draw', 'card advantage']):
            return 'card_draw'
        if 'draw' in oracle and 'card' in oracle:
            return 'card_draw'
        if any(w in cat for w in ['removal', 'targeted removal']):
            return 'removal'
        if 'destroy target' in oracle or 'exile target' in oracle or 'deals' in oracle:
            return 'removal'
        if any(w in cat for w in ['board wipe', 'boardwipe', 'wrath']):
            return 'board_wipes'
        if 'destroy all' in oracle or 'exile all' in oracle:
            return 'board_wipes'
        if any(w in cat for w in ['win', 'finisher', 'combo']):
            return 'win_conditions'
        if 'you win the game' in oracle or 'extra turn' in oracle or 'infinite' in oracle:
            return 'win_conditions'
        if 'creature' in tl:
            return 'creatures'
        return 'utility'

    # Group cards by role
    groups: dict[str, list] = {
        'ramp': [], 'card_draw': [], 'removal': [], 'board_wipes': [],
        'lands': [], 'win_conditions': [], 'creatures': [], 'utility': []
    }
    filtered_count = 0

    for r in rows:
        if color_identity and not card_fits_identity(r['color_identity'], ci_set):
            continue
        filtered_count += 1
        role = detect_role(r)
        groups[role].append({
            'name': r['name'],
            'count': r['quantity'],
            'price': round(r['tcg_price'] or 0, 2),
            'cmc': r['cmc'] or 0,
        })

    # Limit each group to top 30
    group_descriptions = {
        'ramp': 'Mana rocks and land ramp in deck colors',
        'card_draw': 'Card draw and card advantage engines',
        'removal': 'Targeted removal spells (destroy, exile, bounce)',
        'board_wipes': 'Board wipes and mass removal',
        'lands': 'Non-basic lands that fit the color identity',
        'win_conditions': 'Win conditions, combo pieces, and finishers',
        'creatures': 'Creatures (non-commander)',
        'utility': 'Utility spells, enchantments, artifacts, and planeswalkers',
    }

    result_groups = []
    for gid, cards in groups.items():
        if not cards:
            continue
        result_groups.append({
            'group_id': gid,
            'description': group_descriptions.get(gid, ''),
            'cards': cards[:30],
        })

    return {
        'total_cards': len(rows),
        'filtered_cards': filtered_count,
        'groups': result_groups,
    }


def _call_pplx_api(messages: list[dict], max_tokens: int = 4096, temperature: float = 0.2) -> str:
    """Call Perplexity API chat/completions endpoint. Returns the assistant message content."""
    if not CFG.pplx_api_key:
        raise HTTPException(400, 'Perplexity API key not configured. Set PPLX_API_KEY env var or --pplx-key.')

    payload = {
        'model': 'sonar',
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'return_related_questions': False,
    }

    req_data = json.dumps(payload).encode('utf-8')
    req = Request('https://api.perplexity.ai/chat/completions', data=req_data, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Bearer {CFG.pplx_api_key}')

    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        choices = data.get('choices', [])
        if not choices:
            raise ValueError('Empty response from Perplexity API')
        content = choices[0].get('message', {}).get('content', '')
        usage = data.get('usage', {})
        log_pplx.debug(f'tokens: prompt={usage.get("prompt_tokens","?")}, '
              f'completion={usage.get("completion_tokens","?")}, '
              f'model={data.get("model","?")}')
        return content
    except URLError as e:
        raise HTTPException(502, f'Perplexity API call failed: {e}')
    except json.JSONDecodeError as e:
        raise HTTPException(502, f'Perplexity API returned invalid JSON: {e}')


def _extract_json_from_response(text: str) -> dict:
    """Extract JSON object from LLM response, handling markdown fences and extra text."""
    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned.strip())

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f'Could not extract JSON from response: {text[:300]}')


def _postprocess_deck_cards(cards: list[dict], color_identity: list[str] | None = None) -> list[dict]:
    """
    Post-process AI-suggested cards:
    - Validate names against collection DB
    - Attach real prices
    - Set from_collection flag
    """
    conn = _get_db_conn()
    processed = []
    for card in cards:
        name = card.get('name', '')
        if not name:
            continue

        # Look up in collection
        row = conn.execute(
            "SELECT name, tcg_price, quantity, scryfall_id, type_line, cmc, oracle_text "
            "FROM collection_entries WHERE name = ? COLLATE NOCASE LIMIT 1",
            (name,)
        ).fetchone()

        entry = {
            'name': row['name'] if row else name,
            'count': card.get('count', 1),
            'role': card.get('role', ''),
            'from_collection': bool(row and row['quantity'] and row['quantity'] > 0),
            'estimated_price_usd': round(row['tcg_price'], 2) if row and row['tcg_price'] else card.get('estimated_price_usd', 0),
            'scryfall_id': row['scryfall_id'] if row else '',
        }
        # Preserve extra fields from AI response
        for extra_key in ('reason', 'synergy_with', 'priority', 'severity'):
            if extra_key in card:
                entry[extra_key] = card[extra_key]
        processed.append(entry)

    return processed


# Color-to-basic-land mapping for deterministic fill
_COLOR_TO_BASIC = {
    'W': 'Plains',
    'U': 'Island',
    'B': 'Swamp',
    'R': 'Mountain',
    'G': 'Forest',
}
BASIC_LAND_NAMES = set(_COLOR_TO_BASIC.values()) | {'Wastes'}


def _fill_basic_lands(cards: list[dict], color_identity: list[str] | None = None, target_total: int = 100) -> list[dict]:
    """
    Deterministically fill basic lands so the deck hits exactly target_total cards.

    The LLM may list basics with wrong counts, duplicates, or omit them.
    This function:
      1. Strips all basic-land entries the LLM provided
      2. Counts remaining cards (non-basics) and their total count
      3. Computes how many basic land slots are needed
      4. Distributes basics evenly across the commander's colors
    """
    # Separate basics from non-basics
    non_basics = []
    for card in cards:
        name = card.get('name', '').strip()
        if name not in BASIC_LAND_NAMES:
            non_basics.append(card)

    # Count total non-basic cards
    non_basic_total = sum(c.get('count', 1) for c in non_basics)

    # How many basic land copies we need
    basics_needed = max(0, target_total - non_basic_total)

    if basics_needed == 0:
        return non_basics

    # Determine which basics to use from color identity
    ci = [c.upper() for c in (color_identity or [])]
    basic_names = [_COLOR_TO_BASIC[c] for c in ci if c in _COLOR_TO_BASIC]
    if not basic_names:
        # Colorless commander — use Wastes
        basic_names = ['Wastes']

    # Distribute evenly, then add remainders one-by-one
    per_color = basics_needed // len(basic_names)
    remainder = basics_needed % len(basic_names)

    for i, bname in enumerate(basic_names):
        qty = per_color + (1 if i < remainder else 0)
        if qty > 0:
            non_basics.append({
                'name': bname,
                'count': qty,
                'role': 'land',
                'category': 'Land',
                'role_tags': [],
                'reason': 'Basic land for mana fixing',
                'estimated_price_usd': 0.10,
                'from_collection': False,
                'is_basic': True,
            })

    return non_basics


# ── Research Endpoint ─────────────────────────────────────────

@app.post('/api/deck-research')
async def deck_research(req: DeckResearchRequest):
    """Analyze an existing deck using Perplexity AI and suggest improvements."""
    conn = _get_db_conn()

    # Load deck info
    deck = conn.execute('SELECT * FROM decks WHERE id = ?', (req.deck_id,)).fetchone()
    if not deck:
        raise HTTPException(404, f'Deck {req.deck_id} not found')

    deck_name = deck['name']
    commander_name = deck['commander_name'] or 'Unknown'
    color_identity_str = deck['color_identity'] or '[]'
    try:
        color_identity = json.loads(color_identity_str)
    except Exception:
        color_identity = []

    # Load deck cards
    card_rows = conn.execute("""
        SELECT dc.card_name, dc.quantity, dc.is_commander,
               ce.type_line, ce.cmc, ce.oracle_text, ce.tcg_price
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, cmc, oracle_text, tcg_price
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
        ORDER BY dc.is_commander DESC, dc.card_name ASC
    """, (req.deck_id,)).fetchall()

    if not card_rows:
        raise HTTPException(400, 'Deck has no cards')

    # Build decklist text
    decklist_lines = []
    total_price = 0.0
    for r in card_rows:
        price = r['tcg_price'] or 0
        total_price += price * (r['quantity'] or 1)
        cmdr_tag = ' [COMMANDER]' if r['is_commander'] else ''
        decklist_lines.append(f"{r['quantity'] or 1}x {r['card_name']}{cmdr_tag}")

    decklist_text = '\n'.join(decklist_lines)

    # Build collection summary if requested
    collection_block = ''
    if req.use_collection:
        summary = _build_collection_summary(color_identity)
        if summary['filtered_cards'] > 0:
            coll_lines = [f'\nCOLLECTION SUMMARY ({summary["filtered_cards"]} cards in deck colors):']
            for grp in summary['groups']:
                card_names = [f"{c['name']} (${c['price']})" for c in grp['cards'][:15]]
                coll_lines.append(f"  {grp['group_id'].upper()} ({grp['description']}): {', '.join(card_names)}")
            collection_block = '\n'.join(coll_lines)

    omit_block = ''
    if req.omit_cards:
        omit_block = f'\nDO NOT suggest these cards: {", ".join(req.omit_cards)}'

    budget_block = ''
    if req.budget_usd:
        budget_block = f'\nBUDGET: ${req.budget_usd} total for upgrades. Current deck value: ~${total_price:.0f}'

    # Build messages
    system_msg = """You are an elite Magic: The Gathering Commander analyst with encyclopedic knowledge of the format, metagame, and every card ever printed. Provide a DEEP, COMPREHENSIVE analysis.
Always respond with ONLY a JSON object, no markdown fences, no extra text.

JSON schema:
{
  "overall_rating": "1-10 integer",
  "rating_explanation": "2-3 sentence explanation of the rating",
  "deck_description": "3-5 sentence overview of what this deck does, its game plan, and how it wins",
  "archetype": "aggro|midrange|control|combo|stax|voltron|aristocrats|spellslinger|tokens|tribal|group_hug|lands|reanimator|other",
  "bracket_level": {
    "level": 1-4,
    "reasoning": "why this bracket",
    "power_ceiling": "what power level this deck could reach with upgrades"
  },
  "win_conditions": [
    {"name": "Win condition name", "cards_involved": ["card1", "card2"], "description": "How this wins the game", "reliability": "high|medium|low"}
  ],
  "synergy_packages": [
    {"package_name": "Package Name (e.g. Sacrifice Engine, Blink Package)", "cards": ["card1", "card2", "card3"], "description": "How these cards work together", "strength": "strong|moderate|weak"}
  ],
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "threat_assessment": {
    "early_game": "1-2 sentences on turns 1-3 plan",
    "mid_game": "1-2 sentences on turns 4-7 plan",
    "late_game": "1-2 sentences on turns 8+ plan",
    "vulnerability": "What shuts this deck down (e.g. graveyard hate, board wipes)"
  },
  "mana_analysis": {
    "land_count": "current land count assessment",
    "color_fixing": "assessment of color fixing quality",
    "ramp_package": "assessment of ramp quantity and quality",
    "curve_assessment": "is the mana curve appropriate for the strategy",
    "problem_cards": ["cards that are hard to cast or mana-inefficient"]
  },
  "cuts": [{"name": "card to remove", "reason": "why", "severity": "must_cut|should_cut|consider_cutting"}],
  "adds": [{"name": "card to add", "count": 1, "role": "ramp|removal|draw|creature|utility|land|combo_piece|protection|finisher", "estimated_price_usd": 2.5, "reason": "why this card", "synergy_with": ["existing card it synergizes with"], "priority": "critical|high|medium|nice_to_have"}],
  "role_gaps": {
    "ramp": {"current": 8, "recommended": 10, "note": "needs 2 more ramp sources"},
    "card_draw": {"current": 5, "recommended": 10, "note": ""},
    "removal": {"current": 6, "recommended": 8, "note": ""},
    "board_wipes": {"current": 2, "recommended": 3, "note": ""},
    "protection": {"current": 1, "recommended": 3, "note": ""},
    "lands": {"current": 35, "recommended": 36, "note": ""}
  },
  "strategy_notes": "detailed strategic advice for piloting this deck"
}"""

    user_msg = f"""Provide a DEEP, COMPREHENSIVE analysis of this Commander deck.

DECK NAME: {deck_name}
COMMANDER: {commander_name}
COLOR IDENTITY: {', '.join(color_identity) if color_identity else 'Unknown'}
CURRENT DECK VALUE: ~${total_price:.0f}
GOAL: {req.goal}

DECKLIST ({len(card_rows)} cards):
{decklist_text}
{budget_block}{omit_block}{collection_block}

Analyze EVERYTHING: the deck's identity, strategy, archetype, bracket level (1-4 per Commander Rules Committee), ALL synergy packages between cards, ALL win conditions, game plan by phase (early/mid/late), mana base health, every role gap. Suggest specific cuts with severity and specific adds with priority and synergy tags. For adds, prioritize cards from the COLLECTION SUMMARY when available."""

    content = _call_pplx_api([
        {'role': 'system', 'content': system_msg},
        {'role': 'user', 'content': user_msg},
    ], max_tokens=8192)

    try:
        analysis = _extract_json_from_response(content)
    except ValueError as e:
        return JSONResponse({'error': str(e), 'raw_response': content[:500]}, status_code=422)

    # Post-process "adds" — validate against DB
    if 'adds' in analysis and isinstance(analysis['adds'], list):
        analysis['adds'] = _postprocess_deck_cards(analysis['adds'], color_identity)

    # Compute real total cost of adds
    adds_total = sum(c.get('estimated_price_usd', 0) * c.get('count', 1) for c in analysis.get('adds', []))
    analysis['adds_total_usd'] = round(adds_total, 2)
    analysis['deck_name'] = deck_name
    analysis['commander'] = commander_name
    analysis['color_identity'] = color_identity
    analysis['card_count'] = len(card_rows)
    analysis['deck_value_usd'] = round(total_price, 2)

    return analysis


# ── Generate Endpoint ─────────────────────────────────────────

@app.post('/api/deck-generate')
async def deck_generate_ai(req: DeckGenerateAIRequest):
    """Generate a full 100-card Commander deck using Perplexity AI."""
    commander = req.commander.strip()
    if not commander:
        raise HTTPException(400, 'Commander name is required')

    # Look up commander on Scryfall for color identity
    color_identity = []
    commander_type = ''
    try:
        scry_url = f'https://api.scryfall.com/cards/named?fuzzy={commander.replace(" ", "+")}'
        scry_req = Request(scry_url)
        scry_req.add_header('User-Agent', 'CommanderAILab/1.0')
        with urlopen(scry_req, timeout=10) as resp:
            scry_data = json.loads(resp.read())
        color_identity = scry_data.get('color_identity', [])
        commander = scry_data.get('name', commander)  # Use canonical name
        commander_type = scry_data.get('type_line', '')
    except Exception as e:
        log_pplx.error(f'Scryfall lookup failed for "{commander}": {e}')

    # Build collection summary
    collection_block = ''
    if req.use_collection:
        summary = _build_collection_summary(color_identity or None)
        if summary['filtered_cards'] > 0:
            coll_lines = [f'\nCOLLECTION SUMMARY ({summary["filtered_cards"]} cards available):']
            for grp in summary['groups']:
                card_names = [f"{c['name']} (${c['price']})" for c in grp['cards'][:20]]
                coll_lines.append(f"  {grp['group_id'].upper()}: {', '.join(card_names)}")
            collection_block = '\n'.join(coll_lines)

    omit_block = ''
    if req.omit_cards:
        omit_block = f'\nOMIT LIST (do NOT include): {", ".join(req.omit_cards)}'

    budget_block = ''
    if req.budget_usd:
        mode_desc = 'total deck cost' if req.budget_mode == 'total' else 'per card'
        budget_block = f'\nBUDGET: ${req.budget_usd} {mode_desc}. Stay within budget.'

    system_msg = """You are an expert Magic: The Gathering Commander deck builder.
Build a complete, legal 100-card Commander deck (1 commander + 99 other cards).
Prefer cards from the player's collection when available.
Respect the budget and omit list.
Always respond with ONLY a JSON object, no markdown fences, no extra text.

JSON schema:
{
  "commander": "Commander Name",
  "strategy": "1-2 sentence strategy description",
  "cards": [
    {"name": "Card Name", "count": 1, "role": "ramp|removal|draw|creature|land|utility|win_condition", "estimated_price_usd": 2.5}
  ],
  "reasoning": {
    "strategy": "detailed strategy explanation",
    "mana_curve": "mana curve reasoning",
    "key_synergies": "key synergies and combos",
    "budget_notes": "how budget was managed",
    "collection_usage_notes": "which collection cards were used and why"
  },
  "estimated_total_usd": 187.5
}

Deck building rules:
- Exactly 100 cards total (commander + 99)
- No more than 1 copy of any card (except basic lands)
- 36-38 lands including commander-colored basics and utility lands
- ~10 ramp sources, ~10 card draw, ~8-10 removal, ~2-3 board wipes
- Include the commander in the cards list with role "commander"
- All cards must be legal in Commander format"""

    user_msg = f"""Build a complete 100-card Commander deck for:

COMMANDER: {commander}
TYPE: {commander_type}
COLOR IDENTITY: {', '.join(color_identity) if color_identity else 'Unknown'}
{budget_block}{omit_block}{collection_block}

Build the deck as JSON. Prioritize collection cards when they fit the strategy."""

    content = _call_pplx_api([
        {'role': 'system', 'content': system_msg},
        {'role': 'user', 'content': user_msg},
    ], max_tokens=8192, temperature=0.3)

    try:
        result = _extract_json_from_response(content)
    except ValueError as e:
        return JSONResponse({'error': str(e), 'raw_response': content[:500]}, status_code=422)

    # Post-process cards
    if 'cards' in result and isinstance(result['cards'], list):
        result['cards'] = _postprocess_deck_cards(result['cards'], color_identity)
        # Fill basic lands deterministically to hit exactly 100
        result['cards'] = _fill_basic_lands(result['cards'], color_identity, target_total=100)

    # Compute real totals
    real_total = sum(c.get('estimated_price_usd', 0) * c.get('count', 1) for c in result.get('cards', []))
    from_collection_count = sum(1 for c in result.get('cards', []) if c.get('from_collection'))
    result['real_total_usd'] = round(real_total, 2)
    result['from_collection_count'] = from_collection_count
    result['total_cards'] = sum(c.get('count', 1) for c in result.get('cards', []))
    result['color_identity'] = color_identity

    return result


@app.get('/api/pplx/status')
async def pplx_status():
    """Check if Perplexity API is configured."""
    return {
        'configured': bool(CFG.pplx_api_key),
        'key_prefix': CFG.pplx_api_key[:8] + '...' if CFG.pplx_api_key else '',
    }


# ══════════════════════════════════════════════════════════════
# V3 Deck Generator (Perplexity Structured Output)
# ══════════════════════════════════════════════════════════════

@app.get('/api/deck/v3/status')
async def deck_gen_v3_status():
    """Check V3 deck generator status."""
    return {
        'initialized': _deck_gen_v3 is not None,
        'pplx_configured': bool(CFG.pplx_api_key),
        'model': _deck_gen_v3.pplx.model if _deck_gen_v3 else None,
        'embeddings_loaded': (
            _coach_embeddings.loaded if _coach_embeddings else False
        ),
        'embedding_cards': (
            _coach_embeddings.card_count if _coach_embeddings else 0
        ),
        'error': _deck_gen_v3_error,
    }


@app.post('/api/deck/v3/generate')
async def deck_gen_v3_generate(req: DeckGenV3Request):
    """
    V3 Deck Generation — Perplexity structured output with Smart Substitution.

    Pipeline:
      1. Resolve commander via Scryfall
      2. Build collection summary from DB
      3. Call Perplexity Sonar with JSON schema enforcement
      4. Cross-reference cards with collection for ownership
      5. Run Smart Substitution (embedding + Perplexity fallback)
      6. Return complete deck with substitution data
    """
    if _deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized. Check PPLX_API_KEY.')

    if not req.commander_name or len(req.commander_name.strip()) < 2:
        raise HTTPException(400, 'Commander name is required (min 2 chars)')

    try:
        # Generate deck
        result = _deck_gen_v3.generate_deck(
            commander_name=req.commander_name.strip(),
            strategy=req.strategy,
            target_bracket=req.target_bracket,
            budget_usd=req.budget_usd,
            budget_mode=req.budget_mode,
            omit_cards=req.omit_cards,
            use_collection=req.use_collection,
            model=req.model,
        )

        # Run substitution if requested
        if req.run_substitution and result.get('cards'):
            from coach.schemas.substitution_schema import DeckCardWithStatus
            cards = [DeckCardWithStatus(**c) for c in result['cards']]
            sub_result = _deck_gen_v3.run_substitution(
                cards=cards,
                commander=result['commander'],
                strategy=req.strategy,
            )
            result['cards'] = [c.model_dump() for c in sub_result.cards]
            result['substitution_stats'] = {
                'owned': sub_result.owned_count,
                'substituted': sub_result.substituted_count,
                'missing': sub_result.missing_count,
            }
            # Recompute stats with updated cards
            from coach.services.deck_generator import DeckGeneratorV3
            result['stats'] = DeckGeneratorV3._compute_stats(sub_result.cards)

        return result

    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=422)
    except Exception as e:
        log_deckgen.error(f'Error: {e}')
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f'Deck generation failed: {str(e)}')


@app.post('/api/deck/v3/commit')
async def deck_gen_v3_commit(req: DeckGenV3Request):
    """
    V3 Generate + Commit — generates the deck and saves it to the Deck Builder DB.
    Also exports a .dck file for Forge Sim Lab.
    """
    if _deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    if not req.commander_name or len(req.commander_name.strip()) < 2:
        raise HTTPException(400, 'Commander name is required')

    try:
        # Generate deck (same as preview)
        result = _deck_gen_v3.generate_deck(
            commander_name=req.commander_name.strip(),
            strategy=req.strategy,
            target_bracket=req.target_bracket,
            budget_usd=req.budget_usd,
            budget_mode=req.budget_mode,
            omit_cards=req.omit_cards,
            use_collection=req.use_collection,
            model=req.model,
        )

        # Run substitution
        if req.run_substitution and result.get('cards'):
            from coach.schemas.substitution_schema import DeckCardWithStatus
            cards = [DeckCardWithStatus(**c) for c in result['cards']]
            sub_result = _deck_gen_v3.run_substitution(
                cards=cards,
                commander=result['commander'],
                strategy=req.strategy,
            )
            result['cards'] = [c.model_dump() for c in sub_result.cards]

        # Save to DB
        commander = result['commander']
        color_identity = result.get('color_identity', [])
        cards = result.get('cards', [])
        strategy = result.get('strategy_summary', '')
        bracket = result.get('bracket', {}).get('level', 0)

        deck_name = (
            req.deck_name
            or f"V3 - {commander['name']} - B{bracket} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        conn = _get_db_conn()
        cur = conn.execute(
            "INSERT INTO decks (name, commander_scryfall_id, commander_name, color_identity, strategy_tag) "
            "VALUES (?, ?, ?, ?, ?)",
            (deck_name, commander.get('scryfall_id', ''),
             commander.get('name', ''), json.dumps(color_identity),
             f"v3-auto|B{bracket}|{strategy[:60]}")
        )
        conn.commit()
        deck_id = cur.lastrowid

        # Insert commander
        conn.execute(
            "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander, role_tag) "
            "VALUES (?, ?, ?, 1, 1, 'Commander')",
            (deck_id, commander.get('scryfall_id', ''), commander.get('name', ''))
        )

        # Insert the 99
        for card in cards:
            card_name = card.get('name', '')
            if not card_name or card_name == commander.get('name', ''):
                continue  # Skip commander (already inserted)
            scryfall_id = card.get('scryfall_id', '')
            # Use substitute name if substituted
            if card.get('status') == 'substituted' and card.get('selected_substitute'):
                card_name = card['selected_substitute']
            conn.execute(
                "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander, role_tag) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (deck_id, scryfall_id, card_name,
                 card.get('count', 1), card.get('category', ''))
            )
        conn.commit()

        # Export .dck for Forge
        try:
            decks_dir = CFG.forge_decks_dir
            if decks_dir and os.path.isdir(decks_dir):
                safe_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', deck_name).strip().replace(' ', '_')
                if not safe_name:
                    safe_name = f"V3Deck_{deck_id}"
                dck_path = os.path.join(decks_dir, f"{safe_name}.dck")
                dck_lines = ["[metadata]", f"Name={deck_name}", "",
                             "[Commander]", f"1 {commander['name']}", "", "[Main]"]
                for card in cards:
                    cname = card.get('name', '')
                    if card.get('status') == 'substituted' and card.get('selected_substitute'):
                        cname = card['selected_substitute']
                    if cname and cname != commander.get('name', ''):
                        dck_lines.append(f"{card.get('count', 1)} {cname}")
                with open(dck_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(dck_lines))
                log_deckgen.info(f"  Exported .dck: {dck_path}")
        except Exception as e:
            log_deckgen.error(f"  .dck export failed: {e}")

        result['deck_id'] = deck_id
        result['deck_name'] = deck_name
        log_deckgen.info(f"  Committed deck '{deck_name}' (ID: {deck_id})")
        return result

    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=422)
    except Exception as e:
        log_deckgen.error(f'Commit error: {e}')
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f'Deck generation/commit failed: {str(e)}')


@app.post('/api/deck/v3/export/csv')
async def deck_gen_v3_export_csv(req: DeckGenV3Request):
    """Generate a deck and return as CSV."""
    if _deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    result = _deck_gen_v3.generate_deck(
        commander_name=req.commander_name.strip(),
        strategy=req.strategy,
        target_bracket=req.target_bracket,
        budget_usd=req.budget_usd,
        budget_mode=req.budget_mode,
        omit_cards=req.omit_cards,
        use_collection=req.use_collection,
        model=req.model,
    )

    cards = result.get('cards', [])
    commander = result.get('commander', {})

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Count', 'Name', 'Category', 'Roles', 'Status', 'Price_USD', 'Reason'])
    # Commander row
    writer.writerow([1, commander.get('name', ''), 'Commander', '', 'owned', '', 'Commander'])
    for card in cards:
        if card.get('name') == commander.get('name', ''):
            continue
        writer.writerow([
            card.get('count', 1),
            card.get('name', ''),
            card.get('category', ''),
            '; '.join(card.get('role_tags', [])),
            card.get('status', 'unknown'),
            card.get('estimated_price_usd', 0),
            card.get('reason', ''),
        ])

    csv_content = output.getvalue()
    safe_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', commander.get('name', 'deck')).strip().replace(' ', '_')
    return StreamingResponse(
        io.BytesIO(csv_content.encode('utf-8')),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{safe_name}_deck.csv"'},
    )


@app.post('/api/deck/v3/export/dck')
async def deck_gen_v3_export_dck(req: DeckGenV3Request):
    """Generate a deck and return as Forge .dck format."""
    if _deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    result = _deck_gen_v3.generate_deck(
        commander_name=req.commander_name.strip(),
        strategy=req.strategy,
        target_bracket=req.target_bracket,
        budget_usd=req.budget_usd,
        budget_mode=req.budget_mode,
        omit_cards=req.omit_cards,
        use_collection=req.use_collection,
        model=req.model,
    )

    cards = result.get('cards', [])
    commander = result.get('commander', {})

    lines = [
        '[metadata]',
        f'Name={commander.get("name", "Deck")} - V3 Auto',
        '',
        '[Commander]',
        f'1 {commander.get("name", "")}',
        '',
        '[Main]',
    ]
    for card in cards:
        cname = card.get('name', '')
        if card.get('status') == 'substituted' and card.get('selected_substitute'):
            cname = card['selected_substitute']
        if cname and cname != commander.get('name', ''):
            lines.append(f"{card.get('count', 1)} {cname}")

    dck_content = '\n'.join(lines)
    safe_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', commander.get('name', 'deck')).strip().replace(' ', '_')
    return StreamingResponse(
        io.BytesIO(dck_content.encode('utf-8')),
        media_type='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{safe_name}.dck"'},
    )


@app.post('/api/deck/v3/export/moxfield')
async def deck_gen_v3_export_moxfield(req: DeckGenV3Request):
    """Generate a deck and return in Moxfield paste format."""
    if _deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    result = _deck_gen_v3.generate_deck(
        commander_name=req.commander_name.strip(),
        strategy=req.strategy,
        target_bracket=req.target_bracket,
        budget_usd=req.budget_usd,
        budget_mode=req.budget_mode,
        omit_cards=req.omit_cards,
        use_collection=req.use_collection,
        model=req.model,
    )

    cards = result.get('cards', [])
    commander = result.get('commander', {})

    # Moxfield format: card lines in main, commander in dedicated section
    lines = []
    lines.append('// Commander')
    lines.append(f'1 {commander.get("name", "")}')
    lines.append('')
    lines.append('// Deck')
    for card in cards:
        cname = card.get('name', '')
        if card.get('status') == 'substituted' and card.get('selected_substitute'):
            cname = card['selected_substitute']
        if cname and cname != commander.get('name', ''):
            lines.append(f"{card.get('count', 1)} {cname}")

    txt = '\n'.join(lines)
    return {'format': 'moxfield', 'content': txt, 'commander': commander.get('name', '')}


@app.post('/api/deck/v3/export/shopping')
async def deck_gen_v3_export_shopping(req: DeckGenV3Request):
    """Generate a deck and return a shopping list of cards not owned."""
    if _deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    result = _deck_gen_v3.generate_deck(
        commander_name=req.commander_name.strip(),
        strategy=req.strategy,
        target_bracket=req.target_bracket,
        budget_usd=req.budget_usd,
        budget_mode=req.budget_mode,
        omit_cards=req.omit_cards,
        use_collection=req.use_collection,
        model=req.model,
    )

    cards = result.get('cards', [])
    shopping = []
    total = 0.0
    for card in cards:
        if not card.get('owned', True) and card.get('status') != 'substituted':
            price = card.get('estimated_price_usd', 0)
            shopping.append({
                'name': card.get('name', ''),
                'count': card.get('count', 1),
                'category': card.get('category', ''),
                'estimated_price_usd': price,
                'reason': card.get('reason', ''),
            })
            total += price * card.get('count', 1)

    return {
        'commander': result.get('commander', {}).get('name', ''),
        'shopping_list': shopping,
        'total_missing': len(shopping),
        'estimated_cost_usd': round(total, 2),
    }


# ══════════════════════════════════════════════════════════════
# Coach Service (LLM-powered deck coaching)
# ══════════════════════════════════════════════════════════════

# Global coach instances (initialized at startup)
_coach_service = None
_coach_embeddings = None
_coach_llm = None
_deck_gen_v3 = None  # V3 Deck Generator (Perplexity structured output)
_deck_gen_v3_error = None  # Error message if V3 init failed


def init_coach_service():
    """Initialize the coach service with LLM client and embeddings."""
    global _coach_service, _coach_embeddings, _coach_llm, _deck_gen_v3, _deck_gen_v3_error
    try:
        from coach.llm_client import LMStudioClient
        from coach.embeddings import MTGEmbeddingIndex
        from coach.coach_service import CoachService
        from coach.config import ensure_dirs

        ensure_dirs()

        _coach_llm = LMStudioClient()
        _coach_embeddings = MTGEmbeddingIndex()

        # Try to load embeddings (non-blocking — download happens on first use)
        try:
            from coach.config import EMBEDDINGS_NPZ
            if EMBEDDINGS_NPZ.exists():
                _coach_embeddings.load()
                log_coach.info(f"  Coach:        Embeddings loaded ({_coach_embeddings.card_count} cards)")
            else:
                log_coach.warning("  Coach:        Embeddings not yet downloaded (will download on first use)")
        except Exception as e:
            log_coach.error(f"  Coach:        Embeddings load failed: {e}")

        _coach_service = CoachService(_coach_llm, _coach_embeddings)

        # Check LLM connection
        llm_status = _coach_llm.check_connection()
        if llm_status.get("connected"):
            log_coach.info(f"  Coach LLM:    Connected ({llm_status.get('active_model', 'unknown')})")
        else:
            log_coach.warning(f"  Coach LLM:    Not connected (start LM Studio on 192.168.0.122:1234)")

        log_coach.info("  Coach:        Service initialized")

        # Initialize V3 Deck Generator (Perplexity)
        _deck_gen_v3_error = None
        if CFG.pplx_api_key:
            try:
                from coach.clients.perplexity_client import PerplexityClient
                from coach.services.deck_generator import DeckGeneratorV3
                from coach.config import DECK_GEN_MODEL

                pplx_client = PerplexityClient(
                    api_key=CFG.pplx_api_key,
                    model=DECK_GEN_MODEL,
                )
                _deck_gen_v3 = DeckGeneratorV3(
                    pplx_client=pplx_client,
                    db_conn_factory=_get_db_conn,
                    embedding_index=_coach_embeddings,
                )
                log_deckgen.info(f"  Deck Gen V3:  Initialized (model: {DECK_GEN_MODEL})")
            except ImportError as e:
                _deck_gen_v3_error = f"Missing dependency: {e}. Run: pip install openai"
                log_deckgen.error(f"  Deck Gen V3:  {_deck_gen_v3_error}")
                _deck_gen_v3 = None
            except Exception as e:
                _deck_gen_v3_error = str(e)
                log_deckgen.error(f"  Deck Gen V3:  Failed to initialize: {e}")
                _deck_gen_v3 = None
        else:
            _deck_gen_v3_error = "PPLX_API_KEY not set"
            log_deckgen.info("  Deck Gen V3:  Skipped (no PPLX_API_KEY)")

    except Exception as e:
        log_coach.error(f"  Coach:        Failed to initialize: {e}")
        _coach_service = None


@app.get("/api/coach/status")
async def coach_status():
    """Check coach subsystem health."""
    if _coach_service is None:
        return {"llmConnected": False, "embeddingsLoaded": False,
                "embeddingCards": 0, "deckReportsAvailable": 0,
                "error": "Coach service not initialized"}
    status = _coach_service.get_status()
    return status.model_dump()


@app.get("/api/coach/decks")
async def coach_list_decks():
    """List all decks available for coaching (from deck builder DB)."""
    conn = _get_db_conn()
    rows = conn.execute(
        """SELECT d.id as deck_id, d.name as deck_name, d.commander_name,
                  COUNT(dc.id) as card_count
           FROM decks d
           LEFT JOIN deck_cards dc ON dc.deck_id = d.id
           GROUP BY d.id
           ORDER BY d.name"""
    ).fetchall()

    # Also get report availability from coach service
    report_ids = set()
    if _coach_service:
        report_ids = set(_coach_service.list_deck_reports())

    decks = []
    for r in rows:
        deck_name = r["deck_name"]
        # Check if a report exists (by deck name slug match)
        has_report = any(
            deck_name.lower().replace(" ", "-") == rid.lower() or
            deck_name.lower() == rid.lower()
            for rid in report_ids
        )
        decks.append({
            "deck_id": r["deck_id"],
            "deck_name": r["deck_name"],
            "commander": r["commander_name"] or "",
            "card_count": r["card_count"],
            "has_report": has_report,
            "report_count": 1 if has_report else 0,
            "last_report_date": None,
        })
    return decks


@app.get("/api/coach/decks/{deck_id}/report")
async def coach_get_report(deck_id: str):
    """Get the latest DeckReport for a deck."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")
    report = _coach_service.load_deck_report(deck_id)
    if report is None:
        raise HTTPException(404, f"Deck report not found: {deck_id}")
    return report.model_dump()


class CoachRequestBody(BaseModel):
    goals: Optional[dict] = None


class CoachChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class CoachChatRequest(BaseModel):
    deck_id: str
    messages: list[dict]  # conversation history [{role, content}]
    goals: Optional[dict] = None
    stream: Optional[bool] = False

class CoachApplyRequest(BaseModel):
    session_id: str
    deck_id: int  # numeric deck ID in the DB
    accepted_cuts: list[str] = []  # card names to remove
    accepted_adds: list[str] = []  # card names to add

class CoachGoalsRequest(BaseModel):
    target_power_level: Optional[int] = None  # 1-10
    meta_focus: Optional[str] = None  # aggro, control, combo, midrange, stax
    budget: Optional[str] = None  # budget, medium, no-limit
    focus_areas: list[str] = []  # e.g., ["ramp", "card draw"]


@app.post("/api/coach/decks/{deck_id}")
async def coach_run_session(deck_id: str, body: CoachRequestBody = None):
    """Trigger a coaching session for a deck."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")

    # Load embeddings on first use if not loaded
    if _coach_embeddings and not _coach_embeddings.loaded:
        try:
            _coach_embeddings.load(force_download=True)
        except Exception as e:
            log_coach.error(f"  Coach: Embeddings download failed: {e}")

    goals = None
    if body and body.goals:
        from coach.models import CoachGoals
        try:
            goals = CoachGoals(**body.goals)
        except Exception:
            goals = None

    # Build a fallback DeckReport from the DB if no simulation report exists
    fallback_report = None
    try:
        fallback_report = _build_deck_report_from_db(deck_id)
    except Exception as e:
        log_coach.error(f"  Coach: Fallback report build failed for '{deck_id}': {e}")

    try:
        session = await _coach_service.run_coaching_session(deck_id, goals, fallback_report=fallback_report)
        return session.model_dump()
    except ValueError as e:
        raise HTTPException(404, str(e))
    except ConnectionError as e:
        raise HTTPException(503, f"LLM connection failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Coach session failed: {e}")


def _build_deck_report_from_db(deck_slug: str):
    """
    Build a lightweight DeckReport from the deck builder DB when no
    simulation report exists. Allows the coach to analyze deck composition
    even without simulation data.
    """
    from coach.models import DeckReport, CardPerformance, DeckStructure
    conn = _get_db_conn()

    # Find the deck by slug match against the deck name
    rows = conn.execute(
        "SELECT id, name, commander_name, color_identity FROM decks ORDER BY id"
    ).fetchall()

    matched_deck = None
    for r in rows:
        name = r["name"] or ""
        slug = name.lower().replace(" ", "-")
        # Also try a more thorough slugify
        import re
        clean_slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if slug == deck_slug.lower() or clean_slug == deck_slug.lower() or name.lower() == deck_slug.lower():
            matched_deck = r
            break

    if matched_deck is None:
        return None

    deck_id = matched_deck["id"]
    deck_name = matched_deck["name"]
    commander = matched_deck["commander_name"] or ""

    # Parse color identity
    ci_raw = matched_deck["color_identity"] or "[]"
    try:
        color_identity = json.loads(ci_raw) if isinstance(ci_raw, str) else ci_raw
    except Exception:
        color_identity = []

    # Load all cards in this deck
    card_rows = conn.execute(
        """SELECT dc.card_name, dc.quantity, dc.is_commander, dc.role_tag,
                  ce.type_line, ce.cmc, ce.oracle_text
           FROM deck_cards dc
           LEFT JOIN collection_entries ce ON LOWER(dc.card_name) = LOWER(ce.name)
           WHERE dc.deck_id = ?""",
        (deck_id,)
    ).fetchall()

    cards = []
    type_counts = {}
    cmc_buckets = [0] * 8
    land_count = 0

    for cr in card_rows:
        card_name = cr["card_name"] or ""
        type_line = cr["type_line"] or ""
        cmc = cr["cmc"] or 0
        qty = cr["quantity"] or 1
        role_tag = cr["role_tag"] or ""

        # Build tags from type_line and role_tag
        tags = []
        if role_tag:
            tags.append(role_tag)
        if "Land" in type_line:
            tags.append("land")
            land_count += qty
        elif "Creature" in type_line:
            tags.append("creature")
        elif "Instant" in type_line:
            tags.append("instant")
        elif "Sorcery" in type_line:
            tags.append("sorcery")
        elif "Artifact" in type_line:
            tags.append("artifact")
        elif "Enchantment" in type_line:
            tags.append("enchantment")
        elif "Planeswalker" in type_line:
            tags.append("planeswalker")

        # Type count
        for t in ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Land"]:
            if t in type_line:
                type_counts[t] = type_counts.get(t, 0) + qty

        # CMC bucket
        bucket = min(int(cmc), 7)
        cmc_buckets[bucket] += qty

        # CardPerformance with zeroed-out sim stats
        cards.append(CardPerformance(
            name=card_name,
            drawnRate=0.0,
            castRate=0.0,
            impactScore=0.0,
            tags=tags,
        ))

    slug = deck_slug
    return DeckReport(
        deckId=slug,
        commander=commander,
        colorIdentity=color_identity,
        cards=cards,
        structure=DeckStructure(
            landCount=land_count,
            curveBuckets=cmc_buckets,
            cardTypeCounts=type_counts,
        ),
    )


@app.get("/api/coach/sessions")
async def coach_list_sessions(deck_id: str = None):
    """List all coaching sessions, optionally filtered by deck."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")
    return {"sessions": _coach_service.list_sessions(deck_id)}


@app.get("/api/coach/sessions/{session_id}")
async def coach_get_session(session_id: str):
    """Get a specific coaching session."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")
    session = _coach_service.load_session(session_id)
    if session is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    return session.model_dump()


@app.post("/api/coach/embeddings/download")
async def coach_download_embeddings():
    """Download and convert MTG card embeddings from HuggingFace."""
    if _coach_embeddings is None:
        raise HTTPException(500, "Coach service not initialized")
    try:
        _coach_embeddings.load(force_download=True)
        return {
            "success": True,
            "cards": _coach_embeddings.card_count,
            "message": f"Loaded {_coach_embeddings.card_count} card embeddings"
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to download embeddings: {e}")


@app.get("/api/coach/embeddings/search")
async def coach_search_similar(card: str, colors: str = None, top_n: int = 10):
    """Search for similar cards by name."""
    if _coach_embeddings is None or not _coach_embeddings.loaded:
        raise HTTPException(503, "Embeddings not loaded")
    color_filter = list(colors.upper()) if colors else None
    matches = _coach_embeddings.search_similar(
        query_card=card, color_filter=color_filter, top_n=top_n
    )
    return {"query": card, "matches": [m.to_dict() for m in matches]}


@app.post("/api/coach/chat")
async def coach_chat(body: CoachChatRequest):
    """Multi-turn coaching chat. Sends conversation history to LLM and returns response."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")

    # Load deck report for context
    report = _coach_service.load_deck_report(body.deck_id)

    # Build system prompt with report context
    from coach.prompt_template import build_system_prompt
    from coach.models import CoachGoals

    goals = None
    if body.goals:
        try:
            goals = CoachGoals(**body.goals)
        except Exception:
            goals = None

    system_prompt = ""
    if report:
        system_prompt = build_system_prompt(report, goals)
    else:
        system_prompt = (
            "You are an expert Magic: The Gathering Commander deck coach. "
            "Answer questions about deck building, strategy, card choices, and game theory. "
            "Be specific and actionable in your advice."
        )

    # Build messages array for LLM
    messages = [{"role": "system", "content": system_prompt}]
    for msg in body.messages:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    # Call LLM with multi-turn messages
    try:
        import json
        from urllib.request import urlopen, Request as UrlRequest
        from coach.config import LM_STUDIO_URL, LM_STUDIO_TIMEOUT

        model_name = _coach_llm._resolve_model()
        llm_body = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        if body.stream:
            # SSE streaming response
            llm_body["stream"] = True

            async def generate():
                import asyncio
                def _stream():
                    req = UrlRequest(
                        f"{_coach_llm.base_url}/chat/completions",
                        data=json.dumps(llm_body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    import http.client
                    import urllib.parse
                    parsed = urllib.parse.urlparse(f"{_coach_llm.base_url}/chat/completions")
                    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=LM_STUDIO_TIMEOUT)
                    conn.request("POST", parsed.path, body=json.dumps(llm_body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
                    resp = conn.getresponse()
                    chunks = []
                    while True:
                        line = resp.readline()
                        if not line:
                            break
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                chunks.append("[DONE]")
                                break
                            chunks.append(data)
                    conn.close()
                    return chunks

                loop = asyncio.get_event_loop()
                chunks = await loop.run_in_executor(None, _stream)

                for chunk_str in chunks:
                    if chunk_str == "[DONE]":
                        yield f"data: [DONE]\n\n"
                        break
                    try:
                        chunk = json.loads(chunk_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            # Strip think tags from streaming chunks
                            yield f"data: {json.dumps({'content': content})}\n\n"
                    except json.JSONDecodeError:
                        continue

            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            # Non-streaming: regular call
            req = UrlRequest(
                f"{_coach_llm.base_url}/chat/completions",
                data=json.dumps(llm_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            import asyncio
            loop = asyncio.get_event_loop()
            def _call():
                with urlopen(req, timeout=LM_STUDIO_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            raw = await loop.run_in_executor(None, _call)

            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            # Strip think tags
            content = _coach_llm._strip_think_tags(content)
            usage = raw.get("usage", {})

            return {
                "content": content,
                "model": raw.get("model", ""),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }

    except Exception as e:
        raise HTTPException(500, f"Chat failed: {e}")


@app.post("/api/coach/apply")
async def coach_apply_suggestions(body: CoachApplyRequest):
    """Apply accepted coaching suggestions to a deck — remove cuts, add adds."""
    conn = _get_db_conn()

    # Verify deck exists
    deck = conn.execute("SELECT * FROM decks WHERE id = ?", (body.deck_id,)).fetchone()
    if not deck:
        raise HTTPException(404, f"Deck {body.deck_id} not found")

    results = {"cuts": [], "adds": [], "errors": []}

    # Process cuts: remove cards by name
    for card_name in body.accepted_cuts:
        row = conn.execute(
            "SELECT id FROM deck_cards WHERE deck_id = ? AND card_name = ? LIMIT 1",
            (body.deck_id, card_name)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM deck_cards WHERE id = ?", (row["id"],))
            results["cuts"].append({"name": card_name, "status": "removed"})
        else:
            # Try case-insensitive
            row = conn.execute(
                "SELECT id, card_name FROM deck_cards WHERE deck_id = ? AND LOWER(card_name) = LOWER(?) LIMIT 1",
                (body.deck_id, card_name)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM deck_cards WHERE id = ?", (row["id"],))
                results["cuts"].append({"name": row["card_name"], "status": "removed"})
            else:
                results["errors"].append({"name": card_name, "error": "Card not found in deck"})

    # Process adds: look up in collection first, then Scryfall
    for card_name in body.accepted_adds:
        # Try to find in collection
        ce = conn.execute(
            "SELECT scryfall_id, name FROM collection_entries WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (card_name,)
        ).fetchone()

        scryfall_id = None
        resolved_name = card_name

        if ce:
            scryfall_id = ce["scryfall_id"]
            resolved_name = ce["name"]
        else:
            # Try Scryfall API lookup
            try:
                import urllib.parse
                encoded = urllib.parse.quote(card_name)
                scry_req = UrlRequest(
                    f"https://api.scryfall.com/cards/named?fuzzy={encoded}",
                    headers={"User-Agent": "commander-ai-lab/1.0"}
                )
                with urlopen(scry_req, timeout=10) as resp:
                    card_data = json.loads(resp.read().decode("utf-8"))
                    scryfall_id = card_data.get("id")
                    resolved_name = card_data.get("name", card_name)
            except Exception:
                pass

        if scryfall_id:
            # Check if already in deck
            existing = conn.execute(
                "SELECT id FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
                (body.deck_id, scryfall_id)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity) VALUES (?, ?, ?, 1)",
                    (body.deck_id, scryfall_id, resolved_name)
                )
                results["adds"].append({"name": resolved_name, "scryfall_id": scryfall_id, "status": "added"})
            else:
                results["adds"].append({"name": resolved_name, "status": "already_in_deck"})
        else:
            results["errors"].append({"name": card_name, "error": "Could not resolve card"})

    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (body.deck_id,))
    conn.commit()

    results["total_cuts"] = len(results["cuts"])
    results["total_adds"] = len([a for a in results["adds"] if a["status"] == "added"])
    return results


@app.get("/api/coach/cards-like")
async def coach_cards_like(card: str, colors: str = None, top_n: int = 10):
    """Find cards similar to a given card using embeddings. UI-friendly version."""
    if _coach_embeddings is None or not _coach_embeddings.loaded:
        raise HTTPException(503, "Embeddings not loaded")

    color_filter = list(colors.upper()) if colors else None
    matches = _coach_embeddings.search_similar(
        query_card=card, color_filter=color_filter, top_n=top_n
    )

    conn = _get_db_conn()
    results = []
    for m in matches:
        # Check if card is in collection
        owned = conn.execute(
            "SELECT SUM(quantity) as qty FROM collection_entries WHERE LOWER(name) = LOWER(?)",
            (m.name,)
        ).fetchone()
        owned_qty = (owned["qty"] or 0) if owned else 0

        # Get image URL and price
        ce = conn.execute(
            "SELECT image_url, tcg_price FROM collection_entries WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (m.name,)
        ).fetchone()

        results.append({
            "name": m.name,
            "similarity": round(m.similarity, 4),
            "types": m.types,
            "mana_value": m.mana_value,
            "mana_cost": m.mana_cost,
            "text": m.text[:200] if m.text else "",
            "owned_qty": owned_qty,
            "image_url": ce["image_url"] if ce else None,
            "tcg_price": ce["tcg_price"] if ce else None,
        })

    return {"query": card, "results": results}


@app.post("/api/coach/reports/generate")
async def coach_generate_reports():
    """Rebuild all deck reports from batch result JSONs in results/."""
    try:
        from coach.report_generator import generate_deck_reports
        lab_root = Path(__file__).parent
        results_dir = str(lab_root / CFG.results_dir)
        reports_dir = str(lab_root / "deck-reports")
        updated = generate_deck_reports(results_dir, reports_dir)
        return {
            "status": "ok",
            "decksUpdated": updated,
            "count": len(updated),
            "message": f"Generated reports for {len(updated)} decks" if updated else "No batch results found",
        }
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}")


# ══════════════════════════════════════════════════════════════
# ML Training Data Endpoints
# ══════════════════════════════════════════════════════════════

@app.get("/api/ml/status")
async def ml_status():
    """Get ML decision logging status and available training data."""
    global _ml_logging_enabled
    lab_root = Path(__file__).parent
    results_dir = lab_root / CFG.results_dir

    # Find existing ML decision files
    ml_files = []
    if results_dir.exists():
        for f in sorted(results_dir.glob("ml-decisions-*.jsonl")):
            lines = 0
            try:
                with open(f) as fh:
                    lines = sum(1 for _ in fh)
            except Exception:
                pass
            ml_files.append({
                "file": f.name,
                "decisions": lines,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })

    total_decisions = sum(f["decisions"] for f in ml_files)
    return {
        "ml_logging_enabled": _ml_logging_enabled,
        "training_files": ml_files,
        "total_decisions": total_decisions,
        "total_files": len(ml_files),
    }


@app.post("/api/ml/toggle")
async def ml_toggle(enable: bool = True):
    """Enable or disable ML decision logging for future batch runs."""
    global _ml_logging_enabled
    _ml_logging_enabled = enable
    return {
        "ml_logging_enabled": _ml_logging_enabled,
        "message": f"ML decision logging {'enabled' if enable else 'disabled'} for future batches",
    }


@app.get("/api/ml/decisions/{filename}")
async def ml_get_decisions(filename: str, limit: int = 100, offset: int = 0):
    """Read decision snapshots from a training data file."""
    lab_root = Path(__file__).parent
    filepath = lab_root / CFG.results_dir / filename

    if not filepath.exists() or not filename.startswith("ml-decisions-"):
        raise HTTPException(404, f"ML decisions file not found: {filename}")

    decisions = []
    try:
        import json as _json
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(decisions) >= limit:
                    break
                try:
                    decisions.append(_json.loads(line.strip()))
                except _json.JSONDecodeError:
                    continue
    except Exception as e:
        raise HTTPException(500, f"Failed to read decisions: {e}")

    return {
        "file": filename,
        "offset": offset,
        "limit": limit,
        "count": len(decisions),
        "decisions": decisions,
    }


# ══════════════════════════════════════════════════════════════
# ML Policy Inference Endpoints
# ══════════════════════════════════════════════════════════════

# Lazy-loaded policy inference service (only loads when first called)
_policy_service = None
_policy_service_init_attempted = False


def _get_policy_service():
    """Get or initialize the policy inference service (lazy loading)."""
    global _policy_service, _policy_service_init_attempted
    if _policy_service is None and not _policy_service_init_attempted:
        _policy_service_init_attempted = True
        try:
            from ml.serving.policy_server import PolicyInferenceService
            _policy_service = PolicyInferenceService()
            if _policy_service.load():
                log_ml.info(f"Policy model loaded on {_policy_service.device}")
            else:
                log_ml.error(f"Policy model not available: {_policy_service._load_error}")
        except Exception as e:
            log_ml.error(f"Policy service init failed: {e}")
    return _policy_service


@app.post("/api/ml/predict")
async def ml_predict(request: FastAPIRequest):
    """Predict a macro-action from a game state snapshot.

    Accepts DecisionSnapshot-shaped JSON from the Java batch runner.
    Returns the learned policy's recommended action.

    Request body:
        {
            "turn": 5,
            "phase": "main_1",
            "active_seat": 0,
            "players": [...],
            "archetype": "aggro",
            "temperature": 1.0,
            "greedy": false
        }

    Response:
        {
            "action": "cast_creature",
            "action_index": 0,
            "confidence": 0.73,
            "probabilities": {...},
            "inference_ms": 2.3
        }
    """
    svc = _get_policy_service()
    if svc is None or not svc._loaded:
        detail = "Policy model not loaded. "
        if svc:
            detail += svc._load_error or "Train a model first."
        else:
            detail += "PyTorch may not be installed."
        raise HTTPException(status_code=503, detail=detail)

    body = await request.json()
    playstyle = body.pop("archetype", "midrange")
    temperature = body.pop("temperature", 1.0)
    greedy = body.pop("greedy", False)

    result = svc.predict(
        decision_snapshot=body,
        playstyle=playstyle,
        temperature=temperature,
        greedy=greedy,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/api/ml/predict/batch")
async def ml_predict_batch(request: FastAPIRequest):
    """Predict actions for multiple snapshots at once.

    Request body: {"snapshots": [...], "greedy": true}
    """
    svc = _get_policy_service()
    if svc is None or not svc._loaded:
        raise HTTPException(status_code=503, detail="Policy model not loaded")

    body = await request.json()
    snapshots = body.get("snapshots", [])
    greedy = body.get("greedy", True)

    if not snapshots:
        return {"results": []}

    results = svc.predict_batch(snapshots, greedy=greedy)
    return {"results": results, "count": len(results)}


@app.get("/api/ml/model")
async def ml_model_info():
    """Get information about the loaded policy model."""
    svc = _get_policy_service()
    if svc is None:
        return {
            "loaded": False,
            "error": "Policy service not initialized",
            "torch_available": False,
        }
    return svc.get_status()


@app.post("/api/ml/reload")
async def ml_reload_model(checkpoint: str = None):
    """Hot-reload a policy model checkpoint."""
    svc = _get_policy_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Policy service not available")

    # If service hasn't loaded yet, try full load
    if not svc._loaded:
        ok = svc.load()
    else:
        ok = svc.reload(checkpoint)

    return {
        "success": ok,
        "status": svc.get_status(),
    }


# ══════════════════════════════════════════════════════════════
# ML Training Management Endpoints
# ══════════════════════════════════════════════════════════════

# Training state tracking
_training_state = {
    "running": False,
    "progress": 0,
    "total_epochs": 0,
    "current_epoch": 0,
    "phase": "idle",  # idle | building | training | evaluating | done | error
    "message": "",
    "metrics": None,  # latest epoch metrics
    "result": None,   # final training result
    "error": None,
    "started_at": None,
}


def _run_training_pipeline(
    results_dir: str,
    epochs: int,
    lr: float,
    batch_size: int,
    patience: int,
    rebuild_dataset: bool,
):
    """Run the full ML training pipeline in a background thread."""
    global _training_state
    try:
        import sys
        project_root = str(Path(__file__).parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        _training_state["running"] = True
        _training_state["started_at"] = datetime.now().isoformat()
        _training_state["error"] = None
        _training_state["result"] = None

        data_dir = os.path.join(project_root, "ml", "models")
        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        # --- Phase 1: Build Dataset ---
        train_path = os.path.join(data_dir, "train.npz")
        if rebuild_dataset or not os.path.exists(train_path):
            _training_state["phase"] = "building"
            _training_state["message"] = "Loading card embeddings & building dataset..."
            log_ml.info("Building dataset (loading embeddings, may auto-download)...")

            from ml.data.dataset_builder import build_dataset, split_dataset, save_dataset
            dataset = build_dataset(results_dir=results_dir)
            if not dataset:
                raise RuntimeError("No training data produced. Check server log for details.")
            train_ds, val_ds, test_ds = split_dataset(dataset)
            save_dataset(train_ds, os.path.join(data_dir, "train.npz"))
            save_dataset(val_ds, os.path.join(data_dir, "val.npz"))
            save_dataset(test_ds, os.path.join(data_dir, "test.npz"))
            total_samples = len(dataset["states"])
            _training_state["message"] = f"Dataset built: {total_samples} samples"
            log_ml.info(f"Dataset built: {total_samples} samples")

        # --- Phase 2: Train ---
        _training_state["phase"] = "training"
        _training_state["total_epochs"] = epochs
        _training_state["current_epoch"] = 0
        _training_state["message"] = f"Training policy network ({epochs} epochs)..."
        log_ml.info(f"Starting training: {epochs} epochs, lr={lr}, bs={batch_size}")

        import numpy as np
        import torch
        from ml.training.policy_network import PolicyNetwork
        from ml.training.trainer import SupervisedTrainer

        def load_npz_split(path):
            data = np.load(path)
            return data["states"].astype(np.float32), data["labels"].astype(np.int64)

        train_states, train_labels = load_npz_split(train_path)
        val_path = os.path.join(data_dir, "val.npz")
        val_states, val_labels = load_npz_split(val_path)

        actual_dim = train_states.shape[1]
        model = PolicyNetwork(input_dim=actual_dim)

        device = "cpu"
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"

        trainer = SupervisedTrainer(
            model=model,
            device=device,
            learning_rate=lr,
            batch_size=batch_size,
            epochs=epochs,
            patience=patience,
            checkpoint_dir=ckpt_dir,
        )

        # Hook into trainer to report progress
        original_train = trainer.train

        def patched_train(train_s, train_l, val_s, val_l):
            # We'll monitor the checkpoint dir for progress
            return original_train(train_s, train_l, val_s, val_l)

        summary = trainer.train(train_states, train_labels, val_states, val_labels)

        _training_state["current_epoch"] = summary.get("epochs_trained", epochs)
        _training_state["metrics"] = summary

        # --- Phase 3: Evaluate ---
        _training_state["phase"] = "evaluating"
        _training_state["message"] = "Evaluating on test set..."

        test_path = os.path.join(data_dir, "test.npz")
        eval_results = None
        if os.path.exists(test_path):
            from ml.training.trainer import load_checkpoint, evaluate_model
            test_states, test_labels = load_npz_split(test_path)
            best_model, _ = load_checkpoint(summary["checkpoint_path"], device)
            eval_results = evaluate_model(best_model, test_states, test_labels, device)

            eval_path = os.path.join(ckpt_dir, "eval_results.json")
            with open(eval_path, "w") as f:
                json.dump(eval_results, f, indent=2)

        # --- Done ---
        _training_state["phase"] = "done"
        _training_state["running"] = False
        _training_state["result"] = {
            "training": summary,
            "evaluation": eval_results,
            "checkpoint": summary.get("checkpoint_path", ""),
            "device": device,
        }
        _training_state["message"] = f"Training complete! Best val acc: {summary.get('best_val_accuracy', 0):.1%}"
        log_ml.info(f"Complete: {summary.get('best_val_accuracy', 0):.1%} val accuracy")

        # Auto-reload policy server with new checkpoint
        global _policy_service, _policy_service_init_attempted
        if _policy_service and _policy_service._loaded:
            _policy_service.reload(summary.get("checkpoint_path"))
            log_ml.info("Policy server reloaded with new checkpoint")
        elif not _policy_service_init_attempted:
            _policy_service_init_attempted = False  # Allow re-init with new model

    except Exception as e:
        import traceback
        _training_state["phase"] = "error"
        _training_state["running"] = False
        _training_state["error"] = str(e)
        _training_state["message"] = f"Training failed: {e}"
        log_ml.error(f"ERROR: {e}")
        traceback.print_exc()


@app.post("/api/ml/train")
async def ml_start_training(request: FastAPIRequest):
    """Trigger ML training pipeline from the web UI.

    Request body (all optional):
        {
            "epochs": 50,
            "lr": 0.001,
            "batchSize": 256,
            "patience": 10,
            "rebuildDataset": true
        }
    """
    if _training_state["running"]:
        raise HTTPException(409, "Training already in progress")

    body = await request.json() if await request.body() else {}
    epochs = body.get("epochs", 50)
    lr = body.get("lr", 0.001)
    batch_size = body.get("batchSize", 256)
    patience = body.get("patience", 10)
    rebuild = body.get("rebuildDataset", True)

    results_dir = os.path.join(str(Path(__file__).parent), "results")

    # Reset state
    _training_state.update({
        "running": True,
        "progress": 0,
        "total_epochs": epochs,
        "current_epoch": 0,
        "phase": "starting",
        "message": "Initializing training pipeline...",
        "metrics": None,
        "result": None,
        "error": None,
    })

    # Run in background thread
    thread = threading.Thread(
        target=_run_training_pipeline,
        args=(results_dir, epochs, lr, batch_size, patience, rebuild),
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "config": {
            "epochs": epochs,
            "lr": lr,
            "batchSize": batch_size,
            "patience": patience,
            "rebuildDataset": rebuild,
        },
    }


@app.get("/api/ml/train/status")
async def ml_training_status():
    """Get current training pipeline status."""
    return dict(_training_state)


@app.get("/api/ml/data/status")
async def ml_data_status():
    """Get status of available training data and model checkpoints."""
    project_root = Path(__file__).parent
    results_dir = project_root / "results"
    data_dir = project_root / "ml" / "models"
    ckpt_dir = data_dir / "checkpoints"

    # Decision log files
    decision_files = []
    if results_dir.exists():
        for f in sorted(results_dir.glob("ml-decisions-*.jsonl")):
            line_count = 0
            try:
                with open(f, "r") as fh:
                    line_count = sum(1 for _ in fh)
            except Exception:
                pass
            decision_files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "decisions": line_count,
            })

    # Dataset files
    datasets = {}
    for split in ["train", "val", "test"]:
        path = data_dir / f"{split}.npz"
        if path.exists():
            try:
                import numpy as np
                data = np.load(str(path))
                datasets[split] = {
                    "samples": int(data["states"].shape[0]),
                    "features": int(data["states"].shape[1]),
                    "size": path.stat().st_size,
                }
            except Exception:
                datasets[split] = {"size": path.stat().st_size}

    # Checkpoints
    checkpoints = []
    if ckpt_dir.exists():
        for f in sorted(ckpt_dir.glob("*.pt")):
            checkpoints.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    # Eval results
    eval_path = ckpt_dir / "eval_results.json"
    eval_results = None
    if eval_path.exists():
        try:
            with open(eval_path, "r") as f:
                eval_results = json.load(f)
        except Exception:
            pass

    return {
        "decisionFiles": decision_files,
        "totalDecisions": sum(d["decisions"] for d in decision_files),
        "datasets": datasets,
        "checkpoints": checkpoints,
        "evalResults": eval_results,
        "policyLoaded": _policy_service is not None and _policy_service._loaded if _policy_service else False,
    }


# ══════════════════════════════════════════════════════════════
# PPO Training + Tournament Endpoints
# ══════════════════════════════════════════════════════════════

_ppo_state = {
    "running": False,
    "iteration": 0,
    "total_iterations": 0,
    "phase": "idle",
    "message": "",
    "metrics": None,
    "result": None,
    "error": None,
}

_tournament_state = {
    "running": False,
    "phase": "idle",
    "message": "",
    "result": None,
    "error": None,
}


def _run_ppo_pipeline(
    iterations: int, episodes_per_iter: int, ppo_epochs: int, batch_size: int,
    lr: float, clip_epsilon: float, entropy_coeff: float,
    opponent: str, playstyle: str, load_supervised: str,
):
    """Run PPO training in a background thread."""
    global _ppo_state
    try:
        import sys
        project_root = str(Path(__file__).parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        _ppo_state["running"] = True
        _ppo_state["error"] = None
        _ppo_state["result"] = None

        from ml.training.ppo_trainer import PPOTrainer, PPOConfig

        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        config = PPOConfig(
            iterations=iterations,
            episodes_per_iter=episodes_per_iter,
            ppo_epochs=ppo_epochs,
            batch_size=batch_size,
            learning_rate=lr,
            clip_epsilon=clip_epsilon,
            entropy_coeff=entropy_coeff,
            opponent=opponent,
            playstyle=playstyle,
            checkpoint_dir=ckpt_dir,
            load_supervised=load_supervised if load_supervised else None,
        )

        trainer = PPOTrainer(config)

        def progress_cb(iteration, metrics):
            _ppo_state["iteration"] = iteration
            _ppo_state["phase"] = "training"
            _ppo_state["message"] = f"Iteration {iteration}/{iterations} | WR: {metrics.get('win_rate', 0):.0%}"
            _ppo_state["metrics"] = metrics

        summary = trainer.train(progress_callback=progress_cb)

        _ppo_state["phase"] = "done"
        _ppo_state["running"] = False
        _ppo_state["result"] = summary
        _ppo_state["message"] = f"PPO complete! Best win rate: {summary.get('best_win_rate', 0):.0%}"

    except Exception as e:
        import traceback
        _ppo_state["phase"] = "error"
        _ppo_state["running"] = False
        _ppo_state["error"] = str(e)
        _ppo_state["message"] = f"PPO failed: {e}"
        traceback.print_exc()


@app.post("/api/ml/train/ppo")
async def ml_start_ppo(request: FastAPIRequest):
    """Start PPO training pipeline."""
    if _ppo_state["running"]:
        raise HTTPException(409, "PPO training already in progress")
    if _training_state["running"]:
        raise HTTPException(409, "Supervised training in progress — wait for it to finish")

    body = await request.json() if await request.body() else {}
    iterations = body.get("iterations", 100)
    episodes = body.get("episodesPerIter", 64)
    ppo_epochs = body.get("ppoEpochs", 4)
    batch_size = body.get("batchSize", 256)
    lr = body.get("lr", 3e-4)
    clip_eps = body.get("clipEpsilon", 0.2)
    entropy = body.get("entropyCoeff", 0.01)
    opponent = body.get("opponent", "heuristic")
    playstyle = body.get("playstyle", "midrange")
    load_sup = body.get("loadSupervised", "")

    _ppo_state.update({
        "running": True, "iteration": 0, "total_iterations": iterations,
        "phase": "starting", "message": "Initializing PPO...",
        "metrics": None, "result": None, "error": None,
    })

    thread = threading.Thread(
        target=_run_ppo_pipeline,
        args=(iterations, episodes, ppo_epochs, batch_size, lr, clip_eps, entropy, opponent, playstyle, load_sup),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "iterations": iterations}


@app.get("/api/ml/train/ppo/status")
async def ml_ppo_status():
    """Get PPO training status."""
    return dict(_ppo_state)


def _run_tournament_pipeline(episodes: int, playstyle: str):
    """Run tournament in a background thread."""
    global _tournament_state
    try:
        import sys
        project_root = str(Path(__file__).parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        _tournament_state["running"] = True
        _tournament_state["error"] = None
        _tournament_state["result"] = None
        _tournament_state["phase"] = "running"
        _tournament_state["message"] = "Running tournament..."

        from ml.eval.tournament import (
            run_tournament, HeuristicPolicy, RandomPolicy, LearnedPolicy,
        )

        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        policies = {
            "heuristic": HeuristicPolicy(),
            "random": RandomPolicy(),
        }

        sup_path = os.path.join(ckpt_dir, "best_policy.pt")
        if os.path.exists(sup_path):
            policies["supervised"] = LearnedPolicy(sup_path)

        ppo_path = os.path.join(ckpt_dir, "best_ppo.pt")
        if os.path.exists(ppo_path):
            policies["ppo"] = LearnedPolicy(ppo_path)

        result = run_tournament(
            policies=policies,
            episodes_per_matchup=episodes,
            playstyle=playstyle,
        )

        # Save results
        output_path = os.path.join(ckpt_dir, "tournament_results.json")
        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)

        _tournament_state["phase"] = "done"
        _tournament_state["running"] = False
        _tournament_state["result"] = result.to_dict()
        _tournament_state["message"] = f"Tournament complete! {result.total_matches} matches"

    except Exception as e:
        import traceback
        _tournament_state["phase"] = "error"
        _tournament_state["running"] = False
        _tournament_state["error"] = str(e)
        _tournament_state["message"] = f"Tournament failed: {e}"
        traceback.print_exc()


@app.post("/api/ml/tournament")
async def ml_start_tournament(request: FastAPIRequest):
    """Start a tournament evaluation."""
    if _tournament_state["running"]:
        raise HTTPException(409, "Tournament already in progress")

    body = await request.json() if await request.body() else {}
    episodes = body.get("episodes", 50)
    playstyle = body.get("playstyle", "midrange")

    _tournament_state.update({
        "running": True, "phase": "starting",
        "message": "Initializing tournament...",
        "result": None, "error": None,
    })

    thread = threading.Thread(
        target=_run_tournament_pipeline,
        args=(episodes, playstyle),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "episodes": episodes}


@app.get("/api/ml/tournament/status")
async def ml_tournament_status():
    """Get tournament status."""
    return dict(_tournament_state)


@app.get("/api/ml/tournament/results")
async def ml_tournament_results():
    """Get latest tournament results."""
    project_root = Path(__file__).parent
    results_path = project_root / "ml" / "models" / "checkpoints" / "tournament_results.json"
    if results_path.exists():
        with open(results_path, "r") as f:
            return json.load(f)
    return {"error": "No tournament results found. Run a tournament first."}


# ══════════════════════════════════════════════════════════════
# Static File Serving (React SPA) — MUST be after all API routes
# ══════════════════════════════════════════════════════════════

# UI Serving: legacy HTML/JS/CSS pages (primary) or React SPA (fallback)
_legacy_ui_dir = Path(__file__).parent / "ui"
_spa_dir = Path(__file__).parent / "frontend" / "commander-ai-lab-ui" / "dist"

if _legacy_ui_dir.exists():
    # Primary: serve the proven multi-page HTML/JS/CSS UI
    app.mount("/", StaticFiles(directory=str(_legacy_ui_dir), html=True), name="ui")

elif _spa_dir.exists():
    # Fallback: React SPA (only if legacy ui/ folder is missing)
    _spa_assets = _spa_dir / "assets"
    if _spa_assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_spa_assets)), name="spa-assets")

    @app.get("/{full_path:path}")
    async def _spa_catchall(full_path: str):
        from fastapi.responses import FileResponse
        requested_file = _spa_dir / full_path
        if full_path and requested_file.exists() and requested_file.is_file():
            return FileResponse(str(requested_file))
        return FileResponse(str(_spa_dir / "index.html"))


# ══════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description="Commander AI Lab API Server v3")
    parser.add_argument("--forge-jar", default=os.environ.get("FORGE_JAR", ""),
                        help="Path to forge-gui-desktop jar-with-dependencies")
    parser.add_argument("--forge-dir", default=os.environ.get("FORGE_DIR", ""),
                        help="Forge working directory (contains res/)")
    parser.add_argument("--forge-decks-dir", default=os.environ.get("FORGE_DECKS_DIR", ""),
                        help="Path to Commander deck files (default: %%APPDATA%%/Forge/decks/commander)")
    parser.add_argument("--lab-jar", default=os.environ.get("LAB_JAR", ""),
                        help="Path to commander-ai-lab.jar (default: auto-detect from target/)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAB_PORT", "8080")))
    parser.add_argument("--ximilar-key", default=os.environ.get("XIMILAR_API_KEY", "96c7dab35ddbd8829b04c0f5bcea57f5ede20496"),
                        help="Ximilar API key for card scanner (visual AI recognition)")
    parser.add_argument("--pplx-key", default=os.environ.get("PPLX_API_KEY", "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"),
                        help="Perplexity API key for AI deck research/generation (env: PPLX_API_KEY)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable DEBUG-level logging (default: INFO)")
    return parser.parse_args()


def resolve_lab_jar() -> str:
    target_dir = Path(__file__).parent / "target"
    if target_dir.exists():
        for pattern in [
            "commander-ai-lab-*-jar-with-dependencies.jar",
            "commander-ai-lab-*-shaded.jar",
            "commander-ai-lab-*.jar",
        ]:
            jars = sorted(target_dir.glob(pattern))
            jars = [j for j in jars if not j.name.startswith("original-")]
            if jars:
                return str(jars[0])
    return ""


def resolve_forge_decks_dir() -> str:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = os.path.join(appdata, "Forge", "decks", "commander")
            if os.path.isdir(candidate):
                return candidate
    home = Path.home()
    for candidate in [
        home / ".forge" / "decks" / "commander",
        home / "Forge" / "decks" / "commander",
    ]:
        if candidate.is_dir():
            return str(candidate)
    return ""


def load_commander_meta():
    """Load commander meta mapping from file or use builtins."""
    global COMMANDER_META
    meta_path = Path(__file__).parent / "commander-meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                COMMANDER_META = json.load(f)
            log.info(f"  Meta:         Loaded {len(COMMANDER_META)} commanders from {meta_path}")
            return
        except Exception as e:
            log.warning(f"  WARNING: Failed to load commander-meta.json: {e}")

    COMMANDER_META = BUILTIN_COMMANDERS
    log.info(f"  Meta:         {len(COMMANDER_META)} built-in commanders")


def main():
    args = parse_args()
    setup_logging(logging.DEBUG if getattr(args, 'verbose', False) else logging.INFO)

    CFG.forge_jar = args.forge_jar
    CFG.forge_dir = args.forge_dir
    CFG.forge_decks_dir = args.forge_decks_dir or resolve_forge_decks_dir()
    CFG.lab_jar = args.lab_jar or resolve_lab_jar()
    CFG.port = args.port
    CFG.ximilar_api_key = args.ximilar_key
    CFG.pplx_api_key = args.pplx_key

    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║      Commander AI Lab — API Server  v3.0.0      ║")
    log.info("╚══════════════════════════════════════════════════╝")
    log.info("")
    log.info(f"  Forge JAR:    {CFG.forge_jar}")
    log.info(f"  Forge Dir:    {CFG.forge_dir}")
    log.info(f"  Decks Dir:    {CFG.forge_decks_dir}")
    log.info(f"  Lab JAR:      {CFG.lab_jar}")
    log.info(f"  Results Dir:  {CFG.results_dir}")
    log.info(f"  Port:         {CFG.port}")
    log.info(f"  Ximilar:      {'configured' if CFG.ximilar_api_key else 'NOT SET (scanner will fail)'}")
    log.info(f"  Perplexity:   {'configured' if CFG.pplx_api_key else 'NOT SET (AI research/gen disabled)'}")
    j17 = get_java17()
    log.info(f"  Java 17:      {j17 if j17 != 'java' else 'NOT FOUND (batch sim may fail on Java 25+)'}")
    log.info(f"  LM Studio:    http://192.168.0.122:1234")

    load_commander_meta()
    download_precon_database()  # Auto-downloads all 163+ Commander precons on first run
    init_collection_db()
    init_coach_service()

    # Ximilar API key check
    if not CFG.ximilar_api_key:
        log_scan.warning("  WARNING: --ximilar-key not set. Card scanner will not work.")
        log.info("           Set via CLI: --ximilar-key YOUR_KEY")
        log.info("           Or env var:  XIMILAR_API_KEY=YOUR_KEY")

    if not CFG.forge_jar:
        log.warning("WARNING: --forge-jar not set. /api/lab/start will fail.")
    if not CFG.lab_jar:
        log.warning("WARNING: Lab JAR not found. Build with: mvn package -DskipTests")
    if not CFG.forge_decks_dir:
        log.warning("WARNING: Commander decks dir not found. /api/lab/decks will return empty.")

    log.info("")
    log.info(f"  Starting server on http://localhost:{CFG.port}")
    if _spa_dir.exists():
        log.info(f"  Web UI:       http://localhost:{CFG.port}/  (React SPA)")
        log.info(f"  Routes:       / (Batch Sim), /collection, /decks, /autogen, /simulator, /coach, /training")
    else:
        log.info(f"  Web UI:       http://localhost:{CFG.port}/index.html  (legacy HTML)")
        log.info(f"  NOTE: React SPA not built. Run: cd frontend/commander-ai-lab-ui && npm install && npm run build")
    log.info(f"  API docs:     http://localhost:{CFG.port}/docs")
    log.info("")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=CFG.port, log_level="info")


if __name__ == "__main__":
    main()
