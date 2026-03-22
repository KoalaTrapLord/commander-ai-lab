"""
Regression tests for centralized damage routing (Issue #86).

Covers:
  - _apply_damage() source-aware routing
  - Commander damage accumulation via combat
  - Commander damage elimination at 21+
  - Regular (non-commander) combat damage does NOT track commander damage
  - Trample overflow from commanders tracks correctly
  - Double strike commander damage doubled correctly
  - Lifelink healing alongside commander damage tracking
  - Multi-attacker mixed commander + non-commander combat
  - Full game with commander damage kill
"""

import pytest
from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState
from commander_ai_lab.sim.engine import GameEngine


# ── Helpers ──────────────────────────────────────────────────

def _make_creature(
    name: str = "Bear",
    power: int = 2,
    toughness: int = 2,
    keywords: list[str] | None = None,
    is_commander: bool = False,
    card_id: int = 1,
    owner_id: int = 0,
    turn_played: int = -1,
) -> Card:
    """Create a creature card for testing."""
    c = Card(
        name=name,
        type_line="Creature",
        pt=f"{power}/{toughness}",
        power=str(power),
        toughness=str(toughness),
        keywords=keywords or [],
        is_commander=is_commander,
        id=card_id,
        owner_id=owner_id,
        turn_played=turn_played,
    )
    return c


def _two_player_sim(
    p0_life: int = 40,
    p1_life: int = 40,
    p0_battlefield: list[Card] | None = None,
    p1_battlefield: list[Card] | None = None,
) -> SimState:
    """Create a minimal 2-player SimState for damage tests."""
    sim = SimState()
    sim.init_battlefields(2)
    sim.players.append(Player(name="Attacker", life=p0_life, owner_id=0, stats=PlayerStats()))
    sim.players.append(Player(name="Defender", life=p1_life, owner_id=1, stats=PlayerStats()))
    for c in (p0_battlefield or []):
        sim.add_to_battlefield(0, c)
    for c in (p1_battlefield or []):
        sim.add_to_battlefield(1, c)
    return sim


# ── _apply_damage unit tests ─────────────────────────────────

class TestApplyDamage:
    """Direct tests of the _apply_damage static method."""

    def test_regular_creature_damage_reduces_life(self):
        sim = _two_player_sim()
        bear = _make_creature("Bear", power=2, toughness=2, is_commander=False)
        target = sim.players[1]
        GameEngine._apply_damage(sim, bear, 0, target, 5)
        assert target.life == 35
        assert target.stats.damage_received == 5

    def test_regular_creature_no_commander_damage_tracked(self):
        sim = _two_player_sim()
        bear = _make_creature("Bear", is_commander=False)
        target = sim.players[1]
        GameEngine._apply_damage(sim, bear, 0, target, 10)
        assert target.commander_damage_received == {}

    def test_commander_damage_tracked(self):
        sim = _two_player_sim()
        commander = _make_creature("Atraxa", power=4, toughness=4, is_commander=True)
        target = sim.players[1]
        GameEngine._apply_damage(sim, commander, 0, target, 4)
        assert target.commander_damage_received == {0: 4}
        assert target.life == 36

    def test_commander_damage_accumulates(self):
        sim = _two_player_sim()
        commander = _make_creature("Atraxa", power=4, toughness=4, is_commander=True)
        target = sim.players[1]
        GameEngine._apply_damage(sim, commander, 0, target, 10)
        GameEngine._apply_damage(sim, commander, 0, target, 10)
        assert target.commander_damage_received == {0: 20}
        assert target.life == 20
        assert not target.eliminated  # 20 < 21

    def test_commander_damage_21_eliminates(self):
        sim = _two_player_sim()
        commander = _make_creature("Atraxa", power=4, toughness=4, is_commander=True)
        target = sim.players[1]
        GameEngine._apply_damage(sim, commander, 0, target, 21)
        assert target.eliminated
        assert target.commander_damage_received == {0: 21}
        assert target.life == 19  # still above 0 but eliminated by cmdr damage

    def test_commander_damage_over_21_eliminates(self):
        sim = _two_player_sim()
        commander = _make_creature("Atraxa", power=7, toughness=7, is_commander=True)
        target = sim.players[1]
        GameEngine._apply_damage(sim, commander, 0, target, 10)
        GameEngine._apply_damage(sim, commander, 0, target, 12)
        assert target.eliminated
        assert target.commander_damage_received == {0: 22}

    def test_life_lethal_eliminates(self):
        sim = _two_player_sim(p1_life=5)
        bear = _make_creature("Bear", is_commander=False)
        target = sim.players[1]
        GameEngine._apply_damage(sim, bear, 0, target, 5)
        assert target.eliminated
        assert target.life == 0

    def test_zero_damage_is_noop(self):
        sim = _two_player_sim()
        bear = _make_creature("Bear", is_commander=False)
        target = sim.players[1]
        GameEngine._apply_damage(sim, bear, 0, target, 0)
        assert target.life == 40
        assert target.stats.damage_received == 0

    def test_negative_damage_is_noop(self):
        sim = _two_player_sim()
        bear = _make_creature("Bear", is_commander=False)
        target = sim.players[1]
        GameEngine._apply_damage(sim, bear, 0, target, -3)
        assert target.life == 40

    def test_none_source_card_no_commander_tracking(self):
        """Damage with no source card should not track commander damage."""
        sim = _two_player_sim()
        target = sim.players[1]
        GameEngine._apply_damage(sim, None, 0, target, 5)
        assert target.life == 35
        assert target.commander_damage_received == {}

    def test_multiple_commanders_tracked_separately(self):
        """Commander damage from different seats tracked independently."""
        sim = SimState()
        sim.init_battlefields(3)
        for i in range(3):
            sim.players.append(Player(name=f"P{i}", life=40, owner_id=i, stats=PlayerStats()))
        target = sim.players[2]
        cmd_a = _make_creature("Atraxa", is_commander=True)
        cmd_b = _make_creature("Korvold", is_commander=True)
        GameEngine._apply_damage(sim, cmd_a, 0, target, 15)
        GameEngine._apply_damage(sim, cmd_b, 1, target, 10)
        assert target.commander_damage_received == {0: 15, 1: 10}
        assert target.life == 15
        assert not target.eliminated  # neither source at 21

    def test_one_of_multiple_commanders_reaches_21(self):
        """Elimination triggers when one opponent's commander damage hits 21."""
        sim = SimState()
        sim.init_battlefields(3)
        for i in range(3):
            sim.players.append(Player(name=f"P{i}", life=40, owner_id=i, stats=PlayerStats()))
        target = sim.players[2]
        cmd_a = _make_creature("Atraxa", is_commander=True)
        cmd_b = _make_creature("Korvold", is_commander=True)
        GameEngine._apply_damage(sim, cmd_a, 0, target, 21)
        assert target.eliminated
        # Second commander's damage is still at 0
        assert target.commander_damage_received.get(1, 0) == 0


# ── Combat integration tests ────────────────────────────────

class TestCombatCommanderDamage:
    """Integration tests: commander damage tracking through _resolve_combat."""

    def _run_combat(
        self,
        attackers: list[Card],
        blockers: list[Card] | None = None,
        p0_life: int = 40,
        p1_life: int = 40,
    ) -> tuple[SimState, GameEngine]:
        """Set up and run a single combat step."""
        sim = _two_player_sim(
            p0_life=p0_life,
            p1_life=p1_life,
            p0_battlefield=attackers,
            p1_battlefield=blockers or [],
        )
        sim.turn = 1  # attackers need turn_played < sim.turn
        engine = GameEngine()
        engine._resolve_combat(sim, pi=0, turn=1)
        return sim, engine

    def test_unblocked_commander_tracks_damage(self):
        cmd = _make_creature("Atraxa", power=4, toughness=4, is_commander=True, card_id=1, turn_played=0)
        sim, _ = self._run_combat([cmd])
        defender = sim.players[1]
        assert defender.life == 36
        assert defender.commander_damage_received == {0: 4}

    def test_unblocked_regular_creature_no_commander_damage(self):
        bear = _make_creature("Bear", power=3, toughness=3, is_commander=False, card_id=1, turn_played=0)
        sim, _ = self._run_combat([bear])
        defender = sim.players[1]
        assert defender.life == 37
        assert defender.commander_damage_received == {}

    def test_mixed_attackers_only_commander_tracked(self):
        """When commander + regular creature attack, only commander damage is tracked."""
        cmd = _make_creature("Atraxa", power=4, toughness=4, is_commander=True, card_id=1, turn_played=0)
        bear = _make_creature("Bear", power=3, toughness=3, is_commander=False, card_id=2, turn_played=0)
        sim, _ = self._run_combat([cmd, bear])
        defender = sim.players[1]
        assert defender.life == 33  # 40 - 4 - 3
        assert defender.commander_damage_received == {0: 4}

    def test_commander_trample_overflow_tracked(self):
        """Trample overflow from commander attack should be tracked as commander damage.

        The AI blocking heuristic chump-blocks when opp.life <= a_pow * 2.
        With life=10 and attacker power=6 (10 <= 12), the 0/3 will chump block.
        Trample overflow = 6 - 3 = 3, tracked as commander damage.
        """
        cmd = _make_creature(
            "Atraxa", power=6, toughness=6, is_commander=True,
            keywords=["trample"], card_id=1, turn_played=0,
        )
        blocker = _make_creature("Wall", power=0, toughness=3, card_id=10, owner_id=1, turn_played=0)
        sim, _ = self._run_combat([cmd], [blocker], p1_life=10)
        defender = sim.players[1]
        trample_over = 6 - 3  # power - blocker toughness
        assert defender.commander_damage_received == {0: trample_over}
        assert defender.life == 10 - trample_over

    def test_commander_double_strike_unblocked(self):
        """Double strike commander deals 2x damage, all tracked as commander damage."""
        cmd = _make_creature(
            "Rafiq", power=3, toughness=3, is_commander=True,
            keywords=["double strike"], card_id=1, turn_played=0,
        )
        sim, _ = self._run_combat([cmd])
        defender = sim.players[1]
        assert defender.life == 34  # 40 - 3*2
        assert defender.commander_damage_received == {0: 6}

    def test_commander_lifelink_heals_attacker(self):
        """Lifelink on commander heals attacker while tracking commander damage."""
        cmd = _make_creature(
            "Oloro", power=4, toughness=4, is_commander=True,
            keywords=["lifelink"], card_id=1, turn_played=0,
        )
        sim, _ = self._run_combat([cmd], p0_life=30)
        attacker = sim.players[0]
        defender = sim.players[1]
        assert defender.life == 36
        assert defender.commander_damage_received == {0: 4}
        assert attacker.life == 34  # healed 4

    def test_blocked_commander_no_player_damage(self):
        """Fully blocked commander with no trample deals no player damage."""
        cmd = _make_creature(
            "Atraxa", power=3, toughness=3, is_commander=True,
            card_id=1, turn_played=0,
        )
        blocker = _make_creature("Wall", power=0, toughness=5, card_id=10, owner_id=1, turn_played=0)
        sim, _ = self._run_combat([cmd], [blocker])
        defender = sim.players[1]
        assert defender.life == 40
        assert defender.commander_damage_received == {}

    def test_cumulative_combat_commander_damage_kills(self):
        """Multiple combat steps accumulate commander damage to 21+."""
        sim = _two_player_sim(
            p0_battlefield=[
                _make_creature("Atraxa", power=7, toughness=7, is_commander=True, card_id=1, turn_played=0)
            ],
        )
        sim.turn = 1
        engine = GameEngine()
        # Swing 3 times (7 * 3 = 21)
        for _ in range(3):
            # Untap attacker between swings
            for c in sim.get_battlefield(0):
                c.tapped = False
            engine._resolve_combat(sim, pi=0, turn=1)
        defender = sim.players[1]
        assert defender.commander_damage_received == {0: 21}
        assert defender.eliminated

    def test_stats_damage_dealt_tracked(self):
        """Attacker's damage_dealt stat is correctly updated."""
        cmd = _make_creature("Atraxa", power=5, toughness=5, is_commander=True, card_id=1, turn_played=0)
        sim, _ = self._run_combat([cmd])
        attacker = sim.players[0]
        assert attacker.stats.damage_dealt == 5


# ── CommanderGameState compat tests ──────────────────────────

class TestGameStateCompat:
    """Ensure CommanderGameState still works after Player model change."""

    def test_commander_player_delegates_to_base(self):
        from commander_ai_lab.sim.game_state import CommanderPlayer
        p = Player(name="Test", life=40)
        cp = CommanderPlayer(base=p)
        cp.commander_damage_received[0] = 15
        assert p.commander_damage_received == {0: 15}

    def test_commander_game_state_deal_damage(self):
        from commander_ai_lab.sim.game_state import CommanderGameState
        sim = SimState()
        sim.init_battlefields(2)
        sim.players.append(Player(name="P0", life=40, owner_id=0))
        sim.players.append(Player(name="P1", life=40, owner_id=1))
        gs = CommanderGameState.from_sim_state(sim)
        gs.deal_commander_damage(from_seat=0, to_seat=1, amount=10)
        assert gs.get_commander_damage(0, 1) == 10
        assert gs.commander_players[1].life == 30
        # Base Player also has the damage
        assert sim.players[1].commander_damage_received == {0: 10}

    def test_is_dead_to_commander_damage_via_base(self):
        from commander_ai_lab.sim.game_state import CommanderPlayer
        p = Player(name="Test", life=40)
        cp = CommanderPlayer(base=p)
        p.commander_damage_received[0] = 21
        assert cp.is_dead_to_commander_damage()
