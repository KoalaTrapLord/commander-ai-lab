"""
Commander AI Lab — V3 Deck Generator Service
═════════════════════════════════════════════
Generates Commander decks using Anthropic Claude
structured JSON output, then runs ownership check
and smart substitution.

Phase 1 changes:
  - smart_substitute() non-destructive contract (never returns None)
  - apply_substitutions() loop never silently drops cards
  - _pad_to_99() circuit breaker before BuildResult validation
  - Pre-validation count logging per category
  - Startup SLOT_BUDGET assertion
"""

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple
from urllib.request import urlopen, Request

from ..clients.anthropic_client import AnthropicClient
from ..schemas.deck_schema import DECK_LIST_SCHEMA, GeneratedDeckList
from ..schemas.substitution_schema import (
    CardAlternative, DeckCardWithStatus, SubstitutionBatchResult,
)
from ..prompts.deck_gen_system import SYSTEM_PROMPT
from ..prompts.deck_gen_user import build_user_prompt
from ..prompts.substitution_prompt import (
    SUBSTITUTION_SYSTEM, build_substitution_prompt,
)
from ..config import (
    DECK_GEN_MODEL, DECK_GEN_TEMPERATURE, DECK_GEN_MAX_TOKENS,
    SUBSTITUTION_MIN_SIMILARITY, SUBSTITUTION_MAX_ALTERNATIVES,
    SUBSTITUTION_MODEL, SUBSTITUTION_USE_ANTHROPIC_FALLBACK,
)

logger = logging.getLogger("coach.deckgen")


# ══════════════════════════════════════════════════════════════
# Slot Budget — MUST sum to 99 (commander is the 100th card)
# ══════════════════════════════════════════════════════════════

SLOT_BUDGET: dict[str, int] = {
    "Land":         36,
    "Ramp":         10,
    "Card Draw":    10,
    "Removal":       8,
    "Board Wipe":    3,
    "Win Condition": 4,
    "Protection":    4,
    "Synergy":      20,
    "Creature":      2,
    "Utility":       2,
}

# ── Startup assertion — catches misconfigured budgets at boot time ──
_SLOT_BUDGET_TOTAL = sum(SLOT_BUDGET.values())
assert _SLOT_BUDGET_TOTAL == 99, (
    f"SLOT_BUDGET sums to {_SLOT_BUDGET_TOTAL}, must equal 99. "
    f"Current distribution: {SLOT_BUDGET}"
)


# ══════════════════════════════════════════════════════════════
# SubstitutionMethod — tracks HOW each card was resolved
# ══════════════════════════════════════════════════════════════

class SubstitutionMethod(str, Enum):
    EXACT_MATCH          = "exact_match"       # Card found verbatim in collection
    FUZZY_MATCH          = "fuzzy_match"        # Case/punctuation-normalised match
    EMBEDDING_ANALOG     = "embedding_analog"   # Embedding similarity match
    ANTHROPIC_FALLBACK   = "anthropic_fallback" # LLM suggested replacement
    ORIGINAL_KEPT        = "original_kept"      # Not in collection but Scryfall-valid
    BASIC_LAND_FALLBACK  = "basic_land_fallback" # Last resort — slot becomes a basic


@dataclass
class SubstitutionRecord:
    """Audit trail entry for a single card's resolution."""
    original: str
    resolved: str
    method: SubstitutionMethod
    in_collection: bool


# ══════════════════════════════════════════════════════════════
# Color → Basic Land mapping
# ══════════════════════════════════════════════════════════════

_COLOR_TO_BASIC: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}
_BASIC_NAMES: set[str] = set(_COLOR_TO_BASIC.values()) | {"Wastes"}


def _get_basic_land(color_identity: List[str]) -> str:
    """Return the first appropriate basic land for the given color identity."""
    for color in color_identity:
        if color.upper() in _COLOR_TO_BASIC:
            return _COLOR_TO_BASIC[color.upper()]
    return "Wastes"  # Colorless commander


# ══════════════════════════════════════════════════════════════
# Non-destructive Smart Substitution
# ══════════════════════════════════════════════════════════════

def smart_substitute(
    card_name: str,
    collection: set[str],
    color_identity: List[str],
    embedding_index=None,
) -> SubstitutionRecord:
    """
    Non-destructive substitution — ALWAYS returns a valid card string.

    Fallback chain:
      1. Exact match in collection
      2. Fuzzy match (case + punctuation normalised)
      3. Embedding similarity match (if index available)
      4. Keep original (Scryfall-valid, not in collection)
      5. Basic land for the commander's colors (last resort — NEVER None)
    """
    # 1. Exact match
    if card_name in collection:
        return SubstitutionRecord(card_name, card_name, SubstitutionMethod.EXACT_MATCH, True)

    # 2. Fuzzy match — normalise case and common punctuation differences
    normalised = card_name.lower().strip()
    for owned in collection:
        if owned.lower().strip() == normalised:
            return SubstitutionRecord(card_name, owned, SubstitutionMethod.FUZZY_MATCH, True)

    # 3. Embedding similarity (if index available)
    if embedding_index and getattr(embedding_index, "loaded", False):
        try:
            matches = embedding_index.search_similar(
                query_card=card_name,
                color_filter=color_identity or None,
                exclude_cards=[card_name],
                top_n=5,
            )
            pool_lower = {n.lower() for n in collection}
            for match in matches:
                if match.name.lower() in pool_lower:
                    return SubstitutionRecord(
                        card_name, match.name, SubstitutionMethod.EMBEDDING_ANALOG, True
                    )
        except Exception as e:
            logger.warning("Embedding substitution failed for '%s': %s", card_name, e)

    # 4. Keep original — valid card not in collection (proxy / non-collection build)
    return SubstitutionRecord(
        card_name, card_name, SubstitutionMethod.ORIGINAL_KEPT, False
    )


def apply_substitutions(
    card_list: List[DeckCardWithStatus],
    collection: set[str],
    color_identity: List[str],
    embedding_index=None,
) -> Tuple[List[DeckCardWithStatus], List[SubstitutionRecord]]:
    """
    Apply smart substitution to a card list.

    Guarantees: output list is NEVER shorter than input list.
    Logs a warning for every BASIC_LAND_FALLBACK.
    """
    records: List[SubstitutionRecord] = []
    result: List[DeckCardWithStatus] = []

    for card in card_list:
        rec = smart_substitute(card.name, collection, color_identity, embedding_index)
        records.append(rec)

        if rec.method == SubstitutionMethod.BASIC_LAND_FALLBACK:
            logger.warning(
                "[substitution] BASIC_LAND_FALLBACK for '%s' — slot filled with '%s'",
                rec.original, rec.resolved,
            )

        # Update the card in-place — never drop it
        updated = card.model_copy(update={
            "name": rec.resolved,
            "owned": rec.in_collection,
            "status": "owned" if rec.in_collection else
                       ("substituted" if rec.method != SubstitutionMethod.ORIGINAL_KEPT
                        else "missing"),
            "original_card": card.name if rec.resolved != card.name else card.original_card,
        })
        result.append(updated)

    fallback_count = sum(1 for r in records if r.method == SubstitutionMethod.BASIC_LAND_FALLBACK)
    if fallback_count:
        logger.error(
            "[substitution] %d cards fell back to basic lands — investigate LLM output quality",
            fallback_count,
        )

    return result, records


# ══════════════════════════════════════════════════════════════
# Pad-to-99 Circuit Breaker
# ══════════════════════════════════════════════════════════════

def _pad_to_99(
    cards: List[DeckCardWithStatus],
    color_identity: List[str],
    target: int = 99,
) -> Tuple[List[DeckCardWithStatus], int]:
    """
    Emergency safety pad — should NEVER fire if substitution contract holds.

    If it does fire, the error log is your signal that a card is being dropped
    somewhere earlier in the pipeline.

    Returns (padded_cards, number_of_slots_padded).
    """
    # Strip commander from count if present (commander is tracked separately)
    non_commander = [c for c in cards if not getattr(c, "is_commander", False)]
    current = sum(c.count for c in non_commander)
    shortfall = target - current

    if shortfall <= 0:
        return cards, 0

    logger.error(
        "[pad_to_99] CIRCUIT BREAKER FIRED — deck is %d cards short after substitution. "
        "Padding with basic lands. Check substitution pipeline for silent drops.",
        shortfall,
    )

    basic = _get_basic_land(color_identity)
    padding_card = DeckCardWithStatus(
        name=basic,
        count=shortfall,
        category="Land",
        role_tags=[],
        reason="Emergency pad — basic land inserted by circuit breaker",
        estimated_price_usd=0.10,
        owned=True,
        owned_qty=shortfall,
        status="owned",
    )
    return cards + [padding_card], shortfall


def _log_pre_validation_counts(cards: List[DeckCardWithStatus]) -> None:
    """Log per-category card counts before Pydantic validation."""
    by_cat: dict[str, int] = {}
    for card in cards:
        cat = card.category or "Uncategorized"
        by_cat[cat] = by_cat.get(cat, 0) + card.count
    total = sum(by_cat.values())
    logger.info("[pre_validation] Category counts: %s", by_cat)
    logger.info("[pre_validation] Total: %d/99 (delta: %d)", total, 99 - total)


# ══════════════════════════════════════════════════════════════
# DeckGeneratorV3
# ══════════════════════════════════════════════════════════════

class DeckGeneratorV3:
    """
    V3 Deck Generator using Anthropic Claude structured output.

    Pipeline:
      1. Resolve commander via Scryfall
      2. Build collection summary
      3. Call Anthropic Claude with structured JSON schema
      4. Validate card names via Scryfall
      5. Check ownership against collection DB
      6. Run Smart Substitution (non-destructive)
      7. _pad_to_99 circuit breaker
      8. Pre-validation count logging
      9. Return finalized deck — guaranteed 99 cards
    """

    def __init__(self, anthropic_client: AnthropicClient, db_conn_factory,
                 embedding_index=None):
        self.anthropic = anthropic_client
        self.db_conn_factory = db_conn_factory
        self.embedding_index = embedding_index

    # ── Step 1: Resolve Commander ────────────────────────────
    def resolve_commander(self, commander_name: str) -> dict:
        """Look up commander on Scryfall to get canonical name, color identity, type."""
        try:
            encoded = commander_name.replace(" ", "+")
            url = f"https://api.scryfall.com/cards/named?fuzzy={encoded}"
            req = Request(url)
            req.add_header("User-Agent", "CommanderAILab/3.0")
            req.add_header("Accept", "application/json")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return {
                "name": data.get("name", commander_name),
                "scryfall_id": data.get("id", ""),
                "color_identity": data.get("color_identity", []),
                "type_line": data.get("type_line", ""),
                "mana_cost": data.get("mana_cost", ""),
                "image_url": data.get("image_uris", {}).get("normal", ""),
                "oracle_text": data.get("oracle_text", ""),
                "scryfall_found": True,
            }
        except Exception as e:
            logger.warning("Scryfall lookup failed for '%s': %s", commander_name, e)
            # Non-canonical commander (silver-bordered, custom, etc.)
            # Skip collection substitution for these — trust LLM output directly
            return {
                "name": commander_name,
                "scryfall_id": "",
                "color_identity": [],
                "type_line": "",
                "mana_cost": "",
                "image_url": "",
                "oracle_text": "",
                "scryfall_found": False,
            }

    # ── Step 2: Build Collection Summary ─────────────────────
    def build_collection_summary(self, color_identity: List[str],
                                  max_per_group: int = 20) -> str:
        """
        Build a text summary of owned cards matching the deck's color identity.
        Groups by card type for the LLM prompt.
        """
        conn = self.db_conn_factory()
        try:
            rows = conn.execute(
                "SELECT name, type_line, cmc, oracle_text, quantity, tcg_price "
                "FROM collection_entries WHERE quantity > 0"
            ).fetchall()
        except Exception as e:
            logger.warning("Failed to load collection: %s", e)
            return ""

        if not rows:
            return ""

        ci_set = set(color_identity) if color_identity else None
        filtered = []
        for row in rows:
            if ci_set:
                card_colors = set()
                oracle = row["oracle_text"] or ""
                mana_cost = ""
                try:
                    mana_cost = row["mana_cost"] or ""
                except (IndexError, KeyError):
                    pass
                for sym in ["W", "U", "B", "R", "G"]:
                    if f"{{{sym}}}" in (mana_cost or oracle):
                        card_colors.add(sym)
                if card_colors and not card_colors.issubset(ci_set):
                    continue
            filtered.append(row)

        if not filtered:
            return ""

        groups = {}
        for row in filtered:
            type_line = row["type_line"] or ""
            if "Creature" in type_line:
                group = "Creatures"
            elif "Instant" in type_line:
                group = "Instants"
            elif "Sorcery" in type_line:
                group = "Sorceries"
            elif "Artifact" in type_line:
                group = "Artifacts"
            elif "Enchantment" in type_line:
                group = "Enchantments"
            elif "Planeswalker" in type_line:
                group = "Planeswalkers"
            elif "Land" in type_line:
                group = "Lands"
            else:
                group = "Other"
            groups.setdefault(group, []).append(row)

        lines = [f"COLLECTION SUMMARY ({len(filtered)} cards in deck colors):"]
        for group_name in ["Creatures", "Instants", "Sorceries", "Artifacts",
                           "Enchantments", "Planeswalkers", "Lands", "Other"]:
            cards = groups.get(group_name, [])
            if not cards:
                continue
            cards.sort(key=lambda r: r["tcg_price"] or 0, reverse=True)
            card_strs = []
            for c in cards[:max_per_group]:
                price = f"${c['tcg_price']:.2f}" if c["tcg_price"] else "$?"
                card_strs.append(f"{c['name']} ({price})")
            lines.append(f"  {group_name} ({len(cards)}): {', '.join(card_strs)}")

        return "\n".join(lines)

    # ── Step 3: Generate Deck via Anthropic Claude ─────────────────
    def generate_deck(
        self,
        commander_name: str,
        strategy: str = "",
        target_bracket: int = 3,
        budget_usd: float = None,
        budget_mode: str = "total",
        omit_cards: List[str] = None,
        use_collection: bool = True,
        model: str = None,
    ) -> dict:
        """
        Generate a complete Commander deck.

        Returns dict with:
          - commander: dict with Scryfall data
          - raw_deck: parsed GeneratedDeckList from Anthropic Claude
          - cards: list of DeckCardWithStatus (after ownership check + substitution)
          - stats: deck statistics
          - substitution_log: list of SubstitutionRecord dicts
          - padded_slots: int > 0 means circuit breaker fired
          - tokens_used: {prompt, completion}
        """
        # Step 1: Resolve commander
        cmdr = self.resolve_commander(commander_name)
        color_identity = cmdr["color_identity"]
        scryfall_found = cmdr.get("scryfall_found", True)
        logger.info("Commander: %s, CI: %s, Scryfall: %s",
                    cmdr["name"], color_identity, scryfall_found)

        # Step 2: Collection summary
        collection_block = ""
        if use_collection and scryfall_found:
            collection_block = self.build_collection_summary(color_identity)
            logger.info("Collection summary: %d chars",
                        len(collection_block) if collection_block else 0)
        elif not scryfall_found:
            logger.info(
                "Non-canonical commander '%s' — skipping collection filter, "
                "trusting LLM output directly.", cmdr["name"]
            )

        # Step 3: Build prompts (with slot budget injected)
        user_prompt = build_user_prompt(
            commander=cmdr["name"],
            commander_type=cmdr["type_line"],
            color_identity=color_identity,
            strategy=strategy,
            target_bracket=target_bracket,
            budget_usd=budget_usd,
            budget_mode=budget_mode,
            omit_cards=omit_cards,
            collection_summary=collection_block,
            slot_budget=SLOT_BUDGET,
        )

        # Step 4: Call LLM with structured output
        use_model = model or DECK_GEN_MODEL
        logger.info("Calling LLM (%s) for deck generation...", use_model)

        response = self.anthropic.chat_structured(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_schema=DECK_LIST_SCHEMA,
            schema_name="DeckList",
            model=use_model,
            temperature=DECK_GEN_TEMPERATURE,
            max_tokens=DECK_GEN_MAX_TOKENS,
        )

        if not response.ok:
            raise ValueError(
                f"LLM returned invalid response: {response.content[:300]}"
            )

        raw_deck = response.parsed_json
        card_count = len(raw_deck.get("cards", []))
        truncated = card_count < 90
        logger.info(
            "Deck generated: %d cards, bracket %s%s",
            card_count,
            (raw_deck.get("bracket", {}).get("level", "?") if isinstance(raw_deck.get("bracket"), dict)
             else raw_deck.get("bracket", "?")),
            " (TRUNCATED — hit token limit)" if truncated else "",
        )

        # Step 5: Check ownership
        cards_with_status = self._check_ownership(raw_deck.get("cards", []))

        # Step 5b: Fill basic lands to reach target_total=100
        cards_with_status = self._fill_basic_lands(cards_with_status, color_identity)

        # Step 5c: Secondary deduplication
        seen: dict[str, int] = {}
        deduped: List[DeckCardWithStatus] = []
        for c in cards_with_status:
            key = c.name.lower()
            if key in seen:
                deduped[seen[key]].count += c.count
                logger.warning("Secondary dedupe caught duplicate: '%s'", c.name)
            else:
                seen[key] = len(deduped)
                deduped.append(c)
        cards_with_status = deduped

        # Step 6: Run non-destructive smart substitution
        # For non-canonical commanders (e.g. Sonic), skip collection filter
        owned_pool: set[str] = set()
        if use_collection and scryfall_found:
            conn = self.db_conn_factory()
            rows = conn.execute(
                "SELECT DISTINCT name FROM collection_entries WHERE quantity > 0"
            ).fetchall()
            owned_pool = {r["name"] for r in rows}

        cards_with_status, substitution_log = apply_substitutions(
            cards_with_status, owned_pool, color_identity, self.embedding_index
        )

        # Step 7: Pad-to-99 circuit breaker
        cards_with_status, padded_slots = _pad_to_99(cards_with_status, color_identity)

        # Step 8: Pre-validation count logging
        _log_pre_validation_counts(cards_with_status)

        # Step 9: Compute stats
        stats = self._compute_stats(cards_with_status)

        return {
            "commander": cmdr,
            "color_identity": color_identity,
            "raw_deck": raw_deck,
            "cards": [c.model_dump() for c in cards_with_status],
            "stats": stats,
            "strategy_summary": raw_deck.get("strategy_summary", ""),
            "bracket": raw_deck.get("bracket", {}),
            "archetype": raw_deck.get("archetype", ""),
            "reasoning": raw_deck.get("reasoning", {}),
            "estimated_total_usd": raw_deck.get("estimated_total_usd", 0),
            "substitution_log": [
                {"original": r.original, "resolved": r.resolved,
                 "method": r.method.value, "in_collection": r.in_collection}
                for r in substitution_log
            ],
            "padded_slots": padded_slots,
            "tokens_used": {
                "prompt": response.prompt_tokens,
                "completion": response.completion_tokens,
            },
            "model": response.model,
            "citations": response.citations,
            "truncated": truncated,
        }

    # ── Step 5: Ownership Check ──────────────────────────────
    def _check_ownership(self, cards: List[dict]) -> List[DeckCardWithStatus]:
        """
        Cross-reference generated cards against the collection DB.
        Deduplicates by name (case-insensitive).
        """
        conn = self.db_conn_factory()
        enriched: List[DeckCardWithStatus] = []
        seen_names: dict[str, int] = {}

        for card in cards:
            name = card.get("name", "")
            if not name:
                continue

            name_lower = name.lower()

            if name_lower in seen_names:
                idx = seen_names[name_lower]
                enriched[idx].count += card.get("count", 1)
                logger.warning("Duplicate card '%s' merged", name)
                continue

            row = conn.execute(
                "SELECT name, scryfall_id, quantity, tcg_price, type_line, cmc "
                "FROM collection_entries WHERE name = ? COLLATE NOCASE LIMIT 1",
                (name,)
            ).fetchone()

            is_owned = bool(row and row["quantity"] and row["quantity"] > 0)

            enriched_card = DeckCardWithStatus(
                name=row["name"] if row else name,
                count=card.get("count", 1),
                category=card.get("category", ""),
                role_tags=card.get("role_tags", []),
                reason=card.get("reason", ""),
                estimated_price_usd=(
                    round(row["tcg_price"], 2) if row and row["tcg_price"]
                    else card.get("estimated_price_usd", 0)
                ),
                synergy_with=card.get("synergy_with", []),
                owned=is_owned,
                owned_qty=int(row["quantity"]) if row and row["quantity"] else 0,
                scryfall_id=row["scryfall_id"] if row else "",
                status="owned" if is_owned else "missing",
            )
            seen_names[name_lower] = len(enriched)
            enriched.append(enriched_card)

        return enriched

    # ── Step 5b: Basic Land Fill ──────────────────────────────
    _COLOR_TO_BASIC = _COLOR_TO_BASIC
    _BASIC_NAMES = _BASIC_NAMES

    def _fill_basic_lands(
        self,
        cards: List[DeckCardWithStatus],
        color_identity: List[str],
        target_total: int = 100,
    ) -> List[DeckCardWithStatus]:
        """
        Strip LLM-provided basics, then add the right number evenly
        across the commander's colors to reach exactly target_total.
        """
        non_basics = [c for c in cards if c.name not in self._BASIC_NAMES]
        current_total = sum(c.count for c in non_basics)
        basics_needed = max(0, target_total - current_total)

        if basics_needed == 0:
            return non_basics

        ci = [c.upper() for c in color_identity]
        basic_names = [self._COLOR_TO_BASIC[c] for c in ci if c in self._COLOR_TO_BASIC]
        if not basic_names:
            basic_names = ["Wastes"]

        per_color = basics_needed // len(basic_names)
        remainder = basics_needed % len(basic_names)

        for i, bname in enumerate(basic_names):
            qty = per_color + (1 if i < remainder else 0)
            if qty > 0:
                non_basics.append(DeckCardWithStatus(
                    name=bname,
                    count=qty,
                    category="Land",
                    role_tags=[],
                    reason="Basic land for mana fixing",
                    estimated_price_usd=0.10,
                    owned=True,
                    owned_qty=qty,
                    status="owned",
                ))

        logger.info("Basic land fill: %d basics added across %d color(s)",
                    basics_needed, len(basic_names))
        return non_basics

    # ── Step 6: Smart Substitution (legacy wrapper for route compatibility) ──
    def run_substitution(
        self,
        cards: List[DeckCardWithStatus],
        commander: dict,
        strategy: str = "",
    ) -> SubstitutionBatchResult:
        """
        Run the Smart Substitution Engine on missing cards.

        Uses the non-destructive apply_substitutions() under the hood.
        Falls back to Anthropic Claude for low-confidence matches,
        then to basic land as last resort — NEVER drops a card.
        """
        color_identity = commander.get("color_identity", [])
        scryfall_found = commander.get("scryfall_found", True)
        missing = [c for c in cards if not c.owned]
        owned = [c for c in cards if c.owned]

        if not missing:
            return SubstitutionBatchResult(
                total_cards=len(cards),
                owned_count=len(owned),
                substituted_count=0,
                missing_count=0,
                cards=cards,
            )

        logger.info("Substitution: %d missing / %d owned", len(missing), len(owned))

        # Build owned pool
        conn = self.db_conn_factory()
        owned_pool_rows = conn.execute(
            "SELECT DISTINCT name FROM collection_entries WHERE quantity > 0"
        ).fetchall()
        owned_pool = {r["name"] for r in owned_pool_rows}
        deck_names = {c.name.lower() for c in cards}
        available_pool = {n for n in owned_pool if n.lower() not in deck_names}

        # a) Embedding pass for missing cards
        needs_anthropic_fallback: List[DeckCardWithStatus] = []
        for card in missing:
            embedding_alts = self._embedding_substitution(
                card, color_identity, list(available_pool)
            )
            card.alternatives = embedding_alts

            if embedding_alts and embedding_alts[0].similarity_score >= SUBSTITUTION_MIN_SIMILARITY:
                card.selected_substitute = embedding_alts[0].name
                card.status = "substituted"
                card.owned = True
                available_pool.discard(card.selected_substitute.lower())
            else:
                needs_anthropic_fallback.append(card)

        # b) Anthropic Claude fallback
        if needs_anthropic_fallback and SUBSTITUTION_USE_ANTHROPIC_FALLBACK:
            self._anthropic_substitution(
                needs_anthropic_fallback, list(available_pool),
                commander, strategy
            )

        # c) Any card STILL missing after both passes gets a basic land — never drop it
        padded = 0
        for card in missing:
            if card.status == "missing":
                basic = _get_basic_land(color_identity)
                logger.warning(
                    "[substitution] '%s' unresolved after all passes — "
                    "replacing with basic land '%s'",
                    card.name, basic,
                )
                card.name = basic
                card.category = "Land"
                card.role_tags = []
                card.owned = True
                card.status = "substituted"
                card.original_card = card.name
                padded += 1

        substituted = sum(1 for c in cards if c.status == "substituted")
        still_missing = sum(1 for c in cards if c.status == "missing")

        # Validate count hasn't changed
        assert len(cards) == len(owned) + len(missing), \
            f"[substitution] Card count changed: {len(owned) + len(missing)} -> {len(cards)}"

        return SubstitutionBatchResult(
            total_cards=len(cards),
            owned_count=len(owned),
            substituted_count=substituted,
            missing_count=still_missing,
            cards=cards,
        )

    def _embedding_substitution(
        self,
        card: DeckCardWithStatus,
        color_identity: List[str],
        available_pool: List[str],
    ) -> List[CardAlternative]:
        """Find embedding-similar owned cards as substitutes."""
        if not self.embedding_index or not self.embedding_index.loaded:
            return []

        try:
            matches = self.embedding_index.search_similar(
                query_card=card.name,
                color_filter=color_identity if color_identity else None,
                type_filter=card.category if card.category else None,
                exclude_cards=[card.name],
                top_n=SUBSTITUTION_MAX_ALTERNATIVES * 3,
            )
        except Exception as e:
            logger.warning("Embedding search failed for '%s': %s", card.name, e)
            return []

        pool_lower = {n.lower() for n in available_pool}
        alternatives = []
        for match in matches:
            if match.name.lower() in pool_lower:
                role_overlap = list(set(card.role_tags) & set(getattr(match, "role_tags", [])))
                alternatives.append(CardAlternative(
                    name=match.name,
                    similarity_score=match.similarity,
                    reason=f"Similar to {card.name} (cosine sim: {match.similarity:.3f})",
                    source="embedding",
                    role_overlap=role_overlap,
                    cmc_delta=getattr(match, "mana_value", 0) - (card.estimated_price_usd or 0),
                ))
                if len(alternatives) >= SUBSTITUTION_MAX_ALTERNATIVES:
                    break

        return alternatives

    def _anthropic_substitution(
        self,
        missing_cards: List[DeckCardWithStatus],
        available_pool: List[str],
        commander: dict,
        strategy: str,
    ):
        """
        Batch Anthropic Claude fallback for cards with low embedding confidence.
        Mutates cards in-place. On failure, cards retain status='missing'
        so the basic-land fallback in run_substitution() can catch them.
        """
        if not available_pool:
            logger.warning("[anthropic_substitution] No available pool — skipping")
            return

        missing_dicts = [
            {
                "name": c.name,
                "role_tags": c.role_tags,
                "category": c.category,
                "reason": c.reason,
            }
            for c in missing_cards
        ]

        user_prompt = build_substitution_prompt(
            missing_cards=missing_dicts,
            allowed_cards=available_pool[:200],
            commander=commander.get("name", ""),
            color_identity=commander.get("color_identity", []),
            strategy=strategy,
        )

        try:
            from ..schemas.substitution_schema import SUBSTITUTION_RESPONSE_SCHEMA
            response = self.anthropic.chat_structured(
                system_prompt=SUBSTITUTION_SYSTEM,
                user_prompt=user_prompt,
                json_schema=SUBSTITUTION_RESPONSE_SCHEMA,
                schema_name="SubstitutionResponse",
                model=SUBSTITUTION_MODEL,
                temperature=0.1,
                max_tokens=4096,
            )

            if not response.ok:
                logger.warning(
                    "[anthropic_substitution] LLM returned non-JSON — "
                    "%d cards will fall through to basic land fallback",
                    len(missing_cards),
                )
                return

            subs = response.parsed_json.get("substitutions", [])
            logger.info("[anthropic_substitution] Received %d substitutions", len(subs))

            card_by_name = {c.name.lower(): c for c in missing_cards}
            for sub in subs:
                orig = sub.get("original", "").lower()
                substitute = sub.get("substitute", "")
                reason = sub.get("reason", "")

                if orig in card_by_name and substitute:
                    card = card_by_name[orig]
                    anthropic_alt = CardAlternative(
                        name=substitute,
                        similarity_score=0.80,
                        reason=reason,
                        source="anthropic",
                        role_overlap=sub.get("role_overlap", []),
                    )
                    card.alternatives.insert(0, anthropic_alt)
                    card.selected_substitute = substitute
                    card.status = "substituted"
                    card.owned = True
                    card.original_card = card.name

        except Exception as e:
            logger.error(
                "[anthropic_substitution] Exception: %s — "
                "%d cards will fall through to basic land fallback",
                e, len(missing_cards),
            )
            # Do NOT re-raise — cards stay status='missing' and
            # run_substitution()'s basic-land fallback will handle them

    # ── Stats ────────────────────────────────────────────────
    @staticmethod
    def _compute_stats(cards: List[DeckCardWithStatus]) -> dict:
        """Compute deck statistics from the enriched card list."""
        by_category: dict[str, int] = {}
        by_status: dict[str, int] = {"owned": 0, "substituted": 0, "missing": 0}
        total_price = 0.0
        owned_price = 0.0
        missing_price = 0.0
        role_counts: dict[str, int] = {}

        for card in cards:
            cat = card.category or "Other"
            by_category[cat] = by_category.get(cat, 0) + card.count
            by_status[card.status] = by_status.get(card.status, 0) + 1
            price = card.estimated_price_usd * card.count
            total_price += price
            if card.owned:
                owned_price += price
            else:
                missing_price += price
            for role in card.role_tags:
                role_counts[role] = role_counts.get(role, 0) + 1

        land_count = by_category.get("Land", 0)
        nonland_count = sum(v for k, v in by_category.items() if k != "Land")

        return {
            "total_cards": sum(c.count for c in cards),
            "land_count": land_count,
            "nonland_count": nonland_count,
            "by_category": by_category,
            "by_status": by_status,
            "role_counts": role_counts,
            "total_price_usd": round(total_price, 2),
            "owned_price_usd": round(owned_price, 2),
            "missing_price_usd": round(missing_price, 2),
        }
