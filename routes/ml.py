"""
routes/ml.py
============
ML training data, policy inference, supervised training,
PPO training, and tournament endpoints.

  GET  /api/ml/status
  GET  /api/ml/decisions/{filename}
  GET  /api/ml/data/status
  POST /api/ml/toggle
  POST /api/ml/predict
  POST /api/ml/predict/batch
  GET  /api/ml/model
  POST /api/ml/reload
  POST /api/ml/train
  GET  /api/ml/train/status
  POST /api/ml/train/ppo
  GET  /api/ml/train/ppo/status
  POST /api/ml/tournament
  GET  /api/ml/tournament/status
  GET  /api/ml/tournament/results
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest

from models.state import CFG
from services.logging import _ml_logging_enabled

log_ml = logging.getLogger("commander_ai_lab.ml")

router = APIRouter(tags=["ml"])

# ── module-level singletons ──────────────────────────────────────────────────
_policy_service = None
_policy_service_init_attempted = False

# ── Thread-safe state objects ────────────────────────────────────────────────
@dataclasses.dataclass
class _TrainingState:
    running: bool = False
    progress: int = 0
    total_epochs: int = 0
    current_epoch: int = 0
    phase: str = "idle"
    message: str = ""
    metrics: object = None
    result: object = None
    error: object = None
    started_at: object = None

    def snapshot(self) -> dict:
        return dataclasses.asdict(self)

@dataclasses.dataclass
class _PPOState:
    running: bool = False
    iteration: int = 0
    total_iterations: int = 0
    phase: str = "idle"
    message: str = ""
    metrics: object = None
    result: object = None
    error: object = None

    def snapshot(self) -> dict:
        return dataclasses.asdict(self)

@dataclasses.dataclass
class _TournamentState:
    running: bool = False
    phase: str = "idle"
    message: str = ""
    result: object = None
    error: object = None

    def snapshot(self) -> dict:
        return dataclasses.asdict(self)

_training_state = _TrainingState()
_training_lock  = threading.Lock()

_ppo_state  = _PPOState()
_ppo_lock   = threading.Lock()

_tournament_state = _TournamentState()
_tournament_lock  = threading.Lock()

# module-level toggle (local copy; the shared one is for batch runs)
_ml_logging_enabled_local = _ml_logging_enabled


def _get_policy_service():
    """Get or initialize the policy inference service (lazy loading)."""
    global _policy_service, _policy_service_init_attempted
    if _policy_service is None and not _policy_service_init_attempted:
        _policy_service_init_attempted = True
        try:
            from ml.serving.policy_server import PolicyInferenceService
            _policy_service = PolicyInferenceService()
            if _policy_service.load():
                log_ml.info(f"Policy model loaded on {_policy_service.device}")
            else:
                log_ml.error(f"Policy model not available: {_policy_service._load_error}")
        except Exception as e:
            log_ml.error(f"Policy service init failed: {e}")
    return _policy_service


# ==============================================================
# ML Training Data Endpoints
# ==============================================================

@router.get("/api/ml/status")
async def ml_status():
    """Get ML decision logging status and available training data."""
    import services.logging as _logging_mod
    lab_root = Path(__file__).resolve().parent.parent
    results_dir = lab_root / CFG.results_dir
    ml_files = []
    if results_dir.exists():
        for f in sorted(results_dir.glob("ml-decisions-*.jsonl")):
            lines = 0
            try:
                with open(f) as fh:
                    lines = sum(1 for _ in fh)
            except Exception:
                pass
            ml_files.append({
                "file": f.name,
                "decisions": lines,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    total_decisions = sum(f["decisions"] for f in ml_files)
    return {
        "ml_logging_enabled": _logging_mod._ml_logging_enabled,
        "training_files": ml_files,
        "total_decisions": total_decisions,
        "total_files": len(ml_files),
    }


@router.post("/api/ml/toggle")
async def ml_toggle(enable: bool = True):
    """Enable or disable ML decision logging for future batch runs."""
    import services.logging as _logging_mod
    _logging_mod._ml_logging_enabled = enable
    return {
        "ml_logging_enabled": _logging_mod._ml_logging_enabled,
        "message": f"ML decision logging {'enabled' if enable else 'disabled'} for future batches",
    }


@router.get("/api/ml/decisions/{filename}")
async def ml_get_decisions(filename: str, limit: int = 100, offset: int = 0):
    """Read decision snapshots from a training data file."""
    lab_root = Path(__file__).resolve().parent.parent
    filepath = lab_root / CFG.results_dir / filename
    if not filepath.exists() or not filename.startswith("ml-decisions-"):
        raise HTTPException(404, f"ML decisions file not found: {filename}")
    decisions = []
    try:
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(decisions) >= limit:
                    break
                try:
                    decisions.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        raise HTTPException(500, f"Failed to read decisions: {e}")
    return {
        "file": filename,
        "offset": offset,
        "limit": limit,
        "count": len(decisions),
        "decisions": decisions,
    }


# ==============================================================
# Online Learning Store (SQLite WAL — Phase 5 follow-up)
# ==============================================================

_online_store = None
_online_store_init_attempted = False

def _get_online_store():
    """Lazy-init the online learning store singleton."""
    global _online_store, _online_store_init_attempted
    if _online_store is None and not _online_store_init_attempted:
        _online_store_init_attempted = True
        try:
            from ml.serving.online_learning_store import OnlineLearningStore
            _online_store = OnlineLearningStore()
            _online_store.init_db()
            log_ml.info("Online learning store initialized")
        except Exception as e:
            log_ml.error("Online learning store init failed: %s", e)
    return _online_store


# ==============================================================
# ML Policy Inference Endpoints
# ==============================================================

@router.post("/api/policy/decide")
async def policy_decide(request: FastAPIRequest):
    """Predict a macro-action and log the decision for online learning.

    Combines prediction with automatic data collection: every decision
    is appended to the SQLite WAL-backed online learning store so
    future training runs can incorporate live gameplay data.
    """
    svc = _get_policy_service()
    if svc is None or not svc._loaded:
        detail = "Policy model not loaded. "
        if svc:
            detail += svc._load_error or "Train a model first."
        else:
            detail += "PyTorch may not be installed."
        raise HTTPException(status_code=503, detail=detail)

    body = await request.json()
    playstyle = body.pop("archetype", "midrange")
    temperature = body.pop("temperature", 1.0)
    greedy = body.pop("greedy", False)
    collect = body.pop("collect", True)  # opt-out flag

    result = svc.predict(
        decision_snapshot=body,
        playstyle=playstyle,
        temperature=temperature,
        greedy=greedy,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    # Record to online learning store (fire-and-forget — don't block response)
    if collect:
        store = _get_online_store()
        if store is not None:
            try:
                store.record_decision(
                    snapshot=body,
                    action_idx=result["action_index"],
                    confidence=result["confidence"],
                    playstyle=playstyle,
                    temperature=temperature,
                    greedy=greedy,
                )
            except Exception as e:
                log_ml.warning("Online learning record failed: %s", e)

    return result


@router.get("/api/policy/decide/stats")
async def policy_decide_stats():
    """Return counts of collected online learning decisions."""
    store = _get_online_store()
    if store is None:
        return {"total": 0, "unexported": 0, "error": "Store not initialized"}
    return {
        "total": store.count(),
        "unexported": store.count(only_unexported=True),
    }


@router.post("/api/ml/predict")
async def ml_predict(request: FastAPIRequest):
    """Predict a macro-action from a game state snapshot."""
    svc = _get_policy_service()
    if svc is None or not svc._loaded:
        detail = "Policy model not loaded. "
        if svc:
            detail += svc._load_error or "Train a model first."
        else:
            detail += "PyTorch may not be installed."
        raise HTTPException(status_code=503, detail=detail)
    body = await request.json()
    playstyle = body.pop("archetype", "midrange")
    temperature = body.pop("temperature", 1.0)
    greedy = body.pop("greedy", False)
    result = svc.predict(
        decision_snapshot=body,
        playstyle=playstyle,
        temperature=temperature,
        greedy=greedy,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/api/ml/predict/batch")
async def ml_predict_batch(request: FastAPIRequest):
    """Predict actions for multiple snapshots at once."""
    svc = _get_policy_service()
    if svc is None or not svc._loaded:
        raise HTTPException(status_code=503, detail="Policy model not loaded")
    body = await request.json()
    snapshots = body.get("snapshots", [])
    greedy = body.get("greedy", True)
    if not snapshots:
        return {"results": []}
    results = svc.predict_batch(snapshots, greedy=greedy)
    return {"results": results, "count": len(results)}


@router.get("/api/ml/model")
async def ml_model_info():
    """Get information about the loaded policy model."""
    svc = _get_policy_service()
    if svc is None:
        return {
            "loaded": False,
            "error": "Policy service not initialized",
            "torch_available": False,
        }
    return svc.get_status()


@router.post("/api/ml/reload")
async def ml_reload_model(checkpoint: str = None):
    """Hot-reload a policy model checkpoint."""
    svc = _get_policy_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Policy service not available")
    if not svc._loaded:
        ok = svc.load()
    else:
        ok = svc.reload(checkpoint)
    return {
        "success": ok,
        "status": svc.get_status(),
    }


# ==============================================================
# ML Training Management Endpoints
# ==============================================================

def _run_training_pipeline(
    results_dir: str, epochs: int, lr: float,
    batch_size: int, patience: int, rebuild_dataset: bool,
):
    """Run the full ML training pipeline in a background thread."""
    global _policy_service, _policy_service_init_attempted
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        with _training_lock:
            _training_state.running = True
            _training_state.started_at = datetime.now().isoformat()
            _training_state.error = None
            _training_state.result = None
        data_dir = os.path.join(project_root, "ml", "models")
        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)
        # Phase 1: Build Dataset
        train_path = os.path.join(data_dir, "train.npz")
        if rebuild_dataset or not os.path.exists(train_path):
            with _training_lock:
                _training_state.phase = "building"
                _training_state.message = "Loading card embeddings & building dataset..."
            log_ml.info("Building dataset (loading embeddings, may auto-download)...")
            from ml.data.dataset_builder import build_dataset, split_dataset, save_dataset
            dataset = build_dataset(results_dir=results_dir)
            if not dataset:
                raise RuntimeError("No training data produced. Check server log for details.")
            train_ds, val_ds, test_ds = split_dataset(dataset)
            save_dataset(train_ds, os.path.join(data_dir, "train.npz"))
            save_dataset(val_ds, os.path.join(data_dir, "val.npz"))
            save_dataset(test_ds, os.path.join(data_dir, "test.npz"))
            total_samples = len(dataset["states"])
            with _training_lock:
                _training_state.message = f"Dataset built: {total_samples} samples"
            log_ml.info(f"Dataset built: {total_samples} samples")
        # Phase 2: Train
        with _training_lock:
            _training_state.phase = "training"
            _training_state.total_epochs = epochs
            _training_state.current_epoch = 0
            _training_state.message = f"Training policy network ({epochs} epochs)..."
        log_ml.info(f"Starting training: {epochs} epochs, lr={lr}, bs={batch_size}")
        import numpy as np
        import torch
        from ml.training.policy_network import PolicyNetwork
        from ml.training.trainer import SupervisedTrainer
        def load_npz_split(path):
            data = np.load(path)
            return data["states"].astype(np.float32), data["labels"].astype(np.int64)
        train_states, train_labels = load_npz_split(train_path)
        val_path = os.path.join(data_dir, "val.npz")
        val_states, val_labels = load_npz_split(val_path)
        actual_dim = train_states.shape[1]
        model = PolicyNetwork(input_dim=actual_dim)
        device = "cpu"
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        trainer = SupervisedTrainer(
            model=model, device=device, learning_rate=lr,
            batch_size=batch_size, epochs=epochs, patience=patience,
            checkpoint_dir=ckpt_dir,
        )
        summary = trainer.train(train_states, train_labels, val_states, val_labels)
        with _training_lock:
            _training_state.current_epoch = summary.get("epochs_trained", epochs)
            _training_state.metrics = summary
        # Phase 3: Evaluate
        with _training_lock:
            _training_state.phase = "evaluating"
            _training_state.message = "Evaluating on test set..."
        test_path = os.path.join(data_dir, "test.npz")
        eval_results = None
        if os.path.exists(test_path):
            from ml.training.trainer import load_checkpoint, evaluate_model
            test_states, test_labels = load_npz_split(test_path)
            best_model, _ = load_checkpoint(summary["checkpoint_path"], device)
            eval_results = evaluate_model(best_model, test_states, test_labels, device)
            eval_path = os.path.join(ckpt_dir, "eval_results.json")
            with open(eval_path, "w") as f:
                json.dump(eval_results, f, indent=2)
        # Done
        with _training_lock:
            _training_state.phase = "done"
            _training_state.running = False
            _training_state.result = {
                "training": summary,
                "evaluation": eval_results,
                "checkpoint": summary.get("checkpoint_path", ""),
                "device": device,
            }
            _training_state.message = f"Training complete! Best val acc: {summary.get('best_val_acc', 0):.1%}"
        log_ml.info(f"Complete: {summary.get('best_val_acc', 0):.1%} val accuracy")
        # Auto-reload policy server
        if _policy_service and _policy_service._loaded:
            _policy_service.reload(summary.get("checkpoint_path"))
            log_ml.info("Policy server reloaded with new checkpoint")
        elif not _policy_service_init_attempted:
            _policy_service_init_attempted = False
    except Exception as e:
        import traceback
        with _training_lock:
            _training_state.phase = "error"
            _training_state.running = False
            _training_state.error = str(e)
            _training_state.message = f"Training failed: {e}"
        log_ml.error(f"ERROR: {e}")
        traceback.print_exc()


@router.post("/api/ml/train")
async def ml_start_training(request: FastAPIRequest):
    """Trigger ML training pipeline from the web UI."""
    if _training_state.running:
        raise HTTPException(409, "Training already in progress")
    body = await request.json() if await request.body() else {}
    epochs = body.get("epochs", 50)
    lr = body.get("lr", 0.001)
    batch_size = body.get("batchSize", 256)
    patience = body.get("patience", 10)
    rebuild = body.get("rebuildDataset", True)
    results_dir = os.path.join(str(Path(__file__).resolve().parent.parent), "results")
    with _training_lock:
        _training_state.running = True
        _training_state.progress = 0
        _training_state.total_epochs = epochs
        _training_state.current_epoch = 0
        _training_state.phase = "starting"
        _training_state.message = "Initializing training pipeline..."
        _training_state.metrics = None
        _training_state.result = None
        _training_state.error = None
    thread = threading.Thread(
        target=_run_training_pipeline,
        args=(results_dir, epochs, lr, batch_size, patience, rebuild),
        daemon=True,
    )
    thread.start()
    return {
        "status": "started",
        "config": {
            "epochs": epochs, "lr": lr, "batchSize": batch_size,
            "patience": patience, "rebuildDataset": rebuild,
        },
    }


@router.get("/api/ml/train")
async def ml_training_status_poll():
    """Return current training status (polled by Unity client)."""
    with _training_lock:
        return _training_state.snapshot()


@router.get("/api/ml/train/status")
async def ml_training_status():
    """Get current training pipeline status."""
    with _training_lock:
        return _training_state.snapshot()


@router.get("/api/ml/data/status")
async def ml_data_status():
    """Get status of available training data and model checkpoints."""
    project_root = Path(__file__).resolve().parent.parent
    results_dir = project_root / "results"
    data_dir = project_root / "ml" / "models"
    ckpt_dir = data_dir / "checkpoints"
    decision_files = []
    if results_dir.exists():
        for f in sorted(results_dir.glob("ml-decisions-*.jsonl")):
            line_count = 0
            try:
                with open(f, "r") as fh:
                    line_count = sum(1 for _ in fh)
            except Exception:
                pass
            decision_files.append({"name": f.name, "size": f.stat().st_size, "decisions": line_count})
    datasets = {}
    for split in ["train", "val", "test"]:
        path = data_dir / f"{split}.npz"
        if path.exists():
            try:
                import numpy as np
                data = np.load(str(path))
                datasets[split] = {
                    "samples": int(data["states"].shape[0]),
                    "features": int(data["states"].shape[1]),
                    "size": path.stat().st_size,
                }
            except Exception:
                datasets[split] = {"size": path.stat().st_size}
    checkpoints = []
    if ckpt_dir.exists():
        for f in sorted(ckpt_dir.glob("*.pt")):
            checkpoints.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    eval_path = ckpt_dir / "eval_results.json"
    eval_results = None
    if eval_path.exists():
        try:
            with open(eval_path, "r") as f:
                eval_results = json.load(f)
        except Exception:
            pass
    return {
        "decisionFiles": decision_files,
        "totalDecisions": sum(d["decisions"] for d in decision_files),
        "datasets": datasets,
        "checkpoints": checkpoints,
        "evalResults": eval_results,
        "policyLoaded": _policy_service is not None and _policy_service._loaded if _policy_service else False,
    }


# ==============================================================
# PPO Training + Tournament Endpoints
# ==============================================================

def _run_ppo_pipeline(
    iterations: int, episodes_per_iter: int, ppo_epochs: int,
    batch_size: int, lr: float, clip_epsilon: float,
    entropy_coeff: float, opponent: str, playstyle: str,
    load_supervised: str,
):
    """Run PPO training in a background thread."""
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        with _ppo_lock:
            _ppo_state.running = True
            _ppo_state.error = None
            _ppo_state.result = None
        from ml.training.ppo_trainer import PPOTrainer, PPOConfig
        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        config = PPOConfig(
            iterations=iterations, episodes_per_iter=episodes_per_iter,
            ppo_epochs=ppo_epochs, batch_size=batch_size,
            learning_rate=lr, clip_epsilon=clip_epsilon,
            entropy_coeff=entropy_coeff, opponent=opponent,
            playstyle=playstyle, checkpoint_dir=ckpt_dir,
            load_supervised=load_supervised if load_supervised else None,
        )
        trainer = PPOTrainer(config)
        def progress_cb(iteration, metrics):
            with _ppo_lock:
                _ppo_state.iteration = iteration
                _ppo_state.phase = "training"
                _ppo_state.message = f"Iteration {iteration}/{iterations} | WR: {metrics.get('win_rate', 0):.0%}"
                _ppo_state.metrics = metrics
        summary = trainer.train(progress_callback=progress_cb)
        with _ppo_lock:
            _ppo_state.phase = "done"
            _ppo_state.running = False
            _ppo_state.result = summary
            _ppo_state.message = f"PPO complete! Best win rate: {summary.get('best_win_rate', 0):.0%}"
    except Exception as e:
        import traceback
        with _ppo_lock:
            _ppo_state.phase = "error"
            _ppo_state.running = False
            _ppo_state.error = str(e)
            _ppo_state.message = f"PPO failed: {e}"
        traceback.print_exc()


@router.post("/api/ml/train/ppo")
async def ml_start_ppo(request: FastAPIRequest):
    """Start PPO training pipeline."""
    if _ppo_state.running:
        raise HTTPException(409, "PPO training already in progress")
    if _training_state.running:
        raise HTTPException(409, "Supervised training in progress -- wait for it to finish")
    body = await request.json() if await request.body() else {}
    iterations = body.get("iterations", 100)
    episodes = body.get("episodesPerIter", 64)
    ppo_epochs = body.get("ppoEpochs", 4)
    batch_size = body.get("batchSize", 256)
    lr = body.get("lr", 3e-4)
    clip_eps = body.get("clipEpsilon", 0.2)
    entropy = body.get("entropyCoeff", 0.01)
    opponent = body.get("opponent", "heuristic")
    playstyle = body.get("playstyle", "midrange")
    load_sup = body.get("loadSupervised", "")
    with _ppo_lock:
        _ppo_state.running = True
        _ppo_state.iteration = 0
        _ppo_state.total_iterations = iterations
        _ppo_state.phase = "starting"
        _ppo_state.message = "Initializing PPO..."
        _ppo_state.metrics = None
        _ppo_state.result = None
        _ppo_state.error = None
    thread = threading.Thread(
        target=_run_ppo_pipeline,
        args=(iterations, episodes, ppo_epochs, batch_size, lr,
              clip_eps, entropy, opponent, playstyle, load_sup),
        daemon=True,
    )
    thread.start()
    return {"status": "started", "iterations": iterations}


@router.get("/api/ml/train/ppo/status")
async def ml_ppo_status():
    """Get PPO training status."""
    with _ppo_lock:
        return _ppo_state.snapshot()


def _run_tournament_pipeline(episodes: int, playstyle: str):
    """Run tournament in a background thread."""
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        with _tournament_lock:
            _tournament_state.running = True
            _tournament_state.error = None
            _tournament_state.result = None
            _tournament_state.phase = "running"
            _tournament_state.message = "Running tournament..."
        from ml.eval.tournament import (
            run_tournament, HeuristicPolicy, RandomPolicy, LearnedPolicy,
        )
        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        policies = {
            "heuristic": HeuristicPolicy(),
            "random": RandomPolicy(),
        }
        sup_path = os.path.join(ckpt_dir, "best_policy.pt")
        if os.path.exists(sup_path):
            policies["supervised"] = LearnedPolicy(sup_path)
        ppo_path = os.path.join(ckpt_dir, "best_ppo.pt")
        if os.path.exists(ppo_path):
            policies["ppo"] = LearnedPolicy(ppo_path)
        result = run_tournament(
            policies=policies,
            episodes_per_matchup=episodes,
            playstyle=playstyle,
        )
        output_path = os.path.join(ckpt_dir, "tournament_results.json")
        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        with _tournament_lock:
            _tournament_state.phase = "done"
            _tournament_state.running = False
            _tournament_state.result = result.to_dict()
            _tournament_state.message = f"Tournament complete! {result.total_matches} matches"
    except Exception as e:
        import traceback
        with _tournament_lock:
            _tournament_state.phase = "error"
            _tournament_state.running = False
            _tournament_state.error = str(e)
            _tournament_state.message = f"Tournament failed: {e}"
        traceback.print_exc()


@router.post("/api/ml/tournament")
async def ml_start_tournament(request: FastAPIRequest):
    """Start a tournament evaluation."""
    if _tournament_state.running:
        raise HTTPException(409, "Tournament already in progress")
    body = await request.json() if await request.body() else {}
    episodes = body.get("episodes", 50)
    playstyle = body.get("playstyle", "midrange")
    with _tournament_lock:
        _tournament_state.running = True
        _tournament_state.phase = "starting"
        _tournament_state.message = "Initializing tournament..."
        _tournament_state.result = None
        _tournament_state.error = None
    thread = threading.Thread(
        target=_run_tournament_pipeline,
        args=(episodes, playstyle),
        daemon=True,
    )
    thread.start()
    return {"status": "started", "episodes": episodes}


@router.get("/api/ml/tournament/status")
async def ml_tournament_status():
    """Get tournament status."""
    with _tournament_lock:
        return _tournament_state.snapshot()


@router.get("/api/ml/tournament/results")
async def ml_tournament_results():
    """Get latest tournament results."""
    project_root = Path(__file__).resolve().parent.parent
    results_path = project_root / "ml" / "models" / "checkpoints" / "tournament_results.json"
    if results_path.exists():
        with open(results_path, "r") as f:
            return json.load(f)
    return {"error": "No tournament results found. Run a tournament first."}


# ==============================================================
# Model listing and stats endpoints
# ==============================================================

@router.get("/api/ml/models")
async def ml_list_models():
    """List available policy model checkpoints."""
    project_root = Path(__file__).resolve().parent.parent
    ckpt_dir = project_root / "ml" / "models" / "checkpoints"
    checkpoints = []
    if ckpt_dir.exists():
        for f in sorted(ckpt_dir.glob("*.pt")):
            checkpoints.append({
                "name": f.name,
                "path": str(f),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    svc = _get_policy_service()
    return {
        "models": checkpoints,
        "count": len(checkpoints),
        "active_model": svc.get_status() if svc else None,
    }


@router.get("/api/ml/stats")
async def ml_stats():
    """Return aggregate ML training statistics and model performance metrics."""
    project_root = Path(__file__).resolve().parent.parent
    ckpt_dir = project_root / "ml" / "models" / "checkpoints"
    eval_results = None
    eval_path = ckpt_dir / "eval_results.json"
    if eval_path.exists():
        try:
            with open(eval_path, "r") as f:
                eval_results = json.load(f)
        except Exception:
            pass
    with _training_lock:
        training_snapshot = _training_state.snapshot()
    with _ppo_lock:
        ppo_snapshot = _ppo_state.snapshot()
    svc = _get_policy_service()
    return {
        "training": training_snapshot,
        "ppo": ppo_snapshot,
        "eval_results": eval_results,
        "policy_loaded": svc._loaded if svc else False,
    }


# ==============================================================
# Distillation Loop Endpoints
# ==============================================================

@dataclasses.dataclass
class _DistillationState:
    running: bool = False
    generation: int = 0
    max_iterations: int = 0
    phase: str = "idle"
    message: str = ""
    current_step: str = ""
    generations: list = dataclasses.field(default_factory=list)
    result: object = None
    error: object = None
    started_at: object = None

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "generation": self.generation,
            "max_iterations": self.max_iterations,
            "phase": self.phase,
            "message": self.message,
            "current_step": self.current_step,
            "generations": self.generations,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
        }

_distillation_state = _DistillationState()
_distillation_lock  = threading.Lock()
_distillation_loop  = None  # holds the DistillationLoop instance for stop()


def _run_distillation_pipeline(
    max_iterations: int,
    convergence_window: int,
    convergence_threshold: float,
    supervised_epochs: int,
    supervised_lr: float,
    ppo_iterations: int,
    ppo_episodes_per_iter: int,
    ppo_lr: float,
    opponent: str,
    playstyle: str,
    min_win_rate: float,
    forge_weight: float = 1.0,
    ppo_weight: float = 0.0,
):
    """Run the distillation loop in a background thread."""
    global _distillation_loop
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from ml.training.distillation_loop import DistillationLoop, DistillationConfig

        cfg = DistillationConfig(
            max_iterations=max_iterations,
            convergence_window=convergence_window,
            convergence_threshold=convergence_threshold,
            supervised_epochs=supervised_epochs,
            supervised_lr=supervised_lr,
            ppo_iterations=ppo_iterations,
            ppo_episodes_per_iter=ppo_episodes_per_iter,
            ppo_lr=ppo_lr,
            opponent=opponent,
            playstyle=playstyle,
            min_ppo_win_rate=min_win_rate,
            forge_weight=forge_weight,
            ppo_weight=ppo_weight,
            results_dir=os.path.join(project_root, "results"),
            models_dir=os.path.join(project_root, "ml", "models"),
            checkpoint_dir=os.path.join(project_root, "ml", "models", "checkpoints"),
            history_dir=os.path.join(project_root, "results", "distillation-history"),
        )

        loop = DistillationLoop(cfg)
        _distillation_loop = loop

        def progress_callback(gen_num, record):
            with _distillation_lock:
                _distillation_state.generation = gen_num
                _distillation_state.current_step = record.status
                _distillation_state.message = (
                    f"Generation {gen_num}: {record.status}"
                    + (f" — win rate {record.ppo_best_win_rate:.1%}" if record.ppo_best_win_rate > 0 else "")
                )
                _distillation_state.generations = [g.to_dict() for g in loop.generations]

        with _distillation_lock:
            _distillation_state.phase = "running"
            _distillation_state.message = "Initializing distillation loop..."

        summary = loop.run(progress_callback=progress_callback)

        with _distillation_lock:
            _distillation_state.phase = "done"
            _distillation_state.running = False
            _distillation_state.result = summary
            _distillation_state.generations = summary.get("generations", [])
            _distillation_state.message = (
                f"Distillation complete! {summary['generations_run']} generations, "
                f"best win rate: {summary['best_win_rate']:.1%}"
            )

    except Exception as e:
        import traceback
        with _distillation_lock:
            _distillation_state.phase = "error"
            _distillation_state.running = False
            _distillation_state.error = str(e)
            _distillation_state.message = f"Distillation failed: {e}"
        traceback.print_exc()
    finally:
        _distillation_loop = None


@router.get("/api/ml/distill/presets")
async def ml_distill_presets():
    """List available mixed-mode weight presets for distillation."""
    from ml.config.scope import MIXED_MODE_PRESETS
    return {"presets": MIXED_MODE_PRESETS}


@router.post("/api/ml/distill/start")
async def ml_start_distillation(request: FastAPIRequest):
    """Start the closed-loop distillation pipeline.

    Accepts an optional ``preset`` field (e.g. ``"forge_90_10"``)
    which overrides ``forgeWeight`` / ``ppoWeight`` with a named
    configuration from ``MIXED_MODE_PRESETS``.
    """
    if _distillation_state.running:
        raise HTTPException(409, "Distillation loop already in progress")
    if _training_state.running:
        raise HTTPException(409, "Supervised training in progress — wait for it to finish")
    if _ppo_state.running:
        raise HTTPException(409, "PPO training in progress — wait for it to finish")

    body = await request.json() if await request.body() else {}

    max_iterations = body.get("maxIterations", 10)
    convergence_window = body.get("convergenceWindow", 3)
    convergence_threshold = body.get("convergenceThreshold", 0.01)
    supervised_epochs = body.get("supervisedEpochs", 30)
    supervised_lr = body.get("supervisedLr", 1e-3)
    ppo_iterations = body.get("ppoIterations", 50)
    ppo_episodes_per_iter = body.get("ppoEpisodesPerIter", 64)
    ppo_lr = body.get("ppoLr", 3e-4)
    opponent = body.get("opponent", "heuristic")
    playstyle = body.get("playstyle", "midrange")
    min_win_rate = body.get("minWinRate", 0.30)

    # Resolve weights: preset > explicit params > defaults (Forge-only)
    forge_weight = 1.0
    ppo_weight = 0.0
    preset_name = body.get("preset")
    if preset_name:
        from ml.config.scope import get_preset_weights
        try:
            pw = get_preset_weights(preset_name)
            forge_weight = pw["forge_weight"]
            ppo_weight = pw["ppo_weight"]
        except KeyError as e:
            raise HTTPException(400, str(e))
    else:
        forge_weight = body.get("forgeWeight", 1.0)
        ppo_weight = body.get("ppoWeight", 0.0)

    with _distillation_lock:
        _distillation_state.running = True
        _distillation_state.generation = 0
        _distillation_state.max_iterations = max_iterations
        _distillation_state.phase = "starting"
        _distillation_state.message = "Initializing distillation loop..."
        _distillation_state.current_step = ""
        _distillation_state.generations = []
        _distillation_state.result = None
        _distillation_state.error = None
        _distillation_state.started_at = datetime.now().isoformat()

    thread = threading.Thread(
        target=_run_distillation_pipeline,
        args=(
            max_iterations, convergence_window, convergence_threshold,
            supervised_epochs, supervised_lr,
            ppo_iterations, ppo_episodes_per_iter, ppo_lr,
            opponent, playstyle, min_win_rate,
            forge_weight, ppo_weight,
        ),
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "max_iterations": max_iterations,
        "forge_weight": forge_weight,
        "ppo_weight": ppo_weight,
        "preset": preset_name,
    }


@router.get("/api/ml/distill/status")
async def ml_distillation_status():
    """Get distillation loop status."""
    with _distillation_lock:
        return _distillation_state.snapshot()


@router.post("/api/ml/distill/stop")
async def ml_stop_distillation():
    """Signal the distillation loop to stop after the current generation."""
    if not _distillation_state.running:
        raise HTTPException(400, "Distillation loop is not running")

    global _distillation_loop
    if _distillation_loop is not None:
        _distillation_loop.stop()

    with _distillation_lock:
        _distillation_state.message = "Stop signal sent — finishing current generation..."

    return {"status": "stopping", "message": "Will stop after current generation completes"}


@router.get("/api/ml/distill/history")
async def ml_distillation_history():
    """Get distillation generation history from disk."""
    project_root = Path(__file__).resolve().parent.parent
    history_path = project_root / "results" / "distillation-history" / "generations.json"
    summary_path = project_root / "results" / "distillation-history" / "summary.json"

    result = {"generations": [], "summary": None}

    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                result["generations"] = json.load(f)
        except Exception:
            pass

    if summary_path.exists():
        try:
            with open(summary_path, "r") as f:
                result["summary"] = json.load(f)
        except Exception:
            pass

    return result


# ==============================================================
# ELO Tournament Endpoints
# ==============================================================

@dataclasses.dataclass
class _EloTournamentState:
    running: bool = False
    phase: str = "idle"
    message: str = ""
    result: object = None
    error: object = None

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "phase": self.phase,
            "message": self.message,
            "result": self.result,
            "error": self.error,
        }

_elo_tournament_state = _EloTournamentState()
_elo_tournament_lock  = threading.Lock()


def _run_elo_tournament_pipeline(episodes: int, playstyle: str):
    """Run ELO tournament in a background thread."""
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        with _elo_tournament_lock:
            _elo_tournament_state.running = True
            _elo_tournament_state.phase = "running"
            _elo_tournament_state.message = "Running ELO tournament..."
            _elo_tournament_state.error = None
            _elo_tournament_state.result = None

        from ml.eval.elo_tracker import (
            run_generation_tournament, EloHistory,
        )

        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        result = run_generation_tournament(
            checkpoint_dir=ckpt_dir,
            episodes_per_matchup=episodes,
            playstyle=playstyle,
        )

        # Save to ELO history
        history_path = os.path.join(project_root, "data", "elo_history.json")
        history = EloHistory(path=history_path)
        gen_models = [k for k in result.ratings if k.startswith("gen-")]
        gen_num = 0
        if gen_models:
            try:
                gen_num = max(int(g.split("-")[1]) for g in gen_models)
            except (ValueError, IndexError):
                pass
        history.append(gen_num, result.ratings)

        with _elo_tournament_lock:
            _elo_tournament_state.phase = "done"
            _elo_tournament_state.running = False
            _elo_tournament_state.result = result.to_dict()
            _elo_tournament_state.message = (
                f"ELO tournament complete! {result.match_count} matches in {result.total_time_s:.1f}s"
            )

    except Exception as e:
        import traceback
        with _elo_tournament_lock:
            _elo_tournament_state.phase = "error"
            _elo_tournament_state.running = False
            _elo_tournament_state.error = str(e)
            _elo_tournament_state.message = f"ELO tournament failed: {e}"
        traceback.print_exc()


@router.post("/api/ml/elo/tournament")
async def ml_start_elo_tournament(request: FastAPIRequest):
    """Start an ELO-rated tournament across all generation checkpoints."""
    if _elo_tournament_state.running:
        raise HTTPException(409, "ELO tournament already in progress")

    body = await request.json() if await request.body() else {}
    episodes = body.get("episodes", 50)
    playstyle = body.get("playstyle", "midrange")

    with _elo_tournament_lock:
        _elo_tournament_state.running = True
        _elo_tournament_state.phase = "starting"
        _elo_tournament_state.message = "Initializing ELO tournament..."
        _elo_tournament_state.result = None
        _elo_tournament_state.error = None

    thread = threading.Thread(
        target=_run_elo_tournament_pipeline,
        args=(episodes, playstyle),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "episodes": episodes}


@router.get("/api/ml/elo/tournament/status")
async def ml_elo_tournament_status():
    """Get ELO tournament status."""
    with _elo_tournament_lock:
        return _elo_tournament_state.snapshot()


@router.get("/api/ml/elo/history")
async def ml_elo_history():
    """Get ELO rating history."""
    project_root = Path(__file__).resolve().parent.parent
    history_path = project_root / "data" / "elo_history.json"
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"entries": []}
