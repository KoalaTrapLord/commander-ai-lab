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
        # Build a map of scryfall_id -> quantity in deck
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

@router.post("/api/collection/import")
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

