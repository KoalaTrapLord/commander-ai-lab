"""
routes/shared.py
================
Single source of truth for everything every router needs.

Contains:
  - Config class + CFG singleton
  - Logging setup + all named loggers
  - FastAPI app instance
  - In-memory state (active_batches, COMMANDER_META, PRECON_INDEX, AI_PROFILES)
  - All Pydantic request/response models
  - SQLite DB helpers (_get_db_conn, init_collection_db)
  - Scryfall cache + enrichment helpers
  - Collection helpers (_detect_card_roles, _classify_card_type,
      _build_collection_filters, _parse_finish, _parse_csv_content,
      _parse_text_line, _auto_infer_mapping, _row_to_dict, _add_image_url,
      _snake_to_camel, VALID_SORT_FIELDS, _JSON_FIELDS)
  - Deck helpers (_get_deck_or_404, _compute_deck_analysis, _check_ratio_limit,
      _TYPE_TARGETS, _TYPE_PRIORITY, _classify_card_type)
  - Import helpers (_import_from_url, _fetch_archidekt_deck,
      _fetch_edhrec_average, _parse_text_decklist, _save_profile_to_dck,
      _to_edhrec_slug, _http_get, _API_HEADERS, _edhrec_cache_get,
      _edhrec_cache_set)
  - Precon helpers (PRECON_DIR, PRECON_INDEX, download_precon_database,
      load_precon_index, GITHUB_PRECON_URL, PRECON_CACHE_HOURS)
  - Sim helpers (build_java_command, get_java17, BatchState, parse_dck_file,
      AI_PROFILES, run_batch_subprocess, _run_process_blocking,
      _run_deepseek_batch_thread, _load_deck_cards_by_name, _get_deepseek_brain)
"""

from __future__ import annotations

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
from collections import Counter
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

# Configuration (imported from models/state)
from models.state import Config, CFG


# ══════════════════════════════════════════════════════════════
# Logging Setup
# ══════════════════════════════════════════════════════════════

_LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR = Path(os.environ.get("CAL_LOG_DIR", "logs"))
_LOG_MAX_BYTES = int(os.environ.get("CAL_LOG_MAX_MB", "25")) * 1024 * 1024
_LOG_BACKUP_COUNT = int(os.environ.get("CAL_LOG_BACKUP_COUNT", "5"))


def setup_logging(level: int = logging.INFO) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger("commander_ai_lab")
    root_logger.setLevel(level)
    if root_logger.handlers:
        return
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "commander-ai-lab.log",
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


log          = logging.getLogger("commander_ai_lab.api")
log_batch    = logging.getLogger("commander_ai_lab.batch")
log_sim      = logging.getLogger("commander_ai_lab.sim")
log_coach    = logging.getLogger("commander_ai_lab.coach")
log_deckgen  = logging.getLogger("commander_ai_lab.deckgen")
log_collect  = logging.getLogger("commander_ai_lab.collection")
log_scan     = logging.getLogger("commander_ai_lab.scanner")
log_ml       = logging.getLogger("commander_ai_lab.ml")
log_cache    = logging.getLogger("commander_ai_lab.cache")
log_pplx     = logging.getLogger("commander_ai_lab.pplx")


# ══════════════════════════════════════════════════════════════
# In-Memory State
# ══════════════════════════════════════════════════════════════

# In-Memory State (imported from models/state)
from models.state import (
    BatchState, active_batches, COMMANDER_META,
    BUILTIN_COMMANDERS, load_commander_meta,
)


# Pydantic Models (imported from models/)
from models.requests import (
    StartRequest, ImportUrlRequest, ImportTextRequest, MetaFetchRequest,
    CreateDeckRequest, UpdateDeckRequest, AddDeckCardRequest,
    PatchDeckCardRequest, BulkAddRequest, BulkAddRecommendedRequest,
    DeckGenerationSourceConfig, DeckGenerationRequest,
    DeckGenV3Request, DeckGenV3SubstituteRequest,
)
from models.responses import (
    StartResponse, StatusResponse, DeckInfo, GeneratedDeckCard,
)


# Collection Database (imported from services/database.py)
from services.database import (
    COLLECTION_DB_PATH, _get_db_conn, init_collection_db,
    _JSON_FIELDS, VALID_SORT_FIELDS,
    _row_to_dict, _snake_to_camel, _add_image_url, _build_collection_filters,
)
# Card Role Detection (imported from services/card_analysis.py)
from services.card_analysis import _detect_card_roles


# ══════════════════════════════════════════════════════════════
# Deck Helpers (imported from services/deck_service.py)
from services.deck_service import (
    _TYPE_PRIORITY, _TYPE_TARGETS, _classify_card_type, _get_deck_or_404,
    _compute_deck_analysis, _check_ratio_limit, _to_edhrec_slug,
    parse_dck_file, _save_profile_to_dck, _load_deck_cards_by_name,
)


# ══════════════════════════════════════════════════════════════
# Scryfall Cache (imported from services/scryfall.py)
from services.scryfall import (
    SCRYFALL_CACHE_DB_PATH, SCRYFALL_CACHE_TTL_SECONDS, _API_HEADERS,
    _ScryfallCache, _scryfall_cache, _scryfall_lock, _scryfall_last_call,
    _scryfall_rate_limit, _fetch_scryfall_api, _enrich_from_scryfall, _scryfall_fuzzy_lookup,
)

# ══════════════════════════════════════════════════════════════
# Import Helpers (extracted to services/import_helpers.py)
from services.import_helpers import (
    _http_get, _fetch_archidekt_deck, _fetch_edhrec_average,
    _import_from_url, _parse_text_decklist, _save_profile_to_dck,
    _edhrec_cache, _EDHREC_CACHE_TTL, _edhrec_cache_get, _edhrec_cache_set,
)

# ══════════════════════════════════════════════════════════════
# Collection Import Helpers (extracted to services/import_service.py)
from services.import_service import (
    _parse_finish, _parse_text_line, _auto_infer_mapping, _parse_csv_content,
)

# ══════════════════════════════════════════════════════════════
# Precon Helpers (extracted to services/precon_service.py)
from services.precon_service import (
    PRECON_DIR, PRECON_INDEX, GITHUB_PRECON_URL, PRECON_CACHE_HOURS,
    load_precon_index, _sanitize_filename, _deck_to_dck, download_precon_database,
)

# ══════════════════════════════════════════════════════════════
# AI Profiles (imported from models/state)
from models.state import AI_PROFILES

# ══════════════════════════════════════════════════════════════
# Java / Sim Helpers (extracted to services/forge_runner.py)
from services.forge_runner import (
    _find_java17, get_java17, build_java_command, parse_dck_file,
    run_batch_subprocess, _run_process_blocking,
    _run_deepseek_batch_thread, _get_deepseek_brain,
)

_ml_logging_enabled = False
