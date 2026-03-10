"""
Commander AI Lab — Action Labeler
═══════════════════════════════════
Maps raw Forge action records (from DecisionSnapshot JSONL)
to one of 8 macro-action labels for supervised policy learning.

Classification logic:
  1. Check action.type (cast, attack, land, cast_commander, pass)
  2. For "cast" actions, classify by card oracle text / card type keywords
  3. For ambiguous cases, use the raw log line and card name heuristics

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

# Known removal spells (partial list — expanded from common Commander staples)
REMOVAL_KEYWORDS = {
    "destroy", "exile", "sacrifice", "counter", "bounce", "return.*to.*hand",
    "-\\d+/-\\d+", "damage to", "fight", "deathtouch",
}
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
}

# Known draw spells
DRAW_KEYWORDS = {
    "draw", "scry", "look at the top", "reveal.*library",
    "search your library.*hand", "impulse", "brainstorm",
}
DRAW_CARD_NAMES = {
    "rhystic study", "mystic remora", "phyrexian arena", "sylvan library",
    "harmonize", "blue sun's zenith", "pull from tomorrow",
    "windfall", "wheel of fortune", "timetwister", "brainstorm",
    "ponder", "preordain", "opt", "consider", "treasure cruise",
    "dig through time", "fact or fiction", "nights whisper",
    "nights whisper", "sign in blood", "read the bones",
    "painful truths", "ambition's cost", "promise of power",
    "necropotence", "dark confidant", "toski bearer of secrets",
    "beast whisperer", "guardian project", "the great henge",
    "skullclamp", "esper sentinel", "archivist of oghma",
    "mind's eye", "consecrated sphinx", "ancient craving",
    "faithless looting", "cathartic reunion", "thrill of possibility",
    "jeska's will", "valakut awakening", "stinging study",
    "night's whisper", "notion thief", "tymna the weaver",
    "shamanic revelation", "rishkar's expertise", "return of the wildspeaker",
    "garruk's uprising", "elemental bond", "kindred discovery",
    "coastal piracy", "reconnaissance mission", "bident of thassa",
}

# Known ramp cards
RAMP_KEYWORDS = {
    "add {", "add one mana", "mana of any color",
    "land.*onto the battlefield", "search.*basic land.*battlefield",
}
RAMP_CARD_NAMES = {
    "sol ring", "mana crypt", "mana vault", "arcane signet",
    "commander's sphere", "chromatic lantern", "fellwar stone",
    "mind stone", "thought vessel", "thran dynamo", "worn powerstone",
    "gilded lotus", "hedron archive", "everflowing chalice",
    "coalition relic", "prismatic lens", "signets",  # catch-all partial
    "talisman",  # catch-all for talisman cycle
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
}

# Known creature-type indicators
CREATURE_KEYWORDS = {
    "creature", "token", "enters the battlefield",
}


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
    raw_line = (action.get("raw", "") or "").lower()

    # ── Direct type matching ────────────────────────────

    # Commander cast is unambiguous
    if action_type == "cast_commander":
        return ACTION_TO_IDX[MacroAction.CAST_COMMANDER]

    # Attack is unambiguous
    if action_type == "attack":
        return ACTION_TO_IDX[MacroAction.ATTACK_OPPONENT]

    # Land play → classify as CAST_RAMP (developing mana is ramp)
    if action_type == "land":
        return ACTION_TO_IDX[MacroAction.CAST_RAMP]

    # Pass / hold mana
    if action_type in ("pass", "hold"):
        # Check if player had mana open (from state)
        active_seat = decision.get("active_seat", 0)
        players = decision.get("players", [])
        if active_seat < len(players):
            mana = players[active_seat].get("mana", 0)
            if mana >= 2:
                return ACTION_TO_IDX[MacroAction.HOLD_MANA]
        return ACTION_TO_IDX[MacroAction.PASS]

    # ── Cast actions: classify by card identity ─────────

    if action_type == "cast":
        # 1. Check known card name databases
        if card_name in REMOVAL_CARD_NAMES or _partial_match(card_name, REMOVAL_CARD_NAMES):
            return ACTION_TO_IDX[MacroAction.CAST_REMOVAL]

        if card_name in DRAW_CARD_NAMES or _partial_match(card_name, DRAW_CARD_NAMES):
            return ACTION_TO_IDX[MacroAction.CAST_DRAW]

        if card_name in RAMP_CARD_NAMES or _partial_match(card_name, RAMP_CARD_NAMES):
            return ACTION_TO_IDX[MacroAction.CAST_RAMP]

        # 2. Check raw log line for keyword patterns
        for keyword in REMOVAL_KEYWORDS:
            if re.search(keyword, raw_line):
                return ACTION_TO_IDX[MacroAction.CAST_REMOVAL]

        for keyword in DRAW_KEYWORDS:
            if re.search(keyword, raw_line):
                return ACTION_TO_IDX[MacroAction.CAST_DRAW]

        for keyword in RAMP_KEYWORDS:
            if re.search(keyword, raw_line):
                return ACTION_TO_IDX[MacroAction.CAST_RAMP]

        # 3. Default: if it's a spell cast and not recognized, assume creature
        #    (most casts in Commander are creatures or creature-adjacent)
        return ACTION_TO_IDX[MacroAction.CAST_CREATURE]

    # ── Fallback ────────────────────────────────────────
    return ACTION_TO_IDX[MacroAction.PASS]


def _partial_match(name: str, name_set: set) -> bool:
    """Check if card name partially matches any name in the set."""
    for known in name_set:
        if known in name or name in known:
            return True
    return False


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
    """Print and return the distribution of action labels."""
    dist = {}
    for action in MacroAction:
        idx = ACTION_TO_IDX[action]
        count = int(np.sum(labels == idx))
        dist[action.value] = count

    total = len(labels)
    print(f"\n{'Action':<25} {'Count':>8} {'Pct':>8}")
    print("─" * 43)
    for action_name, count in sorted(dist.items(), key=lambda x: -x[1]):
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {action_name:<23} {count:>8} {pct:>7.1f}%")
    print(f"{'─' * 43}")
    print(f"  {'TOTAL':<23} {total:>8}")

    return dist
