"""
Commander AI Deck Builder
~~~~~~~~~~~~~~~~~~~~~~~~~
Top-level package for the deck builder module.

Usage::

    from commander_ai_lab.deck_builder import build_deck, BuildRequest

    result = build_deck(BuildRequest(commander_name="Atraxa, Praetors' Voice"))
"""

__version__ = "0.1.0"

from .pipeline import build_deck
from .core.models import BuildRequest, BuildResult

__all__ = ["build_deck", "BuildRequest", "BuildResult", "__version__"]
