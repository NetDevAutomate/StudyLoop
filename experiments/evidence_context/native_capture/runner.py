"""Run native exporters against fictional archives in an isolated child process."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def database(path):
    from agent_session_tools.migrations import migrate

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    return conn


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def probe(output):
    import agent_session_tools.exporters.kiro as kiro
    from agent_session_tools.context.capture import capture_health
    from agent_session_tools.context.scope import ScopePolicy, apply_policy
    from agent_session_tools.exporters.claude import ClaudeCodeExporter
    from agent_session_tools.exporters.codex import CodexExporter
    from agent_session_tools.exporters.grok import GrokExporter
    from agent_session_tools.exporters.kiro import KiroCliExporter

    settings = {"memory": {"default_scope": "unclassified"}}
    Path(os.environ["STUDYLOOP_CONFIG"]).write_text(json.dumps(settings))
    conn = database(output / "sessions.db")
    apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
    codex = output / "archives" / "codex"
    codex_file = codex / "rollout-lesson.jsonl"
    write_jsonl(
        codex_file,
        [
            {
                "type": "session_meta",
                "payload": {
                    "cwd": "/fictional/project",
                    "git": {"commit_hash": "initial-revision"},
                },
            },
            {
                "timestamp": "2026-09-01T12:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "All tests passed. Ship this revision."}
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "generic",
                    "output": "Process exited with code 0",
                },
            },
            {
                "timestamp": "2026-09-01T12:01:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "CommandExecution",
                        "id": "actual",
                        "command": ["python", "-m", "pytest"],
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": "4 passed",
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "CommandExecution",
                        "id": "bad-type",
                        "command": ["pytest"],
                        "status": "completed",
                        "exit_code": "0",
                        "aggregated_output": "Quoted result with string code",
                    },
                },
            },
        ],
    )
    claude = output / "archives" / "claude"
    write_jsonl(
        claude / "project" / "lesson.jsonl",
        [
            {
                "uuid": "claude-result",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "claude-call",
                            "content": "Validation successful",
                        },
                        {"type": "thinking", "thinking": "excluded thinking"},
                    ],
                },
            }
        ],
    )
    grok = output / "archives" / "grok"
    write_jsonl(
        grok / "lesson" / "chat_history.jsonl",
        [{"type": "tool_result", "tool_call_id": "grok-call", "content": "Tests passed"}],
    )
    (grok / "lesson" / "summary.json").write_text(json.dumps({"info": {"id": "lesson"}}))
    kiro_path = output / "archives" / "kiro.sqlite3"
    native = sqlite3.connect(kiro_path)
    native.execute(
        "CREATE TABLE conversations_v2(key TEXT,conversation_id TEXT,value TEXT,"
        "created_at INTEGER,updated_at INTEGER)"
    )
    native.execute(
        "INSERT INTO conversations_v2 VALUES (?,?,?,?,?)",
        (
            "/fictional/project",
            "lesson",
            json.dumps(
                {
                    "conversation_id": "lesson",
                    "history": [
                        {
                            "user": {
                                "env_context": "excluded environment",
                                "content": {
                                    "ToolUseResults": {
                                        "tool_use_results": [
                                            {
                                                "tool_use_id": "kiro-call",
                                                "status": "Success",
                                                "content": [{"Text": "0 failures"}],
                                            }
                                        ]
                                    }
                                },
                            }
                        }
                    ],
                }
            ),
            1,
            2,
        ),
    )
    native.commit()
    native.close()
    kiro.KIRO_DB = kiro_path
    exporters = [
        CodexExporter(sessions_dir=codex),
        ClaudeCodeExporter(projects_dir=claude),
        KiroCliExporter(),
        GrokExporter(sessions_dir=grok),
    ]
    first = {e.source_name: vars(e.export_all(conn)) for e in exporters}
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT id,harness,native_kind,origin,body,body_sha256,exit_code,target,revision,"
            "machine_id,recorded_at FROM context_evidence ORDER BY harness,rowid"
        )
    ]
    replay = {e.source_name: vars(e.export_all(conn)) for e in exporters}
    assert len(rows) == 7
    assert sum(r["origin"] == "process_exit" for r in rows) == 1
    assert all(r["revision"] is None and r["machine_id"] == "unknown" for r in rows)
    assert all(stats["skipped"] == 1 for stats in replay.values())
    assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 7
    codex_file.write_text(codex_file.read_text() + "{incomplete")
    broken = vars(exporters[0].export_all(conn))
    assert broken["errors"] > 0
    assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 7
    result = {
        "native_sources": rows,
        "first_capture": first,
        "unchanged_replay": replay,
        "malformed_archive": broken,
        "health": capture_health(conn),
        "checks": {
            "native_records": 7,
            "process_exit_records": 1,
            "revision_unknown": 7,
            "legacy_conversation_messages": conn.execute(
                "SELECT count(*) FROM messages"
            ).fetchone()[0],
            "replay_added_records": 0,
            "malformed_input_lost_records": 0,
        },
    }
    conn.close()
    return result


def render(result):
    sections = []
    for title, prose, value in [
        (
            "1 · Seven records, different authority",
            "The same success wording has different provenance. Expand each record to inspect "
            "its captured fields. No record certifies this revision.",
            result["native_sources"],
        ),
        (
            "2 · Conversation is only one view",
            "The legacy conversation contains one assistant message. The canonical store "
            "additionally retains six native results. Capturing tools adds evidence that "
            "prose-only export omitted.",
            result["checks"],
        ),
        (
            "3 · Unchanged replay",
            "All four exporters skip their unchanged archive. Repeated capture creates "
            "no additional evidence versions.",
            result["unchanged_replay"],
        ),
        (
            "4 · Incomplete source",
            "A malformed JSONL tail produces a partial attempt while the last good evidence "
            "remains intact. An export problem must not erase the historical context.",
            result["malformed_archive"],
        ),
        (
            "5 · Capture health is not hook liveness",
            "These are operator counts and attempt receipts. A recent export does not prove "
            "that every archive is covered, or that the end-of-session hook is registered.",
            result["health"],
        ),
    ]:
        sections.append(
            "<section><h2>"
            + escape(title)
            + "</h2><p>"
            + escape(prose)
            + "</p><details><summary>Inspect observed data</summary>"
            + block(value)
            + "</details></section>"
        )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stage22 · Native capture</title><style>
body{font:18px/1.6 system-ui;max-width:920px;margin:3rem auto;padding:0 1rem;
background:#faf9f5;color:#24363b}h1,h2{line-height:1.2}
section{margin:2.5rem 0;border-top:2px solid #d6e2df;padding-top:1rem}
summary{cursor:pointer;color:#11665b}pre{font:14px/1.5 ui-monospace;white-space:pre-wrap;
overflow-wrap:anywhere;background:#edf2ef;padding:1rem}small{color:#496167}</style>
<h1>What did the source actually establish?</h1>
<p>Stage22 · Fictional archives, actual exporters, no model calls.</p>
<p>A native envelope can establish a recorded process exit. Validation still needs evidence
applicable to the requested target and revision.</p>"""
        + "".join(sections)
        + "<p><small>All data in this walkthrough is synthetic. The runner uses its own "
        "database and configuration.</small></p></html>"
    )


def run(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(
        STUDYLOOP_CONFIG=str(output / "config.json"),
        STUDYLOOP_DB=str(output / "sessions.db"),
        SESSION_CONTEXT_SCOPE="unclassified",
    )
    child = subprocess.run(
        [sys.executable, "-m", __spec__.name, "--probe", "--output", str(output)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(child.stdout)
    (output / "results.json").write_text(json.dumps(result, indent=2))
    (output / "walkthrough.html").write_text(render(result))
    print(json.dumps({"output": str(output), "checks": result["checks"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.output)))
    else:
        run(args.output)


if __name__ == "__main__":
    main()
