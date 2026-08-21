"""Tests for the /api/parking/* board API.

These run against a REAL temp SQLite DB rather than monkeypatched functions:
the contract under test is "what the browser gets back", and the decoration
(preview/has_diagram) plus Markdown normalisation only behave correctly when
the whole stack — route → parking.py → sqlite — is in play.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

if TYPE_CHECKING:
    from pathlib import Path

MERMAID_NOTE = """## Why this mattered

The join blew up because the planner chose a nested loop.

```mermaid
graph TD
    A[Big table] --> B[Nested loop]
    B --> C[Slow]
```
"""


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient wired to a fresh temp DB (legacy schema → exercises healing)."""
    db_path = tmp_path / "api.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE study_sessions (id TEXT PRIMARY KEY, started_at TEXT)")
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute("""
        CREATE TABLE parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT,
            session_id TEXT,
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

    from studyloop.web.app import create_app

    return TestClient(create_app(study_dirs=[]))


def _create(client: TestClient, question: str, **body) -> int:
    resp = client.post("/api/parking/item", json={"question": question, **body})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# GET /api/parking/board
# ---------------------------------------------------------------------------


def test_board_returns_default_columns_when_empty(client: TestClient) -> None:
    body = client.get("/api/parking/board").json()
    assert [c["key"] for c in body["columns"]] == ["inbox", "next", "exploring", "done"]
    assert body["total"] == 0
    # The UI's "add a diagram" button needs a template it can insert.
    assert "```mermaid" in body["diagram_template"]


def test_board_decorates_items_with_preview_and_diagram_flag(client: TestClient) -> None:
    """A collapsed card needs readable prose + a "has diagram" hint."""
    _create(client, "Why was the join slow?", notes=MERMAID_NOTE)
    body = client.get("/api/parking/board").json()
    item = body["columns"][0]["items"][0]
    assert item["has_diagram"] is True
    assert "graph TD" not in item["preview"]  # diagram source is not prose
    assert item["preview"].startswith("Why this mattered")
    assert item["note_chars"] > 0


def test_board_preview_falls_back_to_context(client: TestClient) -> None:
    """A terse capture with no notes still shows its captured context."""
    _create(client, "MVCC?", context="came up during the Spark shuffle chat")
    item = client.get("/api/parking/board").json()["columns"][0]["items"][0]
    assert item["preview"] == "came up during the Spark shuffle chat"


# ---------------------------------------------------------------------------
# POST /api/parking/item
# ---------------------------------------------------------------------------


def test_create_item_with_notes_into_named_column(client: TestClient) -> None:
    item_id = _create(client, "Generators vs iterators", notes="# N\n", board_column="next")
    board = client.get("/api/parking/board").json()
    by_key = {c["key"]: c for c in board["columns"]}
    assert [i["id"] for i in by_key["next"]["items"]] == [item_id]


def test_create_rejects_empty_question(client: TestClient) -> None:
    assert client.post("/api/parking/item", json={"question": ""}).status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/parking/item/{id} — in-place editing
# ---------------------------------------------------------------------------


def test_patch_edits_question_in_place(client: TestClient) -> None:
    item_id = _create(client, "terse capture")
    resp = client.patch(
        f"/api/parking/item/{item_id}",
        json={"question": "Why does the planner pick a nested loop here?"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["question"] == "Why does the planner pick a nested loop here?"


def test_patch_stores_clean_markdown(client: TestClient) -> None:
    """Whatever the textarea sends, storage is clean Markdown."""
    item_id = _create(client, "x")
    resp = client.patch(
        f"/api/parking/item/{item_id}",
        json={"notes": "# T\r\n\r\n\r\n\r\nbody   \n\n\n"},
    )
    assert resp.json()["item"]["notes"] == "# T\n\nbody\n"


def test_patch_preserves_mermaid_diagram(client: TestClient) -> None:
    item_id = _create(client, "x")
    resp = client.patch(f"/api/parking/item/{item_id}", json={"notes": MERMAID_NOTE})
    item = resp.json()["item"]
    assert "```mermaid" in item["notes"]
    assert "A[Big table] --> B[Nested loop]" in item["notes"]
    assert item["has_diagram"] is True


def test_patch_partial_update_does_not_clobber_other_fields(client: TestClient) -> None:
    """Sending only `notes` must not blank the question (and vice versa)."""
    item_id = _create(client, "Original question", notes="original notes\n")
    client.patch(f"/api/parking/item/{item_id}", json={"notes": "replaced notes\n"})
    item = client.get("/api/parking/board").json()["columns"][0]["items"][0]
    assert item["question"] == "Original question"
    assert item["notes"] == "replaced notes\n"

    client.patch(f"/api/parking/item/{item_id}", json={"question": "New question"})
    item = client.get("/api/parking/board").json()["columns"][0]["items"][0]
    assert item["question"] == "New question"
    assert item["notes"] == "replaced notes\n"


def test_patch_sets_tech_area_and_priority(client: TestClient) -> None:
    item_id = _create(client, "x")
    item = client.patch(
        f"/api/parking/item/{item_id}", json={"tech_area": "SQL", "priority": 4}
    ).json()["item"]
    assert item["tech_area"] == "SQL"
    assert item["priority"] == 4


def test_patch_rejects_out_of_range_priority(client: TestClient) -> None:
    item_id = _create(client, "x")
    assert client.patch(f"/api/parking/item/{item_id}", json={"priority": 9}).status_code == 422


def test_patch_with_no_fields_is_422(client: TestClient) -> None:
    item_id = _create(client, "x")
    assert client.patch(f"/api/parking/item/{item_id}", json={}).status_code == 422


def test_patch_unknown_item_is_404(client: TestClient) -> None:
    assert client.patch("/api/parking/item/9999", json={"notes": "x"}).status_code == 404


def test_patch_cannot_write_protected_fields(client: TestClient) -> None:
    """`status` is not user-editable — pydantic drops the unknown key, and the
    item must be unchanged rather than silently resolved."""
    item_id = _create(client, "x")
    resp = client.patch(f"/api/parking/item/{item_id}", json={"status": "resolved"})
    assert resp.status_code == 422  # nothing editable was supplied
    assert client.get("/api/parking/board").json()["total"] == 1


# ---------------------------------------------------------------------------
# POST /api/parking/item/{id}/move — Kanban drag/keyboard move
# ---------------------------------------------------------------------------


def test_move_between_columns(client: TestClient) -> None:
    item_id = _create(client, "Move me")
    assert (
        client.post(
            f"/api/parking/item/{item_id}/move", json={"board_column": "exploring"}
        ).status_code
        == 200
    )
    board = client.get("/api/parking/board").json()
    by_key = {c["key"]: c for c in board["columns"]}
    assert [i["id"] for i in by_key["exploring"]["items"]] == [item_id]
    assert by_key["inbox"]["items"] == []


def test_move_reorders_within_a_column(client: TestClient) -> None:
    first = _create(client, "First")
    second = _create(client, "Second")
    client.post(f"/api/parking/item/{second}/move", json={"board_column": "inbox", "position": 0})
    ids = [i["id"] for i in client.get("/api/parking/board").json()["columns"][0]["items"]]
    assert ids == [second, first]


def test_move_to_unknown_column_is_404(client: TestClient) -> None:
    item_id = _create(client, "x")
    resp = client.post(f"/api/parking/item/{item_id}/move", json={"board_column": "nope"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/parking/clear — single / subset / all
# ---------------------------------------------------------------------------


def test_clear_single(client: TestClient) -> None:
    keep = _create(client, "Keep")
    drop = _create(client, "Drop")
    resp = client.post("/api/parking/clear", json={"ids": [drop]})
    assert resp.json() == {
        "ok": True,
        "cleared": 1,
        "scope": "selection",
        "requested": 1,
        "hard": False,
    }
    ids = [i["id"] for c in client.get("/api/parking/board").json()["columns"] for i in c["items"]]
    assert ids == [keep]


def test_clear_user_selected_subset(client: TestClient) -> None:
    ids = [_create(client, f"T{i}") for i in range(5)]
    chosen = [ids[1], ids[2], ids[4]]
    resp = client.post("/api/parking/clear", json={"ids": chosen})
    assert resp.json()["cleared"] == 3
    remaining = {
        i["id"] for c in client.get("/api/parking/board").json()["columns"] for i in c["items"]
    }
    assert remaining == {ids[0], ids[3]}


def test_clear_all(client: TestClient) -> None:
    for i in range(4):
        _create(client, f"T{i}")
    resp = client.post("/api/parking/clear", json={"all": True})
    assert resp.json()["scope"] == "all"
    assert resp.json()["cleared"] == 4
    assert client.get("/api/parking/board").json()["total"] == 0


def test_clear_without_ids_or_all_is_422(client: TestClient) -> None:
    assert client.post("/api/parking/clear", json={}).status_code == 422


def test_soft_clear_is_restorable(client: TestClient) -> None:
    item_id = _create(client, "Precious", notes="# keep\n")
    client.post("/api/parking/clear", json={"ids": [item_id]})
    resp = client.post("/api/parking/restore", json={"ids": [item_id]})
    assert resp.json() == {"ok": True, "restored": 1, "ids": [item_id]}
    board = client.get("/api/parking/board").json()
    assert board["total"] == 1
    assert board["columns"][0]["items"][0]["notes"] == "# keep\n"


def test_hard_clear_is_not_restorable(client: TestClient) -> None:
    item_id = _create(client, "Gone")
    client.post("/api/parking/clear", json={"ids": [item_id], "hard": True})
    assert client.post("/api/parking/restore", json={"ids": [item_id]}).json()["restored"] == 0
    assert client.get("/api/parking/board").json()["total"] == 0


def test_restore_requires_ids(client: TestClient) -> None:
    assert client.post("/api/parking/restore", json={"ids": []}).status_code == 422


# ---------------------------------------------------------------------------
# Columns — user-driven board shape
# ---------------------------------------------------------------------------


def test_list_columns(client: TestClient) -> None:
    keys = [c["key"] for c in client.get("/api/parking/columns").json()["columns"]]
    assert keys == ["inbox", "next", "exploring", "done"]


def test_create_column(client: TestClient) -> None:
    resp = client.post("/api/parking/columns", json={"name": "Deep Dive"})
    assert resp.status_code == 201
    assert resp.json()["column"]["key"] == "deep-dive"
    assert "deep-dive" in [c["key"] for c in client.get("/api/parking/columns").json()["columns"]]


def test_create_column_then_move_card_into_it(client: TestClient) -> None:
    client.post("/api/parking/columns", json={"name": "Blocked"})
    item_id = _create(client, "x")
    assert (
        client.post(
            f"/api/parking/item/{item_id}/move", json={"board_column": "blocked"}
        ).status_code
        == 200
    )
    by_key = {c["key"]: c for c in client.get("/api/parking/board").json()["columns"]}
    assert [i["id"] for i in by_key["blocked"]["items"]] == [item_id]


def test_rename_column(client: TestClient) -> None:
    resp = client.patch("/api/parking/columns/inbox", json={"name": "Brain Dump"})
    assert resp.status_code == 200
    names = {c["key"]: c["name"] for c in client.get("/api/parking/columns").json()["columns"]}
    assert names["inbox"] == "Brain Dump"


def test_rename_unknown_column_is_404(client: TestClient) -> None:
    assert client.patch("/api/parking/columns/ghost", json={"name": "X"}).status_code == 404


def test_delete_column_relocates_its_cards(client: TestClient) -> None:
    item_id = _create(client, "Survivor", board_column="done")
    assert client.delete("/api/parking/columns/done?move_items_to=next").status_code == 200
    board = client.get("/api/parking/board").json()
    assert "done" not in [c["key"] for c in board["columns"]]
    by_key = {c["key"]: c for c in board["columns"]}
    assert [i["id"] for i in by_key["next"]["items"]] == [item_id]


def test_reorder_columns(client: TestClient) -> None:
    resp = client.post(
        "/api/parking/columns/reorder",
        json={"keys": ["done", "exploring", "next", "inbox"]},
    )
    assert resp.status_code == 200
    keys = [c["key"] for c in client.get("/api/parking/columns").json()["columns"]]
    assert keys == ["done", "exploring", "next", "inbox"]


# ---------------------------------------------------------------------------
# Cross-surface consistency: /api/backlog must see the same world
# ---------------------------------------------------------------------------


def test_clearing_removes_items_from_the_backlog_surface_too(client: TestClient) -> None:
    """The board and the 3-topic backlog read the same rows — clearing on one
    surface must not leave ghosts on the other."""
    ids = [_create(client, f"T{i}") for i in range(4)]
    before = client.get("/api/backlog").json()
    assert before["active_count"] + before["parking_lot_count"] == 4

    client.post("/api/parking/clear", json={"ids": ids[:3]})
    after = client.get("/api/backlog").json()
    assert after["active_count"] + after["parking_lot_count"] == 1
