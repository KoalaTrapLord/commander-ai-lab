"""
Commander AI Lab — Prompt Builder (Phase 1)
============================================
Converts a CommanderGameState into a compact, token-efficient LLM prompt.
Also builds the legal moves prompt for AI action selection.

Design goals:
  - Stay under 3000 tokens for the combined system + state + moves prompt
  - Be human-readable so the LLM can reason about it naturally
  - Abbreviate zones aggressively (counts > full lists where possible)

Usage:
    from commander_ai_lab.sim.prompt_builder import state_to_prompt, legal_moves_to_prompt
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from commander_ai_lab.sim.game_state import CommanderGameState


# ── Phase display names ───────────────────────────────────────

PHASE_LABELS: dict[str, str] = {
    "untap": "Untap",
    "upkeep": "Upkeep",
    "draw": "Draw",
    "main1": "Main Phase 1",
    "combat_begin": "Begin Combat",
    "combat_declare_attackers": "Declare Attackers",
    "combat_declare_blockers": "Declare Blockers",
    "combat_damage": "Combat Damage",
    "combat_end": "End of Combat",
    "main2": "Main Phase 2",
    "end": "End Step",
    "cleanup": "Cleanup",
}


def _abbreviate_card_list(cards: list, max_show: int = 6) -> str:
    """Return abbreviated card list string, truncating if too long."""
    if not cards:
        return "(none)"
    names = [getattr(c, 'name', str(c)) for c in cards]
    if len(names) <= max_show:
        return ", ".join(names)
    shown = ", ".join(names[:max_show])
    return f"{shown} ... +{len(names) - max_show} more"


def _format_battlefield(cards: list) -> str:
    """Format battlefield cards with tapped state and P/T."""
    if not cards:
        return "(empty)"
    parts = []
    for c in cards:
        name = getattr(c, 'name', '?')
        tapped = " [T]" if getattr(c, 'tapped', False) else ""
        type_line = getattr(c, 'type_line', '')
        if 'creature' in type_line.lower():
            power = getattr(c, 'power', '') or '?'
            toughness = getattr(c, 'toughness', '') or '?'
            parts.append(f"{name} {power}/{toughness}{tapped}")
        else:
            parts.append(f"{name}{tapped}")
    return ", ".join(parts)


def _format_mana_pool(mana_pool) -> str:
    """Format mana pool as compact string like {W}{W}{U}{C}."""
    if mana_pool.total() == 0:
        return "(empty)"
    parts = []
    for color in ['W', 'U', 'B', 'R', 'G', 'C']:
        count = getattr(mana_pool, color, 0)
        if count > 0:
            parts.extend([f"{{{color}}}"] * count)
    return "".join(parts)


def state_to_prompt(gs: "CommanderGameState", viewer_seat: int) -> str:
    """
    Convert a CommanderGameState into a compact LLM-readable string.

    Args:
        gs: The current game state.
        viewer_seat: The seat index of the AI making the decision
                     (their hand is shown in full; opponents' hands are hidden).

    Returns:
        A multi-line string summarizing the game state for the LLM.
    """
    lines: list[str] = []

    phase_label = PHASE_LABELS.get(gs.current_phase, gs.current_phase)
    active = gs.active_player()
    active_name = active.name if active else f"Player {gs.active_player_seat}"
    priority_p = gs.priority_player()
    priority_name = priority_p.name if priority_p else f"Player {gs.priority_seat}"

    lines.append("=== COMMANDER GAME STATE ===")
    lines.append(f"Turn: {gs.turn}  |  Phase: {phase_label}")
    lines.append(f"Active Player: {active_name}  |  Priority: {priority_name}")
    lines.append("")

    # ── Stack ─────────────────────────────────────────────────
    if gs.stack:
        lines.append(f"STACK ({len(gs.stack)} item{'s' if len(gs.stack) != 1 else ''}):")
        for i, item in enumerate(reversed(gs.stack)):  # top first
            lines.append(f"  [{i+1}] {item.description or item.card_name} "
                         f"(by {gs.commander_players[item.controller_seat].name \
                              if item.controller_seat < len(gs.commander_players) \
                              else 'unknown'})")
        lines.append("")

    # ── Players ───────────────────────────────────────────────
    for i, cp in enumerate(gs.commander_players):
        is_viewer = (i == viewer_seat)
        status = "[YOU]" if is_viewer else ("[ELIM]" if cp.eliminated else "")
        bf = gs.sim_state.get_battlefield(i)

        lines.append(f"--- Player {i}: {cp.name} {status} ---")
        lines.append(f"  Life: {cp.life}  |  Library: {len(cp.library)} cards")

        # Commander zone
        if cp.commander_zone:
            tax_str = f" (tax: +{cp.commander_tax()}" + " mana)" if cp.commander_tax() > 0 else ""
            lines.append(f"  Commander Zone: {_abbreviate_card_list(cp.commander_zone)}{tax_str}")
        else:
            lines.append("  Commander Zone: (on battlefield or graveyard)")

        # Commander damage received
        if cp.commander_damage_received:
            dmg_parts = []
            for from_seat, dmg in cp.commander_damage_received.items():
                if dmg > 0:
                    from_name = (gs.commander_players[from_seat].name
                                 if from_seat < len(gs.commander_players) else f"P{from_seat}")
                    dmg_parts.append(f"{from_name}: {dmg}")
            if dmg_parts:
                lines.append(f"  Commander Damage Received: {', '.join(dmg_parts)}")

        # Hand — full for viewer, count for opponents
        if is_viewer:
            lines.append(f"  Hand ({len(cp.hand)}): {_abbreviate_card_list(cp.hand, max_show=10)}")
            lines.append(f"  Mana Pool: {_format_mana_pool(cp.mana_pool)}")
            if not gs.land_drop_used and i == gs.active_player_seat:
                lines.append("  Land Drop: AVAILABLE this turn")
        else:
            lines.append(f"  Hand: {len(cp.hand)} cards (hidden)")

        # Battlefield
        lines.append(f"  Battlefield: {_format_battlefield(bf)}")

        # Graveyard (abbreviated)
        if cp.graveyard:
            lines.append(f"  Graveyard ({len(cp.graveyard)}): "
                         f"{_abbreviate_card_list(cp.graveyard, max_show=4)}")

        # Exile (abbreviated)
        if cp.exile:
            lines.append(f"  Exile ({len(cp.exile)}): "
                         f"{_abbreviate_card_list(cp.exile, max_show=3)}")

        lines.append("")

    lines.append("=" * 40)
    return "\n".join(lines)


# ── Legal Move Categories ─────────────────────────────────────

LEGAL_MOVE_CATEGORIES = [
    "play_land",
    "cast_spell",
    "cast_commander",
    "activate_ability",
    "attack",
    "block",
    "pass_priority",
    "pass_turn",
    "respond",
    "other",
]


def _category_label(category: str) -> str:
    return {
        "play_land": "Play Land",
        "cast_spell": "Cast Spell",
        "cast_commander": "Cast Commander",
        "activate_ability": "Activate Ability",
        "attack": "Declare Attackers",
        "block": "Declare Blockers",
        "pass_priority": "Pass Priority",
        "pass_turn": "Pass Turn / End Phase",
        "respond": "Respond (Instant/Ability)",
        "other": "Other Action",
    }.get(category, category)


def legal_moves_to_prompt(moves: list[dict]) -> str:
    """
    Convert a list of legal move dicts into a numbered, categorized prompt string.

    Each move dict should have:
        {
            "id": int,                   # unique index for LLM selection
            "category": str,             # from LEGAL_MOVE_CATEGORIES
            "description": str,          # human-readable action description
            "card_name": str (optional), # card involved, if any
            "targets": list (optional),  # target descriptions
        }

    Returns:
        A numbered list string for inclusion in the LLM prompt.
    """
    if not moves:
        return "LEGAL ACTIONS:\n  (none — you must pass priority)"

    lines = ["LEGAL ACTIONS (reply with the number of your choice):"]

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for move in moves:
        cat = move.get("category", "other")
        by_category.setdefault(cat, []).append(move)

    # Output in logical order
    for cat in LEGAL_MOVE_CATEGORIES:
        if cat not in by_category:
            continue
        lines.append(f"\n  [{_category_label(cat)}]")
        for move in by_category[cat]:
            move_id = move.get("id", "?")
            desc = move.get("description", "(no description)")
            targets = move.get("targets", [])
            target_str = f" → targets: {', '.join(str(t) for t in targets)}" if targets else ""
            lines.append(f"    {move_id}. {desc}{target_str}")

    return "\n".join(lines)


def build_full_prompt(
    gs: "CommanderGameState",
    viewer_seat: int,
    moves: list[dict],
    personality: str = "",
) -> str:
    """
    Build the complete prompt to send to the LLM.

    Args:
        gs: Current game state.
        viewer_seat: AI player's seat index.
        moves: List of legal move dicts.
        personality: Optional personality/system prompt prefix.

    Returns:
        Full prompt string ready for LLM inference.
    """
    sections = []

    if personality:
        sections.append(personality.strip())
        sections.append("")

    sections.append(state_to_prompt(gs, viewer_seat))
    sections.append("")
    sections.append(legal_moves_to_prompt(moves))
    sections.append("")
    sections.append(
        "Respond with ONLY the number of the action you choose. "
        "Do not explain your reasoning. Just the number."
    )

    return "\n".join(sections)
