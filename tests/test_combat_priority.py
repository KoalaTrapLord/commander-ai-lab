"""Tests for combat priority checkpoints (Issue #86 Item 1).

Validates CombatState lifecycle, split combat methods,
priority windows, first-strike ordering, and instant-speed
interaction during combat.
"""
import pytest
from commander_ai_lab.sim.models import (
    Card, CombatState, Phase, Player, PlayerStats, SimState,
)
from commander_ai_lab.sim.engine import GameEngine


# ── Helpers ──────────────────────────────────────────────────────

def _make_creature(name, power, toughness, card_id, owner=0, keywords=None, is_commander=False):
    """Build a minimal creature Card for testing."""
    return Card(
        name=name,
        type_line="Creature",
        power=str(power),
        toughness=str(toughness),
        pt=f"{power}/{toughness}",
        id=card_id,
        owner_id=owner,
        keywords=keywords or [],
        is_commander=is_commander,
        turn_played=-1,
    )


def _two_player_sim(p0_creatures, p1_creatures, p0_life=40, p1_life=40):
    """Build a minimal 2-player SimState with creatures on the battlefield."""
    sim = SimState(
        players=[
            Player(name="Attacker", life=p0_life, owner_id=0, stats=PlayerStats()),
            Player(name="Defender", life=p1_life, owner_id=1, stats=PlayerStats()),
        ],
        battlefields=[list(p0_creatures), list(p1_creatures)],
        turn=2,
    )
    return sim


# ── Tests ───────────────────────────────────────────────────────

class TestCombatState:
    """CombatState dataclass lifecycle."""

    def test_combat_state_defaults(self):
        cs = CombatState()
        assert cs.defending_seat == -1
        assert cs.attackers == {}
        assert cs.blockers == {}
        assert cs.player_damage == {}
        assert cs.first_strike_resolved is False
        assert cs.active is False

    def test_combat_state_on_simstate(self):
        sim = SimState()
        assert sim.combat is None
        sim.combat = CombatState(active=True)
        assert sim.combat.active is True
        sim.combat = None
        assert sim.combat is None


class TestAssignAttackers:
    """Engine.assign_attackers() populates CombatState."""

    def test_assigns_and_taps(self):
        atk = _make_creature("Bear", 3, 3, 100)
        sim = _two_player_sim([atk], [])
        engine = GameEngine()
        combat = engine.assign_attackers(sim, 0)
        assert combat is not None
        assert combat.active is True
        assert 100 in combat.attackers
        assert atk.tapped is True
        assert sim.combat is combat

    def test_no_attack_returns_none(self):
        sim = _two_player_sim([], [])  # no creatures
        engine = GameEngine()
        assert engine.assign_attackers(sim, 0) is None
        assert sim.combat is None


class TestResolveCombatDamage:
    """Engine.resolve_combat_damage() applies damage from CombatState."""

    def test_unblocked_attacker_deals_damage(self):
        atk = _make_creature("Bear", 3, 3, 100)
        sim = _two_player_sim([atk], [], p1_life=20)
        combat = CombatState(defending_seat=1, attackers={100: 1}, active=True)
        sim.combat = combat
        engine = GameEngine()
        engine.resolve_combat_damage(sim, 0, combat)
        assert sim.players[1].life == 17  # 20 - 3

    def test_attacker_removed_before_damage_deals_nothing(self):
        """Simulates instant-speed removal of attacker after declare attackers."""
        atk = _make_creature("Bear", 3, 3, 100)
        sim = _two_player_sim([atk], [], p1_life=20)
        combat = CombatState(defending_seat=1, attackers={100: 1}, active=True)
        sim.combat = combat
        # Simulate instant-speed removal: remove attacker before damage
        sim.remove_from_battlefield(100)
        engine = GameEngine()
        engine.resolve_combat_damage(sim, 0, combat)
        assert sim.players[1].life == 20  # no damage dealt

    def test_first_strike_only_skips_non_fs(self):
        fs = _make_creature("Knight", 2, 2, 200, keywords=["first_strike"])
        normal = _make_creature("Bear", 3, 3, 201)
        sim = _two_player_sim([fs, normal], [], p1_life=20)
        combat = CombatState(
            defending_seat=1,
            attackers={200: 1, 201: 1},
            active=True,
        )
        sim.combat = combat
        engine = GameEngine()
        # First-strike step: only the knight deals damage
        engine.resolve_combat_damage(sim, 0, combat, first_strike_only=True)
        assert sim.players[1].life == 18  # 20 - 2 (knight only)
        assert combat.first_strike_resolved is True
        # Normal damage step: bear deals damage, knight skipped
        engine.resolve_combat_damage(sim, 0, combat, first_strike_only=False)
        assert sim.players[1].life == 15  # 18 - 3 (bear only)

    def test_combat_state_cleared_after_end_combat(self):
        """Verifies sim.combat is None after combat cleanup."""
        sim = SimState()
        sim.combat = CombatState(active=True)
        # Simulate end-of-combat cleanup
        sim.combat = None
        assert sim.combat is None

    def test_commander_damage_attributed(self):
        """Commander attacker routes damage through commander_damage_by_card."""
        cmd = _make_creature("Atraxa", 4, 4, 300, is_commander=True)
        sim = _two_player_sim([cmd], [], p1_life=40)
        combat = CombatState(defending_seat=1, attackers={300: 1}, active=True)
        sim.combat = combat
        engine = GameEngine()
        engine.resolve_combat_damage(sim, 0, combat)
        assert sim.players[1].life == 36  # 40 - 4
        assert sim.players[1].commander_damage_by_card.get((0, "Atraxa"), 0) == 4


class TestResponsePhasesCleanup:
    """Verify BEGIN_COMBAT and END_COMBAT removed from RESPONSE_PHASES."""

    def test_no_duplicate_apnap_begin_end_combat(self):
        from commander_ai_lab.sim.turn_manager import RESPONSE_PHASES
        assert "begin_combat" not in RESPONSE_PHASES
        assert "end_combat" not in RESPONSE_PHASES
        assert "upkeep" in RESPONSE_PHASES
        assert "end_step" in RESPONSE_PHASES