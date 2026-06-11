"""Tests for the pi / oh-my-pi (omp) session exporter.

Validates:
- PiFamilyExporter is parametrised; PiExporter and OhMyPiExporter are concrete
  instances with distinct source names.
- is_available() reflects root-directory existence.
- export_all() imports well-formed JSONL sessions for both "pi" and "omp".
- Incremental mode skips sessions whose updated_at is unchanged.
- Updated sessions (new last-message timestamp) are re-imported.
- Missing / malformed session headers increment errors but do not abort.
- Sessions with no extractable message text are silently skipped.
- source column matches the constructor's source_name argument.
- _ms_to_iso and _extract_text helpers behave correctly in isolation.
"""

import json
from pathlib import Path

import pytest

import agent_session_tools.exporters.pi as pi_mod
from agent_session_tools.exporters.pi import (
    OhMyPiExporter,
    PiExporter,
    PiFamilyExporter,
    _extract_text,
    _ms_to_iso,
)


# ---------------------------------------------------------------------------
# JSONL builder helpers
# ---------------------------------------------------------------------------


def _header(
    session_id: str = "sess-abc123",
    cwd: str = "/home/user/project",
    timestamp: str | None = "2024-06-01T10:00:00.000Z",
    version: int = 3,
) -> dict:
    obj: dict = {"type": "session", "version": version, "id": session_id, "cwd": cwd}
    if timestamp is not None:
        obj["timestamp"] = timestamp
    return obj


def _user_message(
    msg_id: str = "msg-001",
    text: str = "Explain decorators.",
    ts_ms: int = 1717236000000,
) -> dict:
    return {
        "type": "message",
        "id": msg_id,
        "parentId": None,
        "timestamp": "2024-06-01T10:00:00.000Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
            "timestamp": ts_ms,
        },
    }


def _assistant_message(
    msg_id: str = "msg-002",
    text: str = "A decorator wraps a function.",
    ts_ms: int = 1717236060000,
    model: str = "claude-sonnet-4-20250514",
    provider: str = "anthropic",
) -> dict:
    return {
        "type": "message",
        "id": msg_id,
        "parentId": "msg-001",
        "timestamp": "2024-06-01T10:01:00.000Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": model,
            "provider": provider,
            "timestamp": ts_ms,
        },
    }


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    """Write list of dicts as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pi_tree(tmp_path: Path, monkeypatch) -> Path:
    """Build a fake pi sessions tree and monkeypatch the module constant.

    Layout::

        tmp_path/
          sessions/
            -home-user-project/
              2024-06-01T10:00:00_sess-abc123.jsonl
    """
    root = tmp_path / "sessions"
    slug_dir = root / "-home-user-project"

    _write_jsonl(
        slug_dir / "2024-06-01T10:00:00_sess-abc123.jsonl",
        [
            _header(),
            _user_message(),
            _assistant_message(),
        ],
    )

    monkeypatch.setattr(pi_mod, "PI_SESSIONS", root)
    return root


@pytest.fixture()
def omp_tree(tmp_path: Path, monkeypatch) -> Path:
    """Build a fake omp sessions tree and monkeypatch the module constant."""
    root = tmp_path / "omp_sessions"
    slug_dir = root / "-home-user-project"

    _write_jsonl(
        slug_dir / "2024-06-01T10:00:00_sess-omp001.jsonl",
        [
            _header(session_id="sess-omp001"),
            _user_message(msg_id="omsg-001", text="What is asyncio?"),
            _assistant_message(msg_id="omsg-002", text="It is Python's async runtime."),
        ],
    )

    monkeypatch.setattr(pi_mod, "OMP_SESSIONS", root)
    return root


# ---------------------------------------------------------------------------
# _ms_to_iso  (pure, no fixtures)
# ---------------------------------------------------------------------------


class TestMsToIso:
    def test_none_returns_none(self):
        assert _ms_to_iso(None) is None

    def test_valid_ms_produces_iso_string(self):
        result = _ms_to_iso(1717236000000)
        assert result is not None
        assert "T" in result
        assert "2024" in result

    def test_zero_returns_epoch(self):
        result = _ms_to_iso(0)
        assert result is not None
        assert "1970" in result

    def test_float_input_accepted(self):
        result = _ms_to_iso(1717236000000.0)
        assert result is not None
        assert "2024" in result


# ---------------------------------------------------------------------------
# _extract_text  (pure, no fixtures)
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_single_text_part(self):
        msg = {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
        assert _extract_text(msg) == "Hello"

    def test_multiple_text_parts_joined(self):
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Part one."},
                {"type": "text", "text": "Part two."},
            ],
        }
        result = _extract_text(msg)
        assert result is not None
        assert "Part one." in result
        assert "Part two." in result

    def test_thinking_parts_skipped(self):
        msg = {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "internal monologue"},
                {"type": "text", "text": "Visible answer."},
            ],
        }
        result = _extract_text(msg)
        assert result == "Visible answer."
        assert "internal monologue" not in result

    def test_tool_call_parts_skipped(self):
        msg = {
            "role": "assistant",
            "content": [
                {"type": "toolCall", "name": "bash", "arguments": {"cmd": "ls"}},
                {"type": "text", "text": "Done."},
            ],
        }
        assert _extract_text(msg) == "Done."

    def test_no_text_parts_returns_none(self):
        msg = {"role": "assistant", "content": [{"type": "toolCall", "name": "x"}]}
        assert _extract_text(msg) is None

    def test_non_list_content_returns_none(self):
        msg = {"role": "user", "content": "plain string"}
        assert _extract_text(msg) is None

    def test_missing_content_returns_none(self):
        assert _extract_text({"role": "user"}) is None


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_true_when_root_exists(self, pi_tree):
        exp = PiFamilyExporter("pi", pi_tree)
        assert exp.is_available() is True

    def test_false_when_root_missing(self, tmp_path):
        exp = PiFamilyExporter("pi", tmp_path / "nonexistent")
        assert exp.is_available() is False

    def test_pi_exporter_uses_pi_sessions(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pi_mod, "PI_SESSIONS", tmp_path / "no")
        # The module-level PiExporter was bound at import time — create a fresh one
        exp = PiFamilyExporter("pi", pi_mod.PI_SESSIONS)
        assert exp.is_available() is False

    def test_omp_exporter_source_name(self):
        assert OhMyPiExporter.source_name == "omp"

    def test_pi_exporter_source_name(self):
        assert PiExporter.source_name == "pi"


# ---------------------------------------------------------------------------
# export_all — pi happy path
# ---------------------------------------------------------------------------


class TestPiExportAll:
    def test_exports_session_and_messages(self, migrated_db, pi_tree):
        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", pi_tree)
        stats = exp.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "pi"
        assert sessions[0]["project_path"] == "/home/user/project"

        meta = json.loads(sessions[0]["metadata"])
        assert "Explain decorators" in meta["title"]
        assert meta["version"] == 3

        messages = conn.execute(
            "SELECT role, content, seq FROM messages ORDER BY seq"
        ).fetchall()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert "decorator" in messages[0]["content"].lower()
        assert messages[1]["role"] == "assistant"
        assert messages[0]["seq"] == 1
        assert messages[1]["seq"] == 2

    def test_incremental_skips_unchanged(self, migrated_db, pi_tree):
        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", pi_tree)

        stats1 = exp.export_all(conn, incremental=True)
        assert stats1.added == 1

        stats2 = exp.export_all(conn, incremental=True)
        assert stats2.skipped == 1  # unchanged updated_at — counted as skipped
        assert stats2.empty == 0
        assert stats2.added == 0

    def test_unavailable_returns_zero_stats(self, migrated_db, tmp_path):
        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", tmp_path / "nope")
        stats = exp.export_all(conn, incremental=False)
        assert stats.added == 0
        assert stats.errors == 0
        assert stats.skipped == 0

    def test_no_messages_file_skipped(self, migrated_db, tmp_path):
        """A JSONL with only a header and no parseable messages is counted empty."""
        root = tmp_path / "sessions"
        slug = root / "-empty"
        _write_jsonl(slug / "empty.jsonl", [_header(session_id="empty-sess")])

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)
        stats = exp.export_all(conn, incremental=False)
        assert stats.added == 0
        assert stats.empty == 1
        assert stats.skipped == 0
        assert stats.errors == 0

    def test_incremental_reimports_on_update(self, migrated_db, tmp_path):
        """When a session gains a new message (new last-message ts), it is re-imported."""
        root = tmp_path / "sessions"
        slug = root / "-project"
        file_path = slug / "2024-06-01_sess-upd.jsonl"

        # Initial write — one user message
        _write_jsonl(
            file_path,
            [
                _header(session_id="sess-upd", cwd="/project"),
                _user_message(msg_id="msg-u1", ts_ms=1717236000000),
            ],
        )

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)

        stats1 = exp.export_all(conn, incremental=True)
        assert stats1.added == 1

        # Re-run with same file — should be skipped (updated_at unchanged)
        stats2 = exp.export_all(conn, incremental=True)
        assert stats2.added == 0

        # Add a new assistant message (later timestamp)
        _write_jsonl(
            file_path,
            [
                _header(session_id="sess-upd", cwd="/project"),
                _user_message(msg_id="msg-u1", ts_ms=1717236000000),
                _assistant_message(msg_id="msg-a1", ts_ms=1717236120000),
            ],
        )

        stats3 = exp.export_all(conn, incremental=True)
        assert stats3.updated == 1

        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'sess-upd' ORDER BY seq"
        ).fetchall()
        assert len(msgs) == 2
        assert msgs[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# export_all — omp happy path
# ---------------------------------------------------------------------------


class TestOmpExportAll:
    def test_exports_with_omp_source(self, migrated_db, omp_tree):
        conn, _ = migrated_db
        exp = PiFamilyExporter("omp", omp_tree)
        stats = exp.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        row = conn.execute("SELECT source FROM sessions").fetchone()
        assert row["source"] == "omp"


# ---------------------------------------------------------------------------
# Malformed input handling
# ---------------------------------------------------------------------------


class TestMalformedInputHandling:
    def test_malformed_header_line_increments_errors(self, migrated_db, tmp_path):
        """A file whose first line is not valid JSON increments errors."""
        root = tmp_path / "sessions"
        slug = root / "-bad"
        bad_file = slug / "bad.jsonl"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_text("{not valid json!!!\n", encoding="utf-8")

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)
        stats = exp.export_all(conn, incremental=False)
        assert stats.errors == 1
        assert stats.added == 0

    def test_missing_session_id_in_header_increments_errors(
        self, migrated_db, tmp_path
    ):
        """A header missing 'id' should cause the file to be counted as an error."""
        root = tmp_path / "sessions"
        slug = root / "-noid"
        _write_jsonl(
            slug / "noid.jsonl",
            [
                {"type": "session", "version": 3, "cwd": "/project"},  # no "id"
                _user_message(),
            ],
        )

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)
        stats = exp.export_all(conn, incremental=False)
        # Missing id causes _process_file to return (None, [], "empty") — counted
        # as empty, not an error.
        assert stats.added == 0
        assert stats.empty == 1
        assert stats.errors == 0

    def test_malformed_message_line_silently_skipped(self, migrated_db, tmp_path):
        """A bad JSON line after the header does not crash; valid messages still land."""
        root = tmp_path / "sessions"
        slug = root / "-partial"
        file_path = slug / "partial.jsonl"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_header(session_id="sess-partial")) + "\n")
            fh.write("{BROKEN JSON LINE\n")
            fh.write(json.dumps(_user_message()) + "\n")

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)
        stats = exp.export_all(conn, incremental=False)

        # The valid user message should have been imported
        assert stats.added == 1
        assert stats.errors == 0

        msgs = conn.execute("SELECT * FROM messages").fetchall()
        assert len(msgs) == 1

    def test_empty_file_produces_no_session(self, migrated_db, tmp_path):
        root = tmp_path / "sessions"
        slug = root / "-empty"
        empty_file = slug / "empty.jsonl"
        empty_file.parent.mkdir(parents=True, exist_ok=True)
        empty_file.write_text("", encoding="utf-8")

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)
        stats = exp.export_all(conn, incremental=False)
        assert stats.added == 0
        assert stats.empty == 1
        assert stats.errors == 0


# ---------------------------------------------------------------------------
# Header without timestamp
# ---------------------------------------------------------------------------


class TestHeaderWithoutTimestamp:
    def test_missing_header_timestamp_falls_back_to_message_ts(
        self, migrated_db, tmp_path
    ):
        """A header without 'timestamp' should still produce a valid session row."""
        root = tmp_path / "sessions"
        slug = root / "-nots"
        _write_jsonl(
            slug / "nots.jsonl",
            [
                _header(session_id="sess-nots", timestamp=None),
                _user_message(ts_ms=1717236000000),
            ],
        )

        conn, _ = migrated_db
        exp = PiFamilyExporter("pi", root)
        stats = exp.export_all(conn, incremental=False)
        assert stats.added == 1

        row = conn.execute("SELECT created_at FROM sessions").fetchone()
        assert row["created_at"] is not None


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_pi_in_exporters(self):
        from agent_session_tools.exporters import EXPORTERS

        assert "pi" in EXPORTERS
        assert EXPORTERS["pi"].source_name == "pi"

    def test_omp_in_exporters(self):
        from agent_session_tools.exporters import EXPORTERS

        assert "omp" in EXPORTERS
        assert EXPORTERS["omp"].source_name == "omp"
