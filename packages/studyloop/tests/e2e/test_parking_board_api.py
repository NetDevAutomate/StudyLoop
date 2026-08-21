"""Parking-board API lifecycle — the whole Kanban surface, end to end.

WHY THIS FILE EXISTS
--------------------
``routes/parking.py`` shipped 12 endpoints with **no test and no UI caller**:
the mandatory coverage gate (``tests/test_e2e_coverage_gate.py``) surfaced them
as dark code. This module walks the surface the way a client would — capture a
card, annotate it in Markdown, move it across columns, reshape the board,
soft-clear and undo — against a real server with an isolated session DB.

Ordering matters: the tests share one server and one board, and each phase
builds on the previous one, so they are numbered.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_parking_board_api.py -m e2e
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import launch_env, shutdown  # noqa: E402

pytestmark = [pytest.mark.e2e]

PORT = 18605


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    """Server with an isolated session DB; yields a small request helper."""
    import requests

    root = tmp_path_factory.mktemp("parking-board")
    env = launch_env(root, PORT)

    class Api:
        base = env.base_url

        def get(self, path: str, **kw):
            return requests.get(f"{self.base}{path}", timeout=20, **kw)

        def post(self, path: str, **kw):
            return requests.post(f"{self.base}{path}", timeout=20, **kw)

        def patch(self, path: str, **kw):
            return requests.patch(f"{self.base}{path}", timeout=20, **kw)

        def delete(self, path: str, **kw):
            return requests.delete(f"{self.base}{path}", timeout=20, **kw)

    try:
        yield Api()
    finally:
        shutdown(env)


@pytest.fixture(scope="module")
def state() -> dict:
    """Ids created by earlier phases, consumed by later ones."""
    return {}


def test_01_board_starts_with_default_columns(api) -> None:
    """GET /api/parking/board and /columns agree on the default board shape."""
    board = api.get("/api/parking/board")
    assert board.status_code == 200, board.text
    body = board.json()
    assert isinstance(body["columns"], list) and body["columns"], "board has no columns"
    assert "total" in body
    # The board ships a Mermaid starter so a card can hold a diagram.
    assert "diagram_template" in body and body["diagram_template"].strip()

    cols = api.get("/api/parking/columns")
    assert cols.status_code == 200, cols.text
    assert [c["key"] for c in cols.json()["columns"]] == [c["key"] for c in body["columns"]], (
        "/columns and /board disagree on the column set"
    )


def test_02_capture_card_with_markdown_notes(api, state) -> None:
    """POST /api/parking/item stores Markdown notes and derived preview fields."""
    resp = api.post(
        "/api/parking/item",
        json={
            "question": "Why does functools.wraps matter for decorators?",
            "notes": "## Context\n\nHit this while reading the decorators lesson.\n",
            "tech_area": "python",
            "context": "Python Decorators lesson 01",
        },
    )
    assert resp.status_code == 201, resp.text
    item_id = resp.json()["id"]
    assert isinstance(item_id, int)
    state["item_id"] = item_id

    board = api.get("/api/parking/board").json()
    cards = [c for col in board["columns"] for c in col["items"]]
    card = next((c for c in cards if c["id"] == item_id), None)
    assert card is not None, f"created card {item_id} is not on the board"
    # Derived, display-only fields are computed server-side for every client.
    assert card["preview"], "no preview computed for a card with notes"
    assert card["note_chars"] > 0
    assert card["has_diagram"] is False, "a card with no fence claims a diagram"


def test_03_edit_card_in_place(api, state) -> None:
    """PATCH /api/parking/item/{id} applies a partial edit and re-derives fields."""
    item_id = state["item_id"]
    resp = api.patch(
        f"/api/parking/item/{item_id}",
        json={"notes": "```mermaid\nflowchart LR\n  a-->b\n```\n", "priority": 2},
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["item"]
    assert item["priority"] == 2
    assert item["has_diagram"] is True, "a card containing a mermaid fence must flag a diagram"
    # The untouched field survived the partial update.
    assert "functools.wraps" in item["question"]

    empty = api.patch(f"/api/parking/item/{item_id}", json={})
    assert empty.status_code == 422, "an empty patch must be rejected, not silently applied"

    missing = api.patch("/api/parking/item/999999", json={"priority": 1})
    assert missing.status_code == 404


def test_04_reshape_the_board(api, state) -> None:
    """Columns can be added, renamed, reordered and deleted (cards relocate)."""
    created = api.post("/api/parking/columns", json={"name": "Deep Dive"})
    assert created.status_code == 201, created.text
    key = created.json()["column"]["key"]
    state["column_key"] = key

    renamed = api.patch(f"/api/parking/columns/{key}", json={"name": "Deep Dives"})
    assert renamed.status_code == 200, renamed.text
    names = {c["key"]: c["name"] for c in api.get("/api/parking/columns").json()["columns"]}
    assert names[key] == "Deep Dives", "rename did not persist"

    keys = [c["key"] for c in api.get("/api/parking/columns").json()["columns"]]
    reordered = api.post("/api/parking/columns/reorder", json={"keys": list(reversed(keys))})
    assert reordered.status_code == 200, reordered.text
    assert [c["key"] for c in api.get("/api/parking/columns").json()["columns"]] == list(
        reversed(keys)
    ), "reorder did not persist"

    assert api.patch("/api/parking/columns/no-such-column", json={"name": "x"}).status_code == 404


def test_05_move_card_between_columns(api, state) -> None:
    """POST /api/parking/item/{id}/move relocates a card to a column+position."""
    item_id, key = state["item_id"], state["column_key"]
    moved = api.post(f"/api/parking/item/{item_id}/move", json={"board_column": key, "position": 0})
    assert moved.status_code == 200, moved.text

    board = api.get("/api/parking/board").json()
    target = next(c for c in board["columns"] if c["key"] == key)
    assert [c["id"] for c in target["items"]][:1] == [item_id], (
        f"card {item_id} is not at position 0 of {key}"
    )

    bad = api.post(f"/api/parking/item/{item_id}/move", json={"board_column": "nope"})
    assert bad.status_code == 404


def test_06_delete_column_relocates_its_cards(api, state) -> None:
    """DELETE /api/parking/columns/{key} never deletes the cards inside it."""
    item_id, key = state["item_id"], state["column_key"]
    columns = api.get("/api/parking/columns").json()["columns"]
    survivors = [c["key"] for c in columns if c["key"] != key]
    resp = api.delete(f"/api/parking/columns/{key}", params={"move_items_to": survivors[0]})
    assert resp.status_code == 200, resp.text

    board = api.get("/api/parking/board").json()
    keys = [c["key"] for c in board["columns"]]
    assert key not in keys, "deleted column is still on the board"
    ids = [c["id"] for col in board["columns"] for c in col["items"]]
    assert item_id in ids, "deleting a column deleted its card — cards must relocate"


def test_07_soft_clear_is_recoverable(api, state) -> None:
    """Clearing hides a card but keeps it; restore puts it back (undo)."""
    item_id = state["item_id"]
    cleared = api.post("/api/parking/clear", json={"ids": [item_id]})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] >= 1
    assert cleared.json()["hard"] is False

    board = api.get("/api/parking/board").json()
    ids = [c["id"] for col in board["columns"] for c in col["items"]]
    assert item_id not in ids, "a cleared card is still shown on the board"

    restored = api.post("/api/parking/restore", json={"ids": [item_id]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] == 1, "soft clear was not recoverable"

    board = api.get("/api/parking/board").json()
    ids = [c["id"] for col in board["columns"] for c in col["items"]]
    assert item_id in ids, "restore did not put the card back on the board"

    assert api.post("/api/parking/clear", json={}).status_code == 422, (
        "clear with neither ids nor all=true must be rejected"
    )


def test_08_clear_all_reports_scope(api) -> None:
    """all=true clears the board and reports the wider scope explicitly."""
    api.post("/api/parking/item", json={"question": "Scratch card for clear-all"})
    resp = api.post("/api/parking/clear", json={"all": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "all"
    assert body["cleared"] >= 1
    board = api.get("/api/parking/board").json()
    assert board["total"] == 0, f"board not empty after clear-all: {board['total']}"
