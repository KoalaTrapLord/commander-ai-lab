"""
Commander AI Lab — Overnight AFK Runner
════════════════════════════════════════
Runs repeated batch simulations and then triggers ML training,
designed to run unattended for hours (e.g., overnight while AFK).

Usage (from commander-ai-lab folder):
    python overnight-run.py

Or via the batch file:
    overnight-run.bat

Prerequisites:
    - Lab server must already be running (start-lab.bat)
    - At least 1 deck available
    - LM Studio / DeepSeek must be running for DeepSeek engine
    - Forge must be built for Java engine

Configuration:
    Edit the settings below, or pass command-line arguments.
"""

import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path


# ── Default Config ──────────────────────────────────────────────
DEFAULT_CONFIG = {
    "lab_url": "http://localhost:8080",
    "engine": "deepseek",       # "deepseek" or "java"
    "games_per_batch": 30,      # games per batch run
    "num_batches": 0,           # 0 = run until time_limit_hours
    "time_limit_hours": 11.5,   # stop after this many hours (leave buffer for training)
    "pause_between_batches": 10,  # seconds to pause between batches
    "auto_train": True,         # trigger ML training after all batches
    "auto_update_weights": True,  # run update_weights.py after sims
    "weights_min_games": 10,    # minimum games required for weight update
    "weights_lr": 0.05,         # learning rate for weight update
    "train_epochs": 100,        # training epochs
    "train_lr": 0.001,          # learning rate
    "train_batch_size": 256,    # training batch size
    "train_patience": 15,       # early stopping patience
    "train_ds_weight": 4.0,     # DeepSeek source upsampling weight (ds-*.jsonl files)
    # Java-only settings (ignored for DeepSeek):
    "java_threads": 4,
    "java_clock": 300,
    "java_decks": [],           # exactly 3 deck names required for Java
    # DeepSeek settings:
    "ds_decks": [],             # deck names (auto-detected if empty)
}


# ── Logging ──────────────────────────────────────────────────
_LOG_DIR = Path(os.environ.get("CAL_LOG_DIR", "logs"))


def setup_overnight_logging() -> logging.Logger:
    """Configure logging for the overnight runner.

    Outputs to both console and a rotating log file so that
    unattended runs always have a persistent record.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("commander_ai_lab.overnight")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "overnight-run.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


log = setup_overnight_logging()


def api_get(base_url, path):
    """GET request to lab API."""
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {body}")


def api_post(base_url, path, data=None):
    """POST request to lab API."""
    url = base_url.rstrip("/") + path
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {err_body}")


def check_server(base_url):
    """Verify the lab server is running."""
    try:
        api_get(base_url, "/api/lab/decks")
        return True
    except Exception:
        return False


def get_available_decks(base_url):
    """Fetch all deck names."""
    resp = api_get(base_url, "/api/lab/decks")
    return [d["name"] for d in resp.get("decks", [])]


def start_deepseek_batch(base_url, decks, num_games):
    """Start a DeepSeek batch and return the batch ID."""
    resp = api_post(base_url, "/api/lab/start-deepseek", {
        "decks": decks,
        "numGames": num_games,
    })
    return resp.get("batchId")


def start_java_batch(base_url, decks, num_games, threads, clock):
    """Start a Java/Forge batch and return the batch ID."""
    resp = api_post(base_url, "/api/lab/start", {
        "decks": decks,
        "numGames": num_games,
        "threads": threads,
        "clock": clock,
    })
    return resp.get("batchId")


def wait_for_batch(base_url, batch_id, engine="deepseek", deadline=None):
    """Poll until batch completes or deadline is reached.
    Returns result dict, or None on error/timeout."""
    poll_interval = 15  # seconds
    consecutive_errors = 0
    last_completed = -1
    stall_checks = 0

    while True:
        # Hard deadline check — stop waiting if we've run out of time
        if deadline and time.time() >= deadline:
            log.info(f"  Time limit reached while batch {batch_id} was running.")
            log.info(f"  The batch will continue on the server but we're moving on.")
            return {"completed": 0, "timed_out": True}

        try:
            status = api_get(base_url, f"/api/lab/status?batchId={batch_id}")
            consecutive_errors = 0

            completed = status.get("completedGames", 0)
            total = status.get("totalGames", "?")
            running = status.get("running", False)
            error = status.get("error")
            elapsed = status.get("elapsedMs", 0)

            if error:
                log.error(f"  Batch {batch_id} ERROR: {error}")
                return None

            if not running and completed > 0:
                elapsed_s = elapsed / 1000 if elapsed else 0
                log.info(f"  Batch {batch_id} complete: {completed} games in {elapsed_s:.0f}s")
                try:
                    result = api_get(base_url, f"/api/lab/result?batchId={batch_id}")
                    return result
                except Exception:
                    return {"completed": completed}

            # Not started yet check (running=False, completed=0)
            if not running and completed == 0:
                stall_checks += 1
                if stall_checks > 20:  # 5 min with no progress
                    log.info(f"  Batch {batch_id} never started. Aborting.")
                    return None

            # Progress log with ETA
            if deadline:
                mins_left = (deadline - time.time()) / 60
                log.info(f"  Progress: {completed}/{total} games ({elapsed / 1000:.0f}s) — {mins_left:.0f}min left in run")
            else:
                log.info(f"  Progress: {completed}/{total} games ({elapsed / 1000:.0f}s)")

            # Track stall
            if completed == last_completed:
                stall_checks += 1
            else:
                stall_checks = 0
                last_completed = completed

        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors > 10:
                log.info(f"  Lost connection to server after 10 retries. Aborting batch.")
                return None
            log.info(f"  Connection error (retry {consecutive_errors}/10): {e}")

        time.sleep(poll_interval)


def run_update_weights(cfg):
    """
    Run ml.scripts.update_weights to nudge learned_weights.json from sim
    decision logs.  This feeds the deck builder's sim_insights injection.

    Returns True on success, False on failure (non-fatal — overnight run
    continues regardless).
    """
    log.info("")
    log.info("── Auto-update sim weights ─────────────────────────────────")
    log.info("Running update_weights.py to refresh learned_weights.json...")

    cmd = [
        sys.executable, "-m", "ml.scripts.update_weights",
        "--min-games", str(cfg["weights_min_games"]),
        "--lr", str(cfg["weights_lr"]),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 min ceiling — this should complete in seconds
        )
        if result.returncode == 0:
            # Print the last ~800 chars of the weight report to the log
            output = (result.stdout or "").strip()
            if output:
                for line in output.splitlines()[-20:]:
                    log.info(f"  {line}")
            log.info("Sim weights updated — deck builder will use new insights on next build.")
            return True
        else:
            log.warning(f"update_weights.py exited with code {result.returncode}")
            if result.stderr:
                log.warning(result.stderr.strip()[-300:])
            return False
    except subprocess.TimeoutExpired:
        log.warning("update_weights.py timed out after 120s — skipping")
        return False
    except Exception as e:
        log.warning(f"update_weights.py failed: {e}")
        return False


def start_training(base_url, epochs, lr, batch_size, patience, ds_weight=4.0):
    """Trigger ML training and return immediately.

    ds_weight: upsampling multiplier for DeepSeek decision files
               (ml-decisions-ds-*.jsonl).  Matches the default in
               DatasetConfig.source_weights added in the recent
               dataset_builder.py update.
    """
    resp = api_post(base_url, "/api/ml/train", {
        "epochs": epochs,
        "lr": lr,
        "batchSize": batch_size,
        "patience": patience,
        "rebuildDataset": True,
        "dsWeight": ds_weight,
    })
    return resp


def wait_for_training(base_url):
    """Poll until training completes."""
    poll_interval = 30  # seconds

    while True:
        try:
            status = api_get(base_url, "/api/ml/train/status")
            running = status.get("running", False)
            phase = status.get("phase", "unknown")
            message = status.get("message", "")
            epoch = status.get("current_epoch", 0)
            total = status.get("total_epochs", 0)
            error = status.get("error")

            if error:
                log.error(f"  Training ERROR: {error}")
                return False

            if not running and phase in ("done", "idle") and epoch > 0:
                result = status.get("result", {})
                log.info(f"  Training complete!")
                if result:
                    log.info(f"  Final accuracy: {result.get('best_val_accuracy', '?')}")
                    log.info(f"  Model saved: {result.get('model_path', '?')}")
                return True

            if phase == "training" and total > 0:
                metrics = status.get("metrics", {})
                val_acc = metrics.get("val_accuracy", "?") if metrics else "?"
                log.info(f"  Training: epoch {epoch}/{total} — {message} (val_acc: {val_acc})")
            else:
                log.info(f"  [{phase}] {message}")

        except Exception as e:
            log.info(f"  Connection error: {e}")

        time.sleep(poll_interval)


def get_ml_data_summary(base_url):
    """Get current ML training data stats."""
    try:
        status = api_get(base_url, "/api/ml/train/status")
        data_files = status.get("data_files", [])
        total = sum(f.get("decisions", 0) for f in data_files)
        return total, len(data_files)
    except Exception:
        return 0, 0


def run_overnight(cfg):
    """Main overnight pipeline."""
    base_url = cfg["lab_url"]

    log.info("=" * 60)
    log.info("  Commander AI Lab — Overnight AFK Runner")
    log.info("=" * 60)

    # ── Verify server ────────────────────────────────────────
    log.info("Checking lab server...")
    if not check_server(base_url):
        log.error(f"ERROR: Cannot reach lab server at {base_url}")
        log.info("Start the lab first: start-lab.bat")
        return False

    log.info(f"Server OK at {base_url}")

    # ── Get decks ─────────────────────────────────────────────
    available_decks = get_available_decks(base_url)
    log.info(f"Found {len(available_decks)} decks: {', '.join(available_decks[:5])}{'...' if len(available_decks) > 5 else ''}")

    engine = cfg["engine"]
    if engine == "deepseek":
        decks = cfg["ds_decks"] if cfg["ds_decks"] else available_decks
        if not decks:
            log.error("ERROR: No decks available. Create decks in the Deck Builder first.")
            return False
        log.info(f"Using DeepSeek engine with {len(decks)} deck(s)")
    else:
        decks = cfg["java_decks"]
        if len(decks) != 3:
            log.error("ERROR: Java engine requires exactly 3 deck names.")
            log.info("Set java_decks in the config or use --decks deck1 deck2 deck3")
            return False
        log.info(f"Using Java/Forge engine with decks: {decks}")

    # ── ML logging ────────────────────────────────────────────
    log.info("Enabling ML logging...")
    try:
        api_post(base_url, "/api/ml/toggle?enable=true", {})
        log.info("ML logging enabled")
    except Exception as e:
        log.warning(f"WARNING: Could not enable ML logging: {e}")
        log.info("(DeepSeek batches always log ML data regardless)")
        # Try alternate form
        try:
            api_get(base_url, "/api/ml/toggle?enable=true")
        except Exception:
            pass

    # ── Initial data stats ────────────────────────────────────
    decisions_before, files_before = get_ml_data_summary(base_url)
    log.info(f"Current ML data: {decisions_before} decisions in {files_before} files")

    # ── Run batches ───────────────────────────────────────────
    games_per_batch = cfg["games_per_batch"]
    num_batches = cfg["num_batches"]
    time_limit = cfg["time_limit_hours"] * 3600  # convert to seconds
    pause_sec = cfg["pause_between_batches"]

    start_time = time.time()
    deadline = start_time + time_limit
    batch_num = 0
    total_games = 0
    total_decisions = 0

    log.info("")
    log.info(f"Starting batch loop:")
    if num_batches > 0:
        log.info(f"  Mode: {num_batches} batches × {games_per_batch} games")
    else:
        log.info(f"  Mode: Run for {cfg['time_limit_hours']}h, {games_per_batch} games/batch")
    log.info(f"  Engine: {engine}")
    log.info(f"  Auto-update weights: {'Yes' if cfg['auto_update_weights'] else 'No'}")
    log.info(f"  Auto-train after: {'Yes' if cfg['auto_train'] else 'No'}")
    log.info(f"  DS upsampling weight: {cfg['train_ds_weight']}x")
    log.info("")

    while True:
        # Check stopping conditions
        if num_batches > 0 and batch_num >= num_batches:
            log.info(f"Reached target of {num_batches} batches. Stopping.")
            break

        elapsed = time.time() - start_time
        remaining = deadline - time.time()
        if remaining < 120:  # need at least 2 min for a batch
            log.info(f"Time limit approaching ({remaining:.0f}s left). Stopping sim loop.")
            break

        batch_num += 1
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        remaining_str = str(timedelta(seconds=int(remaining)))
        log.info(f"── Batch {batch_num} ── (elapsed: {elapsed_str}, remaining: {remaining_str})")

        try:
            if engine == "deepseek":
                batch_id = start_deepseek_batch(base_url, decks, games_per_batch)
            else:
                batch_id = start_java_batch(
                    base_url, decks, games_per_batch,
                    cfg["java_threads"], cfg["java_clock"],
                )

            if not batch_id:
                log.error("  ERROR: Failed to start batch (no batchId returned)")
                log.info("  Waiting 60s before retry...")
                time.sleep(60)
                continue

            log.info(f"  Started batch {batch_id}")
            result = wait_for_batch(base_url, batch_id, engine, deadline=deadline)

            if result:
                total_games += games_per_batch
                # Log deck results if available
                for deck in result.get("decks", []):
                    wr = deck.get("winRate", "?")
                    name = deck.get("deckName", "?")
                    log.info(f"    {name}: {wr}% WR")
            else:
                log.info("  Batch failed, continuing to next...")

        except Exception as e:
            log.error(f"  ERROR starting batch: {e}")
            log.info("  Waiting 60s before retry...")
            time.sleep(60)
            continue

        # Pause between batches
        if pause_sec > 0:
            log.info(f"  Cooling down {pause_sec}s...")
            time.sleep(pause_sec)

    # ── Summary ───────────────────────────────────────────────
    total_elapsed = time.time() - start_time
    decisions_after, files_after = get_ml_data_summary(base_url)
    new_decisions = decisions_after - decisions_before
    new_files = files_after - files_before

    log.info("")
    log.info("=" * 60)
    log.info("  BATCH SIMULATION COMPLETE")
    log.info("=" * 60)
    log.info(f"  Batches run:       {batch_num}")
    log.info(f"  Total games:       ~{total_games}")
    log.info(f"  New ML decisions:  {new_decisions} (in {new_files} new files)")
    log.info(f"  Total ML data:     {decisions_after} decisions")
    log.info(f"  Elapsed time:      {str(timedelta(seconds=int(total_elapsed)))}")
    log.info("")

    # ── Auto-update sim weights ───────────────────────────────
    # Runs update_weights.py to nudge learned_weights.json from the
    # decision logs produced during this run.  This feeds sim_insights
    # into the deck builder's Ollama prompts on the next deck build.
    # Runs before neural net training so both pipelines benefit from
    # the freshest possible data.
    if cfg["auto_update_weights"]:
        run_update_weights(cfg)
    else:
        log.info("Skipping sim weight update (--no-update-weights flag set)")

    # ── Auto-train ────────────────────────────────────────────
    if cfg["auto_train"]:
        if decisions_after < 100:
            log.info("Skipping training — too few decisions (need at least 100)")
            return True

        log.info("Starting ML training pipeline...")
        log.info(f"  Epochs: {cfg['train_epochs']}, LR: {cfg['train_lr']}, "
                 f"Batch: {cfg['train_batch_size']}, Patience: {cfg['train_patience']}, "
                 f"DS Weight: {cfg['train_ds_weight']}x")

        try:
            start_training(
                base_url,
                epochs=cfg["train_epochs"],
                lr=cfg["train_lr"],
                batch_size=cfg["train_batch_size"],
                patience=cfg["train_patience"],
                ds_weight=cfg["train_ds_weight"],
            )
            log.info("Training started, monitoring progress...")
            success = wait_for_training(base_url)
            if success:
                log.info("")
                log.info("=" * 60)
                log.info("  TRAINING COMPLETE — model updated!")
                log.info("=" * 60)
            else:
                log.info("Training finished with errors. Check the Training tab for details.")
        except Exception as e:
            log.error(f"ERROR starting training: {e}")
            return False

    log.info("")
    log.info("Overnight run finished. You can close this window.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Commander AI Lab — Overnight AFK Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run DeepSeek sims for 11.5 hours, then update weights + train:
  python overnight-run.py

  # Run 20 batches of 50 games each, then update weights + train:
  python overnight-run.py --batches 20 --games 50

  # Run for 6 hours with Java engine:
  python overnight-run.py --engine java --hours 6 --decks "Deck A" "Deck B" "Deck C"

  # Just run sims, skip both weight update and training:
  python overnight-run.py --no-train --no-update-weights

  # Custom training settings with higher DS upsampling:
  python overnight-run.py --epochs 200 --lr 0.0005 --patience 20 --ds-weight 6.0
        """,
    )
    parser.add_argument("--url", default="http://localhost:8080",
                        help="Lab server URL (default: http://localhost:8080)")
    parser.add_argument("--engine", choices=["deepseek", "java"], default="deepseek",
                        help="Sim engine (default: deepseek)")
    parser.add_argument("--games", type=int, default=30,
                        help="Games per batch (default: 30)")
    parser.add_argument("--batches", type=int, default=0,
                        help="Number of batches (0 = run until time limit)")
    parser.add_argument("--hours", type=float, default=11.5,
                        help="Max hours to run sims (default: 11.5)")
    parser.add_argument("--pause", type=int, default=10,
                        help="Seconds between batches (default: 10)")
    parser.add_argument("--decks", nargs="+", default=[],
                        help="Deck names (auto-detected if not specified)")
    parser.add_argument("--no-train", action="store_true",
                        help="Skip auto-training after sims")
    parser.add_argument("--no-update-weights", action="store_true",
                        help="Skip updating learned_weights.json after sims")
    parser.add_argument("--weights-min-games", type=int, default=10,
                        help="Minimum games required for weight update (default: 10)")
    parser.add_argument("--weights-lr", type=float, default=0.05,
                        help="Learning rate for sim weight update (default: 0.05)")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Training epochs (default: 100)")
    parser.add_argument("--lr", type=float, default=0.001,
                        help="Training learning rate (default: 0.001)")
    parser.add_argument("--batch-size", type=int, default=256,
                        help="Training batch size (default: 256)")
    parser.add_argument("--patience", type=int, default=15,
                        help="Early stopping patience (default: 15)")
    parser.add_argument("--ds-weight", type=float, default=4.0,
                        help="DeepSeek source upsampling weight for training (default: 4.0)")
    parser.add_argument("--threads", type=int, default=4,
                        help="Java engine threads (default: 4)")
    parser.add_argument("--clock", type=int, default=300,
                        help="Java engine clock (default: 300)")
    args = parser.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    cfg["lab_url"] = args.url
    cfg["engine"] = args.engine
    cfg["games_per_batch"] = args.games
    cfg["num_batches"] = args.batches
    cfg["time_limit_hours"] = args.hours
    cfg["pause_between_batches"] = args.pause
    cfg["auto_train"] = not args.no_train
    cfg["auto_update_weights"] = not args.no_update_weights
    cfg["weights_min_games"] = args.weights_min_games
    cfg["weights_lr"] = args.weights_lr
    cfg["train_epochs"] = args.epochs
    cfg["train_lr"] = args.lr
    cfg["train_batch_size"] = args.batch_size
    cfg["train_patience"] = args.patience
    cfg["train_ds_weight"] = args.ds_weight
    cfg["java_threads"] = args.threads
    cfg["java_clock"] = args.clock

    if args.decks:
        if args.engine == "java":
            cfg["java_decks"] = args.decks
        else:
            cfg["ds_decks"] = args.decks

    success = run_overnight(cfg)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
