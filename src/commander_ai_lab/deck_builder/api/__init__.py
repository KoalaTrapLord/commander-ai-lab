"""API subpackage – external service clients (Scryfall, EDHRec, Ollama)."""

from . import scryfall
from . import edhrec
from . import ollama_client
from .community_scraper import CommunityScraper

__all__ = [
    "scryfall",
    "edhrec",
    "ollama_client",
    "CommunityScraper",
]
