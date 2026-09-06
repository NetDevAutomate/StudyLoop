"""Use real notes/parking routes and MCP stdio with isolated synthetic data."""

import argparse
import asyncio
import json
import os
import runpy
import shlex
import sys
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from agent_session_tools.context.scope import ScopePolicy, apply_policy
from studyloop import notes, parking
from studyloop.history import observations, sessions
from studyloop.learning import practice
from studyloop.web.app import create_app


async def exercise(output, require_installed):
    if require_installed:
        assert "site-packages" in notes.__file__
        assert "site-packages" in sys.modules["agent_session_tools.context.scope"].__file__
    helper = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))
    conn, _, settings, _, _, _, _ = helper["prepare"](output)
    os.environ["STUDYLOOP_DB"] = str(output / "sessions.db")
    app = create_app(study_dirs=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://lesson"
    ) as web:

        async def note(title, study):
            response = await web.post(
                "/api/notes",
                json={"title": title, "body": title + "_BODY", "study_session_id": study},
            )
            assert response.status_code == 201, response.text
            return response.json()["id"]

        personal_study = sessions.start_study_session("python", "high", session_id="s")
        personal_note = await note("PERSONAL_NOTE", personal_study)
        personal_park = parking.park_topic("Shared question", study_session_id=personal_study)
        assert (
            parking.park_topic("Shared question", study_session_id=personal_study) == personal_park
        )
        parking.add_board_column("Private")
        os.environ["SESSION_CONTEXT_SCOPE"] = "work"
        work_study = sessions.start_study_session("python", "high", session_id="w")
        work_note = await note("WORK_NOTE", work_study)
        work_park = parking.park_topic("Shared question", study_session_id=work_study)
        for _ in range(3):
            parking.park_topic("Shared question", study_session_id=work_study)
        parking.add_board_column("WORK_COLUMN")
        os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
        before = {
            "notes": (await web.get("/api/notes", params={"limit": 1})).json()["notes"],
            "board": (await web.get("/api/parking/board")).json(),
            "frequency": parking.get_topic_frequencies(),
        }
        excluded_patch = await web.patch(f"/api/notes/{work_note}", json={"body": "WRONG_SCOPE"})
        checks = {
            "http_notes_filter_before_limit": len(before["notes"]) == 1
            and before["notes"][0]["title"] == "PERSONAL_NOTE",
            "http_board_names_and_cards_scoped": before["board"]["total"] == 1
            and "WORK_" not in json.dumps(before),
            "dedup_keeps_different_owners": personal_park != work_park
            and before["frequency"] == {"Shared question": 2},
            "http_cross_scope_mutation_refused": excluded_patch.status_code == 404
            and not parking.move_parked_topic(work_park, "next"),
        }
        command = shlex.join([sys.executable, "-c", "print('synthetic practice check')"])
        deck = output / "practice.json"
        deck.write_text(
            json.dumps(
                {
                    "title": "Python Practice",
                    "tasks": [
                        {
                            "taskType": "build",
                            "prompt": "Run a fictional practice check",
                            "setup": "",
                            "successCriteria": ["command exits"],
                            "hint": "",
                            "expectedLearningOutcome": "generators",
                            "verification": {
                                "kind": "command",
                                "command": command,
                                "successCriteria": ["command exits"],
                            },
                        }
                    ],
                }
            )
        )
        result = practice.verify_practice_task(
            deck,
            task_index=1,
            workdir=output,
            run_command=True,
            confirmed_command=command,
            notes="PERSONAL_PRACTICE",
        )
        checks["practice_attempt_and_progress_recorded"] = (
            result.passed and result.progress_recorded
        )
        progress = observations.rows(conn)
        conn.rollback()
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "studyloop.mcp.server"],
            env=dict(os.environ),
            cwd=str(output),
            log_file=output / "mcp.log",
        )
        async with Client(transport, timeout=30) as client:
            response = await client.call_tool("get_study_history", {"topic": "python"})
            history = response.structured_content or response.data
            checks["mcp_exposes_scoped_practice"] = (
                len(history["practice_attempts"]) == 1
                and history["practice_attempts"][0]["validation_of_learning"] == "not_established"
            )
        settings["memory"]["projects"]["studyloop"]["scope"] = "work"
        (output / "config.json").write_text(json.dumps(settings))
        apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
        after = {
            "notes": (await web.get("/api/notes")).json()["notes"],
            "board": (await web.get("/api/parking/board")).json(),
        }
        checks["parent_reclassification_withholds_children"] = (
            after["notes"] == [] and after["board"]["total"] == 0
        )
        conn.execute("INSERT INTO context_tombstones VALUES ('s','stage27-forget','2026-09-06')")
        conn.commit()
        checks["logical_parent_forget_purges_notes_and_cards"] = (
            not conn.execute("SELECT 1 FROM study_notes WHERE id=?", (personal_note,)).fetchone()
            and not conn.execute(
                "SELECT 1 FROM parked_topics WHERE id=?", (personal_park,)
            ).fetchone()
        )
        conn.execute("DELETE FROM practice_attempts")
        conn.commit()
        checks["attempt_deletion_retires_derived_progress"] = observations.rows(conn) == []
        conn.rollback()
        checks["foreign_keys_intact"] = conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    assert all(checks.values()), checks
    return {
        "checks": checks,
        "before": before,
        "progress": progress,
        "mcp_history": history,
        "after": after,
        "runtime": {
            "python": sys.executable,
            "studyloop_module": notes.__file__,
            "require_installed": require_installed,
            "http": "actual route modules via ASGI transport",
            "agent": "actual MCP stdio",
        },
        "limits": (
            "Fictional data and a controlled local command. Route handlers are exercised "
            "without the full web application's startup lifecycle. These checks do not "
            "establish learning mastery, full sync/restore or whole-product acceptance."
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
    (output / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"output": str(output), "checks": result["checks"]}))


if __name__ == "__main__":
    main()
