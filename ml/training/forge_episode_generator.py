"""
Commander AI Lab — Forge Episode Generator (Phase 3.2)

Async producer-consumer pipeline: runs Forge batch games in parallel
with PPO training.  Forge produces episodes → shared queue → PPO
trainer consumes.

Uses the existing watchdog (_global_watchdog_loop in forge_runner.py)
to monitor Forge worker processes for stalls.
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from ml.config.scope import (
    ACTION_TO_IDX,
    GAME_SCOPE,
    IDX_TO_ACTION,
    MacroAction,
    NUM_ACTIONS,
    STATE_DIMS,
)
from ml.training.reward import (
    RewardConfig,
    compute_intermediate_reward,
    compute_terminal_reward,
)
from ml.training.decision_exporter import DecisionExporter, ExporterConfig

logger = logging.getLogger("ml.forge_episode_generator")


# ══════════════════════════════════════════════════════════
# Episode / Trajectory data structures
# ══════════════════════════════════════════════════════════

@dataclass
class ForgeTransition:
    """Single (s, a, r, log_prob, value, done) tuple from a Forge game."""
    state: np.ndarray
    action: int
    reward: float
    log_prob: float
    value: float
    done: bool
    # Raw snapshot retained so the exporter can reconstruct game-state context
    snapshot: Optional[Dict[str, Any]] = None


@dataclass
class ForgeEpisode:
    """Complete trajectory from a single Forge game."""
    game_id: str
    transitions: List[ForgeTransition] = field(default_factory=list)
    winner: Optional[int] = None
    total_turns: int = 0
    deck_names: List[str] = field(default_factory=list)
    agent_seat: int = 0
    playstyle: str = "midrange"

    @property
    def length(self) -> int:
        return len(self.transitions)

    @property
    def total_reward(self) -> float:
        return sum(t.reward for t in self.transitions)

    @property
    def won(self) -> bool:
        return self.winner == self.agent_seat


# ══════════════════════════════════════════════════════════
# JSONL Parser — reads Forge ML decision snapshots
# ══════════════════════════════════════════════════════════

def parse_forge_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Parse a JSONL file of Forge ML decision snapshots.

    Each line is a JSON object with keys like:
        game_id, turn, phase, active_seat, state, action, outcome
    """
    snapshots = []
    with open(path, "r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                snapshots.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("Skipping malformed line %d in %s: %s", lineno, path, e)
    logger.info("Parsed %d snapshots from %s", len(snapshots), path)
    return snapshots


def _make_minimal_state(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Build a minimal prev/curr state dict from a Forge snapshot.

    compute_intermediate_reward() expects a dict with a 'players' list
    where each player has 'life_total', 'cards_in_hand',
    'creatures_on_battlefield', etc.  Forge snapshots carry a 'players'
    array directly; we forward it as-is and fall back to scalar fields
    when the array is absent.
    """
    if "players" in snap:
        return {"players": snap["players"]}

    # Fallback: reconstruct a two-player view from flat snapshot fields
    agent_seat = snap.get("active_seat", 0)
    opp_seat = 1 - agent_seat
    players = [None, None]

    def _player(life_key: str, hand_key: str, creatures_key: str) -> Dict:
        return {
            "life_total": snap.get(life_key, 40),
            "cards_in_hand": snap.get(hand_key, 0),
            "creatures_on_battlefield": snap.get(creatures_key, 0),
            "cards_in_graveyard": 0,
            "mana_available": snap.get("mana_available", 0),
            "commander_damage_taken": 0,
            "total_power_on_board": 0,
        }

    players[agent_seat] = _player("agent_life", "agent_hand_size", "agent_creatures")
    players[opp_seat] = _player("opp_life", "opp_hand_size", "opp_creatures")
    return {"players": players}


def snapshots_to_episode(
    snapshots: List[Dict[str, Any]],
    reward_config: Optional[RewardConfig] = None,
    agent_seat: int = 0,
    playstyle: str = "midrange",
) -> ForgeEpisode:
    """Convert a sequence of Forge snapshots into a ForgeEpisode.

    Maps Forge action labels → MacroAction indices and computes
    rewards from game outcomes using ml.training.reward.
    """
    if not snapshots:
        return ForgeEpisode(game_id="empty")

    first = snapshots[0]
    episode = ForgeEpisode(
        game_id=first.get("game_id", "unknown"),
        deck_names=first.get("deck_names", []),
        agent_seat=agent_seat,
        playstyle=playstyle,
    )

    rc = reward_config or RewardConfig()

    for i, snap in enumerate(snapshots):
        # State vector — zero-padded if not present
        state_vec = np.zeros(STATE_DIMS.total_state_dim, dtype=np.float32)
        if "state_vector" in snap:
            raw = np.array(snap["state_vector"], dtype=np.float32)
            state_vec[: min(len(raw), len(state_vec))] = raw[: len(state_vec)]

        # Action mapping
        action_label = snap.get("action", "pass").lower().replace(" ", "_")
        try:
            macro = MacroAction(action_label)
            action_idx = ACTION_TO_IDX[macro]
        except (ValueError, KeyError):
            action_idx = ACTION_TO_IDX[MacroAction.PASS]

        # Reward — use correct reward.py signatures
        is_done = i == len(snapshots) - 1
        if is_done and "outcome" in snap:
            outcome = snap["outcome"]
            reward = compute_terminal_reward(
                won=outcome.get("won", False),
                draw=outcome.get("draw", False),
                timeout=outcome.get("timeout", False),
                config=rc,
            )
        else:
            # Build minimal prev/curr dicts for intermediate reward
            prev_snap = snapshots[i - 1] if i > 0 else snap
            prev_state = _make_minimal_state(prev_snap)
            curr_state = _make_minimal_state(snap)
            reward = compute_intermediate_reward(
                prev_state=prev_state,
                curr_state=curr_state,
                action_taken=action_label,
                agent_seat=agent_seat,
                config=rc,
            )

        episode.transitions.append(ForgeTransition(
            state=state_vec,
            action=action_idx,
            reward=reward,
            log_prob=snap.get("log_prob", 0.0),
            value=snap.get("value", 0.0),
            done=is_done,
            snapshot=snap,
        ))

    episode.total_turns = snapshots[-1].get("turn", len(snapshots))
    if "outcome" in snapshots[-1]:
        episode.winner = snapshots[-1]["outcome"].get("winner_seat")

    return episode


# ══════════════════════════════════════════════════════════
# DecisionExporter adapter for Forge episodes
# ══════════════════════════════════════════════════════════

def _export_forge_episode(episode: ForgeEpisode, exporter: DecisionExporter) -> None:
    """Feed a completed ForgeEpisode into the DecisionExporter.

    Translates each ForgeTransition back into the game_state_snapshot
    format expected by DecisionExporter.record_step(), then finalises
    the episode so the exporter can apply its win/length gates.

    The raw snapshot stored on each ForgeTransition is used directly
    when available; otherwise a minimal dict is synthesised from the
    transition's action index and reward so the schema is always valid.
    """
    exporter.begin_episode(
        agent_seat=episode.agent_seat,
        playstyle=episode.playstyle,
    )

    for t in episode.transitions:
        if t.snapshot is not None:
            game_state = _make_minimal_state(t.snapshot)
            # Carry through turn/phase/active_seat if present
            game_state["turn"] = t.snapshot.get("turn", 1)
            game_state["phase"] = t.snapshot.get("phase", "main_1")
            game_state["active_seat"] = t.snapshot.get("active_seat", episode.agent_seat)
        else:
            # Minimal fallback — exporter only needs players list for schema
            game_state = {
                "turn": 1,
                "phase": "main_1",
                "active_seat": episode.agent_seat,
                "players": [
                    {"life_total": 40, "cards_in_hand": 0, "creatures_on_battlefield": 0,
                     "cards_in_graveyard": 0, "mana_available": 0,
                     "commander_damage_taken": 0, "total_power_on_board": 0, "commander_tax": 0},
                    {"life_total": 40, "cards_in_hand": 0, "creatures_on_battlefield": 0,
                     "cards_in_graveyard": 0, "mana_available": 0,
                     "commander_damage_taken": 0, "total_power_on_board": 0, "commander_tax": 0},
                ],
            }

        exporter.record_step(
            game_state_snapshot=game_state,
            action_idx=t.action,
            reward=t.reward,
        )

    exporter.end_episode(
        won=episode.won,
        episode_return=episode.total_reward,
    )


# ══════════════════════════════════════════════════════════
# Async Episode Queue (producer-consumer)
# ══════════════════════════════════════════════════════════

class ForgeEpisodeQueue:
    """Thread-safe async queue bridging Forge producers and PPO consumer.

    Forge batch workers produce ForgeEpisodes; the PPO trainer consumes
    them as they become available.  Backpressure is applied when the
    queue reaches max_size.
    """

    def __init__(self, max_size: int = 256):
        self._queue: asyncio.Queue[ForgeEpisode] = asyncio.Queue(maxsize=max_size)
        self._produced = 0
        self._consumed = 0
        self._closed = False

    async def put(self, episode: ForgeEpisode) -> None:
        await self._queue.put(episode)
        self._produced += 1

    async def get(self, timeout: float = 30.0) -> Optional[ForgeEpisode]:
        try:
            ep = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            self._consumed += 1
            return ep
        except asyncio.TimeoutError:
            return None

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed and self._queue.empty()

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "produced": self._produced,
            "consumed": self._consumed,
            "pending": self._queue.qsize(),
        }


# ══════════════════════════════════════════════════════════
# Forge Batch Producer
# ══════════════════════════════════════════════════════════

async def forge_producer(
    queue: ForgeEpisodeQueue,
    results_dir: str = "results",
    batch_id: str = "forge-batch",
    num_games: int = 64,
    poll_interval: float = 2.0,
    reward_config: Optional[RewardConfig] = None,
) -> int:
    """Producer coroutine: watches for Forge JSONL output files,
    parses them into episodes, and pushes them onto the queue.

    Returns total number of episodes produced.
    """
    results_path = Path(results_dir)
    pattern = f"ml-decisions-forge-{batch_id}*.jsonl"
    seen_files: set = set()
    total_produced = 0

    logger.info("[PRODUCER] Watching %s for pattern %s", results_path, pattern)

    while total_produced < num_games and not queue.is_closed:
        for jsonl_file in sorted(results_path.glob(pattern)):
            if jsonl_file in seen_files:
                continue
            seen_files.add(jsonl_file)

            try:
                snapshots = parse_forge_jsonl(jsonl_file)
                if not snapshots:
                    continue

                # Group by game_id
                games: Dict[str, List] = {}
                for snap in snapshots:
                    gid = snap.get("game_id", "unknown")
                    games.setdefault(gid, []).append(snap)

                for gid, game_snaps in games.items():
                    episode = snapshots_to_episode(game_snaps, reward_config)
                    if episode.length > 0:
                        await queue.put(episode)
                        total_produced += 1
                        logger.debug("[PRODUCER] Queued episode %s (%d transitions)",
                                     gid, episode.length)

            except Exception as e:
                logger.error("[PRODUCER] Error processing %s: %s", jsonl_file, e)

        await asyncio.sleep(poll_interval)

    logger.info("[PRODUCER] Done — produced %d episodes", total_produced)
    return total_produced


async def ppo_consumer(
    queue: ForgeEpisodeQueue,
    buffer_size: int = 64,
    on_batch_ready=None,
    exporter: Optional[DecisionExporter] = None,
) -> int:
    """Consumer coroutine: pulls episodes from the queue and batches
    them for PPO training updates.

    Args:
        queue: ForgeEpisodeQueue to consume from
        buffer_size: number of episodes per training batch
        on_batch_ready: callback(episodes) when a batch is full
        exporter: Optional DecisionExporter — when provided, every
                  consumed episode is fed into the exporter so winning
                  Forge games accumulate in the distillation JSONL pool.
                  Call exporter.flush() after the pipeline completes to
                  write the JSONL file.

    Returns total episodes consumed.
    """
    batch: List[ForgeEpisode] = []
    total_consumed = 0

    while not queue.is_closed:
        episode = await queue.get(timeout=10.0)
        if episode is None:
            if queue.is_closed:
                break
            continue

        # Feed into distillation exporter (win-gate applied inside exporter)
        if exporter is not None:
            try:
                _export_forge_episode(episode, exporter)
            except Exception as exc:
                logger.warning("[CONSUMER] Exporter error for episode %s: %s",
                               episode.game_id, exc)

        batch.append(episode)
        total_consumed += 1

        if len(batch) >= buffer_size:
            if on_batch_ready:
                on_batch_ready(batch)
            logger.info("[CONSUMER] Batch of %d episodes ready for PPO update", len(batch))
            batch = []

    # Flush remaining
    if batch and on_batch_ready:
        on_batch_ready(batch)
        logger.info("[CONSUMER] Final batch of %d episodes flushed", len(batch))

    logger.info("[CONSUMER] Done — consumed %d episodes", total_consumed)
    return total_consumed


# ══════════════════════════════════════════════════════════
# Convenience runner
# ══════════════════════════════════════════════════════════

async def run_forge_pipeline(
    results_dir: str = "results",
    batch_id: str = "forge-batch",
    num_games: int = 64,
    buffer_size: int = 64,
    max_queue: int = 256,
    on_batch_ready=None,
    reward_config: Optional[RewardConfig] = None,
    exporter: Optional[DecisionExporter] = None,
) -> Dict[str, Any]:
    """Run the full Forge producer → PPO consumer pipeline.

    The Forge Java batch must be started separately (via forge_runner.py
    or MultiThreadBatchRunner). This function handles the Python side:
    reading JSONL output and feeding episodes into the PPO trainer.

    If an exporter is provided, winning Forge episodes are recorded and
    flushed to a PPO JSONL file at the end of the pipeline run.  The
    output path is returned in the stats dict under "exporter_file".

    Example::

        from ml.training.decision_exporter import DecisionExporter, ExporterConfig
        exporter = DecisionExporter(ExporterConfig(model_version="gen-1"))
        stats = await run_forge_pipeline(num_games=128, exporter=exporter)
        print(stats["exporter_file"])   # data/results/ml-decisions-ppo-<id>.jsonl
    """
    queue = ForgeEpisodeQueue(max_size=max_queue)

    producer_task = asyncio.create_task(
        forge_producer(queue, results_dir, batch_id, num_games,
                       reward_config=reward_config)
    )
    consumer_task = asyncio.create_task(
        ppo_consumer(queue, buffer_size, on_batch_ready, exporter=exporter)
    )

    produced = await producer_task
    queue.close()
    consumed = await consumer_task

    # Flush exporter to disk and capture output path
    exporter_file = None
    if exporter is not None:
        exporter_file = exporter.flush()
        if exporter_file:
            logger.info("[PIPELINE] Distillation export: %s  stats=%s",
                        exporter_file, exporter.stats)

    stats: Dict[str, Any] = {
        "produced": produced,
        "consumed": consumed,
        "exporter_file": exporter_file,
        **queue.stats,
    }
    logger.info("[PIPELINE] Complete: %s", stats)
    return stats
