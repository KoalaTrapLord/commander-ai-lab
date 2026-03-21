"""
Commander AI Lab — PPO Decision Exporter
════════════════════════════════════════

Exports PPO self-play decisions as JSONL files in the same schema
as Forge DecisionSnapshot records. This enables the closed-loop
distillation pipeline where PPO-discovered strategies flow back
into the supervised training dataset.

Output files: data/results/ml-decisions-ppo-{batch_id}.jsonl

Each line is a JSON object compatible with the dataset_builder.py
ingestion pipeline, tagged with source="ppo" metadata.

Ref: docs/CLOSED-LOOP-DISTILLATION.md — Phase 1
Issue: #65
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import sys

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import IDX_TO_ACTION, MacroAction

logger = logging.getLogger("ml.decision_exporter")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ExporterConfig:
    """Configuration for the PPO decision exporter."""

    output_dir: str = "data/results"
    only_wins: bool = True          # Only export decisions from winning games
    model_version: str = "unknown"
    min_episode_steps: int = 3      # Skip very short episodes (likely noise)


# ---------------------------------------------------------------------------
# Decision Record Builder
# ---------------------------------------------------------------------------

def _macro_action_to_forge_type(action: MacroAction) -> str:
    """Map a MacroAction enum to the closest Forge action type string."""
    mapping = {
        MacroAction.CAST_CREATURE: "cast_spell",
        MacroAction.CAST_REMOVAL: "cast_spell",
        MacroAction.CAST_DRAW: "cast_spell",
        MacroAction.CAST_RAMP: "cast_spell",
        MacroAction.CAST_COMMANDER: "cast_spell",
        MacroAction.ATTACK_OPPONENT: "attack",
        MacroAction.HOLD_MANA: "pass_priority",
        MacroAction.PASS: "pass_priority",
    }
    return mapping.get(action, "pass_priority")


def build_decision_record(
    game_state_snapshot: dict,
    action_idx: int,
    reward: float,
    agent_seat: int,
    game_id: str,
    game_outcome: str,
    archetype: str = "midrange",
    source: str = "ppo",
    model_version: str = "unknown",
    episode_return: float = 0.0,
) -> dict:
    """
    Build a single decision record in Forge-compatible JSONL format.

    The record mirrors the schema consumed by dataset_builder.py so that
    PPO-generated data can be mixed into the supervised training set.
    """
    action = IDX_TO_ACTION[action_idx]
    players = game_state_snapshot.get("players", [])

    # Build per-player state matching Forge snapshot layout
    player_snapshots = []
    for i, p in enumerate(players):
        player_snapshots.append({
            "seat": i,
            "life": p.get("life_total", 40),
            "handSize": p.get("cards_in_hand", 0),
            "permanentCount": p.get("creatures_on_battlefield", 0),
            "graveyardSize": p.get("cards_in_graveyard", 0),
            "manaAvailable": p.get("mana_available", 0),
            "commanderDamageTaken": p.get("commander_damage_taken", 0),
            "totalPowerOnBoard": p.get("total_power_on_board", 0),
            "commanderTax": p.get("commander_tax", 0),
        })

    return {
        # --- Core fields consumed by dataset_builder / labeler ---
        "game_id": game_id,
        "game_outcome": game_outcome,
        "archetype": archetype,

        # Action info (used by ml.actions.labeler)
        "action": {
            "type": _macro_action_to_forge_type(action),
            "macro_action": action.value,
            "action_idx": action_idx,
            "seat": agent_seat,
        },

        # Board / game state
        "turn": game_state_snapshot.get("turn", 1),
        "phase": game_state_snapshot.get("phase", "main_1"),
        "active_seat": game_state_snapshot.get("active_seat", 0),
        "players": player_snapshots,

        # --- PPO-specific metadata (distinguishes from Forge data) ---
        "source": source,
        "model_version": model_version,
        "reward": round(reward, 6),
        "episode_return": round(episode_return, 6),
    }


# ---------------------------------------------------------------------------
# DecisionExporter — accumulates episode decisions and flushes to JSONL
# ---------------------------------------------------------------------------

class DecisionExporter:
    """
    Collects decisions from PPO self-play episodes and writes them
    to JSONL files compatible with the supervised training pipeline.

    Usage::

        exporter = DecisionExporter(ExporterConfig(model_version="gen-0"))

        for ep in range(num_episodes):
            exporter.begin_episode(agent_seat=0, playstyle="midrange")
            for step in episode_steps:
                exporter.record_step(state_snapshot, action_idx, reward)
            exporter.end_episode(won=True, episode_return=3.14)

        exporter.flush()   # writes JSONL to disk
        print(exporter.stats)
    """

    def __init__(self, config: ExporterConfig = None):
        self.config = config or ExporterConfig()
        self._batch_id = str(uuid.uuid4())[:8]
        self._records: List[dict] = []
        self._episode_buffer: List[dict] = []
        self._current_game_id: Optional[str] = None
        self._current_seat: int = 0
        self._current_playstyle: str = "midrange"

        # Stats
        self._total_episodes = 0
        self._exported_episodes = 0
        self._exported_decisions = 0
        self._skipped_losses = 0
        self._skipped_short = 0

    # -- Episode lifecycle ---------------------------------------------------

    def begin_episode(self, agent_seat: int = 0, playstyle: str = "midrange"):
        """Start tracking a new episode."""
        self._episode_buffer = []
        self._current_game_id = f"ppo-{self._batch_id}-{self._total_episodes}"
        self._current_seat = agent_seat
        self._current_playstyle = playstyle

    def record_step(
        self,
        game_state_snapshot: dict,
        action_idx: int,
        reward: float,
    ):
        """Record a single decision step within the current episode."""
        self._episode_buffer.append({
            "snapshot": game_state_snapshot,
            "action_idx": action_idx,
            "reward": reward,
        })

    def end_episode(self, won: bool, episode_return: float = 0.0):
        """
        Finalize the current episode.

        If config.only_wins is True, decisions from losing episodes
        are discarded (higher signal-to-noise for distillation).
        """
        self._total_episodes += 1

        # Gate: skip losses if configured
        if self.config.only_wins and not won:
            self._skipped_losses += 1
            self._episode_buffer = []
            return

        # Gate: skip very short episodes
        if len(self._episode_buffer) < self.config.min_episode_steps:
            self._skipped_short += 1
            self._episode_buffer = []
            return

        game_outcome = "win" if won else "loss"

        for step in self._episode_buffer:
            record = build_decision_record(
                game_state_snapshot=step["snapshot"],
                action_idx=step["action_idx"],
                reward=step["reward"],
                agent_seat=self._current_seat,
                game_id=self._current_game_id,
                game_outcome=game_outcome,
                archetype=self._current_playstyle,
                source="ppo",
                model_version=self.config.model_version,
                episode_return=episode_return,
            )
            self._records.append(record)

        self._exported_episodes += 1
        self._exported_decisions += len(self._episode_buffer)
        self._episode_buffer = []

    # -- Persistence ---------------------------------------------------------

    def flush(self) -> Optional[str]:
        """
        Write all accumulated records to a JSONL file.

        Returns:
            Path to the written file, or None if no records to write.
        """
        if not self._records:
            logger.info("No PPO decisions to export (0 records).")
            return None

        os.makedirs(self.config.output_dir, exist_ok=True)
        filename = f"ml-decisions-ppo-{self._batch_id}.jsonl"
        filepath = os.path.join(self.config.output_dir, filename)

        with open(filepath, "w") as f:
            for record in self._records:
                f.write(json.dumps(record) + "\n")

        logger.info(
            "Exported %d PPO decisions (%d episodes) to %s",
            len(self._records),
            self._exported_episodes,
            filepath,
        )
        self._records = []
        return filepath

    # -- Reporting -----------------------------------------------------------

    @property
    def stats(self) -> dict:
        """Return export statistics."""
        return {
            "batch_id": self._batch_id,
            "total_episodes": self._total_episodes,
            "exported_episodes": self._exported_episodes,
            "exported_decisions": self._exported_decisions,
            "skipped_losses": self._skipped_losses,
            "skipped_short": self._skipped_short,
            "pending_records": len(self._records),
        }

    @property
    def batch_id(self) -> str:
        return self._batch_id
