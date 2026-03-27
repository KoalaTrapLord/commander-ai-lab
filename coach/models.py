"""
Commander AI Lab — Coach Data Models
═════════════════════════════════════
Pydantic v2 models for deck reports, coach requests/responses,
and coaching session persistence.
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# Deck Report Models (mirrors Java DeckReport)
# ══════════════════════════════════════════════════════════════

class CardPerformance(BaseModel):
    """Per-card aggregated stats from simulation data."""
    name: str
    drawnRate: float = 0.0
    castRate: float = 0.0
    keptInOpeningHandRate: float = 0.0
    deadCardRate: float = 0.0
    impactScore: float = 0.0
    synergyScore: float = 0.0
    clunkinessScore: float = 0.0
    avgTurnCast: Optional[float] = None
    avgDamageDealt: float = 0.0
    tags: List[str] = Field(default_factory=list)


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
    curveBuckets: List[int] = Field(default_factory=lambda: [0]*8)
    cardTypeCounts: Dict[str, int] = Field(default_factory=dict)
    functionalCounts: Dict[str, int] = Field(default_factory=dict)


class ComboRecord(BaseModel):
    """Known combo with performance data."""
    cardNames: List[str]
    winRateWhenAssembled: float = 0.0
    assemblyRate: float = 0.0


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
    targetPowerLevel: Optional[int] = None
    metaFocus: Optional[str] = None
    budget: Optional[str] = None
    focusAreas: List[str] = Field(default_factory=list)


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
    role: str = ""
    reason: str = ""
    synergyWith: List[str] = Field(default_factory=list)
    estimatedManaValue: Optional[float] = None


# ══════════════════════════════════════════════════════════════
# Phase 2: Structured Analysis Models
# ══════════════════════════════════════════════════════════════

class UpgradePriorityItem(BaseModel):
    """A single prioritized cut/add swap ranked by expected impact."""
    rank: int
    cut: str
    add: str
    reasoning: str = ""
    expectedImpact: str = ""


class CommanderDependency(BaseModel):
    """How reliant the deck is on having the commander in play."""
    score: int = 5
    dependentCards: List[str] = Field(default_factory=list)
    recoveryPlan: str = ""


class MulliganAnalysis(BaseModel):
    """Opening hand keepability assessment."""
    estimatedKeepRate: str = ""
    worstOffenders: List[str] = Field(default_factory=list)
    recommendation: str = ""


# ══════════════════════════════════════════════════════════════
# Phase 3: Qualitative Analysis Models
# ══════════════════════════════════════════════════════════════

class RemovalCoverage(BaseModel):
    """Categorized removal package by permanent type."""
    creatures: str = ""             # Assessment of creature removal
    artifacts: str = ""             # Assessment of artifact removal
    enchantments: str = ""          # Assessment of enchantment removal
    planeswalkers: str = ""         # Assessment of planeswalker removal
    lands: str = ""                 # Assessment of land destruction
    massRemoval: str = ""           # Assessment of board wipes / sweepers
    gaps: List[str] = Field(default_factory=list)  # Permanent types with zero coverage


class RampQuality(BaseModel):
    """Ramp package breakdown by subtype and fragility."""
    manaRocks: str = ""             # 2-mana rocks, signets, etc.
    landFetch: str = ""             # Cultivate, Kodama's Reach, etc.
    manaDorks: str = ""             # Llanowar Elves, Birds of Paradise, etc.
    costReducers: str = ""          # Medallions, Helm of Awakening, etc.
    fragility: str = ""             # Overall fragility assessment (creature-heavy = fragile)
    canReachFourByTurnThree: str = ""  # Whether the deck reliably hits 4 mana by turn 3


class DrawEngineProfile(BaseModel):
    """Card draw sustainability analysis."""
    burstDraw: List[str] = Field(default_factory=list)     # One-time draw spells
    repeatableEngines: List[str] = Field(default_factory=list)  # Sustained draw engines
    assessment: str = ""            # Overall draw engine quality evaluation
    sustainability: str = ""        # Whether draw is sustainable or burst-only


class WinCondition(BaseModel):
    """A named win condition with independence rating."""
    name: str                       # e.g., "Craterhoof Behemoth + wide board"
    cards: List[str] = Field(default_factory=list)  # Key cards involved
    independence: str = ""          # How well it works without other combos (high/medium/low)
    description: str = ""           # How this win con functions


class AntiSynergyFlag(BaseModel):
    """An internal conflict between cards in the deck."""
    cards: List[str] = Field(default_factory=list)  # Cards that conflict
    conflict: str = ""              # Description of the conflict
    severity: str = ""              # high, medium, low


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
    # Phase 2: Structured analysis fields
    upgradePriority: List[UpgradePriorityItem] = Field(default_factory=list)
    commanderDependency: Optional[CommanderDependency] = None
    mulliganAnalysis: Optional[MulliganAnalysis] = None
    # Phase 3: Qualitative analysis fields
    removalCoverage: Optional[RemovalCoverage] = None
    rampQuality: Optional[RampQuality] = None
    drawEngineProfile: Optional[DrawEngineProfile] = None
    winConditions: List[WinCondition] = Field(default_factory=list)
    antiSynergyFlags: List[AntiSynergyFlag] = Field(default_factory=list)


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
