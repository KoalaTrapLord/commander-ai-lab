"""Runtime configuration, state classes, and static data for Commander AI Lab."""
from __future__ import annotations
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


log = logging.getLogger("commander_ai_lab.api")


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════
class Config:
    """Runtime configuration -- set via CLI args or env vars."""
    forge_jar: str = ""
    forge_dir: str = ""
    forge_decks_dir: str = ""
    lab_jar: str = ""
    precon_dir: str = ""
    results_dir: str = "results"
    port: int = 8080
    ximilar_api_key: str = ""
    pplx_api_key: str = ""


CFG = Config()


# ══════════════════════════════════════════════════════════════
# In-Memory State
# ══════════════════════════════════════════════════════════════
class BatchState:
    def __init__(self, batch_id: str, total_games: int, threads: int):
        self.batch_id = batch_id
        self.total_games = total_games
        self.threads = threads
        self.completed_games = 0
        self.running = True
        self.start_time = datetime.now()
        self.elapsed_ms = 0
        self.result_path: Optional[str] = None
        self.error: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self.log_lines: list = []
        self.sims_per_sec: float = 0.0


active_batches: dict[str, BatchState] = {}


COMMANDER_META: dict = {}

BUILTIN_COMMANDERS: dict = {
    "Edgar Markov": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["W","B","R"]}],
    "Atraxa, Praetors' Voice": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["W","U","B","G"]}],
    "Korvold, Fae-Cursed King": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["B","R","G"]}],
    "Muldrotha, the Gravetide": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["U","B","G"]}],
    "The Ur-Dragon": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["W","U","B","R","G"]}],
    "Yuriko, the Tiger's Shadow": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["U","B"]}],
    "Krenko, Mob Boss": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["R"]}],
    "Meren of Clan Nel Toth": [{"source": "edhrec", "archetype": "midrange", "colorIdentity": ["B","G"]}],
    "Prossh, Skyraider of Kher": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["B","R","G"]}],
    "Kaalia of the Vast": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["W","B","R"]}],
    "Talrand, Sky Summoner": [{"source": "edhrec", "archetype": "control", "colorIdentity": ["U"]}],
    "Omnath, Locus of Creation": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["W","U","R","G"]}],
    "Teysa Karlov": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["W","B"]}],
    "Lathril, Blade of the Elves": [{"source": "edhrec", "archetype": "aggro", "colorIdentity": ["B","G"]}],
    "Breya, Etherium Shaper": [{"source": "edhrec", "archetype": "combo", "colorIdentity": ["W","U","B","R"]}],
}


def load_commander_meta() -> None:
    """Load commander meta mapping from file or fall back to builtins."""
    global COMMANDER_META
    meta_path = Path(__file__).parent.parent / "commander-meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                COMMANDER_META = json.load(f)
            log.info(f" Meta: Loaded {len(COMMANDER_META)} commanders from {meta_path}")
            return
        except Exception as e:
            log.warning(f" WARNING: Failed to load commander-meta.json: {e}")
    COMMANDER_META = BUILTIN_COMMANDERS
    log.info(f" Meta:    {len(COMMANDER_META)} built-in commanders")


# ══════════════════════════════════════════════════════════════
# AI Profiles
# ══════════════════════════════════════════════════════════════
AI_PROFILES = {
    "default": {"name": "default", "description": "Balanced \u2014 Forge's default AI behavior", "aggression": 0.5, "cardAdvantage": 0.5, "removalPriority": 0.5, "boardPresence": 0.5, "comboPriority": 0.3, "patience": 0.5},
    "aggro": {"name": "aggro", "description": "Aggressive \u2014 attacks early, prioritizes damage", "aggression": 0.9, "cardAdvantage": 0.3, "removalPriority": 0.3, "boardPresence": 0.8, "comboPriority": 0.1, "patience": 0.1},
    "control": {"name": "control", "description": "Control \u2014 defensive, removal-heavy, card advantage", "aggression": 0.2, "cardAdvantage": 0.9, "removalPriority": 0.9, "boardPresence": 0.3, "comboPriority": 0.4, "patience": 0.9},
    "combo": {"name": "combo", "description": "Combo \u2014 ramps, digs for pieces, assembles combos", "aggression": 0.2, "cardAdvantage": 0.8, "removalPriority": 0.4, "boardPresence": 0.3, "comboPriority": 0.95, "patience": 0.7},
    "midrange": {"name": "midrange", "description": "Midrange \u2014 flexible, strong board presence, value-oriented", "aggression": 0.5, "cardAdvantage": 0.6, "removalPriority": 0.6, "boardPresence": 0.7, "comboPriority": 0.3, "patience": 0.5},
}
