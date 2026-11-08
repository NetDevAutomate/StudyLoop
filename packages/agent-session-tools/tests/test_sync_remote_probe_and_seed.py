"""The remote probe is tri-state and the seed never overwrites in place.

Regression tests for the 2026-11-08 incident: a remote host without the
``sqlite3`` CLI made ``_remote_db_exists`` return False (exit 127 read as
"absent"), ``push`` scp'd the local DB straight over the existing remote
file, and the interrupted copy left a truncated, malformed database.

Two invariants are pinned here:

1. ``_remote_db_exists`` answers True (usable DB), False (nothing at the
   path), or raises ``RemoteProbeError``. "Could not tell" is never False.
2. ``_seed_remote_db`` copies a consistent snapshot to a sibling staging
   name and renames it with ``mv -n``; the destination is never written
   in place, and no snapshot is taken from the live file byte-for-byte.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools import sync
from agent_session_tools.sync import (
    RemoteProbeError,
    _remote_db_exists,
    _seed_remote_db,
)

HOST = "user@example.test"
REMOTE = "/home/user/.config/studyloop/sessions.db"
STAGING = f"{REMOTE}.seeding.{os.getpid()}"


def _completed(rc: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout="", stderr=stderr)


@dataclass
class FakeRun:
    """Stand-in for ``subprocess.run`` that records argv and answers per step.

    ``scp_rc`` / ``mv_rc`` fail the copy or the rename; ``on_scp`` lets a test
    inspect the snapshot file while it still exists.
    """

    scp_rc: int = 0
    mv_rc: int = 0
    on_scp: object = None
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv, **kwargs):  # noqa: ANN001 — mirrors subprocess.run
        self.calls.append(list(argv))
        if argv[0] == "scp":
            if self.on_scp is not None:
                self.on_scp(argv)  # type: ignore[operator]
            return _completed(
                self.scp_rc, "scp: connection lost" if self.scp_rc else ""
            )
        remote_cmd = argv[-1]
        if remote_cmd.startswith("mv -n"):
            return _completed(
                self.mv_rc, "mv: destination exists" if self.mv_rc else ""
            )
        return _completed(0)

    def remote_commands(self) -> list[str]:
        return [c[-1] for c in self.calls if c[0] == "ssh"]

    def scp_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] == "scp"]


# --- _remote_db_exists: tri-state ---


class TestRemoteProbe:
    def _probe(self, monkeypatch, rc: int, stderr: str = "") -> bool:
        monkeypatch.setattr(
            sync.subprocess, "run", lambda *a, **k: _completed(rc, stderr)
        )
        return _remote_db_exists(HOST, REMOTE)

    def test_zero_means_a_usable_database_is_present(self, monkeypatch):
        assert self._probe(monkeypatch, 0) is True

    def test_only_the_reserved_absent_code_means_absent(self, monkeypatch):
        assert self._probe(monkeypatch, sync._PROBE_ABSENT) is False

    @pytest.mark.parametrize(
        ("rc", "stderr"),
        [
            (1, "Parse error: database disk image is malformed (11)"),
            (1, "Parse error: no such table: sessions"),
            (sync._PROBE_NO_SQLITE3, ""),
            (126, "permission denied: sqlite3"),
            (127, "zsh:1: command not found: sqlite3"),
            (255, "ssh: connect to host example.test port 22: Connection refused"),
        ],
    )
    def test_every_other_outcome_raises_instead_of_reading_as_absent(
        self, monkeypatch, rc, stderr
    ):
        with pytest.raises(RemoteProbeError) as excinfo:
            self._probe(monkeypatch, rc, stderr)
        message = str(excinfo.value)
        assert HOST in message
        if stderr:
            assert stderr in message

    def test_missing_sqlite3_is_named_with_an_install_hint(self, monkeypatch):
        with pytest.raises(RemoteProbeError, match=r"sqlite3.*not found") as excinfo:
            self._probe(monkeypatch, sync._PROBE_NO_SQLITE3)
        assert "install" in str(excinfo.value).lower()

    def test_unreadable_file_message_says_the_file_was_found(self, monkeypatch):
        with pytest.raises(RemoteProbeError, match="exists but sqlite3 could not read"):
            self._probe(monkeypatch, 1, "database disk image is malformed")

    def test_probe_script_checks_tool_then_path_then_schema(self, monkeypatch):
        fake = FakeRun()
        monkeypatch.setattr(sync.subprocess, "run", fake)
        _remote_db_exists(HOST, REMOTE)

        (script,) = fake.remote_commands()
        tool = script.index("command -v sqlite3")
        path = script.index(f"test -e {REMOTE}")
        schema = script.index("FROM sessions")
        assert tool < path < schema, script
        assert f"exit {sync._PROBE_NO_SQLITE3}" in script
        assert f"exit {sync._PROBE_ABSENT}" in script
        # The probe must never create the file: sqlite3 runs only after test -e.
        assert script.index("sqlite3 " + REMOTE) > path


# --- CLI: push / pull abort on an unknown remote state ---


def _raise_probe_error(*_args, **_kwargs):
    raise RemoteProbeError(f"sqlite3 CLI not found on {HOST}")


def _never_seed(*_args, **_kwargs):
    pytest.fail("_seed_remote_db ran although the remote state was unknown")


class TestCliRefusesToActOnUnknownRemoteState:
    def test_push_aborts_before_seeding(self, temp_db, monkeypatch):
        _, db_path = temp_db
        monkeypatch.setattr(sync, "_remote_db_exists", _raise_probe_error)
        monkeypatch.setattr(sync, "_seed_remote_db", _never_seed)
        monkeypatch.setattr(sync, "_get_sync_state", _never_seed)

        result = CliRunner().invoke(
            sync.app, ["push", f"{HOST}:{REMOTE}", "--db", str(db_path)]
        )

        assert result.exit_code == 1
        assert "sqlite3 CLI not found" in result.output
        assert "left untouched" in result.output

    def test_pull_aborts_before_reading_remote(self, temp_db, monkeypatch):
        _, db_path = temp_db
        monkeypatch.setattr(sync, "_remote_db_exists", _raise_probe_error)
        monkeypatch.setattr(sync, "_remote_sql", _never_seed)

        result = CliRunner().invoke(
            sync.app,
            ["pull", f"{HOST}:{REMOTE}", "--db", str(db_path), "--no-backup"],
        )

        assert result.exit_code == 1
        assert "sqlite3 CLI not found" in result.output


# --- _seed_remote_db: snapshot, staging name, atomic no-clobber rename ---


def _insert_session(conn: sqlite3.Connection, sid: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at) "
        "VALUES (?, 'test', '2024-01-01', '2024-01-01')",
        (sid,),
    )
    conn.commit()


class TestSeedRemoteDb:
    def test_copies_a_consistent_snapshot_to_a_staging_name_then_renames(
        self, temp_db, monkeypatch
    ):
        conn, db_path = temp_db
        # WAL mode with an uncheckpointed commit: a byte-for-byte copy of the
        # main file would miss "in-wal"; the backup API must include it.
        conn.execute("PRAGMA journal_mode=WAL")
        _insert_session(conn, "on-disk")
        _insert_session(conn, "in-wal")
        assert (db_path.parent / f"{db_path.name}-wal").stat().st_size > 0

        seen: dict[str, object] = {}

        def inspect_snapshot(argv: list[str]) -> None:
            source, destination = argv[-2], argv[-1]
            seen["source"] = Path(source)
            seen["destination"] = destination
            snap = sqlite3.connect(source)
            try:
                seen["ok"] = snap.execute("PRAGMA integrity_check").fetchone()[0]
                seen["ids"] = {r[0] for r in snap.execute("SELECT id FROM sessions")}
            finally:
                snap.close()

        fake = FakeRun(on_scp=inspect_snapshot)
        monkeypatch.setattr(sync.subprocess, "run", fake)

        assert _seed_remote_db(HOST, REMOTE, db_path) is True

        # The snapshot is a separate, consistent file — not the live DB.
        assert seen["source"] != db_path
        assert seen["ok"] == "ok"
        assert seen["ids"] == {"on-disk", "in-wal"}
        assert not Path(str(seen["source"])).exists(), "snapshot must be cleaned up"

        # The copy lands at a sibling staging name, never at the final path.
        assert seen["destination"] == f"{HOST}:{STAGING}"
        assert all(c[-1] != f"{HOST}:{REMOTE}" for c in fake.scp_calls())

        # Rename happens after the copy, with -n, and verifies the move took.
        remote = fake.remote_commands()
        assert remote[0].startswith("mkdir -p ")
        mv = remote[-1]
        assert mv.startswith(f"mv -n {STAGING} {REMOTE}")
        assert f"test ! -e {STAGING}" in mv
        scp_index = next(i for i, c in enumerate(fake.calls) if c[0] == "scp")
        mv_index = next(i for i, c in enumerate(fake.calls) if c[-1] == mv)
        assert scp_index < mv_index

    def test_failed_copy_leaves_destination_alone_and_removes_staging(
        self, temp_db, monkeypatch
    ):
        conn, db_path = temp_db
        _insert_session(conn, "s1")
        fake = FakeRun(scp_rc=1)
        monkeypatch.setattr(sync.subprocess, "run", fake)

        assert _seed_remote_db(HOST, REMOTE, db_path) is False

        remote = fake.remote_commands()
        assert not any(c.startswith("mv ") for c in remote)
        assert f"rm -f {STAGING}" in remote

    def test_rename_refused_when_destination_appeared_meanwhile(
        self, temp_db, monkeypatch
    ):
        conn, db_path = temp_db
        _insert_session(conn, "s1")
        fake = FakeRun(mv_rc=1)
        monkeypatch.setattr(sync.subprocess, "run", fake)

        assert _seed_remote_db(HOST, REMOTE, db_path) is False

        remote = fake.remote_commands()
        assert f"rm -f {STAGING}" in remote
        assert not any(
            c.startswith("mv -f") or c.startswith("mv " + STAGING) for c in remote
        )

    def test_tilde_paths_expand_on_the_remote(self, temp_db, monkeypatch):
        conn, db_path = temp_db
        _insert_session(conn, "s1")
        fake = FakeRun()
        monkeypatch.setattr(sync.subprocess, "run", fake)

        assert _seed_remote_db(HOST, "~/.config/studyloop/sessions.db", db_path) is True

        mv = fake.remote_commands()[-1]
        assert '"$HOME/.config/studyloop/sessions.db"' in mv
        assert "~/" not in mv
        # scp gets a home-relative path: portable across legacy and SFTP modes,
        # where a literal ~ depends on server-side expansion support.
        (scp,) = fake.scp_calls()
        assert scp[-1] == f"{HOST}:.config/studyloop/sessions.db.seeding.{os.getpid()}"
