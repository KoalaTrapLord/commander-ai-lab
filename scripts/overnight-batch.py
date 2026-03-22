"""
Commander AI Lab — Overnight Batch Sim Runner
═══════════════════════════════════════════════
Runs sequential batch simulations across the top precon decks,
rotating playstyles each batch. Generates ML decision data for
training.

Usage:
    python scripts/overnight-batch.py
    python scripts/overnight-batch.py --hours 8 --games-per-batch 200
    python scripts/overnight-batch.py --port 8080 --threads 4

Estimated throughput (varies by hardware):
    ~3-5 sims/sec typical → ~200 games in ~40-70 sec
    8 hours ≈ 400-600 batches ≈ 80K-120K games ≈ 200K-400K decisions
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from itertools import combinations

# ── Configuration ────────────────────────────────────────────

PRECON_DECKS = [
    "Undead_Unleashed.dck",    # Wilhelt — Zombie tribal (UB)
    "Elven_Empire.dck",         # Lathril — Elf tribal (BG)
    "Planar_Portal.dck",        # Prosper — Exile/Treasure (BR)
    "Necron_Dynasties.dck",     # Szarekh — Artifact recursion (B)
    "Creative_Energy.dck",      # Satya — Energy/Artifacts (WUR)
    "Veloci-Ramp-Tor.dck",      # Pantlaza — Dinosaur tribal (RGW)
    "Mutant_Menace.dck",        # Wise Mothman — Rad/Proliferate (UBG)
    "Scrappy_Survivors.dck",    # Dogmeat — Aura/Equipment (WRG)
    "Explorers_of_the_Deep.dck", # Hakbal — Merfolk/Explore (UG)
    "Science.dck",              # Dr. Madison Li — Artifact synergies (WUR)
]

PLAYSTYLES = ["midrange", "aggro", "control", "combo"]


def api_call(base_url, path, method="GET", body=None):
    """Make an API call to the local server."""
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"} if body else {}
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        print(f"  API Error {e.code}: {error_body}")
        return None
    except Exception as e:
        print(f"  Connection error: {e}")
        return None


def ensure_ml_logging(base_url):
    """Make sure ML logging is enabled."""
    result = api_call(base_url, "/api/ml/toggle?enable=true", method="POST")
    if result:
        print(f"  ML logging: {'enabled' if result.get('ml_logging_enabled') else 'DISABLED'}")
    return result


def start_batch(base_url, decks, num_games, playstyle, threads):
    """Start a batch simulation."""
    body = {
        "decks": decks,
        "numGames": num_games,
        "threads": threads,
        "policyStyle": playstyle,
        "clock": 6000,
    }
    return api_call(base_url, "/api/lab/start", method="POST", body=body)


def poll_batch(base_url, batch_id, poll_interval=5):
    """Poll batch status until complete. Returns final status."""
    while True:
        result = api_call(base_url, f"/api/lab/status/{batch_id}")
        if result is None:
            time.sleep(poll_interval)
            continue

        completed = result.get("completedGames", 0)
        total = result.get("totalGames", 0)
        running = result.get("running", False)
        sps = result.get("simsPerSec", 0)
        error = result.get("error")

        if error:
            print(f"  ERROR: {error}")
            return result

        if not running and completed >= total and total > 0:
            return result

        if not running and total == 0:
            # Still starting up
            time.sleep(poll_interval)
            continue

        pct = (completed / total * 100) if total > 0 else 0
        speed = f" ({sps:.1f} sims/sec)" if sps > 0 else ""
        print(f"  Progress: {completed}/{total} ({pct:.0f}%){speed}", end="\r")

        time.sleep(poll_interval)


def generate_matchups(decks, pod_size=4):
    """Generate 4-player pods from deck list, cycling through all combos."""
    combos = list(combinations(decks, pod_size))
    return combos


def main():
    parser = argparse.ArgumentParser(
        description="Commander AI Lab — Overnight Batch Runner"
    )
    parser.add_argument(
        "--hours", type=float, default=8,
        help="Maximum hours to run (default: 8)",
    )
    parser.add_argument(
        "--games-per-batch", type=int, default=200,
        help="Games per batch (default: 200)",
    )
    parser.add_argument(
        "--threads", type=int, default=4,
        help="Simulation threads (default: 4)",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Lab server port (default: 8080)",
    )
    parser.add_argument(
        "--pod-size", type=int, default=4, choices=[2, 3, 4],
        help="Players per pod (default: 4)",
    )

    args = parser.parse_args()
    base_url = f"http://localhost:{args.port}"

    print()
    print("=" * 60)
    print("  Commander AI Lab — Overnight Batch Runner")
    print("=" * 60)
    print(f"  Duration:     {args.hours} hours")
    print(f"  Games/batch:  {args.games_per_batch}")
    print(f"  Threads:      {args.threads}")
    print(f"  Pod size:     {args.pod_size}")
    print(f"  Decks:        {len(PRECON_DECKS)}")
    print(f"  Playstyles:   {', '.join(PLAYSTYLES)}")
    print(f"  Server:       {base_url}")
    print("=" * 60)
    print()

    # Check server is up
    print("Checking server connectivity...")
    status = api_call(base_url, "/api/ml/status")
    if status is None:
        print("ERROR: Cannot reach the lab server. Is it running?")
        print(f"  Expected at: {base_url}")
        sys.exit(1)
    print(f"  Server OK — {status.get('total_decisions', 0):,} existing decisions")

    # Enable ML logging
    print("Enabling ML logging...")
    ensure_ml_logging(base_url)

    # Generate matchups
    matchups = generate_matchups(PRECON_DECKS, args.pod_size)
    print(f"  Generated {len(matchups)} unique {args.pod_size}-player matchups")
    print()

    # Calculate stop time
    stop_time = datetime.now() + timedelta(hours=args.hours)
    print(f"  Will run until: {stop_time.strftime('%I:%M %p')}")
    print()

    # ── Main Loop ────────────────────────────────────────────
    batch_count = 0
    total_games = 0
    total_decisions_start = status.get("total_decisions", 0)
    matchup_idx = 0
    playstyle_idx = 0

    try:
        while datetime.now() < stop_time:
            # Pick next matchup and playstyle
            matchup = matchups[matchup_idx % len(matchups)]
            playstyle = PLAYSTYLES[playstyle_idx % len(PLAYSTYLES)]

            deck_names = [os.path.splitext(d)[0].replace("_", " ") for d in matchup]
            batch_count += 1

            remaining = stop_time - datetime.now()
            hrs_left = remaining.total_seconds() / 3600

            print(f"─── Batch {batch_count} ({hrs_left:.1f}h remaining) ───")
            print(f"  Playstyle: {playstyle}")
            print(f"  Decks: {', '.join(deck_names)}")

            # Start batch
            result = start_batch(
                base_url,
                list(matchup),
                args.games_per_batch,
                playstyle,
                args.threads,
            )

            if result is None or "batchId" not in result:
                print("  Failed to start batch — waiting 30s and retrying...")
                time.sleep(30)
                continue

            batch_id = result["batchId"]
            print(f"  Batch ID: {batch_id}")

            # Poll until complete
            final = poll_batch(base_url, batch_id)
            print()  # Clear progress line

            if final:
                games = final.get("completedGames", 0)
                elapsed_s = final.get("elapsedMs", 0) / 1000
                total_games += games
                print(f"  Done: {games} games in {elapsed_s:.0f}s")
            else:
                print("  Batch completed (no status)")

            # Rotate
            matchup_idx += 1
            playstyle_idx += 1

            # Brief pause between batches
            time.sleep(2)
            print()

    except KeyboardInterrupt:
        print("\n\nStopped by user (Ctrl+C)")

    # ── Summary ──────────────────────────────────────────────
    # Check final decision count
    final_status = api_call(base_url, "/api/ml/status")
    total_decisions_end = final_status.get("total_decisions", 0) if final_status else 0
    new_decisions = total_decisions_end - total_decisions_start

    print()
    print("=" * 60)
    print("  OVERNIGHT BATCH COMPLETE")
    print("=" * 60)
    print(f"  Batches run:      {batch_count}")
    print(f"  Total games:      {total_games:,}")
    print(f"  New decisions:    {new_decisions:,}")
    print(f"  Total decisions:  {total_decisions_end:,}")
    print(f"  Decision files:   {final_status.get('total_files', '?')}")
    print("=" * 60)
    print()
    print("  Next step: Run Closed-Loop Distillation from the Distill tab")
    print("  to train on this expanded dataset.")
    print()


if __name__ == "__main__":
    main()
