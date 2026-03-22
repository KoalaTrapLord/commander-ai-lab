"""
Phase 5 Unit Tests — FastAPI Server & WebSocket Channel
=======================================================
Run with: pytest tests/test_phase5.py -v

Requires: pip install fastapi httpx pytest-asyncio
"""

from __future__ import annotations

import json
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_session_store():
    """Reset SessionStore singleton and api module _store before/after each test."""
    from commander_ai_lab.web.session_store import SessionStore
    SessionStore._instance = None
    # Also reset the module-level _store in the API router
    import commander_ai_lab.web.routers.api as api_mod
    api_mod._store = SessionStore()
    yield
    SessionStore._instance = None


@pytest.fixture
def app():
    """Create a fresh FastAPI app for each test."""
    from commander_ai_lab.web.app import create_app
    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_has_version(self, client):
        r = client.get("/health")
        assert "version" in r.json()


# ---------------------------------------------------------------------------
# Game lifecycle
# ---------------------------------------------------------------------------

class TestGameLifecycle:
    def _create(self, client, names=None):
        names = names or ["A", "B", "C", "D"]
        return client.post("/api/v1/games", json={
            "player_names": names,
            "human_seat": 0,
            "ai_personality": ["aggressive", "control", "combo"],
        })

    def test_create_game_201(self, client):
        r = self._create(client)
        assert r.status_code == 201
        assert "game_id" in r.json()

    def test_create_game_wrong_player_count(self, client):
        r = client.post("/api/v1/games", json={
            "player_names": ["A", "B"],
            "human_seat": 0,
            "ai_personality": [],
        })
        assert r.status_code == 400

    def test_list_games_empty(self, client):
        r = client.get("/api/v1/games")
        assert r.status_code == 200
        assert r.json()["games"] == []

    def test_list_games_after_create(self, client):
        self._create(client)
        r = client.get("/api/v1/games")
        assert len(r.json()["games"]) == 1

    def test_get_game_state(self, client):
        gid = self._create(client).json()["game_id"]
        r   = client.get(f"/api/v1/games/{gid}")
        assert r.status_code == 200
        data = r.json()
        assert data["game_id"] == gid
        assert len(data["players"]) == 4

    def test_get_game_404(self, client):
        r = client.get("/api/v1/games/doesnotexist")
        assert r.status_code == 404

    def test_get_legal_moves(self, client):
        gid = self._create(client).json()["game_id"]
        r   = client.get(f"/api/v1/games/{gid}/moves?seat=0")
        assert r.status_code == 200
        assert isinstance(r.json()["moves"], list)
        assert len(r.json()["moves"]) > 0

    def test_submit_move(self, client):
        gid = self._create(client).json()["game_id"]
        moves = client.get(f"/api/v1/games/{gid}/moves?seat=0").json()["moves"]
        move_id = moves[0]["id"]
        r = client.post(f"/api/v1/games/{gid}/move", json={"seat": 0, "move_id": move_id})
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    def test_submit_move_404(self, client):
        r = client.post("/api/v1/games/bad/move", json={"seat": 0, "move_id": 1})
        assert r.status_code == 404

    def test_concede(self, client):
        gid = self._create(client).json()["game_id"]
        r   = client.post(f"/api/v1/games/{gid}/concede", json={"seat": 1})
        assert r.status_code == 200
        assert r.json()["conceded"] is True

    def test_delete_game(self, client):
        gid = self._create(client).json()["game_id"]
        r   = client.delete(f"/api/v1/games/{gid}")
        assert r.status_code == 204
        r2  = client.get(f"/api/v1/games/{gid}")
        assert r2.status_code == 404

    def test_delete_game_404(self, client):
        r = client.delete("/api/v1/games/ghost")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# State snapshot shape
# ---------------------------------------------------------------------------

class TestStateSnapshot:
    def test_snapshot_fields(self, client):
        gid  = client.post("/api/v1/games", json={
            "player_names": ["P0","P1","P2","P3"],
            "human_seat": 0,
            "ai_personality": ["aggressive","control","combo"],
        }).json()["game_id"]
        snap = client.get(f"/api/v1/games/{gid}").json()
        for field in ["game_id","turn","current_phase","active_seat","game_over","winner","players"]:
            assert field in snap, f"Missing field: {field}"

    def test_snapshot_player_fields(self, client):
        gid  = client.post("/api/v1/games", json={
            "player_names": ["P0","P1","P2","P3"],
            "human_seat": 0,
            "ai_personality": ["aggressive","control","combo"],
        }).json()["game_id"]
        snap = client.get(f"/api/v1/games/{gid}").json()
        p    = snap["players"][0]
        for f in ["name","seat","life","eliminated","hand_count","battlefield","graveyard"]:
            assert f in p, f"Missing player field: {f}"

    def test_starting_life_total(self, client):
        gid  = client.post("/api/v1/games", json={
            "player_names": ["P0","P1","P2","P3"],
            "human_seat": 0,
            "ai_personality": ["aggressive","control","combo"],
        }).json()["game_id"]
        snap = client.get(f"/api/v1/games/{gid}").json()
        for p in snap["players"]:
            assert p["life"] == 40


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------

class TestConnectionManager:
    def test_connection_count_zero(self):
        from commander_ai_lab.web.connection_manager import ConnectionManager
        cm = ConnectionManager()
        assert cm.connection_count("abc") == 0

    def test_seats_connected_empty(self):
        from commander_ai_lab.web.connection_manager import ConnectionManager
        cm = ConnectionManager()
        assert cm.seats_connected("abc") == []


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------

class TestSessionStore:
    @pytest.fixture(autouse=True)
    def reset_store(self):
        from commander_ai_lab.web.session_store import SessionStore
        SessionStore._instance = None
        yield
        SessionStore._instance = None

    @pytest.mark.asyncio
    async def test_create_and_get(self):
        from commander_ai_lab.web.session_store import SessionStore
        store   = SessionStore()
        session = await store.create_session(["A","B","C","D"])
        assert store.get_session(session.game_id) is session

    @pytest.mark.asyncio
    async def test_list_ids(self):
        from commander_ai_lab.web.session_store import SessionStore
        store = SessionStore()
        s1    = await store.create_session(["A","B","C","D"])
        s2    = await store.create_session(["W","X","Y","Z"])
        ids   = store.list_session_ids()
        assert s1.game_id in ids
        assert s2.game_id in ids

    @pytest.mark.asyncio
    async def test_remove(self):
        from commander_ai_lab.web.session_store import SessionStore
        store   = SessionStore()
        session = await store.create_session(["A","B","C","D"])
        ok      = store.remove_session(session.game_id)
        assert ok is True
        assert store.get_session(session.game_id) is None

    @pytest.mark.asyncio
    async def test_state_snapshot_shape(self):
        from commander_ai_lab.web.session_store import SessionStore
        store   = SessionStore()
        session = await store.create_session(["A","B","C","D"])
        snap    = session.state_snapshot()
        assert snap["game_id"] == session.game_id
        assert len(snap["players"]) == 4

    @pytest.mark.asyncio
    async def test_concede_marks_eliminated(self):
        from commander_ai_lab.web.session_store import SessionStore
        store   = SessionStore()
        session = await store.create_session(["A","B","C","D"])
        await session.concede(seat=2)
        assert session._gs.players[2].eliminated is True
        assert session._gs.players[2].life == 0

    @pytest.mark.asyncio
    async def test_legal_moves_returned(self):
        from commander_ai_lab.web.session_store import SessionStore
        store   = SessionStore()
        session = await store.create_session(["A","B","C","D"])
        moves   = session.get_legal_moves(0)
        assert isinstance(moves, list)
        assert len(moves) > 0
