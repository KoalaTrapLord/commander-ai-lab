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
# Import Helpers
# ══════════════════════════════════════════════════════════════

def _http_get(url: str) -> str:
    with urlopen(Request(url, headers=_API_HEADERS), timeout=30) as resp:
        return resp.read().decode("utf-8")


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
# AI Profiles (imported from models/state)
from models.state import AI_PROFILES


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
