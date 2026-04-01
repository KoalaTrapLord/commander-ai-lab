"""
services/draw_game_analyzer.py
==============================
Analyses draw-game snapshots captured by forge_runner._run_process_blocking.

A "draw game" is any game that hit the Forge per-game wall-clock timeout
instead of ending via a win condition.  Forge emits a line like:

    [DRAW] [PARSE-SUMMARY] game=42 turns=28 time_ms=61200 \
           seat0=AdaptiveEnchantment:life=46 seat1=AbzanArmor:life=0 \
           seat2=AhoyMateys:life=0 seat3=20WaysToWin:life=8

This module:
  1. Parses those lines out of the log into DrawGameSnapshot objects.
  2. Aggregates them to identify which deck most often leads at timeout.
  3. Exposes a summary dict suitable for embedding in the batch result JSON.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─── regex for the Forge DRAW summary line ────────────────────────────────────
# Example:
#   [DRAW] [PARSE-SUMMARY] game=42 turns=28 time_ms=61200
#           seat0=AdaptiveEnchantment:life=46 seat1=AbzanArmor:life=0
#           seat2=AhoyMateys:life=0 seat3=20WaysToWin:life=8
_DRAW_LINE_RE = re.compile(
    r'\[DRAW\].*?\[PARSE-SUMMARY\]'
    r'.*?game=(\d+)'
    r'.*?turns=(\d+)'
    r'.*?time_ms=(\d+)'
    r'((?:\s+seat\d+=\S+)*)'
    , re.IGNORECASE
)
_SEAT_RE = re.compile(r'seat(\d+)=([^:]+):life=([-\d]+)', re.IGNORECASE)


@dataclass
class DrawGameSnapshot:
    game_id: int
    turns: int
    time_ms: int
    # seat_index -> {deck_name, life}
    seats: Dict[int, dict] = field(default_factory=dict)

    @property
    def leading_deck(self) -> Optional[str]:
        """Name of the deck with the highest life at timeout (None if tie/empty)."""
        if not self.seats:
            return None
        best = max(self.seats.values(), key=lambda s: s["life"])
        return best["deck_name"]

    @property
    def leading_life(self) -> int:
        if not self.seats:
            return 0
        return max(s["life"] for s in self.seats.values())


def parse_draw_snapshots(log_lines: list[str]) -> list[DrawGameSnapshot]:
    """
    Scan raw log lines for [DRAW] [PARSE-SUMMARY] entries and return
    a list of DrawGameSnapshot objects, one per draw game.
    """
    snapshots: list[DrawGameSnapshot] = []
    for line in log_lines:
        m = _DRAW_LINE_RE.search(line)
        if not m:
            continue
        game_id = int(m.group(1))
        turns = int(m.group(2))
        time_ms = int(m.group(3))
        seats_str = m.group(4) or ""
        seats: Dict[int, dict] = {}
        for sm in _SEAT_RE.finditer(seats_str):
            seat_idx = int(sm.group(1))
            deck_name = sm.group(2).strip()
            life = int(sm.group(3))
            seats[seat_idx] = {"deck_name": deck_name, "life": life}
        snapshots.append(DrawGameSnapshot(game_id=game_id, turns=turns, time_ms=time_ms, seats=seats))
    return snapshots


def summarize_draw_games(snapshots: list[DrawGameSnapshot]) -> dict:
    """
    Aggregate draw snapshots into a summary dict for embedding in batch JSON.

    Returns::

        {
          "count": 156,
          "avgTurns": 27.4,
          "avgTimeMs": 61800,
          "perDeck": [
            {
              "deckName": "AdaptiveEnchantment",
              "drawLeadCount": 89,      # times this deck led at timeout
              "drawLeadPct": 57.1,
              "avgLifeAtTimeout": 42.3,
            },
            ...
          ],
          "likelyCause": "AdaptiveEnchantment"  # deck most often leading at timeout
        }
    """
    if not snapshots:
        return {"count": 0, "avgTurns": 0, "avgTimeMs": 0, "perDeck": [], "likelyCause": None}

    total = len(snapshots)
    avg_turns = round(sum(s.turns for s in snapshots) / total, 1)
    avg_time_ms = round(sum(s.time_ms for s in snapshots) / total)

    # Accumulate per-deck stats across all draw games
    deck_lead_count: Dict[str, int] = {}
    deck_life_sum: Dict[str, float] = {}
    deck_life_count: Dict[str, int] = {}

    for snap in snapshots:
        leader = snap.leading_deck
        if leader:
            deck_lead_count[leader] = deck_lead_count.get(leader, 0) + 1
        for seat in snap.seats.values():
            dn = seat["deck_name"]
            deck_life_sum[dn] = deck_life_sum.get(dn, 0.0) + seat["life"]
            deck_life_count[dn] = deck_life_count.get(dn, 0) + 1

    all_decks = set(deck_life_count.keys()) | set(deck_lead_count.keys())
    per_deck = []
    for dn in sorted(all_decks):
        lead_cnt = deck_lead_count.get(dn, 0)
        avg_life = round(deck_life_sum.get(dn, 0) / max(deck_life_count.get(dn, 1), 1), 1)
        per_deck.append({
            "deckName": dn,
            "drawLeadCount": lead_cnt,
            "drawLeadPct": round(lead_cnt / total * 100, 1),
            "avgLifeAtTimeout": avg_life,
        })

    per_deck.sort(key=lambda x: x["drawLeadCount"], reverse=True)
    likely_cause = per_deck[0]["deckName"] if per_deck else None

    return {
        "count": total,
        "avgTurns": avg_turns,
        "avgTimeMs": avg_time_ms,
        "perDeck": per_deck,
        "likelyCause": likely_cause,
    }
