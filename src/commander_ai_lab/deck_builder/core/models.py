"""
Pydantic models for the Commander AI Deck Builder.

Defines CardEntry, DeckCategory, CommanderDeck, and BuildRequest
with full color identity validation and 99-card singleton enforcement.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator


# ── colour identity ──────────────────────────────────────────────
class Color(str, Enum):
    WHITE = "W"
    BLUE = "U"
    BLACK = "B"
    RED = "R"
    GREEN = "G"


WUBRG: Set[str] = {c.value for c in Color}


# ── card entry ───────────────────────────────────────────────────
class CardEntry(BaseModel):
    """A single card in a deck list."""

    name: str
    quantity: int = Field(default=1, ge=1)
    category: str = Field(
        default="uncategorized",
        description="ramp | removal | card_draw | lands | synergy | protection | wincon | uncategorized",
    )
    color_identity: Set[str] = Field(default_factory=set)
    mana_cost: Optional[str] = None
    cmc: float = 0.0
    type_line: Optional[str] = None
    scryfall_id: Optional[str] = None
    edhrec_rank: Optional[int] = None
    source: Optional[str] = None  # edhrec | scryfall | moxfield | archidekt | reddit | ollama

    @field_validator("color_identity", mode="before")
    @classmethod
    def normalize_colors(cls, v):
        if isinstance(v, str):
            return {c.upper() for c in v if c.upper() in WUBRG}
        if isinstance(v, (list, set)):
            return {c.upper() for c in v if c.upper() in WUBRG}
        return set()


# ── deck category targets ────────────────────────────────────────
class DeckRatios(BaseModel):
    """Target card counts per category (must sum to 99)."""

    lands: int = Field(default=36, ge=30, le=42)
    ramp: int = Field(default=10, ge=6, le=15)
    card_draw: int = Field(default=10, ge=6, le=15)
    removal: int = Field(default=8, ge=4, le=14)
    protection: int = Field(default=5, ge=2, le=10)
    synergy: int = Field(default=25, ge=15, le=35)
    wincon: int = Field(default=3, ge=1, le=8)
    uncategorized: int = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def check_total(self) -> "DeckRatios":
        total = (
            self.lands
            + self.ramp
            + self.card_draw
            + self.removal
            + self.protection
            + self.synergy
            + self.wincon
            + self.uncategorized
        )
        if total != 99:
            raise ValueError(f"Card type targets must sum to 99, got {total}")
        return self


# ── commander deck ───────────────────────────────────────────────
class CommanderDeck(BaseModel):
    """Full 99-card Commander deck plus the commander card."""

    commander: CardEntry
    companion: Optional[CardEntry] = None
    cards: List[CardEntry] = Field(default_factory=list)
    ratios: DeckRatios = Field(default_factory=DeckRatios)

    @model_validator(mode="after")
    def validate_deck(self) -> "CommanderDeck":
        # ── singleton check (basic lands exempt) ──
        basic_lands = {
            "Plains", "Island", "Swamp", "Mountain", "Forest",
            "Wastes", "Snow-Covered Plains", "Snow-Covered Island",
            "Snow-Covered Swamp", "Snow-Covered Mountain", "Snow-Covered Forest",
        }
        seen: dict[str, int] = {}
        for card in self.cards:
            if card.name not in basic_lands:
                seen[card.name] = seen.get(card.name, 0) + card.quantity
                if seen[card.name] > 1:
                    raise ValueError(f"Singleton violation: '{card.name}' appears {seen[card.name]} times")

        # ── 99-card check ──
        total = sum(c.quantity for c in self.cards)
        if total != 99:
            raise ValueError(f"Deck must contain exactly 99 cards, got {total}")

        # ── color identity check ──
        commander_ci = self.commander.color_identity
        for card in self.cards:
            if card.color_identity and not card.color_identity.issubset(commander_ci):
                violation = card.color_identity - commander_ci
                raise ValueError(
                    f"'{card.name}' has colors {violation} outside commander identity {commander_ci}"
                )
        return self


# ── build request (API input) ────────────────────────────────────
class BuildRequest(BaseModel):
    """Input payload for the deck build pipeline."""

    commander_name: str
    collection_only: bool = False
    collection_path: Optional[str] = None  # path to CSV
    budget_limit: Optional[float] = None
    ratios: DeckRatios = Field(default_factory=DeckRatios)
    strategy_notes: Optional[str] = None  # free-text guidance for Ollama


# ── build result (API output) ────────────────────────────────────
class BuildResult(BaseModel):
    """Output payload from the deck build pipeline."""

    deck: CommanderDeck
    warnings: List[str] = Field(default_factory=list)
    sources_consulted: List[str] = Field(default_factory=list)
    build_time_seconds: float = 0.0
