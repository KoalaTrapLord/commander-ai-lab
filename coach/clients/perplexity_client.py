"""
Commander AI Lab — Perplexity Sonar Structured Output Client
═════════════════════════════════════════════════════════════
Uses the openai SDK to call Perplexity's chat/completions endpoint
with response_format: json_schema for guaranteed structured output.

Supports both sonar (fast, cheap) and sonar-pro (deep, thorough).
"""

import json
import logging
import asyncio
from typing import Optional

from openai import OpenAI

logger = logging.getLogger("coach.pplx")

# ── Perplexity Models ─────────────────────────────────────────
SONAR = "sonar"
SONAR_PRO = "sonar-pro"
SONAR_DEEP_RESEARCH = "sonar-deep-research"


class PerplexityResponse:
    """Parsed response container from Perplexity API."""
    def __init__(self, content: str, parsed_json: Optional[dict],
                 prompt_tokens: int, completion_tokens: int,
                 model: str, citations: list[str] = None):
        self.content = content
        self.parsed_json = parsed_json
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model
        self.citations = citations or []

    @property
    def ok(self) -> bool:
        return self.parsed_json is not None


class PerplexityClient:
    """
    Perplexity Sonar API client using the openai SDK.

    Usage:
        client = PerplexityClient(api_key="pplx-...")
        resp = client.chat_structured(
            system_prompt="You are a deck builder.",
            user_prompt="Build a deck for...",
            json_schema=deck_schema,
            schema_name="DeckList",
        )
        if resp.ok:
            deck = resp.parsed_json
    """

    def __init__(self, api_key: str, model: str = SONAR,
                                     timeout: int = 120, base_url: str = None):
        if not api_key and not base_url:
            raise ValueError("Perplexity API key is required (or provide base_url for local)")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or "https://api.perplexity.ai",
            timeout=timeout,
        )

    def chat_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict = None,
        schema_name: str = "response",
        model: str = None,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> PerplexityResponse:
        """
        Send a chat request with JSON output.

        Uses        Sonar models do not support the json_schema response_format.
        Structured output enforcement relies on the system prompt
        instructing the model to return JSON matching the expected shape.

        Args:
            system_prompt: System message (should instruct JSON output)
            user_prompt: User message
            json_schema: (ignored) Kept for call-site compatibility
            schema_name: (ignored) Kept for call-site compatibility
            model: Override model (sonar, sonar-pro)
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Max output tokens

        Returns:
            PerplexityResponse with parsed_json from the model's output
        """
        use_model = model or self.model

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._client.chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                 )

            choice = response.choices[0]
            content = choice.message.content or ""
            usage = response.usage

            # Parse the structured JSON
            parsed = None
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to parse structured response: %s", e)
                # Fallback: try extracting JSON object
                parsed = self._extract_json(content)

            # Extract citations if available
            citations = []
            if hasattr(response, 'citations') and response.citations:
                citations = response.citations

            logger.info(
                "[pplx] model=%s tokens=(%d prompt, %d completion) parsed=%s",
                use_model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
                "yes" if parsed else "no",
            )

            return PerplexityResponse(
                content=content,
                parsed_json=parsed,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=use_model,
                citations=citations,
            )

        except Exception as e:
            logger.error("[pplx] API call failed: %s", e)
            raise

    def chat_plain(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> PerplexityResponse:
        """
        Send a plain chat request without structured output.
        Used for substitution fallback queries where schema
        compliance is less critical.
        """
        use_model = model or self.model

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._client.chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            choice = response.choices[0]
            content = choice.message.content or ""
            usage = response.usage

            # Try to parse as JSON anyway
            parsed = self._extract_json(content)

            citations = []
            if hasattr(response, 'citations') and response.citations:
                citations = response.citations

            return PerplexityResponse(
                content=content,
                parsed_json=parsed,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=use_model,
                citations=citations,
            )

        except Exception as e:
            logger.error("[pplx] Plain chat failed: %s", e)
            raise

    async def achat_structured(self, *args, **kwargs) -> PerplexityResponse:
        """Async wrapper — runs structured chat in thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.chat_structured(*args, **kwargs)
        )

    async def achat_plain(self, *args, **kwargs) -> PerplexityResponse:
        """Async wrapper — runs plain chat in thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.chat_plain(*args, **kwargs)
        )

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Best-effort JSON extraction from possibly noisy text."""
        # Direct parse
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, TypeError):
            pass

        # Markdown fences
        import re
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except (json.JSONDecodeError, TypeError):
                pass

        # Brace counting
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
            if ch == '\\' and in_string:
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
                    try:
                        return json.loads(text[start:i+1])
                    except (json.JSONDecodeError, TypeError):
                        return None

        # If we get here, JSON was truncated (depth > 0). Try to repair.
        return PerplexityClient._repair_truncated_json(text[start:])

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[dict]:
        """
        Attempt to repair truncated JSON from max_tokens cutoff.
        Strategy: find the last complete array element in "cards",
        then close all open brackets/braces.
        """
        logger.info("Attempting truncated JSON repair (%d chars)...", len(text))

        # Find the last complete card object (ends with }) in the cards array
        # Walk backwards to find the last closing brace that ends a valid card
        last_good = -1
        depth = 0
        in_string = False
        escape_next = False

        for i in range(len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
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
                if depth >= 1:
                    # This closes a nested object (like a card) — mark as potential cutoff
                    last_good = i

        if last_good == -1:
            return None

        # Take text up to the last complete nested object
        truncated = text[:last_good + 1]

        # Now figure out what we need to close.
        # Re-scan to get the closing sequence.
        close_depth = 0
        in_arr = 0
        in_str = False
        esc = False
        for ch in truncated:
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                close_depth += 1
            elif ch == '}':
                close_depth -= 1
            elif ch == '[':
                in_arr += 1
            elif ch == ']':
                in_arr -= 1

        # Build closing sequence
        suffix = ']' * in_arr + '}' * close_depth
        repaired = truncated + suffix

        try:
            result = json.loads(repaired)
            card_count = len(result.get('cards', []))
            logger.info("JSON repair succeeded: recovered %d cards", card_count)
            return result
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("JSON repair failed: %s", e)
            return None

    def check_status(self) -> dict:
        """Quick health check — try a minimal API call."""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Reply with the word OK."},
                    {"role": "user", "content": "Status check."},
                ],
                max_tokens=10,
            )
            return {
                "connected": True,
                "model": self.model,
                "response": response.choices[0].message.content,
            }
        except Exception as e:
            return {
                "connected": False,
                "model": self.model,
                "error": str(e),
            }
