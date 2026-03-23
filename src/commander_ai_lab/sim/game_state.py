"""
Commander AI Lab — Extended Game State (Phase 1)
=================================================
Wraps the existing SimState/Player models and adds Commander-specific
fields: commander zone, mana pool, stack, priority, and commander
damage matrix. Fully JSON-serializable.

Usage:
    from commander_ai_lab.sim.game_state import CommanderGameState, CommanderPlayer
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from commander_ai_lab.sim.models import Card, Player, SimState


# ── Mana Pool ────────────────────────────────────────────────

@dataclass
class ManaPool:
    """Tracks floating mana available to a player."""
    W: int = 0  # White
    U: int = 0  # Blue
    B: int = 0  # Black
    R: int = 0  # Red
    G: int = 0  # Green
    C: int = 0  # Colorless

    def total(self) -> int:
        return self.W + self.U + self.B + self.R + self.G + self.C

    def empty(self) -> None:
        self.W = self.U = self.B = self.R = self.G = self.C = 0

    def to_dict(self) -> dict:
        return {"W": self.W, "U": self.U, "B": self.B,
                "R": self.R, "G": self.G, "C": self.C,
                "total": self.total()}

    @classmethod
    def from_dict(cls, d: dict) -> "ManaPool":
        return cls(W=d.get("W", 0), U=d.get("U", 0), B=d.get("B", 0),
                   R=d.get("R", 0), G=d.get("G", 0), C=d.get("C", 0))


# ── Stack Item ───────────────────────────────────────────────

@dataclass
class StackItem:
    """A spell or ability on the stack."""
    item_type: str = "spell"          # "spell" | "ability" | "trigger"
    card_name: str = ""
    controller_seat: int = 0
    targets: list[str] = field(default_factory=list)
    description: str = ""             # Human-readable for prompts

    def to_dict(self) -> dict:
        return {
            "type": self.item_type,
            "cardName": self.card_name,
            "controllerSeat": self.controller_seat,
            "targets": self.targets,
            "description": self.description,
        }


# ── Commander Player ─────────────────────────────────────────

@dataclass
class CommanderPlayer:
    """
    Extends the base Player model with Commander-specific zones and tracking.
    Wraps an existing Player instance rather than subclassing to stay
    compatible with the existing simulation engine.
    """
    base: Player = field(default_factory=Player)

    # Commander zone (usually 0 or 1 card, but supports partner commanders)
    commander_zone: list[Card] = field(default_factory=list)

    # Commander tax: how many times commander has been cast from command zone
    commander_cast_count: int = 0

    # Mana pool
    mana_pool: ManaPool = field(default_factory=ManaPool)

    # Lands played this turn
    lands_played_this_turn: int = 0
    land_plays_allowed: int = 1

    # Whether this player has drawn their card this turn
    drawn_this_turn: bool = False

    # ── Convenience pass-throughs to base Player ─────────────

    @property
    def name(self) -> str:
        return self.base.name

    @property
    def life(self) -> int:
        return self.base.life

    @life.setter
    def life(self, value: int) -> None:
        self.base.life = value

    @property
    def eliminated(self) -> bool:
        return self.base.eliminated

    @property
    def owner_id(self) -> int:
        return self.base.owner_id

    @property
    def hand(self) -> list[Card]:
        return self.base.hand

    @property
    def graveyard(self) -> list[Card]:
        return self.base.graveyard

    @property
    def exile(self) -> list[Card]:
        return self.base.exile

    @property
    def library(self) -> list[Card]:
        return self.base.library

    @property
    def commander_damage_received(self) -> dict[int, int]:
        """Delegate to base Player so headless engine writes are visible."""
        return self.base.commander_damage_received

    def commander_tax(self) -> int:
        """Additional mana cost (2 per cast from command zone)."""
        return self.commander_cast_count * 2

    def is_dead_to_commander_damage(self) -> bool:
        """Returns True if any single commander has dealt 21+ damage."""
        return self.base.is_dead_to_commander_damage()

    def to_dict(self) -> dict:
        return {
            "name": self.base.name,
            "life": self.base.life,
            "eliminated": self.base.eliminated,
            "ownerId": self.base.owner_id,
            "hand": [{"name": c.name, "cmc": c.cmc, "type": c.type_line} for c in self.base.hand],
            "handSize": len(self.base.hand),
            "graveyard": [c.name for c in self.base.graveyard],
            "exile": [c.name for c in self.base.exile],
            "librarySize": len(self.base.library),
            "commanderZone": [c.name for c in self.commander_zone],
            "commanderCastCount": self.commander_cast_count,
            "commanderTax": self.commander_tax(),
            "manaPool": self.mana_pool.to_dict(),
            "landsPlayedThisTurn": self.lands_played_this_turn,
            "landPlaysAllowed": self.land_plays_allowed,
            "commanderDamageReceived": self.commander_damage_received,
        }


# ── Commander Game State ─────────────────────────────────────

@dataclass
class CommanderGameState:
    """
    Full Commander game state, extending SimState with:
    - Per-player CommanderPlayer wrappers
    - Stack with priority tracking
    - Phase/step tracking
    - Commander damage matrix
    - JSON serialization
    """

    # Core simulation state (existing engine compatibility)
    sim_state: SimState = field(default_factory=SimState)

    # Extended per-player state (parallel list to sim_state.players)
    commander_players: list[CommanderPlayer] = field(default_factory=list)

    # Stack (ordered: index 0 = bottom, last = top)
    stack: list[StackItem] = field(default_factory=list)

    # Priority
    priority_seat: int = 0          # Which player currently has priority
    active_player_seat: int = 0     # Whose turn it is

    # Phase tracking
    # Phases: untap, upkeep, draw, main1, combat_begin, combat_declare_attackers,
    #         combat_declare_blockers, combat_damage, combat_end, main2, end, cleanup
    current_phase: str = "main1"

    # Turn number (mirrors sim_state.turn)
    turn: int = 0

    # Lands played this turn (global flag for "land drop available")
    land_drop_used: bool = False

    # ── Helpers ──────────────────────────────────────────────

    # Bug 7 fix: provide .players property so turn_manager and threat_assessor
    # can reference game_state.players directly.
    @property
    def players(self) -> list[CommanderPlayer]:
        return self.commander_players

    def active_player(self) -> Optional[CommanderPlayer]:
        if 0 <= self.active_player_seat < len(self.commander_players):
            return self.commander_players[self.active_player_seat]
        return None

    def priority_player(self) -> Optional[CommanderPlayer]:
        if 0 <= self.priority_seat < len(self.commander_players):
            return self.commander_players[self.priority_seat]
        return None

    def battlefield(self, seat: int) -> list[Card]:
        """Return battlefield for given seat from underlying SimState."""
        return self.sim_state.get_battlefield(seat)

    def stack_is_empty(self) -> bool:
        return len(self.stack) == 0

    # Bug 9 fix: stub get_legal_moves() and apply_move() so turn_manager
    # doesn't crash.  These delegate to the rules engine once implemented.
    def get_legal_moves(self, seat: int) -> list[dict]:
        """Return legal moves for a seat. Stub — returns pass-only."""
        return [{"id": 0, "category": "pass_priority", "description": "Pass"}]

    def apply_move(self, seat: int, move_id: int) -> None:
        """Apply a chosen move. Stub — no-op until rules engine is wired."""
        pass

    def living_players(self) -> list[CommanderPlayer]:
        return [p for p in self.commander_players if not p.eliminated]

    def get_commander_damage(self, from_seat: int, to_seat: int) -> int:
        """Get commander damage dealt from one player to another."""
        p = self.commander_players[to_seat] if to_seat < len(self.commander_players) else None
        if p:
            return p.commander_damage_received.get(from_seat, 0)
        return 0

    def deal_commander_damage(
        self, from_seat: int, to_seat: int, amount: int,
        commander_name: str | None = None,
    ) -> None:
        """Record commander damage and reduce life total.

        If *commander_name* is provided the per-card breakdown is also
        updated (needed for partner-correct 21-damage checks).
        """
        if to_seat < len(self.commander_players):
            p = self.commander_players[to_seat]
            p.commander_damage_received[from_seat] = (
                p.commander_damage_received.get(from_seat, 0) + amount
            )
            if commander_name is not None:
                key = (from_seat, commander_name)
                p.base.commander_damage_by_card[key] = (
                    p.base.commander_damage_by_card.get(key, 0) + amount
                )
            p.life -= amount

    # ── Serialization ────────────────────────────────────────

    def to_dict(self) -> dict:
        """Full JSON-serializable snapshot of the game state."""
        return {
            "turn": self.turn,
            "currentPhase": self.current_phase,
            "activePlayerSeat": self.active_player_seat,
            "prioritySeat": self.priority_seat,
            "landDropUsed": self.land_drop_used,
            "stack": [s.to_dict() for s in self.stack],
            "players": [
                {
                    **cp.to_dict(),
                    "seat": i,
                    "battlefield": [
                        {
                            "name": c.name,
                            "type": c.type_line,
                            "tapped": c.tapped,
                            "power": c.get_power(),
                            "toughness": c.get_toughness(),
                        }
                        for c in self.sim_state.get_battlefield(i)
                    ],
                }
                for i, cp in enumerate(self.commander_players)
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize full game state to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_sim_state(cls, sim_state: SimState) -> "CommanderGameState":
        """
        Bootstrap a CommanderGameState from an existing SimState.
        Wraps each player in a CommanderPlayer, preserving all existing data.
        """
        cgs = cls(sim_state=sim_state)
        for player in sim_state.players:
            cp = CommanderPlayer(base=player)
            cgs.commander_players.append(cp)
        cgs.turn = sim_state.turn

        # Bug 18 fix: attempt to identify commanders from each player's library/hand.
        # Cards flagged is_commander=True are moved to the commander zone.
        for i, cp in enumerate(cgs.commander_players):
            for zone in [cp.base.hand, cp.base.library]:
                commanders_found = [c for c in zone if c.is_commander]
                for cmd in commanders_found:
                    zone.remove(cmd)
                    cp.commander_zone.append(cmd)

        # Bug 19 fix: sync land_drop_used from engine's per-player stats
        if sim_state.players:
            active = cgs.active_player()
            if active:
                cgs.land_drop_used = active.base.stats.lands_played > 0

        return cgs
