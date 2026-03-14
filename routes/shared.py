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

class Config:
    """Runtime configuration — set via CLI args or env vars."""
    forge_jar: str = ""
    forge_dir: str = ""
    forge_decks_dir: str = ""
    lab_jar: str = ""
    results_dir: str = "results"
    port: int = 8080
    ximilar_api_key: str = ""
    pplx_api_key: str = ""

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

class BatchState:
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
        self.sims_per_sec: float = 0.0

active_batches: dict[str, BatchState] = {}
COMMANDER_META: dict = {}


# ══════════════════════════════════════════════════════════════
# Pydantic Models
# ══════════════════════════════════════════════════════════════

class StartRequest(BaseModel):
    decks: list[str]
    numGames: int = 100
    threads: int = 4
    seed: Optional[int] = None
    clock: int = 120
    deckSources: Optional[list[Optional[dict]]] = None
    useLearnedPolicy: bool = False
    policyStyle: str = "midrange"
    policyGreedy: bool = False
    aiSimplified: bool = False
    aiThinkTimeMs: int = -1
    maxQueueDepth: int = -1

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
    cards: list[dict]
    respect_ratios: Optional[bool] = False

class BulkAddRecommendedRequest(BaseModel):
    source: str = "collection"
    only_owned: Optional[bool] = True
    respect_ratios: Optional[bool] = False
    types: Optional[list[str]] = None
    roles: Optional[list[str]] = None

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
    card_type: str = ""
    roles: list[str] = []
    source: str = "collection"
    quantity: int = 1
    image_url: str = ""
    owned_qty: int = 0
    is_proxy: bool = False

class DeckGenV3Request(BaseModel):
    commander_name: str = ""
    strategy: str = ""
    target_bracket: int = 3
    budget_usd: Optional[float] = None
    budget_mode: str = "total"
    omit_cards: list[str] = []
    use_collection: bool = True
    run_substitution: bool = True
    model: Optional[str] = None
    deck_name: Optional[str] = ""

class DeckGenV3SubstituteRequest(BaseModel):
    card_name: str
    substitute_name: str


# ══════════════════════════════════════════════════════════════
# Collection Database
# ══════════════════════════════════════════════════════════════

COLLECTION_DB_PATH = Path(__file__).parent.parent / "collection.db"
_db_local = threading.local()


def _get_db_conn() -> sqlite3.Connection:
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        conn = sqlite3.connect(str(COLLECTION_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _db_local.conn = conn
    return _db_local.conn


def init_collection_db():
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


# ══════════════════════════════════════════════════════════════
# Collection Utility Helpers
# ══════════════════════════════════════════════════════════════

_JSON_FIELDS = ("category", "color_identity", "subtypes", "keywords")
VALID_SORT_FIELDS = {"name", "cmc", "tcg_price", "salt_score", "category", "color_identity", "quantity", "type_line", "finish", "rarity", "set_code", "power", "toughness", "edhrec_rank"}


def _row_to_dict(row) -> dict:
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
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _add_image_url(card: dict) -> dict:
    scryfall_id = card.get("scryfall_id", "")
    if scryfall_id:
        card["imageUrl"] = f"https://api.scryfall.com/cards/{scryfall_id}?format=image&version=normal"
    else:
        card["imageUrl"] = None
    for key in list(card.keys()):
        if "_" in key:
            camel = _snake_to_camel(key)
            if camel not in card:
                card[camel] = card[key]
    return card


def _build_collection_filters(
    q=None, colors=None, types=None, isLegendary=None, isBasic=None,
    isGameChanger=None, highSalt=None, finish=None, cmcMin=None, cmcMax=None,
    priceMin=None, priceMax=None, category=None, rarity=None, setCode=None,
    powerMin=None, powerMax=None, toughMin=None, toughMax=None, keyword=None,
    edhrecMin=None, edhrecMax=None, qtyMin=None, qtyMax=None,
) -> tuple:
    conditions = []
    params = []
    if q:
        like_q = f"%{q}%"
        conditions.append("(name LIKE ? OR type_line LIKE ? OR oracle_text LIKE ?)")
        params.extend([like_q, like_q, like_q])
    if colors:
        for color in [c.strip().upper() for c in colors.split(",") if c.strip()]:
            conditions.append("color_identity LIKE ?")
            params.append(f'%"{color}"%')
    if types:
        tc = []
        for t in [t.strip() for t in types.split(",") if t.strip()]:
            tc.append("type_line LIKE ?")
            params.append(f"%{t}%")
        if tc:
            conditions.append(f"({' OR '.join(tc)})")
    if isLegendary is not None:
        conditions.append("is_legendary = ?"); params.append(1 if isLegendary else 0)
    if isBasic is not None:
        conditions.append("is_basic = ?"); params.append(1 if isBasic else 0)
    if isGameChanger is not None:
        conditions.append("is_game_changer = ?"); params.append(1 if isGameChanger else 0)
    if highSalt:
        conditions.append("salt_score > 2.0")
    if finish:
        conditions.append("finish = ?"); params.append(finish.upper())
    if cmcMin is not None:
        conditions.append("cmc >= ?"); params.append(cmcMin)
    if cmcMax is not None:
        conditions.append("cmc <= ?"); params.append(cmcMax)
    if priceMin is not None:
        conditions.append("tcg_price >= ?"); params.append(priceMin)
    if priceMax is not None:
        conditions.append("tcg_price <= ?"); params.append(priceMax)
    if category:
        cc = []
        for c in [c.strip() for c in category.split(",") if c.strip()]:
            cc.append("category LIKE ?"); params.append(f'%"{c}"%')
        if cc:
            conditions.append(f"({' OR '.join(cc)})")
    if rarity:
        rl = [r.strip().lower() for r in rarity.split(",") if r.strip()]
        if rl:
            conditions.append(f"LOWER(rarity) IN ({','.join(['?']*len(rl))})"); params.extend(rl)
    if setCode:
        sl = [s.strip().upper() for s in setCode.split(",") if s.strip()]
        if sl:
            conditions.append(f"UPPER(set_code) IN ({','.join(['?']*len(sl))})"); params.extend(sl)
    if powerMin is not None:
        conditions.append("CAST(power AS REAL) >= ?"); params.append(float(powerMin))
    if powerMax is not None:
        conditions.append("CAST(power AS REAL) <= ?"); params.append(float(powerMax))
    if toughMin is not None:
        conditions.append("CAST(toughness AS REAL) >= ?"); params.append(float(toughMin))
    if toughMax is not None:
        conditions.append("CAST(toughness AS REAL) <= ?"); params.append(float(toughMax))
    if keyword:
        for kw in [k.strip() for k in keyword.split(",") if k.strip()]:
            conditions.append("keywords LIKE ?"); params.append(f"%{kw}%")
    if edhrecMin is not None:
        conditions.append("edhrec_rank >= ?"); params.append(edhrecMin)
    if edhrecMax is not None:
        conditions.append("edhrec_rank <= ?"); params.append(edhrecMax)
    if qtyMin is not None:
        conditions.append("quantity >= ?"); params.append(qtyMin)
    if qtyMax is not None:
        conditions.append("quantity <= ?"); params.append(qtyMax)
    where_str = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_str, params


# ══════════════════════════════════════════════════════════════
# Card Role Detection
# ══════════════════════════════════════════════════════════════

def _detect_card_roles(oracle_text: str, type_line: str, keywords) -> list:
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

    if ("add {" in ot or "add one mana" in ot
            or ("search your library for a" in ot and "land" in ot)
            or "treasure token" in ot or "add mana" in ot):
        roles.append("Ramp")
    if ("draw a card" in ot or "draw cards" in ot or "draws a card" in ot
            or "draw two cards" in ot or "draw three cards" in ot
            or re.search(r"draw \d+ cards?", ot)
            or ("whenever" in ot and "draw" in ot)):
        roles.append("Draw")
    if ("destroy target" in ot or "exile target" in ot
            or re.search(r"deals? \d+ damage to (target|any target)", ot)
            or re.search(r"deals? x damage to (target|any target)", ot)
            or "target creature gets -" in ot or "fights target" in ot):
        roles.append("Removal")
    if ("destroy all" in ot or "exile all" in ot
            or re.search(r"all creatures get -\d+/-\d+", ot)
            or re.search(r"each creature gets -\d+/-\d+", ot)
            or ("deals" in ot and "to each creature" in ot)):
        roles.append("Board Wipe")
    if (re.search(r"creatures? you control get \+", ot)
            or re.search(r"creatures? you control have", ot)
            or re.search(r"other creatures? you control get \+", ot)
            or re.search(r"each creature you control gets? \+", ot)):
        roles.append("Anthem")
    if ("hexproof" in ot or "hexproof" in kw or "indestructible" in ot
            or "indestructible" in kw or "shroud" in ot or "shroud" in kw
            or "ward" in ot or "ward" in kw or "protection from" in ot
            or "can't be the target" in ot):
        roles.append("Protection")
    if "search your library" in ot:
        roles.append("Tutor")
    if "counter target" in ot:
        roles.append("Counter")
    if re.search(r"create[sd]? .*token", ot) or "creature token" in ot:
        roles.append("Token")
    if ("sacrifice a " in ot or "sacrifice another" in ot
            or ("when" in ot and "sacrifice" in ot and "dies" not in ot)
            or "each player sacrifices" in ot):
        roles.append("Sacrifice")
    if (("return" in ot and "from your graveyard" in ot)
            or ("return" in ot and "from a graveyard" in ot)
            or ("put" in ot and "from your graveyard" in ot and "onto the battlefield" in ot)
            or ("put" in ot and "from a graveyard" in ot and "onto the battlefield" in ot)):
        roles.append("Recursion")
    if (("graveyard" in ot and ("mill" in ot or ("put" in ot and "into" in ot and "graveyard" in ot)))
            or "mill" in kw):
        roles.append("Graveyard")
    if ("gain" in ot and "life" in ot) or "lifelink" in ot or "lifelink" in kw:
        roles.append("Lifegain")
    if (re.search(r"deals? \d+ damage to (each|any|target) (opponent|player)", ot)
            or ("each opponent loses" in ot and "life" in ot)
            or "deals damage to each opponent" in ot):
        roles.append("Burn")
    if ("can't cast" in ot or "can't attack" in ot or "can't activate" in ot
            or ("enters the battlefield tapped" in ot and "opponents" in ot)
            or "each player can't" in ot or "players can't" in ot
            or ("cost {" in ot and "more to cast" in ot)):
        roles.append("Stax")
    if ("flying" in kw or "trample" in kw or "menace" in kw or "shadow" in kw
            or "fear" in kw or "intimidate" in kw
            or "can't be blocked" in ot or "unblockable" in ot):
        roles.append("Evasion")
    if ("you win the game" in ot or "extra turn" in ot or "infinite" in ot
            or "loses the game" in ot
            or ("damage equal to" in ot and ("number" in ot or "total" in ot))):
        roles.append("Finisher")
    if ("untap all" in ot or ("copy" in ot and "spell" in ot)
            or "take an extra" in ot
            or ("double" in ot and ("damage" in ot or "counters" in ot or "tokens" in ot))):
        roles.append("Combo")
    return roles


# ══════════════════════════════════════════════════════════════
# Deck Helpers
# ══════════════════════════════════════════════════════════════

_TYPE_PRIORITY = ["Land", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Creature"]
_TYPE_TARGETS = {
    "Land":         [36, 38],
    "Instant":      [9,  11],
    "Sorcery":      [7,  9],
    "Artifact":     [9,  11],
    "Creature":     [20, 30],
    "Enchantment":  [5,  10],
    "Planeswalker": [0,  5],
}


def _classify_card_type(type_line: str) -> str:
    tl = type_line or ""
    for t in _TYPE_PRIORITY:
        if t in tl:
            return t
    return "Other"


def _get_deck_or_404(deck_id: int):
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
    conn = _get_db_conn()
    rows = conn.execute("""
        SELECT dc.id, dc.scryfall_id, dc.card_name, dc.quantity, dc.is_commander, dc.role_tag,
               ce.type_line, ce.oracle_text, ce.keywords, ce.cmc, ce.color_identity
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, oracle_text, keywords, cmc, color_identity
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
    """, (deck_id,)).fetchall()

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
        if card_type != "Land":
            cmc_int = int(cmc)
            if cmc_int >= 6:
                mana_curve["6+"] += qty
            else:
                mana_curve[cmc_int] = mana_curve.get(cmc_int, 0) + qty
        try:
            ci = json.loads(col_id_raw) if isinstance(col_id_raw, str) else col_id_raw
        except Exception:
            ci = []
        for c in ci:
            if c in color_pips:
                color_pips[c] += qty
        card_roles = _detect_card_roles(oracle_text, type_line, keywords)
        for role in card_roles:
            if role in roles_count:
                roles_count[role] += qty

    deltas = {}
    for t, (lo, hi) in _TYPE_TARGETS.items():
        mid = (lo + hi) / 2
        deltas[t] = round(counts_by_type.get(t, 0) - mid, 1)

    return {
        "counts_by_type": counts_by_type,
        "targets": _TYPE_TARGETS,
        "deltas": deltas,
        "mana_curve": mana_curve,
        "color_pips": color_pips,
        "total_cards": total_cards,
        "roles": roles_count,
    }


def _check_ratio_limit(deck_id: int, card_type: str, count_to_add: int = 1) -> bool:
    analysis = _compute_deck_analysis(deck_id)
    current = analysis["counts_by_type"].get(card_type, 0)
    target_max = _TYPE_TARGETS.get(card_type, [0, 9999])[1]
    return (current + count_to_add) <= target_max


# ══════════════════════════════════════════════════════════════
# Scryfall Cache
# ══════════════════════════════════════════════════════════════

SCRYFALL_CACHE_DB_PATH = Path(__file__).parent.parent / "scryfall_cache.db"
SCRYFALL_CACHE_TTL_SECONDS = int(os.environ.get("SCRYFALL_CACHE_TTL", 7 * 24 * 3600))

_API_HEADERS = {"User-Agent": "CommanderAILab/3.0", "Accept": "application/json"}


class _ScryfallCache:
    def __init__(self, db_path: Path = None, ttl_seconds: int = None):
        self._db_path = db_path or SCRYFALL_CACHE_DB_PATH
        self._ttl = ttl_seconds or SCRYFALL_CACHE_TTL_SECONDS
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._hits = 0
        self._misses = 0
        self._init_db()

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

    def get(self, name: str, set_code: str = "", collector_number: str = "") -> Optional[dict]:
        key = self._make_key(name, set_code, collector_number)
        with self._lock:
            row = self._conn.execute(
                "SELECT json_blob, fetched_at FROM scryfall_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if not row:
            self._misses += 1; return None
        try:
            fetched = datetime.fromisoformat(row[1])
            if (datetime.utcnow() - fetched).total_seconds() > self._ttl:
                self._misses += 1; return None
        except (ValueError, TypeError):
            self._misses += 1; return None
        self._hits += 1
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            self._misses += 1; return None

    def put(self, name: str, set_code: str, collector_number: str, card_data: dict):
        key = self._make_key(name, set_code, collector_number)
        blob = json.dumps(card_data, separators=(",", ":"))
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO scryfall_cache (cache_key, json_blob, fetched_at) VALUES (?, ?, datetime('now'))",
                (key, blob),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM scryfall_cache").fetchone()[0]
            oldest = self._conn.execute("SELECT MIN(fetched_at) FROM scryfall_cache").fetchone()
            newest = self._conn.execute("SELECT MAX(fetched_at) FROM scryfall_cache").fetchone()
            db_size = os.path.getsize(str(self._db_path)) if self._db_path.exists() else 0
        return {
            "total_entries": total,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(self._hits + self._misses, 1) * 100, 1),
            "ttl_seconds": self._ttl,
            "ttl_days": round(self._ttl / 86400, 1),
            "oldest_entry": oldest[0] if oldest else None,
            "newest_entry": newest[0] if newest else None,
            "db_size_kb": round(db_size / 1024, 1),
            "db_path": str(self._db_path),
        }

    def clear(self) -> int:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM scryfall_cache").fetchone()[0]
            self._conn.execute("DELETE FROM scryfall_cache")
            self._conn.commit()
            self._conn.execute("VACUUM")
            self._hits = 0; self._misses = 0
        return count

    def evict_expired(self) -> int:
        cutoff = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "DELETE FROM scryfall_cache WHERE (julianday(?) - julianday(fetched_at)) * 86400 > ?",
                (cutoff, self._ttl),
            )
            deleted = self._conn.total_changes
            self._conn.commit()
        return deleted


_scryfall_cache = _ScryfallCache()
_scryfall_lock = threading.Lock()
_scryfall_last_call = 0.0


def _scryfall_rate_limit():
    global _scryfall_last_call
    with _scryfall_lock:
        now = time.monotonic()
        elapsed = now - _scryfall_last_call
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        _scryfall_last_call = time.monotonic()


def _fetch_scryfall_api(name: str, set_code: str = "", collector_number: str = "") -> dict:
    from urllib.parse import quote
    cached = _scryfall_cache.get(name, set_code, collector_number)
    if cached is not None:
        return cached
    card_data = None
    last_error = ""
    if set_code and collector_number:
        _scryfall_rate_limit()
        try:
            url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
            with urlopen(Request(url, headers=_API_HEADERS), timeout=10) as resp:
                card_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = str(e); card_data = None
    if not card_data:
        _scryfall_rate_limit()
        try:
            url = f"https://api.scryfall.com/cards/named?exact={quote(name)}"
            with urlopen(Request(url, headers=_API_HEADERS), timeout=10) as resp:
                card_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = str(e)
            return {"_error": f"Scryfall lookup failed for '{name}': {last_error}"}
    if not card_data or card_data.get("object") == "error":
        err_detail = card_data.get("details", "unknown error") if card_data else last_error
        return {"_error": f"Scryfall returned error for '{name}': {err_detail}"}
    _scryfall_cache.put(name, set_code, collector_number, card_data)
    resolved_name = card_data.get("name", "")
    if resolved_name and resolved_name.lower() != name.strip().lower():
        _scryfall_cache.put(resolved_name, set_code, collector_number, card_data)
    return card_data


def _enrich_from_scryfall(name: str, set_code: str = "", collector_number: str = "") -> dict:
    card_data = _fetch_scryfall_api(name, set_code, collector_number)
    if not card_data or "_error" in card_data:
        return card_data or {}
    type_line = card_data.get("type_line", "")
    color_identity = card_data.get("color_identity", [])
    keywords = card_data.get("keywords", [])
    subtypes = []
    for sep in [" \u2014 ", " - "]:
        if sep in type_line:
            subtypes = [s.strip() for s in type_line.split(sep, 1)[1].split() if s.strip()]
            break
    is_legendary = 1 if "Legendary" in type_line else 0
    is_basic = 1 if "Basic" in type_line else 0
    prices = card_data.get("prices", {})
    try:
        tcg_price = float(prices.get("usd") or prices.get("usd_foil") or "0") or 0.0
    except (ValueError, TypeError):
        tcg_price = 0.0
    oracle_text = card_data.get("oracle_text", "")
    if not oracle_text and card_data.get("card_faces"):
        oracle_text = "\n//\n".join(f.get("oracle_text", "") for f in card_data["card_faces"] if f.get("oracle_text"))
    power = card_data.get("power", "")
    toughness = card_data.get("toughness", "")
    if not power and card_data.get("card_faces"):
        power = card_data["card_faces"][0].get("power", "")
        toughness = card_data["card_faces"][0].get("toughness", "")
    mana_cost = card_data.get("mana_cost", "")
    if not mana_cost and card_data.get("card_faces"):
        mana_cost = card_data["card_faces"][0].get("mana_cost", "")
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


# ══════════════════════════════════════════════════════════════
# Import Helpers
# ══════════════════════════════════════════════════════════════

def _http_get(url: str) -> str:
    with urlopen(Request(url, headers=_API_HEADERS), timeout=30) as resp:
        return resp.read().decode("utf-8")


def _to_edhrec_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[',.]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _fetch_archidekt_deck(deck_id: str) -> dict:
    url = f"https://archidekt.com/api/decks/{deck_id}/"
    data = json.loads(_http_get(url))
    profile = {
        "name": data.get("name", f"Archidekt {deck_id}"),
        "commander": None, "source": "Archidekt",
        "sourceUrl": f"https://archidekt.com/decks/{deck_id}",
        "commanders": {}, "mainboard": {}, "colorIdentity": [], "totalCards": 0,
    }
    for card_entry in data.get("cards", []):
        qty = card_entry.get("quantity", 1)
        oracle = card_entry.get("card", {}).get("oracleCard", {})
        card_name = oracle.get("name", "Unknown")
        is_commander = any(c.lower() == "commander" for c in card_entry.get("categories", []))
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
    slug = _to_edhrec_slug(commander_name)
    url = f"https://json.edhrec.com/pages/average-decks/{slug}.json"
    data = json.loads(_http_get(url))
    container = data.get("container", {})
    json_dict = container.get("json_dict", {})
    card_info = json_dict.get("card", {})
    real_name = card_info.get("name", commander_name.title())
    profile = {
        "name": f"{real_name} — EDHREC Average",
        "commander": real_name, "source": "EDHREC Average",
        "sourceUrl": f"https://edhrec.com/average-decks/{slug}",
        "commanders": {real_name: 1}, "mainboard": {},
        "colorIdentity": card_info.get("color_identity", []),
        "sampleSize": data.get("num_decks_avg"), "totalCards": 0,
    }
    for cl in json_dict.get("cardlists", []):
        for cv in cl.get("cardviews", []):
            card_name = cv.get("name", "")
            if card_name:
                profile["mainboard"][card_name] = 1
    archidekt_data = data.get("archidekt", [])
    if archidekt_data:
        basic_names = []
        for cl in json_dict.get("cardlists", []):
            if cl.get("tag") == "basics":
                for cv in cl.get("cardviews", []):
                    basic_names.append(cv.get("name", ""))
        basic_quantities = [e["q"] for e in archidekt_data if e.get("q", 1) > 1]
        for i, name in enumerate(basic_names):
            if i < len(basic_quantities):
                profile["mainboard"][name] = basic_quantities[i]
    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    return profile


def _import_from_url(url: str) -> dict:
    url = url.strip()
    if "archidekt.com/decks/" in url:
        m = re.search(r"/decks/(\d+)", url)
        if not m:
            raise ValueError("Could not parse Archidekt deck ID from URL")
        return _fetch_archidekt_deck(m.group(1))
    if "edhrec.com/average-decks/" in url:
        slug = re.search(r"/average-decks/([^/?#]+)", url).group(1)
        return _fetch_edhrec_average(slug.replace("-", " "))
    if "edhrec.com/commanders/" in url:
        slug = re.search(r"/commanders/([^/?#]+)", url).group(1)
        return _fetch_edhrec_average(slug.replace("-", " "))
    raise ValueError(f"Unsupported URL: {url}. Supported: archidekt.com/decks/..., edhrec.com/average-decks/..., edhrec.com/commanders/...")


def _parse_text_decklist(text: str, commander_override: str = None) -> dict:
    profile = {
        "name": "Text Import", "commander": None, "source": "Text Import",
        "sourceUrl": None, "commanders": {}, "mainboard": {}, "totalCards": 0,
    }
    section = "main"
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if line.lower().startswith("commander") or line == "[Commander]":
            section = "commander"; continue
        if line.lower().startswith("main") or line.lower().startswith("deck") or line == "[Main]":
            section = "main"; continue
        if line.lower().startswith("sideboard") or line == "[Sideboard]":
            section = "sideboard"; continue
        clean = re.sub(r"\(\w+\)\s*\d*$", "", line).strip()
        clean = re.sub(r"\s*\*.*$", "", clean).strip()
        m = re.match(r"^(\d+)x?\s+(.+)$", clean)
        qty, card_name = (int(m.group(1)), m.group(2).strip()) if m else (1, clean)
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
    lines = ["[metadata]", f"Name={profile.get('name', 'Imported Deck')}", "", "[Commander]"]
    for name, qty in profile.get("commanders", {}).items():
        lines.append(f"{qty} {name}")
    lines += ["", "[Main]"]
    for name, qty in profile.get("mainboard", {}).items():
        lines.append(f"{qty} {name}")
    content = "\n".join(lines)
    safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", profile.get("name", "imported")).replace(" ", "_").strip()
    if not safe_name:
        safe_name = "imported_deck"
    save_dir = CFG.forge_decks_dir
    if not save_dir or not os.path.isdir(save_dir):
        save_dir = os.path.join(Path(__file__).parent.parent, "imported-decks")
        os.makedirs(save_dir, exist_ok=True)
    out_path = Path(save_dir) / f"{safe_name}.dck"
    out_path.write_text(content, encoding="utf-8")
    log_collect.info(f"  Saved .dck: {out_path}")
    return out_path


# EDHREC in-memory cache
_edhrec_cache: dict = {}
_EDHREC_CACHE_TTL = 3600


def _edhrec_cache_get(key: str):
    entry = _edhrec_cache.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > _EDHREC_CACHE_TTL:
        del _edhrec_cache[key]
        return None
    return entry["data"]


def _edhrec_cache_set(key: str, data):
    _edhrec_cache[key] = {"data": data, "ts": time.time()}


# ══════════════════════════════════════════════════════════════
# Collection Import Helpers
# ══════════════════════════════════════════════════════════════

def _parse_finish(raw: str) -> str:
    if not raw:
        return "NORMAL"
    r = raw.strip().lower()
    if r in ("etched", "foil etched", "foil_etched", "etched foil"):
        return "ETCHED"
    if r in ("yes", "foil", "true", "1"):
        return "FOIL"
    return "NORMAL"


def _parse_text_line(line: str) -> dict:
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return {}
    result = {"name": "", "quantity": 1, "set_code": "", "collector_number": ""}
    qty_match = re.match(r"^(\d+)x?\s+", line)
    if qty_match:
        result["quantity"] = int(qty_match.group(1))
        line = line[qty_match.end():]
    bracket_match = re.search(r"\[([A-Za-z0-9]+):(\S+)\]\s*$", line)
    if bracket_match:
        result["set_code"] = bracket_match.group(1).lower()
        result["collector_number"] = bracket_match.group(2)
        result["name"] = line[:bracket_match.start()].strip()
        return result
    paren_coll_match = re.search(r"\(([A-Za-z0-9]+)\)\s+(\S+)\s*$", line)
    if paren_coll_match:
        result["set_code"] = paren_coll_match.group(1).lower()
        result["collector_number"] = paren_coll_match.group(2)
        result["name"] = line[:paren_coll_match.start()].strip()
        return result
    paren_match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", line)
    if paren_match:
        result["set_code"] = paren_match.group(1).lower()
        result["name"] = line[:paren_match.start()].strip()
        return result
    result["name"] = line.strip()
    return result


def _auto_infer_mapping(headers: list) -> dict:
    mapping = {}
    header_lower = {h: h.lower().strip() for h in headers}
    field_patterns = {
        "name": ["name", "card name", "card_name", "cardname", "title"],
        "quantity": ["quantity", "qty", "count", "amount", "number", "#"],
        "set_code": ["set", "set code", "set_code", "edition", "set_name", "edition code"],
        "collector_number": ["collector number", "collector_number", "collectornumber", "col #", "col#", "number", "card number"],
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
    rows = []
    if (source or "").upper() == "TEXT":
        for line in content.splitlines():
            parsed = _parse_text_line(line)
            if parsed.get("name"):
                rows.append(parsed)
        return rows
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    col_map = {h: (mapping.get(h, "") if mapping else "") for h in headers}
    if not mapping:
        col_map = _auto_infer_mapping(headers)
    col_map = {h: (v.lower() if isinstance(v, str) else v) for h, v in col_map.items()}
    for csv_row in reader:
        row = {"name": "", "quantity": 1, "set_code": "", "collector_number": "", "finish": "NORMAL",
               "condition": "", "language": "", "notes": "", "tags": ""}
        for header, field in col_map.items():
            val = csv_row.get(header, "").strip()
            if not val or field == "ignore" or not field:
                continue
            if field == "name":
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
            elif field in ("condition", "language", "notes", "tags"):
                row[field] = val
        if row["name"]:
            rows.append(row)
    return rows


# ══════════════════════════════════════════════════════════════
# Precon Helpers
# ══════════════════════════════════════════════════════════════

PRECON_DIR = Path(__file__).parent.parent / "precon-decks"
PRECON_INDEX: list[dict] = []
GITHUB_PRECON_URL = (
    "https://raw.githubusercontent.com/taw/magic-preconstructed-decks-data/"
    "master/decks_v2.json"
)
PRECON_CACHE_HOURS = 168


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


def _sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = safe.replace(' ', '_').replace("'", '').replace('!', '')
    return re.sub(r'_+', '_', safe).strip('_')


def _deck_to_dck(deck_data: dict) -> str:
    lines = ["[metadata]", f"Name={deck_data['name']}"]
    commanders = deck_data.get('commander', [])
    if commanders:
        lines.append("[Commander]")
        for card in commanders:
            lines.append(f"{card.get('count', 1)} {card['name']}")
    cards = deck_data.get('cards', [])
    if cards:
        lines.append("[Main]")
        for card in cards:
            lines.append(f"{card.get('count', 1)} {card['name']}")
    sideboard = deck_data.get('sideboard', [])
    if sideboard:
        lines.append("[Sideboard]")
        for card in sideboard:
            lines.append(f"{card.get('count', 1)} {card['name']}")
    return "\n".join(lines) + "\n"


def download_precon_database(force: bool = False) -> dict:
    global PRECON_INDEX
    idx_path = PRECON_DIR / "precon-index.json"
    if not force and idx_path.exists():
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if len(existing) > 50:
                age_hours = (time.time() - idx_path.stat().st_mtime) / 3600
                if age_hours < PRECON_CACHE_HOURS:
                    log.info(f"  Precons:      {len(existing)} decks cached ({age_hours:.0f}h old)")
                    PRECON_INDEX = existing
                    return {"downloaded": 0, "skipped": True, "total": len(existing), "error": None}
        except Exception:
            pass
    log.info("  Precons:      Downloading full precon database from GitHub...")
    try:
        req = Request(GITHUB_PRECON_URL, headers={"User-Agent": "CommanderAILab/3.0"})
        with urlopen(req, timeout=120) as resp:
            all_decks = json.loads(resp.read())
    except Exception as e:
        msg = f"Failed to download precon database: {e}"
        log.error(f"  Precons:      ERROR — {msg}")
        if idx_path.exists():
            load_precon_index()
        return {"downloaded": 0, "skipped": False, "error": msg}
    commander_decks = [
        d for d in all_decks
        if d.get('type') == 'Commander Deck' and (d.get('format') or '').lower() == 'commander'
    ]
    log.info(f"  Precons:      Found {len(commander_decks)} Commander precon decks")
    PRECON_DIR.mkdir(parents=True, exist_ok=True)
    name_counts = Counter(_sanitize_filename(d['name']) for d in commander_decks)
    dup_names = {n for n, c in name_counts.items() if c > 1}
    index = []
    written = 0
    for deck in sorted(commander_decks, key=lambda d: (d.get('release_date', ''), d.get('name', ''))):
        safe_name = _sanitize_filename(deck['name'])
        if safe_name in dup_names:
            sc = (deck.get('set_code') or 'unk').upper()
            safe_name = f"{safe_name}_{sc}"
        file_name = f"{safe_name}.dck"
        dck_path = PRECON_DIR / file_name
        commanders = deck.get('commander', [])
        cmdr_names = [c['name'] for c in commanders] if commanders else []
        total_cards = sum(c.get('count', 1) for c in deck.get('cards', [])) + sum(c.get('count', 1) for c in commanders)
        with open(dck_path, "w", encoding="utf-8") as f:
            f.write(_deck_to_dck(deck))
        written += 1
        release = deck.get('release_date', '')
        year = int(release[:4]) if release and len(release) >= 4 else 0
        index.append({
            "name": deck['name'],
            "commander": cmdr_names[0] if cmdr_names else "Unknown",
            "commanders": cmdr_names,
            "colors": [],
            "set": deck.get('set_name', ''),
            "setCode": deck.get('set_code', ''),
            "year": year,
            "releaseDate": release,
            "theme": "",
            "fileName": file_name,
            "cardCount": total_cards,
        })
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    PRECON_INDEX = index
    log.info(f"  Precons:      {written} .dck files written, index saved")
    return {"downloaded": written, "skipped": False, "total": written, "error": None}


# ══════════════════════════════════════════════════════════════
# AI Profiles
# ══════════════════════════════════════════════════════════════

AI_PROFILES = {
    "default":  {"name": "default",  "description": "Balanced \u2014 Forge's default AI behavior",       "aggression": 0.5, "cardAdvantage": 0.5, "removalPriority": 0.5, "boardPresence": 0.5, "comboPriority": 0.3, "patience": 0.5},
    "aggro":    {"name": "aggro",    "description": "Aggressive \u2014 attacks early, prioritizes damage", "aggression": 0.9, "cardAdvantage": 0.3, "removalPriority": 0.3, "boardPresence": 0.8, "comboPriority": 0.1, "patience": 0.1},
    "control":  {"name": "control",  "description": "Control \u2014 defensive, removal-heavy, card advantage", "aggression": 0.2, "cardAdvantage": 0.9, "removalPriority": 0.9, "boardPresence": 0.3, "comboPriority": 0.4, "patience": 0.9},
    "combo":    {"name": "combo",    "description": "Combo \u2014 ramps, digs for pieces, assembles combos",  "aggression": 0.2, "cardAdvantage": 0.8, "removalPriority": 0.4, "boardPresence": 0.3, "comboPriority": 0.95,"patience": 0.7},
    "midrange": {"name": "midrange", "description": "Midrange \u2014 flexible, strong board presence, value-oriented", "aggression": 0.5, "cardAdvantage": 0.6, "removalPriority": 0.6, "boardPresence": 0.7, "comboPriority": 0.3, "patience": 0.5},
}


# ══════════════════════════════════════════════════════════════
# Java / Sim Helpers
# ══════════════════════════════════════════════════════════════

_ml_logging_enabled = False


def _find_java17() -> str:
    search_dirs = [r'C:\Program Files\Eclipse Adoptium', r'C:\Program Files\Java']
    for d in search_dirs:
        if os.path.isdir(d):
            for child in os.listdir(d):
                if child.startswith('jdk-17'):
                    candidate = os.path.join(d, child, 'bin', 'java.exe')
                    if os.path.isfile(candidate):
                        return candidate
    return 'java'


_JAVA17_PATH = None


def get_java17() -> str:
    global _JAVA17_PATH
    if _JAVA17_PATH is None:
        _JAVA17_PATH = _find_java17()
    return _JAVA17_PATH


def build_java_command(
    decks: list[str], num_games: int, threads: int, seed: Optional[int],
    clock: int, output_path: str, use_learned_policy: bool = False,
    policy_server: str = "http://localhost:8080", policy_style: str = "midrange",
    policy_greedy: bool = False, ai_simplified: bool = False,
    ai_think_time_ms: int = -1, max_queue_depth: int = -1,
) -> list[str]:
    java17 = get_java17()
    cmd = [java17, "-jar", CFG.lab_jar, "--forge-jar", CFG.forge_jar, "--forge-dir", CFG.forge_dir]
    for i, deck in enumerate(decks):
        cmd.extend([f"--deck{i+1}", deck])
    cmd += ["--games", str(num_games), "--threads", str(threads), "--clock", str(clock), "--output", output_path]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    if _ml_logging_enabled:
        cmd.append("--ml-log")
    if use_learned_policy:
        cmd += ["--learned-policy", "--policy-server", policy_server, "--policy-style", policy_style]
        if policy_greedy:
            cmd.append("--policy-greedy")
    if ai_simplified:
        cmd.append("--ai-simplified")
    if ai_think_time_ms > 0:
        cmd.extend(["--ai-think-time", str(ai_think_time_ms)])
    if max_queue_depth > 0:
        cmd.extend(["--max-queue", str(max_queue_depth)])
    return cmd


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
                section = line[1:-1]; continue
            if line.startswith("Name="):
                deck_name = line[5:].strip(); continue
            m = re.match(r"^(\d+)\s+(.+?)(?:\|(.+))?$", line)
            if m:
                qty = int(m.group(1))
                name = m.group(2).strip()
                set_code = m.group(3).strip() if m.group(3) else ""
                cards.append({"quantity": qty, "name": name, "set": set_code, "section": section, "is_commander": 1 if section == "Commander" else 0})
                if section == "Commander":
                    commander = name
    total = sum(c["quantity"] for c in cards)
    return {"deckName": deck_name, "commanderName": commander, "totalCards": total, "cardCount": len(cards), "cards": cards[:200]}


def _load_deck_cards_by_name(deck_name: str) -> list[dict]:
    try:
        conn = _get_db_conn()
        row = conn.execute("SELECT id, commander_name FROM decks WHERE name = ? COLLATE NOCASE", (deck_name,)).fetchone()
        if row:
            deck_id = row["id"]
            db_commander_name = row["commander_name"] or ""
            cards = conn.execute("""
                SELECT dc.card_name, dc.quantity, dc.is_commander,
                       ce.type_line, ce.cmc, ce.power, ce.toughness,
                       ce.oracle_text, ce.keywords, ce.mana_cost, ce.color_identity
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
                if not is_cmdr and db_commander_name and r["card_name"].lower() == db_commander_name.lower():
                    is_cmdr = 1
                for _ in range(r["quantity"] or 1):
                    result.append({
                        'name': r["card_name"], 'type_line': r["type_line"] or '',
                        'cmc': r["cmc"] or 0, 'power': r["power"] or '',
                        'toughness': r["toughness"] or '', 'oracle_text': r["oracle_text"] or '',
                        'keywords': r["keywords"] or '', 'mana_cost': r["mana_cost"] or '',
                        'is_commander': is_cmdr, 'color_identity': r["color_identity"] or '',
                    })
            if result:
                return result
    except Exception as e:
        log_sim.error(f"DB lookup failed for '{deck_name}': {e}")
    if CFG.forge_decks_dir and os.path.isdir(CFG.forge_decks_dir):
        dck_path = Path(CFG.forge_decks_dir) / f"{deck_name}.dck"
        if dck_path.exists():
            cards = []
            current_section = None
            with open(dck_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    low = line.lower()
                    if low == '[commander]':
                        current_section = 'commander'; continue
                    elif low in ('[main]', '[deck]'):
                        current_section = 'main'; continue
                    elif line.startswith('['):
                        current_section = None; continue
                    if current_section and line:
                        parts = line.split(' ', 1)
                        if len(parts) == 2:
                            try:
                                qty = int(parts[0])
                                name = parts[1].strip()
                                for _ in range(qty):
                                    cards.append({'name': name, 'type_line': '', 'cmc': 0, 'is_commander': 1 if current_section == 'commander' else 0})
                            except ValueError:
                                pass
            if cards:
                return cards
    return []


def _get_deepseek_brain():
    """Lazily load the DeepSeek brain — returns None if not available."""
    try:
        import sys as _s, os as _o
        src_dir = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'src')
        if src_dir not in _s.path:
            _s.path.insert(0, src_dir)
        from commander_ai_lab.sim.deepseek_brain import get_brain
        return get_brain()
    except Exception:
        return None


async def run_batch_subprocess(
    state: BatchState, decks: list[str], num_games: int, threads: int,
    seed: Optional[int], clock: int, output_path: str,
    use_learned_policy: bool = False, policy_style: str = "midrange",
    policy_greedy: bool = False, ai_simplified: bool = False,
    ai_think_time_ms: int = -1, max_queue_depth: int = -1,
):
    try:
        policy_server = f"http://localhost:{CFG.port}"
        cmd = build_java_command(
            decks, num_games, threads, seed, clock, output_path,
            use_learned_policy=use_learned_policy, policy_server=policy_server,
            policy_style=policy_style, policy_greedy=policy_greedy,
            ai_simplified=ai_simplified, ai_think_time_ms=ai_think_time_ms,
            max_queue_depth=max_queue_depth,
        )
        log_batch.info(f"Starting batch {state.batch_id}: {' '.join(cmd[:6])}...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: _run_process_blocking(state, cmd))
    except Exception as e:
        state.error = str(e)
        state.running = False
        log_batch.error(f"Batch {state.batch_id} ERROR: {e}")


def _run_process_blocking(state: BatchState, cmd: list[str]):
    debug_log_path = Path(CFG.forge_dir).parent / "forge-sim-debug.log" if CFG.forge_dir else Path("forge-sim-debug.log")
    try:
        with open(debug_log_path, "a", encoding="utf-8") as dbg:
            dbg.write(f"\n{'='*60}\nBatch {state.batch_id} @ {datetime.now().isoformat()}\n")
            dbg.write(f"Command: {' '.join(cmd)}\nLab JAR: {CFG.lab_jar}\nForge JAR: {CFG.forge_jar}\n")
            dbg.write(f"Lab JAR exists: {os.path.exists(CFG.lab_jar)}\nForge JAR exists: {os.path.exists(CFG.forge_jar)}\n{'-'*60}\n")
    except Exception as e:
        log_batch.warning(f"Could not write debug log header: {e}")

    env = os.environ.copy()
    java17 = get_java17()
    if java17 != 'java':
        java17_bin = os.path.dirname(java17)
        env['JAVA_HOME'] = os.path.dirname(java17_bin)
        env['PATH'] = java17_bin + os.pathsep + env.get('PATH', '')

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, env=env)
        state.process = proc
        last_activity = [time.time()]

        def _watchdog():
            while proc.poll() is None:
                time.sleep(30)
                if time.time() - last_activity[0] > 300:
                    log_batch.warning('WATCHDOG: No output for 300s. Killing process.')
                    state.log_lines.append('[WATCHDOG] Process stalled. Killed.')
                    proc.kill(); return

        threading.Thread(target=_watchdog, daemon=True).start()

        all_output_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            last_activity[0] = time.time()
            state.log_lines.append(line)
            all_output_lines.append(line)
            if line.startswith("[Game "):
                try:
                    state.completed_games = int(line.split("]")[0].replace("[Game ", "").split("/")[0])
                except (ValueError, IndexError):
                    pass
            if '[PROGRESS]' in line or '[BATCH]' in line:
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

        try:
            with open(debug_log_path, "a", encoding="utf-8") as dbg:
                dbg.write(f"Exit code: {proc.returncode}\nTotal lines: {len(all_output_lines)}\nElapsed: {elapsed}ms\n-- FULL SUBPROCESS OUTPUT --\n")
                for ol in all_output_lines:
                    dbg.write(ol + "\n")
                dbg.write("-- END OUTPUT --\n\n")
        except Exception as e:
            log_batch.warning(f"Could not write debug log output: {e}")

        if proc.returncode != 0:
            if proc.returncode in (-9, 137):
                state.error = 'Forge process killed by watchdog (stalled). Check forge-sim-debug.log.'
            else:
                state.error = f'Java process exited with code {proc.returncode}. Check forge-sim-debug.log.'
        else:
            state.completed_games = state.total_games
            log_batch.info(f"Batch {state.batch_id} completed in {elapsed}ms")
            if state.result_path and os.path.exists(state.result_path):
                try:
                    from coach.report_generator import generate_single_deck_report
                    reports_dir = str(Path(__file__).parent.parent / "deck-reports")
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


def _run_deepseek_batch_thread(state: BatchState, deck_names: list[str], num_games: int, output_path: str):
    try:
        import sys as _s, os as _o, time as _t
        src_dir = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'src')
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

        deck_win_rates = {}
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
        deck_meta = {}
        for dn in deck_names:
            raw_cards = _load_deck_cards_by_name(dn)
            if not raw_cards:
                state.log_lines.append(f'[DeepSeek Batch] WARNING: Could not load deck "{dn}", skipping.')
                continue
            commander_name = ''
            color_identity_set = set()
            deck_objs = []
            for cd in raw_cards:
                c = Card(name=cd['name'])
                if cd.get('type_line'): c.type_line = cd['type_line']
                if cd.get('cmc'): c.cmc = float(cd['cmc'])
                if cd.get('power') and cd.get('toughness'):
                    c.power = str(cd['power']); c.toughness = str(cd['toughness']); c.pt = c.power + '/' + c.toughness
                if cd.get('oracle_text'): c.oracle_text = cd['oracle_text']
                if cd.get('mana_cost'): c.mana_cost = cd['mana_cost']
                if cd.get('keywords'):
                    kw = cd['keywords']
                    if isinstance(kw, str):
                        try: kw = json.loads(kw)
                        except Exception: kw = []
                    if isinstance(kw, list): c.keywords = kw
                if cd.get('is_commander'):
                    c.is_commander = True; commander_name = cd['name']
                ci_str = cd.get('color_identity', '')
                if ci_str:
                    try:
                        ci_parsed = json.loads(ci_str) if isinstance(ci_str, str) else ci_str
                        if isinstance(ci_parsed, list):
                            for color in ci_parsed: color_identity_set.add(color)
                    except Exception:
                        pass
                enrich_card(c)
                deck_objs.append(c)

            creature_count = sum(1 for c in deck_objs if c.is_creature())
            removal_count = sum(1 for c in deck_objs if c.is_removal)
            avg_cmc = sum(c.cmc or 0 for c in deck_objs if not c.is_land()) / max(sum(1 for c in deck_objs if not c.is_land()), 1)
            oracle_all = ' '.join((c.oracle_text or '').lower() for c in deck_objs)
            has_combo_text = any(kw in oracle_all for kw in ['you win the game', 'infinite', 'extra turn'])

            if has_combo_text: archetype = 'combo'
            elif creature_count >= 30 and avg_cmc <= 2.8: archetype = 'aggro'
            elif removal_count >= 10 or (creature_count <= 18 and avg_cmc >= 3.2): archetype = 'control'
            else: archetype = 'midrange'

            deck_meta[dn] = {'commander_name': commander_name, 'color_identity': sorted(list(color_identity_set)), 'archetype': archetype, 'win_rate': deck_win_rates.get(dn)}
            loaded_decks[dn] = deck_objs
            cmdr_info = f' (Commander: {commander_name})' if commander_name else ''
            wr_info = f' [History: {deck_win_rates[dn]:.0f}% WR]' if dn in deck_win_rates else ''
            state.log_lines.append(f'[DeepSeek Batch] Loaded deck "{dn}" ({len(deck_objs)} cards, {archetype}){cmdr_info}{wr_info}')

        if not loaded_decks:
            state.error = 'No decks could be loaded.'; state.running = False; return

        deck_list = list(loaded_decks.keys())
        games_per_deck = max(1, num_games // len(deck_list))
        total_games = games_per_deck * len(deck_list)
        state.total_games = total_games
        state.log_lines.append(f'[DeepSeek Batch] Running {games_per_deck} games per deck × {len(deck_list)} decks = {total_games} total')

        engine = DeepSeekGameEngine(brain=brain, ai_player_index=0, max_turns=25, record_log=True, ml_log=True)
        start_time = _t.time()
        all_deck_results = []
        completed = 0

        for deck_name in deck_list:
            deck_a = loaded_decks[deck_name]
            from commander_ai_lab.lab.experiments import _generate_training_deck
            deck_stats = {'deckName': deck_name, 'wins': 0, 'losses': 0, 'totalGames': games_per_deck,
                          'totalTurns': 0, 'totalDamageDealt': 0, 'totalDamageReceived': 0,
                          'totalSpellsCast': 0, 'totalCreaturesPlayed': 0, 'games': []}
            meta = deck_meta.get(deck_name, {})
            dk_archetype = meta.get('archetype', 'midrange')
            dk_commander = meta.get('commander_name', '')
            dk_colors = meta.get('color_identity', [])
            dk_win_rate = meta.get('win_rate')

            for g in range(games_per_deck):
                try:
                    deck_b = _generate_training_deck()
                    game_id = f'ds-{state.batch_id}-{deck_name[:12]}-g{g+1}'
                    result = engine.run(deck_a, deck_b, name_a=deck_name + ' (AI)', name_b='Training Opponent',
                                        game_id=game_id, archetype=dk_archetype, commander_name=dk_commander,
                                        color_identity=dk_colors, win_rate=dk_win_rate)
                    gd = result.to_dict(); gd['gameNumber'] = g + 1
                    deck_stats['games'].append(gd)
                    if result.winner == 0: deck_stats['wins'] += 1
                    else: deck_stats['losses'] += 1
                    deck_stats['totalTurns'] += result.turns
                    if result.player_a_stats:
                        deck_stats['totalDamageDealt'] += result.player_a_stats.damage_dealt
                        deck_stats['totalDamageReceived'] += result.player_a_stats.damage_received
                        deck_stats['totalSpellsCast'] += result.player_a_stats.spells_cast
                        deck_stats['totalCreaturesPlayed'] += result.player_a_stats.creatures_played
                    state.log_lines.append(f'[Game {completed + 1}/{total_games}] {deck_name} (AI-piloted) → {"WIN" if result.winner == 0 else "LOSS"} (turn {result.turns})')
                except Exception as ge:
                    state.log_lines.append(f'[Game {completed + 1}/{total_games}] ERROR: {ge}')
                    deck_stats['games'].append({'error': str(ge), 'gameNumber': g + 1})
                completed += 1; state.completed_games = completed

            n = deck_stats['totalGames']
            deck_stats['winRate'] = round(deck_stats['wins'] / n * 100, 1) if n > 0 else 0.0
            deck_stats['avgTurns'] = round(deck_stats['totalTurns'] / n, 1) if n > 0 else 0.0
            deck_stats['avgDamageDealt'] = round(deck_stats['totalDamageDealt'] / n, 1) if n > 0 else 0.0
            deck_stats['avgDamageReceived'] = round(deck_stats['totalDamageReceived'] / n, 1) if n > 0 else 0.0
            deck_stats['avgSpellsCast'] = round(deck_stats['totalSpellsCast'] / n, 1) if n > 0 else 0.0
            deck_stats['avgCreaturesPlayed'] = round(deck_stats['totalCreaturesPlayed'] / n, 1) if n > 0 else 0.0
            deck_stats['archetype'] = dk_archetype; deck_stats['commander'] = dk_commander
            deck_stats['colorIdentity'] = dk_colors
            if dk_win_rate is not None: deck_stats['priorWinRate'] = dk_win_rate
            all_deck_results.append(deck_stats)

        elapsed = _t.time() - start_time
        ds_stats = brain.get_stats() if brain else {}
        batch_result = {
            'metadata': {'batchId': state.batch_id, 'timestamp': datetime.now().isoformat(),
                         'completedGames': completed, 'threads': 1, 'elapsedMs': int(elapsed * 1000),
                         'engine': 'deepseek', 'model': brain.config.model if brain else 'unknown'},
            'decks': all_deck_results, 'deepseekStats': ds_stats,
        }

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

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(batch_result, f, indent=2, default=str)

        state.result_path = output_path
        state.elapsed_ms = int(elapsed * 1000)
        state.running = False
        state.completed_games = total_games
        state.log_lines.append(f'[DeepSeek Batch] Complete: {completed} games in {elapsed:.1f}s')
        for ds in all_deck_results:
            state.log_lines.append(f'  {ds["deckName"]}: {ds["wins"]}W-{ds["losses"]}L ({ds["winRate"]}% WR)')
        log_sim.info(f'Batch {state.batch_id} complete: {completed} games in {elapsed:.1f}s')

    except Exception as e:
        import traceback
        state.error = str(e); state.running = False
        state.log_lines.append(f'[DeepSeek Batch] FATAL: {e}')
        traceback.print_exc()
