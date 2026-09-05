"""Runnable canonical-storage lesson. Synthetic fixtures only; no model calls."""

import argparse
import json
import sqlite3
from importlib.resources import files
from pathlib import Path

from agent_session_tools.context.provenance import ExecutionState, Origin, Scope, ScopeAssignment
from agent_session_tools.context.store import Access, Citation, ContextStore, NativeSource
from agent_session_tools.migrations import migrate

from ..assertion_gate.viewer import block


def run(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    conn = sqlite3.connect(output / "sessions.db")
    try:
        conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
        migrate(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        for sid, harness in [
            ("laptop-codex", "codex"),
            ("mini-kiro", "kiro"),
            ("work-grok", "grok"),
        ]:
            conn.execute("INSERT INTO sessions(id,source) VALUES (?,?)", (sid, harness))
        conn.commit()
        store = ContextStore(conn)
        personal = Access(scope=Scope.PERSONAL)
        for project, scope in [
            ("demo-studyloop", Scope.PERSONAL),
            ("demo-mailgraph", Scope.PERSONAL),
            ("demo-work", Scope.WORK),
        ]:
            store.configure_project(
                ScopeAssignment(scope=scope, project_id=project, policy_id="explicit-demo-choice")
            )
        for sid, project in [
            ("laptop-codex", "demo-studyloop"),
            ("mini-kiro", "demo-mailgraph"),
            ("work-grok", "demo-work"),
        ]:
            store.assign_session(sid, project)

        def capture(sid, harness, machine, key, body):
            return store.capture(
                NativeSource(
                    session_id=sid,
                    native_key=key,
                    harness=harness,
                    native_kind="message",
                    native_locator=f"synthetic://{sid}/{key}",
                    parser_version="demo-v1",
                    machine_id=machine,
                    origin=Origin.CONVERSATION,
                    body=body,
                )
            )

        first_body = "I recommend a local retry queue. This is a proposal, not a tested result."
        correction_body = (
            "I changed my recommendation: persist retry state. Validation has not run."
        )
        first = capture("laptop-codex", "codex", "laptop", "message-1", first_body)
        correction = capture("mini-kiro", "kiro", "macmini", "message-9", correction_body)
        work = capture(
            "work-grok", "grok", "work-machine", "message-2", "retry WORK_ONLY_DEMO_MARKER"
        )

        def propose(eid, body, statement):
            return store.propose(
                statement=statement,
                state=ExecutionState.PLANNED,
                target="retry-queue",
                generator="scripted-demo-proposal",
                access=personal,
                citations=[Citation(evidence_id=eid, start=0, end=len(body), quote=body)],
            )

        old = propose(first, first_body, "Earlier advice favored a local retry queue.")
        new = propose(
            correction,
            correction_body,
            "Later advice favors persistent state; validation is missing.",
        )
        store.relate(new, old, "corrects", "scripted-demo-proposer", personal)
        before = store.search("retry", personal)
        relationship = store.relations(old, personal)
        # A changed native body adds a version; it does not move the earlier quote.
        revised = capture(
            "laptop-codex",
            "codex",
            "laptop",
            "message-1",
            "Updated wording: the retry queue still needs validation.",
        )
        old_quote = store.assertion(old, personal)
        try:
            store.propose(
                statement="Bad citation",
                state=ExecutionState.COMPLETED,
                target=None,
                generator="scripted-demo-proposal",
                access=personal,
                citations=[Citation(evidence_id=first, start=0, end=7, quote="WRONG!!")],
            )
        except ValueError as exc:
            bad_citation = str(exc)
        else:
            raise AssertionError("The invalid citation was accepted")
        store.configure_project(
            ScopeAssignment(
                scope=Scope.WORK,
                project_id="demo-mailgraph",
                policy_id="explicit-demo-reclassification",
            )
        )
        results = {
            "mode": (
                "Synthetic fixtures using production storage code; "
                "no native harness or model execution."
            ),
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "personal_search_before_reclassification": before,
            "work_source_hidden": store.source(work, personal) is None,
            "proposed_relationship_before_reclassification": relationship,
            "old_assertion_after_source_edit": old_quote,
            "new_source_version_id": revised,
            "invalid_citation_error": bad_citation,
            "correction_hidden_after_reclassification": store.assertion(new, personal) is None,
            "relationships_after_reclassification": store.relations(old, personal),
            "limitations": (
                "This stage does not integrate legacy CLI/MCP/sync, "
                "automatic retrieval arbitration, or complete forgetting."
            ),
        }
        assert "WORK_ONLY_DEMO_MARKER" not in json.dumps(results)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stage 18 · Bound sources</title>
<style>body{font:17px/1.6 system-ui;color:#20303a;background:#faf9f5;
max-width:950px;margin:40px auto;padding:0 22px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f3;padding:16px;
font:14px/1.5 monospace}
summary{cursor:pointer;padding:12px 0}.notice{background:#fff0cd;padding:18px}</style>
<h1>Sources that cannot silently change</h1>
<p class="notice">This database contains synthetic fixtures.
The demo uses the production package's storage code,
but does not prove installed capture or sync.</p>
<p>Follow a proposal from one harness, a correction from another, an edit to the original source,
and a scope change. These are proposed interpretations; no successful validation is asserted.</p>
"""
        for key, value in results.items():
            page += (
                "<details><summary>"
                + key.replace("_", " ")
                + "</summary>"
                + block(value)
                + "</details>"
            )
        page += "</html>"
        (output / "walkthrough.html").write_text(page)
        print(
            json.dumps(
                {
                    "output": str(output),
                    "work_source_hidden": results["work_source_hidden"],
                    "old_quote_preserved": old_quote["citations"][0]["quote"] == first_body,
                    "correction_hidden": results["correction_hidden_after_reclassification"],
                },
                indent=2,
            )
        )
        return results
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
