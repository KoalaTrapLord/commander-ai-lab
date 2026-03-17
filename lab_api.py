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
# Shared Module — configuration, models, helpers
# ══════════════════════════════════════════════════════════════

from routes.shared import (
    # Configuration
    Config, CFG, setup_logging,
    # Loggers
    # (we re-create named loggers locally below for convenience)
    # In-memory state
    BatchState, COMMANDER_META,
    # Pydantic models
    StartRequest, StartResponse, StatusResponse, DeckInfo,
    ImportUrlRequest, ImportTextRequest, MetaFetchRequest,
    CreateDeckRequest, UpdateDeckRequest, AddDeckCardRequest,
    PatchDeckCardRequest, BulkAddRequest, BulkAddRecommendedRequest,
    DeckGenerationSourceConfig, DeckGenerationRequest, GeneratedDeckCard,
    DeckGenV3Request, DeckGenV3SubstituteRequest,
    # Database
    _get_db_conn, init_collection_db,
    COLLECTION_DB_PATH,
    # Collection helpers
    _row_to_dict, _snake_to_camel, _add_image_url,
    _build_collection_filters,
    _detect_card_roles, _classify_card_type,
    VALID_SORT_FIELDS,
    # Deck helpers
    _get_deck_or_404, _compute_deck_analysis, _check_ratio_limit,
    # Scryfall
    _ScryfallCache, _scryfall_cache, _scryfall_rate_limit,
    _fetch_scryfall_api, _enrich_from_scryfall, _scryfall_fuzzy_lookup,
    SCRYFALL_CACHE_DB_PATH, SCRYFALL_CACHE_TTL_SECONDS,
    _API_HEADERS,
    # Import/fetch helpers
    _http_get, _import_from_url, _fetch_archidekt_deck,
    _fetch_edhrec_average, _parse_text_decklist,
    _save_profile_to_dck, _to_edhrec_slug,
    _parse_finish, _parse_text_line, _auto_infer_mapping, _parse_csv_content,
    # Precon helpers
    load_precon_index, _sanitize_filename, _deck_to_dck,
    download_precon_database,
    PRECON_DIR, PRECON_INDEX, GITHUB_PRECON_URL, PRECON_CACHE_HOURS,
    # Java/batch
    _find_java17, get_java17, build_java_command,
    parse_dck_file, _load_deck_cards_by_name,
    run_batch_subprocess, _run_process_blocking,
    _run_deepseek_batch_thread,
    _get_deepseek_brain,
    # AI profiles & ML
    AI_PROFILES, _ml_logging_enabled,
    # EDHREC cache
    _edhrec_cache, _EDHREC_CACHE_TTL,
    _edhrec_cache_get, _edhrec_cache_set,
    # Commander meta
    load_commander_meta, BUILTIN_COMMANDERS,
)

# Route modules
from routes.collection import router as collection_router
from routes.deckbuilder import router as deckbuilder_router
from routes.precon import router as precon_router
from routes.import_routes import router as import_router
from routes.lab import router as lab_router
from routes.scanner import router as scanner_router
from routes.deepseek import router as deepseek_router
from routes.deckgen import router as deckgen_router
from routes.coach import router as coach_router, init_coach_service
from routes.ml import router as ml_router


# ══════════════════════════════════════════════════════════════
# Logging Setup
# ══════════════════════════════════════════════════════════════

_LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR = Path(os.environ.get("CAL_LOG_DIR", "logs"))

# Named loggers — convenience aliases for remaining endpoints
log = logging.getLogger("commander_ai_lab.api")
log_batch = logging.getLogger("commander_ai_lab.batch")
log_sim = logging.getLogger("commander_ai_lab.sim")
log_coach = logging.getLogger("commander_ai_lab.coach")
log_deckgen = logging.getLogger("commander_ai_lab.deckgen")
log_collect = logging.getLogger("commander_ai_lab.collection")
log_scan = logging.getLogger("commander_ai_lab.scanner")
log_ml = logging.getLogger("commander_ai_lab.ml")
log_cache = logging.getLogger("commander_ai_lab.cache")
log_pplx = logging.getLogger("commander_ai_lab.pplx")


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

# Register extracted route modules
app.include_router(collection_router)
app.include_router(deckbuilder_router)
app.include_router(precon_router)
app.include_router(import_router)
app.include_router(lab_router)
app.include_router(scanner_router)
app.include_router(deepseek_router)
app.include_router(deckgen_router)
app.include_router(coach_router)
app.include_router(ml_router)


@app.on_event("startup")
async def _on_startup():
    """Safety net: ensure DB and precon index are initialized even when
    main() is bypassed (e.g. uvicorn lab_api:app --reload)."""
    import routes.shared as _shared
    _shared.init_collection_db()
    if not _shared.PRECON_INDEX:
        _shared.download_precon_database()
    if not _shared.COMMANDER_META:
        _shared.load_commander_meta()


# ══════════════════════════════════════════════════════════════
# In-Memory State (used by remaining endpoints)
# ══════════════════════════════════════════════════════════════

active_batches: dict[str, BatchState] = {}

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
    parser.add_argument("--ximilar-key", default=os.environ.get("XIMILAR_API_KEY", ""),
                        help="Ximilar API key for card scanner (env: XIMILAR_API_KEY)")
    parser.add_argument("--pplx-key", default=os.environ.get("PPLX_API_KEY", ""),
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


# load_commander_meta() is now in routes/shared.py


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
