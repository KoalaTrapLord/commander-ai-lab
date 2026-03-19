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
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://192.168.0.240:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "gpt-oss:20b")
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

# ── LLM Generation Settings (Coach — LM Studio) ──────────────
DEFAULT_TEMPERATURE = 0.7
# DeepSeek-R1 uses <think> reasoning tokens before the JSON output,
# so we need a generous limit to avoid truncation
DEFAULT_MAX_TOKENS = 8192

# ── Perplexity Deck Generation Settings ───────────────────────
# Provider for deck generation: "perplexity" (V3) or "local" (V2 collection-based)
DECK_GEN_PROVIDER = os.environ.get("DECK_GEN_PROVIDER", "local")
# Model for deck generation (sonar = fast/$0.004, sonar-pro = deep/$0.04)
DECK_GEN_MODEL = os.environ.get("DECK_GEN_MODEL", "gpt-oss:20b")
DECK_GEN_BASE_URL = os.environ.get("DECK_GEN_BASE_URL", "http://192.168.0.240:1234/v1")
DECK_GEN_TEMPERATURE = float(os.environ.get("DECK_GEN_TEMPERATURE", "0.2"))
DECK_GEN_MAX_TOKENS = int(os.environ.get("DECK_GEN_MAX_TOKENS", "16384"))

# ── Smart Substitution Settings ───────────────────────────────
# Minimum embedding similarity to accept a substitute without Perplexity fallback
SUBSTITUTION_MIN_SIMILARITY = float(os.environ.get("SUBSTITUTION_MIN_SIMILARITY", "0.75"))
# Maximum number of alternatives to suggest per missing card
SUBSTITUTION_MAX_ALTERNATIVES = int(os.environ.get("SUBSTITUTION_MAX_ALTERNATIVES", "5"))
# Model for substitution fallback (sonar is fine — small focused queries)
SUBSTITUTION_MODEL = os.environ.get("SUBSTITUTION_MODEL", "gpt-oss:20b")
# Enable Perplexity fallback for low-confidence embedding matches
SUBSTITUTION_USE_PPLX_FALLBACK = os.environ.get("SUBSTITUTION_USE_PPLX_FALLBACK", "true").lower() == "true"

# ── Ensure directories exist ───────────────────────────────
def ensure_dirs():
    """Create required directories if they don't exist."""
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    DECK_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    COACH_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
