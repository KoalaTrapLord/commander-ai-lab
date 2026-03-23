"""Regression tests for direct-damage spell routing (Issue #86).

Tests that burn spells and similar direct-damage effects are routed
through the centralized deal_damage() path, correctly update
life totals / stats, and integrate with commander damage tracking.

Adapted to work with the dual-dict commander damage model from PR #89:
  - commander_damage_received[seat] = per-seat aggregate
  - commander_damage_by_card[(seat, card_name)] = per-card breakdown
"""
import pytest
from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState
from commander_ai_lab.sim.rules import enrich_card
from commander_ai_lab.sim.engine import GameEngine


# ── Helpers ──────────────────────────────────────────────────

def _make_creature(name="Bear", pt="2/2", cmc=2, oracle_text="", **kwargs) -> Card:
    """Build a creature Card with optional oracle text."""
    c = Card(
        name=name,
        type_line="Creature",
        cmc=cmc,
        pt=pt,
        power=pt.split("/")[0],
        toughness=pt.split("/")[1],
        oracle_text=oracle_text,
        **kwargs,
    )
    enrich_card(c)
    return c


def _make_land(name="Forest") -> Card:
    c = Card(name=name)
    enrich_card(c)
    return c


def _make_burn(name="Lightning Bolt", cmc=1, oracle_text="Lightning Bolt deals 3 damage to any target.") -> Card:
    c = Card(name=name, type_line="Instant", cmc=cmc, oracle_text=oracle_text)
    enrich_card(c)
    return c


def _setup_two_player(
    p0_hand=None, p1_hand=None, p0_life=40, p1_life=40,
    p0_battlefield=None, p1_battlefield=None,
) -> tuple[GameEngine, SimState]:
    """Set up a 2-player SimState with controlled hands/battlefields."""
    engine = GameEngine(max_turns=5)
    sim = SimState(max_turns=5)
    for i, (hand, life, bf) in enumerate([
        (p0_hand or [], p0_life, p0_battlefield or []),
        (p1_hand or [], p1_life, p1_battlefield or []),
    ]):
        p = Player(
            name=f"Player {i}",
            life=life,
            owner_id=i,
            hand=list(hand),
            library=[_make_land() for _ in range(30)],
            stats=PlayerStats(cards_drawn=7),
        )
        sim.players.append(p)
    sim.init_battlefields(2)
    for seat, bf_cards in enumerate([p0_battlefield or [], p1_battlefield or []]):
        for c in bf_cards:
            c.owner_id = seat
            c.id = sim.next_card_id
            sim.next_card_id += 1
            c.turn_played = -1
            sim.add_to_battlefield(seat, c)
    return engine, sim


def _setup_four_player(
    hands=None, lives=None, battlefields=None,
) -> tuple[GameEngine, SimState]:
    """Set up a 4-player SimState."""
    engine = GameEngine(max_turns=5)
    sim = SimState(max_turns=5)
    hands = hands or [[] for _ in range(4)]
    lives = lives or [40, 40, 40, 40]
    battlefields = battlefields or [[] for _ in range(4)]
    for i in range(4):
        p = Player(
            name=f"Player {i}",
            life=lives[i],
            owner_id=i,
            hand=list(hands[i]),
            library=[_make_land() for _ in range(30)],
            stats=PlayerStats(cards_drawn=7),
        )
        sim.players.append(p)
    sim.init_battlefields(4)
    for seat, bf_cards in enumerate(battlefields):
        for c in bf_cards:
            c.owner_id = seat
            c.id = sim.next_card_id
            sim.next_card_id += 1
            c.turn_played = -1
            sim.add_to_battlefield(seat, c)
    return engine, sim


# ══════════════════════════════════════════════════════════════
# deal_damage() centralized method tests
# ══════════════════════════════════════════════════════════════

class TestDealDamage:
    """Tests for GameEngine.deal_damage() static method."""

    def test_basic_damage_reduces_life(self):
        engine, sim = _setup_two_player(p1_life=20)
        dealt = engine.deal_damage(sim, 5, target_seat=1, source_seat=0)
        assert dealt == 5
        assert sim.players[1].life == 15

    def test_zero_damage_is_noop(self):
        engine, sim = _setup_two_player(p1_life=20)
        dealt = engine.deal_damage(sim, 0, target_seat=1)
        assert dealt == 0
        assert sim.players[1].life == 20

    def test_negative_damage_is_noop(self):
        engine, sim = _setup_two_player(p1_life=20)
        dealt = engine.deal_damage(sim, -3, target_seat=1)
        assert dealt == 0
        assert sim.players[1].life == 20

    def test_damage_updates_stats(self):
        engine, sim = _setup_two_player()
        engine.deal_damage(sim, 7, target_seat=1, source_seat=0)
        assert sim.players[0].stats.damage_dealt == 7
        assert sim.players[1].stats.damage_received == 7

    def test_damage_eliminates_at_zero(self):
        engine, sim = _setup_two_player(p1_life=3)
        engine.deal_damage(sim, 3, target_seat=1, source_seat=0)
        assert sim.players[1].life == 0
        assert sim.players[1].eliminated is True

    def test_damage_eliminates_below_zero(self):
        engine, sim = _setup_two_player(p1_life=2)
        engine.deal_damage(sim, 5, target_seat=1, source_seat=0)
        assert sim.players[1].life == -3
        assert sim.players[1].eliminated is True

    def test_damage_to_eliminated_player_is_noop(self):
        engine, sim = _setup_two_player(p1_life=0)
        sim.players[1].eliminated = True
        dealt = engine.deal_damage(sim, 10, target_seat=1)
        assert dealt == 0
        assert sim.players[1].life == 0

    def test_events_logged(self):
        engine, sim = _setup_two_player(p1_life=20)
        events: list[str] = []
        engine.deal_damage(sim, 3, target_seat=1, source_seat=0,
                           events=events, label="Bolt deals 3")
        assert len(events) == 1
        assert "Bolt deals 3" in events[0]
        assert "Player 1 now at 17 life" in events[0]

    def test_no_label_means_no_event(self):
        engine, sim = _setup_two_player(p1_life=20)
        events: list[str] = []
        engine.deal_damage(sim, 3, target_seat=1, events=events)
        assert len(events) == 0


# ══════════════════════════════════════════════════════════════
# Commander damage tracking through deal_damage()
# ══════════════════════════════════════════════════════════════

class TestCommanderDamageTracking:
    """Tests for commander damage tracked by deal_damage() using
    the dual-dict model: per-seat aggregate + per-card breakdown."""

    def test_commander_damage_tracked_both_dicts(self):
        engine, sim = _setup_two_player()
        cmd = _make_creature("Atraxa", pt="4/4", is_commander=True)
        engine.deal_damage(sim, 4, target_seat=1, source_card=cmd, source_seat=0, is_combat=True)
        # Per-seat aggregate
        assert sim.players[1].commander_damage_received[0] == 4
        # Per-card breakdown
        assert sim.players[1].commander_damage_by_card[(0, "Atraxa")] == 4

    def test_commander_damage_accumulates(self):
        engine, sim = _setup_two_player()
        cmd = _make_creature("Atraxa", pt="4/4", is_commander=True)
        engine.deal_damage(sim, 4, target_seat=1, source_card=cmd, source_seat=0)
        engine.deal_damage(sim, 4, target_seat=1, source_card=cmd, source_seat=0)
        assert sim.players[1].commander_damage_received[0] == 8
        assert sim.players[1].commander_damage_by_card[(0, "Atraxa")] == 8

    def test_commander_21_damage_eliminates(self):
        engine, sim = _setup_two_player()
        cmd = _make_creature("Atraxa", pt="7/7", is_commander=True)
        for _ in range(3):
            engine.deal_damage(sim, 7, target_seat=1, source_card=cmd, source_seat=0)
        assert sim.players[1].commander_damage_by_card[(0, "Atraxa")] == 21
        assert sim.players[1].eliminated is True

    def test_partner_commanders_tracked_separately(self):
        engine, sim = _setup_two_player()
        cmd_a = _make_creature("Thrasios", pt="1/3", is_commander=True)
        cmd_b = _make_creature("Tymna", pt="2/2", is_commander=True)
        # 15 from Thrasios, 15 from Tymna — neither hits 21 alone
        for _ in range(15):
            engine.deal_damage(sim, 1, target_seat=1, source_card=cmd_a, source_seat=0)
        for _ in range(15):
            engine.deal_damage(sim, 1, target_seat=1, source_card=cmd_b, source_seat=0)
        # Per-card: each under 21
        assert sim.players[1].commander_damage_by_card[(0, "Thrasios")] == 15
        assert sim.players[1].commander_damage_by_card[(0, "Tymna")] == 15
        # Per-seat aggregate: 30 total
        assert sim.players[1].commander_damage_received[0] == 30
        # Life is 10, but not eliminated by commander damage (no single source >= 21)
        assert sim.players[1].life == 10
        assert sim.players[1].is_dead_to_commander_damage() is False

    def test_non_commander_damage_not_tracked(self):
        engine, sim = _setup_two_player()
        regular = _make_creature("Bear", pt="2/2")
        engine.deal_damage(sim, 2, target_seat=1, source_card=regular, source_seat=0)
        assert sim.players[1].commander_damage_received == {}
        assert sim.players[1].commander_damage_by_card == {}

    def test_is_dead_to_commander_damage(self):
        p = Player(name="Test", life=40)
        assert p.is_dead_to_commander_damage() is False
        p.commander_damage_by_card[(0, "Kozilek")] = 20
        p.commander_damage_received[0] = 20
        assert p.is_dead_to_commander_damage() is False
        p.commander_damage_by_card[(0, "Kozilek")] = 21
        p.commander_damage_received[0] = 21
        assert p.is_dead_to_commander_damage() is True

    def test_commander_damage_eliminates_despite_high_life(self):
        """A player at 100 life should still die to 21 commander damage."""
        engine, sim = _setup_two_player(p1_life=100)
        cmd = _make_creature("Voltron", pt="21/21", is_commander=True)
        engine.deal_damage(sim, 21, target_seat=1, source_card=cmd, source_seat=0)
        assert sim.players[1].life == 79
        assert sim.players[1].eliminated is True


# ══════════════════════════════════════════════════════════════
# Direct-damage spell detection (rules.py)
# ══════════════════════════════════════════════════════════════

class TestDirectDamageDetection:
    """Tests for is_direct_damage detection in enrich_card/rules."""

    def test_lightning_bolt_detected(self):
        c = Card(name="Lightning Bolt", type_line="Instant", cmc=1,
                 oracle_text="Lightning Bolt deals 3 damage to any target.")
        enrich_card(c)
        assert c.is_direct_damage is True
        assert c.direct_damage_amount == 3

    def test_shock_detected(self):
        c = Card(name="Shock", type_line="Instant", cmc=1,
                 oracle_text="Shock deals 2 damage to any target.")
        enrich_card(c)
        assert c.is_direct_damage is True
        assert c.direct_damage_amount == 2

    def test_known_burn_by_name(self):
        """Known burn spells should be detected even without oracle text."""
        c = Card(name="Lightning Bolt")
        enrich_card(c)
        assert c.is_direct_damage is True
        assert c.direct_damage_amount == 3

    def test_chain_lightning_detected(self):
        c = Card(name="Chain Lightning")
        enrich_card(c)
        assert c.is_direct_damage is True
        assert c.direct_damage_amount == 3

    def test_boros_charm_detected(self):
        c = Card(name="Boros Charm")
        enrich_card(c)
        assert c.is_direct_damage is True
        assert c.direct_damage_amount == 4

    def test_oracle_text_detection(self):
        """An unknown card with direct-damage oracle text should be detected."""
        c = Card(
            name="Custom Burn Spell",
            type_line="Instant",
            cmc=2,
            oracle_text="Custom Burn Spell deals 5 damage to target creature or player.",
        )
        enrich_card(c)
        assert c.is_direct_damage is True
        assert c.direct_damage_amount == 5

    def test_board_wipe_not_flagged(self):
        """Board wipes should not be flagged as direct damage."""
        c = Card(name="Blasphemous Act", type_line="Sorcery", cmc=9,
                 oracle_text="Blasphemous Act deals 13 damage to each creature.")
        enrich_card(c)
        assert c.is_board_wipe is True
        assert c.is_direct_damage is False

    def test_creature_not_flagged(self):
        """A vanilla creature should not be flagged as direct damage."""
        c = _make_creature("Grizzly Bears", pt="2/2")
        assert c.is_direct_damage is False

    def test_removal_spell_not_flagged_as_direct_damage(self):
        """Pure removal (destroy target) should not become direct damage."""
        c = Card(name="Murder", type_line="Instant", cmc=3,
                 oracle_text="Destroy target creature.")
        enrich_card(c)
        assert c.is_removal is True
        assert c.is_direct_damage is False


# ══════════════════════════════════════════════════════════════
# Direct-damage routing through _play_spells()
# ══════════════════════════════════════════════════════════════

class TestDirectDamageSpellRouting:
    """Tests that burn spells resolve through deal_damage() during gameplay."""

    def test_burn_spell_reduces_opponent_life(self):
        bolt = _make_burn("Lightning Bolt")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_two_player(
            p0_hand=[bolt],
            p0_battlefield=lands,
            p1_life=20,
        )
        events: list[str] = []
        engine._play_spells(sim, 0, available_mana=3, events=events)
        # Lightning Bolt: 3 damage
        assert sim.players[1].life == 17
        assert sim.players[0].stats.damage_dealt == 3
        assert sim.players[1].stats.damage_received == 3

    def test_burn_spell_goes_to_graveyard(self):
        bolt = _make_burn("Lightning Bolt")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_two_player(
            p0_hand=[bolt],
            p0_battlefield=lands,
        )
        engine._play_spells(sim, 0, available_mana=3)
        # Bolt should be in graveyard
        assert any(c.name == "Lightning Bolt" for c in sim.players[0].graveyard)

    def test_burn_spell_eliminates_low_life_opponent(self):
        bolt = _make_burn("Lightning Bolt")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_two_player(
            p0_hand=[bolt],
            p0_battlefield=lands,
            p1_life=2,
        )
        engine._play_spells(sim, 0, available_mana=3)
        assert sim.players[1].life == -1
        assert sim.players[1].eliminated is True

    def test_burn_targets_weakest_opponent(self):
        """In multiplayer, burn should target the weakest opponent."""
        bolt = _make_burn("Lightning Bolt")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_four_player(
            hands=[[bolt], [], [], []],
            lives=[40, 30, 10, 20],
            battlefields=[lands, [], [], []],
        )
        engine._play_spells(sim, 0, available_mana=3)
        # Player 2 (life=10) is weakest, should be targeted
        assert sim.players[2].life == 7

    def test_burn_events_logged(self):
        bolt = _make_burn("Lightning Bolt")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_two_player(
            p0_hand=[bolt],
            p0_battlefield=lands,
            p1_life=20,
        )
        events: list[str] = []
        engine._play_spells(sim, 0, available_mana=3, events=events)
        burn_events = [e for e in events if "Lightning Bolt" in e and "damage" in e]
        assert len(burn_events) >= 1

    def test_burn_spell_taps_lands(self):
        bolt = _make_burn("Lightning Bolt")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_two_player(
            p0_hand=[bolt],
            p0_battlefield=lands,
        )
        engine._play_spells(sim, 0, available_mana=3)
        tapped_lands = [c for c in sim.get_battlefield(0) if c.is_land() and c.tapped]
        assert len(tapped_lands) == 1  # CMC 1

    def test_shock_deals_2(self):
        shock = _make_burn("Shock", cmc=1, oracle_text="Shock deals 2 damage to any target.")
        lands = [_make_land() for _ in range(3)]
        engine, sim = _setup_two_player(
            p0_hand=[shock],
            p0_battlefield=lands,
            p1_life=20,
        )
        engine._play_spells(sim, 0, available_mana=3)
        assert sim.players[1].life == 18


# ══════════════════════════════════════════════════════════════
# Combat damage routing through deal_damage()
# ══════════════════════════════════════════════════════════════

class TestCombatDamageRouting:
    """Tests that combat damage routes through deal_damage()."""

    def test_unblocked_creature_deals_damage(self):
        bear = _make_creature("Bear", pt="2/2")
        lands = [_make_land() for _ in range(5)]
        engine, sim = _setup_two_player(
            p0_battlefield=[bear] + lands,
            p1_life=20,
        )
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].life == 18
        assert sim.players[0].stats.damage_dealt == 2
        assert sim.players[1].stats.damage_received == 2

    def test_commander_combat_damage_tracked(self):
        cmd = _make_creature("Atraxa", pt="4/4", is_commander=True)
        lands = [_make_land() for _ in range(5)]
        engine, sim = _setup_two_player(
            p0_battlefield=[cmd] + lands,
            p1_life=40,
        )
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].life == 36
        # Per-seat aggregate
        assert sim.players[1].commander_damage_received[0] == 4
        # Per-card breakdown
        assert sim.players[1].commander_damage_by_card[(0, "Atraxa")] == 4

    def test_non_commander_combat_damage_not_tracked_as_commander(self):
        bear = _make_creature("Bear", pt="3/3")
        lands = [_make_land() for _ in range(5)]
        engine, sim = _setup_two_player(
            p0_battlefield=[bear] + lands,
            p1_life=40,
        )
        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].life == 37
        assert sim.players[1].commander_damage_received == {}
        assert sim.players[1].commander_damage_by_card == {}

    def test_commander_lethal_at_21(self):
        """A commander dealing 21 damage should eliminate even at high life."""
        cmd = _make_creature("Voltron", pt="7/7", is_commander=True)
        lands = [_make_land() for _ in range(5)]
        engine, sim = _setup_two_player(
            p0_battlefield=[cmd] + lands,
            p1_life=100,
        )
        # Simulate 3 combat rounds
        for t in range(3):
            if sim.players[1].eliminated:
                break
            # Reset attacker for next combat
            cmd.tapped = False
            cmd.turn_played = -1
            engine._resolve_combat(sim, 0, turn=t + 1)
        assert sim.players[1].commander_damage_by_card[(0, "Voltron")] == 21
        assert sim.players[1].eliminated is True


# ══════════════════════════════════════════════════════════════
# Full-game integration with burn spells
# ══════════════════════════════════════════════════════════════

class TestFullGameWithBurn:
    """Integration tests running full games with burn spells in decks."""

    def test_game_with_burn_completes(self):
        """A game with burn spells in decks should complete without error."""
        deck_a = (
            [Card(name="Lightning Bolt") for _ in range(8)]
            + [Card(name="Shock") for _ in range(8)]
            + [Card(name="Forest") for _ in range(24)]
            + [Card(name="Grizzly Bears") for _ in range(20)]
        )
        deck_b = (
            [Card(name="Forest") for _ in range(24)]
            + [Card(name="Serra Angel") for _ in range(10)]
            + [Card(name="Grizzly Bears") for _ in range(20)]
            + [Card(name="Murder") for _ in range(6)]
        )
        for c in deck_a + deck_b:
            enrich_card(c)

        engine = GameEngine(max_turns=25, record_log=True)
        result = engine.run(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
            name_a="Burn",
            name_b="Midrange",
        )
        assert result is not None
        assert result.turns > 0
        assert result.winner_seat in (-1, 0, 1)

    def test_burn_damage_appears_in_stats(self):
        """Burn spell damage should be reflected in player stats."""
        deck_a = (
            [Card(name="Lightning Bolt") for _ in range(15)]
            + [Card(name="Mountain") for _ in range(45)]
        )
        deck_b = [Card(name="Forest") for _ in range(60)]
        for c in deck_a + deck_b:
            enrich_card(c)

        engine = GameEngine(max_turns=25)
        result = engine.run(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
            name_a="Burn",
            name_b="Lands",
        )
        # Player A should have dealt some damage from burn spells
        pa_stats = result.player_a_stats
        assert pa_stats is not None
        assert pa_stats.damage_dealt > 0
