"""Run actual StudyLoop readers over synthetic data in an isolated subprocess."""

import argparse
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.migrations import migrate

from ..assertion_gate.viewer import block, escape


def probe():
    from studyloop.cli._extract import _process_one
    from studyloop.history import _connection, get_last_session_summary, get_study_streaks
    from studyloop.history.search import topic_frequency
    from studyloop.mcp.server import mcp

    delivered = []

    def test_provider(messages, session_id):
        delivered.append({"session": session_id, "messages": messages})
        return []

    conn = _connection._connect()
    assert conn is not None
    write_status = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                _process_one(conn, "work", test_provider, dry_run=True)
            except ScopeError:
                pass
            else:
                raise AssertionError("Excluded direct ID must report unavailable")
            assert delivered == []
            _process_one(conn, "personal", test_provider, dry_run=True)
            try:
                _process_one(conn, "personal", test_provider, dry_run=False)
            except ScopeError:
                write_status = "withheld_missing_scope_lineage_before_provider"
            else:
                assert conn.execute("PRAGMA user_version").fetchone()[0] >= 33
                write_status = "source_linked_observations_available_no_reports_returned"
            assert len(delivered) == (1 if write_status.startswith("withheld") else 2)
    finally:
        conn.close()
    result = {
        "resume": get_last_session_summary(),
        "topic_matches": topic_frequency(["python", "redshift"]),
        "streaks": get_study_streaks(),
        "extractor_deliveries": delivered,
        "classified_progress_write": write_status,
        "mcp_history": mcp._tool_manager._tools["get_study_history"].fn(topic="python"),
    }
    print(json.dumps(result, indent=2))


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    db = output / "sessions.db"
    config = output / "config.yaml"
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/lesson/personal"]},
                "work": {"scope": "work", "roots": ["/lesson/work"]},
            },
        }
    }
    config.write_text(json.dumps(settings, indent=2) + "\n")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
        migrate(conn)
        now = datetime.now(UTC)
        for index, (sid, word) in enumerate([("personal", "python"), ("work", "redshift")]):
            stamp = (now - timedelta(minutes=2 - index)).isoformat()
            conn.execute(
                "INSERT INTO sessions(id,source,project_path,created_at,updated_at) "
                "VALUES (?,?,?,?,?)",
                (sid, "kiro_cli", "/lesson/" + sid, stamp, stamp),
            )
            for seq, role in enumerate(["user", "assistant"]):
                conn.execute(
                    "INSERT INTO messages(id,session_id,role,content,seq,timestamp) "
                    "VALUES (?,?,?,?,?,?)",
                    (sid + str(seq), sid, role, f"{word} question? {sid.upper()}_ONLY", seq, stamp),
                )
        conn.execute(
            "INSERT INTO study_progress(id,topic,concept,confidence,first_seen,last_seen) "
            "VALUES (?,?,?,?,?,?)",
            ("mixed", "sql", "UNOWNED_LEARNING_BODY", "learning", now.isoformat(), now.isoformat()),
        )
        conn.commit()
        apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
    finally:
        conn.close()
    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(config),
        "STUDYLOOP_DB": str(db),
        "STUDYLOOP_STATE_DIR": str(output / "state"),
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    env.pop("SESSION_CONTEXT_SCOPE", None)

    def command(module, args, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", module, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == expected, result.stderr
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

    observed = json.loads(command(__spec__.name, ["--probe"])["stdout"])
    assert observed["resume"]["session_id"] == "personal"
    assert observed["streaks"]["sessions_this_week"] == 1
    assert 1 <= len(observed["extractor_deliveries"]) <= 2
    assert observed["extractor_deliveries"][0]["session"] == "personal"
    cli_result = command("studyloop.cli", ["resume"])
    assert "PERSONAL_ONLY" in cli_result["stdout"]
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    config.write_text(json.dumps(settings, indent=2) + "\n")
    drift = command("studyloop.cli", ["resume"], expected=1)
    assert "session-context policy apply" in drift["stderr"]
    result = {
        "mode": (
            "Synthetic sources, actual workspace consumers; no gateway calls or native capture."
        ),
        "observations": observed,
        "resume_command": cli_result,
        "after_unapplied_config_change": drift,
        "limits": (
            "Global learning lineage remains incomplete. This stage withholds those fields in "
            "resume/history/stats/wins. Other derived consumers, scoped writes, sync, lifecycle "
            "and installed release acceptance remain required."
        ),
    }
    encoded = json.dumps(result, indent=2)
    assert "WORK_ONLY" not in encoded and "UNOWNED_LEARNING_BODY" not in encoded
    (output / "results.json").write_text(encoded + "\n")
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>Stage20 · StudyLoop consumes scoped history</title><style>
body{font:17px/1.6 system-ui;max-width:950px;margin:40px auto;padding:0 22px;
color:#20303a;background:#faf9f5}pre{white-space:pre-wrap;overflow-wrap:anywhere;
background:#edf1f3;padding:16px;font:14px/1.5 monospace}summary{cursor:pointer;padding:12px 0}
</style><h1>StudyLoop consumes scoped history</h1>
<p>Two fictional conversations use the same harness. The work conversation is newer.
The request scope is personal. A merged learning record has no reliable scope lineage.</p>
<p>Expand each actual result. The extractor is a local spy returning no learning records;
it records what it receives and makes no network call.</p>"""
    for name, value in {
        **observed,
        "Actual resume command": cli_result,
        "Unapplied config change": drift,
    }.items():
        page += "<details><summary>" + escape(name) + "</summary>" + block(value) + "</details>"
    page += "<h2>Remaining work</h2><p>" + escape(result["limits"]) + "</p></html>"
    (output / "walkthrough.html").write_text(page)
    print(json.dumps({"output": str(output), "unexpected_body": False}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        probe()
    elif args.output:
        run(args.output)
    else:
        parser.error("--output is required")


if __name__ == "__main__":
    main()
