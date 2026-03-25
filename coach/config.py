"""
Commander AI Lab — Coach Configuration
═══════════════════════════════════════
Central config for Ollama, embeddings, and coach service paths.
All paths are relative to the commander-ai-lab root directory.
"""

import os
from pathlib import Path

# ── Base Paths ────────────────────────────────────────────
LAB_ROOT = Path(os.environ.get("COMMANDER_LAB_ROOT", Path(__file__).parent.parent))

# ── Ollama (OpenAI-compatible API) ──────────────────────
LLM_URL = os.environ.get("LLM_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-oss:20b")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "360"))  # seconds
LLM_MAX_RETRIES = 3

# ── Embeddings ──────────────────────────────────────────────
EMBEDDINGS_DIR = LAB_ROOT / "data"
EMBEDDINGS_NPZ = EMBEDDINGS_DIR / "mtg-embeddings.npz"
EMBEDDINGS_PARQUET = EMBEDDINGS_DIR / "mtg-embeddings.parquet"

# ── Deck Reports ───────────────────────────────────────────
DECK_REPORTS_DIR = LAB_ROOT / "deck-reports"
COACH_SESSIONS_DIR = LAB_ROOT / "coach-sessions"

# ── Prompt Limits ──────────────────────────────────────────
MAX_PROMPT_TOKENS = 2048
MAX_CANDIDATES_PER_UNDERPERFORMER = 5
MAX_UNDERPERFORMERS = 4
UNDERPERFORMER_IMPACT_THRESHOLD = -0.05  # impactScore below this = underperformer

# ── LLM Generation Settings (Coach — Ollama fallback) ────────────
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 8192

# ── Perplexity Deck Generation Settings ───────────────────────
# Provider for deck generation: "perplexity" (V3) or "local" (V2 collection-based)
DECK_GEN_PROVIDER = os.environ.get("DECK_GEN_PROVIDER", "perplexity")
# Model used when DECK_GEN_PROVIDER="perplexity" (sonar = fast, sonar-pro = deep)
DECK_GEN_MODEL = os.environ.get("DECK_GEN_MODEL", "sonar-pro")
# Perplexity cloud model (sonar / sonar-pro / sonar-deep-research)
PPLX_MODEL = os.environ.get("PPLX_MODEL", "sonar-pro")
# Coach chat provider: "perplexity" (Perplexity API) or "local" (Ollama)
COACH_PROVIDER = os.environ.get("COACH_PROVIDER", "perplexity")
DECK_GEN_BASE_URL = os.environ.get("DECK_GEN_BASE_URL", "http://localhost:11434/v1")
DECK_GEN_TEMPERATURE = float(os.environ.get("DECK_GEN_TEMPERATURE", "0.2"))
DECK_GEN_MAX_TOKENS = int(os.environ.get("DECK_GEN_MAX_TOKENS", "16384"))

# ── Smart Substitution Settings ──────────────────────────────
# Minimum embedding similarity to accept a substitute without Perplexity fallback
SUBSTITUTION_MIN_SIMILARITY = float(os.environ.get("SUBSTITUTION_MIN_SIMILARITY", "0.75"))
# Maximum number of alternatives to suggest per missing card
SUBSTITUTION_MAX_ALTERNATIVES = int(os.environ.get("SUBSTITUTION_MAX_ALTERNATIVES", "5"))
# Model for substitution fallback (sonar is fine — small focused queries)
SUBSTITUTION_MODEL = os.environ.get("SUBSTITUTION_MODEL", "sonar")
# Enable Perplexity fallback for low-confidence embedding matches
SUBSTITUTION_USE_PPLX_FALLBACK = os.environ.get("SUBSTITUTION_USE_PPLX_FALLBACK", "true").lower() == "true"

# ── Ensure directories exist ───────────────────────────────────
def ensure_dirs():
    """Create required directories if they don't exist."""
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    DECK_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    COACH_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
