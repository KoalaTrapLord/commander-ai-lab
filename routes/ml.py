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

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest

from routes.shared import CFG, _ml_logging_enabled

log_ml = logging.getLogger("commander_ai_lab.ml")

router = APIRouter(tags=["ml"])

# ---- module-level state (moved from lab_api.py) ----

_policy_service = None
_policy_service_init_attempted = False

_training_state = {
    "running": False,
    "progress": 0,
    "total_epochs": 0,
    "current_epoch": 0,
    "phase": "idle",
    "message": "",
    "metrics": None,
    "result": None,
    "error": None,
    "started_at": None,
}

_ppo_state = {
    "running": False,
    "iteration": 0,
    "total_iterations": 0,
    "phase": "idle",
    "message": "",
    "metrics": None,
    "result": None,
    "error": None,
}

_tournament_state = {
    "running": False,
    "phase": "idle",
    "message": "",
    "result": None,
    "error": None,
}

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
    import routes.shared as _shared
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
        "ml_logging_enabled": _shared._ml_logging_enabled,
        "training_files": ml_files,
        "total_decisions": total_decisions,
        "total_files": len(ml_files),
    }


@router.post("/api/ml/toggle")
async def ml_toggle(enable: bool = True):
    """Enable or disable ML decision logging for future batch runs."""
    import routes.shared as _shared
    _shared._ml_logging_enabled = enable
    return {
        "ml_logging_enabled": _shared._ml_logging_enabled,
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
# ML Policy Inference Endpoints
# ==============================================================

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
    global _training_state, _policy_service, _policy_service_init_attempted
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        _training_state["running"] = True
        _training_state["started_at"] = datetime.now().isoformat()
        _training_state["error"] = None
        _training_state["result"] = None
        data_dir = os.path.join(project_root, "ml", "models")
        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)
        # Phase 1: Build Dataset
        train_path = os.path.join(data_dir, "train.npz")
        if rebuild_dataset or not os.path.exists(train_path):
            _training_state["phase"] = "building"
            _training_state["message"] = "Loading card embeddings & building dataset..."
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
            _training_state["message"] = f"Dataset built: {total_samples} samples"
            log_ml.info(f"Dataset built: {total_samples} samples")
        # Phase 2: Train
        _training_state["phase"] = "training"
        _training_state["total_epochs"] = epochs
        _training_state["current_epoch"] = 0
        _training_state["message"] = f"Training policy network ({epochs} epochs)..."
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
        _training_state["current_epoch"] = summary.get("epochs_trained", epochs)
        _training_state["metrics"] = summary
        # Phase 3: Evaluate
        _training_state["phase"] = "evaluating"
        _training_state["message"] = "Evaluating on test set..."
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
        _training_state["phase"] = "done"
        _training_state["running"] = False
        _training_state["result"] = {
            "training": summary,
            "evaluation": eval_results,
            "checkpoint": summary.get("checkpoint_path", ""),
            "device": device,
        }
        _training_state["message"] = f"Training complete! Best val acc: {summary.get('best_val_accuracy', 0):.1%}"
        log_ml.info(f"Complete: {summary.get('best_val_accuracy', 0):.1%} val accuracy")
        # Auto-reload policy server
        if _policy_service and _policy_service._loaded:
            _policy_service.reload(summary.get("checkpoint_path"))
            log_ml.info("Policy server reloaded with new checkpoint")
        elif not _policy_service_init_attempted:
            _policy_service_init_attempted = False
    except Exception as e:
        import traceback
        _training_state["phase"] = "error"
        _training_state["running"] = False
        _training_state["error"] = str(e)
        _training_state["message"] = f"Training failed: {e}"
        log_ml.error(f"ERROR: {e}")
        traceback.print_exc()


@router.post("/api/ml/train")
async def ml_start_training(request: FastAPIRequest):
    """Trigger ML training pipeline from the web UI."""
    if _training_state["running"]:
        raise HTTPException(409, "Training already in progress")
    body = await request.json() if await request.body() else {}
    epochs = body.get("epochs", 50)
    lr = body.get("lr", 0.001)
    batch_size = body.get("batchSize", 256)
    patience = body.get("patience", 10)
    rebuild = body.get("rebuildDataset", True)
    results_dir = os.path.join(str(Path(__file__).resolve().parent.parent), "results")
    _training_state.update({
        "running": True, "progress": 0, "total_epochs": epochs,
        "current_epoch": 0, "phase": "starting",
        "message": "Initializing training pipeline...",
        "metrics": None, "result": None, "error": None,
    })
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


@router.get("/api/ml/train/status")
async def ml_training_status():
    """Get current training pipeline status."""
    return dict(_training_state)


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
    global _ppo_state
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        _ppo_state["running"] = True
        _ppo_state["error"] = None
        _ppo_state["result"] = None
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
            _ppo_state["iteration"] = iteration
            _ppo_state["phase"] = "training"
            _ppo_state["message"] = f"Iteration {iteration}/{iterations} | WR: {metrics.get('win_rate', 0):.0%}"
            _ppo_state["metrics"] = metrics
        summary = trainer.train(progress_callback=progress_cb)
        _ppo_state["phase"] = "done"
        _ppo_state["running"] = False
        _ppo_state["result"] = summary
        _ppo_state["message"] = f"PPO complete! Best win rate: {summary.get('best_win_rate', 0):.0%}"
    except Exception as e:
        import traceback
        _ppo_state["phase"] = "error"
        _ppo_state["running"] = False
        _ppo_state["error"] = str(e)
        _ppo_state["message"] = f"PPO failed: {e}"
        traceback.print_exc()


@router.post("/api/ml/train/ppo")
async def ml_start_ppo(request: FastAPIRequest):
    """Start PPO training pipeline."""
    if _ppo_state["running"]:
        raise HTTPException(409, "PPO training already in progress")
    if _training_state["running"]:
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
    _ppo_state.update({
        "running": True, "iteration": 0, "total_iterations": iterations,
        "phase": "starting", "message": "Initializing PPO...",
        "metrics": None, "result": None, "error": None,
    })
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
    return dict(_ppo_state)


def _run_tournament_pipeline(episodes: int, playstyle: str):
    """Run tournament in a background thread."""
    global _tournament_state
    try:
        import sys
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        _tournament_state["running"] = True
        _tournament_state["error"] = None
        _tournament_state["result"] = None
        _tournament_state["phase"] = "running"
        _tournament_state["message"] = "Running tournament..."
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
        _tournament_state["phase"] = "done"
        _tournament_state["running"] = False
        _tournament_state["result"] = result.to_dict()
        _tournament_state["message"] = f"Tournament complete! {result.total_matches} matches"
    except Exception as e:
        import traceback
        _tournament_state["phase"] = "error"
        _tournament_state["running"] = False
        _tournament_state["error"] = str(e)
        _tournament_state["message"] = f"Tournament failed: {e}"
        traceback.print_exc()


@router.post("/api/ml/tournament")
async def ml_start_tournament(request: FastAPIRequest):
    """Start a tournament evaluation."""
    if _tournament_state["running"]:
        raise HTTPException(409, "Tournament already in progress")
    body = await request.json() if await request.body() else {}
    episodes = body.get("episodes", 50)
    playstyle = body.get("playstyle", "midrange")
    _tournament_state.update({
        "running": True, "phase": "starting",
        "message": "Initializing tournament...",
        "result": None, "error": None,
    })
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
    return dict(_tournament_state)


@router.get("/api/ml/tournament/results")
async def ml_tournament_results():
    """Get latest tournament results."""
    project_root = Path(__file__).resolve().parent.parent
    results_path = project_root / "ml" / "models" / "checkpoints" / "tournament_results.json"
    if results_path.exists():
        with open(results_path, "r") as f:
            return json.load(f)
    return {"error": "No tournament results found. Run a tournament first."}
