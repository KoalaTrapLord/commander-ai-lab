"""
Commander AI Lab — Deck Report Generator (Python)
══════════════════════════════════════════════════
Reads batch result JSON files from results/ and generates
deck report JSONs in deck-reports/ that the coach service consumes.

Supports both Java batch format and DeepSeek batch format.
Populates deck structure (land count, curve, card types, functional roles)
from the deck builder database when available.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

from .config import DECK_REPORTS_DIR, LAB_ROOT

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
    batch_files = sorted(results_path.glob("ml-decision-*.json"))
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
                    "commanderName": di.get("commanderName", di.get("commander", "")),
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
    for bf in sorted(results_dir.glob("ml-decision-*.json")):
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
            "commanderName": di.get("commanderName", di.get("commander", "")),
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


# ── Database helpers for deck structure ──────────────────────

def _get_deck_card_metadata(deck_name: str) -> Optional[List[dict]]:
    """
    Look up card metadata (type_line, cmc, oracle_text, mana_cost, keywords)
    from the deck builder database for the given deck name.
    Returns None if DB not available or deck not found.
    """
    db_path = LAB_ROOT / "deckbuilder.db"
    if not db_path.exists():
        # Try alternate location
        db_path = LAB_ROOT / "data" / "deckbuilder.db"
    if not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            "SELECT id FROM decks WHERE name = ? COLLATE NOCASE", (deck_name,)
        ).fetchone()
        if not row:
            conn.close()
            return None

        deck_id = row["id"]
        cards = conn.execute("""
            SELECT dc.card_name, dc.quantity, dc.is_commander,
                   ce.type_line, ce.cmc, ce.oracle_text,
                   ce.keywords, ce.mana_cost, ce.color_identity
            FROM deck_cards dc
            LEFT JOIN collection_entries ce ON ce.scryfall_id = dc.scryfall_id
            WHERE dc.deck_id = ?
        """, (deck_id,)).fetchall()

        result = []
        for r in cards:
            for _ in range(r["quantity"] or 1):
                result.append({
                    "name": r["card_name"],
                    "type_line": r["type_line"] or "",
                    "cmc": r["cmc"] or 0,
                    "oracle_text": r["oracle_text"] or "",
                    "keywords": r["keywords"] or "",
                    "mana_cost": r["mana_cost"] or "",
                    "is_commander": r["is_commander"] or 0,
                })
        conn.close()
        return result if result else None
    except Exception as e:
        logger.warning("DB lookup failed for deck '%s': %s", deck_name, e)
        return None


def _compute_structure(deck_cards: List[dict]) -> dict:
    """Compute deck structure (landCount, curveBuckets, cardTypeCounts, functionalCounts)
    from card metadata."""
    land_count = 0
    curve_buckets = [0] * 8  # CMC 0, 1, 2, 3, 4, 5, 6, 7+
    card_type_counts: Dict[str, int] = {}
    functional_counts: Dict[str, int] = {}

    for card in deck_cards:
        type_line = card.get("type_line", "").lower()
        cmc = card.get("cmc", 0) or 0
        oracle = (card.get("oracle_text", "") or "").lower()
        keywords = (card.get("keywords", "") or "").lower()

        # Determine primary type
        primary_type = "Other"
        if "land" in type_line:
            primary_type = "Land"
            land_count += 1
        elif "creature" in type_line:
            primary_type = "Creature"
        elif "instant" in type_line:
            primary_type = "Instant"
        elif "sorcery" in type_line:
            primary_type = "Sorcery"
        elif "artifact" in type_line:
            primary_type = "Artifact"
        elif "enchantment" in type_line:
            primary_type = "Enchantment"
        elif "planeswalker" in type_line:
            primary_type = "Planeswalker"

        card_type_counts[primary_type] = card_type_counts.get(primary_type, 0) + 1

        # Mana curve (exclude lands)
        if primary_type != "Land":
            bucket = min(int(cmc), 7)
            curve_buckets[bucket] += 1

        # Functional role classification
        role = _classify_role(oracle, keywords, type_line, primary_type)
        if role:
            functional_counts[role] = functional_counts.get(role, 0) + 1

    return {
        "landCount": land_count,
        "curveBuckets": curve_buckets,
        "cardTypeCounts": card_type_counts,
        "functionalCounts": functional_counts,
    }


def _classify_role(oracle: str, keywords: str, type_line: str, primary_type: str) -> str:
    """Classify a card's functional role from its oracle text and type."""
    if primary_type == "Land":
        return ""

    # Ramp detection
    if any(phrase in oracle for phrase in [
        "add {", "add one mana", "search your library for a basic land",
        "search your library for a land", "mana of any", "additional land",
    ]):
        return "ramp"

    # Card draw
    if any(phrase in oracle for phrase in [
        "draw a card", "draw two", "draw three", "draw cards",
        "draw x card", "draws a card",
    ]):
        return "draw"

    # Removal
    if any(phrase in oracle for phrase in [
        "destroy target", "exile target", "deals damage to target",
        "-x/-x", "destroy all", "exile all", "return target",
        "counter target spell",
    ]):
        return "removal"

    # Protection / interaction
    if any(phrase in oracle for phrase in [
        "hexproof", "indestructible", "protection from",
        "shroud", "ward",
    ]) or any(kw in keywords for kw in ["hexproof", "indestructible", "ward"]):
        return "protection"

    # Tutor
    if "search your library" in oracle and "land" not in oracle:
        return "tutor"

    # Threat / finisher (high-power creatures, planeswalkers)
    if primary_type == "Planeswalker":
        return "threat"
    if primary_type == "Creature" and (
        "whenever" in oracle or "each" in oracle or "all" in oracle
    ):
        return "threat"

    # Default: utility
    return "utility"


# ── Game data extraction helpers ─────────────────────────────

def _extract_games_from_batch(batch: dict, deck_name: str) -> List[dict]:
    """
    Extract game data from a batch in a normalized format,
    supporting both DeepSeek and Java batch formats.

    Returns list of:
    {
        "won": bool,
        "turns": int,
        "opponents": [str],
        "cardStats": [{"cardName": ..., "drawn": ..., "cast": ..., ...}]
    }
    """
    games = []

    # Find this deck in the batch
    batch_deck = None
    for di in batch.get("decks", []):
        if di.get("deckName", "") == deck_name:
            batch_deck = di
            break
    if batch_deck is None:
        return games

    # Determine opponent names
    opponents = [
        di.get("deckName", "")
        for di in batch.get("decks", [])
        if di.get("deckName", "") != deck_name
    ]

    # ── Format 1: DeepSeek format ──
    # Games are nested inside each deck: batch_deck["games"] = [{"winner": 0, "turns": 12, "playerA": {...}, ...}]
    deck_games = batch_deck.get("games", [])
    if deck_games:
        for game in deck_games:
            if "error" in game and "winner" not in game:
                continue  # Skip errored games

            won = game.get("winner", -1) == 0
            turns = game.get("turns", 0)
            games.append({
                "won": won,
                "turns": turns,
                "opponents": opponents,
                "cardStats": [],  # DeepSeek doesn't have per-card stats
            })
        return games

    # ── Format 2: Java format ──
    # Games are at batch level: batch["games"] = [{"totalTurns": ..., "playerResults": [...]}]
    batch_seat = batch_deck.get("seatIndex", 0)
    for game in batch.get("games", []):
        my_result = None
        for pr in game.get("playerResults", []):
            if pr.get("seatIndex") == batch_seat:
                my_result = pr
                break
        if my_result is None:
            continue

        won = my_result.get("isWinner", False)
        turns = game.get("totalTurns", 0)
        card_stats = my_result.get("cardStats", [])

        games.append({
            "won": won,
            "turns": turns,
            "opponents": opponents,
            "cardStats": card_stats,
        })

    return games


def _build_deck_report(deck_name: str, deck_info: dict, all_batches: list) -> dict:
    """Build a complete deck report from batch data."""
    commander = deck_info.get("commanderName", deck_name)
    colors = deck_info.get("colorIdentity", [])

    total_games = 0
    total_wins = 0
    total_turns = 0

    # Per-card accumulators (from Java format cardStats)
    card_map: Dict[str, dict] = {}

    # Matchup tracking
    matchup_map: Dict[str, List[int]] = {}  # opponent -> [games, wins]

    for batch in all_batches:
        # Update commander/colors from batch deck entry
        for di in batch.get("decks", []):
            if di.get("deckName") == deck_name:
                if not commander or commander == deck_name:
                    commander = di.get("commanderName", di.get("commander", deck_name))
                if not colors:
                    colors = di.get("colorIdentity", [])
                break

        # Extract normalized game data
        games = _extract_games_from_batch(batch, deck_name)

        for game in games:
            total_games += 1
            total_turns += game["turns"]

            won = game["won"]
            if won:
                total_wins += 1

            # Matchups
            for opp in game["opponents"]:
                if opp not in matchup_map:
                    matchup_map[opp] = [0, 0]
                matchup_map[opp][0] += 1
                if won:
                    matchup_map[opp][1] += 1

            # Per-card stats (only available from Java format)
            for pcs in game.get("cardStats", []):
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

    # ── Populate deck structure from DB ───────────────────────

    structure = {
        "landCount": 0,
        "curveBuckets": [0] * 8,
        "cardTypeCounts": {},
        "functionalCounts": {},
    }

    deck_cards_meta = _get_deck_card_metadata(deck_name)
    if deck_cards_meta:
        structure = _compute_structure(deck_cards_meta)
        logger.info("Populated structure for %s from DB: %d lands, types=%s",
                     deck_name, structure["landCount"], structure["cardTypeCounts"])

        # If we have no per-card stats from sim data (DeepSeek format),
        # create placeholder card entries from the DB so the coach has
        # card names to work with
        if not cards and deck_cards_meta:
            for card_meta in deck_cards_meta:
                card_name = card_meta["name"]
                type_line = card_meta.get("type_line", "")
                # Skip basic lands from the card list sent to coach
                if "Basic" in type_line and "Land" in type_line:
                    continue
                cards.append({
                    "name": card_name,
                    "drawnRate": 0.0,
                    "castRate": 0.0,
                    "keptInOpeningHandRate": 0.0,
                    "deadCardRate": 0.0,
                    "impactScore": 0.0,
                    "synergyScore": 0.0,
                    "clunkinessScore": 0.0,
                    "avgTurnCast": None,
                    "avgDamageDealt": 0.0,
                    "tags": _get_card_tags(card_meta),
                })

    # ── Identify under/over performers ────────────────────────

    underperformers = []
    overperformers = []

    if any(c["impactScore"] != 0 for c in cards):
        # We have real sim data — use impact scores
        sorted_by_impact = sorted(cards, key=lambda c: c["impactScore"])

        for c in sorted_by_impact[:MAX_UNDERPERFORMERS]:
            if c["impactScore"] < UNDERPERFORMER_THRESHOLD:
                underperformers.append(c["name"])

        for c in reversed(sorted_by_impact[-MAX_OVERPERFORMERS:]):
            if c["impactScore"] > 0:
                overperformers.append(c["name"])
    elif cards:
        # No real per-card stats (DeepSeek only) — flag cards with
        # highest mana cost and least synergy potential as candidates.
        # This gives the coach SOMETHING to work with.
        logger.info("No per-card sim data for %s — using DB heuristics for underperformers", deck_name)
        if deck_cards_meta:
            # Sort non-land cards by CMC descending — highest cost cards
            # are most likely underperformers in aggressive/midrange decks
            nonland = [c for c in deck_cards_meta if "land" not in (c.get("type_line", "") or "").lower()]
            by_cmc = sorted(nonland, key=lambda c: c.get("cmc", 0) or 0, reverse=True)
            for c in by_cmc[:MAX_UNDERPERFORMERS]:
                if (c.get("cmc", 0) or 0) >= 5:
                    underperformers.append(c["name"])

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
        "structure": structure,
        "cards": cards,
        "underperformers": underperformers,
        "overperformers": overperformers,
        "knownCombos": [],
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
    }


def _get_card_tags(card_meta: dict) -> List[str]:
    """Derive functional tags from card metadata."""
    tags = []
    type_line = (card_meta.get("type_line", "") or "").lower()
    oracle = (card_meta.get("oracle_text", "") or "").lower()
    keywords = (card_meta.get("keywords", "") or "").lower()

    role = _classify_role(oracle, keywords, type_line,
                          _primary_type(type_line))
    if role:
        tags.append(role)

    if "creature" in type_line:
        tags.append("creature")
    if "legendary" in type_line:
        tags.append("legendary")

    return tags


def _primary_type(type_line: str) -> str:
    """Get primary card type from type line."""
    tl = type_line.lower()
    if "land" in tl:
        return "Land"
    elif "creature" in tl:
        return "Creature"
    elif "instant" in tl:
        return "Instant"
    elif "sorcery" in tl:
        return "Sorcery"
    elif "artifact" in tl:
        return "Artifact"
    elif "enchantment" in tl:
        return "Enchantment"
    elif "planeswalker" in tl:
        return "Planeswalker"
    return "Other"
