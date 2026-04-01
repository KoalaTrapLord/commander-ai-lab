"""
Phase 0 — routes/card_art.py

FastAPI router for card art endpoints.

Endpoints:
    GET /card-art/{scryfall_id}
        Local-first image redirect.
        - If local file exists: redirect to /static/card-images/{id}_front.jpg
        - If not: redirect to Scryfall CDN (no 404, always returns an image)

    GET /card-art/{scryfall_id}/back
        Same as above but for the back face of DFCs.

    GET /api/card-image-info/{scryfall_id}
        JSON info: art_url, art_url_back, has_back, is_local

    GET /api/card-image-by-name/{name}
        Look up by card name (case-insensitive). Returns image info JSON.

See issue #167
"""
from __future__ import annotations

import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from commander_ai_lab.cards.image_cache import get_image_cache

router = APIRouter(tags=["card-art"])


@router.get("/card-art/{scryfall_id}")
async def get_card_art(scryfall_id: str):
    """
    Redirect to the front face image for a card.
    Always returns a redirect — never a 404.
    Local cache first, Scryfall CDN fallback.
    """
    cache = get_image_cache()
    result = cache.lookup_by_id(scryfall_id)
    if result:
        return RedirectResponse(url=result.front_url, status_code=302)
    # Ultimate fallback: redirect to CDN directly
    d1 = scryfall_id[0] if scryfall_id else "0"
    d2 = scryfall_id[1] if len(scryfall_id) > 1 else "0"
    cdn = f"https://cards.scryfall.io/normal/front/{d1}/{d2}/{scryfall_id}.jpg"
    return RedirectResponse(url=cdn, status_code=302)


@router.get("/card-art/{scryfall_id}/back")
async def get_card_art_back(scryfall_id: str):
    """
    Redirect to the back face image for a DFC.
    Falls back to CDN back URL if not locally cached.
    """
    cache = get_image_cache()
    result = cache.lookup_by_id(scryfall_id)
    if result and result.back_url:
        return RedirectResponse(url=result.back_url, status_code=302)
    d1 = scryfall_id[0] if scryfall_id else "0"
    d2 = scryfall_id[1] if len(scryfall_id) > 1 else "0"
    cdn = f"https://cards.scryfall.io/normal/back/{d1}/{d2}/{scryfall_id}.jpg"
    return RedirectResponse(url=cdn, status_code=302)


@router.get("/api/card-image-info/{scryfall_id}")
async def get_card_image_info(scryfall_id: str):
    """
    Return JSON image info for a card by Scryfall ID.
    Always returns a result (CDN fallback if not cached locally).
    """
    cache = get_image_cache()
    result = cache.lookup_by_id(scryfall_id)
    if result:
        return result.to_dict()
    raise HTTPException(status_code=404, detail=f"Card not found: {scryfall_id}")


@router.get("/api/card-image-by-name/{name}")
async def get_card_image_by_name(name: str):
    """
    Return JSON image info for a card by name (case-insensitive).
    Uses the SQLite index. Returns 404 if name not found.
    """
    decoded_name = urllib.parse.unquote(name)
    cache = get_image_cache()
    result = cache.lookup_by_name(decoded_name)
    if result:
        return result.to_dict()
    raise HTTPException(status_code=404, detail=f"Card name not found: {decoded_name}")
