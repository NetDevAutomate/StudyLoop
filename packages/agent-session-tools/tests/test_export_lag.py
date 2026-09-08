"""Per-source export lag: chronological stale-context reporting."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from agent_session_tools.maintenance import _parse_session_timestamp, _source_export_lag


def _store(rows: list[tuple[str, str, str]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, updated_at TEXT)"
    )
    conn.executemany("INSERT INTO sessions VALUES (?,?,?)", rows)
    return conn


def test_parse_normalizes_z_offset_and_naive_forms() -> None:
    z = _parse_session_timestamp("2026-09-07T10:00:00Z")
    offset = _parse_session_timestamp("2026-09-07T21:00:00+11:00")
    naive = _parse_session_timestamp("2026-09-07T10:00:00")
    assert z == offset == naive
    assert _parse_session_timestamp("not-a-timestamp") is None
    assert _parse_session_timestamp(None) is None


def test_lag_is_chronological_not_lexicographic() -> None:
    # The +11:00 row is lexicographically the largest text but chronologically
    # EARLIER (09:00Z) than the 12:00Z row; a SQL MAX() would pick the wrong one.
    conn = _store(
        [
            ("a", "codex", "2026-09-07T20:00:00+11:00"),
            ("b", "codex", "2026-09-07T12:00:00Z"),
        ]
    )
    report = _source_export_lag(conn, datetime(2026, 9, 8, 12, 0, tzinfo=UTC), 7)
    assert len(report) == 1
    assert report[0]["newest_session"] == "2026-09-07T12:00:00Z"
    assert report[0]["stale"] is False


def test_lag_classifies_stale_fresh_and_future_per_source() -> None:
    conn = _store(
        [
            ("a", "codex", "2026-08-01T00:00:00Z"),
            ("b", "kiro_cli", "2026-09-08T00:00:00Z"),
            ("c", "opencode", "2026-09-20T00:00:00Z"),
            ("d", "grok", "malformed"),
        ]
    )
    report = _source_export_lag(conn, datetime(2026, 9, 8, 12, 0, tzinfo=UTC), 7)
    by_source = {row["source"]: row for row in report}
    assert by_source["codex"]["stale"] is True
    assert by_source["kiro_cli"]["stale"] is False
    assert by_source["opencode"]["in_future"] is True
    assert "grok" not in by_source
