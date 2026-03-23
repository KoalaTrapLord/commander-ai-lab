"""
Commander AI Lab — Commander Turn Manager (Phase 3)
====================================================
Asynchronous multi-player turn queue with full Commander structure.

Features:
  - Variable player count (2–4 seats), any mix of human / AIOpponent
  - Human seats supported: decide_action() is skipped; caller injects the
    move via human_play(move_id) instead
  - Correct phase ordering: Untap → Upkeep → Draw → Main1 → Combat
    → Main2 → End Step
  - Priority-passing: each phase dispatches to priority_seat and cycles
    through APNAP order until all players pass in sequence
  - AI decisions run in a thread pool so the event loop stays responsive;
    UI can display the "thinking" status via on_thinking callback
  - Player elimination mid-game: eliminated players are removed from the
    turn queue immediately after any damage is dealt
  - Per-turn threat re-evaluation at the start of each AI main phase
  - All game events surfaced through optional async callbacks

Usage (AI-only game)::

    from commander_ai_lab.sim.turn_manager import CommanderTurnManager
    from commander_ai_lab.sim.ai_opponent    import create_four_player_ai_roster
    from commander_ai_lab.sim.game_state     import CommanderGameState

    gs      = CommanderGameState(...)          # build your initial state
    ai_list = create_four_player_ai_roster()   # Phase 2 factory

    tm = CommanderTurnManager(game_state=gs, ai_opponents=ai_list)
    asyncio.run(tm.run_game())

Usage with a human player at seat 0::

    tm = CommanderTurnManager(
        game_state=gs,
        ai_opponents=ai_list,
        human_seats={0},
        on_action=my_ui_callback,
    )
    # In your UI event handler:
    await tm.human_play(move_id=chosen_id)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Set
from commander_ai_lab.sim.models import Phase, PHASE_ORDER, SORCERY_PHASES, CombatState
from commander_ai_lab.sim.game_state import CommanderGameState, CommanderPlayer
from commander_ai_lab.sim.ai_opponent import AIOpponent
from commander_ai_lab.sim.threat_assessor import assess_threats, ThreatScore

logger = logging.getLogger("turn_manager")

# Re-export for backward compatibility; canonical source is models.py
PHASES = [p.value for p in PHASE_ORDER]

# Phases where a player can take an action (play land, cast spell, etc.)
ACTION_PHASES = {p.value for p in SORCERY_PHASES}
# Phases where instant-speed responses can happen
RESPONSE_PHASES = {
    Phase.UPKEEP.value,
    Phase.END_STEP.value,
}


@dataclass
class GameEvent:
    """A single event emitted by the turn manager."""
    event_type: str           # 'phase_change', 'action', 'narration', 'thinking', 'elimination', 'game_over'
    seat: int
    player_name: str
    phase: str
    turn: int
    move_id: Optional[int] = None
    move_description: str = ""
    narration: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class TurnManagerConfig:
    """Tunable parameters for the turn manager."""
    max_turns: int = 40
    ai_decision_timeout: float = float(os.environ.get("BRAIN_TIMEOUT", "300.0"))    # seconds before fallback
    ai_narration_enabled: bool = True
    ai_decision_delay: float = 0.0       # cosmetic pause (set > 0 for UI readability)
    priority_pass_limit: int = 8         # max APNAP passes per phase before auto-advance
    thread_pool_size: int = 3            # concurrent AI threads


class CommanderTurnManager:
    """
    Async Commander turn manager.

    Drives the game loop, dispatching each seat's turn through the correct
    Commander phases, running AI decisions off-thread, and surfacing all
    events via optional callbacks.

    Parameters
    ----------
    game_state : CommanderGameState
        Mutable game state that this manager operates on.
    ai_opponents : list[AIOpponent]
        One AIOpponent per AI seat. Must have seat attribute matching
        game_state.players index. Human seats are gaps in this list.
    human_seats : set[int]
        Seats controlled by human players. Turns for these seats block
        until human_play() is called.
    on_event : async callable, optional
        Async callback invoked for every GameEvent (UI integration hook).
    on_thinking : async callable, optional
        Async callback invoked when AI starts / finishes thinking.
        Signature: on_thinking(seat, is_thinking: bool)
    config : TurnManagerConfig
    """

    def __init__(
        self,
        game_state: CommanderGameState,
        ai_opponents: list[AIOpponent],
        human_seats: Optional[Set[int]] = None,
        on_event: Optional[Callable[[GameEvent], Awaitable[None]]] = None,
        on_thinking: Optional[Callable[[int, bool], Awaitable[None]]] = None,
        config: Optional[TurnManagerConfig] = None,
    ) -> None:
        self.gs = game_state
        self.config = config or TurnManagerConfig()
        self.human_seats: Set[int] = human_seats or set()
        self.on_event = on_event
        self.on_thinking = on_thinking

        # Build seat → AIOpponent map
        self._ai_map: dict[int, AIOpponent] = {ai.seat: ai for ai in ai_opponents}

        # Human move injection: seat → asyncio.Future
        self._human_move_futures: dict[int, asyncio.Future] = {}

        # Turn queue: double-ended queue of active seat indices
        self._turn_queue: deque[int] = deque(
            i for i in range(len(game_state.players))
        )

        # Thread pool for AI inference (keeps event loop unblocked)
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.thread_pool_size,
            thread_name_prefix="ai_worker",
        )

        # Stats
        self._total_actions: int = 0
        self._fallback_count: int = 0
        self.game_over: bool = False
        self.winner_seat: Optional[int] = None

        # Latest threat scores per seat (refreshed each main phase)
        self._threat_cache: dict[int, list[ThreatScore]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_game(self) -> Optional[int]:
        """
        Run the full game loop until one player wins or max_turns is reached.

        Returns the winner's seat index, or None if the game timed out.
        """
        logger.info("Game started. Players: %s",
                    [p.name for p in self.gs.players])

        for turn_num in range(1, self.config.max_turns + 1):
            self.gs.turn = turn_num

            if self.game_over:
                break

            # Snapshot the active seats at the start of each full round
            active_seats = list(self._turn_queue)
            for seat in active_seats:
                if self.gs.players[seat].eliminated:
                    continue
                self.gs.active_player_seat = seat
                await self._run_player_turn(seat, turn_num)

                # Check for eliminations after each player's turn
                await self._check_eliminations()
                if self.game_over:
                    break

            if self.game_over:
                break

        if not self.game_over:
            # Timeout — winner is highest life total
            alive = [
                (p.life, i)
                for i, p in enumerate(self.gs.players)
                if not p.eliminated
            ]
            if alive:
                _, self.winner_seat = max(alive)
            self.game_over = True
            await self._emit(GameEvent(
                event_type="game_over",
                seat=self.winner_seat or 0,
                player_name=self.gs.players[self.winner_seat or 0].name,
                phase="cleanup",
                turn=self.gs.turn,
                extra={"reason": "timeout", "winner": self.winner_seat},
            ))

        logger.info("Game over. Winner seat: %s", self.winner_seat)
        self._executor.shutdown(wait=False)
        return self.winner_seat

    async def human_play(self, move_id: int) -> None:
        """
        Inject a move from a human player.

        Call this from your UI event handler when the human selects an action.
        The turn manager is blocking on an asyncio.Future for the active
        human seat — this resolves it.
        """
        # Find the currently-waiting human seat
        active = self.gs.active_player_seat
        if active in self._human_move_futures:
            fut = self._human_move_futures[active]
            if not fut.done():
                asyncio.get_running_loop().call_soon_threadsafe(fut.set_result, move_id)
            else:
                logger.warning("human_play called but future already resolved for seat %d", active)
        else:
            logger.warning("human_play called but no future pending for seat %d", active)

    def get_legal_moves(self, seat: int) -> list[dict]:
        """
        Return the current legal moves for a seat.
        Delegates to the rules engine on game_state.
        """
        return self.gs.get_legal_moves(seat)

    def get_threat_scores(self, viewer_seat: int) -> list[ThreatScore]:
        """Return the latest cached threat scores from viewer_seat's perspective."""
        return self._threat_cache.get(viewer_seat, [])

    def get_stats(self) -> dict:
        """Return turn manager statistics."""
        return {
            "turn": self.gs.turn,
            "total_actions": self._total_actions,
            "fallback_count": self._fallback_count,
            "game_over": self.game_over,
            "winner_seat": self.winner_seat,
            "active_seats": list(self._turn_queue),
        }

    # ── Turn Phases ───────────────────────────────────────────────────────────

    async def _run_player_turn(self, seat: int, turn_num: int) -> None:
        """Drive all phases of one player's turn."""
        player = self.gs.players[seat]
        logger.debug("Turn %d — %s's turn begins", turn_num, player.name)

        for phase in PHASES:
            if self.game_over:
                return

            self.gs.current_phase = phase
            self.gs.priority_seat = seat

            await self._emit(GameEvent(
                event_type="phase_change",
                seat=seat,
                player_name=player.name,
                phase=phase,
                turn=turn_num,
            ))

            if phase == "untap":
                await self._phase_untap(seat)
            elif phase == "draw":
                await self._phase_draw(seat, turn_num)
            elif phase in ACTION_PHASES:
                await self._phase_main(seat, turn_num, phase)
            elif phase == "declare_attackers":
                await self._phase_combat(seat, turn_num)
            elif phase == "cleanup":
                await self._phase_cleanup(seat)
            elif phase in RESPONSE_PHASES:
                # APNAP priority window — AI opponents may respond
                await self._apnap_priority_window(seat, turn_num, phase)

    # ── Individual Phases ─────────────────────────────────────────────────────

    async def _phase_untap(self, active_seat: int) -> None:
        """Untap all permanents for active player. No priority."""
        player = self.gs.players[active_seat]
        for card in self.gs.sim_state.get_battlefield(active_seat):
            card.tapped = False
        logger.debug("  [untap] %s untapped all permanents", player.name)

    async def _phase_draw(self, active_seat: int, turn_num: int) -> None:
        """Active player draws one card (skip on turn 1 seat 0 by default)."""
        player = self.gs.players[active_seat]
        if turn_num == 1 and active_seat == 0:
            return  # Traditional no-draw-on-first-turn rule
        if player.library:
            drawn = player.library.pop()
            player.hand.append(drawn)
            logger.debug("  [draw] %s drew %s", player.name, drawn.name)

    async def _phase_main(self, active_seat: int, turn_num: int, phase: str) -> None:
        """
        Main phase: active player takes one action, then APNAP window.
        Threat scores re-evaluated at the start of main1.
        """
        if phase == "main1":
            self._refresh_threat_scores(active_seat)

        legal_moves = self.get_legal_moves(active_seat)
        if not legal_moves:
            return

        move_id = await self._get_action(active_seat, legal_moves, turn_num)
        if move_id is not None:
            desc = self._move_desc(move_id, legal_moves)
            self.gs.apply_move(active_seat, move_id)
            self._total_actions += 1

            narration = ""
            if self.config.ai_narration_enabled and active_seat in self._ai_map:
                ai = self._ai_map[active_seat]
                narration = ai.narrate_play(move_id, legal_moves, self.gs)

            await self._emit(GameEvent(
                event_type="action",
                seat=active_seat,
                player_name=self.gs.players[active_seat].name,
                phase=phase,
                turn=turn_num,
                move_id=move_id,
                move_description=desc,
                narration=narration,
            ))

        # APNAP: other players respond after active player acts
        await self._apnap_priority_window(active_seat, turn_num, phase)

    async def _phase_combat(self, active_seat: int, turn_num: int) -> None:
        """Full combat sequence with priority windows at each sub-phase (Issue #86)."""
        sim = self.gs.sim_state

        # 1. Beginning of combat — priority window BEFORE attackers chosen
        await self._apnap_priority_window(active_seat, turn_num, "begin_combat")

        # 2. Declare attackers
        legal_moves = self.get_legal_moves(active_seat)
        attack_moves = [m for m in legal_moves if m.get("category") == "attack"]
        if not attack_moves:
            return

        move_id = await self._get_action(active_seat, attack_moves, turn_num)
        if move_id is not None:
            desc = self._move_desc(move_id, attack_moves)
            self.gs.apply_move(active_seat, move_id)
            self._total_actions += 1

            narration = ""
            if self.config.ai_narration_enabled and active_seat in self._ai_map:
                narration = self._ai_map[active_seat].narrate_play(
                    move_id, attack_moves, self.gs
                )

            await self._emit(GameEvent(
                event_type="action",
                seat=active_seat,
                player_name=self.gs.players[active_seat].name,
                phase="declare_attackers",
                turn=turn_num,
                move_id=move_id,
                move_description=desc,
                narration=narration,
            ))

        # 3. After-attackers priority window
        await self._apnap_priority_window(active_seat, turn_num, "declare_attackers")

        # 4. Declare blockers — each defending player in APNAP order
        for defender_seat in [s for s in range(len(self.gs.players))
                              if s != active_seat
                              and not self.gs.players[s].eliminated]:
            block_moves = [m for m in self.get_legal_moves(defender_seat)
                           if m.get("category") == "block"]
            if block_moves:
                block_id = await self._get_action(defender_seat, block_moves, turn_num)
                if block_id is not None:
                    self.gs.apply_move(defender_seat, block_id)

        # 5. After-blockers priority window
        await self._apnap_priority_window(active_seat, turn_num, "declare_blockers")

        # 6. First-strike damage sub-step (if applicable)
        if self._has_first_strikers():
            # Resolve first-strike damage via engine split method
            if sim.combat and sim.combat.active:
                from commander_ai_lab.sim.engine import GameEngine
                engine = GameEngine()
                engine.resolve_combat_damage(sim, active_seat, sim.combat, first_strike_only=True)
            await self._apnap_priority_window(active_seat, turn_num, "first_strike_damage")

        # 7. Normal combat damage
        if sim.combat and sim.combat.active:
            from commander_ai_lab.sim.engine import GameEngine
            engine = GameEngine()
            engine.resolve_combat_damage(sim, active_seat, sim.combat, first_strike_only=False)

        # 8. End of combat priority window
        await self._apnap_priority_window(active_seat, turn_num, "end_combat")

        # 9. Clear combat state
        sim.combat = None

    async def _phase_cleanup(self, active_seat: int) -> None:
        """Discard to hand size (7), remove end-of-turn effects."""
        player = self.gs.players[active_seat]
        max_hand = 7
        while len(player.hand) > max_hand:
            discarded = player.hand.pop()   # Simplified: discard last
            player.graveyard.append(discarded)
            logger.debug(
                "  [cleanup] %s discarded %s",
                player.name, discarded.name,
            )

    def _has_first_strikers(self) -> bool:
        """Check if any creature in active combat has first_strike or double_strike."""
        sim = self.gs.sim_state
        combat = sim.combat
        if not combat or not combat.active:
            return False
        all_combat_ids = (
            list(combat.attackers.keys()) +
            [bid for blist in combat.blockers.values() for bid in blist]
        )
        for card_id in all_combat_ids:
            card = next((c for bf in sim.battlefields for c in bf if c.id == card_id), None)
            if card and (card.has_keyword("first_strike") or card.has_keyword("double_strike")):
                return True
        return False

    # ── Priority Passing (APNAP) ──────────────────────────────────────────────

    async def _apnap_priority_window(
        self,
        active_seat: int,
        turn_num: int,
        phase: str,
    ) -> None:
        """
        APNAP priority window: Active Player, Non-Active Players in seat order.

        Cycles until all players pass consecutively, or pass_limit is reached.
        AI players may cast instants / activate abilities.
        Human players are skipped (assumed to respond via separate UI flow).
        """
        n = len(self.gs.players)
        # Build APNAP order: active first, then the rest in seat order
        apnap_order = [active_seat] + [
            i for i in range(n)
            if i != active_seat and not self.gs.players[i].eliminated
        ]

        consecutive_passes = 0
        passes_needed = len(apnap_order)
        iterations = 0
        max_iter = passes_needed * self.config.priority_pass_limit

        while consecutive_passes < passes_needed and iterations < max_iter:
            for seat in apnap_order:
                iterations += 1  # Bug 11 fix: always increment iterations
                if self.gs.players[seat].eliminated:
                    consecutive_passes += 1
                    continue

                # Human seats: auto-pass in APNAP window (they act in main phase)
                if seat in self.human_seats:
                    consecutive_passes += 1
                    continue

                # AI instant-speed response
                if seat in self._ai_map:
                    legal = [
                        m for m in self.get_legal_moves(seat)
                        if m.get("category") in ("instant", "activate_ability", "trigger")
                    ]
                    if legal:
                        move_id = await self._get_action(seat, legal, turn_num)
                        if move_id is not None:
                            self.gs.apply_move(seat, move_id)
                            self._total_actions += 1
                            consecutive_passes = 0
                            await self._emit(GameEvent(
                                event_type="action",
                                seat=seat,
                                player_name=self.gs.players[seat].name,
                                phase=phase,
                                turn=turn_num,
                                move_id=move_id,
                                move_description=self._move_desc(move_id, legal),
                                extra={"apnap": True},
                            ))
                            continue

                consecutive_passes += 1

            if iterations >= max_iter:
                logger.debug("APNAP pass limit reached in phase %s", phase)
                break

    # ── AI Decision (off-thread) ──────────────────────────────────────────────

    async def _get_action(
        self,
        seat: int,
        legal_moves: list[dict],
        turn_num: int,
    ) -> Optional[int]:
        """
        Dispatch a decision request to the correct handler:
          - Human seat: await the injected future
          - AI seat: run decide_action() in thread pool
        """
        if seat in self.human_seats:
            return await self._await_human_move(seat)

        if seat in self._ai_map:
            return await self._run_ai_decision(seat, legal_moves)

        # Headless seat (no AI assigned) — pass
        return None

    async def _await_human_move(self, seat: int) -> Optional[int]:
        """Block until human_play() injects a move for this seat."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._human_move_futures[seat] = fut
        try:
            move_id = await asyncio.wait_for(fut, timeout=300.0)  # 5-min timeout
        except asyncio.TimeoutError:
            logger.warning("Human seat %d timed out — passing", seat)
            move_id = None
        finally:
            self._human_move_futures.pop(seat, None)
        return move_id

    async def _run_ai_decision(
        self,
        seat: int,
        legal_moves: list[dict],
    ) -> Optional[int]:
        """
        Run AIOpponent.decide_action() in a thread pool so the event loop
        stays responsive during LLM inference.
        """
        ai = self._ai_map[seat]

        # Signal UI: AI is thinking
        if self.on_thinking:
            await self.on_thinking(seat, True)

        loop = asyncio.get_running_loop()
        t_start = time.monotonic()

        try:
            move_id = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    ai.decide_action,
                    self.gs,
                    legal_moves,
                ),
                timeout=self.config.ai_decision_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[seat %d %s] AI decision timed out after %.1fs — using fallback",
                seat, ai.name, self.config.ai_decision_timeout,
            )
            move_id = ai._heuristic_move(self.gs, legal_moves)
            self._fallback_count += 1
        finally:
            # Signal UI: AI done thinking
            if self.on_thinking:
                await self.on_thinking(seat, False)

        elapsed = time.monotonic() - t_start
        logger.debug("[seat %d %s] decided move=%s in %.2fs", seat, ai.name, move_id, elapsed)

        # Cosmetic delay so humans can follow the AI's play
        if self.config.ai_decision_delay > 0:
            await asyncio.sleep(self.config.ai_decision_delay)

        return move_id

    # ── Eliminations ─────────────────────────────────────────────────────────

    async def _check_eliminations(
        self,
    ) -> None:
        """Detect newly eliminated players and remove from turn queue."""
        for seat, player in enumerate(self.gs.players):
            if player.eliminated and seat in self._turn_queue:
                self._turn_queue.remove(seat)
                logger.info("%s (seat %d) eliminated", player.name, seat)
                await self._emit(GameEvent(
                    event_type="elimination",
                    seat=seat,
                    player_name=player.name,
                    phase=self.gs.current_phase,
                    turn=self.gs.turn,
                    extra={"remaining": list(self._turn_queue)},
                ))

        alive = [i for i in self._turn_queue if not self.gs.players[i].eliminated]
        if len(alive) <= 1:
            self.game_over = True
            self.winner_seat = alive[0] if alive else None
            if self.winner_seat is not None:
                await self._emit(GameEvent(
                    event_type="game_over",
                    seat=self.winner_seat,
                    player_name=self.gs.players[self.winner_seat].name,
                    phase=self.gs.current_phase,
                    turn=self.gs.turn,
                    extra={"winner": self.winner_seat, "reason": "elimination"},
                ))

    # ── Threat Re-evaluation ──────────────────────────────────────────────────

    def _refresh_threat_scores(self, active_seat: int) -> None:
        """Recompute threat scores for all non-eliminated seats."""
        for seat in range(len(self.gs.players)):
            if not self.gs.players[seat].eliminated:
                self._threat_cache[seat] = assess_threats(self.gs, viewer_seat=seat)
        logger.debug(
            "[seat %d] Threat scores refreshed: %s",
            active_seat,
            {s: round(ts[0].total, 3) if ts else 0 for s, ts in self._threat_cache.items()},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _emit(self, event: GameEvent) -> None:
        """Fire the on_event callback if registered."""
        if self.on_event:
            try:
                await self.on_event(event)
            except Exception as exc:
                logger.warning("on_event callback raised: %s", exc)

    @staticmethod
    def _move_desc(move_id: Optional[int], moves: list[dict]) -> str:
        for m in moves:
            if m["id"] == move_id:
                return m.get("description", f"Move {move_id}")
        return f"Move {move_id}"
