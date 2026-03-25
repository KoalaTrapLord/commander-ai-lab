"""
Commander AI Lab — MTG Card Embeddings Index
═════════════════════════════════════════════
Loads pre-computed card embeddings from minimaxir/mtg-embeddings
(Hugging Face) and provides vector similarity search with
metadata filtering (color identity, type, mana value).

Data source: https://huggingface.co/datasets/minimaxir/mtg-embeddings
Format: Parquet with 768-dim float32 embeddings per card (~32K cards)
Model: Alibaba-NLP/gte-modernbert-base

Unknown cards (e.g. newly printed sets) are fetched from Scryfall,
embedded on-the-fly using the same model, and persisted to a local
custom cache (embeddings/mtg_embeddings_custom.npz) so they survive
restarts without re-hitting Scryfall.

Uses NumPy brute-force cosine similarity — fast enough for ~32K cards (<100ms).
"""

import json
import logging
import re
import os
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.parse import quote

import numpy as np

from .config import EMBEDDINGS_DIR, EMBEDDINGS_NPZ, EMBEDDINGS_PARQUET

logger = logging.getLogger("coach.embeddings")

# ── HuggingFace download URL ───────────────────────────────
HF_PARQUET_URL = (
    "https://huggingface.co/datasets/minimaxir/mtg-embeddings/"
    "resolve/main/mtg_embeddings.parquet"
)

# ── Scryfall API ───────────────────────────────────────────
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named?fuzzy={}"

# ── Custom cache for on-the-fly embedded cards ─────────────
CUSTOM_CACHE_PATH = EMBEDDINGS_DIR / "mtg_embeddings_custom.npz"

# ── Embedding model (same as minimaxir/mtg-embeddings) ─────
EMBEDDING_MODEL = "Alibaba-NLP/gte-modernbert-base"

# ── Color identity parsing ─────────────────────────────────
MANA_SYMBOL_COLORS = {
    "W": "W", "U": "U", "B": "B", "R": "R", "G": "G"
}


def _parse_color_identity(mana_cost: str) -> str:
    """Extract color identity string from mana cost like '{2}{W}{U}'."""
    if not mana_cost:
        return ""
    colors = set()
    for match in re.finditer(r'\{([WUBRG])\}', mana_cost or ""):
        colors.add(match.group(1))
    order = "WUBRG"
    return "".join(c for c in order if c in colors)


def _parse_mana_value(mana_cost: str) -> float:
    """Compute converted mana cost from mana cost string."""
    if not mana_cost:
        return 0.0
    total = 0.0
    for match in re.finditer(r'\{([^}]+)\}', mana_cost or ""):
        symbol = match.group(1)
        if symbol in MANA_SYMBOL_COLORS:
            total += 1.0
        elif symbol == "X":
            pass
        else:
            try:
                total += float(symbol)
            except ValueError:
                total += 1.0
    return total


def _is_color_subset(card_colors: str, deck_colors: List[str]) -> bool:
    """Check if card's color identity is within deck's color identity."""
    deck_set = set(deck_colors)
    card_set = set(card_colors)
    return card_set.issubset(deck_set) or len(card_set) == 0


def _fetch_scryfall_card(card_name: str) -> Optional[dict]:
    """Fetch card data from Scryfall by fuzzy name match.

    Returns a dict with keys: name, mana_cost, type_line, oracle_text,
    color_identity. Returns None on any error.
    """
    url = SCRYFALL_NAMED_URL.format(quote(card_name))
    try:
        req = Request(url, headers={"User-Agent": "commander-ai-lab/1.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "name": data.get("name", card_name),
            "mana_cost": data.get("mana_cost", ""),
            "type_line": data.get("type_line", ""),
            "oracle_text": data.get("oracle_text", ""),
            "color_identity": "".join(data.get("color_identity", [])),
        }
    except Exception as e:
        logger.warning("Scryfall lookup failed for '%s': %s", card_name, e)
        return None


def _build_card_text(card: dict) -> str:
    """Build the text string to embed, matching minimaxir/mtg-embeddings format."""
    parts = [card["name"]]
    if card.get("mana_cost"):
        parts.append(card["mana_cost"])
    if card.get("type_line"):
        parts.append(card["type_line"])
    if card.get("oracle_text"):
        parts.append(card["oracle_text"])
    return " | ".join(parts)


class CardMatch:
    """Result from an embedding similarity search."""
    def __init__(self, name: str, similarity: float, types: str = "",
                 mana_value: float = 0, color_identity: str = "",
                 mana_cost: str = "", text: str = ""):
        self.name = name
        self.similarity = similarity
        self.types = types
        self.mana_value = mana_value
        self.color_identity = color_identity
        self.mana_cost = mana_cost
        self.text = text

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "similarity": round(self.similarity, 4),
            "types": self.types,
            "mana_value": self.mana_value,
            "color_identity": self.color_identity,
            "mana_cost": self.mana_cost,
            "text": self.text[:200] if self.text else "",
        }


class MTGEmbeddingIndex:
    """
    In-memory index of MTG card embeddings for similarity search.

    Usage:
        index = MTGEmbeddingIndex()
        index.load()
        matches = index.search_similar("Sol Ring", top_n=10)
    """

    def __init__(self):
        self.names: np.ndarray = None
        self.colors: np.ndarray = None
        self.mana_values: np.ndarray = None
        self.types: np.ndarray = None
        self.mana_costs: np.ndarray = None
        self.texts: np.ndarray = None
        self.vectors: np.ndarray = None
        self._name_to_idx: dict = {}
        self._loaded = False
        self._sentence_model = None   # lazy-loaded only when needed
        self._custom_dirty = False    # tracks whether custom cache needs saving

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def card_count(self) -> int:
        return len(self.names) if self.names is not None else 0

    def download_parquet(self, force: bool = False) -> Path:
        """Download the mtg-embeddings parquet file from HuggingFace."""
        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

        if EMBEDDINGS_PARQUET.exists() and not force:
            logger.info("Parquet already exists: %s", EMBEDDINGS_PARQUET)
            return EMBEDDINGS_PARQUET

        logger.info("Downloading mtg-embeddings from HuggingFace...")
        req = Request(HF_PARQUET_URL, headers={"User-Agent": "commander-ai-lab/1.0"})
        with urlopen(req, timeout=120) as resp:
            data = resp.read()

        with open(EMBEDDINGS_PARQUET, "wb") as f:
            f.write(data)
        logger.info("Downloaded %.1f MB to %s",
                     len(data) / 1024 / 1024, EMBEDDINGS_PARQUET)
        return EMBEDDINGS_PARQUET

    def convert_parquet_to_npz(self) -> Path:
        """Convert the Parquet file to a compact NPZ for fast loading."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas is required: pip install pandas pyarrow")

        logger.info("Converting parquet to NPZ...")
        df = pd.read_parquet(str(EMBEDDINGS_PARQUET))

        names = df["name"].values.astype(str)
        mana_costs = df["manaCost"].fillna("").values.astype(str)
        types = df["type"].fillna("").values.astype(str)
        texts = df["text"].fillna("").values.astype(str)

        colors = np.array([_parse_color_identity(mc) for mc in mana_costs])
        mana_values = np.array([_parse_mana_value(mc) for mc in mana_costs], dtype=np.float32)

        embeddings = np.vstack(df["embedding"].to_numpy()).astype(np.float32)

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms

        np.savez_compressed(
            str(EMBEDDINGS_NPZ),
            names=names,
            colors=colors,
            mana_values=mana_values,
            types=types,
            mana_costs=mana_costs,
            texts=texts,
            vectors=embeddings,
        )

        size_mb = os.path.getsize(EMBEDDINGS_NPZ) / 1024 / 1024
        logger.info("Saved NPZ: %d cards, %.1f MB at %s",
                     len(names), size_mb, EMBEDDINGS_NPZ)
        return EMBEDDINGS_NPZ

    def load(self, force_download: bool = False) -> bool:
        """Load embeddings from NPZ (fast) or fall back to downloading
        and converting from Parquet.
        """
        if self._loaded and not force_download:
            return True

        if EMBEDDINGS_NPZ.exists() and not force_download:
            ok = self._load_npz()
        else:
            try:
                self.download_parquet(force=force_download)
                self.convert_parquet_to_npz()
                ok = self._load_npz()
            except Exception as e:
                logger.error("Failed to load embeddings: %s", e)
                return False

        if ok:
            self._load_custom_cache()

        return ok

    def _load_npz(self) -> bool:
        """Load from pre-built NPZ file."""
        try:
            data = np.load(str(EMBEDDINGS_NPZ), allow_pickle=True)
            self.names = data["names"]
            self.colors = data["colors"]
            self.mana_values = data["mana_values"]
            self.types = data["types"]
            self.mana_costs = data.get("mana_costs", np.array([""] * len(self.names)))
            self.texts = data.get("texts", np.array([""] * len(self.names)))
            self.vectors = data["vectors"]

            self._name_to_idx = {
                name.lower(): i for i, name in enumerate(self.names)
            }
            self._loaded = True
            logger.info("Loaded %d card embeddings from NPZ", len(self.names))
            return True
        except Exception as e:
            logger.error("Failed to load NPZ: %s", e)
            return False

    # ── Custom cache ──────────────────────────────────────────

    def _load_custom_cache(self) -> None:
        """Merge on-the-fly embedded cards from the custom cache into the index."""
        if not CUSTOM_CACHE_PATH.exists():
            return
        try:
            data = np.load(str(CUSTOM_CACHE_PATH), allow_pickle=True)
            c_names = data["names"]
            # Only add cards that aren't already in the main index
            new_mask = np.array(
                [n.lower() not in self._name_to_idx for n in c_names]
            )
            if not new_mask.any():
                return
            self._append_cards(
                c_names[new_mask],
                data["colors"][new_mask],
                data["mana_values"][new_mask],
                data["types"][new_mask],
                data["mana_costs"][new_mask],
                data["texts"][new_mask],
                data["vectors"][new_mask],
            )
            logger.info("Loaded %d custom-cached card embeddings", new_mask.sum())
        except Exception as e:
            logger.warning("Failed to load custom embedding cache: %s", e)

    def _save_custom_cache(self) -> None:
        """Persist the custom cache NPZ (only cards not in the base dataset)."""
        if not self._custom_dirty:
            return
        try:
            EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
            # Collect indices that correspond to custom-added cards
            # We track these by loading the base count at load time — simpler:
            # just re-save the full custom cache from CUSTOM_CACHE_PATH if it
            # exists, merging with any new cards we've added this session.
            existing_names: set = set()
            existing: dict = {}
            if CUSTOM_CACHE_PATH.exists():
                try:
                    d = np.load(str(CUSTOM_CACHE_PATH), allow_pickle=True)
                    for n in d["names"]:
                        existing_names.add(n.lower())
                    existing = dict(d)
                except Exception:
                    pass

            # Find names in our live index that aren't in the base NPZ
            base_data = np.load(str(EMBEDDINGS_NPZ), allow_pickle=True)
            base_names = set(n.lower() for n in base_data["names"])
            custom_mask = np.array(
                [n.lower() not in base_names for n in self.names]
            )
            if not custom_mask.any():
                return

            np.savez_compressed(
                str(CUSTOM_CACHE_PATH),
                names=self.names[custom_mask],
                colors=self.colors[custom_mask],
                mana_values=self.mana_values[custom_mask],
                types=self.types[custom_mask],
                mana_costs=self.mana_costs[custom_mask],
                texts=self.texts[custom_mask],
                vectors=self.vectors[custom_mask],
            )
            self._custom_dirty = False
            logger.info("Saved custom embedding cache: %d cards", custom_mask.sum())
        except Exception as e:
            logger.warning("Failed to save custom embedding cache: %s", e)

    def _append_cards(
        self,
        names: np.ndarray,
        colors: np.ndarray,
        mana_values: np.ndarray,
        types: np.ndarray,
        mana_costs: np.ndarray,
        texts: np.ndarray,
        vectors: np.ndarray,
    ) -> None:
        """Append new card arrays to the live in-memory index."""
        start_idx = len(self.names)
        self.names = np.concatenate([self.names, names])
        self.colors = np.concatenate([self.colors, colors])
        self.mana_values = np.concatenate([self.mana_values, mana_values])
        self.types = np.concatenate([self.types, types])
        self.mana_costs = np.concatenate([self.mana_costs, mana_costs])
        self.texts = np.concatenate([self.texts, texts])
        self.vectors = np.concatenate([self.vectors, vectors], axis=0)
        for i, name in enumerate(names):
            self._name_to_idx[name.lower()] = start_idx + i

    # ── Sentence model (lazy) ─────────────────────────────────

    def _get_sentence_model(self):
        """Lazy-load the sentence-transformers model on first cache miss."""
        if self._sentence_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("Loading embedding model %s (first cache miss)...", EMBEDDING_MODEL)
                self._sentence_model = SentenceTransformer(EMBEDDING_MODEL)
                logger.info("Embedding model loaded.")
            except Exception as e:
                logger.error("Failed to load SentenceTransformer: %s", e)
                return None
        return self._sentence_model

    # ── On-the-fly Scryfall fallback ──────────────────────────

    def _fetch_and_embed_card(self, card_name: str) -> Optional[np.ndarray]:
        """Fetch card from Scryfall, embed it, append to index, persist to cache.

        Returns the L2-normalized embedding vector on success, None on failure.
        """
        logger.info("Fetching unknown card from Scryfall: '%s'", card_name)
        card_data = _fetch_scryfall_card(card_name)
        if card_data is None:
            return None

        model = self._get_sentence_model()
        if model is None:
            return None

        text = _build_card_text(card_data)
        vec = model.encode(text, normalize_embeddings=True).astype(np.float32)
        # Ensure shape (1, 768)
        vec = vec.reshape(1, -1)

        resolved_name = card_data["name"]
        mana_cost = card_data.get("mana_cost", "")
        color_identity = card_data.get("color_identity", "") or _parse_color_identity(mana_cost)

        self._append_cards(
            names=np.array([resolved_name]),
            colors=np.array([color_identity]),
            mana_values=np.array([_parse_mana_value(mana_cost)], dtype=np.float32),
            types=np.array([card_data.get("type_line", "")]),
            mana_costs=np.array([mana_cost]),
            texts=np.array([card_data.get("oracle_text", "")]),
            vectors=vec,
        )

        self._custom_dirty = True
        self._save_custom_cache()
        logger.info("Embedded and cached new card: '%s'", resolved_name)
        return self.vectors[self._name_to_idx[resolved_name.lower()]]

    # ── Public API ────────────────────────────────────────────

    def get_card_vector(self, card_name: str) -> Optional[np.ndarray]:
        """Get the embedding vector for a card by name (case-insensitive).

        On a cache miss, fetches from Scryfall and embeds on the fly.
        """
        idx = self._name_to_idx.get(card_name.lower())
        if idx is not None:
            return self.vectors[idx]

        # Cache miss — try Scryfall fallback
        return self._fetch_and_embed_card(card_name)

    def search_similar(self, query_card: str,
                       color_filter: List[str] = None,
                       type_filter: str = None,
                       mana_range: Tuple[float, float] = None,
                       exclude_cards: List[str] = None,
                       top_n: int = 20) -> List[CardMatch]:
        """
        Find the most similar cards to query_card.

        Args:
            query_card: Card name to find similar cards for
            color_filter: Only return cards within these colors (e.g., ["W", "U", "B"])
            type_filter: Filter by type substring (e.g., "Creature", "Instant")
            mana_range: (min_mv, max_mv) mana value range
            exclude_cards: Card names to exclude from results
            top_n: Number of results to return

        Returns:
            List of CardMatch objects sorted by similarity (descending)
        """
        if not self._loaded:
            logger.warning("Embeddings not loaded, call load() first")
            return []

        query_vec = self.get_card_vector(query_card)
        if query_vec is None:
            logger.warning("Card not found in embeddings and Scryfall fallback failed: %s", query_card)
            return []

        similarities = self.vectors @ query_vec

        exclude_set = set()
        exclude_set.add(query_card.lower())
        if exclude_cards:
            exclude_set.update(name.lower() for name in exclude_cards)

        results = []
        for idx in np.argsort(similarities)[::-1]:
            name = str(self.names[idx])
            if name.lower() in exclude_set:
                continue

            if color_filter:
                card_colors = str(self.colors[idx])
                if not _is_color_subset(card_colors, color_filter):
                    continue

            if type_filter:
                card_type = str(self.types[idx])
                if type_filter.lower() not in card_type.lower():
                    continue

            if mana_range:
                mv = float(self.mana_values[idx])
                if mv < mana_range[0] or mv > mana_range[1]:
                    continue

            results.append(CardMatch(
                name=name,
                similarity=float(similarities[idx]),
                types=str(self.types[idx]),
                mana_value=float(self.mana_values[idx]),
                color_identity=str(self.colors[idx]),
                mana_cost=str(self.mana_costs[idx]) if self.mana_costs is not None else "",
                text=str(self.texts[idx]) if self.texts is not None else "",
            ))

            if len(results) >= top_n:
                break

        return results

    def find_replacements(self, underperformer: str,
                          deck_colors: List[str],
                          deck_card_names: List[str] = None,
                          role_tag: str = None,
                          top_n: int = 10) -> List[CardMatch]:
        """
        Find replacement candidates for an underperforming card.

        Args:
            underperformer: Card name to replace
            deck_colors: Deck's color identity (e.g., ["W", "U", "B"])
            deck_card_names: All card names currently in the deck (excluded from results)
            role_tag: Optional type/role filter
            top_n: Number of candidates to return
        """
        return self.search_similar(
            query_card=underperformer,
            color_filter=deck_colors,
            type_filter=role_tag,
            exclude_cards=deck_card_names,
            top_n=top_n,
        )
