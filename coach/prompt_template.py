"""
Commander AI Lab — Coach Prompt Template
════════════════════════════════════════
Constructs system and user prompts for the LLM coach.
Injects deck report data, underperformer analysis, and
candidate replacement cards into a structured template.
"""

import json
from typing import List, Dict, Optional

from .models import DeckReport, CoachGoals, CardPerformance
from .config import MAX_CANDIDATES_PER_UNDERPERFORMER, MAX_UNDERPERFORMERS


# ══════════════════════════════════════════════════════════════
# System Prompt
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT_TEMPLATE = """You are an expert Magic: The Gathering Commander deck coach.
You analyze deck performance reports from simulation data and provide specific,
actionable suggestions to improve deck construction.

RULES:
- NEVER suggest cutting the commander ({commander}).
- Only suggest cards within the deck's color identity: {color_identity}.
- Base suggestions on the simulation data provided, not general "goodstuff" advice.
- Consider mana curve, role balance (ramp, draw, removal, threats), and synergy.
- When suggesting replacements, prefer cards that fill the same functional role.
{goals_section}

You MUST respond ONLY with valid JSON matching this exact structure:
{{
  "summary": "2-3 sentence overview of the deck's strengths and weaknesses",
  "suggestedCuts": [
    {{
      "cardName": "Card To Remove",
      "reason": "Why this card underperforms",
      "replacementOptions": ["Better Card 1", "Better Card 2"]
    }}
  ],
  "suggestedAdds": [
    {{
      "cardName": "Card To Add",
      "role": "ramp|draw|removal|threat|utility|combo|protection",
      "reason": "Why this card improves the deck",
      "synergyWith": ["Card In Deck 1", "Card In Deck 2"]
    }}
  ],
  "heuristicHints": [
    "Concise strategic tip based on data"
  ],
  "manaBaseAdvice": "Specific mana base improvement suggestion or null",
  "rawTextExplanation": "Detailed paragraph explaining the analysis and reasoning"
}}

Do NOT include any text outside the JSON object. No markdown fences, no preamble."""


# ══════════════════════════════════════════════════════════════
# User Prompt Builder
# ══════════════════════════════════════════════════════════════

USER_PROMPT_TEMPLATE = """## Deck Report: {deck_name}
Commander: {commander}
Color Identity: {color_identity}
Games Simulated: {games_simulated}
Overall Win Rate: {win_rate:.1%}
Avg Game Length: {avg_game_length:.1f} turns

### Deck Structure
- Lands: {land_count}
- Mana Curve: {curve_summary}
- Card Types: {type_summary}
- Functional Roles: {role_summary}

### Matchup Data
{matchup_section}

### Top Performing Cards (by Impact Score)
{top_cards}

### Underperforming Cards (candidates for cuts)
{underperformer_section}

### Candidate Replacement Cards (from embeddings search)
{candidate_section}

{combo_section}
Based on this simulation data, provide your coaching suggestions."""


def _format_goals_section(goals: Optional[CoachGoals]) -> str:
    """Format goals into system prompt rules."""
    if not goals:
        return "- Aim for a balanced, well-rounded deck."

    lines = []
    if goals.targetPowerLevel is not None:
        lines.append(f"- Target power level: {goals.targetPowerLevel}/10.")
        if goals.targetPowerLevel <= 4:
            lines.append("- Keep suggestions casual and fun-focused.")
        elif goals.targetPowerLevel >= 8:
            lines.append("- Prioritize efficiency and competitive staples.")
    if goals.metaFocus:
        lines.append(f"- Optimize for a {goals.metaFocus} strategy.")
    if goals.budget:
        budget_map = {"budget": "under $5 per card", "medium": "under $20 per card",
                      "no-limit": "no budget restrictions"}
        lines.append(f"- Budget constraint: {budget_map.get(goals.budget, goals.budget)}.")
    if goals.focusAreas:
        lines.append(f"- Focus improvement on: {', '.join(goals.focusAreas)}.")
    return "\n".join(lines) if lines else "- Aim for a balanced, well-rounded deck."


def _format_curve(buckets: List[int]) -> str:
    """Format mana curve buckets as a readable string."""
    labels = ["0", "1", "2", "3", "4", "5", "6", "7+"]
    parts = [f"{labels[i]}={buckets[i]}" for i in range(min(len(buckets), 8)) if buckets[i] > 0]
    return ", ".join(parts) if parts else "unknown"


def _format_top_cards(cards: List[CardPerformance], top_n: int = 10) -> str:
    """Format the best performing cards."""
    sorted_cards = sorted(cards, key=lambda c: c.impactScore, reverse=True)
    lines = []
    for c in sorted_cards[:top_n]:
        tags = f" [{', '.join(c.tags)}]" if c.tags else ""
        lines.append(f"- {c.name}: impact={c.impactScore:.3f}, "
                     f"castRate={c.castRate:.1%}, drawnRate={c.drawnRate:.1%}{tags}")
    return "\n".join(lines) if lines else "No card performance data available."


def _format_underperformers(cards: List[CardPerformance],
                            underperformer_names: List[str]) -> str:
    """Format underperforming cards with their stats."""
    card_map = {c.name: c for c in cards}
    lines = []
    for name in underperformer_names[:MAX_UNDERPERFORMERS]:
        c = card_map.get(name)
        if c:
            lines.append(f"- {c.name}: impact={c.impactScore:.3f}, "
                         f"deadCardRate={c.deadCardRate:.1%}, "
                         f"castRate={c.castRate:.1%}, "
                         f"clunkiness={c.clunkinessScore:.3f}")
        else:
            lines.append(f"- {name}: (no detailed stats)")
    return "\n".join(lines) if lines else "No clear underperformers identified."


def _format_candidates(candidates: Dict[str, List[dict]]) -> str:
    """Format replacement candidates grouped by the card they'd replace."""
    if not candidates:
        return "No candidate replacements found."

    lines = []
    for underperformer, replacements in list(candidates.items())[:MAX_UNDERPERFORMERS]:
        lines.append(f"\nReplacements for '{underperformer}':")
        for r in replacements[:MAX_CANDIDATES_PER_UNDERPERFORMER]:
            name = r.get("name", "Unknown")
            types = r.get("types", "")
            mv = r.get("mana_value", "?")
            sim = r.get("similarity", 0)
            lines.append(f"  - {name} (MV:{mv}, {types}) [similarity: {sim:.3f}]")
    return "\n".join(lines)


def _format_matchups(report: DeckReport) -> str:
    """Format matchup data."""
    if not report.matchups:
        return "No matchup data available."
    lines = []
    for m in report.matchups:
        lines.append(f"- vs {m.opponentDeck}: {m.winRate:.1%} "
                     f"({m.gamesPlayed} games)")
    return "\n".join(lines)


def _format_combos(report: DeckReport) -> str:
    """Format known combos section."""
    if not report.knownCombos:
        return ""
    lines = ["### Known Combos"]
    for combo in report.knownCombos:
        cards = " + ".join(combo.cardNames)
        lines.append(f"- {cards}: winRate={combo.winRateWhenAssembled:.1%}, "
                     f"assemblyRate={combo.assemblyRate:.1%}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Main Builder Functions
# ══════════════════════════════════════════════════════════════

def build_system_prompt(report: DeckReport,
                        goals: Optional[CoachGoals] = None) -> str:
    """Build the system prompt with deck-specific rules."""
    color_str = "/".join(report.colorIdentity) if report.colorIdentity else "any"
    return SYSTEM_PROMPT_TEMPLATE.format(
        commander=report.commander,
        color_identity=color_str,
        goals_section=_format_goals_section(goals),
    )


def build_user_prompt(report: DeckReport,
                      candidates: Dict[str, List[dict]] = None) -> str:
    """Build the user prompt with full deck report data."""
    color_str = "/".join(report.colorIdentity) if report.colorIdentity else "unknown"

    type_parts = [f"{k}={v}" for k, v in report.structure.cardTypeCounts.items()] \
        if report.structure.cardTypeCounts else ["unknown"]
    role_parts = [f"{k}={v}" for k, v in report.structure.functionalCounts.items()] \
        if report.structure.functionalCounts else ["unknown"]

    return USER_PROMPT_TEMPLATE.format(
        deck_name=report.deckId,
        commander=report.commander,
        color_identity=color_str,
        games_simulated=report.meta.gamesSimulated,
        win_rate=report.meta.overallWinRate,
        avg_game_length=report.meta.avgGameLength,
        land_count=report.structure.landCount,
        curve_summary=_format_curve(report.structure.curveBuckets),
        type_summary=", ".join(type_parts),
        role_summary=", ".join(role_parts),
        matchup_section=_format_matchups(report),
        top_cards=_format_top_cards(report.cards),
        underperformer_section=_format_underperformers(
            report.cards, report.underperformers),
        candidate_section=_format_candidates(candidates or {}),
        combo_section=_format_combos(report),
    )
