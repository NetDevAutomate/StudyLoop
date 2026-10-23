"""The full tier is a single-writer mirror bound to one canonical instance.

Before anything is migrated or written, ``sync_to_full`` runs a read-only
preflight: hot and full are different files; hot is on the current schema;
hot holds no structured-replication history; and full is either absent/empty
(the first sync binds it to hot's ``context_access_state.instance``) or already
bound to that instance. A populated full with no binding, or one bound to a
different instance, is refused with :class:`tiering.TieringRefused` -- an
unbound upsert would overwrite another history's AUTOINCREMENT rows silently
(council pass 7 §1.2 step 1, A3; remediation plan 6, lane T unit T2 / R12).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from agent_session_tools import tiering
from agent_session_tools.export_sessions import init_db
from agent_session_tools.tiering_registry import MIRROR_TABLE


@pytest.fixture
def tiered(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hot = config_dir / "sessions.db"
    full_dir = tmp_path / "external" / "DB"
    full_dir.mkdir(parents=True)
    full = full_dir / "sessions_full.db"
    cfg = config_dir / "config.yaml"
    cfg.write_text(
        f"database:\n  path: {hot}\n  backup_dir: {full_dir}\n  full_db_path: {full}\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    conn = init_db(str(hot))
    conn.execute(
        "INSERT INTO sessions(id,source,updated_at) VALUES ('s0','codex','2026-01-01')"
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('m0','s0','user','hi')"
    )
    conn.commit()
    conn.close()
    return {"hot": hot, "full": full, "cfg": cfg}


def _instance(path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT instance FROM context_access_state").fetchone()[0]


def _binding(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            f"SELECT canonical_instance, bound_at FROM {MIRROR_TABLE}"
        ).fetchone()


def test_tiering_refused_is_a_value_error_with_a_reason():
    exc = tiering.TieringRefused("unbound_full", "detail")
    assert isinstance(exc, ValueError)
    assert exc.reason == "unbound_full" and exc.fix


def test_first_sync_binds_full(tiered):
    tiering.sync_to_full()
    canonical, bound_at = _binding(tiered["full"])
    assert canonical == _instance(tiered["hot"])
    assert bound_at
    # The binding is the full tier's own state: hot never carries it.
    with closing(sqlite3.connect(tiered["hot"])) as hot:
        assert not hot.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (MIRROR_TABLE,)
        ).fetchone()
    # A second sync keeps the binding.
    tiering.sync_to_full()
    assert _binding(tiered["full"]) == (canonical, bound_at)


def test_an_empty_migrated_full_is_bound(tiered):
    init_db(str(tiered["full"])).close()
    tiering.sync_to_full()
    assert _binding(tiered["full"])[0] == _instance(tiered["hot"])


def test_populated_unbound_full_is_refused(tiered):
    conn = init_db(str(tiered["full"]))
    conn.execute("INSERT INTO sessions(id,source) VALUES ('other-history','codex')")
    conn.commit()
    conn.close()
    before = tiered["full"].read_bytes()

    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()

    assert info.value.reason == "unbound_full"
    assert tiered["full"].read_bytes() == before, "nothing migrated or written"


def test_full_bound_to_another_instance_is_refused(tiered):
    tiering.sync_to_full()
    with closing(sqlite3.connect(tiered["hot"])) as hot:
        hot.execute("UPDATE context_access_state SET instance='rebuilt-hot'")
        hot.commit()
    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()
    assert info.value.reason == "instance_mismatch"


def test_same_file_is_refused(tiered):
    text = tiered["cfg"].read_text().replace(str(tiered["full"]), str(tiered["hot"]))
    tiered["cfg"].write_text(text)
    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()
    assert info.value.reason == "distinct_paths"


def test_hot_on_an_old_schema_is_refused_before_full_is_created(tiered):
    with closing(sqlite3.connect(tiered["hot"])) as hot:
        hot.execute("PRAGMA user_version=40")
    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()
    assert info.value.reason == "schema_mismatch"
    assert not tiered["full"].exists()


@pytest.mark.parametrize("where", ["hot", "full"])
def test_structured_replication_history_is_refused(tiered, where):
    if where == "full":
        init_db(str(tiered["full"])).close()
    with closing(sqlite3.connect(tiered[where])) as conn:
        conn.execute(
            "INSERT INTO context_replica_peers VALUES ('peer','remote','local','instance','now')"
        )
        conn.commit()
    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()
    assert info.value.reason == "peer_ledger_present"
    assert "context_replica_peers" in str(info.value)


def test_unclassified_context_table_in_hot_is_refused(tiered):
    with closing(sqlite3.connect(tiered["hot"])) as hot:
        hot.execute("CREATE TABLE context_future (id TEXT PRIMARY KEY)")
        hot.commit()
    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()
    assert info.value.reason == "unclassified_table"
    assert info.value.table == "context_future"
    assert not tiered["full"].exists()


def test_override_paths_must_be_the_configured_pair(tiered, tmp_path):
    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full(full=tmp_path / "elsewhere.db")
    assert info.value.reason == "noncanonical_override"


def test_first_sync_of_a_hot_with_permanent_controls_binds(tiered):
    """The controls phase writes hot's tombstones into the still-unbound full
    before the content transaction binds it; that is not 'populated'."""
    from agent_session_tools.context import records
    from agent_session_tools.context.lifecycle import purge_session

    with closing(records.connect(tiered["hot"])) as hot:
        hot.execute("INSERT INTO sessions(id,source) VALUES ('forgotten','codex')")
        hot.commit()
        hot.execute("BEGIN IMMEDIATE")
        purge_session(hot, "forgotten")
        hot.commit()

    stats = tiering.sync_to_full()

    assert stats.bound
    assert _binding(tiered["full"])[0] == _instance(tiered["hot"])
    with closing(sqlite3.connect(tiered["full"])) as full:
        assert full.execute(
            "SELECT count(*) FROM context_tombstones WHERE session_id='forgotten'"
        ).fetchone() == (1,)
        assert full.execute("SELECT id FROM sessions").fetchall() == [("s0",)]


def test_a_rebuilt_hot_cannot_overwrite_autoincrement_rows(tiered):
    """Learner tables use AUTOINCREMENT ids as their upsert key. That is only
    safe because full is bound to one instance: a rebuilt hot restarts the ids
    (``study_notes`` id 1 again) and is refused instead of overwriting."""
    with closing(sqlite3.connect(tiered["hot"])) as hot:
        hot.execute("INSERT INTO study_notes(title, body) VALUES ('original', 'A')")
        hot.commit()
    tiering.sync_to_full()
    tiered["hot"].unlink()
    for suffix in ("-wal", "-shm"):
        tiered["hot"].with_name(tiered["hot"].name + suffix).unlink(missing_ok=True)
    rebuilt = init_db(str(tiered["hot"]))
    rebuilt.execute("INSERT INTO study_notes(title, body) VALUES ('rebuilt', 'B')")
    rebuilt.commit()
    rebuilt.close()

    with pytest.raises(tiering.TieringRefused) as info:
        tiering.sync_to_full()

    assert info.value.reason == "instance_mismatch"
    with closing(sqlite3.connect(tiered["full"])) as full:
        assert full.execute("SELECT id, title, body FROM study_notes").fetchall() == [
            (1, "original", "A")
        ]


def test_a_failed_first_content_phase_does_not_strand_the_full(tiered, monkeypatch):
    """The controls phase commits into full before the copy. If the first copy
    then refuses, the next sync must not read those controls as foreign history."""
    from agent_session_tools.context import records
    from agent_session_tools.context.lifecycle import purge_session

    with closing(records.connect(tiered["hot"])) as hot:
        hot.execute("INSERT INTO sessions(id,source) VALUES ('forgotten','codex')")
        hot.commit()
        hot.execute("BEGIN IMMEDIATE")
        purge_session(hot, "forgotten")
        hot.commit()
    real = tiering._copy_payload

    def refuse_once(*_args, **_kwargs):
        raise tiering.TieringRefused("orphan_row", "simulated first-copy failure")

    monkeypatch.setattr(tiering, "_copy_payload", refuse_once)
    with pytest.raises(tiering.TieringRefused):
        tiering.sync_to_full()
    monkeypatch.setattr(tiering, "_copy_payload", real)

    tiering.sync_to_full()

    assert _binding(tiered["full"])[0] == _instance(tiered["hot"])
    with closing(sqlite3.connect(tiered["full"])) as full:
        assert full.execute("SELECT id FROM sessions").fetchall() == [("s0",)]
