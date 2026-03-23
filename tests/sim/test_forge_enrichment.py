"""Tests for Forge card enrichment -- parser, enrich_card(), and score_card()."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from commander_ai_lab.sim.models import Card
from commander_ai_lab.sim.rules import enrich_card, score_card


FORGE_BASIC = textwrap.dedent("""\
    Name:Elvish Mystic
    ManaCost:G
    Types:Creature Elf Druid
    PT:1/1
    Oracle:{T}: Add {G}.
""")

FORGE_ETB = textwrap.dedent("""\
    Name:Llanowar Elves
    ManaCost:G
    Types:Creature Elf Druid
    PT:1/1
    T:Mode$ChangesZone $ Origin$Graveyard $ Destination$Battlefield
""")

FORGE_KEYWORDS = textwrap.dedent("""\
    Name:Serra Angel
    ManaCost:3 W W
    Types:Creature Angel
    PT:4/4
    K:Flying
    K:Vigilance
""")

FORGE_STATIC = textwrap.dedent("""\
    Name:Glorious Anthem
    ManaCost:1 W W
    Types:Enchantment
    S:Mode$Continuous $ Affected$Creature.YouCtrl
""")

FORGE_REPLACEMENT = textwrap.dedent("""\
    Name:Leyline of the Void
    ManaCost:2 B B
    Types:Enchantment
    R:Mode$ReplaceEvent $ Event$MovedToGraveyard
""")


# -- Parser unit tests --

class TestParseForgeFile:
    def _parse(self, txt: str, tmp_path: Path):
        from commander_ai_lab.sim.forge_card_loader import _parse_forge_file
        fpath = tmp_path / "card.txt"
        fpath.write_text(txt, encoding="utf-8")
        return _parse_forge_file(fpath)

    def test_basic_fields(self, tmp_path):
        d = self._parse(FORGE_BASIC, tmp_path)
        assert d.name == "Elvish Mystic"
        assert d.cmc == 1
        assert d.pt == "1/1"
        assert "{T}: Add {G}" in d.oracle_text

    def test_keywords_parsed(self, tmp_path):
        d = self._parse(FORGE_KEYWORDS, tmp_path)
        assert "Flying" in d.keywords and "Vigilance" in d.keywords

    def test_cmc_generic_plus_colored(self, tmp_path):
        d = self._parse(FORGE_KEYWORDS, tmp_path)
        assert d.cmc == 5  # 3 + W + W

    def test_etb_trigger_mode(self, tmp_path):
        d = self._parse(FORGE_ETB, tmp_path)
        assert "ChangesZone" in d.trigger_modes

    def test_static_flag(self, tmp_path):
        d = self._parse(FORGE_STATIC, tmp_path)
        assert d.has_static_ability is True
        assert d.has_replacement_effect is False

    def test_replacement_flag(self, tmp_path):
        d = self._parse(FORGE_REPLACEMENT, tmp_path)
        assert d.has_replacement_effect is True

    def test_empty_file_returns_none(self, tmp_path):
        from commander_ai_lab.sim.forge_card_loader import _parse_forge_file
        fpath = tmp_path / "empty.txt"
        fpath.write_text("", encoding="utf-8")
        assert _parse_forge_file(fpath) is None


# -- enrich_card() integration tests --

class TestEnrichCardForge:
    def _forge(self, **kwargs):
        from commander_ai_lab.sim.forge_card_loader import ForgeCardData
        base = dict(
            name="X", mana_cost="2 G", cmc=3, type_line="Creature Elf",
            oracle_text="", pt="2/2", keywords=["Flying"],
            trigger_modes=[], has_replacement_effect=False,
            has_static_ability=False,
        )
        base.update(kwargs)
        return ForgeCardData(**base)

    def test_forge_applied_to_empty_card(self):
        card = Card(name="X")
        with patch("commander_ai_lab.sim.rules.lookup_forge_card", return_value=self._forge()):
            r = enrich_card(card)
        assert r.forge_enriched and r.cmc == 3 and r.power == "2"
        assert "Flying" in r.keywords

    def test_skipped_when_has_real_data(self):
        card = Card(name="Sol Ring", cmc=1, type_line="Artifact")
        with patch("commander_ai_lab.sim.rules.lookup_forge_card") as m:
            enrich_card(card)
        m.assert_not_called()

    def test_miss_falls_through_to_known_cards(self):
        card = Card(name="Sol Ring")
        with patch("commander_ai_lab.sim.rules.lookup_forge_card", return_value=None):
            r = enrich_card(card)
        assert r.type_line == "Artifact" and r.is_ramp is True

    def test_oracle_flags_from_forge_text(self):
        card = Card(name="X")
        fd = self._forge(oracle_text="Destroy target creature.", keywords=[])
        with patch("commander_ai_lab.sim.rules.lookup_forge_card", return_value=fd):
            r = enrich_card(card)
        assert r.is_removal is True

    def test_no_duplicate_keywords(self):
        card = Card(name="X", keywords=["Flying"])
        fd = self._forge(keywords=["Flying", "Haste"])
        with patch("commander_ai_lab.sim.rules.lookup_forge_card", return_value=fd):
            r = enrich_card(card)
        assert sum(1 for k in r.keywords if k.lower() == "flying") == 1
        assert any(k.lower() == "haste" for k in r.keywords)


# -- score_card() trigger detection tests --

class TestScoreCardForge:
    def test_etb_via_forge_mode_equals_text_detection(self):
        forge = Card(name="A", type_line="Creature", cmc=3, pt="3/3",
                     forge_trigger_modes=["ChangesZone"])
        text = Card(name="B", type_line="Creature", cmc=3, pt="3/3",
                    oracle_text="When this enters the battlefield, gain 1 life.")
        none = Card(name="C", type_line="Creature", cmc=3, pt="3/3")
        sf, st, sn = score_card(forge), score_card(text), score_card(none)
        assert sf > sn and abs(sf - st) < 0.01

    def test_attack_trig_via_forge_mode(self):
        forge = Card(name="A", type_line="Creature", cmc=3, pt="3/3",
                     forge_trigger_modes=["Attacks"])
        none = Card(name="B", type_line="Creature", cmc=3, pt="3/3")
        assert score_card(forge) > score_card(none)
