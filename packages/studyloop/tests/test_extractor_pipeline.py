"""Pipeline-plumbing tests for the struggle-extraction pipeline (P1).

These test the plumbing against a deterministic test-local extractor:
- pre_filter accept/reject logic
- extract_and_write row counts, empty handling, idempotency
- CLI wiring (--help, --dry-run) via click.testing.CliRunner

No LLM calls. No writes to the user's live sessions.db — every DB-touching
test monkeypatches ``studyloop.history._connection._connect`` to a tmp DB.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from studyloop.cli._extract import extract_struggles_cmd
from studyloop.extractors import ExtractorResult
from studyloop.extractors.pipeline import (
    STUDY_SOURCES,
    extract_and_write,
    pre_filter,
)

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
        source_session_id TEXT,
        created_by TEXT DEFAULT 'agent'
    )
"""


def deterministic_test_extract(_messages, _session_id) -> list[ExtractorResult]:
    """Isolated test double for pipeline behavior; never shipped in StudyLoop."""
    return [
        ExtractorResult(
            topic="python",
            concept="abc-vs-protocol",
            confidence="struggling",
            notes="test-only extraction one",
        ),
        ExtractorResult(
            topic="sql-joins",
            concept="outer-join",
            confidence="struggling",
            notes="test-only extraction two",
        ),
    ]


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


def test_pre_filter_rejects_unsupported_source() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    assert pre_filter("s1", "aider", msgs) is False


@pytest.mark.parametrize("source", sorted(STUDY_SOURCES))
def test_pre_filter_accepts_release_harness_session(source: str) -> None:
    msgs = [{"role": "user", "content": "explain ABC"}, {"role": "assistant", "content": "..."}]
    assert pre_filter("s1", source, msgs) is True


def test_pre_filter_rejects_tool_noise_majority() -> None:
    """(b) >50% tool_use/tool_result messages → skip even for kiro source."""
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "tool_use", "content": "{}"},
        {"role": "tool_result", "content": "{}"},
        {"role": "tool_use", "content": "{}"},
    ]  # 3/4 = 75% tool noise
    assert pre_filter("s1", "kiro_cli", msgs) is False


def test_pre_filter_rejects_empty_session() -> None:
    assert pre_filter("s1", "kiro_cli", []) is False


# --------------------------------------------------------------------------- #
# extract_and_write
# --------------------------------------------------------------------------- #


def test_extract_and_write_writes_expected_rows(tmp_db: Path) -> None:
    """(c) an injected extractor writes its validated rows into the tmp DB."""
    msgs = [{"role": "user", "content": "x"}]
    written = extract_and_write("test-session-001", msgs, deterministic_test_extract)
    assert written == 2
    assert _count_struggling(tmp_db) == 2


def test_extract_and_write_trusts_injected_extractor_after_caller_filter(tmp_db: Path) -> None:
    """(d) extract_and_write does not duplicate its caller's pre-filter.

    extract_and_write does NOT pre-filter (that is the caller's job); it trusts
    the injected extractor.
    """
    written = extract_and_write("test-session", [], deterministic_test_extract)
    assert written == 2


def test_extract_and_write_idempotent(tmp_db: Path) -> None:
    """(e) re-running on the same session does not duplicate rows (uuid5 upsert)."""
    msgs = [{"role": "user", "content": "x"}]
    first = extract_and_write("test-session-001", msgs, deterministic_test_extract)
    assert first == 2
    second = extract_and_write("test-session-001", msgs, deterministic_test_extract)
    assert second == 2  # write path ran again...
    conn = sqlite3.connect(tmp_db)
    try:
        rows = conn.execute(
            "SELECT session_count, source_session_id FROM study_progress"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(1, "test-session-001"), (1, "test-session-001")]


def test_extract_and_write_validates_entire_batch_before_first_write(tmp_db: Path) -> None:
    def partly_invalid(_messages, _session_id):
        return [
            ExtractorResult(topic="python", concept="valid", confidence="struggling"),
            ExtractorResult(topic="", concept="invalid", confidence="struggling"),
        ]

    with pytest.raises(ValueError, match="topic"):
        extract_and_write("s1", [{"role": "user", "content": "x"}], partly_invalid)
    assert _count_struggling(tmp_db) == 0


def test_extract_and_write_model_failure_writes_nothing(tmp_db: Path) -> None:
    def failed_model(_messages, _session_id):
        raise RuntimeError("live model unavailable")

    with pytest.raises(RuntimeError, match="live model unavailable"):
        extract_and_write("s1", [{"role": "user", "content": "x"}], failed_model)
    assert _count_struggling(tmp_db) == 0


def test_extract_and_write_dry_run_writes_nothing(tmp_db: Path) -> None:
    msgs = [{"role": "user", "content": "x"}]
    written = extract_and_write("test-session-001", msgs, deterministic_test_extract, dry_run=True)
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
    assert "--harness" in result.output
    assert "--dry-run" in result.output


def test_cli_requires_harness_for_implicit_session_before_opening_database(
    monkeypatch,
) -> None:
    def database_must_not_open():
        raise AssertionError("database opened before harness selection was validated")

    monkeypatch.setattr("studyloop.history._connection._connect", database_must_not_open)
    result = CliRunner().invoke(
        extract_struggles_cmd,
        ["--incremental", "--model", "example.live-model"],
    )

    assert result.exit_code != 0
    assert "--harness" in result.output
    assert not isinstance(result.exception, AssertionError)


def test_cli_requires_explicit_live_model_before_opening_database(monkeypatch) -> None:
    """An unconfigured extraction fails closed before learner state is opened."""

    def database_must_not_open():
        raise AssertionError("database opened before extractor configuration was validated")

    monkeypatch.setattr("studyloop.history._connection._connect", database_must_not_open)

    result = CliRunner().invoke(extract_struggles_cmd, ["--incremental"])

    assert result.exit_code != 0
    assert "--model" in result.output
    assert not isinstance(result.exception, AssertionError)


def test_cli_uses_live_extractor_by_default_when_model_is_supplied(
    tmp_db: Path, monkeypatch
) -> None:
    """The normal CLI path uses transcript-derived live output, never fixtures."""
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO sessions (id, source, updated_at) VALUES (?, ?, ?)",
        ("live-session", "kiro_cli", "2026-08-27T20:00:00Z"),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, seq) VALUES (?, ?, ?, ?)",
        ("live-session", "user", "I still do not understand protocols", 1),
    )
    conn.commit()
    conn.close()

    bedrock = MagicMock()
    bedrock.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "name": "emit_struggle_extractions",
                            "input": {
                                "struggles": [
                                    {
                                        "topic": "python",
                                        "concept": "protocols",
                                        "confidence": "struggling",
                                        "evidence_quote": "I still do not understand protocols",
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        },
        "usage": {},
    }
    monkeypatch.setattr("studyloop.extractors.llm._build_client", lambda: bedrock)

    result = CliRunner().invoke(
        extract_struggles_cmd,
        [
            "--incremental",
            "--session-id",
            "live-session",
            "--dry-run",
            "--model",
            "example.live-model",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "would write 1 row(s)" in result.output
    assert _count_struggling(tmp_db) == 0
    assert bedrock.converse.call_args.kwargs["modelId"] == "example.live-model"


def test_cli_rolls_back_every_result_when_one_progress_write_fails(
    tmp_db: Path, monkeypatch
) -> None:
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO sessions (id, source, updated_at) VALUES (?, ?, ?)",
        ("atomic-session", "kiro_cli", "2026-08-27T20:00:00Z"),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, seq) VALUES (?, ?, ?, ?)",
        ("atomic-session", "user", "Two concepts are still unclear", 1),
    )
    conn.execute(
        """
        CREATE TRIGGER reject_second_progress
        BEFORE INSERT ON study_progress
        WHEN NEW.concept = 'reject-me'
        BEGIN
            SELECT RAISE(ABORT, 'intentional write rejection');
        END
        """
    )
    conn.commit()
    conn.close()

    bedrock = MagicMock()
    bedrock.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "name": "emit_struggle_extractions",
                            "input": {
                                "struggles": [
                                    {
                                        "topic": "python",
                                        "concept": "first-result",
                                        "confidence": "struggling",
                                        "evidence_quote": "Two concepts are still unclear",
                                    },
                                    {
                                        "topic": "python",
                                        "concept": "reject-me",
                                        "confidence": "struggling",
                                        "evidence_quote": "Two concepts are still unclear",
                                    },
                                ]
                            },
                        }
                    }
                ]
            }
        },
        "usage": {},
    }
    monkeypatch.setattr("studyloop.extractors.llm._build_client", lambda: bedrock)

    result = CliRunner().invoke(
        extract_struggles_cmd,
        [
            "--incremental",
            "--session-id",
            "atomic-session",
            "--model",
            "example.live-model",
        ],
    )

    assert result.exit_code != 0
    assert _count_struggling(tmp_db) == 0


def test_cli_records_source_session_provenance(tmp_db: Path, monkeypatch) -> None:
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO sessions (id, source, updated_at) VALUES (?, ?, ?)",
        ("provenance-session", "kiro_cli", "2026-08-27T20:00:00Z"),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, seq) VALUES (?, ?, ?, ?)",
        ("provenance-session", "user", "Protocols are still unclear", 1),
    )
    conn.commit()
    conn.close()

    bedrock = MagicMock()
    bedrock.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "name": "emit_struggle_extractions",
                            "input": {
                                "struggles": [
                                    {
                                        "topic": "python",
                                        "concept": "protocols",
                                        "confidence": "struggling",
                                        "evidence_quote": "Protocols are still unclear",
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        },
        "usage": {},
    }
    monkeypatch.setattr("studyloop.extractors.llm._build_client", lambda: bedrock)

    result = CliRunner().invoke(
        extract_struggles_cmd,
        [
            "--incremental",
            "--session-id",
            "provenance-session",
            "--model",
            "example.live-model",
        ],
    )

    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(tmp_db)
    try:
        row = conn.execute(
            "SELECT source_session_id FROM study_progress WHERE concept = 'protocols'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("provenance-session",)


def test_cli_incremental_dry_run_no_write(tmp_db: Path) -> None:
    """(g) `--incremental --session-id FAKE --dry-run` exits 0, writes nothing.

    A non-existent session id yields zero messages → pre_filter rejects it
    (source is None) → no rows. Either way, dry-run guarantees no DB write.
    """
    result = CliRunner().invoke(
        extract_struggles_cmd,
        [
            "--incremental",
            "--session-id",
            "FAKE",
            "--dry-run",
            "--model",
            "example.live-model",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _count_struggling(tmp_db) == 0
