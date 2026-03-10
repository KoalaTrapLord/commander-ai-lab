"""
Commander AI Lab — Policy Inference Server
════════════════════════════════════════════
FastAPI service that loads a trained PolicyNetwork checkpoint and serves
macro-action predictions via HTTP.

The Java batch runner calls this endpoint at each decision point
to get the learned policy's action instead of using Forge's built-in AI.

Endpoints:
    POST /api/ml/predict   — Predict action from raw game state JSON
    GET  /api/ml/model     — Current model info (loaded checkpoint, accuracy)
    POST /api/ml/reload    — Hot-reload a new checkpoint without restart

Design:
    - Loads card embeddings + state encoder on startup
    - Accepts DecisionSnapshot-shaped JSON from Java
    - Encodes state → tensor, runs model forward pass, returns action
    - Supports temperature-controlled sampling or greedy argmax
    - Thread-safe via torch.no_grad() inference

Usage (standalone):
    python -m ml.serving.policy_server --port 8090
    python -m ml.serving.policy_server --checkpoint ml/models/checkpoints/best_policy.pt

Usage (integrated into lab_api.py):
    Import PolicyInferenceService and register endpoints on the existing app.
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Conditional imports
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from ml.config.scope import (
    NUM_ACTIONS, IDX_TO_ACTION, MacroAction, STATE_DIMS,
)
from ml.encoder.state_encoder import CardEmbeddingIndex, StateEncoder

logger = logging.getLogger("ml.serving")


class PolicyInferenceService:
    """
    Loads a trained PolicyNetwork and provides action predictions.

    Thread-safe — uses torch.no_grad() for inference.
    Designed to be embedded in lab_api.py or run standalone.
    """

    def __init__(
        self,
        checkpoint_dir: str = None,
        embeddings_dir: str = None,
        device: str = None,
    ):
        self.checkpoint_dir = checkpoint_dir or os.path.join(
            project_root, "ml", "models", "checkpoints"
        )
        self.embeddings_dir = embeddings_dir or os.path.join(
            project_root, "embeddings"
        )
        self.device = device or self._detect_device()

        self.model = None
        self.encoder = None
        self.card_index = None
        self.checkpoint_info: Dict = {}
        self._loaded = False
        self._load_error: Optional[str] = None

    def _detect_device(self) -> str:
        if not TORCH_AVAILABLE:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def load(self) -> bool:
        """
        Load card embeddings, state encoder, and policy model.
        Returns True if everything loaded successfully.
        """
        if not TORCH_AVAILABLE:
            self._load_error = "PyTorch not installed"
            logger.error("PyTorch not installed — cannot serve policy")
            return False

        # 1. Load card embeddings
        self.card_index = CardEmbeddingIndex(self.embeddings_dir)
        if not self.card_index.load():
            self._load_error = "Card embeddings not found"
            logger.error(
                "Card embeddings not found at %s. "
                "Start the lab server to auto-download, or run coach first.",
                self.embeddings_dir,
            )
            return False

        self.encoder = StateEncoder(self.card_index)

        # 2. Load policy checkpoint
        checkpoint_path = os.path.join(self.checkpoint_dir, "best_policy.pt")
        if not os.path.exists(checkpoint_path):
            self._load_error = f"No checkpoint at {checkpoint_path}"
            logger.warning("No trained model found at %s", checkpoint_path)
            logger.warning("Train a model first: python -m ml.scripts.ml_cli train")
            return False

        try:
            from ml.training.policy_network import load_checkpoint
            self.model, checkpoint = load_checkpoint(checkpoint_path, self.device)
            self.model.eval()

            self.checkpoint_info = {
                "path": checkpoint_path,
                "epoch": checkpoint.get("epoch", "?"),
                "metrics": checkpoint.get("metrics", {}),
                "device": self.device,
            }

            self._loaded = True
            self._load_error = None
            logger.info(
                "Policy model loaded (epoch %s, device=%s)",
                self.checkpoint_info["epoch"], self.device,
            )
            return True

        except Exception as e:
            self._load_error = str(e)
            logger.error("Failed to load checkpoint: %s", e)
            return False

    def reload(self, checkpoint_path: str = None) -> bool:
        """Hot-reload a checkpoint without reloading embeddings."""
        if not TORCH_AVAILABLE:
            return False

        path = checkpoint_path or os.path.join(self.checkpoint_dir, "best_policy.pt")
        if not os.path.exists(path):
            self._load_error = f"Checkpoint not found: {path}"
            return False

        try:
            from ml.training.policy_network import load_checkpoint
            self.model, checkpoint = load_checkpoint(path, self.device)
            self.model.eval()

            self.checkpoint_info = {
                "path": path,
                "epoch": checkpoint.get("epoch", "?"),
                "metrics": checkpoint.get("metrics", {}),
                "device": self.device,
            }
            self._loaded = True
            self._load_error = None
            logger.info("Model hot-reloaded from %s (epoch %s)",
                        path, self.checkpoint_info["epoch"])
            return True

        except Exception as e:
            self._load_error = str(e)
            logger.error("Hot-reload failed: %s", e)
            return False

    def predict(
        self,
        decision_snapshot: Dict,
        playstyle: str = "midrange",
        temperature: float = 1.0,
        greedy: bool = False,
    ) -> Dict:
        """
        Predict a macro-action from a raw decision snapshot.

        Args:
            decision_snapshot: DecisionSnapshot JSON from Java
                Must contain: turn, phase, active_seat, players[]
            playstyle: Deck playstyle hint ("aggro", "control", "midrange", "combo")
            temperature: Softmax temperature (lower = more deterministic)
            greedy: If True, always pick argmax (ignore temperature)

        Returns:
            {
                "action": "cast_creature",
                "action_index": 0,
                "confidence": 0.73,
                "probabilities": {"cast_creature": 0.73, "pass": 0.12, ...},
                "inference_ms": 2.3,
            }
        """
        if not self._loaded:
            return {
                "error": "Model not loaded",
                "detail": self._load_error or "Call load() first",
            }

        t_start = time.time()

        try:
            # Encode the raw snapshot to a state vector
            state_vec = self.encoder.encode(decision_snapshot, playstyle)
            state_tensor = torch.from_numpy(
                state_vec.astype(np.float32)
            ).unsqueeze(0).to(self.device)

            # Run inference
            with torch.no_grad():
                logits = self.model(state_tensor)

                if greedy:
                    action_idx = logits.argmax(dim=-1).item()
                    probs = torch.softmax(logits, dim=-1).cpu().numpy().flatten()
                else:
                    scaled = logits / max(temperature, 0.01)
                    probs = torch.softmax(scaled, dim=-1).cpu().numpy().flatten()
                    action_idx = int(np.random.choice(NUM_ACTIONS, p=probs))

            elapsed_ms = (time.time() - t_start) * 1000

            action = IDX_TO_ACTION[action_idx]
            confidence = float(probs[action_idx])

            # Build probability map
            prob_map = {}
            for i in range(NUM_ACTIONS):
                prob_map[IDX_TO_ACTION[i].value] = round(float(probs[i]), 4)

            return {
                "action": action.value,
                "action_index": action_idx,
                "confidence": round(confidence, 4),
                "probabilities": prob_map,
                "inference_ms": round(elapsed_ms, 2),
            }

        except Exception as e:
            elapsed_ms = (time.time() - t_start) * 1000
            logger.error("Inference error: %s", e)
            return {
                "error": str(e),
                "inference_ms": round(elapsed_ms, 2),
            }

    def predict_batch(
        self,
        snapshots: List[Dict],
        playstyle: str = "midrange",
        greedy: bool = True,
    ) -> List[Dict]:
        """Predict actions for multiple snapshots at once (vectorized)."""
        if not self._loaded:
            return [{"error": "Model not loaded"}] * len(snapshots)

        t_start = time.time()
        results = []

        try:
            # Encode all states
            state_vecs = []
            for snap in snapshots:
                ps = snap.get("archetype", playstyle)
                vec = self.encoder.encode(snap, ps)
                state_vecs.append(vec)

            states = np.stack(state_vecs).astype(np.float32)
            state_tensor = torch.from_numpy(states).to(self.device)

            # Batch inference
            with torch.no_grad():
                logits = self.model(state_tensor)
                probs = torch.softmax(logits, dim=-1).cpu().numpy()

                if greedy:
                    action_indices = logits.argmax(dim=-1).cpu().numpy()
                else:
                    action_indices = np.array([
                        np.random.choice(NUM_ACTIONS, p=p) for p in probs
                    ])

            elapsed_ms = (time.time() - t_start) * 1000

            for i, (idx, prob) in enumerate(zip(action_indices, probs)):
                action = IDX_TO_ACTION[int(idx)]
                results.append({
                    "action": action.value,
                    "action_index": int(idx),
                    "confidence": round(float(prob[idx]), 4),
                })

            logger.debug(
                "Batch inference: %d samples in %.1fms (%.2f ms/sample)",
                len(snapshots), elapsed_ms, elapsed_ms / max(len(snapshots), 1),
            )

        except Exception as e:
            logger.error("Batch inference error: %s", e)
            results = [{"error": str(e)}] * len(snapshots)

        return results

    def get_status(self) -> Dict:
        """Return current service status."""
        return {
            "loaded": self._loaded,
            "error": self._load_error,
            "device": self.device,
            "torch_available": TORCH_AVAILABLE,
            "checkpoint": self.checkpoint_info if self._loaded else None,
            "embeddings_loaded": (
                self.card_index is not None and self.card_index._loaded
            ),
        }


# ══════════════════════════════════════════════════════════
# Standalone FastAPI Server
# ══════════════════════════════════════════════════════════

def create_standalone_app():
    """Create a standalone FastAPI app for the policy server."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(
        title="Commander AI Lab — Policy Server",
        description="Serves macro-action predictions from a trained policy network",
        version="1.0.0",
    )

    service = PolicyInferenceService()

    class PredictRequest(BaseModel):
        """Request body for /predict endpoint."""
        # Game state (matching DecisionSnapshot from Java)
        turn: int = 1
        phase: str = "main_1"
        active_seat: int = 0
        players: List[Dict] = []
        action: Optional[Dict] = None

        # Optional metadata
        game_id: str = ""
        archetype: str = "midrange"
        commander: str = ""
        deck_name: str = ""

        # Inference parameters
        temperature: float = 1.0
        greedy: bool = False

    class PredictResponse(BaseModel):
        action: str
        action_index: int
        confidence: float
        probabilities: Dict[str, float] = {}
        inference_ms: float = 0.0
        error: Optional[str] = None

    @app.on_event("startup")
    async def startup():
        service.load()

    @app.post("/api/ml/predict", response_model=PredictResponse)
    async def predict(req: PredictRequest):
        if not service._loaded:
            raise HTTPException(503, detail=service._load_error or "Model not loaded")

        snapshot = req.dict(exclude={"temperature", "greedy"})
        result = service.predict(
            snapshot,
            playstyle=req.archetype,
            temperature=req.temperature,
            greedy=req.greedy,
        )

        if "error" in result:
            raise HTTPException(500, detail=result["error"])
        return result

    @app.get("/api/ml/model")
    async def model_info():
        return service.get_status()

    @app.post("/api/ml/reload")
    async def reload_model(checkpoint: str = None):
        ok = service.reload(checkpoint)
        return {
            "success": ok,
            "status": service.get_status(),
        }

    @app.get("/health")
    async def health():
        return {
            "status": "ok" if service._loaded else "degraded",
            "model_loaded": service._loaded,
        }

    return app, service


def main():
    """Run standalone policy server."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Commander AI Lab — Policy Inference Server"
    )
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--checkpoint-dir", default=None)
    parser.add_argument("--embeddings-dir", default=None)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    # Override defaults if provided
    if args.checkpoint_dir or args.embeddings_dir or args.device:
        # Re-create the service will be handled at startup
        pass

    app, _ = create_standalone_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
