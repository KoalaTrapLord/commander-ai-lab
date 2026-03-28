"""
services/card_text.py
=====================
Shared utility for building card text representations.

    Both services/rag_store.py and coach/embeddings.py need to produce
    identical text strings for embedding so that vector similarity is
    consistent across both systems.  This module provides a single
    canonical implementation.

    Format:  Natural-language sentences.
    (fields that are empty/missing are omitted)
"""

from __future__ import annotations


def build_card_text(card: dict) -> str:
    """Build canonical natural-language card text for embedding.

    Produces '{Name} is a {Type}. It costs {ManaCost}. {OracleText}'
    Fields that are empty/None are omitted.

    Args:
        card: Dict with keys 'name', 'mana_cost', 'type_line', 'oracle_text'.
              Missing keys are treated as empty strings.

    Returns:
        Natural language string suitable for nomic-embed-text or GTE models.
    """
    name = (card.get("name", "") or "").strip()
    mana = (card.get("mana_cost", "") or "").strip()
    types = (card.get("type_line", "") or "").strip()
    oracle = (card.get("oracle_text", "") or "").strip()

    parts: list[str] = []
    if name:
        base = f"{name} is a {types}." if types else f"{name}."
        parts.append(base)
    if mana:
        parts.append(f"It costs {mana}.")
    if oracle:
        parts.append(oracle)

    return " ".join(parts) if parts else name
