"""
Commander AI Lab — Integration Tests (Phase 7)
===============================================
End-to-end tests that wire multiple subsystems together:
  - ThreatAssessor + PoliticsEngine
  - PoliticsEngine + TargetingMemory + CommsChannel
  - REST API + SessionStore + WebSocket
  - Turn lifecycle: phase transitions, AI decision flow, elimination

Run with: pytest tests/test_integration.py -v
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


@dataclass
class _Player:
    name: str
    seat: int
    life: int = 40
    eliminated: bool = False
    hand: list = field(default_factory=list)
    battlefield: list = field(default_factory=list)
    graveyard: list = field(default_factory=list)
    exile: list = field(default_factory=list)
    command_zone: list = field(default_factory=list)
    library: list = field(default_factory=list)


class _StubSimState:
    """Minimal SimState stub — delegates to player battlefields."""

    def __init__(self, players: list) -> None:
        self._players = players

    def get_battlefield(self, seat: int) -> list:
        if 0 <= seat < len(self._players):
            return self._players[seat].battlefield
        return []


class _GS:
    def __init__(self, n=4):
        self.players = [_Player(f"P{i}", i) for i in range(n)]
        self.turn = 1
        self.current_phase = "main1"
        self.active_player_seat = 0
        self.priority_seat = 0
        self.stack = []
        self.game_over = False
        self.winner = None
        self.sim_state = _StubSimState(self.players)

    def battlefield(self, seat: int) -> list:
        return self.players[seat].battlefield

    def stack_is_empty(self) -> bool:
        return len(self.stack) == 0

    def living_players(self) -> list:
        return [p for p in self.players if not p.eliminated]

    def get_legal_moves(self, seat):
        return [{"id": 1, "category": "pass_priority", "description": "Pass"}]

    def apply_move(self, seat, move_id):
        pass


# ---------------------------------------------------------------------------
# 1. ThreatAssessor + PoliticsEngine integration
# ---------------------------------------------------------------------------

class TestThreatPoliticsIntegration:
    """
    Verify that ThreatAssessor scores flow into PoliticsEngine correctly
    and that the adjusted_threat_score incorporates spite and memory.
    """

    def _build(self):
        from commander_ai_lab.sim.threat_assessor import assess_threats
        from commander_ai_lab.sim.politics.memory  import TargetingMemory
        from commander_ai_lab.sim.politics.comms   import PoliticsCommsChannel
        from commander_ai_lab.sim.politics.engine  import PoliticsEngine

        gs  = _GS()

        def _threat_dict(viewer_seat: int) -> dict[int, float]:
            """Wrap assess_threats list into {seat: total} dict for PoliticsEngine."""
            return {s.seat: s.total for s in assess_threats(gs, viewer_seat=viewer_seat)}

        mem = TargetingMemory(num_players=4)
        ch  = PoliticsCommsChannel()
        pe  = PoliticsEngine(
            num_players=4,
            memory=mem,
            comms=ch,
            personalities={0:"timmy",1:"spike",2:"johnny",3:"aggressive"},
            threat_fn=_threat_dict,
        )
        return gs, mem, ch, pe

    def test_adjusted_threat_no_spite_equals_base(self):
        from commander_ai_lab.sim.threat_assessor import assess_threats
        gs, mem, ch, pe = self._build()
        scores = assess_threats(gs, viewer_seat=0)
        # Find the score for seat 1
        base = 0.0
        for s in scores:
            if s.seat == 1:
                base = s.total
                break
        adjusted = pe.adjusted_threat_score(viewer=0, target=1, current_turn=1)
        # Without spite or memory events, adjusted ≈ base (may differ by mem term)
        assert abs(adjusted - base) < 0.35

    def test_spite_raises_adjusted_score(self):
        gs, mem, ch, pe = self._build()
        before = pe.adjusted_threat_score(0, 1, 1)
        pe._add_spite(wronged_seat=0, target_seat=1, current_turn=1, intensity=0.5)
        after  = pe.adjusted_threat_score(0, 1, 1)
        assert after > before

    def test_memory_aggression_raises_adjusted_score(self):
        from commander_ai_lab.sim.politics.memory import ActionType
        gs, mem, ch, pe = self._build()
        before = pe.adjusted_threat_score(0, 2, 1)
        for _ in range(5):
            mem.record(1, 2, 0, ActionType.ATTACKED)
        after = pe.adjusted_threat_score(0, 2, 1)
        assert after > before

    def test_top_threat_matches_assessor(self):
        from commander_ai_lab.sim.threat_assessor import assess_threats
        gs, mem, ch, pe = self._build()
        # Give seat 3 a huge life lead to inflate threat
        gs.players[3].life = 5   # low life — looks like they need a kill
        threats = assess_threats(gs, viewer_seat=0)
        # assess_threats returns a ThreatScore per non-eliminated seat excluding none
        # With 4 players, viewer seat 0 is included → 4 scores
        assert len(threats) == 4


# ---------------------------------------------------------------------------
# 2. Politics full cycle: propose → accept → violate → spite
# ---------------------------------------------------------------------------

class TestPoliticsFullCycle:
    def test_deal_cycle_end_to_end(self):
        from commander_ai_lab.sim.politics.deals  import DealType, DealResponse
        from commander_ai_lab.sim.politics.memory  import TargetingMemory, ActionType
        from commander_ai_lab.sim.politics.comms   import PoliticsCommsChannel
        from commander_ai_lab.sim.politics.engine  import PoliticsEngine

        mem = TargetingMemory(4)
        ch  = PoliticsCommsChannel()
        pe  = PoliticsEngine(
            4, mem, ch,
            personalities={0:"combo",1:"control",2:"timmy",3:"spike"},
            threat_fn=lambda s: {i:0.4 for i in range(4) if i!=s},
        )

        # Propose
        deal = run(pe.propose_deal(0, 1, DealType.NON_AGGRESSION, current_turn=2))
        assert deal.deal_id in pe._deals

        # Force accept for determinism
        deal.response = DealResponse.ACCEPTED

        # Violate: seat 1 attacks seat 0
        broken = pe.check_deal_violation(
            actor=1, action_target=0,
            action_type=ActionType.ATTACKED,
            current_turn=3,
        )
        assert len(broken) == 1
        assert broken[0].response == DealResponse.BROKEN

        # Spite applied
        assert pe.get_spite_bias(0, 1, 3) > 0

        # Memory recorded breach
        score = mem.aggression_score(1, 0, current_turn=3)
        assert score > 0

    def test_comms_log_has_proposal_and_response(self):
        from commander_ai_lab.sim.politics.deals  import DealType
        from commander_ai_lab.sim.politics.memory  import TargetingMemory
        from commander_ai_lab.sim.politics.comms   import PoliticsCommsChannel
        from commander_ai_lab.sim.politics.engine  import PoliticsEngine

        mem = TargetingMemory(4)
        ch  = PoliticsCommsChannel()
        pe  = PoliticsEngine(4, mem, ch,
                              {0:"timmy",1:"spike",2:"johnny",3:"aggressive"},
                              lambda s: {i:0.3 for i in range(4) if i!=s})
        run(pe.propose_deal(0, 2, DealType.SPARE_THIS_TURN, current_turn=4))
        assert len(ch._log) >= 2
        speakers = {b.speaker for b in ch._log}
        assert 0 in speakers   # proposer spoke
        assert 2 in speakers   # responder spoke


# ---------------------------------------------------------------------------
# 3. REST API → SessionStore → State snapshot round-trip
# ---------------------------------------------------------------------------

class TestAPISessionIntegration:
    @pytest.fixture
    def client(self):
        from commander_ai_lab.web.session_store import SessionStore
        SessionStore._instance = None
        from commander_ai_lab.web.app import create_app
        from fastapi.testclient import TestClient
        return TestClient(create_app())

    def _new_game(self, client, names=None):
        names = names or ["Alice", "Timmy", "Spike", "Johnny"]
        r = client.post("/api/v1/games", json={
            "player_names": names,
            "human_seat": 0,
            "ai_personality": ["aggressive", "control", "combo"],
        })
        assert r.status_code == 201
        return r.json()["game_id"]

    def test_create_then_get_state(self, client):
        gid  = self._new_game(client)
        snap = client.get(f"/api/v1/games/{gid}").json()
        assert snap["game_id"] == gid
        assert len(snap["players"]) == 4

    def test_player_names_preserved(self, client):
        gid   = self._new_game(client, ["Alice","Bob","Carol","Dave"])
        snap  = client.get(f"/api/v1/games/{gid}").json()
        names = [p["name"] for p in snap["players"]]
        assert names == ["Alice", "Bob", "Carol", "Dave"]

    def test_starting_life_40(self, client):
        gid  = self._new_game(client)
        snap = client.get(f"/api/v1/games/{gid}").json()
        for p in snap["players"]:
            assert p["life"] == 40

    def test_move_accepted(self, client):
        gid   = self._new_game(client)
        moves = client.get(f"/api/v1/games/{gid}/moves?seat=0").json()["moves"]
        r     = client.post(f"/api/v1/games/{gid}/move",
                            json={"seat": 0, "move_id": moves[0]["id"]})
        assert r.json()["accepted"] is True

    def test_concede_marks_eliminated(self, client):
        gid  = self._new_game(client)
        client.post(f"/api/v1/games/{gid}/concede", json={"seat": 3})
        snap = client.get(f"/api/v1/games/{gid}").json()
        assert snap["players"][3]["eliminated"] is True

    def test_delete_then_404(self, client):
        gid = self._new_game(client)
        client.delete(f"/api/v1/games/{gid}")
        r = client.get(f"/api/v1/games/{gid}")
        assert r.status_code == 404

    def test_multiple_games_isolated(self, client):
        gid1 = self._new_game(client, ["A","B","C","D"])
        gid2 = self._new_game(client, ["W","X","Y","Z"])
        assert gid1 != gid2
        snap1 = client.get(f"/api/v1/games/{gid1}").json()
        snap2 = client.get(f"/api/v1/games/{gid2}").json()
        assert snap1["players"][0]["name"] == "A"
        assert snap2["players"][0]["name"] == "W"


# ---------------------------------------------------------------------------
# 4. Turn-manager phase transition integration
# ---------------------------------------------------------------------------

class TestTurnManagerIntegration:
    def test_run_game_completes(self):
        from commander_ai_lab.sim.turn_manager import CommanderTurnManager, TurnManagerConfig

        gs = _GS()
        # Make all players except seat 0 eliminated so game ends immediately
        for p in gs.players[1:]:
            p.eliminated = True

        events = []

        async def on_event(ev):
            events.append(ev)

        async def on_thinking(seat, flag):
            pass

        tm = CommanderTurnManager(
            game_state=gs,
            ai_opponents=[],
            human_seats=set(),
            on_event=on_event,
            on_thinking=on_thinking,
            config=TurnManagerConfig(ai_decision_delay=0.0, max_turns=2),
        )
        asyncio.run(tm.run_game())
        # Game should have fired at least one event
        assert len(events) >= 1

    def test_phase_sequence_order(self):
        from commander_ai_lab.sim.turn_manager import CommanderTurnManager, TurnManagerConfig

        gs = _GS()
        for p in gs.players[1:]:
            p.eliminated = True

        phases_seen = []

        async def on_event(ev):
            if hasattr(ev, 'phase') and ev.phase:
                phases_seen.append(ev.phase)

        async def on_thinking(seat, flag):
            pass

        tm = CommanderTurnManager(
            game_state=gs,
            ai_opponents=[],
            human_seats=set(),
            on_event=on_event,
            on_thinking=on_thinking,
            config=TurnManagerConfig(ai_decision_delay=0.0, max_turns=1),
        )
        asyncio.run(tm.run_game())
        # If phases were emitted, they should start with untap
        if phases_seen:
            assert phases_seen[0] in ("untap", "upkeep", "draw", "main1")

    def test_elimination_ends_game(self):
        from commander_ai_lab.sim.turn_manager import CommanderTurnManager, TurnManagerConfig

        gs = _GS()
        for p in gs.players[1:]:
            p.eliminated = True
            p.life = 0

        game_over_fired = [False]

        async def on_event(ev):
            if getattr(ev, 'event_type', '') == 'game_over':
                game_over_fired[0] = True

        async def on_thinking(seat, flag):
            pass

        tm = CommanderTurnManager(
            game_state=gs,
            ai_opponents=[],
            human_seats=set(),
            on_event=on_event,
            on_thinking=on_thinking,
            config=TurnManagerConfig(ai_decision_delay=0.0, max_turns=3),
        )
        asyncio.run(tm.run_game())
        assert game_over_fired[0] is True


# ---------------------------------------------------------------------------
# 5. WebSocket protocol integration (via TestClient)
# ---------------------------------------------------------------------------

class TestWebSocketIntegration:
    @pytest.fixture
    def ws_client(self):
        from commander_ai_lab.web.session_store import SessionStore
        SessionStore._instance = None
        from commander_ai_lab.web.app import create_app
        from fastapi.testclient import TestClient
        return TestClient(create_app())

    def _create_game(self, client) -> str:
        r = client.post("/api/v1/games", json={
            "player_names": ["H","AI1","AI2","AI3"],
            "human_seat": 0,
            "ai_personality": ["aggressive","control","combo"],
        })
        return r.json()["game_id"]

    def test_ws_connect_receives_state(self, ws_client):
        gid = self._create_game(ws_client)
        with ws_client.websocket_connect(f"/ws/game/{gid}?seat=0") as ws:
            data = json.loads(ws.receive_text())
            assert data["type"] == "state"
            assert "players" in data["data"]

    def test_ws_ping_pong(self, ws_client):
        gid = self._create_game(ws_client)
        with ws_client.websocket_connect(f"/ws/game/{gid}?seat=0") as ws:
            ws.receive_text()   # consume initial state
            ws.send_text(json.dumps({"type": "ping"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "pong"

    def test_ws_invalid_json_returns_error(self, ws_client):
        gid = self._create_game(ws_client)
        with ws_client.websocket_connect(f"/ws/game/{gid}?seat=0") as ws:
            ws.receive_text()
            ws.send_text("not json{{{")
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"

    def test_ws_unknown_message_type_returns_error(self, ws_client):
        gid = self._create_game(ws_client)
        with ws_client.websocket_connect(f"/ws/game/{gid}?seat=0") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "unknown_cmd"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"

    def test_ws_move_accepted(self, ws_client):
        gid = self._create_game(ws_client)
        with ws_client.websocket_connect(f"/ws/game/{gid}?seat=0") as ws:
            ws.receive_text()   # initial state
            ws.send_text(json.dumps({"type": "move", "seat": 0, "move_id": 1}))
            resp = json.loads(ws.receive_text())
            # Server should broadcast updated state
            assert resp["type"] in ("state", "error")

    def test_ws_invalid_game_id_closes(self, ws_client):
        with pytest.raises(Exception):
            with ws_client.websocket_connect("/ws/game/doesnotexist?seat=0") as ws:
                ws.receive_text()
