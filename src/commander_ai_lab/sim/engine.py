"""
Commander AI Lab — Headless Game Engine
=========================================
A headless Commander game simulator for Monte Carlo analysis.
Faithful port of dtSimGame() / dtCreatePlayer() from mtg-commander-lan.

Supports 2–4 player Commander pods (N-player).
  - Draw, land drop, spell casting (up to 2 per turn)
  - AI card scoring for play priority
  - Simplified combat with flying, trample, deathtouch, lifelink, menace, reach
  - Creature removal and board wipe handling
  - Win by elimination (life <= 0) or life comparison at max turns
  - Multiplayer threat targeting: attacks and removal target highest-threat opponent
"""

from __future__ import annotations

import random
from typing import Optional

from commander_ai_lab.sim.models import (
    Card,
    GameResult,
    Player,
    PlayerResult,
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
    Headless Commander game engine — supports 2–4 player pods.

    2-player usage (backward-compatible)::

        engine = GameEngine(max_turns=25)
        result = engine.run(deck_a, deck_b, name_a="Deck A", name_b="Deck B")

    N-player usage::

        result = engine.run_pod(
            decks=[deck_a, deck_b, deck_c, deck_d],
            names=["Alice", "Bob", "Carol", "Dave"],
        )
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
        """Run a 1v1 headless game. Backward-compatible wrapper around run_pod()."""
        return self.run_pod(decks=[deck_a, deck_b], names=[name_a, name_b])

    def run_pod(
        self,
        decks: list[list[Card]],
        names: Optional[list[str]] = None,
    ) -> GameResult:
        """Run an N-player pod game (2–4 players) and return the result."""
        if not decks or len(decks) < 2:
            raise ValueError("run_pod requires at least 2 decks")
        if names is None:
            names = [f"Player {chr(65 + i)}" for i in range(len(decks))]
        if len(names) != len(decks):
            raise ValueError("len(names) must equal len(decks)")

        sim = self._create_state(decks, names)
        game_log: list[dict] = []
        # Track elimination order: first eliminated = highest finish_position number
        sim.elimination_order: list[int] = []  # seat indices in elimination order

        final_turn = 0
        for turn in range(sim.max_turns):
            sim.turn = turn
            turn_entry = {"turn": turn + 1, "phases": []}

            for pi in range(len(sim.players)):
                p = sim.players[pi]
                if p.eliminated:
                    continue
                p.stats.turns_alive += 1
                phase_events: list[str] = []

                # ── Draw ──
                if p.library:
                    drawn = p.library[-1]
                    p.hand.append(p.library.pop())
                    p.stats.cards_drawn += 1
                    if self.record_log:
                        phase_events.append(f"Drew {drawn.name}")

                # ── Land drop ──
                land_before = p.stats.lands_played
                self._play_land(sim, pi)
                if self.record_log and p.stats.lands_played > land_before:
                    last_land = next(
                        (c for c in reversed(sim.get_battlefield(pi)) if c.is_land()),
                        None,
                    )
                    if last_land:
                        phase_events.append(f"Played land: {last_land.name}")

                # ── Available mana ──
                available_mana = self._count_untapped_lands(sim, pi)

                # ── Play spells (up to 2) ──
                self._play_spells(sim, pi, available_mana, phase_events if self.record_log else None)

                # ── Track board size ──
                board_size = len(sim.get_battlefield(pi))
                if board_size > p.stats.max_board_size:
                    p.stats.max_board_size = board_size

                # ── Combat ──
                self._resolve_combat(sim, pi, turn, phase_events if self.record_log else None)

                # ── Check for new eliminations after combat ──
                for opp_idx, opp in enumerate(sim.players):
                    if not opp.eliminated and opp.life <= 0:
                        opp.eliminated = True
                        sim.elimination_order.append(opp_idx)
                        if self.record_log:
                            phase_events.append(f"{opp.name} eliminated!")

                # ── Untap ──
                for c in sim.get_battlefield(pi):
                    c.tapped = False

                if self.record_log:
                    life_snapshot = {sim.players[s].name: sim.players[s].life
                                     for s in range(len(sim.players))}
                    boards = {f"board_{s}": [c.name for c in sim.get_battlefield(s) if c.is_creature()]
                              for s in range(len(sim.players))}
                    turn_entry["phases"].append({
                        "player": p.name,
                        "playerId": pi,
                        "events": phase_events,
                        "lifeAfter": life_snapshot,
                        **boards,
                    })

            alive = [p for p in sim.players if not p.eliminated]
            final_turn = turn + 1
            if self.record_log:
                game_log.append(turn_entry)
            if len(alive) <= 1:
                break

        # Mark any remaining alive players as not-eliminated (they survived)
        result = self._build_result(sim, final_turn)
        if self.record_log:
            result.game_log = game_log
        return result

    # ──────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────

    def _create_state(
        self,
        decks: list[list[Card]],
        names: list[str],
    ) -> SimState:
        """Create initial simulation state for N players."""
        sim = SimState(max_turns=self.max_turns)

        for idx, (deck, name) in enumerate(zip(decks, names)):
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

        sim.init_battlefields(len(sim.players))
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
        sim.add_to_battlefield(pi, land_card)
        p.stats.lands_played += 1

    def _count_untapped_lands(self, sim: SimState, pi: int) -> int:
        """Count untapped lands for a player."""
        return sum(
            1
            for c in sim.get_battlefield(pi)
            if not c.tapped and c.is_land()
        )

    def _pick_removal_target_seat(self, sim: SimState, pi: int) -> int:
        """Pick the best opponent seat to target with removal.

        Returns the seat index of the alive opponent with the highest-value
        creature on the battlefield. Falls back to any alive opponent.
        """
        w = self.weights
        best_seat = -1
        best_score = -1
        for opp_idx, opp in enumerate(sim.players):
            if opp_idx == pi or opp.eliminated:
                continue
            top_creature = max(
                (c for c in sim.get_battlefield(opp_idx) if c.is_creature()),
                key=lambda c: score_card(c, w),
                default=None,
            )
            if top_creature is not None:
                s = score_card(top_creature, w)
                if s > best_score:
                    best_score = s
                    best_seat = opp_idx
        if best_seat == -1:
            # No creatures anywhere — return first alive opponent
            for opp_idx, opp in enumerate(sim.players):
                if opp_idx != pi and not opp.eliminated:
                    return opp_idx
        return best_seat

    def _pick_attack_target_seat(self, sim: SimState, pi: int) -> int:
        """Pick the best opponent seat to attack.

        Targets the alive opponent with the highest total board power
        (i.e. biggest threat). If tied or no creatures, targets the
        opponent with the lowest life (most vulnerable).
        """
        alive_opps = [
            (opp_idx, opp)
            for opp_idx, opp in enumerate(sim.players)
            if opp_idx != pi and not opp.eliminated
        ]
        if not alive_opps:
            return -1
        # Score by: total opponent board power (threat) then lowest life (vulnerability)
        def threat_key(entry):
            opp_idx, opp = entry
            board_power = sum(
                c.get_power() for c in sim.get_battlefield(opp_idx) if c.is_creature()
            )
            return (board_power, -opp.life)

        target_idx, _ = max(alive_opps, key=threat_key)
        return target_idx

    def _play_spells(self, sim: SimState, pi: int, available_mana: int, events: list | None = None) -> None:
        """Play up to 2 spells from hand, prioritized by AI score."""
        p = sim.players[pi]
        w = self.weights

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
            for bf_card in sim.get_battlefield(pi):
                if mana_needed <= 0:
                    break
                if not bf_card.tapped and bf_card.is_land():
                    bf_card.tapped = True
                    mana_needed -= 1

            p.stats.mana_spent += card.cmc or 0
            p.stats.spells_cast += 1

            if card.is_removal:
                p.stats.removal_used += 1
                # N-player: target highest-value opponent creature
                target_seat = self._pick_removal_target_seat(sim, pi)
                if target_seat != -1:
                    opp_creatures = [
                        c for c in sim.get_battlefield(target_seat) if c.is_creature()
                    ]
                    if opp_creatures:
                        opp_creatures.sort(key=lambda c: -score_card(c, w))
                        killed = opp_creatures[0]
                        sim.remove_from_battlefield(killed.id)
                        sim.players[killed.owner_id].graveyard.append(killed)
                        if events is not None:
                            events.append(f"Cast {card.name} (removal) — destroyed {killed.name}")
                    else:
                        if events is not None:
                            events.append(f"Cast {card.name} (removal, no targets)")
                else:
                    if events is not None:
                        events.append(f"Cast {card.name} (removal, no targets)")
                p.graveyard.append(card)

            elif card.is_board_wipe:
                p.stats.board_wipes_used += 1
                wiped_names = []
                for seat_idx in range(len(sim.players)):
                    bf = sim.get_battlefield(seat_idx)
                    keep = []
                    for c in bf:
                        if c.is_creature():
                            wiped_names.append(c.name)
                            sim.players[c.owner_id].graveyard.append(c)
                        else:
                            keep.append(c)
                    sim.battlefields[seat_idx] = keep
                p.graveyard.append(card)
                if events is not None:
                    events.append(f"Cast {card.name} (board wipe) — destroyed {len(wiped_names)} creatures")

            else:
                sim.add_to_battlefield(pi, card)
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
            available_mana = self._count_untapped_lands(sim, pi)

    def _resolve_combat(self, sim: SimState, pi: int, turn: int, events: list | None = None) -> None:
        """Resolve combat phase: attacker targets the highest-threat alive opponent."""
        p = sim.players[pi]
        w = self.weights

        # N-player: pick target opponent by threat level
        opp_idx = self._pick_attack_target_seat(sim, pi)
        if opp_idx == -1:
            return
        opp = sim.players[opp_idx]

        # My creatures that can attack (not tapped, not summoning sick)
        my_creatures = [
            c
            for c in sim.get_battlefield(pi)
            if (
                c.is_creature()
                and not c.tapped
                and (turn > 0 or c.turn_played != turn)
            )
        ]
        if not my_creatures:
            return

        opp_blockers = [
            c
            for c in sim.get_battlefield(opp_idx)
            if c.is_creature() and not c.tapped
        ]

        # ── Decide attackers ──
        attackers = []
        total_my_power = sum(c.get_power() for c in my_creatures)
        for atk in my_creatures:
            a_pow = atk.get_power()
            a_tou = atk.get_toughness()
            has_flying = atk.has_keyword("flying")
            has_trample = atk.has_keyword("trample")
            has_haste = atk.has_keyword("haste")

            if has_flying or has_trample or has_haste or a_pow >= 3 or opp.life <= total_my_power:
                attackers.append(atk)
                atk.tapped = True
                continue

            can_die_profitably = any(
                (
                    (not has_flying or b.has_keyword("flying") or b.has_keyword("reach"))
                    and (b.get_power() >= a_tou or b.has_keyword("deathtouch"))
                    and b.get_toughness() > a_pow
                )
                for b in opp_blockers
            )
            if not can_die_profitably or p.life > 25:
                attackers.append(atk)
                atk.tapped = True

        if events is not None and attackers:
            atk_names = [f"{a.name} ({a.pt})" for a in attackers]
            events.append(f"Attacks {opp.name} with: {', '.join(atk_names)}")

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
                blocker = next(
                    (b for b in valid_blockers if b.get_toughness() > a_pow),
                    None,
                )
                if blocker is None and opp.life <= a_pow * 2 and valid_blockers:
                    blocker = valid_blockers[0]

                if blocker:
                    used_blockers.add(blocker.id)
                    b_pow = blocker.get_power()
                    blocked = True

                    if events is not None:
                        combat_details.append(f"{atk.name} blocked by {blocker.name}")

                    if a_pow >= blocker.get_toughness() or atk.has_keyword("deathtouch"):
                        sim.remove_from_battlefield(blocker.id)
                        sim.players[opp_idx].graveyard.append(blocker)
                        if events is not None:
                            combat_details.append(f"  {blocker.name} dies")

                    if b_pow >= a_tou or blocker.has_keyword("deathtouch"):
                        sim.remove_from_battlefield(atk.id)
                        sim.players[pi].graveyard.append(atk)
                        if events is not None:
                            combat_details.append(f"  {atk.name} dies")

                    if atk.has_keyword("trample") and a_pow > blocker.get_toughness():
                        total_damage += a_pow - blocker.get_toughness()

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

    def _build_result(self, sim: SimState, final_turn: int) -> GameResult:
        """Determine winner and assign finish positions for all N players."""
        num_players = len(sim.players)
        elimination_order = getattr(sim, "elimination_order", [])

        # Players still alive at end of game — determine winner by life total
        alive = [p for p in sim.players if not p.eliminated]

        if not alive:
            # Edge case: everyone eliminated (e.g. simultaneous lethal)
            winner_seat = -1
        elif len(alive) == 1:
            winner_seat = alive[0].owner_id
        else:
            # Multiple players survived max_turns — highest life wins
            winner_seat = max(
                (p.owner_id for p in alive),
                key=lambda idx: sim.players[idx].life,
            )

        # Build finish positions:
        # 1st = winner, then survivors ordered by life (desc), then eliminated in reverse order
        # (last eliminated = best finish among eliminated)
        survivor_seats = sorted(
            [p.owner_id for p in alive if p.owner_id != winner_seat],
            key=lambda idx: -sim.players[idx].life,
        )
        # elimination_order[0] = first out = worst finish
        # Finish positions: winner=1, survivors=2..k, eliminated reversed
        finish: dict[int, int] = {winner_seat: 1}
        pos = 2
        for seat in survivor_seats:
            finish[seat] = pos
            pos += 1
        for seat in reversed(elimination_order):
            if seat not in finish:
                finish[seat] = pos
                pos += 1
        # Any remaining (shouldn't happen, but safety)
        for seat in range(num_players):
            if seat not in finish:
                finish[seat] = pos
                pos += 1

        player_results = [
            PlayerResult(
                seat_index=seat,
                name=sim.players[seat].name,
                life=sim.players[seat].life,
                eliminated=sim.players[seat].eliminated,
                finish_position=finish.get(seat, num_players),
                stats=sim.players[seat].stats,
            )
            for seat in range(num_players)
        ]

        return GameResult(
            winner_seat=winner_seat,
            turns=min(final_turn, sim.max_turns),
            players=player_results,
        )
