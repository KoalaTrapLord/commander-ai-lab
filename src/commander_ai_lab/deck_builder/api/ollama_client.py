"""
Ollama gpt-oss:20b client for the Commander AI Deck Builder.

Uses the OpenAI-compatible API exposed by Ollama at localhost:11434.
Provides 6 core functions:
  1. analyze_synergies  - Rank card candidates by synergy with commander
  2. suggest_cards      - Suggest cards for a specific category
  3. filter_color_identity - Validate cards against commander colors
  4. enforce_deck_ratios - Adjust card counts to hit ratio targets
  5. assemble_deck_json  - Produce final structured 99-card JSON
  6. chat               - Raw chat completion for ad-hoc queries
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# Ollama exposes an OpenAI-compatible endpoint
DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"


def _get_client(base_url: str = DEFAULT_BASE_URL) -> OpenAI:
    """Create an OpenAI client pointing at the local Ollama server."""
    return OpenAI(base_url=base_url, api_key="ollama")


def _extract_json(raw: str) -> Any:
    """Best-effort extraction of JSON from possibly messy LLM output.

    Handles:
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around JSON
    - Trailing commas before } or ]
    """
    text = raw.strip()

    # Strip markdown fences
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Remove trailing commas (common LLM error)
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find the first { or [ and last } or ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            substring = text[start : end + 1]
            substring = re.sub(r",\s*([}\]])", r"\1", substring)
            try:
                return json.loads(substring)
            except json.JSONDecodeError:
                continue

    raise json.JSONDecodeError("No valid JSON found in response", text, 0)


def _parse_card_list_fallback(raw: str) -> List[str]:
    """Last-resort parser for when the LLM ignores json_mode and returns
    a plain comma-separated (or newline-separated) list of card names.

    Strips common junk characters, splits on commas or newlines, and
    returns non-empty tokens.  Returns an empty list if nothing useful
    is found so the caller can decide how to handle it.
    """
    # Remove JSON brackets/quotes/backticks/numbering artefacts
    cleaned = re.sub(r"[\[\]{}\"`]", "", raw)
    # Remove leading bullet / numbering like "1." or "-"
    cleaned = re.sub(r"(?m)^\s*[-*\d]+[.)]\s*", "", cleaned)
    # Split on commas or newlines
    tokens = re.split(r"[,\n]+", cleaned)
    names = [t.strip().strip("'\"") for t in tokens if t.strip()]
    # Filter out tokens that look like prose (>6 words) or are empty
    names = [n for n in names if n and len(n.split()) <= 6]
    return names


def chat(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> str:
    """
    Send a chat completion request to Ollama.

    Returns the assistant's response as a string.
    """
    client = _get_client()
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


# ── 1. Analyze synergies ─────────────────────────────────────────────

def analyze_synergies(
    commander_name: str,
    commander_text: str,
    candidates: List[str],
    strategy_notes: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Rank candidate cards by synergy with the commander.
    Returns a list of dicts: [{"name": str, "score": int, "reason": str}, ...]
    Score is 1-10.
    """
    strategy = f"\nStrategy notes: {strategy_notes}" if strategy_notes else ""
    prompt = f"""You are a Magic: The Gathering Commander deck-building expert.

Commander: {commander_name}
Commander text: {commander_text}
{strategy}

Rate each of these cards on a 1-10 synergy scale with this commander.
Return ONLY a JSON array of objects with keys: "name", "score", "reason".

Cards to evaluate:
{json.dumps(candidates)}"""

    messages = [
        {"role": "system", "content": "You are an expert MTG Commander deck builder. Always respond with valid JSON only. No explanation text."},
        {"role": "user", "content": prompt},
    ]
    raw = chat(messages, json_mode=True)
    try:
        result = _extract_json(raw)
        if isinstance(result, dict) and "cards" in result:
            return result["cards"]
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        logger.error("Failed to parse synergy response: %s", raw[:500])
        return []


# ── 2. Suggest cards for a category ────────────────────────────────

def suggest_cards(
    commander_name: str,
    color_identity: List[str],
    category: str,
    count: int = 10,
    exclude: Optional[List[str]] = None,
    strategy_notes: Optional[str] = None,
    sim_context: str = "",
) -> List[str]:
    """
    Ask the model to suggest cards for a specific deck category.

    Parameters
    ----------
    sim_context:
        Optional natural-language insight string from get_sim_insights().
        When non-empty, appended to the prompt so the LLM can factor in
        statistically successful card traits from simulation data.

    Returns a list of card names.
    """
    exclude_str = f"\nDo NOT suggest these cards: {json.dumps(exclude)}" if exclude else ""
    strategy = f"\nStrategy notes: {strategy_notes}" if strategy_notes else ""
    sim_block = f"\n\n{sim_context}" if sim_context else ""

    prompt = f"""You are a Magic: The Gathering Commander deck-building expert.

Commander: {commander_name}
Color identity: {', '.join(color_identity)}
Category: {category}
{strategy}
{exclude_str}{sim_block}

Suggest exactly {count} cards for the {category} category that work well with this commander.
Only suggest cards that are legal in Commander and match the color identity.

Return ONLY a JSON array of card name strings, like: ["Card A", "Card B", ...]"""

    # One-shot example in the system prompt anchors small models to JSON output
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert MTG Commander deck builder. "
                "You MUST respond with ONLY a JSON array of strings — nothing else. "
                'Example of the required format: ["Sol Ring", "Arcane Signet", "Lightning Greaves"]'
            ),
        },
        {"role": "user", "content": prompt},
    ]
    raw = chat(messages, json_mode=True)
    logger.debug("suggest_cards raw response: %s", raw[:500])
    try:
        result = _extract_json(raw)
        if isinstance(result, dict):
            # Handle {"cards": [...]} or {"suggestions": [...]} etc.
            for key in ("cards", "suggestions", "card_names", "names"):
                if key in result and isinstance(result[key], list):
                    return [str(c) for c in result[key]]
            # If dict has a single list value, use it
            for v in result.values():
                if isinstance(v, list):
                    return [str(c) for c in v]
        if isinstance(result, list):
            return [str(c) for c in result]
        return []
    except json.JSONDecodeError:
        # JSON parse failed — attempt plain-text CSV recovery before giving up
        logger.warning(
            "suggest_cards: JSON parse failed, attempting CSV fallback. "
            "Raw (first 300 chars): %s",
            raw[:300],
        )
        recovered = _parse_card_list_fallback(raw)
        if recovered:
            logger.warning(
                "suggest_cards: CSV fallback recovered %d name(s) for category '%s'",
                len(recovered),
                category,
            )
            return recovered
        logger.error(
            "suggest_cards: CSV fallback also failed for category '%s'. "
            "Returning empty list. Full raw: %s",
            category,
            raw[:500],
        )
        return []


# ── 3. Filter by color identity ────────────────────────────────────

def filter_color_identity(
    card_names: List[str],
    commander_colors: List[str],
) -> List[str]:
    """
    Ask the model to filter out cards that violate color identity.
    Returns only the cards that are legal for the commander.
    """
    prompt = f"""You are a Magic: The Gathering rules expert.

Commander color identity: {', '.join(commander_colors)}

From this list, return ONLY the cards whose color identity is a subset of the commander's.
Remove any card that has mana symbols or color identity outside these colors.
Return a JSON array of valid card name strings.

Cards:
{json.dumps(card_names)}"""

    messages = [
        {"role": "system", "content": "You are an MTG rules expert. Respond with ONLY a JSON array. No other text."},
        {"role": "user", "content": prompt},
    ]
    raw = chat(messages, json_mode=True)
    try:
        result = _extract_json(raw)
        if isinstance(result, dict):
            for key in ("cards", "valid_cards", "legal_cards"):
                if key in result and isinstance(result[key], list):
                    return [str(c) for c in result[key]]
            for v in result.values():
                if isinstance(v, list):
                    return [str(c) for c in v]
        if isinstance(result, list):
            return [str(c) for c in result]
        return card_names  # fallback: return all
    except json.JSONDecodeError:
        return card_names


# ── 4. Enforce deck ratios ───────────────────────────────────────────

def enforce_deck_ratios(
    cards_by_category: Dict[str, List[str]],
    target_ratios: Dict[str, int],
    commander_name: str,
    sim_context: str = "",
) -> Dict[str, List[str]]:
    """
    Ask the model to trim/expand categories to hit target counts.

    Parameters
    ----------
    sim_context:
        Optional natural-language insight string from get_sim_insights().
        When non-empty, appended to the prompt so the LLM preferentially
        retains cards matching statistically high-value traits when trimming.

    Returns adjusted dict of category -> card names.
    """
    sim_block = f"\n\n{sim_context}" if sim_context else ""

    prompt = f"""You are a Magic: The Gathering Commander deck-building expert.

Commander: {commander_name}

Current cards by category:
{json.dumps(cards_by_category, indent=2)}

Target card counts per category:
{json.dumps(target_ratios, indent=2)}

Adjust each category to match the target count. Remove the weakest cards from
over-filled categories. For under-filled categories, suggest additional cards.
The total across all categories must be exactly 99.{sim_block}

Return a JSON object with the same category keys, each mapping to an array of card name strings."""

    messages = [
        {"role": "system", "content": "You are an expert MTG Commander deck builder. Respond with ONLY a JSON object. No other text."},
        {"role": "user", "content": prompt},
    ]
    raw = chat(messages, json_mode=True, max_tokens=8192)
    try:
        result = _extract_json(raw)
        if isinstance(result, dict):
            return {k: [str(c) for c in v] for k, v in result.items() if isinstance(v, list)}
        return cards_by_category
    except json.JSONDecodeError:
        logger.error("Failed to parse ratio response: %s", raw[:500])
        return cards_by_category


# ── 5. Assemble final deck JSON ─────────────────────────────────────────

def assemble_deck_json(
    commander_name: str,
    cards_by_category: Dict[str, List[str]],
) -> Dict[str, Any]:
    """
    Ask the model to produce the final structured deck JSON.
    Returns a dict matching the CommanderDeck schema.
    """
    prompt = f"""You are a Magic: The Gathering Commander deck-building expert.

Commander: {commander_name}

Final card selections by category:
{json.dumps(cards_by_category, indent=2)}

Produce the final deck as a JSON object with this structure:
{{
  "commander": {{"name": "...", "category": "commander"}},
  "cards": [
    {{"name": "...", "category": "...", "quantity": 1}},
    ...
  ]
}}

The "cards" array must have exactly 99 entries (one per card, quantity 1 each).
Use the category from the input grouping for each card.
Return ONLY the JSON object."""

    messages = [
        {"role": "system", "content": "You are an expert MTG Commander deck builder. Respond with ONLY a JSON object. No other text."},
        {"role": "user", "content": prompt},
    ]
    raw = chat(messages, json_mode=True, max_tokens=16384)
    try:
        return _extract_json(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse deck JSON: %s", raw[:500])
        return {}
