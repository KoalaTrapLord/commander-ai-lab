"""Tests for commander_ai_lab.sim.rules."""
import pytest
from commander_ai_lab.sim.models import Card
from commander_ai_lab.sim.rules import enrich_card, score_card, parse_decklist, AI_DEFAULT_WEIGHTS


# ── enrich_card ──────────────────────────────────────────────

class TestEnrichCardBasicLands:
    @pytest.mark.parametrize("name,expected_color", [
        ("Forest", "G"),
        ("Island", "U"),
        ("Plains", "W"),
        ("Swamp", "B"),
        ("Mountain", "R"),
    ])
    def test_basic_land_color(self, name, expected_color):
        c = Card(name=name)
        enrich_card(c)
        assert c.is_land() is True
        assert expected_color in c.oracle_text
        assert c.cmc == 0


class TestEnrichCardKnownCards:
    def test_sol_ring(self):
        c = Card(name="Sol Ring")
        enrich_card(c)
        assert c.is_ramp is True
        assert c.cmc == 1

    def test_murder(self):
        c = Card(name="Murder")
        enrich_card(c)
        assert c.is_removal is True
        assert c.cmc == 3

    def test_wrath_of_god(self):
        c = Card(name="Wrath of God")
        enrich_card(c)
        assert c.is_board_wipe is True

    def test_cultivate(self):
        c = Card(name="Cultivate")
        enrich_card(c)
        assert c.is_ramp is True
        assert c.cmc == 3

    def test_counterspell(self):
        c = Card(name="Counterspell")
        enrich_card(c)
        assert c.is_removal is True


class TestEnrichCardDeterministic:
    def test_same_unknown_card_same_cmc(self):
        """Unknown cards must get deterministic CMC (no random jitter)."""
        c1 = Card(name="Unknown Foobar Card")
        c2 = Card(name="Unknown Foobar Card")
        enrich_card(c1)
        enrich_card(c2)
        assert c1.cmc == c2.cmc
        assert c1.pt == c2.pt

    def test_different_unknown_cards_may_differ(self):
        c1 = Card(name="Aaaaa")
        c2 = Card(name="Zzzzz")
        enrich_card(c1)
        enrich_card(c2)
        # At minimum they are both valid creatures with cmc in [2,6]
        assert 2 <= c1.cmc <= 6
        assert 2 <= c2.cmc <= 6

    def test_unknown_card_cmc_range(self):
        for name in ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]:
            c = Card(name=name)
            enrich_card(c)
            assert 2 <= c.cmc <= 6


class TestEnrichCardPreservesExistingData:
    def test_real_data_not_overwritten(self):
        c = Card(name="Custom Card", type_line="Legendary Creature", cmc=7, pt="6/6")
        enrich_card(c)
        assert c.cmc == 7
        assert c.pt == "6/6"


class TestEnrichCardOracleFlags:
    def test_removal_flag_from_oracle(self):
        c = Card(name="Custom Removal", type_line="Instant", cmc=2,
                 oracle_text="Destroy target creature.")
        enrich_card(c)
        assert c.is_removal is True

    def test_board_wipe_flag_from_oracle(self):
        c = Card(name="Custom Wipe", type_line="Sorcery", cmc=5,
                 oracle_text="Destroy all creatures.")
        enrich_card(c)
        assert c.is_board_wipe is True

    def test_ramp_flag_from_oracle(self):
        c = Card(name="Custom Ramp", type_line="Sorcery", cmc=2,
                 oracle_text="Search your library for a basic land and put it onto the battlefield.")
        enrich_card(c)
        assert c.is_ramp is True


# ── score_card ───────────────────────────────────────────────

class TestScoreCard:
    def test_land_scores_lower_than_creature(self):
        land = Card(name="Forest", type_line="Basic Land — Forest", cmc=0)
        creature = Card(name="Grizzly Bears", type_line="Creature — Bear", cmc=2, pt="2/2")
        enrich_card(land)
        enrich_card(creature)
        # Creature with pt bonus should score higher than a plain land
        assert score_card(creature) > score_card(land)

    def test_flying_bonus(self):
        base = Card(name="Vanilla", type_line="Creature", cmc=3, pt="3/3")
        flyer = Card(name="Flyer", type_line="Creature", cmc=3, pt="3/3",
                     oracle_text="Flying", keywords=["Flying"])
        assert score_card(flyer) > score_card(base)

    def test_ramp_bonus(self):
        ramp = Card(name="Sol Ring", type_line="Artifact", cmc=1, is_ramp=True)
        plain = Card(name="Mox Nothing", type_line="Artifact", cmc=1)
        assert score_card(ramp) > score_card(plain)

    def test_removal_bonus(self):
        removal = Card(name="Murder", type_line="Instant", cmc=3, is_removal=True,
                       oracle_text="Destroy target creature.")
        plain = Card(name="Shock", type_line="Instant", cmc=1)
        assert score_card(removal) > score_card(plain)

    def test_multiplayer_scales_flying(self):
        flyer = Card(name="Flyer", type_line="Creature", cmc=3, pt="3/3",
                     oracle_text="Flying", keywords=["Flying"])
        score_1v1 = score_card(flyer, num_opponents=1)
        score_4p = score_card(flyer, num_opponents=3)
        assert score_4p > score_1v1

    def test_defender_penalty(self):
        defender = Card(name="Wall", type_line="Creature", cmc=2, pt="0/5",
                        oracle_text="Defender", keywords=["Defender"])
        vanilla = Card(name="Vanilla", type_line="Creature", cmc=2, pt="2/2")
        assert score_card(defender) < score_card(vanilla)

    def test_high_cmc_penalized(self):
        cheap = Card(name="Cheap", type_line="Creature", cmc=1, pt="1/1")
        expensive = Card(name="Expensive", type_line="Creature", cmc=8, pt="1/1")
        assert score_card(cheap) > score_card(expensive)


# ── parse_decklist ───────────────────────────────────────────

class TestParseDecklist:
    def test_numbered_entries(self):
        text = "4 Lightning Bolt\n2 Counterspell\n1 Black Lotus"
        cards = parse_decklist(text)
        assert len(cards) == 7
        assert cards[0].name == "Lightning Bolt"

    def test_unnumbered_entries(self):
        cards = parse_decklist("Lightning Bolt")
        assert len(cards) == 1
        assert cards[0].name == "Lightning Bolt"

    def test_skips_comments(self):
        text = "// This is a comment\n1 Sol Ring\n# Also a comment\n1 Forest"
        cards = parse_decklist(text)
        assert len(cards) == 2

    def test_skips_blank_lines(self):
        cards = parse_decklist("1 Sol Ring\n\n\n1 Forest")
        assert len(cards) == 2

    def test_returns_card_objects(self):
        cards = parse_decklist("1 Sol Ring")
        from commander_ai_lab.sim.models import Card
        assert isinstance(cards[0], Card)

    def test_empty_input(self):
        assert parse_decklist("") == []

    def test_multi_word_card_names(self):
        cards = parse_decklist("1 Kodama's Reach")
        assert cards[0].name == "Kodama's Reach"
