"""
routes/rag.py
=============
RAG (Retrieval-Augmented Generation) endpoints for semantic card search.

Endpoints:
  POST /api/rag/build          — build / rebuild the ChromaDB vector index
  POST /api/rag/search         — semantic search over indexed cards
  GET  /api/rag/status         — index health & stats
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("commander_ai_lab.routes.rag")

router = APIRouter(tags=["rag"])


# ── Request / Response models ────────────────────────────────────────────────

class RAGSearchRequest(BaseModel):
    query: str = Field(..., description="Natural-language card search query")
    color_identity: Optional[List[str]] = Field(
        None,
        description="Optional color identity filter, e.g. ['W','U','B']",
    )
    top_k: int = Field(10, ge=1, le=50, description="Number of results to return")


class RAGCardResult(BaseModel):
    name: str
    type_line: str = ""
    oracle_text: str = ""
    color_identity: str = ""
    score: float = 0.0


class RAGSearchResponse(BaseModel):
    query: str
    results: List[RAGCardResult]
    total: int


class RAGBuildRequest(BaseModel):
    force: bool = Field(False, description="Force full rebuild even if index exists")
    batch_size: int = Field(500, ge=50, le=5000)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/api/rag/build")
async def rag_build(body: RAGBuildRequest = RAGBuildRequest()):
    """
    Build or rebuild the ChromaDB vector index from the Scryfall bulk DB.
    Runs synchronously (may take 1-5 min on first build).
    """
    try:
        from services.rag_store import build_index
        result = build_index(force=body.force, batch_size=body.batch_size)
        return {"status": "ok", **result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.exception("RAG build failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/rag/search")
async def rag_search(body: RAGSearchRequest):
    """
    Semantic search over the ChromaDB card index.
    Returns ranked card results with relevance scores.
    """
    try:
        from services.rag_store import query_cards
        raw_results = query_cards(
            query=body.query,
            n_results=body.top_k,
            color_identity=body.color_identity,
        )
        results = [
            RAGCardResult(
                name=r.get("name", ""),
                type_line=r.get("type_line", ""),
                oracle_text=r.get("oracle_text", ""),
                color_identity=r.get("color_identity", ""),
                score=round(1.0 - r.get("distance", 0.0), 4),
            )
            for r in raw_results
        ]
        return RAGSearchResponse(
            query=body.query,
            results=results,
            total=len(results),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Index not built yet. Call POST /api/rag/build first. {exc}",
        )
    except Exception as exc:
        log.exception("RAG search failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/rag/status")
async def rag_status_detail():
    """
    Detailed RAG index status including card count and age.
    """
    try:
        from services.rag_store import get_rag_stats
        return {"status": "ok", **get_rag_stats()}
    except Exception as exc:
        log.exception("RAG status check failed")
        return {"status": "error", "error": str(exc)}
