"""Exercise real graph HTTP/MCP paths using an isolated fictional database."""

import argparse
import asyncio
import json
import os
import runpy
import statistics
import sys
import time
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from agent_session_tools.context.scope import ScopePolicy, apply_policy
from studyloop.history import bridges, concepts
from studyloop.web.app import create_app


async def exercise(output, require_installed):
    if require_installed:
        assert "site-packages" in concepts.__file__
        assert "site-packages" in sys.modules["agent_session_tools.context.scope"].__file__
    prepare = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))["prepare"]
    conn, _, settings, _, _, _, _ = prepare(output)
    os.environ["STUDYLOOP_DB"] = str(output / "sessions.db")
    settings["memory"]["projects"]["studyloop"]["roots"].append(str(output))
    (output / "config.json").write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
    os.chdir(output)
    os.environ["SESSION_CONTEXT_SCOPE"] = "work"
    bridges.record_bridge("WORK_EXCLUDED", "python", "PRIVATE_TARGET", "python", "WORK_MAPPING")
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    for mapping in ("Similar grouping, not a teaching prerequisite", "Independent explanation"):
        bridges.record_bridge(
            "routing", "networking", "closures", "python", mapping, quality="validated"
        )
    assert bridges.migrate_bridges_to_graph() == 2
    app = create_app(study_dirs=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://lesson"
    ) as web:
        initial = (await web.get("/api/mastery/graph", params={"topic": "python"})).json()
        limited = (
            await web.get("/api/mastery/graph", params={"topic": "python", "limit": 1})
        ).json()
        checks = {
            "scope_before_http_limit": len(limited["edges"]) == 1
            and "WORK_" not in json.dumps(limited),
            "independent_same_label_contributions": len(initial["edges"]) == 2
            and len({e["provenance"]["owner_id"] for e in initial["edges"]}) == 2,
            "reported_validated_is_not_semantic_validation": all(
                e["provenance"]["quality_report"] == "validated"
                and e["provenance"]["semantic_validation"] == "not_established"
                for e in initial["edges"]
            ),
            "mapping_and_snapshot_binding_returned": all(
                len(e["provenance"]["snapshot_sha256"]) == 64
                and e["provenance"]["structural_mapping"]
                for e in initial["edges"]
            ),
        }
        edge_id = initial["edges"][0]["provenance"]["record_id"]
        conn.execute(
            "UPDATE knowledge_bridges SET structural_mapping='Corrected explanation' WHERE id=?",
            (edge_id,),
        )
        conn.commit()
        changed = (await web.get("/api/mastery/graph", params={"topic": "python"})).json()
        checks["correction_changes_binding"] = (
            changed["edges"][0]["provenance"]["snapshot_sha256"]
            != initial["edges"][0]["provenance"]["snapshot_sha256"]
        )
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "studyloop.mcp.server"],
            env=dict(os.environ),
            cwd=str(output),
            log_file=output / "mcp.log",
        )
        async with Client(transport, timeout=30) as client:
            response = await client.call_tool(
                "get_concept_context", {"topic": "python", "limit": 2}
            )
            mcp = response.structured_content or response.data
            checks["actual_mcp_returns_provenance"] = (
                len(mcp["edges"]) == 2
                and "WORK_" not in json.dumps(mcp)
                and all(
                    e["provenance"]["semantic_validation"] == "not_established"
                    for e in mcp["edges"]
                )
            )
        conn.execute("DELETE FROM knowledge_bridges WHERE id=?", (edge_id,))
        conn.commit()
        after_delete = (await web.get("/api/mastery/graph", params={"topic": "python"})).json()
        checks["deletion_preserves_independent_contribution"] = (
            len(after_delete["edges"]) == 1
            and after_delete["edges"][0]["provenance"]["record_id"] != edge_id
        )
        checks["no_copied_graph_rows"] = (
            conn.execute("SELECT count(*) FROM concept_relations").fetchone()[0] == 0
        )
        conn.rollback()
        timings = []
        for _ in range(20):
            before = time.perf_counter()
            result = await web.get("/api/mastery/graph", params={"topic": "python"})
            timings.append((time.perf_counter() - before) * 1000)
            assert result.status_code == 200
        settings["memory"]["projects"]["studyloop"]["scope"] = "work"
        (output / "config.json").write_text(json.dumps(settings))
        apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
        after_scope = (await web.get("/api/mastery/graph", params={"topic": "python"})).json()
        checks["project_scope_change_removes_labels_and_edges"] = (
            after_scope["edges"] == [] and concepts.list_concepts() == []
        )
        checks["foreign_keys_intact"] = conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    assert all(checks.values()), checks
    return {
        "checks": checks,
        "initial": initial,
        "mcp": mcp,
        "after_delete": after_delete,
        "after_scope": after_scope,
        "benchmark": {
            "iterations": 20,
            "median_http_ms": round(statistics.median(timings), 3),
            "max_http_ms": round(max(timings), 3),
            "visible_edges": 1,
        },
        "runtime": {
            "python": sys.executable,
            "studyloop_module": concepts.__file__,
            "require_installed": require_installed,
        },
        "limits": (
            "Synthetic mechanical checks; small ASGI route timing excludes "
            "network/startup and scale. "
            "Snapshot hash is not historical archiving. Full file ownership, sync and semantic "
            "usefulness remain unproven."
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
    print(json.dumps({"checks": result["checks"], "output": str(output)}))


if __name__ == "__main__":
    main()
