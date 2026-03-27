"""
services/scryfall_bulk.py
=========================
Downloads and indexes the full Scryfall `default_cards` bulk export into a
local SQLite database with FTS5 full-text search over card names and oracle
text.  This replaces per-card live Scryfall API calls for the RAG pipeline.

Usage (one-time or nightly):
    from services.scryfall_bulk import ensure_bulk_db
    ensure_bulk_db()   # call at startup; no-ops if data is fresh

Public API:
    ensure_bulk_db()                      -> None   (download if stale)
    lookup_card(name)                     -> dict | None
    search_oracle(query, colors, limit)   -> list[dict]
    get_bulk_db()                         -> sqlite3.Connection

Data path:  ./data/scryfall_bulk.db
Re-download: every SCRYFALL_BULK_STALENESS_DAYS days (default 7)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger("commander_ai_lab.scryfall_bulk")

# ── Config ──────────────────────────────────────────────────────────────────
BULK_DB_PATH = Path(__file__).parent.parent / "data" / "scryfall_bulk.db"
BULK_META_URL = "https://api.scryfall.com/bulk-data"
SCRYFALL_BULK_STALENESS_DAYS = int(
    os.environ.get("SCRYFALL_BULK_STALENESS_DAYS", "7")
)
_API_HEADERS = {"User-Agent": "CommanderAILab/3.0", "Accept": "application/json"}

# ── Module-level singletons ──────────────────────────────────────────────────
_bulk_conn: sqlite3.Connection | None = None
_bulk_lock = threading.Lock()


# ── DB init ──────────────────────────────────────────────────────────────────

def _init_db(conn: sqlite3.Connection) -> None:
    """Create tables and FTS5 virtual table on first run."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cards (
            scryfall_id     TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            oracle_text     TEXT DEFAULT '',
            type_line       TEXT DEFAULT '',
            mana_cost       TEXT DEFAULT '',
            cmc             REAL DEFAULT 0,
            color_identity  TEXT DEFAULT '[]',
            keywords        TEXT DEFAULT '[]',
            power           TEXT DEFAULT '',
            toughness       TEXT DEFAULT '',
            rarity          TEXT DEFAULT '',
            edhrec_rank     INTEGER DEFAULT 0,
            legalities      TEXT DEFAULT '{}',
            rulings_uri     TEXT DEFAULT '',
            set_code        TEXT DEFAULT '',
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
            name,
            oracle_text,
            content='cards',
            content_rowid='rowid'
        );

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Staleness check ───────────────────────────────────────────────────────────

def _is_stale(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'last_download'"
    ).fetchone()
    if not row:
        return True
    try:
        age_days = (time.time() - float(row[0])) / 86400
        return age_days > SCRYFALL_BULK_STALENESS_DAYS
    except (ValueError, TypeError):
        return True


# ── Download + index ──────────────────────────────────────────────────────────

def _get_bulk_download_url() -> str:
    """Fetch the current default_cards download URL from the Scryfall manifest."""
    req = Request(BULK_META_URL, headers=_API_HEADERS)
    with urlopen(req, timeout=15) as resp:
        meta = json.loads(resp.read())
    for entry in meta.get("data", []):
        if entry.get("type") == "default_cards":
            return entry["download_uri"]
    raise RuntimeError("Could not find default_cards entry in Scryfall bulk-data manifest")


def _download_and_index(conn: sqlite3.Connection) -> int:
    """
    Download the full default_cards JSON from Scryfall and index into SQLite.
    Replaces all existing rows.  Returns number of cards indexed.
    """
    logger.info("Fetching Scryfall bulk-data manifest...")
    url = _get_bulk_download_url()
    logger.info("Downloading Scryfall default_cards bulk export (~100 MB)...")

    req = Request(url, headers=_API_HEADERS)
    with urlopen(req, timeout=300) as resp:
        raw_bytes = resp.read()

    cards_json: list[dict] = json.loads(raw_bytes)
    logger.info(f"Received {len(cards_json)} card objects from Scryfall.")

    # Wipe existing data for a clean rebuild
    conn.execute("DELETE FROM cards")
    conn.execute("DELETE FROM cards_fts")
    conn.commit()

    BATCH_SIZE = 1000
    inserted = 0
    batch: list[tuple] = []

    _SKIP_LAYOUTS = {"token", "emblem", "art_series", "double_faced_token"}

    for card in cards_json:
        if card.get("layout") in _SKIP_LAYOUTS:
            continue

        # Handle double-faced / meld cards: concatenate face oracle texts
        oracle = card.get("oracle_text", "")
        if not oracle and card.get("card_faces"):
            oracle = "\n//\n".join(
                f.get("oracle_text", "")
                for f in card["card_faces"]
                if f.get("oracle_text")
            )

        mana_cost = card.get("mana_cost", "")
        if not mana_cost and card.get("card_faces"):
            mana_cost = card["card_faces"][0].get("mana_cost", "")

        batch.append((
            card.get("id", ""),
            card.get("name", ""),
            oracle,
            card.get("type_line", ""),
            mana_cost,
            float(card.get("cmc") or 0),
            json.dumps(card.get("color_identity", [])),
            json.dumps(card.get("keywords", [])),
            card.get("power", "") or "",
            card.get("toughness", "") or "",
            card.get("rarity", ""),
            int(card.get("edhrec_rank") or 0),
            json.dumps(card.get("legalities", {})),
            card.get("rulings_uri", "") or "",
            card.get("set", ""),
        ))

        if len(batch) >= BATCH_SIZE:
            _flush_batch(conn, batch)
            inserted += len(batch)
            batch.clear()
            logger.debug(f"  Indexed {inserted} cards...")

    if batch:
        _flush_batch(conn, batch)
        inserted += len(batch)

    # Rebuild FTS5 index from cards table
    conn.execute("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")

    # Record download timestamp
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_download', ?)",
        (str(time.time()),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('card_count', ?)",
        (str(inserted),)
    )
    conn.commit()

    logger.info(f"Scryfall bulk index complete: {inserted} cards stored.")
    return inserted


def _flush_batch(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO cards
          (scryfall_id, name, oracle_text, type_line, mana_cost, cmc,
           color_identity, keywords, power, toughness, rarity,
           edhrec_rank, legalities, rulings_uri, set_code)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        batch,
    )
    conn.commit()


# ── Public API ────────────────────────────────────────────────────────────────

def get_bulk_db() -> sqlite3.Connection:
    """
    Return the module-level SQLite connection, creating it on first call.
    Thread-safe via _bulk_lock.
    """
    global _bulk_conn
    with _bulk_lock:
        if _bulk_conn is None:
            BULK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _bulk_conn = sqlite3.connect(
                str(BULK_DB_PATH), check_same_thread=False
            )
            _bulk_conn.row_factory = sqlite3.Row
            _init_db(_bulk_conn)
    return _bulk_conn


def ensure_bulk_db() -> None:
    """
    Call at startup.  Downloads and indexes the full Scryfall card set if the
    local DB is missing or older than SCRYFALL_BULK_STALENESS_DAYS.
    No-ops if data is already fresh.
    """
    conn = get_bulk_db()
    if _is_stale(conn):
        logger.info(
            "Scryfall bulk DB is stale or missing — downloading now "
            "(~100 MB, one-time per week)..."
        )
        try:
            _download_and_index(conn)
        except Exception as exc:
            logger.error(
                f"Scryfall bulk download failed: {exc}. "
                "Continuing without bulk data — per-card Scryfall cache will be used."
            )
    else:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'card_count'"
        ).fetchone()
        count = row[0] if row else "unknown"
        logger.info(f"Scryfall bulk DB is fresh ({count} cards cached).")


def lookup_card(name: str) -> dict | None:
    """
    Exact case-insensitive card name lookup.

    Returns a dict with all columns from the `cards` table, or None if not
    found.  Prefers the most-recently-printed printing (lowest edhrec_rank).
    """
    conn = get_bulk_db()
    row = conn.execute(
        """
        SELECT * FROM cards
        WHERE LOWER(name) = LOWER(?)
        ORDER BY edhrec_rank ASC
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    return dict(row) if row else None


def search_oracle(
    query: str,
    color_identity: list[str] | None = None,
    type_filter: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Full-text search over card names and oracle text using SQLite FTS5.

    Args:
        query:          Natural language or keyword query string.
        color_identity: If provided, restrict results to cards whose color
                        identity is a subset of this list (e.g. ['W', 'U']).
        type_filter:    Optional type-line substring filter (e.g. 'Creature').
        limit:          Maximum number of results to return.

    Returns:
        List of card dicts ordered by FTS5 relevance rank.
    """
    conn = get_bulk_db()

    # Build FTS5 query: wrap each token in quotes to allow phrase matching
    tokens = [t.strip() for t in query.split() if t.strip()]
    if not tokens:
        return []
    fts_query = " OR ".join(f'"{t}"' for t in tokens)

    # Over-fetch to allow post-filtering by color/type
    fetch_limit = max(limit * 5, 50)
    rows = conn.execute(
        """
        SELECT c.*
        FROM cards c
        JOIN cards_fts fts ON fts.rowid = c.rowid
        WHERE cards_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, fetch_limit),
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        card = dict(row)

        # Color identity filter: card's CI must be a subset of deck's CI
        if color_identity:
            try:
                card_ci = set(json.loads(card.get("color_identity") or "[]"))
            except (json.JSONDecodeError, TypeError):
                card_ci = set()
            if not card_ci.issubset(set(color_identity)):
                continue

        # Optional type-line filter
        if type_filter:
            if type_filter.lower() not in (card.get("type_line") or "").lower():
                continue

        results.append(card)
        if len(results) >= limit:
            break

    return results


def get_stats() -> dict:
    """Return metadata about the current bulk DB state."""
    conn = get_bulk_db()
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    meta = {r["key"]: r["value"] for r in rows}
    card_count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    stale = _is_stale(conn)
    last_dl = meta.get("last_download")
    age_days: float | None = None
    if last_dl:
        try:
            age_days = round((time.time() - float(last_dl)) / 86400, 1)
        except (ValueError, TypeError):
            pass
    return {
        "card_count": card_count,
        "stale": stale,
        "age_days": age_days,
        "db_path": str(BULK_DB_PATH),
        "staleness_threshold_days": SCRYFALL_BULK_STALENESS_DAYS,
    }
