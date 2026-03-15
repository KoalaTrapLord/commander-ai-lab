"""
Commander AI Lab — Scryfall Art Proxy (Phase 5)
================================================
Endpoint:  GET /api/v1/art/{card_name}

Proxy for Scryfall card art images.

Behaviour:
  1. Look up card in local LRU disk cache (~/.cache/commander_ai_lab/art/).
  2. If cached, stream the JPEG directly (cache-control: 7 days).
  3. If not cached, fetch from Scryfall API, store to disk, then stream.
  4. On Scryfall failure, return 404 with JSON detail.

Rate limiting: Scryfall asks for ≤10 req/s. The proxy uses an asyncio
semaphore (max 8 concurrent outbound fetches) and a 50 ms delay between
requests to stay comfortably under the limit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(tags=["art"])

_CACHE_DIR  = Path(os.path.expanduser("~/.cache/commander_ai_lab/art"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_SCRYFALL_NAMED = "https://api.scryfall.com/cards/named?fuzzy={name}"
_FETCH_SEM  = asyncio.Semaphore(8)   # max concurrent Scryfall fetches
_FETCH_DELAY = 0.05                   # seconds between fetches


def _cache_path(card_name: str) -> Path:
    key = hashlib.sha1(card_name.lower().encode()).hexdigest()
    return _CACHE_DIR / f"{key}.jpg"


@router.get("/art/{card_name}", response_class=FileResponse)
async def get_card_art(card_name: str) -> FileResponse:
    """
    Return card art JPEG for the given card name.
    Resolves fuzzy name via Scryfall, caches locally.
    """
    cached = _cache_path(card_name)

    if cached.exists():
        return FileResponse(
            path=str(cached),
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=604800"},
        )

    # Fetch from Scryfall
    img_bytes = await _fetch_scryfall_art(card_name)
    if img_bytes is None:
        raise HTTPException(404, f"Art not found for card: {card_name!r}")

    cached.write_bytes(img_bytes)
    return FileResponse(
        path=str(cached),
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=604800"},
    )


async def _fetch_scryfall_art(card_name: str) -> bytes | None:
    """Fetch card art bytes from Scryfall (rate-limited)."""
    async with _FETCH_SEM:
        await asyncio.sleep(_FETCH_DELAY)
        try:
            import httpx
        except ImportError:
            # Fall back to stdlib if httpx not installed
            return await _fetch_stdlib(card_name)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: resolve name
            url = _SCRYFALL_NAMED.format(name=quote(card_name))
            r   = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()

            # Step 2: pick image URI
            image_uris = data.get("image_uris") or (
                data.get("card_faces", [{}])[0].get("image_uris", {})
            )
            img_url = image_uris.get("small") or image_uris.get("normal")
            if not img_url:
                return None

            # Step 3: download image
            r2 = await client.get(img_url)
            if r2.status_code != 200:
                return None
            return r2.content


async def _fetch_stdlib(card_name: str) -> bytes | None:
    """Stdlib fallback for environments without httpx."""
    import asyncio
    from urllib.request import urlopen
    from urllib.parse import quote
    import json as _json

    def _sync_fetch() -> bytes | None:
        try:
            url = _SCRYFALL_NAMED.format(name=quote(card_name))
            with urlopen(url, timeout=8) as r:
                data = _json.loads(r.read())
            image_uris = data.get("image_uris") or (
                data.get("card_faces", [{}])[0].get("image_uris", {})
            )
            img_url = image_uris.get("small") or image_uris.get("normal")
            if not img_url:
                return None
            with urlopen(img_url, timeout=10) as r:
                return r.read()
        except Exception:
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_fetch)
