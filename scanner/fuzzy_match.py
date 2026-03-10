"""
Card Scanner — Fuzzy Name Matcher
═══════════════════════════════════

Corrects garbled OCR text by matching against a local dictionary of
known MTG card names using edit distance (Levenshtein).

This runs BEFORE the Scryfall lookup so the API receives a clean name
instead of raw OCR garbage.

The dictionary is built from:
  1. All card names already in the user's collection DB
  2. A downloadable Scryfall bulk list (oracle-cards) for full coverage
"""
import json
import os
import time
from pathlib import Path
from typing import Optional, List, Tuple
from urllib.request import Request, urlopen

# ── Edit distance (Levenshtein) ─────────────────────────────

def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            ins = prev_row[j + 1] + 1
            dele = curr_row[j] + 1
            sub = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(ins, dele, sub))
        prev_row = curr_row
    return prev_row[-1]


def _normalized_distance(a: str, b: str) -> float:
    """Edit distance normalized by length of the longer string. 0.0 = identical."""
    maxlen = max(len(a), len(b))
    if maxlen == 0:
        return 0.0
    return _levenshtein(a, b) / maxlen


# ── Card Name Dictionary ────────────────────────────────────

class CardNameDict:
    """
    An in-memory dictionary of known MTG card names for fuzzy matching.
    Names are stored lowercased for comparison. Originals preserved for output.
    """

    def __init__(self):
        self._names: dict[str, str] = {}  # lowercase -> original casing
        self._loaded = False
        self._bulk_path: Optional[Path] = None

    @property
    def size(self) -> int:
        return len(self._names)

    def add_name(self, name: str):
        """Add a single card name."""
        key = name.lower().strip()
        if key and len(key) >= 2:
            self._names[key] = name.strip()

    def add_names(self, names):
        """Add multiple card names."""
        for n in names:
            if n:
                self.add_name(n)

    def load_from_collection_db(self, db_path: str):
        """Load card names from the collection SQLite database."""
        import sqlite3
        try:
            if not os.path.exists(db_path):
                return
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT DISTINCT name FROM collection_entries WHERE name != ''").fetchall()
            for r in rows:
                self.add_name(r["name"])
            # Also load from card_records (enrichment cache)
            try:
                rows2 = conn.execute("SELECT DISTINCT name FROM card_records WHERE name != ''").fetchall()
                for r in rows2:
                    self.add_name(r["name"])
            except Exception:
                pass
            conn.close()
            print(f"    [FUZZY] Loaded {self.size} card names from collection DB")
        except Exception as e:
            print(f"    [FUZZY] Error loading collection DB: {e}")

    def load_bulk_names(self, cache_dir: str):
        """
        Load the Scryfall oracle-cards bulk data for comprehensive name coverage.
        Downloads once and caches locally as a simple name list.
        """
        cache_path = Path(cache_dir) / "card_names_cache.json"
        self._bulk_path = cache_path

        # Use cached file if fresh (< 7 days)
        if cache_path.exists():
            age_days = (time.time() - cache_path.stat().st_mtime) / 86400
            if age_days < 7:
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        names = json.load(f)
                    self.add_names(names)
                    print(f"    [FUZZY] Loaded {len(names)} names from cache (age: {age_days:.1f} days)")
                    self._loaded = True
                    return
                except Exception:
                    pass

        # Download the bulk name catalog from Scryfall
        try:
            print("    [FUZZY] Downloading Scryfall card name catalog...")
            url = "https://api.scryfall.com/catalog/card-names"
            req = Request(url, headers={"User-Agent": "CommanderAILab/1.0", "Accept": "application/json"})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            names = data.get("data", [])
            if names:
                self.add_names(names)
                # Cache to disk
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(names, f)
                print(f"    [FUZZY] Downloaded and cached {len(names)} card names")
                self._loaded = True
        except Exception as e:
            print(f"    [FUZZY] Could not download card names: {e}")

    def find_best_match(self, ocr_text: str, max_distance: float = 0.35) -> Optional[str]:
        """
        Find the closest known card name to the OCR text.

        Returns the corrected name, or None if no good match found.
        max_distance: maximum normalized edit distance (0.35 = up to 35% different)
        """
        if not self._names or not ocr_text:
            return None

        query = ocr_text.lower().strip()
        if not query:
            return None

        # Exact match
        if query in self._names:
            return self._names[query]

        # Quick prefix/contains check
        for key, original in self._names.items():
            if key.startswith(query) or query.startswith(key):
                # Close enough in length?
                if abs(len(key) - len(query)) <= 3:
                    return original

        # Full edit distance search
        # Optimization: only check names within a reasonable length range
        qlen = len(query)
        min_len = max(2, int(qlen * 0.6))
        max_len = int(qlen * 1.5) + 3

        best_name = None
        best_dist = float("inf")

        for key, original in self._names.items():
            klen = len(key)
            if klen < min_len or klen > max_len:
                continue

            # Quick character overlap check before expensive edit distance
            common = len(set(query) & set(key))
            all_chars = len(set(query) | set(key))
            if all_chars > 0 and common / all_chars < 0.4:
                continue

            dist = _normalized_distance(query, key)
            if dist < best_dist:
                best_dist = dist
                best_name = original

        if best_name and best_dist <= max_distance:
            return best_name

        return None

    def find_top_matches(self, ocr_text: str, n: int = 5, max_distance: float = 0.45) -> List[Tuple[str, float]]:
        """
        Find the top N closest matches with their distances.
        Returns list of (card_name, distance) tuples, sorted by distance.
        """
        if not self._names or not ocr_text:
            return []

        query = ocr_text.lower().strip()
        qlen = len(query)
        min_len = max(2, int(qlen * 0.55))
        max_len = int(qlen * 1.5) + 3

        matches = []
        for key, original in self._names.items():
            klen = len(key)
            if klen < min_len or klen > max_len:
                continue
            dist = _normalized_distance(query, key)
            if dist <= max_distance:
                matches.append((original, dist))

        matches.sort(key=lambda x: x[1])
        return matches[:n]


# ── Singleton ───────────────────────────────────────────────

_dict_instance: Optional[CardNameDict] = None


def get_card_dict() -> CardNameDict:
    """Get or create the singleton CardNameDict."""
    global _dict_instance
    if _dict_instance is None:
        _dict_instance = CardNameDict()
    return _dict_instance


def init_card_dict(db_path: str, cache_dir: str):
    """Initialize the card name dictionary from DB + Scryfall bulk."""
    d = get_card_dict()
    d.load_from_collection_db(db_path)
    d.load_bulk_names(cache_dir)
    return d
