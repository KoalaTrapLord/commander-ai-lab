"""
routes/coach.py
===============
LLM-powered deck coaching endpoints:
  GET  /api/coach/status
  GET  /api/coach/decks
  GET  /api/coach/decks/{deck_id}/report
  POST /api/coach/decks/{deck_id}
  GET  /api/coach/sessions
  GET  /api/coach/sessions/{session_id}
  POST /api/coach/embeddings/download
  GET  /api/coach/embeddings/search
  POST /api/coach/chat
  POST /api/coach/apply
  GET  /api/coach/cards-like
  POST /api/coach/reports/generate

Globals:
  _coach_service, _coach_embeddings, _coach_llm
  _deck_gen_v3, _deck_gen_v3_error
  init_coach_service(), _build_deck_report_from_db()
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routes.shared import (
    CFG,
    log_coach, log_deckgen,
    _get_db_conn,
    _compute_deck_analysis,
)

router = APIRouter(tags=["coach"])


# ══════════════════════════════════════════════════════════════
# Coach Service (LLM-powered deck coaching)
# ══════════════════════════════════════════════════════════════

# Global coach instances (initialized at startup)
_coach_service = None
_coach_embeddings = None
_coach_llm = None
_deck_gen_v3 = None  # V3 Deck Generator (Perplexity structured output)
_deck_gen_v3_error = None  # Error message if V3 init failed


def init_coach_service():
    """Initialize the coach service with LLM client and embeddings."""
    global _coach_service, _coach_embeddings, _coach_llm, _deck_gen_v3, _deck_gen_v3_error
    try:
        from coach.llm_client import LMStudioClient
        from coach.embeddings import MTGEmbeddingIndex
        from coach.coach_service import CoachService
        from coach.config import ensure_dirs

        ensure_dirs()

        _coach_llm = LMStudioClient()
        _coach_embeddings = MTGEmbeddingIndex()

        # Try to load embeddings (non-blocking — download happens on first use)
        try:
            from coach.config import EMBEDDINGS_NPZ
            if EMBEDDINGS_NPZ.exists():
                _coach_embeddings.load()
                log_coach.info(f"  Coach:        Embeddings loaded ({_coach_embeddings.card_count} cards)")
            else:
                log_coach.warning("  Coach:        Embeddings not yet downloaded (will download on first use)")
        except Exception as e:
            log_coach.error(f"  Coach:        Embeddings load failed: {e}")

        _coach_service = CoachService(_coach_llm, _coach_embeddings)

        # Check LLM connection
        llm_status = _coach_llm.check_connection()
        if llm_status.get("connected"):
            log_coach.info(f"  Coach LLM:    Connected ({llm_status.get('active_model', 'unknown')})")
        else:
            log_coach.warning(f"  Coach LLM:    Not connected (start LM Studio on 192.168.0.122:1234)")

        log_coach.info("  Coach:        Service initialized")

        # Initialize V3 Deck Generator (Perplexity)
        _deck_gen_v3_error = None
        if CFG.pplx_api_key:
            try:
                from coach.clients.perplexity_client import PerplexityClient
                from coach.services.deck_generator import DeckGeneratorV3
                from coach.config import DECK_GEN_MODEL

                pplx_client = PerplexityClient(
                    api_key=CFG.pplx_api_key,
                    model=DECK_GEN_MODEL,
                )
                _deck_gen_v3 = DeckGeneratorV3(
                    pplx_client=pplx_client,
                    db_conn_factory=_get_db_conn,
                    embedding_index=_coach_embeddings,
                )
                log_deckgen.info(f"  Deck Gen V3:  Initialized (model: {DECK_GEN_MODEL})")
            except ImportError as e:
                _deck_gen_v3_error = f"Missing dependency: {e}. Run: pip install openai"
                log_deckgen.error(f"  Deck Gen V3:  {_deck_gen_v3_error}")
                _deck_gen_v3 = None
            except Exception as e:
                _deck_gen_v3_error = str(e)
                log_deckgen.error(f"  Deck Gen V3:  Failed to initialize: {e}")
                _deck_gen_v3 = None
        else:
            _deck_gen_v3_error = "PPLX_API_KEY not set"
            log_deckgen.info("  Deck Gen V3:  Skipped (no PPLX_API_KEY)")

    except Exception as e:
        log_coach.error(f"  Coach:        Failed to initialize: {e}")
        _coach_service = None


@router.get("/api/coach/status")
async def coach_status():
    """Check coach subsystem health."""
    if _coach_service is None:
        return {"llmConnected": False, "embeddingsLoaded": False,
                "embeddingCards": 0, "deckReportsAvailable": 0,
                "error": "Coach service not initialized"}
    status = _coach_service.get_status()
    return status.model_dump()


@router.get("/api/coach/decks")
async def coach_list_decks():
    """List all decks available for coaching (from deck builder DB)."""
    conn = _get_db_conn()
    rows = conn.execute(
        """SELECT d.id as deck_id, d.name as deck_name, d.commander_name,
                  COUNT(dc.id) as card_count
           FROM decks d
           LEFT JOIN deck_cards dc ON dc.deck_id = d.id
           GROUP BY d.id
           ORDER BY d.name"""
    ).fetchall()

    # Also get report availability from coach service
    report_ids = set()
    if _coach_service:
        report_ids = set(_coach_service.list_deck_reports())

    decks = []
    for r in rows:
        deck_name = r["deck_name"]
        # Check if a report exists (by deck name slug match)
        has_report = any(
            deck_name.lower().replace(" ", "-") == rid.lower() or
            deck_name.lower() == rid.lower()
            for rid in report_ids
        )
        decks.append({
            "deck_id": r["deck_id"],
            "deck_name": r["deck_name"],
            "commander": r["commander_name"] or "",
            "card_count": r["card_count"],
            "has_report": has_report,
            "report_count": 1 if has_report else 0,
            "last_report_date": None,
        })
    return decks


@router.get("/api/coach/decks/{deck_id}/report")
async def coach_get_report(deck_id: str):
    """Get the latest DeckReport for a deck."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")
    report = _coach_service.load_deck_report(deck_id)
    if report is None:
        raise HTTPException(404, f"Deck report not found: {deck_id}")
    return report.model_dump()


class CoachRequestBody(BaseModel):
    goals: Optional[dict] = None


class CoachChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class CoachChatRequest(BaseModel):
    deck_id: str
    messages: list[dict]  # conversation history [{role, content}]
    goals: Optional[dict] = None
    stream: Optional[bool] = False

class CoachApplyRequest(BaseModel):
    session_id: str
    deck_id: int  # numeric deck ID in the DB
    accepted_cuts: list[str] = []  # card names to remove
    accepted_adds: list[str] = []  # card names to add

class CoachGoalsRequest(BaseModel):
    target_power_level: Optional[int] = None  # 1-10
    meta_focus: Optional[str] = None  # aggro, control, combo, midrange, stax
    budget: Optional[str] = None  # budget, medium, no-limit
    focus_areas: list[str] = []  # e.g., ["ramp", "card draw"]


@router.post("/api/coach/decks/{deck_id}")
async def coach_run_session(deck_id: str, body: CoachRequestBody = None):
    """Trigger a coaching session for a deck."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")

    # Load embeddings on first use if not loaded
    if _coach_embeddings and not _coach_embeddings.loaded:
        try:
            _coach_embeddings.load(force_download=True)
        except Exception as e:
            log_coach.error(f"  Coach: Embeddings download failed: {e}")

    goals = None
    if body and body.goals:
        from coach.models import CoachGoals
        try:
            goals = CoachGoals(**body.goals)
        except Exception:
            goals = None

    # Build a fallback DeckReport from the DB if no simulation report exists
    fallback_report = None
    try:
        fallback_report = _build_deck_report_from_db(deck_id)
    except Exception as e:
        log_coach.error(f"  Coach: Fallback report build failed for '{deck_id}': {e}")

    try:
        session = await _coach_service.run_coaching_session(deck_id, goals, fallback_report=fallback_report)
        return session.model_dump()
    except ValueError as e:
        raise HTTPException(404, str(e))
    except ConnectionError as e:
        raise HTTPException(503, f"LLM connection failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Coach session failed: {e}")


def _build_deck_report_from_db(deck_slug: str):
    """
    Build a lightweight DeckReport from the deck builder DB when no
    simulation report exists. Allows the coach to analyze deck composition
    even without simulation data.
    """
    from coach.models import DeckReport, CardPerformance, DeckStructure
    conn = _get_db_conn()

    # Find the deck by slug match against the deck name
    rows = conn.execute(
        "SELECT id, name, commander_name, color_identity FROM decks ORDER BY id"
    ).fetchall()

    matched_deck = None
    for r in rows:
        name = r["name"] or ""
        slug = name.lower().replace(" ", "-")
        # Also try a more thorough slugify
        import re
        clean_slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if slug == deck_slug.lower() or clean_slug == deck_slug.lower() or name.lower() == deck_slug.lower():
            matched_deck = r
            break

    if matched_deck is None:
        return None

    deck_id = matched_deck["id"]
    deck_name = matched_deck["name"]
    commander = matched_deck["commander_name"] or ""

    # Parse color identity
    ci_raw = matched_deck["color_identity"] or "[]"
    try:
        color_identity = json.loads(ci_raw) if isinstance(ci_raw, str) else ci_raw
    except Exception:
        color_identity = []

    # Load all cards in this deck
    card_rows = conn.execute(
        """SELECT dc.card_name, dc.quantity, dc.is_commander, dc.role_tag,
                  ce.type_line, ce.cmc, ce.oracle_text
           FROM deck_cards dc
           LEFT JOIN collection_entries ce ON LOWER(dc.card_name) = LOWER(ce.name)
           WHERE dc.deck_id = ?""",
        (deck_id,)
    ).fetchall()

    cards = []
    type_counts = {}
    cmc_buckets = [0] * 8
    land_count = 0

    for cr in card_rows:
        card_name = cr["card_name"] or ""
        type_line = cr["type_line"] or ""
        cmc = cr["cmc"] or 0
        qty = cr["quantity"] or 1
        role_tag = cr["role_tag"] or ""

        # Build tags from type_line and role_tag
        tags = []
        if role_tag:
            tags.append(role_tag)
        if "Land" in type_line:
            tags.append("land")
            land_count += qty
        elif "Creature" in type_line:
            tags.append("creature")
        elif "Instant" in type_line:
            tags.append("instant")
        elif "Sorcery" in type_line:
            tags.append("sorcery")
        elif "Artifact" in type_line:
            tags.append("artifact")
        elif "Enchantment" in type_line:
            tags.append("enchantment")
        elif "Planeswalker" in type_line:
            tags.append("planeswalker")

        # Type count
        for t in ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Land"]:
            if t in type_line:
                type_counts[t] = type_counts.get(t, 0) + qty

        # CMC bucket
        bucket = min(int(cmc), 7)
        cmc_buckets[bucket] += qty

        # CardPerformance with zeroed-out sim stats
        cards.append(CardPerformance(
            name=card_name,
            drawnRate=0.0,
            castRate=0.0,
            impactScore=0.0,
            tags=tags,
        ))

    slug = deck_slug
    return DeckReport(
        deckId=slug,
        commander=commander,
        colorIdentity=color_identity,
        cards=cards,
        structure=DeckStructure(
            landCount=land_count,
            curveBuckets=cmc_buckets,
            cardTypeCounts=type_counts,
        ),
    )


@router.get("/api/coach/sessions")
async def coach_list_sessions(deck_id: str = None):
    """List all coaching sessions, optionally filtered by deck."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")
    return {"sessions": _coach_service.list_sessions(deck_id)}


@router.get("/api/coach/sessions/{session_id}")
async def coach_get_session(session_id: str):
    """Get a specific coaching session."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")
    session = _coach_service.load_session(session_id)
    if session is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    return session.model_dump()


@router.post("/api/coach/embeddings/download")
async def coach_download_embeddings():
    """Download and convert MTG card embeddings from HuggingFace."""
    if _coach_embeddings is None:
        raise HTTPException(500, "Coach service not initialized")
    try:
        _coach_embeddings.load(force_download=True)
        return {
            "success": True,
            "cards": _coach_embeddings.card_count,
            "message": f"Loaded {_coach_embeddings.card_count} card embeddings"
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to download embeddings: {e}")


@router.get("/api/coach/embeddings/search")
async def coach_search_similar(card: str, colors: str = None, top_n: int = 10):
    """Search for similar cards by name."""
    if _coach_embeddings is None or not _coach_embeddings.loaded:
        raise HTTPException(503, "Embeddings not loaded")
    color_filter = list(colors.upper()) if colors else None
    matches = _coach_embeddings.search_similar(
        query_card=card, color_filter=color_filter, top_n=top_n
    )
    return {"query": card, "matches": [m.to_dict() for m in matches]}


@router.post("/api/coach/chat")
async def coach_chat(body: CoachChatRequest):
    """Multi-turn coaching chat. Sends conversation history to LLM and returns response."""
    if _coach_service is None:
        raise HTTPException(500, "Coach service not initialized")

    # Load deck report for context
    report = _coach_service.load_deck_report(body.deck_id)

    # Build system prompt with report context
    from coach.prompt_template import build_system_prompt
    from coach.models import CoachGoals

    goals = None
    if body.goals:
        try:
            goals = CoachGoals(**body.goals)
        except Exception:
            goals = None

    system_prompt = ""
    if report:
        system_prompt = build_system_prompt(report, goals)
    else:
        system_prompt = (
            "You are an expert Magic: The Gathering Commander deck coach. "
            "Answer questions about deck building, strategy, card choices, and game theory. "
            "Be specific and actionable in your advice."
        )

    # Build messages array for LLM
    messages = [{"role": "system", "content": system_prompt}]
    for msg in body.messages:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    # Call LLM with multi-turn messages
    try:
        import json
        from urllib.request import urlopen, Request as UrlRequest
        from coach.config import LM_STUDIO_URL, LM_STUDIO_TIMEOUT

        model_name = _coach_llm._resolve_model()
        llm_body = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        if body.stream:
            # SSE streaming response
            llm_body["stream"] = True

            async def generate():
                import asyncio
                def _stream():
                    req = UrlRequest(
                        f"{_coach_llm.base_url}/chat/completions",
                        data=json.dumps(llm_body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    import http.client
                    import urllib.parse
                    parsed = urllib.parse.urlparse(f"{_coach_llm.base_url}/chat/completions")
                    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=LM_STUDIO_TIMEOUT)
                    conn.request("POST", parsed.path, body=json.dumps(llm_body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
                    resp = conn.getresponse()
                    chunks = []
                    while True:
                        line = resp.readline()
                        if not line:
                            break
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                chunks.append("[DONE]")
                                break
                            chunks.append(data)
                    conn.close()
                    return chunks

                loop = asyncio.get_event_loop()
                chunks = await loop.run_in_executor(None, _stream)

                for chunk_str in chunks:
                    if chunk_str == "[DONE]":
                        yield f"data: [DONE]\n\n"
                        break
                    try:
                        chunk = json.loads(chunk_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            # Strip think tags from streaming chunks
                            yield f"data: {json.dumps({'content': content})}\n\n"
                    except json.JSONDecodeError:
                        continue

            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            # Non-streaming: regular call
            req = UrlRequest(
                f"{_coach_llm.base_url}/chat/completions",
                data=json.dumps(llm_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            import asyncio
            loop = asyncio.get_event_loop()
            def _call():
                with urlopen(req, timeout=LM_STUDIO_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            raw = await loop.run_in_executor(None, _call)

            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            # Strip think tags
            content = _coach_llm._strip_think_tags(content)
            usage = raw.get("usage", {})

            return {
                "content": content,
                "model": raw.get("model", ""),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }

    except Exception as e:
        raise HTTPException(500, f"Chat failed: {e}")


@router.post("/api/coach/apply")
async def coach_apply_suggestions(body: CoachApplyRequest):
    """Apply accepted coaching suggestions to a deck — remove cuts, add adds."""
    conn = _get_db_conn()

    # Verify deck exists
    deck = conn.execute("SELECT * FROM decks WHERE id = ?", (body.deck_id,)).fetchone()
    if not deck:
        raise HTTPException(404, f"Deck {body.deck_id} not found")

    results = {"cuts": [], "adds": [], "errors": []}

    # Process cuts: remove cards by name
    for card_name in body.accepted_cuts:
        row = conn.execute(
            "SELECT id FROM deck_cards WHERE deck_id = ? AND card_name = ? LIMIT 1",
            (body.deck_id, card_name)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM deck_cards WHERE id = ?", (row["id"],))
            results["cuts"].append({"name": card_name, "status": "removed"})
        else:
            # Try case-insensitive
            row = conn.execute(
                "SELECT id, card_name FROM deck_cards WHERE deck_id = ? AND LOWER(card_name) = LOWER(?) LIMIT 1",
                (body.deck_id, card_name)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM deck_cards WHERE id = ?", (row["id"],))
                results["cuts"].append({"name": row["card_name"], "status": "removed"})
            else:
                results["errors"].append({"name": card_name, "error": "Card not found in deck"})

    # Process adds: look up in collection first, then Scryfall
    for card_name in body.accepted_adds:
        # Try to find in collection
        ce = conn.execute(
            "SELECT scryfall_id, name FROM collection_entries WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (card_name,)
        ).fetchone()

        scryfall_id = None
        resolved_name = card_name

        if ce:
            scryfall_id = ce["scryfall_id"]
            resolved_name = ce["name"]
        else:
            # Try Scryfall API lookup
            try:
                import urllib.parse
                encoded = urllib.parse.quote(card_name)
                scry_req = UrlRequest(
                    f"https://api.scryfall.com/cards/named?fuzzy={encoded}",
                    headers={"User-Agent": "commander-ai-lab/1.0"}
                )
                with urlopen(scry_req, timeout=10) as resp:
                    card_data = json.loads(resp.read().decode("utf-8"))
                    scryfall_id = card_data.get("id")
                    resolved_name = card_data.get("name", card_name)
            except Exception:
                pass

        if scryfall_id:
            # Check if already in deck
            existing = conn.execute(
                "SELECT id FROM deck_cards WHERE deck_id = ? AND scryfall_id = ?",
                (body.deck_id, scryfall_id)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO deck_cards (deck_id, scryfall_id, card_name, quantity) VALUES (?, ?, ?, 1)",
                    (body.deck_id, scryfall_id, resolved_name)
                )
                results["adds"].append({"name": resolved_name, "scryfall_id": scryfall_id, "status": "added"})
            else:
                results["adds"].append({"name": resolved_name, "status": "already_in_deck"})
        else:
            results["errors"].append({"name": card_name, "error": "Could not resolve card"})

    conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (body.deck_id,))
    conn.commit()

    results["total_cuts"] = len(results["cuts"])
    results["total_adds"] = len([a for a in results["adds"] if a["status"] == "added"])
    return results


@router.get("/api/coach/cards-like")
async def coach_cards_like(card: str, colors: str = None, top_n: int = 10):
    """Find cards similar to a given card using embeddings. UI-friendly version."""
    if _coach_embeddings is None or not _coach_embeddings.loaded:
        raise HTTPException(503, "Embeddings not loaded")

    color_filter = list(colors.upper()) if colors else None
    matches = _coach_embeddings.search_similar(
        query_card=card, color_filter=color_filter, top_n=top_n
    )

    conn = _get_db_conn()
    results = []
    for m in matches:
        # Check if card is in collection
        owned = conn.execute(
            "SELECT SUM(quantity) as qty FROM collection_entries WHERE LOWER(name) = LOWER(?)",
            (m.name,)
        ).fetchone()
        owned_qty = (owned["qty"] or 0) if owned else 0

        # Get image URL and price
        ce = conn.execute(
            "SELECT image_url, tcg_price FROM collection_entries WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (m.name,)
        ).fetchone()

        results.append({
            "name": m.name,
            "similarity": round(m.similarity, 4),
            "types": m.types,
            "mana_value": m.mana_value,
            "mana_cost": m.mana_cost,
            "text": m.text[:200] if m.text else "",
            "owned_qty": owned_qty,
            "image_url": ce["image_url"] if ce else None,
            "tcg_price": ce["tcg_price"] if ce else None,
        })

    return {"query": card, "results": results}


@router.post("/api/coach/reports/generate")
async def coach_generate_reports():
    """Rebuild all deck reports from batch result JSONs in results/."""
    try:
        from coach.report_generator import generate_deck_reports
        lab_root = Path(__file__).parent
        results_dir = str(lab_root / CFG.results_dir)
        reports_dir = str(lab_root / "deck-reports")
        updated = generate_deck_reports(results_dir, reports_dir)
        return {
            "status": "ok",
            "decksUpdated": updated,
            "count": len(updated),
            "message": f"Generated reports for {len(updated)} decks" if updated else "No batch results found",
        }
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}")


