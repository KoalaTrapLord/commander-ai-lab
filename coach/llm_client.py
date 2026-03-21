"""
Commander AI Lab — Ollama Client
════════════════════════════════════
Async HTTP client targeting Ollama's OpenAI-compatible
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
    LLM_URL, LLM_MODEL,
    LLM_TIMEOUT, LLM_MAX_RETRIES,
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


class LLMClient:
    """
    Client for Ollama's OpenAI-compatible API.

    Usage:
        client = LLMClient()
        response = await client.chat(system_prompt, user_prompt)
        if response.parsed_json:
            suggestions = response.parsed_json
    """

    def __init__(self, base_url: str = None, model: str = None,
                 timeout: int = None):
        self.base_url = (base_url or LLM_URL).rstrip("/")
        self.model = model or LLM_MODEL
        self.timeout = timeout or LLM_TIMEOUT
        self._resolved_model = None  # actual model name from /models endpoint

    def _resolve_model(self) -> str:
        """Get the actual loaded model name from Ollama /models endpoint."""
        if self._resolved_model:
            return self._resolved_model
        try:
            status = self.check_connection()
            if status.get("connected") and status.get("active_model"):
                self._resolved_model = status["active_model"]
                logger.info("Resolved Ollama model: %s", self._resolved_model)
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

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove DeepSeek-R1 <think>...</think> reasoning blocks from LLM output."""
        import re
        # Remove all <think>...</think> blocks (greedy, handles multiline)
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    @staticmethod
    def _extract_json_object(text: str) -> Optional[dict]:
        """Find and parse the first complete JSON object in text.
        Uses brace-counting to handle nested objects reliably."""
        start = text.find('{')
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False

        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                if in_string:
                    escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        return json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        # Malformed — try next opening brace
                        next_start = text.find('{', start + 1)
                        if next_start != -1 and next_start < i:
                            start = next_start
                            depth = 1  # we're already past this brace
                        return None
        return None

    def _parse_response(self, raw: dict) -> LLMResponse:
        """Extract content and usage from OpenAI-format response.
        Handles DeepSeek-R1 <think> tags, markdown fences, and raw JSON."""
        choice = raw.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = raw.get("usage", {})

        # Step 1: Strip <think>...</think> blocks (DeepSeek-R1)
        cleaned = self._strip_think_tags(content)

        # Step 2: Try direct JSON parse on cleaned content
        parsed = None
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            pass

        # Step 3: Try extracting from markdown fences
        if parsed is None and "```json" in cleaned:
            try:
                start = cleaned.index("```json") + 7
                end = cleaned.index("```", start)
                parsed = json.loads(cleaned[start:end].strip())
            except (json.JSONDecodeError, ValueError, IndexError):
                pass
        if parsed is None and "```" in cleaned:
            try:
                start = cleaned.index("```") + 3
                end = cleaned.index("```", start)
                parsed = json.loads(cleaned[start:end].strip())
            except (json.JSONDecodeError, ValueError, IndexError):
                pass

        # Step 4: Brute-force — find the first valid JSON object in the text
        if parsed is None:
            parsed = self._extract_json_object(cleaned)

        # Step 5: If still nothing, try on the original content (in case
        # think-tag stripping was too aggressive)
        if parsed is None and content != cleaned:
            parsed = self._extract_json_object(content)

        if parsed is not None:
            logger.info("Successfully parsed JSON from LLM response")
        else:
            logger.warning("Could not extract JSON from LLM response (%d chars)",
                           len(content))

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
        Synchronous chat call to Ollama.
        Retries up to LLM_MAX_RETRIES on failure or non-JSON response.
        """
        temp = temperature if temperature is not None else DEFAULT_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        body = self._build_request_body(system_prompt, user_prompt,
                                        temp, tokens, force_json)

        last_error = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                logger.info("LLM call attempt %d/%d", attempt, LLM_MAX_RETRIES)
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

                if attempt < LLM_MAX_RETRIES:
                    import time
                    time.sleep(2 * attempt)  # Simple backoff

        raise ConnectionError(
            f"LLM call failed after {LLM_MAX_RETRIES} attempts: {last_error}"
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
        Check if Ollama is reachable. Returns status dict.
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
