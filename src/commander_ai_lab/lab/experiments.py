"""
Commander AI Lab — Experiments Module
=======================================
High-level simulation helpers for running Commander experiments.

Usage:
    python -m commander_ai_lab.lab.experiments

Functions:
    build_deck(card_names)  — Create an enriched deck from card names
    run_single_game(deck)   — Simulate a single game, return stats dict
    run_simulation(deck, n) — Monte Carlo simulation, return aggregated stats
"""

from __future__ import annotations
import logging

log = logging.getLogger("commander_ai_lab.lab.experiments")


import time
from typing import Optional

from commander_ai_lab.sim.models import Card
from commander_ai_lab.sim.engine import GameEngine
from commander_ai_lab.sim.rules import enrich_card, parse_decklist


# ══════════════════════════════════════════════════════════════
# Deck Building
# ══════════════════════════════════════════════════════════════

def build_deck(card_names: list[str]) -> list[Card]:
    """
    Build an enriched deck from a list of card names.
    Each card is enriched with type/cost heuristics if data is missing.
    """
    deck = []
    for name in card_names:
        card = Card(name=name)
        enrich_card(card)
        deck.append(card)
    return deck


def build_deck_from_text(decklist_text: str) -> list[Card]:
    """
    Build an enriched deck from a decklist string.
    Format: one card per line, optionally prefixed with quantity.
    Example:
        1 Sol Ring
        37 Forest
        Cultivate
    """
    cards = parse_decklist(decklist_text)
    for card in cards:
        enrich_card(card)
    return cards


# ══════════════════════════════════════════════════════════════
# Single Game
# ══════════════════════════════════════════════════════════════

def run_single_game(
    deck_a: list[Card],
    deck_b: Optional[list[Card]] = None,
    name_a: str = "Deck A",
    name_b: str = "Deck B",
    max_turns: int = 25,
) -> dict:
    """
    Run a single simulated game.

    Args:
        deck_a: The primary deck (list of Card objects).
        deck_b: The opponent deck. If None, a default training deck is used.
        name_a: Name for player A.
        name_b: Name for player B.
        max_turns: Maximum turns before the game ends.

    Returns:
        Dict with keys: winner (int), turns (int), result (full GameResult dict).
    """
    if deck_b is None:
        deck_b = _generate_training_deck()

    engine = GameEngine(max_turns=max_turns)
    result = engine.run(deck_a, deck_b, name_a=name_a, name_b=name_b)

    return {
        "winner": result.winner,
        "winner_name": name_a if result.winner == 0 else name_b,
        "turns": result.turns,
        "result": result.to_dict(),
    }


# ══════════════════════════════════════════════════════════════
# Monte Carlo Simulation
# ══════════════════════════════════════════════════════════════

def run_simulation(
    deck_a: list[Card],
    deck_b: Optional[list[Card]] = None,
    num_games: int = 100,
    name_a: str = "Deck A",
    name_b: str = "Deck B",
    max_turns: int = 25,
) -> dict:
    """
    Run a Monte Carlo simulation across multiple games.

    Args:
        deck_a: The primary deck.
        deck_b: The opponent deck. If None, uses default training deck.
        num_games: Number of games to simulate.
        name_a: Name for player A.
        name_b: Name for player B.
        max_turns: Maximum turns per game.

    Returns:
        Aggregated stats dict with win_rate, avg_turns, total_games, wins, losses,
        avg_damage_dealt, avg_damage_received, avg_spells_cast, avg_creatures_played.
    """
    if deck_b is None:
        deck_b = _generate_training_deck()

    engine = GameEngine(max_turns=max_turns)

    wins = 0
    losses = 0
    total_turns = 0
    total_damage_dealt = 0
    total_damage_received = 0
    total_spells_cast = 0
    total_creatures_played = 0
    total_removal_used = 0
    total_ramp_played = 0
    total_cards_drawn = 0
    total_max_board = 0

    start = time.time()

    for _ in range(num_games):
        result = engine.run(deck_a, deck_b, name_a=name_a, name_b=name_b)

        if result.winner == 0:
            wins += 1
        else:
            losses += 1

        total_turns += result.turns
        if result.player_a_stats:
            total_damage_dealt += result.player_a_stats.damage_dealt
            total_damage_received += result.player_a_stats.damage_received
            total_spells_cast += result.player_a_stats.spells_cast
            total_creatures_played += result.player_a_stats.creatures_played
            total_removal_used += result.player_a_stats.removal_used
            total_ramp_played += result.player_a_stats.ramp_played
            total_cards_drawn += result.player_a_stats.cards_drawn
            total_max_board += result.player_a_stats.max_board_size

    elapsed = time.time() - start
    n = num_games

    return {
        "deck_name": name_a,
        "opponent_name": name_b,
        "total_games": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n * 100, 1) if n > 0 else 0.0,
        "avg_turns": round(total_turns / n, 1) if n > 0 else 0.0,
        "avg_damage_dealt": round(total_damage_dealt / n, 1) if n > 0 else 0.0,
        "avg_damage_received": round(total_damage_received / n, 1) if n > 0 else 0.0,
        "avg_spells_cast": round(total_spells_cast / n, 1) if n > 0 else 0.0,
        "avg_creatures_played": round(total_creatures_played / n, 1) if n > 0 else 0.0,
        "avg_removal_used": round(total_removal_used / n, 1) if n > 0 else 0.0,
        "avg_ramp_played": round(total_ramp_played / n, 1) if n > 0 else 0.0,
        "avg_cards_drawn": round(total_cards_drawn / n, 1) if n > 0 else 0.0,
        "avg_max_board_size": round(total_max_board / n, 1) if n > 0 else 0.0,
        "elapsed_seconds": round(elapsed, 2),
    }


# ══════════════════════════════════════════════════════════════
# Default Training Deck
# ══════════════════════════════════════════════════════════════

def _generate_training_deck() -> list[Card]:
    """
    Generate a default opponent deck for testing.
    Ported from generateTrainingDeck() in app.js.
    37 forests + 20 creatures of varying size + some spells.
    """
    deck: list[Card] = []

    # 37 lands
    for _ in range(37):
        c = Card(name="Forest", type_line="Basic Land - Forest", oracle_text="{T}: Add {G}", cmc=0)
        deck.append(c)

    # 20 creatures of varying sizes
    creatures = [
        ("Llanowar Elves", 1, "1/1"), ("Elvish Mystic", 1, "1/1"),
        ("Sakura-Tribe Elder", 2, "1/1"), ("Reclamation Sage", 3, "2/1"),
        ("Beast Whisperer", 4, "2/3"), ("Ravenous Baloth", 4, "4/4"),
        ("Thragtusk", 5, "5/3"), ("Acidic Slime", 5, "2/2"),
        ("Carnage Tyrant", 6, "7/6"), ("Rampaging Baloths", 6, "6/6"),
        ("Verdant Force", 8, "7/7"), ("Woodfall Primus", 8, "6/6"),
        ("Terastodon", 8, "9/9"), ("Craterhoof Behemoth", 8, "5/5"),
        ("Ghalta, Primal Hunger", 12, "12/12"), ("Garruk's Packleader", 5, "4/4"),
        ("Timberwatch Elf", 3, "1/2"), ("Fierce Empath", 3, "1/1"),
        ("Yavimaya Elder", 3, "2/1"), ("Eternal Witness", 3, "2/1"),
    ]
    for name, cmc, pt in creatures:
        parts = pt.split("/")
        c = Card(
            name=name, type_line="Creature", cmc=cmc, pt=pt,
            power=parts[0], toughness=parts[1],
        )
        deck.append(c)

    # 6 spells
    spells = [
        Card(name="Cultivate", type_line="Sorcery", cmc=3, oracle_text="Search your library for two basic lands.", is_ramp=True),
        Card(name="Kodama's Reach", type_line="Sorcery", cmc=3, oracle_text="Search your library for two basic lands.", is_ramp=True),
        Card(name="Harmonize", type_line="Sorcery", cmc=4, oracle_text="Draw three cards."),
        Card(name="Beast Within", type_line="Instant", cmc=3, oracle_text="Destroy target permanent.", is_removal=True),
        Card(name="Nature's Lore", type_line="Sorcery", cmc=2, oracle_text="Search your library for a forest.", is_ramp=True),
        Card(name="Sol Ring", type_line="Artifact", cmc=1, oracle_text="{T}: Add {C}{C}", is_ramp=True),
    ]
    deck.extend(spells)

    return deck


# ══════════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════════

def _print_stats(stats: dict) -> None:
    """Pretty-print simulation stats."""
    log.info("")
    log.info("=" * 60)
    log.info(f"  SIMULATION RESULTS: {stats['deck_name']} vs {stats['opponent_name']}")
    log.info("=" * 60)
    log.info(f"  Games played:      {stats['total_games']}")
    log.info(f"  Wins / Losses:     {stats['wins']} / {stats['losses']}")
    log.info(f"  Win Rate:          {stats['win_rate']}%")
    log.info(f"  Avg Turns:         {stats['avg_turns']}")
    log.info("-" * 60)
    log.info(f"  Avg Damage Dealt:     {stats['avg_damage_dealt']}")
    log.info(f"  Avg Damage Received:  {stats['avg_damage_received']}")
    log.info(f"  Avg Spells Cast:      {stats['avg_spells_cast']}")
    log.info(f"  Avg Creatures Played: {stats['avg_creatures_played']}")
    log.info(f"  Avg Removal Used:     {stats['avg_removal_used']}")
    log.info(f"  Avg Ramp Played:      {stats['avg_ramp_played']}")
    log.info(f"  Avg Cards Drawn:      {stats['avg_cards_drawn']}")
    log.info(f"  Avg Max Board Size:   {stats['avg_max_board_size']}")
    log.info("-" * 60)
    log.info(f"  Elapsed:           {stats['elapsed_seconds']}s")
    log.info("=" * 60)
    log.info("")


def _cli_main() -> None:
    """CLI entry point for `commander-sim` script."""
    _run_smoke_test()


def _run_smoke_test() -> None:
    """Run the built-in smoke test."""
    # ── Smoke test with a small Korvold Aristocrats list ──
    test_decklist = [
        # Commander
        "Korvold, Fae-Cursed King",
        # Lands (37)
        *["Swamp"] * 12,
        *["Forest"] * 12,
        *["Mountain"] * 13,
        # Ramp (8)
        "Sol Ring", "Arcane Signet", "Fellwar Stone",
        "Cultivate", "Kodama's Reach", "Nature's Lore",
        "Rampant Growth", "Farseek",
        # Removal (6)
        "Beast Within", "Chaos Warp", "Go for the Throat",
        "Murder", "Hero's Downfall", "Generous Gift",
        # Board wipes (2)
        "Damnation", "Blasphemous Act",
        # Creatures (10)
        "Sakura-Tribe Elder", "Viscera Seer", "Blood Artist",
        "Zulaport Cutthroat", "Mayhem Devil", "Savvy Hunter",
        "Butcher of Malakir", "Grave Pact", "Dictate of Erebos",
        "Avenger of Zendikar",
        # Draw / utility (3)
        "Harmonize", "Read the Bones", "Phyrexian Arena",
    ]

    log.info("Building test deck (Korvold Aristocrats)...")
    test_deck = build_deck(test_decklist)
    log.info(f"  Deck size: {len(test_deck)} cards")

    log.info("\nRunning single game...")
    single = run_single_game(test_deck, name_a="Korvold")
    log.info(f"  Winner: {single['winner_name']} in {single['turns']} turns")

    log.info("\nRunning Monte Carlo simulation (10 games)...")
    stats = run_simulation(test_deck, num_games=10, name_a="Korvold")
    _print_stats(stats)


if __name__ == "__main__":
    _run_smoke_test()
