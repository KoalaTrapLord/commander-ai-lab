"""
Commander AI Lab — Anthropic Claude Structured Output Client
════════════════════════════════════════════════════════════
Uses the anthropic SDK to call Claude's messages endpoint
with structured JSON output enforced via system prompt.
Supports both sync and native async operation.
"""
import json
import logging
import re
from typing import Optional

import anthropic

logger = logging.getLogger("coach.anthropic")

# ── Anthropic Models ───────────────────────────────────────────
CLAUDE_OPUS = "claude-opus-4-0-20250514"
CLAUDE_SONNET = "claude-sonnet-4-5"
CLAUDE_HAIKU = "claude-haiku-4-5"


class AnthropicResponse:
    """Parsed response container from Anthropic API.

    Drop-in replacement for PerplexityResponse — same attribute shape
    so all existing call-sites work without changes.
    """

    def __init__(
        self,
        content: str,
        parsed_json: Optional[dict],
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
        citations: list[str] = None,
    ):
        self.content = content
        self.parsed_json = parsed_json
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model
        self.citations = citations or []  # Anthropic has no citations; kept for compat

    @property
    def ok(self) -> bool:
        return self.parsed_json is not None


class AnthropicClient:
    """
    Anthropic Claude API client.

    Drop-in replacement for PerplexityClient.

    Usage:
        client = AnthropicClient(api_key="sk-ant-...")
        resp = client.chat_structured(
            system_prompt="You are a deck builder.",
            user_prompt="Build a deck for...",
            json_schema=deck_schema,
            schema_name="DeckList",
        )
        if resp.ok:
            deck = resp.parsed_json
    """

    def __init__(
        self,
        api_key: str,
        model: str = CLAUDE_OPUS,
        timeout: int = 120,
        base_url: str = None,
    ):
        if not api_key:
            raise ValueError("Anthropic API key is required")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=float(timeout),
        )
        self._async_client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=float(timeout),
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
    ) -> AnthropicResponse:
        """
        Send a chat request expecting JSON output.

        The system_prompt should instruct the model to return JSON matching
        the expected schema. Claude Opus follows JSON instructions reliably.

        Args:
            system_prompt: System message (should instruct JSON output)
            user_prompt: User message
            json_schema: (optional) Kept for call-site compatibility; appended
                         as a schema hint in the system prompt when provided
            schema_name: (optional) Label used in the schema hint
            model: Override model
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Max output tokens

        Returns:
            AnthropicResponse with parsed_json extracted from model output
        """
        use_model = model or self.model
        effective_system = self._build_system(system_prompt, json_schema, schema_name)

        try:
            response = self._client.messages.create(
                model=use_model,
                system=effective_system,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._parse_response(response, use_model)
        except Exception as e:
            logger.error("[anthropic] API call failed: %s", e)
            raise

    def chat_plain(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AnthropicResponse:
        """
        Send a plain chat request without strict structured output.
        Used for substitution fallback queries.
        """
        use_model = model or self.model

        try:
            response = self._client.messages.create(
                model=use_model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._parse_response(response, use_model)
        except Exception as e:
            logger.error("[anthropic] Plain chat failed: %s", e)
            raise

    async def achat_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict = None,
        schema_name: str = "response",
        model: str = None,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> AnthropicResponse:
        """Native async structured chat — no run_in_executor needed."""
        use_model = model or self.model
        effective_system = self._build_system(system_prompt, json_schema, schema_name)

        try:
            response = await self._async_client.messages.create(
                model=use_model,
                system=effective_system,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._parse_response(response, use_model)
        except Exception as e:
            logger.error("[anthropic] Async structured chat failed: %s", e)
            raise

    async def achat_plain(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AnthropicResponse:
        """Native async plain chat."""
        use_model = model or self.model

        try:
            response = await self._async_client.messages.create(
                model=use_model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._parse_response(response, use_model)
        except Exception as e:
            logger.error("[anthropic] Async plain chat failed: %s", e)
            raise

    def check_status(self) -> dict:
        """Quick health check — try a minimal API call."""
        try:
            response = self._client.messages.create(
                model=self.model,
                system="Reply with the word OK.",
                messages=[{"role": "user", "content": "Status check."}],
                max_tokens=10,
            )
            content = response.content[0].text if response.content else ""
            return {
                "connected": True,
                "model": self.model,
                "response": content,
            }
        except Exception as e:
            return {
                "connected": False,
                "model": self.model,
                "error": str(e),
            }

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _build_system(system_prompt: str, json_schema: dict, schema_name: str) -> str:
        """Append JSON schema hint to system prompt when a schema is provided."""
        if not json_schema:
            return system_prompt
        schema_str = json.dumps(json_schema, indent=2)
        return (
            f"{system_prompt}\n\n"
            f"You MUST respond with valid JSON only — no markdown fences, no prose.\n"
            f"The response must conform to the following JSON schema ({schema_name}):\n"
            f"{schema_str}"
        )

    def _parse_response(self, response, use_model: str) -> AnthropicResponse:
        """Extract content and attempt JSON parsing from an Anthropic response."""
        content = ""
        if response.content:
            content = response.content[0].text or ""

        usage = response.usage
        prompt_tokens = usage.input_tokens if usage else 0
        completion_tokens = usage.output_tokens if usage else 0

        parsed = None
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = self._extract_json(content)

        logger.info(
            "[anthropic] model=%s tokens=(%d in, %d out) parsed=%s",
            use_model,
            prompt_tokens,
            completion_tokens,
            "yes" if parsed else "no",
        )

        return AnthropicResponse(
            content=content,
            parsed_json=parsed,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=use_model,
            citations=[],
        )

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Best-effort JSON extraction from possibly noisy text."""
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, TypeError):
            pass

        # Markdown fences
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
                        return json.loads(text[start:i + 1])
                    except (json.JSONDecodeError, TypeError):
                        return None

        # Truncated JSON — attempt repair
        return AnthropicClient._repair_truncated_json(text[start:])

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[dict]:
        """
        Attempt to repair truncated JSON from max_tokens cutoff.
        Strategy: find the last complete nested object, then close
        all open brackets/braces.
        """
        logger.info("Attempting truncated JSON repair (%d chars)...", len(text))
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
                    last_good = i

        if last_good == -1:
            return None

        truncated = text[:last_good + 1]
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
