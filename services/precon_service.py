"""Precon deck download, caching, and conversion logic."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path
from urllib.request import urlopen, Request

log = logging.getLogger("commander_ai_lab.api")

# Fallback default — used only when CFG.precon_dir has not been resolved yet.
_DEFAULT_PRECON_DIR = Path(__file__).parent.parent / "precon-decks"

PRECON_INDEX: list[dict] = []
GITHUB_PRECON_URL = (
    "https://raw.githubusercontent.com/taw/magic-preconstructed-decks-data/"
    "master/decks_v2.json"
)
PRECON_CACHE_HOURS = 168


def _get_precon_dir() -> Path:
    """Return the active precon-decks directory from CFG, with fallback."""
    from models.state import CFG
    if CFG.precon_dir:
        return Path(CFG.precon_dir)
    return _DEFAULT_PRECON_DIR


# Re-export for backwards compat — callers that import PRECON_DIR at module
# level will get the default.  Runtime code should call _get_precon_dir().
PRECON_DIR = _DEFAULT_PRECON_DIR


def load_precon_index():
    global PRECON_INDEX
    precon_dir = _get_precon_dir()
    idx_path = precon_dir / "precon-index.json"
    if idx_path.exists():
        with open(idx_path, "r", encoding="utf-8") as f:
            PRECON_INDEX = json.load(f)
        log.info(f"  Precons: {len(PRECON_INDEX)} precon decks loaded")
    else:
        PRECON_INDEX = []
        log.info(f"  Precons: index not found at {idx_path}")


def _sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = safe.replace(' ', '_').replace("'", '').replace('!', '')
    return re.sub(r'_+', '_', safe).strip('_')


def _deck_to_dck(deck_data: dict) -> str:
    lines = ["[metadata]", f"Name={deck_data['name']}"]
    commanders = deck_data.get('commander', [])
    if commanders:
        lines.append("[Commander]")
        for card in commanders:
            lines.append(f"{card.get('count', 1)} {card['name']}")
    cards = deck_data.get('cards', [])
    if cards:
        lines.append("[Main]")
        for card in cards:
            lines.append(f"{card.get('count', 1)} {card['name']}")
    sideboard = deck_data.get('sideboard', [])
    if sideboard:
        lines.append("[Sideboard]")
        for card in sideboard:
            lines.append(f"{card.get('count', 1)} {card['name']}")
    return "\n".join(lines) + "\n"


def download_precon_database(force: bool = False) -> dict:
    global PRECON_INDEX
    precon_dir = _get_precon_dir()
    idx_path = precon_dir / "precon-index.json"
    if not force and idx_path.exists():
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if len(existing) > 50:
                age_hours = (time.time() - idx_path.stat().st_mtime) / 3600
                if age_hours < PRECON_CACHE_HOURS:
                    log.info(f"  Precons: {len(existing)} decks cached ({age_hours:.0f}h old)")
                    PRECON_INDEX = existing
                    return {"downloaded": 0, "skipped": True, "total": len(existing), "error": None}
        except Exception:
            pass
    log.info("  Precons: Downloading full precon database from GitHub...")
    try:
        req = Request(GITHUB_PRECON_URL, headers={"User-Agent": "CommanderAILab/3.0"})
        with urlopen(req, timeout=120) as resp:
            all_decks = json.loads(resp.read())
    except Exception as e:
        msg = f"Failed to download precon database: {e}"
        log.error(f"  Precons: ERROR - {msg}")
        if idx_path.exists():
            load_precon_index()
        return {"downloaded": 0, "skipped": False, "error": msg}
    commander_decks = [
        d for d in all_decks
        if d.get('type') == 'Commander Deck'
        and (d.get('format') or '').lower() == 'commander'
    ]
    log.info(f"  Precons: Found {len(commander_decks)} Commander precon decks")
    precon_dir.mkdir(parents=True, exist_ok=True)
    name_counts = Counter(_sanitize_filename(d['name']) for d in commander_decks)
    dup_names = {n for n, c in name_counts.items() if c > 1}
    index = []
    written = 0
    for deck in sorted(commander_decks, key=lambda d: (d.get('release_date', ''), d.get('name', ''))):
        safe_name = _sanitize_filename(deck['name'])
        if safe_name in dup_names:
            sc = (deck.get('set_code') or 'unk').upper()
            safe_name = f"{safe_name}_{sc}"
        file_name = f"{safe_name}.dck"
        dck_path = precon_dir / file_name
        commanders = deck.get('commander', [])
        cmdr_names = [c['name'] for c in commanders] if commanders else []
        total_cards = sum(c.get('count', 1) for c in deck.get('cards', [])) + sum(c.get('count', 1) for c in commanders)
        with open(dck_path, "w", encoding="utf-8") as f:
            f.write(_deck_to_dck(deck))
        written += 1
        release = deck.get('release_date', '')
        year = int(release[:4]) if release and len(release) >= 4 else 0
        index.append({
            "name": deck['name'], "commander": cmdr_names[0] if cmdr_names else "Unknown",
            "commanders": cmdr_names, "colors": [],
            "set": deck.get('set_name', ''), "setCode": deck.get('set_code', ''),
            "year": year, "releaseDate": release, "theme": "",
            "fileName": file_name, "cardCount": total_cards,
        })
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    PRECON_INDEX = index
    log.info(f"  Precons: {written} .dck files written, index saved")
    return {"downloaded": written, "skipped": False, "total": written, "error": None}
