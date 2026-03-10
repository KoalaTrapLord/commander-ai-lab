"""
Commander AI Lab — LM Studio Client
════════════════════════════════════
Async HTTP client targeting LM Studio's OpenAI-compatible
/v1/chat/completions endpoint. Includes retry logic for
non-JSON responses and configurable timeout.
"""

import json
import logging
import asyncio
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from .config import (
    LM_STUDIO_URL, LM_STUDIO_MODEL,
    LM_STUDIO_TIMEOUT, LM_STUDIO_MAX_RETRIES,
    DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS,
)

logger = logging.getLogger("coach.llm")


class LLMResponse:
    """Parsed LLM response container."""
    def __init__(self, content: str, parsed_json: Optional[dict],
                 prompt_tokens: int, completion_tokens: int,
                 model: str):
        self.content = content
        self.parsed_json = parsed_json
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model


class LMStudioClient:
    """
    Client for LM Studio's OpenAI-compatible API.

    Usage:
        client = LMStudioClient()
        response = await client.chat(system_prompt, user_prompt)
        if response.parsed_json:
            suggestions = response.parsed_json
    """

    def __init__(self, base_url: str = None, model: str = None,
                 timeout: int = None):
        self.base_url = (base_url or LM_STUDIO_URL).rstrip("/")
        self.model = model or LM_STUDIO_MODEL
        self.timeout = timeout or LM_STUDIO_TIMEOUT
        self._resolved_model = None  # actual model name from /models endpoint

    def _resolve_model(self) -> str:
        """Get the actual loaded model name from LM Studio /models endpoint."""
        if self._resolved_model:
            return self._resolved_model
        try:
            status = self.check_connection()
            if status.get("connected") and status.get("active_model"):
                self._resolved_model = status["active_model"]
                logger.info("Resolved LM Studio model: %s", self._resolved_model)
                return self._resolved_model
        except Exception:
            pass
        return self.model

    def _build_request_body(self, system_prompt: str, user_prompt: str,
                            temperature: float, max_tokens: int,
                            force_json: bool) -> dict:
        model_name = self._resolve_model()
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Only request JSON format if using a model that supports it
        # Some models (esp. smaller ones) don't support response_format
        if force_json:
            body["response_format"] = {"type": "json_object"}
        return body

    def _parse_response(self, raw: dict) -> LLMResponse:
        """Extract content and usage from OpenAI-format response."""
        choice = raw.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = raw.get("usage", {})

        # Try to parse content as JSON
        parsed = None
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # Try to extract JSON from markdown fences
            if "```json" in content:
                start = content.index("```json") + 7
                end = content.index("```", start)
                try:
                    parsed = json.loads(content[start:end].strip())
                except (json.JSONDecodeError, ValueError):
                    pass
            elif "```" in content:
                start = content.index("```") + 3
                end = content.index("```", start)
                try:
                    parsed = json.loads(content[start:end].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        return LLMResponse(
            content=content,
            parsed_json=parsed,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=raw.get("model", self.model),
        )

    def chat_sync(self, system_prompt: str, user_prompt: str,
                  temperature: float = None, max_tokens: int = None,
                  force_json: bool = True) -> LLMResponse:
        """
        Synchronous chat call to LM Studio.
        Retries up to LM_STUDIO_MAX_RETRIES on failure or non-JSON response.
        """
        temp = temperature if temperature is not None else DEFAULT_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        body = self._build_request_body(system_prompt, user_prompt,
                                        temp, tokens, force_json)

        last_error = None
        for attempt in range(1, LM_STUDIO_MAX_RETRIES + 1):
            try:
                logger.info("LLM call attempt %d/%d", attempt, LM_STUDIO_MAX_RETRIES)
                req = Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=self.timeout) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))

                result = self._parse_response(raw)

                # If we need JSON and didn't get it, retry
                if force_json and result.parsed_json is None:
                    logger.warning("Attempt %d: LLM returned non-JSON, retrying", attempt)
                    last_error = ValueError("Non-JSON response from LLM")
                    continue

                return result

            except Exception as e:
                logger.warning("Attempt %d failed: %s", attempt, e)
                last_error = e

                # If 400 and we used json response_format, retry without it
                error_str = str(e)
                if "400" in error_str and force_json:
                    logger.warning("Got 400 — retrying without response_format constraint")
                    force_json = False
                    body = self._build_request_body(
                        system_prompt, user_prompt, temp, tokens, False)

                if attempt < LM_STUDIO_MAX_RETRIES:
                    import time
                    time.sleep(2 * attempt)  # Simple backoff

        raise ConnectionError(
            f"LLM call failed after {LM_STUDIO_MAX_RETRIES} attempts: {last_error}"
        )

    async def chat(self, system_prompt: str, user_prompt: str,
                   temperature: float = None, max_tokens: int = None,
                   force_json: bool = True) -> LLMResponse:
        """
        Async chat call — runs the sync call in a thread executor
        so it doesn't block the FastAPI event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.chat_sync(system_prompt, user_prompt,
                                   temperature, max_tokens, force_json)
        )

    def check_connection(self) -> dict:
        """
        Check if LM Studio is reachable. Returns status dict.
        """
        try:
            req = Request(
                f"{self.base_url}/models",
                headers={"Content-Type": "application/json"},
                method="GET",
            )
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                model_ids = [m.get("id", "unknown") for m in models]
                return {
                    "connected": True,
                    "models": model_ids,
                    "active_model": model_ids[0] if model_ids else self.model,
                }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "models": [],
                "active_model": None,
            }
