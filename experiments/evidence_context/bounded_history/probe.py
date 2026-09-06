"""Run real CLI and MCP history continuation against an isolated fictional file."""

import argparse
import asyncio
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from agent_session_tools.context import annotations, records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.store import ContextStore


def cli(db, *args):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "agent_session_tools.context.cli",
            "annotations",
            "history",
            "--db",
            str(db),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


async def exercise(output, require_installed):
    if require_installed:
        assert "site-packages" in annotations.__file__
    helpers = runpy.run_path(str(Path(__file__).with_name("benchmark.py")))
    db = helpers["prepare"](output, 12)
    config_path = output / "config.json"
    config = json.loads(config_path.read_text())
    config["database"] = {"path": str(db)}
    config_path.write_text(json.dumps(config))
    conn = records.connect(db)
    store = ObservationStore(conn)
    store.append(
        kind=annotations.KINDS["note"],
        subject="history",
        payload={"notes": "A second current reviewer disagrees"},
        producer="fictional-peer",
        authority="reported",
        owner_session_id="history",
    )
    first = cli(db, "--limit", "2")
    seen = {v["id"] for v in first["versions"]}
    cursor = first["next_cursor"]
    original_cursor = cursor
    cursors = set()
    pages = []
    transport = StdioTransport(
        command=sys.executable,
        args=["-I", "-m", "agent_session_tools.mcp_server"],
        env=dict(os.environ),
        cwd=str(output),
        log_file=output / "mcp.log",
    )
    async with Client(transport, timeout=30) as client:
        while cursor:
            assert cursor not in cursors
            cursors.add(cursor)
            reply = await client.call_tool(
                "session_annotations", {"session_id": "history", "cursor": cursor, "limit": 2}
            )
            page = reply.structured_content or reply.data
            assert not page["current_group_complete"] and all(
                not v["current"] for v in page["versions"]
            )
            identities = {v["id"] for v in page["versions"]}
            assert not seen & identities
            seen |= identities
            pages.append(page)
            cursor = page["next_cursor"]
        expected = {r[0] for r in conn.execute("SELECT id FROM context_observations")}
        conn.rollback()
        with ContextStore(conn)._atomic(), records.policy_guard(conn):
            annotations.write(
                conn,
                "history",
                "note",
                {"notes": "Explicit reconciliation, not semantic certification"},
            )
        stale = await client.call_tool(
            "session_annotations",
            {"session_id": "history", "cursor": original_cursor},
            raise_on_error=False,
        )
        assert stale.is_error
    store.append(
        kind=annotations.KINDS["note"],
        subject="history",
        payload={"notes": "x" * 5000},
        producer="oversized-peer",
        authority="reported",
        owner_session_id="history",
    )
    atomic = cli(db, "--max-bytes", "4096", "--limit", "2")
    checks = {
        "actual_cli_includes_complete_current_conflict": first["current_count"] == 2
        and first["current_group_complete"]
        and len([v for v in first["versions"] if v["current"]]) == 2,
        "actual_mcp_continuation_recovers_all_versions": seen == expected and len(pages) > 1,
        "no_duplicate_or_repeated_cursor": len(seen) == 13 and len(cursors) == len(pages),
        "actual_mcp_rejects_cursor_after_correction": stale.is_error,
        "oversized_current_group_is_atomic": atomic["current_count"] == 2
        and not atomic["current_group_complete"]
        and not any(v["current"] for v in atomic["versions"]),
        "all_page_outputs_fit_budget": all(
            len(json.dumps(x, ensure_ascii=False, separators=(",", ":")).encode()) <= 32768
            for x in [first, *pages]
        )
        and len(json.dumps(atomic, ensure_ascii=False, separators=(",", ":")).encode()) <= 4096,
        "work_bounds_are_disclosed": first["work"]["vm_steps_observed"]
        < first["work"]["vm_step_limit"],
        "foreign_keys_intact": conn.execute("PRAGMA foreign_key_check").fetchall() == [],
    }
    conn.close()
    assert all(checks.values()), checks
    return {
        "checks": checks,
        "overview": first,
        "history_page": pages[0],
        "atomic_group": atomic,
        "stale_cursor": {
            "refused": stale.is_error,
            "why": "A correction changed the access generation; restart the request",
        },
        "pages_traversed": len(pages),
        "runtime": {
            "python": sys.executable,
            "module": annotations.__file__,
            "require_installed": require_installed,
        },
        "limits": (
            "Fictional mechanical interface checks, not semantic answer quality. VM steps "
            "exclude Python hashing and IO latency. Scoped sync, managed lifecycle "
            "and shared installation remain open."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(exercise(root, args.require_installed))
    (root / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"checks": result["checks"], "output": str(root)}))


if __name__ == "__main__":
    main()
