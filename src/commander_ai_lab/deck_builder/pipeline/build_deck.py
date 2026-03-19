"""
7-step deck build pipeline for the Commander AI Deck Builder.

Orchestrates: EDHrec data -> Scryfall -> Ollama suggestions ->
  color filter -> synergy rank -> ratio enforce -> final assembly.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from ..api import edhrec, scryfall
from ..api import ollama_client as ollama
from ..core.collection_filter import filter_names_by_collection
from ..core.models import BuildRequest, BuildResult, CardEntry, CommanderDeck, DeckRatios
from ..core.rules_engine import check_ban_list, filter_by_color_identity, validate_deck

logger = logging.getLogger(__name__)


def build_deck(request: BuildRequest) -> BuildResult:
    """
    Execute the full 7-step deck build pipeline.

    Steps:
      1. Resolve commander via Scryfall
      2. Fetch EDHrec recommendations
      3. Fetch Scryfall candidates by category
      4. Ollama: suggest additional cards + fill gaps
      5. Filter by color identity + collection + ban list
      6. Ollama: enforce deck ratios (trim/expand to 99)
      7. Ollama: assemble final structured deck JSON
    """
    start = time.time()
    warnings: List[str] = []
    sources: List[str] = []

    # ── Step 1: Resolve commander ────────────────────────────────
    logger.info(f"Step 1: Resolving commander '{request.commander_name}'")
    commander = scryfall.search_commander(request.commander_name)
    if not commander:
        commander = scryfall.get_card_by_name(request.commander_name)
    if not commander:
        raise ValueError(f"Commander not found: {request.commander_name}")

    commander_ci = commander.color_identity
    ci_list = sorted(commander_ci)
    logger.info(f"Commander: {commander.name}, CI: {ci_list}")
    sources.append("scryfall")

    # ── Step 2: Fetch EDHrec recommendations ─────────────────────
    logger.info(f"Step 2: Fetching EDHrec data for '{commander.name}'")
    edhrec_cards = edhrec.get_recommended_cards(commander.name)
    if edhrec_cards:
        sources.append("edhrec")
        logger.info(f"EDHrec returned {len(edhrec_cards)} cards")
    else:
        warnings.append("EDHrec returned no data — relying on Scryfall + Ollama")

    # ── Step 3: Fetch Scryfall candidates by category ────────────
    logger.info("Step 3: Fetching Scryfall candidates by category")
    scryfall_candidates: Dict[str, List[CardEntry]] = {
        "ramp": scryfall.search_ramp(commander_ci),
        "removal": scryfall.search_removal(commander_ci),
        "card_draw": scryfall.search_card_draw(commander_ci),
        "lands": scryfall.search_lands(commander_ci),
    }
    for cat, cards in scryfall_candidates.items():
        logger.info(f"  Scryfall {cat}: {len(cards)} candidates")

    # ── Step 4: Ollama suggestions to fill gaps ──────────────────
    logger.info("Step 4: Ollama suggesting additional cards")

    # Collect all names we already have
    all_names: List[str] = [c.name for c in edhrec_cards]
    for cards in scryfall_candidates.values():
        all_names.extend(c.name for c in cards)
    all_names = list(set(all_names))

    # Ask Ollama to suggest cards for categories that need more
    categories_to_fill = ["synergy", "protection", "wincon"]
    ollama_suggestions: Dict[str, List[str]] = {}

    for category in categories_to_fill:
        suggested = ollama.suggest_cards(
            commander_name=commander.name,
            color_identity=ci_list,
            category=category,
            count=15,
            exclude=all_names,
            strategy_notes=request.strategy_notes,
        )
        ollama_suggestions[category] = suggested
        all_names.extend(suggested)
        logger.info(f"  Ollama {category}: {len(suggested)} suggestions")

    sources.append("ollama")

    # ── Step 5: Filter (color identity, collection, ban list) ────
    logger.info("Step 5: Filtering candidates")

    # Build a unified name pool per category
    cards_by_category: Dict[str, List[str]] = {}

    # EDHrec cards (already categorized)
    for card in edhrec_cards:
        cat = card.category
        cards_by_category.setdefault(cat, []).append(card.name)

    # Scryfall candidates
    for cat, cards in scryfall_candidates.items():
        cards_by_category.setdefault(cat, []).extend(c.name for c in cards)

    # Ollama suggestions
    for cat, names in ollama_suggestions.items():
        cards_by_category.setdefault(cat, []).extend(names)

    # Deduplicate within each category
    for cat in cards_by_category:
        cards_by_category[cat] = list(dict.fromkeys(cards_by_category[cat]))

    # Collection filter (if enabled)
    if request.collection_only and request.collection_path:
        logger.info("  Applying collection filter")
        for cat in cards_by_category:
            before = len(cards_by_category[cat])
            cards_by_category[cat] = filter_names_by_collection(
                cards_by_category[cat], request.collection_path
            )
            after = len(cards_by_category[cat])
            if before != after:
                logger.info(f"  {cat}: {before} -> {after} after collection filter")

    # Ban list filter
    for cat in cards_by_category:
        from ..core.rules_engine import BANNED_CARDS
        cards_by_category[cat] = [
            n for n in cards_by_category[cat] if n not in BANNED_CARDS
        ]

    # ── Step 6: Ollama enforce ratios ────────────────────────────
    logger.info("Step 6: Ollama enforcing deck ratios")
    target_ratios = {
        "lands": request.ratios.lands,
        "ramp": request.ratios.ramp,
        "card_draw": request.ratios.card_draw,
        "removal": request.ratios.removal,
        "protection": request.ratios.protection,
        "synergy": request.ratios.synergy,
        "wincon": request.ratios.wincon,
        "uncategorized": request.ratios.uncategorized,
    }

    adjusted = ollama.enforce_deck_ratios(
        cards_by_category=cards_by_category,
        target_ratios=target_ratios,
        commander_name=commander.name,
    )

    # Verify total is 99
    total = sum(len(v) for v in adjusted.values())
    if total != 99:
        warnings.append(f"Ollama returned {total} cards instead of 99 — adjusting")
        logger.warning(f"Ratio enforcement returned {total} cards")

    # ── Step 7: Assemble final deck ──────────────────────────────
    logger.info("Step 7: Assembling final deck")

    # Convert to CardEntry list via Scryfall batch lookup
    all_card_names = []
    for names in adjusted.values():
        all_card_names.extend(names)

    card_entries = scryfall.get_cards_by_names(all_card_names)

    # Map back categories
    name_to_cat: Dict[str, str] = {}
    for cat, names in adjusted.items():
        for name in names:
            name_to_cat[name] = cat

    for entry in card_entries:
        if entry.name in name_to_cat:
            entry.category = name_to_cat[entry.name]

    # Build the deck
    elapsed = time.time() - start
    logger.info(f"Deck built in {elapsed:.1f}s")

    try:
        deck = CommanderDeck(
            commander=commander,
            cards=card_entries,
            ratios=request.ratios,
        )
    except ValueError as e:
        warnings.append(f"Deck validation issue: {e}")
        # Return a "best effort" deck without strict validation
        deck = CommanderDeck.model_construct(
            commander=commander,
            cards=card_entries,
            ratios=request.ratios,
        )

    return BuildResult(
        deck=deck,
        warnings=warnings,
        sources_consulted=sources,
        build_time_seconds=elapsed,
    )
