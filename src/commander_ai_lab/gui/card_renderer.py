"""
Commander AI Lab — Card Renderer (Phase 4)
==========================================
Draws individual cards onto a Pygame surface.

Features:
  - Tapped / untapped state (rotated 90 degrees)
  - Name, P/T or loyalty, mana cost text
  - Highlight ring (legal target indicator)
  - Scryfall art placeholder (grey box + card name until image loads)
  - Async art loading via a shared image cache (non-blocking)
  - Right-click context menu data (returned as list of option strings,
    rendered by the caller)
"""

from __future__ import annotations

import threading
from typing import Optional

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from commander_ai_lab.gui.constants import (
    CARD_W, CARD_H, CARD_RADIUS, CARD_TAPPED_ANGLE,
    COLOUR_CARD_BACK, COLOUR_CARD_FACE, COLOUR_CARD_TAPPED,
    COLOUR_HIGHLIGHT, COLOUR_TARGET_RING, COLOUR_TEXT, COLOUR_TEXT_DIM,
    COLOUR_ZONE_BORDER,
)


# ---------------------------------------------------------------------------
# Scryfall image cache (shared across all CardRenderer instances)
# ---------------------------------------------------------------------------

class _ScryfallCache:
    """
    Lazy per-name image cache.

    Fetches art from Scryfall API in a background thread when a card is
    first drawn. Surfaces are stored as pygame.Surface objects once loaded.
    Until loaded, None is stored (caller renders placeholder).
    """

    def __init__(self) -> None:
        self._cache: dict[str, Optional[object]] = {}   # name -> Surface | None
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def get(self, card_name: str) -> Optional[object]:
        """Return cached Surface or None (triggers background fetch if first call)."""
        with self._lock:
            if card_name in self._cache:
                return self._cache[card_name]
            if card_name not in self._pending:
                self._pending.add(card_name)
                t = threading.Thread(
                    target=self._fetch,
                    args=(card_name,),
                    daemon=True,
                )
                t.start()
        return None

    def _fetch(self, card_name: str) -> None:
        """Background thread: fetch art from Scryfall and decode into Surface."""
        try:
            from urllib.request import urlopen
            from urllib.parse import quote
            import json
            import io

            # Step 1: resolve card by name
            name_enc = quote(card_name)
            api_url  = f"https://api.scryfall.com/cards/named?fuzzy={name_enc}"
            with urlopen(api_url, timeout=5) as r:
                data = json.loads(r.read())

            # Step 2: get small image URI
            image_uris = data.get("image_uris") or (
                data.get("card_faces", [{}])[0].get("image_uris", {})
            )
            img_url = image_uris.get("small") or image_uris.get("normal")
            if not img_url:
                raise ValueError("No image URI found")

            # Step 3: download image bytes
            with urlopen(img_url, timeout=10) as r:
                img_bytes = r.read()

            # Step 4: decode into pygame Surface
            if _PYGAME_AVAILABLE:
                import pygame
                buf = io.BytesIO(img_bytes)
                surf = pygame.image.load(buf, "card.jpg")
                surf = pygame.transform.scale(surf, (CARD_W, CARD_H))
            else:
                surf = None

            with self._lock:
                self._cache[card_name] = surf
                self._pending.discard(card_name)

        except Exception:
            # On any failure, store None so we fall back to placeholder
            with self._lock:
                self._cache[card_name] = None
                self._pending.discard(card_name)


# Module-level shared cache
_ART_CACHE = _ScryfallCache()


# ---------------------------------------------------------------------------
# CardRenderer
# ---------------------------------------------------------------------------

class CardRenderer:
    """
    Stateless card drawing helper.

    All draw methods accept a target pygame.Surface and a card dict.
    Card dict schema (same as game_state.CommanderPlayer.battlefield):
        {
            "name":     str,
            "type":     str,         # creature / instant / land / …
            "pt":       str | None,  # "3/3"
            "tapped":   bool,
            "cmc":      int,
            "oracle":   str | None,
            "is_commander": bool,
        }
    """

    def __init__(self, font_small=None, font_med=None) -> None:
        self._font_small = font_small
        self._font_med   = font_med

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draw_card(
        self,
        surface,
        card: dict,
        x: int,
        y: int,
        highlighted: bool = False,
        show_art: bool = True,
    ) -> None:
        """
        Draw a single card at (x, y) on surface.
        Tapped cards are rotated 90 degrees clockwise.
        """
        if not _PYGAME_AVAILABLE:
            return

        import pygame
        tapped = card.get("tapped", False)

        # Build card surface at standard orientation
        card_surf = self._build_card_surface(card, highlighted, show_art)

        if tapped:
            card_surf = pygame.transform.rotate(card_surf, -CARD_TAPPED_ANGLE)

        surface.blit(card_surf, (x, y))

    def draw_card_back(
        self,
        surface,
        x: int,
        y: int,
        label: str = "",
    ) -> None:
        """Draw a face-down card back (used for hidden hands)."""
        if not _PYGAME_AVAILABLE:
            return
        import pygame
        rect = pygame.Rect(x, y, CARD_W, CARD_H)
        pygame.draw.rect(surface, COLOUR_CARD_BACK, rect, border_radius=CARD_RADIUS)
        pygame.draw.rect(surface, COLOUR_ZONE_BORDER, rect, width=2, border_radius=CARD_RADIUS)
        if label and self._font_small:
            lbl = self._font_small.render(label[:12], True, COLOUR_TEXT_DIM)
            surface.blit(lbl, (x + 4, y + CARD_H - 18))

    def get_context_menu_options(self, card: dict) -> list[str]:
        """
        Return right-click context menu options for a card.
        Options depend on card type and zone.
        """
        options = []
        if card.get("type", "").lower() == "land":
            options.append("Tap for mana")
        if card.get("is_creature") or "creature" in card.get("type", "").lower():
            options.append("Declare attacker")
        if card.get("oracle"):
            options.append("View oracle text")
        options.append("Move to graveyard")
        options.append("Move to exile")
        return options

    def card_rect(
        self,
        x: int,
        y: int,
        tapped: bool = False,
    ) -> tuple:
        """Return the bounding (x, y, w, h) tuple for hit-testing."""
        if tapped:
            return (x, y, CARD_H, CARD_W)   # rotated dimensions
        return (x, y, CARD_W, CARD_H)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_card_surface(self, card: dict, highlighted: bool, show_art: bool):
        """Construct a CARD_W x CARD_H surface for the card."""
        import pygame
        surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
        rect = pygame.Rect(0, 0, CARD_W, CARD_H)

        # Background
        face_col = COLOUR_CARD_TAPPED if card.get("tapped") else COLOUR_CARD_FACE
        pygame.draw.rect(surf, face_col, rect, border_radius=CARD_RADIUS)

        # Scryfall art (or placeholder)
        if show_art:
            art = _ART_CACHE.get(card.get("name", ""))
            if art:
                surf.blit(art, (0, 0))
            else:
                # Art placeholder: grey block in upper portion
                art_rect = pygame.Rect(4, 4, CARD_W - 8, 54)
                pygame.draw.rect(surf, (80, 90, 110), art_rect, border_radius=3)

        # Border
        border_col = COLOUR_HIGHLIGHT if highlighted else COLOUR_ZONE_BORDER
        border_w   = 3 if highlighted else 1
        pygame.draw.rect(surf, border_col, rect, width=border_w, border_radius=CARD_RADIUS)

        # Commander indicator (gold star)
        if card.get("is_commander"):
            pygame.draw.circle(surf, (255, 210, 0), (CARD_W - 10, 10), 6)

        # Text overlay
        if self._font_small:
            name = card.get("name", "Unknown")[:14]
            name_surf = self._font_small.render(name, True, (10, 10, 10))
            surf.blit(name_surf, (4, CARD_H - 38))

            pt = card.get("pt")
            if pt and self._font_small:
                pt_surf = self._font_small.render(pt, True, (10, 10, 10))
                surf.blit(pt_surf, (CARD_W - 28, CARD_H - 18))

            cmc = card.get("cmc")
            if cmc is not None and self._font_small:
                cmc_str = str(int(cmc)) if isinstance(cmc, float) else str(cmc)
                cmc_surf = self._font_small.render(cmc_str, True, (10, 10, 10))
                surf.blit(cmc_surf, (4, CARD_H - 18))

        # Target ring
        if highlighted:
            pygame.draw.rect(
                surf, COLOUR_TARGET_RING, rect,
                width=3, border_radius=CARD_RADIUS,
            )

        return surf
