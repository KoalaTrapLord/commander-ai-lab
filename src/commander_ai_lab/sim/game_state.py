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

    # Commander damage received from each opponent (keyed by seat index)
    commander_damage_received: dict[int, int] = field(default_factory=dict)

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

    def commander_tax(self) -> int:
        """Additional mana cost (2 per cast from command zone)."""
        return self.commander_cast_count * 2

    def is_dead_to_commander_damage(self) -> bool:
        """Returns True if any single opponent has dealt 21+ commander damage."""
        return any(v >= 21 for v in self.commander_damage_received.values())

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

    # ── Legal Moves & Apply (BUG-02 fix) ─────────────────────
    # These replace the former pass-only stubs so that the turn manager
    # can drive real game actions through the CommanderGameState.

    def get_legal_moves(self, seat: int) -> list[dict]:
        """Return legal moves for a seat based on mana, phase, and card type.

        Move categories:
          - pass_priority: always available
          - play_land: if main phase, land drop not used, and land in hand
          - cast_spell: if main phase and castable cards in hand
          - attack: if declare_attackers phase and creatures can attack
          - instant/activate_ability: if holding-priority phases
        """
        moves: list[dict] = []
        move_id = 0

        if seat >= len(self.commander_players):
            return [{"id": 0, "category": "pass_priority", "description": "Pass"}]

        cp = self.commander_players[seat]
        player = cp.base
        bf = self.sim_state.get_battlefield(seat)

        # Available mana = untapped lands + untapped mana-producing artifacts
        available_mana = sum(
            1 for c in bf
            if not c.tapped and (c.is_land() or (c.is_ramp and not c.is_creature()))
        )

        # ── Main phase actions ──
        if self.current_phase in ("main1", "main2"):
            # Play land (one per turn)
            if not self.land_drop_used:
                for i, card in enumerate(player.hand):
                    if card.is_land():
                        moves.append({
                            "id": move_id,
                            "category": "play_land",
                            "description": f"Play land: {card.name}",
                            "card_index": i,
                            "card_name": card.name,
                        })
                        move_id += 1
                        break  # only one land drop offered

            # Cast spells from hand (sorcery-speed: creatures, sorceries,
            # artifacts, enchantments, planeswalkers)
            for i, card in enumerate(player.hand):
                if card.is_land():
                    continue
                cmc = card.cmc or 0
                if cmc <= available_mana:
                    moves.append({
                        "id": move_id,
                        "category": "cast_spell",
                        "description": f"Cast {card.name} (CMC {cmc})",
                        "card_index": i,
                        "card_name": card.name,
                    })
                    move_id += 1

            # Cast commander from command zone
            for i, cmd in enumerate(cp.commander_zone):
                tax = player.commander_tax.get(cmd.name, 0)
                total = (cmd.cmc or 0) + tax
                if total <= available_mana:
                    moves.append({
                        "id": move_id,
                        "category": "cast_spell",
                        "description": f"Cast commander {cmd.name} (cost {total}, tax {tax})",
                        "card_name": cmd.name,
                        "from_zone": "command",
                        "cmd_index": i,
                    })
                    move_id += 1

        # ── Combat: declare attackers ──
        if self.current_phase == "declare_attackers":
            attackable_creatures = [
                c for c in bf
                if c.can_attack_or_block()
                and not c.tapped
                and (c.turn_played < self.turn or c.has_keyword("haste"))
            ]
            if attackable_creatures:
                moves.append({
                    "id": move_id,
                    "category": "attack",
                    "description": f"Attack with all ({len(attackable_creatures)} creatures)",
                    "attack_mode": "all",
                })
                move_id += 1

        # ── Instant-speed responses ──
        if self.current_phase in ("upkeep", "begin_combat", "end_combat",
                                  "end_step", "declare_blockers"):
            for i, card in enumerate(player.hand):
                if card.is_instant():
                    cmc = card.cmc or 0
                    if cmc <= available_mana:
                        moves.append({
                            "id": move_id,
                            "category": "instant",
                            "description": f"Cast {card.name} (instant, CMC {cmc})",
                            "card_index": i,
                            "card_name": card.name,
                        })
                        move_id += 1

        # Always allow passing priority
        moves.append({
            "id": move_id,
            "category": "pass_priority",
            "description": "Pass",
        })

        return moves

    def apply_move(self, seat: int, move_id: int) -> None:
        """Apply a chosen move to the game state.

        Looks up the move by id in the current legal moves list and
        executes the corresponding game action.
        """
        legal = self.get_legal_moves(seat)
        move = None
        for m in legal:
            if m["id"] == move_id:
                move = m
                break
        if move is None:
            return  # invalid move id — no-op

        cat = move["category"]
        if cat == "pass_priority":
            return

        if seat >= len(self.commander_players):
            return
        cp = self.commander_players[seat]
        player = cp.base
        bf = self.sim_state.get_battlefield(seat)

        if cat == "play_land":
            idx = move.get("card_index", -1)
            if 0 <= idx < len(player.hand):
                card = player.hand.pop(idx)
                card.owner_id = seat
                card.tapped = False
                card.id = self.sim_state.next_card_id
                self.sim_state.next_card_id += 1
                self.sim_state.add_to_battlefield(seat, card)
                self.land_drop_used = True
                cp.lands_played_this_turn += 1

        elif cat == "cast_spell":
            from_zone = move.get("from_zone", "hand")
            if from_zone == "command":
                cmd_idx = move.get("cmd_index", 0)
                if cmd_idx < len(cp.commander_zone):
                    card = cp.commander_zone.pop(cmd_idx)
                    tax = player.commander_tax.get(card.name, 0)
                    total_cost = (card.cmc or 0) + tax
                    card.owner_id = seat
                    card.tapped = False
                    card.id = self.sim_state.next_card_id
                    self.sim_state.next_card_id += 1
                    card.turn_played = self.turn
                    self._tap_mana_sources(seat, total_cost)
                    self.sim_state.add_to_battlefield(seat, card)
                    player.commander_tax[card.name] = tax + 2
            else:
                idx = move.get("card_index", -1)
                if 0 <= idx < len(player.hand):
                    card = player.hand.pop(idx)
                    card.owner_id = seat
                    card.tapped = False
                    card.id = self.sim_state.next_card_id
                    self.sim_state.next_card_id += 1
                    card.turn_played = self.turn
                    self._tap_mana_sources(seat, card.cmc or 0)
                    if card.is_permanent():
                        self.sim_state.add_to_battlefield(seat, card)
                    else:
                        # Instants/sorceries go to graveyard after resolution
                        player.graveyard.append(card)

        elif cat == "instant":
            idx = move.get("card_index", -1)
            if 0 <= idx < len(player.hand):
                card = player.hand.pop(idx)
                card.owner_id = seat
                card.id = self.sim_state.next_card_id
                self.sim_state.next_card_id += 1
                self._tap_mana_sources(seat, card.cmc or 0)
                # Instants resolve and go to graveyard
                player.graveyard.append(card)

        elif cat == "attack":
            # Mark all eligible creatures as attacking (tapped)
            for c in bf:
                if (c.can_attack_or_block()
                        and not c.tapped
                        and (c.turn_played < self.turn or c.has_keyword("haste"))):
                    c.tapped = True

    def _tap_mana_sources(self, seat: int, amount: int) -> None:
        """Tap lands and mana rocks to pay a cost."""
        bf = self.sim_state.get_battlefield(seat)
        remaining = amount
        for c in bf:
            if remaining <= 0:
                break
            if not c.tapped and (c.is_land() or (c.is_ramp and not c.is_creature())):
                c.tapped = True
                remaining -= 1

    def living_players(self) -> list[CommanderPlayer]:
        return [p for p in self.commander_players if not p.eliminated]

    def get_commander_damage(self, from_seat: int, to_seat: int) -> int:
        """Get commander damage dealt from one player to another."""
        p = self.commander_players[to_seat] if to_seat < len(self.commander_players) else None
        if p:
            return p.commander_damage_received.get(from_seat, 0)
        return 0

    def deal_commander_damage(self, from_seat: int, to_seat: int, amount: int) -> None:
        """Record commander damage and reduce life total."""
        if to_seat < len(self.commander_players):
            p = self.commander_players[to_seat]
            p.commander_damage_received[from_seat] = (
                p.commander_damage_received.get(from_seat, 0) + amount
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
