"""Stage 4 uses real file parsing and SQLite writes, synthetic configuration."""

import json

import pytest

from experiments.evidence_context.capture_health.lab import CaptureLab


@pytest.fixture
def lab(tmp_path):
    value = CaptureLab(tmp_path / "health.db")
    yield value
    value.close()


def report(lab, **changes):
    options = {
        "now": "2026-01-01T01:00:00Z",
        "max_age_seconds": 7200,
        "detected": True,
        "skill_installed": True,
        "hook_registered": True,
        "repair_gaps": 0,
    }
    return lab.report("demo", **{**options, **changes})


def capture(lab, tmp_path, content='[{"id":"1","body":"PRIVATE_SENTINEL"}]'):
    path = tmp_path / "source.json"
    path.write_text(content)
    return lab.capture("demo", path, "2026-01-01T00:00:00Z")


def test_installed_is_not_successful_capture(lab):
    result = report(lab)
    assert "no_successful_capture" in result["issues"]
    assert result["last_success"] is None


def test_success_is_observed_not_complete_history(lab, tmp_path):
    assert capture(lab, tmp_path)
    result = report(lab)
    assert result["state"] == "recent_capture_observed"
    assert result["history_completeness"] == "not_established"
    assert result["last_imported_records"] == 1
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


def test_failed_file_preserves_last_success_and_old_records(lab, tmp_path):
    capture(lab, tmp_path)
    assert not capture(lab, tmp_path, "invalid PRIVATE_SENTINEL")
    result = report(lab)
    assert "parse_failed" in result["issues"]
    assert result["last_success"] is not None
    assert result["parse_failures"] == 1
    assert lab.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 1
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"hook_registered": False}, "hook_registered_missing"),
        ({"skill_installed": None}, "skill_installed_unknown"),
        ({"detected": False}, "source_detected_missing"),
        ({"repair_gaps": None}, "repair_coverage_unknown"),
        ({"repair_gaps": 2}, "repair_gaps"),
        ({"now": "2026-01-02T00:00:00Z"}, "capture_stale"),
        ({"now": "2025-12-31T00:00:00Z"}, "clock_inconsistent"),
    ],
)
def test_health_conditions_remain_visible(lab, tmp_path, changes, expected):
    capture(lab, tmp_path)
    assert expected in report(lab, **changes)["issues"]


def test_missing_file_is_not_empty_history(lab, tmp_path):
    assert not lab.capture("demo", tmp_path / "absent", "2026-01-01T00:00:00Z")
    assert "source_unreadable" in report(lab)["issues"]


def test_valid_empty_file_success_does_not_prove_complete_history(lab, tmp_path):
    assert capture(lab, tmp_path, "[]")
    result = report(lab)
    assert result["last_imported_records"] == 0
    assert result["history_completeness"] == "not_established"


def test_malformed_batch_does_not_partially_import(lab, tmp_path):
    assert not capture(lab, tmp_path, '[{"id":"ok","body":"text"},{"id":3}]')
    assert lab.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0


def test_duplicate_capture_idempotent_and_source_health_isolated(lab, tmp_path):
    capture(lab, tmp_path)
    capture(lab, tmp_path)
    assert lab.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 1
    result = lab.report(
        "other",
        now="2026-01-01T01:00:00Z",
        max_age_seconds=60,
        detected=None,
        skill_installed=None,
        hook_registered=None,
    )
    assert result["last_success"] is None


def test_reopen_preserves_health_and_unicode(tmp_path):
    db = tmp_path / "persistent.db"
    original = CaptureLab(db)
    capture(original, tmp_path, '[{"id":"1","body":"αβ 🧪"}]')
    expected = report(original)
    original.close()
    reopened = CaptureLab.open(db)
    try:
        assert report(reopened) == expected
        assert reopened.conn.execute("SELECT body FROM records").fetchone()[0] == "αβ 🧪"
    finally:
        reopened.close()


def test_out_of_order_attempt_rejected_without_mutation(lab, tmp_path):
    capture(lab, tmp_path)
    with pytest.raises(ValueError, match="precedes"):
        lab.capture("demo", tmp_path / "source.json", "2025-12-31T23:59:59Z")
    assert lab.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_invalid_utf8_is_parse_failure(lab, tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(bytes([255, 254]))
    assert not lab.capture("demo", path, "2026-01-01T00:00:00Z")
    assert report(lab)["parse_failures"] == 1


def test_same_record_id_is_separate_per_source(lab, tmp_path):
    capture(lab, tmp_path)
    path = tmp_path / "source.json"
    path.write_text('[{"id":"1","body":"other body"}]')
    lab.capture("other", path, "2026-01-01T00:00:00Z")
    assert lab.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 2
    assert (
        lab.conn.execute("SELECT body FROM records WHERE source='demo'").fetchone()[0]
        == "PRIVATE_SENTINEL"
    )


def test_empty_incremental_import_preserves_prior_rows(lab, tmp_path):
    capture(lab, tmp_path)
    capture(lab, tmp_path, "[]")
    assert lab.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 1
    assert report(lab)["last_imported_records"] == 0


def test_duplicate_ids_fail_atomically(lab, tmp_path):
    assert not capture(lab, tmp_path, '[{"id":"x","body":"one"},{"id":"x","body":"two"}]')
    assert lab.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0


def test_main_and_live_journal_permissions(lab, tmp_path):
    db = tmp_path / "health.db"
    lab.conn.execute("INSERT INTO records VALUES ('demo','id','synthetic')")
    try:
        assert db.stat().st_mode & 0o077 == 0
        journal = tmp_path / "health.db-journal"
        assert journal.exists()
        assert journal.stat().st_mode & 0o077 == 0
    finally:
        lab.conn.rollback()
