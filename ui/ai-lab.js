/**
 * Commander AI Lab — Web UI Controller v3
 * ═══════════════════════════════════════
 *
 * v3 adds:
 *   - URL import (Archidekt/EDHREC) — paste a URL to import a deck
 *   - Commander meta picker with real Scryfall art
 *   - Precon browser with install & batch install
 *   - Deck list with delete / set-as-active / quick-sim
 *   - Import status toasts
 *   - Lab status bar (Forge ready/busy)
 *
 * Depends on: lab_api.py  (/api/lab/…)
 */

(function () {
  'use strict';