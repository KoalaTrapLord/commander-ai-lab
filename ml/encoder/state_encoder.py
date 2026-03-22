"""
Commander AI Lab — State Encoder
═════════════════════════════════
Converts raw decision snapshots (JSONL) into fixed-size tensor vectors
suitable for neural network input.

Pipeline:
  1. Load card embeddings from mtg-embeddings (768-dim, ~32K cards)
  2. For each decision snapshot:
     a. Encode global features (life, mana, turn, phase, etc.)
     b. For each zone per player: mean-pool card embeddings
     c. Encode playstyle as one-hot vector
     d. Concatenate into single fixed-length vector

Output dimensions:
  global_features (29) + zone_embeddings (6144) + playstyle (4) = 6177
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("ml.encoder")

# Import scope config
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from ml.config.scope import (
    STATE_DIMS, PLAYSTYLE_TO_IDX, PHASE_TO_IDX,
    Playstyle, GamePhase, GAME_SCOPE,
)


class CardEmbeddingIndex:
    """
    Loads and caches card embeddings from the minimaxir/mtg-embeddings dataset.
    Provides name → 768-dim vector lookup.

    Uses the same NPZ cache as coach/embeddings.py for consistency.
    """

    def __init__(self, embeddings_dir: str = None):
        self.embeddings_dir = embeddings_dir or str(
            Path(__file__).parent.parent.parent / "embeddings"
        )
        self._name_to_idx: Dict[str, int] = {}
        self._embeddings: Optional[np.ndarray] = None
        self._names: List[str] = []
        self._loaded = False
        self._zero_vec = np.zeros(STATE_DIMS.card_embedding_dim, dtype=np.float32)

    def load(self) -> bool:
        """Load embeddings from NPZ cache.

        Searches multiple known locations and handles two NPZ formats:
          - Coach format: keys 'vectors', 'names' (saved by coach/embeddings.py)
          - ML format: keys 'embeddings', 'names' (legacy)

        If no NPZ is found anywhere, auto-downloads from HuggingFace via
        the coach embedding index and converts to NPZ.
        """
        project_root = Path(__file__).parent.parent.parent
        candidates = [
            str(project_root / "data" / "mtg-embeddings.npz"),
            str(project_root / "data" / "mtg_embeddings.npz"),
            os.path.join(self.embeddings_dir, "mtg_embeddings.npz"),
            os.path.join(self.embeddings_dir, "mtg-embeddings.npz"),
            str(project_root / "embeddings" / "mtg_embeddings.npz"),
            str(project_root / "embeddings" / "mtg-embeddings.npz"),
        ]
        npz_path = None
        for candidate in candidates:
            if os.path.exists(candidate):
                npz_path = candidate
                break

        # Auto-download if nothing found
        if not npz_path:
            logger.info("Embeddings NPZ not found — attempting auto-download...")
            npz_path = self._auto_download(project_root)
            if not npz_path:
                return False

        try:
            data = np.load(npz_path, allow_pickle=True)
            # Handle both NPZ formats:
            #   Coach format has 'vectors', ML legacy has 'embeddings'
            if "vectors" in data:
                self._embeddings = data["vectors"].astype(np.float32)
            elif "embeddings" in data:
                self._embeddings = data["embeddings"].astype(np.float32)
            else:
                logger.error("NPZ at %s has no 'vectors' or 'embeddings' key. Keys: %s",
                             npz_path, list(data.keys()))
                return False
            self._names = list(data["names"])
            self._name_to_idx = {
                name.lower(): i for i, name in enumerate(self._names)
            }
            self._loaded = True
            logger.info(
                "Loaded %d card embeddings (%d-dim) from %s",
                len(self._names), self._embeddings.shape[1], npz_path,
            )
            return True
        except Exception as e:
            logger.error("Failed to load embeddings: %s", e)
            return False

    @staticmethod
    def _auto_download(project_root: Path) -> Optional[str]:
        """Download embeddings from HuggingFace via the coach module.

        Uses coach/embeddings.py MTGEmbeddingIndex which handles downloading
        the parquet from HuggingFace and converting to NPZ. Returns the NPZ
        path on success, or None on failure.
        """
        try:
            import sys
            pr = str(project_root)
            if pr not in sys.path:
                sys.path.insert(0, pr)
            from coach.embeddings import MTGEmbeddingIndex
            from coach.config import EMBEDDINGS_NPZ

            idx = MTGEmbeddingIndex()
            idx.download_parquet()
            idx.convert_parquet_to_npz()

            npz_str = str(EMBEDDINGS_NPZ)
            if os.path.exists(npz_str):
                logger.info("Auto-downloaded embeddings to %s", npz_str)
                return npz_str
            logger.error("Auto-download completed but NPZ not found at %s", npz_str)
            return None
        except Exception as e:
            logger.error("Auto-download failed: %s", e)
            return None

    def get_embedding(self, card_name: str) -> np.ndarray:
        """Get embedding vector for a card name. Returns zero vector if not found."""
        if not self._loaded:
            return self._zero_vec
        idx = self._name_to_idx.get(card_name.lower())
        if idx is not None:
            return self._embeddings[idx]
        # Try fuzzy match: strip trailing set codes, articles
        clean = card_name.lower().split("|")[0].strip()
        idx = self._name_to_idx.get(clean)
        if idx is not None:
            return self._embeddings[idx]
        return self._zero_vec

    def mean_pool_zone(self, card_names: List[str]) -> np.ndarray:
        """Mean-pool embeddings for a list of card names (a game zone)."""
        if not card_names:
            return self._zero_vec
        vectors = [self.get_embedding(name) for name in card_names]
        return np.mean(vectors, axis=0).astype(np.float32)

    @property
    def is_loaded(self) -> bool:
        return self._loaded


class StateEncoder:
    """
    Encodes a decision snapshot JSON dict into a fixed-size numpy vector.

    Input: a dict from the JSONL file (one decision snapshot)
    Output: np.ndarray of shape (6177,)

    Components:
      [0:29]     - Global features (life, mana, turn, phase, etc.)
      [29:6173]  - Zone embeddings (4 zones × 2 players × 768)
      [6173:6177] - Playstyle one-hot (4 dims)
    """

    def __init__(self, card_index: CardEmbeddingIndex):
        self.card_index = card_index
        self.dim = STATE_DIMS

    def encode(self, decision: dict, playstyle: str = "midrange") -> np.ndarray:
        """
        Encode a single decision snapshot into a state vector.

        Args:
            decision: Dict loaded from JSONL line
            playstyle: Deck archetype string (aggro/control/midrange/combo)

        Returns:
            np.ndarray of shape (total_state_dim,)
        """
        players = decision.get("players", [])
        if len(players) < 2:
            # Pad to 2 players for 1v1
            while len(players) < 2:
                players.append(self._empty_player(len(players)))

        # 1. Global features
        global_vec = self._encode_global(decision, players)

        # 2. Zone embeddings
        zone_vec = self._encode_zones(players)

        # 3. Playstyle one-hot
        style_vec = self._encode_playstyle(playstyle)

        # Concatenate
        state = np.concatenate([global_vec, zone_vec, style_vec])
        assert state.shape[0] == self.dim.total_state_dim, (
            f"State dim mismatch: {state.shape[0]} != {self.dim.total_state_dim}"
        )
        return state.astype(np.float32)

    def _encode_global(self, decision: dict, players: list) -> np.ndarray:
        """Encode global scalar features. Shape: (29,)"""
        features = []

        for p in players[:2]:  # Exactly 2 players for 1v1
            # Per-player scalars (10 each)
            life = p.get("life", 40)
            features.append(life / 40.0)  # Normalized life

            cmdr_dmg = p.get("cmdr_dmg", 0)
            features.append(cmdr_dmg / 21.0)  # Normalized commander damage

            mana = p.get("mana", 0)
            features.append(min(mana / 20.0, 1.0))  # Normalized mana

            cmdr_tax = p.get("cmdr_tax", 0)
            features.append(min(cmdr_tax / 10.0, 1.0))  # Normalized tax

            hand_size = len(p.get("hand", []))
            features.append(min(hand_size / 15.0, 1.0))

            grave_size = len(p.get("graveyard", []))
            features.append(min(grave_size / 100.0, 1.0))

            creatures = p.get("creatures", 0)
            features.append(min(creatures / 30.0, 1.0))

            # Total power on board (not yet tracked accurately; use creatures as proxy)
            total_power = creatures * 3  # rough heuristic: avg 3 power
            features.append(min(total_power / 100.0, 1.0))

            # Is active player
            is_active = 1.0 if p.get("seat") == decision.get("active_seat") else 0.0
            features.append(is_active)

            # Land count (extra feature — helps distinguish ramp strategies)
            lands = p.get("lands", 0)
            features.append(min(lands / 15.0, 1.0))

            # Phase one-hot (4 dims per player)
            phase_str = decision.get("phase", "main_1")
            phase_oh = [0.0] * 4
            try:
                phase_enum = GamePhase(phase_str)
                phase_oh[PHASE_TO_IDX[phase_enum]] = 1.0
            except (ValueError, KeyError):
                phase_oh[0] = 1.0  # Default to main_1
            features.extend(phase_oh)

        # Turn number (1 feature, shared)
        turn = decision.get("turn", 1)
        features.append(min(turn / GAME_SCOPE.max_turns, 1.0))

        return np.array(features, dtype=np.float32)

    def _encode_zones(self, players: list) -> np.ndarray:
        """
        Encode zone contents as mean-pooled card embeddings.
        Shape: (4 zones × 2 players × 768) = (6144,)

        Zone embedding boundary: each zone slot is exactly ``zone_pool_dim``
        (768) floats.  Empty zones produce a zero vector of that size.  This
        fixed-size contract is relied upon by every downstream consumer
        (PolicyNetwork, PPOTrainer, dataset builder).  See
        ``StateDimensions`` in ``ml/config/scope.py`` for the canonical
        definition.
        """
        zone_keys = ["hand", "battlefield", "graveyard", "command_zone"]
        vectors = []

        for p in players[:2]:
            for zone_key in zone_keys:
                cards = p.get(zone_key, [])
                # mean_pool_zone returns a zero vector when cards is empty,
                # preserving the fixed 768-dim slot size.
                pooled = self.card_index.mean_pool_zone(cards)
                vectors.append(pooled)

        return np.concatenate(vectors)

    def _encode_playstyle(self, playstyle_str: str) -> np.ndarray:
        """One-hot encode the playstyle. Shape: (4,)"""
        vec = np.zeros(self.dim.playstyle_dim, dtype=np.float32)
        try:
            style = Playstyle(playstyle_str.lower())
            vec[PLAYSTYLE_TO_IDX[style]] = 1.0
        except (ValueError, KeyError):
            # Default: midrange
            vec[PLAYSTYLE_TO_IDX[Playstyle.MIDRANGE]] = 1.0
        return vec

    def _empty_player(self, seat: int) -> dict:
        """Create an empty player dict for padding."""
        return {
            "seat": seat,
            "life": 40,
            "cmdr_dmg": 0,
            "mana": 0,
            "cmdr_tax": 0,
            "creatures": 0,
            "lands": 0,
            "hand": [],
            "battlefield": [],
            "graveyard": [],
            "command_zone": [],
        }


def encode_decisions_file(
    jsonl_path: str,
    card_index: CardEmbeddingIndex,
    max_samples: int = None,
) -> Tuple[np.ndarray, List[dict]]:
    """
    Encode all decisions from a JSONL file into a state matrix.

    Args:
        jsonl_path: Path to ml-decisions-*.jsonl file
        card_index: Loaded card embedding index
        max_samples: Maximum number of samples to encode (None = all)

    Returns:
        (states, raw_decisions) where:
          states: np.ndarray of shape (N, 6177)
          raw_decisions: list of original JSON dicts (for action labels)
    """
    encoder = StateEncoder(card_index)
    states = []
    raw = []

    with open(jsonl_path, "r") as f:
        for i, line in enumerate(f):
            if max_samples and i >= max_samples:
                break
            line = line.strip()
            if not line:
                continue
            try:
                decision = json.loads(line)
                playstyle = decision.get("archetype", "midrange")
                state_vec = encoder.encode(decision, playstyle)
                states.append(state_vec)
                raw.append(decision)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Skipping line %d: %s", i, e)
                continue

    if not states:
        return np.empty((0, STATE_DIMS.total_state_dim), dtype=np.float32), []

    return np.stack(states), raw
