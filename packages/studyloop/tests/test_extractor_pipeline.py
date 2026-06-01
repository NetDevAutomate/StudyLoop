"""Pipeline-plumbing tests for the struggle-extraction pipeline (P1).

These test the PLUMBING only, against the deterministic stub extractor:
- pre_filter accept/reject logic
- extract_and_write row counts, empty handling, idempotency
- CLI wiring (--help, --dry-run) via click.testing.CliRunner

No LLM calls. No writes to the user's live sessions.db — every DB-touching
test monkeypatches ``studyloop.history._connection._connect`` to a tmp DB.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from studyloop.cli._extract import extract_struggles_cmd
from studyloop.extractors import ExtractorResult
from studyloop.extractors.pipeline import (
    STUDY_SOURCE,
    extract_and_write,
    pre_filter,
)
from studyloop.extractors.stub import extract_struggles as stub_extract

if TYPE_CHECKING:
    from pathlib import Path

# study_progress schema — mirrors progress.py (14 columns incl. the v22
# course/section provenance columns). Kept local so the test does not import
# production schema constants and stays a true contract test.
_STUDY_PROGRESS_DDL = """
    CREATE TABLE study_progress (
        id TEXT PRIMARY KEY,
        topic TEXT,
        concept TEXT,
        confidence TEXT,
        first_seen TEXT,
        last_seen TEXT,
        session_count INTEGER,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        source_course TEXT,
        source_section TEXT,
        source_publisher TEXT,
        created_by TEXT DEFAULT 'agent'
    )
"""


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp sessions.db with empty study_progress + sessions + messages tables.

    sessions/messages are minimal stand-ins so the CLI's --incremental query
    path (which reads sessions.source and messages) runs against the tmp DB
    instead of the live one.
    """
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(_STUDY_PROGRESS_DDL)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, seq INTEGER)")
    conn.commit()
    conn.close()

    def _connect_tmp() -> sqlite3.Connection:
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr("studyloop.history._connection._connect", _connect_tmp)
    return db


def _count_struggling(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM study_progress WHERE confidence = 'struggling'"
        ).fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# pre_filter
# --------------------------------------------------------------------------- #


def test_pre_filter_rejects_non_kiro_source() -> None:
    """(a) claude_code build sessions are skipped."""
    msgs = [{"role": "user", "content": "hi"}]
    assert pre_filter("s1", "claude_code", msgs) is False


def test_pre_filter_accepts_kiro_study_session() -> None:
    msgs = [{"role": "user", "content": "explain ABC"}, {"role": "assistant", "content": "..."}]
    assert pre_filter("s1", STUDY_SOURCE, msgs) is True


def test_pre_filter_rejects_tool_noise_majority() -> None:
    """(b) >50% tool_use/tool_result messages → skip even for kiro source."""
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "tool_use", "content": "{}"},
        {"role": "tool_result", "content": "{}"},
        {"role": "tool_use", "content": "{}"},
    ]  # 3/4 = 75% tool noise
    assert pre_filter("s1", STUDY_SOURCE, msgs) is False


def test_pre_filter_rejects_empty_session() -> None:
    assert pre_filter("s1", STUDY_SOURCE, []) is False


# --------------------------------------------------------------------------- #
# extract_and_write
# --------------------------------------------------------------------------- #


def test_extract_and_write_writes_expected_rows(tmp_db: Path) -> None:
    """(c) stub extractor writes its 2 fixture rows into the tmp DB."""
    msgs = [{"role": "user", "content": "x"}]
    written = extract_and_write("stub-session-001", msgs, stub_extract)
    assert written == 2
    assert _count_struggling(tmp_db) == 2


def test_extract_and_write_zero_messages_still_writes_stub_default(tmp_db: Path) -> None:
    """(d) stub ignores content, so even empty messages yield its default list.

    extract_and_write does NOT pre-filter (that is the caller's job); it trusts
    the extractor. With zero messages the stub returns its 2 default rows.
    """
    written = extract_and_write("unknown-session", [], stub_extract)
    assert written == 2


def test_extract_and_write_idempotent(tmp_db: Path) -> None:
    """(e) re-running on the same session does not duplicate rows (uuid5 upsert)."""
    msgs = [{"role": "user", "content": "x"}]
    first = extract_and_write("stub-session-001", msgs, stub_extract)
    assert first == 2
    second = extract_and_write("stub-session-001", msgs, stub_extract)
    assert second == 2  # write path ran again...
    conn = sqlite3.connect(tmp_db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM study_progress").fetchone()[0]
    finally:
        conn.close()
    assert total == 2  # ...but the table still holds exactly 2 distinct rows


def test_extract_and_write_dry_run_writes_nothing(tmp_db: Path) -> None:
    msgs = [{"role": "user", "content": "x"}]
    written = extract_and_write("stub-session-001", msgs, stub_extract, dry_run=True)
    assert written == 2  # counts what *would* be written
    assert _count_struggling(tmp_db) == 0  # but nothing landed


def test_extract_and_write_rejects_invalid_result(tmp_db: Path) -> None:
    """An extractor that emits an invalid result fails loudly, not silently."""

    def bad_extractor(_messages, _session_id):
        return [ExtractorResult(topic="", concept="x", confidence="struggling")]

    with pytest.raises(ValueError, match="topic"):
        extract_and_write("s1", [{"role": "user", "content": "x"}], bad_extractor)


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #


def test_cli_help_exits_zero() -> None:
    """(f) `extract-struggles --help` exits 0 and documents the flags."""
    result = CliRunner().invoke(extract_struggles_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--incremental" in result.output
    assert "--full" in result.output
    assert "--dry-run" in result.output


def test_cli_incremental_dry_run_no_write(tmp_db: Path) -> None:
    """(g) `--incremental --session-id FAKE --dry-run` exits 0, writes nothing.

    A non-existent session id yields zero messages → pre_filter rejects it
    (source is None) → no rows. Either way, dry-run guarantees no DB write.
    """
    result = CliRunner().invoke(
        extract_struggles_cmd,
        ["--incremental", "--session-id", "FAKE", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert _count_struggling(tmp_db) == 0
