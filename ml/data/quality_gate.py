"""
Commander AI Lab — Quality Gate & Validation
═════════════════════════════════════════════

Phase 3 (Issue #67): Prevents bad PPO data from degrading the
supervised model by enforcing quality gates at multiple levels:

1. Forge Validation Holdout — fixed eval set from Forge-only data
2. Accuracy Gate — reject PPO batch if model accuracy drops on Forge eval
3. Win Rate Gate — only export PPO decisions above a win rate threshold
4. Data Quality Metrics — entropy, reward distribution logging

Usage:
    from ml.data.quality_gate import QualityGate, QualityGateConfig

    gate = QualityGate(QualityGateConfig(
        min_forge_accuracy=0.40,
        min_ppo_win_rate=0.30,
    ))

    # Check if PPO batch should be accepted
    verdict = gate.evaluate_ppo_batch(
        forge_eval_accuracy=0.42,
        ppo_win_rate=0.35,
        ppo_decisions=decisions_list,
        baseline_accuracy=0.41,
    )
    if verdict.accepted:
        # merge PPO data into training set
        ...

Ref: docs/CLOSED-LOOP-DISTILLATION.md — Phase 3
Issue: #67
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("ml.quality_gate")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class QualityGateConfig:
    """Configuration for the quality gate system."""

    # --- Forge validation holdout (Task 1) ---
    forge_holdout_ratio: float = 0.12  # 12% of Forge data held out
    forge_holdout_seed: int = 99       # Fixed seed for reproducibility

    # --- Accuracy gate (Task 2) ---
    # If model accuracy on Forge eval drops below this absolute floor,
    # the PPO batch is rejected regardless.
    min_forge_accuracy: float = 0.35

    # If model accuracy drops by more than this relative amount compared
    # to the baseline (pre-PPO model), reject the batch.
    max_accuracy_drop: float = 0.03  # e.g., 41% → 38% = 3% drop → reject

    # --- Win rate gate (Task 3) ---
    # PPO agent must exceed this win rate before its decisions are exported.
    # In a 4-player pod, random baseline is 25%.
    min_ppo_win_rate: float = 0.30

    # --- Quality metrics (Task 4) ---
    # Directory to write quality reports
    reports_dir: str = "data/results/quality-reports"


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------

@dataclass
class GateVerdict:
    """Result of a quality gate evaluation."""
    accepted: bool
    reason: str
    metrics: Dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Forge Validation Holdout (Task 1)
# ---------------------------------------------------------------------------

def create_forge_holdout(
    states: np.ndarray,
    labels: np.ndarray,
    sources: np.ndarray,
    game_ids: np.ndarray,
    holdout_ratio: float = 0.12,
    seed: int = 99,
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """
    Split Forge-only data into training and holdout validation sets.

    The holdout set is a fixed eval set used to detect accuracy regression
    when PPO data is mixed in. Split is done by game_id to prevent leakage.

    Args:
        states, labels, sources, game_ids: Dataset arrays
        holdout_ratio: Fraction of Forge games to hold out
        seed: Fixed random seed for reproducibility

    Returns:
        (train_data, holdout_data) — each a dict with states, labels, sources, game_ids
    """
    # Identify Forge-only samples
    forge_mask = np.array([s == "forge" for s in sources])
    ppo_mask = ~forge_mask

    forge_game_ids = game_ids[forge_mask]
    unique_forge_games = np.unique(forge_game_ids)

    # Deterministic split by game_id
    rng = np.random.default_rng(seed)
    rng.shuffle(unique_forge_games)

    n_holdout = max(1, int(len(unique_forge_games) * holdout_ratio))
    holdout_games = set(unique_forge_games[:n_holdout])
    train_games = set(unique_forge_games[n_holdout:])

    # Build masks
    forge_holdout_mask = np.array([
        (s == "forge" and gid in holdout_games)
        for s, gid in zip(sources, game_ids)
    ])
    forge_train_mask = np.array([
        (s == "forge" and gid in train_games)
        for s, gid in zip(sources, game_ids)
    ])

    # Training set = Forge train + all PPO data
    train_mask = forge_train_mask | ppo_mask

    def _subset(mask):
        return {
            "states": states[mask],
            "labels": labels[mask],
            "sources": sources[mask],
            "game_ids": game_ids[mask],
        }

    holdout = _subset(forge_holdout_mask)
    train = _subset(train_mask)

    logger.info(
        "Forge holdout: %d samples (%d games) held out, %d train samples remaining",
        forge_holdout_mask.sum(), n_holdout, train_mask.sum(),
    )

    return train, holdout


# ---------------------------------------------------------------------------
# Accuracy Gate (Task 2)
# ---------------------------------------------------------------------------

def check_accuracy_gate(
    current_accuracy: float,
    baseline_accuracy: float,
    config: QualityGateConfig,
) -> GateVerdict:
    """
    Check if the current model accuracy on the Forge holdout set
    is acceptable after training with PPO data mixed in.

    Args:
        current_accuracy: Accuracy on Forge holdout after training with PPO data
        baseline_accuracy: Accuracy on Forge holdout from previous model (no PPO)
        config: Quality gate configuration

    Returns:
        GateVerdict — accepted=True if accuracy is acceptable
    """
    metrics = {
        "current_accuracy": round(current_accuracy, 4),
        "baseline_accuracy": round(baseline_accuracy, 4),
        "accuracy_drop": round(baseline_accuracy - current_accuracy, 4),
        "min_forge_accuracy": config.min_forge_accuracy,
        "max_accuracy_drop": config.max_accuracy_drop,
    }

    # Check absolute floor
    if current_accuracy < config.min_forge_accuracy:
        return GateVerdict(
            accepted=False,
            reason=(
                f"Forge eval accuracy ({current_accuracy:.1%}) below absolute "
                f"minimum ({config.min_forge_accuracy:.1%}). PPO batch rejected."
            ),
            metrics=metrics,
        )

    # Check relative drop
    drop = baseline_accuracy - current_accuracy
    if drop > config.max_accuracy_drop:
        return GateVerdict(
            accepted=False,
            reason=(
                f"Forge eval accuracy dropped {drop:.1%} "
                f"(from {baseline_accuracy:.1%} to {current_accuracy:.1%}), "
                f"exceeding max allowed drop of {config.max_accuracy_drop:.1%}. "
                f"PPO batch rejected."
            ),
            metrics=metrics,
        )

    return GateVerdict(
        accepted=True,
        reason=(
            f"Forge eval accuracy {current_accuracy:.1%} is acceptable "
            f"(baseline={baseline_accuracy:.1%}, drop={drop:.1%}). "
            f"PPO batch accepted."
        ),
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Win Rate Gate (Task 3)
# ---------------------------------------------------------------------------

def check_win_rate_gate(
    ppo_win_rate: float,
    config: QualityGateConfig,
    total_episodes: int = 0,
    min_episodes: int = 20,
) -> GateVerdict:
    """
    Check if the PPO agent's win rate exceeds the minimum threshold
    before allowing its decisions to be exported.

    Args:
        ppo_win_rate: Win rate of PPO agent (0.0 to 1.0)
        config: Quality gate configuration
        total_episodes: Number of episodes played
        min_episodes: Minimum episodes required for statistical significance

    Returns:
        GateVerdict — accepted=True if win rate is sufficient
    """
    metrics = {
        "ppo_win_rate": round(ppo_win_rate, 4),
        "min_ppo_win_rate": config.min_ppo_win_rate,
        "total_episodes": total_episodes,
        "min_episodes": min_episodes,
    }

    # Check minimum episode count
    if total_episodes < min_episodes:
        return GateVerdict(
            accepted=False,
            reason=(
                f"Insufficient episodes ({total_episodes}/{min_episodes}). "
                f"Need at least {min_episodes} episodes for reliable win rate."
            ),
            metrics=metrics,
        )

    # Check win rate threshold
    if ppo_win_rate < config.min_ppo_win_rate:
        return GateVerdict(
            accepted=False,
            reason=(
                f"PPO win rate ({ppo_win_rate:.1%}) below minimum "
                f"threshold ({config.min_ppo_win_rate:.1%}). "
                f"Agent not strong enough — decisions not exported."
            ),
            metrics=metrics,
        )

    return GateVerdict(
        accepted=True,
        reason=(
            f"PPO win rate ({ppo_win_rate:.1%}) exceeds minimum "
            f"({config.min_ppo_win_rate:.1%}) over {total_episodes} episodes. "
            f"Decisions approved for export."
        ),
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Data Quality Metrics (Task 4)
# ---------------------------------------------------------------------------

def compute_action_entropy(action_indices: np.ndarray, num_actions: int = 8) -> float:
    """
    Compute Shannon entropy of the action distribution.

    High entropy = diverse actions (good).
    Low entropy = collapsed to few actions (bad — possible mode collapse).
    Max entropy for 8 actions = log2(8) = 3.0 bits.
    """
    counts = np.bincount(action_indices, minlength=num_actions).astype(np.float64)
    probs = counts / max(counts.sum(), 1)
    # Filter zero probabilities for log
    probs = probs[probs > 0]
    entropy = -np.sum(probs * np.log2(probs))
    return float(entropy)


def compute_reward_stats(rewards: np.ndarray) -> Dict[str, float]:
    """Compute summary statistics for reward/episode_return distribution."""
    if len(rewards) == 0:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0,
                "median": 0.0, "p25": 0.0, "p75": 0.0}
    return {
        "mean": float(np.mean(rewards)),
        "std": float(np.std(rewards)),
        "min": float(np.min(rewards)),
        "max": float(np.max(rewards)),
        "median": float(np.median(rewards)),
        "p25": float(np.percentile(rewards, 25)),
        "p75": float(np.percentile(rewards, 75)),
    }


def compute_quality_metrics(
    decisions: List[dict],
    num_actions: int = 8,
) -> Dict:
    """
    Compute comprehensive data quality metrics for a batch of decisions.

    Metrics:
      - action_entropy: Shannon entropy of action distribution
      - action_distribution: count per action
      - reward_stats: mean, std, min, max, median, p25, p75
      - source_breakdown: count per source
      - total_decisions: number of decisions
      - unique_games: number of unique game IDs

    Args:
        decisions: List of decision dicts (from JSONL records)
        num_actions: Total number of possible actions

    Returns:
        Dict of quality metrics
    """
    if not decisions:
        return {"total_decisions": 0, "error": "empty batch"}

    # Extract action indices
    action_indices = np.array([
        d.get("action", {}).get("action_idx", d.get("action_idx", 0))
        for d in decisions
    ])

    # Extract rewards/episode returns
    rewards = np.array([
        d.get("episode_return", d.get("reward", 0.0))
        for d in decisions
    ])

    # Action distribution
    action_counts = np.bincount(action_indices, minlength=num_actions)
    action_distribution = {
        str(i): int(c) for i, c in enumerate(action_counts)
    }

    # Source breakdown
    sources = [d.get("source", d.get("_source", "unknown")) for d in decisions]
    source_counts = {}
    for s in sources:
        source_counts[s] = source_counts.get(s, 0) + 1

    # Unique games
    game_ids = set(d.get("game_id", "?") for d in decisions)

    # Entropy
    entropy = compute_action_entropy(action_indices, num_actions)
    max_entropy = np.log2(num_actions)

    return {
        "total_decisions": len(decisions),
        "unique_games": len(game_ids),
        "action_entropy": round(entropy, 4),
        "max_entropy": round(max_entropy, 4),
        "entropy_ratio": round(entropy / max(max_entropy, 1e-8), 4),
        "action_distribution": action_distribution,
        "reward_stats": compute_reward_stats(rewards),
        "source_breakdown": source_counts,
    }


def log_quality_metrics(metrics: Dict):
    """Pretty-print quality metrics to the logger."""
    logger.info("")
    logger.info("=" * 55)
    logger.info("  Data Quality Report")
    logger.info("=" * 55)
    logger.info("  Total decisions:   %d", metrics.get("total_decisions", 0))
    logger.info("  Unique games:      %d", metrics.get("unique_games", 0))
    logger.info("  Action entropy:    %.3f / %.3f (%.0f%%)",
                metrics.get("action_entropy", 0),
                metrics.get("max_entropy", 0),
                metrics.get("entropy_ratio", 0) * 100)
    logger.info("")

    # Action distribution
    dist = metrics.get("action_distribution", {})
    if dist:
        total = sum(dist.values())
        logger.info("  %-20s %8s %7s", "Action", "Count", "%")
        logger.info("  " + "-" * 37)
        for action_idx, count in sorted(dist.items(), key=lambda x: -x[1]):
            pct = 100.0 * count / max(total, 1)
            logger.info("  %-20s %8d %6.1f%%", f"action_{action_idx}", count, pct)

    # Reward stats
    rstats = metrics.get("reward_stats", {})
    if rstats:
        logger.info("")
        logger.info("  Reward distribution:")
        logger.info("    mean=%.3f  std=%.3f  min=%.3f  max=%.3f",
                    rstats.get("mean", 0), rstats.get("std", 0),
                    rstats.get("min", 0), rstats.get("max", 0))
        logger.info("    p25=%.3f  median=%.3f  p75=%.3f",
                    rstats.get("p25", 0), rstats.get("median", 0),
                    rstats.get("p75", 0))

    # Source breakdown
    sources = metrics.get("source_breakdown", {})
    if sources:
        logger.info("")
        logger.info("  Source breakdown:")
        for src, cnt in sorted(sources.items(), key=lambda x: -x[1]):
            logger.info("    %-12s %d", src, cnt)

    logger.info("=" * 55)


# ---------------------------------------------------------------------------
# Orchestrator — QualityGate class
# ---------------------------------------------------------------------------

class QualityGate:
    """
    Orchestrates all quality checks for the closed-loop distillation pipeline.

    Usage:
        gate = QualityGate(config)

        # Before exporting PPO decisions:
        win_verdict = gate.check_win_rate(ppo_win_rate=0.35, total_episodes=100)

        # After training with mixed data:
        acc_verdict = gate.check_accuracy(
            current_accuracy=0.42,
            baseline_accuracy=0.41,
        )

        # Log quality metrics for a batch:
        gate.report_batch_quality(decisions)
    """

    def __init__(self, config: QualityGateConfig = None):
        self.config = config or QualityGateConfig()
        self.verdicts: List[GateVerdict] = []

    def check_win_rate(
        self,
        ppo_win_rate: float,
        total_episodes: int = 0,
        min_episodes: int = 20,
    ) -> GateVerdict:
        """Check if PPO agent meets win rate threshold for export."""
        verdict = check_win_rate_gate(
            ppo_win_rate, self.config, total_episodes, min_episodes
        )
        self.verdicts.append(verdict)
        if verdict.accepted:
            logger.info("WIN RATE GATE: PASS — %s", verdict.reason)
        else:
            logger.warning("WIN RATE GATE: FAIL — %s", verdict.reason)
        return verdict

    def check_accuracy(
        self,
        current_accuracy: float,
        baseline_accuracy: float,
    ) -> GateVerdict:
        """Check if model accuracy on Forge holdout is acceptable."""
        verdict = check_accuracy_gate(
            current_accuracy, baseline_accuracy, self.config
        )
        self.verdicts.append(verdict)
        if verdict.accepted:
            logger.info("ACCURACY GATE: PASS — %s", verdict.reason)
        else:
            logger.warning("ACCURACY GATE: FAIL — %s", verdict.reason)
        return verdict

    def report_batch_quality(self, decisions: List[dict]) -> Dict:
        """Compute and log quality metrics for a decision batch."""
        metrics = compute_quality_metrics(decisions)
        log_quality_metrics(metrics)

        # Save report to disk
        os.makedirs(self.config.reports_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(
            self.config.reports_dir, f"quality_{timestamp}.json"
        )
        with open(report_path, "w") as f:
            json.dump(metrics, f, indent=2)
        logger.info("Quality report saved: %s", report_path)

        return metrics

    def evaluate_ppo_batch(
        self,
        forge_eval_accuracy: float,
        ppo_win_rate: float,
        ppo_decisions: List[dict],
        baseline_accuracy: float,
        total_episodes: int = 0,
    ) -> GateVerdict:
        """
        Run all quality gates on a PPO batch. Returns a combined verdict.

        This is the main entry point for the distillation pipeline to decide
        whether to accept or reject a batch of PPO-generated training data.
        """
        # 1. Win rate gate
        win_verdict = self.check_win_rate(ppo_win_rate, total_episodes)
        if not win_verdict.accepted:
            return win_verdict

        # 2. Accuracy gate
        acc_verdict = self.check_accuracy(forge_eval_accuracy, baseline_accuracy)
        if not acc_verdict.accepted:
            return acc_verdict

        # 3. Log quality metrics (informational, doesn't block)
        quality_metrics = self.report_batch_quality(ppo_decisions)

        # 4. Check for extreme entropy collapse (soft warning)
        entropy_ratio = quality_metrics.get("entropy_ratio", 1.0)
        if entropy_ratio < 0.3:
            logger.warning(
                "LOW ENTROPY WARNING: action entropy ratio %.2f — "
                "possible mode collapse in PPO agent",
                entropy_ratio,
            )

        return GateVerdict(
            accepted=True,
            reason="All quality gates passed.",
            metrics={
                "win_rate": win_verdict.metrics,
                "accuracy": acc_verdict.metrics,
                "quality": quality_metrics,
            },
        )

    def save_verdict_history(self, path: str = None):
        """Save all verdict history to a JSON file."""
        if path is None:
            os.makedirs(self.config.reports_dir, exist_ok=True)
            path = os.path.join(self.config.reports_dir, "verdict_history.json")

        history = [v.to_dict() for v in self.verdicts]
        with open(path, "w") as f:
            json.dump(history, f, indent=2)
        logger.info("Verdict history saved: %s (%d entries)", path, len(history))
