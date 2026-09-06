"""Unit coverage for `context.withdrawal_gate` read predicates.

Every context read path filters through these predicates, so the identifier
validation and the pending-versus-released denial semantics are pinned here
directly rather than only via the coordinator tests.
"""

import sqlite3

import pytest

from agent_session_tools.context.withdrawal_gate import available, predicate


@pytest.fixture
def plain_db():
    """A connection with no replication schema installed."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_available_false_without_denials_table(plain_db):
    assert available(plain_db) is False


def test_available_true_after_migrations(migrated_db):
    conn, _ = migrated_db
    assert available(conn) is True


def test_available_rejects_injectable_schema_name(plain_db):
    with pytest.raises(ValueError):
        available(plain_db, schema="main; DROP TABLE x--")


def test_predicate_rejects_unknown_kind(migrated_db):
    conn, _ = migrated_db
    with pytest.raises(ValueError):
        predicate(conn, "tombstone", "s.id")


def test_predicate_rejects_malformed_column(migrated_db):
    conn, _ = migrated_db
    for column in ("id", "s.id; --", "s.id OR 1=1"):
        with pytest.raises(ValueError):
            predicate(conn, "session", column)


def test_predicate_is_open_when_gate_absent(plain_db):
    assert predicate(plain_db, "session", "s.id") == "1"


def test_predicate_filters_pending_but_not_released_denials(migrated_db):
    conn, _ = migrated_db
    conn.execute(
        "INSERT INTO sessions(id,source) VALUES ('kept','fixture'),('denied','fixture')"
    )
    conn.execute(
        "INSERT INTO context_replica_peers(peer,instance,local_node,local_instance,first_seen)"
        " VALUES ('peer1','inst1','node0','inst0','2026-09-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO context_replica_denials(peer,scope,kind,object_id,generation,status)"
        " VALUES ('peer1','personal','session','denied',1,'withdrawn')"
    )
    conn.execute(
        "INSERT INTO context_replica_denials(peer,scope,kind,object_id,generation,status)"
        " VALUES ('peer1','personal','session','kept',1,'released')"
    )
    conn.commit()

    clause = predicate(conn, "session", "s.id")
    visible = {
        row[0] for row in conn.execute(f"SELECT s.id FROM sessions s WHERE {clause}")
    }
    assert visible == {"kept"}
