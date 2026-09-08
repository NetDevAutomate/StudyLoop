"""Subprocess loopback acceptance for session-sync over executable SSH/SCP shims."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SSH = """#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]; host, cmd = args[-2], args[-1]
Path(os.environ["SW_LOG"]).open("a").write(json.dumps({"tool":"ssh","host":host,"cmd":cmd})+"\\n")
if host in os.environ.get("SW_UNREACHABLE","").split(","):
    print(f"ssh: connect to host {host}: simulated unreachable", file=sys.stderr); raise SystemExit(255)
raise SystemExit(subprocess.run(["/bin/sh","-c",cmd]).returncode)
"""
_SCP = """#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
a = [x for x in sys.argv[1:] if not x.startswith("-")]; src, remote = a[-2], a[-1]; host, dst = remote.split(":",1)
Path(os.environ["SW_LOG"]).open("a").write(json.dumps({"tool":"scp","host":host,"dst":dst})+"\\n")
if host in os.environ.get("SW_UNREACHABLE","").split(","): raise SystemExit(255)
Path(dst).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
"""


@pytest.fixture
def ssh_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "transport.jsonl"
    for name, body in (("ssh", _SSH), ("scp", _SCP)):
        path = binaries / name
        path.write_text(body)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")
    monkeypatch.setenv("SW_LOG", str(log))
    monkeypatch.setenv("SW_UNREACHABLE", "")
    return log


@pytest.fixture
def peers(
    tmp_path: Path, migrated_db, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    conn, local = migrated_db
    conn.commit()
    peer = tmp_path / "peer" / "sessions.db"
    peer.parent.mkdir()
    with sqlite3.connect(peer) as target:
        conn.backup(target)
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""database:
  path: {local}
logging:
  path: {tmp_path / "sync.log"}
hosts:
  peer-a:
    hostname: phase0-peer-a
    user: test
    ip_address:
      primary: peer-a
    sessions_db: {peer}
"""
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    return {"local": local, "peer": peer, "config": config}


def _sync(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["session-sync", *args], text=True, capture_output=True, check=False
    )


def _rows(db: Path, session_id: str) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return conn.execute(
            "SELECT id, content FROM messages WHERE session_id=? ORDER BY timestamp, id",
            (session_id,),
        ).fetchall()


def _snapshot(db: Path) -> tuple[tuple[int, int | None], tuple[int]]:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return (
            conn.execute("SELECT count(*), max(rowid) FROM messages").fetchone(),
            conn.execute("SELECT count(*) FROM sessions").fetchone(),
        )


def _seed_session_and_message(
    db_path: Path,
    *,
    session_id: str,
    message_id: str,
    content: str,
    updated_at: str,
    source: str = "claude_code",
    role: str = "user",
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, source, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at",
            (session_id, source, updated_at),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, updated_at),
        )
        conn.commit()


def _seed_shared_session_with_local_m1_and_peer_m2(
    local_db: Path, peer_db: Path, session_id: str
) -> None:
    _seed_session_and_message(
        local_db,
        session_id=session_id,
        message_id=f"{session_id}-m1",
        content="local message one",
        updated_at="2026-01-01T00:10:00Z",
        role="user",
    )
    _seed_session_and_message(
        peer_db,
        session_id=session_id,
        message_id=f"{session_id}-m2",
        content="peer message two",
        updated_at="2026-01-01T00:00:00Z",
        role="assistant",
    )


def _seed_same_id_distinct_content(
    local_db: Path,
    peer_db: Path,
    message_id: str,
    local_content: str,
    peer_content: str,
    session_id: str = "conflict-session",
) -> None:
    _seed_session_and_message(
        local_db,
        session_id=session_id,
        message_id=message_id,
        content=local_content,
        updated_at="2026-01-01T00:00:00Z",
    )
    _seed_session_and_message(
        peer_db,
        session_id=session_id,
        message_id=message_id,
        content=peer_content,
        updated_at="2026-01-01T00:00:00Z",
    )


def _seed_identity_conflict_plus_unrelated_new_row(
    local_db: Path, peer_db: Path, *, unrelated: str
) -> None:
    _seed_session_and_message(
        peer_db,
        session_id="s1",
        message_id="shared-msg-id",
        content="peer's own message",
        updated_at="2026-01-01T00:00:00Z",
    )
    with sqlite3.connect(local_db) as conn:
        conn.execute(
            "INSERT INTO sessions (id, source, updated_at) VALUES (?, ?, ?)",
            ("s2", "claude_code", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
            ("shared-msg-id", "s2", "user", "local's conflicting message"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
            (unrelated, "s2", "user", "harmless new message"),
        )
        conn.commit()


@pytest.mark.xfail(
    strict=True,
    reason="BL-1: incremental push/pull timestamp gates cannot select both divergent copies",
)
def test_continued_conversation_reconciles_both_endpoints(
    ssh_shim: Path, peers: dict[str, Path]
) -> None:
    _seed_shared_session_with_local_m1_and_peer_m2(
        peers["local"], peers["peer"], "continued-session"
    )
    result = _sync("all", "--incremental")
    assert result.returncode == 0, result.stderr
    assert _rows(peers["local"], "continued-session") == _rows(
        peers["peer"], "continued-session"
    )
    assert len(_rows(peers["local"], "continued-session")) == 2


def test_repeat_sync_is_idempotent(ssh_shim: Path, peers: dict[str, Path]) -> None:
    _seed_shared_session_with_local_m1_and_peer_m2(peers["local"], peers["peer"], "s")
    assert _sync("all", "--incremental").returncode == 0
    before = (_snapshot(peers["local"]), _snapshot(peers["peer"]))
    assert _sync("all", "--incremental").returncode == 0
    assert (_snapshot(peers["local"]), _snapshot(peers["peer"])) == before


def test_conflicting_nonempty_message_content_is_never_overwritten(
    ssh_shim: Path, peers: dict[str, Path]
) -> None:
    _seed_same_id_distinct_content(
        peers["local"],
        peers["peer"],
        "conflict-msg",
        "local irreplaceable",
        "peer irreplaceable",
    )
    result = _sync("all", "--reconcile")
    assert dict(_rows(peers["local"], "conflict-session"))["conflict-msg"] == (
        "local irreplaceable"
    )
    assert dict(_rows(peers["peer"], "conflict-session"))["conflict-msg"] == (
        "peer irreplaceable"
    )
    assert result.returncode == 0
    assert "retained" in (result.stdout + result.stderr).lower()


def test_identity_conflict_aborts_whole_batch(
    ssh_shim: Path, peers: dict[str, Path]
) -> None:
    _seed_identity_conflict_plus_unrelated_new_row(
        peers["local"], peers["peer"], unrelated="unrelated-new"
    )
    result = _sync("all", "--incremental")
    assert result.returncode != 0
    assert all(row[0] != "unrelated-new" for row in _rows(peers["peer"], "s2"))


def test_unreachable_peer_nonzero_exit_other_peer_still_attempted(
    ssh_shim: Path,
    peers: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peers["config"].write_text(
        peers["config"].read_text()
        + f"  peer-b:\n    hostname: phase0-peer-b\n    user: test\n    ip_address:\n"
        f"      primary: dead-peer\n    sessions_db: {tmp_path / 'dead' / 'sessions.db'}\n"
    )
    monkeypatch.setenv("SW_UNREACHABLE", "test@dead-peer")
    _seed_shared_session_with_local_m1_and_peer_m2(peers["local"], peers["peer"], "s3")
    result = _sync("all", "--incremental")
    hosts = {json.loads(line)["host"] for line in ssh_shim.read_text().splitlines()}
    assert result.returncode != 0
    assert {"test@peer-a", "test@dead-peer"} <= hosts
    assert len(_rows(peers["peer"], "s3")) == 2
