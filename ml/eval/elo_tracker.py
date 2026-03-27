"""
Commander AI Lab — ELO Tracker & Cross-Generation Tournament
═══════════════════════════════════════════════════════════════
Phase 6 (Issue #70): Quantify improvement across distillation
generations using ELO ratings.

- Runs round-robin tournaments between generation checkpoints
  and baselines (heuristic, random)
- Computes ELO ratings using the standard formula
- Persists ELO history to `data/elo_history.json`
- Provides ELO delta for convergence detection

Reuses `run_match`, `LearnedPolicy`, `HeuristicPolicy`,
`RandomPolicy` from `ml/eval/tournament.py`.

Usage:
    python -m ml.eval.elo_tracker
    python -m ml.eval.elo_tracker --episodes 50 --output data/elo_history.json
    python -m ml.eval.elo_tracker --top-n 10
"""

import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.eval.tournament import (
    run_match, LearnedPolicy, HeuristicPolicy, RandomPolicy,
)

logger = logging.getLogger("ml.eval.elo")


# ═══════════════════════════════════════════════════════════
# ELO Rating Engine
# ═══════════════════════════════════════════════════════════

DEFAULT_K = 32
DEFAULT_START_ELO = 1200.0


class EloTracker:
    """Standard ELO rating tracker."""

    def __init__(self, k_factor: float = DEFAULT_K, start_elo: float = DEFAULT_START_ELO):
        self.k = k_factor
        self.start_elo = start_elo
        self.ratings: Dict[str, float] = {}

    def ensure_player(self, name: str):
        if name not in self.ratings:
            self.ratings[name] = self.start_elo

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400.0))

    def update(self, winner: str, loser: str):
        """Update ratings after a decisive match."""
        self.ensure_player(winner)
        self.ensure_player(loser)

        e_win = self.expected_score(self.ratings[winner], self.ratings[loser])
        e_lose = self.expected_score(self.ratings[loser], self.ratings[winner])

        self.ratings[winner] += self.k * (1.0 - e_win)
        self.ratings[loser] += self.k * (0.0 - e_lose)

    def update_draw(self, player_a: str, player_b: str):
        """Update ratings after a draw."""
        self.ensure_player(player_a)
        self.ensure_player(player_b)

        e_a = self.expected_score(self.ratings[player_a], self.ratings[player_b])
        e_b = self.expected_score(self.ratings[player_b], self.ratings[player_a])

        self.ratings[player_a] += self.k * (0.5 - e_a)
        self.ratings[player_b] += self.k * (0.5 - e_b)

    def get_ratings(self) -> Dict[str, float]:
        """Return a copy of current ratings, rounded to 1 decimal."""
        return {k: round(v, 1) for k, v in self.ratings.items()}


# ═══════════════════════════════════════════════════════════
# ELO Result
# ═══════════════════════════════════════════════════════════

@dataclass
class EloResult:
    """Result of an ELO-rated tournament."""
    ratings: Dict[str, float] = field(default_factory=dict)
    match_count: int = 0
    total_time_s: float = 0.0
    policies: List[str] = field(default_factory=list)
    rating_progression: List[Dict[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ratings": self.ratings,
            "match_count": self.match_count,
            "total_time_s": round(self.total_time_s, 1),
            "policies": self.policies,
            "rating_progression": self.rating_progression,
        }


# ═══════════════════════════════════════════════════════════
# ELO History (persistence)
# ═══════════════════════════════════════════════════════════

class EloHistory:
    """Persists ELO ratings across tournament runs."""

    def __init__(self, path: str = "data/elo_history.json"):
        self.path = path
        self.entries: List[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                self.entries = data.get("entries", [])
            except Exception:
                self.entries = []

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"entries": self.entries}, f, indent=2)

    def append(self, generation: int, ratings: Dict[str, float]):
        """Add a new ELO snapshot after a tournament."""
        self.entries.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "generation": generation,
            "ratings": {k: round(v, 1) for k, v in ratings.items()},
        })
        self.save()

    def get_elo_delta(self, window: int = 2) -> Optional[float]:
        """
        Compute average ELO gain of the latest generation model
        over the last `window` entries.

        Returns None if insufficient data.
        """
        if len(self.entries) < window:
            return None

        recent = self.entries[-window:]
        deltas = []

        for i in range(1, len(recent)):
            prev_ratings = recent[i - 1]["ratings"]
            curr_ratings = recent[i]["ratings"]

            # Find the latest generation model name in current entry
            gen_models = [k for k in curr_ratings if k.startswith("gen-")]
            if not gen_models:
                continue

            latest_gen = sorted(gen_models)[-1]
            curr_elo = curr_ratings.get(latest_gen, DEFAULT_START_ELO)

            # Compare to previous entry's latest gen model, or heuristic
            prev_gen_models = [k for k in prev_ratings if k.startswith("gen-")]
            if prev_gen_models:
                prev_latest = sorted(prev_gen_models)[-1]
                prev_elo = prev_ratings.get(prev_latest, DEFAULT_START_ELO)
            else:
                prev_elo = prev_ratings.get("heuristic", DEFAULT_START_ELO)

            deltas.append(curr_elo - prev_elo)

        if not deltas:
            return None

        return sum(deltas) / len(deltas)

    def to_dict(self) -> dict:
        return {"entries": self.entries}

    @classmethod
    def from_dict(cls, data: dict, path: str = "data/elo_history.json") -> "EloHistory":
        h = cls.__new__(cls)
        h.path = path
        h.entries = data.get("entries", [])
        return h


# ═══════════════════════════════════════════════════════════
# Tournament Functions
# ═══════════════════════════════════════════════════════════

def run_elo_tournament(
    policies: Dict[str, object],
    episodes_per_matchup: int = 50,
    playstyle: str = "midrange",
    k_factor: float = DEFAULT_K,
) -> EloResult:
    """
    Run a round-robin ELO-rated tournament.

    Uses `run_match` from tournament.py for match execution.

    Args:
        policies: Dict mapping name → policy object (with select_action method)
        episodes_per_matchup: Games per pair (played both sides)
        playstyle: Game playstyle
        k_factor: ELO K-factor

    Returns:
        EloResult with final ratings, match count, and progression
    """
    t_start = time.time()
    names = list(policies.keys())
    tracker = EloTracker(k_factor=k_factor)

    # Initialize all players
    for name in names:
        tracker.ensure_player(name)

    progression = [tracker.get_ratings().copy()]
    total_matches = 0

    logger.info("ELO Tournament: %d policies, %d games/matchup", len(names), episodes_per_matchup)

    for name_a, name_b in combinations(names, 2):
        policy_a = policies[name_a]
        policy_b = policies[name_b]

        for ep in range(episodes_per_matchup):
            # Game 1: A as seat 0
            m1 = run_match(policy_a, name_a, policy_b, name_b, playstyle=playstyle)
            total_matches += 1
            if m1.winner == name_a:
                tracker.update(name_a, name_b)
            elif m1.winner == name_b:
                tracker.update(name_b, name_a)
            else:
                tracker.update_draw(name_a, name_b)

            # Game 2: B as seat 0
            m2 = run_match(policy_b, name_b, policy_a, name_a, playstyle=playstyle)
            total_matches += 1
            if m2.winner == name_a:
                tracker.update(name_a, name_b)
            elif m2.winner == name_b:
                tracker.update(name_b, name_a)
            else:
                tracker.update_draw(name_a, name_b)

        # Record progression after each matchup
        progression.append(tracker.get_ratings().copy())

        logger.info(
            "  %s (%.0f) vs %s (%.0f)",
            name_a, tracker.ratings[name_a],
            name_b, tracker.ratings[name_b],
        )

    return EloResult(
        ratings=tracker.get_ratings(),
        match_count=total_matches,
        total_time_s=time.time() - t_start,
        policies=names,
        rating_progression=progression,
    )


def run_generation_tournament(
    checkpoint_dir: str = "ml/models/checkpoints",
    episodes_per_matchup: int = 50,
    playstyle: str = "midrange",
    k_factor: float = DEFAULT_K,
    top_n: int = 10,
) -> EloResult:
    """
    Discover generation checkpoints and run an ELO tournament.

    Looks for `gen-*/best_policy.pt` under checkpoint_dir.
    Also includes heuristic and random baselines.

    Args:
        top_n: Only include the N most recent gen-* checkpoints.
               0 means include all (unbounded). Default is 10.
    """
    policies: Dict[str, object] = {
        "heuristic": HeuristicPolicy(),
        "random": RandomPolicy(),
    }

    ckpt_path = Path(checkpoint_dir)
    if ckpt_path.exists():
        gen_dirs = sorted(ckpt_path.glob("gen-*"))

        # Apply top_n cutoff — keep only the latest N generation dirs
        if top_n > 0 and len(gen_dirs) > top_n:
            skipped = len(gen_dirs) - top_n
            logger.info(
                "top_n=%d: skipping %d older generation(s), using %s … %s",
                top_n, skipped,
                gen_dirs[-top_n].name,
                gen_dirs[-1].name,
            )
            gen_dirs = gen_dirs[-top_n:]

        for gen_dir in gen_dirs:
            model_path = gen_dir / "best_policy.pt"
            if model_path.exists():
                name = gen_dir.name  # e.g., "gen-001"
                policies[name] = LearnedPolicy(str(model_path))
                logger.info("Loaded %s: %s", name, model_path)

        # Also check standard checkpoints
        sup_path = ckpt_path / "best_policy.pt"
        if sup_path.exists() and "supervised" not in policies:
            policies["supervised"] = LearnedPolicy(str(sup_path))

        ppo_path = ckpt_path / "best_ppo.pt"
        if ppo_path.exists() and "ppo" not in policies:
            policies["ppo"] = LearnedPolicy(str(ppo_path))

    if len(policies) < 2:
        logger.warning("Need at least 2 policies for ELO tournament")
        return EloResult(
            ratings={k: DEFAULT_START_ELO for k in policies},
            policies=list(policies.keys()),
        )

    logger.info("Running ELO tournament with %d policies: %s", len(policies), list(policies.keys()))

    return run_elo_tournament(
        policies=policies,
        episodes_per_matchup=episodes_per_matchup,
        playstyle=playstyle,
        k_factor=k_factor,
    )


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    """CLI entry point for ELO tournament."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Commander AI Lab — ELO Tournament"
    )
    parser.add_argument(
        "--episodes", type=int, default=50,
        help="Episodes per matchup (default: 50)",
    )
    parser.add_argument(
        "--checkpoint-dir", default="ml/models/checkpoints",
        help="Checkpoint directory (default: ml/models/checkpoints)",
    )
    parser.add_argument(
        "--playstyle", default="midrange",
        help="Playstyle (default: midrange)",
    )
    parser.add_argument(
        "--output", default="data/elo_history.json",
        help="Output path for ELO history (default: data/elo_history.json)",
    )
    parser.add_argument(
        "--k-factor", type=float, default=32,
        help="ELO K-factor (default: 32)",
    )
    parser.add_argument(
        "--top-n", type=int, default=10,
        help="Only include the N most recent gen checkpoints (0 = all, default: 10)",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    result = run_generation_tournament(
        checkpoint_dir=args.checkpoint_dir,
        episodes_per_matchup=args.episodes,
        playstyle=args.playstyle,
        k_factor=args.k_factor,
        top_n=args.top_n,
    )

    # Print results
    logger.info("")
    logger.info("=" * 50)
    logger.info("  ELO RATINGS")
    logger.info("=" * 50)
    sorted_ratings = sorted(result.ratings.items(), key=lambda x: x[1], reverse=True)
    for name, elo in sorted_ratings:
        logger.info("  %-20s %7.1f", name, elo)
    logger.info("")
    logger.info("  %d matches in %.1f s", result.match_count, result.total_time_s)
    logger.info("=" * 50)

    # Save to history
    history = EloHistory(path=args.output)
    # Use the latest generation number, or 0 if no gen models
    gen_models = [k for k in result.ratings if k.startswith("gen-")]
    gen_num = 0
    if gen_models:
        try:
            gen_num = max(int(g.split("-")[1]) for g in gen_models)
        except (ValueError, IndexError):
            pass
    history.append(gen_num, result.ratings)
    logger.info("ELO history saved: %s", args.output)

    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
