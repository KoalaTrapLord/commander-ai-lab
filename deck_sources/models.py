"""
Deck Sources — Shared Models
═════════════════════════════

Common data models for template decks fetched from external sources.
"""


class TemplateDeckCard:
    """A single card in a template deck."""
    __slots__ = ("name", "quantity")

    def __init__(self, name: str, quantity: int = 1):
        self.name = name
        self.quantity = quantity

    def to_dict(self) -> dict:
        return {"name": self.name, "quantity": self.quantity}


class TemplateDeck:
    """A template deck fetched from an external source."""
    __slots__ = ("name", "source", "cards")

    def __init__(self, name: str, source: str, cards: list = None):
        self.name = name
        self.source = source
        self.cards = cards or []  # list of TemplateDeckCard

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "cards": [c.to_dict() for c in self.cards],
        }
