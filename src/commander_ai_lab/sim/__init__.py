"""Commander AI Lab — Simulator subpackage.

Ported from mtg-commander-lan (JavaScript) deck tester / headless sim engine.
Provides a headless Commander game simulator for Monte Carlo analysis.
"""

from commander_ai_lab.sim.models import Card, Player, SimState
from commander_ai_lab.sim.engine import GameEngine
from commander_ai_lab.sim.rules import enrich_card, AI_DEFAULT_WEIGHTS

__all__ = [
    "Card",
    "Player",
    "SimState",
    "GameEngine",
    "enrich_card",
    "AI_DEFAULT_WEIGHTS",
]
