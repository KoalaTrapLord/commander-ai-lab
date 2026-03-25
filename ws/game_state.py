"""Game-state delta engine.

Compares successive game-state snapshots and produces minimal
JSON deltas so that Unity only receives what changed — not
the full 4-player board every tick.

Delta format sent over WebSocket:
{
  "type": "delta" | "snapshot" | "decision" | "game_over",
  "seq": <monotonic int>,
  "game_id": "...",
  "turn": 5,
  "phase": "main_1",
  "timestamp": 1711400000.0,
  "changes": [
    {"path": "players.0.life", "op": "replace", "value": 37},
    {"path": "players.1.battlefield", "op": "add", "value": {"name": "Sol Ring", ...}},
    {"path": "stack", "op": "replace", "value": [...]},
  ]
}
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("ws.game_state")


def _deep_diff(
    old: Any, new: Any, path: str = ""
) -> List[Dict[str, Any]]:
    """Recursively diff two JSON-serialisable structures.

    Returns a list of RFC-6902-style patch operations:
      {"op": "replace"|"add"|"remove", "path": "...", "value": ...}
    """
    changes: List[Dict[str, Any]] = []

    if old is None and new is not None:
        return [{"op": "add", "path": path, "value": new}]
    if old is not None and new is None:
        return [{"op": "remove", "path": path}]
    if type(old) != type(new):
        return [{"op": "replace", "path": path, "value": new}]

    if isinstance(new, dict):
        all_keys = set(list(old.keys()) + list(new.keys()))
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({"op": "add", "path": child_path, "value": new[key]})
            elif key not in new:
                changes.append({"op": "remove", "path": child_path})
            else:
                changes.extend(_deep_diff(old[key], new[key], child_path))
        return changes

    if isinstance(new, list):
        # For lists (battlefield, hand, graveyard, stack) we do a
        # simple length+element comparison. Zone lists change
        # frequently and a full LCS diff is overkill for game state.
        if old == new:
            return []
        # If the list is short or changed significantly, send whole list
        if len(old) != len(new) or _list_diff_ratio(old, new) > 0.5:
            return [{"op": "replace", "path": path, "value": new}]
        # Element-wise diff for same-length lists with few changes
        for i, (o, n) in enumerate(zip(old, new)):
            child_path = f"{path}.{i}"
            changes.extend(_deep_diff(o, n, child_path))
        return changes

    # Scalar comparison
    if old != new:
        return [{"op": "replace", "path": path, "value": new}]
    return []


def _list_diff_ratio(old: list, new: list) -> float:
    """Fraction of elements that differ between two same-length lists."""
    if not old:
        return 0.0
    diffs = sum(1 for a, b in zip(old, new) if a != b)
    return diffs / len(old)


class GameStateTracker:
    """Tracks per-game state and emits deltas on each update.

    Usage:
        tracker = GameStateTracker(game_id)
        delta = tracker.update(new_snapshot)
        # delta is a dict ready to send via WebSocket
    """

    def __init__(self, game_id: str):
        self.game_id = game_id
        self._last_snapshot: Optional[Dict] = None
        self._seq: int = 0
        self._created_at: float = time.time()

    def update(self, snapshot: Dict) -> Dict:
        """Compare snapshot with previous state, return delta message.

        First call returns a full snapshot message (type="snapshot").
        Subsequent calls return delta messages (type="delta").
        """
        self._seq += 1
        now = time.time()

        if self._last_snapshot is None:
            # First update — send full snapshot
            self._last_snapshot = copy.deepcopy(snapshot)
            return {
                "type": "snapshot",
                "seq": self._seq,
                "game_id": self.game_id,
                "turn": snapshot.get("turn", 0),
                "phase": snapshot.get("phase", ""),
                "timestamp": now,
                "state": snapshot,
            }

        # Compute delta
        changes = _deep_diff(self._last_snapshot, snapshot)
        self._last_snapshot = copy.deepcopy(snapshot)

        if not changes:
            return {
                "type": "heartbeat",
                "seq": self._seq,
                "game_id": self.game_id,
                "timestamp": now,
            }

        return {
            "type": "delta",
            "seq": self._seq,
            "game_id": self.game_id,
            "turn": snapshot.get("turn", 0),
            "phase": snapshot.get("phase", ""),
            "timestamp": now,
            "changes": changes,
        }

    def make_decision_event(
        self,
        action: str,
        action_index: int,
        confidence: float,
        probabilities: Optional[Dict[str, float]] = None,
        inference_ms: float = 0.0,
    ) -> Dict:
        """Build a decision event message for the Unity client."""
        self._seq += 1
        return {
            "type": "decision",
            "seq": self._seq,
            "game_id": self.game_id,
            "timestamp": time.time(),
            "action": action,
            "action_index": action_index,
            "confidence": confidence,
            "probabilities": probabilities or {},
            "inference_ms": inference_ms,
        }

    def make_game_over_event(
        self,
        winner_seat: int,
        reason: str = "",
        turns_played: int = 0,
    ) -> Dict:
        """Build a game-over event message."""
        self._seq += 1
        return {
            "type": "game_over",
            "seq": self._seq,
            "game_id": self.game_id,
            "timestamp": time.time(),
            "winner_seat": winner_seat,
            "reason": reason,
            "turns_played": turns_played,
        }

    @property
    def sequence(self) -> int:
        return self._seq

    @property
    def has_baseline(self) -> bool:
        return self._last_snapshot is not None


# Per-game tracker registry
_trackers: Dict[str, GameStateTracker] = {}


def get_tracker(game_id: str) -> GameStateTracker:
    """Get or create a state tracker for a game."""
    if game_id not in _trackers:
        _trackers[game_id] = GameStateTracker(game_id)
    return _trackers[game_id]


def remove_tracker(game_id: str) -> None:
    """Remove a game tracker (called on game end)."""
    _trackers.pop(game_id, None)
