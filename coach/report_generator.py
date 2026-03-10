"""
Commander AI Lab — Deck Report Generator (Python)
══════════════════════════════════════════════════
Reads batch result JSON files from results/ and generates
deck report JSONs in deck-reports/ that the coach service consumes.

This is the Python equivalent of Java ReportAggregator, allowing
report generation without a separate Java invocation.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

from .config import DECK_REPORTS_DIR

logger = logging.getLogger("coach.report_generator")

UNDERPERFORMER_THRESHOLD = -0.05
MAX_UNDERPERFORMERS = 8
MAX_OVERPERFORMERS = 8


def generate_deck_reports(results_dir: str, reports_dir: str = None) -> List[str]:
    """
    Scan all batch-*.json files in results_dir and generate
    one deck report per unique deck across all batches.

    Returns list of deck IDs that were generated.
    """
    results_path = Path(results_dir)
    output_path = Path(reports_dir) if reports_dir else DECK_REPORTS_DIR
    output_path.mkdir(parents=True, exist_ok=True)

    # Load all batch results
    batch_files = sorted(results_path.glob("batch-*.json"))
    if not batch_files:
        logger.info("No batch result files found in %s", results_dir)
        return []

    all_batches = []
    for bf in batch_files:
        try:
            with open(bf, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_batches.append(data)
        except Exception as e:
            logger.warning("Failed to load %s: %s", bf, e)

    if not all_batches:
        return []

    # Find all unique decks across all batches
    deck_seats: Dict[str, dict] = {}  # deckName -> {seatIndex, commanderName, colorIdentity}
    for batch in all_batches:
        for di in batch.get("decks", []):
            name = di.get("deckName", "")
            if name and name not in deck_seats:
                deck_seats[name] = {
                    "seatIndex": di.get("seatIndex", 0),
                    "commanderName": di.get("commanderName", ""),
                    "colorIdentity": di.get("colorIdentity", []),
                }

    # Generate report for each deck
    generated = []
    for deck_name, deck_info in deck_seats.items():
        try:
            report = _build_deck_report(deck_name, deck_info, all_batches)
            out_file = output_path / f"{deck_name}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            generated.append(deck_name)
            logger.info(
                "Generated report for %s: %d games, %.1f%% win rate",
                deck_name,
                report["meta"]["gamesSimulated"],
                report["meta"]["overallWinRate"] * 100,
            )
        except Exception as e:
            logger.error("Failed to generate report for %s: %s", deck_name, e)

    return generated


def generate_single_deck_report(batch_json_path: str, reports_dir: str = None) -> List[str]:
    """
    Generate deck reports from a single batch result JSON file.
    Merges with existing reports if they exist.

    Returns list of deck IDs that were updated.
    """
    output_path = Path(reports_dir) if reports_dir else DECK_REPORTS_DIR
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        with open(batch_json_path, "r", encoding="utf-8") as f:
            batch = json.load(f)
    except Exception as e:
        logger.error("Failed to load batch result: %s", e)
        return []

    # Also load existing batch results for comprehensive reports
    results_dir = Path(batch_json_path).parent
    all_batches = []
    for bf in sorted(results_dir.glob("batch-*.json")):
        try:
            with open(bf, "r", encoding="utf-8") as f:
                all_batches.append(json.load(f))
        except Exception:
            continue

    if not all_batches:
        all_batches = [batch]

    # Generate reports for all decks in this batch
    generated = []
    for di in batch.get("decks", []):
        deck_name = di.get("deckName", "")
        if not deck_name:
            continue
        deck_info = {
            "seatIndex": di.get("seatIndex", 0),
            "commanderName": di.get("commanderName", ""),
            "colorIdentity": di.get("colorIdentity", []),
        }
        try:
            report = _build_deck_report(deck_name, deck_info, all_batches)
            out_file = output_path / f"{deck_name}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            generated.append(deck_name)
            logger.info(
                "Updated report for %s: %d games, %.1f%% win rate",
                deck_name,
                report["meta"]["gamesSimulated"],
                report["meta"]["overallWinRate"] * 100,
            )
        except Exception as e:
            logger.error("Failed to generate report for %s: %s", deck_name, e)

    return generated


def _build_deck_report(deck_name: str, deck_info: dict, all_batches: list) -> dict:
    """Build a complete deck report from batch data."""
    seat_index = deck_info["seatIndex"]
    commander = deck_info.get("commanderName", deck_name)
    colors = deck_info.get("colorIdentity", [])

    total_games = 0
    total_wins = 0
    total_turns = 0

    # Per-card accumulators
    card_map: Dict[str, dict] = {}

    # Matchup tracking
    matchup_map: Dict[str, List[int]] = {}  # opponent -> [games, wins]

    for batch in all_batches:
        # Check if this deck is in this batch
        batch_deck = None
        for di in batch.get("decks", []):
            if di.get("deckName") == deck_name:
                batch_deck = di
                break
        if batch_deck is None:
            continue

        batch_seat = batch_deck.get("seatIndex", seat_index)

        # Update commander/colors from batch if we don't have them
        if not commander or commander == deck_name:
            commander = batch_deck.get("commanderName", deck_name)
        if not colors:
            colors = batch_deck.get("colorIdentity", [])

        # Track opponents
        opponents = [
            di.get("deckName", "")
            for di in batch.get("decks", [])
            if di.get("seatIndex") != batch_seat
        ]

        # Process each game
        for game in batch.get("games", []):
            total_games += 1
            total_turns += game.get("totalTurns", 0)

            # Find this deck's player result
            my_result = None
            for pr in game.get("playerResults", []):
                if pr.get("seatIndex") == batch_seat:
                    my_result = pr
                    break
            if my_result is None:
                continue

            won = my_result.get("isWinner", False)
            if won:
                total_wins += 1

            # Matchups
            for opp in opponents:
                if opp not in matchup_map:
                    matchup_map[opp] = [0, 0]
                matchup_map[opp][0] += 1
                if won:
                    matchup_map[opp][1] += 1

            # Per-card stats
            for pcs in my_result.get("cardStats", []):
                card_name = pcs.get("cardName", "")
                if not card_name:
                    continue

                if card_name not in card_map:
                    card_map[card_name] = {
                        "name": card_name,
                        "gamesSeen": 0,
                        "gamesDrawn": 0,
                        "gamesCast": 0,
                        "gamesWhenCast": 0,
                        "winsWhenCast": 0,
                        "gamesDeadCard": 0,
                        "gamesKeptInOpening": 0,
                        "totalTurnCast": 0.0,
                        "totalDamage": 0.0,
                    }

                cp = card_map[card_name]
                cp["gamesSeen"] += 1

                if pcs.get("drawn", False):
                    cp["gamesDrawn"] += 1
                    if pcs.get("cast", False):
                        cp["gamesCast"] += 1
                        cp["gamesWhenCast"] += 1
                        if won:
                            cp["winsWhenCast"] += 1
                        turn_cast = pcs.get("turnCast", -1)
                        if turn_cast >= 0:
                            cp["totalTurnCast"] += turn_cast
                    if pcs.get("stuckInHand", False):
                        cp["gamesDeadCard"] += 1

                if pcs.get("inOpeningHand", False) and pcs.get("keptInOpeningHand", False):
                    cp["gamesKeptInOpening"] += 1

                cp["totalDamage"] += pcs.get("damageDealt", 0)

    # ── Compute deck-level stats ──────────────────────────────

    overall_win_rate = total_wins / total_games if total_games > 0 else 0.0
    avg_game_length = total_turns / total_games if total_games > 0 else 0.0

    # ── Compute matchups ──────────────────────────────────────

    matchups = []
    for opp_name, stats in matchup_map.items():
        matchups.append({
            "opponentDeck": opp_name,
            "opponentCommander": "",
            "gamesPlayed": stats[0],
            "winRate": stats[1] / stats[0] if stats[0] > 0 else 0.0,
        })

    # ── Compute per-card performance ──────────────────────────

    cards = []
    for cp in card_map.values():
        gs = cp["gamesSeen"]
        if gs == 0:
            continue

        drawn_rate = cp["gamesDrawn"] / gs
        cast_rate = cp["gamesCast"] / cp["gamesDrawn"] if cp["gamesDrawn"] > 0 else 0.0
        dead_card_rate = cp["gamesDeadCard"] / cp["gamesDrawn"] if cp["gamesDrawn"] > 0 else 0.0
        kept_rate = cp["gamesKeptInOpening"] / gs

        # Impact score
        win_rate_when_cast = (
            cp["winsWhenCast"] / cp["gamesWhenCast"]
            if cp["gamesWhenCast"] > 0
            else 0.0
        )
        impact_score = (win_rate_when_cast - overall_win_rate) * cast_rate

        # Clunkiness
        clunkiness = dead_card_rate * (1.0 - cast_rate)

        # Average turn cast
        avg_turn_cast = (
            cp["totalTurnCast"] / cp["gamesCast"] if cp["gamesCast"] > 0 else None
        )

        avg_damage = cp["totalDamage"] / gs

        cards.append({
            "name": cp["name"],
            "drawnRate": round(drawn_rate, 4),
            "castRate": round(cast_rate, 4),
            "keptInOpeningHandRate": round(kept_rate, 4),
            "deadCardRate": round(dead_card_rate, 4),
            "impactScore": round(impact_score, 4),
            "synergyScore": 0.0,
            "clunkinessScore": round(clunkiness, 4),
            "avgTurnCast": round(avg_turn_cast, 2) if avg_turn_cast is not None else None,
            "avgDamageDealt": round(avg_damage, 2),
            "tags": [],
        })

    # ── Identify under/over performers ────────────────────────

    sorted_by_impact = sorted(cards, key=lambda c: c["impactScore"])

    underperformers = []
    for c in sorted_by_impact[:MAX_UNDERPERFORMERS]:
        if c["impactScore"] < UNDERPERFORMER_THRESHOLD:
            underperformers.append(c["name"])

    overperformers = []
    for c in reversed(sorted_by_impact[-MAX_OVERPERFORMERS:]):
        if c["impactScore"] > 0:
            overperformers.append(c["name"])

    # ── Build final report ────────────────────────────────────

    return {
        "deckId": deck_name,
        "commander": commander,
        "colorIdentity": colors,
        "meta": {
            "gamesSimulated": total_games,
            "overallWinRate": round(overall_win_rate, 4),
            "avgGameLength": round(avg_game_length, 2),
            "perArchetypeWinRates": {},
        },
        "matchups": matchups,
        "structure": {
            "landCount": 0,
            "curveBuckets": [0] * 8,
            "cardTypeCounts": {},
            "functionalCounts": {},
        },
        "cards": cards,
        "underperformers": underperformers,
        "overperformers": overperformers,
        "knownCombos": [],
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
    }
