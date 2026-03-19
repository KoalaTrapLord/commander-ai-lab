"""SQLite database management and collection utility helpers."""
from __future__ import annotations
import io
import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log_collect = logging.getLogger("commander_ai_lab.collection")

# ══════════════════════════════════════════════════════════════
# Collection Database
# ══════════════════════════════════════════════════════════════
COLLECTION_DB_PATH = Path(__file__).parent.parent / "collection.db"
_db_local = threading.local()


def _get_db_conn() -> sqlite3.Connection:
    """Return the thread-local SQLite connection, creating it on first use."""
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        conn = sqlite3.connect(str(COLLECTION_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _db_local.conn = conn
    return _db_local.conn


def _close_db_conn() -> None:
    """Close and discard the thread-local connection (call on thread teardown)."""
    conn = getattr(_db_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _db_local.conn = None


def init_collection_db() -> None:
    """Create tables, indexes, and run column migrations.

    Uses _get_db_conn() so the same thread-local connection that route
    handlers will use is warmed up and fully migrated before any request
    arrives.  No separate connection is opened or closed here.
    """
    conn = _get_db_conn()
    conn.executescript("""
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
        CREATE INDEX IF NOT EXISTS idx_ce_quantity ON collection_entries(quantity)
            WHERE quantity > 0;
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

    # ── Column migrations (additive only) ─────────────────────────────────
    _migrate_columns = [
        ("mana_cost",    "TEXT DEFAULT ''"),
        ("power",        "TEXT DEFAULT ''"),
        ("toughness",    "TEXT DEFAULT ''"),
        ("rarity",       "TEXT DEFAULT ''"),
        ("set_name",     "TEXT DEFAULT ''"),
        ("edhrec_rank",  "INTEGER DEFAULT 0"),
    ]
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(collection_entries)").fetchall()
    }
    for col_name, col_def in _migrate_columns:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE collection_entries ADD COLUMN {col_name} {col_def}")
            log_collect.info(f"  Migration: added column '{col_name}' to collection_entries")
    conn.commit()

    log_collect.info(f"  Collection DB ready: {COLLECTION_DB_PATH}")


# ══════════════════════════════════════════════════════════════
# Collection Utility Helpers
# ══════════════════════════════════════════════════════════════
_JSON_FIELDS = ("category", "color_identity", "subtypes", "keywords")
VALID_SORT_FIELDS = {
    "name", "cmc", "tcg_price", "salt_score", "category", "color_identity",
    "quantity", "type_line", "finish", "rarity", "set_code", "power",
    "toughness", "edhrec_rank",
}


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
    q=None,
    colors=None,
    types=None,
    isLegendary=None,
    isBasic=None,
    isGameChanger=None,
    highSalt=None,
    finish=None,
    cmcMin=None,
    cmcMax=None,
    priceMin=None,
    priceMax=None,
    category=None,
    rarity=None,
    setCode=None,
    powerMin=None,
    powerMax=None,
    toughMin=None,
    toughMax=None,
    keyword=None,
    edhrecMin=None,
    edhrecMax=None,
    qtyMin=None,
    qtyMax=None,
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
            params.append(f"%{color}%")
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
            cc.append("category LIKE ?"); params.append(f"%{c}%")
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
