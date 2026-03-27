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
    build_index(force, batch_size) -> dict (explicit build, returns stats)
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
from services.card_text import build_card_text
from pathlib import Path
from typing import Optional

logger = logging.getLogger("commander_ai_lab.rag_store")

# ── Config ────────────────────────────────────────────────────────────────
RAG_CHROMA_DIR = Path(__file__).parent.parent / "data" / "rag_chroma"
BUILD_META_PATH = RAG_CHROMA_DIR / "build_meta.json"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "nomic-embed-text")
COLLECTION_NAME = "mtg_oracle"
DEFAULT_BATCH_SIZE = 500
_rag_lock = threading.Lock()
_rag_ready = False

# Module-level singletons to avoid re-creating client/collection on every call
_chroma_client = None
_chroma_collection = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _build_document(card: dict) -> str:
    """Delegate to shared build_card_text() -- see services/card_text.py."""
    return build_card_text(card)


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
    """Return the module-level persistent ChromaDB client (singleton)."""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client
    try:
        import chromadb
    except ImportError:
        raise ImportError(
            "chromadb is required for RAG Phase 2. "
            "Install with:  pip install 'commander-ai-lab[rag]'"
        )
    RAG_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _chroma_client = chromadb.PersistentClient(path=str(RAG_CHROMA_DIR))
    return _chroma_client


def _get_ollama_embedding_fn():
    """Return a ChromaDB-compatible embedding function using Ollama."""
    try:
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    except ImportError:
        raise ImportError(
            "chromadb >= 0.4.0 with Ollama support is required. "
            "Install with:  pip install 'commander-ai-lab[rag]'"
        )
    return OllamaEmbeddingFunction(
        url=f"{OLLAMA_BASE_URL}/api/embeddings",
        model_name=EMBEDDING_MODEL,
    )


def _get_collection():
    """Return the ChromaDB collection singleton, creating it if needed."""
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    client = _get_chromadb_client()
    embed_fn = _get_ollama_embedding_fn()
    _chroma_collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )
    return _chroma_collection


def _invalidate_collection_singleton() -> None:
    """Reset the cached collection after a rebuild so the next call re-opens it."""
    global _chroma_collection
    _chroma_collection = None


def _read_build_meta() -> dict:
    """Read the sidecar build_meta.json, returning {} if missing or corrupt."""
    try:
        if BUILD_META_PATH.exists():
            return json.loads(BUILD_META_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read build_meta.json: %s", exc)
    return {}


def _write_build_meta(card_count: int) -> None:
    """Persist build timestamp and card count to sidecar JSON file."""
    try:
        RAG_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        BUILD_META_PATH.write_text(
            json.dumps({"built_at": time.time(), "card_count": card_count}),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not write build_meta.json: %s", exc)


def _collection_is_current(collection, bulk_card_count: int) -> bool:
    """Check if the ChromaDB collection is reasonably up-to-date.

    Uses sidecar build_meta.json for the age check (survives restarts),
    and compares card count within a 5% tolerance.
    """
    chroma_count = collection.count()
    if chroma_count == 0:
        return False

    # Age check via sidecar file (not collection.metadata which doesn't persist)
    meta = _read_build_meta()
    built_at = meta.get("built_at", 0)
    if built_at:
        age_days = (time.time() - float(built_at)) / 86400
        if age_days > 14:
            logger.info("RAG collection older than 14 days (%0.1f) — rebuilding.", age_days)
            return False

    ratio = chroma_count / max(bulk_card_count, 1)
    if ratio < 0.95 or ratio > 1.05:
        logger.info(
            "RAG collection count mismatch: chroma=%d, bulk=%d — rebuilding.",
            chroma_count, bulk_card_count,
        )
        return False
    return True


# ── Build pipeline ────────────────────────────────────────────────────────────────

def _build_collection_from_bulk(batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """Read all cards from the bulk SQLite DB and insert into ChromaDB.

    Args:
        batch_size: Number of cards to embed and insert per ChromaDB call.

    Returns:
        Dict with keys: indexed (int), failed (int).

    Raises:
        RuntimeError: If more than 1% of cards failed to insert.
    """
    from services.scryfall_bulk import get_bulk_db

    conn = get_bulk_db()
    cursor = conn.execute(
        "SELECT name, oracle_text, type_line, mana_cost, cmc, "
        "color_identity, rarity, scryfall_id FROM cards "
        "WHERE oracle_text != '' "
        "ORDER BY edhrec_rank ASC"
    )
    all_rows = cursor.fetchall()
    total_rows = len(all_rows)

    client = _get_chromadb_client()
    embed_fn = _get_ollama_embedding_fn()

    # Drop and recreate collection to ensure a clean build
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _invalidate_collection_singleton()

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    inserted = 0
    failed_cards = 0
    failed_batches = 0
    batch_ids: list[str] = []
    batch_docs: list[str] = []
    batch_metas: list[dict] = []

    for row in all_rows:
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

        if len(batch_ids) >= batch_size:
            try:
                collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                )
                inserted += len(batch_ids)
                if inserted % 2000 == 0:
                    logger.info("  RAG indexed %d / %d cards...", inserted, total_rows)
            except Exception as exc:
                failed_cards += len(batch_ids)
                failed_batches += 1
                logger.warning(
                    "RAG batch insert failed (batch #%d, %d cards lost): %s",
                    failed_batches, len(batch_ids), exc,
                )
            batch_ids.clear()
            batch_docs.clear()
            batch_metas.clear()

    # Final partial batch
    if batch_ids:
        try:
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            inserted += len(batch_ids)
        except Exception as exc:
            failed_cards += len(batch_ids)
            failed_batches += 1
            logger.warning("RAG final batch insert failed: %s", exc)

    logger.info(
        "RAG vector store complete: %d indexed, %d failed (%d batches).",
        inserted, failed_cards, failed_batches,
    )

    # Abort if failure rate exceeds 1% — delete partial collection
    if total_rows > 0 and (failed_cards / total_rows) > 0.01:
        logger.error(
            "RAG build failure rate %.1f%% exceeds 1%% threshold — deleting partial collection.",
            100.0 * failed_cards / total_rows,
        )
        try:
            client.delete_collection(COLLECTION_NAME)
            _invalidate_collection_singleton()
        except Exception:
            pass
        raise RuntimeError(
            f"RAG build aborted: {failed_cards}/{total_rows} cards failed to insert. "
            "Check Ollama connectivity and retry."
        )

    _write_build_meta(card_count=inserted)
    # Invalidate singleton so next _get_collection() picks up the new collection
    _invalidate_collection_singleton()
    return {"indexed": inserted, "failed": failed_cards}


# ── Public API ────────────────────────────────────────────────────────────────

def build_index(force: bool = False, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """Explicitly build or rebuild the ChromaDB vector index.

    This is the function called by POST /api/rag/build.
    Unlike ensure_rag_store(), this always runs (no _rag_ready short-circuit)
    and returns stats so the API can surface them to the caller.

    Args:
        force: If True, rebuild even if the index appears current.
        batch_size: Cards per ChromaDB insert batch (default 500).

    Returns:
        Dict with keys: indexed (int), failed (int).
    """
    global _rag_ready
    with _rag_lock:
        if not force:
            try:
                from services.scryfall_bulk import get_stats as bulk_stats
                stats = bulk_stats()
                bulk_count = stats.get("card_count", 0)
                collection = _get_collection()
                if _collection_is_current(collection, bulk_count):
                    logger.info("RAG index is current — skipping rebuild (use force=True to override).")
                    return {"indexed": collection.count(), "failed": 0, "skipped": True}
            except Exception:
                pass

        result = _build_collection_from_bulk(batch_size=batch_size)
        _rag_ready = True
        return result


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
            Applied as a post-query Python filter for ChromaDB compatibility.

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

    try:
        # Fetch extra results to account for post-query color/type filtering
        fetch_n = n_results * 4 if (color_identity or type_filter) else n_results
        results = collection.query(
            query_texts=[query],
            n_results=min(fetch_n, 200),
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

        # Color identity post-filter (Python-side for ChromaDB compat)
        if color_identity:
            card_ci_str = meta.get("color_identity", "")
            card_ci = set(c for c in card_ci_str.split(",") if c) if card_ci_str else set()
            deck_ci = set(color_identity)
            if not card_ci.issubset(deck_ci):
                continue

        # Type post-filter
        if type_filter:
            card_type = meta.get("type_line", "")
            if type_filter.lower() not in card_type.lower():
                continue

        # Document format: Name | Mana Cost | Type | Oracle Text
        parts = doc.split(" | ", 3)
        oracle = parts[3] if len(parts) > 3 else (parts[-1] if parts else "")

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
    except Exception:
        pass

    # Read age from sidecar file (persists across restarts)
    meta = _read_build_meta()
    built_at = meta.get("built_at")
    if built_at:
        result["built_at"] = built_at
        try:
            age = (time.time() - float(built_at)) / 86400
            result["age_days"] = round(age, 1)
        except (ValueError, TypeError):
            pass

    return result


def is_chroma_available() -> bool:
    """Check whether ChromaDB + Ollama are reachable without side effects."""
    try:
        _get_chromadb_client()
    except Exception:
        return False
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/tags",
            headers={"User-Agent": "commander-ai-lab/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        return False
    return True


def check_staleness() -> dict:
    """Return staleness info so a background scheduler can trigger rebuilds.

    Returns dict with keys:
        stale (bool): True if the index should be rebuilt.
        reason (str): Human-readable explanation.
        age_days (float | None): Age of the current build in days.
    """
    meta = _read_build_meta()
    built_at = meta.get("built_at")
    if not built_at:
        return {"stale": True, "reason": "no build metadata found", "age_days": None}
    try:
        age_days = (time.time() - float(built_at)) / 86400
    except (ValueError, TypeError):
        return {"stale": True, "reason": "corrupt build timestamp", "age_days": None}
    if age_days > 14:
        return {"stale": True, "reason": f"index is {age_days:.1f} days old (>14)", "age_days": round(age_days, 1)}
    try:
        from services.scryfall_bulk import get_stats as bulk_stats
        bulk_count = bulk_stats().get("card_count", 0)
        collection = _get_collection()
        chroma_count = collection.count()
        ratio = chroma_count / max(bulk_count, 1)
        if ratio < 0.95 or ratio > 1.05:
            return {
                "stale": True,
                "reason": f"card count drift: chroma={chroma_count}, bulk={bulk_count}",
                "age_days": round(age_days, 1),
            }
    except Exception as exc:
        logger.warning("check_staleness card count check failed: %s", exc)
    return {"stale": False, "reason": "index is current", "age_days": round(age_days, 1)}
