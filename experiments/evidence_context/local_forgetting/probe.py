"""Run actual native capture and local lifecycle CLI against fictional databases."""

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from agent_session_tools.context import annotations, lifecycle, records
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore
from agent_session_tools.exporters.codex import CodexExporter


def cli(db, *args):
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agent_session_tools.context.cli", *args, "--db", str(db)],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def run(output, require_installed):
    if require_installed and (
        "site-packages" not in lifecycle.__file__
        or importlib.util.find_spec("studyloop") is not None
    ):
        raise RuntimeError(
            "This proof requires an installed standalone memory runtime without StudyLoop"
        )
    output.mkdir(parents=True, exist_ok=False)
    config = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal-project": {"scope": "personal", "roots": [str(output / "personal")]},
                "work-project": {"scope": "work", "roots": [str(output / "work")]},
            },
        }
    }
    cfg = output / "config.json"
    cfg.write_text(json.dumps(config))
    os.environ["STUDYLOOP_CONFIG"] = str(cfg)
    os.environ.pop("SESSION_CONTEXT_SCOPE", None)
    archives = output / "archives"
    archives.mkdir()
    for name in ("personal", "work"):
        rows = [
            {"type": "session_meta", "payload": {"cwd": str(output / name)}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": f"UNIQUE_{name.upper()}_CONVERSATION"}
                    ],
                },
            },
        ]
        (archives / f"rollout-{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    original_archives = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archives.iterdir()
    }
    db = output / "sessions.db"
    c = records.connect(db)
    apply_policy(c, ScopePolicy.from_config(config), actor="fictional lesson", dry_run=False)
    exporter = CodexExporter(archives)
    initial = exporter.export_all(c, incremental=False)
    sid = c.execute(
        "SELECT id FROM sessions WHERE project_path=?", (str(output / "personal"),)
    ).fetchone()[0]
    with ContextStore(c)._atomic(), records.policy_guard(c):
        c.execute(
            "INSERT INTO study_sessions(id,session_id,started_at) VALUES ('study',?,'fixture')",
            (sid,),
        )
        records.bind(c, "study_sessions", "study", session_id=sid)
        c.execute(
            "INSERT INTO study_notes(study_session_id,title,body) "
            "VALUES ('study','Older unowned note','UNIQUE_PERSONAL_NOTE')"
        )
        first = annotations.write(c, sid, "note", {"notes": "UNIQUE_PERSONAL_FIRST_REPORT"})
        second = annotations.write(c, sid, "note", {"notes": "UNIQUE_PERSONAL_CORRECTION"})
    reversible = output / "eviction-fixture.db"
    with sqlite3.connect(reversible) as copy:
        c.backup(copy)
    native_links = c.execute("SELECT count(*) FROM context_native_message_sources").fetchone()[0]
    c.close()

    preview = cli(db, "forget", sid)
    start = time.perf_counter()
    applied = cli(db, "forget", sid, "--apply")
    elapsed = round((time.perf_counter() - start) * 1000, 3)
    canonical_files = list(output.glob("sessions.db*"))
    marker_absent = all(b"UNIQUE_PERSONAL_" not in p.read_bytes() for p in canonical_files)
    c = records.connect(db)
    source_gone = not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    legacy_note_gone = not c.execute("SELECT 1 FROM study_notes").fetchone()
    correction_retained = (
        c.execute(
            "SELECT previous_id FROM context_observation_supersedes WHERE observation_id=?",
            (second,),
        ).fetchone()[0]
        == first
    )
    retirements = c.execute(
        "SELECT kind,count(*) FROM context_retirements GROUP BY kind"
    ).fetchall()
    replay = exporter.export_all(c, incremental=False)
    no_reimport = not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    fk_ok = c.execute("PRAGMA foreign_key_check").fetchall() == []
    work_preserved = c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    c.close()

    other = records.connect(reversible)
    with ContextStore(other)._atomic(), lifecycle.eviction(other):
        lifecycle.purge_session(other, sid, permanent=False)
    no_permanent_controls = all(
        other.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
        for t in (
            "context_retirements",
            "context_tombstones",
            "context_observation_tombstones",
            "context_annotation_retirements",
        )
    )
    normal_mode = (
        other.execute("SELECT mode FROM context_lifecycle_mode").fetchone()[0] == "ordinary"
    )
    reimport = exporter.export_all(other, incremental=False)
    reversible_reimport = bool(
        other.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    )
    other.close()
    checks = {
        "actual_native_capture_has_rendering_links": initial.errors == 0 and native_links >= 2,
        "preview_did_not_apply": preview["applied"] is False,
        "actual_cli_applied_local_forgetting": applied["applied"] is True,
        "canonical_file_cleanup_completed": applied["canonical_file_cleanup"]["complete"],
        "unique_forgotten_marker_absent_from_canonical_files": marker_absent,
        "native_source_removed": source_gone,
        "older_detachable_note_removed": legacy_note_gone,
        "content_free_correction_link_retained": correction_retained,
        "actual_exporter_replay_suppressed": replay.forgotten == 1
        and replay.errors == 0
        and no_reimport,
        "unrelated_work_source_preserved": work_preserved,
        "foreign_keys_intact": fk_ok,
        "eviction_did_not_mint_permanent_controls": no_permanent_controls,
        "eviction_mode_restored": normal_mode,
        "eviction_primitive_allows_native_reimport": reversible_reimport and reimport.errors == 0,
        "external_native_archives_unchanged": original_archives
        == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archives.iterdir()},
        "replica_and_restore_limits_explicit": applied["replica_reconciliation"] == "not_performed"
        and applied["managed_restore_reconciled"] is False,
    }
    if not all(checks.values()):
        raise AssertionError(checks)
    return {
        "capture": {
            "native_rendering_links": native_links,
            "sessions": 2,
            "authority": "Native capture is distinct from reported annotations.",
        },
        "preview": preview,
        "forget": applied,
        "replay": {
            "forgotten_sessions": replay.forgotten,
            "errors": replay.errors,
            "native_archives_unchanged": checks["external_native_archives_unchanged"],
        },
        "eviction": {
            "permanent_controls_created": not no_permanent_controls,
            "native_reimport_allowed": reversible_reimport,
            "limit": "Storage primitive only; no peer permission, regrant "
            "or acknowledgement has been simulated.",
        },
        "retirement_counts": {r[0]: r[1] for r in retirements},
        "checks": checks,
        "timing": {
            "single_cli_forget_with_startup_ms": elapsed,
            "limit": "Single fictional run, not a throughput or engine benchmark.",
        },
        "runtime": {"module": lifecycle.__file__, "require_installed": require_installed},
        "limits": "Canonical local database/WAL only. Peer reconciliation, full-store "
        "propagation, managed backup restore and external archive erasure are not "
        "established. The separate eviction fixture intentionally retains fictional "
        "data for the lesson.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.require_installed)
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": result["checks"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
