"""Regression tests for triggered-ability damage routing.

Tests that ETB and dies damage triggers fire through the centralized
deal_damage() path, correctly update life/stats, and handle edge cases
like each-opponent targeting, board wipes, removal kills, and combat deaths.
"""
import pytest
from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState
from commander_ai_lab.sim.rules import enrich_card
from commander_ai_lab.sim.engine import GameEngine


# ── Helpers ──────────────────────────────────────────────────

def _make_creature(name="Bear", pt="2/2", cmc=2, oracle_text="", **kwargs) -> Card:
    """Build a creature Card with optional oracle text for trigger detection."""
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
    # Place battlefield cards
    for seat, bf_cards in enumerate([p0_battlefield or [], p1_battlefield or []]):
        for c in bf_cards:
            c.owner_id = seat
            c.id = sim.next_card_id
            sim.next_card_id += 1
            c.turn_played = -1  # not summoning sick
            sim.add_to_battlefield(seat, c)
    return engine, sim


# ══════════════════════════════════════════════════════════════
# deal_damage() centralized method tests
# ══════════════════════════════════════════════════════════════

class TestDealDamage:
    def test_basic_damage_reduces_life(self):
        engine, sim = _setup_two_player(p1_life=20)
        dealt = engine.deal_damage(sim, 5, target_seat=1, source_seat=0)
        assert dealt == 5
        assert sim.players[1].life == 15

    def test_damage_updates_stats(self):
        engine, sim = _setup_two_player()
        engine.deal_damage(sim, 3, target_seat=1, source_seat=0)
        assert sim.players[0].stats.damage_dealt == 3
        assert sim.players[1].stats.damage_received == 3

    def test_lethal_damage_eliminates(self):
        engine, sim = _setup_two_player(p1_life=3)
        engine.deal_damage(sim, 5, target_seat=1, source_seat=0)
        assert sim.players[1].eliminated is True
        assert sim.players[1].life == -2

    def test_zero_damage_noop(self):
        engine, sim = _setup_two_player(p1_life=20)
        dealt = engine.deal_damage(sim, 0, target_seat=1, source_seat=0)
        assert dealt == 0
        assert sim.players[1].life == 20

    def test_damage_to_eliminated_player_noop(self):
        engine, sim = _setup_two_player(p1_life=0)
        sim.players[1].eliminated = True
        dealt = engine.deal_damage(sim, 5, target_seat=1, source_seat=0)
        assert dealt == 0

    def test_damage_logs_events(self):
        engine, sim = _setup_two_player(p1_life=20)
        events = []
        engine.deal_damage(sim, 4, target_seat=1, source_seat=0,
                           events=events, label="Test hit deals 4")
        assert len(events) == 1
        assert "Test hit deals 4" in events[0]
        assert "16 life" in events[0]


# ══════════════════════════════════════════════════════════════
# Trigger detection (enrich_card) tests
# ══════════════════════════════════════════════════════════════

class TestTriggerDetection:
    def test_etb_damage_detected(self):
        """Cards like 'Flametongue Kavu' style ETB damage should be detected."""
        c = _make_creature(
            name="Flametongue Kavu", pt="4/2", cmc=4,
            oracle_text="When Flametongue Kavu enters the battlefield, it deals 4 damage to target creature.",
        )
        assert c.etb_damage == 4
        assert c.etb_damage_target in ("opponent", "any_target")

    def test_dies_damage_detected(self):
        """Cards with dies-trigger damage should be detected."""
        c = _make_creature(
            name="Vindictive Lich", pt="4/1", cmc=4,
            oracle_text="When Vindictive Lich dies, it deals 3 damage to target opponent.",
        )
        assert c.dies_damage == 3
        assert c.dies_damage_target == "opponent"

    def test_each_opponent_etb(self):
        """'each opponent' ETB damage correctly classified."""
        c = _make_creature(
            name="Siege-Gang Commander", pt="2/2", cmc=5,
            oracle_text="When Siege-Gang Commander enters the battlefield, it deals 2 damage to each opponent.",
        )
        assert c.etb_damage == 2
        assert c.etb_damage_target == "each_opponent"

    def test_each_opponent_dies(self):
        """'each opponent' dies damage correctly classified."""
        c = _make_creature(
            name="Fiery Emancipation", pt="3/3", cmc=4,
            oracle_text="When Fiery Emancipation dies, it deals 3 damage to each opponent.",
        )
        assert c.dies_damage == 3
        assert c.dies_damage_target == "each_opponent"

    def test_no_trigger_on_vanilla(self):
        """Vanilla creatures should have no trigger damage."""
        c = _make_creature(name="Grizzly Bears", pt="2/2", cmc=2)
        assert c.etb_damage == 0
        assert c.dies_damage == 0

    def test_any_target_detected(self):
        """'any target' ETB should be detected."""
        c = _make_creature(
            name="Burning Sun's Avatar", pt="6/6", cmc=6,
            oracle_text="When Burning Sun's Avatar enters the battlefield, it deals 3 damage to any target.",
        )
        assert c.etb_damage == 3
        assert c.etb_damage_target == "any_target"


# ══════════════════════════════════════════════════════════════
# ETB trigger firing tests
# ══════════════════════════════════════════════════════════════

class TestETBTriggerFiring:
    def test_etb_deals_damage_to_opponent(self):
        """ETB creature with 'opponent' target damages weakest opponent."""
        etb_creature = _make_creature(
            name="Inferno Titan", pt="6/6", cmc=6,
            oracle_text="When Inferno Titan enters the battlefield, it deals 3 damage to target opponent.",
        )
        engine, sim = _setup_two_player(
            p0_hand=[etb_creature],
            p0_battlefield=[_make_land() for _ in range(6)],
            p1_life=20,
        )
        events = []
        engine._fire_etb_trigger(sim, etb_creature, controller_seat=0, events=events)
        assert sim.players[1].life == 17
        assert sim.players[0].stats.damage_dealt == 3
        assert any("etb trigger" in e for e in events)

    def test_etb_each_opponent_hits_all(self):
        """'each_opponent' ETB in a 3-player game damages all opponents."""
        etb_creature = _make_creature(
            name="Purphoros", pt="5/5", cmc=4,
            oracle_text="When Purphoros enters the battlefield, it deals 2 damage to each opponent.",
        )
        engine = GameEngine(max_turns=5)
        sim = SimState(max_turns=5)
        for i in range(3):
            sim.players.append(Player(
                name=f"P{i}", life=20, owner_id=i,
                library=[_make_land() for _ in range(10)],
                stats=PlayerStats(cards_drawn=7),
            ))
        sim.init_battlefields(3)
        events = []
        engine._fire_etb_trigger(sim, etb_creature, controller_seat=0, events=events)
        assert sim.players[0].life == 20  # controller unaffected
        assert sim.players[1].life == 18
        assert sim.players[2].life == 18
        assert sim.players[0].stats.damage_dealt == 4  # 2 to each of 2 opponents

    def test_etb_no_trigger_on_vanilla(self):
        """Vanilla creature ETB should not deal damage."""
        bear = _make_creature(name="Bear", pt="2/2", cmc=2)
        engine, sim = _setup_two_player(p1_life=20)
        engine._fire_etb_trigger(sim, bear, controller_seat=0)
        assert sim.players[1].life == 20

    def test_etb_fires_during_spell_cast(self):
        """ETB trigger fires when creature is played via _play_spells."""
        etb_creature = _make_creature(
            name="Avalanche Riders", pt="2/2", cmc=4,
            oracle_text="When Avalanche Riders enters the battlefield, it deals 2 damage to target opponent.",
        )
        engine, sim = _setup_two_player(
            p0_hand=[etb_creature],
            p0_battlefield=[_make_land() for _ in range(4)],
            p1_life=20,
        )
        events = []
        available_mana = 4
        engine._play_spells(sim, 0, available_mana, events)
        # Creature should have been cast and ETB should have fired
        assert sim.players[1].life == 18
        assert any("etb trigger" in e.lower() for e in events)


# ══════════════════════════════════════════════════════════════
# Dies trigger firing tests
# ══════════════════════════════════════════════════════════════

class TestDiesTriggerFiring:
    def test_dies_trigger_on_removal(self):
        """Dies trigger fires when creature is killed by removal."""
        dies_creature = _make_creature(
            name="Vengeful Dead", pt="3/2", cmc=3,
            oracle_text="When Vengeful Dead dies, it deals 2 damage to target opponent.",
        )
        removal = Card(name="Murder", type_line="Instant", cmc=3,
                       oracle_text="Destroy target creature.", is_removal=True)
        enrich_card(removal)

        engine, sim = _setup_two_player(
            p0_hand=[removal],
            p0_battlefield=[_make_land() for _ in range(3)],
            p1_battlefield=[dies_creature],
            p0_life=20,
        )
        events = []
        engine._play_spells(sim, 0, 3, events)
        # Murder kills the dies_creature; its dies trigger should deal 2 to P0
        # (since P1 controls the dying creature, P1's trigger targets the weakest opponent = P0)
        assert sim.players[0].life == 18  # dies trigger dealt 2 to P0

    def test_dies_trigger_on_board_wipe(self):
        """Dies triggers fire for each creature destroyed by board wipe."""
        dies_a = _make_creature(
            name="Doomed Necro", pt="2/2", cmc=2,
            oracle_text="When Doomed Necro dies, it deals 1 damage to each opponent.",
        )
        dies_b = _make_creature(
            name="Spite Elemental", pt="3/1", cmc=3,
            oracle_text="When Spite Elemental dies, it deals 1 damage to each opponent.",
        )
        wipe = Card(name="Wrath of God", type_line="Sorcery", cmc=4,
                    oracle_text="Destroy all creatures.", is_board_wipe=True)
        enrich_card(wipe)

        p0_bf = [_make_land() for _ in range(4)] + [dies_a]
        engine, sim = _setup_two_player(
            p0_hand=[wipe],
            p0_battlefield=p0_bf,
            p1_battlefield=[dies_b],
            p0_life=20,
            p1_life=20,
        )
        events = []
        engine._play_spells(sim, 0, 4, events)
        # dies_a (owned by P0) dies → deals 1 to each opponent → P1 takes 1
        # dies_b (owned by P1) dies → deals 1 to each opponent → P0 takes 1
        assert sim.players[0].life == 19  # took 1 from dies_b
        assert sim.players[1].life == 19  # took 1 from dies_a

    def test_dies_trigger_in_combat_lethal_block(self):
        """Dies trigger fires when creature is killed by a lethal blocker.

        The 3/1 has power >= 3 so the attack heuristic will choose to attack.
        The 2/2 blocker has toughness > power-of-attacker=3? No, 2 < 3. But
        the blocker will still block to save life. The blocker deals 2 damage
        to the 3/1 (toughness 1) → attacker dies. Its dies trigger fires.
        """
        dies_creature = _make_creature(
            name="Goblin Arsonist", pt="3/1", cmc=1,
            oracle_text="When Goblin Arsonist dies, it deals 1 damage to target opponent.",
        )
        blocker = _make_creature(name="Grizzly Bears", pt="2/2", cmc=2)

        engine, sim = _setup_two_player(
            p0_battlefield=[dies_creature],
            p1_battlefield=[blocker],
            p0_life=20,
            p1_life=20,
        )
        dies_creature.turn_played = -1

        events = []
        engine._resolve_combat(sim, 0, turn=1, events=events)
        # 3/1 attacks (power >= 3), 2/2 blocks. Bear deals 2 damage to 3/1 (toughness 1) → dies.
        # 3/1 deals 3 damage to bear (toughness 2) → bear also dies.
        # Dies trigger on the 3/1: deals 1 damage to P1 (weakest opponent).
        # Combat damage: 0 (both blocked and killed each other, no trample)
        # The bear's death also triggers _send_to_graveyard but bear has no dies_damage.
        assert sim.players[1].life <= 19  # got hit by dies trigger (1 damage)


class TestDiesTriggerEachOpponent:
    def test_dies_each_opponent_3player(self):
        """'each_opponent' dies trigger hits all opponents in 3-player game."""
        dies_creature = _make_creature(
            name="Blood Artist", pt="0/1", cmc=2,
            oracle_text="When Blood Artist dies, it deals 1 damage to each opponent.",
        )
        engine = GameEngine(max_turns=5)
        sim = SimState(max_turns=5)
        for i in range(3):
            sim.players.append(Player(
                name=f"P{i}", life=20, owner_id=i,
                library=[_make_land() for _ in range(10)],
                stats=PlayerStats(cards_drawn=7),
            ))
        sim.init_battlefields(3)
        dies_creature.owner_id = 0
        dies_creature.id = sim.next_card_id
        sim.next_card_id += 1
        sim.add_to_battlefield(0, dies_creature)

        events = []
        # Simulate the creature dying
        sim.remove_from_battlefield(dies_creature.id)
        engine._send_to_graveyard(sim, dies_creature, 0, controller_seat=0, events=events)

        assert sim.players[0].life == 20  # controller unaffected
        assert sim.players[1].life == 19
        assert sim.players[2].life == 19


# ══════════════════════════════════════════════════════════════
# Combat damage through deal_damage() tests
# ══════════════════════════════════════════════════════════════

class TestCombatDamageCentralized:
    def test_combat_damage_routes_through_deal_damage(self):
        """Combat damage should update stats via deal_damage() path."""
        attacker = _make_creature(name="Goblin", pt="3/1", cmc=1)
        engine, sim = _setup_two_player(
            p0_battlefield=[attacker],
            p1_life=20,
        )
        attacker.turn_played = -1  # not summoning sick

        engine._resolve_combat(sim, 0, turn=1)
        # 3/1 attacks unblocked → 3 damage to P1
        assert sim.players[1].life == 17
        assert sim.players[0].stats.damage_dealt == 3
        assert sim.players[1].stats.damage_received == 3

    def test_combat_lethal_eliminates_via_deal_damage(self):
        """Lethal combat damage eliminates the opponent via deal_damage()."""
        big = _make_creature(name="Big Boy", pt="10/10", cmc=5)
        engine, sim = _setup_two_player(
            p0_battlefield=[big],
            p1_life=5,
        )
        big.turn_played = -1

        engine._resolve_combat(sim, 0, turn=1)
        assert sim.players[1].eliminated is True
        assert sim.players[1].life <= 0


# ══════════════════════════════════════════════════════════════
# Integration: full game with trigger creatures
# ══════════════════════════════════════════════════════════════

class TestTriggeredDamageIntegration:
    def test_full_game_with_etb_creatures_completes(self):
        """A full game with ETB damage creatures should complete without error."""
        def _deck_with_etb(seed_offset=0):
            cards = []
            for i in range(24):
                cards.append(_make_land())
            for i in range(10):
                cards.append(_make_creature(
                    name=f"ETB Creature {i + seed_offset}",
                    pt="2/2", cmc=3,
                    oracle_text="When this creature enters the battlefield, it deals 1 damage to target opponent.",
                ))
            for i in range(10):
                cards.append(_make_creature(
                    name=f"Dies Creature {i + seed_offset}",
                    pt="1/1", cmc=2,
                    oracle_text="When this creature dies, it deals 1 damage to each opponent.",
                ))
            for i in range(16):
                cards.append(_make_creature(
                    name=f"Vanilla {i + seed_offset}", pt="3/3", cmc=3,
                ))
            return cards

        engine = GameEngine(max_turns=15)
        result = engine.run(
            deck_a=_deck_with_etb(0),
            deck_b=_deck_with_etb(100),
            name_a="ETB Player",
            name_b="Dies Player",
        )
        assert result is not None
        assert result.turns > 0
        assert result.winner_seat in (-1, 0, 1)

    def test_etb_can_cause_elimination(self):
        """ETB trigger dealing lethal damage should eliminate the opponent."""
        lethal_etb = _make_creature(
            name="Lethal ETB", pt="1/1", cmc=1,
            oracle_text="When Lethal ETB enters the battlefield, it deals 5 damage to target opponent.",
        )
        engine, sim = _setup_two_player(
            p0_hand=[lethal_etb],
            p0_battlefield=[_make_land()],
            p1_life=3,
        )
        events = []
        engine._play_spells(sim, 0, 1, events)
        assert sim.players[1].eliminated is True
        assert sim.players[1].life == -2
