"""Derived SQLite index for study plans, and durable checkpoint history.

The Markdown documents are authoritative; everything here is a **cache** that
exists so the web UI and the ``now`` decision engine can query plans without
parsing every file, and so evaluation history survives plan edits.

Two tables (created by ``agent_session_tools`` migration 26, and defensively
here so a plan write never fails on a cold DB):

``study_plans``
    One row per plan document — the queryable projection.

``study_plan_checkpoints``
    Append-only evaluation log, joined to ``study_sessions.study_id`` so a plan
    checkpoint can be traced back to the session that produced it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from .evaluation import PlanEvaluation
    from .models import StudyPlan

logger = logging.getLogger(__name__)

_PLANS_DDL = """
CREATE TABLE IF NOT EXISTS study_plans (
    plan_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    topics TEXT NOT NULL DEFAULT '',
    mission_why TEXT NOT NULL DEFAULT '',
    target_date TEXT NOT NULL DEFAULT '',
    energy_floor INTEGER NOT NULL DEFAULT 3,
    review_cadence_days INTEGER NOT NULL DEFAULT 3,
    milestone_total INTEGER NOT NULL DEFAULT 0,
    milestone_done INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT ''
)
"""

_CHECKPOINTS_DDL = """
CREATE TABLE IF NOT EXISTS study_plan_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    study_id TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL,
    verdict TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    command_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_study_plans_status ON study_plans(status)",
    "CREATE INDEX IF NOT EXISTS idx_plan_checkpoints_plan "
    "ON study_plan_checkpoints(plan_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_plan_checkpoints_study ON study_plan_checkpoints(study_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_checkpoints_command "
    "ON study_plan_checkpoints(command_key) WHERE command_key <> ''",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the plan tables/indexes if they are missing (idempotent)."""
    conn.execute(_PLANS_DDL)
    conn.execute(_CHECKPOINTS_DDL)
    checkpoint_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(study_plan_checkpoints)")
    }
    if "command_key" not in checkpoint_columns:
        conn.execute(
            "ALTER TABLE study_plan_checkpoints ADD COLUMN command_key TEXT NOT NULL DEFAULT ''"
        )
    for statement in _INDEXES:
        conn.execute(statement)


def _connect():
    """Open the sessions DB with plan tables guaranteed, or return None."""
    try:
        from studyloop.history._connection import _connect as connect_sessions
    except Exception:  # pragma: no cover - import guard
        logger.debug("history._connection unavailable", exc_info=True)
        return None
    conn = connect_sessions()
    if conn is None:
        return None
    try:
        ensure_schema(conn)
        conn.commit()
    except Exception:
        logger.debug("Could not ensure study-plan schema", exc_info=True)
        conn.close()
        return None
    return conn


def index_plan(plan: StudyPlan) -> bool:
    """Upsert one plan into the derived index. Returns False when unavailable."""
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute(
            """
            INSERT INTO study_plans (
                plan_id, title, status, topics, mission_why, target_date,
                energy_floor, review_cadence_days, milestone_total,
                milestone_done, created, updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
                title=excluded.title,
                status=excluded.status,
                topics=excluded.topics,
                mission_why=excluded.mission_why,
                target_date=excluded.target_date,
                energy_floor=excluded.energy_floor,
                review_cadence_days=excluded.review_cadence_days,
                milestone_total=excluded.milestone_total,
                milestone_done=excluded.milestone_done,
                updated=excluded.updated
            """,
            (
                plan.plan_id,
                plan.title,
                plan.status,
                ",".join(plan.topics),
                plan.mission.why[:2000],
                plan.target_date,
                plan.energy_floor,
                plan.review_cadence_days,
                plan.milestone_total,
                plan.milestone_done,
                plan.created,
                plan.updated,
            ),
        )
        conn.commit()
        return True
    except Exception:
        logger.debug("index_plan failed for %s", plan.plan_id, exc_info=True)
        return False
    finally:
        conn.close()


def forget_plan(plan_id: str) -> bool:
    """Drop a plan from the index. Checkpoint history is deliberately kept."""
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute("DELETE FROM study_plans WHERE plan_id = ?", (plan_id,))
        conn.commit()
        return True
    except Exception:
        logger.debug("forget_plan failed for %s", plan_id, exc_info=True)
        return False
    finally:
        conn.close()


def reindex_all() -> int:
    """Rebuild the index from the Markdown documents. Returns rows written."""
    from .store import list_plans

    count = 0
    for plan in list_plans():
        if index_plan(plan):
            count += 1
    return count


def record_checkpoint(
    evaluation: PlanEvaluation,
    *,
    study_id: str = "",
    idempotency_key: str = "",
) -> bool:
    """Append a checkpoint once for a lifecycle command key."""
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO study_plan_checkpoints
                (plan_id, study_id, phase, verdict, summary, payload, command_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation.plan_id,
                study_id or evaluation.study_id,
                evaluation.phase,
                evaluation.verdict,
                evaluation.headline[:1000],
                json.dumps(evaluation.to_dict(), default=str),
                idempotency_key,
            ),
        )
        conn.commit()
        return True
    except Exception:
        logger.debug("record_checkpoint failed for %s", evaluation.plan_id, exc_info=True)
        return False
    finally:
        conn.close()


def checkpoint_history(plan_id: str, *, limit: int = 20) -> list[dict]:
    """Return recent checkpoints for a plan, newest first."""
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT plan_id, study_id, phase, verdict, summary, created_at
            FROM study_plan_checkpoints
            WHERE plan_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (plan_id, max(1, min(limit, 200))),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        logger.debug("checkpoint_history failed for %s", plan_id, exc_info=True)
        return []
    finally:
        conn.close()


def indexed_plans(*, status: str = "") -> list[dict]:
    """Query the derived index — cheap listing without touching the disk."""
    conn = _connect()
    if conn is None:
        return []
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM study_plans WHERE status = ? ORDER BY updated DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM study_plans ORDER BY updated DESC").fetchall()
        return [dict(row) for row in rows]
    except Exception:
        logger.debug("indexed_plans failed", exc_info=True)
        return []
    finally:
        conn.close()
