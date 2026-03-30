#!/usr/bin/env python
"""
Commander AI Lab — Eval Policy Script (Issue #153)
═══════════════════════════════════════════════════
Run N Forge evaluation games with a given checkpoint and write results.

Usage:
    python scripts/eval_policy.py \
        --model ml/models/checkpoints/forge-trained/final.pt \
        --games 200 \
        --run-id forge-trained \
        --out results/eval-forge.json

    python scripts/eval_policy.py \
        --model ml/models/checkpoints/baseline-synthetic/final.pt \
        --games 200 \
        --run-id baseline-synthetic \
        --out results/eval-baseline.json \
        --seed 42

Opts:
    --model PATH         Path to .pt checkpoint  [required]
    --games N            Number of eval games  [default: 200]
    --run-id ID          Label for this run  [default: derived from --model]
    --out PATH           Output JSON path  [default: results/eval-{run-id}.json]
    --forge-jar PATH     Forge JAR path  [default: auto-detect]
    --forge-dir DIR      Forge working directory  [default: forge]
    --decks D [D ...]    Deck .dck files to use (2-4)  [default: first 2 found in precon-decks/]
    --threads N          Parallel Forge workers  [default: 4]
    --clock N            Per-game clock limit in seconds  [default: 120]
    --seed N             RNG seed for reproducibility
    --greedy             Use greedy argmax inference (no sampling)
    --temperature T      Softmax temperature  [default: 1.0]
    --device DEVICE      torch device (cpu, cuda, mps)  [default: auto]
    --embeddings DIR     Embeddings directory  [default: embeddings]
    --results-dir DIR    Results output directory  [default: results]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval_policy")


def find_decks(deck_dir: str, n: int = 2) -> list:
    """Auto-discover .dck files under deck_dir."""
    p = Path(deck_dir)
    if not p.exists():
        return []
    files = sorted(p.glob("**/*.dck"))[:n]
    return [str(f) for f in files]


def derive_run_id(model_path: str) -> str:
    """Derive a readable run ID from the checkpoint path."""
    p = Path(model_path)
    # e.g. ml/models/checkpoints/forge-trained/final.pt  ->  forge-trained
    parts = p.parts
    if len(parts) >= 2:
        return parts[-2]
    return p.stem


def auto_forge_jar(search_dirs=None) -> str:
    """Find the Forge JAR by scanning common locations."""
    candidates = [
        "forge/forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar",
        "forge/forge-gui-desktop.jar",
        "forge.jar",
    ]
    dirs = search_dirs or [".", "forge", "lib"]
    for d in dirs:
        for c in candidates:
            path = os.path.join(d, c)
            if os.path.exists(path):
                return path
    # Also glob
    for jar in Path(".").rglob("forge-gui-desktop*.jar"):
        return str(jar)
    return ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run Forge eval games for a policy checkpoint.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model", required=True, help="Path to .pt checkpoint")
    p.add_argument("--games", type=int, default=200)
    p.add_argument("--run-id", default="")
    p.add_argument("--out", default="")
    p.add_argument("--forge-jar", default="")
    p.add_argument("--forge-dir", default="forge")
    p.add_argument("--decks", nargs="+", default=[])
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--clock", type=int, default=120)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--greedy", action="store_true")
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--device", default=None)
    p.add_argument("--embeddings", default="embeddings")
    p.add_argument("--results-dir", default="results")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # ── Resolve run ID
    run_id = args.run_id or derive_run_id(args.model)

    # ── Resolve output path
    out_path = args.out or os.path.join(args.results_dir, f"eval-{run_id}.json")

    # ── Resolve Forge JAR
    forge_jar = args.forge_jar or auto_forge_jar()
    if not forge_jar:
        logger.warning("Forge JAR not found — synthetic fallback will be used.")

    # ── Resolve decks
    deck_files = args.decks
    if not deck_files:
        deck_files = find_decks("precon-decks", n=2)
    if not deck_files:
        logger.warning("No .dck files found — synthetic fallback will be used.")

    logger.info("=" * 60)
    logger.info("Eval run  : %s", run_id)
    logger.info("Checkpoint: %s", args.model)
    logger.info("Games     : %d", args.games)
    logger.info("Threads   : %d", args.threads)
    logger.info("Forge JAR : %s", forge_jar or "(not found)")
    logger.info("Decks     : %s", deck_files or "(none — synthetic)")
    logger.info("Output    : %s", out_path)
    logger.info("=" * 60)

    # ── Import and run evaluator
    from ml.eval.forge_evaluator import EvalConfig, ForgeEvaluator

    cfg = EvalConfig(
        checkpoint_path=args.model,
        embeddings_dir=args.embeddings,
        device=args.device,
        forge_jar=forge_jar,
        forge_work_dir=args.forge_dir,
        deck_files=deck_files,
        deck_names=[Path(f).stem for f in deck_files],
        num_games=args.games,
        num_threads=args.threads,
        clock_seconds=args.clock,
        seed=args.seed,
        run_id=run_id,
        results_dir=args.results_dir,
        greedy=args.greedy,
        temperature=args.temperature,
    )
    # Override result path to match --out
    cfg_out = Path(out_path)
    cfg.results_dir = str(cfg_out.parent)
    cfg.run_id = cfg_out.stem.replace("eval-", "", 1) if cfg_out.stem.startswith("eval-") else cfg_out.stem

    evaluator = ForgeEvaluator(cfg)
    summary = evaluator.run()

    print("\n" + str(summary))
    print(f"Results written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
