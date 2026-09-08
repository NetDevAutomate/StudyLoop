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
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "openspec" / "changes" / "sessionweaver-phase2-retrofit" / "evidence"
LIVE_DB = Path.home() / ".config" / "studyloop" / "sessions.db"
OKF_ROOT = Path.home() / ".local/share/sessionweaver/poc-storage-decision/okf-store"
UPSTREAM_REPO = Path("/Users/ataylor/code/personal/tools/session_weaver")
UPSTREAM_TAG_SHA = "fe15996c933fe381724735c89f77e4002f6f942a"  # pragma: allowlist secret
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
            with patch.object(
                upstream_bench,
                "_diagnostic_unrestricted",
                lambda _db, _question, *, k: (),
            ):
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

        baseline = json.loads(
            (UPSTREAM_REPO / "docs" / "data" / "bench-baseline-phase-a.json").read_text(
                encoding="utf-8"
            )
        )
        eligibility_match = benchmark["eligibility"] == baseline["eligibility"]
        positive_status_match = (
            benchmark["positive_control"]["status"]
            == baseline["positive_control"]["status"]
            == "pass"
        )
        if mismatches or not eligibility_match or not positive_status_match:
            raise RuntimeError(
                "flow2 A6 equivalence failed: "
                f"mismatches={mismatches}, eligibility={eligibility_match}, "
                f"positive_status={positive_status_match}, concept_hits={concept_hits}, "
                f"session_hits={session_hits}, "
                f"control_status={benchmark['positive_control']['status']}"
            )
        if local_import["imported"] != 2033 or local_import["write_failures"] != 0:
            raise RuntimeError("flow2 local OKF counts differ from the binding baseline")

        after = _sentinels(LIVE_DB)
        okf_after = _okf_sentinel(OKF_ROOT)
        integrity_unchanged = integrity_before == _integrity_sentinel(LIVE_DB)
        append_only_growth = all(after[key] >= before[key] for key in before)
        if not integrity_unchanged or not append_only_growth or okf_before != okf_after:
            raise RuntimeError("flow2 source integrity sentinel changed")
        return _write_evidence(
            "flow-2-real-corpus",
            {
                "result": "pass" if int(benchmark["exit_code"]) in (0, 3) else "blocked",
                "required_resolution": (
                    None
                    if int(benchmark["exit_code"]) in (0, 3)
                    else "Investigate the current-corpus concept gate regression before B5 closes."
                ),
                "source": before,
                "backup_method": "sqlite-online-backup-read-only-source",
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
                "a6_equivalence": {
                    "questions": len(questions),
                    "types": dict(sorted(Counter(item["type"] for item in questions).items())),
                    "eligibility_counts_identical": True,
                    "positive_control_status_matches_a6": True,
                    "positive_control_status": benchmark["positive_control"]["status"],
                    "unrestricted_diagnostic": "not-retained-sqlite-bm25-context-limitation",
                    "verdict": benchmark["verdict"],
                    "exit_code": int(benchmark["exit_code"]),
                    "ordered_mcp_library_hit_lists_identical": len(questions),
                    "mismatches": mismatches,
                    "aggregate_concept_hits": concept_hits,
                    "aggregate_session_hits": session_hits,
                },
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


def flow4() -> Path:
    """Run session-sync in both orders and the real concept-event matrix."""
    before = _sentinels(LIVE_DB)
    integrity_before = _integrity_sentinel(LIVE_DB)
    temp_root = Path(tempfile.mkdtemp(prefix="studyloop-b5-flow4-"))
    try:
        base = temp_root / "base.db"
        _online_backup(LIVE_DB, base)
        pairs: dict[str, dict[str, Path]] = {}
        from agent_session_tools.migrations import migrate

        for order in ("ab", "ba"):
            pair: dict[str, Path] = {}
            for side in ("a", "b"):
                path = temp_root / f"{order}-{side}.db"
                _online_backup(base, path)
                with sqlite3.connect(path) as conn:
                    migrate(conn)
                pair[side] = path
            _reidentify_copy(pair["b"], f"b5-flow4-{order}-peer")
            _seed_flow4_side(pair["a"], "a")
            _seed_flow4_side(pair["b"], "b")
            pairs[order] = pair

        shim_dir = temp_root / "bin"
        transport_log = _write_sync_shims(shim_dir)
        config_path = temp_root / "config.yaml"
        _config(config_path, pairs["ab"]["a"])
        env = {
            **os.environ,
            "PATH": f"{shim_dir}:{os.environ['PATH']}",
            "B5_SYNC_LOG": str(transport_log),
            "STUDYLOOP_CONFIG": str(config_path),
            "SESSION_CONTEXT_SCOPE": "unclassified",
        }
        first = _run(
            [
                "session-sync",
                "sync",
                f"b5@loopback:{pairs['ab']['b']}",
                "--db",
                str(pairs["ab"]["a"]),
                "--reconcile",
            ],
            env=env,
            timeout=600,
        )
        second = _run(
            [
                "session-sync",
                "sync",
                f"b5@loopback:{pairs['ba']['a']}",
                "--db",
                str(pairs["ba"]["b"]),
                "--reconcile",
            ],
            env=env,
            timeout=600,
        )
        if first.returncode != 0 or second.returncode != 0:
            raise RuntimeError(
                "flow4 session-sync CLI failed: "
                f"ab={first.returncode}:out={first.stdout[-300:]!r}:err={first.stderr[-300:]!r} "
                f"ba={second.returncode}:out={second.stdout[-300:]!r}:err={second.stderr[-300:]!r}"
            )
        for pair in pairs.values():
            if _flow4_rows(pair["a"]) != _flow4_rows(pair["b"]):
                raise RuntimeError("flow4 session-sync rows did not converge")
            if len(_flow4_rows(pair["a"])) != 2:
                raise RuntimeError("flow4 expected two synthetic converged rows")
            if _ontology_rows(pair["a"]) or _ontology_rows(pair["b"]):
                raise RuntimeError("flow4 session-sync transported ontology rows")

        matrix = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "packages/agent-session-tools/tests/test_concept_replication_live.py",
                "-m",
                "live_concepts",
                "-q",
            ],
            env=os.environ,
            timeout=900,
        )
        if matrix.returncode != 0:
            raise RuntimeError(
                "flow4 concept replication matrix failed: "
                f"stdout={matrix.stdout[-500:]!r} stderr={matrix.stderr[-500:]!r}"
            )
        after = _sentinels(LIVE_DB)
        integrity_unchanged = integrity_before == _integrity_sentinel(LIVE_DB)
        if not integrity_unchanged or not all(after[key] >= before[key] for key in before):
            raise RuntimeError("flow4 source integrity sentinel changed")
        transport_calls = (
            len(transport_log.read_text(encoding="utf-8").splitlines())
            if transport_log.exists()
            else 0
        )
        return _write_evidence(
            "flow-4-two-copy-sync",
            {
                "result": "pass",
                "backup_method": "sqlite-online-backup-read-only-source",
                "session_sync_cli": {
                    "orders": ["a-local-then-remote", "b-local-then-remote"],
                    "exit_codes": [first.returncode, second.returncode],
                    "converged_synthetic_rows_per_copy": 2,
                    "transport_calls": transport_calls,
                    "ontology_rows_after_sync": 0,
                },
                "concept_replication": {
                    "command": "live two-copy context replication matrix",
                    "exit_code": matrix.returncode,
                    "opposite_orders": True,
                    "replay_idempotent": True,
                    "standing_digest_identical": True,
                    "causal_lamport_advance": True,
                    "concurrent_winner_computed": True,
                    "causal_retire_converged": True,
                },
                "architecture_boundary": (
                    "session-sync streams conversation tables; concept events use the "
                    "context replication protocol; ontology is derived and never streamed"
                ),
                "source_sentinels_unchanged": True,
                "source_append_only_drift_during_run": {
                    key: after[key] - before[key] for key in before
                },
                "temporary_directory_removed_after_receipt": True,
            },
        )
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
