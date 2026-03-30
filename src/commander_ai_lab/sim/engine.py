"""
Commander AI Lab — Headless Game Engine
=========================================
A headless Commander game simulator for Monte Carlo analysis.
Faithful port of dtSimGame() / dtCreatePlayer() from mtg-commander-lan.

N-player ready: accepts 2–4 decks and runs a full multiplayer game.
Simulates simplified Commander games:
  - Draw, land drop, spell casting (up to 2 per turn)
  - AI card scoring for play priority
  - Simplified combat with flying, trample, deathtouch, lifelink, menace, reach
  - Multiplayer attack targeting: weakest non-eliminated opponent heuristic
  - Creature removal and board wipe handling
  - Win by elimination (life <= 0) or life comparison at max turns
  - Elimination order tracking for N-player finish positions

Weights are loaded automatically from learned_weights.json (if present)
via load_weights(), so simulation-trained weights take effect without any
code changes. Pass explicit weights= to override.
"""

from __future__ import annotations

import logging
import random
import uuid
from typing import Optional

from commander_ai_lab.sim.models import (
  Card,
    CombatState,
  GameResult,
  Phase,
  PHASE_ORDER,
  Player,
  PlayerResult,
  PlayerStats,
  SORCERY_PHASES,
  SimState,
)
from commander_ai_lab.sim.rules import (
  AI_DEFAULT_WEIGHTS,
  enrich_card,
  load_weights,
  score_card,
)

logger = logging.getLogger("engine")


class GameEngine:
  """
  Headless Commander game engine (N-player ready).

  Usage::

      engine = GameEngine(max_turns=25)
      # 2-player (backward-compatible)
      result = engine.run(deck_a, deck_b, name_a="Deck A", name_b="Deck B")
      # 4-player
      result = engine.run_n(decks=[d1, d2, d3, d4], names=["A","B","C","D"])

  Weights are loaded from learned_weights.json automatically. Pass
  ``weights`` explicitly to override (e.g. for A/B testing).
  """

  # London mulligan: max times a player may mulligan before forced keep
  MAX_MULLIGANS = 4

  def __init__(
    self,
    max_turns: int = 25,
    starting_life: int = 40,
    weights: Optional[dict] = None,
    record_log: bool = False,
    ml_log: bool = False,
    mulligan_rule: str = "london",
  ):
    self.max_turns = max_turns
    self.starting_life = starting_life
    # Auto-load learned weights; caller can override by passing weights=
    self.weights = weights if weights is not None else load_weights()
    self.record_log = record_log
    self.ml_log = ml_log
    self.ml_decisions: list[dict] = []
    self.mulligan_rule = mulligan_rule

  # ──────────────────────────────────────────────────────────
  # Public API
  # ──────────────────────────────────────────────────────────

  def run(
    self,
    deck_a: list[Card],
    deck_b: list[Card],
    name_a: str = "Player A",
    name_b: str = "Player B",
    commander_names: list[str] | None = None,
  ) -> GameResult:
    """Backward-compatible 2-player entry point."""
    return self.run_n(
      decks=[deck_a, deck_b],
      names=[name_a, name_b],
      commander_names=commander_names,
    )

  def run_n(
    self,
    decks: list[list[Card]],
    names: list[str] | None = None,
    commander_names: list[str] | None = None,
    game_id: str | None = None,
    archetype: str = "midrange",
  ) -> GameResult:
    """Run a single headless N-player game and return the result."""
    n = len(decks)
    if names is None:
      names = [f"Player {chr(65 + i)}" for i in range(n)]
    sim = self._create_state(decks, names, commander_names=commander_names)
    game_log: list[dict] = []
    elimination_order: list[int] = []  # seats in order of elimination
    gid = game_id or str(uuid.uuid4())[:12]
    turn_decisions: list[dict] = []
    final_turn = 0

    for turn in range(sim.max_turns):
      sim.turn = turn
      turn_entry = {"turn": turn + 1, "phases": []}

      for pi in range(len(sim.players)):
        p = sim.players[pi]
        if p.eliminated:
          continue
        p.stats.turns_alive += 1
        sim.active_player_index = pi
        phase_events: list[str] = []

        # ── Capture ML snapshot BEFORE turn actions ──
        pre_snapshot = None
        if self.ml_log:
          pre_snapshot = self._capture_ml_snapshot(sim, pi, turn)

        # Track spell/damage counts for ML logging
        spells_before = p.stats.spells_cast
        damage_before_turn = p.stats.damage_dealt
        spells_budget = 2  # shared across main1 + main2

        # ── Walk each phase in order ──
        for phase in PHASE_ORDER:
          sim.current_phase = phase

          if phase == Phase.UNTAP:
            for c in sim.get_battlefield(pi):
              c.tapped = False
              c.damage_marked = 0  # MTG rule 514.2

          elif phase == Phase.UPKEEP:
            pass  # placeholder — triggers would fire here

          elif phase == Phase.DRAW:
            if p.library:
              drawn = p.library[-1]
              p.hand.append(p.library.pop())
              p.stats.cards_drawn += 1
              if self.record_log:
                phase_events.append(f"Drew {drawn.name}")

          elif phase == Phase.MAIN1:
            # Land drop (only in main1, per MTG convention)
            land_before = p.stats.lands_played
            self._play_land(sim, pi)
            played_land = p.stats.lands_played > land_before
            if self.record_log and played_land:
              last_land = next(
                (c for c in reversed(sim.get_battlefield(pi))
                 if c.is_land()),
                None,
              )
              if last_land:
                phase_events.append(f"Played land: {last_land.name}")

            # Play spells (shared budget across main1 + main2)
            available_mana = self._count_untapped_lands(sim, pi)
            cast = self._play_spells(
              sim, pi, available_mana,
              phase_events if self.record_log else None,
              max_spells=spells_budget,
            )
            spells_budget -= cast

          elif phase == Phase.BEGIN_COMBAT:
            pass  # placeholder — "beginning of combat" triggers

          elif phase == Phase.DECLARE_ATTACKERS:
            self._resolve_combat(sim, pi, turn, phase_events if self.record_log else None)

          elif phase == Phase.DECLARE_BLOCKERS:
            pass  # blocking is handled inside _resolve_combat

          elif phase == Phase.COMBAT_DAMAGE:
            pass  # damage is handled inside _resolve_combat

          elif phase == Phase.END_COMBAT:
            pass  # placeholder — "end of combat" triggers

          elif phase == Phase.MAIN2:
            # Second main phase: use remaining spell budget
            if spells_budget > 0:
              available_mana = self._count_untapped_lands(sim, pi)
              cast = self._play_spells(
                sim, pi, available_mana,
                phase_events if self.record_log else None,
                max_spells=spells_budget,
              )
              spells_budget -= cast

          elif phase == Phase.END_STEP:
            pass  # placeholder — "at end of turn" triggers

          elif phase == Phase.CLEANUP:
            pass  # damage clearing already happened in untap for simplicity

        # ── Post-phase bookkeeping ──
        played_spell = p.stats.spells_cast > spells_before
        attacked = p.stats.damage_dealt > damage_before_turn

        # Track board size
        board_size = len(sim.get_battlefield(pi))
        if board_size > p.stats.max_board_size:
          p.stats.max_board_size = board_size

        # ── Record ML decision snapshot ──
        if self.ml_log and pre_snapshot is not None:
          available_mana = self._count_untapped_lands(sim, pi)
          if attacked:
            action_type = "attack"
          elif played_spell:
            action_type = "cast"
          elif available_mana >= 2:
            action_type = "hold"
          else:
            action_type = "pass"
          pre_snapshot["action"] = {"type": action_type}
          pre_snapshot["game_id"] = gid
          pre_snapshot["archetype"] = archetype
          turn_decisions.append(pre_snapshot)

        if self.record_log:
          life_dict = {sp.name: sp.life for sp in sim.players}
          boards_dict = {
            f"board_{si}": [c.name for c in sim.get_battlefield(si) if c.is_creature()]
            for si in range(len(sim.players))
          }
          phase_entry: dict = {
            "player": p.name,
            "playerId": pi,
            "events": phase_events,
            "lifeAfter": life_dict,
            **boards_dict,
          }
          if len(sim.players) == 2:
            phase_entry["boardA"] = boards_dict.get("board_0", [])
            phase_entry["boardB"] = boards_dict.get("board_1", [])
          turn_entry["phases"].append(phase_entry)

        # ── Check for new eliminations after this player's turn ──
        for si, sp in enumerate(sim.players):
          if sp.eliminated and si not in elimination_order:
            elimination_order.append(si)
            if self.record_log:
              phase_events.append(f"{sp.name} eliminated!")

      # Check game over
      alive = [p for p in sim.players if not p.eliminated]
      final_turn = turn + 1
      if self.record_log:
        game_log.append(turn_entry)
      if len(alive) <= 1:
        break

    result = self._build_result(sim, final_turn, elimination_order)
    if self.record_log:
      result.game_log = game_log

    # Stamp game outcome on all ML decisions and add to engine collection
    if self.ml_log and turn_decisions:
      # In base engine there's no single AI seat; use seat 0 as reference
      winner_seat = result.winner_seat
      for td in turn_decisions:
        seat = td.get("active_seat", 0)
        td["game_outcome"] = "win" if seat == winner_seat else "loss"
      self.ml_decisions.extend(turn_decisions)

    return result

  # ──────────────────────────────────────────────────────────
  # ML Decision Snapshot
  # ──────────────────────────────────────────────────────────

  def _capture_ml_snapshot(self, sim: SimState, pi: int, turn: int) -> dict:
    """Capture game state for ML training pipeline."""
    players_data = []
    for seat in range(len(sim.players)):
      p = sim.players[seat]
      seat_bf = sim.get_battlefield(seat)
      my_creatures = sum(1 for c in seat_bf if c.is_creature())
      my_lands = sum(1 for c in seat_bf if c.is_land())
      available_mana = sum(1 for c in seat_bf if not c.tapped and c.is_land())
      hand_names = [c.name for c in p.hand]
      graveyard_names = [c.name for c in p.graveyard]
      battlefield_names = [c.name for c in seat_bf if not c.is_land()]
      players_data.append({
        "seat": seat,
        "life": p.life,
        "mana": available_mana,
        "cmdr_dmg": 0,
        "cmdr_tax": 0,
        "creatures": my_creatures,
        "lands": my_lands,
        "hand": hand_names,
        "graveyard": graveyard_names,
        "battlefield": battlefield_names,
        "command_zone": [],
      })
    return {
      "phase": "main_1",
      "active_seat": pi,
      "turn": turn + 1,
      "players": players_data,
    }

  def flush_ml_decisions(self) -> list[dict]:
    """Return and clear collected ML decisions."""
    decisions = self.ml_decisions[:]
    self.ml_decisions.clear()
    return decisions

  # ──────────────────────────────────────────────────────────
  # Internal helpers
  # ──────────────────────────────────────────────────────────

  # ──────────────────────────────────────────────────────────
  # Opening-hand helpers
  # ──────────────────────────────────────────────────────────

  @staticmethod
  def _count_lands_in_hand(hand: list[Card]) -> int:
    """Count lands in a hand of cards."""
    return sum(1 for c in hand if c.is_land())

  @staticmethod
  def _should_mulligan(hand: list[Card], mulligan_number: int) -> bool:
    """Heuristic: mulligan if opening hand has 0-1 lands or 6-7 lands.

    Becomes more lenient with each successive mulligan — after 2+
    mulligans, accept 1-land hands to avoid going too low on cards.
    """
    lands = GameEngine._count_lands_in_hand(hand)
    total = len(hand)
    if mulligan_number >= 2:
      # Desperate: keep anything with 1-5 lands
      return lands < 1 or lands >= total
    # Standard: keep 2-5 lands in a 7-card hand
    return lands <= 1 or lands >= 6

  @staticmethod
  def _pick_bottom_cards(hand: list[Card], count: int, weights: dict) -> list[Card]:
    """Choose the worst *count* cards to put on the bottom of library.

    Uses the AI scoring function so the least valuable cards are
    bottomed — mirrors a real player's London mulligan decision.
    """
    if count <= 0 or count >= len(hand):
      return []
    scored = sorted(hand, key=lambda c: score_card(c, weights))
    return scored[:count]

  def _create_state(
    self,
    decks: list[list[Card]],
    names: list[str],
    commander_names: list[str] | None = None,
  ) -> SimState:
    """Create initial simulation state with shuffled decks and opening hands (N players).

    Implements the London mulligan rule: each player draws 7, decides
    whether to keep, and if not shuffles back and redraws.  After
    keeping, they put N cards on the bottom of their library where N
    is the number of times they mulliganed.

    If commander_names is provided, the matching card is flagged
    is_commander=True and placed in the player's command_zone
    instead of the library/hand.
    """
    commander_names = commander_names or []
    sim = SimState(max_turns=self.max_turns)
    for idx, (deck, name) in enumerate(zip(decks, names)):
      cards = [enrich_card(c.clone()) for c in deck]
      # Identify and separate commander card
      cmd_name = commander_names[idx].lower() if idx < len(commander_names) else ""
      commander_card = None
      remaining = []
      for c in cards:
        if cmd_name and c.name.lower() == cmd_name and commander_card is None:
          c.is_commander = True
          commander_card = c
        else:
          remaining.append(c)

      # ── London mulligan loop ──
      mulligan_count = 0
      if self.mulligan_rule == "london":
        for attempt in range(self.MAX_MULLIGANS):
          random.shuffle(remaining)
          hand = remaining[:7]
          if not self._should_mulligan(hand, attempt):
            break
          mulligan_count += 1
        else:
          # Exhausted all mulligans — forced keep with last draw
          random.shuffle(remaining)
          hand = remaining[:7]
      else:
        # No mulligan (legacy behavior)
        random.shuffle(remaining)
        hand = remaining[:7]

      library = remaining[7:]

      # ── Bottom N cards for London mulligan ──
      if mulligan_count > 0:
        bottom = self._pick_bottom_cards(hand, mulligan_count, self.weights)
        for card in bottom:
          hand.remove(card)
          library.insert(0, card)  # bottom of library

      opening_lands = self._count_lands_in_hand(hand)
      player = Player(
        name=name,
        life=self.starting_life,
        owner_id=idx,
        library=library,
        hand=hand,
        stats=PlayerStats(
          cards_drawn=7,
          mulligans=mulligan_count,
          opening_hand_lands=opening_lands,
        ),
      )
      if commander_card:
        player.command_zone.append(commander_card)
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

  @staticmethod
  def _send_to_graveyard(sim: SimState, card, owner_idx: int) -> None:
    """Route card to command zone if it's a commander, else graveyard."""
    owner = sim.players[owner_idx]
    if card.is_commander:
      card.tapped = False
      card.turn_played = -1
      owner.command_zone.append(card)
    else:
      owner.graveyard.append(card)

  # ──────────────────────────────────────────────────────────
  # Centralized Damage
  # ──────────────────────────────────────────────────────────

  @staticmethod
  def deal_damage(
    sim: SimState,
    amount: int,
    target_seat: int,
    source_card: Card | None = None,
    source_seat: int | None = None,
    is_combat: bool = False,
    events: list | None = None,
    label: str = "",
  ) -> int:
    """Apply *amount* damage to a player through the centralized path.

    Handles life reduction, stat tracking, commander damage tracking
    (both per-seat aggregate and per-card breakdown from PR #89),
    and elimination checks.  Returns the actual damage dealt.
    """
    if amount <= 0:
      return 0
    target = sim.players[target_seat]
    if target.eliminated:
      return 0

    target.life -= amount
    target.stats.damage_received += amount
    if source_seat is not None:
      sim.players[source_seat].stats.damage_dealt += amount

    # Commander damage tracking — dual-dict model (PR #89):
    #   commander_damage_received[seat] = aggregate per-seat total
    #   commander_damage_by_card[(seat, card_name)] = per-card breakdown
    if source_card and source_card.is_commander and source_seat is not None:
      target.commander_damage_received[source_seat] = (
        target.commander_damage_received.get(source_seat, 0) + amount
      )
      key = (source_seat, source_card.name)
      target.commander_damage_by_card[key] = (
        target.commander_damage_by_card.get(key, 0) + amount
      )

    if events is not None and label:
      events.append(f"{label} ({target.name} now at {target.life} life)")

    if target.life <= 0 or target.is_dead_to_commander_damage():
      target.eliminated = True
    return amount

  def _count_untapped_lands(self, sim: SimState, pi: int) -> int:
    """Count untapped lands for a player."""
    return sum(
      1
      for c in sim.get_battlefield(pi)
      if not c.tapped and c.is_land()
    )

  def _play_spells(self, sim: SimState, pi: int, available_mana: int, events: list | None = None, max_spells: int = 2) -> int:
    """Play up to *max_spells* spells from hand, prioritized by AI score.

    Returns the number of spells actually played this call.
    """
    p = sim.players[pi]
    w = self.weights
    played = 0
    while played < max_spells:
      playable = []
      for i, card in enumerate(p.hand):
        if card.is_land():
          continue
        cmc = card.cmc or 0
        if cmc <= available_mana:
          playable.append((score_card(card, w), i, card))
      playable.sort(key=lambda x: -x[0])
      if not playable:
        break
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
        all_opp_creatures = []
        for oi in range(len(sim.players)):
          if oi == pi or sim.players[oi].eliminated:
            continue
          for c in sim.get_battlefield(oi):
            if c.is_creature():
              all_opp_creatures.append(c)
        if all_opp_creatures:
          all_opp_creatures.sort(key=lambda c: -score_card(c, w))
          killed = all_opp_creatures[0]
          sim.remove_from_battlefield(killed.id)
          self._send_to_graveyard(sim, killed, killed.owner_id)
          if events is not None:
            events.append(f"Cast {card.name} (removal) \u2014 destroyed {killed.name}")
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
              self._send_to_graveyard(sim, c, c.owner_id)
            else:
              keep.append(c)
          sim.battlefields[seat_idx] = keep
        p.graveyard.append(card)
        if events is not None:
          events.append(f"Cast {card.name} (board wipe) \u2014 destroyed {len(wiped_names)} creatures")
      elif card.is_direct_damage and card.direct_damage_amount > 0:
        # Direct-damage spell (burn): route through centralized deal_damage()
        target_seat = self._select_attack_target(sim, pi)
        if target_seat != -1:
          target_name = sim.players[target_seat].name
          self.deal_damage(
            sim, card.direct_damage_amount, target_seat,
            source_card=card, source_seat=pi,
            events=events,
            label=f"{card.name} deals {card.direct_damage_amount} damage to {target_name}",
          )
        elif events is not None:
          events.append(f"Cast {card.name} (burn, no targets)")
        p.graveyard.append(card)
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

    # --- Commander casting from command zone (second pass) ---
    available_mana = self._count_untapped_lands(sim, pi)
    for cmd_card in list(p.command_zone):
      tax = p.commander_tax.get(cmd_card.name, 0)
      total_cost = (cmd_card.cmc or 0) + tax
      if total_cost <= available_mana:
        p.command_zone.remove(cmd_card)
        cmd_card.owner_id = pi
        cmd_card.tapped = False
        cmd_card.id = sim.next_card_id
        sim.next_card_id += 1
        cmd_card.turn_played = sim.turn
        mana_needed = total_cost
        for bf_card in sim.get_battlefield(pi):
          if mana_needed <= 0:
            break
          if not bf_card.tapped and bf_card.is_land():
            bf_card.tapped = True
            mana_needed -= 1
        sim.add_to_battlefield(pi, cmd_card)
        p.stats.spells_cast += 1
        p.stats.mana_spent += total_cost
        p.commander_tax[cmd_card.name] = tax + 2
        if events is not None:
          events.append(
            f"Cast commander {cmd_card.name} from command zone "
            f"for {total_cost} mana (tax={tax})"
          )
        available_mana = self._count_untapped_lands(sim, pi)
    return played

  @staticmethod
  def _select_attack_target(sim: SimState, pi: int) -> int:
    """Select the best opponent to attack.

    Multiplayer heuristic: attack the weakest non-eliminated opponent
    (lowest life total). Ties broken by highest seat index (arbitrary
    but deterministic).

    Returns the seat index of the chosen target, or -1 if no valid target.
    """
    best_seat = -1
    best_life = float('inf')
    for si, sp in enumerate(sim.players):
      if si == pi or sp.eliminated:
        continue
      if sp.life < best_life:
        best_life = sp.life
        best_seat = si
    return best_seat

  def _resolve_combat(self, sim: SimState, pi: int, turn: int, events: list | None = None) -> None:
    """Resolve combat phase for a player (N-player ready).

    This is the backward-compatible atomic path used by run_n().
    For priority-window split combat, use assign_attackers() /
    assign_blockers() / resolve_combat_damage() directly.
    """
    p = sim.players[pi]
    opp_idx = self._select_attack_target(sim, pi)
    if opp_idx == -1:
      return
    opp = sim.players[opp_idx]
    w = self.weights
    my_creatures = [
      c
      for c in sim.get_battlefield(pi)
      if (
        c.is_creature()
        and not c.tapped
        and (c.turn_played < sim.turn or c.has_keyword("haste"))
      )
    ]
    if not my_creatures:
      return
    opp_blockers = [
      c
      for c in sim.get_battlefield(opp_idx)
      if (
        c.is_creature()
        and not c.tapped
      )
    ]
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
    total_damage = 0
    used_blockers: set[int] = set()
    combat_details: list[str] = []
    # Per-attacker damage to route through deal_damage() individually
    attacker_damage: list[tuple[Card, int]] = []
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
      if valid_blockers and (not atk.has_keyword("menace") or len(valid_blockers) >= 2):
        if atk.has_keyword("menace") and len(valid_blockers) >= 2:
          valid_blockers.sort(key=lambda b: -b.get_toughness())
          blocker = valid_blockers[0]
          second_blocker = valid_blockers[1]
          used_blockers.add(second_blocker.id)
        else:
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
          # Accumulate damage on creatures (not binary kill)
          blocker.damage_marked += a_pow
          if blocker.damage_marked >= blocker.get_toughness() or atk.has_keyword("deathtouch"):
            sim.remove_from_battlefield(blocker.id)
            self._send_to_graveyard(sim, blocker, opp_idx)
            if events is not None:
              combat_details.append(f"  {blocker.name} dies")
          atk.damage_marked += b_pow
          if atk.damage_marked >= a_tou or blocker.has_keyword("deathtouch"):
            sim.remove_from_battlefield(atk.id)
            self._send_to_graveyard(sim, atk, pi)
            if events is not None:
              combat_details.append(f"  {atk.name} dies")
          trample_over = 0
          if atk.has_keyword("trample") and a_pow > blocker.get_toughness():
            trample_over = a_pow - blocker.get_toughness()
            attacker_damage.append((atk, trample_over))
            total_damage += trample_over
          if atk.has_keyword("double strike"):
            ds_dmg = a_pow if (a_pow >= blocker.get_toughness() or atk.has_keyword("deathtouch")) else trample_over
            attacker_damage.append((atk, ds_dmg))
            total_damage += ds_dmg
          if atk.has_keyword("lifelink"):
            damage_dealt = min(a_pow, blocker.get_toughness()) + trample_over
            if atk.has_keyword("double strike"):
              damage_dealt *= 2
            p.life += damage_dealt
      if not blocked:
        if atk.has_keyword("double strike"):
          atk_dmg = a_pow * 2
          if atk.has_keyword("lifelink"):
            p.life += a_pow * 2
        else:
          atk_dmg = a_pow
          if atk.has_keyword("lifelink"):
            p.life += a_pow
        attacker_damage.append((atk, atk_dmg))
        total_damage += atk_dmg
    # Route each attacker's damage through deal_damage() for
    # centralized life/stats/commander tracking
    for atk_card, dmg in attacker_damage:
      if dmg > 0:
        self.deal_damage(
          sim, dmg, opp_idx,
          source_card=atk_card, source_seat=pi,
          is_combat=True,
        )
    if events is not None and total_damage > 0:
      # Compute commander damage annotation from the per-card dict
      total_cmd_damage = sum(
        dmg for (atk_card, dmg) in attacker_damage
        if atk_card.is_commander and dmg > 0
      )
      cmd_note = f" ({total_cmd_damage} cmdr)" if total_cmd_damage > 0 else ""
      events.append(
        f"Dealt {total_damage} combat damage{cmd_note} to {opp.name} (now {opp.life} life)"
      )
      events.extend(combat_details)

  # ──────────────────────────────────────────────────────────
  # Split combat methods for turn_manager priority windows
  # (Issue #86 Item 1). Use these for interactive/priority-aware
  # combat; _resolve_combat() remains the atomic run_n() path.
  # ──────────────────────────────────────────────────────────

  def assign_attackers(
      self, sim: SimState, pi: int, events: list | None = None,
  ) -> Optional[CombatState]:
      """Phase 1 of split combat: choose attackers, populate CombatState.

      Returns a CombatState with attackers set and tapped, or None if
      no valid attack is possible.  Does NOT deal any damage.
      """
      p = sim.players[pi]
      opp_idx = self._select_attack_target(sim, pi)
      if opp_idx == -1:
          return None

      opp = sim.players[opp_idx]
      w = self.weights
      my_creatures = [
          c
          for c in sim.get_battlefield(pi)
          if (
              c.is_creature()
              and not c.tapped
              and (c.turn_played < sim.turn or c.has_keyword("haste"))
          )
      ]
      if not my_creatures:
          return None

      opp_blockers = [
          c
          for c in sim.get_battlefield(opp_idx)
          if c.is_creature() and not c.tapped
      ]

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

      if not attackers:
          return None

      if events is not None:
          atk_names = [f"{a.name} ({a.pt})" for a in attackers]
          events.append(f"Attacks {opp.name} with: {', '.join(atk_names)}")

      # Build and store CombatState
      combat = CombatState(
          defending_seat=opp_idx,
          attackers={atk.id: opp_idx for atk in attackers},
          active=True,
      )
      sim.combat = combat
      return combat

  def assign_blockers(
      self, sim: SimState, pi: int, combat: CombatState,
      events: list | None = None,
  ) -> None:
      """Phase 2 of split combat: assign blockers into CombatState.

      Populates combat.blockers and combat.player_damage.
      Does NOT apply any damage to players or creatures yet.
      """
      opp_idx = combat.defending_seat
      opp_blockers = [
          c for c in sim.get_battlefield(opp_idx)
          if c.is_creature() and not c.tapped
      ]
      used_blockers: set[int] = set()

      for atk_id in combat.attackers:
          atk = next((c for bf in sim.battlefields for c in bf if c.id == atk_id), None)
          if atk is None:
              continue
          a_pow = atk.get_power()
          has_flying = atk.has_keyword("flying")
          valid_blockers = [
              b for b in opp_blockers
              if b.id not in used_blockers
              and (not has_flying or b.has_keyword("flying") or b.has_keyword("reach"))
          ]

          blocker = None
          if valid_blockers and (not atk.has_keyword("menace") or len(valid_blockers) >= 2):
              if atk.has_keyword("menace") and len(valid_blockers) >= 2:
                  valid_blockers.sort(key=lambda b: -b.get_toughness())
                  blocker = valid_blockers[0]
                  used_blockers.add(valid_blockers[1].id)
              else:
                  blocker = next(
                      (b for b in valid_blockers if b.get_toughness() > a_pow),
                      None,
                  )
                  opp = sim.players[opp_idx]
                  if blocker is None and opp.life <= a_pow * 2 and valid_blockers:
                      blocker = valid_blockers[0]

          if blocker:
              used_blockers.add(blocker.id)
              combat.blockers[atk_id] = [blocker.id]
              if events is not None:
                  events.append(f"{atk.name} blocked by {blocker.name}")
          else:
              # Unblocked — full damage goes to player
              combat.player_damage[atk_id] = a_pow

  def resolve_combat_damage(
      self, sim: SimState, pi: int, combat: CombatState,
      first_strike_only: bool = False,
      events: list | None = None,
  ) -> None:
      """Phase 3 of split combat: apply damage from CombatState.

      When first_strike_only=True, only processes creatures with
      first_strike or double_strike.  When False, processes all
      remaining (skipping first-strikers if already resolved).
      """
      opp_idx = combat.defending_seat
      p = sim.players[pi]
      total_damage = 0
      attacker_damage: list[tuple[Card, int]] = []
      combat_details: list[str] = []

      for atk_id, def_seat in list(combat.attackers.items()):
          atk = next((c for bf in sim.battlefields for c in bf if c.id == atk_id), None)
          if atk is None:
              continue  # removed by instant before damage

          is_fs = atk.has_keyword("first_strike") or atk.has_keyword("double_strike")
          if first_strike_only and not is_fs:
              continue
          if not first_strike_only and is_fs and combat.first_strike_resolved:
              if not atk.has_keyword("double_strike"):
                  continue  # already dealt damage in FS step

          a_pow = atk.get_power()
          a_tou = atk.get_toughness()
          blocker_ids = combat.blockers.get(atk_id, [])

          if blocker_ids:
              blocker = next((c for bf in sim.battlefields for c in bf if c.id == blocker_ids[0]), None)
              if blocker is None:
                  # Blocker removed — attacker is still blocked but deals no combat damage to player
                  continue
              b_pow = blocker.get_power()
              blocker.damage_marked += a_pow
              if blocker.damage_marked >= blocker.get_toughness() or atk.has_keyword("deathtouch"):
                  sim.remove_from_battlefield(blocker.id)
                  self._send_to_graveyard(sim, blocker, opp_idx)
                  if events is not None:
                      combat_details.append(f"  {blocker.name} dies")
              atk.damage_marked += b_pow
              if atk.damage_marked >= a_tou or blocker.has_keyword("deathtouch"):
                  sim.remove_from_battlefield(atk.id)
                  self._send_to_graveyard(sim, atk, pi)
                  if events is not None:
                      combat_details.append(f"  {atk.name} dies")
              # Trample over
              trample_over = 0
              if atk.has_keyword("trample") and a_pow > blocker.get_toughness():
                  trample_over = a_pow - blocker.get_toughness()
                  attacker_damage.append((atk, trample_over))
                  total_damage += trample_over
              if atk.has_keyword("lifelink"):
                  p.life += min(a_pow, blocker.get_toughness()) + trample_over
          else:
              # Unblocked
              atk_dmg = a_pow * 2 if atk.has_keyword("double_strike") else a_pow
              if atk.has_keyword("lifelink"):
                  p.life += atk_dmg
              attacker_damage.append((atk, atk_dmg))
              total_damage += atk_dmg

      # Route each attacker's damage through deal_damage()
      for atk_card, dmg in attacker_damage:
          if dmg > 0:
              self.deal_damage(
                  sim, dmg, opp_idx,
                  source_card=atk_card, source_seat=pi,
                  is_combat=True,
              )

      if first_strike_only:
          combat.first_strike_resolved = True

      if events is not None and total_damage > 0:
          opp = sim.players[opp_idx]
          total_cmd_damage = sum(
              dmg for (atk_card, dmg) in attacker_damage
              if atk_card.is_commander and dmg > 0
          )
          cmd_note = f" ({total_cmd_damage} cmdr)" if total_cmd_damage > 0 else ""
          events.append(
              f"Dealt {total_damage} combat damage{cmd_note} to {opp.name} (now {opp.life} life)"
          )
          events.extend(combat_details)

  def _build_result(
    self,
    sim: SimState,
    final_turn: int,
    elimination_order: list[int] | None = None,
  ) -> GameResult:
    """Determine winner and build result object (N-player).

    Finish positions:
      1 = winner (last player standing, or highest life if timeout)
      2..N = elimination order (last eliminated = 2nd place, etc.)
    """
    if elimination_order is None:
      elimination_order = []
    n = len(sim.players)
    alive = [i for i, p in enumerate(sim.players) if not p.eliminated]
    if len(alive) == 1:
      winner = alive[0]
    elif len(alive) == 0:
      winner = max(range(n), key=lambda i: sim.players[i].life)
    else:
      winner = max(alive, key=lambda i: sim.players[i].life)

    finish: dict[int, int] = {winner: 1}
    position = 2
    for seat in reversed(elimination_order):
      if seat != winner:
        finish[seat] = position
        position += 1
    remaining_alive = sorted(
      [i for i in alive if i != winner],
      key=lambda i: -sim.players[i].life,
    )
    for seat in remaining_alive:
      if seat not in finish:
        finish[seat] = position
        position += 1

    player_results = []
    for seat, p in enumerate(sim.players):
      player_results.append(PlayerResult(
        seat_index=seat,
        name=p.name,
        life=p.life,
        eliminated=p.eliminated,
        finish_position=finish.get(seat, n),
        stats=p.stats,
      ))
    return GameResult(
      winner_seat=winner,
      turns=min(final_turn, sim.max_turns),
      players=player_results,
    )
