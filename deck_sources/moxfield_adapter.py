"""
Moxfield Adapter (stub)
════════════════════════

Fetches template decklists from Moxfield for a given commander.
Currently returns empty (experimental — not yet implemented).
"""
from .models import TemplateDeck, TemplateDeckCard


def fetch_template_decks(commander_name: str, color_identity: list, config: dict = None) -> list:
    """
    Fetch template decks from Moxfield for the given commander.
    Experimental — not yet implemented.
    """
    print(f"    [MOXFIELD] Stub: Not yet implemented for '{commander_name}'")
    return []
