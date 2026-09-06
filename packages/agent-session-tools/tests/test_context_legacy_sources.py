"""Unit coverage for the legacy-DB evidence boundary (`context.legacy_sources`).

Integration coverage for scope enforcement lives in the studyloop package
(`test_context_consumer_scope.py`); these tests pin the module's own edge
behaviour: ordered binding with unknown provenance, timestamp trust rules,
and the persist-time gates.
"""

import json

import pytest

from agent_session_tools.context.legacy_sources import (
    capture_session_input,
    persist_session_input,
    prepare_session_input,
)
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy


@pytest.fixture
def legacy_db(migrated_db, tmp_path, monkeypatch):
    """A migrated DB with one in-scope session and three legacy messages."""
    conn, _ = migrated_db
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/legacy/personal"]},
            },
        }
    }
    config = tmp_path / "scope.yaml"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
        ("legacy-a", "fixture", "/legacy/personal"),
    )
    rows = [
        # (id, role, content, timestamp, seq) — one tz-aware, one naive, one broken
        ("m1", "user", "first question", "2026-09-01T10:00:00+00:00", 1),
        ("m2", "assistant", None, "2026-09-01T10:00:05", 2),
        ("m3", "user", "follow-up", "not-a-timestamp", 3),
    ]
    for mid, role, content, stamp, seq in rows:
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content,timestamp,seq)"
            " VALUES (?,?,?,?,?,?)",
            (mid, "legacy-a", role, content, stamp, seq),
        )
    conn.commit()
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    return conn


def test_prepare_binds_messages_in_order_with_unknown_provenance(legacy_db):
    captured = prepare_session_input(legacy_db, "legacy-a")

    assert captured.session_id == "legacy-a"
    assert [m["role"] for m in captured.messages] == ["user", "assistant", "user"]
    assert len(captured.evidence_ids) == len(captured.messages) == 3
    # Legacy rows must never be promoted to verified native provenance.
    assert all(s.origin is Origin.UNKNOWN for s in captured.native_sources)
    assert all(s.parser_version == "legacy-db-v1" for s in captured.native_sources)
    assert [s.native_key for s in captured.native_sources] == [
        "legacy-message:m1",
        "legacy-message:m2",
        "legacy-message:m3",
    ]


def test_manifest_preserves_shape_and_null_content(legacy_db):
    captured = prepare_session_input(legacy_db, "legacy-a")
    manifest = captured.manifest()

    assert manifest["kind"] == "legacy_session_messages"
    assert manifest["fingerprint"] == captured.fingerprint
    assert [m["evidence_id"] for m in manifest["messages"]] == list(
        captured.evidence_ids
    )
    assert [m["content_is_null"] for m in manifest["messages"]] == [False, True, False]


def test_recorded_at_trusts_only_timezone_aware_timestamps(legacy_db):
    captured = prepare_session_input(legacy_db, "legacy-a")
    recorded = [s.recorded_at for s in captured.native_sources]

    assert recorded[0] == "2026-09-01T10:00:00+00:00"  # tz-aware: kept
    assert recorded[1] is None  # naive: untrusted
    assert recorded[2] is None  # unparseable: untrusted


def test_prepare_unknown_session_raises_scope_error(legacy_db):
    with pytest.raises(ScopeError):
        prepare_session_input(legacy_db, "no-such-session")


def test_persist_rechecks_scope_after_provider_returns(legacy_db):
    captured = prepare_session_input(legacy_db, "legacy-a")
    # Session disappears (e.g. forgotten/reclassified) between prepare and
    # persist. FKs are relaxed only to simulate the removal in the fixture.
    legacy_db.commit()  # close any open transaction so the pragma applies
    legacy_db.execute("PRAGMA foreign_keys=OFF")
    legacy_db.execute("DELETE FROM messages WHERE session_id='legacy-a'")
    legacy_db.execute("DELETE FROM sessions WHERE id='legacy-a'")
    legacy_db.commit()
    legacy_db.execute("PRAGMA foreign_keys=ON")

    with pytest.raises(ScopeError):
        persist_session_input(legacy_db, captured)


def test_capture_round_trip_is_idempotent(legacy_db):
    first = capture_session_input(legacy_db, "legacy-a")
    stored = {
        row[0]
        for row in legacy_db.execute("SELECT id FROM context_evidence").fetchall()
    }
    assert set(first.evidence_ids) <= stored

    second = capture_session_input(legacy_db, "legacy-a")
    assert second.evidence_ids == first.evidence_ids
    assert second.fingerprint == first.fingerprint
