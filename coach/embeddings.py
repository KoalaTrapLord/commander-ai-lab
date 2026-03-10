"""
Commander AI Lab — MTG Card Embeddings Index
═════════════════════════════════════════════
Loads pre-computed card embeddings from minimaxir/mtg-embeddings
(Hugging Face) and provides vector similarity search with
metadata filtering (color identity, type, mana value).

Data source: https://huggingface.co/datasets/minimaxir/mtg-embeddings
Format: Parquet with 768-dim float32 embeddings per card (~32K cards)
Model: Alibaba-NLP/gte-modernbert-base

Uses NumPy brute-force cosine similarity — fast enough for ~32K cards (<100ms).
"""

import json
import logging
import re
import os
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.request import urlopen, Request

import numpy as np

from .config import EMBEDDINGS_DIR, EMBEDDINGS_NPZ, EMBEDDINGS_PARQUET

logger = logging.getLogger("coach.embeddings")

# ── HuggingFace download URL ───────────────────────────────
HF_PARQUET_URL = (
    "https://huggingface.co/datasets/minimaxir/mtg-embeddings/"
    "resolve/main/mtg_embeddings.parquet"
)

# ── Color identity parsing ─────────────────────────────────
# Maps mana symbols like {W}, {U}, {B}, {R}, {G} to color letters
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
    # Sort in WUBRG order
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
            pass  # X = 0 for CMC purposes
        else:
            try:
                total += float(symbol)
            except ValueError:
                # Hybrid/phyrexian symbols count as 1
                total += 1.0
    return total


def _is_color_subset(card_colors: str, deck_colors: List[str]) -> bool:
    """Check if card's color identity is within deck's color identity."""
    deck_set = set(deck_colors)
    card_set = set(card_colors)
    return card_set.issubset(deck_set) or len(card_set) == 0  # colorless always allowed


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
        self.names: np.ndarray = None       # (N,) string array
        self.colors: np.ndarray = None      # (N,) string array (e.g., "WU", "BRG")
        self.mana_values: np.ndarray = None # (N,) float array
        self.types: np.ndarray = None       # (N,) string array
        self.mana_costs: np.ndarray = None  # (N,) string array
        self.texts: np.ndarray = None       # (N,) string array
        self.vectors: np.ndarray = None     # (N, 768) float32, L2-normalized
        self._name_to_idx: dict = {}
        self._loaded = False

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
        """
        Convert the Parquet file to a compact NPZ for fast loading.
        Requires pandas and pyarrow.
        """
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

        # Parse color identities from mana costs
        colors = np.array([_parse_color_identity(mc) for mc in mana_costs])
        mana_values = np.array([_parse_mana_value(mc) for mc in mana_costs], dtype=np.float32)

        # Extract embedding vectors
        embeddings = np.vstack(df["embedding"].to_numpy()).astype(np.float32)

        # L2 normalize for cosine similarity via dot product
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
        """
        Load embeddings from NPZ (fast) or fall back to downloading
        and converting from Parquet.
        """
        if self._loaded and not force_download:
            return True

        # Try NPZ first (fast path)
        if EMBEDDINGS_NPZ.exists() and not force_download:
            return self._load_npz()

        # Download and convert
        try:
            self.download_parquet(force=force_download)
            self.convert_parquet_to_npz()
            return self._load_npz()
        except Exception as e:
            logger.error("Failed to load embeddings: %s", e)
            return False

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

            # Build name lookup
            self._name_to_idx = {
                name.lower(): i for i, name in enumerate(self.names)
            }
            self._loaded = True
            logger.info("Loaded %d card embeddings from NPZ", len(self.names))
            return True
        except Exception as e:
            logger.error("Failed to load NPZ: %s", e)
            return False

    def get_card_vector(self, card_name: str) -> Optional[np.ndarray]:
        """Get the embedding vector for a card by name (case-insensitive)."""
        idx = self._name_to_idx.get(card_name.lower())
        if idx is not None:
            return self.vectors[idx]
        return None

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
            logger.warning("Card not found in embeddings: %s", query_card)
            return []

        # Compute similarities (dot product on normalized vectors = cosine similarity)
        similarities = self.vectors @ query_vec

        # Build exclusion set
        exclude_set = set()
        exclude_set.add(query_card.lower())
        if exclude_cards:
            exclude_set.update(name.lower() for name in exclude_cards)

        # Filter and collect results
        results = []
        for idx in np.argsort(similarities)[::-1]:
            name = str(self.names[idx])
            if name.lower() in exclude_set:
                continue

            # Color filter
            if color_filter:
                card_colors = str(self.colors[idx])
                if not _is_color_subset(card_colors, color_filter):
                    continue

            # Type filter
            if type_filter:
                card_type = str(self.types[idx])
                if type_filter.lower() not in card_type.lower():
                    continue

            # Mana value range filter
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
