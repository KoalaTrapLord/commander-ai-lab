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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

from .config import (
    DECK_REPORTS_DIR, COACH_SESSIONS_DIR,
    MAX_UNDERPERFORMERS, MAX_CANDIDATES_PER_UNDERPERFORMER,
    UNDERPERFORMER_IMPACT_THRESHOLD, ensure_dirs,
)
from .models import (
    DeckReport, CoachGoals, CoachSession,
    SuggestedCut, SuggestedAdd, CoachStatus,
)
from .llm_client import LMStudioClient
from .embeddings import MTGEmbeddingIndex
from .prompt_template import build_system_prompt, build_user_prompt

logger = logging.getLogger("coach.service")


class CoachService:
    """
    Deck coaching service powered by local LLM and card embeddings.

    Usage:
        embeddings = MTGEmbeddingIndex()
        embeddings.load()
        llm = LMStudioClient()
        coach = CoachService(llm, embeddings)
        session = await coach.run_coaching_session("edgar-markov")
    """

    def __init__(self, llm: LMStudioClient, embeddings: MTGEmbeddingIndex):
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
                if f.stem.lower() == deck_id.lower():
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
        """Persist a coaching session to disk."""
        COACH_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = COACH_SESSIONS_DIR / f"{session.sessionId}.json"
        with open(path, "w") as f:
            f.write(session.model_dump_json(indent=2))
        return path

    def load_session(self, session_id: str) -> Optional[CoachSession]:
        """Load a coaching session from disk."""
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
        """List all coaching sessions, optionally filtered by deck."""
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
                                    goals: Optional[CoachGoals] = None
                                    ) -> CoachSession:
        """
        Full coaching pipeline:
        1. Load deck report
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

        # 1. Load deck report
        report = self.load_deck_report(deck_id)
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

        # 5. Call LLM
        logger.info("Calling LLM for deck: %s", deck_id)
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

        # Check LLM
        llm_status = self.llm.check_connection()
        status.llmConnected = llm_status.get("connected", False)
        status.llmModel = llm_status.get("active_model")
        status.llmModels = llm_status.get("models", [])
        if not status.llmConnected:
            status.error = llm_status.get("error", "LM Studio not reachable")

        # Check embeddings
        status.embeddingsLoaded = self.embeddings.loaded
        status.embeddingCards = self.embeddings.card_count

        # Check deck reports
        status.deckReportsAvailable = len(self.list_deck_reports())

        return status
