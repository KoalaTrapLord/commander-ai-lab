"""
Commander AI Lab — Online Learning Store (SQLite WAL)
═════════════════════════════════════════════════════

Single-machine backing store for online learning data collected during
policy inference (``/api/ml/predict`` and ``/api/policy/decide``).

Each prediction request can optionally log the state snapshot and the
chosen action so that future training runs can incorporate online
decision data alongside Forge and PPO batches.

Design decisions (Phase 5 architecture follow-up):
  - SQLite in WAL mode for concurrent readers + single writer, which is
    the right fit for a single-machine baseline (one API server process).
  - Separate DB file (``online_learning.db``) to avoid contention with
    the collection database.
  - Append-only writes; reads are batched by the dataset builder.
  - Thread-safe via the Python sqlite3 module's ``check_same_thread=False``
    and WAL's built-in reader/writer concurrency.

Usage::

    store = OnlineLearningStore()   # uses default path
    store.init_db()

    # At prediction time:
    store.record_decision(snapshot_json, action_index, confidence, playstyle)

    # At training time:
    decisions = store.fetch_decisions(since_rowid=last_seen, limit=10000)
    store.mark_exported(max_rowid)
"""

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("ml.serving.online_store")

_DEFAULT_DB_PATH = str(
    Path(__file__).parent.parent.parent / "online_learning.db"
)


class OnlineLearningStore:
    """SQLite WAL-backed store for online policy decision collection."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self._local = threading.local()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection with WAL mode enabled."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL for concurrent read/write on single machine.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def close(self) -> None:
        """Close the thread-local connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create the decisions table if it doesn't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS online_decisions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot    TEXT    NOT NULL,
                action_idx  INTEGER NOT NULL,
                confidence  REAL    NOT NULL DEFAULT 0.0,
                playstyle   TEXT    NOT NULL DEFAULT 'midrange',
                temperature REAL    NOT NULL DEFAULT 1.0,
                greedy      INTEGER NOT NULL DEFAULT 0,
                exported    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_od_exported
                ON online_decisions(exported);
            CREATE INDEX IF NOT EXISTS idx_od_created
                ON online_decisions(created_at);
        """)
        conn.commit()
        logger.info("Online learning store ready: %s (WAL mode)", self.db_path)

    # ------------------------------------------------------------------
    # Write path (called during prediction)
    # ------------------------------------------------------------------

    def record_decision(
        self,
        snapshot: Dict,
        action_idx: int,
        confidence: float,
        playstyle: str = "midrange",
        temperature: float = 1.0,
        greedy: bool = False,
    ) -> int:
        """Append a policy decision for future training.

        Returns the row id of the inserted record.
        """
        conn = self._get_conn()
        cur = conn.execute(
            """
            INSERT INTO online_decisions
                (snapshot, action_idx, confidence, playstyle, temperature, greedy)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                json.dumps(snapshot, separators=(",", ":")),
                action_idx,
                confidence,
                playstyle,
                temperature,
                1 if greedy else 0,
            ),
        )
        conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # Read path (called by dataset builder / training pipeline)
    # ------------------------------------------------------------------

    def fetch_decisions(
        self,
        since_rowid: int = 0,
        limit: int = 50000,
        only_unexported: bool = True,
    ) -> List[Dict]:
        """Fetch collected decisions for training.

        Args:
            since_rowid: Only return rows with id > this value.
            limit: Max rows to return.
            only_unexported: If True, skip rows already marked exported.

        Returns:
            List of dicts with keys: id, snapshot (parsed), action_idx,
            confidence, playstyle, temperature, greedy, created_at.
        """
        conn = self._get_conn()
        clauses = ["id > ?"]
        params: list = [since_rowid]
        if only_unexported:
            clauses.append("exported = 0")
        where = " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT * FROM online_decisions WHERE {where} ORDER BY id LIMIT ?",
            (*params, limit),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            try:
                d["snapshot"] = json.loads(d["snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(d)
        return results

    def mark_exported(self, up_to_rowid: int) -> int:
        """Mark decisions as exported so they aren't fetched again.

        Returns the number of rows updated.
        """
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE online_decisions SET exported = 1 WHERE id <= ? AND exported = 0",
            (up_to_rowid,),
        )
        conn.commit()
        return cur.rowcount

    def count(self, only_unexported: bool = False) -> int:
        """Return the total number of stored decisions."""
        conn = self._get_conn()
        if only_unexported:
            row = conn.execute(
                "SELECT COUNT(*) FROM online_decisions WHERE exported = 0"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM online_decisions"
            ).fetchone()
        return row[0]
