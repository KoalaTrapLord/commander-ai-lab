"""
Commander AI Lab — Interactive Play Routes
============================================
REST API for the 3D tabletop Unity client.
Manages interactive game sessions with step-by-step turn execution.

Endpoints:
  POST /api/play/new        — Create a new 4-player game session
  GET  /api/play/state      — Get current game snapshot
  POST /api/play/action      — Submit a player action (play card, attack, pass)
  POST /api/play/next-phase  — Advance to next phase
  POST /api/play/ai-turn     — Let the AI decide and execute its turn
  GET  /api/play/legal-moves — Get legal moves for the active player
"""

import logging
import uuid
import random
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

log = logging.getLogger("commander_ai_lab.play")
router = APIRouter(prefix="/api/play", tags=["play"])

# ── In-memory session store ──────────────────────────────────────
_sessions: dict[str, "GameSession"] = {}

PHASES = ["untap", "upkeep", "draw", "main1", "combat_begin",
          "combat_attackers", "combat_blockers", "combat_damage",
          "combat_end", "main2", "end", "cleanup"]


# ── Pydantic Models ─────────────────────────────────────────────

class NewGameRequest(BaseModel):
    deck_ids: list[str] = Field(default_factory=list,
        description="List of 4 deck IDs; empty = use random precons")
    player_names: list[str] = Field(
        default=["You", "AI-Aggro", "AI-Control", "AI-Combo"])
    human_seat: int = Field(default=0, ge=0, le=3)

class ActionRequest(BaseModel):
    session_id: str
    action_type: str  # "play_card", "attack", "block", "activate", "pass"
    card_id: Optional[int] = None
    target_seat: Optional[int] = None

class BoardCardDTO(BaseModel):
    id: int
    name: str
    type_line: str
    cmc: int
    power: str = ""
    toughness: str = ""
    mana_cost: str = ""
    oracle_text: str = ""
    image_uri: str = ""
    tapped: bool = False
    is_commander: bool = False
    is_creature: bool = False
    owner_seat: int = 0

class PlayerStateDTO(BaseModel):
    seat: int
    name: str
    life: int
    is_human: bool
    eliminated: bool
    hand_count: int
    library_count: int
    hand: list[BoardCardDTO] = []        # only populated for human
    battlefield: list[BoardCardDTO] = []
    graveyard: list[BoardCardDTO] = []
    command_zone: list[BoardCardDTO] = []
    commander_tax: dict = {}
    mana_available: int = 0

class GameStateDTO(BaseModel):
    session_id: str
    turn: int
    phase: str
    active_seat: int
    priority_seat: int
    players: list[PlayerStateDTO]
    log: list[str] = []
    game_over: bool = False
    winner_seat: int = -1

class LegalMoveDTO(BaseModel):
    action_type: str
    card_id: Optional[int] = None
    card_name: Optional[str] = None
    description: str = ""


# ── Internal Game Session ────────────────────────────────────────

class _Card:
    """Lightweight card for the play prototype."""
    __slots__ = ("id", "name", "type_line", "cmc", "power", "toughness",
                 "mana_cost", "oracle_text", "image_uri", "tapped",
                 "is_commander", "is_ramp", "is_removal", "is_board_wipe",
                 "owner_seat", "turn_played", "color_identity", "keywords")

    _next_id = 90000

    def __init__(self, name="Unknown", type_line="", cmc=0, **kw):
        _Card._next_id += 1
        self.id = _Card._next_id
        self.name = name
        self.type_line = type_line
        self.cmc = cmc
        self.power = kw.get("power", "")
        self.toughness = kw.get("toughness", "")
        self.mana_cost = kw.get("mana_cost", "")
        self.oracle_text = kw.get("oracle_text", "")
        self.image_uri = kw.get("image_uri", "")
        self.tapped = False
        self.is_commander = kw.get("is_commander", False)
        self.is_ramp = kw.get("is_ramp", False)
        self.is_removal = kw.get("is_removal", False)
        self.is_board_wipe = kw.get("is_board_wipe", False)
        self.owner_seat = kw.get("owner_seat", 0)
        self.turn_played = -1
        self.color_identity = kw.get("color_identity", [])
        self.keywords = kw.get("keywords", [])

    def is_land(self):
        return "land" in self.type_line.lower()

    def is_creature(self):
        return "creature" in self.type_line.lower()

    def get_power(self):
        try: return int(self.power)
        except: return 0

    def get_toughness(self):
        try: return int(self.toughness)
        except: return 0

    def to_dto(self) -> BoardCardDTO:
        return BoardCardDTO(
            id=self.id, name=self.name, type_line=self.type_line,
            cmc=self.cmc, power=self.power, toughness=self.toughness,
            mana_cost=self.mana_cost, oracle_text=self.oracle_text,
            image_uri=self.image_uri, tapped=self.tapped,
            is_commander=self.is_commander, is_creature=self.is_creature(),
            owner_seat=self.owner_seat
        )


class _Player:
    def __init__(self, seat: int, name: str, is_human: bool):
        self.seat = seat
        self.name = name
        self.is_human = is_human
        self.life = 40
        self.eliminated = False
        self.library: list[_Card] = []
        self.hand: list[_Card] = []
        self.battlefield: list[_Card] = []
        self.graveyard: list[_Card] = []
        self.command_zone: list[_Card] = []
        self.exile: list[_Card] = []
        self.commander_tax: dict[str, int] = {}
        self.land_played_this_turn = False

    @property
    def mana_available(self) -> int:
        return sum(1 for c in self.battlefield if c.is_land() and not c.tapped)

    def to_dto(self, reveal_hand: bool = False) -> PlayerStateDTO:
        return PlayerStateDTO(
            seat=self.seat, name=self.name, life=self.life,
            is_human=self.is_human, eliminated=self.eliminated,
            hand_count=len(self.hand), library_count=len(self.library),
            hand=[c.to_dto() for c in self.hand] if reveal_hand else [],
            battlefield=[c.to_dto() for c in self.battlefield],
            graveyard=[c.to_dto() for c in self.graveyard],
            command_zone=[c.to_dto() for c in self.command_zone],
            commander_tax=self.commander_tax,
            mana_available=self.mana_available
        )


# ── Sample card pool for prototype ──────────────────────────────

_SAMPLE_COMMANDERS = [
    {"name": "Atraxa, Praetors' Voice", "type_line": "Legendary Creature — Phyrexian Angel Horror",
     "cmc": 4, "power": "4", "toughness": "4", "mana_cost": "{G}{W}{U}{B}",
     "image_uri": "https://cards.scryfall.io/normal/front/d/0/d0d33d52-3d28-4635-b985-51e126289259.jpg",
     "color_identity": ["W","U","B","G"], "keywords": ["Flying","Vigilance","Deathtouch","Lifelink"]},
    {"name": "Ur-Dragon, The", "type_line": "Legendary Creature — Dragon Avatar",
     "cmc": 9, "power": "10", "toughness": "10", "mana_cost": "{4}{W}{U}{B}{R}{G}",
     "image_uri": "https://cards.scryfall.io/normal/front/7/e/7e78b70b-0c67-4f14-8ad7-c9f8e3f59743.jpg",
     "color_identity": ["W","U","B","R","G"], "keywords": ["Flying"]},
    {"name": "Korvold, Fae-Cursed King", "type_line": "Legendary Creature — Dragon Noble",
     "cmc": 5, "power": "4", "toughness": "4", "mana_cost": "{2}{B}{R}{G}",
     "image_uri": "https://cards.scryfall.io/normal/front/9/2/92ea1575-eb64-43b5-b604-d6e9e6f8571c.jpg",
     "color_identity": ["B","R","G"], "keywords": ["Flying"]},
    {"name": "Muldrotha, the Gravetide", "type_line": "Legendary Creature — Elemental Avatar",
     "cmc": 6, "power": "6", "toughness": "6", "mana_cost": "{3}{B}{G}{U}",
     "image_uri": "https://cards.scryfall.io/normal/front/c/6/c654737d-34ac-42ff-ae27-3a3bbb930fc1.jpg",
     "color_identity": ["B","G","U"], "keywords": []},
]

_SAMPLE_CARDS = [
    {"name": "Sol Ring", "type_line": "Artifact", "cmc": 1, "mana_cost": "{1}", "is_ramp": True,
     "image_uri": "https://cards.scryfall.io/normal/front/4/c/4cbc6901-6a4a-4d0a-83ea-7eefa3b35021.jpg"},
    {"name": "Command Tower", "type_line": "Land", "cmc": 0,
     "image_uri": "https://cards.scryfall.io/normal/front/b/7/b7f6d929-6571-4fee-9a1a-1fad3ffa5765.jpg"},
    {"name": "Arcane Signet", "type_line": "Artifact", "cmc": 2, "mana_cost": "{2}", "is_ramp": True,
     "image_uri": "https://cards.scryfall.io/normal/front/f/0/f0b666de-5a89-417d-a946-00aafd1f1f11.jpg"},
    {"name": "Swords to Plowshares", "type_line": "Instant", "cmc": 1, "mana_cost": "{W}", "is_removal": True,
     "image_uri": "https://cards.scryfall.io/normal/front/7/d/7d839f21-68c7-47db-8407-ff3e2c3e13b4.jpg"},
    {"name": "Llanowar Elves", "type_line": "Creature — Elf Druid", "cmc": 1, "power": "1", "toughness": "1",
     "mana_cost": "{G}", "is_ramp": True,
     "image_uri": "https://cards.scryfall.io/normal/front/8/b/8bbcfb77-daa1-4ce5-b5f9-48d0a8edbba9.jpg"},
    {"name": "Beast Within", "type_line": "Instant", "cmc": 3, "mana_cost": "{2}{G}", "is_removal": True,
     "image_uri": "https://cards.scryfall.io/normal/front/5/0/50b063b2-020f-41ae-b2ce-b34c3e0889c3.jpg"},
    {"name": "Cultivate", "type_line": "Sorcery", "cmc": 3, "mana_cost": "{2}{G}", "is_ramp": True,
     "image_uri": "https://cards.scryfall.io/normal/front/b/d/bd71a79c-0068-4a63-a3b2-bb5bbd8e8841.jpg"},
    {"name": "Wrath of God", "type_line": "Sorcery", "cmc": 4, "mana_cost": "{2}{W}{W}", "is_board_wipe": True,
     "image_uri": "https://cards.scryfall.io/normal/front/6/6/664e6656-36a3-4f5b-9851-1335e58e9290.jpg"},
    {"name": "Sakura-Tribe Elder", "type_line": "Creature — Snake Shaman", "cmc": 2, "power": "1", "toughness": "1",
     "mana_cost": "{1}{G}", "is_ramp": True,
     "image_uri": "https://cards.scryfall.io/normal/front/c/8/c83be2b7-0373-4389-9aa0-523db58f4d2a.jpg"},
    {"name": "Lightning Greaves", "type_line": "Artifact — Equipment", "cmc": 2, "mana_cost": "{2}",
     "image_uri": "https://cards.scryfall.io/normal/front/8/d/8d9f47af-5929-44f4-bc6b-3ac7e521b959.jpg"},
    {"name": "Kodama's Reach", "type_line": "Sorcery — Arcane", "cmc": 3, "mana_cost": "{2}{G}", "is_ramp": True,
     "image_uri": "https://cards.scryfall.io/normal/front/8/d/8da1bbb5-7884-46a9-962b-cfc9fe35500a.jpg"},
    {"name": "Counterspell", "type_line": "Instant", "cmc": 2, "mana_cost": "{U}{U}", "is_removal": True,
     "image_uri": "https://cards.scryfall.io/normal/front/1/9/1920c024-6440-4966-bbe2-28150cd72e12.jpg"},
    {"name": "Rhystic Study", "type_line": "Enchantment", "cmc": 3, "mana_cost": "{2}{U}",
     "image_uri": "https://cards.scryfall.io/normal/front/d/6/d6914dba-0d27-4055-ac34-b3ebf5802f94.jpg"},
    {"name": "Smothering Tithe", "type_line": "Enchantment", "cmc": 4, "mana_cost": "{3}{W}",
     "image_uri": "https://cards.scryfall.io/normal/front/f/2/f25a4bbe-2af0-4d4a-95d4-d52c5937c747.jpg"},
    {"name": "Eternal Witness", "type_line": "Creature — Human Shaman", "cmc": 3, "power": "2", "toughness": "1",
     "mana_cost": "{1}{G}{G}",
     "image_uri": "https://cards.scryfall.io/normal/front/d/7/d74e7ded-d063-4d90-a9ff-91c44a8098d7.jpg"},
    # Lands (fill out a deck)
    {"name": "Forest", "type_line": "Basic Land — Forest", "cmc": 0,
     "image_uri": "https://cards.scryfall.io/normal/front/1/9/19e540dc-dfad-44bc-8a1a-4e3f7134d0c4.jpg"},
    {"name": "Island", "type_line": "Basic Land — Island", "cmc": 0,
     "image_uri": "https://cards.scryfall.io/normal/front/b/2/b2bcb22e-1a5a-4578-82bf-82522e6c85d8.jpg"},
    {"name": "Plains", "type_line": "Basic Land — Plains", "cmc": 0,
     "image_uri": "https://cards.scryfall.io/normal/front/2/c/2c15cfba-e1c6-4e24-b5d0-19c4920796c1.jpg"},
    {"name": "Swamp", "type_line": "Basic Land — Swamp", "cmc": 0,
     "image_uri": "https://cards.scryfall.io/normal/front/f/c/fc4111be-6dae-4ca5-b4b4-3a93fa3e7295.jpg"},
    {"name": "Mountain", "type_line": "Basic Land — Mountain", "cmc": 0,
     "image_uri": "https://cards.scryfall.io/normal/front/c/7/c7a0f0f4-3344-4d7e-8a56-5d5e62e8c9d4.jpg"},
]


def _build_sample_deck(seat: int, commander_idx: int) -> tuple[_Card, list[_Card]]:
    """Build a 100-card sample deck from the prototype card pool."""
    cmdr_data = _SAMPLE_COMMANDERS[commander_idx % len(_SAMPLE_COMMANDERS)]
    commander = _Card(**cmdr_data, is_commander=True, owner_seat=seat)

    cards: list[_Card] = []
    # Add non-land spells
    for cd in _SAMPLE_CARDS:
        if not cd.get("type_line", "").lower().startswith("basic land"):
            cards.append(_Card(**cd, owner_seat=seat))

    # Fill remaining with basic lands
    land_pool = [cd for cd in _SAMPLE_CARDS if "basic land" in cd.get("type_line", "").lower()]
    while len(cards) < 99:
        land_data = random.choice(land_pool)
        cards.append(_Card(**land_data, owner_seat=seat))

    random.shuffle(cards)
    return commander, cards


class GameSession:
    def __init__(self, session_id: str, player_names: list[str], human_seat: int):
        self.session_id = session_id
        self.turn = 1
        self.phase_idx = 0
        self.active_seat = 0
        self.human_seat = human_seat
        self.game_over = False
        self.winner_seat = -1
        self.log: list[str] = []
        self.players: list[_Player] = []

        for i, name in enumerate(player_names):
            p = _Player(seat=i, name=name, is_human=(i == human_seat))
            cmdr, deck = _build_sample_deck(i, i)
            p.command_zone.append(cmdr)
            p.library = deck
            # Draw opening hand of 7
            for _ in range(7):
                if p.library:
                    p.hand.append(p.library.pop(0))
            self.players.append(p)

        self.log.append(f"Game started! {len(self.players)} players.")

    @property
    def phase(self) -> str:
        return PHASES[self.phase_idx]

    def _active_player(self) -> _Player:
        return self.players[self.active_seat]

    def advance_phase(self) -> str:
        """Advance to the next phase. Returns the new phase name."""
        self.phase_idx += 1
        if self.phase_idx >= len(PHASES):
            self.phase_idx = 0
            self._advance_turn()

        p = self._active_player()
        phase = self.phase

        # Auto-execute untap / upkeep / draw
        if phase == "untap":
            for c in p.battlefield:
                c.tapped = False
            p.land_played_this_turn = False
            self.log.append(f"Turn {self.turn}: {p.name} untaps.")
            return self.advance_phase()

        if phase == "upkeep":
            self.log.append(f"{p.name}'s upkeep.")
            return self.advance_phase()

        if phase == "draw":
            if p.library:
                drawn = p.library.pop(0)
                p.hand.append(drawn)
                if p.is_human:
                    self.log.append(f"You drew {drawn.name}.")
                else:
                    self.log.append(f"{p.name} draws a card.")
            return self.advance_phase()

        return phase

    def _advance_turn(self):
        """Move to the next non-eliminated player."""
        for _ in range(len(self.players)):
            self.active_seat = (self.active_seat + 1) % len(self.players)
            if not self.players[self.active_seat].eliminated:
                break
        if self.active_seat == 0:
            self.turn += 1
        # Check if only one player left
        alive = [p for p in self.players if not p.eliminated]
        if len(alive) <= 1:
            self.game_over = True
            self.winner_seat = alive[0].seat if alive else -1
            self.log.append(f"Game over! {alive[0].name if alive else 'Nobody'} wins!")

    def play_card(self, card_id: int) -> str:
        """Play a card from hand to battlefield (or as land)."""
        p = self._active_player()
        card = next((c for c in p.hand if c.id == card_id), None)
        if not card:
            # Check command zone
            card = next((c for c in p.command_zone if c.id == card_id), None)
            if card:
                tax = p.commander_tax.get(card.name, 0)
                effective_cost = card.cmc + tax
                if p.mana_available < effective_cost:
                    return f"Not enough mana for {card.name} (need {effective_cost})"
                # Tap lands for mana
                paid = 0
                for land in p.battlefield:
                    if land.is_land() and not land.tapped and paid < effective_cost:
                        land.tapped = True
                        paid += 1
                p.command_zone.remove(card)
                p.commander_tax[card.name] = tax + 2
                p.battlefield.append(card)
                card.tapped = False
                self.log.append(f"{p.name} casts {card.name} from command zone (tax {tax})!")
                return f"Cast {card.name} from command zone"
            return "Card not found in hand or command zone"

        if card.is_land():
            if p.land_played_this_turn:
                return "Already played a land this turn"
            p.hand.remove(card)
            p.battlefield.append(card)
            p.land_played_this_turn = True
            self.log.append(f"{p.name} plays {card.name}.")
            return f"Played {card.name}"

        # Non-land: check mana
        if p.mana_available < card.cmc:
            return f"Not enough mana for {card.name} (need {card.cmc}, have {p.mana_available})"

        # Tap lands
        paid = 0
        for land in p.battlefield:
            if land.is_land() and not land.tapped and paid < card.cmc:
                land.tapped = True
                paid += 1

        p.hand.remove(card)
        p.battlefield.append(card)
        self.log.append(f"{p.name} casts {card.name}.")
        return f"Cast {card.name}"

    def attack(self, card_id: int, target_seat: int) -> str:
        """Declare an attacker targeting a player."""
        p = self._active_player()
        card = next((c for c in p.battlefield if c.id == card_id and c.is_creature()), None)
        if not card:
            return "Creature not found on battlefield"
        if card.tapped:
            return f"{card.name} is tapped"
        if card.turn_played == self.turn:
            return f"{card.name} has summoning sickness"

        target = self.players[target_seat] if 0 <= target_seat < len(self.players) else None
        if not target or target.eliminated:
            return "Invalid target"

        card.tapped = True
        dmg = card.get_power()
        target.life -= dmg
        self.log.append(f"{p.name}'s {card.name} attacks {target.name} for {dmg}!")

        if target.life <= 0:
            target.eliminated = True
            self.log.append(f"{target.name} has been eliminated!")
            # Check win condition
            alive = [pp for pp in self.players if not pp.eliminated]
            if len(alive) <= 1:
                self.game_over = True
                self.winner_seat = alive[0].seat if alive else -1

        return f"{card.name} dealt {dmg} damage to {target.name}"

    def ai_turn(self) -> list[str]:
        """Execute a full AI turn with heuristic decisions."""
        p = self._active_player()
        if p.is_human:
            return ["It's your turn!"]

        actions: list[str] = []

        # Play a land if possible
        lands = [c for c in p.hand if c.is_land()]
        if lands and not p.land_played_this_turn:
            result = self.play_card(lands[0].id)
            actions.append(result)

        # Cast spells (cheapest first, prioritize ramp > removal > creatures)
        castable = sorted(
            [c for c in p.hand if not c.is_land() and c.cmc <= p.mana_available],
            key=lambda c: (-(c.is_ramp + c.is_removal * 2), c.cmc)
        )
        for card in castable:
            if p.mana_available >= card.cmc:
                result = self.play_card(card.id)
                actions.append(result)

        # Cast commander if affordable
        for cmd in list(p.command_zone):
            tax = p.commander_tax.get(cmd.name, 0)
            if p.mana_available >= cmd.cmc + tax:
                result = self.play_card(cmd.id)
                actions.append(result)

        # Attack with all available creatures
        creatures = [c for c in p.battlefield if c.is_creature()
                     and not c.tapped and c.turn_played < self.turn]
        if creatures:
            # Pick target: weakest non-eliminated opponent
            targets = [pp for pp in self.players
                       if pp.seat != p.seat and not pp.eliminated]
            if targets:
                target = min(targets, key=lambda pp: pp.life)
                for creature in creatures:
                    result = self.attack(creature.id, target.seat)
                    actions.append(result)

        if not actions:
            actions.append(f"{p.name} passes.")
            self.log.append(f"{p.name} passes.")

        return actions

    def get_legal_moves(self) -> list[LegalMoveDTO]:
        """Return all legal moves for the active player."""
        p = self._active_player()
        moves: list[LegalMoveDTO] = []

        if self.phase in ("main1", "main2"):
            # Lands
            if not p.land_played_this_turn:
                for c in p.hand:
                    if c.is_land():
                        moves.append(LegalMoveDTO(
                            action_type="play_card", card_id=c.id,
                            card_name=c.name, description=f"Play {c.name}"))

            # Castable spells
            for c in p.hand:
                if not c.is_land() and c.cmc <= p.mana_available:
                    moves.append(LegalMoveDTO(
                        action_type="play_card", card_id=c.id,
                        card_name=c.name,
                        description=f"Cast {c.name} ({c.mana_cost})"))

            # Commander from command zone
            for c in p.command_zone:
                tax = p.commander_tax.get(c.name, 0)
                if p.mana_available >= c.cmc + tax:
                    moves.append(LegalMoveDTO(
                        action_type="play_card", card_id=c.id,
                        card_name=c.name,
                        description=f"Cast {c.name} from command zone (tax {tax})"))

        if self.phase in ("combat_attackers",):
            targets = [pp for pp in self.players
                       if pp.seat != p.seat and not pp.eliminated]
            for c in p.battlefield:
                if c.is_creature() and not c.tapped and c.turn_played < self.turn:
                    for t in targets:
                        moves.append(LegalMoveDTO(
                            action_type="attack", card_id=c.id,
                            card_name=c.name,
                            description=f"Attack {t.name} with {c.name}"))

        moves.append(LegalMoveDTO(
            action_type="pass", description="Pass priority"))

        return moves

    def to_dto(self) -> GameStateDTO:
        return GameStateDTO(
            session_id=self.session_id,
            turn=self.turn,
            phase=self.phase,
            active_seat=self.active_seat,
            priority_seat=self.active_seat,
            players=[
                p.to_dto(reveal_hand=p.is_human)
                for p in self.players
            ],
            log=self.log[-20:],
            game_over=self.game_over,
            winner_seat=self.winner_seat
        )


# ── Route Handlers ───────────────────────────────────────────────

@router.post("/new", response_model=GameStateDTO)
async def new_game(req: NewGameRequest):
    """Create a new interactive game session."""
    session_id = str(uuid.uuid4())[:8]
    session = GameSession(
        session_id=session_id,
        player_names=req.player_names,
        human_seat=req.human_seat
    )
    _sessions[session_id] = session
    log.info(f"New game session {session_id}")
    # Advance through initial phases to reach main1
    session.advance_phase()
    return session.to_dto()


@router.get("/state", response_model=GameStateDTO)
async def get_state(session_id: str = Query(...)):
    """Get the current game state snapshot."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    return session.to_dto()


@router.post("/action")
async def do_action(req: ActionRequest):
    """Execute a player action."""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, f"Session {req.session_id} not found")

    if session.game_over:
        return {"result": "Game is over", "state": session.to_dto()}

    result = ""
    if req.action_type == "play_card" and req.card_id is not None:
        result = session.play_card(req.card_id)
    elif req.action_type == "attack" and req.card_id is not None and req.target_seat is not None:
        result = session.attack(req.card_id, req.target_seat)
    elif req.action_type == "pass":
        result = "Passed priority"
    else:
        raise HTTPException(400, "Invalid action")

    return {"result": result, "state": session.to_dto()}


@router.post("/next-phase")
async def next_phase(session_id: str = Query(...)):
    """Advance to the next game phase."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    new_phase = session.advance_phase()
    return {"phase": new_phase, "state": session.to_dto()}


@router.post("/ai-turn")
async def ai_turn(session_id: str = Query(...)):
    """Let the current AI player execute their full turn."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")

    p = session._active_player()
    if p.is_human:
        return {"actions": ["It's your turn — use /action"], "state": session.to_dto()}

    actions = session.ai_turn()

    # Auto-advance through remaining phases to next player
    while session.active_seat == p.seat and not session.game_over:
        session.advance_phase()

    return {"actions": actions, "state": session.to_dto()}


@router.get("/legal-moves", response_model=list[LegalMoveDTO])
async def legal_moves(session_id: str = Query(...)):
    """Get legal moves for the active player."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    return session.get_legal_moves()
