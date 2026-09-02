"""Tests for session_state.py — IPC file read/write/parse."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_read_session_state_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns {} when state file doesn't exist."""
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", tmp_path / "missing.json")
    from studyloop.session_state import read_session_state

    assert read_session_state() == {}


def test_read_session_state_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns parsed JSON when state file exists."""
    state_file = tmp_path / "session-state.json"
    state_file.write_text(json.dumps({"energy": 7, "topic": "python"}))
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", state_file)
    from studyloop.session_state import read_session_state

    result = read_session_state()
    assert result["energy"] == 7
    assert result["topic"] == "python"


def test_read_session_state_corrupt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns {} on corrupt JSON (never raises)."""
    state_file = tmp_path / "session-state.json"
    state_file.write_text("{invalid json")
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", state_file)
    from studyloop.session_state import read_session_state

    assert read_session_state() == {}


def test_write_session_state_creates_and_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write_session_state creates file and merges updates."""
    state_file = tmp_path / "session-state.json"
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", state_file)
    monkeypatch.setattr("studyloop.session_state.SESSION_DIR", tmp_path)
    from studyloop.session_state import write_session_state

    write_session_state({"energy": 5, "topic": "sql"})
    data = json.loads(state_file.read_text())
    assert data["energy"] == 5

    write_session_state({"energy": 8})
    data = json.loads(state_file.read_text())
    assert data["energy"] == 8
    assert data["topic"] == "sql"  # preserved from first write


def test_parse_topics_file_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns [] when topics file doesn't exist."""
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", tmp_path / "missing.md")
    from studyloop.session_state import parse_topics_file

    assert parse_topics_file() == []


def test_parse_topics_file_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parses well-formed topic entries."""
    topics_file = tmp_path / "session-topics.md"
    topics_file.write_text(
        "- [09:14] Spark partitioning | status:learning | Basic concepts clicked\n"
        "- [09:31] SQL window functions | status:struggling | Re-explained twice\n"
        "- [09:45] ECMP bridge | status:insight | Student-generated bridge\n"
    )
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", topics_file)
    from studyloop.session_state import parse_topics_file

    entries = parse_topics_file()
    assert len(entries) == 3
    assert entries[0].time == "09:14"
    assert entries[0].topic == "Spark partitioning"
    assert entries[0].status == "learning"
    assert entries[0].note == "Basic concepts clicked"
    assert entries[1].status == "struggling"
    assert entries[2].status == "insight"


def test_parse_topics_file_skips_malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skips malformed lines without crashing."""
    topics_file = tmp_path / "session-topics.md"
    topics_file.write_text(
        "- [09:14] Good line | status:learning | Note\n"
        "This is not a valid line\n"
        "\n"
        "- bad format no brackets\n"
        "- [09:30] Also good | status:win | Got it\n"
    )
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", topics_file)
    from studyloop.session_state import parse_topics_file

    entries = parse_topics_file()
    assert len(entries) == 2
    assert entries[0].topic == "Good line"
    assert entries[1].status == "win"


def test_parse_parking_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parses parking lot entries."""
    parking_file = tmp_path / "session-parking.md"
    parking_file.write_text(
        "- How does the GIL affect multiprocessing?\n- VPC peering vs Transit Gateway\n"
    )
    monkeypatch.setattr("studyloop.session_state.PARKING_FILE", parking_file)
    from studyloop.session_state import parse_parking_file

    entries = parse_parking_file()
    assert len(entries) == 2
    assert entries[0].question == "How does the GIL affect multiprocessing?"


def test_append_topic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """append_topic adds a line to the topics file."""
    topics_file = tmp_path / "session-topics.md"
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", topics_file)
    monkeypatch.setattr("studyloop.session_state.SESSION_DIR", tmp_path)
    from studyloop.session_state import append_topic

    append_topic("10:00", "Spark DAGs", "learning", "Getting the concept")
    content = topics_file.read_text()
    assert "- [10:00] Spark DAGs | status:learning | Getting the concept" in content


def test_append_parking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """append_parking adds a line to the parking file."""
    parking_file = tmp_path / "session-parking.md"
    monkeypatch.setattr("studyloop.session_state.PARKING_FILE", parking_file)
    monkeypatch.setattr("studyloop.session_state.SESSION_DIR", tmp_path)
    from studyloop.session_state import append_parking

    append_parking("How does asyncio.gather work?")
    content = parking_file.read_text()
    assert "- How does asyncio.gather work?" in content


def test_clear_session_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """clear_session_files removes all IPC files."""
    state = tmp_path / "session-state.json"
    topics = tmp_path / "session-topics.md"
    parking = tmp_path / "session-parking.md"
    for f in (state, topics, parking):
        f.write_text("content")

    monkeypatch.setattr("studyloop.session_state.STATE_FILE", state)
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", topics)
    monkeypatch.setattr("studyloop.session_state.PARKING_FILE", parking)
    from studyloop.session_state import clear_session_files

    clear_session_files()
    assert not state.exists()
    assert not topics.exists()
    assert not parking.exists()


def test_is_session_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """is_session_active returns True only when study_session_id is set."""
    state_file = tmp_path / "session-state.json"
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", state_file)
    from studyloop.session_state import is_session_active

    assert not is_session_active()

    state_file.write_text(json.dumps({"energy": 5}))
    assert not is_session_active()

    state_file.write_text(json.dumps({"study_session_id": "abc-123"}))
    assert is_session_active()


class _VanishingFile:
    """A path that exists when checked but is gone when read.

    This is the deletion race in one object: session release calls
    ``clear_session_files()`` on an executor thread, so a file can be unlinked
    between an ``exists()`` check and the ``read_text()`` that follows it. The
    stub makes that interleaving deterministic — no threads, no timing.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def exists(self) -> bool:
        return True

    def read_text(self, *args: object, **kwargs: object) -> str:
        raise FileNotFoundError(2, "No such file or directory", self._name)


def test_parse_topics_file_survives_deletion_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns [] rather than raising when the file vanishes mid-read.

    Against the previous exists()-then-read() form this raised
    FileNotFoundError, which surfaced as HTTP 500 from GET /api/session/state.
    """
    monkeypatch.setattr(
        "studyloop.session_state.TOPICS_FILE",
        _VanishingFile("session-topics.md"),
    )
    from studyloop.session_state import parse_topics_file

    assert parse_topics_file() == []


def test_parse_parking_file_survives_deletion_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns [] rather than raising when the file vanishes mid-read."""
    monkeypatch.setattr(
        "studyloop.session_state.PARKING_FILE",
        _VanishingFile("session-parking.md"),
    )
    from studyloop.session_state import parse_parking_file

    assert parse_parking_file() == []


def test_parsers_tolerate_unreadable_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Any OSError is absorbed, not just a missing file.

    A directory standing where a file is expected raises IsADirectoryError on
    read. Uses the real filesystem, so it also proves the guard is not merely
    catching the stub above.
    """
    a_dir = tmp_path / "session-topics.md"
    a_dir.mkdir()
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", a_dir)
    monkeypatch.setattr("studyloop.session_state.PARKING_FILE", a_dir)
    from studyloop.session_state import parse_parking_file, parse_topics_file

    assert parse_topics_file() == []
    assert parse_parking_file() == []


# ---------------------------------------------------------------------------
# claim_blocks_cli_start (R-01b) -- the CLI start path's own liveness check,
# mirroring claim_blocks_web_start (docs/architecture/session-authority.md
# clause 2).
# ---------------------------------------------------------------------------


def test_claim_blocks_cli_start_no_claim_never_blocks() -> None:
    from studyloop.session_state import claim_blocks_cli_start

    assert claim_blocks_cli_start({}) is False


def test_claim_blocks_cli_start_ended_claim_never_blocks() -> None:
    from studyloop.session_state import claim_blocks_cli_start

    assert claim_blocks_cli_start({"study_session_id": "x", "mode": "ended"}) is False


def test_claim_blocks_cli_start_live_cli_claim_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CLI-owned claim (no transport key) blocks iff its recorded
    multiplexer session still exists."""
    from studyloop.session_state import claim_blocks_cli_start

    state = {"study_session_id": "x", "mode": "focus", "mux_session": "study-x"}
    monkeypatch.setattr(
        "studyloop.multiplexer.get_backend",
        lambda: type("_Mux", (), {"session_exists": staticmethod(lambda name: True)})(),
    )

    assert claim_blocks_cli_start(state) is True


def test_claim_blocks_cli_start_dead_cli_claim_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from studyloop.session_state import claim_blocks_cli_start

    state = {"study_session_id": "x", "mode": "focus", "mux_session": "study-x"}
    monkeypatch.setattr(
        "studyloop.multiplexer.get_backend",
        lambda: type("_Mux", (), {"session_exists": staticmethod(lambda name: False)})(),
    )

    assert claim_blocks_cli_start(state) is False


def test_claim_blocks_cli_start_cli_claim_with_no_session_name_does_not_block() -> None:
    """No mux/tmux session name recorded means "can't confirm it's alive" --
    treated conservatively as NOT blocking (stale), same rule
    claim_blocks_web_start already applies."""
    from studyloop.session_state import claim_blocks_cli_start

    assert claim_blocks_cli_start({"study_session_id": "x", "mode": "focus"}) is False


def test_claim_blocks_cli_start_live_web_claim_blocks() -> None:
    """A web-owned claim (transport pty/acp) read from the CLI process
    blocks iff its recorded pid is alive."""
    from studyloop.session_state import claim_blocks_cli_start

    state = {
        "study_session_id": "x",
        "mode": "focus",
        "transport": "pty",
        "pid": os.getpid(),
    }
    assert claim_blocks_cli_start(state) is True


def test_claim_blocks_cli_start_dead_web_claim_does_not_block() -> None:
    from studyloop.session_state import claim_blocks_cli_start

    state = {
        "study_session_id": "x",
        "mode": "focus",
        "transport": "pty",
        "pid": 999999999,
    }
    assert claim_blocks_cli_start(state) is False


def test_claim_blocks_cli_start_web_claim_with_no_pid_blocks_conservatively() -> None:
    """No `pid` recorded (a claim written by an older build) blocks --
    the existing message tells the user how to end it explicitly, which is
    safer than reclaiming a claim this process cannot verify."""
    from studyloop.session_state import claim_blocks_cli_start

    state = {"study_session_id": "x", "mode": "focus", "transport": "acp"}
    assert claim_blocks_cli_start(state) is True


def test_claim_blocks_cli_start_permission_error_counts_as_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pid the CLI process cannot signal (owned by another user, or
    reused) still has something live at it -- PermissionError means the
    kernel found a real process, not that the slot is free."""
    from studyloop.session_state import claim_blocks_cli_start

    def _raise_permission_error(pid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "kill", _raise_permission_error)
    state = {"study_session_id": "x", "mode": "focus", "transport": "pty", "pid": 4242}

    assert claim_blocks_cli_start(state) is True


def test_claim_blocks_cli_start_process_lookup_error_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from studyloop.session_state import claim_blocks_cli_start

    def _raise_process_lookup_error(pid: int, sig: int) -> None:
        raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(os, "kill", _raise_process_lookup_error)
    state = {"study_session_id": "x", "mode": "focus", "transport": "acp", "pid": 4242}

    assert claim_blocks_cli_start(state) is False


# ---------------------------------------------------------------------------
# claim_blocks_web_start (C3) -- a foreign, alive web server's pid now
# blocks a second web start; the process's own pid, or no pid at all,
# still behaves exactly as before R-01b.
# ---------------------------------------------------------------------------


def test_claim_blocks_web_start_foreign_alive_pid_blocks() -> None:
    from studyloop.session_state import claim_blocks_web_start

    # pid 1 (init/launchd) always exists and is always foreign to a test
    # process; os.kill(1, 0) raises PermissionError, which counts as alive.
    state = {"study_session_id": "x", "mode": "focus", "transport": "pty", "pid": 1}

    assert claim_blocks_web_start(state) is True


def test_claim_blocks_web_start_own_pid_does_not_block() -> None:
    from studyloop.session_state import claim_blocks_web_start

    state = {
        "study_session_id": "x",
        "mode": "focus",
        "transport": "acp",
        "pid": os.getpid(),
    }

    assert claim_blocks_web_start(state) is False


def test_claim_blocks_web_start_dead_foreign_pid_reclaims() -> None:
    from studyloop.session_state import claim_blocks_web_start

    state = {
        "study_session_id": "x",
        "mode": "focus",
        "transport": "pty",
        "pid": 999999999,
    }

    assert claim_blocks_web_start(state) is False


def test_claim_blocks_web_start_no_pid_unchanged() -> None:
    """A pty/acp claim with no pid recorded (a build before R-01b, or the
    in-process-singleton-already-ruled-out case R-01's own docstring
    describes) never blocks -- unchanged by C3."""
    from studyloop.session_state import claim_blocks_web_start

    state = {"study_session_id": "x", "mode": "focus", "transport": "acp"}

    assert claim_blocks_web_start(state) is False


# ---------------------------------------------------------------------------
# _cli_owned_claim_is_live (C5) -- a multiplexer backend that cannot be
# reached must still fail open (no crash, no false block), but must log
# the exception instead of swallowing it silently.
# ---------------------------------------------------------------------------


def test_cli_owned_claim_is_live_logs_when_the_backend_raises(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    from studyloop.session_state import _cli_owned_claim_is_live

    class _BrokenBackend:
        def session_exists(self, name: str) -> bool:
            raise RuntimeError("tmux server unreachable")

    monkeypatch.setattr("studyloop.multiplexer.get_backend", lambda: _BrokenBackend())
    state = {"mux_session": "study-x"}

    assert _cli_owned_claim_is_live(state) is False
    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "study-x" in warnings[0].message
    assert "tmux server unreachable" in warnings[0].message
