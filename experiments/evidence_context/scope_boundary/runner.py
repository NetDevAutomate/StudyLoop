"""Offline policy/CLI lesson using only synthetic conversations in a disposable DB."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from agent_session_tools.migrations import migrate

from ..assertion_gate.viewer import block, escape


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    db = output / "sessions.db"
    config = output / "config.yaml"
    settings = {
        "database": {"path": str(db)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "demo-personal": {"scope": "personal", "roots": ["/demo/personal"]},
                "demo-work": {"scope": "work", "roots": ["/demo/work"]},
            },
        },
    }
    config.write_text(json.dumps(settings, indent=2) + "\n")
    conn = sqlite3.connect(db)
    try:
        conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
        migrate(conn)
        for sid, root, text in [
            ("personal", "/demo/personal", "retry PERSONAL_DEMO_VISIBLE"),
            ("work", "/demo/work", "retry WORK_DEMO_HIDDEN"),
            ("unknown", "/demo/unknown", "retry UNCLASSIFIED_DEMO_HIDDEN"),
        ]:
            conn.execute(
                "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
                (sid, "same-harness", root),
            )
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content,seq) VALUES (?,?,?,?,?)",
                (sid + "-message", sid, "assistant", text, 1),
            )
        conn.commit()
    finally:
        conn.close()
    env = {**os.environ, "STUDYLOOP_CONFIG": str(config)}
    env.pop("SESSION_CONTEXT_SCOPE", None)
    observations = []

    def command(label, module, args, code=0):
        completed = subprocess.run(
            [sys.executable, "-m", module, *args, "--db", str(db)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != code:
            raise AssertionError(
                f"{label}: expected exit {code}, got {completed.returncode}: {completed.stderr}"
            )
        entry = {
            "step": label,
            "command": " ".join([module, *args, "--db", "<demo-db>"]),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        observations.append(entry)
        return completed.stdout

    query_module = "agent_session_tools.query_sessions"
    policy_module = "agent_session_tools.context.cli"
    command(
        "Before applying the project policy",
        query_module,
        ["search", "retry", "--output-format", "json", "--local-only"],
        2,
    )
    plan = command(
        "Preview classifications without writes",
        policy_module,
        ["policy", "plan", "--actor", "lesson-fixture"],
    )
    assert json.loads(plan)["dry_run"]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM context_scope_audit").fetchone()[0] == 0
    conn.close()
    command(
        "Apply explicit classification",
        policy_module,
        ["policy", "apply", "--actor", "lesson-fixture"],
    )
    visible = command(
        "Personal search after apply",
        query_module,
        ["search", "retry", "--output-format", "json", "--local-only"],
    )
    assert [row["session_id"] for row in json.loads(visible)] == ["personal"]
    hidden = command(
        "A work project filter cannot change scope",
        query_module,
        ["search", "retry", "--project", "/demo/work", "--output-format", "json", "--local-only"],
    )
    assert json.loads(hidden) == []
    settings["memory"]["projects"]["demo-personal"]["scope"] = "work"
    config.write_text(json.dumps(settings, indent=2) + "\n")
    command(
        "Config changed but not yet applied", query_module, ["search", "retry", "--local-only"], 2
    )
    command(
        "Apply reclassification with an audit record",
        policy_module,
        ["policy", "apply", "--actor", "lesson-fixture"],
    )
    final = command(
        "The next personal query excludes reclassified sessions",
        query_module,
        ["search", "retry", "--output-format", "json", "--local-only"],
    )
    assert json.loads(final) == []
    assert all(
        "WORK_DEMO_HIDDEN" not in item["stdout"]
        and "UNCLASSIFIED_DEMO_HIDDEN" not in item["stdout"]
        for item in observations
    )
    result = {
        "mode": "Synthetic command journey; no model calls or real harness capture.",
        "scope_configuration": settings["memory"],
        "observations": observations,
        "limitations": (
            "Core read interfaces only. StudyLoop-specific consumers, native capture, "
            "sync and managed lifecycle remain separate integration work."
        ),
    }
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>Stage19 · Scope before retrieval</title><style>
body{font:17px/1.6 system-ui;max-width:950px;margin:40px auto;padding:0 22px;
color:#20303a;background:#faf9f5}pre{white-space:pre-wrap;overflow-wrap:anywhere;
background:#edf1f3;padding:16px;font:14px/1.5 monospace}summary{cursor:pointer;padding:12px 0}
.notice{background:#fff0cd;padding:18px}</style>
<h1>Scope before retrieval</h1><p class="notice">This journey uses three synthetic records.
The real CLI modules run against a disposable SQLite database and isolated config.</p>
<p>One harness can contain work, personal and unclassified sessions. Follow an explicit
project policy through preview, apply, retrieval and reclassification.</p>
"""
    for item in observations:
        page += (
            "<details><summary>" + escape(item["step"]) + "</summary>" + block(item) + "</details>"
        )
    page += "<h2>What remains</h2><p>" + escape(result["limitations"]) + "</p></html>"
    (output / "walkthrough.html").write_text(page)
    print(
        json.dumps(
            {
                "output": str(output),
                "commands": len(observations),
                "unexpected_private_body": False,
            },
            indent=2,
        )
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
