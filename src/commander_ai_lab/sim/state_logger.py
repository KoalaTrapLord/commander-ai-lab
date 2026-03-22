"""
Commander AI Lab — State Snapshot Logger (Phase 1)
===================================================
Saves game state JSON + LLM prompt string per AI decision for debugging
and AI quality analysis. Rotates to a maximum of MAX_SNAPSHOTS files.

Snapshot files are saved to: logs/snapshots/
Filename format: snapshot_YYYYMMDD_HHMMSS_<turn>_<seat>.json

Usage:
    from commander_ai_lab.sim.state_logger import StateLogger

    logger = StateLogger()                  # uses default logs/snapshots/
    logger = StateLogger(log_dir="my/path") # custom directory

    logger.save(game_state, prompt, chosen_move_id, seat)
    logger.list_snapshots()                 # returns list of file paths
    logger.clear_all()                      # delete all snapshots
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from commander_ai_lab.sim.game_state import CommanderGameState

MAX_SNAPSHOTS = 100
DEFAULT_LOG_DIR = Path("logs") / "snapshots"


class StateLogger:
    """
    Rotating snapshot logger for AI decision states.

    Keeps at most MAX_SNAPSHOTS files in the log directory.
    When the limit is reached, the oldest snapshot is deleted
    before writing the new one (FIFO rotation).
    """

    _counter: int = 0  # monotonic counter to guarantee unique filenames

    def __init__(self, log_dir: Optional[str | Path] = None) -> None:
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────

    def save(
        self,
        game_state: "CommanderGameState",
        prompt: str,
        chosen_move_id: Optional[int],
        seat: int,
        fallback_used: bool = False,
        extra: Optional[dict] = None,
    ) -> Path:
        """
        Save a snapshot of the game state + prompt used for an AI decision.

        Args:
            game_state:     The CommanderGameState at decision time.
            prompt:         The full prompt string sent to the LLM.
            chosen_move_id: The move ID the LLM (or fallback) selected.
            seat:           The AI player's seat index.
            fallback_used:  True if the fallback heuristic was used instead of LLM.
            extra:          Optional dict of extra metadata to include.

        Returns:
            Path to the saved snapshot file.
        """
        self._rotate()

        StateLogger._counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"snapshot_{timestamp}_{StateLogger._counter}_t{game_state.turn}_s{seat}.json"
        filepath = self.log_dir / filename

        snapshot = {
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "turn": game_state.turn,
                "phase": game_state.current_phase,
                "activePlayerSeat": game_state.active_player_seat,
                "decisionBySeat": seat,
                "chosenMoveId": chosen_move_id,
                "fallbackUsed": fallback_used,
            },
            "gameState": game_state.to_dict(),
            "prompt": prompt,
        }

        if extra:
            snapshot["extra"] = extra

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        return filepath

    def list_snapshots(self) -> list[Path]:
        """Return all snapshot files sorted by creation time (oldest first)."""
        files = sorted(
            self.log_dir.glob("snapshot_*.json"),
            key=lambda p: p.stat().st_ctime,
        )
        return files

    def count(self) -> int:
        """Return the number of snapshot files currently stored."""
        return len(self.list_snapshots())

    def clear_all(self) -> int:
        """Delete all snapshot files. Returns the number of files deleted."""
        files = self.list_snapshots()
        for f in files:
            f.unlink(missing_ok=True)
        return len(files)

    def load(self, path: Path) -> dict:
        """Load and return a snapshot dict from a file path."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_latest(self) -> Optional[dict]:
        """Load and return the most recent snapshot, or None if empty."""
        files = self.list_snapshots()
        if not files:
            return None
        return self.load(files[-1])

    # ── Internal ──────────────────────────────────────────────

    def _rotate(self) -> None:
        """
        If at MAX_SNAPSHOTS, delete the oldest file before writing a new one.
        Ensures the log directory never exceeds MAX_SNAPSHOTS files.
        """
        files = self.list_snapshots()
        while len(files) >= MAX_SNAPSHOTS:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)
