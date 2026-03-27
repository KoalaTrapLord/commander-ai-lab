"""
sim_insights.py
===============
Translates learned simulation weights (learned_weights.json) into concise
natural-language insight strings that can be injected into Ollama prompts.

This bridges the gap between the Monte Carlo engine's outcome-weighted
reinforcement learning and the LLM-driven deck builder: keywords that
statistically correlate with wins are surfaced to Ollama so it can
prioritize those card traits when suggesting and trimming cards.

Usage::

    from commander_ai_lab.deck_builder.api.sim_insights import get_sim_insights

    context = get_sim_insights()   # returns "" if no meaningful learning yet
    if context:
        prompt += f"\n\n{context}"

The function is intentionally safe to call when learned_weights.json does
not yet exist (load_weights() falls back to AI_DEFAULT_WEIGHTS silently),
and returns an empty string when no weight has drifted far enough from the
default to be worth mentioning — so existing prompt behaviour is unchanged
until there is real simulation data.
"""

from __future__ import annotations

import logging
from typing import Optional

from commander_ai_lab.sim.rules import AI_DEFAULT_WEIGHTS, load_weights

logger = logging.getLogger(__name__)

# Maps weight keys → human-readable MTG concepts shown to the LLM.
# Only keys the LLM can meaningfully act on are included.
_KEY_TO_CONCEPT: dict[str, str] = {
    "kw_flying":         "flying (evasion)",
    "kw_haste":          "haste",
    "kw_deathtouch":     "deathtouch",
    "kw_indestructible": "indestructible",
    "kw_doubleStrike":   "double strike",
    "kw_hexproof":       "hexproof",
    "kw_trample":        "trample",
    "kw_lifelink":       "lifelink",
    "kw_menace":         "menace",
    "kw_ward":           "ward",
    "kw_annihilator":    "annihilator",
    "kw_cascade":        "cascade",
    "spell_ramp":        "mana ramp spells",
    "spell_destroy":     "targeted removal",
    "spell_draw":        "card draw",
    "spell_counter":     "counterspells and board control",
    "trig_etb":          "enters-the-battlefield triggers",
    "trig_dies":         "death triggers",
    "trig_attack":       "attack triggers",
    "card_ptBonus":      "high power/toughness creatures",
}


def get_sim_insights(
    top_n: int = 6,
    threshold_delta: float = 0.05,
    weights_path: Optional[str] = None,
) -> str:
    """
    Return a concise insight paragraph for injecting into LLM prompts.

    Parameters
    ----------
    top_n:
        Maximum number of concepts to mention (avoids bloating the prompt).
    threshold_delta:
        Minimum absolute drift from the default weight before a concept
        is considered meaningful enough to report.  0.05 means a weight
        must have moved by at least 5% of its default before it matters.
    weights_path:
        Optional explicit path to learned_weights.json.  If None, the
        default location (``src/.../sim/learned_weights.json``) is used.

    Returns
    -------
    str
        A multi-line insight string ready to append to an LLM prompt, or
        an empty string if no meaningful learning is available yet.
    """
    try:
        learned = load_weights(weights_path)
    except Exception as exc:
        logger.warning("sim_insights: could not load weights: %s", exc)
        return ""

    deltas: dict[str, float] = {}
    for key, concept in _KEY_TO_CONCEPT.items():
        default_val = AI_DEFAULT_WEIGHTS.get(key, 0.0)
        learned_val = learned.get(key, default_val)
        delta = learned_val - default_val
        if abs(delta) >= threshold_delta:
            deltas[concept] = delta

    if not deltas:
        # No meaningful drift yet — don't inject noise into prompts
        return ""

    # Sort by magnitude, take top_n
    sorted_items = sorted(deltas.items(), key=lambda x: -abs(x[1]))[:top_n]
    boosted   = [c for c, d in sorted_items if d > 0]
    penalized = [c for c, d in sorted_items if d < 0]

    lines = [
        "[Simulation Insights] Data from thousands of Commander games in this lab suggests:",
    ]
    if boosted:
        lines.append(f"  - PRIORITIZE cards with: {', '.join(boosted)}")
    if penalized:
        lines.append(f"  - DEPRIORITIZE cards with: {', '.join(penalized)}")
    lines.append(
        "Use this to guide your selections where multiple options are otherwise comparable."
    )

    result = "\n".join(lines)
    logger.debug("sim_insights: injecting %d concept(s) into prompt", len(sorted_items))
    return result
