"""
routes/deckbuilder.py
=====================
Deck builder endpoints:
  POST   /api/decks
  GET    /api/decks
  GET    /api/decks/{deck_id}
  PUT    /api/decks/{deck_id}
  DELETE /api/decks/{deck_id}
  DELETE /api/decks
  GET    /api/decks/{deck_id}/cards
  POST   /api/decks/{deck_id}/cards
  DELETE /api/decks/{deck_id}/cards/{card_id}
  PATCH  /api/decks/{deck_id}/cards/{card_id}
  GET    /api/decks/{deck_id}/analysis
  GET    /api/decks/{deck_id}/recommended-from-collection
  GET    /api/decks/{deck_id}/edh-recs
  POST   /api/decks/{deck_id}/bulk-add
  POST   /api/decks/{deck_id}/bulk-add-recommended
  POST   /api/decks/{deck_id}/export-to-sim
  POST   /api/decks/{deck_id}/import
  POST   /api/decks/import-new
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest
from fastapi.responses import JSONResponse

from routes.shared import (
    CFG,
    _get_db_conn,
    _row_to_dict,
    _add_image_url,
    _get_deck_or_404,
    _compute_deck_analysis,
    _check_ratio_limit,
    _classify_card_type,
    _detect_card_roles,
    _enrich_from_scryfall,
    _fetch_scryfall_api,
    _scryfall_rate_limit,
    _to_edhrec_slug,
    _edhrec_cache_get,
    _edhrec_cache_set,
    _fetch_edhrec_average,
    _save_profile_to_dck,
    _parse_text_decklist,
    _API_HEADERS,
    _TYPE_TARGETS,
    CreateDeckRequest,
    UpdateDeckRequest,
    AddDeckCardRequest,
    PatchDeckCardRequest,
    BulkAddRequest,
    BulkAddRecommendedRequest,
    log_collect,
    log_deckgen,
)

router = APIRouter(tags=["deckbuilder"])


@router.post("/api/decks")
async def create_deck(req: CreateDeckRequest):
    """Create a new deck."""
    conn = _get_db_conn()
    color_identity_json = json.dumps(req.color_identity or [])
    cur = conn.execute(
        """
        INSERT INTO decks (name, commander_scryfall_id, commander_name, color_identity, strategy_tag)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            req.name,
            req.commander_scryfall_id or "",
            req.commander_name or "",
            color_identity_json,
            req.strategy_tag or "",
        )
    )
    conn.commit()
    deck_id = cur.lastrowid
    return _get_deck_or_404(deck_id)


@router.get("/api/decks")
async def list_decks_db():
    """List all decks with card counts."""
    conn = _get_db_conn()
    rows = conn.execute(
        """
        SELECT d.*,
               COALESCE(SUM(dc.quantity), 0) AS total_cards,
               COUNT(dc.id) AS card_slots
        FROM decks d
        LEFT JOIN deck_cards dc ON dc.deck_id = d.id
        GROUP BY d.id
        ORDER BY d.updated_at DESC
        """
    ).fetchall()
    decks = []
    for row in rows:
        d = dict(row)
        try:
            d["color_identity"] = json.loads(d.get("color_identity", "[]"))
        except Exception:
            d["color_identity"] = []
        decks.append(d)
    return {"decks": decks}


@router.get("/api/decks/{deck_id}")
async def get_deck(deck_id: int):
    """Get full deck info with composition summary."""
    deck = _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    card_rows = conn.execute(
        "SELECT * FROM deck_cards WHERE deck_id = ? ORDER BY is_commander DESC, card_name ASC",
        (deck_id,)
    ).fetchall()
    deck["cards"] = [dict(r) for r in card_rows]
    deck["total_cards"] = sum(r["quantity"] for r in card_rows)
    deck["card_slots"] = len(card_rows)
    # Composition summary by type
    analysis = _compute_deck_analysis(deck_id)
    deck["composition"] = analysis["counts_by_type"]
    return deck


@router.put("/api/decks/{deck_id}")
async def update_deck(deck_id: int, req: UpdateDeckRequest):
    """Update deck metadata."""
    _get_deck_or_404(deck_id)  # ensure exists
    conn = _get_db_conn()

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.commander_scryfall_id is not None:
        updates["commander_scryfall_id"] = req.commander_scryfall_id
    if req.commander_name is not None:
        updates["commander_name"] = req.commander_name
    if req.color_identity is not None:
        updates["color_identity"] = json.dumps(req.color_identity)
    if req.strategy_tag is not None:
        updates["strategy_tag"] = req.strategy_tag

    if not updates:
        return _get_deck_or_404(deck_id)

    updates["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE decks SET {set_clause} WHERE id = ?", list(updates.values()) + [deck_id])
    conn.commit()
    return _get_deck_or_404(deck_id)


@router.delete("/api/decks/{deck_id}")
async def delete_deck(deck_id: int):
    """Delete a deck and all its cards (cascade)."""
    _get_deck_or_404(deck_id)  # ensure exists
    conn = _get_db_conn()
    conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
    conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    conn.commit()
    return {"deleted": True, "deck_id": deck_id}


@router.delete("/api/decks")
async def delete_all_decks():
    """Delete ALL decks and their cards."""
    conn = _get_db_conn()
    conn.execute("DELETE FROM deck_cards")
    count = conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
    conn.execute("DELETE FROM decks")
    conn.commit()
    return {"deleted": True, "count": count}


# ── 2.2 Deck Card Manipulation ───────────────────────────────

@router.get("/api/decks/{deck_id}/cards")
async def get_deck_cards(deck_id: int):
    """Get all cards in a deck with joined collection data."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    rows = conn.execute(
        """
        SELECT
            dc.id, dc.deck_id, dc.scryfall_id, dc.card_name, dc.quantity,
            dc.is_commander, dc.role_tag,
            ce.type_line, ce.cmc, ce.mana_cost, ce.color_identity, ce.oracle_text, ce.keywords,
            ce.tcg_price, ce.quantity AS owned_qty, ce.is_legendary,
            ce.salt_score, ce.is_game_changer
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, cmc, mana_cost, color_identity,
                   oracle_text, keywords, tcg_price, quantity, is_legendary,
                   salt_score, is_game_changer
            FROM collection_entries
            GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
        ORDER BY dc.is_commander DESC, dc.card_name ASC
        """,
        (deck_id,)
    ).fetchall()
    cards = []
    for row in rows:
        d = dict(row)
        # Parse JSON fields
        for f in ("color_identity", "keywords"):
            if isinstance(d.get(f), str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    d[f] = []
        d["image_url"] = (
            f"https://api.scryfall.com/cards/{d['scryfall_id']}?format=image&version=normal"
            if d.get("scryfall_id") else None
        )
        cards.append(d)
    return {"cards": cards, "total": len(cards)}


@router.post("/api/decks/{deck_id}/cards")
async def add_deck_card(deck_id: int, req: AddDeckCardRequest):
    """Add or update a card in the deck."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    # Look up card_name from collection_entries by scryfall_id, fall back to request
    ce_row = conn.execute(
        "SELECT name FROM collection_entries WHERE scryfall_id = ? LIMIT 1",
        (req.scryfall_id,)
    ).fetchone()
    card_name = ce_row["name"] if ce_row else (req.card_name or "")

    # Check if this scryfall_id is already in the deck
    existing = conn.execute(
        "SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
        (deck_id, req.scryfall_id)
    ).fetchone()

    if existing:
        new_qty = existing["quantity"] + (req.quantity or 1)
        conn.execute(
            "UPDATE deck_cards SET quantity = ?, role_tag = ?, is_commander = ? WHERE id = ?",
            (new_qty, req.role_tag or "", req.is_commander or 0, existing["id"])
        )
        conn.commit()
        row = conn.execute("SELECT * FROM deck_cards WHERE id = ?", (existing["id"],)).fetchone()
    else:
        cur = conn.execute(
            """
            INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander, role_tag)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deck_id, req.scryfall_id, card_name,
                req.quantity or 1,
                req.is_commander or 0,
                req.role_tag or ""
            )
        )
        conn.commit()
        row = conn.execute("SELECT * FROM deck_cards WHERE id = ?", (cur.lastrowid,)).fetchone()

    # Update deck updated_at
    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()
    return dict(row)


@router.delete("/api/decks/{deck_id}/cards/{card_id}")
async def remove_deck_card(deck_id: int, card_id: int):
    """Remove a card from a deck."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    row = conn.execute(
        "SELECT id FROM deck_cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Card slot {card_id} not found in deck {deck_id}")
    conn.execute("DELETE FROM deck_cards WHERE id = ?", (card_id,))
    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()
    return {"deleted": True, "card_id": card_id, "deck_id": deck_id}


@router.patch("/api/decks/{deck_id}/cards/{card_id}")
async def patch_deck_card(deck_id: int, card_id: int, req: PatchDeckCardRequest):
    """Update quantity or role_tag for a card in a deck."""
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()
    row = conn.execute(
        "SELECT * FROM deck_cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Card slot {card_id} not found in deck {deck_id}")

    updates = {}
    if req.quantity is not None:
        if req.quantity < 1:
            raise HTTPException(400, "quantity must be >= 1")
        updates["quantity"] = req.quantity
    if req.role_tag is not None:
        updates["role_tag"] = req.role_tag

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE deck_cards SET {set_clause} WHERE id = ?",
            list(updates.values()) + [card_id]
        )
        conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
        conn.commit()

    updated = conn.execute("SELECT * FROM deck_cards WHERE id = ?", (card_id,)).fetchone()
    return dict(updated)


# ── 2.3 Deck Analysis ────────────────────────────────────────────

@router.get("/api/decks/{deck_id}/analysis")
async def deck_analysis(deck_id: int):
    """Analyze deck composition — type counts, mana curve, color pips, roles, targets, deltas."""
    _get_deck_or_404(deck_id)
    return _compute_deck_analysis(deck_id)


# ── 2.5 Recommendations from Collection ───────────────────────

@router.get("/api/decks/{deck_id}/recommended-from-collection")
async def recommend_from_collection(deck_id: int, max_results: int = 20, roles: Optional[str] = None):
    """
    Recommend cards from the user's collection for a deck.
    Finds shortfalls, then scores owned cards by how well they fit.
    """
    deck = _get_deck_or_404(deck_id)
    deck_color_identity = deck.get("color_identity", [])
    conn = _get_db_conn()

    # Run analysis to find shortfalls
    analysis = _compute_deck_analysis(deck_id)
    deltas = analysis["deltas"]
    counts_by_type = analysis["counts_by_type"]

    # Find types that are below their target midpoint (shortfall)
    shortfall_types = set()
    for t, delta in deltas.items():
        lo, hi = _TYPE_TARGETS.get(t, [0, 0])
        if counts_by_type.get(t, 0) < lo:
            shortfall_types.add(t)

    # Get scryfall_ids already in deck to exclude
    in_deck_ids = set(
        r["scryfall_id"] for r in
        conn.execute("SELECT scryfall_id FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
    )

    # Parse role filter
    role_filter = [r.strip() for r in roles.split(",") if r.strip()] if roles else []

    # Query collection for candidate cards
    coll_rows = conn.execute(
        "SELECT * FROM collection_entries WHERE quantity > 0"
    ).fetchall()

    scored = []
    for row in coll_rows:
        card = _row_to_dict(row)
        card_id = card.get("scryfall_id", "")

        # Skip cards already in deck
        if card_id in in_deck_ids:
            continue

        # Color identity check: all card colors must be in deck colors
        card_ci = card.get("color_identity", [])
        if isinstance(card_ci, str):
            try:
                card_ci = json.loads(card_ci)
            except Exception:
                card_ci = []
        if deck_color_identity and card_ci:
            if not all(c in deck_color_identity for c in card_ci):
                continue

        type_line = card.get("type_line", "")
        oracle_text = card.get("oracle_text", "")
        keywords = card.get("keywords", [])
        card_type = _classify_card_type(type_line)
        card_roles = _detect_card_roles(oracle_text, type_line, keywords)

        # Role filter
        if role_filter and not any(r in card_roles for r in role_filter):
            continue

        # Scoring
        score = 0
        # +3 if card type is in shortfall
        if card_type in shortfall_types:
            score += 3
        # +2 per matching role
        for r in card_roles:
            if r in ("Ramp", "Draw", "Removal", "BoardWipe"):
                score += 2
            else:
                score += 1
        # +1 for lower CMC (curve fit)
        cmc = float(card.get("cmc", 0))
        if cmc <= 3:
            score += 1

        scored.append({
            "id": card.get("id"),
            "scryfall_id": card_id,
            "name": card.get("name"),
            "type_line": type_line,
            "card_type": card_type,
            "cmc": cmc,
            "color_identity": card_ci,
            "owned_qty": card.get("quantity", 0),
            "roles": card_roles,
            "score": score,
            "image_url": f"https://api.scryfall.com/cards/{card_id}?format=image&version=normal" if card_id else None,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Group by type
    grouped = {}
    for card in scored[:max_results]:
        ct = card["card_type"]
        grouped.setdefault(ct, []).append(card)

    return {
        "shortfall_types": list(shortfall_types),
        "role_filter": role_filter,
        "grouped": grouped,
        "total": len(scored[:max_results]),
    }


# ── 2.6 EDHREC-style Recommendations ────────────────────────

@router.get("/api/decks/{deck_id}/edh-recs")
async def deck_edh_recs(deck_id: int, only_owned: bool = False, max_results: int = 30):
    """
    Fetch EDHREC average deck recommendations for this deck's commander.
    Cross-references with collection for owned status.
    """
    deck = _get_deck_or_404(deck_id)
    commander_name = deck.get("commander_name", "")
    if not commander_name:
        raise HTTPException(400, "Deck has no commander_name set. Update the deck first.")

    # Cache check
    cache_key = f"edhrec:avg:{_to_edhrec_slug(commander_name)}"
    cached_profile = _edhrec_cache_get(cache_key)
    if cached_profile is None:
        try:
            cached_profile = _fetch_edhrec_average(commander_name)
            _edhrec_cache_set(cache_key, cached_profile)
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch EDHREC data for '{commander_name}': {str(e)}")

    edhrec_profile = cached_profile
    mainboard = edhrec_profile.get("mainboard", {})

    conn = _get_db_conn()

    # Get cards already in deck
    in_deck_names = set(
        r["card_name"].lower() for r in
        conn.execute("SELECT card_name FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
    )

    # Build collection lookup: name (lower) -> {owned, qty, scryfall_id}
    coll_rows = conn.execute(
        "SELECT name, quantity, scryfall_id FROM collection_entries"
    ).fetchall()
    coll_map = {}
    for r in coll_rows:
        key = r["name"].lower()
        existing = coll_map.get(key)
        if not existing or r["quantity"] > existing["qty"]:
            coll_map[key] = {"owned": True, "qty": r["quantity"], "scryfall_id": r["scryfall_id"]}

    # Also look up card details from collection_entries for type/role
    coll_details = {}
    for r in conn.execute("SELECT name, type_line, oracle_text, keywords, scryfall_id FROM collection_entries").fetchall():
        key = r["name"].lower()
        if key not in coll_details:
            coll_details[key] = dict(r)

    results = []
    for card_name in mainboard:
        name_lower = card_name.lower()
        # Skip cards already in deck
        if name_lower in in_deck_names:
            continue

        owned_info = coll_map.get(name_lower, {"owned": False, "qty": 0, "scryfall_id": ""})

        if only_owned and not owned_info["owned"]:
            continue

        # Get type/role from collection if available
        details = coll_details.get(name_lower, {})
        type_line = details.get("type_line", "")
        oracle_text = details.get("oracle_text", "")
        keywords = details.get("keywords", "[]")
        card_roles = _detect_card_roles(oracle_text, type_line, keywords)
        scryfall_id = owned_info.get("scryfall_id") or details.get("scryfall_id", "")

        results.append({
            "name": card_name,
            "type_line": type_line,
            "role": card_roles[0] if card_roles else "Other",
            "roles": card_roles,
            "inclusion_pct": None,  # EDHREC average doesn't expose % directly in this path
            "synergy_score": None,
            "owned": owned_info["owned"],
            "owned_qty": owned_info["qty"],
            "scryfall_id": scryfall_id,
            "image_url": f"https://api.scryfall.com/cards/{scryfall_id}?format=image&version=normal" if scryfall_id else None,
        })

    return {
        "commander": commander_name,
        "source": "EDHREC Average",
        "total": len(results[:max_results]),
        "recommendations": results[:max_results],
    }


# ── 2.7 Bulk Add Operations ────────────────────────────────

def _check_ratio_limit(deck_id: int, card_type: str, count_to_add: int = 1) -> bool:
    """
    Return True if adding count_to_add cards of card_type stays within target max.
    """
    analysis = _compute_deck_analysis(deck_id)
    current = analysis["counts_by_type"].get(card_type, 0)
    target_max = _TYPE_TARGETS.get(card_type, [0, 9999])[1]
    return (current + count_to_add) <= target_max


@router.post("/api/decks/{deck_id}/bulk-add")
async def bulk_add_cards(deck_id: int, req: BulkAddRequest):
    """
    Bulk-add cards to a deck by scryfall_id.
    If respect_ratios, skips cards of a type when the target max is already reached.
    """
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    added = 0
    skipped = 0
    details = []

    for card_entry in req.cards:
        scryfall_id = str(card_entry.get("scryfall_id", "")).strip()
        quantity = int(card_entry.get("quantity", 1))
        if not scryfall_id:
            skipped += 1
            details.append({"scryfall_id": scryfall_id, "status": "skipped", "reason": "missing scryfall_id"})
            continue

        # Look up card name and type from collection
        ce_row = conn.execute(
            "SELECT name, type_line, oracle_text, keywords FROM collection_entries WHERE scryfall_id = ? LIMIT 1",
            (scryfall_id,)
        ).fetchone()
        card_name = ce_row["name"] if ce_row else ""
        type_line = ce_row["type_line"] if ce_row else ""
        card_type = _classify_card_type(type_line)

        if req.respect_ratios and not _check_ratio_limit(deck_id, card_type, quantity):
            skipped += 1
            details.append({
                "scryfall_id": scryfall_id,
                "name": card_name,
                "card_type": card_type,
                "status": "skipped",
                "reason": f"Type '{card_type}' at or above target max",
            })
            continue

        # Upsert
        existing = conn.execute(
            "SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
            (deck_id, scryfall_id)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE deck_cards SET quantity = ? WHERE id = ?",
                (existing["quantity"] + quantity, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity) VALUES (?, ?, ?, ?)",
                (deck_id, scryfall_id, card_name, quantity)
            )
        conn.commit()
        added += 1
        details.append({"scryfall_id": scryfall_id, "name": card_name, "card_type": card_type, "status": "added", "quantity": quantity})

    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()

    analysis = _compute_deck_analysis(deck_id)
    return {"added": added, "skipped": skipped, "details": details, "analysis": analysis}


@router.post("/api/decks/{deck_id}/bulk-add-recommended")
async def bulk_add_recommended(deck_id: int, req: BulkAddRecommendedRequest):
    """
    Fetch recommendations from 'collection' or 'edhrec', filter, and bulk-add to deck.
    """
    _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    source = (req.source or "collection").lower()
    type_filter = [t.strip() for t in req.types] if req.types else []
    role_filter = [r.strip() for r in req.roles] if req.roles else []

    candidates = []

    if source == "collection":
        # Reuse the recommend_from_collection logic
        deck = _get_deck_or_404(deck_id)
        deck_color_identity = deck.get("color_identity", [])
        analysis = _compute_deck_analysis(deck_id)
        counts_by_type = analysis["counts_by_type"]
        shortfall_types = {t for t, (lo, _) in _TYPE_TARGETS.items() if counts_by_type.get(t, 0) < lo}

        in_deck_ids = set(
            r["scryfall_id"] for r in
            conn.execute("SELECT scryfall_id FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
        )
        coll_rows = conn.execute("SELECT * FROM collection_entries WHERE quantity > 0").fetchall()
        for row in coll_rows:
            card = _row_to_dict(row)
            cid = card.get("scryfall_id", "")
            if cid in in_deck_ids:
                continue
            card_ci = card.get("color_identity", [])
            if isinstance(card_ci, str):
                try:
                    card_ci = json.loads(card_ci)
                except Exception:
                    card_ci = []
            if deck_color_identity and card_ci:
                if not all(c in deck_color_identity for c in card_ci):
                    continue
            tl = card.get("type_line", "")
            ct = _classify_card_type(tl)
            card_roles = _detect_card_roles(card.get("oracle_text", ""), tl, card.get("keywords", []))
            if type_filter and ct not in type_filter:
                continue
            if role_filter and not any(r in card_roles for r in role_filter):
                continue
            candidates.append({"scryfall_id": cid, "card_type": ct, "quantity": 1})

    elif source == "edhrec":
        deck = _get_deck_or_404(deck_id)
        commander_name = deck.get("commander_name", "")
        if not commander_name:
            raise HTTPException(400, "Deck has no commander_name set")
        try:
            edhrec_profile = _fetch_edhrec_average(commander_name)
        except Exception as e:
            raise HTTPException(502, f"EDHREC fetch failed: {e}")
        mainboard = edhrec_profile.get("mainboard", {})
        in_deck_names = set(
            r["card_name"].lower() for r in
            conn.execute("SELECT card_name FROM deck_cards WHERE deck_id = ?", (deck_id,)).fetchall()
        )
        coll_rows = conn.execute("SELECT name, scryfall_id, type_line, oracle_text, keywords, quantity FROM collection_entries").fetchall()
        coll_map = {r["name"].lower(): dict(r) for r in coll_rows}

        for card_name in mainboard:
            name_lower = card_name.lower()
            if name_lower in in_deck_names:
                continue
            coll_info = coll_map.get(name_lower)
            if req.only_owned and not coll_info:
                continue
            if not coll_info:
                continue  # can't add without scryfall_id
            scryfall_id = coll_info.get("scryfall_id", "")
            if not scryfall_id:
                continue
            tl = coll_info.get("type_line", "")
            ct = _classify_card_type(tl)
            card_roles = _detect_card_roles(coll_info.get("oracle_text", ""), tl, coll_info.get("keywords", []))
            if type_filter and ct not in type_filter:
                continue
            if role_filter and not any(r in card_roles for r in role_filter):
                continue
            candidates.append({"scryfall_id": scryfall_id, "card_type": ct, "quantity": 1})
    else:
        raise HTTPException(400, f"Unknown source '{source}'. Use 'collection' or 'edhrec'.")

    # Now bulk-add candidates
    added = 0
    skipped = 0
    details = []

    for c in candidates:
        scryfall_id = c["scryfall_id"]
        card_type = c["card_type"]
        quantity = c["quantity"]

        if req.respect_ratios and not _check_ratio_limit(deck_id, card_type, quantity):
            skipped += 1
            details.append({"scryfall_id": scryfall_id, "card_type": card_type, "status": "skipped", "reason": "ratio limit"})
            continue

        ce_row = conn.execute(
            "SELECT name FROM collection_entries WHERE scryfall_id = ? LIMIT 1", (scryfall_id,)
        ).fetchone()
        card_name = ce_row["name"] if ce_row else ""

        existing = conn.execute(
            "SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
            (deck_id, scryfall_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE deck_cards SET quantity = ? WHERE id = ?",
                (existing["quantity"] + quantity, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity) VALUES (?, ?, ?, ?)",
                (deck_id, scryfall_id, card_name, quantity)
            )
        conn.commit()
        added += 1
        details.append({"scryfall_id": scryfall_id, "name": card_name, "card_type": card_type, "status": "added"})

    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()

    analysis = _compute_deck_analysis(deck_id)
    return {"added": added, "skipped": skipped, "details": details, "analysis": analysis}


# ── 2.9 Simulation Export ───────────────────────────────────

@router.post("/api/decks/{deck_id}/export-to-sim")
async def export_deck_to_sim(deck_id: int):
    """
    Export a deck to Forge .dck format and save to the Forge decks directory.
    Returns the deck name for use in simulations.
    """
    deck = _get_deck_or_404(deck_id)
    conn = _get_db_conn()

    card_rows = conn.execute(
        "SELECT card_name, quantity, is_commander FROM deck_cards WHERE deck_id = ? ORDER BY is_commander DESC, card_name ASC",
        (deck_id,)
    ).fetchall()

    if not card_rows:
        raise HTTPException(400, "Deck has no cards to export")

    # Build .dck content
    lines = ["[metadata]"]
    deck_name = deck.get("name", f"Deck {deck_id}")
    lines.append(f"Name={deck_name}")
    lines.append("")

    commanders = [r for r in card_rows if r["is_commander"]]
    mainboard = [r for r in card_rows if not r["is_commander"]]

    lines.append("[Commander]")
    for r in commanders:
        name = r["card_name"] or "Unknown"
        qty = r["quantity"] or 1
        lines.append(f"{qty} {name}")

    lines.append("")
    lines.append("[Main]")
    for r in mainboard:
        name = r["card_name"] or "Unknown"
        qty = r["quantity"] or 1
        lines.append(f"{qty} {name}")

    content = "\n".join(lines)

    # Determine save directory
    safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", deck_name).replace(" ", "_").strip()
    if not safe_name:
        safe_name = f"deck_{deck_id}"

    save_dir = CFG.forge_decks_dir
    if not save_dir or not os.path.isdir(save_dir):
        save_dir = os.path.join(os.path.dirname(__file__), "exported-decks")
        os.makedirs(save_dir, exist_ok=True)

    out_path = Path(save_dir) / f"{safe_name}.dck"
    out_path.write_text(content, encoding="utf-8")
    log_deckgen.info(f"  Exported deck {deck_id} to {out_path}")

    return {
        "success": True,
        "deckName": safe_name,
        "dckFile": str(out_path),
        "totalCards": sum(r["quantity"] for r in card_rows),
        "commanderCount": len(commanders),
        "mainboardCount": len(mainboard),
    }


# ══════════════════════════════════════════════════════════════
# Deck Import Endpoint
# ══════════════════════════════════════════════════════════════


def _parse_decklist_text(text: str) -> dict:
    """
    Parse a decklist from text. Supports:
      - Forge .dck format with [Commander], [Deck], [Main] sections
      - MTGA format: 1 Card Name
      - Plain: Card Name (assumed qty 1)
      - Lines starting with // or # are comments
    Returns { 'commanders': [{'name': str, 'qty': int}], 'cards': [{'name': str, 'qty': int}] }
    """
    commanders = []
    cards = []
    section = 'main'  # default section

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('//') or line.startswith('#'):
            continue

        # Section headers
        low = line.lower()
        if low.startswith('[commander'):
            section = 'commander'
            continue
        if low.startswith('[deck') or low.startswith('[main') or low.startswith('[mainboard'):
            section = 'main'
            continue
        if low.startswith('[sideboard') or low.startswith('[side') or low.startswith('[metadata'):
            section = 'skip'
            continue
        if low.startswith('['):
            # Unknown section, treat as main
            section = 'main'
            continue

        if section == 'skip':
            continue

        # Parse quantity + name
        m = re.match(r'^(\d+)\s*[xX]?\s+(.+)$', line)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip()
        else:
            qty = 1
            name = line

        # Strip set codes like "(M21)" or "(M21) 123" from MTGA exports
        name = re.sub(r'\s*\([A-Z0-9]+\)\s*\d*\s*$', '', name).strip()

        if not name:
            continue

        if section == 'commander':
            commanders.append({'name': name, 'qty': qty})
        else:
            cards.append({'name': name, 'qty': qty})

    return {'commanders': commanders, 'cards': cards}


@router.post('/api/decks/{deck_id}/import')
async def import_decklist(deck_id: int, request: FastAPIRequest):
    """
    Import a decklist into an existing deck. Parses text, looks up each card
    on Scryfall, and adds them to the deck.

    Body: { "text": "1 Sol Ring\n1 Cultivate..." , "clearFirst": false }
    """
    deck = _get_deck_or_404(deck_id)
    body = await request.json()
    text = body.get('text', '')
    clear_first = body.get('clearFirst', False)

    if not text.strip():
        return JSONResponse({'error': 'No decklist text provided'}, status_code=400)

    parsed = _parse_decklist_text(text)
    all_entries = []
    for c in parsed['commanders']:
        all_entries.append({**c, 'is_commander': True})
    for c in parsed['cards']:
        all_entries.append({**c, 'is_commander': False})

    if not all_entries:
        return JSONResponse({'error': 'No cards found in decklist'}, status_code=400)

    conn = _get_db_conn()

    # Optionally clear existing cards
    if clear_first:
        conn.execute('DELETE FROM deck_cards WHERE deck_id = ?', (deck_id,))
        conn.commit()

    added = 0
    failed = []
    results = []

    for entry in all_entries:
        name = entry['name']
        qty = entry['qty']
        is_cmd = entry['is_commander']

        # Look up on Scryfall
        sf = _scryfall_fuzzy_lookup(name)
        if not sf:
            failed.append(name)
            results.append({'name': name, 'status': 'not_found'})
            continue

        scryfall_id = sf.get('id', '')
        resolved_name = sf.get('name', name)

        # Check if already in deck
        existing = conn.execute(
            'SELECT id, quantity FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?',
            (deck_id, scryfall_id)
        ).fetchone()

        if existing:
            conn.execute(
                'UPDATE deck_cards SET quantity = ?, is_commander = ? WHERE id = ?',
                (existing['quantity'] + qty, 1 if is_cmd else existing.get('is_commander', 0), existing['id'])
            )
        else:
            conn.execute(
                'INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander) VALUES (?, ?, ?, ?, ?)',
                (deck_id, scryfall_id, resolved_name, qty, 1 if is_cmd else 0)
            )
        conn.commit()
        added += 1
        results.append({'name': resolved_name, 'qty': qty, 'status': 'added', 'isCommander': is_cmd})

    # Update commander on deck record if we found one
    cmd_entries = [r for r in results if r.get('isCommander')]
    if cmd_entries:
        cmd_name = cmd_entries[0]['name']
        # Look up scryfall_id from the deck_cards we just inserted
        cmd_row = conn.execute(
            'SELECT scryfall_id FROM deck_cards WHERE deck_id = ? AND is_commander = 1 LIMIT 1',
            (deck_id,)
        ).fetchone()
        cmd_sf_id = cmd_row['scryfall_id'] if cmd_row else ''
        conn.execute(
            'UPDATE decks SET commander_name = ?, commander_scryfall_id = ?, updated_at = datetime(\'now\') WHERE id = ?',
            (cmd_name, cmd_sf_id, deck_id)
        )
    else:
        conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
    conn.commit()

    return {
        'added': added,
        'failed': len(failed),
        'failedNames': failed,
        'total': len(all_entries),
        'results': results,
    }


@router.post('/api/decks/import-new')
async def import_decklist_new(request: FastAPIRequest):
    """
    Import a decklist as a brand-new deck. Creates the deck, then imports cards.

    Body: { "text": "...", "name": "My Deck" }
    """
    body = await request.json()
    text = body.get('text', '')
    deck_name = body.get('name', '').strip()

    if not text.strip():
        return JSONResponse({'error': 'No decklist text provided'}, status_code=400)

    parsed = _parse_decklist_text(text)
    all_entries = []
    for c in parsed['commanders']:
        all_entries.append({**c, 'is_commander': True})
    for c in parsed['cards']:
        all_entries.append({**c, 'is_commander': False})

    if not all_entries:
        return JSONResponse({'error': 'No cards found in decklist'}, status_code=400)

    # Auto-name from first commander if no name given
    if not deck_name:
        cmd = parsed['commanders'][0]['name'] if parsed['commanders'] else None
        deck_name = cmd or 'Imported Deck'

    conn = _get_db_conn()
    cur = conn.execute(
        "INSERT INTO decks (name, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))",
        (deck_name,)
    )
    conn.commit()
    new_deck_id = cur.lastrowid

    # Set commander on the deck if we have one
    first_cmd_scryfall = None
    first_cmd_name = None

    added = 0
    failed = []

    for entry in all_entries:
        name = entry['name']
        qty = entry['qty']
        is_cmd = entry['is_commander']

        sf = _scryfall_fuzzy_lookup(name)
        if not sf:
            failed.append(name)
            continue

        scryfall_id = sf.get('id', '')
        resolved_name = sf.get('name', name)

        if is_cmd and not first_cmd_scryfall:
            first_cmd_scryfall = scryfall_id
            first_cmd_name = resolved_name

        conn.execute(
            'INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity, is_commander) VALUES (?, ?, ?, ?, ?)',
            (new_deck_id, scryfall_id, resolved_name, qty, 1 if is_cmd else 0)
        )
        conn.commit()
        added += 1

    # Update commander on deck record
    if first_cmd_scryfall:
        conn.execute(
            'UPDATE decks SET commander_name = ?, commander_scryfall_id = ? WHERE id = ?',
            (first_cmd_name, first_cmd_scryfall, new_deck_id)
        )
        conn.commit()

    return {
        'deckId': new_deck_id,
        'deckName': deck_name,
        'added': added,
        'failed': len(failed),
        'failedNames': failed,
        'total': len(all_entries),
    }


# ══════════════════════════════════════════════════════════════
# Card Scanner Endpoint
# ══════════════════════════════════════════════════════════════

def _scryfall_fuzzy_lookup(name: str) -> Optional[dict]:
    """
    Fuzzy-search Scryfall for a card name (used by the scanner pipeline).
    Returns the raw Scryfall JSON dict, or None on failure.
    """
    _scryfall_rate_limit()
    try:
        encoded = quote(name)
        url = f"https://api.scryfall.com/cards/named?fuzzy={encoded}"
        req = Request(url, headers=_API_HEADERS)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("object") == "error":
            return None
        return data
    except Exception:
        return None
