"""
Commander AI Lab — Threat Assessor (Phase 3)
=============================================
Scores every seat's threat level so the turn manager and AI opponents can
make targeting / blocking decisions.

Threat score is a weighted sum of:
  - Board power (total creature power)
  - Board size (non-land permanents)
  - Hand size (unknown cards = potential)
  - Life total proximity to win (40 is baseline)
  - Combo proximity (commanders in play, key enchantments, etc.)

Scores are normalized to [0.0, 1.0]. Higher = more dangerous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from commander_ai_lab.sim.game_state import CommanderGameState


@dataclass
class ThreatScore:
    seat: int
    name: str
    total: float                   # Normalized [0.0, 1.0]
    board_power: float
    board_size: float
    hand_potential: float
    life_threat: float             # How much damage they could deal relative to opponents' life
    combo_proximity: float
    raw: dict = field(default_factory=dict)   # Raw sub-scores before normalization

    def __repr__(self) -> str:
        return (
            f"ThreatScore(seat={self.seat} name={self.name!r} "
            f"total={self.total:.3f} board_power={self.board_power:.3f} "
            f"life_threat={self.life_threat:.3f})"
        )


# Weight config — tune these without changing logic
_W_BOARD_POWER   = 0.35
_W_BOARD_SIZE    = 0.20
_W_HAND          = 0.15
_W_LIFE_THREAT   = 0.20
_W_COMBO         = 0.10

# Combo-indicator keywords / oracle phrases
_COMBO_KEYWORDS = [
    "infinite", "you win the game", "extra turn", "search your library",
    "whenever .* enters", "double", "each opponent loses",
]


def assess_threats(
    game_state: CommanderGameState,
    viewer_seat: int,
) -> list[ThreatScore]:
    """
    Return a list of ThreatScore for every non-eliminated seat, ordered by
    descending threat. The viewer's own seat is included but marked.

    Args:
        game_state: Current CommanderGameState.
        viewer_seat: The AI seat requesting the assessment (used for relative
                     life threat calculation).

    Returns:
        List[ThreatScore] sorted by total descending.
    """
    scores: list[ThreatScore] = []
    players = game_state.players
    viewer = players[viewer_seat] if viewer_seat < len(players) else None
    viewer_life = viewer.life if viewer else 40

    for seat, player in enumerate(players):
        if player.eliminated:
            continue

        # --- Board power ---
        total_power = 0
        board_size = 0
        combo_score = 0
        for c in player.battlefield:
            if c.get("type") in ("creature", "Creature") or "creature" in c.get("type", "").lower():
                try:
                    pt = c.get("pt", "0/0")
                    pw = int(pt.split("/")[0]) if "/" in pt else 0
                except (ValueError, IndexError):
                    pw = 0
                total_power += pw
            if not (c.get("type", "").lower() == "land"):
                board_size += 1
            # Combo proximity: scan oracle text for combo indicators
            oracle = (c.get("oracle", "") or "").lower()
            for kw in _COMBO_KEYWORDS:
                import re
                if re.search(kw, oracle):
                    combo_score += 1
                    break

        hand_size = len(player.hand)

        # Normalize sub-scores to [0, 1]
        bp_norm   = min(total_power / 20.0, 1.0)
        bs_norm   = min(board_size  / 10.0, 1.0)
        hand_norm = min(hand_size   / 10.0, 1.0)
        combo_norm = min(combo_score / 5.0, 1.0)

        # Life threat: how close are they to killing the viewer?
        # If their total power >= viewer's life → maximum threat
        life_threat_raw = total_power / max(viewer_life, 1)
        lt_norm = min(life_threat_raw, 1.0)

        total = (
            _W_BOARD_POWER * bp_norm
            + _W_BOARD_SIZE * bs_norm
            + _W_HAND       * hand_norm
            + _W_LIFE_THREAT * lt_norm
            + _W_COMBO      * combo_norm
        )

        scores.append(ThreatScore(
            seat=seat,
            name=player.name,
            total=round(total, 4),
            board_power=round(bp_norm, 4),
            board_size=round(bs_norm, 4),
            hand_potential=round(hand_norm, 4),
            life_threat=round(lt_norm, 4),
            combo_proximity=round(combo_norm, 4),
            raw={
                "total_power": total_power,
                "board_non_land": board_size,
                "hand_size": hand_size,
                "combo_indicators": combo_score,
                "life": player.life,
            },
        ))

    scores.sort(key=lambda s: -s.total)
    return scores


def top_threat(
    game_state: CommanderGameState,
    viewer_seat: int,
    exclude_self: bool = True,
) -> Optional[ThreatScore]:
    """
    Return the single highest-threat opponent.

    Args:
        exclude_self: If True (default), skip viewer_seat.
    """
    threats = assess_threats(game_state, viewer_seat)
    for t in threats:
        if exclude_self and t.seat == viewer_seat:
            continue
        return t
    return None
