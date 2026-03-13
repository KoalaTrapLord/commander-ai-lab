"""
MTGGoldfish Adapter (stub)
═══════════════════════════

Fetches template decklists from MTGGoldfish for a given commander.
Currently returns empty (experimental — not yet implemented).
"""
from .models import TemplateDeck, TemplateDeckCard
import logging

log = logging.getLogger("commander_ai_lab.deckgen.mtggoldfish")



def fetch_template_decks(commander_name: str, color_identity: list, config: dict = None) -> list:
    """
    Fetch template decks from MTGGoldfish for the given commander.
    Experimental — not yet implemented.
    """
    log.info(f"    Stub: Not yet implemented for '{commander_name}'")
    return []
