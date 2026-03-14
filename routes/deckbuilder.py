"""
routes/deckbuilder.py
=====================
Deck Builder endpoints:
  POST   /api/decks
  GET    /api/decks
  GET    /api/decks/{deck_id}
  PUT    /api/decks/{deck_id}
  DELETE /api/decks/{deck_id}
  DELETE /api/decks
  GET    /api/decks/{deck_id}/cards
  POST   /api/decks/{deck_id}/cards
  DELETE /api/decks/{deck_id}/cards/{card_id}
  PATCH  /api/decks/{deck_id}/cards/{card_id}
  GET    /api/decks/{deck_id}/analysis
  GET    /api/decks/{deck_id}/recommended-from-collection
  GET    /api/decks/{deck_id}/edh-recs
  POST   /api/decks/{deck_id}/bulk-add
  POST   /api/decks/{deck_id}/bulk-add-recommended
  POST   /api/decks/{deck_id}/export-to-sim
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from routes.shared import get as _get

router = APIRouter(prefix="/api/decks", tags=["deckbuilder"])


# ---------------------------------------------------------------------------
# Deck CRUD
# ---------------------------------------------------------------------------

@router.post("")
async def create_deck(body: dict):
    fn = _get("create_deck")
    return await fn(body)


@router.get("")
async def list_decks_db():
    fn = _get("list_decks_db")
    return await fn()


@router.get("/{deck_id}")
async def get_deck(deck_id: int):
    fn = _get("get_deck")
    return await fn(deck_id)


@router.put("/{deck_id}")
async def update_deck(deck_id: int, body: dict):
    fn = _get("update_deck")
    return await fn(deck_id, body)


@router.delete("/{deck_id}")
async def delete_deck(deck_id: int):
    fn = _get("delete_deck")
    return await fn(deck_id)


@router.delete("")
async def delete_all_decks():
    fn = _get("delete_all_decks")
    return await fn()


# ---------------------------------------------------------------------------
# Deck card manipulation
# ---------------------------------------------------------------------------

@router.get("/{deck_id}/cards")
async def get_deck_cards(deck_id: int):
    fn = _get("get_deck_cards")
    return await fn(deck_id)


@router.post("/{deck_id}/cards")
async def add_deck_card(deck_id: int, body: dict):
    fn = _get("add_deck_card")
    return await fn(deck_id, body)


@router.delete("/{deck_id}/cards/{card_id}")
async def remove_deck_card(deck_id: int, card_id: int):
    fn = _get("remove_deck_card")
    return await fn(deck_id, card_id)


@router.patch("/{deck_id}/cards/{card_id}")
async def patch_deck_card(deck_id: int, card_id: int, body: dict):
    fn = _get("patch_deck_card")
    return await fn(deck_id, card_id, body)


# ---------------------------------------------------------------------------
# Analysis + recommendations
# ---------------------------------------------------------------------------

@router.get("/{deck_id}/analysis")
async def deck_analysis(deck_id: int):
    fn = _get("deck_analysis")
    return await fn(deck_id)


@router.get("/{deck_id}/recommended-from-collection")
async def recommend_from_collection(
    deck_id: int,
    max_results: int = 20,
    roles: Optional[str] = None,
):
    fn = _get("recommend_from_collection")
    return await fn(deck_id, max_results=max_results, roles=roles)


@router.get("/{deck_id}/edh-recs")
async def deck_edh_recs(
    deck_id: int,
    only_owned: bool = False,
    max_results: int = 30,
):
    fn = _get("deck_edh_recs")
    return await fn(deck_id, only_owned=only_owned, max_results=max_results)


# ---------------------------------------------------------------------------
# Bulk add
# ---------------------------------------------------------------------------

@router.post("/{deck_id}/bulk-add")
async def bulk_add_cards(deck_id: int, body: dict):
    fn = _get("bulk_add_cards")
    return await fn(deck_id, body)


@router.post("/{deck_id}/bulk-add-recommended")
async def bulk_add_recommended(deck_id: int, body: dict):
    fn = _get("bulk_add_recommended")
    return await fn(deck_id, body)


# ---------------------------------------------------------------------------
# Simulation export
# ---------------------------------------------------------------------------

@router.post("/{deck_id}/export-to-sim")
async def export_deck_to_sim(deck_id: int):
    fn = _get("export_deck_to_sim")
    return await fn(deck_id)
