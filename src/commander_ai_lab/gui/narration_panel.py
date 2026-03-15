"""
Commander AI Lab — Narration Panel (Phase 4)
=============================================
Scrolling log panel (right-side strip) that shows AI flavor text,
game events, and phase transitions in a chat-style feed.

Features:
  - Colour-coded by player seat
  - Auto-scrolls to latest message
  - Capped at NARRATION_MAX_LINES to avoid overflow
  - "AI is thinking..." animated indicator for active inference seats
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from commander_ai_lab.gui.constants import (
    SCREEN_H, NARRATION_X, NARRATION_Y, NARRATION_W, NARRATION_H,
    NARRATION_MAX_LINES,
    COLOUR_NARRATION_BG, COLOUR_TEXT, COLOUR_TEXT_DIM,
    COLOUR_THINKING, COLOUR_ZONE_BORDER,
    SEAT_COLOURS,
)


@dataclass
class NarrationEntry:
    seat: int
    text: str
    is_thinking: bool = False
    turn: int = 0


class NarrationPanel:
    """
    Scrolling AI narration / event log panel.

    Usage::

        panel = NarrationPanel(font_small=font)
        panel.add(seat=1, text="Timmy attacks with everything!")
        panel.add_thinking(seat=2)    # show spinner
        panel.clear_thinking(seat=2)  # remove spinner when done
        panel.render(surface)
    """

    def __init__(self, font_small=None) -> None:
        self._font = font_small
        self._entries: list[NarrationEntry] = []
        self._thinking: dict[int, bool] = {}   # seat -> thinking flag
        self._scroll_offset: int = 0
        self._anim_tick: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        seat: int,
        text: str,
        turn: int = 0,
        is_event: bool = False,
    ) -> None:
        """
        Append a narration or event line.

        Args:
            seat:     Seat index (0–3) for colour coding. Use -1 for system events.
            text:     Line text. Long lines are auto-wrapped.
            turn:     Current game turn (shown as prefix).
            is_event: True for phase/system events (shown dimmer).
        """
        # Word-wrap to fit panel width
        for line in self._wrap(text, max_chars=32):
            self._entries.append(NarrationEntry(
                seat=seat,
                text=line,
                is_thinking=False,
                turn=turn,
            ))

        # Trim to max lines
        if len(self._entries) > NARRATION_MAX_LINES * 3:
            self._entries = self._entries[-(NARRATION_MAX_LINES * 3):]

        # Auto-scroll to bottom
        self._scroll_to_bottom()

    def add_thinking(
        self,
        seat: int,
    ) -> None:
        """Show 'thinking...' animation for seat."""
        self._thinking[seat] = True

    def clear_thinking(
        self,
        seat: int,
    ) -> None:
        """Remove thinking indicator for seat."""
        self._thinking.pop(seat, None)

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()
        self._thinking.clear()
        self._scroll_offset = 0

    def render(
        self,
        surface,
        turn: int = 0,
    ) -> None:
        """
        Render the narration panel onto the display surface.
        Call once per frame from the main game loop.
        """
        if not _PYGAME_AVAILABLE:
            return
        import pygame
        self._anim_tick += 1

        panel_rect = pygame.Rect(NARRATION_X, NARRATION_Y, NARRATION_W, NARRATION_H)
        pygame.draw.rect(surface, COLOUR_NARRATION_BG, panel_rect, border_radius=6)
        pygame.draw.rect(surface, COLOUR_ZONE_BORDER, panel_rect, width=1, border_radius=6)

        if not self._font:
            return

        line_h  = self._font.get_linesize() + 2
        visible = NARRATION_H // line_h
        start   = max(0, len(self._entries) - visible - self._scroll_offset)
        shown   = self._entries[start: start + visible]

        y = NARRATION_Y + 6
        for entry in shown:
            col = SEAT_COLOURS[entry.seat % len(SEAT_COLOURS)] if entry.seat >= 0 else COLOUR_TEXT_DIM
            txt = self._font.render(entry.text[:36], True, col)
            surface.blit(txt, (NARRATION_X + 6, y))
            y += line_h

        # Thinking indicators (animated dots)
        for seat, is_thinking in self._thinking.items():
            if not is_thinking:
                continue
            dots = "." * ((self._anim_tick // 20) % 4)
            p_name = f"P{seat}"
            think_txt = self._font.render(
                f"{p_name} thinking{dots}", True, COLOUR_THINKING
            )
            surface.blit(think_txt, (NARRATION_X + 6, y))
            y += line_h

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self) -> None:
        self._scroll_offset = 0

    def scroll_up(self, lines: int = 3) -> None:
        self._scroll_offset = min(
            self._scroll_offset + lines,
            max(0, len(self._entries) - 1),
        )

    def scroll_down(self, lines: int = 3) -> None:
        self._scroll_offset = max(0, self._scroll_offset - lines)

    @staticmethod
    def _wrap(text: str, max_chars: int) -> list[str]:
        """Simple word-wrap to max_chars per line."""
        words  = text.split()
        lines  = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= max_chars:
                current = (current + " " + word).strip()
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [text[:max_chars]]
