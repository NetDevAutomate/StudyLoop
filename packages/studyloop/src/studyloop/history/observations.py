"""StudyLoop's progress projection over memory-owned, source-linked observations.

The independent memory package stores observations and controls source access.
StudyLoop supplies its confidence vocabulary and display/scheduling projection.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from agent_session_tools.context.legacy import legacy_global_visible
from agent_session_tools.context.legacy_sources import capture_session_input
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopeError
from agent_session_tools.context.store import _hash, _json

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from agent_session_tools.context.legacy_sources import SessionInput

KIND = "studyloop.progress"
CONFIDENCE = ("struggling", "learning", "confident", "mastered")


def available(conn: sqlite3.Connection) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='context_observations' AND type='table'"
        ).fetchone()
    )


def record(
    conn: sqlite3.Connection,
    topic: str,
    concept: str,
    confidence: str,
    notes: str | None = None,
    *,
    source_course: str | None = None,
    source_section: str | None = None,
    source_publisher: str | None = None,
    source_session_id: str | None = None,
    created_by: str = "agent",
    evidence_ids: tuple[str, ...] | None = None,
    input_snapshot: SessionInput | None = None,
    last_teachback_score: int | None = None,
    angle: str | None = None,
    owner_path: Path | None = None,
) -> str:
    """Record a report or source-derived proposal on the caller's transaction."""
    topic, concept = topic.lower().strip(), concept.lower().strip()
    if not topic or not concept or confidence not in CONFIDENCE:
        raise ValueError("Progress needs a topic, concept and supported confidence")
    for value in (notes, source_course, source_section, source_publisher, source_session_id, angle):
        if value is not None and not isinstance(value, str):
            raise ValueError("Progress text fields must be strings or null")
    store = ObservationStore(conn)
    subject = json.dumps([topic, concept], separators=(",", ":"))
    with store.sources._atomic():
        refs = evidence_ids or ()
        if source_session_id and evidence_ids is None:
            input_snapshot = capture_session_input(conn, source_session_id)
            refs = input_snapshot.evidence_ids
        if input_snapshot is not None and (
            input_snapshot.session_id != source_session_id or input_snapshot.evidence_ids != refs
        ):
            raise ValueError("Progress input manifest does not match its source dependencies")
        if source_session_id and not refs:
            raise ScopeError("Source-linked progress requires nonempty captured input")
        if refs and source_session_id:
            for ref in refs:
                source = conn.execute(
                    "SELECT session_id FROM context_evidence WHERE id=?", (ref,)
                ).fetchone()
                if source is None or source[0] != source_session_id:
                    raise ValueError("Progress source id does not match its evidence dependencies")
        payload = {
            "topic": topic,
            "concept": concept,
            "confidence": confidence,
            "notes": notes,
            "source_course": source_course,
            "source_section": source_section,
            "source_publisher": source_publisher,
            "source_session_id": source_session_id,
            "created_by": created_by,
            "last_teachback_score": last_teachback_score,
            "angle": angle,
            "input_trace": input_snapshot.manifest() if input_snapshot is not None else None,
        }
        # A direct record-progress operation updates the reported assessment.
        # Independent model proposals do not silently supersede prior reports.
        previous = [] if refs else [row["id"] for row in store.list(KIND, subject=subject)]
        return store.append(
            kind=KIND,
            subject=subject,
            payload=payload,
            producer=created_by,
            authority="model_interpretation" if created_by == "extractor" else "reported",
            evidence_ids=refs,
            supersedes=previous,
            request_key="same-input-and-result" if refs else None,
            owner_path=owner_path,
        )


def _legacy_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not legacy_global_visible(conn):
        return []
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_progress'"
    ).fetchone():
        return []
    cursor = conn.execute(
        "SELECT * FROM study_progress WHERE topic IS NOT NULL AND concept IS NOT NULL"
    )
    columns = [col[0] for col in cursor.description]
    return [
        {
            **dict(zip(columns, row, strict=True)),
            "confidence_status": "unclassified_legacy_aggregate",
            "observation_ids": [],
        }
        for row in cursor
    ]


def rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Rebuild from permitted observations; no persistent copied context cache.

    Concurrent/incompatible current reports stay visible. The scheduling value is
    the most conservative confidence and explicitly marked conflicting; it is not
    an arbitration result or a claim that the least confident report is true.
    """
    legacy = _legacy_rows(conn)
    if not available(conn):
        return legacy
    store = ObservationStore(conn)
    history = store.list(KIND, current=False)
    current_ids = {row["id"] for row in store.list(KIND)}
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in history:
        by_subject[observation["subject"]].append(observation)
    projected = {}
    for subject, events in by_subject.items():
        current = [event for event in events if event["id"] in current_ids]
        if not current:
            # Retired history must not fall back to the old global aggregate.
            projected[subject] = None
            continue
        values = {event["payload"]["confidence"] for event in current}
        if not values.issubset(CONFIDENCE):
            raise ValueError("Stored progress has an unsupported confidence")
        confidence = min(values, key=CONFIDENCE.index)
        payload = current[0]["payload"]
        sessions = {ref["session_id"] for event in events for ref in event["sources"]}
        manual = {event["id"] for event in events if not event["sources"]}
        notes = [
            f"[{e['producer']}; {e['semantic_status']}; observation:{e['id']}]\n"
            + e["payload"]["notes"]
            for e in current
            if e["payload"].get("notes")
        ]
        row = {
            "id": subject,
            "topic": payload["topic"],
            "concept": payload["concept"],
            "confidence": confidence,
            "confidence_status": "conflicting_reports"
            if len(values) > 1
            else (
                "unverified_interpretation"
                if any(e["semantic_status"] == "unverified_interpretation" for e in current)
                else "reported_assessment"
            ),
            "reported_confidences": sorted(values, key=CONFIDENCE.index),
            "first_seen": min(e["recorded_at"] for e in events),
            "last_seen": max(e["recorded_at"] for e in current),
            "time_basis": "assessment_recorded_at",
            "source_recorded_at": sorted(
                {
                    ref["recorded_at"]
                    for e in current
                    for ref in e["sources"]
                    if ref["recorded_at"] is not None
                }
            ),
            "session_count": len(sessions) + len(manual),
            "notes": "\n\n".join(notes) or None,
            "last_teachback_score": payload.get("last_teachback_score")
            if len(current) == 1
            else None,
            "angles_used": json.dumps(
                sorted({e["payload"]["angle"] for e in events if e["payload"].get("angle")})
            ),
            "created_by": payload.get("created_by") if len(current) == 1 else "multiple_reports",
            "observation_ids": [e["id"] for e in current],
            "source_evidence_ids": sorted({ref["id"] for e in current for ref in e["sources"]}),
            "record_dependencies": list(
                {
                    ref["owner_id"]: ref
                    for e in current
                    for ref in e.get("record_dependencies", [])
                }.values()
            ),
            "history_incomplete": any(e["history_incomplete"] for e in current),
        }
        for field in ("source_course", "source_section", "source_publisher", "source_session_id"):
            candidates = {e["payload"].get(field) for e in current}
            row[field] = candidates.pop() if len(candidates) == 1 else None
        projected[subject] = row
    for row in legacy:
        subject = json.dumps(
            [row["topic"].lower().strip(), row["concept"].lower().strip()], separators=(",", ":")
        )
        retired = conn.execute(
            "SELECT 1 FROM context_observation_retired_subjects WHERE subject_sha256=?",
            (_hash(_json([KIND, subject])),),
        ).fetchone()
        if retired:
            continue
        if subject not in projected:
            projected[subject] = row
    return sorted(
        (row for row in projected.values() if row is not None),
        key=lambda row: (row["topic"], row["concept"]),
    )
