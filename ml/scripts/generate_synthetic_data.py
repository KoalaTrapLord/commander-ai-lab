"""
Commander AI Lab — Synthetic Training Data Generator
═════════════════════════════════════════════════════
Generates realistic-looking decision snapshot JSONL files
for testing the full ML pipeline without running actual Forge sims.

Uses real card names from precon decks and simulates plausible
game progressions (draws, casts, attacks, mana development).

Usage:
    python -m ml.scripts.generate_synthetic_data --games 200 --output results/ml-decisions-synthetic.jsonl
"""

import json
import os
import random
import sys
import argparse
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# ── Load real card names from precon decks ─────────────────

def load_precon_cards(precon_dir: str) -> dict:
    """Load card names from .dck files, grouped by deck."""
    decks = {}
    precon_path = Path(precon_dir)
    if not precon_path.exists():
        print(f"Precon dir not found: {precon_dir}")
        return {}

    for dck_file in precon_path.glob("*.dck"):
        deck_name = dck_file.stem.replace("_", " ")
        cards = {"commander": None, "creatures": [], "spells": [], "lands": [], "artifacts": [], "all": []}

        section = "Main"
        with open(dck_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//") or line.startswith("Name="):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                    continue

                # Parse "1 Card Name|SET"
                parts = line.split(" ", 1)
                if len(parts) < 2:
                    continue
                try:
                    qty = int(parts[0])
                except ValueError:
                    continue
                card_name = parts[1].split("|")[0].strip()

                if section == "Commander":
                    cards["commander"] = card_name
                else:
                    cards["all"].append(card_name)
                    lower = card_name.lower()
                    if any(k in lower for k in ["plains", "island", "swamp", "mountain", "forest",
                                                  "command tower", "temple", "gate", "land"]):
                        cards["lands"].append(card_name)
                    elif any(k in lower for k in ["sol ring", "signet", "talisman", "mana crypt",
                                                    "cultivate", "kodama", "rampant", "farseek"]):
                        cards["artifacts"].append(card_name)
                    else:
                        # Rough split: ~60% creatures, ~40% spells
                        if random.random() < 0.6:
                            cards["creatures"].append(card_name)
                        else:
                            cards["spells"].append(card_name)

        if cards["commander"]:
            decks[deck_name] = cards

    return decks


# ── Known removal/draw/ramp for more accurate labeling ────

REMOVAL_NAMES = [
    "Swords to Plowshares", "Path to Exile", "Beast Within", "Chaos Warp",
    "Counterspell", "Swan Song", "Cyclonic Rift", "Blasphemous Act",
    "Wrath of God", "Generous Gift", "Terminate", "Go for the Throat",
    "Doom Blade", "Rapid Hybridization", "Vandalblast", "Krosan Grip",
]

DRAW_NAMES = [
    "Rhystic Study", "Mystic Remora", "Harmonize", "Brainstorm",
    "Ponder", "Preordain", "Night's Whisper", "Sign in Blood",
    "Phyrexian Arena", "Sylvan Library", "Skullclamp", "Read the Bones",
]

RAMP_NAMES = [
    "Sol Ring", "Arcane Signet", "Cultivate", "Kodama's Reach",
    "Rampant Growth", "Farseek", "Mind Stone", "Commander's Sphere",
    "Fellwar Stone", "Thought Vessel", "Nature's Lore", "Solemn Simulacrum",
]

PLAYSTYLES = ["aggro", "control", "midrange", "combo"]
PHASES = ["main_1", "combat", "main_2", "end"]


def generate_game_decisions(
    game_id: str,
    deck_a: dict,
    deck_b: dict,
    deck_a_name: str,
    deck_b_name: str,
) -> list:
    """Generate synthetic decisions for a single game."""
    decisions = []

    # Shuffle decks (simulating library)
    lib_a = list(deck_a["all"])
    lib_b = list(deck_b["all"])
    random.shuffle(lib_a)
    random.shuffle(lib_b)

    # Starting state
    life = [40, 40]
    hand = [lib_a[:7], lib_b[:7]]
    lib_a = lib_a[7:]
    lib_b = lib_b[7:]
    libraries = [lib_a, lib_b]
    battlefield = [[], []]
    graveyard = [[], []]
    cmd_zone = [[deck_a["commander"]], [deck_b["commander"]]]
    cmdr_dmg = [0, 0]
    cmdr_casts = [0, 0]
    lands_played = [0, 0]
    playstyle_a = random.choice(PLAYSTYLES)
    playstyle_b = random.choice(PLAYSTYLES)
    playstyles = [playstyle_a, playstyle_b]
    commanders = [deck_a["commander"], deck_b["commander"]]
    deck_names = [deck_a_name, deck_b_name]

    max_turns = random.randint(8, 20)
    winner = None

    for turn in range(1, max_turns + 1):
        for active_seat in range(2):
            if life[0] <= 0 or life[1] <= 0:
                break

            # Draw a card
            if libraries[active_seat]:
                drawn = libraries[active_seat].pop(0)
                hand[active_seat].append(drawn)

            # Decide number of actions this turn (1-3)
            num_actions = random.randint(1, 3)

            for _ in range(num_actions):
                if life[0] <= 0 or life[1] <= 0:
                    break

                phase = random.choice(["main_1", "main_2", "combat"])

                # Build player snapshots
                players = []
                for s in range(2):
                    players.append({
                        "seat": s,
                        "life": life[s],
                        "cmdr_dmg": cmdr_dmg[s],
                        "mana": lands_played[s],
                        "cmdr_tax": cmdr_casts[s] * 2,
                        "creatures": len([c for c in battlefield[s]
                                          if c.lower() not in ["sol ring", "arcane signet"]]),
                        "lands": lands_played[s],
                        "hand": list(hand[s]),
                        "battlefield": list(battlefield[s]),
                        "graveyard": list(graveyard[s]),
                        "command_zone": list(cmd_zone[s]),
                    })

                # Choose action based on game state
                action = choose_synthetic_action(
                    active_seat, turn, phase, hand[active_seat],
                    battlefield[active_seat], lands_played[active_seat],
                    commanders[active_seat], cmd_zone[active_seat],
                    cmdr_casts[active_seat], playstyles[active_seat],
                )

                # Build decision
                decision = {
                    "game_id": game_id,
                    "turn": turn,
                    "phase": phase,
                    "active_seat": active_seat,
                    "game_outcome": "",  # filled later
                    "deck_name": deck_names[active_seat],
                    "commander": commanders[active_seat],
                    "archetype": playstyles[active_seat],
                    "players": players,
                    "action": action,
                }
                decisions.append(decision)

                # Apply action effects to state
                apply_action(
                    action, active_seat, hand, battlefield, graveyard,
                    cmd_zone, lands_played, life, cmdr_dmg, cmdr_casts,
                    commanders, libraries,
                )

        if life[0] <= 0 or life[1] <= 0:
            break

    # Determine winner
    if life[1] <= 0 and life[0] > 0:
        winner = "win_seat_0"
    elif life[0] <= 0 and life[1] > 0:
        winner = "win_seat_1"
    else:
        # Random winner if game timed out
        winner = random.choice(["win_seat_0", "win_seat_1"])

    # Backfill game_outcome
    for d in decisions:
        d["game_outcome"] = winner

    return decisions


def choose_synthetic_action(
    seat, turn, phase, hand, battlefield, mana, commander, cmd_zone,
    cmdr_casts, playstyle,
) -> dict:
    """Choose a plausible action based on game state."""

    # Early game: prioritize lands and ramp
    if turn <= 3:
        # Play land if in hand
        for card in hand:
            lower = card.lower()
            if any(k in lower for k in ["plains", "island", "swamp", "mountain", "forest",
                                          "command tower", "temple", "gate"]):
                return {"type": "land", "card": card, "target": "", "raw": f"plays {card}."}

        # Cast ramp
        for card in hand:
            if card in RAMP_NAMES or card.lower() in [r.lower() for r in RAMP_NAMES]:
                if mana >= 1:
                    return {"type": "cast", "card": card, "target": "", "raw": f"casts {card}."}

    # Mid/late game: more variety
    action_weights = {
        "aggro": {"attack": 0.35, "creature": 0.30, "removal": 0.10, "draw": 0.05, "ramp": 0.05, "commander": 0.10, "pass": 0.05},
        "control": {"attack": 0.10, "creature": 0.15, "removal": 0.30, "draw": 0.20, "ramp": 0.10, "commander": 0.05, "pass": 0.10},
        "midrange": {"attack": 0.20, "creature": 0.25, "removal": 0.15, "draw": 0.10, "ramp": 0.10, "commander": 0.10, "pass": 0.10},
        "combo": {"attack": 0.10, "creature": 0.20, "removal": 0.10, "draw": 0.25, "ramp": 0.15, "commander": 0.10, "pass": 0.10},
    }
    weights = action_weights.get(playstyle, action_weights["midrange"])

    # Roll action type
    roll = random.random()
    cumulative = 0
    chosen_type = "pass"
    for action_type, weight in weights.items():
        cumulative += weight
        if roll <= cumulative:
            chosen_type = action_type
            break

    # Attack
    if chosen_type == "attack" and phase == "combat" and battlefield:
        return {"type": "attack", "card": "", "target": "", "raw": "attacks with creatures."}

    # Cast commander
    if chosen_type == "commander" and cmd_zone and commander in cmd_zone:
        tax = cmdr_casts * 2
        if mana >= 3 + tax:  # rough mana check
            return {"type": "cast_commander", "card": commander, "target": "", "raw": f"casts {commander}."}

    # Cast creature from hand
    if chosen_type == "creature" and hand:
        card = random.choice(hand)
        return {"type": "cast", "card": card, "target": "", "raw": f"casts {card}."}

    # Cast removal
    if chosen_type == "removal":
        removal_in_hand = [c for c in hand if c in REMOVAL_NAMES or c.lower() in [r.lower() for r in REMOVAL_NAMES]]
        if removal_in_hand:
            card = random.choice(removal_in_hand)
            return {"type": "cast", "card": card, "target": "opponent creature", "raw": f"casts {card}."}
        # Use any spell as removal stand-in
        if hand:
            card = random.choice(hand)
            return {"type": "cast", "card": card, "target": "", "raw": f"casts {card}."}

    # Cast draw
    if chosen_type == "draw":
        draw_in_hand = [c for c in hand if c in DRAW_NAMES or c.lower() in [r.lower() for r in DRAW_NAMES]]
        if draw_in_hand:
            card = random.choice(draw_in_hand)
            return {"type": "cast", "card": card, "target": "", "raw": f"casts {card}."}

    # Cast ramp
    if chosen_type == "ramp":
        ramp_in_hand = [c for c in hand if c in RAMP_NAMES or c.lower() in [r.lower() for r in RAMP_NAMES]]
        if ramp_in_hand:
            card = random.choice(ramp_in_hand)
            return {"type": "cast", "card": card, "target": "", "raw": f"casts {card}."}

    # Land play fallback
    for card in hand:
        lower = card.lower()
        if any(k in lower for k in ["plains", "island", "swamp", "mountain", "forest", "command tower"]):
            return {"type": "land", "card": card, "target": "", "raw": f"plays {card}."}

    # Pass
    if mana >= 2:
        return {"type": "pass", "card": "", "target": "", "raw": "passes priority."}

    return {"type": "pass", "card": "", "target": "", "raw": "passes."}


def apply_action(action, seat, hand, battlefield, graveyard, cmd_zone,
                  lands_played, life, cmdr_dmg, cmdr_casts, commanders, libraries):
    """Apply an action's side effects to game state."""
    atype = action["type"]
    card = action.get("card", "")

    if atype == "land" and card and card in hand[seat]:
        hand[seat].remove(card)
        battlefield[seat].append(card)
        lands_played[seat] += 1

    elif atype == "cast" and card and card in hand[seat]:
        hand[seat].remove(card)
        battlefield[seat].append(card)

    elif atype == "cast_commander" and card:
        if card in cmd_zone[seat]:
            cmd_zone[seat].remove(card)
        battlefield[seat].append(card)
        cmdr_casts[seat] += 1

    elif atype == "attack":
        # Simulate some damage
        opponent = 1 - seat
        num_attackers = min(len(battlefield[seat]), random.randint(1, 4))
        damage = num_attackers * random.randint(2, 5)
        life[opponent] -= damage
        # Commander damage if commander is on field
        if commanders[seat] in battlefield[seat] and random.random() < 0.3:
            cmd_dmg = random.randint(3, 7)
            cmdr_dmg[opponent] += cmd_dmg


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic ML training data")
    parser.add_argument("--games", type=int, default=200,
                        help="Number of games to simulate (default: 200)")
    parser.add_argument("--output", default="results/ml-decisions-synthetic.jsonl",
                        help="Output JSONL path")
    parser.add_argument("--precon-dir", default=None,
                        help="Path to precon decks (default: auto-detect)")
    args = parser.parse_args()

    # Find precon decks
    precon_dir = args.precon_dir or str(Path(project_root) / "precon-decks")
    decks = load_precon_cards(precon_dir)

    if not decks:
        print("No precon decks found. Cannot generate synthetic data.")
        sys.exit(1)

    deck_names = list(decks.keys())
    print(f"Loaded {len(deck_names)} precon decks: {', '.join(deck_names[:5])}...")

    # Generate games
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    total_decisions = 0

    with open(args.output, "w") as f:
        for game_idx in range(args.games):
            # Pick two random decks
            d1_name, d2_name = random.sample(deck_names, 2)
            d1, d2 = decks[d1_name], decks[d2_name]

            game_id = f"synthetic-{game_idx:04d}"
            decisions = generate_game_decisions(game_id, d1, d2, d1_name, d2_name)

            for d in decisions:
                f.write(json.dumps(d) + "\n")
                total_decisions += 1

            if (game_idx + 1) % 50 == 0:
                print(f"  Generated {game_idx + 1}/{args.games} games...")

    print(f"\nDone: {args.games} games, {total_decisions:,} decisions")
    print(f"Output: {args.output}")
    print(f"Average {total_decisions / args.games:.1f} decisions per game")


if __name__ == "__main__":
    main()
