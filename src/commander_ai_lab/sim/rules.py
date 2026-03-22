"""
Commander AI Lab — Simulator Rules & Helpers
==============================================
AI weights, card enrichment heuristics, and scoring functions.
Ported from mtg-commander-lan JavaScript (AI_DEFAULT_WEIGHTS,
enrichCardForSim, headlessScoreCard, headlessGetPower/Toughness/HasKw).

N-player ready: score_card() accepts num_opponents so keyword weights
scale with pod size (e.g. Propaganda is worth more vs 3 opponents).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
    # Commander bonus
    "commander_bonus": 5.0,
}

_log = logging.getLogger(__name__)

# Default path for learned weights (written by ml/scripts/update_weights.py)
_LEARNED_WEIGHTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'learned_weights.json'
)


def load_weights(path: Optional[str] = None) -> dict[str, float]:
    """Load AI weights from a JSON file, falling back to AI_DEFAULT_WEIGHTS.

    If *path* is None the default ``learned_weights.json`` next to this
    module is checked.  If the file does not exist or is invalid the
    built-in defaults are returned silently.
    """
    fpath = path or _LEARNED_WEIGHTS_PATH
    if os.path.isfile(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                learned = json.load(f)
            if isinstance(learned, dict):
                merged = dict(AI_DEFAULT_WEIGHTS)
                merged.update(learned)
                _log.info('Loaded learned weights from %s (%d keys)', fpath, len(learned))
                return merged
        except Exception as exc:
            _log.warning('Failed to load learned weights from %s: %s', fpath, exc)
    return dict(AI_DEFAULT_WEIGHTS)


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
    Also sets combat flags (is_removal, is_ramp, is_board_wipe) from oracle text.
    Modifies the card in-place and returns it.
    """
    name_lower = (card.name or "").lower().strip()

    has_real_data = card.cmc > 0 or (card.type_line and len(card.type_line) > 5)

    if not has_real_data:
        # Basic lands
        if name_lower in _BASIC_LAND_COLORS:
            color = _BASIC_LAND_COLORS[name_lower]
            card.type_line = f"Basic Land - {card.name}"
            card.oracle_text = "{{T}}: Add {{{color}}}".format(color=color)
            card.cmc = 0
            _apply_oracle_flags(card)
            return card

        # Known card patterns
        for pattern, attrs in _KNOWN_CARDS:
            if pattern.search(card.name):
                for k, v in attrs.items():
                    setattr(card, k, v)
                _apply_oracle_flags(card)
                return card

        # Default: unknown cards get deterministic CMC based on card
        # name hash (fixes #32 — no more random.randint jitter).
        # Fix #82: do NOT default to "Creature". Unknown cards are
        # classified as "Unknown" and cannot attack/block until their
        # real type is confirmed via Scryfall data.
        if not card.type_line or len(card.type_line) < 3:
            name_hash = int(hashlib.md5(name_lower.encode()).hexdigest(), 16)
            estimated_cmc = (name_hash % 5) + 2          # 2-6 inclusive
            estimated_pow = max(1, estimated_cmc - 1)
            card.type_line = "Unknown"
            card.cmc = estimated_cmc
            card.pt = f"{estimated_pow}/{estimated_pow}"
            card.power = str(estimated_pow)
            card.toughness = str(estimated_pow)

    # Always apply oracle-text-based flags
    _apply_oracle_flags(card)
    return card


def _apply_oracle_flags(card: Card) -> None:
    """Set is_removal, is_ramp, is_board_wipe from oracle_text and type_line."""
    oracle = (card.oracle_text or "").lower()
    type_line = (card.type_line or "").lower()

    # Board wipes (skip if already set)
    if not card.is_board_wipe:
        if any(phrase in oracle for phrase in [
            "destroy all creature", "destroy all permanent",
            "all creatures get -", "exile all creature",
            "each creature gets -", "deals 13 damage to each creature",
        ]):
            card.is_board_wipe = True

    # Removal (skip if already set)
    if not card.is_removal:
        if any(phrase in oracle for phrase in [
            "destroy target", "exile target creature", "exile target permanent",
            "deals damage to target", "target creature gets -",
            "counter target spell", "return target",
        ]):
            card.is_removal = True

    # Bug 17 fix: evaluate ramp independently — cards can be both removal and ramp
    # (e.g. Nature's Claim, Beast Within, Abrupt Decay)
    if not card.is_ramp:
        if any(phrase in oracle for phrase in [
            "search your library for a basic land",
            "search your library for a land",
            "add one mana", "add {c}{c}", "add {c}",
            "add one mana of any color",
        ]) or (
            "land" in oracle and "onto the battlefield" in oracle
        ) or (
            "{t}: add" in oracle and "land" not in type_line
        ):
            card.is_ramp = True


# ── Multi-opponent scaling factors ────────────────────────────
# Keywords / effects that become more valuable in larger pods.
# Each entry maps a weight key → the extra bonus *per additional
# opponent* beyond 1.  1v1 uses base weights; 4-player FFA adds
# 3× the bonus for each matching keyword.
_MULTI_OPP_SCALING: dict[str, float] = {
    # Group-slug / pillowfort effects punish each opponent
    "kw_menace":       0.5,     # harder to block with more players
    "kw_flying":       0.3,     # evasion matters more in FFA
    "kw_hexproof":     0.5,     # more removal flying around
    "kw_indestructible": 0.5,
    "kw_ward":         0.4,
    # Multiplayer-relevant triggered abilities
    "trig_etb":        0.3,
    "trig_dies":       0.5,     # more creatures dying in FFA
    # Spells that scale with opponents
    "spell_destroy":   0.5,     # removal more precious
    "spell_draw":      0.3,     # card advantage matters more
    "spell_counter":   0.5,     # counters protect from more threats
}


def score_card(
    card: Card,
    weights: Optional[dict] = None,
    num_opponents: int = 1,
) -> float:
    """
    Score a card for AI play priority.

    Ported from headlessScoreCard() in app.js.  The optional
    *num_opponents* parameter (default 1 for 1v1) scales keywords
    that become more valuable in larger pods.
    """
    w = weights or AI_DEFAULT_WEIGHTS
    extra_opps = max(0, num_opponents - 1)   # 0 for 1v1
    cmc = card.cmc or 0
    score = 10.0 - cmc * w.get("card_baseCmcPenalty", 1.0)

    # ── Power / toughness bonus ──
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

    # ── Keyword / oracle-text scoring ──
    text = (card.oracle_text or "").lower()
    kw_list = [k.lower() for k in (card.keywords or [])]

    def _kw_bonus(keyword: str, weight_key: str, default: float) -> float:
        """Return base weight + per-extra-opponent scaling."""
        base = w.get(weight_key, default)
        multi = _MULTI_OPP_SCALING.get(weight_key, 0.0) * extra_opps
        return base + multi

    if "flying" in text or "flying" in kw_list:
        score += _kw_bonus("flying", "kw_flying", 2.5)
    if "deathtouch" in text or "deathtouch" in kw_list:
        score += _kw_bonus("deathtouch", "kw_deathtouch", 2.5)
    if "haste" in text or "haste" in kw_list:
        score += _kw_bonus("haste", "kw_haste", 2.5)
    if "trample" in text or "trample" in kw_list:
        score += _kw_bonus("trample", "kw_trample", 1.5)
    if "lifelink" in text or "lifelink" in kw_list:
        score += _kw_bonus("lifelink", "kw_lifelink", 1.5)
    if "double strike" in text or "double strike" in kw_list:
        score += _kw_bonus("double strike", "kw_doubleStrike", 3.0)
    if "first strike" in text or "first strike" in kw_list:
        score += _kw_bonus("first strike", "kw_firstStrike", 1.5)
    if "hexproof" in text or "hexproof" in kw_list:
        score += _kw_bonus("hexproof", "kw_hexproof", 2.0)
    if "indestructible" in text or "indestructible" in kw_list:
        score += _kw_bonus("indestructible", "kw_indestructible", 3.0)
    if "menace" in text or "menace" in kw_list:
        score += _kw_bonus("menace", "kw_menace", 1.5)
    if "vigilance" in text or "vigilance" in kw_list:
        score += w.get("kw_vigilance", 1.0)
    if "ward" in text or "ward" in kw_list:
        score += _kw_bonus("ward", "kw_ward", 1.5)
    if "infect" in text or "infect" in kw_list:
        score += w.get("kw_infect", 3.0)
    if "annihilator" in text:
        score += w.get("kw_annihilator", 4.0)
    if "cascade" in text or "cascade" in kw_list:
        score += w.get("kw_cascade", 3.0)
    if "defender" in text or "defender" in kw_list:
        score += w.get("kw_defender", -2.0)

    # ── Triggered ability bonuses ──
    if "when" in text and "enters" in text:
        score += w.get("trig_etb", 2.0) + _MULTI_OPP_SCALING.get("trig_etb", 0.0) * extra_opps
    if "whenever" in text and "attack" in text:
        score += w.get("trig_attack", 1.5)
    if "when" in text and "dies" in text:
        score += w.get("trig_dies", 1.0) + _MULTI_OPP_SCALING.get("trig_dies", 0.0) * extra_opps

    # ── Multiplayer-specific oracle patterns ──
    if extra_opps > 0:
        # "each opponent" effects scale linearly with opponent count
        if "each opponent" in text:
            score += 2.0 * extra_opps
        # Pillowfort (Propaganda, Ghostly Prison, etc.)
        if "attack you" in text and ("pay" in text or "tax" in text or "can't" in text):
            score += 1.5 * extra_opps
        # "each player" draw/damage effects
        if "each player" in text:
            score += 1.0 * extra_opps

    # ── Spell-type bonuses ──
    if card.is_ramp:
        score += w.get("spell_ramp", 6.0)
    if card.is_removal:
        score += _kw_bonus("removal", "spell_destroy", 5.0)
    if card.is_board_wipe:
        # Board wipes get better in multiplayer — more creatures to hit
        score += 1.0 * extra_opps
    if "draw" in text and ("card" in text or "cards" in text):
        score += w.get("spell_draw", 3.0) + _MULTI_OPP_SCALING.get("spell_draw", 0.0) * extra_opps
    if "counter target" in text:
        score += w.get("spell_counter", 4.0) + _MULTI_OPP_SCALING.get("spell_counter", 0.0) * extra_opps
    if "search your library" in text:
        score += w.get("spell_search", 2.0)

    # ── Commander bonus ──
    if card.is_commander:
        score += w.get("commander_bonus", 5.0)

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
