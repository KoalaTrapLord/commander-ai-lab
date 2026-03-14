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

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from routes.shared import get as _get

router = APIRouter(prefix="/api/lab", tags=["precon"])


@router.get("/precons")
async def list_precons():
    """List all available precon decks."""
    PRECON_INDEX = _get("PRECON_INDEX")
    return {"precons": PRECON_INDEX}


@router.post("/precons/install")
async def install_precon(req: dict):
    """Install a precon deck to the Forge decks directory."""
    PRECON_DIR = _get("PRECON_DIR")
    CFG = _get("CFG")
    import os
    file_name = req.get("fileName", "")
    if not file_name:
        raise HTTPException(400, "fileName is required")
    src = PRECON_DIR / file_name
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


@router.post("/precons/install-batch")
async def install_precons_batch(req: dict):
    """Install multiple precon decks at once."""
    PRECON_DIR = _get("PRECON_DIR")
    CFG = _get("CFG")
    import os
    file_names = req.get("fileNames", [])
    if not file_names:
        raise HTTPException(400, "fileNames list is required")
    decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        raise HTTPException(500, f"Forge decks directory not found: {decks_dir}")
    results = []
    for file_name in file_names:
        src = PRECON_DIR / file_name
        if not src.exists():
            results.append({"fileName": file_name, "installed": False, "error": "not found"})
            continue
        dst = Path(decks_dir) / file_name
        shutil.copy2(str(src), str(dst))
        deck_name = file_name.replace(".dck", "")
        results.append({"fileName": file_name, "installed": True, "deckName": deck_name})
    return {"results": results}


@router.post("/precons/refresh")
async def refresh_precons():
    """Force re-download of all Commander precon decks from GitHub."""
    download_precon_database = _get("download_precon_database")
    result = download_precon_database(force=True)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return {
        "message": f"Downloaded {result['downloaded']} Commander precon decks",
        "total": result.get("total", 0),
    }
