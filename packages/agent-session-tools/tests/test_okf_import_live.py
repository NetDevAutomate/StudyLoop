"""Opt-in full legacy OKF import against a real SQLite Online Backup.

tasks.md 3.5: the 2,033-file legacy OKF corpus is imported on a disposable
Online Backup copy, counts are reconciled against the A3b1 baseline
(``legacy-okf-import-baseline.json``: scanned/parsed/legacy_unbound = 2,033,
bound = 0), and the sanitized aggregates-only report is attached to the
OpenSpec change directory. The OKF tree is read-only for the importer and
its sentinel is asserted unchanged; the live database is only ever touched
through the Online Backup API.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agent_session_tools.context.concept_live import run_live_okf_import

LIVE_DB = Path.home() / ".config/studyloop/sessions.db"
OKF_ROOT = Path.home() / ".local/share/sessionweaver/poc-storage-decision/okf-store"
EVIDENCE = (
    Path(__file__).resolve().parents[3]
    / "openspec"
    / "changes"
    / "sessionweaver-phase2-retrofit"
    / "evidence"
    / "legacy-okf-import-report.json"
)

# A3b1 baseline (SessionWeaver docs/data/legacy-okf-import-baseline.json,
# captured 2026-09-07 on a v47 corpus of 5,678 sessions): every parseable
# record imports as legacy-unbound, nothing binds, nothing is dropped.
# Explained delta against the baseline's scanned=2033: the tree on disk has
# since gained two non-record markdown files, which classify as
# invalid_schema -- reported, never silently dropped (errata #2) -- while
# the parseable corpus is still exactly the baseline's 2,033 records.
BASELINE = {
    "scanned": 2035,
    "invalid_schema": 2,
    "parsed": 2033,
    "legacy_unbound": 2033,
    "bound": 0,
    "missing_session": 0,
    "imported": 2033,
    "write_failures": 0,
}

pytestmark = [
    pytest.mark.live_concepts,
    pytest.mark.timeout(600),
    pytest.mark.skipif(not LIVE_DB.is_file(), reason="owner's live database absent"),
    pytest.mark.skipif(not OKF_ROOT.is_dir(), reason="legacy OKF tree absent"),
]


def _sentinels(path: Path) -> tuple[int, int]:
    with closing(
        sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    ) as conn:
        return (
            conn.execute("PRAGMA user_version").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        )


def test_full_legacy_okf_import_reconciles_against_the_a3b1_baseline(
    tmp_path, monkeypatch
):
    before = _sentinels(LIVE_DB)
    config_path = tmp_path / "live-okf-config.json"
    config_path.write_text(
        json.dumps({"memory": {"default_scope": "unclassified", "projects": {}}})
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)

    report = run_live_okf_import(LIVE_DB, OKF_ROOT, config_path=config_path)

    # Baseline reconciliation: the frozen corpus facts (2,033 parseable
    # records, all imported legacy-unbound, zero binds/losses) must hold
    # exactly; the visibility sub-classification split may differ from the
    # baseline because this run widens the scope (every project retained
    # unclassified) on a newer corpus -- the report retains the split for
    # the ledger to explain.
    for key, expected in BASELINE.items():
        assert report["write"][key] == expected, (key, report["write"][key])
    assert report["dry_run"]["writes"] == 0
    assert report["status"]["dry_run_write_classification_matches"] is True
    assert report["idempotent_reimport"]["already_present"] == 2033
    assert report["idempotent_reimport"]["writes"] == 0
    assert report["status"]["idempotent_reimport"] is True

    integrity = report["integrity"]
    assert integrity["concept_roots"] == 2033
    assert integrity["legacy_roots"] == 2033
    assert integrity["lifecycle_events"] == 2033
    assert integrity["foreign_key_violations"] == 0
    assert integrity["fts_consistent"] is True
    assert integrity["fts_rows"] == 2033

    assert report["okf_source_sentinel_unchanged"] is True
    assert report["source_sentinels_unchanged"] is True
    assert report["source"]["okf_markdown_files"] >= 2033

    serialized = json.dumps(report, sort_keys=True)
    assert str(OKF_ROOT) not in serialized
    assert str(LIVE_DB) not in serialized

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    assert _sentinels(LIVE_DB) == before
