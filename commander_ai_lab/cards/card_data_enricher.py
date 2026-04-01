"""
Phase 0 — card_data_enricher.py

Injects art_url and art_url_back into card data dicts/DTOs
before they are broadcast to Unity via WebSocket.

Used by:
    - Phase 1 game_state_parser.py  (enriches cards in GameStateDTO)
    - Phase 3 WebSocket handler     (enriches full game state before broadcast)

Lookup chain per card:
    1. scryfall_id present  -> ImageCache.lookup_by_id()
    2. scryfall_id absent   -> ImageCache.lookup_by_name()  (Forge card name)
    3. Both fail            -> Scryfall CDN fallback URL
    4. CDN fallback absent  -> empty string (Unity shows card back texture)

See issue #167
"""
from __future__ import annotations

import logging
from typing import Any

from commander_ai_lab.cards.image_cache import get_image_cache, ImageCacheResult

log = logging.getLogger("commander_ai_lab.cards.card_data_enricher")

# Scryfall CDN fallback when both local cache and DB are unavailable
_CDN_FRONT = "https://cards.scryfall.io/normal/front/{d1}/{d2}/{sid}.jpg"
_CDN_BACK = "https://cards.scryfall.io/normal/back/{d1}/{d2}/{sid}.jpg"


def _cdn_fallback_urls(scryfall_id: str) -> tuple[str, str | None]:
    if not scryfall_id:
        return "", None
    d1 = scryfall_id[0]
    d2 = scryfall_id[1] if len(scryfall_id) > 1 else "0"
    front = _CDN_FRONT.format(d1=d1, d2=d2, sid=scryfall_id)
    back = _CDN_BACK.format(d1=d1, d2=d2, sid=scryfall_id)
    return front, back


def enrich_card(card: dict[str, Any]) -> dict[str, Any]:
    """
    Inject art_url and art_url_back into a single card dict.
    Mutates in place AND returns the card for convenience.

    Input card dict is expected to have at minimum:
        - 'name': str  (card name from Forge)
        - 'scryfall_id': str (optional but preferred)

    After enrichment the card will have:
        - 'art_url': str           front face image URL
        - 'art_url_back': str|None back face image URL (DFCs only)
        - 'has_back': bool
    """
    # Skip if already enriched
    if card.get("art_url"):
        return card

    cache = get_image_cache()
    result: ImageCacheResult | None = None

    scryfall_id = card.get("scryfall_id", "")
    if scryfall_id:
        result = cache.lookup_by_id(scryfall_id)

    if result is None:
        name = card.get("name", "")
        if name:
            result = cache.lookup_by_name(name)

    if result is not None:
        card["art_url"] = result.front_url
        card["art_url_back"] = result.back_url
        card["has_back"] = result.has_back
    else:
        # Hard fallback: build CDN URL from scryfall_id if available
        front, back = _cdn_fallback_urls(scryfall_id)
        card["art_url"] = front
        card["art_url_back"] = back if back else None
        card["has_back"] = False
        if not front:
            log.warning("No art URL resolved for card: %s (id=%s)", card.get("name"), scryfall_id)

    return card


def enrich_card_list(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich a list of card dicts. Mutates in place."""
    for card in cards:
        enrich_card(card)
    return cards


def enrich_game_state(state: dict[str, Any]) -> dict[str, Any]:
    """
    Enrich all card lists in a full GameStateDTO dict.
    Walks all players and all zones: hand, battlefield, graveyard, exile, command_zone.
    Mutates in place AND returns state.
    """
    zone_keys = ("hand", "battlefield", "graveyard", "exile", "command_zone")

    for player in state.get("players", []):
        for zone in zone_keys:
            cards = player.get(zone)
            if isinstance(cards, list):
                enrich_card_list(cards)

    # Also enrich the stack
    for stack_item in state.get("stack", []):
        card = stack_item.get("card")
        if isinstance(card, dict):
            enrich_card(card)

    return state
