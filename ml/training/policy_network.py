"""
Commander AI Lab — Policy Network
══════════════════════════════════
Feed-forward neural network that maps game state + playstyle → action logits.

Architecture:
  Input:  state vector (6177-dim) = global features + zone embeddings + playstyle
  Hidden: 3 FC layers with SiLU activation and layer normalization
  Output: logits over 8 macro-actions

The network is designed for:
  1. Supervised learning (cross-entropy on expert/AI action labels)
  2. Later conversion to PPO actor-critic (add value head)
"""

import os
import sys
from pathlib import Path

# Conditional torch import — graceful failure if not installed
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("[ML] PyTorch not installed. Install with: pip install torch")

import numpy as np

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import STATE_DIMS, NUM_ACTIONS, TRAINING_CONFIG


class PolicyNetwork(nn.Module):
    """
    Feed-forward policy network for Commander macro-action prediction.

    Input:  (batch, 6177) state vector
    Output: (batch, 8) action logits (unnormalized log-probabilities)

    Architecture:
      FC(6177 → 512) → LayerNorm → SiLU → Dropout
      FC(512 → 512) → LayerNorm → SiLU → Dropout
      FC(512 → 256) → LayerNorm → SiLU → Dropout
      FC(256 → 8)
    """

    def __init__(
        self,
        input_dim: int = None,
        hidden_dim: int = None,
        num_actions: int = None,
        num_layers: int = None,
        dropout: float = None,
    ):
        super().__init__()

        input_dim = input_dim or STATE_DIMS.total_state_dim
        hidden_dim = hidden_dim or TRAINING_CONFIG.hidden_dim
        num_actions = num_actions or NUM_ACTIONS
        num_layers = num_layers or TRAINING_CONFIG.num_layers
        dropout = dropout or TRAINING_CONFIG.dropout

        layers = []

        # Input layer
        layers.append(nn.Linear(input_dim, hidden_dim))
        layers.append(nn.LayerNorm(hidden_dim))
        layers.append(nn.SiLU())
        layers.append(nn.Dropout(dropout))

        # Hidden layers
        for i in range(num_layers - 1):
            out_dim = hidden_dim if i < num_layers - 2 else hidden_dim // 2
            layers.append(nn.Linear(hidden_dim if i == 0 else hidden_dim, out_dim))
            layers.append(nn.LayerNorm(out_dim))
            layers.append(nn.SiLU())
            layers.append(nn.Dropout(dropout))
            hidden_dim = out_dim

        self.features = nn.Sequential(*layers)

        # Output head
        self.action_head = nn.Linear(hidden_dim, num_actions)

        # Initialize weights
        self._init_weights()

    def _init_weights(self):
        """Kaiming initialization for SiLU activations."""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity='linear')
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Args:
            state: (batch, input_dim) tensor

        Returns:
            (batch, num_actions) logits
        """
        features = self.features(state)
        return self.action_head(features)

    def predict_action(self, state: torch.Tensor, temperature: float = 1.0) -> int:
        """
        Predict a single action (for inference).

        Args:
            state: (1, input_dim) or (input_dim,) tensor
            temperature: Softmax temperature (1.0 = normal, <1 = more greedy, >1 = more random)

        Returns:
            action index (int)
        """
        self.eval()
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            logits = self.forward(state)
            if temperature != 1.0:
                logits = logits / temperature
            probs = F.softmax(logits, dim=-1)
            action = torch.multinomial(probs, 1).item()
        return action

    def predict_action_greedy(self, state: torch.Tensor) -> int:
        """Predict the most likely action (argmax, no sampling)."""
        self.eval()
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            logits = self.forward(state)
            return logits.argmax(dim=-1).item()

    def get_action_probs(self, state: torch.Tensor) -> np.ndarray:
        """Get action probability distribution for a state."""
        self.eval()
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            logits = self.forward(state)
            probs = F.softmax(logits, dim=-1)
            return probs.cpu().numpy().flatten()


class PolicyValueNetwork(PolicyNetwork):
    """
    Extended policy network with a value head for actor-critic / PPO.

    Same architecture as PolicyNetwork, plus:
      value_head: FC(hidden → 1) predicting state value V(s)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Value head shares features, outputs scalar
        last_hidden = self.action_head.in_features
        self.value_head = nn.Linear(last_hidden, 1)
        nn.init.zeros_(self.value_head.bias)

    def forward_with_value(self, state: torch.Tensor):
        """
        Forward pass returning both action logits and state value.

        Returns:
            (action_logits, value) — shapes (batch, num_actions), (batch, 1)
        """
        features = self.features(state)
        action_logits = self.action_head(features)
        value = self.value_head(features)
        return action_logits, value


def save_checkpoint(
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    metrics: dict,
    path: str,
):
    """Save model checkpoint with training metadata."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    torch.save({
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "metrics": metrics,
        "model_config": {
            "input_dim": STATE_DIMS.total_state_dim,
            "hidden_dim": TRAINING_CONFIG.hidden_dim,
            "num_actions": NUM_ACTIONS,
            "num_layers": TRAINING_CONFIG.num_layers,
            "dropout": TRAINING_CONFIG.dropout,
        },
    }, path)
    print(f"[ML] Checkpoint saved: {path}")


def load_checkpoint(path: str, device: str = "cpu"):
    """Load model from checkpoint."""
    checkpoint = torch.load(path, map_location=device, weights_only=False)
    config = checkpoint.get("model_config", {})

    model = PolicyNetwork(
        input_dim=config.get("input_dim", STATE_DIMS.total_state_dim),
        hidden_dim=config.get("hidden_dim", TRAINING_CONFIG.hidden_dim),
        num_actions=config.get("num_actions", NUM_ACTIONS),
        num_layers=config.get("num_layers", TRAINING_CONFIG.num_layers),
        dropout=config.get("dropout", TRAINING_CONFIG.dropout),
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)

    return model, checkpoint
