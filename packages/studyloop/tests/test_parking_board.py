"""Tests for the parking-lot Kanban board layer (parking.py, v26).

The fixture deliberately builds a **pre-v26** ``parked_topics`` table so every
test also exercises ``_ensure_board_schema``'s drift recovery — the same
self-healing path the v14-v17 fallback exists for. If board columns were only
ever created by the migration, a user on a drifted DB would hit
``no such column: board_column`` on their first board load.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def board_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp DB with a LEGACY (pre-v26) parked_topics table."""
    db_path = tmp_path / "board.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE study_sessions (id TEXT PRIMARY KEY, started_at TEXT)")
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute("""
        CREATE TABLE parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            topic_tag TEXT,
            question TEXT NOT NULL,
            context TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
            scheduled_for TEXT,
            resolved_at TEXT,
            parked_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT DEFAULT 'agent',
            source TEXT NOT NULL DEFAULT 'parked'
                CHECK(source IN ('parked', 'struggled', 'manual')),
            tech_area TEXT,
            priority INTEGER
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr("studyloop.parking.get_db_path", lambda: db_path)
    return db_path


def _park(question: str, **kw) -> int:
    from studyloop.parking import park_topic

    row_id = park_topic(question, **kw)
    assert row_id is not None
    return row_id


# ---------------------------------------------------------------------------
# Schema self-healing + default board
# ---------------------------------------------------------------------------


def test_legacy_schema_is_healed_with_board_columns(board_db: Path) -> None:
    """A pre-v26 table gains notes/board_column/board_order/updated_at."""
    from studyloop.parking import get_board_columns

    get_board_columns()  # triggers _connect → _ensure_board_schema
    conn = sqlite3.connect(str(board_db))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(parked_topics)")}
    conn.close()
    assert {"notes", "board_column", "board_order", "updated_at"} <= cols


def test_default_board_columns_seeded(board_db: Path) -> None:
    """A fresh board is never column-less — defaults are seeded on read."""
    from studyloop.parking import get_board_columns

    keys = [c["key"] for c in get_board_columns()]
    assert keys == ["inbox", "next", "exploring", "done"]


def test_concurrent_first_reads_prepare_one_fresh_database(board_db: Path) -> None:
    """The first browser requests must not race SQLite WAL/schema setup."""
    from studyloop.parking import get_board

    with ThreadPoolExecutor(max_workers=4) as pool:
        boards = list(pool.map(lambda _: get_board(), range(4)))

    assert all(
        [column["key"] for column in board["columns"]]
        == [
            "inbox",
            "next",
            "exploring",
            "done",
        ]
        for board in boards
    )


def test_get_board_groups_items_by_column(board_db: Path) -> None:
    from studyloop.parking import get_board, move_parked_topic

    a = _park("A")
    b = _park("B")
    move_parked_topic(b, "next")

    board = get_board()
    by_key = {c["key"]: c for c in board["columns"]}
    assert [i["id"] for i in by_key["inbox"]["items"]] == [a]
    assert [i["id"] for i in by_key["next"]["items"]] == [b]
    assert board["total"] == 2


def test_board_surfaces_orphaned_column_items_in_first_column(board_db: Path) -> None:
    """An item pointing at a deleted column must not vanish from the board."""
    from studyloop.parking import get_board

    item = _park("Orphan")
    conn = sqlite3.connect(str(board_db))
    conn.execute("UPDATE parked_topics SET board_column = 'ghost' WHERE id = ?", (item,))
    conn.commit()
    conn.close()

    board = get_board()
    first = board["columns"][0]
    assert item in [i["id"] for i in first["items"]]
    assert board["total"] == 1


# ---------------------------------------------------------------------------
# In-place editing
# ---------------------------------------------------------------------------


def test_update_edits_question_and_notes(board_db: Path) -> None:
    from studyloop.parking import update_parked_topic

    item = _park("terse")
    updated = update_parked_topic(
        item,
        question="Why does MVCC avoid read locks?",
        notes="## Why\n\nBecause readers see a snapshot.",
    )
    assert updated is not None
    assert updated["question"] == "Why does MVCC avoid read locks?"
    assert updated["notes"].startswith("## Why")
    assert updated["updated_at"]


def test_update_normalises_notes_to_clean_markdown(board_db: Path) -> None:
    """Whatever the client sends, the DB holds clean Markdown."""
    from studyloop.parking import update_parked_topic

    item = _park("x")
    updated = update_parked_topic(item, notes="# T\r\n\r\n\r\nbody   \n\n\n")
    assert updated is not None
    assert updated["notes"] == "# T\n\nbody\n"


def test_update_closes_unterminated_diagram_fence(board_db: Path) -> None:
    from studyloop.parking import update_parked_topic

    item = _park("x")
    updated = update_parked_topic(item, notes="```mermaid\ngraph TD\n A-->B")
    assert updated is not None
    assert updated["notes"].count("```") == 2


def test_update_rejects_non_editable_field(board_db: Path) -> None:
    """A typo'd/forbidden field must fail loudly, not silently no-op."""
    from studyloop.parking import update_parked_topic

    item = _park("x")
    with pytest.raises(ValueError, match="Not editable"):
        update_parked_topic(item, status="resolved")


def test_update_rejects_empty_question(board_db: Path) -> None:
    from studyloop.parking import update_parked_topic

    item = _park("x")
    with pytest.raises(ValueError, match="question cannot be empty"):
        update_parked_topic(item, question="   ")


def test_update_clamps_priority(board_db: Path) -> None:
    from studyloop.parking import update_parked_topic

    item = _park("x")
    high = update_parked_topic(item, priority=99)
    low = update_parked_topic(item, priority=-4)
    assert high is not None
    assert low is not None
    assert high["priority"] == 5
    assert low["priority"] == 1


def test_update_missing_item_returns_none(board_db: Path) -> None:
    from studyloop.parking import update_parked_topic

    assert update_parked_topic(9999, notes="x") is None


def test_park_topic_accepts_notes_and_column(board_db: Path) -> None:
    from studyloop.parking import get_board

    item = _park("With notes", notes="a\r\n\r\n\r\nb", board_column="next", source="manual")
    board = get_board()
    by_key = {c["key"]: c for c in board["columns"]}
    stored = next(i for i in by_key["next"]["items"] if i["id"] == item)
    assert stored["notes"] == "a\n\nb\n"


# ---------------------------------------------------------------------------
# Moving cards (Kanban)
# ---------------------------------------------------------------------------


def test_move_places_item_at_position(board_db: Path) -> None:
    from studyloop.parking import get_board, move_parked_topic

    a, b, c = _park("A"), _park("B"), _park("C")
    for item in (a, b, c):
        move_parked_topic(item, "next")
    # Insert A at the front of `next`.
    assert move_parked_topic(a, "next", 0)

    board = get_board()
    order = [i["id"] for i in next(x for x in board["columns"] if x["key"] == "next")["items"]]
    assert order[0] == a
    assert set(order) == {a, b, c}


def test_move_appends_when_position_omitted(board_db: Path) -> None:
    from studyloop.parking import get_board, move_parked_topic

    a, b = _park("A"), _park("B")
    move_parked_topic(a, "done")
    move_parked_topic(b, "done")
    board = get_board()
    order = [i["id"] for i in next(x for x in board["columns"] if x["key"] == "done")["items"]]
    assert order == [a, b]


def test_move_to_unknown_column_is_rejected(board_db: Path) -> None:
    from studyloop.parking import move_parked_topic

    assert move_parked_topic(_park("A"), "nope") is False


def test_move_unknown_item_is_rejected(board_db: Path) -> None:
    from studyloop.parking import move_parked_topic

    assert move_parked_topic(4242, "next") is False


def test_board_order_is_dense_after_move(board_db: Path) -> None:
    """Ordering renormalises — no drifting gaps to reason about later."""
    from studyloop.parking import move_parked_topic

    items = [_park(f"T{i}") for i in range(4)]
    for item in items:
        move_parked_topic(item, "exploring")
    move_parked_topic(items[3], "exploring", 0)

    conn = sqlite3.connect(str(board_db))
    orders = [
        r[0]
        for r in conn.execute(
            "SELECT board_order FROM parked_topics WHERE board_column='exploring' "
            "ORDER BY board_order"
        )
    ]
    conn.close()
    assert orders == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Concurrency — the board-order read-modify-write must serialise
# ---------------------------------------------------------------------------


def test_concurrent_parks_to_one_column_keep_distinct_dense_order(board_db: Path) -> None:
    """Parking many cards into one column at once must not collide on order.

    ``park_topic`` reads ``MAX(board_order)+1`` then inserts. Without holding
    the write lock across both statements, two concurrent parkers read the same
    MAX and write the same ``board_order`` — a lost update that leaves two cards
    sharing a slot. A single ``BEGIN IMMEDIATE`` transaction serialises them, so
    the resulting orders stay a dense, collision-free ``0..n-1``.
    """
    from studyloop.parking import park_topic

    n = 12
    with ThreadPoolExecutor(max_workers=n) as pool:
        ids = list(pool.map(lambda i: park_topic(f"card-{i}", board_column="inbox"), range(n)))

    assert all(i is not None for i in ids), "every concurrent park should succeed"

    conn = sqlite3.connect(str(board_db))
    orders = [
        r[0]
        for r in conn.execute(
            "SELECT board_order FROM parked_topics "
            "WHERE board_column = 'inbox' AND status = 'pending' ORDER BY board_order"
        )
    ]
    conn.close()

    assert len(orders) == n
    assert len(set(orders)) == n, f"duplicate board_order (lost update): {orders}"
    assert orders == list(range(n)), f"ordering is not dense 0..n-1: {orders}"


# ---------------------------------------------------------------------------
# Clearing — single / subset / all, soft and hard
# ---------------------------------------------------------------------------


def test_clear_single_item(board_db: Path) -> None:
    from studyloop.parking import clear_parked_topics, get_board

    a, b = _park("A"), _park("B")
    assert clear_parked_topics([a]) == 1
    remaining = [i["id"] for c in get_board()["columns"] for i in c["items"]]
    assert remaining == [b]


def test_clear_arbitrary_user_selected_subset(board_db: Path) -> None:
    """Selection is user-driven: any subset, not a fixed rule."""
    from studyloop.parking import clear_parked_topics, get_board

    ids = [_park(f"T{i}") for i in range(5)]
    chosen = [ids[0], ids[3], ids[4]]
    assert clear_parked_topics(chosen) == 3
    remaining = {i["id"] for c in get_board()["columns"] for i in c["items"]}
    assert remaining == {ids[1], ids[2]}


def test_clear_all(board_db: Path) -> None:
    from studyloop.parking import clear_all_parked_topics, get_board

    for i in range(4):
        _park(f"T{i}")
    assert clear_all_parked_topics() == 4
    assert get_board()["total"] == 0


def test_clear_empty_selection_is_a_noop(board_db: Path) -> None:
    from studyloop.parking import clear_parked_topics

    assert clear_parked_topics([]) == 0


def test_soft_clear_keeps_the_row_and_is_restorable(board_db: Path) -> None:
    """The whole point of soft clear: an accidental clear is recoverable."""
    from studyloop.parking import clear_parked_topics, get_board, restore_parked_topic

    item = _park("Precious thought", notes="# keep me\n")
    clear_parked_topics([item])
    assert get_board()["total"] == 0

    assert restore_parked_topic(item) is True
    board = get_board()
    assert board["total"] == 1
    restored = next(i for c in board["columns"] for i in c["items"])
    assert restored["question"] == "Precious thought"
    assert restored["notes"] == "# keep me\n"


def test_hard_clear_deletes_the_row(board_db: Path) -> None:
    from studyloop.parking import clear_parked_topics

    item = _park("Gone")
    assert clear_parked_topics([item], hard=True) == 1
    conn = sqlite3.connect(str(board_db))
    count = conn.execute("SELECT COUNT(*) FROM parked_topics WHERE id = ?", (item,)).fetchone()[0]
    conn.close()
    assert count == 0


def test_hard_clear_all_empties_the_table(board_db: Path) -> None:
    from studyloop.parking import clear_all_parked_topics

    for i in range(3):
        _park(f"T{i}")
    assert clear_all_parked_topics(hard=True) == 3
    conn = sqlite3.connect(str(board_db))
    assert conn.execute("SELECT COUNT(*) FROM parked_topics").fetchone()[0] == 0
    conn.close()


def test_restore_only_applies_to_dismissed(board_db: Path) -> None:
    from studyloop.parking import restore_parked_topic

    assert restore_parked_topic(_park("Still pending")) is False


# ---------------------------------------------------------------------------
# User-editable columns
# ---------------------------------------------------------------------------


def test_add_column(board_db: Path) -> None:
    from studyloop.parking import add_board_column, get_board_columns

    created = add_board_column("Deep Dive")
    assert created is not None
    assert created["key"] == "deep-dive"
    assert [c["key"] for c in get_board_columns()][-1] == "deep-dive"


def test_add_column_dedupes_key_clash(board_db: Path) -> None:
    from studyloop.parking import add_board_column

    add_board_column("Inbox")  # clashes with the seeded 'inbox'
    second = add_board_column("Inbox")
    assert second is not None
    assert second["key"] == "inbox-3"


def test_add_column_rejects_blank_name(board_db: Path) -> None:
    from studyloop.parking import add_board_column

    assert add_board_column("   ") is None


def test_rename_column_keeps_key_and_items(board_db: Path) -> None:
    from studyloop.parking import get_board, rename_board_column

    item = _park("A")
    assert rename_board_column("inbox", "Brain Dump") is True
    board = get_board()
    first = board["columns"][0]
    assert first["key"] == "inbox"
    assert first["name"] == "Brain Dump"
    assert [i["id"] for i in first["items"]] == [item]


def test_delete_column_relocates_items_never_deletes_them(board_db: Path) -> None:
    """Deleting a column must not delete the user's thoughts."""
    from studyloop.parking import delete_board_column, get_board, move_parked_topic

    item = _park("Survivor")
    move_parked_topic(item, "exploring")
    assert delete_board_column("exploring", move_items_to="done") is True

    board = get_board()
    assert "exploring" not in [c["key"] for c in board["columns"]]
    done = next(c for c in board["columns"] if c["key"] == "done")
    assert [i["question"] for i in done["items"]] == ["Survivor"]
    assert board["total"] == 1


def test_delete_column_falls_back_to_first_column(board_db: Path) -> None:
    from studyloop.parking import delete_board_column, get_board, move_parked_topic

    item = _park("A")
    move_parked_topic(item, "done")
    delete_board_column("done")  # no explicit target
    board = get_board()
    assert item in [i["id"] for i in board["columns"][0]["items"]]


def test_cannot_delete_the_last_column(board_db: Path) -> None:
    """A board with zero columns is unusable — refuse."""
    from studyloop.parking import delete_board_column, get_board_columns

    for key in ("next", "exploring", "done"):
        delete_board_column(key)
    assert [c["key"] for c in get_board_columns()] == ["inbox"]
    assert delete_board_column("inbox") is False


def test_reorder_columns(board_db: Path) -> None:
    from studyloop.parking import get_board_columns, reorder_board_columns

    assert reorder_board_columns(["done", "exploring", "next", "inbox"]) is True
    assert [c["key"] for c in get_board_columns()] == ["done", "exploring", "next", "inbox"]


def test_reorder_rejects_empty(board_db: Path) -> None:
    from studyloop.parking import reorder_board_columns

    assert reorder_board_columns([]) is False


# ---------------------------------------------------------------------------
# Board-column concurrency — add / delete / reorder are read-modify-write
# ---------------------------------------------------------------------------


def _column_rows(board_db: Path) -> list[tuple[str, int]]:
    """(key, position) for every column, ordered by position."""
    conn = sqlite3.connect(str(board_db))
    try:
        return [
            (r[0], r[1])
            for r in conn.execute("SELECT key, position FROM board_columns ORDER BY position")
        ]
    finally:
        conn.close()


def test_concurrent_same_name_adds_all_get_distinct_keys(board_db: Path) -> None:
    """Adding the same column name at once must de-duplicate, not raise.

    ``add_board_column`` reads every existing key, picks the first free
    ``slug``/``slug-2``/``slug-3``, then inserts. The read and the insert are two
    statements on a deferred transaction, so concurrent callers see the same key
    set, choose the SAME key, and one hits the ``key TEXT PRIMARY KEY``
    constraint with an unhandled IntegrityError -- a 500 to the user, from a
    button that should always work.
    """
    from studyloop.parking import add_board_column, get_board_columns

    get_board_columns()  # warm up: schema prep must not absorb the race window
    n = 8
    gate = threading.Barrier(n)

    def add() -> dict | None:
        gate.wait()
        return add_board_column("Research")

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = [f.result() for f in [pool.submit(add) for _ in range(n)]]

    assert all(r is not None for r in results), (
        f"every concurrent add should succeed, got {results.count(None)} failures"
    )
    keys = [r["key"] for r in results]
    assert len(set(keys)) == n, f"duplicate keys handed out: {sorted(keys)}"


def test_concurrent_distinct_name_adds_get_dense_unique_positions(board_db: Path) -> None:
    """Concurrent adds of different names must not land on the same position.

    ``position`` is ``MAX(position)+1`` read in its own statement, and the column
    has no UNIQUE constraint -- so a lost update here is SILENT. Two columns
    sharing a position give an order that depends on SQLite's row order rather
    than on what the user arranged.
    """
    from studyloop.parking import add_board_column, get_board_columns

    before = len(get_board_columns())
    n = 8
    gate = threading.Barrier(n)

    def add(i: int) -> dict | None:
        gate.wait()
        return add_board_column(f"Topic {i}")

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = [f.result() for f in [pool.submit(add, i) for i in range(n)]]

    assert all(r is not None for r in results)
    rows = _column_rows(board_db)
    positions = [p for _, p in rows]
    assert len(rows) == before + n
    assert len(set(positions)) == len(positions), f"duplicate positions: {rows}"
    assert positions == list(range(len(rows))), f"positions not dense 0..n-1: {rows}"


def test_concurrent_reorder_and_delete_leave_a_coherent_board(board_db: Path) -> None:
    """Reorder and delete both rewrite every position from a snapshot they read.

    ``reorder_board_columns`` reads the current order then writes each position;
    ``delete_board_column`` reads all keys, relocates the doomed column's cards
    to a target chosen from that snapshot, then renumbers the survivors. Run at
    once on a deferred transaction they interleave into an arrangement neither
    caller asked for, and a card can be relocated INTO the column the other
    caller is deleting -- which strands it under a key no column owns.

    Asserts the invariants rather than one winning order: positions dense and
    unique, and every card sitting under a key that still exists.
    """
    from studyloop.parking import add_board_column, delete_board_column, reorder_board_columns

    for name in ("Alpha", "Beta"):
        assert add_board_column(name) is not None
    _park("card in alpha", board_column="alpha")
    _park("card in beta", board_column="beta")

    gate = threading.Barrier(2)

    def reorder() -> bool:
        gate.wait()
        return reorder_board_columns(["done", "exploring", "next", "inbox"])

    def delete() -> bool:
        gate.wait()
        return delete_board_column("alpha")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reorder), pool.submit(delete)]
        [f.result() for f in futures]

    rows = _column_rows(board_db)
    positions = [p for _, p in rows]
    assert len(set(positions)) == len(positions), f"duplicate positions: {rows}"
    assert positions == list(range(len(rows))), f"positions not dense 0..n-1: {rows}"

    live_keys = {k for k, _ in rows}
    conn = sqlite3.connect(str(board_db))
    try:
        stored = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT board_column FROM parked_topics WHERE status = 'pending'"
            )
        }
    finally:
        conn.close()
    assert stored <= live_keys, f"cards stranded under deleted columns: {stored - live_keys}"
