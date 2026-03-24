"""
routes/precon.py
================
Precon deck management endpoints:
  GET  /api/lab/precons
  POST /api/lab/precons/install
  POST /api/lab/precons/install-batch
  POST /api/lab/precons/refresh
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from models.state import CFG
from services.precon_service import download_precon_database, PRECON_INDEX, _get_precon_dir
from services.logging import log

router = APIRouter(tags=["precon"])


@router.get("/api/lab/precons")
async def list_precons():
    """List all available precon decks."""
    return {"precons": PRECON_INDEX}


@router.post("/api/lab/precons/install")
async def install_precon(req: dict):
    """Install a precon deck to the Forge decks directory.
    Body: {"fileName": "Elven_Empire.dck"} or {"name": "Elven_Empire.dck"}
    """
    file_name = req.get("fileName", "") or req.get("name", "")
    if not file_name:
        raise HTTPException(400, "fileName is required")

    src = _get_precon_dir() / file_name
    if not src.exists():
        raise HTTPException(404, f"Precon not found: {file_name}")

    decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        raise HTTPException(500, f"Forge decks directory not found: {decks_dir}")

    dst = Path(decks_dir) / file_name
    shutil.copy2(str(src), str(dst))

    deck_name = file_name.replace(".dck", "")
    return {
        "installed": True,
        "deckName": deck_name,
        "destination": str(dst),
        "message": f"Installed {deck_name} to Forge decks",
    }


@router.post("/api/lab/precons/install-batch")
async def install_precons_batch(req: dict):
    """Install multiple precon decks at once.
    Body: {"fileNames": ["Elven_Empire.dck", ...]} or {"names": ["Elven_Empire.dck", ...]}
    """
    file_names = req.get("fileNames", []) or req.get("names", [])
    if not file_names:
        raise HTTPException(400, "fileNames list is required")

    decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        raise HTTPException(500, f"Forge decks directory not found: {decks_dir}")

    results = []
    for file_name in file_names:
        src = _get_precon_dir() / file_name
        if not src.exists():
            results.append({"fileName": file_name, "installed": False, "error": "not found"})
            continue
        dst = Path(decks_dir) / file_name
        shutil.copy2(str(src), str(dst))
        deck_name = file_name.replace(".dck", "")
        results.append({"fileName": file_name, "installed": True, "deckName": deck_name})

    return {"results": results}


@router.post("/api/lab/precons/refresh")
async def refresh_precons():
    """Force re-download of all Commander precon decks from GitHub."""
    result = download_precon_database(force=True)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return {
        "message": f"Downloaded {result['downloaded']} Commander precon decks",
        "total": result.get("total", 0),
    }
