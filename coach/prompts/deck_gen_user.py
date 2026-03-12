"""
Commander AI Lab — Deck Generation User Prompt Builder
═══════════════════════════════════════════════════════
Constructs the user message for Perplexity deck generation
from a DeckGenV3Request.
"""

from typing import List, Optional


def build_user_prompt(
    commander: str,
    commander_type: str = "",
    color_identity: List[str] = None,
    strategy: str = "",
    target_bracket: int = 3,
    budget_usd: float = None,
    budget_mode: str = "total",
    omit_cards: List[str] = None,
    collection_summary: str = "",
) -> str:
    """
    Build the user prompt for deck generation.

    Args:
        commander: Commander card name
        commander_type: Type line from Scryfall
        color_identity: List of color letters, e.g. ["U", "B"]
        strategy: User-specified strategy focus (e.g. "zombie tokens")
        target_bracket: Target bracket level 1-4
        budget_usd: Optional budget constraint
        budget_mode: "total" for total deck cost, "per_card" for per-card max
        omit_cards: Cards to exclude
        collection_summary: Pre-built collection summary text block
    """
    ci_str = ", ".join(color_identity) if color_identity else "Unknown"

    lines = [
        f"Build a complete 100-card Commander deck.",
        f"",
        f"COMMANDER: {commander}",
    ]

    if commander_type:
        lines.append(f"TYPE: {commander_type}")

    lines.append(f"COLOR IDENTITY: {ci_str}")
    lines.append(f"TARGET BRACKET: {target_bracket}")

    if strategy:
        lines.append(f"STRATEGY FOCUS: {strategy}")

    if budget_usd:
        if budget_mode == "per_card":
            lines.append(f"BUDGET: Max ${budget_usd:.0f} per card. No card should exceed this price.")
        else:
            lines.append(f"BUDGET: ${budget_usd:.0f} total deck cost. Stay within budget.")

    if omit_cards:
        lines.append(f"OMIT LIST (do NOT include these cards): {', '.join(omit_cards)}")

    if collection_summary:
        lines.append(f"")
        lines.append(collection_summary)
        lines.append(f"")
        lines.append(f"STRONGLY PREFER cards from the collection when they fit the strategy.")
    else:
        lines.append(f"")
        lines.append(f"No collection data available — suggest the best cards regardless of ownership.")

    lines.append(f"")
    lines.append(f"Build the deck as a structured JSON response. Include the commander in the cards list.")
    lines.append(f"Ensure exactly 100 total cards. Assign role_tags and bracket info accurately.")

    return "\n".join(lines)
