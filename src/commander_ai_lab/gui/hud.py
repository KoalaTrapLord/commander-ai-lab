"""
Commander AI Lab — HUD (Phase 4)
=================================
Renders the phase/step indicator bar, life total trackers,
4-player commander damage matrix, and player name tags.
"""

from __future__ import annotations

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from commander_ai_lab.gui.constants import (
    SCREEN_W, SCREEN_H, PHASE_BAR_H,
    COMMANDER_PHASES, PHASE_LABELS,
    COLOUR_PHASE_BAR, COLOUR_PHASE_ACTIVE, COLOUR_TEXT, COLOUR_TEXT_DIM,
    COLOUR_LIFE_HIGH, COLOUR_LIFE_MED, COLOUR_LIFE_LOW,
    COLOUR_ELIMINATED, COLOUR_THINKING, COLOUR_BG,
    SEAT_COLOURS, NARRATION_X,
    LIFE_PANEL_W, LIFE_PANEL_H,
)

_BOARD_W = NARRATION_X - 4


class HUD:
    """
    Draws all HUD elements onto the display surface.

    Parameters
    ----------
    font_small, font_med, font_large : pygame.font.Font | None
        Pass pre-loaded fonts; None falls back to system default.
    """

    def __init__(self, font_small=None, font_med=None, font_large=None) -> None:
        self._fs = font_small
        self._fm = font_med
        self._fl = font_large

    # ------------------------------------------------------------------
    # Public render methods
    # ------------------------------------------------------------------

    def render_phase_bar(
        self,
        surface,
        current_phase: str,
        active_seat: int,
        player_name: str,
    ) -> None:
        """
        Draw the phase / step indicator bar at the very top of the screen.
        Highlights the current phase, shows active player name on the left.
        """
        if not _PYGAME_AVAILABLE:
            return
        import pygame

        bar_rect = pygame.Rect(0, 0, _BOARD_W, PHASE_BAR_H)
        pygame.draw.rect(surface, COLOUR_PHASE_BAR, bar_rect)

        # Active player label
        seat_col = SEAT_COLOURS[active_seat % len(SEAT_COLOURS)]
        if self._fs:
            lbl = self._fs.render(f"{player_name}", True, seat_col)
            surface.blit(lbl, (6, (PHASE_BAR_H - lbl.get_height()) // 2))

        # Phase tabs
        total_phases = len(COMMANDER_PHASES)
        tab_w = (_BOARD_W - 90) // total_phases
        for i, phase in enumerate(COMMANDER_PHASES):
            tx   = 90 + i * tab_w
            trect = pygame.Rect(tx, 0, tab_w - 2, PHASE_BAR_H)
            is_active_phase = (phase == current_phase)
            bg = COLOUR_PHASE_ACTIVE if is_active_phase else COLOUR_PHASE_BAR
            pygame.draw.rect(surface, bg, trect, border_radius=3)
            if self._fs:
                label = PHASE_LABELS.get(phase, phase)
                col   = COLOUR_TEXT if is_active_phase else COLOUR_TEXT_DIM
                txt   = self._fs.render(label[:8], True, col)
                surface.blit(txt, (tx + 3, (PHASE_BAR_H - txt.get_height()) // 2))

    def render_life_totals(
        self,
        surface,
        players: list,
    ) -> None:
        """
        Draw life total boxes in the four corners of the board.
        Corner positions match seat quadrant positions.
        """
        if not _PYGAME_AVAILABLE:
            return
        import pygame

        # Corner positions: (x, y) per seat
        corners = {
            0: (_BOARD_W - LIFE_PANEL_W - 4, SCREEN_H - LIFE_PANEL_H - 4),  # bottom-right
            1: (_BOARD_W - LIFE_PANEL_W - 4, SCREEN_H // 2 - LIFE_PANEL_H // 2),  # right-mid
            2: (_BOARD_W - LIFE_PANEL_W - 4, PHASE_BAR_H + 4),                    # top-right
            3: (4, SCREEN_H // 2 - LIFE_PANEL_H // 2),                            # left-mid
        }

        for seat, player in enumerate(players):
            if seat not in corners:
                continue
            cx, cy = corners[seat]
            life   = getattr(player, "life", 40)
            elim   = getattr(player, "eliminated", False)
            name   = getattr(player, "name", f"P{seat}")

            # Life colour
            if elim:
                life_col = COLOUR_ELIMINATED
            elif life >= 30:
                life_col = COLOUR_LIFE_HIGH
            elif life >= 15:
                life_col = COLOUR_LIFE_MED
            else:
                life_col = COLOUR_LIFE_LOW

            panel = pygame.Rect(cx, cy, LIFE_PANEL_W, LIFE_PANEL_H)
            pygame.draw.rect(surface, (22, 26, 40), panel, border_radius=6)
            pygame.draw.rect(surface, SEAT_COLOURS[seat % len(SEAT_COLOURS)], panel, width=2, border_radius=6)

            if self._fl:
                life_txt = self._fl.render(str(life), True, life_col)
                surface.blit(life_txt, (cx + 10, cy + 10))
            if self._fs:
                name_txt = self._fs.render(name[:12], True, COLOUR_TEXT_DIM)
                surface.blit(name_txt, (cx + 6, cy + LIFE_PANEL_H - 20))

    def render_commander_damage_matrix(
        self,
        surface,
        players: list,
        commander_damage: dict,  # {(dealer_seat, receiver_seat): int}
    ) -> None:
        """
        Draw the 4x4 commander damage grid.
        Rows = damage dealer, columns = damage receiver.
        Positioned in the center-bottom of the board.
        """
        if not _PYGAME_AVAILABLE or not self._fs:
            return
        import pygame

        n    = len(players)
        cell = 28
        ox   = (_BOARD_W - n * cell - 30) // 2
        oy   = SCREEN_H - PHASE_BAR_H - n * cell - 40

        # Header labels
        for i, player in enumerate(players):
            col  = SEAT_COLOURS[i % len(SEAT_COLOURS)]
            lbl  = self._fs.render(f"P{i}", True, col)
            surface.blit(lbl, (ox + 32 + i * cell, oy - 16))
            surface.blit(lbl, (ox + 4,  oy + i * cell))

        # Cells
        for dealer in range(n):
            for recv in range(n):
                if dealer == recv:
                    continue
                dmg  = commander_damage.get((dealer, recv), 0)
                rect = pygame.Rect(ox + 32 + recv * cell, oy + dealer * cell, cell - 2, cell - 2)
                bg   = (60, 20, 20) if dmg >= 21 else (28, 32, 48)
                pygame.draw.rect(surface, bg, rect, border_radius=3)
                pygame.draw.rect(surface, COLOUR_ZONE_BORDER, rect, width=1, border_radius=3)
                if dmg > 0:
                    col  = (255, 80, 80) if dmg >= 21 else COLOUR_TEXT_DIM
                    txt  = self._fs.render(str(dmg), True, col)
                    surface.blit(txt, (rect.x + 6, rect.y + 6))

    def render_player_tags(
        self,
        surface,
        players: list,
        active_seat: int,
        thinking_seats: set[int],
    ) -> None:
        """Render player name tags near each quadrant."""
        if not _PYGAME_AVAILABLE or not self._fm:
            return
        import pygame

        tag_positions = {
            0: (4, SCREEN_H - PHASE_BAR_H - 20),
            1: (_BOARD_W - 130, SCREEN_H // 2),
            2: (4, PHASE_BAR_H + 4),
            3: (4, SCREEN_H // 2),
        }

        for seat, player in enumerate(players):
            if seat not in tag_positions:
                continue
            tx, ty = tag_positions[seat]
            name   = getattr(player, "name", f"P{seat}")
            elim   = getattr(player, "eliminated", False)
            col    = COLOUR_ELIMINATED if elim else (
                COLOUR_THINKING if seat in thinking_seats else
                SEAT_COLOURS[seat % len(SEAT_COLOURS)]
            )
            think_sfx = " [thinking...]" if seat in thinking_seats else ""
            tag = self._fm.render(f"{name}{think_sfx}", True, col)
            surface.blit(tag, (tx, ty))
