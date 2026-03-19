"""
EDHrec JSON client for the Commander AI Deck Builder.

Fetches commander recommendations, top cards, and synergy data
from EDHrec's public JSON API (json.edhrec.com).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import requests

from ..core.models import CardEntry

logger = logging.getLogger(__name__)

BASE_URL = "https://json.edhrec.com/pages"
HEADERS = {
    "User-Agent": "CommanderAI-DeckBuilder/0.1 (github.com/KoalaTrapLord/commander-ai-lab)",
}


def _slugify(name: str) -> str:
    """Convert a commander name to an EDHrec URL slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[',.]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def _get_json(path: str) -> Optional[Dict]:
    """Fetch JSON from EDHrec, returning None on failure."""
    url = f"{BASE_URL}/{path}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except (requests.HTTPError, requests.ConnectionError, ValueError) as e:
        logger.warning(f"EDHrec fetch failed for {url}: {e}")
        return None


# ── commander page ───────────────────────────────────────────────
def get_commander_data(commander_name: str) -> Optional[Dict]:
    """
    Fetch the full EDHrec commander page JSON.

    Returns the raw dict with keys like 'cardlists', 'container', etc.
    """
    slug = _slugify(commander_name)
    return _get_json(f"commanders/{slug}")


def get_recommended_cards(commander_name: str) -> List[CardEntry]:
    """
    Get EDHrec's recommended cards for a commander.

    Returns CardEntry objects with edhrec_rank populated from
    the 'num_decks' / inclusion percentage.
    """
    data = get_commander_data(commander_name)
    if not data:
        return []

    cards: List[CardEntry] = []
    cardlists = data.get("container", {}).get("json_dict", {}).get("cardlists", [])

    for cardlist in cardlists:
        header = cardlist.get("header", "uncategorized").lower()
        category = _map_edhrec_category(header)

        for card_data in cardlist.get("cardviews", []):
            name = card_data.get("name", "")
            if not name:
                continue

            cards.append(
                CardEntry(
                    name=name,
                    category=category,
                    color_identity=set(card_data.get("color_identity", [])),
                    cmc=card_data.get("cmc", 0.0),
                    type_line=card_data.get("type_line"),
                    edhrec_rank=card_data.get("num_decks"),
                    source="edhrec",
                )
            )

    return cards


# ── top cards by color identity ──────────────────────────────────
def get_top_cards_by_colors(colors: str) -> List[CardEntry]:
    """
    Fetch top EDHrec cards for a color combination.

    Args:
        colors: e.g. "wub", "rg", "wubrg", "colorless"
    """
    data = _get_json(f"commanders/{colors.lower()}")
    if not data:
        return []

    cards: List[CardEntry] = []
    card_list = data.get("container", {}).get("json_dict", {}).get("cardlists", [])
    for cardlist in card_list:
        for card_data in cardlist.get("cardviews", []):
            name = card_data.get("name", "")
            if name:
                cards.append(
                    CardEntry(
                        name=name,
                        color_identity=set(card_data.get("color_identity", [])),
                        edhrec_rank=card_data.get("num_decks"),
                        source="edhrec",
                    )
                )
    return cards


# ── average deck ─────────────────────────────────────────────────
def get_average_deck(commander_name: str) -> List[CardEntry]:
    """
    Fetch the EDHrec 'average deck' for a commander.

    This is the most common 99 cards people play with this commander.
    """
    slug = _slugify(commander_name)
    data = _get_json(f"average-decks/{slug}")
    if not data:
        return []

    cards: List[CardEntry] = []
    deck_data = data.get("container", {}).get("json_dict", {})

    for card_data in deck_data.get("cardlists", [{}]):
        for cv in card_data.get("cardviews", []):
            name = cv.get("name", "")
            if name:
                cards.append(
                    CardEntry(
                        name=name,
                        color_identity=set(cv.get("color_identity", [])),
                        edhrec_rank=cv.get("num_decks"),
                        source="edhrec",
                    )
                )

    return cards


# ── category mapper ──────────────────────────────────────────────
def _map_edhrec_category(header: str) -> str:
    """Map EDHrec section headers to our deck categories."""
    header = header.lower()
    mapping = {
        "ramp": "ramp",
        "mana": "ramp",
        "land": "lands",
        "lands": "lands",
        "draw": "card_draw",
        "card draw": "card_draw",
        "card advantage": "card_draw",
        "removal": "removal",
        "interaction": "removal",
        "board wipe": "removal",
        "wipe": "removal",
        "protection": "protection",
        "counter": "protection",
        "win": "wincon",
        "finisher": "wincon",
        "combo": "wincon",
    }
    for keyword, category in mapping.items():
        if keyword in header:
            return category
    return "synergy"
