"""Standalone installed CLI/MCP review journey using fictional source records."""

import argparse
import asyncio
import importlib.util
import json
import os
import runpy
import sys
from dataclasses import replace
from pathlib import Path

import agent_session_tools.context.public as public
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopePolicy, apply_policy


async def exercise(output, require_installed=False):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    if require_installed:
        assert "site-packages" in public.__file__
        assert importlib.util.find_spec("studyloop") is None
        assert (Path(sys.executable).parent / "session-context").is_file()
    helper = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))
    conn, store, settings, ids, base, other, _ = helper["prepare"](output)
    extra_source = replace(
        other, native_key="review-evidence", body="No comparative database benchmark was run."
    )
    extra = store.capture(extra_source)

    def cite(eid, body):
        return {"evidence_id": eid, "start": 0, "end": len(body), "quote": body}

    request = output / "review.json"
    with public.open_context(output / "sessions.db", write=True) as context:
        claim = context.propose(
            statement="SQLite was proven faster than every graph database.",
            state="completed",
            target=None,
            producer="fixture-author",
            citations=[cite(ids["base"], base.body)],
        )["assertion_id"]
    (output / "assertions.json").write_text(json.dumps([claim]))
    binary = Path(sys.executable).parent / "session-db-mcp"
    transport = StdioTransport(
        command=str(binary),
        args=[],
        env=dict(os.environ),
        cwd=str(output),
        log_file=output / "mcp-server.log",
    )
    async with Client(transport, timeout=30) as client:

        async def call(name, **args):
            result = await client.call_tool(name, args)
            assert not result.is_error
            return result.structured_content or result.data

        initial = await call("memory_assess", query="cache", assertion_ids=[claim])
        assert initial["assessment"]["status"] == "review_needed"
        negative = await call(
            "memory_review",
            target_kind="assertion",
            target_id=claim,
            verdict="unsupported",
            rationale="Atomic writes do not establish comparative speed.",
            citations=[cite(extra, extra_source.body)],
        )
        unsupported = await call("memory_assess", query="cache", assertion_ids=[claim])
        assert unsupported["assessment"]["status"] == "unsupported_by_available_reviews"
        doc = {
            "target_kind": "assertion",
            "target_id": claim,
            "verdict": "supported",
            "rationale": "A deliberately overconfident fictional review for this lesson.",
            "citations": [cite(ids["base"], base.body)],
        }
        request.write_text(json.dumps(doc))
        positive = helper["cli"]("review", str(request))
        disputed = await call("memory_assess", query="cache", assertion_ids=[claim])
        assert disputed["assessment"]["status"] == "disputed_reviews"
        refused = False
        try:
            await call(
                "memory_review",
                target_kind="assertion",
                target_id=claim,
                verdict="unsupported",
                rationale="Attempt to replace another adapter's review.",
                citations=[cite(extra, extra_source.body)],
                supersedes=[positive["review_id"]],
            )
        except Exception as error:
            # Synthetic error; persist only the class and accepted refusal state.
            refused = "another producer" in str(error)
        assert refused
        doc.update(
            verdict="unsupported",
            rationale="The source did not contain comparative measurements.",
            citations=[cite(extra, extra_source.body)],
            supersedes=[positive["review_id"]],
        )
        request.write_text(json.dumps(doc))
        revised = helper["cli"]("review", str(request))
        history = await call("memory_reviews", target_kind="assertion", target_id=claim)
        assert len(history["reviews"]) == 3
        assert not next(r for r in history["reviews"] if r["id"] == positive["review_id"])[
            "current"
        ]
        assert ObservationStore(conn).forget(revised["review_id"])
        retired = await call("memory_reviews", target_kind="assertion", target_id=claim)
        assert not next(r for r in retired["reviews"] if r["id"] == positive["review_id"])[
            "current"
        ]
        settings["memory"]["projects"]["mailgraph"]["scope"] = "work"
        (output / "config.json").write_text(json.dumps(settings))
        apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
        revoked = await call("memory_assess", query="cache", assertion_ids=[claim])
        assert revoked["assessment"]["status"] == "review_needed"
        assert revoked["reviews"] == []
        assert extra_source.body not in json.dumps(revoked)
    conn.close()
    return {
        "runtime": {
            "python": sys.executable,
            "package_file": public.__file__,
            "wheel_only_required": require_installed,
            "mcp_transport": "stdio",
        },
        "initial": initial,
        "unsupported": unsupported,
        "disputed": disputed,
        "history": history,
        "retired": retired,
        "revoked": revoked,
        "checks": {
            "exact_citation_not_entailment": True,
            "mcp_records_attributed_review": True,
            "cli_and_mcp_disagreement_retained": True,
            "cross_producer_supersession_refused": refused,
            "explicit_revision_keeps_history": True,
            "forgotten_successor_does_not_reactivate": True,
            "live_scope_change_revokes_review": True,
            "model_reviews_never_validate_change": all(
                x["assessment"]["validation_of_change"] == "not_established"
                for x in (initial, unsupported, disputed, revoked)
            ),
        },
        "review_id": negative["review_id"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(exercise(args.output, args.require_installed))
    (args.output / "results.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {"output": str(args.output), "checks": result["checks"], "runtime": result["runtime"]}
        )
    )


if __name__ == "__main__":
    main()
