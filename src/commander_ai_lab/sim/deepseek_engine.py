"""
Commander AI Lab — DeepSeek-Enhanced Game Engine
=================================================
Extends the headless GameEngine so that one player (the AI opponent)
uses the DeepSeek LLM brain for decision-making instead of the static
heuristic scorer.

The LLM decides:
  1. Whether to play a land (and which one)
  2. Which spell(s) to cast (up to 2 per turn, same as base engine)
  3. Combat stance: attack_all, attack_safe, or hold

If the LLM is unreachable or times out, falls back to the base-engine
heuristic transparently.

Usage::

    from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine
    from commander_ai_lab.sim.deepseek_brain import DeepSeekBrain, DeepSeekConfig

    brain = DeepSeekBrain(DeepSeekConfig(api_base="http://192.168.0.122:1234"))
    brain.check_connection()
    engine = DeepSeekGameEngine(brain=brain, ai_player_index=1)
    result = engine.run(deck_a, deck_b, name_a="My Deck", name_b="DeepSeek AI")
"""

from __future__ import annotations

import logging
import random
import uuid
from typing import Optional

from commander_ai_lab.sim.models import Card, GameResult, Player, PlayerResult, PlayerStats, SimState
from commander_ai_lab.sim.rules import AI_DEFAULT_WEIGHTS, enrich_card, score_card
from commander_ai_lab.sim.deepseek_brain import DeepSeekBrain, DeepSeekConfig, build_deck_context

logger = logging.getLogger("deepseek_engine")


class DeepSeekGameEngine:
    """
    Headless Commander game engine with LLM-powered opponent.

    One player uses DeepSeek for decisions; the other uses the heuristic.
    Both players use the same core game mechanics (mana, combat, etc.)
    """

    def __init__(
        self,
        brain: DeepSeekBrain | None = None,
        ai_player_index: int = 1,      # Which player is the LLM AI (0 or 1)
        max_turns: int = 25,
        starting_life: int = 40,
        weights: Optional[dict] = None,
        record_log: bool = False,
        ml_log: bool = False,          # Capture ML decision snapshots
    ):
        self.brain = brain or DeepSeekBrain()
        self.ai_player_index = ai_player_index
        self.max_turns = max_turns
        self.starting_life = starting_life
        self.weights = weights or AI_DEFAULT_WEIGHTS
        self.record_log = record_log
        self.ml_log = ml_log
        self.ml_decisions: list[dict] = []  # Collected ML decision snapshots

    def run(
        self,
        deck_a: list[Card],
        deck_b: list[Card],
        name_a: str = "Player A",
        name_b: str = "Player B",
        game_id: str | None = None,
        archetype: str = "midrange",
        commander_name: str = "",
        color_identity: list[str] | None = None,
        win_rate: float | None = None,
    ) -> GameResult:
        """Run a single game. The AI player uses DeepSeek for decisions."""
        sim = self._create_state(deck_a, deck_b, name_a, name_b)
        game_log: list[dict] = []
        gid = game_id or str(uuid.uuid4())[:12]
        turn_decisions: list[dict] = []  # raw (snapshot, action_type) pairs

        # Build deck intelligence context once at game start
        ai_deck = deck_b if self.ai_player_index == 1 else deck_a
        self._deck_context = build_deck_context(
            full_deck=ai_deck,
            commander_name=commander_name,
            color_identity=color_identity,
            archetype=archetype,
            win_rate=win_rate,
        )

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
                    drawn = p.library[-1]
                    p.hand.append(p.library.pop())
                    p.stats.cards_drawn += 1
                    if self.record_log:
                        phase_events.append(f"Drew {drawn.name}")

                # ── Capture ML snapshot BEFORE the turn (state before action) ──
                pre_snapshot = None
                if self.ml_log:
                    pre_snapshot = self._capture_ml_snapshot(sim, pi, turn)

                # ── Decide: LLM or Heuristic? ──
                action_type = "pass"  # default
                if pi == self.ai_player_index and self.brain._connected:
                    action_type = self._play_turn_deepseek(sim, pi, turn, phase_events, getattr(self, '_deck_context', None))
                else:
                    action_type = self._play_turn_heuristic(sim, pi, turn, phase_events)

                # ── Record ML decision snapshot ──
                if self.ml_log and pre_snapshot is not None:
                    pre_snapshot["action"] = {"type": action_type}
                    pre_snapshot["game_id"] = gid
                    pre_snapshot["archetype"] = archetype
                    turn_decisions.append(pre_snapshot)

                # ── Track board size ──
                board_size = len(sim.get_battlefield(pi))
                if board_size > p.stats.max_board_size:
                    p.stats.max_board_size = board_size

                # ── Untap ──
                for c in sim.get_battlefield(pi):
                    c.tapped = False

                if self.record_log:
                    turn_entry["phases"].append({
                        "player": p.name,
                        "playerId": pi,
                        "events": phase_events,
                        "lifeAfter": {
                            sim.players[0].name: sim.players[0].life,
                            sim.players[1].name: sim.players[1].life,
                        },
                        "boardA": [c.name for c in sim.get_battlefield(0) if c.is_creature()],
                        "boardB": [c.name for c in sim.get_battlefield(1) if c.is_creature()],
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

        # Stamp game outcome on all ML decisions and add to engine collection
        if self.ml_log and turn_decisions:
            outcome = "win" if result.winner == 0 else "loss" if result.winner == 1 else "draw"
            for td in turn_decisions:
                td["game_outcome"] = outcome
            self.ml_decisions.extend(turn_decisions)

        # Flush decision log at end of game
        if self.brain.config.log_decisions and self.brain._decision_log:
            try:
                self.brain.flush_log()
            except Exception as e:
                logger.warning("Failed to flush decision log: %s", e)

        return result

    # ──────────────────────────────────────────────────────────
    # DeepSeek-powered turn
    # ──────────────────────────────────────────────────────────

    def _play_turn_deepseek(
        self, sim: SimState, pi: int, turn: int, events: list[str],
        deck_context: dict | None = None,
    ) -> str:
        """
        Execute a full turn for the AI player using DeepSeek decisions.

        The LLM gets called once per turn. Based on its action, we execute
        the appropriate game mechanics using the existing engine helpers.
        Multiple actions are possible per turn (land + spell + combat).

        Returns: ML action type string for decision logging.
        """
        p = sim.players[pi]
        available_mana = self._count_untapped_lands(sim, pi)

        # Ask DeepSeek what to do — with full deck intelligence
        decision = self.brain.choose_action(sim, pi, turn, available_mana, deck_context=deck_context)
        action = decision.get("action", "hold")
        target_card_name = decision.get("target_card", "")
        reasoning = decision.get("reasoning", "")
        source = decision.get("source", "?")

        if self.record_log:
            events.append(f"[AI Brain: {source}] Action: {action} "
                         f"{'→ ' + target_card_name if target_card_name else ''} "
                         f"({reasoning})")

        # ── Phase 1: Land drop ──
        # Always try to play a land (even if LLM didn't say "play_land")
        self._play_land(sim, pi, target_card_name if action == "play_land" else None, events)

        # Recalculate mana after land drop
        available_mana = self._count_untapped_lands(sim, pi)

        # ── Phase 2: Cast spells (up to 2) based on LLM action ──
        if action in ("cast_creature", "cast_removal", "cast_board_wipe",
                       "cast_ramp", "cast_spell"):
            self._play_spells_targeted(
                sim, pi, available_mana, action, target_card_name, events
            )
        elif action != "hold":
            # For attack actions or unknowns, still try to cast something first
            self._play_spells_heuristic(sim, pi, available_mana, events)

        # ── Phase 3: Combat ──
        if action in ("attack_all", "attack_safe"):
            self._resolve_combat_deepseek(sim, pi, turn, action, events)
        elif action == "hold":
            # LLM chose to hold — no combat
            if self.record_log:
                events.append("Holds — no attack")
        else:
            # Default: still attack if we have creatures and it makes sense
            self._resolve_combat_heuristic(sim, pi, turn, events)

        # Map DeepSeek action to ML macro-action type for training data
        return self._map_action_to_ml_type(action, available_mana)

    # ──────────────────────────────────────────────────────────
    # Heuristic turn (for human player or fallback)
    # ──────────────────────────────────────────────────────────

    def _play_turn_heuristic(
        self, sim: SimState, pi: int, turn: int, events: list[str]
    ) -> str:
        """Standard heuristic turn (same as base GameEngine). Returns ML action type."""
        # Land drop
        self._play_land(sim, pi, None, events)

        # Available mana
        available_mana = self._count_untapped_lands(sim, pi)

        # Play spells
        played_spell = self._play_spells_heuristic(sim, pi, available_mana, events)

        # Combat
        attacked = self._resolve_combat_heuristic(sim, pi, turn, events)

        # Determine the primary action for ML logging
        if attacked:
            return "attack"
        elif played_spell:
            return "cast"  # generic cast — labeler uses card name to classify
        elif available_mana >= 2:
            return "hold"
        else:
            return "pass"

    # ──────────────────────────────────────────────────────────
    # Land drop
    # ──────────────────────────────────────────────────────────

    def _play_land(
        self, sim: SimState, pi: int,
        preferred_name: str | None, events: list[str] | None
    ):
        """Play a land from hand. If preferred_name given, try that first."""
        p = sim.players[pi]
        land_idx = -1

        if preferred_name:
            # Try to find the preferred land
            for i, card in enumerate(p.hand):
                if card.is_land() and card.name.lower() == preferred_name.lower():
                    land_idx = i
                    break

        if land_idx == -1:
            # Fall back to first available land
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

        if events is not None and self.record_log:
            events.append(f"Played land: {land_card.name}")

    # ──────────────────────────────────────────────────────────
    # Spell casting — targeted (LLM-directed)
    # ──────────────────────────────────────────────────────────

    def _play_spells_targeted(
        self, sim: SimState, pi: int, available_mana: int,
        action: str, target_card_name: str, events: list[str] | None
    ):
        """
        Cast spells based on LLM's action choice.
        Tries the target card first, then fills with heuristic picks.
        Up to 2 spells per turn.
        """
        p = sim.players[pi]
        w = self.weights
        played = 0

        # Try to cast the LLM's target card first
        if target_card_name:
            target_idx = -1
            for i, card in enumerate(p.hand):
                if (not card.is_land()
                    and card.name.lower() == target_card_name.lower()
                    and (card.cmc or 0) <= available_mana):
                    target_idx = i
                    break

            if target_idx >= 0:
                card = p.hand.pop(target_idx)
                available_mana = self._cast_spell(sim, pi, card, available_mana, events)
                played += 1

        # Fill remaining spell slots with heuristic
        if played < 2:
            played += self._play_spells_heuristic_inner(
                sim, pi, available_mana, events, max_spells=2 - played
            )

    def _play_spells_heuristic(
        self, sim: SimState, pi: int, available_mana: int, events: list[str] | None
    ) -> bool:
        """Play up to 2 spells using heuristic scoring. Returns True if any spell was played."""
        return self._play_spells_heuristic_inner(sim, pi, available_mana, events, max_spells=2) > 0

    def _play_spells_heuristic_inner(
        self, sim: SimState, pi: int, available_mana: int,
        events: list[str] | None, max_spells: int = 2
    ) -> int:
        """Core heuristic spell casting. Returns number of spells played."""
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
        while playable and played < max_spells:
            _, _, best_card = playable.pop(0)
            hand_pos = -1
            for i, c in enumerate(p.hand):
                if c is best_card:
                    hand_pos = i
                    break
            if hand_pos == -1:
                continue

            card = p.hand.pop(hand_pos)
            available_mana = self._cast_spell(sim, pi, card, available_mana, events)
            played += 1

            # Recalculate available mana
            available_mana = self._count_untapped_lands(sim, pi)

        return played

    # ──────────────────────────────────────────────────────────
    # Spell resolution (shared)
    # ──────────────────────────────────────────────────────────

    def _cast_spell(
        self, sim: SimState, pi: int, card: Card,
        available_mana: int, events: list[str] | None
    ) -> int:
        """
        Resolve a single spell cast. Returns remaining mana.
        Handles removal, board wipes, creatures, ramp, and other spells.
        """
        p = sim.players[pi]
        w = self.weights

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

        # Handle removal
        if card.is_removal:
            p.stats.removal_used += 1
            opp_idx_r = 1 - pi
            opp_creatures = [
                c for c in sim.get_battlefield(opp_idx_r)
                if c.is_creature()
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

        return self._count_untapped_lands(sim, pi)

    # ──────────────────────────────────────────────────────────
    # Combat — DeepSeek directed
    # ──────────────────────────────────────────────────────────

    def _resolve_combat_deepseek(
        self, sim: SimState, pi: int, turn: int,
        attack_mode: str, events: list[str] | None
    ):
        """
        Resolve combat based on LLM's attack choice.
        attack_all: send everything
        attack_safe: only evasive/large creatures
        """
        p = sim.players[pi]
        opp_idx = 1 - pi
        opp = sim.players[opp_idx]

        if opp.eliminated:
            return

        my_creatures = [
            c for c in sim.get_battlefield(pi)
            if c.is_creature() and not c.tapped
            and (turn > 0 or c.turn_played != turn)
        ]
        if not my_creatures:
            return

        opp_blockers = [
            c for c in sim.get_battlefield(opp_idx)
            if c.is_creature() and not c.tapped
        ]

        # Select attackers based on LLM's preference
        attackers = []
        if attack_mode == "attack_all":
            attackers = my_creatures[:]
        elif attack_mode == "attack_safe":
            # Only evasive (flying, trample, menace) or large (power >= 4)
            for atk in my_creatures:
                if (atk.has_keyword("flying") or atk.has_keyword("trample")
                        or atk.has_keyword("menace") or atk.get_power() >= 4):
                    attackers.append(atk)

        for atk in attackers:
            atk.tapped = True

        if events is not None and attackers:
            mode_label = "all-in" if attack_mode == "attack_all" else "safe"
            atk_names = [f"{a.name} ({a.pt})" for a in attackers]
            events.append(f"Attacks ({mode_label}): {', '.join(atk_names)}")

        # Resolve blocking and damage (same logic as base engine)
        self._resolve_damage(sim, pi, attackers, opp_blockers, turn, events)

    def _resolve_combat_heuristic(
        self, sim: SimState, pi: int, turn: int, events: list[str] | None
    ) -> bool:
        """Heuristic combat (same as base GameEngine._resolve_combat). Returns True if attacked."""
        p = sim.players[pi]
        opp_idx = 1 - pi
        opp = sim.players[opp_idx]

        if opp.eliminated:
            return False

        my_creatures = [
            c for c in sim.get_battlefield(pi)
            if c.is_creature() and not c.tapped
            and (turn > 0 or c.turn_played != turn)
        ]
        if not my_creatures:
            return False

        opp_blockers = [
            c for c in sim.get_battlefield(opp_idx)
            if c.is_creature() and not c.tapped
        ]

        # Same attacker selection as base engine
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
            events.append(f"Attacks with: {', '.join(atk_names)}")

        self._resolve_damage(sim, pi, attackers, opp_blockers, turn, events)
        return len(attackers) > 0

    # ──────────────────────────────────────────────────────────
    # Damage resolution (shared by both combat modes)
    # ──────────────────────────────────────────────────────────

    def _resolve_damage(
        self, sim: SimState, pi: int,
        attackers: list[Card], opp_blockers: list[Card],
        turn: int, events: list[str] | None
    ):
        """Resolve blocking and combat damage."""
        p = sim.players[pi]
        opp_idx = 1 - pi
        opp = sim.players[opp_idx]
        w = self.weights

        total_damage = 0
        used_blockers: set[int] = set()
        combat_details: list[str] = []

        for atk in attackers:
            a_pow = atk.get_power()
            a_tou = atk.get_toughness()
            has_flying = atk.has_keyword("flying")

            valid_blockers = [
                b for b in opp_blockers
                if b.id not in used_blockers
                and (not has_flying or b.has_keyword("flying") or b.has_keyword("reach"))
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

        if opp.life <= 0:
            opp.eliminated = True

    # ──────────────────────────────────────────────────────────
    # Shared helpers
    # ──────────────────────────────────────────────────────────

    # ──────────────────────────────────────────────────────────
    # ML Decision Snapshot Capture
    # ──────────────────────────────────────────────────────────

    def _capture_ml_snapshot(self, sim: SimState, pi: int, turn: int) -> dict:
        """
        Capture the current game state in the format expected by the ML
        training pipeline (dataset_builder → state_encoder → labeler).

        Returns a dict compatible with ml-decisions-*.jsonl format.
        """
        players_data = []
        for seat in range(2):
            p = sim.players[seat]
            # Count creatures and lands on battlefield
            seat_bf = sim.get_battlefield(seat)
            my_creatures = sum(
                1 for c in seat_bf
                if c.is_creature()
            )
            my_lands = sum(
                1 for c in seat_bf
                if c.is_land()
            )
            available_mana = sum(
                1 for c in seat_bf
                if not c.tapped and c.is_land()
            )

            # Card name lists for zones (for embedding lookup)
            hand_names = [c.name for c in p.hand]
            graveyard_names = [c.name for c in p.graveyard]
            battlefield_names = [
                c.name for c in seat_bf
                if not c.is_land()
            ]
            # Command zone — not explicitly tracked in Python sim, use empty
            command_zone_names = []

            players_data.append({
                "seat": seat,
                "life": p.life,
                "mana": available_mana,
                "cmdr_dmg": 0,      # Not tracked in Python sim
                "cmdr_tax": 0,      # Not tracked in Python sim
                "creatures": my_creatures,
                "lands": my_lands,
                "hand": hand_names,
                "graveyard": graveyard_names,
                "battlefield": battlefield_names,
                "command_zone": command_zone_names,
            })

        # Determine game phase — Python sim is simplified, treat as main_1
        phase = "main_1"

        return {
            "phase": phase,
            "active_seat": pi,
            "turn": turn + 1,
            "players": players_data,
            # game_id, game_outcome, archetype, action are set by caller
        }

    @staticmethod
    def _map_action_to_ml_type(deepseek_action: str, mana_available: int = 0) -> str:
        """
        Map a DeepSeek brain action string to an ML labeler-compatible
        action type string.
        """
        mapping = {
            "cast_creature": "cast",
            "cast_removal": "cast",
            "cast_board_wipe": "cast",
            "cast_ramp": "cast",
            "cast_spell": "cast",
            "play_land": "land",
            "attack_all": "attack",
            "attack_safe": "attack",
            "cast_commander": "cast_commander",
        }
        ml_type = mapping.get(deepseek_action)
        if ml_type:
            return ml_type
        # hold / unknown
        if deepseek_action == "hold" and mana_available >= 2:
            return "hold"
        return "pass"

    def flush_ml_decisions(self) -> list[dict]:
        """Return and clear collected ML decisions."""
        decisions = self.ml_decisions[:]
        self.ml_decisions.clear()
        return decisions

    def _count_untapped_lands(self, sim: SimState, pi: int) -> int:
        return sum(
            1 for c in sim.get_battlefield(pi)
            if not c.tapped and c.is_land()
        )

    def _create_state(
        self, deck_a: list[Card], deck_b: list[Card],
        name_a: str, name_b: str,
    ) -> SimState:
        sim = SimState(max_turns=self.max_turns)
        for idx, (deck, name) in enumerate([(deck_a, name_a), (deck_b, name_b)]):
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

    def _build_result(
        self, sim: SimState, final_turn: int,
        name_a: str, name_b: str,
    ) -> GameResult:
        pa = sim.players[0]
        pb = sim.players[1]

        if pa.eliminated and not pb.eliminated:
            winner = 1
        elif not pa.eliminated and pb.eliminated:
            winner = 0
        else:
            winner = 0 if pa.life >= pb.life else 1

        player_results = []
        for seat, p in enumerate(sim.players):
            player_results.append(PlayerResult(
                seat_index=seat,
                name=p.name,
                life=p.life,
                eliminated=p.eliminated,
                finish_position=1 if seat == winner else 2,
                stats=p.stats,
            ))

        return GameResult(
            winner_seat=winner,
            turns=min(final_turn, sim.max_turns),
            players=player_results,
        )
