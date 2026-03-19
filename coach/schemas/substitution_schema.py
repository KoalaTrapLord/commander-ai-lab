"""
Commander AI Lab — Substitution Schemas
════════════════════════════════════════
Pydantic models and JSON Schema dicts for the
Smart Substitution Engine output.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# Pydantic Models
# ══════════════════════════════════════════════════════════════

class CardAlternative(BaseModel):
    """A single substitute card suggestion."""
    name: str = Field(description="Exact card name")
    similarity_score: float = Field(default=0.0, description="Cosine similarity score (0-1)")
    reason: str = Field(default="", description="Why this card is a good substitute")
    source: str = Field(default="embedding", description="How it was found: 'embedding' or 'perplexity'")
    role_overlap: List[str] = Field(default_factory=list, description="Shared functional roles")
    cmc_delta: float = Field(default=0.0, description="CMC difference from original")


class DeckCardWithStatus(BaseModel):
    """A deck card enriched with ownership and substitution data."""
    
    class Config:
        extra = "ignore"
    name: str
    count: int = 1
    category: str = ""
    role_tags: List[str] = Field(default_factory=list)
    reason: str = ""
    estimated_price_usd: float = 0.0
    synergy_with: List[str] = Field(default_factory=list)

    # Ownership & substitution
    owned: bool = True
    owned_qty: int = 0
    scryfall_id: str = ""
    status: str = Field(default="owned", description="owned | substituted | missing")
    original_card: Optional[str] = Field(default=None, description="Original card name if this is a substitution")
    alternatives: List[CardAlternative] = Field(default_factory=list)
    selected_substitute: Optional[str] = Field(default=None, description="User-selected substitute name")


class SubstitutionRequest(BaseModel):
    """Request for substitution on a single card."""
    card_name: str
    role_tags: List[str] = Field(default_factory=list)
    category: str = ""
    cmc: float = 0.0
    color_identity: List[str] = Field(default_factory=list)


class SubstitutionBatchResult(BaseModel):
    """Result of a batch substitution pass."""
    total_cards: int = 0
    owned_count: int = 0
    substituted_count: int = 0
    missing_count: int = 0
    cards: List[DeckCardWithStatus] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# JSON Schema dicts (for Perplexity fallback substitution)
# ══════════════════════════════════════════════════════════════

SUBSTITUTION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "substitutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string", "description": "Card that needs replacing"},
                    "substitute": {"type": "string", "description": "Recommended replacement from the allowed list"},
                    "reason": {"type": "string", "description": "Why this substitute works"},
                    "role_overlap": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Shared functional roles",
                    },
                },
                "required": ["original", "substitute", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["substitutions"],
    "additionalProperties": False,
}
