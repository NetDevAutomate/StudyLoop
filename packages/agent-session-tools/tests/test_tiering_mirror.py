"""``sync_to_full`` mirrors the whole context tier into a bound full database.

Remediation plan 6, lane T unit T4 (council pass 7: C1-C4, A1-A3; RED tests
R2-R9, R11, R14 and the index pin). Every hot database here is built through
the real Codex exporter (``exporters/base.py`` + ``context/capture.py``), so
the rows are the ones a learner's ``session-export`` writes -- evidence per
message, native message sources, capture runs, retention origins -- plus the
assertion/observation/annotation APIs the MCP tools use.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agent_session_tools import tiering
from agent_session_tools import tiering_registry as registry
from agent_session_tools.context import annotations, records
from agent_session_tools.context import managed_history as managed
from agent_session_tools.context.lifecycle import eviction, purge_session
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.provenance import ExecutionState, Scope
from agent_session_tools.context.store import Access, Citation, ContextStore
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import legacy
from agent_session_tools.tiering import TieringRefused, fts_integrity, sync_to_full

OLD = "2020-01-0{}T10:00:00Z"


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hot = config_dir / "sessions.db"
    full_dir = tmp_path / "external" / "DB"
    full_dir.mkdir(parents=True)
    full = full_dir / "sessions_full.db"
    cfg = config_dir / "config.yaml"
    cfg.write_text(
        f"database:\n  path: {hot}\n  backup_dir: {full_dir}\n"
        f"  full_db_path: {full}\n  snapshot_interval_days: 0\n"
        "semantic_search:\n  auto_embed: false\n"
        "memory:\n  default_scope: unclassified\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    archives = tmp_path / "archives"
    archives.mkdir()
    state = {
        "hot": hot,
        "full": full,
        "cfg": cfg,
        "archives": archives,
        "tmp": tmp_path,
    }
    yield state
    conn = state.get("conn")
    if conn is not None:
        conn.close()


def _connect(state) -> sqlite3.Connection:
    if state.get("conn") is None:
        state["conn"] = records.connect(state["hot"])
    return state["conn"]


def export(state, name: str, texts: list[str], day: int = 1) -> str:
    """Write a Codex rollout and run the real exporter over it; the session id."""
    rows = [
        {
            "timestamp": OLD.format(day),
            "type": "session_meta",
            "payload": {"id": name, "cwd": str(state["tmp"] / "proj")},
        }
    ]
    for i, text in enumerate(texts):
        rows.append(
            {
                "timestamp": OLD.format(day),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": [
                        {
                            "type": "input_text" if i % 2 == 0 else "output_text",
                            "text": text,
                        }
                    ],
                },
            }
        )
    (state["archives"] / f"rollout-{name}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    conn = _connect(state)
    stats = CodexExporter(state["archives"]).export_all(conn, incremental=False)
    assert not stats.errors
    return conn.execute(
        "SELECT id FROM sessions WHERE metadata LIKE ?", (f"%rollout-{name}.jsonl%",)
    ).fetchone()[0]


def enrich(state, sid: str, tag: str) -> dict:
    """An assertion with a citation, a sourced observation and a session note."""
    conn = _connect(state)
    source = dict(
        conn.execute(
            "SELECT * FROM context_evidence WHERE session_id=? ORDER BY rowid", (sid,)
        ).fetchone()
    )
    store = ContextStore(conn)
    assertion = store.propose(
        statement=f"ASSERTION_{tag}",
        state=ExecutionState.UNKNOWN,
        target=None,
        generator="fixture",
        citations=[
            Citation(evidence_id=source["id"], start=0, end=4, quote=source["body"][:4])
        ],
        access=Access(scope=Scope.UNCLASSIFIED),
    )
    with store._atomic(), records.policy_guard(conn):
        observation = ObservationStore(conn).append(
            kind="fixture.report",
            subject=f"subject-{tag}",
            payload={"text": f"REPORT_{tag}"},
            producer="fixture",
            authority="model_interpretation",
            evidence_ids=[source["id"]],
        )
        note = annotations.write(conn, sid, "note", {"notes": f"NOTE_{tag}"})
    return {
        "assertion": assertion,
        "observation": observation,
        "note": note,
        "evidence": source["id"],
    }


def rows(path: Path, table: str) -> set[tuple]:
    with closing(sqlite3.connect(path)) as conn:
        cols = registry.columns(conn, table)
        return set(conn.execute(f"SELECT {','.join(cols)} FROM {table}"))


def count(path: Path, sql: str, *args) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql, args).fetchone()[0]


def payload_subset(state) -> dict[str, set]:
    """Every payload row of hot that full lacks (empty when mirrored)."""
    missing = {}
    for entry in registry.PAYLOAD:
        gap = rows(state["hot"], entry.name) - rows(state["full"], entry.name)
        if gap:
            missing[entry.name] = gap
    return missing


def receipt(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            f"SELECT last_source_revision FROM {registry.MIRROR_TABLE}"
        ).fetchone()[0]


def two_sessions(state) -> tuple[str, str]:
    a = export(state, "alpha", ["alpha decorators question", "alpha answer"], day=1)
    b = export(state, "beta", ["beta generators question", "beta answer"], day=2)
    enrich(state, a, "A")
    enrich(state, b, "B")
    return a, b


# ---------------------------------------------------------------------------
# The mirror carries the context tier
# ---------------------------------------------------------------------------


def test_a_real_export_mirrors_every_payload_row(mirror):
    two_sessions(mirror)
    stats = sync_to_full()
    assert stats.sessions_synced == 2
    assert payload_subset(mirror) == {}
    assert count(mirror["full"], "SELECT count(*) FROM context_evidence") >= 4
    with closing(sqlite3.connect(mirror["full"])) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert fts_integrity(conn).healthy
    # Local-only state is never transplanted.
    for table in ("context_capture_runs", "context_retention_origins"):
        assert count(mirror["hot"], f"SELECT count(*) FROM {table}") > 0
        assert count(mirror["full"], f"SELECT count(*) FROM {table}") == 0
    assert receipt(mirror["full"]) == count(
        mirror["hot"], "SELECT revision FROM context_replica_content_state"
    )


def test_repeated_sync_is_zero_write_and_fts_stable(mirror):  # R2
    two_sessions(mirror)
    sync_to_full()
    with closing(sqlite3.connect(mirror["full"])) as conn:
        before = conn.execute("PRAGMA data_version").fetchone()[0]
        again = sync_to_full()
        assert conn.execute("PRAGMA data_version").fetchone()[0] == before
    assert again.sessions_synced == 0 and again.messages_synced == 0
    assert sum(again.rows_copied.values()) == 0
    with closing(sqlite3.connect(mirror["full"])) as conn:
        integrity = fts_integrity(conn)
        assert integrity.healthy
        assert integrity.evidence_fts_rows == integrity.evidence_rows > 0
        for term in ("decorators", "generators"):
            assert (
                conn.execute(
                    "SELECT count(*) FROM context_evidence_fts WHERE "
                    "context_evidence_fts MATCH ?",
                    (term,),
                ).fetchone()[0]
                == 1
            ), term


def test_context_append_syncs_when_session_hash_is_unchanged(mirror):  # R3
    a, _ = two_sessions(mirror)
    sync_to_full()
    before = {e.name: rows(mirror["full"], e.name) for e in registry.PAYLOAD}
    hash_before = count(
        mirror["hot"], "SELECT count(*) FROM sessions WHERE content_hash IS NULL"
    )
    added = enrich(mirror, a, "LATER")

    stats = sync_to_full()

    assert stats.sessions_synced == 0, "no session row or message changed"
    assert (
        count(mirror["hot"], "SELECT count(*) FROM sessions WHERE content_hash IS NULL")
        == hash_before
    )
    assert payload_subset(mirror) == {}
    for key in ("assertion", "observation", "note"):
        assert (
            count(
                mirror["full"],
                "SELECT count(*) FROM context_observations WHERE id=?",
                added[key],
            )
            + count(
                mirror["full"],
                "SELECT count(*) FROM context_assertions WHERE id=?",
                added[key],
            )
            == 1
        ), key
    for name, old in before.items():
        assert old <= rows(mirror["full"], name), f"{name} lost or rewrote a row"


def test_sync_after_eviction_accepts_archive_only_sessions(mirror):  # R4
    a, b = two_sessions(mirror)
    sync_to_full()
    conn = _connect(mirror)
    conn.execute("BEGIN IMMEDIATE")
    with eviction(conn):
        purge_session(conn, a, permanent=False)
    conn.commit()
    added = enrich(mirror, b, "AFTER")

    stats = sync_to_full()

    assert stats.sessions_synced == 0
    assert not count(mirror["hot"], "SELECT count(*) FROM sessions WHERE id=?", a)
    assert count(mirror["full"], "SELECT count(*) FROM sessions WHERE id=?", a) == 1
    assert (
        count(
            mirror["full"],
            "SELECT count(*) FROM context_evidence WHERE session_id=?",
            a,
        )
        > 0
    )
    assert (
        count(
            mirror["full"],
            "SELECT count(*) FROM context_assertions WHERE id=?",
            added["assertion"],
        )
        == 1
    )
    assert payload_subset(mirror) == {}


def test_permanent_forget_reconciles_before_content(mirror):  # R5
    a, b = two_sessions(mirror)
    sync_to_full()
    conn = _connect(mirror)
    conn.execute("BEGIN IMMEDIATE")
    purge_session(conn, a)
    conn.commit()

    sync_to_full()

    # Control identity is the key (managed_history._keys); a dependent
    # tombstone the archive's own cascade wrote first keeps its own timestamp.
    for entry in registry.CONTROL:
        with (
            closing(sqlite3.connect(mirror["hot"])) as h,
            closing(sqlite3.connect(mirror["full"])) as f,
        ):
            sql = f"SELECT {','.join(entry.key)} FROM {entry.name}"
            assert set(h.execute(sql)) == set(f.execute(sql)), entry.name
    assert (
        count(
            mirror["full"],
            "SELECT count(*) FROM context_tombstones WHERE session_id=?",
            a,
        )
        == 1
    )
    for sql in (
        "SELECT count(*) FROM sessions WHERE id=?",
        "SELECT count(*) FROM messages WHERE session_id=?",
        "SELECT count(*) FROM context_evidence WHERE session_id=?",
    ):
        assert count(mirror["full"], sql, a) == 0, sql
    assert count(mirror["full"], "SELECT count(*) FROM sessions WHERE id=?", b) == 1
    # A retry resurrects nothing.
    again = sync_to_full()
    assert sum(again.rows_copied.values()) == 0
    assert count(mirror["full"], "SELECT count(*) FROM sessions WHERE id=?", a) == 0


@pytest.mark.parametrize(
    "reason", ["full_store_unavailable", "managed_store_busy_or_unavailable"]
)
def test_incomplete_reconcile_refuses_before_any_body_write(
    mirror, monkeypatch, reason
):  # R6
    a, _ = two_sessions(mirror)
    sync_to_full()
    enrich(mirror, a, "PENDING")
    before = {e.name: rows(mirror["full"], e.name) for e in registry.PAYLOAD}
    stamp = receipt(mirror["full"])
    monkeypatch.setattr(
        managed,
        "reconcile_full_controls",
        lambda **_: {
            "configured": True,
            "complete": False,
            "controls_stable": False,
            "reason": reason,
        },
    )
    with pytest.raises(TieringRefused) as info:
        sync_to_full()
    assert info.value.reason == reason
    assert {e.name: rows(mirror["full"], e.name) for e in registry.PAYLOAD} == before
    assert receipt(mirror["full"]) == stamp


def test_controls_changed_in_the_gap_refuses(mirror, monkeypatch):  # R6
    a, b = two_sessions(mirror)
    sync_to_full()
    enrich(mirror, b, "PENDING")
    before = {e.name: rows(mirror["full"], e.name) for e in registry.PAYLOAD}
    real = managed.reconcile_full_controls

    def then_forget(**kwargs):
        result = real(**kwargs)
        with closing(records.connect(mirror["hot"])) as other:
            other.execute("BEGIN IMMEDIATE")
            purge_session(other, a)
            other.commit()
        return result

    monkeypatch.setattr(managed, "reconcile_full_controls", then_forget)
    with pytest.raises(TieringRefused) as info:
        sync_to_full()
    assert info.value.reason == "controls_changed"
    assert {e.name: rows(mirror["full"], e.name) for e in registry.PAYLOAD} == before


def test_immutable_collision_refuses_without_replacement(mirror):  # R8
    a, _ = two_sessions(mirror)
    sync_to_full()
    evidence = (
        "INSERT INTO context_evidence VALUES ('collide','k',?,'codex','jsonl','/x','v1',"
        "'m',NULL,'2026-01-01',?,'sha','conversation_message',NULL,NULL,NULL,NULL)"
    )
    with closing(sqlite3.connect(mirror["full"])) as conn:
        conn.execute(evidence, (a, "FULL VERSION"))
        conn.commit()
    conn = _connect(mirror)
    conn.execute(evidence, (a, "HOT VERSION"))
    conn.commit()
    full_rows = rows(mirror["full"], "context_evidence")
    with closing(sqlite3.connect(mirror["full"])) as full:
        fts_before = fts_integrity(full)
    stamp = receipt(mirror["full"])

    with pytest.raises(TieringRefused) as info:
        sync_to_full()

    assert info.value.reason == "immutable_collision"
    assert info.value.table == "context_evidence"
    assert info.value.key == ("collide",)
    assert "context_evidence" in str(info.value) and "collide" in str(info.value)
    assert rows(mirror["full"], "context_evidence") == full_rows
    with closing(sqlite3.connect(mirror["full"])) as full:
        assert fts_integrity(full) == fts_before
    assert receipt(mirror["full"]) == stamp


def test_changed_session_replaces_native_without_touching_evidence(mirror):  # R9
    a = export(mirror, "alpha", ["alpha one", "alpha two", "alpha three"], day=1)
    sync_to_full()
    old_evidence = rows(mirror["full"], "context_evidence")
    # The harness appends a turn; the exporter re-captures the session.
    a2 = export(
        mirror, "alpha", ["alpha one", "alpha two", "alpha three", "alpha four"], day=1
    )
    assert a2 == a
    conn = _connect(mirror)
    # A source compaction drops a captured message (its native link cascades in hot).
    victim = conn.execute(
        "SELECT id FROM messages WHERE session_id=? ORDER BY rowid LIMIT 1", (a,)
    ).fetchone()[0]
    conn.execute("DELETE FROM messages WHERE id=?", (victim,))
    conn.commit()

    sync_to_full()

    assert rows(mirror["full"], "messages") == rows(mirror["hot"], "messages")
    assert old_evidence <= rows(mirror["full"], "context_evidence"), "old evidence kept"
    assert rows(mirror["hot"], "context_evidence") <= rows(
        mirror["full"], "context_evidence"
    )
    native = "SELECT message_id, evidence_id, rendered_body_sha256 FROM context_native_message_sources"
    with (
        closing(sqlite3.connect(mirror["hot"])) as h,
        closing(sqlite3.connect(mirror["full"])) as f,
    ):
        assert set(f.execute(native)) == set(h.execute(native)), "native links restored"
        assert fts_integrity(f).healthy
        assert f.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sessions_upsert_never_cascades_in_full(mirror):  # R11
    a, _ = two_sessions(mirror)
    sync_to_full()
    evidence = {r for r in rows(mirror["full"], "context_evidence") if a in r}
    conn = _connect(mirror)
    conn.execute("UPDATE sessions SET content_hash='changed' WHERE id=?", (a,))
    conn.commit()

    stats = sync_to_full()

    assert stats.sessions_synced == 1
    assert (
        count(
            mirror["full"],
            "SELECT count(*) FROM sessions WHERE id=? AND content_hash='changed'",
            a,
        )
        == 1
    )
    assert {r for r in rows(mirror["full"], "context_evidence") if a in r} == evidence
    assert count(mirror["full"], "SELECT count(*) FROM context_retirements") == 0
    assert payload_subset(mirror) == {}


def test_the_copier_never_replaces():
    source = inspect.getsource(tiering._mirror_copy) + inspect.getsource(
        tiering._upsert_sql
    )
    assert "REPLACE" not in source.upper()


def test_sync_full_fast_path_opens_no_write_txn(mirror):  # R14
    two_sessions(mirror)
    sync_to_full()
    reader = sqlite3.connect(mirror["hot"])
    version = reader.execute("PRAGMA data_version").fetchone()[0]
    # Another writer holds hot's write lock: the fast path must not need it.
    writer = sqlite3.connect(mirror["hot"], timeout=0.1)
    writer.execute("BEGIN IMMEDIATE")
    try:
        stats = sync_to_full()
    finally:
        writer.rollback()
        writer.close()
    assert stats.fast_path is True
    assert stats.sessions_synced == 0 and sum(stats.rows_copied.values()) == 0
    assert stats.sessions_total_full == 2
    assert reader.execute("PRAGMA data_version").fetchone()[0] == version
    reader.close()


def test_fast_path_still_sees_untracked_tables(mirror):
    """``scrub_log``/``message_concepts`` and the concept graph do not advance
    hot's content revision (migration 46), so the receipt alone cannot clear them."""
    a, _ = two_sessions(mirror)
    sync_to_full()
    conn = _connect(mirror)
    conn.execute(
        "INSERT INTO concepts(id,name,domain) VALUES ('c1','decorators','python')"
    )
    message = conn.execute(
        "SELECT id FROM messages WHERE session_id=?", (a,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO message_concepts(message_id,concept_id) VALUES (?,'c1')",
        (message,),
    )
    conn.execute(
        "INSERT INTO scrub_log(session_id,message_id,entity_type,placeholder) VALUES (?,?,'email','<EMAIL>')",
        (a, message),
    )
    conn.commit()
    stats = sync_to_full()
    assert stats.fast_path is False
    assert stats.rows_copied.get("message_concepts") == 1
    assert payload_subset(mirror) == {}


def test_copier_anti_join_uses_an_index(mirror):
    two_sessions(mirror)
    sync_to_full()
    with closing(sqlite3.connect(mirror["full"])) as conn:
        conn.execute("ATTACH DATABASE ? AS hot", (str(mirror["hot"]),))
        for entry in registry.PAYLOAD:
            cols = registry.columns(conn, entry.name)
            for sql in (
                tiering._missing_sql(entry.name, cols, entry.key, keys_only=True),
                tiering._missing_sql(entry.name, cols, entry.key, keys_only=False),
            ):
                plan = " | ".join(
                    r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql)
                )
                inner = [part for part in plan.split(" | ") if " x " in f" {part} "]
                assert inner and all("SEARCH" in p and "USING" in p for p in inner), (
                    entry.name,
                    plan,
                )


# ---------------------------------------------------------------------------
# Peer and legacy paths are untouched (R7)
# ---------------------------------------------------------------------------


def test_peer_legacy_paths_still_refuse_modern_context(mirror):  # R7
    two_sessions(mirror)
    with closing(sqlite3.connect(mirror["hot"])) as conn:
        with pytest.raises(legacy.LegacySyncRefused, match="context_evidence"):
            legacy.check_database(conn)
    mirror["cfg"].write_text(
        mirror["cfg"].read_text()
        + "  sync:\n    node_id: a\n    peers:\n      b:\n        allowed_scopes: [personal]\n"
    )
    with pytest.raises(legacy.LegacySyncRefused):
        sync_to_full()
    assert not mirror["full"].exists()


# ---------------------------------------------------------------------------
# T5 -- prune's archive proof consumes the same registry (R10, contamination)
# ---------------------------------------------------------------------------


def _accepts(state) -> bool:
    with closing(sqlite3.connect(state["hot"])) as probe:
        probe.execute("ATTACH DATABASE ? AS full", (str(state["full"]),))
        return tiering._archive_context_complete(probe)


def test_acceptance_holds_after_a_real_sync(mirror):
    """Instance-local rows every export writes are not required in full."""
    two_sessions(mirror)
    sync_to_full()
    for table in ("context_retention_origins", "context_capture_runs"):
        assert count(mirror["hot"], f"SELECT count(*) FROM {table}") > 0
        assert count(mirror["full"], f"SELECT count(*) FROM {table}") == 0
    assert _accepts(mirror) is True


def test_acceptance_ignores_peer_and_local_only_rows(mirror):
    two_sessions(mirror)
    sync_to_full()
    conn = _connect(mirror)
    conn.execute(
        "INSERT INTO context_scope_audit VALUES ('a','reclassify','s','{}','{}','fixture','d','now')"
    )
    conn.commit()
    assert _accepts(mirror) is True
    conn.execute(
        "INSERT INTO context_replica_peers VALUES ('peer','remote','local','instance','now')"
    )
    conn.commit()
    assert _accepts(mirror) is True, "peer ledgers are never copied, so never required"


def test_unclassified_context_table_fails_closed(mirror):  # R10
    two_sessions(mirror)
    sync_to_full()
    for path in (mirror["hot"], mirror["full"]):
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE context_future (id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO context_future VALUES ('same-in-both')")
            conn.commit()
    assert _accepts(mirror) is False
    with pytest.raises(TieringRefused) as info:
        sync_to_full()
    assert info.value.reason == "unclassified_table"
    assert info.value.table == "context_future"


def test_acceptance_sees_a_mutable_row_changed_after_sync(mirror):
    two_sessions(mirror)
    sync_to_full()
    conn = _connect(mirror)
    conn.execute("INSERT INTO study_notes(title, body) VALUES ('t', 'first')")
    conn.commit()
    assert _accepts(mirror) is False
    sync_to_full()
    assert _accepts(mirror) is True
    conn.execute("UPDATE study_notes SET body='edited'")
    conn.commit()
    assert _accepts(mirror) is False
    sync_to_full()
    assert _accepts(mirror) is True


def test_acceptance_needs_equal_controls(mirror):
    two_sessions(mirror)
    sync_to_full()
    with closing(sqlite3.connect(mirror["full"])) as conn:
        conn.execute(
            "INSERT INTO context_tombstones VALUES ('only-in-full','d-1','2026-01-01')"
        )
        conn.commit()
    assert _accepts(mirror) is False


def plain(state) -> None:
    """A hot with no exporter rows, so nothing else can make the proof false."""
    conn = _connect(state)
    conn.execute(
        "INSERT INTO sessions(id,source,updated_at) VALUES ('p0','codex','2020-01-01')"
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('p0-m','p0','user','hi')"
    )
    conn.commit()


def test_unclassified_context_table_fails_closed_on_its_own(mirror):  # R10
    plain(mirror)
    sync_to_full()
    assert _accepts(mirror) is True
    for path in (mirror["hot"], mirror["full"]):
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE context_future (id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO context_future VALUES ('same-in-both')")
            conn.commit()
    assert _accepts(mirror) is False


def test_acceptance_needs_equal_controls_on_its_own(mirror):
    plain(mirror)
    sync_to_full()
    assert _accepts(mirror) is True
    with closing(sqlite3.connect(mirror["full"])) as conn:
        conn.execute(
            "INSERT INTO context_tombstones VALUES ('only-in-full','d-1','2026-01-01')"
        )
        conn.commit()
    assert _accepts(mirror) is False


# ---------------------------------------------------------------------------
# T8 -- the end-to-end acceptance test for the record (R1; ruling §4 Q6)
# ---------------------------------------------------------------------------


def test_sync_full_then_prune_evicts_a_real_exported_session(mirror):  # R1
    """A current-schema session exported by the real exporter is mirrored, then
    evicted from hot by ``prune_hot`` with its whole closure queryable in full;
    FK and both FTS invariants hold; a repeat sync writes nothing; a permanent
    forget of the archived session never resurrects it."""
    from datetime import UTC, datetime

    from agent_session_tools.context import managed_history
    from agent_session_tools.tiering import prune_hot

    old = export(mirror, "alpha", ["alpha decorators question", "alpha answer"], day=1)
    today = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows_recent = [
        {
            "timestamp": today,
            "type": "session_meta",
            "payload": {"id": "beta", "cwd": "/x"},
        },
        {
            "timestamp": today,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "beta generators today"}],
            },
        },
    ]
    (mirror["archives"] / "rollout-beta.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows_recent)
    )
    conn = _connect(mirror)
    assert (
        not CodexExporter(mirror["archives"]).export_all(conn, incremental=False).errors
    )
    recent = conn.execute(
        "SELECT id FROM sessions WHERE metadata LIKE '%rollout-beta.jsonl%'"
    ).fetchone()[0]
    ids = enrich(mirror, old, "R1")
    # A scope-owned observation (context_observation_owners): an owner row that
    # does not anchor the session to hot.
    store = ContextStore(conn)
    with store._atomic(), records.policy_guard(conn):
        owned = ObservationStore(conn).append(
            kind="fixture.plan",
            subject="r1-owned",
            payload={"text": "OWNED_REPORT"},
            producer="fixture",
            authority="reported",
        )
    for table, column, value in (
        ("context_evidence", "session_id", old),
        ("context_native_message_sources", "evidence_id", ids["evidence"]),
        ("context_citations", "assertion_id", ids["assertion"]),
        ("context_observation_sources", "observation_id", ids["observation"]),
        ("context_observation_session_owners", "session_id", old),
        ("context_observation_owners", "observation_id", owned),
    ):
        assert count(
            mirror["hot"], f"SELECT count(*) FROM {table} WHERE {column}=?", value
        ), table
    before = {e.name: rows(mirror["hot"], e.name) for e in registry.PAYLOAD}
    assert not mirror["full"].exists()

    stats = sync_to_full()

    assert stats.bound and stats.sessions_synced == 2
    assert payload_subset(mirror) == {}
    with closing(sqlite3.connect(mirror["full"])) as full:
        assert full.execute("PRAGMA foreign_key_check").fetchall() == []

    pruned = prune_hot(days=30, dry_run=False)

    assert pruned.sessions_deleted == 1, pruned
    assert pruned.skipped_unverified == 0 and pruned.skipped_anchored == 0
    assert count(mirror["hot"], "SELECT count(*) FROM sessions WHERE id=?", old) == 0
    assert count(mirror["hot"], "SELECT count(*) FROM sessions WHERE id=?", recent) == 1
    assert (
        count(
            mirror["hot"],
            "SELECT count(*) FROM context_evidence WHERE session_id=?",
            old,
        )
        == 0
    )
    # The whole pre-prune closure is queryable in full, row for row.
    for name, hot_rows in before.items():
        assert hot_rows <= rows(mirror["full"], name), name
    with (
        closing(sqlite3.connect(mirror["full"])) as full,
        closing(sqlite3.connect(mirror["hot"])) as hot,
    ):
        assert full.execute("PRAGMA foreign_key_check").fetchall() == []
        assert hot.execute("PRAGMA foreign_key_check").fetchall() == []
        for db in (full, hot):
            integrity = fts_integrity(db)
            assert integrity.healthy, integrity
        assert (
            full.execute(
                "SELECT count(*) FROM context_evidence_fts WHERE context_evidence_fts MATCH 'decorators'"
            ).fetchone()[0]
            == 1
        )

    again = sync_to_full()
    assert sum(again.rows_copied.values()) == 0 and again.sessions_synced == 0

    # A permanent forget of the archive-only session reaches full and sticks.
    assert managed_history.forget_with_history(old, apply=True)["applied"]
    sync_to_full()
    for sql in (
        "SELECT count(*) FROM sessions WHERE id=?",
        "SELECT count(*) FROM messages WHERE session_id=?",
        "SELECT count(*) FROM context_evidence WHERE session_id=?",
    ):
        assert count(mirror["full"], sql, old) == 0, sql
        assert count(mirror["hot"], sql, old) == 0, sql
    resurrect = sync_to_full()
    assert sum(resurrect.rows_copied.values()) == 0
    assert count(mirror["full"], "SELECT count(*) FROM sessions WHERE id=?", old) == 0
    assert (
        count(mirror["full"], "SELECT count(*) FROM sessions WHERE id=?", recent) == 1
    )


def test_a_trigger_that_rolls_back_is_reported_as_a_refusal(mirror):
    """RAISE(ROLLBACK) ends the transaction itself; the refusal must still be a
    TieringRefused, not 'cannot rollback - no transaction is active'."""
    a = export(mirror, "alpha", ["alpha one"], day=1)
    sync_to_full()
    with closing(sqlite3.connect(mirror["full"])) as conn:
        conn.execute(
            "CREATE TRIGGER fixture_veto BEFORE INSERT ON context_evidence "
            "BEGIN SELECT RAISE(ROLLBACK, 'fixture veto'); END"
        )
        conn.commit()
    export(mirror, "alpha", ["alpha one", "alpha two"], day=1)
    before = rows(mirror["full"], "messages")

    with pytest.raises(TieringRefused) as info:
        sync_to_full()

    assert info.value.reason == "constraint_violation"
    assert "fixture veto" in str(info.value)
    assert rows(mirror["full"], "messages") == before
    assert (
        count(mirror["hot"], "SELECT count(*) FROM messages WHERE session_id=?", a) == 2
    )


# --- council pass 8 (coordinator units) -------------------------------------


def _unbind(full: Path) -> None:
    with closing(sqlite3.connect(full)) as conn:
        conn.execute("DELETE FROM tiering_mirror_state")
        conn.commit()


def _rebind_to(full: Path, instance: str) -> None:
    with closing(sqlite3.connect(full)) as conn:
        conn.execute(
            "UPDATE tiering_mirror_state SET canonical_instance=?", (instance,)
        )
        conn.commit()


def test_prune_refuses_a_full_that_is_not_bound_to_this_hot(mirror):
    """Pass 8 (luna B1): ``prune_hot`` deletes from hot on the strength of rows it
    finds in ``full``; it must first prove that full is THIS hot's mirror. A
    full written by someone else, or bound to another instance, can hold the
    same rows (the same learner on two machines exports the same transcripts)
    and is still not this database's archive."""
    from agent_session_tools.tiering import prune_hot

    export(mirror, "alpha", ["alpha decorators question", "alpha answer"], day=1)
    sync_to_full()
    _rebind_to(mirror["full"], "someone-else")
    with pytest.raises(TieringRefused) as info:
        prune_hot(days=0, dry_run=False)
    assert info.value.reason == "instance_mismatch"
    assert count(mirror["hot"], "SELECT COUNT(*) FROM sessions") == 1

    _unbind(mirror["full"])
    with pytest.raises(TieringRefused) as info:
        prune_hot(days=0, dry_run=True)
    assert info.value.reason == "unbound_full"
    assert count(mirror["hot"], "SELECT COUNT(*) FROM sessions") == 1


def test_prune_refuses_an_unclassified_table_by_name(mirror):
    """Pass 8 (sol S6): the docs promise prune refuses like sync-full does; it
    used to log a warning, verify nothing and report every candidate skipped."""
    from agent_session_tools.tiering import prune_hot

    export(mirror, "alpha", ["alpha decorators question", "alpha answer"], day=1)
    sync_to_full()
    for path in (mirror["hot"], mirror["full"]):
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE context_future (id TEXT PRIMARY KEY)")
            conn.commit()
    with pytest.raises(TieringRefused) as info:
        prune_hot(days=0, dry_run=True)
    assert info.value.reason == "unclassified_table"
    assert info.value.table == "context_future"


def test_sync_refuses_an_unclassified_table_that_only_full_has(mirror):
    """Pass 8 (sol S3): fail-closed classification covered hot only; a table in
    the bound full that the registry cannot name (FK-linked to payload or not)
    must refuse before the changed-session deletion can cascade through it."""
    two_sessions(mirror)
    sync_to_full()
    with closing(sqlite3.connect(mirror["full"])) as conn:
        conn.execute("CREATE TABLE context_future (id TEXT PRIMARY KEY)")
        conn.commit()
    with pytest.raises(TieringRefused) as info:
        sync_to_full()
    assert info.value.reason == "unclassified_table"
    assert info.value.table == "context_future"


def test_a_corrupt_full_file_is_a_refusal_not_a_traceback(mirror):
    """Pass 8 (sol S2 / luna M1): an existing full path that is not a SQLite
    database failed at ``PRAGMA user_version`` with a bare ``DatabaseError``."""
    export(mirror, "alpha", ["alpha decorators question"], day=1)
    mirror["full"].write_text("this is not a database\n")
    with pytest.raises(TieringRefused) as info:
        sync_to_full()
    assert info.value.reason == "full_store_unavailable"
    assert (
        "not a database" in str(info.value).lower()
        or "file is not" in str(info.value).lower()
    )
