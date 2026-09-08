"""Opt-in concept-sidecar checks against a real SQLite Online Backup.

These tests only run with ``-m live_concepts`` and only touch the owner's
real database through the SQLite Online Backup API on a disposable copy
under ``/tmp``; source sentinels are asserted unchanged by the harness
itself and re-asserted here.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agent_session_tools.context.concept_live import (
    run_live_copy_migration_receipt,
)
from agent_session_tools.migrations import CURRENT_VERSION

LIVE_DB = Path.home() / ".config/studyloop/sessions.db"
RECEIPT = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "data"
    / "concept-sidecar-migration-v49-receipt.json"
)

pytestmark = [
    pytest.mark.live_concepts,
    pytest.mark.skipif(not LIVE_DB.is_file(), reason="owner's live database absent"),
]


def _sentinels(path: Path) -> tuple[int, int]:
    with closing(
        sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    ) as conn:
        return (
            conn.execute("PRAGMA user_version").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        )


def test_real_online_backup_upgrades_to_v49_with_retained_receipt():
    before = _sentinels(LIVE_DB)

    receipt = run_live_copy_migration_receipt(LIVE_DB)

    assert receipt["to_version"] == CURRENT_VERSION == 49
    assert receipt["sidecar_tables_present"] == [
        "context_concepts",
        "context_concept_events",
        "context_concept_clock",
        "context_concept_fts",
        "context_concept_schema",
    ]
    # Freshly installed sidecar is empty on the disposable copy.
    assert receipt["counts"]["context_concepts"] == 0
    assert receipt["counts"]["context_concept_events"] == 0
    assert receipt["counts"]["sessions"] > 0

    RECEIPT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    assert _sentinels(LIVE_DB) == before
