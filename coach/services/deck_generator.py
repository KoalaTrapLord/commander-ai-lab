"""
Commander AI Lab — V3 Deck Generator Service
═════════════════════════════════════════════
Generates Commander decks using Perplexity Sonar
structured JSON output, then runs ownership check
and smart substitution.
"""

import json
import logging
import re
import sqlite3
from typing import List, Optional, Tuple
from urllib.request import urlopen, Request

from ..clients.perplexity_client import PerplexityClient
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
    SUBSTITUTION_MODEL, SUBSTITUTION_USE_PPLX_FALLBACK,
)

logger = logging.getLogger("coach.deckgen")


class DeckGeneratorV3:
    """
    V3 Deck Generator using Perplexity structured output.

    Pipeline:
      1. Resolve commander via Scryfall
      2. Build collection summary
      3. Call Perplexity with structured JSON schema
      4. Validate card names via Scryfall
      5. Check ownership against collection DB
      6. Run Smart Substitution (embedding + Perplexity fallback)
      7. Return finalized deck with substitution data
    """

    def __init__(self, pplx_client: PerplexityClient, db_conn_factory,
                 embedding_index=None):
        """
        Args:
            pplx_client: Configured PerplexityClient instance
            db_conn_factory: Callable that returns sqlite3.Connection
            embedding_index: Optional MTGEmbeddingIndex for substitution
        """
        self.pplx = pplx_client
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
            }
        except Exception as e:
            logger.warning("Scryfall lookup failed for '%s': %s", commander_name, e)
            return {
                "name": commander_name,
                "scryfall_id": "",
                "color_identity": [],
                "type_line": "",
                "mana_cost": "",
                "image_url": "",
                "oracle_text": "",
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

        # Filter by color identity
        ci_set = set(color_identity) if color_identity else None
        filtered = []
        for row in rows:
            name = row["name"]
            type_line = row["type_line"] or ""
            # Basic lands and colorless are always allowed
            if ci_set:
                # Simple color check from type_line and name
                # For proper filtering we'd check mana cost but this is good enough for summary
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

        # Group by card type
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

        # Sort each group by popularity/price and build text
        lines = [f"COLLECTION SUMMARY ({len(filtered)} cards in deck colors):"]
        for group_name in ["Creatures", "Instants", "Sorceries", "Artifacts",
                           "Enchantments", "Planeswalkers", "Lands", "Other"]:
            cards = groups.get(group_name, [])
            if not cards:
                continue
            # Sort by price descending (higher value = likely better card)
            cards.sort(key=lambda r: r["tcg_price"] or 0, reverse=True)
            card_strs = []
            for c in cards[:max_per_group]:
                price = f"${c['tcg_price']:.2f}" if c["tcg_price"] else "$?"
                card_strs.append(f"{c['name']} ({price})")
            lines.append(f"  {group_name} ({len(cards)}): {', '.join(card_strs)}")

        return "\n".join(lines)

    # ── Step 3: Generate Deck via Perplexity ─────────────────
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
          - raw_deck: parsed GeneratedDeckList from Perplexity
          - cards: list of DeckCardWithStatus (after ownership check)
          - stats: deck statistics
          - tokens_used: {prompt, completion}
        """
        # Step 1: Resolve commander
        cmdr = self.resolve_commander(commander_name)
        color_identity = cmdr["color_identity"]
        logger.info("Commander: %s, CI: %s", cmdr["name"], color_identity)

        # Step 2: Collection summary
        collection_block = ""
        if use_collection:
            collection_block = self.build_collection_summary(color_identity)
            logger.info("Collection summary: %d chars",
                        len(collection_block) if collection_block else 0)

        # Step 3: Build prompts
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
        )

        # Step 4: Call Perplexity with structured output
        use_model = model or DECK_GEN_MODEL
        logger.info("Calling Perplexity (%s) for deck generation...", use_model)

        response = self.pplx.chat_structured(
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
                f"Perplexity returned invalid response: {response.content[:300]}"
            )

        raw_deck = response.parsed_json
        logger.info("Deck generated: %d cards, bracket %d",
                     len(raw_deck.get("cards", [])),
                     raw_deck.get("bracket", {}).get("level", 0))

        # Step 5: Check ownership and build enriched card list
        cards_with_status = self._check_ownership(raw_deck.get("cards", []))

        # Step 6: Compute stats
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
            "tokens_used": {
                "prompt": response.prompt_tokens,
                "completion": response.completion_tokens,
            },
            "model": response.model,
            "citations": response.citations,
        }

    # ── Step 5: Ownership Check ──────────────────────────────
    def _check_ownership(self, cards: List[dict]) -> List[DeckCardWithStatus]:
        """
        Cross-reference generated cards against the collection DB.
        Sets owned/scryfall_id/owned_qty and real price.
        """
        conn = self.db_conn_factory()
        enriched = []

        for card in cards:
            name = card.get("name", "")
            if not name:
                continue

            # Look up in collection
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
            enriched.append(enriched_card)

        return enriched

    # ── Step 6: Smart Substitution ───────────────────────────
    def run_substitution(
        self,
        cards: List[DeckCardWithStatus],
        commander: dict,
        strategy: str = "",
    ) -> SubstitutionBatchResult:
        """
        Run the Smart Substitution Engine on missing cards.

        Pipeline:
          a) Identify missing cards
          b) For each: try embedding similarity (free, fast)
          c) For low-confidence matches: batch Perplexity fallback
          d) Auto-select best substitute per card

        Returns SubstitutionBatchResult with all cards updated.
        """
        color_identity = commander.get("color_identity", [])
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

        # Build list of owned card names for substitution pool
        conn = self.db_conn_factory()
        owned_pool_rows = conn.execute(
            "SELECT DISTINCT name FROM collection_entries WHERE quantity > 0"
        ).fetchall()
        owned_pool = [r["name"] for r in owned_pool_rows]

        # Exclude cards already in the deck
        deck_names = set(c.name.lower() for c in cards)
        available_pool = [n for n in owned_pool if n.lower() not in deck_names]

        # a) Embedding pass
        needs_pplx_fallback = []
        for card in missing:
            embedding_alts = self._embedding_substitution(
                card, color_identity, available_pool
            )
            card.alternatives = embedding_alts

            # Check if best match meets threshold
            if embedding_alts and embedding_alts[0].similarity_score >= SUBSTITUTION_MIN_SIMILARITY:
                card.selected_substitute = embedding_alts[0].name
                card.status = "substituted"
                # Remove selected from pool
                if card.selected_substitute.lower() in [n.lower() for n in available_pool]:
                    available_pool = [n for n in available_pool
                                     if n.lower() != card.selected_substitute.lower()]
            else:
                needs_pplx_fallback.append(card)

        # b) Perplexity fallback for low-confidence matches
        if needs_pplx_fallback and SUBSTITUTION_USE_PPLX_FALLBACK:
            self._pplx_substitution(
                needs_pplx_fallback, available_pool,
                commander, strategy
            )

        # Count results
        substituted = sum(1 for c in cards if c.status == "substituted")
        still_missing = sum(1 for c in cards if c.status == "missing")

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

        # Use the embeddings search to find similar cards
        matches = self.embedding_index.search_similar(
            query_card=card.name,
            color_filter=color_identity if color_identity else None,
            type_filter=card.category if card.category else None,
            exclude_cards=[card.name],
            top_n=SUBSTITUTION_MAX_ALTERNATIVES * 3,  # Over-fetch, then filter to owned
        )

        # Filter to only cards in the available pool
        pool_lower = set(n.lower() for n in available_pool)
        alternatives = []
        for match in matches:
            if match.name.lower() in pool_lower:
                # Compute role overlap
                match_roles = []  # Would need card's role_tags from DB
                role_overlap = list(set(card.role_tags) & set(match_roles)) if match_roles else []

                alternatives.append(CardAlternative(
                    name=match.name,
                    similarity_score=match.similarity,
                    reason=f"Similar to {card.name} (cosine sim: {match.similarity:.3f})",
                    source="embedding",
                    role_overlap=role_overlap,
                    cmc_delta=match.mana_value - (card.estimated_price_usd or 0),
                ))

                if len(alternatives) >= SUBSTITUTION_MAX_ALTERNATIVES:
                    break

        return alternatives

    def _pplx_substitution(
        self,
        missing_cards: List[DeckCardWithStatus],
        available_pool: List[str],
        commander: dict,
        strategy: str,
    ):
        """
        Batch Perplexity fallback for cards with low embedding confidence.
        Mutates the cards in-place with substitution data.
        """
        if not available_pool:
            return

        # Build the request
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
            allowed_cards=available_pool[:200],  # Limit to avoid token overflow
            commander=commander.get("name", ""),
            color_identity=commander.get("color_identity", []),
            strategy=strategy,
        )

        try:
            from ..schemas.substitution_schema import SUBSTITUTION_RESPONSE_SCHEMA
            response = self.pplx.chat_structured(
                system_prompt=SUBSTITUTION_SYSTEM,
                user_prompt=user_prompt,
                json_schema=SUBSTITUTION_RESPONSE_SCHEMA,
                schema_name="SubstitutionResponse",
                model=SUBSTITUTION_MODEL,
                temperature=0.1,
                max_tokens=4096,
            )

            if not response.ok:
                logger.warning("Perplexity substitution fallback failed — non-JSON response")
                return

            subs = response.parsed_json.get("substitutions", [])
            logger.info("Perplexity suggested %d substitutions", len(subs))

            # Apply substitutions
            card_by_name = {c.name.lower(): c for c in missing_cards}
            for sub in subs:
                orig = sub.get("original", "").lower()
                substitute = sub.get("substitute", "")
                reason = sub.get("reason", "")

                if orig in card_by_name and substitute:
                    card = card_by_name[orig]
                    # Add as top alternative
                    pplx_alt = CardAlternative(
                        name=substitute,
                        similarity_score=0.80,  # Nominal score for Perplexity suggestions
                        reason=reason,
                        source="perplexity",
                        role_overlap=sub.get("role_overlap", []),
                    )
                    # Insert at front
                    card.alternatives.insert(0, pplx_alt)
                    card.selected_substitute = substitute
                    card.status = "substituted"

        except Exception as e:
            logger.error("Perplexity substitution fallback error: %s", e)

    # ── Stats ────────────────────────────────────────────────
    @staticmethod
    def _compute_stats(cards: List[DeckCardWithStatus]) -> dict:
        """Compute deck statistics from the enriched card list."""
        by_category = {}
        by_status = {"owned": 0, "substituted": 0, "missing": 0}
        total_price = 0.0
        owned_price = 0.0
        missing_price = 0.0
        role_counts = {}

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
