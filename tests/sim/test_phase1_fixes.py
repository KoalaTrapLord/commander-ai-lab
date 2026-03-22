"""
Phase 1 regression tests — BUG-01, BUG-02, BUG-05.

These tests verify the critical simulation fixes:
  BUG-01: Unknown cards no longer default to Creature; combat eligibility
          requires 'Creature' in type_line.
  BUG-02: get_legal_moves() and apply_move() produce real game actions.
  BUG-05: Instants and sorceries go to graveyard after resolution, not
          battlefield.
"""
import pytest

from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState
from commander_ai_lab.sim.rules import enrich_card
from commander_ai_lab.sim.engine import GameEngine
from commander_ai_lab.sim.game_state import (
    CommanderGameState,
    CommanderPlayer,
    ManaPool,
)


# ═══════════════════════════════════════════════════════════════
# BUG-01: Card type classification & combat eligibility
# ═══════════════════════════════════════════════════════════════


class TestBug01_EnrichCardNoDefaultCreature:
    """enrich_card() must NOT turn unknown cards into Creature."""

    def test_unknown_card_gets_unknown_type(self):
        """Card with no Scryfall data should be 'Unknown', not 'Creature'."""
        c = Card(name="Totally Made Up Card")
        enrich_card(c)
        assert c.type_line == "Unknown"
        assert c.is_creature() is False

    def test_unknown_card_deterministic_cmc(self):
        """Unknown cards still get deterministic CMC from hash."""
        c = Card(name="Totally Made Up Card")
        enrich_card(c)
        assert 2 <= c.cmc <= 6

    def test_artifact_sol_ring_stays_artifact(self):
        """Sol Ring (known card) should be Artifact, not Creature."""
        c = Card(name="Sol Ring")
        enrich_card(c)
        assert c.type_line == "Artifact"
        assert c.is_creature() is False
        assert c.is_ramp is True

    def test_arcane_signet_stays_artifact(self):
        c = Card(name="Arcane Signet")
        enrich_card(c)
        assert c.type_line == "Artifact"
        assert c.is_creature() is False

    def test_sorcery_cultivate_stays_sorcery(self):
        c = Card(name="Cultivate")
        enrich_card(c)
        assert c.type_line == "Sorcery"
        assert c.is_creature() is False

    def test_instant_murder_stays_instant(self):
        c = Card(name="Murder")
        enrich_card(c)
        assert c.type_line == "Instant"
        assert c.is_creature() is False

    def test_real_creature_preserved(self):
        """Card with real Scryfall Creature data should keep its type."""
        c = Card(name="Grizzly Bears", type_line="Creature — Bear",
                 cmc=2, pt="2/2")
        enrich_card(c)
        assert c.is_creature() is True
        assert c.type_line == "Creature — Bear"

    def test_artifact_creature_preserved(self):
        """Artifact Creature type_line should be preserved."""
        c = Card(name="Ornithopter", type_line="Artifact Creature — Thopter",
                 cmc=0, pt="0/2")
        enrich_card(c)
        assert c.is_creature() is True
        assert "artifact" in c.type_line.lower()

    def test_short_type_line_not_overwritten(self):
        """A real short type like 'Land' should NOT be replaced."""
        c = Card(name="Wastes", type_line="Land", cmc=0)
        enrich_card(c)
        # has_real_data is True because type_line is set and cmc=0 but len > 3
        assert c.type_line == "Land"


class TestBug01_CanAttackOrBlock:
    """can_attack_or_block() method enforces creature-only combat."""

    def test_creature_can_attack(self):
        c = Card(name="Hill Giant", type_line="Creature — Giant",
                 cmc=4, pt="3/3")
        assert c.can_attack_or_block() is True

    def test_artifact_cannot_attack(self):
        c = Card(name="Sol Ring", type_line="Artifact", cmc=1)
        assert c.can_attack_or_block() is False

    def test_enchantment_cannot_attack(self):
        c = Card(name="Rhystic Study", type_line="Enchantment", cmc=3)
        assert c.can_attack_or_block() is False

    def test_instant_cannot_attack(self):
        c = Card(name="Lightning Bolt", type_line="Instant", cmc=1)
        assert c.can_attack_or_block() is False

    def test_sorcery_cannot_attack(self):
        c = Card(name="Cultivate", type_line="Sorcery", cmc=3)
        assert c.can_attack_or_block() is False

    def test_unknown_type_cannot_attack(self):
        c = Card(name="Mystery", type_line="Unknown")
        assert c.can_attack_or_block() is False

    def test_empty_type_cannot_attack(self):
        c = Card(name="Nothing", type_line="")
        assert c.can_attack_or_block() is False

    def test_artifact_creature_can_attack(self):
        c = Card(name="Solemn Simulacrum",
                 type_line="Artifact Creature — Golem",
                 cmc=4, pt="2/2")
        assert c.can_attack_or_block() is True

    def test_legendary_creature_can_attack(self):
        c = Card(name="Korvold",
                 type_line="Legendary Creature — Dragon Noble",
                 cmc=5, pt="4/4")
        assert c.can_attack_or_block() is True

    def test_planeswalker_cannot_attack(self):
        c = Card(name="Jace", type_line="Legendary Planeswalker — Jace",
                 cmc=4)
        assert c.can_attack_or_block() is False


class TestBug01_CombatFiltering:
    """Engine combat only picks creatures, not artifacts/enchantments."""

    def _build_sim_with_battlefield(self, cards_p0, cards_p1=None):
        """Build a SimState with two players and specific battlefields."""
        sim = SimState(max_turns=25)
        p0 = Player(name="Alice", life=40, owner_id=0,
                     stats=PlayerStats(cards_drawn=7))
        p1 = Player(name="Bob", life=40, owner_id=1,
                     stats=PlayerStats(cards_drawn=7))
        sim.players = [p0, p1]
        sim.init_battlefields(2)
        cid = 90000
        for c in cards_p0:
            c.id = cid
            c.owner_id = 0
            c.tapped = False
            c.turn_played = 0  # played on turn 0, so eligible on turn 1+
            cid += 1
            sim.add_to_battlefield(0, c)
        for c in (cards_p1 or []):
            c.id = cid
            c.owner_id = 1
            c.tapped = False
            c.turn_played = 0
            cid += 1
            sim.add_to_battlefield(1, c)
        sim.next_card_id = cid
        return sim

    def test_artifact_does_not_attack(self):
        """Sol Ring on battlefield should not be selected as an attacker."""
        creature = Card(name="Hill Giant", type_line="Creature — Giant",
                        cmc=4, pt="3/3")
        artifact = Card(name="Sol Ring", type_line="Artifact", cmc=1)
        sim = self._build_sim_with_battlefield([creature, artifact])
        sim.turn = 1

        engine = GameEngine()
        events = []
        engine._resolve_combat(sim, 0, 1, events)

        # Hill Giant should have attacked, Sol Ring should not
        assert creature.tapped is True   # attacked
        assert artifact.tapped is False  # did NOT attack

    def test_enchantment_does_not_block(self):
        """Rhystic Study should not be selected as a blocker."""
        attacker = Card(name="Hill Giant", type_line="Creature — Giant",
                        cmc=4, pt="3/3")
        enchantment = Card(name="Rhystic Study", type_line="Enchantment",
                           cmc=3)
        blocker_creature = Card(name="Wall of Stone",
                                type_line="Creature — Wall",
                                cmc=3, pt="0/8")

        sim = self._build_sim_with_battlefield(
            [attacker],
            [enchantment, blocker_creature],
        )
        sim.turn = 1
        engine = GameEngine()
        events = []
        engine._resolve_combat(sim, 0, 1, events)

        # The enchantment should still be on the battlefield untouched
        bob_bf = sim.get_battlefield(1)
        enchantments = [c for c in bob_bf if c.name == "Rhystic Study"]
        assert len(enchantments) == 1


# ═══════════════════════════════════════════════════════════════
# BUG-02: get_legal_moves() and apply_move() implementation
# ═══════════════════════════════════════════════════════════════


class TestBug02_GetLegalMoves:
    """get_legal_moves() returns actual playable actions, not just pass."""

    def _make_cgs(self, hand=None, bf=None, phase="main1",
                  land_drop_used=False):
        """Build a CommanderGameState for testing."""
        sim = SimState(max_turns=25)
        p = Player(name="Alice", life=40, owner_id=0,
                   hand=hand or [], stats=PlayerStats(cards_drawn=7))
        sim.players = [p]
        sim.init_battlefields(1)
        cid = 90000
        for c in (bf or []):
            c.id = cid
            c.owner_id = 0
            c.tapped = False
            cid += 1
            sim.add_to_battlefield(0, c)
        sim.next_card_id = cid

        cgs = CommanderGameState.from_sim_state(sim)
        cgs.current_phase = phase
        cgs.land_drop_used = land_drop_used
        cgs.turn = 1
        return cgs

    def test_pass_always_available(self):
        cgs = self._make_cgs()
        moves = cgs.get_legal_moves(0)
        pass_moves = [m for m in moves if m["category"] == "pass_priority"]
        assert len(pass_moves) >= 1

    def test_land_in_hand_during_main_phase(self):
        land = Card(name="Forest", type_line="Basic Land — Forest", cmc=0)
        cgs = self._make_cgs(hand=[land], phase="main1")
        moves = cgs.get_legal_moves(0)
        land_moves = [m for m in moves if m["category"] == "play_land"]
        assert len(land_moves) == 1
        assert "Forest" in land_moves[0]["description"]

    def test_no_land_play_when_drop_used(self):
        land = Card(name="Forest", type_line="Basic Land — Forest", cmc=0)
        cgs = self._make_cgs(hand=[land], phase="main1", land_drop_used=True)
        moves = cgs.get_legal_moves(0)
        land_moves = [m for m in moves if m["category"] == "play_land"]
        assert len(land_moves) == 0

    def test_castable_spell_with_mana(self):
        spell = Card(name="Grizzly Bears", type_line="Creature — Bear",
                     cmc=2, pt="2/2")
        lands = [
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
        ]
        cgs = self._make_cgs(hand=[spell], bf=lands, phase="main1")
        moves = cgs.get_legal_moves(0)
        cast_moves = [m for m in moves if m["category"] == "cast_spell"]
        assert len(cast_moves) == 1
        assert "Grizzly Bears" in cast_moves[0]["description"]

    def test_spell_too_expensive(self):
        spell = Card(name="Big Creature", type_line="Creature", cmc=5,
                     pt="5/5")
        lands = [Card(name="Forest", type_line="Basic Land", cmc=0)]
        cgs = self._make_cgs(hand=[spell], bf=lands, phase="main1")
        moves = cgs.get_legal_moves(0)
        cast_moves = [m for m in moves if m["category"] == "cast_spell"]
        assert len(cast_moves) == 0

    def test_no_spells_during_combat(self):
        spell = Card(name="Grizzly Bears", type_line="Creature — Bear",
                     cmc=2, pt="2/2")
        lands = [
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
        ]
        cgs = self._make_cgs(hand=[spell], bf=lands,
                              phase="declare_attackers")
        moves = cgs.get_legal_moves(0)
        cast_moves = [m for m in moves if m["category"] == "cast_spell"]
        assert len(cast_moves) == 0

    def test_attack_move_with_creatures(self):
        creature = Card(name="Hill Giant", type_line="Creature — Giant",
                        cmc=4, pt="3/3", turn_played=0)
        cgs = self._make_cgs(bf=[creature], phase="declare_attackers")
        moves = cgs.get_legal_moves(0)
        atk_moves = [m for m in moves if m["category"] == "attack"]
        assert len(atk_moves) == 1

    def test_no_attack_without_creatures(self):
        artifact = Card(name="Sol Ring", type_line="Artifact", cmc=1)
        cgs = self._make_cgs(bf=[artifact], phase="declare_attackers")
        moves = cgs.get_legal_moves(0)
        atk_moves = [m for m in moves if m["category"] == "attack"]
        assert len(atk_moves) == 0

    def test_instant_available_during_response_phase(self):
        instant = Card(name="Swords to Plowshares", type_line="Instant",
                       cmc=1, oracle_text="Exile target creature.")
        lands = [Card(name="Plains", type_line="Basic Land — Plains", cmc=0)]
        cgs = self._make_cgs(hand=[instant], bf=lands, phase="end_step")
        moves = cgs.get_legal_moves(0)
        instant_moves = [m for m in moves if m["category"] == "instant"]
        assert len(instant_moves) == 1


class TestBug02_ApplyMove:
    """apply_move() properly executes game actions."""

    def _make_cgs(self, hand=None, bf=None, phase="main1",
                  land_drop_used=False):
        sim = SimState(max_turns=25)
        p = Player(name="Alice", life=40, owner_id=0,
                   hand=hand or [], stats=PlayerStats(cards_drawn=7))
        sim.players = [p]
        sim.init_battlefields(1)
        cid = 90000
        for c in (bf or []):
            c.id = cid
            c.owner_id = 0
            c.tapped = False
            cid += 1
            sim.add_to_battlefield(0, c)
        sim.next_card_id = cid

        cgs = CommanderGameState.from_sim_state(sim)
        cgs.current_phase = phase
        cgs.land_drop_used = land_drop_used
        cgs.turn = 1
        return cgs

    def test_play_land_moves_to_battlefield(self):
        land = Card(name="Forest", type_line="Basic Land — Forest", cmc=0)
        cgs = self._make_cgs(hand=[land], phase="main1")

        moves = cgs.get_legal_moves(0)
        land_move = next(m for m in moves if m["category"] == "play_land")
        cgs.apply_move(0, land_move["id"])

        bf = cgs.sim_state.get_battlefield(0)
        assert any(c.name == "Forest" for c in bf)
        assert len(cgs.commander_players[0].base.hand) == 0
        assert cgs.land_drop_used is True

    def test_cast_creature_to_battlefield(self):
        creature = Card(name="Grizzly Bears", type_line="Creature — Bear",
                        cmc=2, pt="2/2")
        lands = [
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
        ]
        cgs = self._make_cgs(hand=[creature], bf=lands, phase="main1")

        moves = cgs.get_legal_moves(0)
        cast_move = next(m for m in moves if m["category"] == "cast_spell")
        cgs.apply_move(0, cast_move["id"])

        bf = cgs.sim_state.get_battlefield(0)
        creature_on_bf = [c for c in bf if c.name == "Grizzly Bears"]
        assert len(creature_on_bf) == 1

    def test_cast_sorcery_goes_to_graveyard(self):
        sorcery = Card(name="Cultivate", type_line="Sorcery", cmc=3,
                       oracle_text="Search your library for two basic lands.")
        lands = [
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
            Card(name="Forest", type_line="Basic Land — Forest", cmc=0),
        ]
        cgs = self._make_cgs(hand=[sorcery], bf=lands, phase="main1")

        moves = cgs.get_legal_moves(0)
        cast_move = next(m for m in moves if m["category"] == "cast_spell")
        cgs.apply_move(0, cast_move["id"])

        bf = cgs.sim_state.get_battlefield(0)
        sorceries_on_bf = [c for c in bf if c.name == "Cultivate"]
        assert len(sorceries_on_bf) == 0, "Sorcery should NOT be on battlefield"

        gy = cgs.commander_players[0].base.graveyard
        assert any(c.name == "Cultivate" for c in gy), \
            "Sorcery should be in graveyard"

    def test_pass_priority_is_noop(self):
        cgs = self._make_cgs(phase="main1")
        moves = cgs.get_legal_moves(0)
        pass_move = next(m for m in moves if m["category"] == "pass_priority")
        # Should not raise
        cgs.apply_move(0, pass_move["id"])


# ═══════════════════════════════════════════════════════════════
# BUG-05: Instants/sorceries should not remain on the battlefield
# ═══════════════════════════════════════════════════════════════


class TestBug05_SpellResolution:
    """Instants and sorceries are routed to graveyard, not battlefield."""

    def test_is_permanent_creature(self):
        c = Card(name="Bear", type_line="Creature — Bear")
        assert c.is_permanent() is True

    def test_is_permanent_artifact(self):
        c = Card(name="Sol Ring", type_line="Artifact")
        assert c.is_permanent() is True

    def test_is_permanent_enchantment(self):
        c = Card(name="Rhystic Study", type_line="Enchantment")
        assert c.is_permanent() is True

    def test_is_not_permanent_instant(self):
        c = Card(name="Lightning Bolt", type_line="Instant")
        assert c.is_permanent() is False

    def test_is_not_permanent_sorcery(self):
        c = Card(name="Cultivate", type_line="Sorcery")
        assert c.is_permanent() is False

    def test_engine_sorcery_not_on_battlefield(self):
        """A non-removal, non-wipe sorcery cast via engine goes to graveyard."""
        # Build a deck with a draw sorcery (Harmonize) and lots of lands
        harmonize = Card(name="Harmonize")
        enrich_card(harmonize)
        assert harmonize.type_line == "Sorcery"

        # Build mini sim state
        sim = SimState(max_turns=25)
        p0 = Player(name="Alice", life=40, owner_id=0,
                     hand=[harmonize],
                     stats=PlayerStats(cards_drawn=7))
        sim.players = [p0, Player(name="Bob", life=40, owner_id=1,
                                  stats=PlayerStats(cards_drawn=7))]
        sim.init_battlefields(2)

        # Give Alice 5 untapped lands on battlefield
        cid = 90000
        for i in range(5):
            land = Card(name="Forest", type_line="Basic Land — Forest",
                        cmc=0, id=cid, owner_id=0, tapped=False)
            cid += 1
            sim.add_to_battlefield(0, land)
        sim.next_card_id = cid

        engine = GameEngine()
        engine._play_spells(sim, 0, 5)

        # Harmonize should NOT be on the battlefield
        bf = sim.get_battlefield(0)
        sorceries = [c for c in bf if c.name == "Harmonize"]
        assert len(sorceries) == 0, "Sorcery should not stay on battlefield"

        # It should be in the graveyard
        assert any(c.name == "Harmonize" for c in p0.graveyard), \
            "Sorcery should be in graveyard after resolution"

    def test_engine_artifact_stays_on_battlefield(self):
        """An artifact (permanent) should stay on battlefield after being cast."""
        sol_ring = Card(name="Sol Ring")
        enrich_card(sol_ring)

        sim = SimState(max_turns=25)
        p0 = Player(name="Alice", life=40, owner_id=0,
                     hand=[sol_ring],
                     stats=PlayerStats(cards_drawn=7))
        sim.players = [p0, Player(name="Bob", life=40, owner_id=1,
                                  stats=PlayerStats(cards_drawn=7))]
        sim.init_battlefields(2)

        cid = 90000
        for i in range(2):
            land = Card(name="Forest", type_line="Basic Land — Forest",
                        cmc=0, id=cid, owner_id=0, tapped=False)
            cid += 1
            sim.add_to_battlefield(0, land)
        sim.next_card_id = cid

        engine = GameEngine()
        engine._play_spells(sim, 0, 2)

        bf = sim.get_battlefield(0)
        artifacts = [c for c in bf if c.name == "Sol Ring"]
        assert len(artifacts) == 1, "Artifact should remain on battlefield"


class TestBug05_IsInstantAndSorcery:
    """Card.is_instant() and is_sorcery() helpers."""

    def test_instant_detected(self):
        c = Card(name="Bolt", type_line="Instant")
        assert c.is_instant() is True
        assert c.is_sorcery() is False

    def test_sorcery_detected(self):
        c = Card(name="Wrath", type_line="Sorcery")
        assert c.is_sorcery() is True
        assert c.is_instant() is False

    def test_creature_not_instant_or_sorcery(self):
        c = Card(name="Bear", type_line="Creature — Bear")
        assert c.is_instant() is False
        assert c.is_sorcery() is False

    def test_empty_type_line(self):
        c = Card(name="?")
        assert c.is_instant() is False
        assert c.is_sorcery() is False


# ═══════════════════════════════════════════════════════════════
# Integration: full game still runs with all fixes applied
# ═══════════════════════════════════════════════════════════════


class TestIntegration:
    """Sanity check that a full game can still run with all fixes."""

    def _make_deck(self, size=60):
        """Build a test deck with mixed card types."""
        cards = []
        # 24 lands
        for _ in range(24):
            c = Card(name="Forest")
            enrich_card(c)
            cards.append(c)
        # 15 creatures (with real type data)
        for _ in range(15):
            c = Card(name="Grizzly Bears", type_line="Creature — Bear",
                     cmc=2, pt="2/2")
            enrich_card(c)
            cards.append(c)
        # 5 removal instants
        for _ in range(5):
            c = Card(name="Murder")
            enrich_card(c)
            cards.append(c)
        # 3 board wipes
        for _ in range(3):
            c = Card(name="Wrath of God")
            enrich_card(c)
            cards.append(c)
        # 5 artifacts (ramp)
        for _ in range(5):
            c = Card(name="Sol Ring")
            enrich_card(c)
            cards.append(c)
        # 3 ramp sorceries
        for _ in range(3):
            c = Card(name="Cultivate")
            enrich_card(c)
            cards.append(c)
        # 5 unknown cards (should be "Unknown" type, not creatures)
        for i in range(5):
            c = Card(name=f"Mystery Card {i}")
            enrich_card(c)
            cards.append(c)
        return cards

    def test_full_game_completes(self):
        """A 2-player game with mixed deck should complete without errors."""
        engine = GameEngine(max_turns=25)
        deck_a = self._make_deck()
        deck_b = self._make_deck()
        result = engine.run(
            [c.clone() for c in deck_a],
            [c.clone() for c in deck_b],
            name_a="Alice",
            name_b="Bob",
        )
        assert result is not None
        assert result.turns > 0
        assert result.winner_seat in (-1, 0, 1)

    def test_no_artifacts_in_combat_log(self):
        """With record_log, no artifact names should appear in attack events."""
        engine = GameEngine(max_turns=10, record_log=True)
        deck_a = self._make_deck()
        deck_b = self._make_deck()
        result = engine.run(
            [c.clone() for c in deck_a],
            [c.clone() for c in deck_b],
            name_a="Alice",
            name_b="Bob",
        )
        for turn_entry in result.game_log:
            for phase in turn_entry.get("phases", []):
                for event in phase.get("events", []):
                    if "Attacks" in event:
                        assert "Sol Ring" not in event, \
                            f"Sol Ring should not attack: {event}"

    def test_unknown_cards_not_in_combat(self):
        """Unknown-type cards should not appear in attack event logs."""
        engine = GameEngine(max_turns=10, record_log=True)
        deck_a = self._make_deck()
        deck_b = self._make_deck()
        result = engine.run(
            [c.clone() for c in deck_a],
            [c.clone() for c in deck_b],
            name_a="Alice",
            name_b="Bob",
        )
        for turn_entry in result.game_log:
            for phase in turn_entry.get("phases", []):
                for event in phase.get("events", []):
                    if "Attacks" in event:
                        assert "Mystery Card" not in event, \
                            f"Unknown card should not attack: {event}"
