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
    ensure_rag_store()             -> None   (build if missing / stale)
    build_index(force, batch_size) -> dict   (explicit build, returns stats)
    query_cards(text, n, colors)   -> list[dict]
    get_rag_stats()                -> dict

Data path:   ./data/rag_chroma/
Embedding:   nomic-embed-text via Ollama (localhost:11434)
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
BATCH_RETRY_LIMIT = 3   # Fix #126: retry failed batches before dropping
BATCH_RETRY_DELAY = 2.0  # seconds between retries (doubles each attempt)
_rag_lock = threading.Lock()
_rag_ready = False

# Module-level singletons to avoid re-creating client/collection on every call
_chroma_client = None
_chroma_collection = None

# ── Phase 2a: Forge behavioral enrichment (optional — graceful if Forge not configured) ──
def _try_import_forge_lookup():
    try:
        from src.commanderailab.sim.forge_card_loader import lookup_forge_card
        return lookup_forge_card
    except ImportError:
        return None

_forge_lookup = _try_import_forge_lookup()

# ── Helpers ────────────────────────────────────────────────────────────────
def _build_document(card: dict) -> str:
    """Build embedding document: Scryfall oracle text + optional Forge behavioral tags."""
    base = build_card_text(card)  # canonical NL text from card_text.py
    if _forge_lookup:
        try:
            forge = _forge_lookup(card.get("name", ""))
            if forge:
                tags: list[str] = []
                if forge.trigger_modes:
                    tags.append("Triggers: " + ", ".join(forge.trigger_modes[:6]))
                if forge.has_replacement_effect:
                    tags.append("Has replacement effect")
                if forge.has_static_ability:
                    tags.append("Has static ability")
                if forge.keywords:
                    tags.append("Keywords: " + ", ".join(forge.keywords[:6]))
                if tags:
                    return base + " " + " ".join(tags)
        except Exception as exc:
            logger.debug("Forge enrichment skipped for %s: %s", card.get("name"), exc)
    return base

def _build_metadata(card: dict) -> dict:
    """Build ChromaDB metadata dict for filtering.

    Core fields always present: name, type_line, cmc, color_identity, rarity, mana_cost
    Forge fields when Forge is configured: has_trigger, has_replacement, has_static, trigger_modes
    """
    ci_raw = card.get("color_identity", "[]")
    if isinstance(ci_raw, str):
        try:
            ci_list = json.loads(ci_raw)
        except (json.JSONDecodeError, TypeError):
            ci_list = []
    else:
        ci_list = ci_raw or []

    meta = {
        "name": card.get("name", ""),
        "type_line": card.get("type_line", ""),
        "cmc": float(card.get("cmc") or 0),
        "color_identity": ",".join(sorted(ci_list)),
        "rarity": card.get("rarity", ""),
        "mana_cost": card.get("mana_cost", ""),
        # Forge behavioral fields — default to 0/empty so filtering is always safe
        "has_trigger": 0,
        "has_replacement": 0,
        "has_static": 0,
        "trigger_modes": "",
    }
    if _forge_lookup:
        try:
            forge = _forge_lookup(card.get("name", ""))
            if forge:
                meta["has_trigger"] = int(bool(forge.trigger_modes))
                meta["has_replacement"] = int(forge.has_replacement_effect)
                meta["has_static"] = int(forge.has_static_ability)
                meta["trigger_modes"] = ",".join(forge.trigger_modes[:8])
        except Exception as exc:
            logger.debug("Forge metadata enrichment skipped for %s: %s", card.get("name"), exc)
    return meta

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
            "Install with: pip install 'commander-ai-lab[rag]'"
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
            "Install with: pip install 'commander-ai-lab[rag]'"
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


def _write_build_meta(card_count: int, forge_coverage: int = 0) -> None:
    """Persist build timestamp, card count, and Forge coverage to sidecar JSON."""
    try:
        RAG_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        BUILD_META_PATH.write_text(
            json.dumps({
                "built_at": time.time(),
                "card_count": card_count,
                "forge_coverage": forge_coverage,
            }),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not write build_meta.json: %s", exc)
    # Fix #127: also persist built_at in ChromaDB collection metadata
    try:
        col = _get_collection()
        col.modify(metadata={"hnsw:space": "cosine", "built_at": time.time()})
    except Exception:
        pass  # best-effort — sidecar is primary


def _collection_is_current(collection, bulk_card_count: int) -> bool:
    """Check if the ChromaDB collection is reasonably up-to-date."""
    chroma_count = collection.count()
    if chroma_count == 0:
        return False
    meta = _read_build_meta()
    built_at = meta.get("built_at", 0)
    # Fix #127: fallback to collection metadata if sidecar is missing
    if not built_at:
        try:
            col_meta = collection.metadata or {}
            built_at = col_meta.get("built_at", 0)
        except Exception:
            pass
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


def _insert_batch_with_retry(collection, ids, docs, metas):
    """Insert a batch into ChromaDB with exponential backoff retry. (Fix #126)"""
    delay = BATCH_RETRY_DELAY
    for attempt in range(1, BATCH_RETRY_LIMIT + 1):
        try:
            collection.add(ids=ids, documents=docs, metadatas=metas)
            return len(ids), 0  # (inserted, failed)
        except Exception as exc:
            if attempt == BATCH_RETRY_LIMIT:
                logger.error(
                    "Batch insert permanently failed after %d attempts (%d cards): %s",
                    BATCH_RETRY_LIMIT, len(ids), exc,
                )
                return 0, len(ids)
            logger.warning(
                "Batch insert attempt %d/%d failed, retrying in %.1fs: %s",
                attempt, BATCH_RETRY_LIMIT, delay, exc,
            )
            time.sleep(delay)
            delay *= 2
    return 0, len(ids)  # unreachable but safe

# ── Build pipeline ────────────────────────────────────────────────────────────────
def _build_collection_from_bulk(batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """Read all cards from the bulk SQLite DB and insert into ChromaDB."""
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
    forge_enriched_count = 0  # Phase 2e: track Forge coverage
    batch_ids: list[str] = []
    batch_docs: list[str] = []
    batch_metas: list[dict] = []
    for row in all_rows:
        # Support both sqlite3.Row (supports dict()) and SimpleNamespace (needs vars())
        card = dict(row) if hasattr(row, "keys") else vars(row)
        doc = _build_document(card)
        if not doc.strip():
            continue
        card_id = card.get("scryfall_id", "")
        if not card_id:
            continue
        meta = _build_metadata(card)
        # Phase 2e: count Forge-enriched cards
        if meta.get("has_trigger") or meta.get("has_replacement") or meta.get("has_static"):
            forge_enriched_count += 1
        batch_ids.append(card_id)
        batch_docs.append(doc)
        batch_metas.append(meta)
        if len(batch_ids) >= batch_size:
            ok, bad = _insert_batch_with_retry(collection, batch_ids, batch_docs, batch_metas)
            inserted += ok
            failed_cards += bad
            if bad:
                failed_batches += 1
            if ok and inserted % 2000 == 0:
                logger.info("  RAG indexed %d / %d cards...", inserted, total_rows)
            batch_ids.clear()
            batch_docs.clear()
            batch_metas.clear()
    if batch_ids:
        ok, bad = _insert_batch_with_retry(collection, batch_ids, batch_docs, batch_metas)
        inserted += ok
        failed_cards += bad
        if bad:
            failed_batches += 1
    logger.info(
        "RAG vector store complete: %d indexed, %d failed (%d batches). Forge-enriched: %d",
        inserted, failed_cards, failed_batches, forge_enriched_count,
    )
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
    _write_build_meta(card_count=inserted, forge_coverage=forge_enriched_count)
    _invalidate_collection_singleton()
    return {"indexed": inserted, "failed": failed_cards}

# ── Public API ────────────────────────────────────────────────────────────────
def build_index(force: bool = False, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """Explicitly build or rebuild the ChromaDB vector index."""
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
    """Build the ChromaDB vector store if it is missing or stale."""
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
                logger.info("RAG vector store is current (%d cards).", collection.count())
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
    require_trigger: Optional[str] = None,
    require_replacement: bool = False,
    require_static: bool = False,
) -> list[dict]:
    """Semantic search over card oracle text.

    Args:
        query: Natural language query.
        n_results: Maximum results returned.
        color_identity: Only return cards within these colors.
        type_filter: Optional type_line substring filter.
        require_trigger: If set, only return cards whose trigger_modes contains this string.
        require_replacement: If True, only return cards with replacement effects.
        require_static: If True, only return cards with static abilities.

    Returns:
        List of dicts: name, type_line, oracle_text, cmc, color_identity, mana_cost,
        distance, trigger_modes (new), has_replacement (new), has_static (new).
    """
    if not _rag_ready:
        logger.warning("RAG store not ready — returning empty results.")
        return []
    try:
        collection = _get_collection()
    except Exception as exc:
        logger.error("Failed to get RAG collection: %s", exc)
        return []

    # Build native ChromaDB where clause for Forge boolean flags
    where_clause: Optional[dict] = None
    forge_filters = []
    if require_replacement:
        forge_filters.append({"has_replacement": {"$eq": 1}})
    if require_static:
        forge_filters.append({"has_static": {"$eq": 1}})
    if len(forge_filters) == 1:
        where_clause = forge_filters[0]
    elif len(forge_filters) > 1:
        where_clause = {"$and": forge_filters}

    try:
        has_filters = bool(color_identity or type_filter or require_trigger)
        fetch_n = n_results * 4 if has_filters else n_results
        query_kwargs = dict(
            query_texts=[query],
            n_results=min(fetch_n, 200),
            include=["documents", "metadatas", "distances"],
        )
        if where_clause:
            query_kwargs["where"] = where_clause
        results = collection.query(**query_kwargs)
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

        # Color identity post-filter (Python-side)
        if color_identity:
            card_ci_str = meta.get("color_identity", "")
            card_ci = set(c for c in card_ci_str.split(",") if c) if card_ci_str else set()
            if not card_ci.issubset(set(color_identity)):
                continue

        # Type post-filter
        if type_filter:
            if type_filter.lower() not in meta.get("type_line", "").lower():
                continue

        # Trigger mode substring post-filter (can't do substring in Chroma where clause)
        if require_trigger:
            tms = meta.get("trigger_modes", "")
            if require_trigger.lower() not in tms.lower():
                continue

        # Parse oracle from document — handle both old pipe format and new NL format
        parts = doc.split(" | ", 3)
        oracle = parts[-1] if len(parts) > 1 else doc

        cards.append({
            "name": meta.get("name", ""),
            "type_line": meta.get("type_line", ""),
            "oracle_text": oracle,
            "cmc": meta.get("cmc", 0),
            "color_identity": meta.get("color_identity", ""),
            "mana_cost": meta.get("mana_cost", ""),
            "distance": round(dists[i], 4) if i < len(dists) else 0.0,
            # New fields — consumers check for presence, not required
            "trigger_modes": meta.get("trigger_modes", ""),
            "has_replacement": bool(meta.get("has_replacement", 0)),
            "has_static": bool(meta.get("has_static", 0)),
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
        "forge_enriched": _forge_lookup is not None,  # Phase 2e
    }
    try:
        collection = _get_collection()
        result["card_count"] = collection.count()
    except Exception:
        pass
    meta = _read_build_meta()
    built_at = meta.get("built_at")
    if built_at:
        result["built_at"] = built_at
        try:
            age = (time.time() - float(built_at)) / 86400
            result["age_days"] = round(age, 1)
        except (ValueError, TypeError):
            pass
    # Phase 2e: report Forge coverage count from sidecar
    result["forge_coverage"] = meta.get("forge_coverage", 0)
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
    """Return staleness info so a background scheduler can trigger rebuilds."""
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


# ── Phase 3: Rules RAG ── second ChromaDB collection (mtgrules) ──────────────────
RULES_COLLECTION_NAME = "mtgrules"
RULES_META_PATH = RAG_CHROMA_DIR / "rules_meta.json"
_rules_collection = None


def _get_rules_collection():
    """Return the mtgrules ChromaDB collection singleton."""
    global _rules_collection
    if _rules_collection is not None:
        return _rules_collection
    client = _get_chromadb_client()
    embed_fn = _get_ollama_embedding_fn()
    _rules_collection = client.get_or_create_collection(
        name=RULES_COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )
    return _rules_collection


def build_rules_index(rules_text_path: str, chunk_size: int = 400) -> dict:
    """Build a rules RAG collection from a plain-text Comprehensive Rules document.

    Chunks the document by rule number boundaries (e.g. 100., 903.),
    embeds each chunk, and inserts into the mtgrules ChromaDB collection.

    Args:
        rules_text_path: Path to MagicCompRules.txt (download from WotC).
        chunk_size: Approximate characters per chunk; splits on rule breaks.

    Returns:
        Dict with keys: indexed (int), failed (int).
    """
    import re
    global _rules_collection

    path = Path(rules_text_path)
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_text_path}")

    text = path.read_text(encoding="utf-8", errors="replace")

    # Split on lines that start with a rule number like 100., 903.4a, etc.
    rule_pattern = re.compile(r"(?m)^\d{3,4}\.")
    raw_chunks = rule_pattern.split(text)

    # Merge very short fragments into the previous chunk
    chunks: list[str] = []
    buffer = ""
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        buffer = buffer + " " + chunk if buffer else chunk
        if len(buffer) >= chunk_size:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        chunks.append(buffer)

    client = _get_chromadb_client()
    embed_fn = _get_ollama_embedding_fn()

    # Drop and recreate for a clean build
    try:
        client.delete_collection(RULES_COLLECTION_NAME)
    except Exception:
        pass
    _rules_collection = None
    collection = client.create_collection(
        name=RULES_COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    inserted = 0
    failed = 0
    batch_ids: list[str] = []
    batch_docs: list[str] = []

    for idx, chunk in enumerate(chunks):
        rule_id_match = re.match(r"[\d\.a-z]+", chunk)
        rule_id = rule_id_match.group(0) if rule_id_match else str(idx)
        batch_ids.append(f"rule-{rule_id}-{idx}")
        batch_docs.append(chunk[:2000])  # hard cap per doc

        if len(batch_ids) >= 100:
            try:
                collection.add(ids=batch_ids, documents=batch_docs)
                inserted += len(batch_ids)
            except Exception as exc:
                failed += len(batch_ids)
                logger.warning("Rules batch insert failed: %s", exc)
            batch_ids.clear()
            batch_docs.clear()

    if batch_ids:
        try:
            collection.add(ids=batch_ids, documents=batch_docs)
            inserted += len(batch_ids)
        except Exception as exc:
            failed += len(batch_ids)
            logger.warning("Rules final batch failed: %s", exc)

    RULES_META_PATH.write_text(
        json.dumps({"built_at": time.time(), "chunk_count": inserted}),
        encoding="utf-8",
    )
    logger.info("Rules RAG: %d chunks indexed, %d failed", inserted, failed)
    return {"indexed": inserted, "failed": failed}


def query_rules(query: str, n_results: int = 5) -> list[dict]:
    """Semantic search over the MTG Comprehensive Rules.

    Returns:
        List of dicts with keys: rule_id, text, distance.
    """
    try:
        collection = _get_rules_collection()
        if collection.count() == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, 20),
            include=["documents", "distances"],
        )
    except Exception as exc:
        logger.error("Rules RAG query failed: %s", exc)
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    out = []
    for i, doc_id in enumerate(results["ids"][0]):
        out.append({
            "rule_id": doc_id,
            "text": results["documents"][0][i] if results.get("documents") else "",
            "distance": round(results["distances"][0][i], 4) if results.get("distances") else 0.0,
        })
    return out
