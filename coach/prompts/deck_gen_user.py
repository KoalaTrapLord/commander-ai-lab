"""
Commander AI Lab — Deck Generation User Prompt Builder
═══════════════════════════════════════════════════════
Constructs the user message for LLM deck generation.

Phase 1 changes:
  - slot_budget parameter injected into prompt so LLM targets exactly 99 cards
  - Explicit card count requirement in prompt text
"""

from typing import Dict, List, Optional


def build_slot_budget_segment(slot_budget: Dict[str, int]) -> str:
    """
    Build the slot budget prompt segment.
    Informs the LLM of exact per-category card counts so it never undershoots.
    """
    total = sum(slot_budget.values())
    lines = [f"SLOT BUDGET (you must fill EXACTLY {total} cards, excluding the commander):"]
    for cat, count in slot_budget.items():
        lines.append(f"  {cat}: {count}")
    lines.append(f"  TOTAL: {total}")
    lines.append("")
    lines.append(
        f"CRITICAL: Return exactly {total} cards in the JSON 'cards' array "
        "(not counting the commander). Every slot in the budget above must be filled. "
        "Do not return more or fewer cards."
    )
    return "\n".join(lines)


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
    slot_budget: Optional[Dict[str, int]] = None,
) -> str:
    """
    Build the user prompt for deck generation.

    Args:
        commander: Commander card name
        commander_type: Type line from Scryfall
        color_identity: List of color letters, e.g. ["U", "B"]
        strategy: User-specified strategy focus
        target_bracket: Target bracket level 1-4
        budget_usd: Optional budget constraint
        budget_mode: "total" for total deck cost, "per_card" for per-card max
        omit_cards: Cards to exclude
        collection_summary: Pre-built collection summary text block
        slot_budget: Dict of category -> card count (must sum to 99)
    """
    ci_str = ", ".join(color_identity) if color_identity else "Unknown"

    lines = [
        "Build a complete 100-card Commander deck.",
        "",
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
        lines.append("")
        lines.append(collection_summary)
        lines.append("")
        lines.append("STRONGLY PREFER cards from the collection when they fit the strategy.")
    else:
        lines.append("")
        lines.append("No collection data available — suggest the best cards regardless of ownership.")

    # Inject slot budget so LLM knows exact target counts
    if slot_budget:
        lines.append("")
        lines.append(build_slot_budget_segment(slot_budget))

    lines.append("")
    lines.append("Build the deck as a structured JSON response. Include the commander in the cards list.")
    lines.append("Ensure exactly 100 total cards. Assign role_tags and bracket info accurately.")

    return "\n".join(lines)
