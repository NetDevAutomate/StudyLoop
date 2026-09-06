"""Synthetic records through real StudyLoop APIs and MCP stdio."""

import argparse
import asyncio
import json
import os
import runpy
import sys
from pathlib import Path

from agent_session_tools.context.scope import ScopePolicy, apply_policy
from studyloop.history import bridges, observations, sessions, teachback


async def exercise(output, require_installed=False):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    if require_installed:
        assert "site-packages" in sessions.__file__
        assert "site-packages" in sys.modules["agent_session_tools.context.scope"].__file__
    helper = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))
    conn, _, settings, _, _, _, _ = helper["prepare"](output)
    os.environ["STUDYLOOP_DB"] = str(output / "sessions.db")
    for sid, body in [("s", "PERSONAL_INPUT generators"), ("w", "WORK_INPUT generators")]:
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content,seq) VALUES (?,?,?,?,0)",
            (sid + "0", sid, "user", body),
        )
    conn.commit()

    def record(scope, sid, score, note):
        os.environ["SESSION_CONTEXT_SCOPE"] = scope
        identity = sessions.start_study_session("python", "high", session_id=sid)
        assert identity is not None
        assert sessions.end_study_session(identity, note + "_SESSION", win_count=1)
        assert teachback.record_teachback(
            "generators", "python", (score,) * 5, "full", notes=note + "_SCORE", session_id=sid
        )
        assert bridges.record_bridge("packets", "network", "generators", "python", note + "_BRIDGE")
        return identity

    personal_id = record("personal", "s", 2, "PERSONAL")
    work_id = record("work", "w", 4, "WORK")
    work_bridge = bridges.get_bridges()[0]["id"]
    work_progress = observations.rows(conn)
    conn.rollback()
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    before = {
        "sessions": sessions.get_study_session_stats(),
        "scores": teachback.get_teachback_history("generators"),
        "bridges": bridges.get_bridges(),
        "progress": observations.rows(conn),
    }
    conn.rollback()
    checks = {
        "permitted_history_remains_useful": len(before["sessions"]) == 1
        and before["sessions"][0]["sessions"] == 1
        and bool(before["scores"])
        and bool(before["bridges"]),
        "excluded_learning_bodies_withheld": "WORK_" not in json.dumps(before),
        "same_concept_assessments_separated": before["progress"][0]["last_teachback_score"] == 10
        and work_progress[0]["last_teachback_score"] == 20,
        "cross_scope_updates_refused": sessions.end_study_session(work_id, "wrong scope") is False
        and bridges.update_bridge_usage(work_bridge, True) is False,
    }
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "studyloop.mcp.server"],
        env=dict(os.environ),
        cwd=str(output),
        log_file=output / "mcp-server.log",
    )
    async with Client(transport, timeout=30) as client:

        async def view():
            value = await client.call_tool("get_study_history", {"topic": "python"})
            return value.structured_content or value.data

        mcp_before = await view()
        checks["mcp_includes_scoped_scores_and_sessions"] = (
            mcp_before["session_stats"][0]["sessions"] == 1
            and mcp_before["teachback_scores"][0]["notes"] == "PERSONAL_SCORE"
            and "WORK_" not in json.dumps(mcp_before)
        )
        settings["memory"]["projects"]["studyloop"]["scope"] = "work"
        (output / "config.json").write_text(json.dumps(settings))
        refused = False
        try:
            await view()
        except Exception as error:
            refused = "policy apply" in str(error)
        checks["unapplied_policy_change_refused"] = refused
        apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
        after = await view()
        checks["running_mcp_observes_reclassification"] = (
            not after["session_stats"]
            and not after["teachback_scores"]
            and sessions.get_session_notes(personal_id) is None
        )
    conn.execute(
        "INSERT INTO context_tombstones(session_id,deletion_id,deleted_at) "
        "VALUES ('s','lesson-forget','2026-09-06')"
    )
    conn.commit()
    checks["logical_forget_purges_linked_application_rows"] = (
        not conn.execute("SELECT 1 FROM study_sessions WHERE id=?", (personal_id,)).fetchone()
        and not conn.execute("SELECT 1 FROM teach_back_scores WHERE session_id='s'").fetchone()
        and conn.execute("PRAGMA foreign_key_check").fetchall() == []
    )
    conn.close()
    assert all(checks.values()), checks
    return {
        "checks": checks,
        "before": before,
        "mcp_before": mcp_before,
        "mcp_after": after,
        "runtime": {
            "python": sys.executable,
            "studyloop_module": sessions.__file__,
            "require_installed": require_installed,
            "mcp_transport": "stdio",
        },
        "limits": "Fictional records, real interfaces. Three tables have ownership; "
        "parking, notes, practice, concept/dependency/plan state, scoped sync and "
        "full restore/forget remain required.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(exercise(args.output.resolve(), args.require_installed))
    (args.output / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"output": str(args.output), "checks": result["checks"]}))


if __name__ == "__main__":
    main()
