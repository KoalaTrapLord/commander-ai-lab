"""
Commander AI Lab — Headless Game Engine
=========================================
A headless Commander game simulator for Monte Carlo analysis.
Faithful port of dtSimGame() / dtCreatePlayer() from mtg-commander-lan.

Simulates simplified 1v1 Commander games:
  - Draw, land drop, spell casting (up to 2 per turn)
  - AI card scoring for play priority
  - Simplified combat with flying, trample, deathtouch, lifelink, menace, reach
  - Creature removal and board wipe handling
  - Win by elimination (life <= 0) or life comparison at max turns
"""

from __future__ import annotations

import random
from typing import Optional

from commander_ai_lab.sim.models import (
    Card,
    GameResult,
    Player,
    PlayerStats,
    SimState,
)
from commander_ai_lab.sim.rules import (
    AI_DEFAULT_WEIGHTS,
    enrich_card,
    score_card,
)


class GameEngine:
    """
    Headless Commander game engine.

    Usage::

        engine = GameEngine(max_turns=25)
        result = engine.run(deck_a, deck_b, name_a="Deck A", name_b="Deck B")
    """

    def __init__(
        self,
        max_turns: int = 25,
        starting_life: int = 40,
        weights: Optional[dict] = None,
        record_log: bool = False,
    ):
        self.max_turns = max_turns
        self.starting_life = starting_life
        self.weights = weights or AI_DEFAULT_WEIGHTS
        self.record_log = record_log

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def run(
        self,
        deck_a: list[Card],
        deck_b: list[Card],
        name_a: str = "Player A",
        name_b: str = "Player B",
    ) -> GameResult:
        """Run a single headless game and return the result."""
        sim = self._create_state(deck_a, deck_b, name_a, name_b)
        game_log: list[dict] = []  # turn-by-turn log

        final_turn = 0
        for turn in range(sim.max_turns):
            turn_entry = {"turn": turn + 1, "phases": []}

            for pi in range(2):
                p = sim.players[pi]
                if p.eliminated:
                    continue
                p.stats.turns_alive += 1
                phase_events: list[str] = []

                # ── Draw ──
                if p.library:
                    drawn = p.library[-1]  # peek before pop
                    p.hand.append(p.library.pop())
                    p.stats.cards_drawn += 1
                    if self.record_log:
                        phase_events.append(f"Drew {drawn.name}")

                # ── Land drop ──
                land_before = p.stats.lands_played
                self._play_land(sim, pi)
                if self.record_log and p.stats.lands_played > land_before:
                    # Find what land was just played
                    last_land = next(
                        (c for c in reversed(sim.battlefield)
                         if c.owner_id == pi and c.is_land()),
                        None,
                    )
                    if last_land:
                        phase_events.append(f"Played land: {last_land.name}")

                # ── Available mana ──
                available_mana = self._count_untapped_lands(sim, pi)

                # ── Play spells (up to 2) ──
                spells_before = p.stats.spells_cast
                self._play_spells(sim, pi, available_mana, phase_events if self.record_log else None)

                # ── Track board size ──
                board_size = sum(
                    1 for c in sim.battlefield if c.owner_id == pi
                )
                if board_size > p.stats.max_board_size:
                    p.stats.max_board_size = board_size

                # ── Combat ──
                combat_before_life_a = sim.players[0].life
                combat_before_life_b = sim.players[1].life
                self._resolve_combat(sim, pi, turn, phase_events if self.record_log else None)

                # ── Untap ──
                for c in sim.battlefield:
                    if c.owner_id == pi:
                        c.tapped = False

                if self.record_log:
                    turn_entry["phases"].append({
                        "player": p.name,
                        "playerId": pi,
                        "events": phase_events,
                        "lifeAfter": {sim.players[0].name: sim.players[0].life,
                                      sim.players[1].name: sim.players[1].life},
                        "boardA": [c.name for c in sim.battlefield if c.owner_id == 0 and c.is_creature()],
                        "boardB": [c.name for c in sim.battlefield if c.owner_id == 1 and c.is_creature()],
                    })

            # Check game over
            alive = [p for p in sim.players if not p.eliminated]
            final_turn = turn + 1
            if self.record_log:
                game_log.append(turn_entry)
            if len(alive) <= 1:
                if self.record_log:
                    elim_name = next((p.name for p in sim.players if p.eliminated), None)
                    if elim_name:
                        game_log[-1]["event"] = f"{elim_name} eliminated!"
                break
            if self.record_log:
                game_log.append(turn_entry) if turn_entry not in game_log else None

        result = self._build_result(sim, final_turn, name_a, name_b)
        if self.record_log:
            result.game_log = game_log
        return result

    # ──────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────

    def _create_state(
        self,
        deck_a: list[Card],
        deck_b: list[Card],
        name_a: str,
        name_b: str,
    ) -> SimState:
        """Create initial simulation state with shuffled decks and opening hands."""
        sim = SimState(max_turns=self.max_turns)

        for idx, (deck, name) in enumerate([(deck_a, name_a), (deck_b, name_b)]):
            # Enrich + deep copy cards
            cards = [enrich_card(c.clone()) for c in deck]
            random.shuffle(cards)

            hand = cards[:7]
            library = cards[7:]

            player = Player(
                name=name,
                life=self.starting_life,
                owner_id=idx,
                library=library,
                hand=hand,
                stats=PlayerStats(cards_drawn=7),
            )
            sim.players.append(player)

        return sim

    def _play_land(self, sim: SimState, pi: int) -> None:
        """Play the first land from hand onto the battlefield."""
        p = sim.players[pi]
        land_idx = -1
        for i, card in enumerate(p.hand):
            if card.is_land():
                land_idx = i
                break
        if land_idx == -1:
            return

        land_card = p.hand.pop(land_idx)
        land_card.owner_id = pi
        land_card.tapped = False
        land_card.id = sim.next_card_id
        sim.next_card_id += 1
        sim.battlefield.append(land_card)
        p.stats.lands_played += 1

    def _count_untapped_lands(self, sim: SimState, pi: int) -> int:
        """Count untapped lands for a player."""
        return sum(
            1
            for c in sim.battlefield
            if c.owner_id == pi and not c.tapped and c.is_land()
        )

    def _play_spells(self, sim: SimState, pi: int, available_mana: int, events: list | None = None) -> None:
        """Play up to 2 spells from hand, prioritized by AI score."""
        p = sim.players[pi]
        w = self.weights

        # Score playable non-land cards
        playable = []
        for i, card in enumerate(p.hand):
            if card.is_land():
                continue
            cmc = card.cmc or 0
            if cmc <= available_mana:
                playable.append((score_card(card, w), i, card))

        playable.sort(key=lambda x: -x[0])

        played = 0
        while playable and played < 2:
            _, _, best_card = playable.pop(0)
            hand_pos = -1
            for i, c in enumerate(p.hand):
                if c is best_card:
                    hand_pos = i
                    break
            if hand_pos == -1:
                continue

            card = p.hand.pop(hand_pos)
            card.owner_id = pi
            card.tapped = False
            card.id = sim.next_card_id
            sim.next_card_id += 1
            card.turn_played = sim.turn

            # Pay mana
            mana_needed = card.cmc or 0
            for bf_card in sim.battlefield:
                if mana_needed <= 0:
                    break
                if (
                    bf_card.owner_id == pi
                    and not bf_card.tapped
                    and bf_card.is_land()
                ):
                    bf_card.tapped = True
                    mana_needed -= 1

            p.stats.mana_spent += card.cmc or 0
            p.stats.spells_cast += 1

            # Handle removal
            if card.is_removal:
                p.stats.removal_used += 1
                opp_creatures = [
                    c
                    for c in sim.battlefield
                    if c.owner_id != pi and c.is_creature()
                ]
                if opp_creatures:
                    opp_creatures.sort(key=lambda c: -score_card(c, w))
                    killed = opp_creatures[0]
                    sim.battlefield = [
                        c for c in sim.battlefield if c.id != killed.id
                    ]
                    sim.players[killed.owner_id].graveyard.append(killed)
                    if events is not None:
                        events.append(f"Cast {card.name} (removal) — destroyed {killed.name}")
                else:
                    if events is not None:
                        events.append(f"Cast {card.name} (removal, no targets)")
                p.graveyard.append(card)

            elif card.is_board_wipe:
                p.stats.board_wipes_used += 1
                wiped = [c.name for c in sim.battlefield if c.is_creature()]
                surviving = []
                for c in sim.battlefield:
                    if c.is_creature():
                        sim.players[c.owner_id].graveyard.append(c)
                    else:
                        surviving.append(c)
                sim.battlefield = surviving
                p.graveyard.append(card)
                if events is not None:
                    events.append(f"Cast {card.name} (board wipe) — destroyed {len(wiped)} creatures")

            else:
                sim.battlefield.append(card)
                if card.is_creature():
                    p.stats.creatures_played += 1
                    if events is not None:
                        events.append(f"Cast {card.name} ({card.pt or 'creature'}) for {card.cmc} mana")
                elif card.is_ramp:
                    p.stats.ramp_played += 1
                    if events is not None:
                        events.append(f"Cast {card.name} (ramp) for {card.cmc} mana")
                else:
                    if events is not None:
                        events.append(f"Cast {card.name} for {card.cmc} mana")

            played += 1

            # Recalculate available mana for next spell
            available_mana = self._count_untapped_lands(sim, pi)

    def _resolve_combat(self, sim: SimState, pi: int, turn: int, events: list | None = None) -> None:
        """Resolve combat phase for a player."""
        p = sim.players[pi]
        opp_idx = 1 - pi
        opp = sim.players[opp_idx]
        w = self.weights

        if opp.eliminated:
            return

        # My creatures that can attack (not tapped, not summoning sick)
        my_creatures = [
            c
            for c in sim.battlefield
            if (
                c.owner_id == pi
                and c.is_creature()
                and not c.tapped
                and (turn > 0 or c.turn_played != turn)
            )
        ]
        if not my_creatures:
            return

        opp_blockers = [
            c
            for c in sim.battlefield
            if (
                c.owner_id == opp_idx
                and c.is_creature()
                and not c.tapped
            )
        ]

        # ── Decide attackers ──
        # Aggressive strategy: attack with most creatures.
        # Only hold back small creatures (power < 3) when opponent has
        # blockers that would profitably trade AND we have plenty of life.
        attackers = []
        total_my_power = sum(c.get_power() for c in my_creatures)
        for atk in my_creatures:
            a_pow = atk.get_power()
            a_tou = atk.get_toughness()
            has_flying = atk.has_keyword("flying")
            has_trample = atk.has_keyword("trample")
            has_haste = atk.has_keyword("haste")

            # Always attack with evasion, big creatures, or if opponent is low
            if has_flying or has_trample or has_haste or a_pow >= 3 or opp.life <= total_my_power:
                attackers.append(atk)
                atk.tapped = True
                continue

            # For small creatures, check if a profitable block exists
            can_die_profitably = any(
                (
                    (not has_flying or b.has_keyword("flying") or b.has_keyword("reach"))
                    and (b.get_power() >= a_tou or b.has_keyword("deathtouch"))
                    and b.get_toughness() > a_pow  # blocker survives = bad trade
                )
                for b in opp_blockers
            )
            # Attack unless we'd lose the creature for nothing AND we're healthy
            if not can_die_profitably or p.life > 25:
                attackers.append(atk)
                atk.tapped = True

        if events is not None and attackers:
            atk_names = [f"{a.name} ({a.pt})" for a in attackers]
            events.append(f"Attacks with: {', '.join(atk_names)}")

        # ── Blocking and damage ──
        total_damage = 0
        used_blockers: set[int] = set()
        combat_details: list[str] = []

        for atk in attackers:
            a_pow = atk.get_power()
            a_tou = atk.get_toughness()
            has_flying = atk.has_keyword("flying")

            valid_blockers = [
                b
                for b in opp_blockers
                if (
                    b.id not in used_blockers
                    and (not has_flying or b.has_keyword("flying") or b.has_keyword("reach"))
                )
            ]

            blocked = False
            if valid_blockers and not atk.has_keyword("menace"):
                # Try to find a blocker that survives
                blocker = next(
                    (b for b in valid_blockers if b.get_toughness() > a_pow),
                    None,
                )
                # If life is critical, chump block
                if blocker is None and opp.life <= a_pow * 2 and valid_blockers:
                    blocker = valid_blockers[0]

                if blocker:
                    used_blockers.add(blocker.id)
                    b_pow = blocker.get_power()
                    blocked = True

                    if events is not None:
                        combat_details.append(f"{atk.name} blocked by {blocker.name}")

                    # Attacker kills blocker?
                    if a_pow >= blocker.get_toughness() or atk.has_keyword("deathtouch"):
                        sim.battlefield = [
                            c for c in sim.battlefield if c.id != blocker.id
                        ]
                        sim.players[opp_idx].graveyard.append(blocker)
                        if events is not None:
                            combat_details.append(f"  {blocker.name} dies")

                    # Blocker kills attacker?
                    if b_pow >= a_tou or blocker.has_keyword("deathtouch"):
                        sim.battlefield = [
                            c for c in sim.battlefield if c.id != atk.id
                        ]
                        sim.players[pi].graveyard.append(atk)
                        if events is not None:
                            combat_details.append(f"  {atk.name} dies")

                    # Trample overflow
                    if atk.has_keyword("trample") and a_pow > blocker.get_toughness():
                        total_damage += a_pow - blocker.get_toughness()

                    # Lifelink
                    if atk.has_keyword("lifelink"):
                        p.life += min(a_pow, blocker.get_toughness())

            if not blocked:
                total_damage += a_pow
                if atk.has_keyword("lifelink"):
                    p.life += a_pow

        opp.life -= total_damage
        p.stats.damage_dealt += total_damage
        opp.stats.damage_received += total_damage

        if events is not None and total_damage > 0:
            events.append(f"Dealt {total_damage} combat damage to {opp.name} (now {opp.life} life)")
            events.extend(combat_details)

        if opp.life <= 0:
            opp.eliminated = True

    def _build_result(
        self,
        sim: SimState,
        final_turn: int,
        name_a: str,
        name_b: str,
    ) -> GameResult:
        """Determine winner and build result object."""
        pa = sim.players[0]
        pb = sim.players[1]

        if pa.eliminated and not pb.eliminated:
            winner = 1
        elif not pa.eliminated and pb.eliminated:
            winner = 0
        else:
            # Both alive or both dead: compare life
            winner = 0 if pa.life >= pb.life else 1

        return GameResult(
            winner=winner,
            turns=min(final_turn, sim.max_turns),
            player_a_name=name_a,
            player_a_life=pa.life,
            player_a_eliminated=pa.eliminated,
            player_a_stats=pa.stats,
            player_b_name=name_b,
            player_b_life=pb.life,
            player_b_eliminated=pb.eliminated,
            player_b_stats=pb.stats,
        )
