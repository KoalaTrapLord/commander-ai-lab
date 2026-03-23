"""
tests/test_check_ownership_dedup.py
====================================
Unit tests for duplicate-card deduplication in
DeckGeneratorV3._check_ownership().

Uses an in-memory SQLite database so no real collection DB is required.
"""
from __future__ import annotations

import logging
import sqlite3
from unittest.mock import MagicMock

import pytest

from coach.services.deck_generator import DeckGeneratorV3


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    """Return a seeded in-memory DB matching the collection_entries schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE collection_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            scryfall_id TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            tcg_price REAL DEFAULT 0,
            type_line TEXT DEFAULT '',
            cmc REAL DEFAULT 0
        )
    """)
    cards = [
        ("Cultivate",    "cult-001", 2, 1.50, "Sorcery", 3),
        ("Sol Ring",     "sol-001",  1, 5.00, "Artifact", 0),
        ("Kodama's Reach", "kr-001", 1, 0.80, "Sorcery", 3),
    ]
    conn.executemany(
        "INSERT INTO collection_entries (name, scryfall_id, quantity, tcg_price, type_line, cmc) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        cards,
    )
    conn.commit()
    return conn


def _make_generator(conn: sqlite3.Connection) -> DeckGeneratorV3:
    """Build a DeckGeneratorV3 with a mock Perplexity client."""
    return DeckGeneratorV3(
        pplx_client=MagicMock(),
        db_conn_factory=lambda: conn,
    )


# ── Tests ────────────────────────────────────────────────────────────────────

class TestCheckOwnershipDedup:

    def setup_method(self):
        self.conn = _make_conn()
        self.gen = _make_generator(self.conn)

    def test_duplicate_cards_merged(self):
        """Duplicate card names should be merged into a single entry with summed count."""
        cards = [
            {"name": "Cultivate", "count": 1, "category": "Ramp"},
            {"name": "Sol Ring", "count": 1, "category": "Ramp"},
            {"name": "Cultivate", "count": 1, "category": "Ramp"},
        ]
        result = self.gen._check_ownership(cards)
        names = [c.name for c in result]

        # No duplicate names (case-insensitive)
        assert len(names) == len(set(n.lower() for n in names)), (
            f"Duplicate names found in output: {names}"
        )
        # Only 2 unique cards
        assert len(result) == 2

        # Merged count should be 2
        cultivate = next(c for c in result if c.name.lower() == "cultivate")
        assert cultivate.count == 2

    def test_case_insensitive_dedup(self):
        """Deduplication should be case-insensitive."""
        cards = [
            {"name": "cultivate", "count": 1, "category": "Ramp"},
            {"name": "CULTIVATE", "count": 1, "category": "Ramp"},
            {"name": "Cultivate", "count": 1, "category": "Ramp"},
        ]
        result = self.gen._check_ownership(cards)

        assert len(result) == 1
        assert result[0].count == 3

    def test_warning_logged_on_duplicate(self, caplog):
        """A WARNING log should be emitted when a duplicate is merged."""
        cards = [
            {"name": "Cultivate", "count": 1, "category": "Ramp"},
            {"name": "Cultivate", "count": 1, "category": "Ramp"},
        ]
        with caplog.at_level(logging.WARNING, logger="coach.deckgen"):
            self.gen._check_ownership(cards)

        assert any("Duplicate" in msg or "merged" in msg for msg in caplog.messages), (
            f"Expected WARNING about duplicate/merged, got: {caplog.messages}"
        )

    def test_no_duplicates_passes_through(self):
        """When there are no duplicates, all cards pass through normally."""
        cards = [
            {"name": "Cultivate", "count": 1, "category": "Ramp"},
            {"name": "Sol Ring", "count": 1, "category": "Ramp"},
            {"name": "Kodama's Reach", "count": 1, "category": "Ramp"},
        ]
        result = self.gen._check_ownership(cards)

        assert len(result) == 3
        assert all(c.count == 1 for c in result)

    def test_empty_name_skipped(self):
        """Cards with empty names should be silently skipped."""
        cards = [
            {"name": "", "count": 1},
            {"name": "Sol Ring", "count": 1, "category": "Ramp"},
        ]
        result = self.gen._check_ownership(cards)

        assert len(result) == 1
        assert result[0].name == "Sol Ring"
