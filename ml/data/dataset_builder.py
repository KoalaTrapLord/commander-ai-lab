"""
Commander AI Lab — Training Dataset Builder
════════════════════════════════════════════

Reads ML decision JSONL files, encodes states, labels actions,
and produces a training-ready dataset saved as NPZ.

Phase 2: Source Awareness (Issue #66)
  - Scans both Forge sim files (ml-decisions-sim-*.jsonl) and
    PPO self-play files (ml-decisions-ppo-*.jsonl)
  - Configurable source_weights for sampling ratios
  - min_reward_threshold filter for PPO data quality
  - Each sample tagged with source for downstream analysis

Usage:
    python -m ml.data.dataset_builder --results-dir results/ --output ml/models/dataset.npz

Output NPZ structure:
    states:     float32 (N, 6177) — encoded state vectors
    labels:     int64   (N,)      — macro-action indices (0-7)
    game_ids:   object  (N,)      — game ID for each sample
    outcomes:   object  (N,)      — game outcome per sample
    playstyles: object  (N,)      — deck archetype per sample
    sources:    object  (N,)      — data source ("forge" or "ppo")
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Configuration (Phase 2)
# ---------------------------------------------------------------------------

@dataclass
class DatasetConfig:
    """Configuration for dataset building with source awareness."""

    results_dir: str = "results"
    embeddings_dir: Optional[str] = None
    max_samples: Optional[int] = None

    # Source weights control sampling ratios between Forge and PPO data.
    # e.g. {"forge": 1.0, "ppo": 0.5} means keep all Forge data but
    # randomly sample 50% of PPO data to avoid overwhelming the baseline.
    source_weights: Dict[str, float] = field(
        default_factory=lambda: {"forge": 1.0, "ppo": 0.5}
    )

    # Minimum reward threshold for PPO data — only include decisions
    # from games where the episode return exceeds this value.
    # Set to None to disable filtering.
    min_reward_threshold: Optional[float] = 0.0


# ---------------------------------------------------------------------------
# Source-aware file discovery (Phase 2 — Task 1)
# ---------------------------------------------------------------------------

def _discover_jsonl_files(results_dir: str) -> Dict[str, List[Path]]:
    """
    Scan results directory for both Forge sim and PPO decision files.

    Returns:
        Dict mapping source name to list of JSONL file paths.
        Keys: "forge" for ml-decisions-sim-*.jsonl
              "ppo"   for ml-decisions-ppo-*.jsonl
    """
    results_path = Path(results_dir)
    sources = {}

    # Forge batch sim files
    forge_files = sorted(results_path.glob("ml-decisions-sim-*.jsonl"))
    if forge_files:
        sources["forge"] = forge_files

    # PPO self-play files (from Phase 1 DecisionExporter)
    ppo_files = sorted(results_path.glob("ml-decisions-ppo-*.jsonl"))
    if ppo_files:
        sources["ppo"] = ppo_files

    # Also pick up legacy files that don't have sim/ppo prefix
    legacy_files = sorted(
        f for f in results_path.glob("ml-decisions-*.jsonl")
        if f not in set(forge_files + ppo_files)
    )
    if legacy_files:
        sources.setdefault("forge", []).extend(legacy_files)

    return sources


# ---------------------------------------------------------------------------
# PPO reward filter (Phase 2 — Task 3)
# ---------------------------------------------------------------------------

def _passes_reward_filter(
    decision: dict,
    source: str,
    min_reward_threshold: Optional[float],
) -> bool:
    """
    Filter PPO decisions by reward threshold.
    Forge data always passes. PPO data must meet the threshold.
    """
    if source != "ppo":
        return True
    if min_reward_threshold is None:
        return True
    episode_return = decision.get("episode_return", 0.0)
    return episode_return >= min_reward_threshold


# ---------------------------------------------------------------------------
# Source-aware sampling (Phase 2 — Task 2)
# ---------------------------------------------------------------------------

def _apply_source_weights(
    samples_by_source: Dict[str, List[dict]],
    source_weights: Dict[str, float],
    rng: np.random.Generator,
) -> List[dict]:
    """
    Apply source weights to control the mixing ratio.

    A weight of 1.0 keeps all samples from that source.
    A weight of 0.5 randomly keeps ~50% of samples.
    A weight > 1.0 oversamples (with replacement).
    """
    combined = []
    for source, samples in samples_by_source.items():
        weight = source_weights.get(source, 1.0)
        if weight <= 0:
            logger.info("  Skipping %d %s samples (weight=0)", len(samples), source)
            continue
        if weight >= 1.0 and weight == 1.0:
            combined.extend(samples)
        elif weight < 1.0:
            # Subsample
            n_keep = max(1, int(len(samples) * weight))
            indices = rng.choice(len(samples), size=n_keep, replace=False)
            combined.extend(samples[i] for i in indices)
            logger.info(
                "  Subsampled %s: %d → %d (weight=%.2f)",
                source, len(samples), n_keep, weight,
            )
        else:
            # Oversample (weight > 1.0)
            n_target = int(len(samples) * weight)
            indices = rng.choice(len(samples), size=n_target, replace=True)
            combined.extend(samples[i] for i in indices)
            logger.info(
                "  Oversampled %s: %d → %d (weight=%.2f)",
                source, len(samples), n_target, weight,
            )
    return combined


# ---------------------------------------------------------------------------
# Main dataset builder (updated for Phase 2)
# ---------------------------------------------------------------------------

def build_dataset(
    results_dir: str,
    embeddings_dir: str = None,
    max_samples: int = None,
    source_weights: Dict[str, float] = None,
    min_reward_threshold: float = 0.0,
) -> Dict[str, np.ndarray]:
    """
    Build complete training dataset from all ML decision files.

    Phase 2 additions:
      - Scans both Forge and PPO JSONL files
      - Applies source_weights for configurable mixing
      - Filters PPO data by min_reward_threshold
      - Tags each sample with its source

    Args:
        results_dir: Path to results/ directory containing JSONL files
        embeddings_dir: Path to embeddings/ directory (default: auto-detect)
        max_samples: Cap total samples (None = unlimited)
        source_weights: Dict of source → sampling weight (default: forge=1.0, ppo=0.5)
        min_reward_threshold: Min episode_return for PPO data (default: 0.0)

    Returns:
        Dict with keys: states, labels, game_ids, outcomes, playstyles, sources
    """
    if source_weights is None:
        source_weights = {"forge": 1.0, "ppo": 0.5}

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

    # --- Phase 2 Task 1: Discover files from both sources ---
    source_files = _discover_jsonl_files(results_dir)
    if not source_files:
        logger.error("No ML decision files found in %s", results_dir)
        logger.error("Run batch simulations with --ml-log or enable ML logging in the UI first.")
        raise RuntimeError(
            f"No ml-decisions-*.jsonl files found in {results_dir}. "
            "Run batch simulations with ML logging enabled first."
        )

    total_files = sum(len(files) for files in source_files.values())
    logger.info(
        "Found %d ML decision files across %d sources: %s",
        total_files,
        len(source_files),
        {src: len(files) for src, files in source_files.items()},
    )

    # --- Read and filter all decisions, grouped by source ---
    rng = np.random.default_rng(42)
    samples_by_source: Dict[str, List[dict]] = {}
    total_skipped = 0
    total_filtered = 0

    for source, jsonl_files in source_files.items():
        source_samples = []

        for jsonl_file in jsonl_files:
            logger.info("Processing %s [%s] ...", jsonl_file.name, source)
            file_count = 0

            with open(jsonl_file, "r") as f:
                for line_num, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        decision = json.loads(line)

                        # --- Phase 2 Task 3: PPO reward filter ---
                        if not _passes_reward_filter(
                            decision, source, min_reward_threshold
                        ):
                            total_filtered += 1
                            continue

                        # --- Phase 2 Task 4: Tag with source ---
                        decision["_source"] = source

                        source_samples.append(decision)
                        file_count += 1

                    except Exception as e:
                        total_skipped += 1
                        if total_skipped <= 10:
                            logger.warning(
                                "Skipping %s line %d: %s", jsonl_file.name, line_num, e
                            )

            logger.info("  → %d samples from %s", file_count, jsonl_file.name)

        if source_samples:
            samples_by_source[source] = source_samples

    if not samples_by_source:
        logger.error("No valid samples found.")
        return {}

    # Log per-source counts before weighting
    for src, samples in samples_by_source.items():
        logger.info("Source '%s': %d raw samples", src, len(samples))
    if total_filtered > 0:
        logger.info("PPO reward filter removed %d samples (threshold=%.2f)",
                     total_filtered, min_reward_threshold or 0.0)

    # --- Phase 2 Task 2: Apply source weights ---
    combined_decisions = _apply_source_weights(
        samples_by_source, source_weights, rng
    )

    # Apply max_samples cap after weighting
    if max_samples and len(combined_decisions) > max_samples:
        rng.shuffle(combined_decisions)
        combined_decisions = combined_decisions[:max_samples]
        logger.info("Capped to %d samples", max_samples)

    # --- Encode all decisions ---
    all_states = []
    all_labels = []
    all_game_ids = []
    all_outcomes = []
    all_playstyles = []
    all_sources = []
    encode_errors = 0

    for decision in combined_decisions:
        try:
            playstyle = decision.get("archetype", "midrange")
            state_vec = encoder.encode(decision, playstyle)
            action_idx = label_action(decision)
            game_id = decision.get("game_id", "unknown")
            outcome = decision.get("game_outcome", "unknown")
            source = decision.get("_source", "forge")

            all_states.append(state_vec)
            all_labels.append(action_idx)
            all_game_ids.append(game_id)
            all_outcomes.append(outcome)
            all_playstyles.append(playstyle)
            all_sources.append(source)

        except Exception as e:
            encode_errors += 1
            if encode_errors <= 5:
                logger.warning("Encode error: %s", e)

    if not all_states:
        logger.error("No valid samples after encoding.")
        return {}

    # Convert to arrays
    states = np.stack(all_states).astype(np.float32)
    labels = np.array(all_labels, dtype=np.int64)
    game_ids = np.array(all_game_ids, dtype=object)
    outcomes = np.array(all_outcomes, dtype=object)
    playstyles = np.array(all_playstyles, dtype=object)
    sources = np.array(all_sources, dtype=object)

    logger.info(
        "Dataset built: %d samples, %d features, %d actions, %d skipped, %d encode errors",
        len(states), states.shape[1], NUM_ACTIONS, total_skipped, encode_errors,
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

    # --- Phase 2 Task 4: Print source distribution ---
    unique_sources, source_counts = np.unique(sources, return_counts=True)
    logger.info(f"\n{'Source':<25} {'Count':>8} {'%':>7}")
    logger.info("─" * 42)
    for s, c in sorted(zip(unique_sources, source_counts), key=lambda x: -x[1]):
        pct = 100.0 * c / len(sources)
        logger.info(f"  {str(s):<23} {c:>8} {pct:>6.1f}%")

    return {
        "states": states,
        "labels": labels,
        "game_ids": game_ids,
        "outcomes": outcomes,
        "playstyles": playstyles,
        "sources": sources,
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
    # Phase 2 CLI arguments
    parser.add_argument(
        "--forge-weight", type=float, default=1.0,
        help="Sampling weight for Forge sim data (default: 1.0)",
    )
    parser.add_argument(
        "--ppo-weight", type=float, default=0.5,
        help="Sampling weight for PPO self-play data (default: 0.5)",
    )
    parser.add_argument(
        "--min-reward", type=float, default=0.0,
        help="Minimum episode_return for PPO data (default: 0.0)",
    )

    args = parser.parse_args()

    source_weights = {
        "forge": args.forge_weight,
        "ppo": args.ppo_weight,
    }

    # Build dataset
    dataset = build_dataset(
        results_dir=args.results_dir,
        embeddings_dir=args.embeddings_dir,
        max_samples=args.max_samples,
        source_weights=source_weights,
        min_reward_threshold=args.min_reward,
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
