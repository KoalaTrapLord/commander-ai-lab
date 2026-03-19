"""
Deck assembler – converts Ollama JSON output into validated CardEntry lists.

Responsible for parsing the structured JSON that Ollama returns after the
ratio-enforcement step and mapping card names back to Scryfall CardEntry
objects with correct categories.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

from .models import CardEntry

logger = logging.getLogger(__name__)


def parse_ollama_deck_json(raw: str) -> Dict[str, List[str]]:
    """Parse the JSON blob Ollama returns into {category: [card_names]}.

    Ollama is instructed to return JSON like::

        {
            "Creatures": ["Sol Ring", ...],
            "Instants": [...],
            ...
        }

    This function tolerates minor formatting issues (trailing commas,
    markdown fences, etc.).
    """
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (possibly ```json)
        first_nl = cleaned.index("\n")
        cleaned = cleaned[first_nl + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -3]
    cleaned = cleaned.strip()

    # Remove trailing commas before closing braces/brackets (common LLM error)
    import re
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Ollama deck JSON: %s", exc)
        logger.debug("Raw output:\n%s", raw[:500])
        raise ValueError(f"Ollama returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected dict from Ollama, got {type(data).__name__}")

    result: Dict[str, List[str]] = {}
    for key, val in data.items():
        if isinstance(val, list):
            result[key] = [str(v) for v in val]
        else:
            logger.warning("Skipping non-list category %s", key)
    return result


def flatten_categories(categorised: Dict[str, List[str]]) -> List[str]:
    """Return a flat, deduplicated list of card names from categorised dict."""
    seen: set[str] = set()
    names: List[str] = []
    for cards in categorised.values():
        for name in cards:
            lower = name.lower()
            if lower not in seen:
                seen.add(lower)
                names.append(name)
    return names


def assign_categories(
    entries: List[CardEntry],
    categorised: Dict[str, List[str]],
) -> List[CardEntry]:
    """Set each CardEntry's category based on the Ollama categorisation."""
    name_to_cat: Dict[str, str] = {}
    for cat, names in categorised.items():
        for name in names:
            name_to_cat[name.lower()] = cat

    for entry in entries:
        cat = name_to_cat.get(entry.name.lower())
        if cat:
            entry.category = cat
    return entries


def deduplicate_entries(entries: List[CardEntry]) -> List[CardEntry]:
    """Remove duplicate card entries, keeping the first occurrence."""
    seen: set[str] = set()
    unique: List[CardEntry] = []
    for entry in entries:
        key = entry.name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique
