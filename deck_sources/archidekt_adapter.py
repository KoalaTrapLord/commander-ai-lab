"""
Archidekt Adapter (stub)
═════════════════════════

Fetches template decklists from Archidekt for a given commander.
Currently returns a hardcoded sample for end-to-end wiring.
Real implementation will call the Archidekt API.
"""
from .models import TemplateDeck, TemplateDeckCard


def fetch_template_decks(commander_name: str, color_identity: list, config: dict = None) -> list:
    """
    Fetch template decks from Archidekt for the given commander.

    Args:
        commander_name: The commander's name
        color_identity: List of color letters, e.g. ["W", "U", "B"]
        config: Optional config (URLs, IDs, etc.)

    Returns:
        List of TemplateDeck objects (currently stubbed)
    """
    # STUB: Return empty list until real Archidekt API integration
    # When implemented, this will:
    # 1. Search Archidekt for popular decks with this commander
    # 2. Fetch the top 3-5 decklists
    # 3. Normalize card names and return as TemplateDeck
    print(f"    [ARCHIDEKT] Stub: No template decks for '{commander_name}' (not yet implemented)")
    return []
