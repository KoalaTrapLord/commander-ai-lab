#!/usr/bin/env python3
"""
Phase 0 — build_image_index.py

Builds (or rebuilds) the SQLite card image index at:
    data/card_image_index.db

Schema:
    card_images(
        scryfall_id  TEXT PRIMARY KEY,
        name         TEXT NOT NULL,         -- card name, lowercased for lookup
        name_raw     TEXT NOT NULL,         -- original casing
        front_path   TEXT,                  -- relative path from project root
        back_path    TEXT,                  -- DFC back face, NULL for single-faced
        has_back     INTEGER DEFAULT 0      -- 1 if DFC
    )
    CREATE INDEX idx_name ON card_images(name);

Usage:
    python scripts/build_image_index.py
    python scripts/build_image_index.py --rebuild
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import urllib.request
from pathlib import Path

log = logging.getLogger("build_image_index")

SCRYFALL_BULK_API = "https://api.scryfall.com/bulk-data/default-cards"
PROJECT_ROOT = Path(__file__).parent.parent
IMAGE_DIR = PROJECT_ROOT / "static" / "card-images"
DB_PATH = PROJECT_ROOT / "data" / "card_image_index.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS card_images (
    scryfall_id  TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    name_raw     TEXT NOT NULL,
    front_path   TEXT,
    back_path    TEXT,
    has_back     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_name ON card_images(name);
"""


def fetch_bulk_cards() -> list[dict]:
    log.info("Fetching Scryfall bulk manifest...")
    with urllib.request.urlopen(SCRYFALL_BULK_API, timeout=30) as r:
        meta = json.loads(r.read())
    url = meta["download_uri"]
    log.info("Downloading bulk card data...")
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read())


def build_rows(cards: list[dict]) -> list[tuple]:
    """
    For each card, check if the image file(s) exist locally.
    Builds rows for both single-faced and DFC cards.
    Tokens are included if they have image files.
    """
    rows: list[tuple] = []

    for card in cards:
        scryfall_id = card.get("id", "")
        name_raw = card.get("name", "")
        if not scryfall_id or not name_raw:
            continue

        name = name_raw.lower().strip()

        front_file = IMAGE_DIR / f"{scryfall_id}_front.jpg"
        back_file = IMAGE_DIR / f"{scryfall_id}_back.jpg"

        front_path = f"static/card-images/{scryfall_id}_front.jpg" if front_file.exists() else None
        back_path = f"static/card-images/{scryfall_id}_back.jpg" if back_file.exists() else None
        has_back = 1 if back_path else 0

        rows.append((scryfall_id, name, name_raw, front_path, back_path, has_back))

    return rows


def write_db(rows: list[tuple], rebuild: bool) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if rebuild and DB_PATH.exists():
        DB_PATH.unlink()
        log.info("Deleted existing database for rebuild.")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(CREATE_TABLE_SQL)
        conn.executemany(
            """
            INSERT OR REPLACE INTO card_images
                (scryfall_id, name, name_raw, front_path, back_path, has_back)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows
        )
        conn.commit()
        log.info("Indexed %d cards into %s", len(rows), DB_PATH)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Build SQLite card image index.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and rebuild the database from scratch")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    cards = fetch_bulk_cards()
    log.info("Processing %d card entries...", len(cards))
    rows = build_rows(cards)
    log.info("Found %d cards with local images.", len(rows))
    write_db(rows, args.rebuild)
    log.info("Index build complete: %s", DB_PATH)


if __name__ == "__main__":
    main()
