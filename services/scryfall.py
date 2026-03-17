"""Scryfall API client and cache service."""
import json
import os
import sqlite3
import threading
import time
import datetime
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

# Lazy import to avoid circular dependency
def _detect_card_roles(oracle_text, type_line, keywords):
        from services.card_analysis import _detect_card_roles as _dcr
    return _dcr(oracle_text, type_line, keywords)


SCRYFALL_CACHE_DB_PATH = Path(__file__).parent.parent / "scryfall_cache.db"
SCRYFALL_CACHE_TTL_SECONDS = int(os.environ.get("SCRYFALL_CACHE_TTL", 7 * 24 * 3600))

_API_HEADERS = {"User-Agent": "CommanderAILab/3.0", "Accept": "application/json"}


class _ScryfallCache:
    def __init__(self, db_path: Path = None, ttl_seconds: int = None):
        self._db_path = db_path or SCRYFALL_CACHE_DB_PATH
        self._ttl = ttl_seconds or SCRYFALL_CACHE_TTL_SECONDS
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._hits = 0
        self._misses = 0
        self._init_db()

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

            def get(self, name: str, set_code: str = "", collector_number: str = "") -> Optional[dict]:
        key = self._make_key(name, set_code, collector_number)
        with self._lock:
            row = self._conn.execute(
                "SELECT json_blob FROM scryfall_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if row:
            self._hits += 1
            return json.loads(row[0])
        self._misses += 1
        return None

            def put(self, name: str, set_code: str, collector_number: str, data: dict):
        key = self._make_key(name, set_code, collector_number)
        blob = json.dumps(data)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO scryfall_cache (cache_key, json_blob) VALUES (?, ?)",
                (key, blob),
            )
            self._conn.commit()

                def stats(self) -> dict:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM scryfall_cache").fetchone()[0]
        return {"cached": count, "hits": self._hits, "misses": self._misses}

            def clear(self) -> int:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM scryfall_cache").fetchone()[0]
            self._conn.execute("DELETE FROM scryfall_cache")
            self._conn.commit()
            self._conn.execute("VACUUM")
            self._hits = 0; self._misses = 0
        return count

    def evict_expired(self) -> int:
        cutoff = datetime.datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "DELETE FROM scryfall_cache WHERE (julianday(?) - julianday(fetched_at)) * 86400 > ?",
                (cutoff, self._ttl),
            )
            deleted = self._conn.total_changes
            self._conn.commit()
        return deleted


        _scryfall_cache = _ScryfallCache()
_scryfall_lock = threading.Lock()
_scryfall_last_call = 0.0


def _scryfall_rate_limit():
    global _scryfall_last_call
    with _scryfall_lock:
        now = time.monotonic()
        elapsed = now - _scryfall_last_call
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        _scryfall_last_call = time.monotonic()


        def _fetch_scryfall_api(name: str, set_code: str = "", collector_number: str = "") -> dict:
    from urllib.parse import quote
    cached = _scryfall_cache.get(name, set_code, collector_number)
    if cached is not None:
        return cached
    card_data = None
    last_error = ""
    if set_code and collector_number:
        _scryfall_rate_limit()
        try:
            url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
            with urlopen(Request(url, headers=_API_HEADERS), timeout=10) as resp:
                card_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = str(e); card_data = None
    if not card_data:
        _scryfall_rate_limit()
        try:
            url = f"https://api.scryfall.com/cards/named?exact={quote(name)}"
            with urlopen(Request(url, headers=_API_HEADERS), timeout=10) as resp:
                card_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = str(e)
                if not card_data or card_data.get("object") == "error":
        err_detail = card_data.get("details", "unknown error") if card_data else last_error
        return {"_error": f"Scryfall returned error for '{name}': {err_detail}"}
    _scryfall_cache.put(name, set_code, collector_number, card_data)
    resolved_name = card_data.get("name", "")
    if resolved_name and resolved_name.lower() != name.strip().lower():
        _scryfall_cache.put(resolved_name, set_code, collector_number, card_data)
    return card_data


    def _enrich_from_scryfall(name: str, set_code: str = "", collector_number: str = "") -> dict:
    card_data = _fetch_scryfall_api(name, set_code, collector_number)
    if not card_data or "_error" in card_data:
        return card_data or {}
    type_line = card_data.get("type_line", "")
    color_identity = card_data.get("color_identity", [])
    keywords = card_data.get("keywords", [])
    subtypes = []
    for sep in [" \u2014 ", " - "]:
        if sep in type_line:
            subtypes = [s.strip() for s in type_line.split(sep, 1)[1].split() if s.strip()]
            break
    is_legendary = 1 if "Legendary" in type_line else 0
    is_basic = 1 if "Basic" in type_line else 0
    prices = card_data.get("prices", {})
    try:
        tcg_price = float(prices.get("usd") or prices.get("usd_foil") or "0") or 0.0
    except (ValueError, TypeError):
        tcg_price = 0.0
    oracle_text = card_data.get("oracle_text", "")
    if not oracle_text and card_data.get("card_faces"):
        oracle_text = "\n//\n".join(f.get("oracle_text", "") for f in card_data["card_faces"] if f.get("oracle_text"))
            power = card_data.get("power", "")
    toughness = card_data.get("toughness", "")
    if not power and card_data.get("card_faces"):
        power = card_data["card_faces"][0].get("power", "")
        toughness = card_data["card_faces"][0].get("toughness", "")
    mana_cost = card_data.get("mana_cost", "")
    if not mana_cost and card_data.get("card_faces"):
        mana_cost = card_data["card_faces"][0].get("mana_cost", "")
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


    def _scryfall_fuzzy_lookup(name: str) -> Optional[dict]:
    """Fuzzy-search Scryfall for a card name. Returns raw Scryfall JSON dict, or None on failure."""
    from urllib.parse import quote
    _scryfall_rate_limit()
    try:
        encoded = quote(name)
        url = f"https://api.scryfall.com/cards/named?fuzzy={encoded}"
        req = Request(url, headers=_API_HEADERS)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("object") == "error":
                return None
            return data
    except Exception:
        return None