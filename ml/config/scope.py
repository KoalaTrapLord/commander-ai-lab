"""
Commander AI Lab — RL Scope Configuration
═══════════════════════════════════════════
Defines the simplified game scope, playstyle labels,
macro-action space, and state encoding dimensions for
the first RL prototype.

Design decisions:
  - 1v1 Commander (2 players, 40 life, commander damage 21)
  - ~8 macro-actions per decision point
  - 4 playstyle labels: Aggro, Control, Midrange, Combo
  - State = global features + per-zone card embeddings
"""

from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum

# ══════════════════════════════════════════════════════════
# Game Scope
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GameScope:
    """Simplified Commander rules for RL prototype."""
    pod_size: int = 2                   # 1v1
    starting_life: int = 40
    commander_damage_lethal: int = 21
    max_turns: int = 25                 # Force game end
    mulligan_rule: str = "london"
    format: str = "commander"

GAME_SCOPE = GameScope()


# ══════════════════════════════════════════════════════════
# Playstyle Labels
# ══════════════════════════════════════════════════════════

class Playstyle(str, Enum):
    """Deck archetype / playstyle labels.

    Each label implies a preferred strategic approach:
      AGGRO   — Prioritize attacking, fast damage, low curve
      CONTROL — Hold up mana, prioritize removal, card advantage
      MIDRANGE— Balanced: develop board, then attack when advantageous
      COMBO   — Protect combo pieces, tutor aggressively, race to assemble
    """
    AGGRO = "aggro"
    CONTROL = "control"
    MIDRANGE = "midrange"
    COMBO = "combo"


# Heuristic playstyle assignment rules (applied to deck metadata)
# These map deck characteristics → playstyle label
PLAYSTYLE_HEURISTICS = {
    Playstyle.AGGRO: {
        "avg_mana_value_max": 3.0,       # Low average CMC
        "creature_ratio_min": 0.30,       # High creature density
        "removal_ratio_max": 0.08,        # Low removal count
        "description": "Low curve, creature-heavy, minimal interaction"
    },
    Playstyle.CONTROL: {
        "avg_mana_value_min": 3.2,
        "removal_ratio_min": 0.10,        # High removal/interaction
        "creature_ratio_max": 0.25,
        "description": "High interaction, card advantage, late-game finishers"
    },
    Playstyle.MIDRANGE: {
        "avg_mana_value_min": 2.5,
        "avg_mana_value_max": 3.8,
        "creature_ratio_min": 0.20,
        "creature_ratio_max": 0.35,
        "description": "Balanced curve, flexible strategy"
    },
    Playstyle.COMBO: {
        "combo_pieces_min": 2,            # Has known combo cards
        "tutor_count_min": 2,             # Has tutors to find them
        "description": "Win via specific card combinations"
    },
}

# One-hot encoding dimension for playstyle
PLAYSTYLE_DIM = len(Playstyle)  # 4

# Mapping for one-hot encoding
PLAYSTYLE_TO_IDX: Dict[Playstyle, int] = {
    Playstyle.AGGRO: 0,
    Playstyle.CONTROL: 1,
    Playstyle.MIDRANGE: 2,
    Playstyle.COMBO: 3,
}


# ══════════════════════════════════════════════════════════
# Macro-Action Space
# ══════════════════════════════════════════════════════════

class MacroAction(str, Enum):
    """High-level actions the RL agent can choose.

    Each macro-action maps to one or more concrete Forge actions.
    The Java side translates the chosen macro into specific game moves.

    8 actions for the initial prototype:
    """
    # Proactive plays
    CAST_CREATURE       = "cast_creature"       # Play the best available creature
    CAST_REMOVAL        = "cast_removal"         # Cast removal on strongest enemy threat
    CAST_DRAW           = "cast_draw"            # Cast card-draw or cantrip spell
    CAST_RAMP           = "cast_ramp"            # Cast ramp spell or mana rock
    CAST_COMMANDER      = "cast_commander"       # Cast your commander from command zone

    # Combat
    ATTACK_OPPONENT     = "attack_opponent"      # Attack with all profitable attackers

    # Reactive / passive
    HOLD_MANA           = "hold_mana"            # Pass priority, keep mana open
    PASS                = "pass"                 # Pass with no action (end step, etc.)


# Number of discrete actions
NUM_ACTIONS = len(MacroAction)  # 8

# Action index mapping
ACTION_TO_IDX: Dict[MacroAction, int] = {a: i for i, a in enumerate(MacroAction)}
IDX_TO_ACTION: Dict[int, MacroAction] = {i: a for a, i in ACTION_TO_IDX.items()}


# ══════════════════════════════════════════════════════════
# State Encoding Dimensions
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StateDimensions:
    """Dimensions for the state vector encoding.

    State = [global_features | zone_embeddings | playstyle_vector]

    Global features (per player × 2 players):
      - life_total (normalized 0-1 by /40)
      - commander_damage_taken (normalized 0-1 by /21)
      - mana_available (0-20 range, normalized)
      - commander_tax (0-10 range, normalized)
      - cards_in_hand (0-15, normalized)
      - cards_in_graveyard (0-100, normalized)
      - creatures_on_battlefield (0-30, normalized)
      - total_power_on_board (0-100, normalized)
      - is_active_player (0 or 1)
      - turn_number (normalized 0-1 by /max_turns)
      - phase (one-hot: main1, combat, main2, end = 4)

    Per player = 10 scalar + 4 phase one-hot = 14 features
    2 players = 28 global features
    + turn_number = 1
    Total global = 29

    Zone embedding boundary (architectural decision — Phase 5 follow-up):
      Zone dims are **always** 768 per zone slot, zero-padded when a zone
      is empty (no cards).  The fixed 6144-dim zone block is the contract
      between ForgeEpisodeGenerator (upstream) and the policy network
      (downstream).  All downstream consumers (PolicyNetwork, PPOTrainer,
      dataset builder) depend on this shape.  If a future change adds
      attention pooling or variable-length zone representations, the
      boundary must be updated here *and* in StateEncoder._encode_zones.
    """
    card_embedding_dim: int = 768       # From mtg-embeddings
    zone_pool_dim: int = 768            # Mean-pooled per zone (zero-vec when empty)

    # Zones per player: hand, battlefield, graveyard, command_zone
    zones_per_player: int = 4
    num_players: int = 2                # 1v1

    # Zone vectors: 4 zones × 2 players × 768 = 6144
    # This is a fixed-size block; empty zones produce zero vectors.
    total_zone_dim: int = 4 * 2 * 768  # 6144

    # Global scalar features
    per_player_scalars: int = 10
    phase_onehot: int = 4               # main1, combat, main2, end
    per_player_features: int = 14       # 10 + 4
    global_features: int = 29           # 14×2 + 1 (turn)

    # Playstyle vector
    playstyle_dim: int = 4              # One-hot over 4 styles

    @property
    def total_state_dim(self) -> int:
        """Total dimension of the flattened state vector."""
        return self.global_features + self.total_zone_dim + self.playstyle_dim
        # 29 + 6144 + 4 = 6177

STATE_DIMS = StateDimensions()


# ══════════════════════════════════════════════════════════
# Game Phase Encoding
# ══════════════════════════════════════════════════════════

class GamePhase(str, Enum):
    MAIN_1 = "main_1"
    COMBAT = "combat"
    MAIN_2 = "main_2"
    END = "end"

PHASE_TO_IDX = {
    GamePhase.MAIN_1: 0,
    GamePhase.COMBAT: 1,
    GamePhase.MAIN_2: 2,
    GamePhase.END: 3,
}


# ══════════════════════════════════════════════════════════
# Forge Log Action-Label Mapping Keywords
# ══════════════════════════════════════════════════════════

# These keywords in Forge log lines help classify raw actions
# into macro-actions for supervised learning.
# Used by ml/actions/labeler.py

ACTION_KEYWORDS = {
    MacroAction.CAST_CREATURE: [
        "creature", "token", "summon",
    ],
    MacroAction.CAST_REMOVAL: [
        "destroy", "exile", "damage to", "counter",
        "-X/-X", "sacrifice", "bounce",
    ],
    MacroAction.CAST_DRAW: [
        "draw", "scry", "look at the top", "reveal",
        "search your library",
    ],
    MacroAction.CAST_RAMP: [
        "add {", "mana", "land onto the battlefield",
        "search your library for a basic land",
    ],
    MacroAction.CAST_COMMANDER: [],  # Detected by matching commander name
    MacroAction.ATTACK_OPPONENT: [
        "attacks", "declare attackers", "combat damage",
    ],
    MacroAction.HOLD_MANA: [],       # Inferred: priority passed with mana open
    MacroAction.PASS: [],            # Inferred: priority passed with no mana / no actions
}


# ══════════════════════════════════════════════════════════
# Training Defaults
# ══════════════════════════════════════════════════════════

@dataclass
class TrainingConfig:
    """Default hyperparameters for supervised policy learning."""
    batch_size: int = 64
    learning_rate: float = 1e-3
    epochs: int = 50
    hidden_dim: int = 512
    num_layers: int = 3
    dropout: float = 0.1
    activation: str = "silu"
    early_stop_patience: int = 5
    val_split: float = 0.15
    test_split: float = 0.10
    checkpoint_dir: str = "ml/models/checkpoints"
    log_every: int = 100               # Log every N batches

TRAINING_CONFIG = TrainingConfig()


# ══════════════════════════════════════════════════════════
# Distillation Loop Defaults (Phase 4)
# ══════════════════════════════════════════════════════════

@dataclass
class DistillationDefaults:
    """Default hyperparameters for the closed-loop distillation pipeline.

    These are consumed by ml.training.distillation_loop.DistillationConfig
    when no explicit override is provided.

    Default weights: Forge-only (forge_weight=1.0, ppo_weight=0.0).
    The baseline trains exclusively on Forge simulation data.  Use
    ``MIXED_MODE_PRESETS`` below for blended Forge+PPO configurations.
    """
    max_iterations: int = 10
    convergence_window: int = 3
    convergence_threshold: float = 0.01

    # PPO self-play per generation
    ppo_iterations: int = 50
    ppo_episodes_per_iter: int = 64
    ppo_lr: float = 3e-4
    ppo_clip_epsilon: float = 0.2
    ppo_entropy_coeff: float = 0.01
    ppo_eval_episodes: int = 100

    # Dataset mixing — Forge-only by default (Phase 5 follow-up decision)
    forge_weight: float = 1.0
    ppo_weight: float = 0.0
    min_reward_threshold: float = 0.0

    # Quality gate thresholds
    min_forge_accuracy: float = 0.35
    max_accuracy_drop: float = 0.03
    min_ppo_win_rate: float = 0.30

    # Retry behaviour on gate failure
    max_retries_per_generation: int = 2
    retry_lr_factor: float = 0.5
    retry_entropy_boost: float = 0.005

    # Output paths
    results_dir: str = "data/results"
    history_dir: str = "data/results/distillation-history"


DISTILLATION_DEFAULTS = DistillationDefaults()


# ══════════════════════════════════════════════════════════
# Mixed-Mode Presets (Phase 5 follow-up)
# ══════════════════════════════════════════════════════════

# Pre-defined Forge/PPO weight combinations for common scenarios.
# Select a preset by name when starting a distillation run to
# override the Forge-only defaults without specifying raw weights.
#
# "forge_only"  — baseline: 100% Forge data, ignore PPO
# "forge_90_10" — light PPO blending: 90% Forge, 10% PPO
# "forge_80_20" — heavier PPO blending: 80% Forge, 20% PPO
MIXED_MODE_PRESETS: Dict[str, Dict[str, float]] = {
    "forge_only": {"forge_weight": 1.0, "ppo_weight": 0.0},
    "forge_90_10": {"forge_weight": 1.0, "ppo_weight": 0.11},  # ~10% PPO
    "forge_80_20": {"forge_weight": 1.0, "ppo_weight": 0.25},  # ~20% PPO
}


def get_preset_weights(preset_name: str) -> Dict[str, float]:
    """Look up a mixed-mode preset by name.

    Returns a dict with ``forge_weight`` and ``ppo_weight`` keys.
    Raises ``KeyError`` if the preset name is unknown.
    """
    if preset_name not in MIXED_MODE_PRESETS:
        raise KeyError(
            f"Unknown preset '{preset_name}'. "
            f"Available: {list(MIXED_MODE_PRESETS.keys())}"
        )
    return dict(MIXED_MODE_PRESETS[preset_name])
