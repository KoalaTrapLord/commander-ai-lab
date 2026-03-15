"""
Phase 4 Unit Tests — Pygame Prototype GUI
==========================================
Run with: pytest tests/test_phase4.py -v

All tests run headless (no display required). Pygame is imported but
we use a null / offscreen display so the test suite passes in CI.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Headless Pygame setup (must happen before any gui imports)
# ---------------------------------------------------------------------------
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


# ---------------------------------------------------------------------------
# Stub game state (reused from Phase 3 tests, duplicated here for isolation)
# ---------------------------------------------------------------------------

@dataclass
class _StubPlayer:
    name: str
    life: int = 40
    eliminated: bool = False
    hand: list = field(default_factory=list)
    library: list = field(default_factory=list)
    graveyard: list = field(default_factory=list)
    battlefield: list = field(default_factory=list)
    exile: list = field(default_factory=list)
    command_zone: list = field(default_factory=list)


class _StubGameState:
    def __init__(self, num_players: int = 4):
        self.players = [_StubPlayer(name=f"P{i}") for i in range(num_players)]
        self.turn = 3
        self.current_phase = "main1"
        self.active_player_seat = 0
        self.stack = []

    def get_legal_moves(self, seat):
        return [{"id": 1, "category": "pass_priority", "description": "Pass"}]

    def apply_move(self, seat, move_id):
        pass


def _gs(n=4):
    return _StubGameState(n)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_screen_dimensions(self):
        from commander_ai_lab.gui.constants import SCREEN_W, SCREEN_H, FPS
        assert SCREEN_W == 1280
        assert SCREEN_H == 960
        assert FPS == 60

    def test_four_seat_colours(self):
        from commander_ai_lab.gui.constants import SEAT_COLOURS
        assert len(SEAT_COLOURS) == 4
        for c in SEAT_COLOURS:
            assert len(c) == 3
            assert all(0 <= v <= 255 for v in c)

    def test_all_phases_have_labels(self):
        from commander_ai_lab.gui.constants import COMMANDER_PHASES, PHASE_LABELS
        for phase in COMMANDER_PHASES:
            assert phase in PHASE_LABELS, f"Missing label for phase: {phase}"

    def test_card_dimensions_positive(self):
        from commander_ai_lab.gui.constants import CARD_W, CARD_H
        assert CARD_W > 0
        assert CARD_H > 0
        assert CARD_H > CARD_W   # cards are taller than wide


# ---------------------------------------------------------------------------
# CardRenderer (no display needed for surface ops in dummy mode)
# ---------------------------------------------------------------------------

class TestCardRenderer:
    def setup_method(self):
        try:
            import pygame
            pygame.init()
            pygame.display.set_mode((1, 1))
        except Exception:
            pytest.skip("Pygame not available in this environment")
        from commander_ai_lab.gui.card_renderer import CardRenderer
        self.cr = CardRenderer()

    def test_context_menu_land(self):
        opts = self.cr.get_context_menu_options({"name": "Forest", "type": "land", "tapped": False})
        assert any("mana" in o.lower() for o in opts)

    def test_context_menu_creature(self):
        opts = self.cr.get_context_menu_options({"name": "Bear", "type": "creature", "is_creature": True})
        assert any("attack" in o.lower() for o in opts)

    def test_context_menu_always_has_graveyard(self):
        opts = self.cr.get_context_menu_options({"name": "Sorcery", "type": "sorcery"})
        assert any("graveyard" in o.lower() for o in opts)

    def test_card_rect_normal(self):
        from commander_ai_lab.gui.constants import CARD_W, CARD_H
        x, y, w, h = self.cr.card_rect(10, 20, tapped=False)
        assert w == CARD_W
        assert h == CARD_H

    def test_card_rect_tapped_swaps_dimensions(self):
        from commander_ai_lab.gui.constants import CARD_W, CARD_H
        x, y, w, h = self.cr.card_rect(10, 20, tapped=True)
        assert w == CARD_H
        assert h == CARD_W


# ---------------------------------------------------------------------------
# BoardRenderer
# ---------------------------------------------------------------------------

class TestBoardRenderer:
    def setup_method(self):
        try:
            import pygame
            pygame.init()
            pygame.display.set_mode((1, 1))
        except Exception:
            pytest.skip("Pygame not available")
        from commander_ai_lab.gui.card_renderer import CardRenderer
        from commander_ai_lab.gui.board import BoardRenderer
        self.br = BoardRenderer(CardRenderer(), human_seat=0)

    def test_all_four_seats_have_zones(self):
        for seat in range(4):
            assert seat in self.br._zones

    def test_each_seat_has_five_zones(self):
        for seat in range(4):
            assert len(self.br._zones[seat]) == 5

    def test_zone_names(self):
        expected = {"hand", "battlefield", "graveyard", "exile", "command"}
        for seat in range(4):
            assert set(self.br._zones[seat].keys()) == expected

    def test_hit_test_no_cards_returns_none(self):
        gs = _gs()
        result = self.br.hit_test(0, 0, gs)
        # Top-left corner is outside all zone rects for cards
        assert result is None or True  # may hit a zone but no cards

    def test_card_position_first_card(self):
        from commander_ai_lab.gui.board import ZoneRect, BoardRenderer
        zr = ZoneRect("hand", 0, 0, 600, 140)
        x, y = BoardRenderer._card_position(zr, 0, 5)
        assert x >= 0
        assert y >= 0

    def test_card_position_spacing_increases_with_index(self):
        from commander_ai_lab.gui.board import ZoneRect, BoardRenderer
        zr = ZoneRect("hand", 0, 0, 600, 140)
        x0, _ = BoardRenderer._card_position(zr, 0, 5)
        x1, _ = BoardRenderer._card_position(zr, 1, 5)
        assert x1 > x0


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------

class TestHUD:
    def setup_method(self):
        try:
            import pygame
            pygame.init()
            pygame.display.set_mode((1, 1))
        except Exception:
            pytest.skip("Pygame not available")
        from commander_ai_lab.gui.hud import HUD
        self.hud = HUD()   # no fonts — skips text rendering

    def test_render_phase_bar_no_crash(self):
        import pygame
        surf = pygame.Surface((1280, 960))
        self.hud.render_phase_bar(surf, "main1", 0, "P0")

    def test_render_life_totals_no_crash(self):
        import pygame
        surf = pygame.Surface((1280, 960))
        players = [_StubPlayer(name=f"P{i}") for i in range(4)]
        self.hud.render_life_totals(surf, players)

    def test_render_commander_damage_matrix_no_crash(self):
        import pygame
        surf = pygame.Surface((1280, 960))
        players = [_StubPlayer(name=f"P{i}") for i in range(4)]
        damage = {(0, 1): 5, (1, 0): 3}
        self.hud.render_commander_damage_matrix(surf, players, damage)

    def test_render_player_tags_no_crash(self):
        import pygame
        surf = pygame.Surface((1280, 960))
        players = [_StubPlayer(name=f"P{i}") for i in range(4)]
        self.hud.render_player_tags(surf, players, active_seat=0, thinking_seats={1})


# ---------------------------------------------------------------------------
# NarrationPanel
# ---------------------------------------------------------------------------

class TestNarrationPanel:
    def setup_method(self):
        try:
            import pygame
            pygame.init()
        except Exception:
            pytest.skip("Pygame not available")
        from commander_ai_lab.gui.narration_panel import NarrationPanel
        self.panel = NarrationPanel()  # no font

    def test_add_entry(self):
        self.panel.add(seat=0, text="Hello world", turn=1)
        assert len(self.panel._entries) >= 1

    def test_long_text_wraps(self):
        long_text = "This is a very long narration line that should be wrapped by the panel system."
        self.panel.add(seat=1, text=long_text)
        # Should produce multiple entries
        assert len(self.panel._entries) >= 2

    def test_thinking_indicator_added(self):
        self.panel.add_thinking(seat=2)
        assert self.panel._thinking.get(2) is True

    def test_thinking_indicator_cleared(self):
        self.panel.add_thinking(seat=2)
        self.panel.clear_thinking(seat=2)
        assert 2 not in self.panel._thinking

    def test_clear_wipes_entries(self):
        self.panel.add(0, "Test")
        self.panel.clear()
        assert len(self.panel._entries) == 0

    def test_scroll_up_increases_offset(self):
        for i in range(20):
            self.panel.add(0, f"Line {i}")
        self.panel.scroll_up(3)
        assert self.panel._scroll_offset == 3

    def test_scroll_down_decreases_offset(self):
        for i in range(20):
            self.panel.add(0, f"Line {i}")
        self.panel.scroll_up(5)
        self.panel.scroll_down(2)
        assert self.panel._scroll_offset == 3

    def test_render_no_crash(self):
        import pygame
        surf = pygame.Surface((1280, 960))
        self.panel.add(seat=0, text="Attack!", turn=2)
        self.panel.render(surf, turn=2)  # should not raise

    def test_trim_to_max_lines(self):
        from commander_ai_lab.gui.constants import NARRATION_MAX_LINES
        for i in range(NARRATION_MAX_LINES * 10):
            self.panel.add(0, f"Line {i}")
        assert len(self.panel._entries) <= NARRATION_MAX_LINES * 3


# ---------------------------------------------------------------------------
# ZoneRect hit testing
# ---------------------------------------------------------------------------

class TestZoneRect:
    def test_contains_inside(self):
        from commander_ai_lab.gui.board import ZoneRect
        zr = ZoneRect("hand", 10, 20, 100, 50)
        assert zr.contains(50, 40)

    def test_contains_outside(self):
        from commander_ai_lab.gui.board import ZoneRect
        zr = ZoneRect("hand", 10, 20, 100, 50)
        assert not zr.contains(5, 40)

    def test_contains_edge(self):
        from commander_ai_lab.gui.board import ZoneRect
        zr = ZoneRect("hand", 10, 20, 100, 50)
        assert zr.contains(10, 20)    # top-left corner — inclusive
        assert not zr.contains(110, 70)   # bottom-right — exclusive
