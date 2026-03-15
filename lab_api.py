#!/usr/bin/env python3
"""
Commander AI Lab — FastAPI Backend v3
═════════════════════════════════════

v3 adds:
  POST /api/lab/import/url       — Import deck from Archidekt/EDHREC URL
  POST /api/lab/import/text      — Import deck from card list text
  GET  /api/lab/meta/commanders  — List available commanders in meta mapping
  GET  /api/lab/meta/search      — Search commanders by name
  POST /api/lab/meta/fetch       — Fetch EDHREC average deck for a commander
  POST /api/lab/start            — Extended: accepts imported deck profiles

Runs on port 8080 by default. Serves the web UI static files at /.
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Request as FastAPIRequest
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    print("ERROR: FastAPI not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
# Shared Module — configuration, models, helpers
# ══════════════════════════════════════════════════════════════

from routes.shared import (
    # Configuration
    Config, CFG, setup_logging,
    # Loggers
    # (we re-create named loggers locally below for convenience)
    # In-memory state
    BatchState, COMMANDER_META,
    # Pydantic models
    StartRequest, StartResponse, StatusResponse, DeckInfo,
    ImportUrlRequest, ImportTextRequest, MetaFetchRequest,
    CreateDeckRequest, UpdateDeckRequest, AddDeckCardRequest,
    PatchDeckCardRequest, BulkAddRequest, BulkAddRecommendedRequest,
    DeckGenerationSourceConfig, DeckGenerationRequest, GeneratedDeckCard,
    DeckGenV3Request, DeckGenV3SubstituteRequest,
    # Database
    _get_db_conn, init_collection_db,
    COLLECTION_DB_PATH,
    # Collection helpers
    _row_to_dict, _snake_to_camel, _add_image_url,
    _build_collection_filters,
    _detect_card_roles, _classify_card_type,
    VALID_SORT_FIELDS,
    # Deck helpers
    _get_deck_or_404, _compute_deck_analysis, _check_ratio_limit,
    # Scryfall
    _ScryfallCache, _scryfall_cache, _scryfall_rate_limit,
    _fetch_scryfall_api, _enrich_from_scryfall, _scryfall_fuzzy_lookup,
    SCRYFALL_CACHE_DB_PATH, SCRYFALL_CACHE_TTL_SECONDS,
    _API_HEADERS,
    # Import/fetch helpers
    _http_get, _import_from_url, _fetch_archidekt_deck,
    _fetch_edhrec_average, _parse_text_decklist,
    _save_profile_to_dck, _to_edhrec_slug,
    _parse_finish, _parse_text_line, _auto_infer_mapping, _parse_csv_content,
    # Precon helpers
    load_precon_index, _sanitize_filename, _deck_to_dck,
    download_precon_database,
    PRECON_DIR, PRECON_INDEX, GITHUB_PRECON_URL, PRECON_CACHE_HOURS,
    # Java/batch
    _find_java17, get_java17, build_java_command,
    parse_dck_file, _load_deck_cards_by_name,
    run_batch_subprocess, _run_process_blocking,
    _run_deepseek_batch_thread,
    _get_deepseek_brain,
    # AI profiles & ML
    AI_PROFILES, _ml_logging_enabled,
    # EDHREC cache
    _edhrec_cache, _EDHREC_CACHE_TTL,
    _edhrec_cache_get, _edhrec_cache_set,
    # Commander meta
    load_commander_meta, BUILTIN_COMMANDERS,
)

# Route modules
from routes.collection import router as collection_router
from routes.deckbuilder import router as deckbuilder_router
from routes.precon import router as precon_router
from routes.import_routes import router as import_router
from routes.lab import router as lab_router
from routes.scanner import router as scanner_router
from routes.deepseek import router as deepseek_router
from routes.deckgen import router as deckgen_router
from routes.coach import router as coach_router, init_coach_service


# ══════════════════════════════════════════════════════════════
# Logging Setup
# ══════════════════════════════════════════════════════════════

_LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR = Path(os.environ.get("CAL_LOG_DIR", "logs"))

# Named loggers — convenience aliases for remaining endpoints
log = logging.getLogger("commander_ai_lab.api")
log_batch = logging.getLogger("commander_ai_lab.batch")
log_sim = logging.getLogger("commander_ai_lab.sim")
log_coach = logging.getLogger("commander_ai_lab.coach")
log_deckgen = logging.getLogger("commander_ai_lab.deckgen")
log_collect = logging.getLogger("commander_ai_lab.collection")
log_scan = logging.getLogger("commander_ai_lab.scanner")
log_ml = logging.getLogger("commander_ai_lab.ml")
log_cache = logging.getLogger("commander_ai_lab.cache")
log_pplx = logging.getLogger("commander_ai_lab.pplx")


# ══════════════════════════════════════════════════════════════
# App Setup
# ══════════════════════════════════════════════════════════════

app = FastAPI(title="Commander AI Lab API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register extracted route modules
app.include_router(collection_router)
app.include_router(deckbuilder_router)
app.include_router(precon_router)
app.include_router(import_router)
app.include_router(lab_router)
app.include_router(scanner_router)
app.include_router(deepseek_router)
app.include_router(deckgen_router)
app.include_router(coach_router)


@app.on_event("startup")
async def _on_startup():
    """Safety net: ensure DB and precon index are initialized even when
    main() is bypassed (e.g. uvicorn lab_api:app --reload)."""
    import routes.shared as _shared
    _shared.init_collection_db()
    if not _shared.PRECON_INDEX:
        _shared.download_precon_database()
    if not _shared.COMMANDER_META:
        _shared.load_commander_meta()


# ══════════════════════════════════════════════════════════════
# In-Memory State (used by remaining endpoints)
# ══════════════════════════════════════════════════════════════

active_batches: dict[str, BatchState] = {}

# ══════════════════════════════════════════════════════════════
# ML Training Data Endpoints
# ══════════════════════════════════════════════════════════════

@app.get("/api/ml/status")
async def ml_status():
    """Get ML decision logging status and available training data."""
    global _ml_logging_enabled
    lab_root = Path(__file__).parent
    results_dir = lab_root / CFG.results_dir

    # Find existing ML decision files
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
        "ml_logging_enabled": _ml_logging_enabled,
        "training_files": ml_files,
        "total_decisions": total_decisions,
        "total_files": len(ml_files),
    }


@app.post("/api/ml/toggle")
async def ml_toggle(enable: bool = True):
    """Enable or disable ML decision logging for future batch runs."""
    global _ml_logging_enabled
    _ml_logging_enabled = enable
    return {
        "ml_logging_enabled": _ml_logging_enabled,
        "message": f"ML decision logging {'enabled' if enable else 'disabled'} for future batches",
    }


@app.get("/api/ml/decisions/{filename}")
async def ml_get_decisions(filename: str, limit: int = 100, offset: int = 0):
    """Read decision snapshots from a training data file."""
    lab_root = Path(__file__).parent
    filepath = lab_root / CFG.results_dir / filename

    if not filepath.exists() or not filename.startswith("ml-decisions-"):
        raise HTTPException(404, f"ML decisions file not found: {filename}")

    decisions = []
    try:
        import json as _json
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(decisions) >= limit:
                    break
                try:
                    decisions.append(_json.loads(line.strip()))
                except _json.JSONDecodeError:
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


# ══════════════════════════════════════════════════════════════
# ML Policy Inference Endpoints
# ══════════════════════════════════════════════════════════════

# Lazy-loaded policy inference service (only loads when first called)
_policy_service = None
_policy_service_init_attempted = False


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


@app.post("/api/ml/predict")
async def ml_predict(request: FastAPIRequest):
    """Predict a macro-action from a game state snapshot.

    Accepts DecisionSnapshot-shaped JSON from the Java batch runner.
    Returns the learned policy's recommended action.

    Request body:
        {
            "turn": 5,
            "phase": "main_1",
            "active_seat": 0,
            "players": [...],
            "archetype": "aggro",
            "temperature": 1.0,
            "greedy": false
        }

    Response:
        {
            "action": "cast_creature",
            "action_index": 0,
            "confidence": 0.73,
            "probabilities": {...},
            "inference_ms": 2.3
        }
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

    result = svc.predict(
        decision_snapshot=body,
        playstyle=playstyle,
        temperature=temperature,
        greedy=greedy,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/api/ml/predict/batch")
async def ml_predict_batch(request: FastAPIRequest):
    """Predict actions for multiple snapshots at once.

    Request body: {"snapshots": [...], "greedy": true}
    """
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


@app.get("/api/ml/model")
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


@app.post("/api/ml/reload")
async def ml_reload_model(checkpoint: str = None):
    """Hot-reload a policy model checkpoint."""
    svc = _get_policy_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Policy service not available")

    # If service hasn't loaded yet, try full load
    if not svc._loaded:
        ok = svc.load()
    else:
        ok = svc.reload(checkpoint)

    return {
        "success": ok,
        "status": svc.get_status(),
    }


# ══════════════════════════════════════════════════════════════
# ML Training Management Endpoints
# ══════════════════════════════════════════════════════════════

# Training state tracking
_training_state = {
    "running": False,
    "progress": 0,
    "total_epochs": 0,
    "current_epoch": 0,
    "phase": "idle",  # idle | building | training | evaluating | done | error
    "message": "",
    "metrics": None,  # latest epoch metrics
    "result": None,   # final training result
    "error": None,
    "started_at": None,
}


def _run_training_pipeline(
    results_dir: str,
    epochs: int,
    lr: float,
    batch_size: int,
    patience: int,
    rebuild_dataset: bool,
):
    """Run the full ML training pipeline in a background thread."""
    global _training_state
    try:
        import sys
        project_root = str(Path(__file__).parent)
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

        # --- Phase 1: Build Dataset ---
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

        # --- Phase 2: Train ---
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
            model=model,
            device=device,
            learning_rate=lr,
            batch_size=batch_size,
            epochs=epochs,
            patience=patience,
            checkpoint_dir=ckpt_dir,
        )

        # Hook into trainer to report progress
        original_train = trainer.train

        def patched_train(train_s, train_l, val_s, val_l):
            # We'll monitor the checkpoint dir for progress
            return original_train(train_s, train_l, val_s, val_l)

        summary = trainer.train(train_states, train_labels, val_states, val_labels)

        _training_state["current_epoch"] = summary.get("epochs_trained", epochs)
        _training_state["metrics"] = summary

        # --- Phase 3: Evaluate ---
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

        # --- Done ---
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

        # Auto-reload policy server with new checkpoint
        global _policy_service, _policy_service_init_attempted
        if _policy_service and _policy_service._loaded:
            _policy_service.reload(summary.get("checkpoint_path"))
            log_ml.info("Policy server reloaded with new checkpoint")
        elif not _policy_service_init_attempted:
            _policy_service_init_attempted = False  # Allow re-init with new model

    except Exception as e:
        import traceback
        _training_state["phase"] = "error"
        _training_state["running"] = False
        _training_state["error"] = str(e)
        _training_state["message"] = f"Training failed: {e}"
        log_ml.error(f"ERROR: {e}")
        traceback.print_exc()


@app.post("/api/ml/train")
async def ml_start_training(request: FastAPIRequest):
    """Trigger ML training pipeline from the web UI.

    Request body (all optional):
        {
            "epochs": 50,
            "lr": 0.001,
            "batchSize": 256,
            "patience": 10,
            "rebuildDataset": true
        }
    """
    if _training_state["running"]:
        raise HTTPException(409, "Training already in progress")

    body = await request.json() if await request.body() else {}
    epochs = body.get("epochs", 50)
    lr = body.get("lr", 0.001)
    batch_size = body.get("batchSize", 256)
    patience = body.get("patience", 10)
    rebuild = body.get("rebuildDataset", True)

    results_dir = os.path.join(str(Path(__file__).parent), "results")

    # Reset state
    _training_state.update({
        "running": True,
        "progress": 0,
        "total_epochs": epochs,
        "current_epoch": 0,
        "phase": "starting",
        "message": "Initializing training pipeline...",
        "metrics": None,
        "result": None,
        "error": None,
    })

    # Run in background thread
    thread = threading.Thread(
        target=_run_training_pipeline,
        args=(results_dir, epochs, lr, batch_size, patience, rebuild),
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "config": {
            "epochs": epochs,
            "lr": lr,
            "batchSize": batch_size,
            "patience": patience,
            "rebuildDataset": rebuild,
        },
    }


@app.get("/api/ml/train/status")
async def ml_training_status():
    """Get current training pipeline status."""
    return dict(_training_state)


@app.get("/api/ml/data/status")
async def ml_data_status():
    """Get status of available training data and model checkpoints."""
    project_root = Path(__file__).parent
    results_dir = project_root / "results"
    data_dir = project_root / "ml" / "models"
    ckpt_dir = data_dir / "checkpoints"

    # Decision log files
    decision_files = []
    if results_dir.exists():
        for f in sorted(results_dir.glob("ml-decisions-*.jsonl")):
            line_count = 0
            try:
                with open(f, "r") as fh:
                    line_count = sum(1 for _ in fh)
            except Exception:
                pass
            decision_files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "decisions": line_count,
            })

    # Dataset files
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

    # Checkpoints
    checkpoints = []
    if ckpt_dir.exists():
        for f in sorted(ckpt_dir.glob("*.pt")):
            checkpoints.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    # Eval results
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


# ══════════════════════════════════════════════════════════════
# PPO Training + Tournament Endpoints
# ══════════════════════════════════════════════════════════════

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


def _run_ppo_pipeline(
    iterations: int, episodes_per_iter: int, ppo_epochs: int, batch_size: int,
    lr: float, clip_epsilon: float, entropy_coeff: float,
    opponent: str, playstyle: str, load_supervised: str,
):
    """Run PPO training in a background thread."""
    global _ppo_state
    try:
        import sys
        project_root = str(Path(__file__).parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        _ppo_state["running"] = True
        _ppo_state["error"] = None
        _ppo_state["result"] = None

        from ml.training.ppo_trainer import PPOTrainer, PPOConfig

        ckpt_dir = os.path.join(project_root, "ml", "models", "checkpoints")
        config = PPOConfig(
            iterations=iterations,
            episodes_per_iter=episodes_per_iter,
            ppo_epochs=ppo_epochs,
            batch_size=batch_size,
            learning_rate=lr,
            clip_epsilon=clip_epsilon,
            entropy_coeff=entropy_coeff,
            opponent=opponent,
            playstyle=playstyle,
            checkpoint_dir=ckpt_dir,
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


@app.post("/api/ml/train/ppo")
async def ml_start_ppo(request: FastAPIRequest):
    """Start PPO training pipeline."""
    if _ppo_state["running"]:
        raise HTTPException(409, "PPO training already in progress")
    if _training_state["running"]:
        raise HTTPException(409, "Supervised training in progress — wait for it to finish")

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
        args=(iterations, episodes, ppo_epochs, batch_size, lr, clip_eps, entropy, opponent, playstyle, load_sup),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "iterations": iterations}


@app.get("/api/ml/train/ppo/status")
async def ml_ppo_status():
    """Get PPO training status."""
    return dict(_ppo_state)


def _run_tournament_pipeline(episodes: int, playstyle: str):
    """Run tournament in a background thread."""
    global _tournament_state
    try:
        import sys
        project_root = str(Path(__file__).parent)
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

        # Save results
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


@app.post("/api/ml/tournament")
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


@app.get("/api/ml/tournament/status")
async def ml_tournament_status():
    """Get tournament status."""
    return dict(_tournament_state)


@app.get("/api/ml/tournament/results")
async def ml_tournament_results():
    """Get latest tournament results."""
    project_root = Path(__file__).parent
    results_path = project_root / "ml" / "models" / "checkpoints" / "tournament_results.json"
    if results_path.exists():
        with open(results_path, "r") as f:
            return json.load(f)
    return {"error": "No tournament results found. Run a tournament first."}


# ══════════════════════════════════════════════════════════════
# Static File Serving (React SPA) — MUST be after all API routes
# ══════════════════════════════════════════════════════════════

# UI Serving: legacy HTML/JS/CSS pages (primary) or React SPA (fallback)
_legacy_ui_dir = Path(__file__).parent / "ui"
_spa_dir = Path(__file__).parent / "frontend" / "commander-ai-lab-ui" / "dist"

if _legacy_ui_dir.exists():
    # Primary: serve the proven multi-page HTML/JS/CSS UI
    app.mount("/", StaticFiles(directory=str(_legacy_ui_dir), html=True), name="ui")

elif _spa_dir.exists():
    # Fallback: React SPA (only if legacy ui/ folder is missing)
    _spa_assets = _spa_dir / "assets"
    if _spa_assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_spa_assets)), name="spa-assets")

    @app.get("/{full_path:path}")
    async def _spa_catchall(full_path: str):
        from fastapi.responses import FileResponse
        requested_file = _spa_dir / full_path
        if full_path and requested_file.exists() and requested_file.is_file():
            return FileResponse(str(requested_file))
        return FileResponse(str(_spa_dir / "index.html"))


# ══════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description="Commander AI Lab API Server v3")
    parser.add_argument("--forge-jar", default=os.environ.get("FORGE_JAR", ""),
                        help="Path to forge-gui-desktop jar-with-dependencies")
    parser.add_argument("--forge-dir", default=os.environ.get("FORGE_DIR", ""),
                        help="Forge working directory (contains res/)")
    parser.add_argument("--forge-decks-dir", default=os.environ.get("FORGE_DECKS_DIR", ""),
                        help="Path to Commander deck files (default: %%APPDATA%%/Forge/decks/commander)")
    parser.add_argument("--lab-jar", default=os.environ.get("LAB_JAR", ""),
                        help="Path to commander-ai-lab.jar (default: auto-detect from target/)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAB_PORT", "8080")))
    parser.add_argument("--ximilar-key", default=os.environ.get("XIMILAR_API_KEY", "REDACTED_XIMILAR_KEY"),
                        help="Ximilar API key for card scanner (visual AI recognition)")
    parser.add_argument("--pplx-key", default=os.environ.get("PPLX_API_KEY", "REDACTED_PPLX_KEY"),
                        help="Perplexity API key for AI deck research/generation (env: PPLX_API_KEY)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable DEBUG-level logging (default: INFO)")
    return parser.parse_args()


def resolve_lab_jar() -> str:
    target_dir = Path(__file__).parent / "target"
    if target_dir.exists():
        for pattern in [
            "commander-ai-lab-*-jar-with-dependencies.jar",
            "commander-ai-lab-*-shaded.jar",
            "commander-ai-lab-*.jar",
        ]:
            jars = sorted(target_dir.glob(pattern))
            jars = [j for j in jars if not j.name.startswith("original-")]
            if jars:
                return str(jars[0])
    return ""


def resolve_forge_decks_dir() -> str:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = os.path.join(appdata, "Forge", "decks", "commander")
            if os.path.isdir(candidate):
                return candidate
    home = Path.home()
    for candidate in [
        home / ".forge" / "decks" / "commander",
        home / "Forge" / "decks" / "commander",
    ]:
        if candidate.is_dir():
            return str(candidate)
    return ""


# load_commander_meta() is now in routes/shared.py


def main():
    args = parse_args()
    setup_logging(logging.DEBUG if getattr(args, 'verbose', False) else logging.INFO)

    CFG.forge_jar = args.forge_jar
    CFG.forge_dir = args.forge_dir
    CFG.forge_decks_dir = args.forge_decks_dir or resolve_forge_decks_dir()
    CFG.lab_jar = args.lab_jar or resolve_lab_jar()
    CFG.port = args.port
    CFG.ximilar_api_key = args.ximilar_key
    CFG.pplx_api_key = args.pplx_key

    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║      Commander AI Lab — API Server  v3.0.0      ║")
    log.info("╚══════════════════════════════════════════════════╝")
    log.info("")
    log.info(f"  Forge JAR:    {CFG.forge_jar}")
    log.info(f"  Forge Dir:    {CFG.forge_dir}")
    log.info(f"  Decks Dir:    {CFG.forge_decks_dir}")
    log.info(f"  Lab JAR:      {CFG.lab_jar}")
    log.info(f"  Results Dir:  {CFG.results_dir}")
    log.info(f"  Port:         {CFG.port}")
    log.info(f"  Ximilar:      {'configured' if CFG.ximilar_api_key else 'NOT SET (scanner will fail)'}")
    log.info(f"  Perplexity:   {'configured' if CFG.pplx_api_key else 'NOT SET (AI research/gen disabled)'}")
    j17 = get_java17()
    log.info(f"  Java 17:      {j17 if j17 != 'java' else 'NOT FOUND (batch sim may fail on Java 25+)'}")
    log.info(f"  LM Studio:    http://192.168.0.122:1234")

    load_commander_meta()
    download_precon_database()  # Auto-downloads all 163+ Commander precons on first run
    init_collection_db()
    init_coach_service()

    # Ximilar API key check
    if not CFG.ximilar_api_key:
        log_scan.warning("  WARNING: --ximilar-key not set. Card scanner will not work.")
        log.info("           Set via CLI: --ximilar-key YOUR_KEY")
        log.info("           Or env var:  XIMILAR_API_KEY=YOUR_KEY")

    if not CFG.forge_jar:
        log.warning("WARNING: --forge-jar not set. /api/lab/start will fail.")
    if not CFG.lab_jar:
        log.warning("WARNING: Lab JAR not found. Build with: mvn package -DskipTests")
    if not CFG.forge_decks_dir:
        log.warning("WARNING: Commander decks dir not found. /api/lab/decks will return empty.")

    log.info("")
    log.info(f"  Starting server on http://localhost:{CFG.port}")
    if _spa_dir.exists():
        log.info(f"  Web UI:       http://localhost:{CFG.port}/  (React SPA)")
        log.info(f"  Routes:       / (Batch Sim), /collection, /decks, /autogen, /simulator, /coach, /training")
    else:
        log.info(f"  Web UI:       http://localhost:{CFG.port}/index.html  (legacy HTML)")
        log.info(f"  NOTE: React SPA not built. Run: cd frontend/commander-ai-lab-ui && npm install && npm run build")
    log.info(f"  API docs:     http://localhost:{CFG.port}/docs")
    log.info("")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=CFG.port, log_level="info")


if __name__ == "__main__":
    main()
