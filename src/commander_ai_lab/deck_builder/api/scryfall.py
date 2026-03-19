"""
Scryfall API client for the Commander AI Deck Builder.

Provides card lookup, commander search, and color-identity-filtered
card queries using the free Scryfall REST API.
Rate-limited to 50ms between requests per Scryfall's guidelines.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

import requests

from ..core.models import CardEntry

BASE_URL = "https://api.scryfall.com"
_last_request_time: float = 0.0
REQUEST_DELAY = 0.1  # 100ms between requests (Scryfall asks for 50-100ms)


def _throttle() -> None:
    """Respect Scryfall rate limits."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def _get(endpoint: str, params: Optional[Dict] = None) -> Dict:
    """Make a throttled GET request to Scryfall."""
    _throttle()
    resp = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── card lookup ──────────────────────────────────────────────────
def get_card_by_name(name: str) -> Optional[CardEntry]:
    """Look up a single card by exact or fuzzy name."""
    try:
        data = _get("/cards/named", {"fuzzy": name})
        return _parse_card(data)
    except requests.HTTPError:
        return None


def get_card_by_id(scryfall_id: str) -> Optional[CardEntry]:
    """Look up a single card by Scryfall UUID."""
    try:
        data = _get(f"/cards/{scryfall_id}")
        return _parse_card(data)
    except requests.HTTPError:
        return None


# ── commander search ─────────────────────────────────────────────
def search_commander(name: str) -> Optional[CardEntry]:
    """Find a legendary creature / commander by name."""
    try:
        data = _get("/cards/named", {"fuzzy": name})
        type_line = data.get("type_line", "")
        if "Legendary" not in type_line:
            return None
        return _parse_card(data)
    except requests.HTTPError:
        return None


# ── search cards by color identity ───────────────────────────────
def search_cards_by_identity(
    color_identity: Set[str],
    query_extra: str = "",
    max_results: int = 100,
) -> List[CardEntry]:
    """
    Search Scryfall for cards within a commander's color identity.

    Uses the `id<=` operator so results only include cards whose
    color identity is a subset of the commander's.

    Args:
        color_identity: e.g. {"W", "U", "B"}
        query_extra: additional Scryfall search syntax (e.g. 't:creature')
        max_results: cap on total cards returned
    """
    ci_str = "".join(sorted(color_identity)) if color_identity else "C"
    q = f"id<={ci_str} f:commander"
    if query_extra:
        q += f" {query_extra}"

    cards: List[CardEntry] = []
    params = {"q": q, "order": "edhrec", "dir": "asc"}

    try:
        data = _get("/cards/search", params)
    except requests.HTTPError:
        return cards

    while True:
        for item in data.get("data", []):
            cards.append(_parse_card(item))
            if len(cards) >= max_results:
                return cards

        if not data.get("has_more"):
            break

        # Scryfall provides next_page URL directly
        next_url = data.get("next_page")
        if not next_url:
            break
        _throttle()
        resp = requests.get(next_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

    return cards


# ── search by category (typed helpers) ───────────────────────────
def search_ramp(color_identity: Set[str], max_results: int = 30) -> List[CardEntry]:
    """Find mana ramp cards within color identity."""
    return search_cards_by_identity(
        color_identity,
        query_extra='(t:artifact o:"add" o:mana) or (t:creature o:"add" o:mana) or (t:enchantment o:"add" o:mana) or (t:sorcery o:land o:"search")',
        max_results=max_results,
    )


def search_removal(color_identity: Set[str], max_results: int = 30) -> List[CardEntry]:
    """Find removal cards within color identity."""
    return search_cards_by_identity(
        color_identity,
        query_extra='(o:destroy or o:exile or o:"-/-") -t:land',
        max_results=max_results,
    )


def search_card_draw(color_identity: Set[str], max_results: int = 30) -> List[CardEntry]:
    """Find card draw / card advantage cards."""
    return search_cards_by_identity(
        color_identity,
        query_extra='(o:"draw a card" or o:"draw cards" or o:"draw two" or o:"draw three")',
        max_results=max_results,
    )


def search_lands(color_identity: Set[str], max_results: int = 45) -> List[CardEntry]:
    """Find lands within color identity."""
    return search_cards_by_identity(
        color_identity,
        query_extra="t:land",
        max_results=max_results,
    )


# ── bulk name lookup (collection matching) ───────────────────────
def get_cards_by_names(names: List[str]) -> List[CardEntry]:
    """
    Batch-lookup cards by name using Scryfall's /cards/collection endpoint.
    Accepts up to 75 names per request.
    """
    cards: List[CardEntry] = []
    for i in range(0, len(names), 75):
        batch = names[i : i + 75]
        identifiers = [{"name": n} for n in batch]
        _throttle()
        resp = requests.post(
            f"{BASE_URL}/cards/collection",
            json={"identifiers": identifiers},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            cards.append(_parse_card(item))
    return cards


# ── parser ───────────────────────────────────────────────────────
def _parse_card(data: Dict) -> CardEntry:
    """Convert a Scryfall JSON card object into a CardEntry."""
    return CardEntry(
        name=data.get("name", "Unknown"),
        color_identity=set(data.get("color_identity", [])),
        mana_cost=data.get("mana_cost"),
        cmc=data.get("cmc", 0.0),
        type_line=data.get("type_line"),
        scryfall_id=data.get("id"),
        edhrec_rank=data.get("edhrec_rank"),
        source="scryfall",
    )
