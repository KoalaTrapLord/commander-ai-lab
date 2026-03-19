"""
Adapter: bridges the new Ollama deck_builder pipeline to the legacy
DeckGeneratorV3 dict interface expected by lab_api_new.py endpoints.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from .pipeline.build_deck import build_deck
from .core.models import BuildRequest, BuildResult, DeckRatios

logger = logging.getLogger("commander_ai_lab.deckgen")


class DeckBuilderAdapter:
    """
    Drop-in replacement for DeckGeneratorV3.
    Wraps the Ollama-based build_deck pipeline and returns
    the same dict shape the existing FastAPI endpoints expect.
    """

    def __init__(
        self,
        db_conn_factory: Callable[[], sqlite3.Connection] = None,
        model: str = "gpt-oss:20b",
    ):
        self.db_conn_factory = db_conn_factory
        self.model = model

    # ── public API (matches DeckGeneratorV3.generate_deck signature) ──
    def generate_deck(
        self,
        commander_name: str,
        strategy: str = "",
        target_bracket: int = 3,
        budget_usd: Optional[float] = None,
        budget_mode: str = "total",
        omit_cards: Optional[List[str]] = None,
        use_collection: bool = True,
        model: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Run the 7-step Ollama pipeline and return a dict that matches
        the shape expected by /api/deck/v3/generate.
        """
        # Map legacy params -> BuildRequest
        request = BuildRequest(
            commander_name=commander_name,
            strategy_notes=strategy or None,
            collection_only=use_collection,
            budget_limit=budget_usd,
            ratios=DeckRatios(),  # use defaults
        )

        result: BuildResult = build_deck(request)
        deck = result.deck
        commander = deck.commander

        # Build color_identity list
        color_identity = sorted(commander.color_identity)

        # Convert cards to legacy dict format + check collection ownership
        cards_with_status = self._check_ownership(
            [self._card_to_dict(c) for c in deck.cards]
        )

        # Fill basic lands to 100 total
        cards_with_status = self._fill_basic_lands(
            cards_with_status, color_identity, target_total=100
        )

        # Compute stats
        stats = self._compute_stats(cards_with_status)

        # Build the raw_deck structure (what Ollama/Perplexity originally returned)
        raw_deck = {
            "commander": commander.name,
            "strategy_summary": strategy or f"{commander.name} synergy deck",
            "archetype": strategy or "synergy",
            "bracket": {"level": target_bracket},
            "reasoning": {
                "strategy": f"Built with local Ollama ({self.model})",
                "sources": result.sources_consulted,
                "warnings": result.warnings,
            },
            "estimated_total_usd": 0,
            "cards": [self._card_to_raw(c) for c in deck.cards],
        }

        return {
            "commander": {
                "name": commander.name,
                "type_line": commander.type_line or "Legendary Creature",
                "color_identity": color_identity,
                "mana_cost": commander.mana_cost or "",
                "cmc": commander.cmc,
                "scryfall_id": commander.scryfall_id,
            },
            "color_identity": color_identity,
            "raw_deck": raw_deck,
            "cards": [c for c in cards_with_status],
            "stats": stats,
            "strategy_summary": raw_deck["strategy_summary"],
            "bracket": raw_deck["bracket"],
            "archetype": raw_deck["archetype"],
            "reasoning": raw_deck["reasoning"],
            "estimated_total_usd": 0,
            "tokens_used": {"prompt": 0, "completion": 0},
            "model": self.model,
            "citations": [],
            "truncated": False,
            "build_time_seconds": result.build_time_seconds,
        }

    # ── helpers ───────────────────────────────────────────────────
    @staticmethod
    def _card_to_dict(card) -> Dict[str, Any]:
        """Convert a CardEntry to a flat dict."""
        return {
            "name": card.name,
            "count": card.quantity,
            "category": card.category,
            "mana_cost": card.mana_cost or "",
            "cmc": card.cmc,
            "type_line": card.type_line or "",
            "color_identity": sorted(card.color_identity),
            "scryfall_id": card.scryfall_id,
            "edhrec_rank": card.edhrec_rank,
            "source": card.source or "ollama",
        }

    @staticmethod
    def _card_to_raw(card) -> Dict[str, Any]:
        """Convert a CardEntry to the raw_deck card format."""
        return {
            "name": card.name,
            "count": card.quantity,
            "category": card.category,
            "reasoning": "",
        }

    def _check_ownership(self, cards: List[Dict]) -> List[Dict]:
        """Check which cards are in the user's collection."""
        if not self.db_conn_factory:
            for c in cards:
                c["owned"] = False
                c["owned_qty"] = 0
                c["from_collection"] = False
                c.setdefault("estimated_price_usd", 0)
            return cards

        try:
            conn = self.db_conn_factory()
            for card in cards:
                name = card.get("name", "")
                if not name:
                    continue
                row = conn.execute(
                    "SELECT name, scryfall_id, quantity, tcg_price, type_line, cmc "
                    "FROM collection_entries WHERE name = ? COLLATE NOCASE LIMIT 1",
                    (name,),
                ).fetchone()
                if row:
                    card["owned"] = True
                    card["owned_qty"] = row["quantity"] if isinstance(row, dict) else (row[2] if row else 0)
                    card["from_collection"] = True
                    card["scryfall_id"] = card.get("scryfall_id") or (row["scryfall_id"] if isinstance(row, dict) else row[1])
                    price = row["tcg_price"] if isinstance(row, dict) else row[3]
                    card["estimated_price_usd"] = float(price) if price else 0
                else:
                    card["owned"] = False
                    card["owned_qty"] = 0
                    card["from_collection"] = False
                    card.setdefault("estimated_price_usd", 0)
        except Exception as e:
            logger.warning(f"Collection check failed: {e}")
            for c in cards:
                c.setdefault("owned", False)
                c.setdefault("owned_qty", 0)
                c.setdefault("from_collection", False)
                c.setdefault("estimated_price_usd", 0)

        return cards

    @staticmethod
    def _fill_basic_lands(
        cards: List[Dict], color_identity: List[str], target_total: int = 100
    ) -> List[Dict]:
        """Fill basic lands to reach target card count."""
        current = sum(c.get("count", 1) for c in cards)
        needed = target_total - current
        if needed <= 0:
            return cards

        ci_to_basic = {
            "W": "Plains",
            "U": "Island",
            "B": "Swamp",
            "R": "Mountain",
            "G": "Forest",
        }

        basics = [ci_to_basic[c] for c in color_identity if c in ci_to_basic]
        if not basics:
            basics = ["Wastes"]

        # Distribute evenly
        for i in range(needed):
            land_name = basics[i % len(basics)]
            # Check if already in deck
            existing = next((c for c in cards if c["name"] == land_name), None)
            if existing:
                existing["count"] = existing.get("count", 1) + 1
            else:
                cards.append({
                    "name": land_name,
                    "count": 1,
                    "category": "lands",
                    "mana_cost": "",
                    "cmc": 0,
                    "type_line": "Basic Land",
                    "color_identity": [],
                    "owned": False,
                    "owned_qty": 0,
                    "from_collection": False,
                    "estimated_price_usd": 0,
                    "source": "auto-fill",
                })

        return cards

    @staticmethod
    def _compute_stats(cards: List[Dict]) -> Dict[str, Any]:
        """Compute deck statistics."""
        total = sum(c.get("count", 1) for c in cards)
        categories = Counter()
        cmc_total = 0.0
        nonland_count = 0

        for c in cards:
            count = c.get("count", 1)
            cat = c.get("category", "uncategorized")
            categories[cat] += count
            if cat != "lands":
                cmc_total += c.get("cmc", 0) * count
                nonland_count += count

        avg_cmc = round(cmc_total / nonland_count, 2) if nonland_count else 0

        return {
            "total_cards": total,
            "category_breakdown": dict(categories),
            "average_cmc": avg_cmc,
            "land_count": categories.get("lands", 0),
            "nonland_count": nonland_count,
        }
