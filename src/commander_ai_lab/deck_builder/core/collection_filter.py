"""
Collection filter for the Commander AI Deck Builder.

Loads a user's card collection from CSV and filters candidate
cards to only those the user owns (collection-only mode).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from .models import CardEntry

logger = logging.getLogger(__name__)


def load_collection(path: str) -> Dict[str, int]:
    """
    Load a card collection from CSV.

    Expected CSV columns: name, quantity, [set_code]
    Returns a dict of card_name -> quantity.
    """
    collection: Dict[str, int] = {}
    csv_path = Path(path)

    if not csv_path.exists():
        logger.error(f"Collection file not found: {path}")
        return collection

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue
            qty = int(row.get("quantity", 1))
            # Accumulate quantities (user may have multiple entries)
            collection[name] = collection.get(name, 0) + qty

    logger.info(f"Loaded collection: {len(collection)} unique cards from {path}")
    return collection


def get_collection_names(path: str) -> Set[str]:
    """Load collection and return just the set of card names."""
    return set(load_collection(path).keys())


def filter_by_collection(
    cards: List[CardEntry],
    collection_path: str,
) -> List[CardEntry]:
    """
    Filter a list of CardEntry objects to only those in the collection.

    Cards not found in the collection are removed.
    """
    collection = load_collection(collection_path)
    if not collection:
        logger.warning("Empty collection — returning all cards unfiltered")
        return cards

    filtered = []
    for card in cards:
        if card.name in collection:
            filtered.append(card)
        else:
            logger.debug(f"Filtered out (not in collection): {card.name}")

    logger.info(
        f"Collection filter: {len(filtered)}/{len(cards)} cards matched"
    )
    return filtered


def filter_names_by_collection(
    names: List[str],
    collection_path: str,
) -> List[str]:
    """Filter a list of card name strings to only those in the collection."""
    owned = get_collection_names(collection_path)
    return [n for n in names if n in owned]
