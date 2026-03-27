"""
Commander AI Lab — Coach Prompt Template
════════════════════════════════════════
Constructs system and user prompts for the LLM coach.
Injects deck report data, underperformer analysis, and
candidate replacement cards into a structured template.
"""

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
- IMPORTANT: Suggest 5-8 DIFFERENT cards to cut and 5-8 DIFFERENT cards to add.
- Each suggested add MUST be a different card — never suggest the same card twice.
- Vary your suggestions across different functional roles (ramp, draw, removal, threats, utility).
- If the deck is missing a functional role (e.g., no card draw, no removal), prioritize adding cards for that role.
- If candidate replacements are provided from embeddings search, prefer those over generic suggestions.
- For each suggested cut, provide a DETAILED reason citing specific stats (impact score, cast rate, dead card rate, clunkiness, synergy score).
- For each suggested add, explain the SPECIFIC synergy with existing cards in the deck.
- When reasoning about cuts, also consider keptInOpeningHandRate (low = bad in opening hands) and avgTurnCast (high = too slow for the curve).
- When evaluating synergy, use the synergyScore: cards below 0.1 have weak co-occurrence with the rest of the deck.
- Use perArchetypeWinRates to identify which matchup types this deck struggles with and tailor suggestions accordingly.
- Provide at least 5 heuristic hints covering different strategic dimensions.
{goals_section}

You MUST respond ONLY with valid JSON matching this exact structure:
{{
  "summary": "4-6 sentence detailed overview of the deck's strengths, weaknesses, key synergies, and strategic identity. Reference specific win rates and simulation data.",
  "suggestedCuts": [
    {{
      "cardName": "Card To Remove",
      "reason": "Detailed explanation citing specific simulation stats (impact score, cast rate, dead card rate, clunkiness score, synergy score, avg turn cast) and why this card underperforms in this specific deck context",
      "replacementOptions": ["Better Card 1", "Better Card 2"],
      "functionalRole": "ramp|draw|removal|threat|utility|combo|protection",
      "estimatedImpact": "How cutting this card is expected to improve the deck"
    }}
  ],
  "suggestedAdds": [
    {{
      "cardName": "Card To Add",
      "role": "ramp|draw|removal|threat|utility|combo|protection",
      "reason": "Detailed explanation of why this card improves the deck, referencing specific weaknesses it addresses",
      "synergyWith": ["Card In Deck 1", "Card In Deck 2"],
      "estimatedManaCost": "The mana value of the suggested card",
      "strategicRationale": "How this card fits into the overall game plan and addresses a specific gap"
    }}
  ],
  "manaCurveAnalysis": {{
    "currentAssessment": "Detailed analysis of the current mana curve distribution and its implications",
    "recommendations": "Specific suggestions for curve adjustments with reasoning",
    "idealRange": "What the curve should look like for this deck's strategy"
  }},
  "roleBreakdown": {{
    "ramp": "Assessment of ramp package - count, quality, and suggestions",
    "draw": "Assessment of card draw package",
    "removal": "Assessment of removal package",
    "threats": "Assessment of win conditions and threats",
    "protection": "Assessment of protection and interaction"
  }},
  "synergyAnalysis": [
    "Description of a key synergy chain in the deck and how well it performed in simulation"
  ],
  "heuristicHints": [
    "Detailed strategic tip explaining the reasoning and data behind the suggestion"
  ],
  "manaBaseAdvice": "Specific mana base improvement suggestion including land count, color fixing, and utility lands, or null if mana base is solid",
  "rawTextExplanation": "3-5 paragraph in-depth analysis covering: (1) overall deck strategy assessment and how well the deck executes its game plan based on simulation data, (2) mana curve and resource analysis with specific numbers including avgTurnCast for key cards, (3) card synergy evaluation highlighting the strongest and weakest interactions using synergyScore data, (4) meta considerations and matchup-specific insights referencing perArchetypeWinRates, and (5) prioritized list of improvements ranked by expected impact on win rate"
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

### Archetype Win Rates
{archetype_section}

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
    return ", ".join(parts) if parts else "not available (analyze deck structure manually)"


def _format_top_cards(cards: List[CardPerformance], top_n: int = 10) -> str:
    """Format the best performing cards with extended stats."""
    sorted_cards = sorted(cards, key=lambda c: c.impactScore, reverse=True)
    lines = []
    for c in sorted_cards[:top_n]:
        tags = f" [{', '.join(c.tags)}]" if c.tags else ""
        turn_str = f", avgTurnCast={c.avgTurnCast:.1f}" if c.avgTurnCast is not None else ""
        lines.append(
            f"- {c.name}: impact={c.impactScore:.3f}, "
            f"castRate={c.castRate:.1%}, drawnRate={c.drawnRate:.1%}, "
            f"synergy={c.synergyScore:.3f}{turn_str}{tags}"
        )
    return "\n".join(lines) if lines else "No card performance data available."


def _format_underperformers(cards: List[CardPerformance],
                             underperformer_names: List[str]) -> str:
    """Format underperforming cards with full available stats."""
    card_map = {c.name: c for c in cards}
    lines = []
    for name in underperformer_names[:MAX_UNDERPERFORMERS]:
        c = card_map.get(name)
        if c:
            turn_str = f", avgTurnCast={c.avgTurnCast:.1f}" if c.avgTurnCast is not None else ""
            lines.append(
                f"- {c.name}: impact={c.impactScore:.3f}, "
                f"deadCardRate={c.deadCardRate:.1%}, "
                f"castRate={c.castRate:.1%}, "
                f"clunkiness={c.clunkinessScore:.3f}, "
                f"synergy={c.synergyScore:.3f}, "
                f"keptInOpeningHand={c.keptInOpeningHandRate:.1%}"
                f"{turn_str}"
            )
        else:
            lines.append(f"- {name}: (no detailed stats)")
    return "\n".join(lines) if lines else "No clear underperformers identified."


def _format_candidates(candidates: Dict[str, List[dict]]) -> str:
    """Format replacement candidates grouped by the card they'd replace."""
    if not candidates:
        return (
            "No embedding-based candidates available. "
            "Use your MTG knowledge to suggest cards that fit the deck's "
            "color identity, strategy, and missing functional roles. "
            "Suggest at least 3 different cards across different roles "
            "(ramp, draw, removal, threats, utility)."
        )

    lines = []
    for underperformer, replacements in list(candidates.items())[:MAX_UNDERPERFORMERS]:
        lines.append(f"\nReplacements for '{underperformer}':")
        for r in replacements[:MAX_CANDIDATES_PER_UNDERPERFORMER]:
            name = r.get("name", "Unknown")
            types = r.get("types", "")
            mv = r.get("mana_value", "?")
            sim = r.get("similarity", 0)
            text_preview = r.get("text", "")[:80]
            lines.append(f"  - {name} (MV:{mv}, {types}) [similarity: {sim:.3f}]")
            if text_preview:
                lines.append(f"    Oracle: {text_preview}")

    lines.append("\nChoose from these candidates when possible, but also suggest ")
    lines.append("cards NOT in this list if they better address the deck's weaknesses.")
    return "\n".join(lines)


def _format_matchups(report: DeckReport) -> str:
    """Format per-opponent matchup data."""
    if not report.matchups:
        return "No matchup data available."
    lines = []
    for m in report.matchups:
        lines.append(
            f"- vs {m.opponentDeck}: {m.winRate:.1%} "
            f"({m.gamesPlayed} games)"
        )
    return "\n".join(lines)


def _format_archetypes(report: DeckReport) -> str:
    """Format per-archetype win rates from DeckMeta."""
    rates = report.meta.perArchetypeWinRates
    if not rates:
        return "No archetype breakdown available."
    lines = []
    for archetype, wr in sorted(rates.items(), key=lambda x: x[1]):
        lines.append(f"- vs {archetype}: {wr:.1%}")
    return "\n".join(lines)


def _format_combos(report: DeckReport) -> str:
    """Format known combos section."""
    if not report.knownCombos:
        return ""
    lines = ["### Known Combos"]
    for combo in report.knownCombos:
        cards = " + ".join(combo.cardNames)
        lines.append(
            f"- {cards}: winRate={combo.winRateWhenAssembled:.1%}, "
            f"assemblyRate={combo.assemblyRate:.1%}"
        )
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
        archetype_section=_format_archetypes(report),
        top_cards=_format_top_cards(report.cards),
        underperformer_section=_format_underperformers(
            report.cards, report.underperformers),
        candidate_section=_format_candidates(candidates or {}),
        combo_section=_format_combos(report),
    )
