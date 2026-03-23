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
  GameResult,
  Player,
  PlayerResult,
  PlayerStats,
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

  def __init__(
    self,
    max_turns: int = 25,
    starting_life: int = 40,
    weights: Optional[dict] = None,
    record_log: bool = False,
    ml_log: bool = False,
  ):
    self.max_turns = max_turns
    self.starting_life = starting_life
    # Auto-load learned weights; caller can override by passing weights=
    self.weights = weights if weights is not None else load_weights()
    self.record_log = record_log
    self.ml_log = ml_log
    self.ml_decisions: list[dict] = []

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
      turn_entry = {"turn": turn + 1, "phases": []}

      for pi in range(len(sim.players)):
        p = sim.players[pi]
        if p.eliminated:
          continue
        p.stats.turns_alive += 1
        phase_events: list[str] = []

        # ── Untap (correct MTG order: untap is first) ──
        for c in sim.get_battlefield(pi):
          c.tapped = False
          c.damage_marked = 0  # clear damage each turn (MTG rule 514.2)

        # ── Draw ──
        if p.library:
          drawn = p.library[-1]
          p.hand.append(p.library.pop())
          p.stats.cards_drawn += 1
          if self.record_log:
            phase_events.append(f"Drew {drawn.name}")

        # ── Capture ML snapshot BEFORE turn actions ──
        pre_snapshot = None
        if self.ml_log:
          pre_snapshot = self._capture_ml_snapshot(sim, pi, turn)

        # ── Land drop ──
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

        # ── Available mana ──
        available_mana = self._count_untapped_lands(sim, pi)

        # ── Play spells (up to 2) ──
        spells_before = p.stats.spells_cast
        self._play_spells(sim, pi, available_mana, phase_events if self.record_log else None)
        played_spell = p.stats.spells_cast > spells_before

        # ── Track board size ──
        board_size = len(sim.get_battlefield(pi))
        if board_size > p.stats.max_board_size:
          p.stats.max_board_size = board_size

        # ── Combat ──
        damage_before = p.stats.damage_dealt
        self._resolve_combat(sim, pi, turn, phase_events if self.record_log else None)
        attacked = p.stats.damage_dealt > damage_before

        # ── Record ML decision snapshot ──
        if self.ml_log and pre_snapshot is not None:
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

  def _create_state(
    self,
    decks: list[list[Card]],
    names: list[str],
    commander_names: list[str] | None = None,
  ) -> SimState:
    """Create initial simulation state with shuffled decks and opening hands (N players).

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
      random.shuffle(remaining)
      hand = remaining[:7]
      library = remaining[7:]
      player = Player(
        name=name,
        life=self.starting_life,
        owner_id=idx,
        library=library,
        hand=hand,
        stats=PlayerStats(cards_drawn=7),
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

  def _count_untapped_lands(self, sim: SimState, pi: int) -> int:
    """Count untapped lands for a player."""
    return sum(
      1
      for c in sim.get_battlefield(pi)
      if not c.tapped and c.is_land()
    )

  def _play_spells(self, sim: SimState, pi: int, available_mana: int, events: list | None = None) -> None:
    """Play up to 2 spells from hand, prioritized by AI score."""
    p = sim.players[pi]
    w = self.weights
    played = 0
    while played < 2:
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
    """Resolve combat phase for a player (N-player ready)."""
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
    # Per-commander-card damage dealt to the opponent this combat.
    # Key = attacker card name; only populated for is_commander cards.
    cmd_damage_by_card: dict[str, int] = {}
    used_blockers: set[int] = set()
    combat_details: list[str] = []
    for atk in attackers:
      a_pow = atk.get_power()
      a_tou = atk.get_toughness()
      has_flying = atk.has_keyword("flying")
      is_commander_atk = atk.is_commander
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
            total_damage += trample_over
            if is_commander_atk:
              cmd_damage_by_card[atk.name] = cmd_damage_by_card.get(atk.name, 0) + trample_over
          if atk.has_keyword("double strike"):
            if a_pow >= blocker.get_toughness() or atk.has_keyword("deathtouch"):
              total_damage += a_pow
              if is_commander_atk:
                cmd_damage_by_card[atk.name] = cmd_damage_by_card.get(atk.name, 0) + a_pow
            else:
              total_damage += trample_over
              if is_commander_atk:
                cmd_damage_by_card[atk.name] = cmd_damage_by_card.get(atk.name, 0) + trample_over
          if atk.has_keyword("lifelink"):
            damage_dealt = min(a_pow, blocker.get_toughness()) + trample_over
            if atk.has_keyword("double strike"):
              damage_dealt *= 2
            p.life += damage_dealt
      if not blocked:
        if atk.has_keyword("double strike"):
          total_damage += a_pow * 2
          if is_commander_atk:
            cmd_damage_by_card[atk.name] = cmd_damage_by_card.get(atk.name, 0) + a_pow * 2
          if atk.has_keyword("lifelink"):
            p.life += a_pow * 2
        else:
          total_damage += a_pow
          if is_commander_atk:
            cmd_damage_by_card[atk.name] = cmd_damage_by_card.get(atk.name, 0) + a_pow
          if atk.has_keyword("lifelink"):
            p.life += a_pow
    # Apply damage to opponent
    opp.life -= total_damage
    p.stats.damage_dealt += total_damage
    opp.stats.damage_received += total_damage
    # Track commander damage — both per-seat aggregate and per-card breakdown
    total_cmd_damage = sum(cmd_damage_by_card.values())
    if total_cmd_damage > 0:
      opp.commander_damage_received[pi] = (
        opp.commander_damage_received.get(pi, 0) + total_cmd_damage
      )
      for cmd_name, dmg in cmd_damage_by_card.items():
        key = (pi, cmd_name)
        opp.commander_damage_by_card[key] = (
          opp.commander_damage_by_card.get(key, 0) + dmg
        )
    if events is not None and total_damage > 0:
      cmd_note = f" ({total_cmd_damage} cmdr)" if total_cmd_damage > 0 else ""
      events.append(
        f"Dealt {total_damage} combat damage{cmd_note} to {opp.name} (now {opp.life} life)"
      )
      events.extend(combat_details)
    # Check elimination: life <= 0 or commander damage >= 21
    if opp.life <= 0 or opp.is_dead_to_commander_damage():
      opp.eliminated = True

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
