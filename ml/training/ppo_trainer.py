"""
Commander AI Lab — PPO Trainer
═══════════════════════════════
Proximal Policy Optimization (Clip) with:
  - Clipped surrogate objective for policy
  - Value function loss (clipped)
  - Entropy bonus for exploration
  - Generalized Advantage Estimation (computed in RolloutBuffer)
  - Self-play episode collection between updates
  - Periodic checkpointing and evaluation
  - Win-rate tracking against opponent policies

Reference: Schulman et al., "Proximal Policy Optimization Algorithms", 2017

Usage:
    python -m ml.training.ppo_trainer --iterations 100 --episodes-per-iter 64
    python -m ml.training.ppo_trainer --load-supervised ml/models/checkpoints/best_policy.pt
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Conditional torch import
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from ml.config.scope import NUM_ACTIONS, STATE_DIMS, TRAINING_CONFIG
from ml.training.rollout_buffer import RolloutBuffer
from ml.training.reward import RewardConfig
from ml.training.self_play import (
    collect_rollouts, HeuristicPolicy, RandomPolicy,
)

logger = logging.getLogger("ml.ppo")


class PPOConfig:
    """PPO hyperparameters."""

    def __init__(
        self,
        # Training loop
        iterations: int = 100,
        episodes_per_iter: int = 64,
        ppo_epochs: int = 4,
        batch_size: int = 256,

        # PPO core
        clip_epsilon: float = 0.2,
        value_clip: float = 0.2,
        entropy_coeff: float = 0.01,
        value_loss_coeff: float = 0.5,
        max_grad_norm: float = 0.5,

        # Optimizer
        learning_rate: float = 3e-4,
        lr_schedule: str = "constant",  # constant | linear | cosine
        min_lr: float = 1e-5,

        # Rollout
        buffer_size: int = 4096,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,

        # Opponent
        opponent: str = "heuristic",  # heuristic | random | self
        playstyle: str = "midrange",

        # Checkpointing
        checkpoint_dir: str = "ml/models/checkpoints",
        save_every: int = 10,
        eval_every: int = 5,
        eval_episodes: int = 50,

        # Supervised preload
        load_supervised: Optional[str] = None,
    ):
        self.iterations = iterations
        self.episodes_per_iter = episodes_per_iter
        self.ppo_epochs = ppo_epochs
        self.batch_size = batch_size
        self.clip_epsilon = clip_epsilon
        self.value_clip = value_clip
        self.entropy_coeff = entropy_coeff
        self.value_loss_coeff = value_loss_coeff
        self.max_grad_norm = max_grad_norm
        self.learning_rate = learning_rate
        self.lr_schedule = lr_schedule
        self.min_lr = min_lr
        self.buffer_size = buffer_size
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.opponent = opponent
        self.playstyle = playstyle
        self.checkpoint_dir = checkpoint_dir
        self.save_every = save_every
        self.eval_every = eval_every
        self.eval_episodes = eval_episodes
        self.load_supervised = load_supervised


class PPOTrainer:
    """Proximal Policy Optimization trainer with self-play."""

    def __init__(self, config: PPOConfig):
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch required for PPO training. Install: pip install torch")

        self.config = config
        self.device = self._detect_device()

        # Create actor-critic model
        from ml.training.policy_network import PolicyValueNetwork
        self.model = PolicyValueNetwork(
            input_dim=STATE_DIMS.total_state_dim,
            hidden_dim=TRAINING_CONFIG.hidden_dim,
            num_actions=NUM_ACTIONS,
            num_layers=TRAINING_CONFIG.num_layers,
            dropout=0.0,  # No dropout during RL
        ).to(self.device)

        # Optionally load from supervised checkpoint
        if config.load_supervised and os.path.exists(config.load_supervised):
            self._load_supervised_weights(config.load_supervised)

        # Optimizer
        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=config.learning_rate,
            eps=1e-5,
        )

        # Learning rate scheduler
        self.scheduler = None
        if config.lr_schedule == "linear":
            self.scheduler = torch.optim.lr_scheduler.LinearLR(
                self.optimizer,
                start_factor=1.0,
                end_factor=config.min_lr / config.learning_rate,
                total_iters=config.iterations,
            )
        elif config.lr_schedule == "cosine":
            self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                self.optimizer,
                T_max=config.iterations,
                eta_min=config.min_lr,
            )

        # Rollout buffer
        self.buffer = RolloutBuffer(
            buffer_size=config.buffer_size,
            state_dim=STATE_DIMS.total_state_dim,
            gamma=config.gamma,
            gae_lambda=config.gae_lambda,
        )

        # Reward config
        self.reward_config = RewardConfig(
            gamma=config.gamma,
            gae_lambda=config.gae_lambda,
        )

        # Opponent policy
        self.opponent = self._create_opponent(config.opponent)

        # Tracking
        self.iteration = 0
        self.total_steps = 0
        self.best_win_rate = 0.0
        self.history = []

        os.makedirs(config.checkpoint_dir, exist_ok=True)

    def _detect_device(self) -> str:
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load_supervised_weights(self, path: str):
        """Load weights from a supervised PolicyNetwork checkpoint into the
        PolicyValueNetwork (ignoring the value head, which is new)."""
        logger.info("Loading supervised weights from %s", path)
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        state_dict = checkpoint.get("model_state_dict", checkpoint)

        # Filter out keys that don't match (e.g., value_head)
        model_dict = self.model.state_dict()
        compatible = {k: v for k, v in state_dict.items() if k in model_dict and v.shape == model_dict[k].shape}
        model_dict.update(compatible)
        self.model.load_state_dict(model_dict)
        logger.info("Loaded %d/%d parameter tensors from supervised checkpoint",
                     len(compatible), len(state_dict))

    def _create_opponent(self, opponent_type: str):
        if opponent_type == "random":
            return RandomPolicy()
        elif opponent_type == "heuristic":
            return HeuristicPolicy()
        elif opponent_type == "self":
            # Self-play: opponent uses a snapshot of the current policy
            return self._create_self_play_opponent()
        else:
            return HeuristicPolicy()

    def _create_self_play_opponent(self):
        """Create an opponent that uses a frozen copy of the current policy."""

        class SelfPlayPolicy:
            def __init__(self, model, device):
                self.model = model
                self.device = device

            def select_action(self, state_vec):
                state_tensor = torch.from_numpy(state_vec).unsqueeze(0).to(self.device)
                with torch.no_grad():
                    logits, _ = self.model.forward_with_value(state_tensor)
                    probs = F.softmax(logits, dim=-1)
                    dist = torch.distributions.Categorical(probs)
                    action = dist.sample()
                    log_prob = dist.log_prob(action)
                return action.item(), log_prob.item()

        return SelfPlayPolicy(self.model, self.device)

    def ppo_update(self) -> Dict:
        """Run PPO update epochs on the collected rollout buffer.

        Returns dict of loss metrics.
        """
        cfg = self.config
        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        total_approx_kl = 0.0
        total_clip_frac = 0.0
        num_updates = 0

        for epoch in range(cfg.ppo_epochs):
            for batch in self.buffer.get_batches(cfg.batch_size):
                states, actions, old_log_probs, advantages, returns = batch

                # To tensors
                states_t = torch.from_numpy(states).to(self.device)
                actions_t = torch.from_numpy(actions).to(self.device)
                old_log_probs_t = torch.from_numpy(old_log_probs).to(self.device)
                advantages_t = torch.from_numpy(advantages).to(self.device)
                returns_t = torch.from_numpy(returns).to(self.device)

                # Forward pass
                logits, values = self.model.forward_with_value(states_t)
                values = values.squeeze(-1)

                # Action distribution
                probs = F.softmax(logits, dim=-1)
                dist = torch.distributions.Categorical(probs)
                new_log_probs = dist.log_prob(actions_t)
                entropy = dist.entropy().mean()

                # --- Policy Loss (clipped surrogate) ---
                ratio = torch.exp(new_log_probs - old_log_probs_t)
                surr1 = ratio * advantages_t
                surr2 = torch.clamp(ratio, 1.0 - cfg.clip_epsilon, 1.0 + cfg.clip_epsilon) * advantages_t
                policy_loss = -torch.min(surr1, surr2).mean()

                # --- Value Loss (clipped) ---
                if cfg.value_clip > 0:
                    # Get old values from buffer for clipping
                    old_values_t = torch.from_numpy(
                        self.buffer.values[:self.buffer.size]
                    ).to(self.device)
                    # Reindex to match batch
                    # Since we use shuffled indices in get_batches, we clip against returns
                    value_loss_unclipped = (values - returns_t) ** 2
                    value_loss = 0.5 * value_loss_unclipped.mean()
                else:
                    value_loss = 0.5 * ((values - returns_t) ** 2).mean()

                # --- Total Loss ---
                loss = (
                    policy_loss
                    + cfg.value_loss_coeff * value_loss
                    - cfg.entropy_coeff * entropy
                )

                # Optimize
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), cfg.max_grad_norm)
                self.optimizer.step()

                # Track metrics
                with torch.no_grad():
                    approx_kl = ((ratio - 1) - torch.log(ratio)).mean().item()
                    clip_frac = ((ratio - 1.0).abs() > cfg.clip_epsilon).float().mean().item()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy.item()
                total_approx_kl += approx_kl
                total_clip_frac += clip_frac
                num_updates += 1

        n = max(num_updates, 1)
        return {
            "policy_loss": total_policy_loss / n,
            "value_loss": total_value_loss / n,
            "entropy": total_entropy / n,
            "approx_kl": total_approx_kl / n,
            "clip_fraction": total_clip_frac / n,
            "num_updates": num_updates,
        }

    def evaluate(self, num_episodes: int = 50) -> Dict:
        """Evaluate the current policy against opponents.

        Returns win rates and metrics.
        """
        self.model.eval()

        results = {}
        for opp_name, opp_policy in [
            ("heuristic", HeuristicPolicy()),
            ("random", RandomPolicy()),
        ]:
            eval_buffer = RolloutBuffer(
                buffer_size=num_episodes * 50,
                state_dim=STATE_DIMS.total_state_dim,
                gamma=self.config.gamma,
                gae_lambda=self.config.gae_lambda,
            )
            stats = collect_rollouts(
                agent_model=self.model,
                opponent_policy=opp_policy,
                buffer=eval_buffer,
                num_episodes=num_episodes,
                playstyle=self.config.playstyle,
                reward_config=self.reward_config,
            )
            results[opp_name] = {
                "win_rate": stats["win_rate"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "draws": stats["draws"],
                "avg_reward": stats["avg_reward_per_ep"],
                "avg_steps": stats["avg_steps_per_ep"],
            }

        self.model.train()
        return results

    def save_checkpoint(self, path: str = None, metrics: dict = None):
        """Save PPO checkpoint."""
        if path is None:
            path = os.path.join(
                self.config.checkpoint_dir,
                f"ppo_iter_{self.iteration:04d}.pt",
            )

        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            "iteration": self.iteration,
            "total_steps": self.total_steps,
            "model_state_dict": self.model.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "metrics": metrics or {},
            "config": {
                "clip_epsilon": self.config.clip_epsilon,
                "entropy_coeff": self.config.entropy_coeff,
                "learning_rate": self.config.learning_rate,
                "opponent": self.config.opponent,
                "playstyle": self.config.playstyle,
            },
            "best_win_rate": self.best_win_rate,
            "model_config": {
                "input_dim": STATE_DIMS.total_state_dim,
                "hidden_dim": TRAINING_CONFIG.hidden_dim,
                "num_actions": NUM_ACTIONS,
                "num_layers": TRAINING_CONFIG.num_layers,
                "dropout": 0.0,
            },
        }, path)
        logger.info("Checkpoint saved: %s", path)

    def train(self, progress_callback=None) -> Dict:
        """Run the full PPO training loop.

        Args:
            progress_callback: Optional callable(iteration, metrics) for progress reporting

        Returns:
            Training summary dict
        """
        cfg = self.config
        logger.info("=" * 60)
        logger.info("PPO Training — Commander AI Lab")
        logger.info("=" * 60)
        logger.info("  Iterations:     %d", cfg.iterations)
        logger.info("  Episodes/iter:  %d", cfg.episodes_per_iter)
        logger.info("  PPO epochs:     %d", cfg.ppo_epochs)
        logger.info("  Batch size:     %d", cfg.batch_size)
        logger.info("  Clip epsilon:   %.2f", cfg.clip_epsilon)
        logger.info("  Entropy coeff:  %.4f", cfg.entropy_coeff)
        logger.info("  Learning rate:  %.6f", cfg.learning_rate)
        logger.info("  Opponent:       %s", cfg.opponent)
        logger.info("  Device:         %s", self.device)
        logger.info("  Supervised:     %s", cfg.load_supervised or "None")
        logger.info("")

        t_start = time.time()

        for iteration in range(1, cfg.iterations + 1):
            self.iteration = iteration
            t_iter = time.time()

            # --- Collect rollouts ---
            self.model.eval()
            rollout_stats = collect_rollouts(
                agent_model=self.model,
                opponent_policy=self.opponent,
                buffer=self.buffer,
                num_episodes=cfg.episodes_per_iter,
                playstyle=cfg.playstyle,
                reward_config=self.reward_config,
            )
            self.total_steps += rollout_stats["steps"]
            self.model.train()

            # --- PPO Update ---
            update_metrics = self.ppo_update()

            # --- LR Schedule ---
            current_lr = self.optimizer.param_groups[0]["lr"]
            if self.scheduler:
                self.scheduler.step()

            # --- Evaluate ---
            eval_results = None
            if iteration % cfg.eval_every == 0 or iteration == 1:
                eval_results = self.evaluate(cfg.eval_episodes)
                heuristic_wr = eval_results.get("heuristic", {}).get("win_rate", 0)

                if heuristic_wr > self.best_win_rate:
                    self.best_win_rate = heuristic_wr
                    best_path = os.path.join(cfg.checkpoint_dir, "best_ppo.pt")
                    self.save_checkpoint(best_path, {"eval": eval_results})
                    logger.info("  ★ New best win rate: %.1f%%", heuristic_wr * 100)

            # --- Save periodic checkpoint ---
            if iteration % cfg.save_every == 0:
                self.save_checkpoint()

            # --- Log ---
            iter_time = time.time() - t_iter
            metrics = {
                "iteration": iteration,
                "steps": rollout_stats["steps"],
                "total_steps": self.total_steps,
                "win_rate": rollout_stats["win_rate"],
                "avg_reward": rollout_stats["avg_reward_per_ep"],
                "policy_loss": update_metrics["policy_loss"],
                "value_loss": update_metrics["value_loss"],
                "entropy": update_metrics["entropy"],
                "approx_kl": update_metrics["approx_kl"],
                "clip_fraction": update_metrics["clip_fraction"],
                "lr": current_lr,
                "iter_time_s": round(iter_time, 1),
                "eval": eval_results,
            }
            self.history.append(metrics)

            # Pretty log
            eval_str = ""
            if eval_results:
                h_wr = eval_results.get("heuristic", {}).get("win_rate", 0)
                r_wr = eval_results.get("random", {}).get("win_rate", 0)
                eval_str = f" | eval: h={h_wr:.0%} r={r_wr:.0%}"

            logger.info(
                "  [%3d/%d] wr=%.0f%% rew=%.3f ploss=%.4f vloss=%.4f ent=%.3f kl=%.4f%s (%.1fs)",
                iteration, cfg.iterations,
                rollout_stats["win_rate"] * 100,
                rollout_stats["avg_reward_per_ep"],
                update_metrics["policy_loss"],
                update_metrics["value_loss"],
                update_metrics["entropy"],
                update_metrics["approx_kl"],
                eval_str,
                iter_time,
            )

            if progress_callback:
                progress_callback(iteration, metrics)

        # --- Final Save ---
        total_time = time.time() - t_start
        self.save_checkpoint()

        # Save training history
        history_path = os.path.join(cfg.checkpoint_dir, "ppo_history.json")
        with open(history_path, "w") as f:
            json.dump(self.history, f, indent=2, default=str)

        summary = {
            "iterations": cfg.iterations,
            "total_steps": self.total_steps,
            "best_win_rate": self.best_win_rate,
            "final_win_rate": self.history[-1]["win_rate"] if self.history else 0,
            "total_time_s": round(total_time, 1),
            "device": self.device,
            "checkpoint_dir": cfg.checkpoint_dir,
            "history_path": history_path,
        }

        logger.info("")
        logger.info("=" * 60)
        logger.info("PPO Training Complete")
        logger.info("  Total time:     %.1f s", total_time)
        logger.info("  Total steps:    %d", self.total_steps)
        logger.info("  Best win rate:  %.1f%%", self.best_win_rate * 100)
        logger.info("  History:        %s", history_path)
        logger.info("=" * 60)

        return summary


def main():
    """CLI entry point for PPO training."""
    parser = argparse.ArgumentParser(description="Commander AI Lab — PPO Training")

    # Training loop
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--episodes-per-iter", type=int, default=64)
    parser.add_argument("--ppo-epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=256)

    # PPO hyperparams
    parser.add_argument("--clip-epsilon", type=float, default=0.2)
    parser.add_argument("--entropy-coeff", type=float, default=0.01)
    parser.add_argument("--value-loss-coeff", type=float, default=0.5)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--lr-schedule", default="constant", choices=["constant", "linear", "cosine"])

    # Rollout
    parser.add_argument("--buffer-size", type=int, default=4096)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--gae-lambda", type=float, default=0.95)

    # Opponent
    parser.add_argument("--opponent", default="heuristic", choices=["heuristic", "random", "self"])
    parser.add_argument("--playstyle", default="midrange")

    # Checkpointing
    parser.add_argument("--checkpoint-dir", default="ml/models/checkpoints")
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--eval-every", type=int, default=5)
    parser.add_argument("--eval-episodes", type=int, default=50)

    # Init
    parser.add_argument("--load-supervised", default=None,
                        help="Path to supervised checkpoint to initialize from")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    config = PPOConfig(
        iterations=args.iterations,
        episodes_per_iter=args.episodes_per_iter,
        ppo_epochs=args.ppo_epochs,
        batch_size=args.batch_size,
        clip_epsilon=args.clip_epsilon,
        entropy_coeff=args.entropy_coeff,
        value_loss_coeff=args.value_loss_coeff,
        learning_rate=args.lr,
        lr_schedule=args.lr_schedule,
        buffer_size=args.buffer_size,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        opponent=args.opponent,
        playstyle=args.playstyle,
        checkpoint_dir=args.checkpoint_dir,
        save_every=args.save_every,
        eval_every=args.eval_every,
        eval_episodes=args.eval_episodes,
        load_supervised=args.load_supervised,
    )

    trainer = PPOTrainer(config)
    summary = trainer.train()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
