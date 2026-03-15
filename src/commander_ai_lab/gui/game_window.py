"""
Commander AI Lab — GameWindow (Phase 4)
========================================
Top-level Pygame application class.

Responsibilities:
  - Initialise Pygame display, fonts, clock
  - Own the main game loop (run())
  - Bridge between CommanderTurnManager events and GUI components
  - Handle human player input (click-to-play, right-click context menu)
  - Show end-of-game summary screen with win condition + final stats

Usage (blocking, runs until window closes)::

    from commander_ai_lab.gui.game_window import GameWindow
    from commander_ai_lab.sim.ai_opponent import create_four_player_ai_roster
    from commander_ai_lab.sim.game_state  import CommanderGameState

    gs        = CommanderGameState(...)         # build your game state
    ai_roster = create_four_player_ai_roster()

    window = GameWindow(game_state=gs, ai_opponents=ai_roster, human_seat=0)
    window.run()   # blocks until game over or window closed
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from commander_ai_lab.gui.constants import (
    SCREEN_W, SCREEN_H, FPS, TITLE,
    COLOUR_BG, COLOUR_TEXT, COLOUR_TEXT_DIM, COLOUR_HIGHLIGHT,
    SEAT_COLOURS, NARRATION_X, NARRATION_W,
)
from commander_ai_lab.gui.board          import BoardRenderer
from commander_ai_lab.gui.card_renderer  import CardRenderer
from commander_ai_lab.gui.hud            import HUD
from commander_ai_lab.gui.narration_panel import NarrationPanel
from commander_ai_lab.sim.turn_manager   import CommanderTurnManager, GameEvent, TurnManagerConfig


class GameWindow:
    """
    Main Pygame application window for Commander AI Lab.

    Parameters
    ----------
    game_state :    CommanderGameState — mutable game state.
    ai_opponents :  List of AIOpponent instances (Phase 2).
    human_seat :    Seat index for the human player (default 0).
                    Pass None for a fully AI game.
    config :        TurnManagerConfig for the turn manager.
    """

    def __init__(
        self,
        game_state,
        ai_opponents: list,
        human_seat: Optional[int] = 0,
        config: Optional[TurnManagerConfig] = None,
    ) -> None:
        self.gs            = game_state
        self.human_seat    = human_seat
        self._ai_opponents = ai_opponents
        self._config       = config or TurnManagerConfig(ai_decision_delay=1.0)

        # Turn manager
        human_seats = {human_seat} if human_seat is not None else set()
        self._tm = CommanderTurnManager(
            game_state=game_state,
            ai_opponents=ai_opponents,
            human_seats=human_seats,
            on_event=self._on_game_event,
            on_thinking=self._on_thinking,
            config=self._config,
        )

        # GUI state
        self._thinking_seats: set[int] = set()
        self._highlighted_cards: set   = set()
        self._selected_card            = None
        self._context_menu             = None   # (x, y, options)
        self._game_over_info: Optional[dict] = None

        # Pygame objects (initialised in run())
        self._screen  = None
        self._clock   = None
        self._board   = None
        self._hud     = None
        self._narration = None
        self._cr        = None

        # Commander damage matrix: {(dealer, receiver): int}
        self._cmd_damage: dict[tuple, int] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Initialise Pygame and run the main loop (blocking)."""
        if not _PYGAME_AVAILABLE:
            raise RuntimeError(
                "Pygame is not installed. Run: pip install pygame"
            )

        pygame.init()
        pygame.display.set_caption(TITLE)
        self._screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self._clock  = pygame.time.Clock()

        # Fonts
        font_small = pygame.font.SysFont("segoeui",  11)
        font_med   = pygame.font.SysFont("segoeui",  13)
        font_large = pygame.font.SysFont("segoeui",  28, bold=True)

        # GUI components
        self._cr      = CardRenderer(font_small=font_small, font_med=font_med)
        self._board   = BoardRenderer(card_renderer=self._cr, human_seat=self.human_seat or 0)
        self._hud     = HUD(font_small=font_small, font_med=font_med, font_large=font_large)
        self._narration = NarrationPanel(font_small=font_small)

        # Start the async turn manager in a background thread
        self._loop = asyncio.new_event_loop()
        self._game_thread = threading.Thread(
            target=self._run_game_loop_async,
            daemon=True,
        )
        self._game_thread.start()

        # Main render loop
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self._handle_mouse_click(event)
                elif event.type == pygame.MOUSEWHEEL:
                    if event.y > 0:
                        self._narration.scroll_up()
                    else:
                        self._narration.scroll_down()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

            self._render_frame()
            self._clock.tick(FPS)

        pygame.quit()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_frame(self) -> None:
        if self._game_over_info:
            self._render_game_over_screen()
            return

        # Board
        self._board.render(
            self._screen,
            self.gs,
            active_seat=self.gs.active_player_seat,
            thinking_seats=self._thinking_seats,
            highlighted_cards=self._highlighted_cards,
        )

        # HUD
        self._hud.render_phase_bar(
            self._screen,
            current_phase=self.gs.current_phase,
            active_seat=self.gs.active_player_seat,
            player_name=self.gs.players[self.gs.active_player_seat].name,
        )
        self._hud.render_life_totals(self._screen, self.gs.players)
        self._hud.render_commander_damage_matrix(
            self._screen, self.gs.players, self._cmd_damage,
        )
        self._hud.render_player_tags(
            self._screen, self.gs.players,
            self.gs.active_player_seat, self._thinking_seats,
        )

        # Narration panel
        self._narration.render(self._screen, turn=self.gs.turn)

        # Context menu (right-click)
        if self._context_menu:
            self._render_context_menu()

        pygame.display.flip()

    def _render_game_over_screen(self) -> None:
        """Full-screen game over summary."""
        import pygame
        self._screen.fill(COLOUR_BG)
        info = self._game_over_info or {}
        winner_seat = info.get("winner", 0)
        reason      = info.get("reason", "")

        font_title  = pygame.font.SysFont("segoeui", 48, bold=True)
        font_body   = pygame.font.SysFont("segoeui", 20)
        font_small  = pygame.font.SysFont("segoeui", 14)

        winner_name = self.gs.players[winner_seat].name if winner_seat is not None else "Draw"
        col = SEAT_COLOURS[winner_seat % len(SEAT_COLOURS)] if winner_seat is not None else COLOUR_TEXT

        title = font_title.render(f"{winner_name} wins!", True, col)
        self._screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 140))

        sub = font_body.render(f"by {reason}", True, COLOUR_TEXT_DIM)
        self._screen.blit(sub, (SCREEN_W // 2 - sub.get_width() // 2, 200))

        # Final stats per player
        y = 270
        for seat, player in enumerate(self.gs.players):
            name    = player.name
            life    = player.life
            elim    = player.eliminated
            stat_col = COLOUR_TEXT_DIM if elim else SEAT_COLOURS[seat % len(SEAT_COLOURS)]
            row = font_body.render(
                f"{'[ELIM] ' if elim else '       '}P{seat} {name:<16} Life: {life:>3}",
                True, stat_col,
            )
            self._screen.blit(row, (SCREEN_W // 2 - 200, y))
            y += 30

        hint = font_small.render("Press ESC to exit", True, COLOUR_TEXT_DIM)
        self._screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, y + 30))

        pygame.display.flip()

    def _render_context_menu(
        self,
    ) -> None:
        """Draw right-click context menu."""
        import pygame
        if not self._context_menu:
            return
        x, y, options = self._context_menu
        font = pygame.font.SysFont("segoeui", 13)
        item_h = 22
        w = 180
        bg = pygame.Rect(x, y, w, item_h * len(options) + 8)
        pygame.draw.rect(self._screen, (30, 35, 50), bg, border_radius=4)
        pygame.draw.rect(self._screen, COLOUR_HIGHLIGHT, bg, width=1, border_radius=4)
        for i, opt in enumerate(options):
            txt = font.render(opt, True, COLOUR_TEXT)
            self._screen.blit(txt, (x + 6, y + 4 + i * item_h))

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _handle_mouse_click(self, event) -> None:
        import pygame
        px, py = event.pos

        # Dismiss context menu on any click
        if self._context_menu:
            self._context_menu = None
            return

        hit = self._board.hit_test(px, py, self.gs)
        if hit is None:
            return

        if event.button == 3:   # right-click
            options = self._cr.get_context_menu_options(hit.card)
            self._context_menu = (px, py, options)
            return

        # Left-click: human play flow
        if self.human_seat is not None and hit.seat == self.human_seat:
            if hit.zone == "hand":
                # Select card → highlight legal targets
                if self._selected_card and self._selected_card.card_index == hit.card_index:
                    # Confirm: inject move into turn manager
                    legal = self._tm.get_legal_moves(self.human_seat)
                    move_id = self._find_move_for_card(hit.card, legal)
                    if move_id is not None:
                        asyncio.run_coroutine_threadsafe(
                            self._tm.human_play(move_id), self._loop
                        )
                    self._selected_card = None
                    self._highlighted_cards.clear()
                else:
                    # First click: select + highlight
                    self._selected_card = hit
                    self._board.set_selected(hit)
                    self._highlighted_cards = self._compute_legal_targets(hit)

    @staticmethod
    def _find_move_for_card(card: dict, legal_moves: list) -> Optional[int]:
        """Match a hand card to a legal move by name."""
        name = card.get("name", "").lower()
        for m in legal_moves:
            if name in m.get("description", "").lower():
                return m["id"]
        return legal_moves[0]["id"] if legal_moves else None

    def _compute_legal_targets(
        self,
        selected: object,
    ) -> set:
        """Return set of (seat, zone, idx) tuples for legal targets."""
        # Simplified: highlight all opponent battlefield cards as targets
        targets = set()
        if self.human_seat is None:
            return targets
        for seat, player in enumerate(self.gs.players):
            if seat == self.human_seat:
                continue
            for idx in range(len(getattr(player, "battlefield", []))):
                targets.add((seat, "battlefield", idx))
        return targets

    # ------------------------------------------------------------------
    # Async game loop (runs in background thread)
    # ------------------------------------------------------------------

    def _run_game_loop_async(self) -> None:
        """Run the turn manager coroutine in a dedicated event loop thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._tm.run_game())

    # ------------------------------------------------------------------
    # Turn manager callbacks
    # ------------------------------------------------------------------

    async def _on_game_event(self, event: GameEvent) -> None:
        """Handle game events from the turn manager."""
        if event.event_type == "game_over":
            self._game_over_info = event.extra

        elif event.event_type == "action" and event.narration:
            self._narration.add(
                seat=event.seat,
                text=f"{event.player_name}: {event.narration}",
                turn=event.turn,
            )

        elif event.event_type == "phase_change":
            self._narration.add(
                seat=-1,
                text=f"T{event.turn} {event.player_name} — {event.phase}",
                turn=event.turn,
            )

        elif event.event_type == "elimination":
            self._narration.add(
                seat=event.seat,
                text=f"{event.player_name} has been eliminated!",
                turn=event.turn,
            )

    async def _on_thinking(self, seat: int, is_thinking: bool) -> None:
        """Show / hide the AI thinking indicator."""
        if is_thinking:
            self._thinking_seats.add(seat)
            self._narration.add_thinking(seat)
        else:
            self._thinking_seats.discard(seat)
            self._narration.clear_thinking(seat)
