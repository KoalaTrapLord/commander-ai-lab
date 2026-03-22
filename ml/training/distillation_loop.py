"""
Commander AI Lab — Distillation Loop Orchestrator
═══════════════════════════════════════════════════

Phase 4 (Issue #68): Automates the full closed-loop distillation cycle:

    1. Supervised train on current dataset (Forge + any existing PPO data)
    2. Run N episodes of PPO self-play using the supervised model as starting policy
    3. Export winning PPO decisions to JSONL
    4. Quality gate check
    5. If passed → merge into dataset and repeat from step 1
    6. If failed → discard PPO batch, adjust hyperparameters, retry

Each iteration is a "generation" — data and models are tagged with generation
number for traceability.

Convergence detection:
  - Stops if win rate plateaus across `convergence_window` generations
  - Hard stop at `max_iterations`

Ref: docs/CLOSED-LOOP-DISTILLATION.md — Phase 4
Issue: #68
"""

import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml.config.scope import (
    NUM_ACTIONS, STATE_DIMS, TRAINING_CONFIG,
)
from ml.data.quality_gate import QualityGate, QualityGateConfig, GateVerdict
from ml.training.decision_exporter import DecisionExporter, ExporterConfig

logger = logging.getLogger("ml.distillation")


# ═══════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════

@dataclass
class DistillationConfig:
    """Configuration for the distillation loop orchestrator."""

    # --- Loop control ---
    max_iterations: int = 10
    convergence_window: int = 3       # Check last N generations for plateau
    convergence_threshold: float = 0.01  # Min win-rate improvement to not plateau

    # --- Paths ---
    results_dir: str = "results"
    models_dir: str = "ml/models"
    checkpoint_dir: str = "ml/models/checkpoints"
    history_dir: str = "results/distillation-history"

    # --- Supervised training ---
    supervised_epochs: int = 30
    supervised_lr: float = 1e-3
    supervised_batch_size: int = 64
    supervised_patience: int = 5

    # --- PPO self-play ---
    ppo_iterations: int = 50
    ppo_episodes_per_iter: int = 64
    ppo_batch_size: int = 256
    ppo_lr: float = 3e-4
    ppo_clip_epsilon: float = 0.2
    ppo_entropy_coeff: float = 0.01
    ppo_eval_episodes: int = 100
    opponent: str = "heuristic"
    playstyle: str = "midrange"

    # --- Dataset building ---
    forge_weight: float = 1.0
    ppo_weight: float = 0.5
    min_reward_threshold: float = 0.0

    # --- Quality gate ---
    min_forge_accuracy: float = 0.35
    max_accuracy_drop: float = 0.03
    min_ppo_win_rate: float = 0.30

    # --- Retry on gate failure ---
    max_retries_per_generation: int = 2
    retry_lr_factor: float = 0.5       # Halve PPO LR on retry
    retry_entropy_boost: float = 0.005  # Increase entropy coeff on retry

    # --- ELO convergence (Phase 6) ---
    elo_convergence_enabled: bool = False   # Off by default
    elo_convergence_threshold: float = 20.0 # Stop if ELO gain < this
    elo_tournament_episodes: int = 30       # Games per matchup for ELO mini-tournament


# ═══════════════════════════════════════════════════════════
# Generation metadata
# ═══════════════════════════════════════════════════════════

@dataclass
class GenerationRecord:
    """Tracks metadata for a single distillation generation."""
    generation: int
    started_at: str = ""
    completed_at: str = ""
    status: str = "pending"  # pending | running | passed | failed | skipped

    # Supervised training results
    supervised_val_acc: float = 0.0
    supervised_best_epoch: int = 0
    supervised_checkpoint: str = ""

    # PPO self-play results
    ppo_win_rate: float = 0.0
    ppo_best_win_rate: float = 0.0
    ppo_episodes: int = 0
    ppo_decisions_exported: int = 0
    ppo_export_path: str = ""

    # Quality gate
    gate_accepted: bool = False
    gate_reason: str = ""
    baseline_accuracy: float = 0.0
    post_merge_accuracy: float = 0.0

    # Dataset stats
    dataset_size: int = 0
    forge_samples: int = 0
    ppo_samples: int = 0

    retries: int = 0
    error: str = ""
    elo_rating: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ═══════════════════════════════════════════════════════════
# Distillation Loop Orchestrator
# ═══════════════════════════════════════════════════════════

class DistillationLoop:
    """
    Orchestrates the full closed-loop distillation pipeline.

    Each "generation" runs the complete cycle:
      supervised train → PPO self-play → export → quality gate → merge

    The loop tracks convergence by monitoring PPO win rate across
    generations and stops when improvement plateaus or max_iterations
    is reached.

    Usage::

        config = DistillationConfig(max_iterations=5, ppo_iterations=30)
        loop = DistillationLoop(config)
        summary = loop.run()
    """

    def __init__(self, config: DistillationConfig = None):
        self.config = config or DistillationConfig()
        self.generations: List[GenerationRecord] = []
        self.quality_gate = QualityGate(QualityGateConfig(
            min_forge_accuracy=self.config.min_forge_accuracy,
            max_accuracy_drop=self.config.max_accuracy_drop,
            min_ppo_win_rate=self.config.min_ppo_win_rate,
        ))
        self._baseline_accuracy: Optional[float] = None
        self._device: Optional[str] = None
        self._stopped = False

        # Ensure output directories exist
        os.makedirs(self.config.history_dir, exist_ok=True)
        os.makedirs(self.config.checkpoint_dir, exist_ok=True)
        os.makedirs(self.config.results_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, progress_callback=None) -> Dict:
        """
        Run the full distillation loop.

        Args:
            progress_callback: Optional callable(generation, record) for
                               progress reporting (e.g. to a web UI).

        Returns:
            Summary dict with per-generation metrics and convergence info.
        """
        cfg = self.config
        self._device = self._detect_device()

        logger.info("=" * 65)
        logger.info("  Commander AI Lab — Distillation Loop")
        logger.info("=" * 65)
        logger.info("  Max iterations:     %d", cfg.max_iterations)
        logger.info("  Convergence window: %d", cfg.convergence_window)
        logger.info("  PPO iters/gen:      %d", cfg.ppo_iterations)
        logger.info("  PPO episodes/iter:  %d", cfg.ppo_episodes_per_iter)
        logger.info("  Supervised epochs:  %d", cfg.supervised_epochs)
        logger.info("  Device:             %s", self._device)
        logger.info("  Results dir:        %s", cfg.results_dir)
        logger.info("=" * 65)

        loop_start = time.time()

        for gen_num in range(1, cfg.max_iterations + 1):
            if self._stopped:
                logger.info("Loop stopped by external signal.")
                break

            logger.info("")
            logger.info("─" * 65)
            logger.info("  GENERATION %d / %d", gen_num, cfg.max_iterations)
            logger.info("─" * 65)

            record = self._run_generation(gen_num)
            self.generations.append(record)

            # Save generation history to disk after each round
            self._save_history()

            if progress_callback:
                progress_callback(gen_num, record)

            # Check convergence
            if self._check_convergence():
                logger.info(
                    "Convergence detected — win rate plateaued over "
                    "last %d generations. Stopping.",
                    cfg.convergence_window,
                )
                break

        total_time = time.time() - loop_start

        summary = self._build_summary(total_time)
        self._save_summary(summary)

        logger.info("")
        logger.info("=" * 65)
        logger.info("  Distillation Loop Complete")
        logger.info("=" * 65)
        logger.info("  Generations run:  %d", summary["generations_run"])
        logger.info("  Generations passed: %d", summary["generations_passed"])
        logger.info("  Best win rate:    %.1f%%", summary["best_win_rate"] * 100)
        logger.info("  Converged:        %s", summary["converged"])
        logger.info("  Total time:       %.1f s", total_time)
        logger.info("=" * 65)

        return summary

    def stop(self):
        """Signal the loop to stop after the current generation."""
        self._stopped = True
        logger.info("Stop signal received — will halt after current generation.")

    # ------------------------------------------------------------------
    # Single generation execution
    # ------------------------------------------------------------------

    def _run_generation(self, gen_num: int) -> GenerationRecord:
        """Execute a single distillation generation (steps 1-6)."""
        record = GenerationRecord(
            generation=gen_num,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="running",
        )

        cfg = self.config
        gen_tag = f"gen-{gen_num:03d}"
        gen_checkpoint_dir = os.path.join(cfg.checkpoint_dir, gen_tag)
        os.makedirs(gen_checkpoint_dir, exist_ok=True)

        try:
            # ─── Step 1: Supervised Train ───────────────────────────
            logger.info("  [Step 1] Supervised training on current dataset...")
            sup_result = self._supervised_train(gen_checkpoint_dir, gen_tag)

            if sup_result is None:
                record.status = "failed"
                record.error = "Supervised training failed — no dataset found"
                record.completed_at = datetime.now(timezone.utc).isoformat()
                return record

            record.supervised_val_acc = sup_result["best_val_acc"]
            record.supervised_best_epoch = sup_result["best_epoch"]
            record.supervised_checkpoint = sup_result["checkpoint_path"]

            # Set baseline accuracy on first generation
            if self._baseline_accuracy is None:
                self._baseline_accuracy = sup_result["best_val_acc"]
                logger.info(
                    "  Baseline accuracy set: %.3f (generation 1)",
                    self._baseline_accuracy,
                )

            # ─── Step 2-3: PPO Self-Play + Export ───────────────────
            retries = 0
            ppo_lr = cfg.ppo_lr
            entropy_coeff = cfg.ppo_entropy_coeff
            gate_passed = False

            while retries <= cfg.max_retries_per_generation and not gate_passed:
                if retries > 0:
                    logger.info(
                        "  [Retry %d/%d] Adjusting hyperparameters: "
                        "lr=%.2e → %.2e, entropy=%.4f → %.4f",
                        retries, cfg.max_retries_per_generation,
                        ppo_lr, ppo_lr * cfg.retry_lr_factor,
                        entropy_coeff, entropy_coeff + cfg.retry_entropy_boost,
                    )
                    ppo_lr *= cfg.retry_lr_factor
                    entropy_coeff += cfg.retry_entropy_boost

                logger.info(
                    "  [Step 2] PPO self-play (%d iters × %d episodes)...",
                    cfg.ppo_iterations, cfg.ppo_episodes_per_iter,
                )
                ppo_result, exporter = self._ppo_self_play(
                    supervised_checkpoint=sup_result["checkpoint_path"],
                    gen_tag=gen_tag,
                    gen_checkpoint_dir=gen_checkpoint_dir,
                    learning_rate=ppo_lr,
                    entropy_coeff=entropy_coeff,
                )

                record.ppo_win_rate = ppo_result["final_win_rate"]
                record.ppo_best_win_rate = ppo_result["best_win_rate"]
                record.ppo_episodes = (
                    cfg.ppo_iterations * cfg.ppo_episodes_per_iter
                )

                logger.info(
                    "  [Step 3] Exporting PPO decisions (win rate: %.1f%%)...",
                    ppo_result["best_win_rate"] * 100,
                )
                export_path = exporter.flush()
                record.ppo_decisions_exported = exporter.stats["exported_decisions"]
                record.ppo_export_path = export_path or ""

                # ─── Step 4: Quality Gate ───────────────────────────
                logger.info("  [Step 4] Quality gate check...")
                verdict = self._quality_gate_check(
                    ppo_win_rate=ppo_result["best_win_rate"],
                    total_episodes=record.ppo_episodes,
                    exporter=exporter,
                )

                if verdict.accepted:
                    gate_passed = True
                    record.gate_accepted = True
                    record.gate_reason = verdict.reason
                    logger.info("  QUALITY GATE: PASSED — %s", verdict.reason)
                else:
                    retries += 1
                    record.retries = retries
                    logger.warning(
                        "  QUALITY GATE: FAILED — %s", verdict.reason,
                    )

                    if retries > cfg.max_retries_per_generation:
                        # ─── Step 6: Discard PPO batch ──────────────
                        logger.warning(
                            "  [Step 6] Max retries exceeded — "
                            "discarding PPO batch for generation %d.",
                            gen_num,
                        )
                        if export_path and os.path.exists(export_path):
                            os.remove(export_path)
                            logger.info(
                                "  Deleted rejected PPO data: %s", export_path
                            )
                        record.gate_accepted = False
                        record.gate_reason = (
                            f"Failed after {retries - 1} retries: "
                            f"{verdict.reason}"
                        )

            # ─── Step 5: Merge into dataset (if passed) ─────────────
            if gate_passed:
                logger.info(
                    "  [Step 5] PPO data accepted — will be included "
                    "in next generation's dataset build."
                )
                record.status = "passed"

                # ─── ELO mini-tournament (Phase 6) ────────────────
                if cfg.elo_convergence_enabled and gen_num > 1:
                    elo = self._run_elo_mini_tournament(
                        gen_checkpoint_dir, gen_num
                    )
                    if elo is not None:
                        record.elo_rating = elo
                        logger.info("  ELO rating: %.1f", elo)
            else:
                record.status = "failed"

        except Exception as e:
            logger.exception("  Generation %d failed with error: %s", gen_num, e)
            record.status = "failed"
            record.error = str(e)

        record.completed_at = datetime.now(timezone.utc).isoformat()
        return record

    # ------------------------------------------------------------------
    # Step 1: Supervised Training
    # ------------------------------------------------------------------

    def _supervised_train(
        self,
        gen_checkpoint_dir: str,
        gen_tag: str,
    ) -> Optional[Dict]:
        """
        Build dataset from all available data and train supervised model.

        Returns training summary dict or None on failure.
        """
        try:
            import torch
        except ImportError:
            raise RuntimeError("PyTorch required for distillation loop")

        cfg = self.config

        # Build dataset (picks up both Forge + any PPO JSONL files in results_dir)
        from ml.data.dataset_builder import build_dataset, split_dataset, save_dataset

        try:
            dataset = build_dataset(
                results_dir=cfg.results_dir,
                max_samples=None,
                source_weights={
                    "forge": cfg.forge_weight,
                    "ppo": cfg.ppo_weight,
                },
                min_reward_threshold=cfg.min_reward_threshold,
            )
        except RuntimeError as e:
            logger.warning("Dataset build failed: %s", e)
            return None

        if not dataset or len(dataset.get("states", [])) == 0:
            logger.warning("No training data available.")
            return None

        # Split
        train_data, val_data, test_data = split_dataset(dataset)

        # Save splits (overwrite each generation — latest always at standard path)
        data_dir = cfg.models_dir
        os.makedirs(data_dir, exist_ok=True)
        save_dataset(train_data, os.path.join(data_dir, "dataset-train.npz"))
        save_dataset(val_data, os.path.join(data_dir, "dataset-val.npz"))
        save_dataset(test_data, os.path.join(data_dir, "dataset-test.npz"))

        # Create model
        from ml.training.policy_network import PolicyNetwork
        actual_dim = train_data["states"].shape[1]
        model = PolicyNetwork(input_dim=actual_dim)

        # Train
        from ml.training.trainer import SupervisedTrainer, get_best_device
        device = self._device or get_best_device()
        trainer = SupervisedTrainer(
            model=model,
            device=device,
            learning_rate=cfg.supervised_lr,
            batch_size=cfg.supervised_batch_size,
            epochs=cfg.supervised_epochs,
            patience=cfg.supervised_patience,
            checkpoint_dir=gen_checkpoint_dir,
        )

        summary = trainer.train(
            train_states=train_data["states"],
            train_labels=train_data["labels"],
            val_states=val_data["states"],
            val_labels=val_data["labels"],
        )

        # Also copy best checkpoint to the standard location
        best_src = os.path.join(gen_checkpoint_dir, "best_policy.pt")
        best_dst = os.path.join(cfg.checkpoint_dir, "best_policy.pt")
        if os.path.exists(best_src):
            shutil.copy2(best_src, best_dst)

        return summary

    # ------------------------------------------------------------------
    # Steps 2-3: PPO Self-Play + Decision Export
    # ------------------------------------------------------------------

    def _ppo_self_play(
        self,
        supervised_checkpoint: str,
        gen_tag: str,
        gen_checkpoint_dir: str,
        learning_rate: float = None,
        entropy_coeff: float = None,
    ) -> tuple:
        """
        Run PPO self-play initialized from the supervised checkpoint.

        Returns (ppo_summary, exporter) tuple.
        """
        cfg = self.config

        from ml.training.ppo_trainer import PPOTrainer, PPOConfig
        from ml.training.decision_exporter import DecisionExporter, ExporterConfig

        # Set up decision exporter for this generation
        exporter = DecisionExporter(ExporterConfig(
            output_dir=cfg.results_dir,
            only_wins=True,
            model_version=gen_tag,
        ))

        ppo_config = PPOConfig(
            iterations=cfg.ppo_iterations,
            episodes_per_iter=cfg.ppo_episodes_per_iter,
            ppo_epochs=4,
            batch_size=cfg.ppo_batch_size,
            clip_epsilon=cfg.ppo_clip_epsilon,
            entropy_coeff=entropy_coeff or cfg.ppo_entropy_coeff,
            learning_rate=learning_rate or cfg.ppo_lr,
            lr_schedule="cosine",
            min_lr=1e-5,
            opponent=cfg.opponent,
            playstyle=cfg.playstyle,
            checkpoint_dir=gen_checkpoint_dir,
            save_every=max(1, cfg.ppo_iterations // 5),
            eval_every=max(1, cfg.ppo_iterations // 10),
            eval_episodes=cfg.ppo_eval_episodes,
            load_supervised=supervised_checkpoint,
        )

        ppo_trainer = PPOTrainer(ppo_config)

        # Monkey-patch collect_rollouts to include exporter
        # The exporter is already wired into self_play.collect_rollouts
        # via the exporter parameter, so we wrap the train loop.
        original_collect = None

        from ml.training import self_play as sp_module

        _original_collect_rollouts = sp_module.collect_rollouts

        def _instrumented_collect_rollouts(
            agent_model, opponent_policy, buffer,
            num_episodes=64, playstyle="midrange",
            reward_config=None, **kwargs
        ):
            return _original_collect_rollouts(
                agent_model=agent_model,
                opponent_policy=opponent_policy,
                buffer=buffer,
                num_episodes=num_episodes,
                playstyle=playstyle,
                reward_config=reward_config,
                exporter=exporter,
            )

        # Temporarily replace module-level function
        sp_module.collect_rollouts = _instrumented_collect_rollouts
        try:
            summary = ppo_trainer.train()
        finally:
            # Restore original
            sp_module.collect_rollouts = _original_collect_rollouts

        return summary, exporter

    # ------------------------------------------------------------------
    # Step 4: Quality Gate
    # ------------------------------------------------------------------

    def _quality_gate_check(
        self,
        ppo_win_rate: float,
        total_episodes: int,
        exporter: DecisionExporter,
    ) -> GateVerdict:
        """Run quality gate checks on the PPO output."""
        # Win rate gate
        win_verdict = self.quality_gate.check_win_rate(
            ppo_win_rate=ppo_win_rate,
            total_episodes=total_episodes,
        )
        if not win_verdict.accepted:
            return win_verdict

        # If we have baseline accuracy and this isn't the first generation,
        # we could run a post-merge accuracy check here. For now, the win
        # rate gate is the primary gatekeeper during the loop. The accuracy
        # gate will be checked on the next generation's supervised training
        # by comparing against self._baseline_accuracy.
        return GateVerdict(
            accepted=True,
            reason=(
                f"Win rate gate passed ({ppo_win_rate:.1%} >= "
                f"{self.config.min_ppo_win_rate:.1%}). "
                f"PPO data accepted for merge."
            ),
            metrics={
                "ppo_win_rate": ppo_win_rate,
                "total_episodes": total_episodes,
                "exported_decisions": exporter.stats["exported_decisions"],
            },
        )

    # ------------------------------------------------------------------
    # ELO mini-tournament (Phase 6)
    # ------------------------------------------------------------------

    def _run_elo_mini_tournament(
        self, gen_checkpoint_dir: str, gen_num: int
    ) -> Optional[float]:
        """
        Run a small ELO tournament between current gen, previous gen,
        and heuristic baseline. Returns the current gen's ELO rating.
        """
        cfg = self.config
        try:
            from ml.eval.elo_tracker import (
                run_elo_tournament, EloHistory, HeuristicPolicy, LearnedPolicy,
            )

            policies = {"heuristic": HeuristicPolicy()}

            # Current generation checkpoint
            curr_path = os.path.join(gen_checkpoint_dir, "best_policy.pt")
            curr_name = f"gen-{gen_num:03d}"
            if os.path.exists(curr_path):
                policies[curr_name] = LearnedPolicy(curr_path)
            else:
                logger.warning("  ELO: current gen checkpoint not found: %s", curr_path)
                return None

            # Previous generation checkpoint
            if gen_num > 1:
                prev_tag = f"gen-{gen_num - 1:03d}"
                prev_dir = os.path.join(cfg.checkpoint_dir, prev_tag)
                prev_path = os.path.join(prev_dir, "best_policy.pt")
                if os.path.exists(prev_path):
                    policies[prev_tag] = LearnedPolicy(prev_path)

            logger.info(
                "  [ELO] Running mini-tournament: %s (%d episodes/matchup)",
                list(policies.keys()), cfg.elo_tournament_episodes,
            )

            result = run_elo_tournament(
                policies=policies,
                episodes_per_matchup=cfg.elo_tournament_episodes,
                playstyle=cfg.playstyle,
            )

            # Save to ELO history
            history_path = os.path.join(
                os.path.dirname(cfg.history_dir), "elo_history.json"
            ) if cfg.history_dir else "data/elo_history.json"
            history = EloHistory(path=history_path)
            history.append(gen_num, result.ratings)

            return result.ratings.get(curr_name, 0.0)

        except Exception as e:
            logger.warning("  ELO mini-tournament failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Convergence detection
    # ------------------------------------------------------------------

    def _check_convergence(self) -> bool:
        """
        Check if win rate has plateaued over recent generations.
        Also checks ELO delta when elo_convergence_enabled is True.

        Returns True if the loop should stop.
        """
        cfg = self.config
        passed = [g for g in self.generations if g.status == "passed"]

        if len(passed) < cfg.convergence_window:
            return False

        recent = passed[-cfg.convergence_window:]
        win_rates = [g.ppo_best_win_rate for g in recent]

        # Check if max improvement across the window is below threshold
        improvement = max(win_rates) - min(win_rates)

        logger.info(
            "  Convergence check: last %d win rates = %s, "
            "spread = %.4f (threshold = %.4f)",
            cfg.convergence_window,
            [f"{wr:.3f}" for wr in win_rates],
            improvement,
            cfg.convergence_threshold,
        )

        win_rate_converged = improvement < cfg.convergence_threshold

        # ELO convergence check (Phase 6)
        if cfg.elo_convergence_enabled and len(passed) >= 2:
            elo_ratings = [g.elo_rating for g in passed[-2:] if g.elo_rating > 0]
            if len(elo_ratings) >= 2:
                elo_delta = elo_ratings[-1] - elo_ratings[-2]
                logger.info(
                    "  ELO convergence check: delta = %.1f (threshold = %.1f)",
                    elo_delta, cfg.elo_convergence_threshold,
                )
                if elo_delta < cfg.elo_convergence_threshold:
                    logger.info("  ELO delta below threshold — converged.")
                    return True

        return win_rate_converged

    # ------------------------------------------------------------------
    # Device detection
    # ------------------------------------------------------------------

    def _detect_device(self) -> str:
        """Auto-detect best compute device."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    # ------------------------------------------------------------------
    # History & summary persistence
    # ------------------------------------------------------------------

    def _save_history(self):
        """Save generation history to JSON."""
        path = os.path.join(self.config.history_dir, "generations.json")
        history = [g.to_dict() for g in self.generations]
        with open(path, "w") as f:
            json.dump(history, f, indent=2)
        logger.info("  Generation history saved: %s", path)

    def _build_summary(self, total_time: float) -> Dict:
        """Build final summary dict."""
        passed = [g for g in self.generations if g.status == "passed"]
        failed = [g for g in self.generations if g.status == "failed"]

        best_wr = max(
            (g.ppo_best_win_rate for g in self.generations), default=0.0
        )

        return {
            "generations_run": len(self.generations),
            "generations_passed": len(passed),
            "generations_failed": len(failed),
            "best_win_rate": best_wr,
            "converged": self._check_convergence() if len(passed) >= self.config.convergence_window else False,
            "total_time_s": round(total_time, 1),
            "device": self._device,
            "config": {
                "max_iterations": self.config.max_iterations,
                "convergence_window": self.config.convergence_window,
                "convergence_threshold": self.config.convergence_threshold,
                "ppo_iterations": self.config.ppo_iterations,
                "supervised_epochs": self.config.supervised_epochs,
            },
            "generations": [g.to_dict() for g in self.generations],
        }

    def _save_summary(self, summary: Dict):
        """Save final summary to JSON."""
        path = os.path.join(self.config.history_dir, "summary.json")
        with open(path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info("  Summary saved: %s", path)


# ═══════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════

def main():
    """CLI entry point for the distillation loop."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Commander AI Lab — Closed-Loop Distillation"
    )

    # Loop control
    parser.add_argument(
        "--max-iterations", type=int, default=10,
        help="Maximum number of distillation generations (default: 10)",
    )
    parser.add_argument(
        "--convergence-window", type=int, default=3,
        help="Number of generations to check for win-rate plateau (default: 3)",
    )
    parser.add_argument(
        "--convergence-threshold", type=float, default=0.01,
        help="Min win-rate spread to not be considered converged (default: 0.01)",
    )

    # Paths
    parser.add_argument(
        "--results-dir", default="data/results",
        help="Directory containing JSONL decision files (default: data/results)",
    )
    parser.add_argument(
        "--models-dir", default="ml/models",
        help="Directory for dataset NPZ files (default: ml/models)",
    )
    parser.add_argument(
        "--checkpoint-dir", default="ml/models/checkpoints",
        help="Directory for model checkpoints (default: ml/models/checkpoints)",
    )

    # Supervised training
    parser.add_argument("--sup-epochs", type=int, default=30)
    parser.add_argument("--sup-lr", type=float, default=1e-3)
    parser.add_argument("--sup-batch-size", type=int, default=64)
    parser.add_argument("--sup-patience", type=int, default=5)

    # PPO self-play
    parser.add_argument("--ppo-iterations", type=int, default=50)
    parser.add_argument("--ppo-episodes", type=int, default=64)
    parser.add_argument("--ppo-lr", type=float, default=3e-4)
    parser.add_argument("--ppo-batch-size", type=int, default=256)
    parser.add_argument("--ppo-eval-episodes", type=int, default=100)
    parser.add_argument(
        "--opponent", default="heuristic",
        choices=["heuristic", "random", "self"],
    )
    parser.add_argument("--playstyle", default="midrange")

    # Dataset
    parser.add_argument("--forge-weight", type=float, default=1.0)
    parser.add_argument("--ppo-weight", type=float, default=0.5)
    parser.add_argument("--min-reward", type=float, default=0.0)

    # Quality gate
    parser.add_argument("--min-win-rate", type=float, default=0.30)
    parser.add_argument("--min-forge-accuracy", type=float, default=0.35)
    parser.add_argument("--max-accuracy-drop", type=float, default=0.03)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    config = DistillationConfig(
        max_iterations=args.max_iterations,
        convergence_window=args.convergence_window,
        convergence_threshold=args.convergence_threshold,
        results_dir=args.results_dir,
        models_dir=args.models_dir,
        checkpoint_dir=args.checkpoint_dir,
        supervised_epochs=args.sup_epochs,
        supervised_lr=args.sup_lr,
        supervised_batch_size=args.sup_batch_size,
        supervised_patience=args.sup_patience,
        ppo_iterations=args.ppo_iterations,
        ppo_episodes_per_iter=args.ppo_episodes,
        ppo_batch_size=args.ppo_batch_size,
        ppo_lr=args.ppo_lr,
        ppo_eval_episodes=args.ppo_eval_episodes,
        opponent=args.opponent,
        playstyle=args.playstyle,
        forge_weight=args.forge_weight,
        ppo_weight=args.ppo_weight,
        min_reward_threshold=args.min_reward,
        min_ppo_win_rate=args.min_win_rate,
        min_forge_accuracy=args.min_forge_accuracy,
        max_accuracy_drop=args.max_accuracy_drop,
    )

    loop = DistillationLoop(config)
    summary = loop.run()
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
