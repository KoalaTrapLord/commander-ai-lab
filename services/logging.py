"""
services/logging.py
====================
Single source of truth for application logging configuration and named loggers.

Moved from routes/shared.py so that every layer (routes, services, CLI
entry-points) can import logging without pulling in the full shared module.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# ── Format / rotation constants ───────────────────────────────────────────────
_LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR = Path(os.environ.get("CAL_LOG_DIR", "logs"))
_LOG_MAX_BYTES = int(os.environ.get("CAL_LOG_MAX_MB", "25")) * 1024 * 1024
_LOG_BACKUP_COUNT = int(os.environ.get("CAL_LOG_BACKUP_COUNT", "5"))


def setup_logging(level: int = logging.INFO) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger("commander_ai_lab")
    root_logger.setLevel(level)
    if root_logger.handlers:
        return
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "commander-ai-lab.log",
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


# ── Named loggers ────────────────────────────────────────────────────────────
log          = logging.getLogger("commander_ai_lab.api")
log_batch    = logging.getLogger("commander_ai_lab.batch")
log_sim      = logging.getLogger("commander_ai_lab.sim")
log_coach    = logging.getLogger("commander_ai_lab.coach")
log_deckgen  = logging.getLogger("commander_ai_lab.deckgen")
log_collect  = logging.getLogger("commander_ai_lab.collection")
log_scan     = logging.getLogger("commander_ai_lab.scanner")
log_ml       = logging.getLogger("commander_ai_lab.ml")
log_cache    = logging.getLogger("commander_ai_lab.cache")
log_pplx     = logging.getLogger("commander_ai_lab.pplx")

# ── ML logging toggle ────────────────────────────────────────────────────────
_ml_logging_enabled = True
