"""
Rules engine for the Commander AI Deck Builder.

Validates decks against Commander format rules:
  - Color identity compliance
  - Singleton rule (basic lands exempt)
  - Exactly 99 cards + 1 commander
  - Minimum card type ratios
  - Ban list checking
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set, Tuple

from .models import CardEntry, CommanderDeck, DeckRatios

logger = logging.getLogger(__name__)

# Commander ban list (partial — keep updated)
BANNED_CARDS: Set[str] = {
    "Ancestral Recall", "Balance", "Biorhythm", "Black Lotus",
    "Braids, Cabal Minion", "Channel", "Chaos Orb", "Coalition Victory",
    "Emrakul, the Aeons Torn", "Erayo, Soratami Ascendant",
    "Falling Star", "Fastbond", "Flash", "Gifts Ungiven",
    "Golos, Tireless Pilgrim", "Griselbrand", "Hullbreacher",
    "Iona, Shield of Emeria", "Karakas", "Leovold, Emissary of Trest",
    "Library of Alexandria", "Limited Resources", "Lutri, the Spellchaser",
    "Mox Emerald", "Mox Jet", "Mox Pearl", "Mox Ruby", "Mox Sapphire",
    "Panoptic Mirror", "Paradox Engine", "Primeval Titan",
    "Prophet of Kruphix", "Recurring Nightmare", "Rofellos, Llanowar Emissary",
    "Shahrazad", "Sundering Titan", "Sway of the Stars",
    "Sylvan Primordial", "Time Vault", "Time Walk", "Tinker",
    "Tolarian Academy", "Trade Secrets", "Upheaval", "Worldfire",
}

BASIC_LANDS: Set[str] = {
    "Plains", "Island", "Swamp", "Mountain", "Forest",
    "Wastes", "Snow-Covered Plains", "Snow-Covered Island",
    "Snow-Covered Swamp", "Snow-Covered Mountain", "Snow-Covered Forest",
}


# ── color identity validation ────────────────────────────────────
def validate_color_identity(
    card: CardEntry,
    commander_identity: Set[str],
) -> bool:
    """Check if a card's color identity is within the commander's."""
    if not card.color_identity:
        return True  # colorless cards are always legal
    return card.color_identity.issubset(commander_identity)


def filter_by_color_identity(
    cards: List[CardEntry],
    commander_identity: Set[str],
) -> Tuple[List[CardEntry], List[CardEntry]]:
    """
    Split cards into valid and invalid based on color identity.

    Returns (valid_cards, rejected_cards).
    """
    valid = []
    rejected = []
    for card in cards:
        if validate_color_identity(card, commander_identity):
            valid.append(card)
        else:
            rejected.append(card)
    return valid, rejected


# ── singleton validation ─────────────────────────────────────────
def validate_singleton(cards: List[CardEntry]) -> List[str]:
    """
    Check for singleton violations.

    Returns a list of card names that appear more than once
    (excluding basic lands).
    """
    seen: Dict[str, int] = {}
    violations: List[str] = []

    for card in cards:
        if card.name in BASIC_LANDS:
            continue
        seen[card.name] = seen.get(card.name, 0) + card.quantity
        if seen[card.name] > 1 and card.name not in violations:
            violations.append(card.name)

    return violations


# ── ban list check ───────────────────────────────────────────────
def check_ban_list(cards: List[CardEntry]) -> List[str]:
    """Return names of any banned cards found in the list."""
    return [c.name for c in cards if c.name in BANNED_CARDS]


# ── card count validation ────────────────────────────────────────
def validate_card_count(cards: List[CardEntry], expected: int = 99) -> int:
    """Return the difference from expected count (0 = valid)."""
    total = sum(c.quantity for c in cards)
    return total - expected


# ── ratio validation ─────────────────────────────────────────────
def validate_ratios(
    cards: List[CardEntry],
    ratios: DeckRatios,
) -> Dict[str, Dict[str, int]]:
    """
    Check if card categories meet minimum targets.

    Returns a dict of category -> {"target": int, "actual": int, "diff": int}.
    """
    counts: Dict[str, int] = {}
    for card in cards:
        cat = card.category
        counts[cat] = counts.get(cat, 0) + card.quantity

    result: Dict[str, Dict[str, int]] = {}
    targets = {
        "lands": ratios.lands,
        "ramp": ratios.ramp,
        "card_draw": ratios.card_draw,
        "removal": ratios.removal,
        "protection": ratios.protection,
        "synergy": ratios.synergy,
        "wincon": ratios.wincon,
        "uncategorized": ratios.uncategorized,
    }

    for cat, target in targets.items():
        actual = counts.get(cat, 0)
        result[cat] = {
            "target": target,
            "actual": actual,
            "diff": actual - target,
        }

    return result


# ── full deck validation ─────────────────────────────────────────
def validate_deck(
    commander: CardEntry,
    cards: List[CardEntry],
    ratios: DeckRatios,
) -> Dict[str, any]:
    """
    Run all validation checks on a deck.

    Returns a dict with:
      - "valid": bool
      - "errors": list of fatal errors
      - "warnings": list of non-fatal warnings
      - "ratio_report": category ratio details
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Color identity
    commander_ci = commander.color_identity
    _, rejected = filter_by_color_identity(cards, commander_ci)
    if rejected:
        names = [c.name for c in rejected]
        errors.append(f"Color identity violations: {', '.join(names)}")

    # Singleton
    dupes = validate_singleton(cards)
    if dupes:
        errors.append(f"Singleton violations: {', '.join(dupes)}")

    # Ban list
    banned = check_ban_list(cards)
    if banned:
        errors.append(f"Banned cards: {', '.join(banned)}")

    # Card count
    diff = validate_card_count(cards)
    if diff != 0:
        direction = "too many" if diff > 0 else "too few"
        errors.append(f"Card count: {abs(diff)} {direction} (need exactly 99)")

    # Ratios
    ratio_report = validate_ratios(cards, ratios)
    for cat, info in ratio_report.items():
        if info["diff"] < 0:
            warnings.append(
                f"{cat}: {info['actual']}/{info['target']} "
                f"({abs(info['diff'])} short)"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "ratio_report": ratio_report,
    }
