"""Pydantic models for Commander AI Lab API."""

from models.requests import (
    StartRequest,
    ImportUrlRequest,
    ImportTextRequest,
    MetaFetchRequest,
    CreateDeckRequest,
    UpdateDeckRequest,
    AddDeckCardRequest,
    PatchDeckCardRequest,
    BulkAddRequest,
    BulkAddRecommendedRequest,
    DeckGenerationSourceConfig,
    DeckGenerationRequest,
    DeckGenV3Request,
    DeckGenV3SubstituteRequest,
)
from models.responses import (
    StartResponse,
    StatusResponse,
    DeckInfo,
    GeneratedDeckCard,
)

__all__ = [
    # Requests
    "StartRequest",
    "ImportUrlRequest",
    "ImportTextRequest",
    "MetaFetchRequest",
    "CreateDeckRequest",
    "UpdateDeckRequest",
    "AddDeckCardRequest",
    "PatchDeckCardRequest",
    "BulkAddRequest",
    "BulkAddRecommendedRequest",
    "DeckGenerationSourceConfig",
    "DeckGenerationRequest",
    "DeckGenV3Request",
    "DeckGenV3SubstituteRequest",
    # Responses
    "StartResponse",
    "StatusResponse",
    "DeckInfo",
    "GeneratedDeckCard",
]
