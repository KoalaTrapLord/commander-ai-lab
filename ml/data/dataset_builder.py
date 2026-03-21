"""
Commander AI Lab — Training Dataset Builder
════════════════════════════════════════════
Reads ML decision JSONL files, encodes states, labels actions,
and produces a training-ready dataset saved as NPZ.

Usage:
    python -m ml.data.dataset_builder --results-dir results/ --output ml/models/dataset.npz

Output NPZ structure:
    states:     float32 (N, 6177) — encoded state vectors
    labels:     int64   (N,)      — macro-action indices (0-7)
    game_ids:   object  (N,)      — game ID for each sample
    outcomes:   object  (N,)      — game outcome per sample
    playstyles: object  (N,)      — deck archetype per sample
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import (
    NUM_ACTIONS, STATE_DIMS, MacroAction, ACTION_TO_IDX,
)
from ml.encoder.state_encoder import CardEmbeddingIndex, StateEncoder
from ml.actions.labeler import label_action, print_label_distribution

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("ml.dataset")


def build_dataset(
    results_dir: str,
    embeddings_dir: str = None,
    max_samples: int = None,
) -> Dict[str, np.ndarray]:
    """
    Build complete training dataset from all ML decision files.

    Args:
        results_dir: Path to results/ directory containing ml-decisions-*.jsonl
        embeddings_dir: Path to embeddings/ directory (default: auto-detect)
        max_samples: Cap total samples (None = unlimited)

    Returns:
        Dict with keys: states, labels, game_ids, outcomes, playstyles
    """
    # Load card embeddings
    card_index = CardEmbeddingIndex(embeddings_dir)
    if not card_index.load():
        logger.error("Cannot build dataset without card embeddings.")
        logger.error("Start the lab server first to auto-download embeddings,")
        logger.error("or manually download mtg_embeddings.npz to embeddings/ or data/")
        raise RuntimeError(
            "Card embeddings not found. The coach must download them first — "
            "open the Coach tab and ensure embeddings are loaded, or place "
            "mtg-embeddings.npz in the data/ folder."
        )

    encoder = StateEncoder(card_index)

    # Find all JSONL files
    results_path = Path(results_dir)
    jsonl_files = sorted(results_path.glob("ml-decisions-*.jsonl"))
    if not jsonl_files:
        logger.error("No ML decision files found in %s", results_dir)
        logger.error("Run batch simulations with --ml-log or enable ML logging in the UI first.")
        raise RuntimeError(
            f"No ml-decisions-*.jsonl files found in {results_dir}. "
            "Run batch simulations with ML logging enabled first."
        )

    logger.info("Found %d ML decision files", len(jsonl_files))

    all_states = []
    all_labels = []
    all_game_ids = []
    all_outcomes = []
    all_playstyles = []
    total_skipped = 0

    for jsonl_file in jsonl_files:
        logger.info("Processing %s ...", jsonl_file.name)
        file_count = 0

        with open(jsonl_file, "r") as f:
            for line_num, line in enumerate(f):
                if max_samples and len(all_states) >= max_samples:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    decision = json.loads(line)

                    # Encode state
                    playstyle = decision.get("archetype", "midrange")
                    state_vec = encoder.encode(decision, playstyle)

                    # Label action
                    action_idx = label_action(decision)

                    # Metadata
                    game_id = decision.get("game_id", f"unknown-{line_num}")
                    outcome = decision.get("game_outcome", "unknown")

                    all_states.append(state_vec)
                    all_labels.append(action_idx)
                    all_game_ids.append(game_id)
                    all_outcomes.append(outcome)
                    all_playstyles.append(playstyle)
                    file_count += 1

                except Exception as e:
                    total_skipped += 1
                    if total_skipped <= 10:
                        logger.warning(
                            "Skipping %s line %d: %s", jsonl_file.name, line_num, e
                        )

        logger.info("  → %d samples from %s", file_count, jsonl_file.name)

    if not all_states:
        logger.error("No valid samples found.")
        return {}

    # Convert to arrays
    states = np.stack(all_states).astype(np.float32)
    labels = np.array(all_labels, dtype=np.int64)
    game_ids = np.array(all_game_ids, dtype=object)
    outcomes = np.array(all_outcomes, dtype=object)
    playstyles = np.array(all_playstyles, dtype=object)

    logger.info(
        "Dataset built: %d samples, %d features, %d actions, %d skipped",
        len(states), states.shape[1], NUM_ACTIONS, total_skipped,
    )

    # Print label distribution
    print_label_distribution(labels)

    # Print game outcome distribution
    unique_outcomes, outcome_counts = np.unique(outcomes, return_counts=True)
    logger.info(f"\n{'Outcome':<25} {'Count':>8}")
    logger.info("─" * 35)
    for o, c in sorted(zip(unique_outcomes, outcome_counts), key=lambda x: -x[1]):
        logger.info(f"  {str(o):<23} {c:>8}")

    # Print playstyle distribution
    unique_styles, style_counts = np.unique(playstyles, return_counts=True)
    logger.info(f"\n{'Playstyle':<25} {'Count':>8}")
    logger.info("─" * 35)
    for s, c in sorted(zip(unique_styles, style_counts), key=lambda x: -x[1]):
        logger.info(f"  {str(s):<23} {c:>8}")

    return {
        "states": states,
        "labels": labels,
        "game_ids": game_ids,
        "outcomes": outcomes,
        "playstyles": playstyles,
    }


def split_dataset(
    dataset: Dict[str, np.ndarray],
    val_split: float = 0.15,
    test_split: float = 0.10,
    split_by_game: bool = True,
) -> Tuple[Dict, Dict, Dict]:
    """
    Split dataset into train/val/test sets.

    If split_by_game=True, splits by game_id to prevent data leakage
    (all decisions from one game go to the same split).

    Returns:
        (train, val, test) — each a dict with same keys as input
    """
    states = dataset["states"]
    labels = dataset["labels"]
    game_ids = dataset["game_ids"]

    if split_by_game:
        # Get unique game IDs and shuffle
        unique_games = np.unique(game_ids)
        rng = np.random.default_rng(42)
        rng.shuffle(unique_games)

        n_games = len(unique_games)
        n_test = max(1, int(n_games * test_split))
        n_val = max(1, int(n_games * val_split))

        test_games = set(unique_games[:n_test])
        val_games = set(unique_games[n_test:n_test + n_val])
        train_games = set(unique_games[n_test + n_val:])

        train_mask = np.array([gid in train_games for gid in game_ids])
        val_mask = np.array([gid in val_games for gid in game_ids])
        test_mask = np.array([gid in test_games for gid in game_ids])
    else:
        # Simple random split by sample
        n = len(states)
        rng = np.random.default_rng(42)
        indices = rng.permutation(n)

        n_test = max(1, int(n * test_split))
        n_val = max(1, int(n * val_split))

        test_mask = np.zeros(n, dtype=bool)
        val_mask = np.zeros(n, dtype=bool)
        train_mask = np.zeros(n, dtype=bool)

        test_mask[indices[:n_test]] = True
        val_mask[indices[n_test:n_test + n_val]] = True
        train_mask[indices[n_test + n_val:]] = True

    def _subset(mask):
        return {k: v[mask] for k, v in dataset.items()}

    train = _subset(train_mask)
    val = _subset(val_mask)
    test = _subset(test_mask)

    logger.info(
        "Split: train=%d, val=%d, test=%d (by_game=%s)",
        len(train["states"]), len(val["states"]), len(test["states"]),
        split_by_game,
    )

    return train, val, test


def save_dataset(
    dataset: Dict[str, np.ndarray],
    output_path: str,
):
    """Save dataset to NPZ file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    np.savez_compressed(output_path, **dataset)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info("Saved dataset to %s (%.1f MB)", output_path, size_mb)


def main():
    parser = argparse.ArgumentParser(
        description="Build ML training dataset from decision logs"
    )
    parser.add_argument(
        "--results-dir", default="results",
        help="Directory containing ml-decisions-*.jsonl files",
    )
    parser.add_argument(
        "--embeddings-dir", default=None,
        help="Directory containing mtg_embeddings.npz (default: auto-detect)",
    )
    parser.add_argument(
        "--output", default="ml/models/dataset.npz",
        help="Output path for the dataset NPZ file",
    )
    parser.add_argument(
        "--max-samples", type=int, default=None,
        help="Maximum number of samples (default: unlimited)",
    )
    parser.add_argument(
        "--no-split", action="store_true",
        help="Don't split into train/val/test (save single file)",
    )
    args = parser.parse_args()

    # Build dataset
    dataset = build_dataset(
        results_dir=args.results_dir,
        embeddings_dir=args.embeddings_dir,
        max_samples=args.max_samples,
    )
    if not dataset:
        logger.info("\nNo data to save. Run simulations with --ml-log first.")
        sys.exit(1)

    if args.no_split:
        save_dataset(dataset, args.output)
    else:
        train, val, test = split_dataset(dataset)
        base = args.output.replace(".npz", "")
        save_dataset(train, f"{base}-train.npz")
        save_dataset(val, f"{base}-val.npz")
        save_dataset(test, f"{base}-test.npz")

    logger.info("\nDataset build complete.")


if __name__ == "__main__":
    main()
