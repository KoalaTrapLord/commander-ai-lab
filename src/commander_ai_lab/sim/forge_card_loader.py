"""
Forge Card Loader
=================
Parse Forge cardsfolder .txt files into structured data for sim enrichment.
Lazy-loaded and cached at module level.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from models.state import CFG

_log = logging.getLogger(__name__)


@dataclass
class ForgeCardData:
    """Structured representation of a single Forge .txt card definition."""
    name: str = ""
    mana_cost: str = ""
    cmc: int = 0
    type_line: str = ""
    oracle_text: str = ""
    pt: str = ""
    keywords: list[str] = field(default_factory=list)
    trigger_modes: list[str] = field(default_factory=list)
    has_replacement_effect: bool = False
    has_static_ability: bool = False


# -- Module-level lazy cache ---
_FORGE_CACHE: dict[str, ForgeCardData] = {}
_FORGE_CACHE_LOADED: bool = False


def _get_cards_folder() -> Path:
    """Resolve the Forge cardsfolder directory from CFG.forge_dir."""
    if not CFG.forge_dir:
        return Path("")
    return Path(CFG.forge_dir) / "forge-gui" / "res" / "cardsfolder"


def _parse_forge_file(filepath: Path) -> Optional[ForgeCardData]:
    """Parse a single Forge .txt card file into ForgeCardData."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    data = ForgeCardData()
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Name
        if line.startswith("Name:"):
            data.name = line.split(":", 1)[1].strip()
        # ManaCost
        elif line.startswith("ManaCost:"):
            raw = line.split(":", 1)[1].strip()
            data.mana_cost = raw
            data.cmc = _calc_cmc(raw)
        # Types
        elif line.startswith("Types:"):
            data.type_line = line.split(":", 1)[1].strip()
        # PT
        elif line.startswith("PT:"):
            data.pt = line.split(":", 1)[1].strip()
        # Oracle
        elif line.startswith("Oracle:"):
            data.oracle_text = line.split(":", 1)[1].strip()
        # K -- Keywords
        elif line.startswith("K:"):
            kw = line.split(":", 1)[1].strip()
            if kw and kw not in data.keywords:
                data.keywords.append(kw)
        # T -- Trigger modes (e.g. T:Mode$ ChangesZone)
        elif line.startswith("T:"):
            mode_match = re.search(r"Mode\$\s*(\w+)", line)
            if mode_match:
                mode = mode_match.group(1)
                if mode not in data.trigger_modes:
                    data.trigger_modes.append(mode)
        # R -- Replacement effects
        elif line.startswith("R:"):
            data.has_replacement_effect = True
        # S -- Static abilities
        elif line.startswith("S:"):
            data.has_static_ability = True
        # SVar (secondary -- grab Oracle from SVar if not set)
        elif line.startswith("SVar:") and not data.oracle_text:
            if "Oracle:" in line:
                oracle_part = line.split("Oracle:", 1)[1].strip()
                data.oracle_text = oracle_part

    return data if data.name else None


def _calc_cmc(mana_cost: str) -> int:
    """Calculate CMC from Forge mana cost string like '2 W U'."""
    total = 0
    for part in mana_cost.split():
        part = part.strip().upper()
        if not part:
            continue
        if part.isdigit():
            total += int(part)
        elif part == "X":
            continue
        else:
            total += 1
    return total


def _load_forge_cache() -> None:
    """Walk the Forge cardsfolder and cache every card by lowercase name."""
    global _FORGE_CACHE_LOADED
    if _FORGE_CACHE_LOADED:
        return

    cards_folder = _get_cards_folder()
    if not cards_folder.is_dir():
        _log.warning("Forge cardsfolder not found at %s", cards_folder)
        _FORGE_CACHE_LOADED = True
        return

    count = 0
    for root, _dirs, files in os.walk(cards_folder):
        for fname in files:
            if not fname.endswith(".txt"):
                continue
            fpath = Path(root) / fname
            parsed = _parse_forge_file(fpath)
            if parsed and parsed.name:
                _FORGE_CACHE[parsed.name.lower()] = parsed
                count += 1

    _log.info("Forge card cache loaded: %d cards from %s", count, cards_folder)
    _FORGE_CACHE_LOADED = True


def lookup_forge_card(card_name: str) -> Optional[ForgeCardData]:
    """Look up a card by name from the Forge cache. Returns None on miss."""
    _load_forge_cache()
    return _FORGE_CACHE.get((card_name or "").lower().strip())
