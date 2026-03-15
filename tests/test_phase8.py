"""
Commander AI Lab — Phase 8 Unit Tests
======================================
Covers: LobbyManager, ChatChannel, SpectatorManager,
        LANBeacon, PrivateHandBus, Lobby REST API

Run with: pytest tests/test_phase8.py -v
"""

from __future__ import annotations

import asyncio
import json
import time
import pytest


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# LobbyManager
# ---------------------------------------------------------------------------

class TestLobbyManager:
    def _mgr(self):
        from commander_ai_lab.multiplayer.lobby import LobbyManager
        return LobbyManager()

    def test_create_room_returns_id(self):
        mgr = self._mgr()
        rid = run(mgr.create_room("Test Room", "Alice"))
        assert isinstance(rid, str) and len(rid) > 0

    def test_host_in_seat_0(self):
        mgr = self._mgr()
        rid = run(mgr.create_room("Test", "Alice"))
        room = mgr.get_room(rid)
        assert room.slots[0].player_name == "Alice"
        assert room.slots[0].is_host is True

    def test_ai_slot_filled(self):
        mgr = self._mgr()
        rid = run(mgr.create_room("Test", "Alice",
                                   ai_slots=[{"seat": 2, "personality": "spike"}]))
        room = mgr.get_room(rid)
        assert room.slots[2].is_ai is True
        assert room.slots[2].is_ready is True

    def test_join_room_assigns_seat(self):
        mgr = self._mgr()
        rid  = run(mgr.create_room("Test", "Alice"))
        seat = run(mgr.join_room(rid, "Bob"))
        assert seat in [1, 2, 3]

    def test_join_full_room_raises(self):
        mgr = self._mgr()
        rid = run(mgr.create_room("Full", "A",
                                   ai_slots=[{"seat":1,"personality":"spike"},
                                             {"seat":2,"personality":"timmy"},
                                             {"seat":3,"personality":"johnny"}]))
        with pytest.raises(ValueError, match="full"):
            run(mgr.join_room(rid, "Lateomer"))

    def test_wrong_password_raises(self):
        mgr = self._mgr()
        rid = run(mgr.create_room("Secret", "Alice", password="hunter2"))
        with pytest.raises(ValueError, match="password"):
            run(mgr.join_room(rid, "Eve", password="wrong"))

    def test_correct_password_joins(self):
        mgr = self._mgr()
        rid  = run(mgr.create_room("Secret", "Alice", password="hunter2"))
        seat = run(mgr.join_room(rid, "Bob", password="hunter2"))
        assert isinstance(seat, int)

    def test_set_ready_transitions_state(self):
        from commander_ai_lab.multiplayer.lobby import RoomState
        mgr = self._mgr()
        rid = run(mgr.create_room("R", "Alice",
                                   ai_slots=[{"seat":1,"personality":"spike"},
                                             {"seat":2,"personality":"timmy"},
                                             {"seat":3,"personality":"johnny"}]))
        state = run(mgr.set_ready(rid, seat=0))
        assert state == RoomState.READY

    def test_launch_requires_ready_state(self):
        mgr = self._mgr()
        rid = run(mgr.create_room("R", "Alice"))
        with pytest.raises(ValueError, match="ready"):
            run(mgr.launch_game(rid))

    def test_launch_fires_callback(self):
        from commander_ai_lab.multiplayer.lobby import RoomState
        fired = [False]
        async def cb(rid, room): fired[0] = True
        mgr = LobbyManager_with_cb(cb)
        rid = run(mgr.create_room("R", "Alice",
                                   ai_slots=[{"seat":1,"personality":"spike"},
                                             {"seat":2,"personality":"timmy"},
                                             {"seat":3,"personality":"johnny"}]))
        run(mgr.set_ready(rid, 0))
        run(mgr.launch_game(rid))
        assert fired[0] is True

    def test_list_open_rooms(self):
        mgr = self._mgr()
        run(mgr.create_room("Room1", "Alice"))
        run(mgr.create_room("Room2", "Bob"))
        rooms = mgr.list_open_rooms()
        assert len(rooms) == 2

    def test_spectator_limit(self):
        from commander_ai_lab.multiplayer.lobby import MAX_SPECTATORS
        mgr = self._mgr()
        rid = run(mgr.create_room("Spec", "Alice"))
        for i in range(MAX_SPECTATORS):
            run(mgr.add_spectator(rid, f"spec-{i}"))
        with pytest.raises(ValueError, match="limit"):
            run(mgr.add_spectator(rid, "one-too-many"))


def LobbyManager_with_cb(cb):
    from commander_ai_lab.multiplayer.lobby import LobbyManager
    return LobbyManager(on_launch=cb)


# ---------------------------------------------------------------------------
# ChatChannel
# ---------------------------------------------------------------------------

class TestChatChannel:
    def _ch(self):
        from commander_ai_lab.multiplayer.chat import ChatChannel
        return ChatChannel(room_id="test")

    def test_send_stores_message(self):
        ch = self._ch()
        run(ch.send("Alice", "Hello!", seat=0))
        assert len(ch.history()) == 1

    def test_message_truncated(self):
        from commander_ai_lab.multiplayer.chat import MAX_MSG_LENGTH
        ch  = self._ch()
        msg = run(ch.send("Bob", "x" * (MAX_MSG_LENGTH + 100)))
        assert len(msg.text) == MAX_MSG_LENGTH

    def test_history_capped(self):
        from commander_ai_lab.multiplayer.chat import MAX_HISTORY
        ch = self._ch()
        for i in range(MAX_HISTORY + 50):
            run(ch.send("A", str(i)))
        assert len(ch._history) == MAX_HISTORY

    def test_system_message_role(self):
        from commander_ai_lab.multiplayer.chat import ChatRole
        ch = self._ch()
        run(ch.system("Game started"))
        h = ch.history(role_filter=ChatRole.SYSTEM)
        assert len(h) == 1
        assert h[0]["role"] == "SYSTEM"

    def test_ai_message_role(self):
        from commander_ai_lab.multiplayer.chat import ChatRole
        ch = self._ch()
        run(ch.ai_says("Timmy", 1, "I'll block!"))
        h = ch.history(role_filter=ChatRole.AI)
        assert h[0]["sender"] == "Timmy"

    def test_handler_receives_message(self):
        ch = self._ch()
        received = []
        async def handler(payload): received.append(payload)
        ch.register(seat=0, send_fn=handler)
        run(ch.send("A", "Test", seat=0))
        assert len(received) == 1
        assert received[0]["text"] == "Test"

    def test_unregistered_handler_not_called(self):
        ch = self._ch()
        received = []
        async def handler(payload): received.append(payload)
        ch.register(seat=0, send_fn=handler)
        ch.unregister(0)
        run(ch.send("A", "Test"))
        assert len(received) == 0


# ---------------------------------------------------------------------------
# SpectatorManager
# ---------------------------------------------------------------------------

class TestSpectatorManager:
    def test_add_and_count(self):
        from commander_ai_lab.multiplayer.spectator import SpectatorManager
        mgr = SpectatorManager()
        async def noop(s): pass
        mgr.add("room1", "conn1", noop)
        assert mgr.count("room1") == 1

    def test_remove(self):
        from commander_ai_lab.multiplayer.spectator import SpectatorManager
        mgr = SpectatorManager()
        async def noop(s): pass
        mgr.add("room1", "conn1", noop)
        mgr.remove("room1", "conn1")
        assert mgr.count("room1") == 0

    def test_broadcast_strips_hands(self):
        from commander_ai_lab.multiplayer.spectator import SpectatorManager
        mgr = SpectatorManager()
        received = []
        async def capture(s): received.append(s)
        mgr.add("room1", "c1", capture)
        snapshot = {
            "players": [{"seat": 0, "life": 40, "hand": [{"name": "Sol Ring"}]}]
        }
        run(mgr.broadcast("room1", snapshot))
        payload = json.loads(received[0])
        assert "hand" not in payload["data"]["players"][0]

    def test_dead_connection_pruned(self):
        from commander_ai_lab.multiplayer.spectator import SpectatorManager
        mgr = SpectatorManager()
        async def fail(s): raise ConnectionError("dead")
        mgr.add("room1", "dead_conn", fail)
        run(mgr.broadcast("room1", {"players": []}))
        assert mgr.count("room1") == 0

    def test_multiple_spectators_all_receive(self):
        from commander_ai_lab.multiplayer.spectator import SpectatorManager
        mgr = SpectatorManager()
        buckets = [[], [], []]
        for i in range(3):
            idx = i
            async def cap(s, i=idx): buckets[i].append(s)
            mgr.add("room1", f"c{i}", cap)
        run(mgr.broadcast("room1", {"players": []}))
        assert all(len(b) == 1 for b in buckets)


# ---------------------------------------------------------------------------
# LANBeacon
# ---------------------------------------------------------------------------

class TestLANBeacon:
    def test_not_stale_immediately(self):
        from commander_ai_lab.multiplayer.lan import LANBeacon
        b = LANBeacon("192.168.1.1", 8000, "rid", "Room", 2, 4, False)
        assert b.is_stale() is False

    def test_stale_after_ttl(self):
        from commander_ai_lab.multiplayer.lan import LANBeacon, BEACON_TTL
        b = LANBeacon("192.168.1.1", 8000, "rid", "Room", 2, 4, False,
                      last_seen=time.time() - BEACON_TTL - 1)
        assert b.is_stale() is True

    def test_to_dict_fields(self):
        from commander_ai_lab.multiplayer.lan import LANBeacon
        b = LANBeacon("10.0.0.1", 8000, "abc", "My Room", 3, 4, True)
        d = b.to_dict()
        assert d["room_name"] == "My Room"
        assert d["has_password"] is True

    def test_discovery_build_beacon(self):
        from commander_ai_lab.multiplayer.lan import LANDiscovery
        ld = LANDiscovery(mode="host", room_info={
            "room_id": "abc", "room_name": "Test",
            "player_count": 2, "max_players": 4, "has_password": False,
        })
        payload = ld._build_beacon_payload()
        assert payload["room_name"] == "Test"
        assert payload["app"] == "commander-ai-lab"

    def test_handle_beacon_stores(self):
        from commander_ai_lab.multiplayer.lan import LANDiscovery, APP_ID
        ld = LANDiscovery(mode="client")
        raw = json.dumps({
            "app": APP_ID, "version": "0.8.0",
            "room_id": "xyz", "room_name": "LAN Game",
            "player_count": 1, "max_players": 4,
            "has_password": False, "host_port": 8000,
        }).encode()
        ld._handle_beacon(raw, "192.168.0.5")
        assert "192.168.0.5" in ld._discovered

    def test_unknown_app_ignored(self):
        from commander_ai_lab.multiplayer.lan import LANDiscovery
        ld = LANDiscovery(mode="client")
        raw = json.dumps({"app": "some-other-app", "room_id": "x"}).encode()
        ld._handle_beacon(raw, "10.0.0.1")
        assert len(ld._discovered) == 0

    def test_invalid_json_ignored(self):
        from commander_ai_lab.multiplayer.lan import LANDiscovery
        ld = LANDiscovery(mode="client")
        ld._handle_beacon(b"not json{{{", "10.0.0.2")
        assert len(ld._discovered) == 0


# ---------------------------------------------------------------------------
# PrivateHandBus
# ---------------------------------------------------------------------------

class TestPrivateHandBus:
    def test_dispatch_sends_hand_to_human(self):
        from commander_ai_lab.multiplayer.hands import PrivateHandBus
        bus = PrivateHandBus()
        received = []
        async def send(s): received.append(json.loads(s))
        bus.register(seat=0, send_fn=send, is_human=True)
        snapshot = {
            "players": [
                {"seat": 0, "life": 40, "hand": [{"name": "Sol Ring"}]},
                {"seat": 1, "life": 40, "hand": [{"name": "Command Tower"}]},
            ]
        }
        public = run(bus.dispatch(snapshot, current_turn=3))
        assert len(received) == 1
        assert received[0]["type"] == "hand"
        assert received[0]["seat"] == 0
        assert received[0]["cards"][0]["name"] == "Sol Ring"

    def test_public_snapshot_has_no_hands(self):
        from commander_ai_lab.multiplayer.hands import PrivateHandBus
        bus = PrivateHandBus()
        async def noop(s): pass
        bus.register(seat=0, send_fn=noop)
        snapshot = {"players": [{"seat": 0, "hand": [{"name": "Mox"}]}]}
        public = run(bus.dispatch(snapshot, current_turn=1))
        assert "hand" not in public["players"][0]

    def test_ai_seat_not_called(self):
        from commander_ai_lab.multiplayer.hands import PrivateHandBus
        bus = PrivateHandBus()
        received = []
        async def send(s): received.append(s)
        bus.register(seat=1, send_fn=send, is_human=False)
        snapshot = {"players": [{"seat": 1, "hand": [{"name": "Island"}]}]}
        run(bus.dispatch(snapshot, current_turn=2))
        assert len(received) == 0

    def test_registered_seats_sorted(self):
        from commander_ai_lab.multiplayer.hands import PrivateHandBus
        bus = PrivateHandBus()
        async def noop(s): pass
        bus.register(3, noop)
        bus.register(1, noop)
        bus.register(0, noop)
        assert bus.registered_seats() == [0, 1, 3]

    def test_unregister_removes_seat(self):
        from commander_ai_lab.multiplayer.hands import PrivateHandBus
        bus = PrivateHandBus()
        async def noop(s): pass
        bus.register(0, noop)
        bus.unregister(0)
        assert 0 not in bus.registered_seats()


# ---------------------------------------------------------------------------
# Lobby REST API
# ---------------------------------------------------------------------------

class TestLobbyAPI:
    @pytest.fixture
    def client(self):
        from commander_ai_lab.web.routers.lobby import router, ws_router, _lobby
        import commander_ai_lab.web.routers.lobby as lobby_mod
        lobby_mod._lobby     = None
        lobby_mod._spectators = None
        lobby_mod._chats     = {}
        lobby_mod._ws_rooms  = {}
        from commander_ai_lab.web.app import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        return TestClient(app)

    def test_create_room(self, client):
        r = client.post("/api/v1/lobby/rooms", json={
            "room_name": "Friday", "host_name": "Alice"
        })
        assert r.status_code == 201
        assert "room_id" in r.json()

    def test_list_rooms(self, client):
        client.post("/api/v1/lobby/rooms", json={"room_name": "A", "host_name": "X"})
        client.post("/api/v1/lobby/rooms", json={"room_name": "B", "host_name": "Y"})
        r = client.get("/api/v1/lobby/rooms")
        assert len(r.json()["rooms"]) == 2

    def test_get_room_not_found(self, client):
        r = client.get("/api/v1/lobby/rooms/doesnotexist")
        assert r.status_code == 404

    def test_join_room(self, client):
        rid = client.post("/api/v1/lobby/rooms",
                          json={"room_name": "J", "host_name": "A"}).json()["room_id"]
        r   = client.post(f"/api/v1/lobby/rooms/{rid}/join",
                          json={"player_name": "Bob"})
        assert "seat" in r.json()

    def test_ready_and_launch(self, client):
        r = client.post("/api/v1/lobby/rooms", json={
            "room_name": "Launch", "host_name": "H",
            "ai_slots": [{"seat":1,"personality":"spike"},
                         {"seat":2,"personality":"timmy"},
                         {"seat":3,"personality":"johnny"}],
        })
        rid = r.json()["room_id"]
        client.post(f"/api/v1/lobby/rooms/{rid}/ready", json={"seat": 0})
        launch_r = client.post(f"/api/v1/lobby/rooms/{rid}/launch")
        assert launch_r.json()["state"] == "IN_PROGRESS"

    def test_launch_without_ready_fails(self, client):
        rid = client.post("/api/v1/lobby/rooms",
                          json={"room_name": "X", "host_name": "Y"}).json()["room_id"]
        r = client.post(f"/api/v1/lobby/rooms/{rid}/launch")
        assert r.status_code == 400
