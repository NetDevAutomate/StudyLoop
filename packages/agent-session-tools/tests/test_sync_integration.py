"""Gate 2a. Executable ssh/scp shims on PATH; every DB under tmp_path. Never touches ~/.config/studyloop.

Exercises the 10 real `subprocess.run` call sites in sync.py (sync.py:359,
441, 460, 469, 486, 999, 1007, 1090, 1269, 1495 -- pack-phase0 pack §5.3)
through the real `session-sync` CLI entry point and the real process
boundary, using executable `ssh`/`scp` shims on PATH instead of
`monkeypatch`-ing `agent_session_tools.sync.subprocess.run`. This proves the
exact argv sync.py builds (including `_SSH_MUX_OPTS`, sync.py:304-319) is
correct, not just the Python-level call.

Two corrections made against the plan skeleton after reading sync.py:

* `logging.path` is pinned into every test's `hosts:` config (sync.py:273-283
  `_setup_logging`, an `@app.callback()` that runs on every CLI invocation
  and opens a `logging.FileHandler` at `get_log_path(cfg)`). The default
  config value resolves to `~/.config/studyloop/sessions.log`. The autouse
  `_isolated_studyloop_config` fixture in conftest.py only protects
  `agent_session_tools.*` module state inside *this* pytest process --
  `session-sync` runs as a genuinely separate subprocess (per this file's
  own docstring promise, "never touches ~/.config/studyloop"), so the log
  path has to be redirected explicitly in the written config.yaml.
* `SW_UNREACHABLE` is compared against the *literal* second-to-last ssh/scp
  argument, which is always `f"{username}@{ip}"` (sync.py:357
  `_resolve_remote`: `host = f"{username}@{ip}"`), not the bare `ip_address`
  value from config. The plan skeleton's `SW_UNREACHABLE=dead-peer` /
  `{"peer-a", "dead-peer"} <= hosts` never matches anything sync.py actually
  passes to ssh/scp (always `test@peer-a` / `test@dead-peer` here); both are
  written in the `user@ip` form actually observed on the wire (transport.jsonl).
"""

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
def ssh_shim(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    log = tmp_path / "transport.jsonl"
    for name, body in (("ssh", _SSH), ("scp", _SCP)):
        p = b / name
        p.write_text(body)
        p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")
    monkeypatch.setenv("SW_LOG", str(log))
    monkeypatch.setenv("SW_UNREACHABLE", "")
    return log


@pytest.fixture
def peers(tmp_path, migrated_db, monkeypatch):
    conn, local = migrated_db
    conn.commit()
    peer = tmp_path / "peer" / "sessions.db"
    peer.parent.mkdir()
    with sqlite3.connect(peer) as p:
        conn.backup(p)
    cfg = tmp_path / "config.yaml"
    # Local DB path config key verified against source: get_db_path()
    # (config_loader.py:350-370) reads config["database"]["path"] --
    # database.path, exactly as the plan skeleton guessed.
    # logging.path is pinned here too -- see module docstring correction #1.
    cfg.write_text(
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
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    return {"local": local, "peer": peer, "config": cfg}


def _sync(*args):  # CLI on PATH via the workspace venv
    return subprocess.run(
        ["session-sync", *args], text=True, capture_output=True, check=False
    )


def _rows(db, sid):
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        return c.execute(
            "SELECT id, content FROM messages WHERE session_id=? ORDER BY timestamp, id",
            (sid,),
        ).fetchall()


def _snapshot(db):
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        return (
            c.execute("SELECT count(*), max(rowid) FROM messages").fetchone(),
            c.execute("SELECT count(*) FROM sessions").fetchone(),
        )


# Insert helpers reuse the schema-valid minimal-column pattern from
# test_sync_conversation_integrity.py (`sessions(id,source)`,
# `messages(id,session_id,role,content)`) and test_sync_r19.py. Verified
# against schema.sql: the only NOT NULL columns are sessions.source,
# messages.session_id and messages.role -- every other column (including
# updated_at/timestamp) is nullable, so the helpers below only set the
# columns each scenario actually needs to distinguish.


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
    """Same conversation continued on both machines under the identical
    session id: `local` holds the earlier message (m1), `peer` holds a
    later one (m2). `local`'s session `updated_at` is kept strictly newer
    than `peer`'s so the session-level recency gate in
    `_get_sync_state`/`pull` (sync.py:845-880, sync.py:1250-1255) resolves
    `push` as the direction that carries `m1` to `peer` -- see
    reviews/2026-09-06-sessionweaver-phase0/evidence/gate2/REPRO.md for why
    a single `--incremental` pass cannot *also* pull `m2` back down to
    `local` in the same run once that push has equalised the two sides'
    `updated_at`.
    """
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
    """Same session id, same message id, different nonempty content on each
    side. Both sides use the same session `source` and `updated_at` so the
    only trigger this can fire is `sync_content_conflict`
    (sync.py:955-958) -- not `sync_session_identity` (sync.py:952-954).
    """
    _seed_session_and_message(
        local_db,
        session_id=session_id,
        message_id=message_id,
        content=local_content,
        updated_at="2026-01-01T00:00:00Z",
        role="user",
    )
    _seed_session_and_message(
        peer_db,
        session_id=session_id,
        message_id=message_id,
        content=peer_content,
        updated_at="2026-01-01T00:00:00Z",
        role="user",
    )


def _seed_identity_conflict_plus_unrelated_new_row(
    local_db: Path, peer_db: Path, *, unrelated: str
) -> None:
    """`peer` already owns message id `shared-msg-id` under session `s1`.
    `local` starts a brand-new session `s2` (unknown to `peer`, so it is
    unconditionally in `new_ids` regardless of timestamps -- sync.py:872)
    that reuses the same message id under the different session `s2`, in
    the same push batch as an unrelated, genuinely new row. The
    `sync_message_identity` BEFORE INSERT trigger (sync.py:949-951) fires
    when that row streams into `peer` and RAISEs(ABORT), rolling back the
    whole `sqlite3 -bail` transaction -- including the unrelated row
    inserted earlier in the same batch (proving atomicity, not per-row skip).
    """
    _seed_session_and_message(
        peer_db,
        session_id="s1",
        message_id="shared-msg-id",
        content="peer's own message",
        updated_at="2026-01-01T00:00:00Z",
        role="user",
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
    reason=(
        "sync.py's session-level recency gate makes push's and pull's "
        "inclusion conditions mutually exclusive under --incremental: "
        "whichever direction wins equalises both sides' session "
        "updated_at as a side effect, so the losing direction never runs "
        "in the same invocation and the losing side's exclusive message "
        "never comes back. See reviews/2026-09-06-sessionweaver-phase0/"
        "evidence/gate2/REPRO.md (sync.py:872-880, sync.py:1239-1255, "
        "sync.py:579-580). Not fixable without changing sync.py, which is "
        "out of scope for WP-4."
    ),
)
def test_continued_conversation_reconciles_both_endpoints(ssh_shim, peers):
    _seed_shared_session_with_local_m1_and_peer_m2(
        peers["local"], peers["peer"], "continued-session"
    )
    r = _sync("all", "--incremental")
    assert r.returncode == 0, r.stderr
    assert _rows(peers["local"], "continued-session") == _rows(
        peers["peer"], "continued-session"
    )
    assert len(_rows(peers["local"], "continued-session")) == 2


def test_repeat_sync_is_idempotent(ssh_shim, peers):
    _seed_shared_session_with_local_m1_and_peer_m2(peers["local"], peers["peer"], "s")
    assert _sync("all", "--incremental").returncode == 0
    before = (_snapshot(peers["local"]), _snapshot(peers["peer"]))
    assert _sync("all", "--incremental").returncode == 0
    assert (_snapshot(peers["local"]), _snapshot(peers["peer"])) == before


def test_conflicting_nonempty_message_content_is_never_overwritten(ssh_shim, peers):
    """`sync_content_conflict` (sync.py:955-958) is `BEFORE INSERT ... BEGIN
    INSERT OR IGNORE INTO sync_conflicts VALUES(NEW.id); END` -- it records
    the divergent id and lets the statement's own `ON CONFLICT(id) DO
    UPDATE SET content = COALESCE(NULLIF(messages.content,''),
    excluded.content)` (sync.py:576, `_build_insert_select_sql`) proceed:
    since the destination's content is already nonempty, COALESCE keeps
    it and discards the incoming value. The transaction commits (no
    RAISE(ABORT) anywhere in this trigger) and `_stream_sql_to_target`
    (sync.py:1030-1032) prints "Retained destination content for N
    divergent message(s) ... No content was overwritten." to stdout via
    `console.print`. EXPECT_ABORT = False.
    """
    EXPECT_ABORT = False
    _seed_same_id_distinct_content(
        peers["local"],
        peers["peer"],
        "conflict-msg",
        "local irreplaceable",
        "peer irreplaceable",
    )
    r = _sync("all", "--reconcile")
    assert (
        dict(_rows(peers["local"], "conflict-session"))["conflict-msg"]
        == "local irreplaceable"
    )
    assert (
        dict(_rows(peers["peer"], "conflict-session"))["conflict-msg"]
        == "peer irreplaceable"
    )
    if EXPECT_ABORT:
        assert r.returncode != 0
    else:
        assert r.returncode == 0 and "retained" in (r.stdout + r.stderr).lower()


def test_identity_conflict_aborts_whole_batch(ssh_shim, peers):
    """Same message id claimed by a different session_id -> RAISE(ABORT)
    rolls back the whole `sqlite3 -bail` batch (sync.py:999/1007 paths).
    """
    _seed_identity_conflict_plus_unrelated_new_row(
        peers["local"], peers["peer"], unrelated="unrelated-new"
    )
    r = _sync("all", "--incremental")
    assert r.returncode != 0
    assert all(
        row[0] != "unrelated-new" for row in _rows(peers["peer"], "s2")
    )  # atomicity, not per-row skip


def test_unreachable_peer_nonzero_exit_other_peer_still_attempted(
    ssh_shim, peers, tmp_path, monkeypatch
):
    peers["config"].write_text(
        peers["config"].read_text()
        + f"  peer-b:\n    hostname: phase0-peer-b\n    user: test\n    ip_address:\n"
        f"      primary: dead-peer\n    sessions_db: {tmp_path / 'dead' / 'sessions.db'}\n"
    )
    # sync.py:357 (_resolve_remote) builds ssh/scp's host argument as
    # f"{username}@{ip}" -- "test@dead-peer" here, never the bare
    # ip_address value -- so SW_UNREACHABLE and the assertion below use
    # that literal form (module docstring correction #2).
    monkeypatch.setenv("SW_UNREACHABLE", "test@dead-peer")
    _seed_shared_session_with_local_m1_and_peer_m2(peers["local"], peers["peer"], "s3")
    r = _sync("all", "--incremental")
    hosts = {json.loads(line)["host"] for line in ssh_shim.read_text().splitlines()}
    assert r.returncode != 0 and {"test@peer-a", "test@dead-peer"} <= hosts
    assert len(_rows(peers["peer"], "s3")) == 2  # reachable peer's push still landed
