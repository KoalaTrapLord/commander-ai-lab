"""
Commander AI Lab — Board Renderer (Phase 4)
============================================
Layouts and renders the 4-player split-screen board.

Layout (1280 x 960):

    ┌──────────────────────────────────────────────┐
    │         Player 2 (top — opponent)            │
    ├──────────┬───────────────────┬───────────────┤
    │          │   STACK / CENTER  │               │
    │ Player 3 │                   │  Player 1     │
    │  (left)  │                   │  (right)      │
    ├──────────┴───────────────────┴───────────────┤
    │      Player 0 (bottom — human / seat 0)      │
    └──────────────────────────────────────────────┘

Each quadrant contains:
  hand zone | battlefield (creatures / non-creatures) | graveyard | exile | command zone

The narration panel occupies the far right strip (270 px wide).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from commander_ai_lab.gui.constants import (
    SCREEN_W, SCREEN_H,
    CARD_W, CARD_H,
    COLOUR_BG, COLOUR_ZONE_BG, COLOUR_ZONE_BORDER,
    COLOUR_TEXT, COLOUR_TEXT_DIM, COLOUR_HIGHLIGHT,
    COLOUR_ELIMINATED, COLOUR_THINKING,
    SEAT_COLOURS,
    NARRATION_X, NARRATION_W,
    PHASE_BAR_H,
)
from commander_ai_lab.gui.card_renderer import CardRenderer

# Width available to the board (narration panel occupies the right strip)
_BOARD_W = NARRATION_X - 4
# Quadrant dimensions
_TOP_H    = 220
_BOTTOM_H = 220
_MID_H    = SCREEN_H - _TOP_H - _BOTTOM_H - PHASE_BAR_H
_SIDE_W   = 200
_CENTER_W = _BOARD_W - 2 * _SIDE_W


@dataclass
class ZoneRect:
    """Pixel rectangle for a named zone."""
    name: str
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


@dataclass
class CardHit:
    """Result of a click hit-test: which card in which zone."""
    seat: int
    zone: str          # 'hand', 'battlefield', 'graveyard', 'exile', 'command'
    card_index: int    # index in the list
    card: dict


class BoardRenderer:
    """
    Manages zone layout and renders the full 4-player board each frame.

    Parameters
    ----------
    card_renderer : CardRenderer
        Shared card drawing helper.
    human_seat : int
        Seat whose hand is shown face-up (bottom quadrant).
    """

    # Seat -> screen quadrant mapping
    # seat 0 = bottom, 1 = right, 2 = top, 3 = left
    _SEAT_QUADRANT = {0: "bottom", 1: "right", 2: "top", 3: "left"}

    def __init__(
        self,
        card_renderer: CardRenderer,
        human_seat: int = 0,
    ) -> None:
        self.cr = card_renderer
        self.human_seat = human_seat

        # Highlighted card (legal target indicator)
        self._highlighted: Optional[CardHit] = None
        # Selected card in hand (waiting for target)
        self._selected: Optional[CardHit] = None

        # Zone rects computed once
        self._zones: dict[int, dict[str, ZoneRect]] = {}
        self._build_zones()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        surface,
        game_state,
        active_seat: int,
        thinking_seats: set[int],
        highlighted_cards: set[tuple] | None = None,  # {(seat, zone, idx)}
    ) -> None:
        """
        Render the full board onto surface for the current frame.

        Args:
            surface:          Main pygame display surface.
            game_state:       CommanderGameState (or compatible stub).
            active_seat:      Seat whose turn it is (highlighted border).
            thinking_seats:   Set of seat indices currently running AI inference.
            highlighted_cards: Cards to show with a highlight ring.
        """
        if not _PYGAME_AVAILABLE:
            return

        highlighted_cards = highlighted_cards or set()
        surface.fill(COLOUR_BG)

        for seat, player in enumerate(game_state.players):
            self._render_player_zones(
                surface, seat, player, active_seat,
                thinking_seats, highlighted_cards,
            )

        self._render_stack_zone(surface, game_state)
        self._render_center_dividers(surface)

    def hit_test(
        self,
        px: int,
        py: int,
        game_state,
    ) -> Optional[CardHit]:
        """
        Return the CardHit under pixel (px, py), or None.
        Used by the input handler to resolve clicks.
        """
        for seat, zones in self._zones.items():
            player = game_state.players[seat]
            for zone_name, zone_rect in zones.items():
                if not zone_rect.contains(px, py):
                    continue
                cards = self._get_zone_cards(player, zone_name)
                idx = self._card_index_at(px, py, zone_rect, cards)
                if idx is not None:
                    return CardHit(
                        seat=seat,
                        zone=zone_name,
                        card_index=idx,
                        card=cards[idx],
                    )
        return None

    def set_highlighted(self, hit: Optional[CardHit]) -> None:
        self._highlighted = hit

    def set_selected(self, hit: Optional[CardHit]) -> None:
        self._selected = hit

    # ------------------------------------------------------------------
    # Zone Layout
    # ------------------------------------------------------------------

    def _build_zones(self) -> None:
        """Pre-compute zone rects for all 4 seats."""
        # seat 0: bottom quadrant
        self._zones[0] = self._zones_for_bottom()
        # seat 1: right quadrant
        self._zones[1] = self._zones_for_right()
        # seat 2: top quadrant
        self._zones[2] = self._zones_for_top()
        # seat 3: left quadrant
        self._zones[3] = self._zones_for_left()

    def _zones_for_bottom(self) -> dict[str, ZoneRect]:
        y_bf   = SCREEN_H - _BOTTOM_H - PHASE_BAR_H
        y_hand = SCREEN_H - CARD_H - 20 - PHASE_BAR_H
        return {
            "battlefield": ZoneRect("battlefield", _SIDE_W, y_bf,       _CENTER_W, _BOTTOM_H - CARD_H - 24),
            "hand":        ZoneRect("hand",        0,       y_hand,     _BOARD_W - CARD_W * 2 - 8, CARD_H + 8),
            "graveyard":   ZoneRect("graveyard",   _BOARD_W - CARD_W * 2 - 4, y_bf,   CARD_W + 4, CARD_H + 4),
            "exile":       ZoneRect("exile",       _BOARD_W - CARD_W - 2,     y_bf,   CARD_W + 2, CARD_H + 4),
            "command":     ZoneRect("command",     _BOARD_W - CARD_W - 2,     y_hand, CARD_W + 2, CARD_H + 4),
        }

    def _zones_for_top(self) -> dict[str, ZoneRect]:
        return {
            "battlefield": ZoneRect("battlefield", _SIDE_W, PHASE_BAR_H + 8,  _CENTER_W, _TOP_H - CARD_H - 16),
            "hand":        ZoneRect("hand",        _SIDE_W, PHASE_BAR_H + _TOP_H - CARD_H - 8, _CENTER_W, CARD_H + 8),
            "graveyard":   ZoneRect("graveyard",   _BOARD_W - CARD_W - 2, PHASE_BAR_H + 4, CARD_W + 2, CARD_H + 4),
            "exile":       ZoneRect("exile",       _BOARD_W - CARD_W * 2 - 4, PHASE_BAR_H + 4, CARD_W + 4, CARD_H + 4),
            "command":     ZoneRect("command",     4, PHASE_BAR_H + 4, CARD_W + 2, CARD_H + 4),
        }

    def _zones_for_left(self) -> dict[str, ZoneRect]:
        mid_y = _TOP_H + PHASE_BAR_H
        return {
            "battlefield": ZoneRect("battlefield", 4,              mid_y,          _SIDE_W - 4, _MID_H),
            "hand":        ZoneRect("hand",        4,              mid_y + _MID_H - CARD_H - 8, _SIDE_W - 4, CARD_H + 8),
            "graveyard":   ZoneRect("graveyard",   4,              mid_y + 4,      CARD_W + 2,  CARD_H + 4),
            "exile":       ZoneRect("exile",       CARD_W + 8,    mid_y + 4,      CARD_W + 2,  CARD_H + 4),
            "command":     ZoneRect("command",     4,              mid_y + CARD_H + 12, CARD_W + 2, CARD_H + 4),
        }

    def _zones_for_right(self) -> dict[str, ZoneRect]:
        mid_y = _TOP_H + PHASE_BAR_H
        rx    = _BOARD_W - _SIDE_W + 4
        return {
            "battlefield": ZoneRect("battlefield", rx,             mid_y,          _SIDE_W - 8, _MID_H),
            "hand":        ZoneRect("hand",        rx,             mid_y + _MID_H - CARD_H - 8, _SIDE_W - 8, CARD_H + 8),
            "graveyard":   ZoneRect("graveyard",   rx,             mid_y + 4,      CARD_W + 2,  CARD_H + 4),
            "exile":       ZoneRect("exile",       rx + CARD_W + 4, mid_y + 4,    CARD_W + 2,  CARD_H + 4),
            "command":     ZoneRect("command",     rx,             mid_y + CARD_H + 12, CARD_W + 2, CARD_H + 4),
        }

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_player_zones(
        self,
        surface,
        seat: int,
        player,
        active_seat: int,
        thinking_seats: set[int],
        highlighted_cards: set,
    ) -> None:
        import pygame
        seat_col  = SEAT_COLOURS[seat % len(SEAT_COLOURS)]
        is_active = (seat == active_seat)
        is_elim   = getattr(player, "eliminated", False)
        is_think  = seat in thinking_seats

        zones = self._zones.get(seat, {})

        for zone_name, zr in zones.items():
            bg_col     = COLOUR_ZONE_BG
            border_col = COLOUR_ELIMINATED if is_elim else (
                COLOUR_THINKING if is_think else (
                    seat_col if is_active else COLOUR_ZONE_BORDER
                )
            )
            border_w = 2 if is_active or is_think else 1

            rect = pygame.Rect(zr.x, zr.y, zr.w, zr.h)
            pygame.draw.rect(surface, bg_col, rect, border_radius=4)
            pygame.draw.rect(surface, border_col, rect, width=border_w, border_radius=4)

            # Zone label
            # (font rendering omitted here — HUD handles text labels)

            # Draw cards
            cards = self._get_zone_cards(player, zone_name)
            face_up = (seat == self.human_seat or zone_name in ("battlefield", "graveyard", "command"))

            for idx, card in enumerate(cards):
                cx, cy = self._card_position(zr, idx, len(cards))
                is_hl  = (seat, zone_name, idx) in highlighted_cards

                if face_up:
                    self.cr.draw_card(surface, card, cx, cy, highlighted=is_hl)
                else:
                    self.cr.draw_card_back(surface, cx, cy, label=str(len(cards)))
                    break  # only draw one face-down back per hidden hand

        # Player name tag
        # (rendered by HUD.render_player_tags)

    def _render_stack_zone(self, surface, game_state) -> None:
        """Render the stack in the center of the board."""
        import pygame
        from commander_ai_lab.gui.constants import (
            ZONE_STACK_X, ZONE_STACK_Y, ZONE_STACK_W,
        )
        stack = getattr(game_state, "stack", [])
        if not stack:
            return
        rect = pygame.Rect(ZONE_STACK_X, ZONE_STACK_Y, ZONE_STACK_W, min(len(stack) * 20 + 16, 180))
        pygame.draw.rect(surface, COLOUR_ZONE_BG, rect, border_radius=4)
        pygame.draw.rect(surface, COLOUR_HIGHLIGHT, rect, width=2, border_radius=4)

    def _render_center_dividers(self, surface) -> None:
        """Draw subtle lines separating the four quadrants."""
        import pygame
        col = COLOUR_ZONE_BORDER
        # Horizontal dividers
        y_top_end = _TOP_H + PHASE_BAR_H
        y_bot_start = SCREEN_H - _BOTTOM_H - PHASE_BAR_H
        pygame.draw.line(surface, col, (0, y_top_end),   (_BOARD_W, y_top_end),   1)
        pygame.draw.line(surface, col, (0, y_bot_start), (_BOARD_W, y_bot_start), 1)
        # Vertical dividers
        pygame.draw.line(surface, col, (_SIDE_W, y_top_end),   (_SIDE_W, y_bot_start),   1)
        pygame.draw.line(surface, col, (_BOARD_W - _SIDE_W, y_top_end), (_BOARD_W - _SIDE_W, y_bot_start), 1)

    # ------------------------------------------------------------------
    # Card positioning within a zone
    # ------------------------------------------------------------------

    @staticmethod
    def _card_position(zone_rect: ZoneRect, idx: int, total: int) -> tuple[int, int]:
        """Compute pixel position for card at index idx in a zone."""
        if total == 0:
            return zone_rect.x + 4, zone_rect.y + 4
        spacing = min(CARD_W + 6, max(20, (zone_rect.w - 8) // max(total, 1)))
        x = zone_rect.x + 4 + idx * spacing
        y = zone_rect.y + 4
        return x, y

    @staticmethod
    def _card_index_at(px: int, py: int, zone_rect: ZoneRect, cards: list) -> Optional[int]:
        """Return the card index at pixel position, or None."""
        if not cards:
            return None
        total   = len(cards)
        spacing = min(CARD_W + 6, max(20, (zone_rect.w - 8) // max(total, 1)))
        for idx in reversed(range(total)):   # top-most card first
            cx = zone_rect.x + 4 + idx * spacing
            cy = zone_rect.y + 4
            if cx <= px < cx + CARD_W and cy <= py < cy + CARD_H:
                return idx
        return None

    @staticmethod
    def _get_zone_cards(player, zone_name: str) -> list:
        mapping = {
            "hand":        "hand",
            "battlefield": "battlefield",
            "graveyard":   "graveyard",
            "exile":       "exile",
            "command":     "command_zone",
        }
        attr = mapping.get(zone_name, zone_name)
        return getattr(player, attr, []) or []
