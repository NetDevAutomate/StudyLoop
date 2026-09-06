"""Exercise real observation and extraction code with synthetic, isolated sources."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def probe(output: Path):
    from agent_session_tools.context.legacy_sources import prepare_session_input
    from agent_session_tools.context.observations import ObservationStore
    from agent_session_tools.context.scope import ScopePolicy, apply_policy
    from agent_session_tools.context.store import ContextStore
    from agent_session_tools.migrations import migrate
    from studyloop.extractors import ExtractorResult
    from studyloop.extractors.pipeline import extract_and_write
    from studyloop.history import observations

    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/lesson/personal"]},
                "work": {"scope": "work", "roots": ["/lesson/work"]},
            },
        }
    }
    Path(os.environ["STUDYLOOP_CONFIG"]).write_text(json.dumps(settings))
    conn = sqlite3.connect(os.environ["STUDYLOOP_DB"])
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    for sid, project, content in [
        ("first", "personal", "PERSONAL_NOTE: I still need help explaining generators."),
        ("second", "personal", "SECOND_NOTE: I think I understand generators now."),
        ("work", "work", "WORK_NOTE: I used a generator at work."),
    ]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "kiro_cli", "/lesson/" + project),
        )
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content,seq) VALUES (?,?,?,?,?)",
            (sid + "0", sid, "user", content, 0),
        )
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content,seq) VALUES (?,?,?,?,?)",
            (sid + "1", sid, "assistant", "Quoted claim: all tests passed.", 1),
        )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
    deliveries = []

    def extract(sid, confidence, note):
        captured = prepare_session_input(conn, sid)
        conn.rollback()

        def provider(messages, identity):
            assert not conn.in_transaction
            deliveries.append({"session_id": identity, "messages": messages})
            return [ExtractorResult("python", "generators", confidence, note)]

        assert extract_and_write(sid, captured.messages, provider, connection=conn) == 1
        return captured

    def view(scope):
        conn.rollback()
        os.environ["SESSION_CONTEXT_SCOPE"] = scope
        return observations.rows(conn)

    first = extract("first", "learning", "PERSONAL_NOTE")
    personal_before = view("personal")
    view("work")
    extract("work", "confident", "WORK_NOTE")
    work_before = view("work")
    assert "PERSONAL_NOTE" not in json.dumps(work_before)
    assert "WORK_NOTE" not in json.dumps(view("personal"))
    second = extract("second", "confident", "SECOND_NOTE")
    conflicts = view("personal")
    assert conflicts[0]["confidence_status"] == "conflicting_reports"
    conn.rollback()
    conn.execute("DELETE FROM context_evidence WHERE id=?", (second.evidence_ids[0],))
    conn.commit()
    after_dependency_removal = view("personal")
    assert after_dependency_removal[0]["session_count"] == 1
    assert "SECOND_NOTE" not in json.dumps(after_dependency_removal)

    manual = observations.record(
        conn, "python", "generators", "confident", "Explicit updated report"
    )
    conn.commit()
    correction = view("personal")
    store = ObservationStore(conn)
    assert store.forget(manual)
    conn.commit()
    after_correction_retired = view("personal")
    assert after_correction_retired == []
    retained_history = store.list(observations.KIND, current=False)
    assert retained_history  # original is inspectable, but not current again
    assert all(
        source["origin"] == "unknown" for row in retained_history for source in row["sources"]
    )

    conn.rollback()
    ContextStore(conn).assign_session("first", "work")
    conn.commit()
    assert store.list(observations.KIND, current=False) == []
    view("work")
    moved_history = store.list(observations.KIND, current=False)
    assert any(
        source["id"] in first.evidence_ids for row in moved_history for source in row["sources"]
    )
    conn.close()
    return {
        "mode": (
            "Synthetic inputs; real workspace pipeline/store/projection; no provider network call."
        ),
        "personal_before": personal_before,
        "work_before": work_before,
        "conflicting_personal_reports": conflicts,
        "after_one_source_removed": after_dependency_removal,
        "explicit_correction": correction,
        "after_correction_forgotten": after_correction_retired,
        "history_before_reclassification": retained_history,
        "history_after_reclassification_to_work": moved_history,
        "extractor_calls": len(deliveries),
        "limits": "Input traceability does not establish claim-specific support or semantic truth. "
        "Legacy provenance remains unknown. Local dependency retirement is not complete session "
        "forgetting, sync, backup restoration, native capture or release acceptance.",
    }


def run(output: Path):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(output / "config.json"),
        "STUDYLOOP_DB": str(output / "sessions.db"),
        "SESSION_CONTEXT_SCOPE": "personal",
    }
    result = subprocess.run(
        [sys.executable, "-m", __spec__.name, "--probe", "--output", str(output)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    observed = json.loads(result.stdout)
    (output / "results.json").write_text(json.dumps(observed, indent=2) + "\n")
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>Stage21 · Where did this assessment come from?</title><style>
body{font:17px/1.6 system-ui;max-width:950px;margin:40px auto;padding:0 22px;
color:#20303a;background:#faf9f5}pre{white-space:pre-wrap;overflow-wrap:anywhere;
background:#edf1f3;padding:16px;font:14px/1.5 monospace}summary{cursor:pointer;padding:12px 0}
</style><h1>Where did this assessment come from?</h1>
<p>Read each intervention in order. All three fictional conversations use the same harness.
Project configuration determines scope. The two scopes are deliberately shown separately here.</p>
<p>A source link proves which input was used.
It does not prove the model interpreted it correctly.</p>"""
    explanations = {
        "personal_before": "One personal report: the summary can name its immutable input.",
        "work_before": "Same concept and harness, separate work scope.",
        "conflicting_personal_reports": (
            "Two current reports disagree. Learning is the conservative scheduling cue; "
            "neither report is declared true."
        ),
        "after_one_source_removed": (
            "Removing a dependency purges only its derived observation; the summary is rebuilt."
        ),
        "explicit_correction": (
            "An explicit update supersedes previous heads while preserving history."
        ),
        "after_correction_forgotten": (
            "No current result: retirement prevents an older report silently becoming "
            "current again."
        ),
        "history_before_reclassification": (
            "Historical interpretation remains unverified, including the quoted claim "
            "that tests passed."
        ),
        "history_after_reclassification_to_work": (
            "Source ownership changes access without rewriting the recorded assessment."
        ),
    }
    for key, explanation in explanations.items():
        page += (
            "<details><summary>"
            + escape(explanation)
            + "</summary>"
            + block(observed[key])
            + "</details>"
        )
    page += "<h2>What this does not prove</h2><p>" + escape(observed["limits"]) + "</p></html>"
    (output / "walkthrough.html").write_text(page)
    print(json.dumps({"output": str(output), "interventions": len(explanations)}))
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.output)))
    else:
        run(args.output)


if __name__ == "__main__":
    main()
