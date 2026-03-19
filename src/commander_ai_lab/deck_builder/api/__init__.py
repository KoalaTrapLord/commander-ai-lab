"""API subpackage – external service clients (Scryfall, EDHRec, Ollama)."""

from .scryfall import ScryfallClient
from .edhrec import EDHRecClient
from .ollama_client import OllamaClient

__all__ = [
    "ScryfallClient",
    "EDHRecClient",
    "OllamaClient",
]
