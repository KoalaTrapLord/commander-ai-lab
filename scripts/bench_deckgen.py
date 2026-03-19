#!/usr/bin/env python3
"""
scripts/bench_deckgen.py
========================
Benchmark for _get_collection_for_colors() and _build_collection_summary().

Seeds an in-memory SQLite DB with randomised collection_entries rows,
then times the SQL-filtered query for various commander colour identities.

Usage:
    python scripts/bench_deckgen.py [--rows 1000]
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from typing import List

# ── Helpers ──────────────────────────────────────────────────────────────────

ALL_COLORS = ["W", "U", "B", "R", "G"]

CARD_TYPE_LINES = [
    "Creature - Human Soldier",
    "Creature - Elf Druid",
    "Instant",
    "Sorcery",
    "Artifact",
    "Enchantment",
    "Land",
    "Artifact Creature - Golem",
    "Legendary Creature - Dragon",
    "Planeswalker - Jace",
]


def _random_color_identity() -> list:
    """Return a random colour identity (including ~15% chance of colorless)."""
    if random.random() < 0.15:
        return []
    n = random.randint(1, 3)
    return sorted(random.sample(ALL_COLORS, n))


def _seed_db(conn: sqlite3.Connection, num_rows: int):
    """Create collection_entries table and insert random rows."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type_line TEXT DEFAULT '',
            color_identity TEXT DEFAULT '[]',
            cmc REAL DEFAULT 0,
            mana_cost TEXT DEFAULT '',
            oracle_text TEXT DEFAULT '',
            keywords TEXT DEFAULT '[]',
            quantity INTEGER DEFAULT 1,
            edhrec_rank INTEGER DEFAULT 0,
            scryfall_id TEXT DEFAULT '',
            tcg_price REAL DEFAULT 0,
            salt_score REAL DEFAULT 0,
            is_game_changer INTEGER DEFAULT 0,
            category TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ce_quantity
            ON collection_entries (quantity) WHERE quantity > 0
    """)

    rows = []
    for i in range(num_rows):
        ci = _random_color_identity()
        qty = random.choice([0, 1, 1, 1, 2, 3])  # ~17% zero quantity
        rows.append((
            f"Card_{i:05d}",
            random.choice(CARD_TYPE_LINES),
            json.dumps(ci),
            round(random.uniform(0, 8), 1),
            "",
            f"Sample oracle text for card {i}",
            json.dumps([]),
            qty,
            random.randint(1, 20000),
            f"scryfall-{i:05d}" if random.random() > 0.02 else "",
            round(random.uniform(0, 50), 2),
            round(random.uniform(0, 5), 2),
            1 if random.random() < 0.05 else 0,
            random.choice(["", "ramp", "draw", "removal", ""]),
        ))

    conn.executemany("""
        INSERT INTO collection_entries
            (name, type_line, color_identity, cmc, mana_cost, oracle_text,
             keywords, quantity, edhrec_rank, scryfall_id, tcg_price,
             salt_score, is_game_changer, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    print(f"  Seeded {num_rows} rows ({sum(1 for r in rows if r[7] > 0)} with qty > 0)")


# ── Query under test (same as routes/deckgen.py) ────────────────────────────

def get_collection_for_colors(conn: sqlite3.Connection, color_identity: list) -> list:
    """Mirrors the new SQL-filtered implementation."""
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


def get_collection_for_colors_old(conn: sqlite3.Connection, color_identity: list) -> list:
    """Old implementation: SELECT * + Python-side filter."""
    rows = conn.execute(
        "SELECT * FROM collection_entries WHERE quantity > 0"
    ).fetchall()
    valid = []
    for row in rows:
        card = dict(row)
        card_ci = card.get("color_identity", "[]")
        if isinstance(card_ci, str):
            try:
                card_ci = json.loads(card_ci)
            except Exception:
                card_ci = []
        if color_identity and card_ci:
            if not all(c in color_identity for c in card_ci):
                continue
        if not card.get("scryfall_id"):
            continue
        card["color_identity"] = card_ci
        valid.append(card)
    return valid


# ── Main ─────────────────────────────────────────────────────────────────────

COMMANDERS = [
    ("Mono-W",    ["W"]),
    ("WUB",       ["W", "U", "B"]),
    ("WUBRG",     ["W", "U", "B", "R", "G"]),
    ("Colorless", []),
    ("Mono-G",    ["G"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1000)
    args = parser.parse_args()

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_db(conn, args.rows)

    print(f"\n{'Commander':<14} {'Old ms':>8} {'New ms':>8} {'Old#':>6} {'New#':>6} {'Match':>6}")
    print("-" * 60)

    for label, ci in COMMANDERS:
        # Old
        t0 = time.perf_counter()
        old_result = get_collection_for_colors_old(conn, ci)
        old_ms = (time.perf_counter() - t0) * 1000

        # New
        t0 = time.perf_counter()
        new_result = get_collection_for_colors(conn, ci)
        new_ms = (time.perf_counter() - t0) * 1000

        match = len(old_result) == len(new_result)
        # NOTE: Colorless ([]) intentionally differs — old code had a bug that
        # skipped the colour check entirely when color_identity was empty,
        # returning ALL cards.  The new SQL correctly restricts to colourless.
        if not ci:  # colorless commander
            marker = "FIX" if len(new_result) < len(old_result) else "OK"
        else:
            marker = "OK" if match else "FAIL"
        print(f"  {label:<12} {old_ms:>7.2f} {new_ms:>7.2f} {len(old_result):>6} {len(new_result):>6} {marker:>6}")

        if not match and ci:  # only flag non-colorless mismatches
            old_names = {c["name"] for c in old_result}
            new_names = {c["name"] for c in new_result}
            print(f"    Only in old: {len(old_names - new_names)} cards")
            print(f"    Only in new: {len(new_names - old_names)} cards")

    print()


if __name__ == "__main__":
    main()
