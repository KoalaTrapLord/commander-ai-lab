"""Async SQLite wrapper for FastAPI — eliminates event-loop blocking.

Drop-in async replacements for the sync helpers in services/database.py.
Uses aiosqlite under the hood so every DB call yields back to the
event loop instead of freezing it.

Usage in route handlers:
    from services.async_db import async_get_db, async_execute, async_fetchall

    rows = await async_fetchall("SELECT * FROM decks")
    row  = await async_fetchone("SELECT * FROM decks WHERE id = ?", (1,))
    await async_execute("INSERT INTO ...", params)
    await async_execute_commit("DELETE FROM ...", params)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import aiosqlite

log = logging.getLogger("commander_ai_lab.async_db")

# Re-use the same DB path as the sync module
COLLECTION_DB_PATH = Path(__file__).parent.parent / "collection.db"

# Module-level connection (lazy-init, one per process)
_aconn: Optional[aiosqlite.Connection] = None


async def async_get_db() -> aiosqlite.Connection:
    """Return (or create) the module-level async SQLite connection."""
    global _aconn
    if _aconn is None:
        _aconn = await aiosqlite.connect(str(COLLECTION_DB_PATH))
        _aconn.row_factory = aiosqlite.Row
        await _aconn.execute("PRAGMA journal_mode=WAL")
        log.info("Async SQLite connection opened: %s", COLLECTION_DB_PATH)
    return _aconn


async def async_close_db() -> None:
    """Close the module-level connection (call on shutdown)."""
    global _aconn
    if _aconn is not None:
        await _aconn.close()
        _aconn = None
        log.info("Async SQLite connection closed.")


# ── Convenience helpers ─────────────────────────────────────────

async def async_fetchall(
    sql: str, params: tuple = (), *, conn: aiosqlite.Connection = None
) -> list[dict]:
    """Execute a SELECT and return all rows as dicts."""
    db = conn or await async_get_db()
    async with db.execute(sql, params) as cursor:
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]


async def async_fetchone(
    sql: str, params: tuple = (), *, conn: aiosqlite.Connection = None
) -> Optional[dict]:
    """Execute a SELECT and return one row as a dict (or None)."""
    db = conn or await async_get_db()
    async with db.execute(sql, params) as cursor:
        columns = [d[0] for d in cursor.description]
        row = await cursor.fetchone()
        return dict(zip(columns, row)) if row else None


async def async_execute(
    sql: str, params: tuple = (), *, conn: aiosqlite.Connection = None
) -> int:
    """Execute a write statement. Returns lastrowid."""
    db = conn or await async_get_db()
    cursor = await db.execute(sql, params)
    return cursor.lastrowid


async def async_execute_commit(
    sql: str, params: tuple = (), *, conn: aiosqlite.Connection = None
) -> int:
    """Execute a write statement and commit. Returns lastrowid."""
    db = conn or await async_get_db()
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.lastrowid


async def async_executemany_commit(
    sql: str, params_seq, *, conn: aiosqlite.Connection = None
) -> None:
    """Execute many and commit."""
    db = conn or await async_get_db()
    await db.executemany(sql, params_seq)
    await db.commit()


async def async_commit(*, conn: aiosqlite.Connection = None) -> None:
    """Commit the current transaction."""
    db = conn or await async_get_db()
    await db.commit()


# ── JSON field helpers (mirrors database._row_to_dict) ──────────

_JSON_FIELDS = ("category", "color_identity", "subtypes", "keywords")


def row_to_dict_parsed(row: dict) -> dict:
    """Parse JSON string columns into Python lists (same as database._row_to_dict)."""
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


# ── Coach session async helpers ─────────────────────────────────

async def async_save_coach_session(session_data: dict) -> int:
    """Insert or update a coach session. Returns row id."""
    db = await async_get_db()
    existing = await async_fetchone(
        "SELECT id FROM coach_sessions WHERE session_id = ?",
        (session_data["session_id"],),
    )
    if existing:
        await db.execute(
            """UPDATE coach_sessions SET
                deck_id=?, timestamp=?, model_used=?, prompt_tokens=?,
                completion_tokens=?, summary=?, goals_json=?, cuts_json=?,
                adds_json=?, heuristic_hints_json=?, mana_base_advice=?,
                raw_text=?
            WHERE session_id=?""",
            (
                session_data.get("deck_id", ""),
                session_data.get("timestamp", ""),
                session_data.get("model_used", ""),
                session_data.get("prompt_tokens", 0),
                session_data.get("completion_tokens", 0),
                session_data.get("summary", ""),
                session_data.get("goals_json", "{}"),
                session_data.get("cuts_json", "[]"),
                session_data.get("adds_json", "[]"),
                session_data.get("heuristic_hints_json", "[]"),
                session_data.get("mana_base_advice", ""),
                session_data.get("raw_text", ""),
                session_data["session_id"],
            ),
        )
        await db.commit()
        return existing["id"]
    else:
        cursor = await db.execute(
            """INSERT INTO coach_sessions
                (session_id, deck_id, timestamp, model_used, prompt_tokens,
                 completion_tokens, summary, goals_json, cuts_json, adds_json,
                 heuristic_hints_json, mana_base_advice, raw_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_data["session_id"],
                session_data.get("deck_id", ""),
                session_data.get("timestamp", ""),
                session_data.get("model_used", ""),
                session_data.get("prompt_tokens", 0),
                session_data.get("completion_tokens", 0),
                session_data.get("summary", ""),
                session_data.get("goals_json", "{}"),
                session_data.get("cuts_json", "[]"),
                session_data.get("adds_json", "[]"),
                session_data.get("heuristic_hints_json", "[]"),
                session_data.get("mana_base_advice", ""),
                session_data.get("raw_text", ""),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def async_load_coach_session(session_id: str) -> Optional[dict]:
    """Load a single coach session by session_id."""
    return await async_fetchone(
        "SELECT * FROM coach_sessions WHERE session_id = ?", (session_id,)
    )


async def async_list_coach_sessions(deck_id: str = None) -> list[dict]:
    """List coach sessions, optionally filtered by deck_id."""
    if deck_id:
        return await async_fetchall(
            "SELECT session_id, deck_id, timestamp, summary, created_at "
            "FROM coach_sessions WHERE deck_id = ? ORDER BY timestamp DESC",
            (deck_id,),
        )
    return await async_fetchall(
        "SELECT session_id, deck_id, timestamp, summary, created_at "
        "FROM coach_sessions ORDER BY timestamp DESC"
    )


async def async_delete_coach_session(session_id: str) -> bool:
    """Delete a coach session. Returns True if a row was deleted."""
    db = await async_get_db()
    cursor = await db.execute(
        "DELETE FROM coach_sessions WHERE session_id = ?", (session_id,)
    )
    await db.commit()
    return cursor.rowcount > 0
