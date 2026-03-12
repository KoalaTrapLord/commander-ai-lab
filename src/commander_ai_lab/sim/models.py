"""
Commander AI Lab — Simulator Models
====================================
Data classes for Card, Player, PlayerStats, and SimState.
Ported from mtg-commander-lan JavaScript (dtCreatePlayer, dtSimGame structs).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Card:
    """A single card in the simulation."""

    name: str = ""
    type_line: str = ""
    oracle_text: str = ""
    cmc: int = 0
    pt: str = ""  # e.g. "3/4"
    mana_cost: str = ""
    power: str = ""
    toughness: str = ""
    color_identity: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    # Functional flags (set by enrich_card)
    is_ramp: bool = False
    is_removal: bool = False
    is_board_wipe: bool = False
    is_commander: bool = False

    # Runtime fields (set during game)
    id: int = 0
    owner_id: int = -1
    tapped: bool = False
    turn_played: int = -1

    def get_power(self) -> int:
        """Extract numeric power from pt string."""
        if self.power:
            try:
                return int(self.power)
            except ValueError:
                return 0
        if not self.pt:
            return 0
        parts = self.pt.split("/")
        try:
            return int(parts[0])
        except (ValueError, IndexError):
            return 0

    def get_toughness(self) -> int:
        """Extract numeric toughness from pt string."""
        if self.toughness:
            try:
                return int(self.toughness)
            except ValueError:
                return 0
        if not self.pt:
            return 0
        parts = self.pt.split("/")
        try:
            return int(parts[1])
        except (ValueError, IndexError):
            return 0

    def has_keyword(self, kw: str) -> bool:
        """Check if card has a keyword (checks keywords list and oracle text)."""
        kw_lower = kw.lower()
        if self.keywords and any(k.lower() == kw_lower for k in self.keywords):
            return True
        return kw_lower in (self.oracle_text or "").lower()

    def is_land(self) -> bool:
        return bool(self.type_line and "land" in self.type_line.lower())

    def is_creature(self) -> bool:
        return bool(self.type_line and "creature" in self.type_line.lower())

    def clone(self) -> "Card":
        """Return a deep copy of this card."""
        return copy.deepcopy(self)


@dataclass
class PlayerStats:
    """Per-game statistics tracked for a player."""

    cards_drawn: int = 7  # starting hand
    lands_played: int = 0
    spells_cast: int = 0
    creatures_played: int = 0
    removal_used: int = 0
    board_wipes_used: int = 0
    ramp_played: int = 0
    damage_dealt: int = 0
    damage_received: int = 0
    max_board_size: int = 0
    turns_alive: int = 0
    mana_spent: int = 0

    def to_dict(self) -> dict:
        return {
            "cardsDrawn": self.cards_drawn,
            "landsPlayed": self.lands_played,
            "spellsCast": self.spells_cast,
            "creaturesPlayed": self.creatures_played,
            "removalUsed": self.removal_used,
            "boardWipesUsed": self.board_wipes_used,
            "rampPlayed": self.ramp_played,
            "damageDealt": self.damage_dealt,
            "damageReceived": self.damage_received,
            "maxBoardSize": self.max_board_size,
            "turnsAlive": self.turns_alive,
            "manaSpent": self.mana_spent,
        }


@dataclass
class Player:
    """A player in the headless simulation."""

    name: str = ""
    life: int = 40
    eliminated: bool = False
    owner_id: int = 0

    # Zones
    library: list[Card] = field(default_factory=list)
    hand: list[Card] = field(default_factory=list)
    graveyard: list[Card] = field(default_factory=list)
    exile: list[Card] = field(default_factory=list)

    stats: PlayerStats = field(default_factory=PlayerStats)


@dataclass
class SimState:
    """Full simulation state for a headless game."""

    players: list[Player] = field(default_factory=list)
    battlefield: list[Card] = field(default_factory=list)
    turn: int = 0
    max_turns: int = 25
    next_card_id: int = 90000


@dataclass
class GameResult:
    """Result of a single simulated game."""

    winner: int = -1  # 0 or 1 (player index), -1 = draw
    turns: int = 0
    player_a_name: str = ""
    player_a_life: int = 0
    player_a_eliminated: bool = False
    player_a_stats: Optional[PlayerStats] = None
    player_b_name: str = ""
    player_b_life: int = 0
    player_b_eliminated: bool = False
    player_b_stats: Optional[PlayerStats] = None
    game_log: list = field(default_factory=list)  # turn-by-turn log (populated when record_log=True)

    def to_dict(self) -> dict:
        d = {
            "winner": self.winner,
            "turns": self.turns,
            "playerA": {
                "name": self.player_a_name,
                "life": self.player_a_life,
                "eliminated": self.player_a_eliminated,
                "stats": self.player_a_stats.to_dict() if self.player_a_stats else {},
            },
            "playerB": {
                "name": self.player_b_name,
                "life": self.player_b_life,
                "eliminated": self.player_b_eliminated,
                "stats": self.player_b_stats.to_dict() if self.player_b_stats else {},
            },
        }
        if self.game_log:
            d["gameLog"] = self.game_log
        return d
