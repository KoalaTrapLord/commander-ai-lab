"""
services/rag_store.py
=====================
ChromaDB-backed semantic vector store over the Scryfall bulk card database.

Reads all cards from the Phase 1 SQLite bulk DB (services/scryfall_bulk.py),
embeds their oracle text using Ollama's nomic-embed-text model, and stores
the vectors in a persistent ChromaDB collection on disk.

This is RAG Phase 2.  Phase 3 will query this store to inject relevant card
oracle text into the LLM prompt before calling the coach.

Public API:
    ensure_rag_store()           -> None   (build if missing / stale)
    query_cards(text, n, colors) -> list[dict]
    get_rag_stats()              -> dict

Data path:  ./data/rag_chroma/
Embedding:  nomic-embed-text via Ollama (localhost:11434)
"""
from __future__ import annotations

import json
import logging
import os
import time
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("commander_ai_lab.rag_store")

# ── Config ──────────────────────────────────────────────────────────────────
RAG_CHROMA_DIR = Path(__file__).parent.parent / "data" / "rag_chroma"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "nomic-embed-text")
COLLECTION_NAME = "mtg_oracle"
BATCH_SIZE = 200
_rag_lock = threading.Lock()
_rag_ready = False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_document(card: dict) -> str:
    """Build the text document to embed for a single card.

    Format:  Name | Type | Oracle Text
    This mirrors the structure used by the existing coach embeddings
    (coach/embeddings.py) so vector similarity is consistent across
    both systems.
    """
    parts = [card.get("name", "")]
    type_line = card.get("type_line", "")
    if type_line:
        parts.append(type_line)
    oracle = card.get("oracle_text", "")
    if oracle:
        parts.append(oracle)
    return " | ".join(parts)


def _build_metadata(card: dict) -> dict:
    """Build ChromaDB metadata dict for filtering."""
    ci_raw = card.get("color_identity", "[]")
    if isinstance(ci_raw, str):
        try:
            ci_list = json.loads(ci_raw)
        except (json.JSONDecodeError, TypeError):
            ci_list = []
    else:
        ci_list = ci_raw or []

    return {
        "name": card.get("name", ""),
        "type_line": card.get("type_line", ""),
        "cmc": float(card.get("cmc") or 0),
        "color_identity": ",".join(sorted(ci_list)),
        "rarity": card.get("rarity", ""),
        "mana_cost": card.get("mana_cost", ""),
    }


def _get_chromadb_client():
    """Return a persistent ChromaDB client, creating the data dir if needed."""
    try:
        import chromadb
    except ImportError:
        raise ImportError(
            "chromadb is required for RAG Phase 2. "
            "Install with:  pip install chromadb"
        )
    RAG_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(RAG_CHROMA_DIR))


def _get_ollama_embedding_fn():
    """Return a ChromaDB-compatible embedding function using Ollama."""
    try:
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    except ImportError:
        raise ImportError(
            "chromadb >= 0.4.0 with Ollama support is required. "
            "Install with:  pip install chromadb"
        )
    return OllamaEmbeddingFunction(
        url=f"{OLLAMA_BASE_URL}/api/embeddings",
        model_name=EMBEDDING_MODEL,
    )


def _get_collection():
    """Return the ChromaDB collection, creating it if needed."""
    client = _get_chromadb_client()
    embed_fn = _get_ollama_embedding_fn()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )


def _collection_is_current(collection, bulk_card_count: int) -> bool:
    """Check if the ChromaDB collection is reasonably up-to-date.

    We compare the stored card count against the bulk DB count.  If they
    differ by more than 5%, we consider the collection stale and rebuild.
    """
    chroma_count = collection.count()
    if chroma_count == 0:
        return False
    try:
        meta = collection.metadata or {}
        built_at = float(meta.get("built_at", 0))
        age_days = (time.time() - built_at) / 86400
        if age_days > 14:
            logger.info("RAG collection older than 14 days — rebuilding.")
            return False
    except (ValueError, TypeError):
        pass
    ratio = chroma_count / max(bulk_card_count, 1)
    if ratio < 0.95 or ratio > 1.05:
        logger.info(
            "RAG collection count mismatch: chroma=%d, bulk=%d — rebuilding.",
            chroma_count, bulk_card_count,
        )
        return False
    return True


# ── Build pipeline ───────────────────────────────────────────────────────────

def _build_collection_from_bulk() -> int:
    """Read all cards from the bulk SQLite DB and insert into ChromaDB.

    Returns the number of cards indexed.
    """
    from services.scryfall_bulk import get_bulk_db

    conn = get_bulk_db()
    cursor = conn.execute(
        "SELECT name, oracle_text, type_line, mana_cost, cmc, "
        "color_identity, rarity, scryfall_id FROM cards "
        "WHERE oracle_text != '' "
        "ORDER BY edhrec_rank ASC"
    )

    client = _get_chromadb_client()
    embed_fn = _get_ollama_embedding_fn()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={
            "hnsw:space": "cosine",
            "built_at": str(time.time()),
        },
    )

    inserted = 0
    batch_ids: list[str] = []
    batch_docs: list[str] = []
    batch_metas: list[dict] = []

    for row in cursor:
        card = dict(row)
        doc = _build_document(card)
        if not doc.strip():
            continue

        card_id = card.get("scryfall_id", "")
        if not card_id:
            continue

        batch_ids.append(card_id)
        batch_docs.append(doc)
        batch_metas.append(_build_metadata(card))

        if len(batch_ids) >= BATCH_SIZE:
            try:
                collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                )
                inserted += len(batch_ids)
                if inserted % 2000 == 0:
                    logger.info("  RAG indexed %d cards...", inserted)
            except Exception as exc:
                logger.warning(
                    "RAG batch insert failed at %d: %s", inserted, exc
                )
            batch_ids.clear()
            batch_docs.clear()
            batch_metas.clear()

    if batch_ids:
        try:
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            inserted += len(batch_ids)
        except Exception as exc:
            logger.warning("RAG final batch insert failed: %s", exc)

    logger.info("RAG vector store complete: %d cards indexed.", inserted)
    return inserted


# ── Public API ───────────────────────────────────────────────────────────────

def ensure_rag_store() -> None:
    """Build the ChromaDB vector store if it is missing or stale.

    Safe to call at startup — no-ops quickly if the store is current.
    Requires:
      - Phase 1 bulk DB to be populated (services/scryfall_bulk)
      - Ollama running with nomic-embed-text pulled
    """
    global _rag_ready
    with _rag_lock:
        if _rag_ready:
            return
        try:
            from services.scryfall_bulk import get_stats as bulk_stats
            stats = bulk_stats()
            bulk_count = stats.get("card_count", 0)
            if bulk_count == 0:
                logger.warning(
                    "Scryfall bulk DB is empty — skipping RAG store build. "
                    "Run ensure_bulk_db() first."
                )
                return

            collection = _get_collection()
            if _collection_is_current(collection, bulk_count):
                logger.info(
                    "RAG vector store is current (%d cards).",
                    collection.count(),
                )
                _rag_ready = True
                return

            logger.info(
                "Building RAG vector store from %d bulk cards "
                "(this may take several minutes on first run)...",
                bulk_count,
            )
            _build_collection_from_bulk()
            _rag_ready = True

        except ImportError as exc:
            logger.warning("RAG store unavailable: %s", exc)
        except Exception as exc:
            logger.error("RAG store build failed: %s", exc)


def query_cards(
    query: str,
    n_results: int = 8,
    color_identity: Optional[list[str]] = None,
    type_filter: Optional[str] = None,
) -> list[dict]:
    """Semantic search over card oracle text.

    Args:
        query: Natural language query (e.g. "draw cards when creatures die").
        n_results: Maximum number of results.
        color_identity: If provided, only return cards whose color identity
            is a subset (e.g. ["W", "U", "B"]).
        type_filter: Optional type_line substring filter (e.g. "Creature").

    Returns:
        List of dicts with keys: name, type_line, oracle_text, cmc,
        color_identity, mana_cost, distance.
    """
    if not _rag_ready:
        logger.warning("RAG store not ready — returning empty results.")
        return []

    try:
        collection = _get_collection()
    except Exception as exc:
        logger.error("Failed to get RAG collection: %s", exc)
        return []

    where_filter = None
    if type_filter:
        where_filter = {"type_line": {"$contains": type_filter}}

    try:
        fetch_n = n_results * 3 if color_identity else n_results
        results = collection.query(
            query_texts=[query],
            n_results=min(fetch_n, 50),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.error("RAG query failed: %s", exc)
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    cards: list[dict] = []
    ids = results["ids"][0]
    docs = results["documents"][0] if results.get("documents") else [""] * len(ids)
    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
    dists = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

    for i, card_id in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        doc = docs[i] if i < len(docs) else ""

        if color_identity:
            card_ci_str = meta.get("color_identity", "")
            card_ci = set(card_ci_str.split(",")) if card_ci_str else set()
            deck_ci = set(color_identity)
            if not card_ci.issubset(deck_ci):
                continue

        parts = doc.split(" | ", 2)
        oracle = parts[2] if len(parts) > 2 else parts[-1] if parts else ""

        cards.append({
            "name": meta.get("name", ""),
            "type_line": meta.get("type_line", ""),
            "oracle_text": oracle,
            "cmc": meta.get("cmc", 0),
            "color_identity": meta.get("color_identity", ""),
            "mana_cost": meta.get("mana_cost", ""),
            "distance": round(dists[i], 4) if i < len(dists) else 0.0,
        })
        if len(cards) >= n_results:
            break

    return cards


def get_rag_stats() -> dict:
    """Return metadata about the RAG vector store state."""
    result = {
        "ready": _rag_ready,
        "chroma_dir": str(RAG_CHROMA_DIR),
        "embedding_model": EMBEDDING_MODEL,
        "ollama_url": OLLAMA_BASE_URL,
        "card_count": 0,
        "built_at": None,
        "age_days": None,
    }
    try:
        collection = _get_collection()
        result["card_count"] = collection.count()
        meta = collection.metadata or {}
        built_at = meta.get("built_at")
        if built_at:
            result["built_at"] = built_at
            try:
                age = (time.time() - float(built_at)) / 86400
                result["age_days"] = round(age, 1)
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return result
