"""
Commander AI Lab — AIOpponent (Phase 2)
========================================
High-level AI player that wraps DeepSeekBrain + Phase 1 prompt builder
+ personality prompts to produce per-turn decisions and narration.

Design:
  - Each seat gets one AIOpponent instance (supports 2–4 simultaneous).
  - decide_action() builds the full LLM prompt using Phase 1 helpers,
    calls GPT-OSS 20B via Ollama, parses the response, validates the
    action index against legal_moves, and falls back to heuristic on failure.
  - narrate_play() calls the LLM with a short narration prompt and
    enforces a 30-word cap to prevent UI overflow.
  - All fallback events are logged via StateLogger for tuning.

Usage:
    from commander_ai_lab.sim.ai_opponent import AIOpponent
    from commander_ai_lab.sim.personality_prompts import AGGRO_TIMMY

    ai = AIOpponent(
        name="Timmy",
        seat=1,
        personality=AGGRO_TIMMY,
        deck=[...],  # list[Card]
    )
    ai.brain.check_connection()

    move_id = ai.decide_action(game_state, legal_moves)
    flavor  = ai.narrate_play(move_id, legal_moves)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from commander_ai_lab.sim.deepseek_brain import DeepSeekBrain, DeepSeekConfig
from commander_ai_lab.sim.game_state import CommanderGameState
from commander_ai_lab.sim.personality_prompts import Personality, AGGRO_TIMMY
from commander_ai_lab.sim.prompt_builder import build_full_prompt
from commander_ai_lab.sim.state_logger import StateLogger

logger = logging.getLogger("ai_opponent")

_MAX_NARRATION_WORDS = 30


# ── Memory Log Entry ────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """One entry in the AI's short-term memory log."""
    turn: int
    phase: str
    chosen_move_id: Optional[int]
    move_description: str
    narration: str
    fallback_used: bool
    latency_ms: float


# ── AIOpponent ─────────────────────────────────────────────────────────

@dataclass
class AIOpponent:
    """
    A single AI seat in a Commander game.

    Parameters
    ----------
    name : str
        Display name shown in the UI.
    seat : int
        Seat index in the game (0–3).
    personality : Personality
        One of the four archetype personalities from personality_prompts.py.
    deck : list
        List of Card objects for this player's deck (used for deck context).
    brain_config : DeepSeekConfig | None
        LLM configuration. Defaults to GPT-OSS 20B via Ollama localhost.
    log_dir : str | None
        Directory for StateLogger snapshots. Defaults to logs/snapshots/.
    """

    name: str
    seat: int
    personality: Personality = field(default_factory=lambda: AGGRO_TIMMY)
    deck: list = field(default_factory=list)
    brain_config: Optional[DeepSeekConfig] = None
    log_dir: Optional[str] = None

    # Populated post-init
    brain: DeepSeekBrain = field(init=False)
    state_logger: StateLogger = field(init=False)
    memory_log: list[MemoryEntry] = field(init=False, default_factory=list)

    # Stats
    _total_decisions: int = field(init=False, default=0)
    _total_fallbacks: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.brain = DeepSeekBrain(config=self.brain_config)
        self.state_logger = StateLogger(log_dir=self.log_dir)

    # ── Core API ─────────────────────────────────────────────────

    def decide_action(
        self,
        game_state: CommanderGameState,
        legal_moves: list[dict],
    ) -> Optional[int]:
        """
        Choose a legal move for this AI seat.

        Workflow:
          1. Build the full LLM prompt (Phase 1 helpers + personality).
          2. Send to GPT-OSS 20B via DeepSeekBrain.
          3. Parse LLM response for a move index.
          4. Validate the index is in legal_moves.
          5. On failure, fall back to heuristic and log the event.

        Args:
            game_state:   Current CommanderGameState.
            legal_moves:  List of legal move dicts from the rules engine.
                          Each dict: {"id": int, "category": str, "description": str, ...}

        Returns:
            int: The chosen move's "id" value, or None if no legal moves.
        """
        if not legal_moves:
            return None

        t_start = time.time()
        self._total_decisions += 1
        fallback_used = False
        chosen_id: Optional[int] = None

        # Build the complete prompt
        prompt = build_full_prompt(
            gs=game_state,
            viewer_seat=self.seat,
            moves=legal_moves,
            personality=self.personality.system_prompt,
        )

        # ── Attempt LLM decision ────────────────────────────────
        if self.brain._connected:
            try:
                chosen_id = self._call_llm_for_move(prompt, legal_moves)
            except Exception as exc:
                logger.warning(
                    "[%s seat=%d] LLM decision failed: %s — using fallback",
                    self.name, self.seat, exc,
                )
                chosen_id = None

        # ── Fallback if LLM failed or not connected ────────────────
        if chosen_id is None:
            fallback_used = True
            self._total_fallbacks += 1
            chosen_id = self._heuristic_move(game_state, legal_moves)
            logger.info(
                "[%s seat=%d] Fallback triggered. Chose move id=%s",
                self.name, self.seat, chosen_id,
            )

        latency_ms = round((time.time() - t_start) * 1000, 1)
        move_desc = self._move_description(chosen_id, legal_moves)

        # ── Save snapshot for debugging ───────────────────────────
        try:
            self.state_logger.save(
                game_state=game_state,
                prompt=prompt,
                chosen_move_id=chosen_id,
                seat=self.seat,
                fallback_used=fallback_used,
                extra={"latency_ms": latency_ms, "personality": self.personality.key},
            )
        except Exception as log_exc:
            logger.warning("[%s] State logger failed: %s", self.name, log_exc)

        # ── Memory log ────────────────────────────────────────────
        self.memory_log.append(MemoryEntry(
            turn=game_state.turn,
            phase=game_state.current_phase,
            chosen_move_id=chosen_id,
            move_description=move_desc,
            narration="",  # filled in by narrate_play()
            fallback_used=fallback_used,
            latency_ms=latency_ms,
        ))

        return chosen_id

    def narrate_play(
        self,
        move_id: Optional[int],
        legal_moves: list[dict],
        game_state: Optional[CommanderGameState] = None,
    ) -> str:
        """
        Generate a short in-character flavor line for the chosen action.

        Calls GPT-OSS 20B with a lightweight narration prompt.
        Falls back to a canned line if the LLM is unavailable.
        Always enforces the 30-word cap.

        Args:
            move_id:      The chosen move id (from decide_action).
            legal_moves:  Full legal moves list (to look up description).
            game_state:   Optional state for richer context.

        Returns:
            A narration string of at most 30 words.
        """
        move_desc = self._move_description(move_id, legal_moves)
        narration = ""

        if self.brain._connected:
            try:
                narration = self._call_llm_for_narration(move_desc)
            except Exception as exc:
                logger.debug("[%s] Narration LLM failed: %s", self.name, exc)

        if not narration:
            narration = self._canned_narration(move_desc)

        # Enforce word cap
        words = narration.split()
        if len(words) > _MAX_NARRATION_WORDS:
            narration = " ".join(words[:_MAX_NARRATION_WORDS]) + "…"

        # Back-fill narration into most recent memory entry
        if self.memory_log:
            self.memory_log[-1].narration = narration

        return narration

    # ── LLM Helpers ────────────────────────────────────────────────

    def _call_llm_for_move(
        self,
        prompt: str,
        legal_moves: list[dict],
    ) -> Optional[int]:
        """
        Send the full prompt to the LLM and parse a move index from the response.
        Returns the move id or None if parsing fails.
        """
        from urllib.request import Request, urlopen
        import json as _json

        cfg = self.brain.config
        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": cfg.temperature,
            "max_tokens": 64,   # We only need a number
            "top_p": cfg.top_p,
            "stream": False,
        }

        url = cfg.api_base.rstrip("/") + "/v1/chat/completions"
        req_data = _json.dumps(payload).encode("utf-8")
        req = Request(url, data=req_data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urlopen(req, timeout=cfg.request_timeout) as resp:
            resp_data = _json.loads(resp.read())

        choices = resp_data.get("choices", [])
        if not choices:
            return None

        raw = choices[0].get("message", {}).get("content", "").strip()
        return self._parse_move_id(raw, legal_moves)

    def _call_llm_for_narration(self, move_desc: str) -> str:
        """
        Call the LLM with a short narration prompt.
        Returns raw narration text (word-capping applied in narrate_play).
        """
        from urllib.request import Request, urlopen
        import json as _json

        narration_prompt = (
            f"{self.personality.system_prompt}\n\n"
            f"You just played: {move_desc}\n"
            f"Give a single in-character reaction of at most {_MAX_NARRATION_WORDS} words. "
            f"No explanation. Just the flavor line."
        )

        cfg = self.brain.config
        payload = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": narration_prompt}],
            "temperature": 0.8,    # Higher temperature for creative narration
            "max_tokens": 80,
            "stream": False,
        }

        url = cfg.api_base.rstrip("/") + "/v1/chat/completions"
        req_data = _json.dumps(payload).encode("utf-8")
        req = Request(url, data=req_data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urlopen(req, timeout=10.0) as resp:
            resp_data = _json.loads(resp.read())

        choices = resp_data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()

    # ── Response Parsing ───────────────────────────────────────────────

    def _parse_move_id(
        self,
        raw: str,
        legal_moves: list[dict],
    ) -> Optional[int]:
        """
        Extract a valid move id from the LLM's raw text response.

        Strategies (in order):
          1. Raw text is just a number → use it if valid.
          2. First integer found in text → use it if valid.
          3. JSON with an 'id' or 'action' key → extract and validate.
          4. Return None (triggers fallback).
        """
        valid_ids = {m["id"] for m in legal_moves}

        # Strip think blocks (reasoning models)
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

        # Strategy 1: whole response is a number
        stripped = raw.strip()
        if stripped.isdigit():
            mid = int(stripped)
            if mid in valid_ids:
                return mid

        # Strategy 2: first integer in text
        nums = re.findall(r'\b(\d+)\b', raw)
        for n in nums:
            mid = int(n)
            if mid in valid_ids:
                return mid

        # Strategy 3: JSON object with id/action key
        json_match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                for key in ("id", "move_id", "choice", "action"):
                    if key in parsed:
                        mid = int(parsed[key])
                        if mid in valid_ids:
                            return mid
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        logger.debug("[%s] Could not parse move id from: %r", self.name, raw[:100])
        return None

    # ── Heuristic Fallback ───────────────────────────────────────────────

    def _heuristic_move(self, game_state: CommanderGameState, legal_moves: list[dict]) -> int:
        """
        Priority-based heuristic fallback.

        Priority order (personality-agnostic safe default):
          1. play_land
          2. cast_commander
          3. cast_spell
          4. attack
          5. activate_ability
          6. pass_priority / pass_turn
          7. Any other move (first available)
        """
        priority_categories = [
            "play_land",
            "cast_commander",
            "cast_spell",
            "attack",
            "activate_ability",
            "pass_priority",
            "pass_turn",
        ]

        moves_by_cat: dict[str, list[dict]] = {}
        for m in legal_moves:
            cat = m.get("category", "other")
            moves_by_cat.setdefault(cat, []).append(m)

        for cat in priority_categories:
            if cat in moves_by_cat:
                return moves_by_cat[cat][0]["id"]

        # Absolute last resort
        return legal_moves[0]["id"]

    # ── Canned Narration ───────────────────────────────────────────────

    _CANNED: dict[str, dict[str, str]] = {
        "aggro_timmy": {
            "play_land": "More mana, more mayhem!",
            "cast_spell": "Here comes the pain!",
            "attack": "ATTACK! Take everything!",
            "pass_priority": "Fine, go… but I’m watching you.",
            "default": "Let’s smash something!",
        },
        "control_spike": {
            "play_land": "Mana secured. Proceeding.",
            "cast_spell": "Optimal play. As expected.",
            "attack": "Calculated aggression — acceptable risk.",
            "pass_priority": "Holding interaction mana. Predictable of you.",
            "default": "Inevitable victory approaches.",
        },
        "combo_johnny": {
            "play_land": "One step closer to the combo!",
            "cast_spell": "Assembling the pieces…",
            "attack": "Buying time until the combo fires.",
            "pass_priority": "Patience. The combo is coming.",
            "default": "The pieces are falling into place!",
        },
        "political_negotiator": {
            "play_land": "Just tapping a land. Nothing threatening here.",
            "cast_spell": "This helps us all, really.",
            "attack": "I’m afraid I must — for the good of the table.",
            "pass_priority": "I’ll let this resolve. For now.",
            "default": "Let’s all be reasonable about this.",
        },
    }

    def _canned_narration(self, move_desc: str) -> str:
        """Return a canned flavor line matching personality and move category."""
        canned = self._CANNED.get(self.personality.key, {})
        desc_lower = move_desc.lower()
        for key in ("play_land", "cast_spell", "attack", "pass_priority"):
            if key.replace("_", " ") in desc_lower or key in desc_lower:
                return canned.get(key, canned.get("default", "Interesting move."))
        return canned.get("default", "Interesting move.")

    # ── Utilities ──────────────────────────────────────────────────────────

    @staticmethod
    def _move_description(move_id: Optional[int], legal_moves: list[dict]) -> str:
        if move_id is None:
            return "(no move)"
        for m in legal_moves:
            if m["id"] == move_id:
                return m.get("description", f"Move {move_id}")
        return f"Move {move_id}"

    def get_stats(self) -> dict:
        """Return per-opponent decision statistics."""
        return {
            "name": self.name,
            "seat": self.seat,
            "personality": self.personality.key,
            "total_decisions": self._total_decisions,
            "total_fallbacks": self._total_fallbacks,
            "fallback_rate": (
                round(self._total_fallbacks / max(self._total_decisions, 1), 3)
            ),
            "memory_entries": len(self.memory_log),
            "llm_stats": self.brain.get_stats(),
        }

    def new_game(self) -> None:
        """Reset per-game state for a new game."""
        self.memory_log.clear()
        self._total_decisions = 0
        self._total_fallbacks = 0
        self.brain.new_game(ai_player_index=self.seat)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_four_player_ai_roster(
    names: list[str] | None = None,
    brain_config: DeepSeekConfig | None = None,
    log_dir: str | None = None,
) -> list[AIOpponent]:
    """
    Create a standard 4-player AI roster with one of each personality.

    Args:
        names: Optional list of 4 display names. Defaults to personality display names.
        brain_config: Shared LLM config for all opponents.
        log_dir: Shared snapshot log directory.

    Returns:
        List of 4 AIOpponent instances (seats 0–3).
    """
    from commander_ai_lab.sim.personality_prompts import (
        AGGRO_TIMMY, CONTROL_SPIKE, COMBO_JOHNNY, POLITICAL_NEGOTIATOR
    )

    archetypes = [AGGRO_TIMMY, CONTROL_SPIKE, COMBO_JOHNNY, POLITICAL_NEGOTIATOR]
    default_names = [p.display_name for p in archetypes]
    display_names = names if (names and len(names) == 4) else default_names

    return [
        AIOpponent(
            name=display_names[i],
            seat=i,
            personality=archetypes[i],
            brain_config=brain_config,
            log_dir=log_dir,
        )
        for i in range(4)
    ]
