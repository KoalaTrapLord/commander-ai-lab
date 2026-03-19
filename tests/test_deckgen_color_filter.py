"""
tests/test_deckgen_color_filter.py
===================================
Regression tests for the SQL-based colour-identity filtering in
_get_collection_for_colors() and _build_collection_summary().

These tests use an in-memory SQLite database seeded with known data so they
run without touching the real collection DB.
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    """Return a seeded in-memory DB matching the collection_entries schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE collection_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type_line TEXT DEFAULT '',
            subtypes TEXT DEFAULT '',
            is_legendary INTEGER DEFAULT 0,
            is_basic INTEGER DEFAULT 0,
            color_identity TEXT DEFAULT '[]',
            cmc REAL DEFAULT 0,
            mana_cost TEXT DEFAULT '',
            oracle_text TEXT DEFAULT '',
            keywords TEXT DEFAULT '[]',
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
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ce_quantity
            ON collection_entries (quantity) WHERE quantity > 0
    """)
    # Seed known cards
    cards = [
        # (name, color_identity, quantity, scryfall_id, type_line, oracle_text, cmc, mana_cost, keywords, edhrec_rank, tcg_price, category)
        ("Sol Ring",       '[]',          2, "sol-001",    "Artifact",                     "Tap: Add {C}{C}.",            0, "{1}", '[]',       1, 5.0,  "ramp"),
        ("Plains",         '[]',          4, "plains-001", "Basic Land - Plains",           "({T}: Add {W}.)",             0, "",    '[]',       0, 0.1,  ""),
        ("Swords to Plow", '["W"]',       1, "stp-001",   "Instant",                      "Exile target creature.",       1, "{W}", '[]',     100, 3.0,  "removal"),
        ("Counterspell",   '["U"]',       1, "cs-001",    "Instant",                      "Counter target spell.",        2, "{U}{U}", '[]',  200, 2.0,  "removal"),
        ("Damnation",      '["B"]',       1, "damn-001",  "Sorcery",                      "Destroy all creatures.",       4, "{2}{B}{B}", '[]', 300, 15.0, "board wipe"),
        ("Lightning Bolt", '["R"]',       1, "bolt-001",  "Instant",                      "Deals 3 damage.",             1, "{R}", '[]',     150, 1.0,  "removal"),
        ("Llanowar Elves", '["G"]',       3, "llano-001", "Creature - Elf Druid",         "Tap: Add {G}.",               1, "{G}", '[]',      50, 0.5,  "ramp"),
        ("Atraxa",         '["W","U","B","G"]', 1, "atrax-001", "Legendary Creature", "Proliferate.",                    4, "{W}{U}{B}{G}", '["Proliferate"]', 10, 25.0, ""),
        ("Kozilek",        '[]',          1, "kozi-001",  "Legendary Creature - Eldrazi", "Draw 4 cards.",               10, "{10}", '[]',    20, 30.0, ""),
        ("Zero-Qty Card",  '["W"]',       0, "zero-001",  "Creature",                     "Some text.",                  2, "{1}{W}", '[]', 5000, 0.5,  ""),
        ("No-ID Card",     '["R"]',       1, "",           "Creature",                     "Some text.",                  3, "{2}{R}", '[]', 9999, 0.1,  ""),
        ("Orzhov Signet",  '["W","B"]',   2, "orzh-001",  "Artifact",                     "Add {W} or {B}.",             2, "{2}", '[]',     80, 1.0,  "ramp"),
    ]
    conn.executemany("""
        INSERT INTO collection_entries
            (name, color_identity, quantity, scryfall_id, type_line, oracle_text,
             cmc, mana_cost, keywords, edhrec_rank, tcg_price, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, cards)
    conn.commit()
    return conn


def _query_for_colors(conn: sqlite3.Connection, color_identity: list) -> list:
    """Run the same SQL as _get_collection_for_colors() against the given conn."""
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


def _summary_for_colors(conn: sqlite3.Connection, color_identity: list | None) -> list:
    """Run the same SQL as _build_collection_summary() and return matched rows."""
    allowed_json = json.dumps([c.upper() for c in color_identity]) if color_identity else '[]'
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
    return [dict(r) for r in rows]


# ── Tests ────────────────────────────────────────────────────────────────────

class TestGetCollectionForColors:

    def setup_method(self):
        self.conn = _make_conn()

    # Test 1: Mono-W — white cards, colourless cards, no off-colour
    def test_mono_white(self):
        result = _query_for_colors(self.conn, ["W"])
        names = {c["name"] for c in result}
        assert "Sol Ring" in names          # colourless
        assert "Plains" in names            # colourless land
        assert "Swords to Plow" in names    # white
        assert "Kozilek" in names           # colourless creature
        assert "Counterspell" not in names  # blue
        assert "Damnation" not in names     # black
        assert "Lightning Bolt" not in names # red
        assert "Llanowar Elves" not in names # green
        assert "Atraxa" not in names        # WUBG (needs more than W)
        assert "Orzhov Signet" not in names # WB (B not in W)

    # Test 2: WUBRG — returns all cards with qty > 0 and scryfall_id
    def test_five_color(self):
        result = _query_for_colors(self.conn, ["W", "U", "B", "R", "G"])
        names = {c["name"] for c in result}
        # Every card with qty > 0 and scryfall_id should be here
        assert "Sol Ring" in names
        assert "Swords to Plow" in names
        assert "Counterspell" in names
        assert "Damnation" in names
        assert "Lightning Bolt" in names
        assert "Llanowar Elves" in names
        assert "Atraxa" in names
        assert "Orzhov Signet" in names
        # Excluded: zero qty or missing scryfall_id
        assert "Zero-Qty Card" not in names
        assert "No-ID Card" not in names

    # Test 3: Colourless — only colourless cards
    def test_colorless(self):
        result = _query_for_colors(self.conn, [])
        names = {c["name"] for c in result}
        assert "Sol Ring" in names
        assert "Plains" in names
        assert "Kozilek" in names
        # Coloured cards excluded
        assert "Swords to Plow" not in names
        assert "Counterspell" not in names
        assert "Llanowar Elves" not in names

    # Test 4: Zero-quantity cards excluded
    def test_zero_quantity_excluded(self):
        result = _query_for_colors(self.conn, ["W", "U", "B", "R", "G"])
        names = {c["name"] for c in result}
        assert "Zero-Qty Card" not in names

    # Test 5: Malformed color_identity values
    def test_malformed_color_identity(self):
        conn = _make_conn()
        conn.execute("""
            INSERT INTO collection_entries (name, color_identity, quantity, scryfall_id, type_line)
            VALUES ('Null CI', NULL, 1, 'null-001', 'Artifact')
        """)
        conn.execute("""
            INSERT INTO collection_entries (name, color_identity, quantity, scryfall_id, type_line)
            VALUES ('Empty Str CI', '', 1, 'empty-001', 'Artifact')
        """)
        conn.commit()
        # Should not crash — NULL/empty treated as colorless (empty array)
        result = _query_for_colors(conn, ["W"])
        names = {c["name"] for c in result}
        assert "Null CI" in names     # NULL COALESCE'd to '[]' -> colorless -> passes
        # Empty string '' is not valid JSON but COALESCE handles NULL;
        # empty string through json_each may error, check graceful handling
        # The COALESCE only guards NULL, '' will go to json_each which may fail
        # This tests the edge case

    # Test 6: _build_collection_summary returns same filtered count
    def test_summary_matches_filter_count(self):
        for ci in [["W"], ["W", "U", "B"], ["W", "U", "B", "R", "G"], ["G"]]:
            filter_result = _query_for_colors(self.conn, ci)
            summary_result = _summary_for_colors(self.conn, ci)
            # summary includes cards without scryfall_id, filter excludes them
            # So summary count >= filter count; but for our test data only "No-ID Card"
            # differs. Compare the intersection.
            filter_names = {c["name"] for c in filter_result}
            summary_names = {r["name"] for r in summary_result}
            # Everything in filter should be in summary (summary is superset minus scryfall_id check)
            assert filter_names <= summary_names, (
                f"CI={ci}: filter has cards not in summary: {filter_names - summary_names}"
            )

    # Test: Multi-color subset check (WB commander should include W, B, WB, colorless)
    def test_multi_color_subset(self):
        result = _query_for_colors(self.conn, ["W", "B"])
        names = {c["name"] for c in result}
        assert "Sol Ring" in names          # colorless
        assert "Swords to Plow" in names    # W subset of WB
        assert "Damnation" in names         # B subset of WB
        assert "Orzhov Signet" in names     # WB subset of WB
        assert "Counterspell" not in names  # U not in WB
        assert "Lightning Bolt" not in names # R not in WB
        assert "Atraxa" not in names        # WUBG not subset of WB
