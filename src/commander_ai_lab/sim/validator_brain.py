"""
src/commander_ai_lab/sim/validator_brain.py
===========================================
DeepSeek-R1-Distill-Qwen-14B validator / explainer brain.

Called AFTER GPT-OSS 20B chooses an action.  Receives the game-state
snapshot and the chosen action, then returns:
  - legality check (legal / illegal / unclear)
  - tactical quality assessment
  - suggested improvement (or null)
  - player_explanation: 2-5 sentences suitable for display in the UI

Strips <think> blocks automatically (R1-style reasoning models always
emit them).  Falls back silently on timeout so it never blocks the
game loop.

Environment variables (all optional -- see ValidatorConfig defaults):
  VALIDATOR_ENABLED      true/false (default: false)
  VALIDATOR_API_BASE     Ollama/LM-Studio base URL (default: http://localhost:11434)
  VALIDATOR_MODEL        model name              (default: deepseek-r1:14b)
  VALIDATOR_TEMPERATURE  generation temperature  (default: 0.0)
  VALIDATOR_MAX_TOKENS   max output tokens       (default: 2048)
  VALIDATOR_TIMEOUT      request timeout seconds (default: 60.0)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from urllib.request import Request, urlopen

logger = logging.getLogger("validator_brain")


# ==============================================================
# Configuration
# ==============================================================

@dataclass
class ValidatorConfig:
    """
    Configuration for the R1-14B validator brain.

    All fields can be overridden via environment variables at runtime
    (see module docstring).  Defaults target deepseek-r1:14b served by
    Ollama on localhost.

    Example -- LM Studio::
        cfg = ValidatorConfig(
            api_base="http://192.168.0.240:1234",
            model="deepseek-r1-distill-qwen-14b",
        )
    """
    api_base: str = "http://localhost:11434"
    model: str = "deepseek-r1:14b"
    temperature: float = 0.0
    max_tokens: int = 2048
    request_timeout: float = 300.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "ValidatorConfig":
        """Build a ValidatorConfig from environment variables."""
        enabled_str = os.environ.get("VALIDATOR_ENABLED", "false").lower()
        return cls(
            api_base=os.environ.get("VALIDATOR_API_BASE", "http://localhost:11434"),
            model=os.environ.get("VALIDATOR_MODEL", "deepseek-r1:14b"),
            temperature=float(os.environ.get("VALIDATOR_TEMPERATURE", "0.0")),
            max_tokens=int(os.environ.get("VALIDATOR_MAX_TOKENS", "2048")),
            request_timeout=float(os.environ.get("VALIDATOR_TIMEOUT", "300.0")),
            enabled=(enabled_str == "true"),
        )


# ==============================================================
# Prompts
# ==============================================================

VALIDATOR_SYSTEM_PROMPT = """You are an expert Magic: The Gathering Commander rules judge and strategy coach.

You will receive:
1. A JSON game-state snapshot.
2. A proposed action chosen by an AI opponent.

Your tasks:
1. LEGALITY CHECK -- verify the proposed action is rules-legal given the game state.
   Check: does the player have the mana to cast the target card? Is the target card
   actually in hand? Is the action type appropriate (e.g., no attacking on turn 1
   with a creature played this turn without haste)?
2. TACTICAL QUALITY -- evaluate how strong the action is for the active player given
   their archetype, threat level, and hand.
3. EXPLANATION -- write a clear 2-5 sentence explanation suitable for showing to
   a human player watching the simulation.

IMPORTANT:
- Think through your reasoning internally using <think> blocks.
- Then output ONLY the JSON object below -- no other text outside the JSON.

Output this exact JSON structure:
{
  "legality": "legal",
  "legality_issues": [],
  "tactical_assessment": "short paragraph describing tactical quality",
  "suggested_improvement": null,
  "player_explanation": "2-5 sentence explanation of what the AI did and why"
}

Rules:
- Set "legality" to "legal", "illegal", or "unclear".
- Set "legality_issues" to a list of issue strings if illegal/unclear, otherwise [].
- Set "suggested_improvement" to a one-sentence alternative if a clearly better line
  exists, otherwise null.
- Keep "player_explanation" concise, friendly, and informative for a human audience.
"""

VALIDATOR_USER_TEMPLATE = """Game state:
{game_state_json}

Chosen action:
{action_json}

Validate this action and provide your analysis. Respond with ONLY valid JSON."""


# ==============================================================
# ValidatorBrain
# ==============================================================

class ValidatorBrain:
    """
    Thin LLM client for the DeepSeek-R1-14B validator role.

    Designed to be called after GPT-OSS 20B chooses an action.
    Never raises -- returns None on timeout or parse failure so the
    game loop is never blocked.

    Usage::
        from commander_ai_lab.sim.validator_brain import ValidatorBrain, ValidatorConfig

        cfg = ValidatorConfig.from_env()   # reads VALIDATOR_* env vars
        validator = ValidatorBrain(cfg)
        result = validator.validate(game_state_snapshot, chosen_action)
        if result:
            print(result["player_explanation"])
    """

    def __init__(self, config: ValidatorConfig | None = None):
        self.config = config or ValidatorConfig.from_env()
        self._total_calls: int = 0
        self._total_failures: int = 0
        self._total_latency_ms: float = 0.0

    # -- Public API ----------------------------------------

    def validate(
        self,
        game_state_snapshot: dict,
        chosen_action: dict,
    ) -> dict | None:
        """
        Validate a chosen action against the current game state.

        Returns a dict with keys:
          legality            -- "legal" | "illegal" | "unclear"
          legality_issues     -- list[str]
          tactical_assessment -- str
          suggested_improvement -- str | None
          player_explanation  -- str

        Returns None on timeout, connection error, or JSON parse failure.
        The caller should silently continue with the original action.
        """
        if not self.config.enabled:
            return None

        self._total_calls += 1
        t_start = time.time()

        game_state_json = json.dumps(game_state_snapshot, indent=2)
        action_json = json.dumps(chosen_action, indent=2)
        user_msg = VALIDATOR_USER_TEMPLATE.format(
            game_state_json=game_state_json,
            action_json=action_json,
        )

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": VALIDATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }

        try:
            url = self.config.api_base.rstrip("/") + "/v1/chat/completions"
            req = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")

            with urlopen(req, timeout=self.config.request_timeout) as resp:
                data = json.loads(resp.read())

            raw = data["choices"][0]["message"]["content"]
            result = self._parse_response(raw)
            latency = round((time.time() - t_start) * 1000, 1)
            self._total_latency_ms += latency
            logger.debug(
                "Validator latency: %sms  legality=%s",
                latency, result.get("legality"),
            )
            return result

        except Exception as exc:
            self._total_failures += 1
            logger.warning("Validator call failed (proceeding without validation): %s", exc)
            return None

    def check_connection(self) -> bool:
        """Test whether the validator endpoint is reachable."""
        try:
            url = self.config.api_base.rstrip("/") + "/v1/models"
            req = Request(url, method="GET")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = data.get("data", [])
                if models:
                    logger.info(
                        "Validator connected to %s  model=%s",
                        self.config.api_base, self.config.model,
                    )
                return True
        except Exception as exc:
            logger.warning("Validator connection check failed: %s", exc)
            return False

    def get_stats(self) -> dict:
        """Return performance statistics for monitoring/API endpoints."""
        successful = self._total_calls - self._total_failures
        avg_latency = round(
            self._total_latency_ms / max(successful, 1), 1
        )
        return {
            "total_calls": self._total_calls,
            "failures": self._total_failures,
            "successful": successful,
            "avg_latency_ms": avg_latency,
            "model": self.config.model,
            "api_base": self.config.api_base,
            "enabled": self.config.enabled,
        }

    # -- Internal helpers ----------------------------------

    def _parse_response(self, raw_text: str) -> dict:
        """Strip <think> blocks and markdown fences, then parse JSON."""
        text = raw_text.strip()

        # Strip R1-style <think>...</think> reasoning blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Strip any unclosed <think> block trailing the response
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()

        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

        # Extract outermost JSON object if any surrounding text leaked through
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)

        parsed = json.loads(text)

        return {
            "legality": parsed.get("legality", "unclear"),
            "legality_issues": parsed.get("legality_issues", []),
            "tactical_assessment": parsed.get("tactical_assessment", ""),
            "suggested_improvement": parsed.get("suggested_improvement"),
            "player_explanation": parsed.get("player_explanation", ""),
        }
