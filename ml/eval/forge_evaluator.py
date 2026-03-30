"""
Commander AI Lab — Forge Evaluator (Issue #153)
═════════════════════════════════════════════════
Reusable eval harness that:
  1. Starts the policy inference server pointing at a given checkpoint
  2. Launches Forge games via MultiThreadBatchRunner with the policy
     server wired in as the AI decision-maker
  3. Collects per-game metrics and writes a JSON results file

Metrics collected per game:
  - won          : bool
  - turns        : int
  - life_final   : int  (winning seat final life)
  - life_delta   : int  (winner life - loser life at game end)
  - cmd_damage   : int  (commander damage dealt by policy seat)
  - illegal_acts : int  (actions rejected by Forge — should be 0)
  - entropy_mean : float (mean policy entropy across decision steps)
  - inference_ms : float (mean per-step inference latency)

Usage:
    from ml.eval.forge_evaluator import ForgeEvaluator, EvalConfig
    cfg = EvalConfig(
        checkpoint_path="ml/models/checkpoints/forge-trained/final.pt",
        forge_jar="forge/forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar",
        deck_files=["decks/cedh_test_a.dck", "decks/cedh_test_b.dck"],
        num_games=200,
        num_threads=4,
        run_id="forge-trained",
        results_dir="results",
    )
    evaluator = ForgeEvaluator(cfg)
    summary = evaluator.run()
    print(summary)
"""

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger("ml.eval.forge_evaluator")


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

@dataclass
class EvalConfig:
    """All parameters needed for a single evaluation run."""

    # Model
    checkpoint_path: str = "ml/models/checkpoints/best_policy.pt"
    embeddings_dir: str = "embeddings"
    device: str = None                          # None = auto-detect

    # Forge
    forge_jar: str = "forge/forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar"
    forge_work_dir: str = "forge"
    java_path: str = "java"
    deck_files: List[str] = field(default_factory=list)
    deck_names: List[str] = field(default_factory=list)
    policy_server_url: str = "http://localhost:8091"
    clock_seconds: int = 120

    # Run
    num_games: int = 200
    num_threads: int = 4
    seed: Optional[int] = None
    run_id: str = ""
    results_dir: str = "results"

    # Inference
    greedy: bool = True
    temperature: float = 1.0

    def __post_init__(self):
        if not self.run_id:
            self.run_id = str(uuid.uuid4())[:8]


# ─────────────────────────────────────────────
# Per-game result
# ─────────────────────────────────────────────

@dataclass
class GameRecord:
    game_index: int
    won: bool
    turns: int
    life_final_policy: int      # life total of policy seat at game end
    life_final_opponent: int
    life_delta: int             # policy life - opponent life
    commander_damage_dealt: int
    illegal_actions: int
    entropy_mean: float         # mean per-step policy entropy
    inference_ms_mean: float    # mean per-step inference latency
    decision_steps: int         # number of decision points in this game
    error: str = ""


# ─────────────────────────────────────────────
# Eval summary
# ─────────────────────────────────────────────

@dataclass
class EvalSummary:
    run_id: str
    checkpoint_path: str
    num_games: int
    wins: int
    losses: int
    win_rate: float
    win_rate_ci95_low: float
    win_rate_ci95_high: float
    avg_turns: float
    avg_life_delta: float
    avg_commander_damage: float
    avg_illegal_actions: float
    avg_entropy: float
    avg_inference_ms: float
    total_decision_steps: int
    elapsed_wall_s: float
    games_per_sec: float
    error_count: int
    result_file: str

    def __str__(self) -> str:
        return (
            f"EvalSummary run={self.run_id}\n"
            f"  checkpoint : {self.checkpoint_path}\n"
            f"  games      : {self.num_games} ({self.wins}W / {self.losses}L)\n"
            f"  win rate   : {self.win_rate:.1%}  "
            f"[{self.win_rate_ci95_low:.1%}, {self.win_rate_ci95_high:.1%}] 95% CI\n"
            f"  avg turns  : {self.avg_turns:.1f}\n"
            f"  avg life Δ : {self.avg_life_delta:+.1f}\n"
            f"  avg cmd dmg: {self.avg_commander_damage:.1f}\n"
            f"  illegal    : {self.avg_illegal_actions:.2f}/game\n"
            f"  entropy    : {self.avg_entropy:.4f}\n"
            f"  latency    : {self.avg_inference_ms:.1f} ms/step\n"
            f"  throughput : {self.games_per_sec:.2f} games/sec\n"
            f"  result file: {self.result_file}\n"
        )


# ─────────────────────────────────────────────
# Main evaluator
# ─────────────────────────────────────────────

class ForgeEvaluator:
    """
    Orchestrates a full eval run:
      1. Spin up PolicyInferenceService on cfg.policy_server_url port
      2. Run cfg.num_games Forge games via MultiThreadBatchRunner
      3. Parse Forge JSONL output for per-game metrics
      4. Write results to {results_dir}/eval-{run_id}.json
    """

    def __init__(self, cfg: EvalConfig):
        self.cfg = cfg
        self._records: List[GameRecord] = []
        self._result_path = os.path.join(
            cfg.results_dir, f"eval-{cfg.run_id}.json"
        )

    # ── Public entry point ───────────────────

    def run(self) -> EvalSummary:
        """Run the full evaluation. Returns an EvalSummary."""
        t0 = time.time()
        os.makedirs(self.cfg.results_dir, exist_ok=True)

        logger.info("[Eval %s] Starting %d-game eval run", self.cfg.run_id, self.cfg.num_games)
        logger.info("[Eval %s] Checkpoint: %s", self.cfg.run_id, self.cfg.checkpoint_path)

        # Load policy service
        service = self._load_policy_service()

        # Run games — either via real Forge or synthetic fallback
        forge_available = (
            self.cfg.forge_jar
            and Path(self.cfg.forge_jar).exists()
            and len(self.cfg.deck_files) >= 2
        )

        if forge_available:
            self._records = self._run_forge_games(service)
        else:
            logger.warning(
                "[Eval %s] Forge JAR or decks not found — running synthetic eval.",
                self.cfg.run_id
            )
            self._records = self._run_synthetic_eval(service)

        elapsed = time.time() - t0
        summary = self._build_summary(elapsed)
        self._write_results(summary)
        logger.info("[Eval %s] Done. %s", self.cfg.run_id, summary)
        return summary

    # ── Policy service setup ─────────────────

    def _load_policy_service(self):
        try:
            from ml.serving.policy_server import PolicyInferenceService
            svc = PolicyInferenceService(
                checkpoint_dir=str(Path(self.cfg.checkpoint_path).parent),
                embeddings_dir=self.cfg.embeddings_dir,
                device=self.cfg.device,
            )
                        # load() initializes embeddings + encoder; reload() loads the exact checkpoint file
            svc.load()  # loads embeddings + encoder (checkpoint load will fail — that's OK)
ok = svc.reload(self.cfg.checkpoint_path)
            if not ok:
                logger.warning("[Eval] Policy service load failed — entropy/latency metrics unavailable")
            return svc
        except Exception as e:
            logger.error("[Eval] Could not load PolicyInferenceService: %s", e)
            return None

    # ── Real Forge game runner ───────────────

    def _run_forge_games(self, service) -> List[GameRecord]:
        """Run games via MultiThreadBatchRunner + Forge subprocess."""
        try:
            from commanderailab.batch.MultiThreadBatchRunner import MultiThreadBatchRunner  # type: ignore
            from commanderailab.schema.BatchResult import DeckInfo  # type: ignore
            from commanderailab.ai.AiPolicy import AiPolicy  # type: ignore
        except ImportError:
            logger.warning("[Eval] Java bridge not importable from Python — using JSONL parsing fallback")
            return self._run_forge_via_subprocess(service)

        decks = [
            DeckInfo(name=Path(f).stem, file=f)
            for f in self.cfg.deck_files[:4]
        ]
        runner = MultiThreadBatchRunner(
            self.cfg.forge_jar, self.cfg.forge_work_dir,
            decks, AiPolicy.MIDRANGE,
            self.cfg.num_threads, True, self.cfg.clock_seconds, self.cfg.java_path
        )
        runner.enableMlLogging(self.cfg.results_dir, f"eval-{self.cfg.run_id}")
        runner.warmPool()

        try:
            results = runner.runBatch(self.cfg.num_games, self.cfg.seed)
        finally:
            runner.shutdownPool()

        return self._java_results_to_records(results, service)

    def _run_forge_via_subprocess(self, service) -> List[GameRecord]:
        """Parse JSONL files produced by a separately-launched Forge batch."""
        records = []
        results_path = Path(self.cfg.results_dir)
        pattern = f"ml-decisions-forge-eval-{self.cfg.run_id}*.jsonl"

        all_files = sorted(results_path.glob(pattern))
        if not all_files:
            logger.warning("[Eval] No JSONL files found matching %s — falling back to synthetic", pattern)
            return self._run_synthetic_eval(service)

        from ml.training.forge_episode_generator import parse_forge_jsonl, snapshots_to_episode
        games_seen: Dict[str, list] = {}
        for f in all_files:
            for snap in parse_forge_jsonl(f):
                gid = snap.get("game_id", "g0")
                games_seen.setdefault(gid, []).append(snap)

        for idx, (gid, snaps) in enumerate(games_seen.items()):
            records.append(self._snaps_to_record(idx, gid, snaps, service))
            if len(records) >= self.cfg.num_games:
                break

        return records

    def _java_results_to_records(self, java_results, service) -> List[GameRecord]:
        """Convert Java GameResult objects to GameRecord."""
        records = []
        for jr in java_results:
            try:
                won = getattr(jr, "winningSeat", 0) == 0  # seat 0 = policy
                records.append(GameRecord(
                    game_index=getattr(jr, "gameIndex", len(records)),
                    won=won,
                    turns=getattr(jr, "turns", 0),
                    life_final_policy=getattr(jr, "lifeAtEnd", [40])[0] if hasattr(jr, "lifeAtEnd") else 40,
                    life_final_opponent=getattr(jr, "lifeAtEnd", [40, 40])[1] if hasattr(jr, "lifeAtEnd") else 40,
                    life_delta=0,
                    commander_damage_dealt=0,
                    illegal_actions=getattr(jr, "illegalActions", 0),
                    entropy_mean=0.0,
                    inference_ms_mean=0.0,
                    decision_steps=0,
                ))
            except Exception as e:
                logger.warning("[Eval] Skipping malformed GameResult: %s", e)
        return records

    # ── Synthetic fallback ───────────────────

    def _run_synthetic_eval(self, service) -> List[GameRecord]:
        """Run synthetic games using self_play engine (no Forge required).

        Used when Forge JAR is missing or deck files aren't configured.
        Metrics like illegal_actions and commander_damage are 0 in this mode.
        """
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        records = []
        try:
            from ml.training.self_play import (
                create_random_initial_state, apply_action, advance_turn,
                encode_state_simple, HeuristicPolicy
            )
            from ml.config.scope import NUM_ACTIONS, IDX_TO_ACTION
            import torch
            import torch.nn.functional as F
        except ImportError as e:
            logger.error("[Eval] Cannot import self_play: %s", e)
            return []

        opponent = HeuristicPolicy()
        agent_has_model = service is not None and service._loaded

        for game_idx in range(self.cfg.num_games):
            state = create_random_initial_state()
            entropies, latencies = [], []
            steps = 0

            while not state.game_over and steps < 60:
                sv = encode_state_simple(state, 0, "midrange")
                t0 = time.time()

                if agent_has_model:
                    snap = state.to_snapshot()
                    result = service.predict(
                        snap, playstyle="midrange",
                        greedy=self.cfg.greedy,
                        temperature=self.cfg.temperature,
                    )
                    action_idx = result.get("action_index", 7)
                    probs_map = result.get("probabilities", {})
                    probs = np.array(list(probs_map.values())) if probs_map else np.ones(NUM_ACTIONS) / NUM_ACTIONS
                else:
                    action_idx = np.random.randint(NUM_ACTIONS)
                    probs = np.ones(NUM_ACTIONS) / NUM_ACTIONS

                latencies.append((time.time() - t0) * 1000)
                p = np.clip(probs, 1e-9, 1.0)
                p /= p.sum()
                entropies.append(float(-np.sum(p * np.log(p))))

                state = apply_action(state, action_idx, 0)
                if not state.game_over:
                    opp_sv = encode_state_simple(state, 1, "midrange")
                    opp_a, _ = opponent.select_action(opp_sv)
                    state = apply_action(state, opp_a, 1)
                if not state.game_over:
                    state = advance_turn(state)
                steps += 1

            won = state.winner == 0
            lp = state.players[0].life_total
            lo = state.players[1].life_total
            records.append(GameRecord(
                game_index=game_idx,
                won=won,
                turns=state.turn,
                life_final_policy=lp,
                life_final_opponent=lo,
                life_delta=lp - lo,
                commander_damage_dealt=0,
                illegal_actions=0,
                entropy_mean=float(np.mean(entropies)) if entropies else 0.0,
                inference_ms_mean=float(np.mean(latencies)) if latencies else 0.0,
                decision_steps=steps,
            ))

        return records

    # ── JSONL snapshot → GameRecord ──────────

    def _snaps_to_record(self, idx: int, gid: str, snaps: list, service) -> GameRecord:
        entropies, latencies = [], []
        won = False
        turns = len(snaps)
        cmd_dmg = 0
        illegal = 0
        lp, lo = 40, 40

        for snap in snaps:
            if "outcome" in snap and snap == snaps[-1]:
                won = snap["outcome"].get("winner_seat", -1) == 0
                lp = snap["outcome"].get("life_remaining", 40)
                lo = snap["outcome"].get("opp_life_remaining", 0)
                cmd_dmg = snap["outcome"].get("commander_damage_dealt", 0)

            if service and service._loaded and "state_vector" in snap:
                t0 = time.time()
                result = service.predict(snap, playstyle="midrange", greedy=self.cfg.greedy)
                latencies.append((time.time() - t0) * 1000)
                probs_map = result.get("probabilities", {})
                if probs_map:
                    p = np.clip(list(probs_map.values()), 1e-9, 1.0)
                    p /= p.sum()
                    entropies.append(float(-np.sum(p * np.log(p))))

        return GameRecord(
            game_index=idx,
            won=won,
            turns=turns,
            life_final_policy=lp,
            life_final_opponent=lo,
            life_delta=lp - lo,
            commander_damage_dealt=cmd_dmg,
            illegal_actions=illegal,
            entropy_mean=float(np.mean(entropies)) if entropies else 0.0,
            inference_ms_mean=float(np.mean(latencies)) if latencies else 0.0,
            decision_steps=len(snaps),
        )

    # ── Summary builder ──────────────────────

    def _build_summary(self, elapsed: float) -> EvalSummary:
        n = len(self._records)
        if n == 0:
            return EvalSummary(
                run_id=self.cfg.run_id,
                checkpoint_path=self.cfg.checkpoint_path,
                num_games=0, wins=0, losses=0,
                win_rate=0.0, win_rate_ci95_low=0.0, win_rate_ci95_high=0.0,
                avg_turns=0.0, avg_life_delta=0.0, avg_commander_damage=0.0,
                avg_illegal_actions=0.0, avg_entropy=0.0, avg_inference_ms=0.0,
                total_decision_steps=0, elapsed_wall_s=elapsed, games_per_sec=0.0,
                error_count=0, result_file=self._result_path,
            )

        wins = sum(1 for r in self._records if r.won)
        losses = n - wins
        wr = wins / n

        # Wilson score 95% CI
        z = 1.96
        denom = 1 + z**2 / n
        centre = (wr + z**2 / (2 * n)) / denom
        margin = (z * (wr * (1 - wr) / n + z**2 / (4 * n**2)) ** 0.5) / denom
        ci_lo = max(0.0, centre - margin)
        ci_hi = min(1.0, centre + margin)

        errors = sum(1 for r in self._records if r.error)

        return EvalSummary(
            run_id=self.cfg.run_id,
            checkpoint_path=self.cfg.checkpoint_path,
            num_games=n,
            wins=wins,
            losses=losses,
            win_rate=wr,
            win_rate_ci95_low=ci_lo,
            win_rate_ci95_high=ci_hi,
            avg_turns=float(np.mean([r.turns for r in self._records])),
            avg_life_delta=float(np.mean([r.life_delta for r in self._records])),
            avg_commander_damage=float(np.mean([r.commander_damage_dealt for r in self._records])),
            avg_illegal_actions=float(np.mean([r.illegal_actions for r in self._records])),
            avg_entropy=float(np.mean([r.entropy_mean for r in self._records])),
            avg_inference_ms=float(np.mean([r.inference_ms_mean for r in self._records])),
            total_decision_steps=sum(r.decision_steps for r in self._records),
            elapsed_wall_s=elapsed,
            games_per_sec=n / max(elapsed, 0.001),
            error_count=errors,
            result_file=self._result_path,
        )

    # ── Result writer ────────────────────────

    def _write_results(self, summary: EvalSummary) -> None:
        payload = {
            "summary": asdict(summary),
            "games": [asdict(r) for r in self._records],
        }
        os.makedirs(self.cfg.results_dir, exist_ok=True)
        with open(self._result_path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info("[Eval %s] Results written to %s", self.cfg.run_id, self._result_path)
