"""
Commander AI Lab — Substitution Prompt Templates
═════════════════════════════════════════════════
Prompts for the Perplexity fallback substitution pass.
"""


SUBSTITUTION_SYSTEM = """You are an expert Magic: The Gathering Commander deck builder specializing in card substitutions.

Given a list of cards that a player does NOT own, suggest the best replacement from their available collection. Each substitute should:
1. Fill the same functional role (ramp → ramp, removal → removal, lord → lord)
2. Be within the same color identity
3. Have a similar mana cost (within ±2 CMC)
4. Maintain the deck's strategy and synergies as much as possible

Only suggest cards from the ALLOWED CARDS LIST provided. Do not suggest cards outside that list.
If no good substitute exists for a card, omit it from the substitutions array."""


def build_substitution_prompt(
    missing_cards: list[dict],
    allowed_cards: list[str],
    commander: str,
    color_identity: list[str],
    strategy: str = "",
) -> str:
    """
    Build the user prompt for batch substitution.

    Args:
        missing_cards: List of dicts with 'name', 'role_tags', 'category', 'reason'
        allowed_cards: List of card names the player owns that can be used
        commander: Commander name
        color_identity: Deck color identity
        strategy: Deck strategy summary
    """
    lines = [
        f"DECK: {commander} ({', '.join(color_identity)})",
    ]
    if strategy:
        lines.append(f"STRATEGY: {strategy}")

    lines.append(f"")
    lines.append(f"CARDS THAT NEED REPLACING ({len(missing_cards)}):")
    for card in missing_cards:
        roles = ", ".join(card.get("role_tags", []))
        lines.append(f"  - {card['name']} [{card.get('category', '?')}] (roles: {roles}) — {card.get('reason', '')}")

    lines.append(f"")
    lines.append(f"ALLOWED CARDS (player's collection, {len(allowed_cards)} cards):")
    # Group into chunks to stay readable
    chunk_size = 20
    for i in range(0, len(allowed_cards), chunk_size):
        chunk = allowed_cards[i:i+chunk_size]
        lines.append(f"  {', '.join(chunk)}")

    lines.append(f"")
    lines.append(f"For each missing card, suggest the BEST substitute from the allowed list.")
    lines.append(f"Return structured JSON with the substitutions array.")

    return "\n".join(lines)
