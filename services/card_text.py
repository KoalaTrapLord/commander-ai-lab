"""
services/card_text.py
=====================
Shared utility for building card text representations.

Both services/rag_store.py and coach/embeddings.py need to produce
identical text strings for embedding so that vector similarity is
consistent across both systems.  This module provides a single
canonical implementation.

Format:  Name | Mana Cost | Type | Oracle Text
(fields that are empty/missing are omitted)
"""
from __future__ import annotations


def build_card_text(card: dict) -> str:
    """Build the canonical text representation of a card for embedding.

    Args:
        card: Dict with keys 'name', 'mana_cost', 'type_line', 'oracle_text'.
              Missing keys are treated as empty strings.

    Returns:
        Pipe-separated string like 'Sol Ring | {1} | Artifact | {T}: Add {C}{C}.'
    """
    parts = [card.get("name", "") or ""]
    mana_cost = card.get("mana_cost", "") or ""
    if mana_cost:
        parts.append(mana_cost)
    type_line = card.get("type_line", "") or ""
    if type_line:
        parts.append(type_line)
    oracle = card.get("oracle_text", "") or ""
    if oracle:
        parts.append(oracle)
    return " | ".join(parts)
