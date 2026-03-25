"""
Commander AI Lab — Coach Service
═════════════════════════════════
Main orchestrator: loads deck reports, identifies underperformers,
finds replacement candidates via embeddings, builds prompts,
calls the LLM, parses responses, and persists coaching sessions.
"""

import json
import logging
import uuid
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

from .config import (
    DECK_REPORTS_DIR, COACH_SESSIONS_DIR,
    MAX_UNDERPERFORMERS, MAX_CANDIDATES_PER_UNDERPERFORMER,
    COACH_PROVIDER, PPLX_MODEL,
    UNDERPERFORMER_IMPACT_THRESHOLD, ensure_dirs,
)
from .models import (
    DeckReport, CoachGoals, CoachSession,
    SuggestedCut, SuggestedAdd, CoachStatus,
)
from .llm_client import LLMClient
from .embeddings import MTGEmbeddingIndex
from .prompt_template import build_system_prompt, build_user_prompt

logger = logging.getLogger("coach.service")

# SQLite persistence for coach sessions
try:
    from services.database import (
        save_coach_session as _db_save_session,
        load_coach_session as _db_load_session,
        list_coach_sessions as _db_list_sessions,
        delete_coach_session as _db_delete_session,
    )
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


class CoachService:
    """
    Deck coaching service powered by local LLM and card embeddings.

    Usage:
        embeddings = MTGEmbeddingIndex()
        embeddings.load()
        llm = LLMClient()
        coach = CoachService(llm, embeddings)
        session = await coach.run_coaching_session("edgar-markov")
    """

    def __init__(self, llm: LLMClient, embeddings: MTGEmbeddingIndex):
        self.llm = llm
        self.embeddings = embeddings
        ensure_dirs()

    # ── Deck Report I/O ────────────────────────────────────────

    def load_deck_report(self, deck_id: str) -> Optional[DeckReport]:
        """Load a deck report from disk."""
        # Try exact filename first, then case-insensitive search
        report_path = DECK_REPORTS_DIR / f"{deck_id}.json"
        if not report_path.exists():
            # Try case-insensitive match
            for f in DECK_REPORTS_DIR.glob("*.json"):
                if re.sub(r'[^a-z0-9]', '', f.stem.lower()) == re.sub(r'[^a-z0-9]', '', deck_id.lower()):
                    report_path = f
                    break

        if not report_path.exists():
            logger.warning("Deck report not found: %s", deck_id)
            return None

        try:
            with open(report_path, "r") as f:
                data = json.load(f)
            return DeckReport(**data)
        except Exception as e:
            logger.error("Failed to load deck report %s: %s", deck_id, e)
            return None

    def list_deck_reports(self) -> List[str]:
        """List all available deck report IDs."""
        if not DECK_REPORTS_DIR.exists():
            return []
        return [f.stem for f in DECK_REPORTS_DIR.glob("*.json")]

    # ── Coach Session I/O ──────────────────────────────────────

    def save_session(self, session: CoachSession) -> Path:
        """Persist a coaching session to disk and SQLite."""
        # 1. Write JSON file (backward compat)
        COACH_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = COACH_SESSIONS_DIR / f"{session.sessionId}.json"
        with open(path, "w") as f:
            f.write(session.model_dump_json(indent=2))
        # 2. Write to SQLite
        if _DB_AVAILABLE:
            try:
                _db_save_session({
                    "session_id": session.sessionId,
                    "deck_id": session.deckId,
                    "timestamp": session.timestamp,
                    "model_used": session.modelUsed or "",
                    "prompt_tokens": session.promptTokens or 0,
                    "completion_tokens": session.completionTokens or 0,
                    "summary": session.summary or "",
                    "goals_json": json.dumps(session.goals.model_dump() if session.goals else {}),
                    "cuts_json": json.dumps([c.model_dump() for c in session.suggestedCuts]),
                    "adds_json": json.dumps([a.model_dump() for a in session.suggestedAdds]),
                    "heuristic_hints_json": json.dumps(session.heuristicHints or []),
                    "mana_base_advice": session.manaBaseAdvice or "",
                    "raw_text": session.rawTextExplanation or "",
                })
                logger.info("Coach session persisted to SQLite: %s", session.sessionId)
            except Exception as e:
                logger.warning("Failed to persist session to SQLite: %s", e)
        return path


    def load_session(self, session_id: str) -> Optional[CoachSession]:
        """Load a coaching session from SQLite, falling back to disk."""
        # Try SQLite first
        if _DB_AVAILABLE:
            try:
                row = _db_load_session(session_id)
                if row:
                    data = dict(row)
                    return CoachSession(
                        sessionId=data["session_id"],
                        deckId=data["deck_id"],
                        timestamp=data["timestamp"],
                        modelUsed=data.get("model_used", ""),
                        promptTokens=data.get("prompt_tokens", 0),
                        completionTokens=data.get("completion_tokens", 0),
                        summary=data.get("summary", ""),
                        goals=json.loads(data["goals_json"]) if data.get("goals_json") and data["goals_json"] != "{}" else None,
                        suggestedCuts=[SuggestedCut(**c) for c in json.loads(data.get("cuts_json", "[]"))],
                        suggestedAdds=[SuggestedAdd(**a) for a in json.loads(data.get("adds_json", "[]"))],
                        heuristicHints=json.loads(data.get("heuristic_hints_json", "[]")),
                        manaBaseAdvice=data.get("mana_base_advice", ""),
                        rawTextExplanation=data.get("raw_text", ""),
                    )
            except Exception as e:
                logger.warning("SQLite load failed for %s: %s", session_id, e)
        # Fallback to disk
        path = COACH_SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return CoachSession(**data)
        except Exception as e:
            logger.error("Failed to load session %s: %s", session_id, e)
            return None


    def list_sessions(self, deck_id: str = None) -> List[dict]:
        """List coaching sessions from SQLite, falling back to disk."""
        # Try SQLite first
        if _DB_AVAILABLE:
            try:
                rows = _db_list_sessions(deck_id)
                if rows is not None:
                    return rows
            except Exception as e:
                logger.warning("SQLite list_sessions failed: %s", e)
        # Fallback to disk
        if not COACH_SESSIONS_DIR.exists():
            return []
        sessions = []
        for f in sorted(COACH_SESSIONS_DIR.glob("*.json"), reverse=True):
            try:
                with open(f, "r") as fh:
                    data = json.load(fh)
                if deck_id and data.get("deckId", "") != deck_id:
                    continue
                sessions.append({
                    "sessionId": data.get("sessionId", f.stem),
                    "deckId": data.get("deckId", ""),
                    "timestamp": data.get("timestamp", ""),
                    "summary": data.get("summary", "")[:100],
                    "cutsCount": len(data.get("suggestedCuts", [])),
                    "addsCount": len(data.get("suggestedAdds", [])),
                })
            except Exception:
                continue
        return sessions


    # ── Main Coaching Pipeline ─────────────────────────────────

    async def run_coaching_session(self, deck_id: str,
                                    goals: Optional[CoachGoals] = None,
                                    fallback_report: Optional[DeckReport] = None,
                                    ) -> CoachSession:
        """
        Full coaching pipeline:
        1. Load deck report (or use fallback from DB card list)
        2. Identify underperformers
        3. Find replacement candidates via embeddings
        4. Build prompt
        5. Call LLM
        6. Parse response
        7. Persist session
        """
        # 0. Auto-load embeddings if not loaded
        if not self.embeddings.loaded:
            logger.info("Embeddings not loaded — attempting auto-load...")
            try:
                loaded = self.embeddings.load()
                if loaded:
                    logger.info("Embeddings auto-loaded: %d cards", self.embeddings.card_count)
                else:
                    logger.warning("Embeddings auto-load returned False")
            except Exception as e:
                logger.warning("Embeddings auto-load failed: %s", e)

        # 1. Load deck report — try simulation report first, then fallback
        report = self.load_deck_report(deck_id)
        if report is None and fallback_report is not None:
            report = fallback_report
            logger.info("Using DB-built fallback report for '%s' (no simulation data)", deck_id)
        if report is None:
            raise ValueError(f"Deck report not found for: {deck_id}")

        # 2. Get deck card names (for exclusion from candidates)
        deck_card_names = [c.name for c in report.cards]

        # 3. Find replacement candidates for underperformers
        candidates: Dict[str, List[dict]] = {}

        underperformers = report.underperformers[:MAX_UNDERPERFORMERS]
        if not underperformers:
            # If no explicit underperformers, pick lowest impact cards
            sorted_cards = sorted(report.cards, key=lambda c: c.impactScore)
            underperformers = [
                c.name for c in sorted_cards[:MAX_UNDERPERFORMERS]
                if c.impactScore < UNDERPERFORMER_IMPACT_THRESHOLD
            ]

        # If still no underperformers and we have cards, pick bottom N by impact
        if not underperformers and report.cards:
            sorted_cards = sorted(report.cards, key=lambda c: c.impactScore)
            # Take the bottom 5 non-land cards as candidates for cuts
            underperformers = [
                c.name for c in sorted_cards[:5]
                if not any(t in (c.tags or []) for t in [])
            ][:MAX_UNDERPERFORMERS]

        if self.embeddings.loaded:
            for card_name in underperformers:
                matches = self.embeddings.find_replacements(
                    underperformer=card_name,
                    deck_colors=report.colorIdentity,
                    deck_card_names=deck_card_names,
                    top_n=MAX_CANDIDATES_PER_UNDERPERFORMER,
                )
                if matches:
                    candidates[card_name] = [m.to_dict() for m in matches]
        else:
            logger.warning("Embeddings not loaded — skipping candidate search")

        # 4. Build prompts
        system_prompt = build_system_prompt(report, goals)
        user_prompt = build_user_prompt(report, candidates)

        # 5. Call LLM (Perplexity or local Ollama)
        logger.info("Calling LLM for deck: %s (provider=%s)", deck_id, COACH_PROVIDER)
        if COACH_PROVIDER == "perplexity":
            import httpx
            pplx_key = os.environ.get("PPLX_API_KEY", "")
            if not pplx_key:
                raise ConnectionError("Perplexity API key not configured. Set PPLX_API_KEY env var.")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            pplx_payload = {
                "model": PPLX_MODEL,
                "messages": messages,
                "max_tokens": 8192,
                "temperature": 0.7,
            }
            pplx_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {pplx_key}",
            }
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    json=pplx_payload,
                    headers=pplx_headers,
                )
                resp.raise_for_status()
                raw = resp.json()
            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = raw.get("usage", {})
            # Build an LLMResponse-compatible object
            from types import SimpleNamespace
            llm_response = SimpleNamespace(
                content=content,
                model=raw.get("model", PPLX_MODEL),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                parsed_json=None,
            )
            # Try to parse JSON from the response
            try:
                import re as _re
                cleaned = _re.sub(r'^```(?:json)?\s*', '', content.strip())
                cleaned = _re.sub(r'\s*```$', '', cleaned.strip())
                llm_response.parsed_json = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                # Try to find JSON object in the text
                match = re.search(r'\{[\s\S]*\}', content)
                if match:
                    try:
                        llm_response.parsed_json = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        pass
        else:
            llm_response = await self.llm.chat(system_prompt, user_prompt)

        # 6. Parse response into CoachSession
        session_id = f"sess-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

        session = CoachSession(
            sessionId=session_id,
            deckId=deck_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            modelUsed=llm_response.model,
            promptTokens=llm_response.prompt_tokens,
            completionTokens=llm_response.completion_tokens,
            goals=goals,
        )

        if llm_response.parsed_json:
            self._populate_session_from_json(session, llm_response.parsed_json)
        else:
            # Fallback: store raw text
            session.rawTextExplanation = llm_response.content
            session.summary = "LLM returned non-JSON response. See raw explanation."

        # 7. Persist
        self.save_session(session)
        logger.info("Coaching session saved: %s", session_id)

        return session

    def _populate_session_from_json(self, session: CoachSession, data: dict):
        """Parse LLM JSON response into CoachSession fields."""
        session.summary = data.get("summary", "")
        session.rawTextExplanation = data.get("rawTextExplanation", "")
        session.manaBaseAdvice = data.get("manaBaseAdvice")

        # Heuristic hints
        hints = data.get("heuristicHints", [])
        session.heuristicHints = hints if isinstance(hints, list) else [str(hints)]

        # Suggested cuts
        for cut_data in data.get("suggestedCuts", []):
            if isinstance(cut_data, dict):
                session.suggestedCuts.append(SuggestedCut(
                    cardName=cut_data.get("cardName", ""),
                    reason=cut_data.get("reason", ""),
                    replacementOptions=cut_data.get("replacementOptions", []),
                ))

        # Suggested adds
        for add_data in data.get("suggestedAdds", []):
            if isinstance(add_data, dict):
                session.suggestedAdds.append(SuggestedAdd(
                    cardName=add_data.get("cardName", ""),
                    role=add_data.get("role", ""),
                    reason=add_data.get("reason", ""),
                    synergyWith=add_data.get("synergyWith", []),
                ))

    # ── Status Check ───────────────────────────────────────────

    def get_status(self) -> CoachStatus:
        """Check the health of all coach subsystems."""
        status = CoachStatus()

        # Check LLM / Perplexity provider
        if COACH_PROVIDER == "perplexity":
            pplx_key = os.environ.get("PPLX_API_KEY", "")
            if pplx_key:
                status.llmConnected = True
                status.llmModel = f"Perplexity ({PPLX_MODEL})"
                status.llmModels = [PPLX_MODEL]
            else:
                status.llmConnected = False
                status.llmModel = None
                status.llmModels = []
                status.error = "Perplexity API key not configured. Set PPLX_API_KEY env var."
        else:
            llm_status = self.llm.check_connection()
            status.llmConnected = llm_status.get("connected", False)
            status.llmModel = llm_status.get("active_model")
            status.llmModels = llm_status.get("models", [])
            if not status.llmConnected:
                status.error = llm_status.get("error", "Local LLM not reachable")

        # Check embeddings
        status.embeddingsLoaded = self.embeddings.loaded
        status.embeddingCards = self.embeddings.card_count

        # Check deck reports
        status.deckReportsAvailable = len(self.list_deck_reports())

        return status
