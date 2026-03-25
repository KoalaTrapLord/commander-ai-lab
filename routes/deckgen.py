"""
routes/deckgen.py
=================
Deck generation endpoints (classic, Perplexity V1, V3):
  GET  /api/deck-generator/config
  POST /api/deck-generator/preview
  POST /api/deck-generator/commit
  GET  /api/deck-generator/commander-search
  POST /api/deck-research
  POST /api/deck-generate
  GET  /api/pplx/status
  GET  /api/deck/v3/status
  POST /api/deck/v3/generate
  POST /api/deck/v3/commit
  POST /api/deck/v3/export/csv
  POST /api/deck/v3/export/dck
  POST /api/deck/v3/export/moxfield
  POST /api/deck/v3/export/shopping
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from models.requests import DeckResearchRequest, DeckGenerateAIRequest

import routes.coach as _coach  # for _deck_gen_v3 / _deck_gen_v3_error module-level access
from models.state import CFG
from models.requests import (
    DeckGenerationRequest, DeckGenV3Request, DeckGenV3SubstituteRequest,
    DeckGenerationSourceConfig,
)
from models.responses import GeneratedDeckCard
from services.database import _get_db_conn
from services.logging import log_deckgen, log_pplx
from services.scryfall import _scryfall_rate_limit, _API_HEADERS
from services.deck_service import _write_dck_file, _build_dck_lines

router = APIRouter(tags=["deckgen"])

# ── V3 Result Cache (avoids re-generating on export) ─────────────
import hashlib
_v3_result_cache: dict[str, tuple[float, dict]] = {}  # key -> (timestamp, result)
_V3_CACHE_TTL = 600  # 10 minutes

def _v3_cache_key(req) -> str:
    """Deterministic cache key from a DeckGenV3Request."""
    blob = json.dumps({
        'commander': req.commander_name.strip().lower(),
        'strategy': req.strategy or '',
        'bracket': req.target_bracket,
        'budget': req.budget_usd,
        'budget_mode': req.budget_mode,
        'omit': sorted(req.omit_cards or []),
        'collection': req.use_collection,
        'model': req.model or '',
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]

def _v3_cache_get(key: str) -> dict | None:
    """Return cached result if within TTL, else None."""
    entry = _v3_result_cache.get(key)
    if entry and (time.time() - entry[0]) < _V3_CACHE_TTL:
        return entry[1]
    if entry:
        del _v3_result_cache[key]
    return None

def _v3_cache_put(key: str, result: dict):
    """Store result in cache with current timestamp."""
    # Evict stale entries if cache grows large
    if len(_v3_result_cache) > 50:
        cutoff = time.time() - _V3_CACHE_TTL
        stale = [k for k, (ts, _) in _v3_result_cache.items() if ts < cutoff]
        for k in stale:
            del _v3_result_cache[k]
    _v3_result_cache[key] = (time.time(), result)


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
            "SELECT name, type_line, color_identity, mana_cost, scryfall_id, oracle_text FROM collection_entries WHERE scryfall_id = ? LIMIT 1",
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
                "oracle_text": row["oracle_text"] or "",
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
            "SELECT name, type_line, color_identity, mana_cost, scryfall_id, oracle_text FROM collection_entries WHERE LOWER(name) = ? LIMIT 1",
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
                "oracle_text": row["oracle_text"] or "",
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
        "oracle_text": data.get("oracle_text", ""),
        "image_url": image_uris.get("normal", ""),
    }


def _get_collection_for_colors(color_identity: list) -> list:
    """Fetch collection cards whose color identity is a subset of *color_identity*.

    Uses SQLite's json_each() to push the colour-subset check into SQL so we
    only transfer the rows we actually need.  The NOT EXISTS sub-query ensures
    every colour symbol in the card's identity appears in the commander's
    identity list.  Cards with an empty colour identity (colourless / lands)
    always pass because the NOT EXISTS has no rows to violate.

    Only the columns consumed downstream are projected (no SELECT *).
    """
    conn = _get_db_conn()
    allowed_json = json.dumps([c.upper() for c in color_identity]) if color_identity else '[]'

    rows = conn.execute("""
        SELECT scryfall_id, name, type_line, mana_cost, cmc,
               oracle_text, keywords, quantity, edhrec_rank, color_identity
        FROM collection_entries
        WHERE quantity > 0
          AND scryfall_id != ''
          AND NOT EXISTS (
              SELECT 1 FROM json_each(
                  CASE WHEN collection_entries.color_identity IS NULL
                            OR collection_entries.color_identity = ''
                       THEN '[]'
                       ELSE collection_entries.color_identity
                  END
              ) AS jc
              WHERE jc.value NOT IN (
                  SELECT value FROM json_each(?)
              )
          )
    """, (allowed_json,)).fetchall()

    valid = []
    for row in rows:
        card = dict(row)
        ci = card.get("color_identity", "[]")
        try:
            card["color_identity"] = json.loads(ci) if isinstance(ci, str) else ci
        except Exception:
            card["color_identity"] = []
        valid.append(card)
    return valid


# ── Oracle-text keyword extraction for scoring ────────────────────
_ORACLE_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'of', 'to', 'and', 'or', 'is', 'it', 'its',
    'in', 'on', 'at', 'for', 'by', 'with', 'from', 'as', 'if',
    'that', 'this', 'you', 'your', 'up', 'all', 'each', 'may',
    'can', 'one', 'two', 'three', 'four', 'five', 'card', 'cards',
    'target', 'player', 'creature', 'creatures', 'spell', 'spells',
    'permanent', 'permanents', 'turn', 'end', 'step', 'phase',
    'mana', 'color', 'pay', 'cost', 'tap', 'untap', 'put', 'get',
    'has', 'have', 'are', 'be', 'been', 'was', 'were', 'do', 'does',
    'any', 'no', 'not', 'only', 'also', 'then', 'when', 'whenever',
    'where', 'which', 'who', 'them', 'they', 'their', 'other',
    'more', 'less', 'than', 'into', 'under', 'over', 'until',
    'would', 'could', 'instead', 'about', 'number', 'equal',
})


def _extract_oracle_keywords(oracle_text: str) -> set[str]:
    """Extract meaningful keywords from oracle text, filtering stop words."""
    if not oracle_text:
        return set()
    cleaned = re.sub(r'\([^)]*\)', '', oracle_text)
    tokens = re.findall(r'[a-z]{3,}', cleaned.lower())
    return {t for t in tokens if t not in _ORACLE_STOP_WORDS}

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
    commander_keywords = _extract_oracle_keywords(commander.get("oracle_text", ""))
    log_deckgen.info(f"  Commander keywords ({len(commander_keywords)}): {sorted(commander_keywords)[:15]}")

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
                "oracle_text": card.get("oracle_text", ""),
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
            # Oracle-text keyword overlap with commander
            card_oracle = card.get("oracle_text") or ""
            if commander_keywords and card_oracle:
                card_kw = _extract_oracle_keywords(card_oracle)
                overlap = len(commander_keywords & card_kw)
                if overlap >= 4:
                    score += 12
                elif overlap >= 2:
                    score += 7
                elif overlap >= 1:
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


@router.get("/api/deck-generator/config")
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


@router.post("/api/deck-generator/preview")
async def deck_generator_preview(req: DeckGenerationRequest):
    """
    Generate a deck preview without saving it.
    Returns the generated deck data for user review.
    """
    result = _generate_deck(req)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/api/deck-generator/commit")
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

    try:
        _write_dck_file(deck_name, commander['name'], cards, fallback_id=deck_id)
    except Exception as e:
        log_deckgen.warning(f"  Warning: Failed to export .dck file: {e}")

    log_deckgen.info(f"  Saved deck '{deck_name}' (ID: {deck_id}) with {len(cards)} cards + commander")

    result["deck_id"] = deck_id
    result["deck_name"] = deck_name
    return result


@router.get("/api/deck-generator/commander-search")
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



def _build_collection_summary(color_identity: list[str] | None = None) -> dict:
    """Build a compact collection summary for the AI, optionally filtered by color identity.

    Uses the same json_each NOT EXISTS pattern as _get_collection_for_colors()
    so that colour-identity filtering happens in SQL rather than Python.
    """
    conn = _get_db_conn()

    allowed_json = json.dumps([c.upper() for c in color_identity]) if color_identity else '[]'

    # SQL handles the colour-identity subset check via json_each
    ci_filter = """
          AND NOT EXISTS (
              SELECT 1 FROM json_each(
                  CASE WHEN collection_entries.color_identity IS NULL
                            OR collection_entries.color_identity = ''
                       THEN '[]'
                       ELSE collection_entries.color_identity
                  END
              ) AS jc
              WHERE jc.value NOT IN (
                  SELECT value FROM json_each(?)
              )
          )
    """ if color_identity else ""

    params = (allowed_json,) if color_identity else ()

    rows = conn.execute(f"""
        SELECT name, type_line, cmc, oracle_text, keywords, tcg_price, quantity,
               color_identity, category, is_game_changer, salt_score
        FROM collection_entries
        WHERE quantity > 0
        {ci_filter}
        ORDER BY edhrec_rank ASC, tcg_price DESC
    """, params).fetchall()

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
    filtered_count = len(rows)  # SQL already filtered

    for r in rows:
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


async def _call_pplx_api(messages: list[dict], max_tokens: int = 4096, temperature: float = 0.2) -> str:
    """Call Perplexity API chat/completions endpoint (non-blocking).
    Uses httpx.AsyncClient so the uvicorn event loop is never stalled.
    Returns the assistant message content.
    """
    from coach.config import DECK_GEN_PROVIDER, DECK_GEN_BASE_URL, DECK_GEN_MODEL, PPLX_MODEL

    if DECK_GEN_PROVIDER == 'local':
        base_url = DECK_GEN_BASE_URL
        model = DECK_GEN_MODEL
        headers = {'Content-Type': 'application/json'}
    else:
        if not CFG.pplx_api_key:
            raise HTTPException(400, 'Perplexity API key not configured. Set PPLX_API_KEY env var or --pplx-key.')
        base_url = 'https://api.perplexity.ai'
        model = PPLX_MODEL
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {CFG.pplx_api_key}',
        }
    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f'{base_url}/chat/completions',
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f'Perplexity API returned {e.response.status_code}: {e.response.text[:200]}')
    except httpx.RequestError as e:
        raise HTTPException(502, f'Perplexity API call failed: {e}')

    choices = data.get('choices', [])
    if not choices:
        raise HTTPException(502, 'Empty response from Perplexity API')
    content = choices[0].get('message', {}).get('content', '')
    usage = data.get('usage', {})
    log_pplx.debug(
        f'tokens: prompt={usage.get("prompt_tokens", "?")}, '
        f'completion={usage.get("completion_tokens", "?")}, '
        f'model={data.get("model", "?")}'
    )
    return content


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


# ── Research Endpoint ───────────────────────────────────────────────────

@router.post('/api/deck-research')
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

    content = await _call_pplx_api([
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


# ── Generate Endpoint ───────────────────────────────────────────────

@router.post('/api/deck-generate')
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

    content = await _call_pplx_api([
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


@router.get('/api/pplx/status')
async def pplx_status():
    """Check if Perplexity API is configured."""
    return {
        'configured': bool(CFG.pplx_api_key),
    }


# ══════════════════════════════════════════════════════════════
# V3 Deck Generator (Perplexity Structured Output)
# ══════════════════════════════════════════════════════════════

@router.get('/api/deck/v3/status')
async def deck_gen_v3_status():
    """Check V3 deck generator status."""
    return {
        'initialized': _coach._deck_gen_v3 is not None,
        'pplx_configured': bool(CFG.pplx_api_key),
        'model': getattr(_coach._deck_gen_v3, 'model', getattr(getattr(_coach._deck_gen_v3, 'pplx', None), 'model', 'ollama/gpt-oss:20b')) if _coach._deck_gen_v3 else None,
        'embeddings_loaded': False,
        'embedding_cards': 0,
        'error': _coach._deck_gen_v3_error,
    }


@router.post('/api/deck/v3/generate')
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
    if _coach._deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized. Ensure Ollama is running with gpt-oss:20b model.')

    if not req.commander_name or len(req.commander_name.strip()) < 2:
        raise HTTPException(400, 'Commander name is required (min 2 chars)')

    try:
        # Generate deck
        result = _coach._deck_gen_v3.generate_deck(
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
            sub_result = _coach._deck_gen_v3.run_substitution(
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

        # Cache result for export endpoints
        _v3_cache_put(_v3_cache_key(req), result)

        return result

    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=422)
    except Exception as e:
        log_deckgen.error(f'V3 generate error: {e}', exc_info=True)
        raise HTTPException(500, f'Deck generation failed: {str(e)}')


@router.post('/api/deck/v3/commit')
async def deck_gen_v3_commit(req: DeckGenV3Request):
    """
    V3 Generate + Commit — generates the deck and saves it to the Deck Builder DB.
    Also exports a .dck file for Forge Sim Lab.
    """
    if _coach._deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    if not req.commander_name or len(req.commander_name.strip()) < 2:
        raise HTTPException(400, 'Commander name is required')

    try:
        # Generate deck (same as preview)
        result = _coach._deck_gen_v3.generate_deck(
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
            sub_result = _coach._deck_gen_v3.run_substitution(
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

        try:
            _write_dck_file(deck_name, commander['name'], cards, fallback_id=deck_id, resolve_substitutes=True)
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


@router.post('/api/deck/v3/export/csv')
async def deck_gen_v3_export_csv(req: DeckGenV3Request):
    """Generate a deck and return as CSV."""
    if _coach._deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    _ck = _v3_cache_key(req)
    result = _v3_cache_get(_ck)
    if result is None:
        result = _coach._deck_gen_v3.generate_deck(
            commander_name=req.commander_name.strip(),
            strategy=req.strategy,
            target_bracket=req.target_bracket,
            budget_usd=req.budget_usd,
            budget_mode=req.budget_mode,
            omit_cards=req.omit_cards,
            use_collection=req.use_collection,
            model=req.model,
        )
        _v3_cache_put(_ck, result)
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


@router.post('/api/deck/v3/export/dck')
async def deck_gen_v3_export_dck(req: DeckGenV3Request):
    """Generate a deck and return as Forge .dck format."""
    if _coach._deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    _ck = _v3_cache_key(req)
    result = _v3_cache_get(_ck)
    if result is None:
        result = _coach._deck_gen_v3.generate_deck(
            commander_name=req.commander_name.strip(),
            strategy=req.strategy,
            target_bracket=req.target_bracket,
            budget_usd=req.budget_usd,
            budget_mode=req.budget_mode,
            omit_cards=req.omit_cards,
            use_collection=req.use_collection,
            model=req.model,
        )
        _v3_cache_put(_ck, result)

    cards = result.get('cards', [])
    commander = result.get('commander', {})

    lines = _build_dck_lines(
        f"{commander.get('name', 'Deck')} - V3 Auto",
        commander.get('name', ''),
        cards,
        resolve_substitutes=True,
    )
    dck_content = '\n'.join(lines)
    safe_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', commander.get('name', 'deck')).strip().replace(' ', '_')
    return StreamingResponse(
        io.BytesIO(dck_content.encode('utf-8')),
        media_type='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{safe_name}.dck"'},
    )


@router.post('/api/deck/v3/export/moxfield')
async def deck_gen_v3_export_moxfield(req: DeckGenV3Request):
    """Generate a deck and return in Moxfield paste format."""
    if _coach._deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    _ck = _v3_cache_key(req)
    result = _v3_cache_get(_ck)
    if result is None:
        result = _coach._deck_gen_v3.generate_deck(
            commander_name=req.commander_name.strip(),
            strategy=req.strategy,
            target_bracket=req.target_bracket,
            budget_usd=req.budget_usd,
            budget_mode=req.budget_mode,
            omit_cards=req.omit_cards,
            use_collection=req.use_collection,
            model=req.model,
        )
        _v3_cache_put(_ck, result)

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


@router.post('/api/deck/v3/export/shopping')
async def deck_gen_v3_export_shopping(req: DeckGenV3Request):
    """Generate a deck and return a shopping list of cards not owned."""
    if _coach._deck_gen_v3 is None:
        raise HTTPException(503, 'V3 Deck Generator not initialized.')

    _ck = _v3_cache_key(req)
    result = _v3_cache_get(_ck)
    if result is None:
        result = _coach._deck_gen_v3.generate_deck(
            commander_name=req.commander_name.strip(),
            strategy=req.strategy,
            target_bracket=req.target_bracket,
            budget_usd=req.budget_usd,
            budget_mode=req.budget_mode,
            omit_cards=req.omit_cards,
            use_collection=req.use_collection,
            model=req.model,
        )
        _v3_cache_put(_ck, result)

    cards = result.get('cards', [])
    shopping = []
    total = 0.0
    for card in cards:
        if not card.get('from_collection', False) and card.get('status') != 'substituted':
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
