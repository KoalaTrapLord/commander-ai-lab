"""
Commander AI Lab — Simulator Rules & Helpers
==============================================
AI weights, card enrichment heuristics, and scoring functions.
Ported from mtg-commander-lan JavaScript (AI_DEFAULT_WEIGHTS,
enrichCardForSim, headlessScoreCard, headlessGetPower/Toughness/HasKw).
"""

from __future__ import annotations

import re
import random
from typing import Optional

from commander_ai_lab.sim.models import Card


# ══════════════════════════════════════════════════════════════
# AI Weights (ported from AI_DEFAULT_WEIGHTS in app.js)
# ══════════════════════════════════════════════════════════════

AI_DEFAULT_WEIGHTS: dict[str, float] = {
    # Card scoring
    "card_baseCmcPenalty": 1.0,
    "card_ptBonus": 1.0,
    # Keyword weights
    "kw_flying": 2.5,
    "kw_haste": 2.5,
    "kw_deathtouch": 2.5,
    "kw_doubleStrike": 3.0,
    "kw_firstStrike": 1.5,
    "kw_lifelink": 1.5,
    "kw_trample": 1.5,
    "kw_hexproof": 2.0,
    "kw_indestructible": 3.0,
    "kw_menace": 1.5,
    "kw_vigilance": 1.0,
    "kw_reach": 0.5,
    "kw_infect": 3.0,
    "kw_toxic": 2.0,
    "kw_annihilator": 4.0,
    "kw_cascade": 3.0,
    "kw_undying": 2.0,
    "kw_persist": 2.0,
    "kw_prowess": 1.5,
    "kw_ward": 1.5,
    "kw_flash": 1.0,
    "kw_defender": -2.0,
    "kw_default": 0.5,
    # Triggered ability bonuses
    "trig_etb": 2.0,
    "trig_attack": 1.5,
    "trig_dies": 1.0,
    "trig_other": 0.5,
    # Activated ability bonus
    "activated_bonus": 1.0,
    # Spell type weights
    "spell_destroy": 5.0,
    "spell_draw": 3.0,
    "spell_counter": 4.0,
    "spell_graveyard": 2.0,
    "spell_search": 2.0,
    "spell_ramp": 6.0,
    "spell_equipment": 4.0,
    "spell_enchantment": 3.0,
    "spell_flash": 2.0,
    "spell_cascade": 3.0,
}


# ══════════════════════════════════════════════════════════════
# Card Enrichment — guess type/cost for cards without Scryfall data
# Ported from enrichCardForSim() in deck_tester_js.txt
# ══════════════════════════════════════════════════════════════

_BASIC_LAND_COLORS = {
    "plains": "W",
    "island": "U",
    "swamp": "B",
    "mountain": "R",
    "forest": "G",
}

_KNOWN_CARDS: list[tuple[re.Pattern, dict]] = [
    # Artifacts / ramp
    (re.compile(r"^sol ring$", re.I), {"type_line": "Artifact", "cmc": 1, "oracle_text": "{T}: Add {C}{C}", "is_ramp": True}),
    (re.compile(r"arcane signet|fellwar stone|talisman|signet", re.I), {"type_line": "Artifact", "cmc": 2, "oracle_text": "{T}: Add one mana", "is_ramp": True}),
    (re.compile(r"commander.?s sphere", re.I), {"type_line": "Artifact", "cmc": 3, "oracle_text": "{T}: Add one mana", "is_ramp": True}),
    # Instant removal
    (re.compile(r"swords to plowshares|path to exile", re.I), {"type_line": "Instant", "cmc": 1, "oracle_text": "Exile target creature.", "is_removal": True}),
    (re.compile(r"beast within|chaos warp|generous gift", re.I), {"type_line": "Instant", "cmc": 3, "oracle_text": "Destroy target permanent.", "is_removal": True}),
    (re.compile(r"murder|go for the throat|hero.?s downfall", re.I), {"type_line": "Instant", "cmc": 3, "oracle_text": "Destroy target creature.", "is_removal": True}),
    (re.compile(r"counterspell|negate|arcane denial", re.I), {"type_line": "Instant", "cmc": 2, "oracle_text": "Counter target spell.", "is_removal": True}),
    # Board wipes
    (re.compile(r"wrath of god|damnation|blasphemous act|day of judgment|farewell|toxic deluge", re.I), {"type_line": "Sorcery", "cmc": 4, "oracle_text": "Destroy all creatures.", "is_board_wipe": True}),
    # Ramp sorceries
    (re.compile(r"rampant growth|nature.?s lore", re.I), {"type_line": "Sorcery", "cmc": 2, "oracle_text": "Search your library for a basic land.", "is_ramp": True}),
    (re.compile(r"cultivate|kodama.?s reach", re.I), {"type_line": "Sorcery", "cmc": 3, "oracle_text": "Search your library for two basic lands.", "is_ramp": True}),
    (re.compile(r"farseek|three visits", re.I), {"type_line": "Sorcery", "cmc": 2, "oracle_text": "Search your library for a land.", "is_ramp": True}),
    # Draw
    (re.compile(r"harmonize|concentrate", re.I), {"type_line": "Sorcery", "cmc": 4, "oracle_text": "Draw three cards."}),
]


def enrich_card(card: Card) -> Card:
    """
    Enrich a card with type/cost heuristics if it lacks Scryfall data.
    Modifies the card in-place and returns it.
    """
    name_lower = (card.name or "").lower().strip()

    # Already enriched — has real data
    if card.cmc > 0 or (card.type_line and len(card.type_line) > 5):
        return card

    # Basic lands
    if name_lower in _BASIC_LAND_COLORS:
        color = _BASIC_LAND_COLORS[name_lower]
        card.type_line = f"Basic Land - {card.name}"
        card.oracle_text = "{{T}}: Add {{{color}}}".format(color=color)
        card.cmc = 0
        return card

    # Known card patterns
    for pattern, attrs in _KNOWN_CARDS:
        if pattern.search(card.name):
            for k, v in attrs.items():
                setattr(card, k, v)
            return card

    # Default: treat as creature with random CMC
    if not card.type_line or len(card.type_line) < 3:
        estimated_cmc = random.randint(2, 6)
        estimated_pow = max(1, estimated_cmc - 1)
        card.type_line = "Creature"
        card.cmc = estimated_cmc
        card.pt = f"{estimated_pow}/{estimated_pow}"
        card.power = str(estimated_pow)
        card.toughness = str(estimated_pow)

    return card


def score_card(card: Card, weights: Optional[dict] = None) -> float:
    """
    Score a card for AI play priority.
    Ported from headlessScoreCard() in app.js.
    """
    w = weights or AI_DEFAULT_WEIGHTS
    cmc = card.cmc or 0
    score = 10.0 - cmc * w.get("card_baseCmcPenalty", 1.0)

    if card.pt:
        parts = card.pt.split("/")
        try:
            p = int(parts[0])
        except (ValueError, IndexError):
            p = 0
        try:
            t = int(parts[1])
        except (ValueError, IndexError):
            t = 0
        score += (p + t) * w.get("card_ptBonus", 1.0)

    text = (card.oracle_text or "").lower()
    if "flying" in text:
        score += w.get("kw_flying", 2.5)
    if "deathtouch" in text:
        score += w.get("kw_deathtouch", 2.5)
    if "haste" in text:
        score += w.get("kw_haste", 2.5)
    if "trample" in text:
        score += w.get("kw_trample", 1.5)
    if "lifelink" in text:
        score += w.get("kw_lifelink", 1.5)

    if card.is_ramp:
        score += w.get("spell_ramp", 6.0)
    if card.is_removal:
        score += w.get("spell_destroy", 5.0)

    return score


def parse_decklist(text: str) -> list[Card]:
    """
    Parse a simple decklist (one per line: '1 Lightning Bolt' or 'Lightning Bolt').
    Returns a list of Card objects (not yet enriched).
    """
    cards: list[Card] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip()
        else:
            qty = 1
            name = line
        for _ in range(qty):
            cards.append(Card(name=name))
    return cards
