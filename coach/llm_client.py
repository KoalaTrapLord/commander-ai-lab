"""
Commander AI Lab — Ollama LLM Client
════════════════════════════════════
Fully async HTTP client targeting Ollama's OpenAI-compatible
/v1/chat/completions endpoint.  Every network call uses
httpx.AsyncClient so it NEVER blocks the FastAPI event loop.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from .config import (
    LLM_URL,
    LLM_MODEL,
    LLM_TIMEOUT,
    LLM_MAX_RETRIES,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
)

logger = logging.getLogger("coach.llm")


class LLMResponse:
    """Parsed LLM response container."""

    def __init__(
        self,
        content: str,
        parsed_json: Optional[dict],
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ):
        self.content = content
        self.parsed_json = parsed_json
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model


class LLMClient:
    """
    Fully async client for Ollama's OpenAI-compatible API.

    Usage:
        client = LLMClient()
        response = await client.chat(system_prompt, user_prompt)
        if response.parsed_json:
            suggestions = response.parsed_json
    """

    def __init__(
        self,
        base_url: str = None,
        model: str = None,
        timeout: int = None,
    ):
        self.base_url = (base_url or LLM_URL).rstrip("/")
        self.model = model or LLM_MODEL
        self.timeout = timeout or LLM_TIMEOUT
        self._resolved_model: Optional[str] = None

    # ── Model resolution ───────────────────────────────────────

    async def _resolve_model(self) -> str:
        """Get the actual loaded model name from Ollama /models endpoint."""
        if self._resolved_model:
            return self._resolved_model
        try:
            status = await self.check_connection()
            if status.get("connected") and status.get("active_model"):
                self._resolved_model = status["active_model"]
                logger.info("Resolved Ollama model: %s", self._resolved_model)
                return self._resolved_model
        except Exception:
            pass
        return self.model

    # ── Request building ──────────────────────────────────────

    async def _build_request_body(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        force_json: bool,
    ) -> dict:
        model_name = await self._resolve_model()
        body: dict = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if force_json:
            body["response_format"] = {"type": "json_object"}
        return body

    # ── Response parsing ──────────────────────────────────────

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove DeepSeek-R1 <think>...</think> reasoning blocks."""
        import re
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    @staticmethod
    def _extract_json_object(text: str) -> Optional[dict]:
        """Find and parse the first complete JSON object via brace-counting."""
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
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        next_start = text.find('{', start + 1)
                        if next_start != -1 and next_start < i:
                            start = next_start
                            depth = 1
                            return None
        return None

    def _parse_response(self, raw: dict) -> LLMResponse:
        """Extract content and usage from an OpenAI-format response."""
        choice = raw.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = raw.get("usage", {})
        cleaned = self._strip_think_tags(content)
        parsed: Optional[dict] = None
        # 1. Direct JSON parse
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            pass
        # 2. Markdown fences
        if parsed is None and "```json" in cleaned:
            try:
                s = cleaned.index("```json") + 7
                e = cleaned.index("```", s)
                parsed = json.loads(cleaned[s:e].strip())
            except (json.JSONDecodeError, ValueError, IndexError):
                pass
        if parsed is None and "```" in cleaned:
            try:
                s = cleaned.index("```") + 3
                e = cleaned.index("```", s)
                parsed = json.loads(cleaned[s:e].strip())
            except (json.JSONDecodeError, ValueError, IndexError):
                pass
        # 3. Brace-counting extraction
        if parsed is None:
            parsed = self._extract_json_object(cleaned)
        # 4. Fallback on original content
        if parsed is None and content != cleaned:
            parsed = self._extract_json_object(content)
        if parsed is not None:
            logger.info("Successfully parsed JSON from LLM response")
        else:
            logger.warning(
                "Could not extract JSON from LLM response (%d chars)", len(content)
            )
        return LLMResponse(
            content=content,
            parsed_json=parsed,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=raw.get("model", self.model),
        )

    # ── Public API ─────────────────────────────────────────────

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        force_json: bool = True,
    ) -> LLMResponse:
        """
        Async chat call to Ollama.  Retries up to LLM_MAX_RETRIES.
        Never blocks the event loop — uses httpx.AsyncClient throughout.
        """
        temp = temperature if temperature is not None else DEFAULT_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        body = await self._build_request_body(
            system_prompt, user_prompt, temp, tokens, force_json
        )
        last_error: Optional[Exception] = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                logger.info("LLM call attempt %d/%d", attempt, LLM_MAX_RETRIES)
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(float(self.timeout))
                ) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=body,
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    raw = resp.json()
                result = self._parse_response(raw)
                if force_json and result.parsed_json is None:
                    logger.warning(
                        "Attempt %d: LLM returned non-JSON, retrying", attempt
                    )
                    last_error = ValueError("Non-JSON response from LLM")
                    continue
                return result
            except httpx.HTTPStatusError as e:
                logger.warning("Attempt %d HTTP error %s", attempt, e.response.status_code)
                last_error = e
                # 400 with json format → retry without response_format constraint
                if e.response.status_code == 400 and force_json:
                    logger.warning("Got 400 — retrying without response_format")
                    force_json = False
                    body = await self._build_request_body(
                        system_prompt, user_prompt, temp, tokens, False
                    )
            except Exception as e:
                logger.warning("Attempt %d failed: %s", attempt, e)
                last_error = e
            if attempt < LLM_MAX_RETRIES:
                import asyncio
                await asyncio.sleep(2 * attempt)
        raise ConnectionError(
            f"LLM call failed after {LLM_MAX_RETRIES} attempts: {last_error}"
        )

    async def check_connection(self) -> dict:
        """Check if Ollama is reachable. Returns status dict."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
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
