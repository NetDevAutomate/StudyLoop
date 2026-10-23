"""The tier-mirror table registry classifies every migrated table exactly once.

``sync_to_full`` copies by the registry and ``_archive_context_complete`` (the
proof ``prune_hot`` relies on) checks by it, so a table the registry does not
know must never be silently copied, silently required, or silently dropped
(council pass 7, C2; remediation plan 6, lane T unit T1).
"""

from __future__ import annotations

import sqlite3
from collections import Counter

import pytest

from agent_session_tools import tiering_registry as registry
from agent_session_tools.export_sessions import init_db


@pytest.fixture
def migrated(tmp_path):
    conn = init_db(str(tmp_path / "sessions.db"))
    yield conn
    conn.close()


def test_every_migrated_table_is_classified_exactly_once(migrated):
    tables = registry.database_tables(migrated)
    assert tables, "a migrated database has tables"
    unknown = [t for t in tables if t not in registry.REGISTRY]
    assert unknown == [], f"unclassified tables in a migrated database: {unknown}"
    every_entry = [
        entry.name
        for group in (
            registry.PAYLOAD,
            registry.CONTROL,
            registry.LOCAL_ONLY,
            registry.PEER_LEDGER,
            registry.DERIVED,
        )
        for entry in group
    ]
    twice = [name for name, n in Counter(every_entry).items() if n > 1]
    assert twice == [], f"tables classified more than once: {twice}"
    # No stale registrations: every name except the mirror's own table (which
    # the copier creates in the full tier only) exists after migration.
    stale = set(registry.REGISTRY) - set(tables) - {registry.MIRROR_TABLE}
    assert stale == set(), f"registered tables no migration creates: {stale}"
    registered, unmanaged = registry.classify_database(migrated)
    assert set(registered) == set(tables) and unmanaged == []


def test_registered_keys_are_the_declared_primary_keys(migrated):
    for entry in registry.REGISTRY.values():
        if entry.role is registry.Role.DERIVED or entry.name == registry.MIRROR_TABLE:
            continue
        assert registry.primary_key(migrated, entry.name) == entry.key, entry.name


def test_copy_order_puts_every_payload_parent_first(migrated):
    order = {entry.name: entry.order for entry in registry.PAYLOAD}
    assert sorted(order.values()) == list(range(1, len(order) + 1))
    for entry in registry.PAYLOAD:
        for fk in migrated.execute(f"PRAGMA foreign_key_list({entry.name})"):
            parent = fk[2]
            assert parent in registry.REGISTRY, (entry.name, parent)
            if parent in order:
                assert order[parent] < entry.order, (entry.name, parent)
            else:
                # A payload row may only point at another payload row.
                pytest.fail(f"{entry.name} references non-payload {parent}")


def test_unknown_context_table_raises_naming_it(migrated):
    with pytest.raises(registry.UnclassifiedTable, match="context_future"):
        registry.classify("context_future")
    migrated.execute("CREATE TABLE context_future (id TEXT PRIMARY KEY)")
    with pytest.raises(registry.UnclassifiedTable, match="context_future") as info:
        registry.classify_database(migrated)
    assert info.value.table == "context_future"


def test_unknown_table_referencing_payload_fails_closed(migrated):
    migrated.execute(
        "CREATE TABLE later_payload (id TEXT PRIMARY KEY, "
        "session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE)"
    )
    with pytest.raises(registry.UnclassifiedTable, match="later_payload.*sessions"):
        registry.classify_database(migrated)


def test_application_table_beside_the_schema_is_unmanaged(migrated):
    """StudyLoop keeps tables such as ``card_reviews`` in sessions.db."""
    migrated.execute("CREATE TABLE card_reviews (id INTEGER PRIMARY KEY, card TEXT)")
    registered, unmanaged = registry.classify_database(migrated)
    assert unmanaged == ["card_reviews"]
    assert "card_reviews" not in registered


def test_generated_columns_are_not_insertable_columns(migrated):
    columns = registry.columns(migrated, "teach_back_scores")
    assert "total_score" not in columns and "score_accuracy" in columns


def test_classify_works_on_an_attached_schema(tmp_path, migrated):
    other = sqlite3.connect(":memory:")
    other.execute("ATTACH DATABASE ? AS hot", (str(tmp_path / "sessions.db"),))
    registered, _ = registry.classify_database(other, "hot")
    assert "context_evidence" in registered
    other.close()
