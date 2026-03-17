"""Pydantic response models for Commander AI Lab API."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class StartResponse(BaseModel):
    batchId: str
    status: str = "started"
    message: str = ""


class StatusResponse(BaseModel):
    batchId: str = ""
    running: bool = False
    completed: int = 0
    total: int = 0
    threads: int = 0
    elapsedMs: int = 0
    error: Optional[str] = None
    simsPerSec: float = 0.0
    run_id: str = ""
    games_completed: int = 0
    total_games: int = 0
    current_decks: list = []


class DeckInfo(BaseModel):
    name: str
    filename: str


class GeneratedDeckCard(BaseModel):
    scryfall_id: str = ""
    name: str = ""
    type_line: str = ""
    mana_cost: str = ""
    cmc: float = 0
    card_type: str = ""
    roles: list[str] = []
    source: str = "collection"
    quantity: int = 1
    image_url: str = ""
    owned_qty: int = 0
    is_proxy: bool = False
