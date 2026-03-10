"""
Commander AI Lab — Coach Configuration
═══════════════════════════════════════
Central config for LM Studio, embeddings, and coach service paths.
All paths are relative to the commander-ai-lab root directory.
"""

import os
from pathlib import Path

# ── Base Paths ──────────────────────────────────────────────
# Resolve relative to wherever the lab is installed
LAB_ROOT = Path(os.environ.get("COMMANDER_LAB_ROOT", Path(__file__).parent.parent))

# ── LM Studio (OpenAI-compatible API) ──────────────────────
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://192.168.0.122:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")
LM_STUDIO_TIMEOUT = int(os.environ.get("LM_STUDIO_TIMEOUT", "120"))  # seconds
LM_STUDIO_MAX_RETRIES = 3

# ── Embeddings ─────────────────────────────────────────────
EMBEDDINGS_DIR = LAB_ROOT / "data"
EMBEDDINGS_NPZ = EMBEDDINGS_DIR / "mtg-embeddings.npz"
EMBEDDINGS_PARQUET = EMBEDDINGS_DIR / "mtg-embeddings.parquet"

# ── Deck Reports ───────────────────────────────────────────
DECK_REPORTS_DIR = LAB_ROOT / "deck-reports"
COACH_SESSIONS_DIR = LAB_ROOT / "coach-sessions"

# ── Prompt Limits ──────────────────────────────────────────
MAX_PROMPT_TOKENS = 4096
MAX_CANDIDATES_PER_UNDERPERFORMER = 10
MAX_UNDERPERFORMERS = 8
UNDERPERFORMER_IMPACT_THRESHOLD = -0.05  # impactScore below this = underperformer

# ── LLM Generation Settings ────────────────────────────────
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048

# ── Ensure directories exist ───────────────────────────────
def ensure_dirs():
    """Create required directories if they don't exist."""
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    DECK_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    COACH_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
