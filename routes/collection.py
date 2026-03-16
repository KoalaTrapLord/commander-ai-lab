"""
routes/collection.py
====================
Collection management endpoints:
  GET    /api/collection
  GET    /api/collection/export
  GET    /api/collection/sets
  GET    /api/collection/keywords
  POST   /api/collection/import
  GET    /api/collection/{cardId}
  PATCH  /api/collection/{cardId}
  GET    /api/cache/scryfall
  DELETE /api/cache/scryfall
  POST   /api/cache/scryfall/evict
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from routes.shared import (
    CFG,
    _get_db_conn,
    _row_to_dict,
    _add_image_url,
    _build_collection_filters,
    _detect_card_roles,
    _classify_card_type,
    _enrich_from_scryfall,
    _fetch_scryfall_api,
    _parse_finish,
    _parse_text_line,
    _parse_csv_content,
    _auto_infer_mapping,
    _scryfall_cache,
    _scryfall_rate_limit,
    _snake_to_camel,
    VALID_SORT_FIELDS,
    _JSON_FIELDS,
    SCRYFALL_CACHE_DB_PATH,
    SCRYFALL_CACHE_TTL_SECONDS,
    _API_HEADERS,
    log_collect,
    log_cache,
)

router = APIRouter(tags=["collection"])


@router.get("/api/collection/export")
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


@router.get("/api/collection/sets")
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


@router.get("/api/collection/keywords")
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


@router.get("/api/collection")
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
        deck_card_rows = conn.execute(
            "SELECT scryfall_id, SUM(quantity) as qty FROM deck_cards WHERE deck_id = ? GROUP BY scryfall_id",
            (deck_id,)
        ).fetchall()
        in_deck_map = {row["scryfall_id"]: row["qty"] for row in deck_card_rows}
        for item in items:
            item["in_deck_quantity"] = in_deck_map.get(item.get("scryfall_id", ""), 0)

    return {"items": items, "page": page, "pageSize": pageSize, "total": total}


@router.get("/api/collection/{cardId}")
async def get_collection_card(cardId: int):
    """Get a single collection entry by ID."""
    conn = _get_db_conn()
    row = conn.execute("SELECT * FROM collection_entries WHERE id = ?", (cardId,)).fetchone()
    if not row:
        raise HTTPException(404, f"Card with id {cardId} not found")
    return _add_image_url(_row_to_dict(row))


@router.patch("/api/collection/{cardId}")
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
# Scryfall Cache Management Endpoints
# ══════════════════════════════════════════════════════════════


@router.get("/api/cache/scryfall")
async def scryfall_cache_stats():
    """Return Scryfall response cache statistics."""
    return _scryfall_cache.stats()


@router.delete("/api/cache/scryfall")
async def scryfall_cache_clear():
    """Clear all cached Scryfall responses."""
    deleted = _scryfall_cache.clear()
    return {"cleared": deleted, "message": f"Deleted {deleted} cached entries"}


@router.post("/api/cache/scryfall/evict")
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
