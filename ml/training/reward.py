"""
Commander AI Lab — Reward Shaping for RL
═════════════════════════════════════════
Computes intermediate and terminal rewards for PPO training.

Reward signals (1v1 Commander):
  Terminal:
    +1.0  for winning the game
    -1.0  for losing the game
     0.0  for draw / timeout

  Intermediate (dense shaping, scaled small to avoid dominating terminal):
    Life delta:      +0.01 per life point gained, -0.01 per life lost
    Board control:   +0.005 per creature advantage over opponent
    Damage dealt:    +0.01 per point of damage dealt this turn
    Commander cast:  +0.02 for casting commander (tempo boost signal)
    Card advantage:  +0.005 per card in hand above opponent

All intermediate rewards are optional and configurable via RewardConfig.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class RewardConfig:
    """Weights for reward shaping components."""
    # Terminal rewards
    win_reward: float = 1.0
    loss_reward: float = -1.0
    draw_reward: float = 0.0
    timeout_reward: float = -0.1        # Slight penalty for games timing out

    # Intermediate reward weights (set to 0.0 to disable)
    life_delta_weight: float = 0.01     # Per life point change
    board_control_weight: float = 0.005 # Per creature advantage
    damage_dealt_weight: float = 0.01   # Per damage dealt
    commander_cast_weight: float = 0.02 # Bonus for casting commander
    card_advantage_weight: float = 0.005 # Per card advantage in hand

    # Discount factor for GAE
    gamma: float = 0.99
    # GAE lambda
    gae_lambda: float = 0.95

    # Clip intermediate rewards to prevent outliers
    intermediate_clip: float = 0.1


REWARD_CONFIG = RewardConfig()


def compute_terminal_reward(
    won: bool,
    draw: bool = False,
    timeout: bool = False,
    config: RewardConfig = None,
) -> float:
    """Compute terminal reward for end of game.

    Args:
        won: True if the agent won
        draw: True if the game was a draw
        timeout: True if the game hit the turn limit
        config: Reward weights

    Returns:
        Terminal reward scalar
    """
    cfg = config or REWARD_CONFIG

    if draw:
        return cfg.draw_reward
    if timeout:
        return cfg.timeout_reward
    return cfg.win_reward if won else cfg.loss_reward


def compute_intermediate_reward(
    prev_state: Dict,
    curr_state: Dict,
    action_taken: str,
    agent_seat: int = 0,
    config: RewardConfig = None,
) -> float:
    """Compute dense intermediate reward from state transition.

    Args:
        prev_state: Previous game state snapshot (DecisionSnapshot-like dict)
        curr_state: Current game state snapshot after action
        action_taken: The macro-action string that was taken
        agent_seat: Which player seat is the agent (0 or 1)
        config: Reward weights

    Returns:
        Intermediate reward scalar (clipped)
    """
    cfg = config or REWARD_CONFIG
    reward = 0.0

    opp_seat = 1 - agent_seat

    # Extract player states
    prev_players = prev_state.get("players", [])
    curr_players = curr_state.get("players", [])

    if len(prev_players) < 2 or len(curr_players) < 2:
        return 0.0

    prev_agent = prev_players[agent_seat]
    curr_agent = curr_players[agent_seat]
    prev_opp = prev_players[opp_seat]
    curr_opp = curr_players[opp_seat]

    # --- Life Delta ---
    if cfg.life_delta_weight != 0.0:
        agent_life_delta = (
            curr_agent.get("life_total", 40) - prev_agent.get("life_total", 40)
        )
        opp_life_delta = (
            curr_opp.get("life_total", 40) - prev_opp.get("life_total", 40)
        )
        # Agent gaining life is good, opponent losing life is good
        reward += cfg.life_delta_weight * (agent_life_delta - opp_life_delta)

    # --- Board Control (creature count advantage) ---
    if cfg.board_control_weight != 0.0:
        agent_creatures = curr_agent.get("creatures_on_battlefield", 0)
        opp_creatures = curr_opp.get("creatures_on_battlefield", 0)
        prev_agent_creatures = prev_agent.get("creatures_on_battlefield", 0)
        prev_opp_creatures = prev_opp.get("creatures_on_battlefield", 0)

        # Change in creature advantage
        prev_advantage = prev_agent_creatures - prev_opp_creatures
        curr_advantage = agent_creatures - opp_creatures
        board_delta = curr_advantage - prev_advantage
        reward += cfg.board_control_weight * board_delta

    # --- Damage Dealt ---
    if cfg.damage_dealt_weight != 0.0:
        # Damage dealt = opponent life decrease this step
        opp_life_lost = max(
            0,
            prev_opp.get("life_total", 40) - curr_opp.get("life_total", 40)
        )
        reward += cfg.damage_dealt_weight * opp_life_lost

    # --- Commander Cast Bonus ---
    if cfg.commander_cast_weight != 0.0 and action_taken == "cast_commander":
        reward += cfg.commander_cast_weight

    # --- Card Advantage ---
    if cfg.card_advantage_weight != 0.0:
        agent_cards = curr_agent.get("cards_in_hand", 0)
        opp_cards = curr_opp.get("cards_in_hand", 0)
        prev_agent_cards = prev_agent.get("cards_in_hand", 0)
        prev_opp_cards = prev_opp.get("cards_in_hand", 0)

        prev_card_adv = prev_agent_cards - prev_opp_cards
        curr_card_adv = agent_cards - opp_cards
        card_delta = curr_card_adv - prev_card_adv
        reward += cfg.card_advantage_weight * card_delta

    # Clip to prevent extreme intermediate rewards
    reward = max(-cfg.intermediate_clip, min(cfg.intermediate_clip, reward))

    return reward


def compute_game_rewards(
    trajectory: list,
    won: bool,
    draw: bool = False,
    timeout: bool = False,
    agent_seat: int = 0,
    config: RewardConfig = None,
) -> list:
    """Compute rewards for an entire game trajectory.

    Args:
        trajectory: List of (prev_state, curr_state, action_taken) tuples
        won: Did the agent win?
        draw: Was it a draw?
        timeout: Did the game time out?
        agent_seat: Agent's player seat (0 or 1)
        config: Reward configuration

    Returns:
        List of reward floats, one per step. Terminal reward added to last step.
    """
    cfg = config or REWARD_CONFIG
    rewards = []

    for prev_state, curr_state, action_taken in trajectory:
        r = compute_intermediate_reward(
            prev_state, curr_state, action_taken, agent_seat, cfg
        )
        rewards.append(r)

    # Add terminal reward to last step
    if rewards:
        terminal = compute_terminal_reward(won, draw, timeout, cfg)
        rewards[-1] += terminal

    return rewards
