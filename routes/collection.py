"""
routes/collection.py
====================
Collection management endpoints:
  GET    /api/collection
  GET    /api/collection/export
  GET    /api/collection/sets
  GET    /api/collection/keywords
  POST   /api/collection/import
  GET    /api/collection/{cardId}
  PATCH  /api/collection/{cardId}
  GET    /api/cache/scryfall
  DELETE /api/cache/scryfall
  POST   /api/cache/scryfall/evict
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from routes.shared import get as _get

router = APIRouter(tags=["collection"])


# ---------------------------------------------------------------------------
# Collection list / search
# ---------------------------------------------------------------------------

@router.get("/api/collection")
async def list_collection(
    page: int = 1,
    pageSize: int = 50,
    q: Optional[str] = None,
    sortField: Optional[str] = None,
    sortDir: Optional[str] = None,
    colors: Optional[str] = None,
    types: Optional[str] = None,
    isLegendary: Optional[bool] = None,
    isBasic: Optional[bool] = None,
    isGameChanger: Optional[bool] = None,
    highSalt: Optional[bool] = None,
    finish: Optional[str] = None,
    cmcMin: Optional[float] = None,
    cmcMax: Optional[float] = None,
    priceMin: Optional[float] = None,
    priceMax: Optional[float] = None,
    category: Optional[str] = None,
    deck_id: Optional[int] = None,
    rarity: Optional[str] = None,
    setCode: Optional[str] = None,
    powerMin: Optional[str] = None,
    powerMax: Optional[str] = None,
    toughMin: Optional[str] = None,
    toughMax: Optional[str] = None,
    keyword: Optional[str] = None,
    edhrecMin: Optional[int] = None,
    edhrecMax: Optional[int] = None,
    qtyMin: Optional[int] = None,
    qtyMax: Optional[int] = None,
):
    fn = _get("list_collection")
    return await fn(
        page=page, pageSize=pageSize, q=q, sortField=sortField, sortDir=sortDir,
        colors=colors, types=types, isLegendary=isLegendary, isBasic=isBasic,
        isGameChanger=isGameChanger, highSalt=highSalt, finish=finish,
        cmcMin=cmcMin, cmcMax=cmcMax, priceMin=priceMin, priceMax=priceMax,
        category=category, deck_id=deck_id, rarity=rarity, setCode=setCode,
        powerMin=powerMin, powerMax=powerMax, toughMin=toughMin, toughMax=toughMax,
        keyword=keyword, edhrecMin=edhrecMin, edhrecMax=edhrecMax,
        qtyMin=qtyMin, qtyMax=qtyMax,
    )


@router.get("/api/collection/export")
async def export_collection(
    format: str = "INTERNAL_CSV",
    q: Optional[str] = None,
    colors: Optional[str] = None,
    types: Optional[str] = None,
    isLegendary: Optional[bool] = None,
    isBasic: Optional[bool] = None,
    isGameChanger: Optional[bool] = None,
    highSalt: Optional[bool] = None,
    finish: Optional[str] = None,
    cmcMin: Optional[float] = None,
    cmcMax: Optional[float] = None,
    priceMin: Optional[float] = None,
    priceMax: Optional[float] = None,
    category: Optional[str] = None,
):
    fn = _get("export_collection")
    return await fn(
        format=format, q=q, colors=colors, types=types,
        isLegendary=isLegendary, isBasic=isBasic, isGameChanger=isGameChanger,
        highSalt=highSalt, finish=finish, cmcMin=cmcMin, cmcMax=cmcMax,
        priceMin=priceMin, priceMax=priceMax, category=category,
    )


@router.get("/api/collection/sets")
async def collection_sets():
    fn = _get("collection_sets")
    return await fn()


@router.get("/api/collection/keywords")
async def collection_keywords():
    fn = _get("collection_keywords")
    return await fn()


@router.post("/api/collection/import")
async def import_collection(body: dict):
    fn = _get("import_collection")
    return await fn(body)


@router.get("/api/collection/{cardId}")
async def get_collection_card(cardId: int):
    fn = _get("get_collection_card")
    return await fn(cardId)


@router.patch("/api/collection/{cardId}")
async def update_collection_card(cardId: int, body: dict):
    fn = _get("update_collection_card")
    return await fn(cardId, body)


# ---------------------------------------------------------------------------
# Scryfall cache management
# ---------------------------------------------------------------------------

@router.get("/api/cache/scryfall")
async def scryfall_cache_stats():
    fn = _get("scryfall_cache_stats")
    return await fn()


@router.delete("/api/cache/scryfall")
async def scryfall_cache_clear():
    fn = _get("scryfall_cache_clear")
    return await fn()


@router.post("/api/cache/scryfall/evict")
async def scryfall_cache_evict_expired():
    fn = _get("scryfall_cache_evict_expired")
    return await fn()
