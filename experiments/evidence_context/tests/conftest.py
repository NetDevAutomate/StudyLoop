"""Private-free synthetic fixtures for the evidence-context prototype."""

from dataclasses import replace

import pytest

from experiments.evidence_context.store import EvidenceRecord, EvidenceStore


@pytest.fixture
def store(tmp_path):
    database = EvidenceStore.create(tmp_path / "synthetic-evidence.db")
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def record():
    """Factories explicitly set scope; a harness name never supplies it."""
    base = EvidenceRecord(
        message_id="message-1",
        session_id="session-1",
        harness="codex",
        project="synthetic-project",
        scope="personal",
        content="cachepolicy initially favored a local SQLite store.",
        timestamp="2026-01-01T10:00:00Z",
        available_at="2026-01-01T10:00:01Z",
        source_locator="synthetic://session-1/message-1",
        role="assistant",
        lineage_id=None,
        seq=1,
    )

    def build(**changes):
        return replace(base, **changes)

    return build
