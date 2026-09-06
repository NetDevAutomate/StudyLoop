"""Actual native capture, archive-only reads, forgetting and offline cleanup retry."""

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path


def run(output, require_installed=False):
    from agent_session_tools.context import managed_history, records
    from agent_session_tools.context.observations import ObservationStore
    from agent_session_tools.context.scope import ScopePolicy, apply_policy
    from agent_session_tools.exporters.codex import CodexExporter
    from agent_session_tools.tiering import prune_hot

    if output.exists():
        raise ValueError("Choose a fresh output directory")
    output.mkdir(parents=True)
    archive_dir = output / "archive"
    archive_dir.mkdir()
    hot, full = output / "sessions.db", archive_dir / "sessions_full.db"
    native = output / "native"
    native.mkdir()
    config = {
        "database": {"path": str(hot), "full_db_path": str(full)},
        "logging": {"path": str(output / "session.log"), "level": "WARNING"},
        "memory": {
            "default_scope": "personal",
            "projects": {
                scope: {"scope": scope, "roots": [str(output / scope)]}
                for scope in ("personal", "work")
            },
        },
    }
    cfg = output / "config.json"
    cfg.write_text(json.dumps(config))
    os.environ["STUDYLOOP_CONFIG"] = str(cfg)
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    cli = Path(sys.executable).parent / "session-context"
    query = Path(sys.executable).parent / "session-query"
    if require_installed:
        assert "site-packages" in managed_history.__file__
        assert importlib.util.find_spec("studyloop") is None
        assert cli.is_file() and query.is_file()
    sources = {}
    for name, scope in (("archived", "personal"), ("offline", "personal"), ("work", "work")):
        rows = [
            {"type": "session_meta", "payload": {"id": name, "cwd": str(output / scope)}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "IRIS_" + name.upper() + "_NATIVE"}],
                },
            },
        ]
        path = native / ("rollout-" + name + ".jsonl")
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        sources[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(records.connect(hot)) as conn:
        apply_policy(conn, ScopePolicy.from_config(config), actor="fictional lesson", dry_run=False)
        exporter = CodexExporter(native)
        capture = exporter.export_all(conn, incremental=False)
        assert not capture.errors
        ids = {
            name: conn.execute(
                "SELECT session_id FROM messages WHERE content=?",
                ("IRIS_" + name.upper() + "_NATIVE",),
            ).fetchone()[0]
            for name in ("archived", "offline", "work")
        }
        evidence = conn.execute(
            "SELECT id FROM context_evidence WHERE session_id=?", (ids["archived"],)
        ).fetchone()[0]
        report = ObservationStore(conn).append(
            kind="fixture.report",
            subject="why archive this choice",
            payload={"text": "IRIS_ARCHIVED_REPORT"},
            producer="fictional lesson",
            authority="model_interpretation",
            evidence_ids=[evidence],
        )
        conn.execute("UPDATE sessions SET updated_at='2026-01-01T00:00:00Z'")
        conn.commit()
        with closing(sqlite3.connect(full)) as destination:
            conn.backup(destination)
    pruning = prune_hot(
        days=30,
        hot=hot,
        full=full,
        config=config,
        dry_run=False,
        vacuum=False,
        keep_session_ids={ids["offline"], ids["work"]},
    )
    assert pruning.sessions_deleted == 1

    def call(binary, *args, expected=0):
        module = (
            "agent_session_tools.context.cli"
            if binary == cli
            else "agent_session_tools.query_sessions"
        )
        entry = [str(binary)] if binary.is_file() else [sys.executable, "-m", module]
        result = subprocess.run([*entry, *args], capture_output=True, text=True, timeout=45)
        if result.returncode != expected:
            raise RuntimeError(f"Fixture command failed: {result.returncode}: {result.stderr}")
        return json.loads(result.stdout)

    initial = call(query, "search", "IRIS", "--output-format", "json")
    preview = call(cli, "forget", ids["archived"])
    started = time.perf_counter()
    forgotten = call(cli, "forget", ids["archived"], "--apply")
    elapsed = (time.perf_counter() - started) * 1000
    # Move the whole fixture directory so any SQLite sidecars move with it.
    offline_dir = output / "archive-offline"
    archive_dir.rename(offline_dir)
    pending = call(cli, "forget", ids["offline"], "--apply", expected=2)
    offline_dir.rename(archive_dir)
    hidden = call(query, "search", "IRIS", "--output-format", "json")
    cleanup = call(cli, "cleanup")
    with closing(records.connect(hot)) as conn:
        replay = CodexExporter(native).export_all(conn, incremental=False)
        remaining_hot = {row[0] for row in conn.execute("SELECT id FROM sessions")}
    with closing(records.connect(full)) as conn:
        remaining_full = {row[0] for row in conn.execute("SELECT id FROM sessions")}
        report_absent = not conn.execute(
            "SELECT 1 FROM context_observations WHERE id=?", (report,)
        ).fetchone()
        fts = conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0]
        fk = not conn.execute("PRAGMA foreign_key_check").fetchone()
    checks = {
        "real_native_capture": not capture.errors,
        "actual_verified_hot_pruning": pruning.sessions_deleted == 1,
        "archive_only_source_retrieved": any(
            row["session_id"] == ids["archived"] and row["tier"] == "full" for row in initial
        ),
        "work_excluded_from_search": "IRIS_WORK_NATIVE" not in json.dumps(initial),
        "archive_only_forget_preview": preview.get("selected_from") == "configured_full_history"
        and not preview["applied"],
        "online_permanent_cleanup_complete": forgotten["configured_full_cleanup"]["complete"],
        "offline_cleanup_reported_pending": pending["configured_full_cleanup"]["reason"]
        == "full_store_unavailable",
        "returned_stale_archive_stays_hidden": hidden == [],
        "cleanup_retry_completes": cleanup["complete"],
        "native_reimport_does_not_resurrect": not replay.errors and remaining_hot == {ids["work"]},
        "unrelated_work_preserved_in_full": remaining_full == {ids["work"]},
        "source_derived_report_purged": report_absent,
        "full_fts_and_fk_valid": fts == 1 and fk,
        "full_file_lacks_forgotten_markers": all(
            marker not in full.read_bytes()
            for marker in (b"IRIS_ARCHIVED_NATIVE", b"IRIS_OFFLINE_NATIVE", b"IRIS_ARCHIVED_REPORT")
        ),
        "external_native_files_unchanged": all(
            hashlib.sha256(path.read_bytes()).hexdigest() == value
            for path, value in sources.items()
        ),
    }
    assert all(checks.values()), checks
    return {
        "runtime": {"memory_module": managed_history.__file__, "installed": require_installed},
        "archive_read": {"pruned_sessions": pruning.sessions_deleted, "results": initial},
        "permanent_forgetting": {"preview": preview, "applied": forgotten},
        "offline_recovery": {"pending": pending, "stale_search": hidden, "cleanup": cleanup},
        "reimport": {
            "hot_sessions": len(remaining_hot),
            "full_sessions": len(remaining_full),
            "derived_report_absent": report_absent,
        },
        "checks": checks,
        "timing": {
            "one_archive_only_forget_cli_ms": elapsed,
            "limit": "One fictional run including CLI startup; no engine or throughput comparison.",
        },
        "limits": (
            "Permanent controls in one canonical and one configured full database. "
            "Current/historical withdrawal hides stale archive-only rows; fresh archive "
            "regrant coverage, modern full copying, rich full-history consumers and managed "
            "backup restore remain required. No real owner data/config/archives or peers "
            "changed. External native files intentionally remain unchanged."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.require_installed)
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(result["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
