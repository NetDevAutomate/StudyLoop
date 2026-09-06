"""Opt-in local archive audit. Emits aggregate diagnostics, never transcript bodies.

Selected JSONL files are referenced read-only through temporary symlinks. Kiro's
selected rows are copied from a read-only connection into an isolated source DB.
All captured bodies and temporary source copies disappear when the probe ends.
The output contains counts, timings and source-file hashes, not conversations.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections import Counter
from pathlib import Path

from .runner import database


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def select_files(root, pattern, limit, eligible):
    candidates = sorted(root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    selected = []
    for path in candidates:
        stat = path.stat()
        if time.time() - stat.st_mtime < 60 or stat.st_size > 32 * 1024 * 1024:
            continue
        try:
            if eligible(path):
                selected.append(path)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if len(selected) >= limit:
            break
    return selected


def project_matches(value):
    return isinstance(value, str) and any(
        name in value.lower() for name in ("studyloop", "mailgraph")
    )


def codex_meta(path):
    with path.open() as handle:
        for _ in range(10):
            line = handle.readline()
            if not line:
                break
            row = json.loads(line)
            if isinstance(row, dict) and row.get("type") == "session_meta":
                return row.get("payload", {})
    return {}


def audit(limit, *, inspect=None):
    import agent_session_tools.exporters.kiro as kiro
    from agent_session_tools.context.capture import capture_health
    from agent_session_tools.exporters.claude import ClaudeCodeExporter
    from agent_session_tools.exporters.codex import CodexExporter
    from agent_session_tools.exporters.grok import GrokExporter
    from agent_session_tools.exporters.kiro import KiroCliExporter

    selected = {
        "codex": select_files(
            Path.home() / ".codex/sessions",
            "rollout-*.jsonl",
            limit,
            lambda p: project_matches(codex_meta(p).get("cwd")),
        ),
        "claude_code": select_files(
            Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "projects",
            "*.jsonl",
            limit,
            lambda p: project_matches(str(p.parent)),
        ),
        "grok": select_files(
            Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))) / "sessions",
            "chat_history.jsonl",
            limit,
            lambda p: project_matches(
                json.loads((p.parent / "summary.json").read_text()).get("info", {}).get("cwd")
            ),
        ),
    }
    fingerprints = {name: [digest(p) for p in paths] for name, paths in selected.items()}
    frontends = Counter()
    for path in selected["codex"]:
        value = codex_meta(path).get("originator")
        frontends[
            value
            if value
            in ("Codex Desktop", "codex_desktop", "codex_cli_rs", "codex_vscode", "codex_exec")
            else "other_or_unknown"
        ] += 1
    with tempfile.TemporaryDirectory(prefix="native-capture-audit-") as directory:
        temp = Path(directory)
        config = temp / "config.json"
        config.write_text('{"memory":{"default_scope":"unclassified"}}')
        previous_config = os.environ.get("STUDYLOOP_CONFIG")
        previous_kiro = kiro.KIRO_DB
        os.environ["STUDYLOOP_CONFIG"] = str(config)
        try:
            for harness, paths in selected.items():
                for index, path in enumerate(paths):
                    link = temp / harness / str(index) / path.name
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(path)
                    if harness == "grok":
                        (link.parent / "summary.json").symlink_to(path.parent / "summary.json")
            kiro_count = 0
            if kiro.KIRO_DB.is_file():
                source = sqlite3.connect(kiro.KIRO_DB.resolve().as_uri() + "?mode=ro", uri=True)
                rows = source.execute(
                    "SELECT key,conversation_id,value,created_at,updated_at FROM conversations_v2 "
                    "WHERE lower(key) LIKE '%studyloop%' OR lower(key) LIKE '%mailgraph%' "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                source.close()
                kiro_count = len(rows)
                native = sqlite3.connect(temp / "kiro.sqlite3")
                native.execute(
                    "CREATE TABLE conversations_v2(key TEXT,conversation_id TEXT,value TEXT,"
                    "created_at INTEGER,updated_at INTEGER)"
                )
                native.executemany("INSERT INTO conversations_v2 VALUES (?,?,?,?,?)", rows)
                native.commit()
                native.close()
                fingerprints["kiro_cli"] = [
                    hashlib.sha256(str(row[2]).encode()).hexdigest() for row in rows
                ]
            kiro.KIRO_DB = temp / "kiro.sqlite3"
            conn = database(temp / "sessions.db")
            exporters = [
                CodexExporter(sessions_dir=temp / "codex"),
                ClaudeCodeExporter(projects_dir=temp / "claude_code"),
                GrokExporter(sessions_dir=temp / "grok"),
                KiroCliExporter(),
            ]
            captures = {}
            for exporter in exporters:
                before = time.perf_counter()
                stats = exporter.export_all(conn)
                captures[exporter.source_name] = {
                    **vars(stats),
                    "elapsed_seconds": round(time.perf_counter() - before, 3),
                }
            evidence = conn.execute("SELECT body,body_sha256 FROM context_evidence").fetchall()
            valid = sum(hashlib.sha256(row[0].encode()).hexdigest() == row[1] for row in evidence)
            report = {
                "sample_selection": (
                    "latest stable StudyLoop/MailGraph archives; at most 32MiB per JSONL file; "
                    "not representative or exhaustive"
                ),
                "selected_sessions": {
                    **{name: len(paths) for name, paths in selected.items()},
                    "kiro_cli": kiro_count,
                },
                "source_hashes": fingerprints,
                "codex_originator_values": dict(frontends),
                "capture_stats": captures,
                "health": capture_health(conn),
                "stored_body_hashes_valid": valid,
                "stored_body_count": len(evidence),
                "legacy_message_count": conn.execute("SELECT count(*) FROM messages").fetchone()[0],
                "native_kind_counts": [
                    dict(zip(("harness", "kind", "count"), row, strict=True))
                    for row in conn.execute(
                        "SELECT harness,native_kind,count(*) FROM context_evidence "
                        "GROUP BY harness,native_kind"
                    )
                ],
                "revision_known": conn.execute(
                    "SELECT count(*) FROM context_evidence WHERE revision IS NOT NULL"
                ).fetchone()[0],
                "native_machine_known": conn.execute(
                    "SELECT count(*) FROM context_evidence WHERE machine_id != 'unknown'"
                ).fetchone()[0],
                "claims": {
                    "archive_completeness": "not_established",
                    "installed_hook_runtime": "not_established",
                    "answer_accuracy_improvement": "not_measured",
                },
            }
            if inspect is not None:
                report["context_probe"] = inspect(conn)
            conn.close()
            report["source_files_unchanged_during_probe"] = all(
                [digest(p) for p in paths] == fingerprints[name] for name, paths in selected.items()
            )
            return report
        finally:
            kiro.KIRO_DB = previous_kiro
            if previous_config is None:
                os.environ.pop("STUDYLOOP_CONFIG", None)
            else:
                os.environ["STUDYLOOP_CONFIG"] = previous_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=2, choices=range(1, 6))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a fresh report path")
    report = audit(args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "captures": report["capture_stats"],
                "stored_body_count": report["stored_body_count"],
                "hashes_valid": report["stored_body_hashes_valid"],
            }
        )
    )


if __name__ == "__main__":
    main()
