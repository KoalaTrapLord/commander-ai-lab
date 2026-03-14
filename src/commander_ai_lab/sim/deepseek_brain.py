"""
Commander AI Lab — DeepSeek LLM Brain for AI Opponent
======================================================
Integrates a local LLM (DeepSeek-R1 via LM Studio / Ollama) as the
decision-making "brain" for the AI opponent in the headless simulator.

The LLM receives a structured game-state snapshot and returns a JSON
action describing what to do this turn (play land, cast spell, attack,
hold/pass, use removal, use board wipe, cast ramp, cast commander).

Supports:
  - LM Studio (OpenAI-compatible API) — default at http://192.168.0.122:1234
  - Ollama (OpenAI-compatible mode) — http://localhost:11434
  - Any OpenAI-compatible endpoint

Performance features:
  - Configurable timeout with fallback to heuristic
  - Response caching for identical game states
  - Structured JSON output with validation
  - Decision logging (JSONL) for future RL training data
    Each JSONL entry includes game_result (winner_seat, winner_name,
    player_lives, reward) once flush_log() is called with a GameResult.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("deepseek_brain")


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

@dataclass
class DeepSeekConfig:
    """Configuration for the DeepSeek LLM brain."""

    # API endpoint (OpenAI-compatible)
    api_base: str = "http://192.168.0.122:1234"
    model: str = "deepseek-r1-distill-qwen-8b"  # LM Studio model name

    # Generation parameters
    temperature: float = 0.3       # Low for more deterministic play
    max_tokens: int = 2048         # R1 needs room for <think> reasoning + JSON response
    top_p: float = 0.9

    # Timeouts
    request_timeout: float = 10.0  # seconds per LLM call
    fallback_on_timeout: bool = True  # use heuristic if LLM times out

    # Caching
    cache_enabled: bool = True
    cache_max_size: int = 256      # LRU cache entries

    # Logging
    log_decisions: bool = True
    log_dir: str = ""              # Set at runtime

    # Retry
    max_retries: int = 1           # Retry once on parse failure


# ══════════════════════════════════════════════════════════════
# Game-State Schema  (Step 2) — Full Intelligence Snapshot
# ══════════════════════════════════════════════════════════════

# Basic land → color mapping for mana color tracking
_LAND_COLOR_MAP = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
}

# Known combo/synergy patterns detected from oracle text
_COMBO_PATTERNS = [
    ("infinite", "Infinite combo piece"),
    ("you win the game", "Alternate win condition"),
    ("extra turn", "Extra turn effect"),
    ("whenever .* enters the battlefield", "ETB synergy payoff"),
    ("whenever .* dies", "Death trigger payoff"),
    ("create .* token", "Token generator"),
    ("double", "Doubling effect"),
    ("each opponent", "Multiplayer damage / drain"),
    ("draw .* cards?", "Card draw engine"),
    ("search your library", "Tutor effect"),
    ("return .* from .* graveyard", "Recursion / reanimation"),
    ("can't be countered", "Uncounterable threat"),
    ("hexproof|shroud|indestructible|ward", "Protected threat"),
]


def build_game_state_snapshot(
    sim_state,          # SimState
    player_index: int,  # Which player is the AI (0 or 1)
    turn: int,
    deck_context: dict | None = None,  # Full deck intelligence
) -> dict:
    """
    Build a comprehensive game-state dict for the LLM with full intelligence.

    deck_context (optional):
        commander_name, commander_zone, color_identity, archetype,
        full_decklist, combo_pieces, win_rate_history, deck_size
    """
    me = sim_state.players[player_index]
    opp = sim_state.players[1 - player_index]
    ctx = deck_context or {}

    # ── Mana by Color (Enhancement #8) ────────────────────────────
    mana_total = 0
    mana_by_color = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    my_bf = sim_state.get_battlefield(player_index)
    opp_bf = sim_state.get_battlefield(1 - player_index)
    for c in my_bf:
        if not c.tapped and c.is_land():
            mana_total += 1
            land_name = c.name.lower().strip()
            if land_name in _LAND_COLOR_MAP:
                mana_by_color[_LAND_COLOR_MAP[land_name]] += 1
            elif c.oracle_text:
                oracle_lower = c.oracle_text.lower()
                if "any color" in oracle_lower:
                    for clr in "WUBRG":
                        mana_by_color[clr] += 1
                else:
                    for clr, sym in [("W", "{w}"), ("U", "{u}"), ("B", "{b}"),
                                     ("R", "{r}"), ("G", "{g}")]:
                        if sym in oracle_lower or f"add {clr.lower()}" in oracle_lower:
                            mana_by_color[clr] += 1
                    if not any(mana_by_color[k] for k in "WUBRG"):
                        mana_by_color["C"] += 1
            else:
                mana_by_color["C"] += 1

    mana_colors = {k: v for k, v in mana_by_color.items() if v > 0}

    # ── My Hand — Full Oracle Text (Enhancement #5) ────────────────
    my_hand = []
    for c in me.hand:
        card_info = {
            "name": c.name,
            "type": _short_type(c.type_line),
            "cmc": c.cmc or 0,
        }
        if c.pt:
            card_info["pt"] = c.pt
        if c.keywords:
            card_info["keywords"] = c.keywords[:5]
        roles = []
        if c.is_removal:
            roles.append("removal")
        if c.is_board_wipe:
            roles.append("board_wipe")
        if c.is_ramp:
            roles.append("ramp")
        if c.is_commander:
            roles.append("commander")
        if roles:
            card_info["roles"] = roles
        if c.oracle_text:
            card_info["oracle"] = c.oracle_text
        card_info["castable"] = (c.cmc or 0) <= mana_total and not c.is_land()
        my_hand.append(card_info)

    # ── My Board ──
    my_board = []
    for c in my_bf:
        if c.is_land():
            continue
        entry = {"name": c.name, "type": _short_type(c.type_line)}
        if c.pt:
            entry["pt"] = c.pt
        if c.tapped:
            entry["tapped"] = True
        if c.keywords:
            entry["keywords"] = c.keywords[:5]
        if c.is_commander:
            entry["is_commander"] = True
        my_board.append(entry)

    # ── Opponent's Board — with Threat Assessment (Enhancement #9) ──
    opp_board = []
    opp_total_power = 0
    opp_evasion_count = 0
    opp_protected_count = 0
    for c in opp_bf:
        if c.is_land():
            continue
        entry = {"name": c.name, "type": _short_type(c.type_line)}
        if c.pt:
            entry["pt"] = c.pt
            opp_total_power += c.get_power()
        if c.tapped:
            entry["tapped"] = True
        if c.keywords:
            entry["keywords"] = c.keywords[:5]
            kw_lower = [k.lower() for k in c.keywords]
            if any(k in kw_lower for k in ["flying", "trample", "menace", "unblockable", "shadow"]):
                opp_evasion_count += 1
            if any(k in kw_lower for k in ["hexproof", "shroud", "indestructible", "ward"]):
                opp_protected_count += 1
        opp_board.append(entry)

    if opp_total_power >= me.life:
        threat_level = "LETHAL"
    elif opp_total_power >= me.life * 0.5:
        threat_level = "HIGH"
    elif len(opp_board) >= 4 or opp_total_power >= 10:
        threat_level = "MODERATE"
    elif opp_board:
        threat_level = "LOW"
    else:
        threat_level = "NONE"

    # ── Graveyard Contents (Enhancement #6) ──────────────────────
    my_gy = [{"name": c.name, "type": _short_type(c.type_line)} for c in me.graveyard[:15]]
    opp_gy = [{"name": c.name, "type": _short_type(c.type_line)} for c in opp.graveyard[:10]]

    # ── Draw Tracking (Enhancement #7) ─────────────────────────
    total_deck_size = ctx.get("deck_size", 100)
    cards_seen = len(me.hand) + len(me.graveyard) + len(my_bf)
    cards_remaining = len(me.library)
    pct_drawn = round(cards_seen / max(total_deck_size, 1) * 100)

    key_cards_in_library = []
    if ctx.get("key_cards"):
        library_names = {c.name.lower() for c in me.library}
        for kc in ctx["key_cards"]:
            if kc.lower() in library_names:
                key_cards_in_library.append(kc)

    # ── Build the snapshot ────────────────────────────────────
    snapshot = {
        "turn": turn + 1,
        "my_life": me.life,
        "opp_life": opp.life,
        "my_mana_total": mana_total,
        "my_mana_by_color": mana_colors,
        "my_hand": my_hand,
        "my_board": my_board,
        "opp_board": opp_board,
        "opp_threat": {
            "level": threat_level,
            "total_power": opp_total_power,
            "evasive_creatures": opp_evasion_count,
            "protected_creatures": opp_protected_count,
        },
        "my_graveyard": my_gy,
        "opp_graveyard": opp_gy,
        "my_library_count": cards_remaining,
        "opp_library_count": len(opp.library),
        "deck_drawn_pct": pct_drawn,
    }

    if ctx.get("commander_name"):
        cmd_name_lower = ctx["commander_name"].lower()
        cmd_zone = "library"
        for c in me.hand:
            if c.name.lower() == cmd_name_lower:
                cmd_zone = "hand"
                break
        for c in my_bf:
            if c.name.lower() == cmd_name_lower:
                cmd_zone = "battlefield"
                break
        for c in me.graveyard:
            if c.name.lower() == cmd_name_lower:
                cmd_zone = "graveyard"
                break
        snapshot["commander"] = {
            "name": ctx["commander_name"],
            "zone": cmd_zone,
            "color_identity": ctx.get("color_identity", []),
        }

    if ctx.get("deck_summary"):
        snapshot["deck_summary"] = ctx["deck_summary"]
    if ctx.get("combo_pieces"):
        snapshot["combo_pieces"] = ctx["combo_pieces"]
    if key_cards_in_library:
        snapshot["key_cards_in_library"] = key_cards_in_library[:10]
    if ctx.get("win_rate") is not None:
        snapshot["historical_win_rate"] = ctx["win_rate"]

    return snapshot


def _short_type(type_line: str) -> str:
    """Shorten type_line for token efficiency."""
    if not type_line:
        return "?"
    tl = type_line.lower()
    if "creature" in tl:
        return "creature"
    if "instant" in tl:
        return "instant"
    if "sorcery" in tl:
        return "sorcery"
    if "artifact" in tl:
        return "artifact"
    if "enchantment" in tl:
        return "enchantment"
    if "planeswalker" in tl:
        return "planeswalker"
    if "land" in tl:
        return "land"
    return type_line[:20]


def build_deck_context(
    full_deck: list,
    commander_name: str = "",
    color_identity: list[str] | None = None,
    archetype: str = "midrange",
    win_rate: float | None = None,
) -> dict:
    """
    Build a deck intelligence context dict from the full decklist.
    Called once before a game starts, then passed to build_game_state_snapshot each turn.
    """
    ctx: dict[str, Any] = {
        "commander_name": commander_name,
        "color_identity": color_identity or [],
        "archetype": archetype,
        "deck_size": len(full_deck),
    }

    if win_rate is not None:
        ctx["win_rate"] = win_rate

    type_counts: dict[str, int] = {}
    roles: dict[str, list[str]] = {"removal": [], "ramp": [], "board_wipe": [], "draw": []}
    key_cards: list[str] = []
    combo_pieces: list[dict] = []
    total_cmc = 0
    non_land_count = 0

    for card in full_deck:
        ctype = _short_type(card.type_line) if card.type_line else "?"
        type_counts[ctype] = type_counts.get(ctype, 0) + 1
        if not card.is_land():
            total_cmc += card.cmc or 0
            non_land_count += 1
        if card.is_removal:
            roles["removal"].append(card.name)
        if card.is_board_wipe:
            roles["board_wipe"].append(card.name)
        if card.is_ramp:
            roles["ramp"].append(card.name)
        oracle = (card.oracle_text or "").lower()
        if re.search(r"draw .* cards?", oracle):
            roles["draw"].append(card.name)
        for pattern, label in _COMBO_PATTERNS:
            if re.search(pattern, oracle):
                combo_pieces.append({"name": card.name, "role": label})
                key_cards.append(card.name)
                break

    avg_cmc = round(total_cmc / max(non_land_count, 1), 1)
    ctx["deck_summary"] = {
        "card_types": type_counts,
        "avg_cmc": avg_cmc,
        "removal_count": len(roles["removal"]),
        "ramp_count": len(roles["ramp"]),
        "board_wipe_count": len(roles["board_wipe"]),
        "draw_count": len(roles["draw"]),
        "archetype": archetype,
    }
    ctx["combo_pieces"] = combo_pieces[:15]
    ctx["key_cards"] = list(set(key_cards))[:15]
    return ctx


# ══════════════════════════════════════════════════════════════
# Action Schema  (Step 3)
# ══════════════════════════════════════════════════════════════

VALID_ACTIONS = [
    "play_land",
    "cast_creature",
    "cast_removal",
    "cast_board_wipe",
    "cast_ramp",
    "cast_spell",
    "attack_all",
    "attack_safe",
    "hold",
]

ACTION_SCHEMA = {
    "action": "one of: " + ", ".join(VALID_ACTIONS),
    "target_card": "(optional) name of card to cast or target",
    "reasoning": "(brief) why this action",
}


# ══════════════════════════════════════════════════════════════
# System / User Prompts  (Step 3)
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are an expert Magic: The Gathering Commander player.
Your goal is to WIN by reducing your opponent's life to 0.

GAME RULES:
- 1 land drop per turn. Cast spells up to available mana.
- Creatures have summoning sickness (can't attack the turn they enter unless they have haste).
- Commander can be recast from command zone with +2 mana tax each time.

RESPONSE FORMAT — respond with ONLY this JSON, nothing else:
{"action": "<action_name>", "target_card": "<card name>", "reasoning": "<1 sentence>"}

VALID ACTIONS:
- play_land — play a land from hand (always do this first)
- cast_creature — cast a creature spell
- cast_removal — use removal on opponent's best threat
- cast_board_wipe — wipe the board (when behind on creatures)
- cast_ramp — cast mana ramp to accelerate
- cast_spell — cast any other spell (enchantment, artifact, etc.)
- attack_all — attack with all untapped creatures
- attack_safe — attack only with evasive/large creatures (flying, trample, power>=4)
- hold — pass/save mana (bluff or save for next turn)

GAME STATE DATA YOU RECEIVE:
You get a JSON snapshot each turn. Key fields:
- my_hand: cards in hand with name, type, cmc, oracle text, roles (removal/ramp/board_wipe/commander), and "castable" flag
- my_board / opp_board: non-land permanents on each side
- my_mana_total / my_mana_by_color: available mana and color breakdown (W/U/B/R/G/C)
- opp_threat: {level: NONE/LOW/MODERATE/HIGH/LETHAL, total_power, evasive_creatures, protected_creatures}
- my_graveyard / opp_graveyard: cards in graveyards (check for recursion targets)
- deck_drawn_pct: percentage of deck you've drawn
- commander: {name, zone (hand/battlefield/graveyard/library), color_identity}
- deck_summary: {card_types, avg_cmc, removal_count, ramp_count, board_wipe_count, draw_count, archetype}
- combo_pieces: detected synergy/combo cards in the deck
- key_cards_in_library: important cards still in your library
- historical_win_rate: how this deck has performed in past games

ARCHETYPE STRATEGIES:

AGGRO:
- Curve out fast: cast creatures turns 1-3, attack relentlessly from turn 3+
- Only use removal on blockers that stop your damage. Don't hold back.
- Prioritize attack_all unless opponent has deathtouch blockers
- If board stalls, use evasion (flying/trample) to push through

MIDRANGE:
- Ramp turns 1-3, then play value creatures and removal
- Balance threats and answers. Remove opponent's best creature before attacking.
- Use board wipe when behind by 3+ creatures. Hold if ahead and no good plays.
- Cast commander when you have mana to protect or benefit from it

CONTROL:
- Prioritize ramp and draw early. Hold removal for real threats.
- Don't overcommit creatures — play 1-2 threats and protect them
- Board wipe aggressively when opponent goes wide. Hold mana for instant-speed removal.
- Win through card advantage and inevitability, not early aggression

COMBO:
- Prioritize draw spells and tutors to find combo pieces
- Play ramp to reach combo mana threshold ASAP
- Protect combo pieces — don't expose them to removal unnecessarily
- If combo pieces are in key_cards_in_library, prioritize draw effects
- Use attack_safe or hold to buy time; don't race with creatures

DECISION PRIORITIES:
1. If you have lethal (your total power >= opp_life and opp has few blockers) → attack_all
2. If opp_threat.level is LETHAL → cast removal or board wipe immediately
3. If turn <= 3 and you have ramp in hand → cast_ramp
4. If your commander is in hand and castable, and it enables your strategy → cast_creature with commander
5. Follow your archetype strategy above
6. Always play a land first if you have one
7. Cast the highest-impact spell you can afford (check castable flag)
8. When nothing impactful is castable, hold to save mana for future turns"""

USER_PROMPT_TEMPLATE = """Current game state:
{game_state_json}

What is your action? Respond with ONLY valid JSON."""


# ══════════════════════════════════════════════════════════════
# LLM Client
# ══════════════════════════════════════════════════════════════

class DeepSeekBrain:
    """
    LLM-powered decision engine for the AI opponent.

    Sends game state to a local DeepSeek/GPT-OSS model and parses the action response.
    Falls back to heuristic on timeout/error.

    Decision log entries include game outcome once flush_log() is called
    with a GameResult, enabling downstream RL weight learning.
    """

    def __init__(self, config: DeepSeekConfig | None = None):
        self.config = config or DeepSeekConfig()
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._decision_log: list[dict] = []
        self._current_game_id: str = self._new_game_id()
        self._ai_player_index: int | None = None  # set by caller if known
        self._total_calls = 0
        self._total_fallbacks = 0
        self._total_cache_hits = 0
        self._total_latency_ms = 0.0
        self._connected = False
        self._log_file = None

    @staticmethod
    def _new_game_id() -> str:
        """Generate a short unique game ID for grouping decisions in the log."""
        return hashlib.md5(str(time.time()).encode()).hexdigest()[:12]

    def new_game(self, ai_player_index: int | None = None) -> None:
        """
        Signal the start of a new game.

        Call this before each game so that log entries are grouped by game_id
        and the ai_player_index is recorded for reward calculation.
        """
        self._current_game_id = self._new_game_id()
        self._ai_player_index = ai_player_index

    def check_connection(self) -> bool:
        """Test if the LLM endpoint is reachable."""
        try:
            url = self.config.api_base.rstrip("/") + "/v1/models"
            req = Request(url, method="GET")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                self._connected = True
                models = data.get("data", [])
                if models:
                    model_id = models[0].get("id", self.config.model)
                    if model_id:
                        self.config.model = model_id
                        logger.info("Auto-detected model: %s", model_id)
                logger.info("DeepSeek brain connected to %s", self.config.api_base)
                return True
        except Exception as e:
            logger.warning("DeepSeek brain connection failed: %s", e)
            self._connected = False
            return False

    def choose_action(
        self,
        sim_state,
        player_index: int,
        turn: int,
        available_mana: int | None = None,
        deck_context: dict | None = None,
    ) -> dict:
        """
        Choose an action for the AI player.

        Returns:
            {
                "action": str,
                "target_card": str,
                "reasoning": str,
                "source": "deepseek" | "heuristic" | "cache",
                "latency_ms": float,
            }
        """
        self._total_calls += 1
        t_start = time.time()

        snapshot = build_game_state_snapshot(sim_state, player_index, turn, deck_context=deck_context)
        if available_mana is not None:
            snapshot["my_mana_available"] = available_mana

        if self.config.cache_enabled:
            cache_key = self._cache_key(snapshot)
            if cache_key in self._cache:
                self._total_cache_hits += 1
                cached = self._cache[cache_key].copy()
                cached["source"] = "cache"
                cached["latency_ms"] = round((time.time() - t_start) * 1000, 1)
                return cached

        if not self._connected:
            return self._fallback_action(snapshot, t_start, "not_connected")

        try:
            result = self._call_llm(snapshot)
            result["source"] = "deepseek"
            result["latency_ms"] = round((time.time() - t_start) * 1000, 1)

            if self.config.cache_enabled:
                self._put_cache(cache_key, result)

            if self.config.log_decisions:
                self._log_decision(snapshot, result, player_index)

            self._total_latency_ms += result["latency_ms"]
            return result

        except Exception as e:
            logger.warning("DeepSeek call failed (turn %d): %s", turn + 1, e)
            if self.config.fallback_on_timeout:
                return self._fallback_action(snapshot, t_start, str(e))
            raise

    def _call_llm(self, snapshot: dict) -> dict:
        """Send game state to LLM and parse response."""
        game_state_json = json.dumps(snapshot, indent=2)
        user_prompt = USER_PROMPT_TEMPLATE.format(game_state_json=game_state_json)

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
            "stream": False,
        }

        url = self.config.api_base.rstrip("/") + "/v1/chat/completions"
        req_data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=req_data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urlopen(req, timeout=self.config.request_timeout) as resp:
            resp_data = json.loads(resp.read())

        choices = resp_data.get("choices", [])
        if not choices:
            raise ValueError("Empty response from LLM")

        raw_text = choices[0].get("message", {}).get("content", "")
        return self._parse_action(raw_text)

    def _parse_action(self, raw_text: str) -> dict:
        """
        Parse the LLM's response into a validated action dict.
        Handles common LLM quirks (markdown fences, extra text, etc.)
        """
        text = raw_text.strip()
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        text = re.sub(r'<think>.*', '', text, flags=re.DOTALL).strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            for action in VALID_ACTIONS:
                if action in raw_text.lower():
                    return {
                        "action": action,
                        "target_card": "",
                        "reasoning": "Parsed from freeform response",
                    }
            raise ValueError(f"Could not parse LLM response as JSON: {raw_text[:200]}")

        action = parsed.get("action", "hold")
        if action not in VALID_ACTIONS:
            for valid in VALID_ACTIONS:
                if valid in action.lower() or action.lower() in valid:
                    action = valid
                    break
            else:
                action = "hold"

        return {
            "action": action,
            "target_card": parsed.get("target_card", parsed.get("card", "")),
            "reasoning": parsed.get("reasoning", parsed.get("reason", "")),
        }

    def _fallback_action(self, snapshot: dict, t_start: float, reason: str) -> dict:
        """Generate a heuristic action when LLM is unavailable."""
        self._total_fallbacks += 1

        hand = snapshot.get("my_hand", [])
        mana = snapshot.get("my_mana_available", 0)
        my_board = snapshot.get("my_board", [])
        opp_board = snapshot.get("opp_board", [])
        turn = snapshot.get("turn", 1)

        action = "hold"
        target = ""
        reasoning = f"Fallback ({reason})"

        lands_in_hand = [c for c in hand if c.get("type") == "land"]
        if lands_in_hand:
            action = "play_land"
            target = lands_in_hand[0]["name"]
            reasoning = "Play land first"
        elif turn <= 4:
            ramp_cards = [c for c in hand if c.get("role") == "ramp" and c.get("cmc", 99) <= mana]
            if ramp_cards:
                ramp_cards.sort(key=lambda c: c.get("cmc", 0))
                action = "cast_ramp"
                target = ramp_cards[0]["name"]
                reasoning = "Early ramp"
            else:
                creatures = [c for c in hand if c.get("type") == "creature" and c.get("cmc", 99) <= mana]
                if creatures:
                    creatures.sort(key=lambda c: c.get("cmc", 0))
                    action = "cast_creature"
                    target = creatures[0]["name"]
                    reasoning = "Cheap creature development"
        elif len(opp_board) >= 3 and len(my_board) <= 1:
            wipes = [c for c in hand if c.get("role") == "board_wipe" and c.get("cmc", 99) <= mana]
            if wipes:
                action = "cast_board_wipe"
                target = wipes[0]["name"]
                reasoning = "Opponent has board advantage, wiping"
        elif opp_board:
            removal = [c for c in hand if c.get("role") == "removal" and c.get("cmc", 99) <= mana]
            if removal:
                action = "cast_removal"
                target = removal[0]["name"]
                reasoning = "Remove opponent threat"
        if action == "hold":
            castable = [c for c in hand if c.get("type") == "creature" and c.get("cmc", 99) <= mana]
            if castable:
                castable.sort(key=lambda c: -int(c.get("pt", "0/0").split("/")[0]) if c.get("pt") else 0)
                action = "cast_creature"
                target = castable[0]["name"]
                reasoning = "Play threat"
        if action == "hold" and my_board:
            creatures_on_board = [c for c in my_board if c.get("type") == "creature" and not c.get("tapped")]
            if creatures_on_board:
                action = "attack_all"
                reasoning = "Attack with available creatures"

        result = {
            "action": action,
            "target_card": target,
            "reasoning": reasoning,
            "source": "heuristic",
            "latency_ms": round((time.time() - t_start) * 1000, 1),
        }

        if self.config.log_decisions:
            self._log_decision(snapshot, result)

        return result

    # ── Cache helpers ──

    def _cache_key(self, snapshot: dict) -> str:
        key_data = json.dumps(snapshot, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()

    def _put_cache(self, key: str, value: dict):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        while len(self._cache) > self.config.cache_max_size:
            self._cache.popitem(last=False)

    # ── Decision logging ──

    def _log_decision(self, snapshot: dict, result: dict, player_index: int | None = None) -> None:
        """
        Append a decision entry to the in-memory log.

        The entry is tagged with game_id so flush_log() can backfill
        game_result fields once the game is complete.
        """
        entry = {
            "timestamp": time.time(),
            "game_id": self._current_game_id,
            "player_index": player_index if player_index is not None else self._ai_player_index,
            "game_state": snapshot,
            "decision": {
                "action": result.get("action"),
                "target_card": result.get("target_card"),
                "reasoning": result.get("reasoning"),
                "source": result.get("source"),
                "latency_ms": result.get("latency_ms"),
            },
            # game_result is None until flush_log() is called with a GameResult
            "game_result": None,
        }
        self._decision_log.append(entry)

    def flush_log(
        self,
        filepath: str | None = None,
        game_result=None,  # Optional[GameResult] from engine.py
    ) -> str | None:
        """
        Write accumulated decision log to a JSONL file.

        Parameters
        ----------
        filepath : str, optional
            Destination file path.  Defaults to logs/decisions/<timestamp>.jsonl
            next to the package root.
        game_result : GameResult, optional
            Result from GameEngine.run() / run_n().  When provided, every
            buffered entry is backfilled with:

            ``game_result`` dict containing:
              - ``winner_seat``  : int   — seat index of the winner
              - ``winner_name``  : str   — display name of the winning player
              - ``turns``        : int   — total game length in turns
              - ``player_lives`` : dict  — {seat_index: final_life} for all seats
              - ``reward``       : float — normalised reward in [-1.0, 1.0]
                                          for the AI player recorded in each entry
                                          (winner_life - loser_life) / 40.0

        Returns the absolute path written, or None if the log was empty.
        """
        if not self._decision_log:
            return None

        # ── Build game_result payload from GameResult dataclass ──
        result_payload: dict | None = None
        if game_result is not None:
            try:
                winner_seat: int = game_result.winner_seat
                winner_name: str = game_result.players[winner_seat].name
                turns: int = game_result.turns

                # Per-seat final life totals
                player_lives: dict[int, int] = {
                    pr.seat_index: pr.life
                    for pr in game_result.players
                }

                result_payload = {
                    "winner_seat": winner_seat,
                    "winner_name": winner_name,
                    "turns": turns,
                    "player_lives": player_lives,
                }
            except Exception as exc:
                logger.warning("Could not extract game_result fields: %s", exc)

        # ── Backfill each entry with game_result + per-entry reward ──
        for entry in self._decision_log:
            if result_payload is None:
                entry["game_result"] = None
                continue

            # Determine reward for the player who made this decision
            pi = entry.get("player_index")
            winner_seat = result_payload["winner_seat"]
            player_lives = result_payload["player_lives"]

            if pi is not None and len(player_lives) >= 2:
                my_life = player_lives.get(pi, 0)
                # Sum of all opponents' final life totals
                opp_life_sum = sum(
                    v for k, v in player_lives.items() if k != pi
                )
                opp_count = max(len(player_lives) - 1, 1)
                avg_opp_life = opp_life_sum / opp_count
                raw_reward = (my_life - avg_opp_life) / 40.0
                reward = round(max(-1.0, min(1.0, raw_reward)), 4)
            else:
                # Fallback: binary win/loss
                reward = 1.0 if (pi is not None and pi == winner_seat) else -1.0

            entry["game_result"] = {
                **result_payload,
                "reward": reward,
            }

        # ── Write to JSONL ──
        if filepath is None:
            log_dir = self.config.log_dir or os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "logs", "decisions"
            )
            os.makedirs(log_dir, exist_ok=True)
            filepath = os.path.join(
                log_dir,
                f"decisions_{int(time.time())}.jsonl"
            )

        with open(filepath, "a", encoding="utf-8") as f:
            for entry in self._decision_log:
                f.write(json.dumps(entry) + "\n")

        count = len(self._decision_log)
        self._decision_log.clear()
        logger.info("Flushed %d decisions to %s", count, filepath)
        return filepath

    def get_stats(self) -> dict:
        """Return performance statistics."""
        avg_latency = (
            self._total_latency_ms / max(
                self._total_calls - self._total_fallbacks - self._total_cache_hits, 1
            )
        )
        return {
            "total_calls": self._total_calls,
            "cache_hits": self._total_cache_hits,
            "fallbacks": self._total_fallbacks,
            "llm_calls": self._total_calls - self._total_fallbacks - self._total_cache_hits,
            "avg_latency_ms": round(avg_latency, 1),
            "connected": self._connected,
            "model": self.config.model,
            "api_base": self.config.api_base,
            "pending_log_entries": len(self._decision_log),
            "current_game_id": self._current_game_id,
        }
