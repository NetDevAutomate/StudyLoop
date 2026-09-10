"""D6: a child ingested before its parent still gets its lineage edge.

Council reproduction D6: ingesting a child whose ``lineage`` named PARENT, then
ingesting PARENT, left ``lineage`` empty forever — the "deferred, lands on
re-ingest" note was data loss, because nothing re-ingests the child.

``lineage_pending`` is written in the child's own transaction and reconciled in the
parent's. Circular pairs fall out for free: each side reconciles the other on
arrival.
"""

from __future__ import annotations

from learning_memory import Event, ParsedSession, Session, Store


def _session(
    session_id: str, lineage: list[str] | None = None, parent: str | None = None
) -> ParsedSession:
    return ParsedSession(
        session=Session(id=session_id, harness="kiro", parent_id=parent),
        events=[Event(turn_id=0, seq=0, kind="user", text=f"work for {session_id}?", actor="user")],
        lineage=lineage or [],
        adapter_version="kiro@1",
    )


def _edges(store: Store) -> set[tuple[str, str]]:
    return {
        (str(row["parent_id"]), str(row["child_id"]))
        for row in store.connection.execute("SELECT parent_id, child_id FROM lineage").fetchall()
    }


def test_child_before_parent_lands_when_the_parent_arrives(store: Store) -> None:
    """The exact D6 probe."""
    child = store.ingest(_session("s-child", lineage=["s-parent"]))
    assert child.lineage_inserted == 0
    assert child.lineage_deferred == ("s-parent",)
    assert store.pending_lineage() == [{"child_id": "s-child", "parent_id": "s-parent"}]

    parent = store.ingest(_session("s-parent"))
    assert parent.lineage_reconciled == 1
    assert _edges(store) == {("s-parent", "s-child")}
    assert store.pending_lineage() == [], "reconciled rows are removed, not left behind"


def test_parent_before_child_lands_immediately(store: Store) -> None:
    store.ingest(_session("s-parent"))
    child = store.ingest(_session("s-child", lineage=["s-parent"]))
    assert child.lineage_inserted == 1
    assert child.lineage_deferred == ()
    assert _edges(store) == {("s-parent", "s-child")}
    assert store.pending_lineage() == []


def test_circular_pending_pair_yields_both_edges(store: Store) -> None:
    """A declares B as parent before B exists; B declares A. Both edges must land."""
    first = store.ingest(_session("s-a", lineage=["s-b"]))
    assert first.lineage_deferred == ("s-b",)

    second = store.ingest(_session("s-b", lineage=["s-a"]))
    assert second.lineage_inserted == 1, "A exists, so B->A's parent edge lands directly"
    assert second.lineage_reconciled == 1, "and A's parked edge on B is reconciled"
    assert _edges(store) == {("s-a", "s-b"), ("s-b", "s-a")}
    assert store.pending_lineage() == []


def test_a_parent_that_never_arrives_stays_pending_and_is_reported(store: Store) -> None:
    result = store.ingest(_session("s-orphan", lineage=["s-ghost", "s-phantom"]))
    assert result.lineage_deferred == ("s-ghost", "s-phantom")
    assert result.lineage_inserted == 0
    assert _edges(store) == set()
    assert store.pending_lineage() == [
        {"child_id": "s-orphan", "parent_id": "s-ghost"},
        {"child_id": "s-orphan", "parent_id": "s-phantom"},
    ]

    # And re-ingesting the child does not multiply the pending rows.
    again = store.ingest(_session("s-orphan", lineage=["s-ghost", "s-phantom"]))
    assert again.lineage_deferred == ("s-ghost", "s-phantom")
    assert store.row_counts()["lineage_pending"] == 2


def test_one_parent_arriving_reconciles_only_its_own_edge(store: Store) -> None:
    store.ingest(_session("s-orphan", lineage=["s-ghost", "s-phantom"]))
    arrived = store.ingest(_session("s-ghost"))
    assert arrived.lineage_reconciled == 1
    assert _edges(store) == {("s-ghost", "s-orphan")}
    assert store.pending_lineage() == [{"child_id": "s-orphan", "parent_id": "s-phantom"}]


def test_session_parent_id_is_treated_as_a_lineage_edge(store: Store) -> None:
    """A declared ``parent_id`` cannot be lost just because it was not also in lineage."""
    child = store.ingest(_session("s-kid", parent="s-mum"))
    assert child.lineage_deferred == ("s-mum",)

    store.ingest(_session("s-mum"))
    assert _edges(store) == {("s-mum", "s-kid")}


def test_parent_id_is_filled_when_the_parent_is_already_present(store: Store) -> None:
    store.ingest(_session("s-mum"))
    store.ingest(_session("s-kid", parent="s-mum"))
    row = store.connection.execute("SELECT parent_id FROM sessions WHERE id = 's-kid'").fetchone()
    assert row["parent_id"] == "s-mum"


def test_a_session_is_not_its_own_parent(store: Store) -> None:
    result = store.ingest(_session("s-self", lineage=["s-self"], parent="s-self"))
    assert result.lineage_inserted == 0
    assert result.lineage_deferred == ()
    assert _edges(store) == set()
    assert store.pending_lineage() == []


def test_reingest_after_reconciliation_changes_nothing(store: Store) -> None:
    store.ingest(_session("s-child", lineage=["s-parent"]))
    store.ingest(_session("s-parent"))
    before = store.row_counts()
    store.ingest(_session("s-child", lineage=["s-parent"]))
    assert store.row_counts() == before
    assert _edges(store) == {("s-parent", "s-child")}
