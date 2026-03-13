"""
EDHREC Adapter (stub)
══════════════════════

Fetches popular/recommended cards from EDHREC for a given commander.
Currently returns a hardcoded sample for end-to-end wiring.
Real implementation will parse EDHREC commander pages.
"""
from .models import TemplateDeck, TemplateDeckCard
import logging

log = logging.getLogger("commander_ai_lab.deckgen.edhrec")



def fetch_template_decks(commander_name: str, color_identity: list, config: dict = None) -> list:
    """
    Fetch recommended cards from EDHREC for the given commander.

    Args:
        commander_name: The commander's name
        color_identity: List of color letters
        config: Optional config

    Returns:
        List of TemplateDeck objects (currently stubbed)
    """
    # STUB: Return empty list until real EDHREC integration
    # When implemented, this will:
    # 1. Build EDHREC URL for the commander (e.g., /commanders/korvold-fae-cursed-king)
    # 2. Fetch the "Average Deck" or "Top Cards" list
    # 3. Parse card names and inclusion percentages
    # 4. Return as a single TemplateDeck with weighted cards
    log.info(f"    Stub: No recommendations for '{commander_name}' (not yet implemented)")
    return []
