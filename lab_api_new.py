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
)

# Route modules
from routes.collection import router as collection_router
from routes.deckbuilder import router as deckbuilder_router
from routes.precon import router as precon_router
from routes.import_routes import router as import_router
from routes.lab import router as lab_router


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


# ══════════════════════════════════════════════════════════════
# In-Memory State (used by remaining endpoints)
# ══════════════════════════════════════════════════════════════

active_batches: dict[str, BatchState] = {}

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
