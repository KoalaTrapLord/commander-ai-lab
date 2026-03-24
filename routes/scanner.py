"""
routes/scanner.py
=================
Card scanner & collection enrichment endpoints:
  POST /api/collection/scan
  POST /api/collection/scan/add
  POST /api/collection/re-enrich
  POST /api/collection/auto-classify
  POST /api/collection/auto-classify-all
  GET  /api/collection/{cardId}/edhrec
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from fastapi import APIRouter, HTTPException
from fastapi import Request as FastAPIRequest

from models.state import CFG
from services.card_analysis import _detect_card_roles
from services.database import _get_db_conn, _row_to_dict
from services.deck_service import _to_edhrec_slug
from services.import_helpers import _edhrec_cache_get, _edhrec_cache_set
from services.logging import log_scan, log_deckgen
from services.scryfall import _API_HEADERS, _enrich_from_scryfall, _scryfall_fuzzy_lookup

router = APIRouter(tags=["scanner"])


@router.post("/api/collection/scan")
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


@router.post("/api/collection/scan/add")
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

@router.post("/api/collection/re-enrich")
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

@router.post("/api/collection/auto-classify")
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


@router.post("/api/collection/auto-classify-all")
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

@router.get("/api/collection/{cardId}/edhrec")
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


