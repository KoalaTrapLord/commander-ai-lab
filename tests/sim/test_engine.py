"""Seeded simulation tests for the game engine."""
import random
import pytest
from commander_ai_lab.sim.models import Card, Player, PlayerStats
from commander_ai_lab.sim.rules import enrich_card
from commander_ai_lab.sim.engine import GameEngine


def _make_deck(seed: int, size: int = 60) -> list[Card]:
    """Build a deterministic test deck using a seeded RNG."""
    rng = random.Random(seed)
    card_pool = [
        Card(name="Forest"),
        Card(name="Sol Ring"),
        Card(name="Cultivate"),
        Card(name="Murder"),
        Card(name="Wrath of God"),
        Card(name="Grizzly Bears"),
        Card(name="Serra Angel"),
    ]
    for c in card_pool:
        enrich_card(c)
    deck = []
    for i in range(size):
        deck.append(card_pool[i % len(card_pool)].clone())
    rng.shuffle(deck)
    return deck


class TestGameEngineTwoPlayer:
    def test_game_completes(self):
        """A 2-player seeded game should finish without error."""
        engine = GameEngine(seed=42)
        deck_a = _make_deck(seed=1)
        deck_b = _make_deck(seed=2)
        result = engine.run_game(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
            player_a_name="Alice",
            player_b_name="Bob",
        )
        assert result is not None
        assert result.turns > 0

    def test_result_has_winner_or_draw(self):
        """winner_seat must be 0, 1, or -1 (draw)."""
        engine = GameEngine(seed=99)
        deck = _make_deck(seed=5)
        result = engine.run_game(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
            player_a_name="P1",
            player_b_name="P2",
        )
        assert result.winner_seat in (-1, 0, 1)

    def test_seeded_game_is_deterministic(self):
        """Same seed must produce identical results."""
        deck_a = _make_deck(seed=7)
        deck_b = _make_deck(seed=8)

        engine1 = GameEngine(seed=42)
        result1 = engine1.run_game(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
            player_a_name="Alice",
            player_b_name="Bob",
        )

        engine2 = GameEngine(seed=42)
        result2 = engine2.run_game(
            deck_a=[c.clone() for c in deck_a],
            deck_b=[c.clone() for c in deck_b],
            player_a_name="Alice",
            player_b_name="Bob",
        )

        assert result1.winner_seat == result2.winner_seat
        assert result1.turns == result2.turns

    def test_to_dict_serializable(self):
        """Game result must serialize to a dict with expected keys."""
        import json
        engine = GameEngine(seed=77)
        deck = _make_deck(seed=3)
        result = engine.run_game(
            deck_a=[c.clone() for c in deck],
            deck_b=[c.clone() for c in deck],
            player_a_name="A",
            player_b_name="B",
        )
        d = result.to_dict()
        assert "winner" in d
        assert "turns" in d
        assert "playerResults" in d
        # Ensure it's JSON-serializable
        json.dumps(d)
