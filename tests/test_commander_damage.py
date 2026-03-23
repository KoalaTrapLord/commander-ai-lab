"""
Commander Damage Regression Tests
==================================
Run with: pytest tests/test_commander_damage.py -v

Covers:
  - Commander source identity during combat
  - Trample overflow counts as commander damage
  - Double strike commander damage
  - Partner / multi-commander per-card tracking
  - 21-damage lethal check (per-card, not per-seat)
  - Commander damage through CommanderGameState helper
  - Non-commander creatures do NOT generate commander damage
  - Lifelink + commander damage interaction
"""

from __future__ import annotations

import pytest

from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState
from commander_ai_lab.sim.engine import GameEngine
from commander_ai_lab.sim.game_state import (
    CommanderGameState,
    CommanderPlayer,
)


# ── Helpers ──────────────────────────────────────────────────


def _make_creature(
    name: str,
    power: str = "3",
    toughness: str = "3",
    keywords: list[str] | None = None,
    is_commander: bool = False,
) -> Card:
    c = Card(
        name=name,
        type_line="Legendary Creature" if is_commander else "Creature",
        cmc=3,
        power=power,
        toughness=toughness,
        keywords=keywords or [],
        is_commander=is_commander,
    )
    return c


def _make_land(name: str = "Mountain") -> Card:
    return Card(name=name, type_line="Basic Land", cmc=0)


def _setup_combat(
    attacker_creatures: list[Card],
    blocker_creatures: list[Card] | None = None,
    attacker_life: int = 40,
    defender_life: int = 40,
) -> tuple[GameEngine, SimState, int, int]:
    """Set up a 2-player SimState ready for _resolve_combat.

    Returns (engine, sim, attacker_seat, defender_seat).
    Attacker is seat 0, defender is seat 1.
    All creatures are pre-placed on battlefield, untapped, played on a previous turn.
    """
    engine = GameEngine(max_turns=25, starting_life=40, record_log=True)
    sim = SimState(max_turns=25)
    sim.turn = 5  # so creatures played earlier pass summoning sickness check

    p0 = Player(name="Attacker", life=attacker_life, owner_id=0, stats=PlayerStats())
    p1 = Player(name="Defender", life=defender_life, owner_id=1, stats=PlayerStats())
    sim.players = [p0, p1]
    sim.init_battlefields(2)

    card_id = 90000
    for c in attacker_creatures:
        c.owner_id = 0
        c.tapped = False
        c.turn_played = 1  # played on an earlier turn
        c.id = card_id
        card_id += 1
        sim.add_to_battlefield(0, c)

    for c in (blocker_creatures or []):
        c.owner_id = 1
        c.tapped = False
        c.turn_played = 1
        c.id = card_id
        card_id += 1
        sim.add_to_battlefield(1, c)

    sim.next_card_id = card_id
    return engine, sim, 0, 1


# ── Tests: Basic commander damage tracking ───────────────────


class TestCommanderDamageBasic:
    """Commander creatures attacking unblocked should generate
    commander damage tracked on the defending player."""

    def test_unblocked_commander_deals_commander_damage(self):
        cmd = _make_creature("Krenko", "5", "5", is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        # Life reduced
        assert opp.life == 35
        # Per-seat aggregate
        assert opp.commander_damage_received[pi] == 5
        # Per-card breakdown
        assert opp.commander_damage_by_card[(pi, "Krenko")] == 5

    def test_unblocked_non_commander_no_commander_damage(self):
        creature = _make_creature("Goblin", "4", "4", is_commander=False)
        engine, sim, pi, oi = _setup_combat([creature])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        assert opp.life == 36
        assert opp.commander_damage_received == {}
        assert opp.commander_damage_by_card == {}

    def test_mixed_attackers_only_commander_tracked(self):
        cmd = _make_creature("Krenko", "3", "3", is_commander=True)
        grunt = _make_creature("Goblin", "2", "2", is_commander=False)
        engine, sim, pi, oi = _setup_combat([cmd, grunt])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        # Total damage = 3 + 2 = 5
        assert opp.life == 35
        # Only commander damage tracked
        assert opp.commander_damage_received[pi] == 3
        assert opp.commander_damage_by_card[(pi, "Krenko")] == 3

    def test_cumulative_commander_damage_across_combats(self):
        cmd = _make_creature("Krenko", "5", "5", is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd])
        # First combat
        engine._resolve_combat(sim, pi, sim.turn, [])
        assert sim.players[oi].commander_damage_received[pi] == 5
        # Reset tapped state for second combat
        cmd.tapped = False
        sim.turn += 1
        engine._resolve_combat(sim, pi, sim.turn, [])
        assert sim.players[oi].commander_damage_received[pi] == 10
        assert sim.players[oi].commander_damage_by_card[(pi, "Krenko")] == 10


# ── Tests: Commander damage lethal (21+) ─────────────────────


class TestCommanderDamageLethal:

    def test_21_damage_eliminates(self):
        cmd = _make_creature("Krenko", "7", "7", is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd], defender_life=100)
        # Deal 7 per combat, need 3 combats = 21
        for _ in range(3):
            cmd.tapped = False
            engine._resolve_combat(sim, pi, sim.turn, [])
            sim.turn += 1
        opp = sim.players[oi]
        assert opp.commander_damage_received[pi] == 21
        assert opp.eliminated

    def test_20_damage_not_lethal(self):
        """20 commander damage should NOT eliminate."""
        p = Player(name="Test", life=40)
        p.commander_damage_received = {0: 20}
        p.commander_damage_by_card = {(0, "Krenko"): 20}
        assert not p.is_dead_to_commander_damage()

    def test_21_per_card_not_per_seat(self):
        """With partners, 21 must come from a SINGLE commander, not combined."""
        p = Player(name="Test", life=40)
        # Two partner commanders from seat 0, 11 each = 22 total but neither is 21
        p.commander_damage_by_card = {
            (0, "Brallin"): 11,
            (0, "Shabraz"): 11,
        }
        p.commander_damage_received = {0: 22}
        assert not p.is_dead_to_commander_damage()

    def test_21_from_one_partner_is_lethal(self):
        """If one partner reaches 21, that's lethal even if the other has 0."""
        p = Player(name="Test", life=40)
        p.commander_damage_by_card = {
            (0, "Brallin"): 21,
            (0, "Shabraz"): 3,
        }
        p.commander_damage_received = {0: 24}
        assert p.is_dead_to_commander_damage()

    def test_backward_compat_no_by_card(self):
        """If commander_damage_by_card is empty, fall back to per-seat check."""
        p = Player(name="Test", life=40)
        p.commander_damage_received = {0: 21}
        # No by_card data (older game state)
        assert p.is_dead_to_commander_damage()


# ── Tests: Trample commander damage ──────────────────────────


class TestCommanderDamageTrample:

    def test_trample_overflow_is_commander_damage(self):
        """When a commander with trample is chump-blocked, overflow to
        the player should count as commander damage."""
        cmd = _make_creature("Ghalta", "12", "12", keywords=["trample"], is_commander=True)
        # Defender life low enough that AI decides to chump-block
        # (opp.life <= a_pow * 2  ⇒  20 <= 24)
        blocker = _make_creature("Bear", "2", "2")
        engine, sim, pi, oi = _setup_combat([cmd], [blocker], defender_life=20)
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        # Bear (2/2) chump-blocks Ghalta (12/12 trample).
        # Trample overflow = 12 - 2 = 10 damage to player.
        assert opp.commander_damage_received[pi] == 10
        assert opp.commander_damage_by_card[(pi, "Ghalta")] == 10
        assert opp.life == 10

    def test_fully_blocked_commander_no_player_damage(self):
        """Commander fully absorbed by a survivable blocker — no commander
        damage to the defending player."""
        cmd = _make_creature("Krenko", "3", "3", is_commander=True)
        # Blocker toughness > attacker power so AI selects it
        blocker = _make_creature("Wall", "0", "5")
        engine, sim, pi, oi = _setup_combat([cmd], [blocker])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        # No damage to player (absorbed by blocker, no trample)
        assert opp.life == 40
        assert opp.commander_damage_received == {}


# ── Tests: Double strike commander damage ────────────────────


class TestCommanderDamageDoubleStrike:

    def test_unblocked_double_strike_commander(self):
        cmd = _make_creature("Rafiq", "5", "5", keywords=["double strike"], is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        # Double strike unblocked = power * 2
        assert opp.life == 30
        assert opp.commander_damage_received[pi] == 10
        assert opp.commander_damage_by_card[(pi, "Rafiq")] == 10


# ── Tests: Partner / multi-commander ─────────────────────────


class TestPartnerCommanderDamage:

    def test_two_partner_commanders_tracked_separately(self):
        cmd_a = _make_creature("Brallin", "4", "4", is_commander=True)
        cmd_b = _make_creature("Shabraz", "3", "3", is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd_a, cmd_b])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        opp = sim.players[oi]
        # Total damage = 4 + 3 = 7
        assert opp.life == 33
        # Aggregate per-seat
        assert opp.commander_damage_received[pi] == 7
        # Per-card individual
        assert opp.commander_damage_by_card[(pi, "Brallin")] == 4
        assert opp.commander_damage_by_card[(pi, "Shabraz")] == 3

    def test_partner_21_check_per_card(self):
        """Even with partners, only 21 from ONE commander kills."""
        cmd_a = _make_creature("Brallin", "7", "7", is_commander=True)
        cmd_b = _make_creature("Shabraz", "7", "7", is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd_a, cmd_b], defender_life=100)
        # 3 combats: 7*3=21 for Brallin, 7*3=21 for Shabraz
        # After 2 combats: 14 each — not lethal
        for _ in range(2):
            cmd_a.tapped = False
            cmd_b.tapped = False
            engine._resolve_combat(sim, pi, sim.turn, [])
            sim.turn += 1
        opp = sim.players[oi]
        assert not opp.eliminated  # 14 from each, neither is 21
        # 3rd combat pushes both to 21
        cmd_a.tapped = False
        cmd_b.tapped = False
        engine._resolve_combat(sim, pi, sim.turn, [])
        assert opp.eliminated


# ── Tests: CommanderGameState integration ────────────────────


class TestCommanderGameStateDamage:

    def test_deal_commander_damage_with_name(self):
        sim = SimState()
        sim.init_battlefields(2)
        for i in range(2):
            sim.players.append(Player(name=f"P{i}", life=40, owner_id=i))
        gs = CommanderGameState.from_sim_state(sim)
        gs.deal_commander_damage(0, 1, 10, commander_name="Krenko")
        cp = gs.commander_players[1]
        assert cp.commander_damage_received[0] == 10
        assert cp.base.commander_damage_by_card[(0, "Krenko")] == 10
        assert cp.life == 30

    def test_deal_commander_damage_without_name_backward_compat(self):
        sim = SimState()
        sim.init_battlefields(2)
        for i in range(2):
            sim.players.append(Player(name=f"P{i}", life=40, owner_id=i))
        gs = CommanderGameState.from_sim_state(sim)
        gs.deal_commander_damage(0, 1, 10)
        cp = gs.commander_players[1]
        assert cp.commander_damage_received[0] == 10
        assert cp.base.commander_damage_by_card == {}
        assert cp.life == 30

    def test_commander_player_property_delegates_to_base(self):
        """CommanderPlayer.commander_damage_received should be the same
        object as base.commander_damage_received."""
        p = Player(name="Test", life=40)
        cp = CommanderPlayer(base=p)
        # Write through base
        p.commander_damage_received[0] = 15
        # Read through wrapper
        assert cp.commander_damage_received[0] == 15
        # Write through wrapper
        cp.commander_damage_received[1] = 7
        assert p.commander_damage_received[1] == 7


# ── Tests: Event log annotation ──────────────────────────────


class TestCommanderDamageEvents:

    def test_event_log_includes_cmdr_annotation(self):
        cmd = _make_creature("Krenko", "5", "5", is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        # Should mention commander damage in the event text
        damage_event = [e for e in events if "combat damage" in e]
        assert len(damage_event) == 1
        assert "5 cmdr" in damage_event[0]

    def test_no_cmdr_annotation_for_non_commanders(self):
        grunt = _make_creature("Goblin", "3", "3", is_commander=False)
        engine, sim, pi, oi = _setup_combat([grunt])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        damage_event = [e for e in events if "combat damage" in e]
        assert len(damage_event) == 1
        assert "cmdr" not in damage_event[0]


# ── Tests: Lifelink + commander interaction ──────────────────


class TestCommanderDamageLifelink:

    def test_commander_with_lifelink_heals_and_tracks(self):
        cmd = _make_creature("Oloro", "5", "5", keywords=["lifelink"], is_commander=True)
        engine, sim, pi, oi = _setup_combat([cmd])
        events: list[str] = []
        engine._resolve_combat(sim, pi, sim.turn, events)
        attacker = sim.players[pi]
        opp = sim.players[oi]
        # Commander damage tracked
        assert opp.commander_damage_received[pi] == 5
        # Lifelink healed attacker
        assert attacker.life == 45
        # Defender took damage
        assert opp.life == 35


# ── Tests: Player model ─────────────────────────────────────


class TestPlayerCommanderDamageModel:

    def test_fresh_player_has_empty_tracking(self):
        p = Player(name="Test")
        assert p.commander_damage_received == {}
        assert p.commander_damage_by_card == {}
        assert not p.is_dead_to_commander_damage()

    def test_is_dead_prefers_by_card(self):
        """When by_card data exists, per-seat aggregate is ignored for lethal check."""
        p = Player(name="Test")
        p.commander_damage_received = {0: 25}  # aggregate says lethal
        p.commander_damage_by_card = {
            (0, "CmdA"): 12,
            (0, "CmdB"): 13,
        }
        # Per-card: neither commander has 21 → NOT lethal
        assert not p.is_dead_to_commander_damage()
