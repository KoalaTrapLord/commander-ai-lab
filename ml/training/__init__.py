"""
Commander AI Lab - Training Subpackage
======================================
Provides RL training infrastructure including PPO, rollout buffers,
Forge episode generation, self-play, and distillation.
"""

from ml.training.rollout_buffer import RolloutBuffer, ForgeEpisodeQueue
from ml.training.reward import compute_intermediate_reward, compute_terminal_reward, RewardConfig
from ml.training.decision_exporter import DecisionExporter
from ml.training.forge_episode_generator import (
    ForgeEpisodeGenerator,
    AsyncForgeEpisodeGenerator,
)

__all__ = [
    # Rollout & Buffers
    "RolloutBuffer",
    "ForgeEpisodeQueue",
    # Rewards
    "compute_intermediate_reward",
    "compute_terminal_reward",
    "RewardConfig",
    # Decision export
    "DecisionExporter",
    # Forge episode generation (Phase 3)
    "ForgeEpisodeGenerator",
    "AsyncForgeEpisodeGenerator",
]
