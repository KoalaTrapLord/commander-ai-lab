"""
Commander AI Lab — Simulator Models
====================================
Data classes for Card, Player, PlayerResult, PlayerStats, SimState, and GameResult.
Ported from mtg-commander-lan JavaScript (dtCreatePlayer, dtSimGame structs).

N-player ready: GameResult.players is a list[PlayerResult] (no hardcoded seat count).
SimState.battlefields is per-player: battlefields[seat_index] holds that player's permanents.
"""

from __future__ import annotations

import copy
import enum
import json
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Turn Phases ──────────────────────────────────────────────

class Phase(str, enum.Enum):
    """MTG turn phases in order.

    Using ``str`` as a mixin allows direct comparison with plain strings
    and clean JSON serialization (``phase.value`` is a string).
    """

    UNTAP = "untap"
    UPKEEP = "upkeep"
    DRAW = "draw"
    MAIN1 = "main1"
    BEGIN_COMBAT = "begin_combat"
    DECLARE_ATTACKERS = "declare_attackers"
    DECLARE_BLOCKERS = "declare_blockers"
    COMBAT_DAMAGE = "combat_damage"
    END_COMBAT = "end_combat"
    MAIN2 = "main2"
    END_STEP = "end_step"
    CLEANUP = "cleanup"


# Ordered tuple for iteration
PHASE_ORDER: tuple[Phase, ...] = tuple(Phase)

# Phases where sorcery-speed actions (land drops, casting creatures) are legal
SORCERY_PHASES: frozenset[Phase] = frozenset({Phase.MAIN1, Phase.MAIN2})


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
    is_direct_damage: bool = False
    direct_damage_amount: int = 0

    # Runtime fields (set during game)
    id: int = 0
    owner_id: int = -1
    tapped: bool = False
    turn_played: int = -1
    damage_marked: int = 0  # track damage marked on creature (cleared each cleanup step)

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
        # Bug 15 fix: word-boundary match prevents false positives
        # (e.g. "reach" matching "breach", "ward" matching "reward")
        return bool(re.search(r'\b' + re.escape(kw_lower) + r'\b', (self.oracle_text or "").lower()))

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
    mulligans: int = 0
    opening_hand_lands: int = 0
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
            "mulligans": self.mulligans,
            "openingHandLands": self.opening_hand_lands,
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
    command_zone: list[Card] = field(default_factory=list)

    # commander_tax tracks the cumulative tax per commander name.
    # Keyed by card name so N-player pods with multiple commanders
    # each track their own tax independently.
    # engine._play_spells uses: tax = p.commander_tax.get(name, 0)
    #                           p.commander_tax[name] = tax + 2
    commander_tax: dict = field(default_factory=dict)

    # Commander damage received from each opponent, keyed by seat index.
    # This is the aggregate per-seat total (used by GUI matrix and prompt
    # builder).  For games where a player controls partner commanders
    # the per-card breakdown lives in commander_damage_by_card.
    commander_damage_received: dict[int, int] = field(default_factory=dict)

    # Per-commander breakdown: {(seat, card_name): damage}.
    # In MTG rules, lethal commander damage (21+) is tracked per individual
    # commander card, not per player.  This dict captures that.
    commander_damage_by_card: dict[tuple[int, str], int] = field(default_factory=dict)

    stats: PlayerStats = field(default_factory=PlayerStats)

    def is_dead_to_commander_damage(self) -> bool:
        """Returns True if any single commander has dealt 21+ damage.

        Checks per-card tracking first (partner-correct); falls back to
        per-seat totals for backward compatibility with older game states.
        """
        if self.commander_damage_by_card:
            return any(v >= 21 for v in self.commander_damage_by_card.values())
        return any(v >= 21 for v in self.commander_damage_received.values())


@dataclass
class SimState:
    """Full simulation state for a headless game.

    battlefields is a list-of-lists: battlefields[seat_index] holds
    the permanents controlled by that player. Legacy single-list code
    should use the helpers get_battlefield() / all_battlefield_cards().
    """

    players: list[Player] = field(default_factory=list)
    battlefields: list[list[Card]] = field(default_factory=list)
    turn: int = 0
    max_turns: int = 25
    next_card_id: int = 90000
    current_phase: Phase = Phase.MAIN1
    active_player_index: int = 0

    # ── Battlefield helpers ──────────────────────────────────

    def get_battlefield(self, seat: int) -> list[Card]:
        """Return the battlefield list for a given seat index."""
        while len(self.battlefields) <= seat:
            self.battlefields.append([])
        return self.battlefields[seat]

    def all_battlefield_cards(self) -> list[Card]:
        """Return a flat list of every card on every player's battlefield."""
        cards: list[Card] = []
        for bf in self.battlefields:
            cards.extend(bf)
        return cards

    def add_to_battlefield(self, seat: int, card: Card) -> None:
        """Place a card onto the given player's battlefield."""
        while len(self.battlefields) <= seat:
            self.battlefields.append([])
        self.battlefields[seat].append(card)

    def remove_from_battlefield(self, card_id: int) -> Optional[Card]:
        """Remove a card by id from any player's battlefield. Returns the card or None."""
        for bf in self.battlefields:
            for i, c in enumerate(bf):
                if c.id == card_id:
                    return bf.pop(i)
        return None

    def filter_battlefield(self, seat: int, predicate) -> list[Card]:
        """Remove cards from seat's battlefield that don't match predicate, return removed."""
        bf = self.get_battlefield(seat)
        keep = []
        removed = []
        for c in bf:
            if predicate(c):
                keep.append(c)
            else:
                removed.append(c)
        self.battlefields[seat] = keep
        return removed

    def init_battlefields(self, num_players: int) -> None:
        """Ensure battlefields list has one empty list per player."""
        while len(self.battlefields) < num_players:
            self.battlefields.append([])


# ══════════════════════════════════════════════════════════════
# Game Results — N-player ready
# ══════════════════════════════════════════════════════════════

@dataclass
class PlayerResult:
    """Post-game result snapshot for one player.

    Matches the Java BatchResult.PlayerResult schema structure.
    """

    seat_index: int = 0
    name: str = ""
    life: int = 0
    eliminated: bool = False
    finish_position: int = 0  # 1 = winner, 2+ = elimination order
    stats: Optional[PlayerStats] = None

    def to_dict(self) -> dict:
        return {
            "seatIndex": self.seat_index,
            "name": self.name,
            "finalLife": self.life,
            "eliminated": self.eliminated,
            "finishPosition": self.finish_position,
            "isWinner": self.finish_position == 1,
            "stats": self.stats.to_dict() if self.stats else {},
        }


@dataclass
class GameResult:
    """Result of a single simulated game (N-player ready).

    - players: list of PlayerResult, one per seat
    - winner_seat: index of the winning player (-1 = draw)
    - Backward-compat properties player_a_stats / player_b_stats delegate to players[0] / players[1]
    """

    winner_seat: int = -1
    turns: int = 0
    players: list[PlayerResult] = field(default_factory=list)
    game_log: list = field(default_factory=list)

    # ── Convenience accessors ────────────────────────────────

    def player(self, seat: int) -> Optional[PlayerResult]:
        """Safe accessor for a seat's result."""
        if 0 <= seat < len(self.players):
            return self.players[seat]
        return None

    # Backward-compat properties so existing code referencing
    # result.player_a_stats or result.winner keeps working.

    @property
    def winner(self) -> int:
        return self.winner_seat

    @property
    def player_a_stats(self) -> Optional[PlayerStats]:
        p = self.player(0)
        return p.stats if p else None

    @property
    def player_b_stats(self) -> Optional[PlayerStats]:
        p = self.player(1)
        return p.stats if p else None

    @property
    def player_a_name(self) -> str:
        p = self.player(0)
        return p.name if p else ""

    @property
    def player_b_name(self) -> str:
        p = self.player(1)
        return p.name if p else ""

    @property
    def player_a_life(self) -> int:
        p = self.player(0)
        return p.life if p else 0

    @property
    def player_b_life(self) -> int:
        p = self.player(1)
        return p.life if p else 0

    @property
    def player_a_eliminated(self) -> bool:
        p = self.player(0)
        return p.eliminated if p else False

    @property
    def player_b_eliminated(self) -> bool:
        p = self.player(1)
        return p.eliminated if p else False

    def to_dict(self) -> dict:
        """Serialize to dict.

        Returns both the legacy 2-player keys (winner, playerA, playerB)
        that the existing UI and lab_api consumers expect AND the new
        N-player 'playerResults' array for the Java BatchResult schema.
        """
        d: dict = {
            # Legacy keys (UI expects these)
            "winner": self.winner_seat,
            "turns": self.turns,
            # New N-player keys (Java BatchResult schema)
            "winningSeat": self.winner_seat,
            "playerResults": [p.to_dict() for p in self.players],
        }

        # Legacy playerA / playerB dicts for the UI
        pa = self.player(0)
        pb = self.player(1)
        d["playerA"] = {
            "name": pa.name if pa else "",
            "life": pa.life if pa else 0,
            "eliminated": pa.eliminated if pa else False,
            "stats": pa.stats.to_dict() if pa and pa.stats else {},
        }
        d["playerB"] = {
            "name": pb.name if pb else "",
            "life": pb.life if pb else 0,
            "eliminated": pb.eliminated if pb else False,
            "stats": pb.stats.to_dict() if pb and pb.stats else {},
        }

        if self.game_log:
            d["gameLog"] = self.game_log
        return d
