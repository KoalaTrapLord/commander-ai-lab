"""
routes/import_routes.py
=======================
Deck import & commander meta endpoints:
  POST /api/lab/import/url
  POST /api/lab/import/text
  GET  /api/lab/meta/commanders
  GET  /api/lab/meta/search
  POST /api/lab/meta/fetch
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from routes.shared import (
    COMMANDER_META,
    ImportUrlRequest,
    ImportTextRequest,
    MetaFetchRequest,
    _import_from_url,
    _parse_text_decklist,
    _save_profile_to_dck,
    _fetch_edhrec_average,
    log,
)

router = APIRouter(tags=["import"])


@router.post("/api/lab/import/url")
async def import_from_url(req: ImportUrlRequest):
    """Import a deck from Archidekt or EDHREC URL. Returns parsed DeckProfile + saves .dck file."""
    url = req.url.strip()
    try:
        profile = _import_from_url(url)
        dck_path = _save_profile_to_dck(profile)
        return {
            "success": True,
            "deckName": profile["name"],
            "commander": profile["commander"],
            "source": profile["source"],
            "sourceUrl": profile["sourceUrl"],
            "totalCards": profile["totalCards"],
            "dckFile": dck_path.stem,
            "colorIdentity": profile.get("colorIdentity", []),
            "archetype": profile.get("archetype"),
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/api/lab/import/text")
async def import_from_text(req: ImportTextRequest):
    """Import a deck from plain text card list."""
    try:
        profile = _parse_text_decklist(req.text, req.commander)
        dck_path = _save_profile_to_dck(profile)
        return {
            "success": True,
            "deckName": profile["name"],
            "commander": profile["commander"],
            "source": "Text Import",
            "totalCards": profile["totalCards"],
            "dckFile": dck_path.stem,
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/api/lab/meta/commanders")
async def list_meta_commanders():
    """List available commanders in the meta mapping."""
    commanders = []
    for name, entries in COMMANDER_META.items():
        entry = entries[0] if entries else {}
        commanders.append({
            "name": name,
            "archetype": entry.get("archetype", ""),
            "colorIdentity": entry.get("colorIdentity", []),
            "source": entry.get("source", "edhrec"),
        })
    return {"commanders": commanders}


@router.get("/api/lab/meta/search")
async def search_meta_commanders(q: str = ""):
    """Search commanders by partial name match."""
    query = q.lower()
    matches = []
    for name, entries in COMMANDER_META.items():
        if query in name.lower():
            entry = entries[0] if entries else {}
            matches.append({
                "name": name,
                "archetype": entry.get("archetype", ""),
                "colorIdentity": entry.get("colorIdentity", []),
            })
    return {"results": matches}


@router.post("/api/lab/meta/fetch")
async def fetch_meta_deck(req: MetaFetchRequest):
    """Fetch EDHREC average deck for a commander and save as .dck file."""
    try:
        profile = _fetch_edhrec_average(req.commander)
        dck_path = _save_profile_to_dck(profile)
        return {
            "success": True,
            "deckName": profile["name"],
            "commander": profile["commander"],
            "source": "EDHREC Average",
            "sourceUrl": profile.get("sourceUrl", ""),
            "totalCards": profile["totalCards"],
            "dckFile": dck_path.stem,
            "colorIdentity": profile.get("colorIdentity", []),
            "sampleSize": profile.get("sampleSize"),
        }
    except Exception as e:
        raise HTTPException(400, f"Failed to fetch meta deck for '{req.commander}': {str(e)}")


# ══════════════════════════════════════════════════════════════
# Existing Endpoints (v1/v2)
# ══════════════════════════════════════════════════════════════
