#!/usr/bin/env python3
"""
Phase 0 — download_card_images.py

Bulk-downloads all MTG card images from Scryfall's default_cards bulk export.
Stores images at:  static/card-images/{scryfall_id}_front.jpg
                   static/card-images/{scryfall_id}_back.jpg  (DFCs only)

Usage:
    python scripts/download_card_images.py
    python scripts/download_card_images.py --image-size normal
    python scripts/download_card_images.py --workers 8 --resume

Scryfall bulk image domain has no rate limits, so no sleep is needed.
See: https://scryfall.com/docs/api/bulk-data
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

log = logging.getLogger("download_card_images")

SCRYFALL_BULK_API = "https://api.scryfall.com/bulk-data/default-cards"
DEFAULT_IMAGE_SIZE = "normal"  # 488x680px — ideal for Unity card rendering
DEFAULT_WORKERS = 6
PLACEHOLDER_URL = "https://cards.scryfall.io/normal/front/0/0/placeholder.jpg"

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "static" / "card-images"


def fetch_bulk_download_url(image_size: str) -> str:
    """Get the Scryfall bulk data download URL for default_cards."""
    log.info("Fetching Scryfall bulk data manifest...")
    with urllib.request.urlopen(SCRYFALL_BULK_API, timeout=30) as resp:
        meta = json.loads(resp.read())
    return meta["download_uri"]


def load_bulk_data(download_url: str) -> list[dict]:
    """Stream-download and parse the bulk JSON (can be ~100MB)."""
    log.info("Downloading bulk card data from %s ...", download_url)
    with urllib.request.urlopen(download_url, timeout=120) as resp:
        cards = json.loads(resp.read())
    log.info("Loaded %d card entries.", len(cards))
    return cards


def get_image_jobs(cards: list[dict], image_size: str, resume: bool) -> list[tuple[str, str]]:
    """
    Build a list of (url, dest_path) tuples to download.
    Handles:
      - Single-faced cards: {scryfall_id}_front.jpg
      - Double-faced cards (DFCs): {scryfall_id}_front.jpg + {scryfall_id}_back.jpg
      - Tokens: uses image_uris if present, else skips gracefully
    """
    jobs: list[tuple[str, str]] = []

    for card in cards:
        scryfall_id = card.get("id", "")
        if not scryfall_id:
            continue

        # Single-faced or meld cards
        if "image_uris" in card:
            url = card["image_uris"].get(image_size)
            if url:
                dest = str(OUTPUT_DIR / f"{scryfall_id}_front.jpg")
                if not resume or not Path(dest).exists():
                    jobs.append((url, dest))

        # Double-faced cards (DFCs): modal, transform, adventure, etc.
        elif "card_faces" in card:
            for idx, face in enumerate(card["card_faces"]):
                face_uris = face.get("image_uris", {})
                url = face_uris.get(image_size)
                if url:
                    side = "front" if idx == 0 else "back"
                    dest = str(OUTPUT_DIR / f"{scryfall_id}_{side}.jpg")
                    if not resume or not Path(dest).exists():
                        jobs.append((url, dest))

    return jobs


def download_image(url: str, dest: str) -> tuple[bool, str]:
    """Download a single image. Returns (success, dest)."""
    try:
        urllib.request.urlretrieve(url, dest)
        return True, dest
    except Exception as exc:
        log.warning("Failed to download %s -> %s: %s", url, dest, exc)
        return False, dest


def run_downloads(jobs: list[tuple[str, str]], workers: int) -> tuple[int, int]:
    """Download all jobs concurrently. Returns (success_count, fail_count)."""
    success = 0
    fail = 0

    iterator = tqdm(total=len(jobs), unit="img", desc="Downloading") if tqdm else None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_image, url, dest): dest for url, dest in jobs}
        for future in as_completed(futures):
            ok, _ = future.result()
            if ok:
                success += 1
            else:
                fail += 1
            if iterator:
                iterator.update(1)

    if iterator:
        iterator.close()

    return success, fail


def main():
    parser = argparse.ArgumentParser(description="Bulk download Scryfall card images.")
    parser.add_argument("--image-size", default=DEFAULT_IMAGE_SIZE,
                        choices=["small", "normal", "large", "png", "art_crop", "border_crop"],
                        help="Image size to download (default: normal = 488x680px)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="Concurrent download threads (default: 6)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip images that already exist on disk")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Output directory: %s", OUTPUT_DIR)

    download_url = fetch_bulk_download_url(args.image_size)
    cards = load_bulk_data(download_url)
    jobs = get_image_jobs(cards, args.image_size, args.resume)

    log.info("Jobs to download: %d (resume=%s)", len(jobs), args.resume)
    if not jobs:
        log.info("Nothing to do. All images already present.")
        return

    success, fail = run_downloads(jobs, args.workers)
    log.info("Done. Success: %d  Failed: %d  Total: %d", success, fail, len(jobs))
    if fail > 0:
        log.warning("%d images failed — re-run with --resume to retry.", fail)
        sys.exit(1)


if __name__ == "__main__":
    main()
