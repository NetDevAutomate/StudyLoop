"""Canonical-path scope, immutable citation and transaction regression tests."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from agent_session_tools.context.provenance import (
    ExecutionState,
    Origin,
    Scope,
    ScopeAssignment,
)
from agent_session_tools.context.store import (
    Access,
    Citation,
    ContextStore,
    NativeSource,
)
from agent_session_tools.migrations import CURRENT_VERSION, migrate

PERSONAL = Access(scope=Scope.PERSONAL)
WORK = Access(scope=Scope.WORK)


def native(session="p1", key="event-1", body="Parser smoke passed.", **kwargs):
    return NativeSource(
        session_id=session,
        native_key=key,
        harness="codex",
        native_kind="message",
        native_locator="fixture.jsonl:1",
        parser_version="fixture-v1",
        machine_id="fixture-machine",
        body=body,
        origin=Origin.CONVERSATION,
        **kwargs,
    )


@pytest.fixture
def store(migrated_db):
    conn, _ = migrated_db
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    for sid in ("p1", "p2", "w1", "u1"):
        conn.execute("INSERT INTO sessions(id,source) VALUES (?,?)", (sid, "fixture"))
    conn.commit()
    core = ContextStore(conn)
    for project, scope in (
        ("personal-one", Scope.PERSONAL),
        ("personal-two", Scope.PERSONAL),
        ("work-one", Scope.WORK),
    ):
        core.configure_project(
            ScopeAssignment(
                scope=scope, project_id=project, policy_id="explicit-fixture-policy"
            )
        )
    for sid, project in (
        ("p1", "personal-one"),
        ("p2", "personal-two"),
        ("w1", "work-one"),
    ):
        core.assign_session(sid, project)
    return core


def proposal(store, evidence_id, body, access=PERSONAL, statement="A reported check"):
    return store.propose(
        statement=statement,
        state=ExecutionState.COMPLETED,
        target="parser",
        generator="fixture-model",
        citations=[
            Citation(evidence_id=evidence_id, start=0, end=len(body), quote=body)
        ],
        access=access,
    )


def test_versions_are_immutable_idempotent_and_content_bound(store):
    old = native(body="I will run the check.")
    first = store.capture(old)
    assert store.capture(old) == first
    newer = store.capture(replace(old, body="I have now run the check."))
    assert newer != first
    assert store.source(first, PERSONAL)["body"] == old.body
    assert (
        store.source(newer, PERSONAL)["source_key"]
        == store.source(first, PERSONAL)["source_key"]
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.conn.execute(
            "UPDATE context_evidence SET body=? WHERE id=?", ("changed", first)
        )
    assert (
        store.conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 2
    )


def test_unknown_source_time_is_not_import_time(store):
    eid = store.capture(native())
    row = store.source(eid, PERSONAL)
    assert row["recorded_at"] is None
    assert row["first_captured_at"]


def test_source_and_search_filter_scope_before_output(store):
    p = store.capture(native(body="shared PERSONAL marker"))
    w = store.capture(native("w1", body="shared WORK_SECRET marker"))
    u = store.capture(native("u1", body="shared UNCLASSIFIED_SECRET marker"))
    assert store.source(w, PERSONAL) is None
    assert store.source(u, PERSONAL) is None
    assert store.source(p, WORK) is None
    rows = store.search("shared", PERSONAL)
    assert [r["id"] for r in rows] == [p]
    assert "SECRET" not in json.dumps(rows)
    assert (
        store.search("shared", Access(scope=Scope.PERSONAL, projects=frozenset())) == []
    )
    assert store.source(u, Access(scope=Scope.UNCLASSIFIED)) is not None
    assert (
        store.source(
            u, Access(scope=Scope.UNCLASSIFIED, projects=frozenset({"personal-one"}))
        )
        is None
    )


def test_citations_use_exact_unicode_offsets_and_retain_old_version(store):
    old = native(body="🐍 café: the check is planned.")
    eid = store.capture(old)
    quote = "the check is planned."
    start = old.body.index(quote)
    aid = store.propose(
        statement="It was planned",
        state=ExecutionState.PLANNED,
        target=None,
        generator="test",
        access=PERSONAL,
        citations=[
            Citation(evidence_id=eid, start=start, end=len(old.body), quote=quote)
        ],
    )
    store.capture(replace(old, body="The check completed."))
    assertion = store.assertion(aid, PERSONAL)
    assert assertion["citations"][0]["quote"] == quote
    assert assertion["semantic_status"] == "unverified_interpretation"
    assert assertion["citations"][0]["evidence_id"] == eid


@pytest.mark.parametrize(
    "start,end,quote",
    [
        (0, 100, "Parser smoke passed."),
        (1, 20, "Parser smoke passed."),
        (0, 6, "forged"),
    ],
)
def test_bad_citation_cannot_leave_an_assertion(store, start, end, quote):
    eid = store.capture(native())
    with pytest.raises(ValueError, match="Citation does not match"):
        store.propose(
            statement="Invalid",
            state=ExecutionState.COMPLETED,
            target=None,
            generator="test",
            citations=[Citation(evidence_id=eid, start=start, end=end, quote=quote)],
            access=PERSONAL,
        )
    assert (
        store.conn.execute("SELECT count(*) FROM context_assertions").fetchone()[0] == 0
    )


def test_cross_scope_proposal_cannot_select_a_work_source(store):
    eid = store.capture(native("w1", body="work secret"))
    with pytest.raises(ValueError, match="unavailable"):
        proposal(store, eid, "work secret")
    aid = proposal(store, eid, "work secret", access=WORK)
    assert store.assertion(aid, PERSONAL) is None


def test_reclassification_hides_entire_multi_project_assertion_and_relationship(store):
    body = "same check"
    p1 = store.capture(native(body=body))
    p2 = store.capture(native("p2", body=body))
    first = proposal(store, p1, body)
    joint = store.propose(
        statement="Both projects used the same check",
        state=ExecutionState.UNKNOWN,
        target=None,
        generator="test",
        access=PERSONAL,
        citations=[
            Citation(evidence_id=eid, start=0, end=len(body), quote=body)
            for eid in (p1, p2)
        ],
    )
    store.relate(joint, first, "supports", "test", PERSONAL)
    assert len(store.relations(first, PERSONAL)) == 1
    store.configure_project(
        ScopeAssignment(
            scope=Scope.WORK, project_id="personal-two", policy_id="reclassified"
        )
    )
    assert store.assertion(joint, PERSONAL) is None
    assert store.assertion(joint, WORK) is None
    assert store.relations(first, PERSONAL) == []
    assert store.assertion(first, PERSONAL) is not None


def test_concurrent_corrections_keep_both_branches_and_original(store):
    body = "Check status is disputed."
    eid = store.capture(native(body=body))
    original = proposal(store, eid, body)
    corrections = [
        proposal(store, eid, body, statement=s)
        for s in ("It is planned", "It is complete")
    ]
    for aid in corrections:
        relation = store.relate(aid, original, "corrects", "test", PERSONAL)
        assert store.relate(aid, original, "corrects", "test", PERSONAL) == relation
    assert len(store.relations(original, PERSONAL)) == 2
    assert store.assertion(original, PERSONAL)["statement"] == "A reported check"
    assert all(
        store.assertion(aid, PERSONAL)["semantic_status"] == "unverified_interpretation"
        for aid in corrections
    )


def test_failure_inside_outer_transaction_rolls_back_only_operation(store):
    body = "a fact"
    eid = store.capture(native(body=body))
    store.conn.execute("INSERT INTO sessions(id,source) VALUES ('outer','fixture')")
    citation = Citation(evidence_id=eid, start=0, end=len(body), quote=body)
    with pytest.raises(sqlite3.IntegrityError):
        store.propose(
            statement="Duplicate citation fails late",
            state=ExecutionState.UNKNOWN,
            target=None,
            generator="test",
            citations=[citation, citation],
            access=PERSONAL,
        )
    assert store.conn.in_transaction
    assert store.conn.execute("SELECT 1 FROM sessions WHERE id='outer'").fetchone()
    assert not store.conn.execute("SELECT 1 FROM context_assertions").fetchone()
    store.conn.rollback()


def test_deleted_source_purges_dependent_assertion_and_fts(store):
    # This tests canonical dependency cleanup, not full application forgetting.
    eid = store.capture(native(body="unique_deleted_token"))
    aid = proposal(store, eid, "unique_deleted_token")
    store.conn.execute("DELETE FROM context_evidence WHERE id=?", (eid,))
    assert store.assertion(aid, PERSONAL) is None
    assert not store.conn.execute(
        "SELECT 1 FROM context_assertions WHERE id=?", (aid,)
    ).fetchone()
    assert store.search("unique_deleted_token", PERSONAL) == []


def test_tombstone_suppresses_native_and_legacy_insert_paths(store):
    store.conn.execute(
        "INSERT INTO context_tombstones VALUES (?,?,?)",
        ("gone", "deletion-fixture", "2026-09-05T00:00:00Z"),
    )
    store.conn.execute("INSERT INTO sessions(id,source) VALUES ('gone','fixture')")
    store.conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('gone-message','gone','user','secret')"
    )
    assert not store.conn.execute("SELECT 1 FROM sessions WHERE id='gone'").fetchone()
    assert not store.conn.execute(
        "SELECT 1 FROM messages WHERE id='gone-message'"
    ).fetchone()
    with pytest.raises(ValueError, match="forgotten"):
        store.capture(native("gone", body="secret"))
    # This is suppression, not proof of deletion propagation or managed restore.


def test_migration_failure_is_atomic_and_retry_preserves_legacy(temp_db, monkeypatch):
    import agent_session_tools.context.schema as schema
    import agent_session_tools.migrations as migrations

    conn, _ = temp_db
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "CURRENT_VERSION", 30)
        migrate(conn)
    conn.execute("INSERT INTO sessions(id,source) VALUES ('old','fixture')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('old-msg','old','user','old words')"
    )
    conn.commit()
    with monkeypatch.context() as patch:
        patch.setattr(schema, "STATEMENTS", (*schema.STATEMENTS[:3], "INVALID SQL"))
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 30
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_projects'"
    ).fetchone()
    migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
    assert (
        conn.execute("SELECT content FROM messages WHERE id='old-msg'").fetchone()[0]
        == "old words"
    )
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert migrate(conn) == []


def test_compaction_preserves_live_wal_evidence_and_rebuilds_fts(store, tmp_path):
    from agent_session_tools.tiering import compact_database

    store.conn.execute("PRAGMA wal_autocheckpoint=0")
    eid = store.capture(native(body="evidence in the live journal"))
    aid = proposal(store, eid, "evidence in the live journal")
    source_path = store.conn.execute("PRAGMA database_list").fetchone()[2]
    dest = tmp_path / "compacted.db"
    stats = compact_database(Path(source_path), dest)
    conn = sqlite3.connect(dest)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        copied = ContextStore(conn)
        assert copied.source(eid, PERSONAL) is not None
        assert copied.assertion(aid, PERSONAL) is not None
        assert [row["id"] for row in copied.search("journal", PERSONAL)] == [eid]
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not any("_fts" in table for table in stats.tables_copied)
    finally:
        conn.close()


def test_corrupted_source_is_rejected_on_every_body_read_path(store):
    eid = store.capture(native(body="original searchable words"))
    aid = proposal(store, eid, "original searchable words")
    # Fault injection outside the supported API: the hash must still reject it.
    store.conn.execute("DROP TRIGGER context_evidence_immutable")
    store.conn.execute(
        "UPDATE context_evidence SET body=? WHERE id=?", ("altered content", eid)
    )
    for read in (
        lambda: store.source(eid, PERSONAL),
        lambda: store.search("original", PERSONAL),
        lambda: store.assertion(aid, PERSONAL),
    ):
        with pytest.raises(ValueError, match="binding failed"):
            read()


def test_citation_cannot_be_shifted_by_an_update(store):
    eid = store.capture(native(body="same same"))
    aid = proposal(store, eid, "same same")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.conn.execute(
            "UPDATE context_citations SET start_offset=5,end_offset=9,quote=? WHERE assertion_id=?",
            ("same", aid),
        )


def test_source_time_normalizes_zone_before_ordering(store):
    early = store.capture(
        native(key="early", body="zone test", recorded_at="2026-09-05T10:00:00+02:00")
    )
    late = store.capture(
        native(key="late", body="zone test", recorded_at="2026-09-05T09:00:00Z")
    )
    assert [r["id"] for r in store.search("zone", PERSONAL)] == [late, early]
    assert store.source(early, PERSONAL)["recorded_at"] == "2026-09-05T08:00:00+00:00"


def test_existing_tombstoned_version_cannot_be_recaptured(store):
    record = native()
    eid = store.capture(record)
    store.conn.execute(
        "INSERT INTO context_tombstones VALUES (?,?,?)",
        ("p1", "deleted-existing", "2026-09-05T00:00:00Z"),
    )
    with pytest.raises(ValueError, match="forgotten"):
        store.capture(record)
    assert store.source(eid, PERSONAL) is None


def test_failed_upgrade_preserves_callers_outer_transaction(temp_db, monkeypatch):
    import agent_session_tools.context.schema as schema
    import agent_session_tools.migrations as migrations

    conn, _ = temp_db
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "CURRENT_VERSION", 30)
        migrate(conn)
    conn.execute("INSERT INTO sessions(id,source) VALUES ('outer-owner','fixture')")
    with monkeypatch.context() as patch:
        patch.setattr(schema, "STATEMENTS", (*schema.STATEMENTS[:3], "INVALID SQL"))
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn)
    assert conn.in_transaction
    assert conn.execute("SELECT 1 FROM sessions WHERE id='outer-owner'").fetchone()
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_projects'"
    ).fetchone()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 30
    conn.commit()
    migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION


def test_newer_database_is_not_silently_accepted(store):
    store.conn.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError, match="newer"):
        migrate(store.conn)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 999
    with pytest.raises(RuntimeError, match="Unsupported context schema"):
        store.search("anything", PERSONAL)
