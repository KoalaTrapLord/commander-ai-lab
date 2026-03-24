"""
Commander AI Lab — Self-Play Episode Generator
════════════════════════════════════════════════
Generates synthetic 1v1 Commander game episodes for PPO training.

Since we can't run real Forge games at training speed, this module
simulates simplified game episodes using:
  1. Random initial states (life, hand size, board)
  2. Turn-by-turn state evolution with heuristic transitions
  3. The agent's policy to select macro-actions at each decision point
  4. An opponent policy (learned, random, or heuristic)

The episode generator produces trajectories of:
    (state, action, reward, value, log_prob, done)
that feed directly into the RolloutBuffer for PPO training.

For real game integration (Phase 9+), the Java sim would call the
policy server and feed back actual game states — this synthetic
version allows training to begin immediately.

.. deprecated:: Phase 3 (Issue #83)
    Synthetic training mode is DEPRECATED for production training.
    Use forge_episode_generator.py with real Forge engine games.
    Retained ONLY for quick local testing and unit tests.
"""

import logging
import warnings
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import (
    NUM_ACTIONS, MacroAction, ACTION_TO_IDX, IDX_TO_ACTION,
    Playstyle, PLAYSTYLE_TO_IDX, STATE_DIMS, GamePhase, PHASE_TO_IDX,
)
from ml.training.reward import compute_intermediate_reward, compute_terminal_reward, RewardConfig
from ml.training.decision_exporter import DecisionExporter

logger = logging.getLogger("ml.self_play")

_TRAINING_DEPRECATION_MSG = (
    "self_play.py synthetic training is deprecated for production training (Issue #83). "
    "Use forge_episode_generator.py with real Forge engine games instead. "
    "Synthetic self-play is retained for local testing and unit tests only."
)


@dataclass
class PlayerState:
    """Simplified player state for synthetic games."""
    life_total: int = 40
    commander_damage_taken: int = 0
    mana_available: int = 0
    commander_tax: int = 0
    cards_in_hand: int = 7
    cards_in_graveyard: int = 0
    creatures_on_battlefield: int = 0
    total_power_on_board: int = 0
    commander_in_play: bool = False

    def to_dict(self) -> dict:
        return {
            "life_total": self.life_total,
            "commander_damage_taken": self.commander_damage_taken,
            "mana_available": self.mana_available,
            "commander_tax": self.commander_tax,
            "cards_in_hand": self.cards_in_hand,
            "cards_in_graveyard": self.cards_in_graveyard,
            "creatures_on_battlefield": self.creatures_on_battlefield,
            "total_power_on_board": self.total_power_on_board,
        }


@dataclass
class GameState:
    """Full synthetic game state."""
    turn: int = 1
    phase: str = "main_1"
    active_seat: int = 0
    players: list = field(default_factory=lambda: [PlayerState(), PlayerState()])
    game_over: bool = False
    winner: Optional[int] = None
    draw: bool = False
    timeout: bool = False

    def to_snapshot(self) -> dict:
        """Convert to DecisionSnapshot-compatible dict."""
        return {
            "turn": self.turn,
            "phase": self.phase,
            "active_seat": self.active_seat,
            "players": [p.to_dict() for p in self.players],
        }


def create_random_initial_state() -> GameState:
    """Create a randomized starting game state (turn 1-3)."""
    state = GameState()

    # Random starting turn (simulate some early game development)
    start_turn = random.randint(1, 3)
    state.turn = start_turn

    for i, p in enumerate(state.players):
        p.life_total = 40
        p.mana_available = start_turn + random.randint(0, 1)  # Ramp variance
        p.cards_in_hand = max(2, 7 - start_turn + random.randint(-1, 1))

        # Some early board presence
        if start_turn >= 2:
            p.creatures_on_battlefield = random.randint(0, 2)
            p.total_power_on_board = p.creatures_on_battlefield * random.randint(1, 3)
            p.cards_in_graveyard = random.randint(0, 2)

    state.active_seat = 0  # Agent always starts as seat 0
    return state


def apply_action(
    state: GameState,
    action_idx: int,
    player_seat: int,
) -> GameState:
    """Apply a macro-action to the game state, returning the new state.

    This is a simplified heuristic simulation — not a real MTG rules engine.
    It models approximate state transitions for training purposes.
    """
    player = state.players[player_seat]
    opponent = state.players[1 - player_seat]
    action = IDX_TO_ACTION[action_idx]

    # Decrement mana for actions that cost mana
    mana_costs = {
        MacroAction.CAST_CREATURE: random.randint(2, 5),
        MacroAction.CAST_REMOVAL: random.randint(2, 4),
        MacroAction.CAST_DRAW: random.randint(1, 3),
        MacroAction.CAST_RAMP: random.randint(1, 3),
        MacroAction.CAST_COMMANDER: max(3, 3 + player.commander_tax),
        MacroAction.ATTACK_OPPONENT: 0,
        MacroAction.HOLD_MANA: 0,
        MacroAction.PASS: 0,
    }

    cost = mana_costs[action]

    # Check if player has enough mana — if not, treat as pass
    if cost > player.mana_available:
        action = MacroAction.PASS

    if action == MacroAction.CAST_CREATURE:
        player.mana_available -= cost
        player.cards_in_hand = max(0, player.cards_in_hand - 1)
        player.creatures_on_battlefield += 1
        power = random.randint(1, 4)
        player.total_power_on_board += power

    elif action == MacroAction.CAST_REMOVAL:
        player.mana_available -= cost
        player.cards_in_hand = max(0, player.cards_in_hand - 1)
        if opponent.creatures_on_battlefield > 0:
            opponent.creatures_on_battlefield -= 1
            removed_power = random.randint(1, 4)
            opponent.total_power_on_board = max(
                0, opponent.total_power_on_board - removed_power
            )
            opponent.cards_in_graveyard += 1

    elif action == MacroAction.CAST_DRAW:
        player.mana_available -= cost
        player.cards_in_hand = max(0, player.cards_in_hand - 1)  # Cast the spell
        cards_drawn = random.randint(1, 3)
        player.cards_in_hand += cards_drawn

    elif action == MacroAction.CAST_RAMP:
        player.mana_available -= cost
        player.cards_in_hand = max(0, player.cards_in_hand - 1)
        # Ramp gives future mana — represented as a small immediate bonus
        # (In the next turn, mana naturally increases)

    elif action == MacroAction.CAST_COMMANDER:
        if not player.commander_in_play:
            player.mana_available -= cost
            player.commander_in_play = True
            player.creatures_on_battlefield += 1
            power = random.randint(3, 6)
            player.total_power_on_board += power

    elif action == MacroAction.ATTACK_OPPONENT:
        if player.creatures_on_battlefield > 0:
            # Calculate combat damage
            damage = player.total_power_on_board
            # Opponent may block with some creatures
            blocked_power = 0
            if opponent.creatures_on_battlefield > 0:
                blockers = random.randint(
                    0, min(opponent.creatures_on_battlefield,
                           player.creatures_on_battlefield)
                )
                blocked_power = blockers * random.randint(1, 3)

                # Some creatures die in combat
                attacking_deaths = random.randint(0, min(1, blockers))
                blocking_deaths = random.randint(0, blockers)
                player.creatures_on_battlefield = max(
                    0, player.creatures_on_battlefield - attacking_deaths
                )
                opponent.creatures_on_battlefield = max(
                    0, opponent.creatures_on_battlefield - blocking_deaths
                )

                player.total_power_on_board = max(
                    0, player.total_power_on_board - attacking_deaths * 2
                )
                opponent.total_power_on_board = max(
                    0, opponent.total_power_on_board - blocking_deaths * 2
                )
                opponent.cards_in_graveyard += blocking_deaths
                player.cards_in_graveyard += attacking_deaths

            net_damage = max(0, damage - blocked_power)
            opponent.life_total -= net_damage

            # Commander damage
            if player.commander_in_play and net_damage > 0:
                cmd_dmg = random.randint(1, min(net_damage, 5))
                opponent.commander_damage_taken += cmd_dmg

    elif action == MacroAction.HOLD_MANA:
        pass  # Intentionally hold mana — no state change

    elif action == MacroAction.PASS:
        pass  # End step — no state change

    # Check win conditions
    if opponent.life_total <= 0:
        state.game_over = True
        state.winner = player_seat
    elif opponent.commander_damage_taken >= 21:
        state.game_over = True
        state.winner = player_seat

    return state


def advance_turn(state: GameState) -> GameState:
    """Advance to the next turn in the game.

    Both players:
      - Get mana = turn number (simplified)
      - Draw a card
    """
    state.turn += 1

    # Check for timeout
    if state.turn > 25:
        state.game_over = True
        state.timeout = True
        # Whoever has more life wins, or draw
        if state.players[0].life_total > state.players[1].life_total:
            state.winner = 0
        elif state.players[1].life_total > state.players[0].life_total:
            state.winner = 1
        else:
            state.draw = True
        return state

    for p in state.players:
        p.mana_available = min(state.turn + random.randint(0, 2), 15)
        p.cards_in_hand += 1  # Draw for turn

    # Alternate phase
    state.phase = random.choice(["main_1", "main_2"])
    return state


def encode_state_simple(
    state: GameState,
    agent_seat: int,
    playstyle: str = "midrange",
) -> np.ndarray:
    """Encode a GameState into a flat feature vector for the policy network.

    Uses actual state dimensions from scope.py to match the supervised
    training format. Zones are filled with zero embeddings (no real cards).
    """
    agent = state.players[agent_seat]
    opp = state.players[1 - agent_seat]

    # --- Global Features (29 dims) ---
    features = []

    # Per-player scalars (agent first, then opponent) × 14 each = 28
    for p, is_active in [(agent, agent_seat == state.active_seat),
                         (opp, (1 - agent_seat) == state.active_seat)]:
        features.extend([
            p.life_total / 40.0,
            p.commander_damage_taken / 21.0,
            min(p.mana_available, 20) / 20.0,
            min(p.commander_tax, 10) / 10.0,
            min(p.cards_in_hand, 15) / 15.0,
            min(p.cards_in_graveyard, 100) / 100.0,
            min(p.creatures_on_battlefield, 30) / 30.0,
            min(p.total_power_on_board, 100) / 100.0,
            float(is_active),
            state.turn / 25.0,
        ])
        # Phase one-hot (4 dims)
        phase_idx = {"main_1": 0, "combat": 1, "main_2": 2, "end": 3}.get(
            state.phase, 0
        )
        phase_vec = [0.0] * 4
        phase_vec[phase_idx] = 1.0
        features.extend(phase_vec)

    # Turn number (1 dim)
    features.append(state.turn / 25.0)

    # --- Zone Embeddings (6144 dims) — zeros for synthetic ---
    zone_dims = STATE_DIMS.total_zone_dim  # 6144
    features.extend([0.0] * zone_dims)

    # --- Playstyle One-Hot (4 dims) ---
    ps_idx = {"aggro": 0, "control": 1, "midrange": 2, "combo": 3}.get(
        playstyle, 2
    )
    ps_vec = [0.0] * 4
    ps_vec[ps_idx] = 1.0
    features.extend(ps_vec)

    return np.array(features, dtype=np.float32)


class RandomPolicy:
    """Uniform random action selection (baseline opponent)."""

    def select_action(self, state_vec: np.ndarray) -> Tuple[int, float]:
        """Returns (action_index, log_prob)."""
        action = random.randint(0, NUM_ACTIONS - 1)
        log_prob = -np.log(NUM_ACTIONS)
        return action, log_prob


class HeuristicPolicy:
    """Simple heuristic opponent that makes reasonable-ish decisions."""

    def select_action(self, state_vec: np.ndarray) -> Tuple[int, float]:
        """Returns (action_index, log_prob)."""
        # Extract key features from the state vector
        # agent_life = state_vec[0] * 40 (index 0 in the flat vector)
        # agent_mana = state_vec[2] * 20 (index 2)
        # agent_creatures = state_vec[6] * 30 (index 6)
        # agent_hand = state_vec[4] * 15 (index 4)

        mana = state_vec[2] * 20
        creatures = state_vec[6] * 30
        hand = state_vec[4] * 15

        # Simple decision rules
        weights = np.ones(NUM_ACTIONS) * 0.5

        if mana >= 2:
            weights[ACTION_TO_IDX[MacroAction.CAST_CREATURE]] = 3.0
        if mana >= 2 and hand <= 3:
            weights[ACTION_TO_IDX[MacroAction.CAST_DRAW]] = 2.5
        if mana >= 1 and mana <= 4:
            weights[ACTION_TO_IDX[MacroAction.CAST_RAMP]] = 2.0
        if creatures >= 2:
            weights[ACTION_TO_IDX[MacroAction.ATTACK_OPPONENT]] = 4.0
        if mana >= 5:
            weights[ACTION_TO_IDX[MacroAction.CAST_COMMANDER]] = 2.0
        if mana < 2:
            weights[ACTION_TO_IDX[MacroAction.PASS]] = 3.0

        # Normalize to probabilities
        probs = weights / weights.sum()
        action = np.random.choice(NUM_ACTIONS, p=probs)
        log_prob = np.log(probs[action] + 1e-8)

        return int(action), float(log_prob)


def run_self_play_episode(
    agent_model,
    opponent_policy,
    agent_seat: int = 0,
    playstyle: str = "midrange",
    max_steps: int = 50,
    reward_config: RewardConfig = None,
    exporter: DecisionExporter = None,
) -> List[dict]:
    """Run a single self-play episode and return the trajectory.

    Args:
        agent_model: PolicyValueNetwork with forward_with_value method.
                    If None, uses random policy for the agent too.
        opponent_policy: Policy object with select_action(state_vec) method
        agent_seat: Agent's player seat (0 or 1)
        playstyle: Playstyle for state encoding
        max_steps: Maximum decision steps per episode
        reward_config: Reward configuration
        exporter: Optional DecisionExporter to record steps for distillation

    Returns:
        List of step dicts: [{state, action, reward, value, log_prob, done}, ...]
    """
    try:
        import torch
        import torch.nn.functional as F
    except ImportError:
        raise ImportError("PyTorch required for self-play")

    state = create_random_initial_state()
    trajectory = []
    opp_seat = 1 - agent_seat
    cfg = reward_config or RewardConfig()

    for step in range(max_steps):
        if state.game_over:
            break

        prev_snapshot = state.to_snapshot()

        # Agent's turn
        state_vec = encode_state_simple(state, agent_seat, playstyle)

        if agent_model is not None:
            # Detect device from model parameters (e.g. cuda:0)
            _device = next(agent_model.parameters()).device
            state_tensor = torch.from_numpy(state_vec).unsqueeze(0).to(_device)
            with torch.no_grad():
                logits, value = agent_model.forward_with_value(state_tensor)
                probs = F.softmax(logits, dim=-1)
                dist = torch.distributions.Categorical(probs)
                action = dist.sample()
                log_prob = dist.log_prob(action)

                action_idx = action.item()
                value_scalar = value.item()
                log_prob_scalar = log_prob.item()
        else:
            action_idx = random.randint(0, NUM_ACTIONS - 1)
            value_scalar = 0.0
            log_prob_scalar = -np.log(NUM_ACTIONS)

        # Apply agent's action
        state = apply_action(state, action_idx, agent_seat)

        if state.game_over:
            curr_snapshot = state.to_snapshot()
            reward = compute_intermediate_reward(
                prev_snapshot, curr_snapshot, IDX_TO_ACTION[action_idx].value,
                agent_seat, cfg
            )
            won = state.winner == agent_seat
            reward += compute_terminal_reward(won, state.draw, state.timeout, cfg)

            trajectory.append({
                "state": state_vec,
                "action": action_idx,
                "reward": reward,
                "value": value_scalar,
                "log_prob": log_prob_scalar,
                "done": True,
            })
            if exporter is not None:
                exporter.record_step(
                    game_state_snapshot=prev_snapshot,
                    action_idx=action_idx,
                    reward=reward,
                )
            break

        # Opponent's turn
        opp_state_vec = encode_state_simple(state, opp_seat, "midrange")
        opp_action, _ = opponent_policy.select_action(opp_state_vec)
        state = apply_action(state, opp_action, opp_seat)

        curr_snapshot = state.to_snapshot()

        if state.game_over:
            reward = compute_intermediate_reward(
                prev_snapshot, curr_snapshot, IDX_TO_ACTION[action_idx].value,
                agent_seat, cfg
            )
            won = state.winner == agent_seat
            reward += compute_terminal_reward(won, state.draw, state.timeout, cfg)

            trajectory.append({
                "state": state_vec,
                "action": action_idx,
                "reward": reward,
                "value": value_scalar,
                "log_prob": log_prob_scalar,
                "done": True,
            })
            if exporter is not None:
                exporter.record_step(
                    game_state_snapshot=prev_snapshot,
                    action_idx=action_idx,
                    reward=reward,
                )
            break

        # Intermediate reward
        reward = compute_intermediate_reward(
            prev_snapshot, curr_snapshot, IDX_TO_ACTION[action_idx].value,
            agent_seat, cfg
        )

        trajectory.append({
            "state": state_vec,
            "action": action_idx,
            "reward": reward,
            "value": value_scalar,
            "log_prob": log_prob_scalar,
            "done": False,
        })
        if exporter is not None:
            exporter.record_step(
                game_state_snapshot=prev_snapshot,
                action_idx=action_idx,
                reward=reward,
            )

        # Advance turn
        state = advance_turn(state)

    return trajectory


def collect_rollouts(
    agent_model,
    opponent_policy,
    buffer,
    num_episodes: int = 64,
    playstyle: str = "midrange",
    reward_config: RewardConfig = None,
    exporter: DecisionExporter = None,
) -> dict:
    """Collect multiple self-play episodes into a rollout buffer.

    Args:
        agent_model: PolicyValueNetwork (or None for random agent)
        opponent_policy: Opponent policy object
        buffer: RolloutBuffer to fill
        num_episodes: Number of episodes to collect
        playstyle: Agent playstyle
        reward_config: Reward configuration
        exporter: Optional DecisionExporter to record decisions for distillation

    Returns:
        Collection statistics dict
    """
    buffer.reset()
    total_wins = 0
    total_losses = 0
    total_draws = 0
    warnings.warn(_TRAINING_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
  total_steps = 0
    total_rewards = 0.0

    for ep in range(num_episodes):
        # Alternate agent seat for balanced training
        agent_seat = ep % 2

        if exporter is not None:
            exporter.begin_episode(agent_seat=agent_seat, playstyle=playstyle)

        trajectory = run_self_play_episode(
            agent_model=agent_model,
            opponent_policy=opponent_policy,
            agent_seat=agent_seat,
            playstyle=playstyle,
            reward_config=reward_config,
            exporter=exporter,
        )

        for step in trajectory:
            buffer.add(
                state=step["state"],
                action=step["action"],
                reward=step["reward"],
                value=step["value"],
                log_prob=step["log_prob"],
                done=step["done"],
            )
            total_rewards += step["reward"]

        total_steps += len(trajectory)

        # Track outcomes
        if trajectory and trajectory[-1]["done"]:
            final_reward = trajectory[-1]["reward"]
            if final_reward > 0.5:
                total_wins += 1
            elif final_reward < -0.5:
                total_losses += 1
            else:
                total_draws += 1

        if exporter is not None:
            won = trajectory and trajectory[-1]["done"] and trajectory[-1]["reward"] > 0.5
            ep_return = sum(s["reward"] for s in trajectory)
            exporter.end_episode(won=won, episode_return=ep_return)

    # Compute GAE after collection
    buffer.compute_returns_and_advantages(last_value=0.0)

    return {
        "episodes": num_episodes,
        "steps": total_steps,
        "avg_steps_per_ep": total_steps / max(num_episodes, 1),
        "total_reward": total_rewards,
        "avg_reward_per_ep": total_rewards / max(num_episodes, 1),
        "wins": total_wins,
        "losses": total_losses,
        "draws": total_draws,
        "win_rate": total_wins / max(num_episodes, 1),
        "buffer_size": buffer.size,
    }
