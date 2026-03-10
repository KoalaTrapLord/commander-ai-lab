"""
Commander AI Lab — Rollout Buffer for PPO
══════════════════════════════════════════
Stores experience trajectories collected during self-play episodes.
Computes Generalized Advantage Estimation (GAE) for PPO training.

Each step stores:
    state       — (state_dim,) float32 state vector
    action      — int action index
    reward      — float scalar reward
    value       — float V(s) from value head
    log_prob    — float log π(a|s) from policy
    done        — bool episode terminal flag

After collection, call compute_returns_and_advantages() to produce:
    returns     — GAE-based return targets for value head
    advantages  — Advantage estimates for policy gradient
"""

import numpy as np
from typing import List, Tuple


class RolloutBuffer:
    """Fixed-size buffer for PPO rollout collection.

    Collects experience from self-play, then computes GAE
    advantages for a PPO training update.
    """

    def __init__(self, buffer_size: int, state_dim: int, gamma: float = 0.99, gae_lambda: float = 0.95):
        """
        Args:
            buffer_size: Maximum number of steps to store
            state_dim: Dimension of state vector
            gamma: Discount factor
            gae_lambda: GAE lambda parameter
        """
        self.buffer_size = buffer_size
        self.state_dim = state_dim
        self.gamma = gamma
        self.gae_lambda = gae_lambda

        # Pre-allocate arrays
        self.states = np.zeros((buffer_size, state_dim), dtype=np.float32)
        self.actions = np.zeros(buffer_size, dtype=np.int64)
        self.rewards = np.zeros(buffer_size, dtype=np.float32)
        self.values = np.zeros(buffer_size, dtype=np.float32)
        self.log_probs = np.zeros(buffer_size, dtype=np.float32)
        self.dones = np.zeros(buffer_size, dtype=np.float32)

        # Computed after collection
        self.advantages = np.zeros(buffer_size, dtype=np.float32)
        self.returns = np.zeros(buffer_size, dtype=np.float32)

        self.pos = 0       # Current write position
        self.full = False  # Whether buffer has been filled

    @property
    def size(self) -> int:
        """Number of valid steps stored."""
        return self.buffer_size if self.full else self.pos

    def reset(self):
        """Clear the buffer for a new collection phase."""
        self.pos = 0
        self.full = False

    def add(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        value: float,
        log_prob: float,
        done: bool,
    ):
        """Add a single experience step.

        Args:
            state: State vector (state_dim,)
            action: Action index
            reward: Scalar reward
            value: V(s) from critic
            log_prob: log π(a|s) from actor
            done: True if episode ended after this step
        """
        if self.pos >= self.buffer_size:
            self.full = True
            return  # Buffer is full — silently drop

        self.states[self.pos] = state
        self.actions[self.pos] = action
        self.rewards[self.pos] = reward
        self.values[self.pos] = value
        self.log_probs[self.pos] = log_prob
        self.dones[self.pos] = float(done)

        self.pos += 1
        if self.pos >= self.buffer_size:
            self.full = True

    def compute_returns_and_advantages(self, last_value: float = 0.0):
        """Compute GAE advantages and discounted returns.

        Must be called after all steps are collected, before generating batches.

        Args:
            last_value: V(s_T+1) bootstrap value for the last state
                       (0.0 if the episode ended, else critic estimate)
        """
        n = self.size
        last_gae = 0.0

        for t in reversed(range(n)):
            if t == n - 1:
                next_non_terminal = 1.0 - self.dones[t]
                next_value = last_value
            else:
                next_non_terminal = 1.0 - self.dones[t]
                next_value = self.values[t + 1]

            # TD error: δ_t = r_t + γ * V(s_{t+1}) * (1 - done) - V(s_t)
            delta = (
                self.rewards[t]
                + self.gamma * next_value * next_non_terminal
                - self.values[t]
            )

            # GAE: A_t = δ_t + γλ * (1 - done) * A_{t+1}
            last_gae = delta + self.gamma * self.gae_lambda * next_non_terminal * last_gae
            self.advantages[t] = last_gae

        # Returns = advantages + values (for value function target)
        self.returns[:n] = self.advantages[:n] + self.values[:n]

    def get_batches(self, batch_size: int) -> List[Tuple]:
        """Generate random mini-batches for PPO update.

        Yields:
            (states, actions, old_log_probs, advantages, returns)
            as numpy arrays of shape (batch_size, ...)
        """
        n = self.size
        indices = np.random.permutation(n)

        # Normalize advantages
        adv = self.advantages[:n]
        adv_mean = adv.mean()
        adv_std = adv.std() + 1e-8
        normalized_adv = (adv - adv_mean) / adv_std

        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            batch_idx = indices[start:end]

            yield (
                self.states[batch_idx],
                self.actions[batch_idx],
                self.log_probs[batch_idx],
                normalized_adv[batch_idx],
                self.returns[batch_idx],
            )

    def get_stats(self) -> dict:
        """Get buffer statistics for logging."""
        n = self.size
        if n == 0:
            return {"size": 0}

        episodes = int(self.dones[:n].sum())
        return {
            "size": n,
            "episodes": episodes,
            "mean_reward": float(self.rewards[:n].mean()),
            "total_reward": float(self.rewards[:n].sum()),
            "mean_value": float(self.values[:n].mean()),
            "mean_advantage": float(self.advantages[:n].mean()),
            "std_advantage": float(self.advantages[:n].std()),
        }
