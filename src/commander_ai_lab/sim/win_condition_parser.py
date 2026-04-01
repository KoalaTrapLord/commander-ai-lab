"""
Commander AI Lab — Alternate Win Condition Parser
==================================================
Scans Forge log lines or oracle text for non-combat "you win the game"
triggers and returns a win type category string.

Used by:
  - services/forge_runner.py  (Java batch path: post-process log_lines)
  - src/commander_ai_lab/sim/deepseek_engine.py  (DeepSeek path: check oracle text)
  - src/commander_ai_lab/sim/engine.py  (Python sim path: check oracle text)
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Alternate win card registry
# ---------------------------------------------------------------------------
# Maps lowercase card name -> win category.
# Categories: "Combo", "Drain", "Mill", "Poison"
# "Combat" is the default and should never appear here.

ALTERNATE_WIN_CARDS: dict[str, str] = {
    # Spell-based
    "approach of the second sun": "Combo",
    "thassa's oracle": "Combo",
    "jace, wielder of mysteries": "Combo",
    "laboratory maniac": "Combo",
    "leveler": "Combo",          # pairs with Lab Man / Thassa
    "gleemax": "Combo",
    "coalition victory": "Combo",
    "helix pinnacle": "Combo",
    "mayael's aria": "Combo",
    "mechanized production": "Combo",
    "happily ever after": "Combo",
    "simic ascendancy": "Combo",
    "azor's elocutors": "Combo",
    "chance encounter": "Combo",
    "darksteel reactor": "Combo",
    "hellkite tyrant": "Combo",
    "mortal kombat": "Combo",
    "revel in riches": "Drain",
    "test of endurance": "Combo",
    "felidar sovereign": "Combo",
    "celestial convergence": "Combo",
    "barren glory": "Combo",
    "maze's end": "Combo",
    "new horizons": "Combo",
    "thespian's stage": "Combo",   # copying Maze's End
    # Poison / Infect
    "phyrexian unlife": "Poison",
    "poisoned tips": "Poison",
    # Mill
    "milling": "Mill",             # generic tag
    "the fall of lord karsus": "Mill",
}

# ---------------------------------------------------------------------------
# Forge log scanner
# ---------------------------------------------------------------------------

# Matches lines like:
#   [COMBAT-LINE] Resolve Stack: Approach of the Second Sun ... you win the game.
#   [OUTCOME-LINE] ... you win the game ...
#   Game Result: Player won (Approach of the Second Sun)
_YOU_WIN_RE = re.compile(
    r'you win the game',
    re.IGNORECASE,
)

# Extracts a card name from the line so we can look it up in ALTERNATE_WIN_CARDS.
# Forge typically formats these as "Resolve Stack: <CardName> ..." or
# "Player won via <CardName>".
_CARD_NAME_RE = re.compile(
    r'(?:Resolve Stack|via|won by|triggered by|winning card)[:\s]+([A-Za-z\'\,\.\- ]+)',
    re.IGNORECASE,
)


def detect_win_type_from_log(log_lines: list[str]) -> str:
    """
    Scan a list of Forge stdout log lines for alternate win condition triggers.

    Returns the win category ("Combo", "Drain", "Mill", "Poison") if an
    alternate win card is detected, otherwise returns "Combat".

    Scans *all* lines so the last detected alternate win takes precedence
    (handles edge cases where the log mentions multiple near-wins).
    """
    result = "Combat"
    for line in log_lines:
        if not _YOU_WIN_RE.search(line):
            continue
        # Try to extract the card name responsible
        m = _CARD_NAME_RE.search(line)
        if m:
            card_name = m.group(1).strip().rstrip('.').lower()
            # Exact lookup first
            if card_name in ALTERNATE_WIN_CARDS:
                result = ALTERNATE_WIN_CARDS[card_name]
                continue
            # Partial / substring match for long card names
            for known, category in ALTERNATE_WIN_CARDS.items():
                if known in card_name or card_name in known:
                    result = category
                    break
        else:
            # No card name found but "you win the game" is present —
            # scan the full line for any known card name
            line_lower = line.lower()
            for known, category in ALTERNATE_WIN_CARDS.items():
                if known in line_lower:
                    result = category
                    break
    return result


# ---------------------------------------------------------------------------
# Oracle text scanner (Python / DeepSeek engine path)
# ---------------------------------------------------------------------------

def detect_win_type_from_cards(cards_on_battlefield: list) -> str:
    """
    Inspect a player's battlefield (list of Card objects) for alternate win
    permanents. Returns the win category or "Combat".

    Checks:
      1. Card name against ALTERNATE_WIN_CARDS (fastest)
      2. oracle_text for "you win the game" as a safety net
    """
    for card in cards_on_battlefield:
        name_lower = getattr(card, 'name', '').lower()
        if name_lower in ALTERNATE_WIN_CARDS:
            return ALTERNATE_WIN_CARDS[name_lower]
        oracle = getattr(card, 'oracle_text', '') or ''
        if 'you win the game' in oracle.lower():
            # Unknown alternate win card — still not Combat
            return "Combo"
    return "Combat"


def detect_win_type_from_oracle(oracle_text: str, card_name: str = "") -> str:
    """
    Simple oracle text probe used when we have a resolved spell/ability
    but not a full battlefield list.
    """
    if card_name:
        lookup = card_name.strip().lower()
        if lookup in ALTERNATE_WIN_CARDS:
            return ALTERNATE_WIN_CARDS[lookup]
    if 'you win the game' in (oracle_text or '').lower():
        return "Combo"
    return "Combat"
