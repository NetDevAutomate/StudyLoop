from __future__ import annotations

import pytest

from studyloop.planning.context_ingestion import PlanningContextIngestor
from studyloop.planning.conversation_contracts import ConversationRefusedError
from studyloop.planning.conversation_store import ConversationStore


def test_context_ingestion_preserves_text_but_strips_source_path_label(tmp_path) -> None:
    store = ConversationStore(tmp_path / "private" / "conversations.sqlite3")
    store.create_conversation("conversation-1", "create")
    ingested = PlanningContextIngestor(store).ingest(
        "conversation-1",
        label="/Users/private/course.md",
        content="See https://example.test/course and /learner/authored/path verbatim.",
    )
    assert ingested.label == "selected text context"
    assert store.attach_context  # the production store owns the exact text
    assert ingested.tier == 4


@pytest.mark.parametrize("media_type", ["application/pdf", "image/png"])
def test_context_ingestion_refuses_non_text(media_type: str, tmp_path) -> None:
    store = ConversationStore(tmp_path / "private" / "conversations.sqlite3")
    store.create_conversation("conversation-1", "create")
    with pytest.raises(ConversationRefusedError, match="plain-text"):
        PlanningContextIngestor(store).ingest(
            "conversation-1",
            label="course",
            content="not accepted",
            media_type=media_type,
        )
