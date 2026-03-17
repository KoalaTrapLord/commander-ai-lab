"""Pydantic request models for Commander AI Lab API."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class StartRequest(BaseModel):
    decks: list[str]
    numGames: int = 100
    threads: int = 4
    seed: Optional[int] = None
    clock: int = 120
    deckSources: Optional[list[Optional[dict]]] = None
    useLearnedPolicy: bool = False
    policyStyle: str = "midrange"
    policyGreedy: bool = False
    aiSimplified: bool = False
    aiThinkTimeMs: int = -1
    maxQueueDepth: int = -1


class ImportUrlRequest(BaseModel):
    url: str


class ImportTextRequest(BaseModel):
    text: str
    commander: Optional[str] = None


class MetaFetchRequest(BaseModel):
    commander: str


class CreateDeckRequest(BaseModel):
    name: str
    commander_scryfall_id: Optional[str] = ""
    commander_name: Optional[str] = ""
    color_identity: Optional[list] = []
    strategy_tag: Optional[str] = ""


class UpdateDeckRequest(BaseModel):
    name: Optional[str] = None
    commander_scryfall_id: Optional[str] = None
    commander_name: Optional[str] = None
    color_identity: Optional[list] = None
    strategy_tag: Optional[str] = None


class AddDeckCardRequest(BaseModel):
    scryfall_id: str
    card_name: Optional[str] = ""
    quantity: Optional[int] = 1
    is_commander: Optional[int] = 0
    role_tag: Optional[str] = ""


class PatchDeckCardRequest(BaseModel):
    quantity: Optional[int] = None
    role_tag: Optional[str] = None


class BulkAddRequest(BaseModel):
    cards: list[dict]
    respect_ratios: Optional[bool] = False


class BulkAddRecommendedRequest(BaseModel):
    source: str = "collection"
    only_owned: Optional[bool] = True
    respect_ratios: Optional[bool] = False
    types: Optional[list[str]] = None
    roles: Optional[list[str]] = None


class DeckGenerationSourceConfig(BaseModel):
    use_archidekt: bool = True
    use_edhrec: bool = True
    use_moxfield: bool = False
    use_mtggoldfish: bool = False
    archidekt_url: Optional[str] = ""
    moxfield_url: Optional[str] = ""
    mtggoldfish_url: Optional[str] = ""


class DeckGenerationRequest(BaseModel):
    commander_name: Optional[str] = ""
    commander_scryfall_id: Optional[str] = ""
    color_identity: Optional[list[str]] = None
    sources: Optional[DeckGenerationSourceConfig] = None
    target_land_count: int = 37
    target_instant_count: int = 10
    target_sorcery_count: int = 8
    target_artifact_count: int = 10
    target_enchantment_count: int = 8
    target_creature_count: int = 25
    target_planeswalker_count: int = 2
    only_cards_in_collection: bool = False
    allow_proxies: bool = True
    deck_name: Optional[str] = ""


class DeckGenV3Request(BaseModel):
    commander_name: str = ""
    strategy: str = ""
    target_bracket: int = 3
    budget_usd: Optional[float] = None
    budget_mode: str = "total"
    omit_cards: list[str] = []
    use_collection: bool = True
    run_substitution: bool = True
    model: Optional[str] = None
    deck_name: Optional[str] = ""


class DeckGenV3SubstituteRequest(BaseModel):
    card_name: str
    substitute_name: str
