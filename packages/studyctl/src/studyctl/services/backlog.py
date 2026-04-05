"""Backlog service — auto-persist struggled topics from sessions.

Framework-agnostic: no CLI imports, no console output. The caller
(CLI, cleanup, MCP) decides what to do with the return value.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def auto_persist_struggled(
    study_session_id: str,
    topic_entries: list,
) -> int:
    """Persist struggled topics from a session to the backlog.

    Uses FCIS pattern — ``plan_auto_persist`` decides what to save,
    then ``park_topic`` writes each one.

    Returns the number of topics successfully persisted.
    """
    from studyctl.logic.backlog_logic import plan_auto_persist
    from studyctl.parking import get_parked_topics, park_topic

    existing = get_parked_topics(study_session_id=study_session_id)
    existing_questions = {t["question"] for t in existing}

    actions = plan_auto_persist(topic_entries, existing_questions, study_session_id)

    persisted = 0
    for action in actions:
        result = park_topic(
            question=action.question,
            topic_tag=action.topic_tag,
            context=action.context,
            study_session_id=action.study_session_id,
            source=action.source,
        )
        if result:
            persisted += 1

    return persisted
