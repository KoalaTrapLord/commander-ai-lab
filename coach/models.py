"""
Commander AI Lab — Coach Data Models
═════════════════════════════════════
Pydantic v2 models for deck reports, coach requests/responses,
and coaching session persistence.
"""

from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# Deck Report Models (mirrors Java DeckReport)
# ══════════════════════════════════════════════════════════════

class CardPerformance(BaseModel):
    """Per-card aggregated stats from simulation data."""
    name: str
    drawnRate: float = 0.0          # Fraction of games where card was drawn
    castRate: float = 0.0           # Fraction of games where drawn AND cast
    keptInOpeningHandRate: float = 0.0
    deadCardRate: float = 0.0       # Drawn but never cast/used
    impactScore: float = 0.0        # (winRateWhenCast - overallWinRate) * castRate
    synergyScore: float = 0.0       # Co-occurrence uplift with other deck cards
    clunkinessScore: float = 0.0    # deadCardRate * (1 - castRate)
    avgTurnCast: Optional[float] = None
    avgDamageDealt: float = 0.0
    tags: List[str] = Field(default_factory=list)  # ramp, draw, removal, etc.


class MatchupRecord(BaseModel):
    """Win rate against a specific opponent deck."""
    opponentDeck: str
    opponentCommander: str = ""
    gamesPlayed: int = 0
    winRate: float = 0.0


class DeckMeta(BaseModel):
    """High-level deck statistics."""
    gamesSimulated: int = 0
    overallWinRate: float = 0.0
    avgGameLength: float = 0.0
    perArchetypeWinRates: Dict[str, float] = Field(default_factory=dict)


class DeckStructure(BaseModel):
    """Deck composition breakdown."""
    landCount: int = 0
    curveBuckets: List[int] = Field(default_factory=lambda: [0]*8)  # CMC 0-7+
    cardTypeCounts: Dict[str, int] = Field(default_factory=dict)
    functionalCounts: Dict[str, int] = Field(default_factory=dict)


class ComboRecord(BaseModel):
    """Known combo with performance data."""
    cardNames: List[str]
    winRateWhenAssembled: float = 0.0
    assemblyRate: float = 0.0  # Fraction of games where all pieces drawn


class DeckReport(BaseModel):
    """
    Complete deck performance report — produced by the Java
    ReportAggregator and consumed by the Python coach service.
    """
    deckId: str
    commander: str
    colorIdentity: List[str] = Field(default_factory=list)
    meta: DeckMeta = Field(default_factory=DeckMeta)
    matchups: List[MatchupRecord] = Field(default_factory=list)
    structure: DeckStructure = Field(default_factory=DeckStructure)
    cards: List[CardPerformance] = Field(default_factory=list)
    underperformers: List[str] = Field(default_factory=list)
    overperformers: List[str] = Field(default_factory=list)
    knownCombos: List[ComboRecord] = Field(default_factory=list)
    lastUpdated: str = ""


# ══════════════════════════════════════════════════════════════
# Coach Request / Response Models
# ══════════════════════════════════════════════════════════════

class CoachGoals(BaseModel):
    """User-specified coaching goals."""
    targetPowerLevel: Optional[int] = None          # 1-10
    metaFocus: Optional[str] = None                 # aggro, control, combo, midrange, stax
    budget: Optional[str] = None                    # budget, medium, no-limit
    focusAreas: List[str] = Field(default_factory=list)  # e.g., ["ramp", "card draw"]


class CoachRequest(BaseModel):
    """Request body for POST /api/coach/decks/{deckId}."""
    deck_id: str = ""
    goals: Optional[CoachGoals] = None


class SuggestedCut(BaseModel):
    """A card the coach suggests removing."""
    cardName: str
    reason: str
    replacementOptions: List[str] = Field(default_factory=list)
    currentImpactScore: float = 0.0


class SuggestedAdd(BaseModel):
    """A card the coach suggests adding."""
    cardName: str
    role: str = ""          # ramp, draw, removal, finisher, etc.
    reason: str = ""
    synergyWith: List[str] = Field(default_factory=list)
    estimatedManaValue: Optional[float] = None


class CoachSession(BaseModel):
    """
    Complete coaching session result.
    Persisted to coach-sessions/{sessionId}.json.
    """
    sessionId: str
    deckId: str
    timestamp: str = ""
    summary: str = ""
    suggestedCuts: List[SuggestedCut] = Field(default_factory=list)
    suggestedAdds: List[SuggestedAdd] = Field(default_factory=list)
    heuristicHints: List[str] = Field(default_factory=list)
    manaBaseAdvice: Optional[str] = None
    rawTextExplanation: str = ""
    modelUsed: str = ""
    promptTokens: int = 0
    completionTokens: int = 0
    goals: Optional[CoachGoals] = None


class ApplyRequest(BaseModel):
    """Request body for applying coach suggestions to a deck."""
    acceptedCuts: List[str] = Field(default_factory=list)
    acceptedAdds: List[str] = Field(default_factory=list)


class CoachStatus(BaseModel):
    """Status of the coach subsystem."""
    llmConnected: bool = False
    llmModel: Optional[str] = None
    llmModels: List[str] = Field(default_factory=list)
    embeddingsLoaded: bool = False
    embeddingCards: int = 0
    deckReportsAvailable: int = 0
    error: Optional[str] = None
