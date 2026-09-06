"""Bounded history must preserve current disagreement and honest continuation."""

import base64
import json
from collections import Counter

import pytest

from agent_session_tools.context import annotation_pages as pages, annotations, records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.query_budget import QueryBudgetExceeded, query_budget
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, _json


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "p": {"scope": "personal", "roots": [str(tmp_path / "p")]},
                "w": {"scope": "work", "roots": [str(tmp_path / "w")]},
            },
        }
    }
    config = tmp_path / "scope.json"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    path = tmp_path / "sessions.db"
    conn = records.connect(path)
    conn.executemany(
        "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
        [("p", "fixture", str(tmp_path / "p")), ("w", "fixture", str(tmp_path / "w"))],
    )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    yield conn, path, config, settings
    conn.close()


def chain(conn, count, *, previous=None, text_size=0):
    identities = []
    store = ObservationStore(conn)
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        for n in range(count):
            identity = store.append(
                kind=annotations.KINDS["note"],
                subject="p",
                payload={"notes": "x" * text_size + f"version {n}"},
                producer="fixture",
                authority="reported",
                owner_session_id="p",
                supersedes=previous or [],
            )
            previous = [identity]
            identities.append(identity)
    return identities


def test_history_pages_recover_all_versions_without_duplicates(history_db):
    conn, *_ = history_db
    ids = chain(conn, 20)
    first = annotations.view(conn, "p", limit=3)
    assert first["current_count"] == 1 and first["current_group_complete"]
    assert next(v for v in first["versions"] if v["current"])["id"] == ids[-1]
    seen = {v["id"] for v in first["versions"]}
    cursor = first["next_cursor"]
    traversed = set()
    conn.rollback()
    while cursor is not None:
        assert cursor not in traversed
        traversed.add(cursor)
        result = annotations.view(conn, "p", limit=3, cursor=cursor)
        assert result["coverage"] == "partial"
        assert result["current_count"] == 1 and not result["current_group_complete"]
        assert all(not v["current"] for v in result["versions"])
        page_ids = {v["id"] for v in result["versions"]}
        assert not seen & page_ids
        seen |= page_ids
        cursor = result["next_cursor"]
        conn.rollback()
    assert seen == set(ids)


def test_current_conflict_group_is_all_or_none(history_db):
    conn, *_ = history_db
    chain(conn, 1)
    chain(conn, 1, text_size=4000)
    result = annotations.view(conn, "p", max_bytes=4096)
    assert result["current_count"] == 2 and result["conflicting_current_versions"]
    assert not result["current_group_complete"] and result["coverage"] == "partial"
    assert not any(v["current"] for v in result["versions"])
    assert len(_json(result).encode()) <= 4096


def test_current_candidate_overflow_keeps_count_without_arbitrary_winner(history_db):
    conn, *_ = history_db
    for _ in range(pages.MAX_CURRENT + 1):
        chain(conn, 1)
    result = annotations.view(conn, "p")
    assert result["current_count"] == pages.MAX_CURRENT + 1
    assert result["current_omission_reason"] == "current_candidate_limit"
    assert result["versions"] == [] and result["next_cursor"] is None


def test_full_current_page_continues_without_skipping_history(history_db):
    conn, *_ = history_db
    ids = chain(conn, 2, text_size=1800)
    result = annotations.view(conn, "p", max_bytes=4096)
    assert result["current_group_complete"]
    assert [v["id"] for v in result["versions"]] == [ids[-1]]
    assert result["history_omissions"] == [] and result["next_cursor"]
    conn.rollback()
    continuation = annotations.view(
        conn, "p", max_bytes=4096, cursor=result["next_cursor"]
    )
    assert [v["id"] for v in continuation["versions"]] == [ids[0]]
    assert continuation["next_cursor"] is None


def test_oversized_history_is_disclosed_once_and_cursor_advances(history_db):
    conn, *_ = history_db
    old = chain(conn, 1, text_size=8000)
    chain(conn, 2, previous=old)
    result = annotations.view(conn, "p", max_bytes=4096)
    assert result["history_omissions"] == [
        {"id": old[0], "reason": "report_exceeds_byte_budget"}
    ]
    assert result["next_cursor"] is None and result["coverage"] == "partial"


@pytest.mark.parametrize("change", ["correct", "forget", "reclassify"])
def test_changed_snapshot_refuses_continuation(history_db, change):
    conn, _, _, _ = history_db
    ids = chain(conn, 5)
    cursor = annotations.view(conn, "p", limit=1)["next_cursor"]
    conn.rollback()
    if change == "correct":
        chain(conn, 1, previous=[ids[-1]])
    elif change == "forget":
        ObservationStore(conn).forget(ids[0])
    else:
        for project in ("w", "p"):
            conn.execute(
                "UPDATE context_session_projects SET project_id=? WHERE session_id='p'",
                (project,),
            )
            conn.commit()
    with pytest.raises(ValueError, match="invalid or stale"):
        annotations.view(conn, "p", cursor=cursor)


def test_cursor_is_query_bound_and_anchor_checked(history_db):
    conn, *_ = history_db
    chain(conn, 5)
    cursor = annotations.view(conn, "p", limit=1)["next_cursor"]
    conn.rollback()
    with pytest.raises(ValueError, match="invalid or stale"):
        annotations.view(conn, "p", kind="tags", cursor=cursor)
    conn.rollback()
    value = json.loads(base64.urlsafe_b64decode(cursor))
    value["after"] = ["invented", "anchor"]
    forged = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(ValueError, match="invalid or stale"):
        annotations.view(conn, "p", cursor=forged)


def test_scope_filters_before_selected_payload_validation(history_db, monkeypatch):
    conn, *_ = history_db
    chain(conn, 2)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    with pytest.raises(ScopeError, match="unavailable"):
        annotations.view(conn, "p")


def test_only_selected_bodies_are_validated(history_db, monkeypatch):
    conn, *_ = history_db
    chain(conn, 100)
    checked = []
    original = ObservationStore._checked

    def observe(self, row, *args, **kwargs):
        checked.append(row["id"])
        return original(self, row, *args, **kwargs)

    monkeypatch.setattr(ObservationStore, "_checked", observe)
    result = annotations.view(conn, "p", limit=3)
    assert len(checked) == 4 and len(result["versions"]) == 4
    assert result["version_count"] == 100 and result["coverage"] == "partial"


def test_sql_statement_count_tracks_page_not_history(history_db):
    conn, *_ = history_db
    ids = chain(conn, 100)

    def count():
        counts = Counter()
        conn.set_trace_callback(lambda sql: counts.update([sql.split()[0].upper()]))
        try:
            result = annotations.view(conn, "p", limit=8)
        finally:
            conn.set_trace_callback(None)
            conn.rollback()
        assert result["history_candidates"] == 8
        return counts["SELECT"]

    small = count()
    chain(conn, 900, previous=[ids[-1]])
    large = count()
    assert large <= small + 20 and large < 1000


def test_vm_work_exhaustion_returns_no_partial_context_and_resets_handler(
    history_db, monkeypatch
):
    conn, *_ = history_db
    chain(conn, 100)
    monkeypatch.setattr(pages, "VM_STEPS", 1000)
    with pytest.raises(QueryBudgetExceeded, match="no context returned"):
        annotations.view(conn, "p")
    conn.rollback()
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    with query_budget(conn, steps=1000):
        assert conn.execute("SELECT 1").fetchone()[0] == 1


def test_selected_body_still_requires_valid_immutable_binding(history_db):
    conn, *_ = history_db
    ids = chain(conn, 4)
    conn.execute("DROP TRIGGER context_observations_immutable")
    conn.execute(
        "UPDATE context_observations SET payload=? WHERE id=?",
        ('{"notes":"corrupted"}', ids[-1]),
    )
    conn.commit()
    with pytest.raises(ValueError, match="binding failed"):
        annotations.view(conn, "p", limit=1)


def test_cached_predicate_does_not_bypass_final_response_guard(history_db, monkeypatch):
    from agent_session_tools.context.public import open_context
    from agent_session_tools.context.response import ScopeConflict

    conn, path, *_ = history_db
    chain(conn, 3)
    original = pages.Reader.checked

    def change(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
        return result

    monkeypatch.setattr(pages.Reader, "checked", change)
    with pytest.raises(ScopeConflict), open_context(path) as context:
        annotations.view(context.conn, "p")


def test_large_dependency_set_is_explicitly_unavailable(history_db):
    conn, *_ = history_db
    ids = []
    for _ in range(pages.MAX_LINKS + 1):
        ids.extend(chain(conn, 1))
    chain(conn, 1, previous=ids)
    result = annotations.view(conn, "p", limit=1)
    assert result["current_count"] == 1 and not result["current_group_complete"]
    assert result["current_omission_reason"] == "dependency_limit"
    assert not any(v["current"] for v in result["versions"])


def test_history_index_migration_is_additive_and_recoverable(tmp_path, monkeypatch):
    from agent_session_tools import migrations

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 40)
    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 39)
        conn = records.connect(tmp_path / "upgrade.db")
    conn.execute("INSERT INTO sessions(id,source) VALUES ('original','fixture')")
    conn.commit()
    description, original = migrations.MIGRATIONS[40]

    def fail(database):
        original(database)
        raise RuntimeError("injected index migration failure")

    with monkeypatch.context() as broken:
        broken.setitem(migrations.MIGRATIONS, 40, (description, fail))
        with pytest.raises(RuntimeError, match="injected"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 39
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_observations_ordered'"
    ).fetchone()
    assert len(migrations.migrate(conn)) == 1
    assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "original"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_native_parent_visibility_does_not_bypass_other_dependencies(history_db):
    conn, _, config, settings = history_db
    other_root = config.parent / "other"
    settings["memory"]["projects"]["other"] = {
        "scope": "personal",
        "roots": [str(other_root)],
    }
    config.write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    identity = chain(conn, 1)[0]
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        row = conn.execute(
            "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) VALUES ('a','fixture','b','fixture')"
        )
        owner = records.bind(
            conn, "knowledge_bridges", row.lastrowid, owner_path=other_root
        )
        records.link_observation(conn, owner, identity)
        conn.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES ('p','old shadow')"
        )
    assert annotations.view(conn, "p")["current_count"] == 1
    conn.rollback()
    settings["memory"]["projects"]["other"]["scope"] = "work"
    config.write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    result = annotations.view(conn, "p")
    assert result["current_count"] == 0 and result["versions"] == []
    assert result["legacy"] is None


def test_metadata_size_is_checked_before_loading_report(history_db, monkeypatch):
    conn, *_ = history_db
    ObservationStore(conn).append(
        kind=annotations.KINDS["note"],
        subject="p",
        payload={"notes": "small"},
        producer="large metadata" * 1000,
        authority="reported",
        owner_session_id="p",
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized metadata reached body validation")

    monkeypatch.setattr(ObservationStore, "_checked", forbidden)
    result = annotations.view(conn, "p", max_bytes=4096)
    assert result["current_count"] == 1
    assert result["current_omission_reason"] == "report_exceeds_byte_budget"
    assert not result["current_group_complete"] and result["versions"] == []


@pytest.mark.parametrize("kind", ["note", "tags", "learning"])
def test_legacy_size_is_checked_before_loading_body(history_db, monkeypatch, kind):
    conn, *_ = history_db
    if kind == "note":
        conn.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES ('p',?)", ("x" * 8000,)
        )
    elif kind == "tags":
        conn.execute(
            "INSERT INTO session_tags(session_id,tag) VALUES ('p',?)", ("x" * 8000,)
        )
    else:
        conn.execute(
            "INSERT INTO session_learning_metadata(session_id,notes) VALUES ('p',?)",
            ("x" * 8000,),
        )
    conn.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized legacy report body was loaded")

    monkeypatch.setattr(pages, "_legacy", forbidden)
    result = annotations.view(conn, "p", kind=kind, max_bytes=4096)
    assert result["current_count"] == 1 and result["legacy"] is None
    assert result["legacy_authority"] == "unattributed_report"
    assert result["current_omission_reason"] == "report_exceeds_byte_budget"
    assert result["coverage"] == "partial" and not result["current_group_complete"]


def test_record_dependency_fanout_is_bounded_before_materializing(history_db):
    conn, _, config, _ = history_db
    identity = chain(conn, 1)[0]
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        for _ in range(pages.MAX_LINKS + 1):
            row = conn.execute(
                "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) "
                "VALUES ('a','fixture','b','fixture')"
            )
            owner = records.bind(
                conn, "knowledge_bridges", row.lastrowid, owner_path=config.parent / "p"
            )
            records.link_observation(conn, owner, identity)
    result = annotations.view(conn, "p")
    assert result["current_count"] == 1
    assert result["current_omission_reason"] == "dependency_limit"
    assert not result["current_group_complete"] and result["versions"] == []


def test_policy_digest_change_invalidates_cursor_even_if_parent_stays_visible(
    history_db,
):
    conn, _, config, settings = history_db
    chain(conn, 4)
    cursor = annotations.view(conn, "p", limit=1)["next_cursor"]
    conn.rollback()
    settings["memory"]["projects"]["new"] = {
        "scope": "personal",
        "roots": [str(config.parent / "new")],
    }
    config.write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    with pytest.raises(ValueError, match="invalid or stale"):
        annotations.view(conn, "p", cursor=cursor)
