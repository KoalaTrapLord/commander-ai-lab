"""
Commander AI Lab — Deck Generation JSON Schemas
═════════════════════════════════════════════════
Pydantic models and JSON Schema dicts for Perplexity
structured output deck generation.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# Pydantic Models (for validation & type checking)
# ══════════════════════════════════════════════════════════════

class DeckCard(BaseModel):
    """A single card in a generated deck."""
    name: str = Field(description="Exact card name as printed")
    count: int = Field(default=1, description="Number of copies (1 for all except basic lands)")
    category: str = Field(description="Card category: Creature, Instant, Sorcery, Artifact, Enchantment, Planeswalker, Land, Battle")
    role_tags: List[str] = Field(
        default_factory=list,
        description="Functional roles: ramp, card_draw, removal, board_wipe, protection, finisher, combo_piece, utility, lord, sac_outlet, token_generator, recursion, tutor, counter, lifegain, graveyard_hate, mana_rock, mana_dork, anthem"
    )
    reason: str = Field(default="", description="Brief explanation of why this card is included")
    estimated_price_usd: float = Field(default=0.0, description="Estimated TCG market price in USD")
    synergy_with: List[str] = Field(default_factory=list, description="Names of other cards in the deck this synergizes with")


class BracketInfo(BaseModel):
    """Commander bracket classification (1-4 per Rules Committee)."""
    level: int = Field(ge=1, le=4, description="Bracket level 1-4")
    reasoning: str = Field(description="Why this bracket was assigned")
    game_changers: List[str] = Field(
        default_factory=list,
        description="Cards that count as 'Game Changers' for bracket classification"
    )


class DeckReasoning(BaseModel):
    """Strategic reasoning behind deck construction."""
    strategy: str = Field(description="Core game plan and win conditions")
    mana_curve: str = Field(description="How the mana curve was designed")
    key_synergies: str = Field(description="Most important card interactions")
    budget_notes: str = Field(default="", description="How budget constraints were managed")
    bracket_compliance: str = Field(default="", description="How bracket rules were respected")


class GeneratedDeckList(BaseModel):
    """Complete generated deck output from Perplexity."""
    commander: str = Field(description="Commander card name")
    strategy_summary: str = Field(description="1-2 sentence strategy overview")
    bracket: BracketInfo
    archetype: str = Field(description="Primary archetype: aggro, midrange, control, combo, stax, voltron, aristocrats, spellslinger, tokens, tribal, group_hug, lands, reanimator")
    cards: List[DeckCard] = Field(description="Complete card list (commander + 99)")
    reasoning: DeckReasoning
    estimated_total_usd: float = Field(default=0.0, description="Estimated total deck cost")


# ══════════════════════════════════════════════════════════════
# JSON Schema dicts (for Perplexity response_format)
# ══════════════════════════════════════════════════════════════

DECK_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Exact card name as printed"},
        "count": {"type": "integer", "description": "Number of copies (1 for all except basic lands)"},
        "category": {
            "type": "string",
            "description": "Card category",
            "enum": ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Land", "Battle"],
        },
        "role_tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Functional roles: ramp, card_draw, removal, board_wipe, protection, finisher, combo_piece, utility, lord, sac_outlet, token_generator, recursion, tutor, counter, lifegain, graveyard_hate, mana_rock, mana_dork, anthem",
        },
        "reason": {"type": "string", "description": "Brief explanation of why this card is included"},
        "estimated_price_usd": {"type": "number", "description": "Estimated TCG market price in USD"},
        "synergy_with": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Names of other cards this synergizes with",
        },
    },
    "required": ["name", "count", "category", "role_tags", "reason"],
    "additionalProperties": False,
}

BRACKET_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "integer", "description": "Bracket level 1-4"},
        "reasoning": {"type": "string", "description": "Why this bracket was assigned"},
        "game_changers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Cards that are Game Changers for bracket classification",
        },
    },
    "required": ["level", "reasoning", "game_changers"],
    "additionalProperties": False,
}

DECK_REASONING_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string", "description": "Core game plan and win conditions"},
        "mana_curve": {"type": "string", "description": "How the mana curve was designed"},
        "key_synergies": {"type": "string", "description": "Most important card interactions"},
        "budget_notes": {"type": "string", "description": "How budget constraints were managed"},
        "bracket_compliance": {"type": "string", "description": "How bracket rules were respected"},
    },
    "required": ["strategy", "mana_curve", "key_synergies"],
    "additionalProperties": False,
}

DECK_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "commander": {"type": "string", "description": "Commander card name"},
        "strategy_summary": {"type": "string", "description": "1-2 sentence strategy overview"},
        "bracket": BRACKET_SCHEMA,
        "archetype": {
            "type": "string",
            "description": "Primary archetype",
            "enum": ["aggro", "midrange", "control", "combo", "stax", "voltron", "aristocrats", "spellslinger", "tokens", "tribal", "group_hug", "lands", "reanimator", "other"],
        },
        "cards": {
            "type": "array",
            "items": DECK_CARD_SCHEMA,
            "description": "Complete card list (commander + 99)",
        },
        "reasoning": DECK_REASONING_SCHEMA,
        "estimated_total_usd": {"type": "number", "description": "Estimated total deck cost"},
    },
    "required": ["commander", "strategy_summary", "bracket", "archetype", "cards", "reasoning", "estimated_total_usd"],
    "additionalProperties": False,
}
