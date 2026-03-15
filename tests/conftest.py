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
    pt: Optional[str]  = "2/2"
    cmc: int           = 3
    tapped: bool       = False
    is_commander: bool = False
    oracle: str        = ""

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
    seat: int
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


class StubGameState:
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
        self.stack              = []
        self.game_over          = False
        self.winner             = None
        self.commander_damage: dict[tuple, int] = {}

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
    from commander_ai_lab.web.app import create_app
    return create_app()


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
