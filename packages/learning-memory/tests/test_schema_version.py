"""Schema v2 refuses to open a v1 file, by name, instead of migrating it.

Stage B changed shape under the council's findings: per-event evidence, a deferred
citation FK, a VIEW behind the FTS index, position-bearing event hashes. None of that
is reachable from a v1 file by ALTER, and nothing real has been ingested yet, so the
honest move is to refuse and rebuild rather than ship an untested upgrade path.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from learning_memory import SCHEMA_VERSION, Event, ParsedSession, SchemaError, Session, Store

if TYPE_CHECKING:
    from pathlib import Path


def _write_v1_marker(path: Path) -> None:
    """A file that looks like the Stage B store to ``install()``: v1 in schema_version."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY,"
            " tokenizer TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_version(version, tokenizer, applied_at)"
            " VALUES (1, 'porter unicode61', '2026-09-10T00:00:00+00:00')"
        )
    finally:
        conn.close()


def test_schema_version_is_two() -> None:
    assert SCHEMA_VERSION == 2


def test_install_refuses_an_older_store_and_names_both_versions(tmp_path: Path) -> None:
    _write_v1_marker(tmp_path / "old.db")
    store = Store.connect(tmp_path / "old.db")
    try:
        with pytest.raises(SchemaError) as err:
            store.install()
    finally:
        store.close()
    message = str(err.value)
    assert "v1" in message, "the version found must be named"
    assert "v2" in message, "the version this code writes must be named"
    assert "no migration" in message


def test_install_is_idempotent_on_a_current_store(tmp_path: Path) -> None:
    path = tmp_path / "current.db"
    first = Store.connect(path)
    first.install()
    first.ingest(
        ParsedSession(
            session=Session(id="s-1", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user")],
            adapter_version="kiro@1",
        )
    )
    first.close()

    second = Store.connect(path)
    try:
        second.install()  # must not raise, and must not wipe anything
        assert second.row_counts()["events"] == 1
        row = second.connection.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION
    finally:
        second.close()


def test_install_refuses_an_empty_schema_version_table(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY,"
        " tokenizer TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.close()

    store = Store.connect(path)
    try:
        with pytest.raises(SchemaError, match="empty"):
            store.install()
    finally:
        store.close()


def test_the_v1_1_tables_exist(store: Store) -> None:
    """The tables-only half of Stage B.1: shape now, derivation logic in Stage D."""
    names = set(store.row_counts())
    assert {
        "claim_citations",
        "claim_relations",
        "claims",
        "concept_aliases",
        "concept_occurrences",
        "concept_tags",
        "concepts",
        "evidence",
        "events",
        "exchanges",
        "lineage",
        "lineage_pending",
        "review_items",
        "schema_version",
        "sessions",
    } <= names
    assert "recurrence" not in names, "replaced by concepts + concept_occurrences (finding 10)"


def test_exchanges_are_unique_per_derivation_version(store: Store) -> None:
    """The UNIQUE that survives a renumbering (council finding 8)."""
    store.ingest(
        ParsedSession(
            session=Session(id="s-1", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user")],
            adapter_version="kiro@1",
        )
    )
    insert = (
        "INSERT INTO exchanges(session_id, derivation_version, turn_id, is_question)"
        " VALUES ('s-1', ?, 0, 1)"
    )
    store.connection.execute(insert, ("derive@1",))
    store.connection.execute(insert, ("derive@2",))  # same turn, new version: allowed
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(insert, ("derive@1",))  # same version and turn: refused
    assert store.row_counts()["exchanges"] == 2


def test_exchanges_require_a_derivation_version(store: Store) -> None:
    store.ingest(
        ParsedSession(
            session=Session(id="s-1", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user")],
            adapter_version="kiro@1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "INSERT INTO exchanges(session_id, turn_id, is_question) VALUES ('s-1', 0, 1)"
        )


def test_concept_tags_point_at_canonical_concepts(store: Store) -> None:
    """No free-text concept column: a tag names a concept id (council finding 10)."""
    store.connection.execute("INSERT INTO concepts(id, canonical) VALUES ('c-1', 'spark')")
    store.connection.execute(
        "INSERT INTO concept_aliases(alias, concept_id) VALUES ('pyspark', 'c-1')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.connection.execute(
            "INSERT INTO concept_aliases(alias, concept_id) VALUES ('dangling', 'c-missing')"
        )
    columns = {
        str(row["name"])
        for row in store.connection.execute("PRAGMA table_info(concept_tags)").fetchall()
    }
    assert "concept_id" in columns
    assert "concept" not in columns
