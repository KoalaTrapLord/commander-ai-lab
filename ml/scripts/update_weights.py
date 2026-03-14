"""
update_weights.py
=================
Outcome-weighted reinforcement learning for Commander AI card weights.

Reads all decisions_*.jsonl files produced by DeepSeekBrain.flush_log(),
applies a gradient-free reward nudge to each weight key based on the
normalised reward signal (-1.0 to +1.0) stamped on every decision entry,
then saves the updated weights to learned_weights.json via save_weights().

Usage
-----
    # Basic run (reads logs/decisions/, updates learned_weights.json)
    python -m ml.scripts.update_weights

    # Custom paths
    python -m ml.scripts.update_weights \\
        --log-dir logs/decisions \\
        --weights-out src/commander_ai_lab/sim/learned_weights.json \\
        --lr 0.05 \\
        --min-games 10

    # Dry-run (print proposed changes, don't write)
    python -m ml.scripts.update_weights --dry-run

    # Reset to defaults then exit
    python -m ml.scripts.update_weights --reset

Algorithm
---------
For each decision entry that has a non-null game_result:

    delta = learning_rate * reward * action_weight_for(action)

Each weight key is nudged by the mean delta across all decisions that
touched that key.  Keys with no decisions are left unchanged.
All values are clamped to [-20.0, 20.0] by save_weights().

Reward is the normalised life-delta from flush_log():
    reward = (my_final_life - avg_opp_final_life) / 40.0  in [-1.0, 1.0]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Allow running as a script without installing the package
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from commander_ai_lab.sim.rules import (
    AI_DEFAULT_WEIGHTS,
    load_weights,
    reset_weights,
    save_weights,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("update_weights")

# ---------------------------------------------------------------------------
# Action → weight key mapping
# Maps each VALID_ACTION to the weight(s) it most directly influences.
# A single action may touch multiple keys (listed as a tuple).
# ---------------------------------------------------------------------------
ACTION_WEIGHT_MAP: dict[str, tuple[str, ...]] = {
    "play_land":       (),                                    # no weight key — always correct
    "cast_ramp":       ("spell_ramp",),
    "cast_removal":    ("spell_destroy",),
    "cast_board_wipe": ("spell_counter",),                   # reuse counter as board-control proxy
    "cast_creature":   ("card_ptBonus",),
    "cast_spell":      ("spell_enchantment", "spell_draw"),
    "attack_all":      ("kw_haste", "kw_flying"),            # aggression / evasion proxy
    "attack_safe":     ("kw_flying", "kw_trample"),
    "hold":            (),                                    # no weight key — passing is neutral
}


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _iter_log_entries(log_dir: str) -> Iterator[dict]:
    """Yield every entry from all decisions_*.jsonl files in log_dir."""
    log_path = Path(log_dir)
    if not log_path.exists():
        logger.warning("Log directory not found: %s", log_dir)
        return

    files = sorted(log_path.glob("decisions_*.jsonl"))
    if not files:
        logger.warning("No decisions_*.jsonl files found in %s", log_dir)
        return

    logger.info("Found %d log file(s) in %s", len(files), log_dir)
    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed line %d in %s: %s", lineno, fpath.name, exc)


# ---------------------------------------------------------------------------
# Core learning loop
# ---------------------------------------------------------------------------

def compute_weight_updates(
    log_dir: str,
    current_weights: dict[str, float],
    learning_rate: float = 0.05,
    min_games: int = 1,
) -> tuple[dict[str, float], dict]:
    """
    Read decision logs and compute updated weights.

    Returns
    -------
    updated_weights : dict[str, float]
        New weight dict after applying mean reward nudges.
    stats : dict
        Diagnostic info (games seen, decisions processed, keys changed, etc.)
    """
    # Accumulators: key → list of (reward * lr) deltas
    key_deltas: dict[str, list[float]] = defaultdict(list)

    total_entries = 0
    labelled_entries = 0  # entries with non-null game_result
    game_ids_seen: set[str] = set()
    action_counts: dict[str, int] = defaultdict(int)

    for entry in _iter_log_entries(log_dir):
        total_entries += 1

        game_result = entry.get("game_result")
        if not game_result:
            continue  # no outcome stamped — skip (pre-flush or incomplete game)

        labelled_entries += 1
        game_ids_seen.add(entry.get("game_id", "unknown"))

        reward: float = float(game_result.get("reward", 0.0))
        action: str = entry.get("decision", {}).get("action", "hold")
        action_counts[action] += 1

        weight_keys = ACTION_WEIGHT_MAP.get(action, ())
        for key in weight_keys:
            if key in current_weights:
                key_deltas[key].append(learning_rate * reward)

    num_games = len(game_ids_seen)
    logger.info(
        "Processed %d entries | %d labelled | %d unique games",
        total_entries, labelled_entries, num_games,
    )

    if num_games < min_games:
        logger.warning(
            "Only %d game(s) found — minimum is %d.  Skipping update.",
            num_games, min_games,
        )
        return dict(current_weights), {
            "skipped": True,
            "reason": f"need {min_games} games, have {num_games}",
            "total_entries": total_entries,
            "labelled_entries": labelled_entries,
            "games": num_games,
        }

    # Apply mean delta per key
    updated = dict(current_weights)
    changed_keys: dict[str, tuple[float, float]] = {}  # key → (old, new)

    for key, deltas in key_deltas.items():
        if not deltas:
            continue
        mean_delta = sum(deltas) / len(deltas)
        old_val = updated[key]
        new_val = round(old_val + mean_delta, 6)
        updated[key] = new_val
        if abs(new_val - old_val) >= 0.0001:
            changed_keys[key] = (old_val, new_val)

    stats = {
        "skipped": False,
        "total_entries": total_entries,
        "labelled_entries": labelled_entries,
        "games": num_games,
        "keys_changed": len(changed_keys),
        "changes": changed_keys,
        "action_counts": dict(action_counts),
    }
    return updated, stats


def print_diff(stats: dict, current: dict, updated: dict) -> None:
    """Pretty-print weight changes to stdout."""
    changes = stats.get("changes", {})
    if not changes:
        print("  (no weight changes above threshold)")
        return

    col_w = max(len(k) for k in changes) + 2
    print(f"  {'Key':<{col_w}}  {'Before':>10}  {'After':>10}  {'Delta':>10}")
    print("  " + "-" * (col_w + 36))
    for key, (old, new) in sorted(changes.items(), key=lambda x: abs(x[1][1] - x[1][0]), reverse=True):
        delta = new - old
        arrow = "▲" if delta > 0 else "▼"
        print(f"  {key:<{col_w}}  {old:>10.4f}  {new:>10.4f}  {arrow} {abs(delta):>8.4f}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_log_dir() -> str:
    return str(_REPO_ROOT / "logs" / "decisions")


def _default_weights_out() -> str:
    return str(_REPO_ROOT / "src" / "commander_ai_lab" / "sim" / "learned_weights.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update AI card weights from simulation decision logs."
    )
    parser.add_argument(
        "--log-dir",
        default=_default_log_dir(),
        help="Directory containing decisions_*.jsonl files (default: logs/decisions/)",
    )
    parser.add_argument(
        "--weights-out",
        default=_default_weights_out(),
        help="Path to write learned_weights.json (default: src/.../sim/learned_weights.json)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=0.05,
        help="Learning rate — how much each game nudges a weight (default: 0.05)",
    )
    parser.add_argument(
        "--min-games",
        type=int,
        default=10,
        help="Minimum number of completed games required before updating (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed changes without writing learned_weights.json",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete learned_weights.json and restore AI_DEFAULT_WEIGHTS, then exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show action distribution and per-key delta counts",
    )
    args = parser.parse_args(argv)

    # ── Reset mode ──────────────────────────────────────────────
    if args.reset:
        reset_weights(args.weights_out)
        print(f"Reset: deleted {args.weights_out} (if it existed). Defaults restored.")
        return 0

    # ── Load current weights ─────────────────────────────────────
    current = load_weights(args.weights_out)
    logger.info("Loaded %d weight keys from %s", len(current), args.weights_out)

    # ── Compute updates ──────────────────────────────────────────
    updated, stats = compute_weight_updates(
        log_dir=args.log_dir,
        current_weights=current,
        learning_rate=args.lr,
        min_games=args.min_games,
    )

    # ── Report ───────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Commander AI — Weight Update Report")
    print("=" * 60)
    print(f"  Log dir    : {args.log_dir}")
    print(f"  Weights out: {args.weights_out}")
    print(f"  Games      : {stats['games']}")
    print(f"  Entries    : {stats['total_entries']}  ({stats['labelled_entries']} labelled)")
    print(f"  LR         : {args.lr}")
    print()

    if stats.get("skipped"):
        print(f"  SKIPPED — {stats['reason']}")
        print()
        return 0

    print(f"  Keys changed: {stats['keys_changed']}")
    print()
    print_diff(stats, current, updated)
    print()

    if args.verbose:
        print("  Action distribution:")
        for action, count in sorted(stats["action_counts"].items(), key=lambda x: -x[1]):
            print(f"    {action:<20} {count:>6} decisions")
        print()

    # ── Write ────────────────────────────────────────────────────
    if args.dry_run:
        print("  DRY RUN — no file written.")
    else:
        out_path = save_weights(updated, args.weights_out)
        print(f"  Saved updated weights to: {out_path}")

    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
