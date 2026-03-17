"""
Moxfield Adapter
================
Fetches template decklists from Moxfield for a given commander.
Uses the undocumented but usable api2.moxfield.com API.
Rate-limited to <=10 req/sec. Errors are caught and logged.
"""
import logging
import time

import httpx

from .models import TemplateDeck, TemplateDeckCard

log = logging.getLogger("commander_ai_lab.deckgen.moxfield")

MOXFIELD_API = "https://api2.moxfield.com"
HEADERS = {
    "User-Agent": "CommanderAILab/1.0",
    "Accept": "application/json",
}
# Minimum seconds between requests (<=10 req/sec)
_RATE_LIMIT_DELAY = 0.12


def _slugify_commander(name: str) -> str:
    """Return the commander name as-is for the Moxfield search query."""
    return name.strip()


def _build_cards_from_deck(deck_data: dict) -> list:
    """Extract commander + mainboard cards from a full Moxfield deck response."""
    cards = []
    # Commanders first
    for card_name, card_obj in deck_data.get("commanders", {}).items():
        qty = card_obj.get("quantity", 1)
        cards.append(TemplateDeckCard(name=card_name, quantity=qty))
    # Mainboard
    for card_name, card_obj in deck_data.get("mainboard", {}).items():
        qty = card_obj.get("quantity", 1)
        cards.append(TemplateDeckCard(name=card_name, quantity=qty))
    return cards


def fetch_template_decks(
    commander_name: str,
    color_identity: list,
    config: dict = None,
) -> list:
    """
    Fetch top Commander decks from Moxfield for the given commander.

    Returns a list of TemplateDeck objects. Returns empty list on any
    API failure — errors are logged, never raised.

    Args:
        commander_name: The commander's card name.
        color_identity: List of color symbols (unused, kept for interface compat).
        config: Optional dict. Supported key: ``max_decks`` (default 3).

    Returns:
        List of TemplateDeck objects populated with commander + mainboard cards.
    """
    max_decks = (config or {}).get("max_decks", 3)
    results = []

    try:
        # Step 1 — Search for top decks by commander name
        search_url = f"{MOXFIELD_API}/v2/decks/search"
        params = {
            "q": "",
            "fmt": "commander",
            "commander": _slugify_commander(commander_name),
            "sortType": "views",
            "sortDirection": "Descending",
            "pageSize": max_decks,
        }
        log.info(f" Moxfield: Searching for '{commander_name}' (max={max_decks})")
        resp = httpx.get(search_url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        search_data = resp.json()

        deck_summaries = search_data.get("data", [])[:max_decks]
        if not deck_summaries:
            log.info(f" Moxfield: No decks found for '{commander_name}'")
            return []

        log.info(f" Moxfield: Found {len(deck_summaries)} deck(s) for '{commander_name}', fetching details...")

        # Step 2 — Fetch full detail for each deck
        for summary in deck_summaries:
            deck_id = summary.get("publicId")
            deck_name = summary.get("name", f"Moxfield {commander_name}")
            if not deck_id:
                log.warning(" Moxfield: Skipping deck with no publicId")
                continue

            time.sleep(_RATE_LIMIT_DELAY)  # Rate limit: <=10 req/sec

            try:
                deck_url = f"{MOXFIELD_API}/v3/decks/all/{deck_id}"
                deck_resp = httpx.get(deck_url, headers=HEADERS, timeout=15)
                deck_resp.raise_for_status()
                deck_data = deck_resp.json()
            except Exception as deck_err:
                log.warning(f" Moxfield: Failed to fetch deck '{deck_id}': {deck_err}")
                continue

            cards = _build_cards_from_deck(deck_data)
            if not cards:
                log.warning(f" Moxfield: Deck '{deck_name}' ({deck_id}) had no cards, skipping")
                continue

            results.append(TemplateDeck(
                name=f"{deck_name} (Moxfield)",
                source=f"https://moxfield.com/decks/{deck_id}",
                cards=cards,
            ))
            log.info(f" Moxfield: Added deck '{deck_name}' ({len(cards)} cards)")

        log.info(f" Moxfield: Returning {len(results)} deck(s) for '{commander_name}'")

    except httpx.HTTPStatusError as e:
        log.warning(
            f" Moxfield fetch failed for '{commander_name}': "
            f"HTTP {e.response.status_code} — {e}"
        )
    except httpx.RequestError as e:
        log.warning(f" Moxfield request error for '{commander_name}': {e}")
    except Exception as e:
        log.warning(f" Moxfield unexpected error for '{commander_name}': {e}")

    return results
