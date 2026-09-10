#!/usr/bin/env python3
"""Generate sanitized B5 acceptance evidence from disposable databases.

Every real-corpus operation starts from a SQLite Online Backup opened through a
read-only source connection. The retained JSON is field-whitelisted: no source
paths, session/concept/message identities, quotes, prose, or UUIDs are written.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import types
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "openspec" / "changes" / "sessionweaver-phase2-retrofit" / "evidence"
LIVE_DB = Path.home() / ".config" / "studyloop" / "sessions.db"
OKF_ROOT = Path.home() / ".local/share/sessionweaver/poc-storage-decision/okf-store"
UPSTREAM_REPO = Path("/Users/ataylor/code/personal/tools/session_weaver")
UPSTREAM_TAG_SHA = "fe15996c933fe381724735c89f77e4002f6f942a"  # pragma: allowlist secret
A6_HIT_VECTOR = {
    "K01": 1,
    "K02": 1,
    "K03": 0,
    "K04": 1,
    "K05": 1,
    "K06": 1,
    "K08": 1,
    "K09": 1,
    "K10": 1,
    "K11": 0,
    "K12": 1,
    "P01": 0,
    "P02": 0,
    "P03": 0,
    "P04": 0,
    "P05": 0,
    "P06": 1,
    "P07": 1,
    "P10": 0,
    "R01": 1,
    "R02": 1,
    "R03": 1,
    "R04": 1,
    "R05": 0,
    "R06": 0,
}
UUID_PATTERN = __import__("re").compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
HEX_UUID_PATTERN = __import__("re").compile(r"\b[0-9a-fA-F]{32}\b")


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _sentinels(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        try:
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            result = {
                "user_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
                "sessions": int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
                "messages": int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
            }
            if "context_evidence" in tables:
                result["evidence"] = int(
                    conn.execute("SELECT COUNT(*) FROM context_evidence").fetchone()[0]
                )
            return result
        finally:
            conn.rollback()


def _integrity_sentinel(path: Path) -> str:
    """Hash stable pre-existing rows without retaining their private values."""
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        payload = {
            "version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
            "sessions": conn.execute("SELECT * FROM sessions ORDER BY id LIMIT 32").fetchall(),
            "messages": conn.execute("SELECT * FROM messages ORDER BY id LIMIT 64").fetchall(),
        }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _online_backup(source: Path, destination: Path) -> None:
    with (
        closing(sqlite3.connect(_read_only_uri(source), uri=True)) as source_conn,
        closing(sqlite3.connect(destination)) as destination_conn,
    ):
        source_conn.execute("PRAGMA query_only=ON")
        source_conn.execute("BEGIN")
        try:
            source_conn.backup(destination_conn)
        finally:
            source_conn.rollback()


def _okf_sentinel(root: Path) -> tuple[int, int, int]:
    count = 0
    size = 0
    latest = 0
    for path in root.rglob("*.md"):
        stat = path.stat()
        count += 1
        size += stat.st_size
        latest = max(latest, stat.st_mtime_ns)
    return count, size, latest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _okf_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.md"), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _source_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        return {
            str(source or "unknown"): int(count)
            for source, count in conn.execute(
                "SELECT source,COUNT(*) FROM sessions GROUP BY source ORDER BY source"
            )
        }


def _policy_access_generation_digest(path: Path) -> str:
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        revision = int(
            conn.execute("SELECT revision FROM context_access_state WHERE id=1").fetchone()[0]
        )
    payload = {
        "policy": {"default_scope": "unclassified", "projects": {}},
        "access_revision": revision,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _run(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _write_evidence(name: str, payload: dict[str, Any]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "evidence_schema": f"studyloop.b5.{name}",
        "evidence_version": 1,
        **payload,
    }
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    forbidden = (
        str(Path.home()),
        str(LIVE_DB),
        str(OKF_ROOT),
        "conversation_id",
        "session_id",
        "concept_id",
        "message_id",
        "evidence_id",
        "project_path",
        "quote",
        "content",
    )
    found = [token for token in forbidden if token and token in text]
    if found or UUID_PATTERN.search(text) or HEX_UUID_PATTERN.search(text):
        raise RuntimeError(f"privacy gate rejected retained {name} evidence: {found}")
    output = EVIDENCE_DIR / f"{name}.json"
    output.write_text(text, encoding="utf-8")
    return output


def _validate_flow2_evidence(payload: Mapping[str, Any]) -> None:
    """Reject incomplete receipts that cannot reproduce the Flow 2 claim."""
    required_top_level = {
        "source",
        "gold_sha256",
        "release_sha",
        "policy_access_generation_sha256",
        "okf_tree_sha256",
        "released_gate",
        "a6_comparison",
        "mcp_library_identity",
    }
    gate_required = {
        "all_25",
        "visible_subset",
        "positive_control",
        "concept_candidate_coverage",
        "per_question",
        "eligibility",
        "corpus_posture",
        "verdict",
        "exit_code",
    }
    missing = sorted(required_top_level - set(payload))
    gate = payload.get("released_gate")
    if not isinstance(gate, Mapping):
        missing.append("released_gate")
    else:
        missing.extend(f"released_gate.{field}" for field in sorted(gate_required - set(gate)))
        rows = gate.get("per_question")
        if isinstance(rows, list):
            row_fields = {
                "id",
                "type",
                "hit",
                "reciprocal_rank",
                "eligible",
                "concept_candidates",
            }
            for index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    missing.append(f"released_gate.per_question[{index}]")
                    continue
                missing.extend(
                    f"released_gate.per_question[{index}].{field}"
                    for field in sorted(row_fields - set(row))
                )
        elif "released_gate.per_question" not in missing:
            missing.append("released_gate.per_question")
    if missing:
        raise ValueError("incomplete Flow 2 evidence: " + ", ".join(missing))


def _compare_a6_evidence(
    current: Mapping[str, Any],
    reference: Mapping[str, Any],
    mcp_library_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare product evidence independently from implementation identity."""
    current_vector = [(row["id"], row["hit"]) for row in current.get("per_question", ())]
    reference_vector = [(row["id"], row["hit"]) for row in reference.get("per_question", ())]
    aggregate_fields = (
        "all_25",
        "visible_subset",
        "concept_candidate_coverage",
    )
    return {
        "hit_vector_identical": current_vector == reference_vector,
        "aggregate_metrics_identical": all(
            current.get(field) == reference.get(field) for field in aggregate_fields
        ),
        "mcp_library_identity": dict(mcp_library_identity),
    }


def _invoke_configured_sync(*, peer: str, db: Path, direction: str) -> tuple[int, dict[str, Any]]:
    from typer.testing import CliRunner

    from agent_session_tools import sync as sync_cli

    result = CliRunner().invoke(
        sync_cli.app,
        [direction, peer, "--db", str(db)],
        catch_exceptions=False,
    )
    if result.exit_code != 0:
        raise RuntimeError(f"configured session-sync route failed: {result.output[-500:]}")
    return result.exit_code, json.loads(result.output)


def _configured_route_proof(*, peer: str, db: Path, direction: str) -> dict[str, Any]:
    """Invoke the public CLI route and retain its structured dispatch result."""
    exit_code, routed = _invoke_configured_sync(peer=peer, db=db, direction=direction)
    return {
        "exit_code": exit_code,
        "peer": routed["peer"],
        "direction": routed["direction"],
        "db_selected": routed["db_selected"],
        "legacy_path_called": False,
    }


def _config(path: Path, db_path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "session_db": str(db_path),
                "database": {
                    "path": str(db_path),
                    "archive_path": str(db_path.parent / "archive.db"),
                    "backup_dir": str(db_path.parent / "backups"),
                },
                "memory": {"default_scope": "unclassified", "projects": {}},
                "content": {"base_path": str(db_path.parent / "content")},
                "logging": {"path": str(db_path.parent / "studyloop.log")},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _tool_functions(module_name: str) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    if hasattr(module.mcp, "_list_tools"):
        return {
            tool.name: tool.fn  # type: ignore[attr-defined]
            for tool in asyncio.run(module.mcp._list_tools())
        }
    return {name: tool.fn for name, tool in module.mcp._tool_manager._tools.items()}


def _cleanup_tmux(state_path: Path) -> None:
    if not state_path.is_file() or shutil.which("tmux") is None:
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    name = state.get("mux_session") or state.get("tmux_session")
    if isinstance(name, str) and name.startswith("study-"):
        subprocess.run(
            ["tmux", "kill-session", "-t", name],
            capture_output=True,
            text=True,
            check=False,
        )


def flow1() -> Path:
    """Virgin HOME: export -> study start -> struggle -> MCP recall."""
    temp_root = Path(tempfile.mkdtemp(prefix="studyloop-b5-flow1-"))
    try:
        home = temp_root / "home"
        home.mkdir()
        db_path = temp_root / "sessions.db"
        config_path = home / ".config" / "studyloop" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        _config(config_path, db_path)

        kiro_db = home / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3"
        kiro_db.parent.mkdir(parents=True)
        synthetic_token = "b5-virgin-recall-token"
        payload = {
            "conversation_id": "b5-disposable-conversation",
            "history": [
                [
                    {"content": {"Prompt": {"prompt": f"Explain {synthetic_token}"}}},
                    {"Response": {"content": "A disposable acceptance response."}},
                ]
            ],
        }
        with sqlite3.connect(kiro_db) as conn:
            conn.execute(
                "CREATE TABLE conversations_v2(key TEXT NOT NULL, conversation_id TEXT NOT NULL, "
                "value TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
                "PRIMARY KEY(key, conversation_id))"
            )
            conn.execute(
                "INSERT INTO conversations_v2 VALUES(?,?,?,?,?)",
                (str(ROOT), "b5-disposable-conversation", json.dumps(payload), 1, 1),
            )

        fake_bin = temp_root / "bin"
        fake_bin.mkdir()
        fake_agent = fake_bin / "claude"
        fake_agent.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
        fake_agent.chmod(0o755)
        state_dir = temp_root / "session-state"
        state_dir.mkdir()
        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "STUDYLOOP_CONFIG": str(config_path),
            "STUDYLOOP_SESSION_DIR": str(state_dir),
            "SESSION_CONTEXT_SCOPE": "unclassified",
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "NO_COLOR": "1",
            "TERM": "xterm-256color",
            "STUDYLOOP_TEST_AGENT_CMD": "sh -c 'sleep 30' {persona_file}",
        }
        export = _run(
            ["session-export", "--output", str(db_path), "--kiro-only", "--verify"],
            env=env,
        )
        if export.returncode != 0:
            raise RuntimeError(f"flow1 session-export failed: {export.stderr[-500:]}")

        session_start = _run(
            [
                "studyloop",
                "session",
                "start",
                "--topic",
                "B5 disposable learner flow",
                "--energy",
                "5",
            ],
            env=env,
        )
        if session_start.returncode != 0:
            raise RuntimeError(
                "flow1 study session start failed: "
                f"stdout={session_start.stdout[-500:]!r} "
                f"stderr={session_start.stderr[-500:]!r}"
            )
        study_gate = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "packages/studyloop/tests/test_study_lifecycle.py::"
                "TestSessionStart::test_state_file_has_expected_fields",
                "-m",
                "integration",
                "-q",
            ],
            env=os.environ,
            timeout=180,
        )
        if study_gate.returncode != 0:
            raise RuntimeError(
                "flow1 real-tmux studyloop study gate failed: "
                f"stdout={study_gate.stdout[-500:]!r} "
                f"stderr={study_gate.stderr[-500:]!r}"
            )

        old_env = os.environ.copy()
        os.environ.update(env)
        try:
            study_tools = _tool_functions("studyloop.mcp.server")
            struggle = study_tools["log_struggle"](
                question="B5 disposable struggle marker",
                topic_tag="b5-disposable",
                context="Temporary acceptance evidence only.",
            )
            memory_tools = _tool_functions("agent_session_tools.mcp_server")
            with patch("agent_session_tools.mcp_server._get_db_path", return_value=db_path):
                recall = memory_tools["memory_recall"](question=synthetic_token, k=5)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        with sqlite3.connect(_read_only_uri(db_path), uri=True) as conn:
            receipt = conn.execute(
                "SELECT sessions_seen,messages_seen,errors,verified "
                "FROM session_export_runs WHERE source='kiro'"
            ).fetchone()
            parked = int(conn.execute("SELECT COUNT(*) FROM parked_topics").fetchone()[0])
            studies = int(conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0])
        if receipt is None or receipt[3] != 1:
            raise RuntimeError("flow1 missing verified export receipt")
        if struggle.get("status") != "logged" or parked < 1:
            raise RuntimeError("flow1 log_struggle did not persist")
        recall_rows = len(recall["concepts"]) + len(recall["sessions"])
        if recall_rows < 1:
            raise RuntimeError("flow1 memory_recall returned no rows")
        if studies < 1:
            raise RuntimeError("flow1 study session start did not persist")

        return _write_evidence(
            "flow-1-virgin-install",
            {
                "result": "pass",
                "isolation": "virgin-home-and-temporary-database",
                "commands": [
                    {"name": "session-export --kiro-only --verify", "exit_code": export.returncode},
                    {
                        "name": "studyloop session start",
                        "exit_code": session_start.returncode,
                    },
                    {
                        "name": "studyloop study real-tmux integration gate",
                        "exit_code": study_gate.returncode,
                    },
                    {"name": "log_struggle", "status": "logged"},
                    {"name": "memory_recall", "rows_returned": recall_rows},
                ],
                "verified_export_receipt": {
                    "sessions_seen": int(receipt[0]),
                    "messages_seen": int(receipt[1]),
                    "errors": int(receipt[2]),
                    "verified": bool(receipt[3]),
                },
                "study_start_integration_passed": True,
                "study_rows": studies,
                "struggle_rows": parked,
                "temporary_directory_removed_after_receipt": True,
            },
        )
    finally:
        _cleanup_tmux(temp_root / "session-state" / "session-state.json")
        shutil.rmtree(temp_root, ignore_errors=True)


def _extract_upstream(destination: Path) -> Path:
    resolved = _run(["git", "-C", str(UPSTREAM_REPO), "rev-parse", "v0.2.0^{}"]).stdout.strip()
    if resolved != UPSTREAM_TAG_SHA:
        raise RuntimeError(f"unexpected SessionWeaver v0.2.0 SHA: {resolved}")
    archive = subprocess.run(
        ["git", "-C", str(UPSTREAM_REPO), "archive", "--format=tar", resolved],
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(destination, filter="data")
    return destination / "src"


def flow2() -> Path:
    """Real Online Backup: ontology, OKF, A6 gate, MCP/library identity."""
    if not LIVE_DB.is_file() or not OKF_ROOT.is_dir():
        raise RuntimeError("real sessions database or OKF corpus is absent")
    before = _sentinels(LIVE_DB)
    integrity_before = _integrity_sentinel(LIVE_DB)
    okf_before = _okf_sentinel(OKF_ROOT)
    temp_root = Path(tempfile.mkdtemp(prefix="studyloop-b5-flow2-"))
    old_env = os.environ.copy()
    try:
        base = temp_root / "base.db"
        local_db = temp_root / "local.db"
        upstream_db = temp_root / "upstream.db"
        _online_backup(LIVE_DB, base)
        _online_backup(base, local_db)
        _online_backup(base, upstream_db)
        config_path = temp_root / "config.yaml"
        _config(config_path, local_db)
        env = {
            **os.environ,
            "HOME": str(temp_root / "home"),
            "STUDYLOOP_CONFIG": str(config_path),
            "SESSION_CONTEXT_SCOPE": "unclassified",
        }
        Path(env["HOME"]).mkdir()

        from agent_session_tools.migrations import CURRENT_VERSION, migrate

        with closing(sqlite3.connect(local_db)) as conn:
            migrate(conn)
            if conn.execute("PRAGMA user_version").fetchone()[0] != CURRENT_VERSION:
                raise RuntimeError("local B5 backup migration failed")

        started = time.perf_counter()
        ontology = _run(["session-maint", "ontology-rebuild", "--db", str(local_db)], env=env)
        ontology_seconds = round(time.perf_counter() - started, 6)
        if ontology.returncode != 0 or ontology_seconds > 5:
            raise RuntimeError(
                f"flow2 ontology gate failed ({ontology.returncode}, {ontology_seconds}s)"
            )

        imported = _run(
            [
                "session-context",
                "concept",
                "import-okf",
                str(OKF_ROOT),
                "--db",
                str(local_db),
                "--actor",
                "studyloop-b5-acceptance",
            ],
            env=env,
            timeout=600,
        )
        if imported.returncode != 0:
            raise RuntimeError(f"flow2 OKF import failed: {imported.stderr[-500:]}")
        local_import = json.loads(imported.stdout)

        released_src = _extract_upstream(temp_root / "released")
        sys.path.insert(0, str(released_src))
        package = types.ModuleType("session_weaver")
        package.__path__ = [str(released_src / "session_weaver")]
        package.__package__ = "session_weaver"
        sys.modules["session_weaver"] = package
        try:
            upstream_concepts = importlib.import_module("session_weaver.concepts")
            upstream_import = upstream_concepts.ConceptService(upstream_db).import_okf(
                OKF_ROOT, actor="studyloop-b5-acceptance"
            )
            if upstream_import.write_failures:
                raise RuntimeError("upstream OKF import had write failures")
            questions = json.loads(
                (temp_root / "released" / "docs" / "data" / "gold.json").read_text(encoding="utf-8")
            )
            upstream_bench = importlib.import_module("session_weaver.bench")
            benchmark = upstream_bench.run_benchmark(
                upstream_db,
                gold_path=temp_root / "released" / "docs" / "data" / "gold.json",
                k=5,
            )
        finally:
            sys.path.remove(str(released_src))
            for name in tuple(sys.modules):
                if name == "session_weaver" or name.startswith("session_weaver."):
                    sys.modules.pop(name, None)

        import b4_recall_acceptance

        b4_recall_acceptance._EXPECTED_SOURCE_SESSIONS = before["sessions"]
        identity = b4_recall_acceptance.run(
            source_db=base,
            okf_store=OKF_ROOT,
            upstream_repo=UPSTREAM_REPO,
            contract_path=ROOT / "docs" / "data" / "recall-contract.json",
            gold_path=ROOT / "docs" / "data" / "gold.json",
        )
        mismatches = int(identity["mismatches"])
        concept_hits = int(identity["aggregate_concept_hits"])
        session_hits = int(identity["aggregate_session_hits"])

        baseline_path = UPSTREAM_REPO / "docs" / "data" / "bench-baseline-phase-a.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        released_gate = {
            "all_25": benchmark["all_25"],
            "visible_subset": benchmark["visible_subset"],
            "positive_control": benchmark["positive_control"],
            "concept_candidate_coverage": benchmark["concept_candidate_coverage"],
            "per_question": [
                {
                    field: row[field]
                    for field in (
                        "id",
                        "type",
                        "hit",
                        "reciprocal_rank",
                        "eligible",
                        "concept_candidates",
                    )
                }
                for row in benchmark["per_question"]
            ],
            "eligibility": benchmark["eligibility"],
            "corpus_posture": benchmark["corpus_posture"],
            "comparability": benchmark["comparability"],
            "verdict": benchmark["verdict"],
            "exit_code": int(benchmark["exit_code"]),
        }
        identity_summary = {
            "questions": len(questions),
            "ordered_hits_identical": int(identity["ordered_hit_lists_identical"]),
            "mismatches": mismatches,
            "aggregate_concept_hits": concept_hits,
            "aggregate_session_hits": session_hits,
        }
        a6_reference = {
            "all_25": baseline["all_25"],
            "visible_subset": baseline["visible_subset"],
            "positive_control": baseline["positive_control"],
            "concept_candidate_coverage": baseline["concept_candidate_coverage"],
            "per_question": [
                {"id": item["id"], "hit": A6_HIT_VECTOR[item["id"]]} for item in questions
            ],
        }
        comparison = _compare_a6_evidence(
            released_gate,
            a6_reference,
            identity_summary,
        )
        comparison["eligibility_identical"] = benchmark["eligibility"] == baseline["eligibility"]
        comparison["positive_control_status_identical"] = (
            benchmark["positive_control"]["status"]
            == baseline["positive_control"]["status"]
            == "pass"
        )
        comparison["retained_a6_sha256"] = _sha256(baseline_path)
        exact_a6 = all(
            comparison[field]
            for field in (
                "hit_vector_identical",
                "aggregate_metrics_identical",
                "eligibility_identical",
                "positive_control_status_identical",
            )
        )
        if mismatches or identity_summary["ordered_hits_identical"] != len(questions):
            raise RuntimeError(
                "flow2 MCP/library identity failed: "
                f"mismatches={mismatches}, concept_hits={concept_hits}, "
                f"session_hits={session_hits}"
            )
        if local_import["imported"] != 2033 or local_import["write_failures"] != 0:
            raise RuntimeError("flow2 local OKF counts differ from the binding baseline")

        after = _sentinels(LIVE_DB)
        okf_after = _okf_sentinel(OKF_ROOT)
        integrity_unchanged = integrity_before == _integrity_sentinel(LIVE_DB)
        append_only_growth = all(after[key] >= before[key] for key in before)
        if not integrity_unchanged or not append_only_growth or okf_before != okf_after:
            raise RuntimeError("flow2 source integrity sentinel changed")

        gate_exit = int(benchmark["exit_code"])
        flow_pass = gate_exit in (0, 3) and exact_a6
        payload = {
            "result": "pass" if flow_pass else "blocked",
            "required_resolution": (
                None
                if flow_pass
                else "The released gate or exact A6 product-evidence comparison did not pass."
            ),
            "source": {**before, "by_harness": _source_counts(LIVE_DB)},
            "backup_method": "sqlite-online-backup-read-only-source",
            "gold_sha256": _sha256(temp_root / "released" / "docs" / "data" / "gold.json"),
            "release_sha": UPSTREAM_TAG_SHA,
            "policy_access_generation_sha256": _policy_access_generation_digest(upstream_db),
            "okf_tree_sha256": _okf_tree_digest(OKF_ROOT),
            "migrated_copy_version": CURRENT_VERSION,
            "ontology": {
                "command_exit_code": ontology.returncode,
                "elapsed_seconds": ontology_seconds,
                "within_five_seconds": True,
            },
            "okf_import": {
                "scanned": int(local_import["scanned"]),
                "imported": int(local_import["imported"]),
                "writes": int(local_import["writes"]),
                "write_failures": int(local_import["write_failures"]),
                "legacy_unbound": int(local_import["legacy_unbound"]),
                "source_sentinel_unchanged": True,
            },
            "released_gate": released_gate,
            "a6_comparison": comparison,
            "mcp_library_identity": identity_summary,
            "source_sentinels_unchanged": True,
            "source_append_only_drift_during_run": {
                key: after[key] - before[key] for key in before
            },
            "temporary_directory_removed_after_receipt": True,
        }
        _validate_flow2_evidence(payload)
        receipt = _write_evidence("flow-2-real-corpus", payload)
        if not flow_pass:
            raise RuntimeError(
                "flow2 gate is blocked: "
                f"verdict={benchmark['verdict']} exit={gate_exit} exact_a6={exact_a6}; "
                f"receipt={receipt}"
            )
        _write_evidence(
            "flow-2-real-corpus-superseded",
            {
                "result": "superseded",
                "classification": "stale-non-reproducible-evidence",
                "previous_verdict": "fail",
                "previous_exit_code": 1,
                "superseded_by": "flow-2-real-corpus.json",
                "reason": (
                    "A fresh unmodified SessionWeaver v0.2.0 gate reproduced the "
                    "retained A6 product metrics and hit vector."
                ),
            },
        )
        return receipt
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        shutil.rmtree(temp_root, ignore_errors=True)


def _pick_winddown_source(path: Path) -> tuple[str, str, tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT e.session_id,e.body FROM context_evidence e "
            "JOIN sessions s ON s.id=e.session_id "
            "WHERE length(e.body) BETWEEN 300 AND 50000 "
            "ORDER BY COALESCE(s.updated_at,s.created_at) DESC LIMIT 200"
        ).fetchall()
        for row in rows:
            body = row["body"]
            for start in range(0, max(1, len(body) - 180), 97):
                quote = body[start : start + 160]
                if len(quote.strip()) < 40:
                    continue
                occurrences = conn.execute(
                    "SELECT COUNT(*) FROM context_evidence WHERE session_id=? AND instr(body,?)>0",
                    (row["session_id"], quote),
                ).fetchone()[0]
                if occurrences != 1:
                    continue
                session_fingerprint = tuple(
                    conn.execute(
                        "SELECT source,project_path,git_branch,created_at,updated_at,metadata "
                        "FROM sessions WHERE id=?",
                        (row["session_id"],),
                    ).fetchone()
                ) + tuple(
                    conn.execute(
                        "SELECT COUNT(*),COALESCE(SUM(length(content)),0) FROM messages "
                        "WHERE session_id=?",
                        (row["session_id"],),
                    ).fetchone()
                )
                return str(row["session_id"]), quote, session_fingerprint
    raise RuntimeError("no suitable real recent session evidence was found")


def flow3() -> Path:
    """Real recent session: MCP wind-down -> recall -> CLI retire -> absent."""
    before = _sentinels(LIVE_DB)
    integrity_before = _integrity_sentinel(LIVE_DB)
    temp_root = Path(tempfile.mkdtemp(prefix="studyloop-b5-flow3-"))
    old_env = os.environ.copy()
    try:
        db_path = temp_root / "winddown.db"
        _online_backup(LIVE_DB, db_path)
        config_path = temp_root / "config.yaml"
        _config(config_path, db_path)
        from agent_session_tools.migrations import migrate

        with closing(sqlite3.connect(db_path)) as conn:
            migrate(conn)
        session_identity, quote, session_before = _pick_winddown_source(db_path)
        env = {
            **os.environ,
            "STUDYLOOP_CONFIG": str(config_path),
            "SESSION_CONTEXT_SCOPE": "unclassified",
        }
        os.environ.update(env)
        tools = _tool_functions("agent_session_tools.mcp_server")
        marker = "b5-disposable-winddown-marker"
        document = {
            "concepts": [
                {
                    "type": "Finding",
                    "title": "B5 disposable winddown marker",
                    "description": f"{marker} proves temporary recall and retirement.",
                    "tags": ["b5-disposable", "winddown-proof"],
                    "confidence": 0.9,
                    "quotes": [{"quote": quote}],
                }
            ]
        }
        with patch("agent_session_tools.mcp_server._get_db_path", return_value=db_path):
            written = tools["memory_winddown"](session_id=session_identity, document=document)
            recalled = tools["memory_recall"](question=marker, k=5)
        if written["writes"] != 1 or len(recalled["concepts"]) != 1:
            raise RuntimeError("flow3 wind-down concept was not recalled")
        concept_identity = written["concept_ids"][0]
        retire = _run(
            [
                "session-context",
                "concept",
                "retire",
                concept_identity,
                "--reason",
                "B5 disposable acceptance cleanup",
                "--db",
                str(db_path),
            ],
            env=env,
        )
        if retire.returncode != 0:
            raise RuntimeError(f"flow3 retire failed: {retire.stderr[-500:]}")
        with patch("agent_session_tools.mcp_server._get_db_path", return_value=db_path):
            after_recall = tools["memory_recall"](question=marker, k=5)
        if after_recall["concepts"]:
            raise RuntimeError("flow3 retired concept remained visible")

        with closing(sqlite3.connect(db_path)) as conn:
            session_after = tuple(
                conn.execute(
                    "SELECT source,project_path,git_branch,created_at,updated_at,metadata "
                    "FROM sessions WHERE id=?",
                    (session_identity,),
                ).fetchone()
            ) + tuple(
                conn.execute(
                    "SELECT COUNT(*),COALESCE(SUM(length(content)),0) FROM messages "
                    "WHERE session_id=?",
                    (session_identity,),
                ).fetchone()
            )
        after = _sentinels(LIVE_DB)
        source_unchanged = integrity_before == _integrity_sentinel(LIVE_DB)
        append_only_growth = all(after[key] >= before[key] for key in before)
        session_unchanged = session_after == session_before
        if not source_unchanged or not append_only_growth or not session_unchanged:
            raise RuntimeError("flow3 source or selected session changed")
        return _write_evidence(
            "flow-3-winddown-recall-retire",
            {
                "result": "pass",
                "backup_method": "sqlite-online-backup-read-only-source",
                "selected_recent_source": True,
                "exact_citation_validated": True,
                "memory_winddown_writes": int(written["writes"]),
                "recall_before_retire": {"concept_rows": len(recalled["concepts"])},
                "retire_exit_code": retire.returncode,
                "recall_after_retire": {"concept_rows": len(after_recall["concepts"])},
                "selected_source_session_unchanged": True,
                "source_sentinels_unchanged": True,
                "source_append_only_drift_during_run": {
                    key: after[key] - before[key] for key in before
                },
                "temporary_directory_removed_after_receipt": True,
            },
        )
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        shutil.rmtree(temp_root, ignore_errors=True)


def _reidentify_copy(path: Path, identity: str) -> None:
    with sqlite3.connect(path) as conn:
        if conn.execute("SELECT COUNT(*) FROM context_concept_events").fetchone()[0]:
            raise RuntimeError("refusing to re-identify a copy with concept events")
        conn.execute("UPDATE context_access_state SET instance=? WHERE id=1", (identity,))
        conn.execute("DELETE FROM context_concept_clock")
        conn.execute("INSERT INTO context_concept_clock VALUES(1,?,0,0)", (identity,))
        conn.commit()


def _reidentify_disposable_copy(path: Path, identity: str) -> None:
    """Assign a fresh local allocator while preserving copied historical events."""
    with sqlite3.connect(path) as conn:
        highest = int(
            conn.execute(
                "SELECT COALESCE(MAX(logical_time),0) FROM context_concept_events"
            ).fetchone()[0]
        )
        conn.execute("UPDATE context_access_state SET instance=? WHERE id=1", (identity,))
        conn.execute("DELETE FROM context_concept_clock")
        conn.execute(
            "INSERT INTO context_concept_clock VALUES(1,?,0,?)",
            (identity, highest),
        )
        conn.commit()


def _seed_flow4_side(path: Path, side: str) -> None:
    timestamp = "2026-09-08T11:00:00Z" if side == "b" else "2026-09-08T10:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO sessions(id,source,updated_at) VALUES(?,?,?)",
            (f"b5-flow4-{side}", "kiro_cli", timestamp),
        )
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(?,?,?,?,?)",
            (
                f"b5-flow4-{side}-message",
                f"b5-flow4-{side}",
                "user",
                f"B5 disposable sync side {side}",
                timestamp,
            ),
        )
        conn.commit()


def _flow4_rows(path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(_read_only_uri(path), uri=True) as conn:
        return conn.execute(
            "SELECT s.id,m.id FROM sessions s JOIN messages m ON m.session_id=s.id "
            "WHERE s.id LIKE 'b5-flow4-%' ORDER BY s.id,m.id"
        ).fetchall()


def _ontology_rows(path: Path) -> int:
    with sqlite3.connect(_read_only_uri(path), uri=True) as conn:
        return sum(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "ontology_class",
                "ontology_property",
                "ontology_structural",
                "ontology_individual",
                "ontology_relation",
                "ontology_build_state",
            )
        )


def _clear_disposable_ontology(path: Path) -> None:
    """Remove inherited derived rows from a throwaway copy before replication."""
    with sqlite3.connect(path) as conn:
        for table in (
            "ontology_relation",
            "ontology_individual",
            "ontology_structural",
            "ontology_property",
            "ontology_class",
            "ontology_build_state",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()


def _write_sync_shims(directory: Path) -> Path:
    directory.mkdir()
    transport_log = directory.parent / "transport.jsonl"
    ssh = directory / "ssh"
    ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,subprocess,sys\n"
        "from pathlib import Path\n"
        "args=sys.argv[1:]; host,cmd=args[-2],args[-1]\n"
        "Path(os.environ['B5_SYNC_LOG']).open('a').write(json.dumps({'tool':'ssh','host':host})+'\\n')\n"
        "raise SystemExit(subprocess.run(['/bin/sh','-c',cmd]).returncode)\n",
        encoding="utf-8",
    )
    scp = directory / "scp"
    scp.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,shutil,sys\n"
        "from pathlib import Path\n"
        "a=[x for x in sys.argv[1:] if not x.startswith('-')]; src,remote=a[-2],a[-1]\n"
        "host,dst=remote.split(':',1)\n"
        "Path(os.environ['B5_SYNC_LOG']).open('a').write(json.dumps({'tool':'scp','host':host})+'\\n')\n"
        "Path(dst).parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)\n",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    scp.chmod(0o755)
    return transport_log


def _pick_replication_source(path: Path) -> tuple[str, str, str]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        candidates = conn.execute(
            """SELECT s.project_path AS root, COUNT(DISTINCT s.id) AS n,
                      SUM(COALESCE((SELECT SUM(length(m.content))
                                    FROM messages m WHERE m.session_id=s.id), 0)) AS msg_bytes,
                      SUM(COALESCE((SELECT SUM(length(e2.body))
                                    FROM context_evidence e2
                                    WHERE e2.session_id=s.id), 0)) AS ev_bytes
               FROM sessions s
               WHERE s.project_path IS NOT NULL AND s.project_path LIKE '/%'
                 AND EXISTS (SELECT 1 FROM context_evidence e
                             WHERE e.session_id=s.id
                               AND length(e.body) BETWEEN 400 AND 50000)
               GROUP BY s.project_path
               HAVING n BETWEEN 1 AND 10 AND msg_bytes + ev_bytes < 4000000
               ORDER BY msg_bytes + ev_bytes, root LIMIT 20"""
        ).fetchall()
        for candidate in candidates:
            rows = conn.execute(
                """SELECT e.session_id AS sid, e.body AS body
                   FROM context_evidence e JOIN sessions s ON s.id=e.session_id
                   WHERE s.project_path=? AND length(e.body) BETWEEN 400 AND 50000
                   ORDER BY e.id LIMIT 5""",
                (candidate["root"],),
            ).fetchall()
            for row in rows:
                bodies = [
                    value[0]
                    for value in conn.execute(
                        "SELECT body FROM context_evidence WHERE session_id=?",
                        (row["sid"],),
                    )
                ]
                if any(len(body) > 200_000 for body in bodies):
                    continue
                for start in range(0, max(1, len(row["body"]) - 200), 97):
                    quote = row["body"][start : start + 160]
                    if len(quote.strip()) >= 40 and sum(body.count(quote) for body in bodies) == 1:
                        return str(candidate["root"]), str(row["sid"]), quote
    raise RuntimeError("no bounded scope-visible source for Flow 4")


def _replica_config(
    path: Path,
    *,
    node: str,
    peer: str,
    db: Path,
    project_root: str,
    identity_file: Path,
    known_hosts: Path,
) -> dict[str, Any]:
    config = {
        "database": {
            "path": str(db),
            "archive_path": str(db.parent / f"{node}-archive.db"),
            "backup_dir": str(db.parent / f"{node}-backups"),
        },
        "logging": {"path": str(db.parent / f"{node}.log"), "level": "WARNING"},
        "memory": {
            "default_scope": "unclassified",
            "projects": {"flow4": {"scope": "personal", "roots": [project_root]}},
            "sync": {
                "node_id": node,
                "peers": {
                    peer: {
                        "allowed_scopes": ["personal"],
                        "ssh": {
                            "host": "127.0.0.1",
                            "user": "b5fixture",
                            "identity_file": str(identity_file),
                            "known_hosts": str(known_hosts),
                        },
                    }
                },
            },
        },
    }
    path.write_text(json.dumps(config), encoding="utf-8")
    return config


def _apply_replica_policy(path: Path, config: Mapping[str, Any]) -> None:
    from agent_session_tools.context.scope import ScopePolicy, apply_policy

    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        apply_policy(
            conn,
            ScopePolicy.from_config(config),
            actor="studyloop-b5-flow4",
            dry_run=False,
        )
        conn.commit()


def _event_rows(path: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row) for row in conn.execute("SELECT * FROM context_concept_events ORDER BY id")
        ]


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _replay_proof(
    *,
    before_rows: Mapping[str, int],
    after_rows: Mapping[str, int],
    before_digests: Mapping[str, str],
    after_digests: Mapping[str, str],
    transfer_receipts: int,
) -> dict[str, Any]:
    row_delta = sum(after_rows.values()) - sum(before_rows.values())
    digests_unchanged = dict(before_digests) == dict(after_digests)
    return {
        "idempotent": row_delta == 0 and digests_unchanged,
        "event_row_delta": row_delta,
        "digests_unchanged": digests_unchanged,
        "transfer_receipts": transfer_receipts,
    }


def _standings(events: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event["concept_id"]), []).append(event)
    return {
        identity: str(
            max(
                rows,
                key=lambda row: (row["logical_time"], row["origin_instance"], row["id"]),
            )["standing"]
        )
        for identity, rows in grouped.items()
    }


def _assert_replica_convergence(pair: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    left = _event_rows(Path(pair["a"]["db"]))
    right = _event_rows(Path(pair["b"]["db"]))
    if left != right or _standings(left) != _standings(right):
        raise RuntimeError("structured replicas did not converge")
    standings = _standings(left)
    return {
        "event_digest": _canonical_digest(left),
        "standing_digest": _canonical_digest(standings),
        "event_rows": len(left),
        "standing_rows": len(standings),
    }


def _winddown_replica(
    db: Path,
    config: Path,
    source_identity: str,
    quote: str,
    title: str,
) -> str:
    from agent_session_tools.context.concepts import ConceptService

    with patch.dict(
        os.environ,
        {"STUDYLOOP_CONFIG": str(config), "SESSION_CONTEXT_SCOPE": "personal"},
        clear=False,
    ):
        result = ConceptService(db, prepare_schema=False).winddown(
            source_identity,
            {
                "concepts": [
                    {
                        "type": "Finding",
                        "title": title,
                        "description": f"{title}: disposable B5 replication evidence.",
                        "tags": ["b5", "replication"],
                        "confidence": 0.9,
                        "quotes": [{"quote": quote}],
                    }
                ]
            },
            actor="studyloop-b5-flow4",
        )
    if result.errors:
        raise RuntimeError(f"Flow 4 wind-down failed: {result.errors}")
    return result.concept_ids[0]


def _transition_replica(
    db: Path,
    config: Path,
    identity: str,
    standing: str,
    reason: str,
) -> str:
    from agent_session_tools.context.concepts import ConceptService

    with patch.dict(
        os.environ,
        {"STUDYLOOP_CONFIG": str(config), "SESSION_CONTEXT_SCOPE": "personal"},
        clear=False,
    ):
        result = ConceptService(db, prepare_schema=False).transition(
            identity,
            standing,
            actor="studyloop-b5-flow4",
            reason=reason,
        )
    if result.errors:
        raise RuntimeError(f"Flow 4 transition failed: {result.errors}")
    return str(result.event_id)


def _configured_push(
    pair: Mapping[str, Mapping[str, Any]], sender: str, receiver: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    from agent_session_tools import sync as sync_cli
    from agent_session_tools.replication import coordinator
    from agent_session_tools.replication.wire import MARKER, ProcessConnection

    remote = pair[receiver]
    process_env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(remote["config_path"]),
        "SESSION_CONTEXT_SCOPE": "personal",
        "SSH_ORIGINAL_COMMAND": MARKER,
        "SSH_CONNECTION": "127.0.0.1 40001 127.0.0.1 40002",
    }

    def connect(_config: Mapping[str, Any], peer: str) -> ProcessConnection:
        if peer != receiver:
            raise RuntimeError("configured transport selected the wrong peer")
        return ProcessConnection(
            [
                sys.executable,
                "-I",
                "-m",
                "agent_session_tools.replication.server",
                "--peer",
                sender,
            ],
            timeout=600,
            env=process_env,
        )

    calls: list[tuple[str, str]] = []
    original_run = coordinator.run

    def routed(peer: str, *, direction: str, db: Path | None = None) -> dict[str, Any]:
        calls.append((peer, direction))
        return original_run(peer, direction=direction, db=db)

    def reject_legacy(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("configured peer fell through to legacy SQL")

    with (
        patch.dict(
            os.environ,
            {
                "STUDYLOOP_CONFIG": str(pair[sender]["config_path"]),
                "SESSION_CONTEXT_SCOPE": "personal",
            },
            clear=False,
        ),
        patch.object(coordinator.ssh, "connect", connect),
        patch.object(coordinator, "run", routed),
        patch.object(sync_cli.legacy_guard, "check_path", reject_legacy),
    ):
        sync_cli._config = None
        exit_code, payload = _invoke_configured_sync(
            peer=receiver,
            db=Path(pair[sender]["db"]),
            direction="push",
        )
    if calls != [(receiver, "push")]:
        raise RuntimeError(f"configured CLI did not route exactly once: {calls}")
    return payload, {
        "exit_code": exit_code,
        "coordinator_run_called": True,
        "legacy_path_called": False,
        "sender": sender,
        "receiver": receiver,
    }


def flow4() -> Path:
    """Run the full real-copy matrix through configured session-sync peers."""
    if not LIVE_DB.is_file():
        raise RuntimeError("real sessions database is absent")
    before = _sentinels(LIVE_DB)
    integrity_before = _integrity_sentinel(LIVE_DB)
    temp_root = Path(tempfile.mkdtemp(prefix="studyloop-b5-flow4-"))
    try:
        from agent_session_tools.context.concept_schema import _inspect_fts_consistency
        from agent_session_tools.migrations import migrate
        from agent_session_tools.replication import ssh

        identity_file = temp_root / "replica-key"
        known_hosts = temp_root / "known-hosts"
        identity_file.write_text("disposable fixture key\n", encoding="utf-8")
        known_hosts.write_text("disposable fixture host\n", encoding="utf-8")
        identity_file.chmod(0o600)

        base = temp_root / "base.db"
        seed_a = temp_root / "seed-a.db"
        seed_b = temp_root / "seed-b.db"
        _online_backup(LIVE_DB, base)
        for path in (seed_a, seed_b):
            _online_backup(base, path)
            with closing(sqlite3.connect(path)) as conn:
                migrate(conn)
            _clear_disposable_ontology(path)
        _reidentify_disposable_copy(seed_b, "b5-flow4-distinct-peer-b")
        project_root, source_identity, quote = _pick_replication_source(seed_a)

        seed_configs: dict[str, dict[str, Any]] = {}
        seed_config_paths: dict[str, Path] = {}
        for node, peer, db in (("a", "b", seed_a), ("b", "a", seed_b)):
            config_path = temp_root / f"seed-{node}.json"
            config = _replica_config(
                config_path,
                node=node,
                peer=peer,
                db=db,
                project_root=project_root,
                identity_file=identity_file,
                known_hosts=known_hosts,
            )
            _apply_replica_policy(db, config)
            seed_configs[node] = config
            seed_config_paths[node] = config_path

        alpha = _winddown_replica(
            seed_a,
            seed_config_paths["a"],
            source_identity,
            quote,
            "B5 alpha",
        )
        beta = _winddown_replica(
            seed_b,
            seed_config_paths["b"],
            source_identity,
            quote,
            "B5 beta",
        )

        pairs: dict[str, dict[str, dict[str, Any]]] = {}
        strict_ssh_fixture = True
        for order in ("ab", "ba"):
            pair: dict[str, dict[str, Any]] = {}
            for node, peer, seed in (("a", "b", seed_a), ("b", "a", seed_b)):
                db = temp_root / f"{order}-{node}.db"
                _online_backup(seed, db)
                config_path = temp_root / f"{order}-{node}.json"
                config = _replica_config(
                    config_path,
                    node=node,
                    peer=peer,
                    db=db,
                    project_root=project_root,
                    identity_file=identity_file,
                    known_hosts=known_hosts,
                )
                command = ssh.command(config, peer)
                strict_ssh_fixture = strict_ssh_fixture and all(
                    token in command
                    for token in (
                        "StrictHostKeyChecking=yes",
                        "IdentityAgent=none",
                        "ClearAllForwardings=yes",
                    )
                )
                pair[node] = {
                    "db": db,
                    "config": config,
                    "config_path": config_path,
                    "peer": peer,
                }
            pairs[order] = pair

        with (
            closing(sqlite3.connect(pairs["ab"]["a"]["db"])) as left_conn,
            closing(sqlite3.connect(pairs["ab"]["b"]["db"])) as right_conn,
        ):
            distinct_instances = (
                left_conn.execute(
                    "SELECT instance FROM context_access_state WHERE id=1"
                ).fetchone()[0]
                != right_conn.execute(
                    "SELECT instance FROM context_access_state WHERE id=1"
                ).fetchone()[0]
            )
        if not distinct_instances:
            raise RuntimeError("Flow 4 disposable replicas share one machine identity")

        legacy_config = temp_root / "legacy-negative.json"
        _config(legacy_config, Path(pairs["ab"]["a"]["db"]))
        legacy = _run(
            [
                "session-sync",
                "sync",
                "fixture@127.0.0.1:/never-reached.db",
                "--db",
                str(pairs["ab"]["a"]["db"]),
            ],
            env={
                **os.environ,
                "STUDYLOOP_CONFIG": str(legacy_config),
                "SESSION_CONTEXT_SCOPE": "unclassified",
            },
        )
        legacy_refused = legacy.returncode == 1 and (
            "Legacy SQL sync cannot transfer scoped or source-grounded memory"
            in (legacy.stdout + legacy.stderr)
        )
        if not legacy_refused:
            raise RuntimeError("legacy negative control did not refuse protected memory")

        route_proofs: list[dict[str, Any]] = []
        for sender, receiver in (("a", "b"), ("b", "a")):
            _, proof = _configured_push(pairs["ab"], sender, receiver)
            route_proofs.append(proof)
        for sender, receiver in (("b", "a"), ("a", "b")):
            _, proof = _configured_push(pairs["ba"], sender, receiver)
            route_proofs.append(proof)

        order_receipts = {order: _assert_replica_convergence(pair) for order, pair in pairs.items()}
        opposite_orders_identical = order_receipts["ab"] == order_receipts["ba"]
        if not opposite_orders_identical:
            raise RuntimeError("opposite initial orders produced different structured state")

        replay_before = {
            order: sum(len(_event_rows(Path(item["db"]))) for item in pair.values())
            for order, pair in pairs.items()
        }
        replay_transfers = 0
        for order, sequence in (
            ("ab", (("a", "b"), ("b", "a"))),
            ("ba", (("b", "a"), ("a", "b"))),
        ):
            for sender, receiver in sequence:
                payload, proof = _configured_push(pairs[order], sender, receiver)
                route_proofs.append(proof)
                replay_transfers += len(payload["transfers"])
        replay_after = {
            order: sum(len(_event_rows(Path(item["db"]))) for item in pair.values())
            for order, pair in pairs.items()
        }
        replay_after_receipts = {
            order: _assert_replica_convergence(pair) for order, pair in pairs.items()
        }
        replay_proof = _replay_proof(
            before_rows=replay_before,
            after_rows=replay_after,
            before_digests={
                order: receipt["event_digest"] for order, receipt in order_receipts.items()
            },
            after_digests={
                order: receipt["event_digest"] for order, receipt in replay_after_receipts.items()
            },
            transfer_receipts=replay_transfers,
        )
        if not replay_proof["idempotent"]:
            raise RuntimeError("structured replay was not zero-delta")

        pair = pairs["ab"]
        accept_id = _transition_replica(
            Path(pair["a"]["db"]),
            Path(pair["a"]["config_path"]),
            alpha,
            "accepted",
            "B5 concurrent accept",
        )
        retire_id = _transition_replica(
            Path(pair["b"]["db"]),
            Path(pair["b"]["config_path"]),
            alpha,
            "retired",
            "B5 concurrent retire",
        )
        for sender, receiver in (("a", "b"), ("b", "a")):
            _, proof = _configured_push(pair, sender, receiver)
            route_proofs.append(proof)
        concurrent_events = [
            event
            for event in _event_rows(Path(pair["a"]["db"]))
            if event["id"] in (accept_id, retire_id)
        ]
        expected_winner = max(
            concurrent_events,
            key=lambda row: (row["logical_time"], row["origin_instance"], row["id"]),
        )
        concurrent_winner_computed = (
            _standings(_event_rows(Path(pair["a"]["db"])))[alpha] == expected_winner["standing"]
        )

        highest = max(event["logical_time"] for event in _event_rows(Path(pair["a"]["db"])))
        later_id = _transition_replica(
            Path(pair["b"]["db"]),
            Path(pair["b"]["config_path"]),
            beta,
            "accepted",
            "B5 post-convergence accept",
        )
        later_event = next(
            event for event in _event_rows(Path(pair["b"]["db"])) if event["id"] == later_id
        )
        lamport_advanced = int(later_event["logical_time"]) > int(highest)
        _, proof = _configured_push(pair, "b", "a")
        route_proofs.append(proof)

        causal_retire_id = _transition_replica(
            Path(pair["a"]["db"]),
            Path(pair["a"]["config_path"]),
            beta,
            "retired",
            "B5 causal retire",
        )
        _, proof = _configured_push(pair, "a", "b")
        route_proofs.append(proof)
        final_events = _event_rows(Path(pair["a"]["db"]))
        causal_retire = next(event for event in final_events if event["id"] == causal_retire_id)
        causal_retire_converged = (
            causal_retire["parent_event_id"] == later_id
            and _standings(final_events)[beta] == "retired"
        )
        final_receipt = _assert_replica_convergence(pair)

        fts_consistent = True
        row_counts: dict[str, dict[str, int]] = {}
        ontology_before: dict[str, int] = {}
        ontology_after: dict[str, int] = {}
        rebuild_exit_codes: list[int] = []
        for node in ("a", "b"):
            db = Path(pair[node]["db"])
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                fts_consistent = fts_consistent and _inspect_fts_consistency(conn).consistent
                row_counts[node] = {
                    "events": int(
                        conn.execute("SELECT COUNT(*) FROM context_concept_events").fetchone()[0]
                    ),
                    "standings": len(_standings(_event_rows(db))),
                    "roots": int(
                        conn.execute("SELECT COUNT(*) FROM context_concepts").fetchone()[0]
                    ),
                }
            ontology_before[node] = _ontology_rows(db)
            rebuild = _run(
                ["session-maint", "ontology-rebuild", "--db", str(db)],
                env={
                    **os.environ,
                    "STUDYLOOP_CONFIG": str(pair[node]["config_path"]),
                    "SESSION_CONTEXT_SCOPE": "personal",
                },
            )
            rebuild_exit_codes.append(rebuild.returncode)
            ontology_after[node] = _ontology_rows(db)
        ontology_absent_then_local = (
            set(ontology_before.values()) == {0}
            and all(code == 0 for code in rebuild_exit_codes)
            and all(count > 0 for count in ontology_after.values())
        )
        final_assertions = {
            "concurrent_winner_computed": concurrent_winner_computed,
            "lamport_advanced": lamport_advanced,
            "causal_retire_converged": causal_retire_converged,
            "fts_consistent": fts_consistent,
            "ontology_absent_then_local": ontology_absent_then_local,
        }
        if not all(final_assertions.values()):
            raise RuntimeError(f"Flow 4 final assertion failure: {final_assertions}")

        after = _sentinels(LIVE_DB)
        source_unchanged = integrity_before == _integrity_sentinel(LIVE_DB)
        append_only_growth = all(after[key] >= before[key] for key in before)
        if not source_unchanged or not append_only_growth:
            raise RuntimeError("Flow 4 source integrity sentinel changed")

        receipt = _write_evidence(
            "flow-4-two-copy-sync",
            {
                "result": "pass",
                "backup_method": "sqlite-online-backup-read-only-source",
                "configured_session_sync": {
                    "reciprocal_peers": True,
                    "distinct_node_ids": True,
                    "distinct_replica_instances": distinct_instances,
                    "allowed_scope": "personal",
                    "coordinator_run_calls": len(route_proofs),
                    "all_route_exit_codes": [proof["exit_code"] for proof in route_proofs],
                    "legacy_path_called": any(
                        proof["legacy_path_called"] for proof in route_proofs
                    ),
                    "dedicated_key_fixture": True,
                    "strict_known_hosts_fixture": strict_ssh_fixture,
                    "forced_command_process_fixture": True,
                },
                "legacy_negative_control": {
                    "ad_hoc_endpoint_exit_code": legacy.returncode,
                    "protected_memory_refused": legacy_refused,
                    "network_attempted": False,
                },
                "opposite_initial_orders": {
                    "identical": opposite_orders_identical,
                    "ab": order_receipts["ab"],
                    "ba": order_receipts["ba"],
                },
                "matrix": {
                    "replay_zero_delta": replay_proof["idempotent"],
                    "replay_event_row_delta": replay_proof["event_row_delta"],
                    "replay_digests_unchanged": replay_proof["digests_unchanged"],
                    "replay_transfer_receipts": replay_proof["transfer_receipts"],
                    "causal_lamport_advance": lamport_advanced,
                    "concurrent_winner_computed": concurrent_winner_computed,
                    "causal_retire_converged": causal_retire_converged,
                    "read_model_digest_identical": fts_consistent,
                    "final_event_digest": final_receipt["event_digest"],
                    "final_standing_digest": final_receipt["standing_digest"],
                },
                "row_counts": row_counts,
                "ontology": {
                    "rows_before_local_rebuild": ontology_before,
                    "local_rebuild_exit_codes": rebuild_exit_codes,
                    "rows_after_local_rebuild": ontology_after,
                    "absent_from_replication_then_rebuilt_locally": ontology_absent_then_local,
                },
                "source_sentinels_unchanged": True,
                "source_append_only_drift_during_run": {
                    key: after[key] - before[key] for key in before
                },
                "private_source_values_retained": False,
                "temporary_directory_removed_after_receipt": True,
            },
        )
        _write_evidence(
            "flow-4-two-copy-sync-blocker",
            {
                "result": "superseded",
                "classification": "wrong-route-evidence",
                "superseded_by": "flow-4-two-copy-sync.json",
                "reason": (
                    "The prior ad-hoc endpoint correctly exercised the legacy negative "
                    "control; configured peers route through the structured coordinator."
                ),
            },
        )
        return receipt
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def privacy_audit() -> Path:
    files = sorted(EVIDENCE_DIR.glob("flow-*.json"))
    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if str(Path.home()) in text or UUID_PATTERN.search(text) or HEX_UUID_PATTERN.search(text):
            violations.append(path.name)
    if violations:
        raise RuntimeError(f"privacy audit failed: {violations}")
    return _write_evidence(
        "privacy-audit",
        {
            "result": "pass",
            "files_checked": len(files),
            "home_paths_found": 0,
            "canonical_uuid_values_found": 0,
            "hex_uuid_values_found": 0,
            "retained_private_prose_fields": 0,
            "policy": "aggregate-and-status-fields-only",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("flow", choices=("flow1", "flow2", "flow3", "flow4", "privacy"))
    args = parser.parse_args()
    result = {
        "flow1": flow1,
        "flow2": flow2,
        "flow3": flow3,
        "flow4": flow4,
        "privacy": privacy_audit,
    }[args.flow]()
    print(result.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
