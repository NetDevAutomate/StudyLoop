"""Exercise actual installed commands and MCP with fictional scoped annotations."""

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from agent_session_tools.context import annotations, records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore


def command(module, db, *args):
    return subprocess.run(
        [sys.executable, "-I", "-m", module, *args, "--db", str(db)],
        capture_output=True,
        text=True,
        timeout=30,
    )


async def exercise(output, require_installed):
    if require_installed:
        assert "site-packages" in annotations.__file__
    db = output / "sessions.db"
    config = {
        "database": {"path": str(db)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "p": {"scope": "personal", "roots": [str(output / "personal")]},
                "w": {"scope": "work", "roots": [str(output / "work")]},
            },
        },
    }
    config_path = output / "config.json"
    config_path.write_text(json.dumps(config))
    os.environ["STUDYLOOP_CONFIG"] = str(config_path)
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    os.chdir(output)
    conn = records.connect(db)
    conn.executemany(
        "INSERT INTO sessions(id,source,project_path,content_hash) VALUES (?,?,?,?)",
        [
            ("personal", "fixture", str(output / "personal"), "same"),
            ("personal-copy", "fixture", str(output / "personal"), "same"),
            ("work", "fixture", str(output / "work"), "same"),
        ],
    )
    conn.execute(
        "INSERT INTO session_notes(session_id,notes) "
        "VALUES ('personal','SQLite was validated everywhere')"
    )
    conn.execute("INSERT INTO session_notes(session_id,notes) VALUES ('work','EXCLUDED_WORK_NOTE')")
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="lesson", dry_run=False)
    initial = annotations.view(conn, "personal")
    conn.rollback()
    corrected = command(
        "agent_session_tools.query_sessions",
        db,
        "note",
        "personal",
        "--text",
        "The fixture tested transaction rollback; answer quality was not measured",
    )
    assert corrected.returncode == 0, corrected.stderr
    context = command("agent_session_tools.context.cli", db, "annotations", "personal")
    assert context.returncode == 0, context.stderr
    current = json.loads(context.stdout)
    ObservationStore(conn).append(
        kind=annotations.KINDS["note"],
        subject="personal",
        payload={"notes": "Another reviewer reports a narrower test scope"},
        producer="fictional-peer",
        authority="reported",
        owner_session_id="personal",
    )
    transport = StdioTransport(
        command=sys.executable,
        args=["-I", "-m", "agent_session_tools.mcp_server"],
        env=dict(os.environ),
        cwd=str(output),
        log_file=output / "mcp.log",
    )
    async with Client(transport, timeout=30) as client:
        reply = await client.call_tool("session_annotations", {"session_id": "personal"})
        conflict = reply.structured_content or reply.data
        hidden = await client.call_tool(
            "session_annotations", {"session_id": "work"}, raise_on_error=False
        )
        assert hidden.is_error
    reconcile = command(
        "agent_session_tools.query_sessions",
        db,
        "note",
        "personal",
        "--text",
        "Reconciled report: only fixture transaction rollback is established",
    )
    assert reconcile.returncode == 0, reconcile.stderr
    reconciled = annotations.view(conn, "personal")
    conn.rollback()
    identity = next(v["id"] for v in reconciled["versions"] if v["current"])
    ObservationStore(conn).forget(identity)
    forgotten = annotations.view(conn, "personal")
    conn.rollback()
    merge = command(
        "agent_session_tools.maintenance",
        db,
        "find-duplicates",
        "--merge-ids",
        "personal",
        "--merge-ids",
        "personal-copy",
    )
    replay_refused = False
    try:
        conn.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES ('personal','stale replica')"
        )
    except Exception as exc:
        import sqlite3

        if not isinstance(exc, sqlite3.IntegrityError):
            raise
        replay_refused = True
    finally:
        conn.rollback()
    checks = {
        "legacy_remains_unattributed": initial["legacy_authority"] == "unattributed_report",
        "actual_cli_retains_correction_history": len(current["versions"]) == 2
        and current["current_count"] == 1,
        "ownership_is_not_evidence": current["relationship"] == "about_session"
        and current["semantic_validation"] == "not_established"
        and conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 0,
        "actual_mcp_keeps_conflicting_reports": conflict["current_count"] == 2
        and conflict["conflicting_current_versions"],
        "actual_mcp_excludes_work": hidden.is_error and "EXCLUDED_WORK_NOTE" not in str(hidden),
        "explicit_correction_names_both_predecessors": len(
            next(v for v in reconciled["versions"] if v["current"])["supersedes"]
        )
        == 2,
        "forget_does_not_revive_prior_advice": forgotten["current_count"] == 0
        and forgotten["legacy"] is None,
        "forgotten_legacy_shadow_replay_refused": replay_refused,
        "physical_merge_refuses_classified_sources": merge.returncode != 0
        and "classified" in merge.stdout
        and conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 3,
        "foreign_keys_intact": conn.execute("PRAGMA foreign_key_check").fetchall() == [],
    }
    conn.close()
    assert all(checks.values()), checks
    return {
        "checks": checks,
        "initial": initial,
        "corrected": current,
        "conflict": conflict,
        "reconciled": reconciled,
        "forgotten": forgotten,
        "runtime": {
            "python": sys.executable,
            "module": annotations.__file__,
            "require_installed": require_installed,
        },
        "limits": (
            "Fictional mechanical fixtures. No semantic accuracy claim, engine comparison, "
            "scoped sync or managed restore proof."
        ),
    }


def benchmark(output):
    results = []
    for count in (10, 100, 1000):
        db = output / f"scale-{count}.db"
        conn = records.connect(db)
        conn.execute("INSERT INTO sessions(id,source) VALUES ('history','fixture')")
        conn.commit()
        # Match the existing lesson policy even though this source is unclassified.
        from agent_session_tools.context.scope import active_policy

        apply_policy(conn, active_policy(), actor="benchmark", dry_run=False)
        os.environ["SESSION_CONTEXT_SCOPE"] = "unclassified"
        store = ObservationStore(conn)
        previous = []
        before = time.perf_counter()
        with ContextStore(conn)._atomic(), records.policy_guard(conn):
            for n in range(count):
                previous = [
                    store.append(
                        kind=annotations.KINDS["note"],
                        subject="history",
                        payload={"notes": f"Correction {n}: fixture result only"},
                        producer="fixture",
                        authority="reported",
                        owner_session_id="history",
                        supersedes=previous,
                    )
                ]
        append_ms = (time.perf_counter() - before) * 1000
        timings = []
        for _ in range(5):
            before = time.perf_counter()
            value = annotations.view(conn, "history")
            timings.append((time.perf_counter() - before) * 1000)
            conn.rollback()
        results.append(
            {
                "versions": count,
                "append_batch_ms": round(append_ms, 3),
                "median_read_ms": round(statistics.median(timings), 3),
                "max_read_ms": round(max(timings), 3),
                "returned_versions": len(value["versions"]),
                "current_count": value["current_count"],
                "coverage": value["coverage"],
                "response_bytes": len(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                ),
            }
        )
        assert value["current_count"] == 1 and any(v["current"] for v in value["versions"])
        conn.close()
    return {
        "measurements": results,
        "limits": (
            "Five warm direct helper reads; short reports, one batch commit, no transport/startup "
            "or cold-disk timing. Work scans history even when output is bounded."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(exercise(output, args.require_installed))
    result["benchmark"] = benchmark(output)
    (output / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"checks": result["checks"], "output": str(output)}))


if __name__ == "__main__":
    main()
