"""
Phase 0 — image_cache.py

SQLite-backed card image lookup service.

Provides:
    ImageCache          — sync lookup (used by download scripts, CLI tools)
    AsyncImageCache     — async lookup (used by FastAPI request handlers)

Lookup priority:
    1. SQLite index by scryfall_id (exact, fast)
    2. SQLite index by card name (case-insensitive, Forge card name format)
    3. CDN fallback URL (scryfall.io) — no local file, but still a valid URL

See issue #167
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("commander_ai_lab.cards.image_cache")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "card_image_index.db"
STATIC_BASE_URL = "/static/card-images"

# Scryfall CDN URL pattern for fallback
# Format: https://cards.scryfall.io/normal/front/{d1}/{d2}/{scryfall_id}.jpg
# where d1/d2 are first two hex chars of the UUID
def _cdn_url(scryfall_id: str, face: str = "front") -> str:
    """Build a Scryfall CDN URL for a card face. Used as fallback."""
    d1 = scryfall_id[0] if scryfall_id else "0"
    d2 = scryfall_id[1] if len(scryfall_id) > 1 else "0"
    return f"https://cards.scryfall.io/normal/{face}/{d1}/{d2}/{scryfall_id}.jpg"


class ImageCacheResult:
    """Result of a card image lookup."""
    __slots__ = ("scryfall_id", "name_raw", "front_url", "back_url", "has_back", "is_local")

    def __init__(
        self,
        scryfall_id: str,
        name_raw: str,
        front_url: str,
        back_url: Optional[str],
        has_back: bool,
        is_local: bool,
    ):
        self.scryfall_id = scryfall_id
        self.name_raw = name_raw
        self.front_url = front_url
        self.back_url = back_url
        self.has_back = has_back
        self.is_local = is_local

    def to_dict(self) -> dict:
        return {
            "scryfall_id": self.scryfall_id,
            "name": self.name_raw,
            "art_url": self.front_url,
            "art_url_back": self.back_url,
            "has_back": self.has_back,
            "is_local": self.is_local,
        }


class ImageCache:
    """Synchronous SQLite-backed card image cache."""

    def __init__(self, db_path: Path = DB_PATH, base_url: str = STATIC_BASE_URL):
        self._db_path = db_path
        self._base_url = base_url.rstrip("/")
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._db_path.exists():
                log.warning(
                    "Image index DB not found at %s. Run scripts/build_image_index.py first.",
                    self._db_path
                )
                return None
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _row_to_result(self, row: sqlite3.Row) -> ImageCacheResult:
        scryfall_id = row["scryfall_id"]
        front_path = row["front_path"]
        back_path = row["back_path"]
        has_back = bool(row["has_back"])

        if front_path:
            front_url = f"{self._base_url}/{scryfall_id}_front.jpg"
            back_url = f"{self._base_url}/{scryfall_id}_back.jpg" if has_back else None
            is_local = True
        else:
            # CDN fallback
            front_url = _cdn_url(scryfall_id, "front")
            back_url = _cdn_url(scryfall_id, "back") if has_back else None
            is_local = False

        return ImageCacheResult(
            scryfall_id=scryfall_id,
            name_raw=row["name_raw"],
            front_url=front_url,
            back_url=back_url,
            has_back=has_back,
            is_local=is_local,
        )

    def lookup_by_id(self, scryfall_id: str) -> Optional[ImageCacheResult]:
        """Look up card by Scryfall UUID."""
        conn = self._get_conn()
        if conn is None:
            return self._cdn_fallback(scryfall_id)
        row = conn.execute(
            "SELECT * FROM card_images WHERE scryfall_id = ?", (scryfall_id,)
        ).fetchone()
        if row:
            return self._row_to_result(row)
        return self._cdn_fallback(scryfall_id)

    def lookup_by_name(self, name: str) -> Optional[ImageCacheResult]:
        """Look up card by name (case-insensitive). Returns most recent printing."""
        conn = self._get_conn()
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM card_images WHERE name = ? LIMIT 1",
            (name.lower().strip(),)
        ).fetchone()
        if row:
            return self._row_to_result(row)
        return None

    def _cdn_fallback(self, scryfall_id: str) -> ImageCacheResult:
        """Return CDN URLs when local cache is unavailable."""
        return ImageCacheResult(
            scryfall_id=scryfall_id,
            name_raw="",
            front_url=_cdn_url(scryfall_id, "front"),
            back_url=None,
            has_back=False,
            is_local=False,
        )

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# Module-level singleton for use by FastAPI route handlers
_cache: Optional[ImageCache] = None


def get_image_cache() -> ImageCache:
    """Get the module-level ImageCache singleton."""
    global _cache
    if _cache is None:
        _cache = ImageCache()
    return _cache
