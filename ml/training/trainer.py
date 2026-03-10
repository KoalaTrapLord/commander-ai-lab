"""
Commander AI Lab — Supervised Policy Trainer
═════════════════════════════════════════════
Trains the PolicyNetwork on labeled decision data using
cross-entropy loss with class-weight balancing.

Features:
  - Class weighting to handle imbalanced action distribution
  - Cosine annealing LR schedule with warmup
  - Early stopping on validation loss
  - Per-class accuracy tracking
  - Periodic checkpoint saving (best + every N epochs)
  - CUDA/MPS/CPU auto-detection

Usage:
    python -m ml.training.trainer --data-dir ml/models --epochs 50
    python -m ml.training.trainer --data-dir ml/models --lr 5e-4 --batch-size 128
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Conditional torch import
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import (
    NUM_ACTIONS, STATE_DIMS, IDX_TO_ACTION, TRAINING_CONFIG,
)
from ml.training.policy_network import (
    PolicyNetwork, save_checkpoint, load_checkpoint,
)

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("ml.trainer")


# ══════════════════════════════════════════════════════════
# Dataset Loading
# ══════════════════════════════════════════════════════════

def load_npz_split(path: str) -> Tuple[np.ndarray, np.ndarray]:
    """Load states and labels from an NPZ file."""
    data = np.load(path, allow_pickle=True)
    states = data["states"].astype(np.float32)
    labels = data["labels"].astype(np.int64)
    return states, labels


def make_dataloader(
    states: np.ndarray,
    labels: np.ndarray,
    batch_size: int,
    shuffle: bool = True,
    device: str = "cpu",
) -> DataLoader:
    """Create a PyTorch DataLoader from numpy arrays."""
    state_tensor = torch.from_numpy(states)
    label_tensor = torch.from_numpy(labels)
    dataset = TensorDataset(state_tensor, label_tensor)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        pin_memory=(device != "cpu"),
        drop_last=False,
    )


def compute_class_weights(labels: np.ndarray, num_classes: int) -> torch.Tensor:
    """
    Compute inverse-frequency class weights for cross-entropy.

    Uses smoothed inverse frequency:
        w_c = N / (num_classes * count_c)
    Capped at 10× to prevent extreme weights on rare classes.
    """
    counts = np.bincount(labels, minlength=num_classes).astype(np.float64)
    # Avoid division by zero for classes with no samples
    counts = np.maximum(counts, 1.0)
    n = len(labels)
    weights = n / (num_classes * counts)
    # Cap extreme weights
    weights = np.minimum(weights, 10.0)
    return torch.from_numpy(weights).float()


# ══════════════════════════════════════════════════════════
# Training Loop
# ══════════════════════════════════════════════════════════

class SupervisedTrainer:
    """
    Trains PolicyNetwork with cross-entropy on expert decision data.

    Features:
      - Class-weighted loss for imbalanced actions
      - Cosine annealing with linear warmup
      - Early stopping on validation loss
      - Best-model and periodic checkpointing
      - Detailed per-epoch metrics
    """

    def __init__(
        self,
        model: PolicyNetwork,
        device: str = "cpu",
        learning_rate: float = None,
        batch_size: int = None,
        epochs: int = None,
        patience: int = None,
        checkpoint_dir: str = None,
        warmup_epochs: int = 3,
        save_every: int = 10,
    ):
        self.model = model.to(device)
        self.device = device
        self.lr = learning_rate or TRAINING_CONFIG.learning_rate
        self.batch_size = batch_size or TRAINING_CONFIG.batch_size
        self.epochs = epochs or TRAINING_CONFIG.epochs
        self.patience = patience or TRAINING_CONFIG.early_stop_patience
        self.checkpoint_dir = checkpoint_dir or TRAINING_CONFIG.checkpoint_dir
        self.warmup_epochs = warmup_epochs
        self.save_every = save_every

        # Will be initialized in train()
        self.optimizer = None
        self.scheduler = None
        self.criterion = None
        self.history: List[Dict] = []

    def train(
        self,
        train_states: np.ndarray,
        train_labels: np.ndarray,
        val_states: np.ndarray,
        val_labels: np.ndarray,
    ) -> Dict:
        """
        Run the full training loop.

        Returns:
            Dict with training summary (best metrics, epoch count, etc.)
        """
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch not installed. Run: pip install torch")

        logger.info("=" * 60)
        logger.info("  Commander AI Lab — Supervised Policy Training")
        logger.info("=" * 60)
        logger.info("  Device:        %s", self.device)
        logger.info("  Train samples: %d", len(train_states))
        logger.info("  Val samples:   %d", len(val_states))
        logger.info("  Batch size:    %d", self.batch_size)
        logger.info("  Learning rate: %s", self.lr)
        logger.info("  Max epochs:    %d", self.epochs)
        logger.info("  Patience:      %d", self.patience)
        logger.info("  Warmup epochs: %d", self.warmup_epochs)
        logger.info("=" * 60)

        # Data loaders
        train_loader = make_dataloader(
            train_states, train_labels, self.batch_size, shuffle=True, device=self.device
        )
        val_loader = make_dataloader(
            val_states, val_labels, self.batch_size, shuffle=False, device=self.device
        )

        # Class-weighted cross-entropy
        class_weights = compute_class_weights(train_labels, NUM_ACTIONS).to(self.device)
        self.criterion = nn.CrossEntropyLoss(weight=class_weights)

        logger.info("  Class weights: %s", 
                     {IDX_TO_ACTION[i].value: f"{w:.2f}" 
                      for i, w in enumerate(class_weights.cpu().numpy())})

        # Optimizer
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=self.lr,
            weight_decay=1e-4,
        )

        # Cosine annealing with warmup
        # During warmup, LR ramps from lr/10 to lr
        # After warmup, cosine decay to lr/100
        total_steps = self.epochs * len(train_loader)
        warmup_steps = self.warmup_epochs * len(train_loader)

        def lr_lambda(step):
            if step < warmup_steps:
                return 0.1 + 0.9 * (step / max(warmup_steps, 1))
            progress = (step - warmup_steps) / max(total_steps - warmup_steps, 1)
            return 0.01 + 0.99 * 0.5 * (1 + np.cos(np.pi * progress))

        self.scheduler = torch.optim.lr_scheduler.LambdaLR(
            self.optimizer, lr_lambda
        )

        # Training state
        best_val_loss = float("inf")
        best_val_acc = 0.0
        best_epoch = 0
        epochs_without_improvement = 0

        os.makedirs(self.checkpoint_dir, exist_ok=True)

        for epoch in range(1, self.epochs + 1):
            t_start = time.time()

            # Train one epoch
            train_loss, train_acc, train_per_class = self._train_epoch(
                train_loader, epoch
            )

            # Validate
            val_loss, val_acc, val_per_class = self._validate(val_loader)

            elapsed = time.time() - t_start
            current_lr = self.optimizer.param_groups[0]["lr"]

            # Record history
            epoch_metrics = {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_acc": train_acc,
                "val_loss": val_loss,
                "val_acc": val_acc,
                "lr": current_lr,
                "time_s": elapsed,
                "train_per_class": train_per_class,
                "val_per_class": val_per_class,
            }
            self.history.append(epoch_metrics)

            # Log
            logger.info(
                "  Epoch %3d/%d | train_loss=%.4f train_acc=%.3f | "
                "val_loss=%.4f val_acc=%.3f | lr=%.2e | %.1fs",
                epoch, self.epochs,
                train_loss, train_acc,
                val_loss, val_acc,
                current_lr, elapsed,
            )

            # Check for improvement
            improved = False
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_val_acc = val_acc
                best_epoch = epoch
                epochs_without_improvement = 0
                improved = True

                # Save best model
                save_checkpoint(
                    self.model, self.optimizer, epoch,
                    {"val_loss": val_loss, "val_acc": val_acc,
                     "train_loss": train_loss, "train_acc": train_acc},
                    os.path.join(self.checkpoint_dir, "best_policy.pt"),
                )
            else:
                epochs_without_improvement += 1

            # Periodic checkpoint
            if epoch % self.save_every == 0:
                save_checkpoint(
                    self.model, self.optimizer, epoch,
                    {"val_loss": val_loss, "val_acc": val_acc},
                    os.path.join(self.checkpoint_dir, f"policy_epoch_{epoch:03d}.pt"),
                )

            # Early stopping
            if epochs_without_improvement >= self.patience:
                logger.info(
                    "  Early stopping at epoch %d (no improvement for %d epochs)",
                    epoch, self.patience,
                )
                break

        # Final summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("  Training Complete")
        logger.info("=" * 60)
        logger.info("  Best epoch:     %d", best_epoch)
        logger.info("  Best val_loss:  %.4f", best_val_loss)
        logger.info("  Best val_acc:   %.3f", best_val_acc)
        logger.info("  Total epochs:   %d", len(self.history))
        logger.info("  Checkpoint:     %s", os.path.join(self.checkpoint_dir, "best_policy.pt"))
        logger.info("=" * 60)

        # Save training history
        history_path = os.path.join(self.checkpoint_dir, "training_history.json")
        # Convert per-class dicts for JSON serialization
        serializable_history = []
        for h in self.history:
            entry = {k: v for k, v in h.items()
                     if k not in ("train_per_class", "val_per_class")}
            entry["train_per_class"] = {
                str(k): v for k, v in h["train_per_class"].items()
            }
            entry["val_per_class"] = {
                str(k): v for k, v in h["val_per_class"].items()
            }
            serializable_history.append(entry)

        with open(history_path, "w") as f:
            json.dump(serializable_history, f, indent=2)
        logger.info("  History saved:  %s", history_path)

        return {
            "best_epoch": best_epoch,
            "best_val_loss": best_val_loss,
            "best_val_acc": best_val_acc,
            "total_epochs": len(self.history),
            "checkpoint_path": os.path.join(self.checkpoint_dir, "best_policy.pt"),
        }

    def _train_epoch(
        self,
        loader: DataLoader,
        epoch: int,
    ) -> Tuple[float, float, Dict[int, float]]:
        """Train for one epoch. Returns (loss, accuracy, per_class_acc)."""
        self.model.train()
        total_loss = 0.0
        correct = 0
        total = 0
        per_class_correct = np.zeros(NUM_ACTIONS)
        per_class_total = np.zeros(NUM_ACTIONS)

        for batch_idx, (states, labels) in enumerate(loader):
            states = states.to(self.device)
            labels = labels.to(self.device)

            # Forward
            logits = self.model(states)
            loss = self.criterion(logits, labels)

            # Backward
            self.optimizer.zero_grad()
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)

            self.optimizer.step()
            self.scheduler.step()

            # Metrics
            total_loss += loss.item() * len(labels)
            preds = logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += len(labels)

            # Per-class tracking
            for c in range(NUM_ACTIONS):
                mask = labels == c
                per_class_total[c] += mask.sum().item()
                per_class_correct[c] += (preds[mask] == c).sum().item()

        avg_loss = total_loss / max(total, 1)
        accuracy = correct / max(total, 1)

        per_class_acc = {}
        for c in range(NUM_ACTIONS):
            if per_class_total[c] > 0:
                per_class_acc[c] = per_class_correct[c] / per_class_total[c]
            else:
                per_class_acc[c] = 0.0

        return avg_loss, accuracy, per_class_acc

    @torch.no_grad()
    def _validate(
        self,
        loader: DataLoader,
    ) -> Tuple[float, float, Dict[int, float]]:
        """Validate on held-out data. Returns (loss, accuracy, per_class_acc)."""
        self.model.eval()
        total_loss = 0.0
        correct = 0
        total = 0
        per_class_correct = np.zeros(NUM_ACTIONS)
        per_class_total = np.zeros(NUM_ACTIONS)

        for states, labels in loader:
            states = states.to(self.device)
            labels = labels.to(self.device)

            logits = self.model(states)
            loss = self.criterion(logits, labels)

            total_loss += loss.item() * len(labels)
            preds = logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += len(labels)

            for c in range(NUM_ACTIONS):
                mask = labels == c
                per_class_total[c] += mask.sum().item()
                per_class_correct[c] += (preds[mask] == c).sum().item()

        avg_loss = total_loss / max(total, 1)
        accuracy = correct / max(total, 1)

        per_class_acc = {}
        for c in range(NUM_ACTIONS):
            if per_class_total[c] > 0:
                per_class_acc[c] = per_class_correct[c] / per_class_total[c]
            else:
                per_class_acc[c] = 0.0

        return avg_loss, accuracy, per_class_acc


# ══════════════════════════════════════════════════════════
# Evaluation
# ══════════════════════════════════════════════════════════

def evaluate_model(
    model: PolicyNetwork,
    test_states: np.ndarray,
    test_labels: np.ndarray,
    device: str = "cpu",
) -> Dict:
    """
    Full evaluation on test set with detailed metrics.

    Returns:
        Dict with overall accuracy, per-class accuracy, confusion matrix
    """
    model.eval()
    model.to(device)

    states_t = torch.from_numpy(test_states.astype(np.float32)).to(device)
    labels_t = torch.from_numpy(test_labels.astype(np.int64)).to(device)

    with torch.no_grad():
        logits = model(states_t)
        preds = logits.argmax(dim=-1)

    preds_np = preds.cpu().numpy()
    labels_np = test_labels

    # Overall accuracy
    overall_acc = (preds_np == labels_np).mean()

    # Per-class metrics
    per_class = {}
    for c in range(NUM_ACTIONS):
        mask = labels_np == c
        total_c = mask.sum()
        correct_c = (preds_np[mask] == c).sum() if total_c > 0 else 0
        pred_as_c = (preds_np == c).sum()

        precision = correct_c / max(pred_as_c, 1)
        recall = correct_c / max(total_c, 1) 
        f1 = 2 * precision * recall / max(precision + recall, 1e-8)

        action_name = IDX_TO_ACTION[c].value
        per_class[action_name] = {
            "support": int(total_c),
            "correct": int(correct_c),
            "predicted": int(pred_as_c),
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "f1": round(float(f1), 4),
        }

    # Confusion matrix
    confusion = np.zeros((NUM_ACTIONS, NUM_ACTIONS), dtype=int)
    for true_c, pred_c in zip(labels_np, preds_np):
        confusion[true_c][pred_c] += 1

    return {
        "overall_accuracy": round(float(overall_acc), 4),
        "total_samples": len(labels_np),
        "per_class": per_class,
        "confusion_matrix": confusion.tolist(),
    }


def print_evaluation(results: Dict):
    """Pretty-print evaluation results."""
    print()
    print("=" * 65)
    print("  Test Set Evaluation")
    print("=" * 65)
    print(f"  Overall Accuracy: {results['overall_accuracy']:.1%}")
    print(f"  Total Samples:    {results['total_samples']:,}")
    print()
    print(f"  {'Action':<20} {'Support':>8} {'Prec':>7} {'Recall':>7} {'F1':>7}")
    print("  " + "-" * 55)

    for action_name, m in results["per_class"].items():
        print(
            f"  {action_name:<20} {m['support']:>8} "
            f"{m['precision']:>7.3f} {m['recall']:>7.3f} {m['f1']:>7.3f}"
        )

    print("  " + "-" * 55)

    # Confusion matrix
    print()
    print("  Confusion Matrix (rows=true, cols=predicted):")
    header = "  " + " " * 18
    for c in range(NUM_ACTIONS):
        short_name = IDX_TO_ACTION[c].value[:6]
        header += f" {short_name:>6}"
    print(header)

    for r in range(NUM_ACTIONS):
        row_name = IDX_TO_ACTION[r].value[:16]
        row_str = f"  {row_name:<18}"
        for c in range(NUM_ACTIONS):
            row_str += f" {results['confusion_matrix'][r][c]:>6}"
        print(row_str)
    print()


# ══════════════════════════════════════════════════════════
# Device Selection
# ══════════════════════════════════════════════════════════

def get_best_device() -> str:
    """Auto-detect the best available compute device."""
    if not TORCH_AVAILABLE:
        return "cpu"
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        mem = torch.cuda.get_device_properties(0).total_mem / (1024**3)
        logger.info("  CUDA device: %s (%.1f GB)", name, mem)
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        logger.info("  Using Apple MPS")
        return "mps"
    logger.info("  Using CPU (no GPU detected)")
    return "cpu"


# ══════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Commander AI Lab — Train Policy Network"
    )
    parser.add_argument(
        "--data-dir", default="ml/models",
        help="Directory containing dataset-train.npz / dataset-val.npz / dataset-test.npz",
    )
    parser.add_argument(
        "--epochs", type=int, default=None,
        help=f"Max training epochs (default: {TRAINING_CONFIG.epochs})",
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help=f"Batch size (default: {TRAINING_CONFIG.batch_size})",
    )
    parser.add_argument(
        "--lr", type=float, default=None,
        help=f"Learning rate (default: {TRAINING_CONFIG.learning_rate})",
    )
    parser.add_argument(
        "--patience", type=int, default=None,
        help=f"Early stopping patience (default: {TRAINING_CONFIG.early_stop_patience})",
    )
    parser.add_argument(
        "--checkpoint-dir", default=None,
        help=f"Checkpoint directory (default: {TRAINING_CONFIG.checkpoint_dir})",
    )
    parser.add_argument(
        "--device", default=None,
        help="Compute device: cuda, mps, or cpu (default: auto-detect)",
    )
    parser.add_argument(
        "--eval-only", action="store_true",
        help="Only evaluate an existing checkpoint on test data",
    )
    parser.add_argument(
        "--checkpoint", default=None,
        help="Path to checkpoint for --eval-only (default: best_policy.pt)",
    )
    args = parser.parse_args()

    if not TORCH_AVAILABLE:
        print("PyTorch not installed. Install with:")
        print("  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        sys.exit(1)

    device = args.device or get_best_device()
    data_dir = args.data_dir
    ckpt_dir = args.checkpoint_dir or TRAINING_CONFIG.checkpoint_dir

    # Load data
    train_path = os.path.join(data_dir, "dataset-train.npz")
    val_path = os.path.join(data_dir, "dataset-val.npz")
    test_path = os.path.join(data_dir, "dataset-test.npz")

    if args.eval_only:
        # Evaluation only
        if not os.path.exists(test_path):
            print(f"Test data not found: {test_path}")
            print("Run: python -m ml.scripts.ml_cli build")
            sys.exit(1)

        ckpt_path = args.checkpoint or os.path.join(ckpt_dir, "best_policy.pt")
        if not os.path.exists(ckpt_path):
            print(f"Checkpoint not found: {ckpt_path}")
            sys.exit(1)

        test_states, test_labels = load_npz_split(test_path)
        model, checkpoint = load_checkpoint(ckpt_path, device)
        logger.info("  Loaded checkpoint from epoch %d", checkpoint.get("epoch", "?"))

        results = evaluate_model(model, test_states, test_labels, device)
        print_evaluation(results)

        # Save evaluation results
        eval_path = os.path.join(ckpt_dir, "eval_results.json")
        with open(eval_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  Results saved: {eval_path}")
        return

    # Training mode
    for path, label in [(train_path, "train"), (val_path, "val")]:
        if not os.path.exists(path):
            print(f"{label} data not found: {path}")
            print("Build the dataset first:")
            print("  python -m ml.scripts.ml_cli build --results-dir results/")
            sys.exit(1)

    train_states, train_labels = load_npz_split(train_path)
    val_states, val_labels = load_npz_split(val_path)

    logger.info("  Train: %d samples, %d features", *train_states.shape)
    logger.info("  Val:   %d samples, %d features", *val_states.shape)

    # Verify dimensions match expected state size
    actual_dim = train_states.shape[1]
    expected_dim = STATE_DIMS.total_state_dim
    if actual_dim != expected_dim:
        logger.warning(
            "  State dimension mismatch: data=%d, config=%d. Using data dimension.",
            actual_dim, expected_dim,
        )

    # Create model
    model = PolicyNetwork(input_dim=actual_dim)
    param_count = sum(p.numel() for p in model.parameters())
    logger.info("  Model parameters: %s", f"{param_count:,}")

    # Train
    trainer = SupervisedTrainer(
        model=model,
        device=device,
        learning_rate=args.lr,
        batch_size=args.batch_size,
        epochs=args.epochs,
        patience=args.patience,
        checkpoint_dir=ckpt_dir,
    )

    summary = trainer.train(train_states, train_labels, val_states, val_labels)

    # Evaluate on test set if available
    if os.path.exists(test_path):
        logger.info("")
        logger.info("  Running test set evaluation...")
        test_states, test_labels = load_npz_split(test_path)

        # Reload best checkpoint for evaluation
        best_model, _ = load_checkpoint(summary["checkpoint_path"], device)
        results = evaluate_model(best_model, test_states, test_labels, device)
        print_evaluation(results)

        eval_path = os.path.join(ckpt_dir, "eval_results.json")
        with open(eval_path, "w") as f:
            json.dump(results, f, indent=2)
        logger.info("  Eval results saved: %s", eval_path)
    else:
        logger.info("  No test data found at %s — skipping evaluation.", test_path)


if __name__ == "__main__":
    main()
