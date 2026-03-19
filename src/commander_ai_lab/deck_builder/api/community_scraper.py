"""
Community scraper – pull popular decklists from Moxfield, Archidekt, and Reddit.

This is a Phase-3 expansion module. Currently provides stub implementations
that return empty results. Wire up real scraping logic as the project matures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MOXFIELD_API = "https://api2.moxfield.com/v3/decks/search"
ARCHIDEKT_API = "https://archidekt.com/api/decks/"


@dataclass
class CommunityDeck:
    """Minimal representation of a community-sourced decklist."""

    source: str  # "moxfield" | "archidekt" | "reddit"
    title: str
    url: str
    card_names: List[str] = field(default_factory=list)
    author: Optional[str] = None


class CommunityScraper:
    """Aggregate community decklists for a given commander."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CommanderAILab/0.1"})

    # ------------------------------------------------------------------
    # Moxfield
    # ------------------------------------------------------------------
    def search_moxfield(
        self, commander_name: str, *, max_results: int = 10
    ) -> List[CommunityDeck]:
        """Search Moxfield for public decks featuring *commander_name*."""
        try:
            resp = self._session.get(
                MOXFIELD_API,
                params={
                    "q": commander_name,
                    "fmt": "commander",
                    "sort": "views",
                    "sortDirection": "descending",
                    "pageSize": max_results,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            decks: List[CommunityDeck] = []
            for item in data.get("data", []):
                pub_id = item.get("publicId", "")
                decks.append(
                    CommunityDeck(
                        source="moxfield",
                        title=item.get("name", ""),
                        url=f"https://www.moxfield.com/decks/{pub_id}",
                        author=item.get("createdByUser", {}).get("userName"),
                    )
                )
            logger.info("Moxfield returned %d decks for %s", len(decks), commander_name)
            return decks
        except Exception:
            logger.warning("Moxfield search failed for %s", commander_name, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Archidekt
    # ------------------------------------------------------------------
    def search_archidekt(
        self, commander_name: str, *, max_results: int = 10
    ) -> List[CommunityDeck]:
        """Search Archidekt for public decks featuring *commander_name*."""
        try:
            resp = self._session.get(
                ARCHIDEKT_API,
                params={
                    "commanders": commander_name,
                    "formats": 3,  # Commander
                    "orderBy": "-viewCount",
                    "pageSize": max_results,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            decks: List[CommunityDeck] = []
            for item in data.get("results", []):
                deck_id = item.get("id", "")
                decks.append(
                    CommunityDeck(
                        source="archidekt",
                        title=item.get("name", ""),
                        url=f"https://archidekt.com/decks/{deck_id}",
                        author=item.get("owner", {}).get("username"),
                    )
                )
            logger.info("Archidekt returned %d decks for %s", len(decks), commander_name)
            return decks
        except Exception:
            logger.warning("Archidekt search failed for %s", commander_name, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    def search_all(
        self, commander_name: str, *, max_per_source: int = 10
    ) -> List[CommunityDeck]:
        """Search all community sources and return combined results."""
        results: List[CommunityDeck] = []
        results.extend(self.search_moxfield(commander_name, max_results=max_per_source))
        results.extend(self.search_archidekt(commander_name, max_results=max_per_source))
        return results

    def extract_popular_cards(
        self, decks: List[CommunityDeck], *, min_frequency: int = 2
    ) -> Dict[str, int]:
        """Count card frequency across decks; return cards seen >= min_frequency."""
        counts: Dict[str, int] = {}
        for deck in decks:
            for name in deck.card_names:
                counts[name] = counts.get(name, 0) + 1
        return {k: v for k, v in counts.items() if v >= min_frequency}
