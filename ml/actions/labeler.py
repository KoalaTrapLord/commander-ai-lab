"""
Commander AI Lab — Action Labeler
═══════════════════════════════════
Maps raw Forge action records (from DecisionSnapshot JSONL)
to one of 8 macro-action labels for supervised policy learning.

Classification logic (updated):
  1. Check action.type for unambiguous types (attack, land, pass, hold,
     cast_commander)
  2. For "cast" actions:
     a. If action.card is present, match directly against name databases
     b. If action.card is absent (Forge omits it), scan the active
        player's hand against name databases to infer the cast type.
        Priority: removal > ramp > draw > commander > creature (default)
  3. Fallback: PASS

Macro-actions (from ml.config.scope):
  0: CAST_CREATURE    — Play a creature
  1: CAST_REMOVAL     — Cast removal / interaction
  2: CAST_DRAW        — Cast card-draw spell
  3: CAST_RAMP        — Cast ramp spell / mana rock
  4: CAST_COMMANDER   — Cast your commander
  5: ATTACK_OPPONENT  — Attack declaration
  6: HOLD_MANA        — Pass priority with mana open
  7: PASS             — Pass with nothing to do
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from ml.config.scope import (
    MacroAction, ACTION_TO_IDX, NUM_ACTIONS, ACTION_KEYWORDS,
)

logger = logging.getLogger("ml.labeler")


# ══════════════════════════════════════════════════════════
# Card Type Keyword Databases
# ══════════════════════════════════════════════════════════

REMOVAL_CARD_NAMES = {
    "swords to plowshares", "path to exile", "beast within", "chaos warp",
    "counterspell", "swan song", "negate", "arcane denial", "doomblade",
    "doom blade", "go for the throat", "terminate", "anguished unmaking",
    "vindicate", "generous gift", "rapid hybridization", "pongify",
    "cyclonic rift", "farewell", "toxic deluge", "blasphemous act",
    "wrath of god", "damnation", "supreme verdict", "vandalblast",
    "krosan grip", "nature's claim", "return to dust", "despark",
    "assassin's trophy", "abrupt decay", "force of will",
    "mana drain", "force of negation", "deflecting swat",
    "fierce guardianship", "deadly rollick", "snuff out",
    "murderous rider", "shriekmaw", "ravenous chupacabra",
    "bane of progress", "austere command", "merciless eviction",
    "decree of pain", "in garruk's wake", "plague wind",
    "fire covenant", "imprisoned in the moon", "darksteel mutation",
    "kenrith's transformation", "song of the dryads",
    "abrade", "disenchant", "naturalize", "wear", "tear",
    "shattering spree", "shatter", "smash to smithereens",
    "lightning bolt", "lightning helix", "condemn", "oust",
    "pongify", "reality shift", "turn to frog", "polymorph",
    "boros charm", "utter end", "anguished unmaking", "mortify",
    "putrefy", "maelstrom pulse", "void rend", "render silent",
    "overwhelming denial", "test of talents", "dispel", "spell pierce",
    "flusterstorm", "mental misstep", "pact of negation",
    "opposition agent", "hullbreacher", "narset parter of veils",
    "grafdigger's cage", "rest in peace", "leyline of the void",
    "tormod's crypt", "relic of progenitus",
}

DRAW_CARD_NAMES = {
    "rhystic study", "mystic remora", "phyrexian arena", "sylvan library",
    "harmonize", "blue sun's zenith", "pull from tomorrow",
    "windfall", "wheel of fortune", "timetwister", "brainstorm",
    "ponder", "preordain", "opt", "consider", "treasure cruise",
    "dig through time", "fact or fiction", "night's whisper",
    "sign in blood", "read the bones", "painful truths",
    "ambition's cost", "promise of power", "necropotence",
    "dark confidant", "toski bearer of secrets", "beast whisperer",
    "guardian project", "the great henge", "skullclamp",
    "esper sentinel", "archivist of oghma", "mind's eye",
    "consecrated sphinx", "ancient craving", "faithless looting",
    "cathartic reunion", "thrill of possibility", "jeska's will",
    "valakut awakening", "stinging study", "notion thief",
    "tymna the weaver", "shamanic revelation", "rishkar's expertise",
    "return of the wildspeaker", "garruk's uprising", "elemental bond",
    "kindred discovery", "coastal piracy", "reconnaissance mission",
    "bident of thassa", "distant melody", "slate of ancestry",
    "wheel of fate", "reforge the soul", "magus of the wheel",
    "river's rebuke", "prosperity", "intellectual offering",
    "peer into the abyss", "mind spring", "stroke of genius",
    "jace's ingenuity", "tidings", "concentrate", "divination",
    "inspiration", "counsel of the soratami", "accumulated knowledge",
    "predict", "pressure point", "quicken", "serum visions",
    "gitaxian probe", "mental note", "thought scour",
}

RAMP_CARD_NAMES = {
    "sol ring", "mana crypt", "mana vault", "arcane signet",
    "commander's sphere", "chromatic lantern", "fellwar stone",
    "mind stone", "thought vessel", "thran dynamo", "worn powerstone",
    "gilded lotus", "hedron archive", "everflowing chalice",
    "coalition relic", "prismatic lens",
    "cultivate", "kodama's reach", "rampant growth", "farseek",
    "nature's lore", "three visits", "skyshroud claim",
    "explosive vegetation", "migration path", "circuitous route",
    "tempt with discovery", "hour of promise", "boundless realms",
    "sakura-tribe elder", "wood elves", "farhaven elf",
    "solemn simulacrum", "burnished hart", "knight of the white orchid",
    "dockside extortionist", "smothering tithe", "black market",
    "cabal coffers", "nykthos shrine to nyx", "ancient tomb",
    "birds of paradise", "llanowar elves", "elvish mystic",
    "fyndhorn elves", "avacyn's pilgrim", "elves of deep shadow",
    "bloom tender", "priest of titania", "selvala heart of the wilds",
    "boreal druid", "green sun's zenith", "eternal witness",
    "reclamation sage", "mystic snake", "fierce empath",
    "signal the clans", "crop rotation", "harrow", "kodama's reach",
    "traverse the ulvenwald", "search for tomorrow", "primal growth",
    "land grant", "untamed wilds", "rangers path", "rangers' path",
    "nissa's pilgrimage", "forest grove", "grove of the burnwillows",
    "cabal stronghold", "urborg tomb of yawgmoth", "urborg, tomb of yawgmoth",
    "bojuka bog", "ghost quarter", "field of ruin", "strip mine",
    "wasteland", "tectonic edge", "dust bowl",
    "worn powerstone", "basalt monolith", "grim monolith",
    "mana geode", "darksteel ingot", "manalith", "opaline unicorn",
    "vessel of endless rest", "corrupted grafstone", "dreamstone hedron",
    "sisay's ring", "ur-golem's eye", "blinkmoth urn",
    "astral cornucopia", "druids' repository", "black market",
    "cryptolith rite", "earthcraft", "citanul hierophants",
    "zendikar resurgent", "mirari's wake", "mana reflection",
    "vorinclex voice of hunger", "vorinclex, voice of hunger",
}

# Partial-match prefixes (for cycles like Signets, Talismans)
RAMP_PARTIAL_PREFIXES = {
    "talisman", "signet", "locket", "banner", "obelisk",
    "keyrune", "cluestone", "monolith", "medallion",
}

DRAW_PARTIAL_PREFIXES = {
    "scroll", "tome", "journal",
}


# ══════════════════════════════════════════════════════════
# Core classification helpers
# ══════════════════════════════════════════════════════════

def _classify_card_name(name: str) -> Optional[MacroAction]:
    """
    Classify a single card name into a MacroAction, or None if unknown.

    Checks exact matches first, then partial prefix matches.
    Returns None for unrecognised cards (caller handles the default).
    """
    n = name.lower().strip()
    if not n:
        return None

    if n in REMOVAL_CARD_NAMES:
        return MacroAction.CAST_REMOVAL
    if n in DRAW_CARD_NAMES:
        return MacroAction.CAST_DRAW
    if n in RAMP_CARD_NAMES:
        return MacroAction.CAST_RAMP

    # Partial prefix match for cycles (Talismans, Signets, etc.)
    for prefix in RAMP_PARTIAL_PREFIXES:
        if n.startswith(prefix):
            return MacroAction.CAST_RAMP
    for prefix in DRAW_PARTIAL_PREFIXES:
        if n.startswith(prefix):
            return MacroAction.CAST_DRAW

    # Substring match (catches "Doom Blade" inside longer names etc.)
    for known in REMOVAL_CARD_NAMES:
        if known in n or n in known:
            return MacroAction.CAST_REMOVAL
    for known in DRAW_CARD_NAMES:
        if known in n or n in known:
            return MacroAction.CAST_DRAW
    for known in RAMP_CARD_NAMES:
        if known in n or n in known:
            return MacroAction.CAST_RAMP

    return None  # Unknown → caller defaults to CAST_CREATURE


def _classify_from_hand(
    players: list,
    active_seat: int,
    commander_names: Optional[set] = None,
) -> MacroAction:
    """
    Infer the cast action type by scanning the active player's hand.

    When action.card is absent (Forge omits it), the hand snapshot
    is the best available signal.  We scan all hand cards and return
    the highest-priority match:

        removal > ramp > draw > commander > creature (default)

    Priority rationale: Forge's AI plays the highest-impact available
    action, so if any removal/ramp/draw spell is in hand during a cast
    decision, it's the most likely card played.
    """
    if active_seat >= len(players):
        return MacroAction.CAST_CREATURE

    hand: List[str] = players[active_seat].get("hand", [])
    command_zone: List[str] = players[active_seat].get("command_zone", [])

    # Build commander name set from command_zone if not provided
    if commander_names is None:
        commander_names = {c.lower().strip() for c in command_zone if c}

    found_removal = False
    found_ramp = False
    found_draw = False
    found_commander = False

    for card in hand:
        card_lower = card.lower().strip()

        # Commander check: hand card matches a command zone card
        if card_lower in commander_names:
            found_commander = True
            continue

        result = _classify_card_name(card_lower)
        if result == MacroAction.CAST_REMOVAL:
            found_removal = True
        elif result == MacroAction.CAST_RAMP:
            found_ramp = True
        elif result == MacroAction.CAST_DRAW:
            found_draw = True

    # Return highest-priority found
    if found_removal:
        return MacroAction.CAST_REMOVAL
    if found_ramp:
        return MacroAction.CAST_RAMP
    if found_draw:
        return MacroAction.CAST_DRAW
    if found_commander:
        return MacroAction.CAST_COMMANDER
    return MacroAction.CAST_CREATURE


# ══════════════════════════════════════════════════════════
# Main label_action entry point
# ══════════════════════════════════════════════════════════

def label_action(decision: dict) -> int:
    """
    Classify a single decision snapshot's action into a macro-action index.

    Args:
        decision: Dict loaded from JSONL line

    Returns:
        Integer index into MacroAction enum (0-7)
    """
    action = decision.get("action", {})
    action_type = action.get("type", "").lower()
    card_name = (action.get("card", "") or "").lower().strip()

    players = decision.get("players", [])
    active_seat = decision.get("active_seat", 0)

    # ── Unambiguous direct-type matches ──────────────────────

    if action_type == "cast_commander":
        return ACTION_TO_IDX[MacroAction.CAST_COMMANDER]

    if action_type == "attack":
        return ACTION_TO_IDX[MacroAction.ATTACK_OPPONENT]

    # Land play → developing mana base = ramp
    if action_type == "land":
        return ACTION_TO_IDX[MacroAction.CAST_RAMP]

    # Pass / hold mana — check available mana to distinguish
    if action_type in ("pass", "hold"):
        if active_seat < len(players):
            mana = players[active_seat].get("mana", 0)
            if mana >= 2:
                return ACTION_TO_IDX[MacroAction.HOLD_MANA]
        return ACTION_TO_IDX[MacroAction.PASS]

    # ── Cast actions ──────────────────────────────────────

    if action_type == "cast":
        # Path A: action.card is present — classify it directly
        if card_name:
            result = _classify_card_name(card_name)
            if result is not None:
                return ACTION_TO_IDX[result]
            # Unrecognised named card → default creature
            return ACTION_TO_IDX[MacroAction.CAST_CREATURE]

        # Path B: action.card absent (Forge omits it) — infer from hand
        inferred = _classify_from_hand(players, active_seat)
        return ACTION_TO_IDX[inferred]

    # ── Fallback ──────────────────────────────────────────
    return ACTION_TO_IDX[MacroAction.PASS]


# ══════════════════════════════════════════════════════════
# File-level helpers
# ══════════════════════════════════════════════════════════

def label_decisions_file(jsonl_path: str) -> Tuple[np.ndarray, List[dict]]:
    """
    Label all decisions in a JSONL file.

    Returns:
        (labels, raw_decisions) where:
          labels: np.ndarray of shape (N,) with int action indices
          raw_decisions: list of original JSON dicts
    """
    labels = []
    raw = []

    with open(jsonl_path, "r") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                decision = json.loads(line)
                label = label_action(decision)
                labels.append(label)
                raw.append(decision)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Skipping line %d: %s", i, e)
                continue

    return np.array(labels, dtype=np.int64), raw


def print_label_distribution(labels: np.ndarray) -> Dict[str, int]:
    """Print and return the distribution of action labels.

    Iterates MacroAction enum in index order so the display always
    matches ACTION_TO_IDX regardless of dict insertion order.
    """
    dist = {}
    for action in MacroAction:
        idx = ACTION_TO_IDX[action]
        count = int(np.sum(labels == idx))
        dist[action.value] = count

    total = len(labels)
    logger.info(f"\n{'Action':<25} {'Count':>8} {'Pct':>8}")
    logger.info("─" * 43)
    # Sort descending by count for readability
    for action_name, count in sorted(dist.items(), key=lambda x: -x[1]):
        pct = (count / total * 100) if total > 0 else 0
        logger.info(f"  {action_name:<23} {count:>8} {pct:>7.1f}%")
    logger.info("─" * 43)
    logger.info(f"  {'TOTAL':<23} {total:>8}")

    return dist
