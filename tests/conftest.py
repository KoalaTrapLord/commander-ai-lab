"""
Commander AI Lab — Shared Test Fixtures (Phase 7)
==================================================
Provides pytest fixtures reused across all phase test modules.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Optional

import pytest

# Headless Pygame for GUI tests
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


# ---------------------------------------------------------------------------
# Stub domain objects (shared across all phases)
# ---------------------------------------------------------------------------

@dataclass
class StubCard:
    name: str
    type: str          = "creature"
    type_line: str     = ""
    pt: Optional[str]  = "2/2"
    cmc: int           = 3
    tapped: bool       = False
    is_commander: bool = False
    oracle: str        = ""
    oracle_text: str   = ""
    power: str         = ""
    toughness: str     = ""
    keywords: list     = field(default_factory=list)

    def get_power(self) -> int:
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

    def is_land(self) -> bool:
        return bool(self.type_line and "land" in self.type_line.lower())

    def is_creature(self) -> bool:
        return bool(self.type_line and "creature" in self.type_line.lower())

    def has_keyword(self, kw: str) -> bool:
        kw_lower = kw.lower()
        if self.keywords and any(k.lower() == kw_lower for k in self.keywords):
            return True
        return kw_lower in (self.oracle_text or "").lower()

    def to_dict(self) -> dict:
        return {
            "name":         self.name,
            "type":         self.type,
            "pt":           self.pt,
            "cmc":          self.cmc,
            "tapped":       self.tapped,
            "is_commander": self.is_commander,
            "oracle":       self.oracle,
        }


@dataclass
class StubPlayer:
    name: str
    seat: int = 0
    life: int                  = 40
    eliminated: bool           = False
    hand: list                 = field(default_factory=list)
    battlefield: list          = field(default_factory=list)
    graveyard: list            = field(default_factory=list)
    exile: list                = field(default_factory=list)
    command_zone: list         = field(default_factory=list)
    library: list              = field(default_factory=list)
    commander_damage: dict     = field(default_factory=dict)
    mana_pool: dict            = field(default_factory=dict)

    def to_dict(self, private: bool = False) -> dict:
        return {
            "name":        self.name,
            "seat":        self.seat,
            "life":        self.life,
            "eliminated":  self.eliminated,
            "hand_count":  len(self.hand),
            "hand":        [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.hand]
                           if private else [],
            "battlefield": [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.battlefield],
            "graveyard":   [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.graveyard],
            "exile":       [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.exile],
            "command_zone":[c.to_dict() if hasattr(c, 'to_dict') else c for c in self.command_zone],
        }


class _StubSimState:
    """Minimal SimState-compatible stub — delegates to player battlefields."""

    def __init__(self, players: list) -> None:
        self._players = players

    def get_battlefield(self, seat: int) -> list:
        if 0 <= seat < len(self._players):
            return self._players[seat].battlefield
        return []

    def add_to_battlefield(self, seat: int, card) -> None:
        if 0 <= seat < len(self._players):
            self._players[seat].battlefield.append(card)


class StubGameState:
    """
    Shared test stub that implements the CommanderGameState interface
    used by ThreatAssessor, TurnManager, and other subsystems.
    """

    def __init__(
        self,
        num_players: int = 4,
        names: Optional[list[str]] = None,
    ) -> None:
        names = names or [f"P{i}" for i in range(num_players)]
        self.players = [StubPlayer(name=n, seat=i) for i, n in enumerate(names)]
        self.turn               = 1
        self.current_phase      = "main1"
        self.active_player_seat = 0
        self.priority_seat      = 0
        self.stack: list        = []
        self.game_over          = False
        self.winner             = None
        self.commander_damage: dict[tuple, int] = {}

        # SimState-compatible sub-object for turn_manager._phase_untap() etc.
        self.sim_state = _StubSimState(self.players)

    # -- CommanderGameState interface methods --

    def battlefield(self, seat: int) -> list:
        """Return the battlefield for *seat* (delegates to sim_state)."""
        return self.sim_state.get_battlefield(seat)

    def stack_is_empty(self) -> bool:
        return len(self.stack) == 0

    def living_players(self) -> list:
        return [p for p in self.players if not p.eliminated]

    def get_legal_moves(self, seat: int) -> list[dict]:
        return [
            {"id": 1, "category": "pass_priority",  "description": "Pass priority"},
            {"id": 2, "category": "play_land",      "description": "Play a land"},
            {"id": 3, "category": "cast_spell",     "description": "Cast a spell"},
        ]

    def apply_move(self, seat: int, move_id: int) -> None:
        pass

    def advance_turn(self) -> None:
        self.active_player_seat = (self.active_player_seat + 1) % len(self.players)
        if self.active_player_seat == 0:
            self.turn += 1

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "current_phase": self.current_phase,
            "active_player_seat": self.active_player_seat,
            "players": [p.to_dict() for p in self.players],
        }


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def game_state():
    return StubGameState()


@pytest.fixture
def game_state_2p():
    return StubGameState(num_players=2, names=["Alice", "Bob"])


@pytest.fixture
def basic_creature():
    """A simple Card instance for clone and attribute tests."""
    from commander_ai_lab.sim.models import Card
    return Card(
        name="Grizzly Bears",
        type_line="Creature — Bear",
        cmc=2,
        pt="2/2",
        power="2",
        toughness="2",
    )


@pytest.fixture
def targeting_memory():
    from commander_ai_lab.sim.politics.memory import TargetingMemory
    return TargetingMemory(num_players=4)


@pytest.fixture
def comms_channel():
    from commander_ai_lab.sim.politics.comms import PoliticsCommsChannel
    return PoliticsCommsChannel()


@pytest.fixture
def politics_engine(targeting_memory, comms_channel):
    from commander_ai_lab.sim.politics.engine import PoliticsEngine
    return PoliticsEngine(
        num_players=4,
        memory=targeting_memory,
        comms=comms_channel,
        personalities={0: "timmy", 1: "spike", 2: "johnny", 3: "aggressive"},
        threat_fn=lambda s: {i: 0.3 for i in range(4) if i != s},
    )


@pytest.fixture
def threat_assessor():
    from commander_ai_lab.sim.threat_assessor import ThreatAssessor
    gs = StubGameState()
    return ThreatAssessor(game_state=gs, num_players=4)


@pytest.fixture
def fresh_app():
    """FastAPI test app with a clean session store."""
    from commander_ai_lab.web.session_store import SessionStore
    SessionStore._instance = None
    import commander_ai_lab.web.routers.api as api_mod
    api_mod._store = SessionStore()
    from commander_ai_lab.web.app import create_app
    app = create_app()
    yield app
    SessionStore._instance = None


@pytest.fixture
def http_client(fresh_app):
    from fastapi.testclient import TestClient
    return TestClient(fresh_app)


@pytest.fixture
def event_loop():
    """Provide a fresh event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
