#!/usr/bin/env python3
"""Run B4's aggregate-only live identity gate on a disposable Online Backup."""

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
import types
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

_EXPECTED_REF = (
    "fe15996c933fe3817247"  # pragma: allowlist secret
    "35c89f77e4002f6f942a"  # pragma: allowlist secret
)
_EXPECTED_CONTRACT_HASH = (
    "504c2d403ebf77e26639e86795b9397b"  # pragma: allowlist secret
    "77c0c1346e6092401ea7919b20d2b8d1"  # pragma: allowlist secret
)
_EXPECTED_GOLD_HASH = (
    "1bdc8e2488eff430fc4f49dd73625465"  # pragma: allowlist secret
    "3b21cb7ab4d777c9854e1b0764248280"  # pragma: allowlist secret
)
_EXPECTED_SOURCE_VERSION = 47
_EXPECTED_SOURCE_SESSIONS = 5_813


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _sentinels(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        try:
            return {
                "user_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
                "session_count": int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
                "message_count": int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
            }
        finally:
            conn.rollback()


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


def _extract_released_source(repo: Path, destination: Path) -> Path:
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "v0.2.0^{}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if resolved != _EXPECTED_REF:
        raise RuntimeError(f"v0.2.0 resolved to unexpected commit {resolved}")
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", _EXPECTED_REF],
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(destination, filter="data")
    return destination / "src"


def _tools() -> dict[str, Any]:
    from agent_session_tools.mcp_server import mcp

    return {
        tool.name: tool.fn  # type: ignore[attr-defined]
        for tool in asyncio.run(mcp._list_tools())
    }


def _ordered_hits(payload: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "concepts": [hit["concept_id"] for hit in payload["concepts"]],
        "sessions": [hit["session_id"] for hit in payload["sessions"]],
    }


def run(
    *,
    source_db: Path,
    okf_store: Path,
    upstream_repo: Path,
    contract_path: Path,
    gold_path: Path,
) -> dict[str, Any]:
    """Execute the identity gate and return sanitized aggregate evidence."""
    if _sha256(contract_path) != _EXPECTED_CONTRACT_HASH:
        raise RuntimeError("recall contract hash does not match SessionWeaver v0.2.0")
    if _sha256(gold_path) != _EXPECTED_GOLD_HASH:
        raise RuntimeError("gold corpus hash does not match SessionWeaver v0.2.0")
    before = _sentinels(source_db)
    if before["user_version"] != _EXPECTED_SOURCE_VERSION:
        raise RuntimeError(f"expected live schema v47, found v{before['user_version']}")
    if before["session_count"] != _EXPECTED_SOURCE_SESSIONS:
        raise RuntimeError(
            f"expected {_EXPECTED_SOURCE_SESSIONS} live sessions, found {before['session_count']}"
        )

    temp_root = Path(tempfile.mkdtemp(prefix="studyloop-b4-recall-"))
    old_env = {
        key: os.environ.get(key)
        for key in ("HOME", "STUDYLOOP_CONFIG", "STUDYLOOP_DB", "DATABASE_PATH")
    }
    evidence: dict[str, Any] | None = None
    try:
        base_backup = temp_root / "base-v47.db"
        local_db = temp_root / "studyloop-v49.db"
        upstream_db = temp_root / "sessionweaver-v47.db"
        _online_backup(source_db, base_backup)
        # Both implementations receive clones of one pinned Online Backup.
        # Their schema authorities are intentionally incompatible: released
        # SessionWeaver owns v47 while StudyLoop B3 owns v49.
        _online_backup(base_backup, local_db)
        _online_backup(base_backup, upstream_db)
        home = temp_root / "home"
        home.mkdir()
        config_path = temp_root / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "memory": {"default_scope": "unclassified", "projects": {}},
                    "database": {
                        "path": str(local_db),
                        "archive_path": str(temp_root / "archive.db"),
                        "backup_dir": str(temp_root / "backups"),
                    },
                    "logging": {"path": str(temp_root / "studyloop.log")},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        os.environ["HOME"] = str(home)
        os.environ["STUDYLOOP_CONFIG"] = str(config_path)
        os.environ.pop("STUDYLOOP_DB", None)
        os.environ.pop("DATABASE_PATH", None)

        from agent_session_tools.context.concepts import ConceptService
        from agent_session_tools.migrations import migrate

        with closing(sqlite3.connect(local_db)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            migrate(conn)
        local_import = ConceptService(local_db).import_okf(
            okf_store, actor="studyloop-b4-live-acceptance"
        )
        if local_import.write_failures:
            raise RuntimeError(
                f"StudyLoop legacy import had {local_import.write_failures} write failures"
            )

        released_src = _extract_released_source(upstream_repo, temp_root / "upstream")
        sys.path.insert(0, str(released_src))
        released_package = types.ModuleType("session_weaver")
        released_package.__path__ = [str(released_src / "session_weaver")]
        released_package.__package__ = "session_weaver"
        sys.modules["session_weaver"] = released_package
        try:
            upstream_recall = importlib.import_module("session_weaver.recall").recall
            upstream_service = importlib.import_module("session_weaver.concepts").ConceptService(
                upstream_db
            )
            upstream_import = upstream_service.import_okf(
                okf_store, actor="studyloop-b4-live-acceptance"
            )
            if upstream_import.write_failures:
                raise RuntimeError(
                    "SessionWeaver legacy import had "
                    f"{upstream_import.write_failures} write failures"
                )
            tools = _tools()
            questions = json.loads(gold_path.read_text(encoding="utf-8"))
            total_concepts = 0
            total_sessions = 0
            mismatches = 0
            with patch("agent_session_tools.mcp_server._get_db_path", return_value=local_db):
                for question in questions:
                    local_payload = tools["memory_recall"](question=question["question"], k=5)
                    upstream_payload = upstream_recall(
                        upstream_db, question["question"], k=5
                    ).to_dict()
                    local_hits = _ordered_hits(local_payload)
                    upstream_hits = _ordered_hits(upstream_payload)
                    if local_hits != upstream_hits:
                        mismatches += 1
                    total_concepts += len(local_hits["concepts"])
                    total_sessions += len(local_hits["sessions"])
        finally:
            sys.path.remove(str(released_src))
            for name in tuple(sys.modules):
                if name == "session_weaver" or name.startswith("session_weaver."):
                    sys.modules.pop(name, None)

        evidence = {
            "evidence_schema": "studyloop.b4-recall-live-identity",
            "evidence_version": 1,
            "source": {
                "user_version": before["user_version"],
                "session_count": before["session_count"],
                "message_count": before["message_count"],
            },
            "scope": "unclassified",
            "released_upstream_commit": _EXPECTED_REF[:8],
            "questions": len(questions),
            "questions_by_type": dict(sorted(Counter(item["type"] for item in questions).items())),
            "ordered_hit_lists_identical": len(questions) - mismatches,
            "mismatches": mismatches,
            "aggregate_concept_hits": total_concepts,
            "aggregate_session_hits": total_sessions,
            "okf_import": {
                "studyloop": {
                    "scanned": local_import.scanned,
                    "imported": local_import.imported,
                    "writes": local_import.writes,
                    "write_failures": local_import.write_failures,
                },
                "sessionweaver": {
                    "scanned": upstream_import.scanned,
                    "imported": upstream_import.imported,
                    "writes": upstream_import.writes,
                    "write_failures": upstream_import.write_failures,
                },
            },
        }
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(temp_root, ignore_errors=False)

    after = _sentinels(source_db)
    if before != after:
        raise RuntimeError("live source sentinels changed during B4 acceptance")
    if temp_root.exists():
        raise RuntimeError(f"temporary acceptance directory survived: {temp_root}")
    assert evidence is not None
    evidence["source_sentinels_unchanged"] = True
    evidence["temporary_directory_removed"] = True
    if evidence["mismatches"]:
        raise RuntimeError(
            f"ordered hit-list identity failed for {evidence['mismatches']} questions"
        )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--source-db",
        type=Path,
        default=Path.home() / ".config/studyloop/sessions.db",
    )
    parser.add_argument(
        "--okf-store",
        type=Path,
        default=Path.home() / ".local/share/sessionweaver/poc-storage-decision/okf-store",
    )
    parser.add_argument(
        "--upstream-repo",
        type=Path,
        default=Path("/Users/ataylor/code/personal/tools/session_weaver"),
    )
    parser.add_argument("--contract", type=Path, default=root / "docs/data/recall-contract.json")
    parser.add_argument("--gold", type=Path, default=root / "docs/data/gold.json")
    args = parser.parse_args()
    evidence = run(
        source_db=args.source_db,
        okf_store=args.okf_store,
        upstream_repo=args.upstream_repo,
        contract_path=args.contract,
        gold_path=args.gold,
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
