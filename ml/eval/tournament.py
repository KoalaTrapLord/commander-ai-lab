"""
Commander AI Lab — Tournament Evaluator (Phase 10)
═══════════════════════════════════════════════════
Round-robin evaluation of multiple AI policies:
  - Learned Policy (supervised or PPO checkpoint)
  - Heuristic Policy (rule-based baseline)
  - Random Policy (uniform random baseline)
  - Forge AI (via Java subprocess, when available)

Runs many synthetic games between each pair of policies,
tracks win rates, and produces a tournament results table.

Usage:
    python -m ml.eval.tournament
    python -m ml.eval.tournament --episodes 100 --checkpoint ml/models/checkpoints/best_ppo.pt
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import NUM_ACTIONS, STATE_DIMS, IDX_TO_ACTION
from ml.training.reward import RewardConfig
from ml.training.self_play import (
    GameState, create_random_initial_state, apply_action, advance_turn,
    encode_state_simple, RandomPolicy, HeuristicPolicy,
    run_self_play_episode,
)

logger = logging.getLogger("ml.eval.tournament")


class LearnedPolicy:
    """Policy that uses a trained neural network checkpoint."""

    def __init__(self, checkpoint_path: str, device: str = "cpu"):
        import torch
        import torch.nn.functional as F

        self.torch = torch
        self.F = F
        self.device = device
        self.model = None
        self.name = "learned"

        if os.path.exists(checkpoint_path):
            checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
            config = checkpoint.get("model_config", {})

            # Try PolicyValueNetwork first (PPO), fall back to PolicyNetwork (supervised)
            try:
                from ml.training.policy_network import PolicyValueNetwork
                self.model = PolicyValueNetwork(
                    input_dim=config.get("input_dim", STATE_DIMS.total_state_dim),
                    hidden_dim=config.get("hidden_dim", 512),
                    num_actions=config.get("num_actions", NUM_ACTIONS),
                    num_layers=config.get("num_layers", 3),
                    dropout=config.get("dropout", 0.0),
                ).to(device)
                self.model.load_state_dict(checkpoint["model_state_dict"])
                self.name = "learned_ppo"
            except (RuntimeError, KeyError):
                from ml.training.policy_network import PolicyNetwork
                self.model = PolicyNetwork(
                    input_dim=config.get("input_dim", STATE_DIMS.total_state_dim),
                    hidden_dim=config.get("hidden_dim", 512),
                    num_actions=config.get("num_actions", NUM_ACTIONS),
                    num_layers=config.get("num_layers", 3),
                    dropout=config.get("dropout", 0.0),
                ).to(device)
                self.model.load_state_dict(checkpoint["model_state_dict"])
                self.name = "learned_supervised"

            self.model.eval()
            logger.info("Loaded checkpoint: %s", checkpoint_path)
        else:
            logger.warning("Checkpoint not found: %s — will act as random", checkpoint_path)

    def select_action(self, state_vec: np.ndarray) -> Tuple[int, float]:
        if self.model is None:
            action = np.random.randint(0, NUM_ACTIONS)
            return action, -np.log(NUM_ACTIONS)

        state_tensor = self.torch.from_numpy(state_vec).unsqueeze(0).to(self.device)
        with self.torch.no_grad():
            if hasattr(self.model, 'forward_with_value'):
                logits, _ = self.model.forward_with_value(state_tensor)
            else:
                logits = self.model(state_tensor)

            probs = self.F.softmax(logits, dim=-1)
            action = probs.argmax(dim=-1).item()  # Greedy for evaluation
            log_prob = self.torch.log(probs[0, action]).item()

        return action, log_prob


@dataclass
class MatchResult:
    """Result of a single match between two policies."""
    policy_a: str
    policy_b: str
    winner: Optional[str]  # Name of winner, or None for draw
    steps: int
    total_reward_a: float
    total_reward_b: float
    timeout: bool = False


@dataclass
class TournamentResult:
    """Aggregated tournament results."""
    policies: List[str]
    match_results: List[MatchResult] = field(default_factory=list)
    win_matrix: Dict = field(default_factory=dict)
    win_rates: Dict = field(default_factory=dict)
    total_matches: int = 0
    total_time_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "policies": self.policies,
            "total_matches": self.total_matches,
            "total_time_s": round(self.total_time_s, 1),
            "win_rates": self.win_rates,
            "win_matrix": self.win_matrix,
            "matches": [
                {
                    "policy_a": m.policy_a,
                    "policy_b": m.policy_b,
                    "winner": m.winner,
                    "steps": m.steps,
                    "timeout": m.timeout,
                }
                for m in self.match_results
            ],
        }


def run_match(
    policy_a, name_a: str,
    policy_b, name_b: str,
    playstyle: str = "midrange",
    max_steps: int = 50,
    reward_config: RewardConfig = None,
) -> MatchResult:
    """Run a single match between two policies.

    policy_a plays as seat 0, policy_b as seat 1.
    """
    state = create_random_initial_state()
    cfg = reward_config or RewardConfig()

    total_reward_a = 0.0
    total_reward_b = 0.0
    steps = 0

    for step in range(max_steps):
        if state.game_over:
            break

        prev_snapshot = state.to_snapshot()

        # Policy A's turn (seat 0)
        state_vec_a = encode_state_simple(state, agent_seat=0, playstyle=playstyle)
        action_a, _ = policy_a.select_action(state_vec_a)
        state = apply_action(state, action_a, player_seat=0)

        if state.game_over:
            steps = step + 1
            break

        # Policy B's turn (seat 1)
        state_vec_b = encode_state_simple(state, agent_seat=1, playstyle=playstyle)
        action_b, _ = policy_b.select_action(state_vec_b)
        state = apply_action(state, action_b, player_seat=1)

        steps = step + 1

        if state.game_over:
            break

        state = advance_turn(state)

    # Determine winner
    winner = None
    timeout = False

    if state.game_over:
        if state.draw:
            winner = None
        elif state.timeout:
            timeout = True
            if state.winner is not None:
                winner = name_a if state.winner == 0 else name_b
        elif state.winner is not None:
            winner = name_a if state.winner == 0 else name_b
    else:
        # Max steps reached without game ending — check life totals
        timeout = True
        if state.players[0].life_total > state.players[1].life_total:
            winner = name_a
        elif state.players[1].life_total > state.players[0].life_total:
            winner = name_b
        # else draw

    return MatchResult(
        policy_a=name_a,
        policy_b=name_b,
        winner=winner,
        steps=steps,
        total_reward_a=total_reward_a,
        total_reward_b=total_reward_b,
        timeout=timeout,
    )


def run_tournament(
    policies: Dict[str, object],
    episodes_per_matchup: int = 100,
    playstyle: str = "midrange",
) -> TournamentResult:
    """Run a round-robin tournament between all policy pairs.

    Args:
        policies: Dict mapping policy name → policy object (with select_action method)
        episodes_per_matchup: Games per pair (played both sides)
        playstyle: Default playstyle

    Returns:
        TournamentResult with full stats
    """
    t_start = time.time()
    names = list(policies.keys())
    result = TournamentResult(policies=names)

    # Initialize win matrix
    for name in names:
        result.win_matrix[name] = {n: 0 for n in names}
        result.win_rates[name] = {"wins": 0, "losses": 0, "draws": 0, "total": 0}

    total_matchups = len(list(combinations(names, 2)))
    logger.info("Tournament: %d policies, %d matchups, %d games each (×2 sides) = %d total games",
                len(names), total_matchups, episodes_per_matchup,
                total_matchups * episodes_per_matchup * 2)
    logger.info("")

    for name_a, name_b in combinations(names, 2):
        policy_a = policies[name_a]
        policy_b = policies[name_b]

        a_wins = 0
        b_wins = 0
        draws = 0

        for ep in range(episodes_per_matchup):
            # Play both sides for fairness
            # Game 1: A as seat 0, B as seat 1
            m1 = run_match(policy_a, name_a, policy_b, name_b, playstyle=playstyle)
            result.match_results.append(m1)

            if m1.winner == name_a:
                a_wins += 1
            elif m1.winner == name_b:
                b_wins += 1
            else:
                draws += 1

            # Game 2: B as seat 0, A as seat 1
            m2 = run_match(policy_b, name_b, policy_a, name_a, playstyle=playstyle)
            result.match_results.append(m2)

            if m2.winner == name_a:
                a_wins += 1
            elif m2.winner == name_b:
                b_wins += 1
            else:
                draws += 1

        total_games = episodes_per_matchup * 2
        result.win_matrix[name_a][name_b] = a_wins
        result.win_matrix[name_b][name_a] = b_wins

        result.win_rates[name_a]["wins"] += a_wins
        result.win_rates[name_a]["losses"] += b_wins
        result.win_rates[name_a]["draws"] += draws
        result.win_rates[name_a]["total"] += total_games

        result.win_rates[name_b]["wins"] += b_wins
        result.win_rates[name_b]["losses"] += a_wins
        result.win_rates[name_b]["draws"] += draws
        result.win_rates[name_b]["total"] += total_games

        logger.info("  %s vs %s: %d-%d-%d (%.0f%% vs %.0f%%)",
                     name_a, name_b, a_wins, b_wins, draws,
                     a_wins / total_games * 100, b_wins / total_games * 100)

    result.total_matches = len(result.match_results)
    result.total_time_s = time.time() - t_start

    # Compute overall win rates
    for name in names:
        wr = result.win_rates[name]
        total = wr["total"]
        if total > 0:
            wr["win_rate"] = round(wr["wins"] / total, 4)
        else:
            wr["win_rate"] = 0.0

    return result


def print_tournament_results(result: TournamentResult):
    """Pretty-print tournament results."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  TOURNAMENT RESULTS")
    logger.info("=" * 60)
    logger.info("")

    # Leaderboard
    sorted_policies = sorted(
        result.policies,
        key=lambda n: result.win_rates[n].get("win_rate", 0),
        reverse=True,
    )

    logger.info("  %-20s %6s %6s %6s %6s %8s", "Policy", "Wins", "Losses", "Draws", "Total", "Win Rate")
    logger.info("  " + "-" * 56)

    for name in sorted_policies:
        wr = result.win_rates[name]
        logger.info("  %-20s %6d %6d %6d %6d %7.1f%%",
                     name, wr["wins"], wr["losses"], wr["draws"], wr["total"],
                     wr.get("win_rate", 0) * 100)

    # Win matrix
    logger.info("")
    logger.info("  Win Matrix (row beats column):")
    header = "  %-14s" + " %10s" * len(result.policies)
    logger.info(header, "", *result.policies)
    for name in result.policies:
        row = [result.win_matrix[name].get(n, "-") for n in result.policies]
        row_strs = [str(v) if name != n else "-" for v, n in zip(row, result.policies)]
        logger.info("  %-14s" + " %10s" * len(row_strs), name, *row_strs)

    logger.info("")
    logger.info("  Total matches: %d", result.total_matches)
    logger.info("  Total time:    %.1f s", result.total_time_s)
    logger.info("=" * 60)


def main():
    """CLI entry point for tournament evaluation."""
    import argparse

    parser = argparse.ArgumentParser(description="Commander AI Lab — Tournament Evaluator")
    parser.add_argument("--episodes", type=int, default=50,
                        help="Episodes per matchup pair (played ×2 for both sides)")
    parser.add_argument("--checkpoint", default=None,
                        help="Path to learned policy checkpoint (.pt)")
    parser.add_argument("--ppo-checkpoint", default=None,
                        help="Path to PPO checkpoint (.pt)")
    parser.add_argument("--playstyle", default="midrange")
    parser.add_argument("--output", default=None,
                        help="Save results JSON to this path")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Build policy roster
    policies = {
        "heuristic": HeuristicPolicy(),
        "random": RandomPolicy(),
    }

    # Add learned policies if checkpoints exist
    ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")

    supervised_path = args.checkpoint or os.path.join(ckpt_dir, "best_policy.pt")
    if os.path.exists(supervised_path):
        policies["supervised"] = LearnedPolicy(supervised_path)
        logger.info("Added supervised policy: %s", supervised_path)

    ppo_path = args.ppo_checkpoint or os.path.join(ckpt_dir, "best_ppo.pt")
    if os.path.exists(ppo_path):
        policies["ppo"] = LearnedPolicy(ppo_path)
        logger.info("Added PPO policy: %s", ppo_path)

    if len(policies) < 2:
        logger.error("Need at least 2 policies for a tournament. Train a model first.")
        sys.exit(1)

    logger.info("")

    # Run tournament
    result = run_tournament(
        policies=policies,
        episodes_per_matchup=args.episodes,
        playstyle=args.playstyle,
    )

    print_tournament_results(result)

    # Save results
    output_path = args.output or os.path.join(ckpt_dir, "tournament_results.json")
    with open(output_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    logger.info("Results saved: %s", output_path)


if __name__ == "__main__":
    main()
