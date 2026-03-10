"""
Commander AI Lab — ML Pipeline CLI
════════════════════════════════════
Unified CLI for ML training data workflows.

Commands:
    status      — Show ML logging status and available training data
    build       — Build training dataset from decision logs
    train       — Train policy network on built dataset (supervised)
    eval        — Evaluate a trained model on test data
    inspect     — Inspect a JSONL decision file (sample entries)
    stats       — Show action label distribution from decisions
    ppo         — Train with PPO (self-play reinforcement learning)
    tournament  — Run round-robin tournament evaluation

Usage:
    python -m ml.scripts.ml_cli status
    python -m ml.scripts.ml_cli build --results-dir results/
    python -m ml.scripts.ml_cli train --epochs 50 --lr 1e-3
    python -m ml.scripts.ml_cli eval
    python -m ml.scripts.ml_cli inspect --file results/ml-decisions-abc12345.jsonl
    python -m ml.scripts.ml_cli stats --results-dir results/
    python -m ml.scripts.ml_cli ppo --iterations 100 --opponent heuristic
    python -m ml.scripts.ml_cli tournament --episodes 50
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def cmd_status(args):
    """Show ML logging status and available data files."""
    results_dir = Path(args.results_dir)

    print("\n╔══════════════════════════════════════════╗")
    print("║  Commander AI Lab — ML Training Status   ║")
    print("╚══════════════════════════════════════════╝\n")

    if not results_dir.exists():
        print(f"  Results directory not found: {results_dir}")
        print("  Run batch simulations first.\n")
        return

    # Find decision files
    jsonl_files = sorted(results_dir.glob("ml-decisions-*.jsonl"))
    if not jsonl_files:
        print("  No ML decision files found.")
        print("  Enable ML logging and run batch simulations:")
        print("    • Web UI: POST /api/ml/toggle?enable=true")
        print("    • CLI:    java -jar ... --ml-log")
        print()
        return

    total_decisions = 0
    total_size = 0

    print(f"  {'File':<40} {'Decisions':>10} {'Size':>10}")
    print("  " + "─" * 62)

    for f in jsonl_files:
        lines = 0
        try:
            with open(f) as fh:
                lines = sum(1 for _ in fh)
        except Exception:
            pass
        size = f.stat().st_size
        total_decisions += lines
        total_size += size
        print(f"  {f.name:<40} {lines:>10,} {size/1024:>9.1f}K")

    print("  " + "─" * 62)
    print(f"  {'TOTAL':<40} {total_decisions:>10,} {total_size/1024:>9.1f}K")

    # Check for embeddings
    emb_path = Path(project_root) / "embeddings" / "mtg_embeddings.npz"
    emb_status = "✓ Loaded" if emb_path.exists() else "✗ Not found"
    print(f"\n  Embeddings: {emb_status}")

    # Check for existing datasets
    models_dir = Path(project_root) / "ml" / "models"
    npz_files = sorted(models_dir.glob("*.npz")) if models_dir.exists() else []
    if npz_files:
        print(f"\n  Existing datasets:")
        for f in npz_files:
            print(f"    {f.name} ({f.stat().st_size/1024:.1f}K)")

    print()


def cmd_build(args):
    """Build training dataset."""
    from ml.data.dataset_builder import build_dataset, split_dataset, save_dataset

    dataset = build_dataset(
        results_dir=args.results_dir,
        embeddings_dir=args.embeddings_dir,
        max_samples=args.max_samples,
    )
    if not dataset:
        print("\nNo data to build. Enable ML logging and run simulations first.")
        return

    if args.no_split:
        save_dataset(dataset, args.output)
    else:
        train, val, test = split_dataset(dataset)
        base = args.output.replace(".npz", "")
        save_dataset(train, f"{base}-train.npz")
        save_dataset(val, f"{base}-val.npz")
        save_dataset(test, f"{base}-test.npz")

    print("\n✓ Dataset build complete.")


def cmd_inspect(args):
    """Inspect a JSONL decision file."""
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}")
        return

    print(f"\n  Inspecting: {filepath.name}\n")
    count = 0
    with open(filepath) as f:
        for i, line in enumerate(f):
            if i >= args.limit:
                break
            try:
                d = json.loads(line.strip())
                action = d.get("action", {})
                players = d.get("players", [])
                p0_life = players[0]["life"] if players else "?"
                p1_life = players[1]["life"] if len(players) > 1 else "?"

                print(f"  [{i:>4}] Turn {d.get('turn', '?'):>2} "
                      f"| Phase: {d.get('phase', '?'):<8} "
                      f"| Seat {d.get('active_seat', '?')} "
                      f"| Life: {p0_life}/{p1_life} "
                      f"| {action.get('type', '?')}: {action.get('card', '-')}")
                count += 1
            except Exception as e:
                print(f"  [{i:>4}] ERROR: {e}")

    with open(filepath) as f:
        total = sum(1 for _ in f)
    print(f"\n  Showing {count} of {total:,} total decisions.\n")


def cmd_train(args):
    """Train policy network."""
    from ml.training.trainer import main as trainer_main
    # Re-construct sys.argv for the trainer CLI
    argv = ["trainer"]
    if args.data_dir:
        argv += ["--data-dir", args.data_dir]
    if args.epochs:
        argv += ["--epochs", str(args.epochs)]
    if args.batch_size:
        argv += ["--batch-size", str(args.batch_size)]
    if args.lr:
        argv += ["--lr", str(args.lr)]
    if args.patience:
        argv += ["--patience", str(args.patience)]
    if args.checkpoint_dir:
        argv += ["--checkpoint-dir", args.checkpoint_dir]
    if args.device:
        argv += ["--device", args.device]
    sys.argv = argv
    trainer_main()


def cmd_eval(args):
    """Evaluate trained model."""
    from ml.training.trainer import main as trainer_main
    argv = ["trainer", "--eval-only"]
    if args.data_dir:
        argv += ["--data-dir", args.data_dir]
    if args.checkpoint_dir:
        argv += ["--checkpoint-dir", args.checkpoint_dir]
    if args.checkpoint:
        argv += ["--checkpoint", args.checkpoint]
    if args.device:
        argv += ["--device", args.device]
    sys.argv = argv
    trainer_main()


def cmd_ppo(args):
    """Train with PPO (self-play RL)."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from ml.training.ppo_trainer import PPOTrainer, PPOConfig

    config = PPOConfig(
        iterations=args.iterations,
        episodes_per_iter=args.episodes_per_iter,
        ppo_epochs=args.ppo_epochs,
        batch_size=args.batch_size,
        clip_epsilon=args.clip_epsilon,
        entropy_coeff=args.entropy_coeff,
        learning_rate=args.lr,
        lr_schedule=args.lr_schedule,
        buffer_size=args.buffer_size,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        opponent=args.opponent,
        playstyle=args.playstyle,
        checkpoint_dir=args.checkpoint_dir or "ml/models/checkpoints",
        save_every=args.save_every,
        eval_every=args.eval_every,
        eval_episodes=args.eval_episodes,
        load_supervised=args.load_supervised,
    )

    trainer = PPOTrainer(config)
    summary = trainer.train()
    print(json.dumps(summary, indent=2))


def cmd_tournament(args):
    """Run round-robin tournament evaluation."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from ml.eval.tournament import main as tournament_main
    argv = ["tournament"]
    if args.episodes:
        argv += ["--episodes", str(args.episodes)]
    if args.checkpoint:
        argv += ["--checkpoint", args.checkpoint]
    if args.ppo_checkpoint:
        argv += ["--ppo-checkpoint", args.ppo_checkpoint]
    if args.playstyle:
        argv += ["--playstyle", args.playstyle]
    if args.output:
        argv += ["--output", args.output]
    sys.argv = argv
    tournament_main()


def cmd_stats(args):
    """Show action label distribution."""
    from ml.actions.labeler import label_decisions_file, print_label_distribution
    import numpy as np

    results_dir = Path(args.results_dir)
    jsonl_files = sorted(results_dir.glob("ml-decisions-*.jsonl"))

    if not jsonl_files:
        print("No ML decision files found.")
        return

    all_labels = []
    for f in jsonl_files:
        labels, _ = label_decisions_file(str(f))
        all_labels.append(labels)

    combined = np.concatenate(all_labels)
    print(f"\nCombined stats from {len(jsonl_files)} files:")
    print_label_distribution(combined)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Commander AI Lab — ML Pipeline CLI"
    )
    subparsers = parser.add_subparsers(dest="command")

    # status
    sp_status = subparsers.add_parser("status", help="Show ML training data status")
    sp_status.add_argument("--results-dir", default="results")

    # build
    sp_build = subparsers.add_parser("build", help="Build training dataset")
    sp_build.add_argument("--results-dir", default="results")
    sp_build.add_argument("--embeddings-dir", default=None)
    sp_build.add_argument("--output", default="ml/models/dataset.npz")
    sp_build.add_argument("--max-samples", type=int, default=None)
    sp_build.add_argument("--no-split", action="store_true")

    # inspect
    sp_inspect = subparsers.add_parser("inspect", help="Inspect a decision file")
    sp_inspect.add_argument("--file", required=True)
    sp_inspect.add_argument("--limit", type=int, default=20)

    # train
    sp_train = subparsers.add_parser("train", help="Train policy network")
    sp_train.add_argument("--data-dir", default="ml/models")
    sp_train.add_argument("--epochs", type=int, default=None)
    sp_train.add_argument("--batch-size", type=int, default=None)
    sp_train.add_argument("--lr", type=float, default=None)
    sp_train.add_argument("--patience", type=int, default=None)
    sp_train.add_argument("--checkpoint-dir", default=None)
    sp_train.add_argument("--device", default=None)

    # eval
    sp_eval = subparsers.add_parser("eval", help="Evaluate trained model on test set")
    sp_eval.add_argument("--data-dir", default="ml/models")
    sp_eval.add_argument("--checkpoint-dir", default=None)
    sp_eval.add_argument("--checkpoint", default=None)
    sp_eval.add_argument("--device", default=None)

    # stats
    sp_stats = subparsers.add_parser("stats", help="Show action label distribution")
    sp_stats.add_argument("--results-dir", default="results")

    # ppo
    sp_ppo = subparsers.add_parser("ppo", help="Train with PPO (self-play RL)")
    sp_ppo.add_argument("--iterations", type=int, default=100)
    sp_ppo.add_argument("--episodes-per-iter", type=int, default=64)
    sp_ppo.add_argument("--ppo-epochs", type=int, default=4)
    sp_ppo.add_argument("--batch-size", type=int, default=256)
    sp_ppo.add_argument("--clip-epsilon", type=float, default=0.2)
    sp_ppo.add_argument("--entropy-coeff", type=float, default=0.01)
    sp_ppo.add_argument("--lr", type=float, default=3e-4)
    sp_ppo.add_argument("--lr-schedule", default="constant", choices=["constant", "linear", "cosine"])
    sp_ppo.add_argument("--buffer-size", type=int, default=4096)
    sp_ppo.add_argument("--gamma", type=float, default=0.99)
    sp_ppo.add_argument("--gae-lambda", type=float, default=0.95)
    sp_ppo.add_argument("--opponent", default="heuristic", choices=["heuristic", "random", "self"])
    sp_ppo.add_argument("--playstyle", default="midrange")
    sp_ppo.add_argument("--checkpoint-dir", default=None)
    sp_ppo.add_argument("--save-every", type=int, default=10)
    sp_ppo.add_argument("--eval-every", type=int, default=5)
    sp_ppo.add_argument("--eval-episodes", type=int, default=50)
    sp_ppo.add_argument("--load-supervised", default=None,
                        help="Path to supervised checkpoint to initialize from")

    # tournament
    sp_tourney = subparsers.add_parser("tournament", help="Run round-robin tournament evaluation")
    sp_tourney.add_argument("--episodes", type=int, default=50)
    sp_tourney.add_argument("--checkpoint", default=None)
    sp_tourney.add_argument("--ppo-checkpoint", default=None)
    sp_tourney.add_argument("--playstyle", default="midrange")
    sp_tourney.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "train":
        cmd_train(args)
    elif args.command == "eval":
        cmd_eval(args)
    elif args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "ppo":
        cmd_ppo(args)
    elif args.command == "tournament":
        cmd_tournament(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
