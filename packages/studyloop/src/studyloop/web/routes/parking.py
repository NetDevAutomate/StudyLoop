"""Parking-lot board API — editable, Kanban-style, Markdown-native.

Why this exists as its own router rather than more verbs on ``backlog.py``:
``/api/backlog`` answers one narrow question ("which 3 topics are live?").
The parking lot is a different surface with a different lifecycle — arrange,
edit, annotate, clear — and mixing the two made the backlog contract mean two
things at once.

Design decisions worth knowing:

* **Clearing is soft by default.** ``status='dismissed'`` keeps the row, so an
  accidental "clear all" is recoverable via ``POST /api/parking/restore``.
  ``hard=true`` is available for a genuine purge.
* **Selection is caller-driven.** ``POST /api/parking/clear`` takes an explicit
  id list, or ``all=true``. There is no server-imposed "clear the oldest N".
* **Notes are Markdown, normalised server-side.** The client never has to get
  whitespace/fence hygiene right; ``normalise_markdown`` is the single gate, so
  the DB only ever holds clean Markdown.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from studyloop.markdown_notes import MERMAID_TEMPLATE, has_diagram, summarise_markdown
from studyloop.parking import (
    add_board_column,
    clear_all_parked_topics,
    clear_parked_topics,
    delete_board_column,
    get_board,
    get_board_columns,
    move_parked_topic,
    park_topic,
    rename_board_column,
    reorder_board_columns,
    restore_parked_topic,
    update_parked_topic,
)

router = APIRouter()


def _decorate(item: dict) -> dict:
    """Attach derived, display-only fields the UI would otherwise recompute.

    ``preview``/``has_diagram`` are computed here (not in the browser) so the
    collapsed-card rendering is identical for any client — the TUI, a future
    mobile view, or the web board.
    """
    notes = item.get("notes") or ""
    return {
        **item,
        "notes": notes,
        "preview": summarise_markdown(notes) or summarise_markdown(item.get("context")),
        "has_diagram": has_diagram(notes),
        "note_chars": len(notes),
    }


def _require_question(question: str) -> str:
    """Reject a blank / whitespace-only question with 400; return trimmed text.

    Pydantic's ``min_length=1`` only stops the empty string ``""``; a value
    like ``"   "`` clears it but collapses to nothing once trimmed, which would
    otherwise persist an empty-question card.
    """
    trimmed = question.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="question cannot be blank")
    return trimmed


def _require_known_column(board_column: str) -> None:
    """Reject a board_column that is not one of the board's real columns (400)."""
    known = {col["key"] for col in get_board_columns()}
    if board_column not in known:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown board column: {board_column!r}",
        )


@router.get("/parking/board")
def get_parking_board() -> dict:
    """Return the whole board: ordered columns, each with its ordered cards."""
    board = get_board()
    return {
        "columns": [
            {**col, "items": [_decorate(i) for i in col["items"]]} for col in board["columns"]
        ],
        "total": board["total"],
        "diagram_template": MERMAID_TEMPLATE,
    }


class ParkingCreate(BaseModel):
    """POST /api/parking/item — create a card directly on the board."""

    question: str = Field(min_length=1, max_length=500)
    notes: str | None = None
    tech_area: str | None = None
    context: str | None = None
    board_column: str = "inbox"


@router.post("/parking/item", status_code=201)
def create_parking_item(body: ParkingCreate) -> dict:
    """Create a parked item (board-native capture, with notes from the start)."""
    question = _require_question(body.question)
    _require_known_column(body.board_column)
    row_id = park_topic(
        question,
        notes=body.notes,
        tech_area=body.tech_area,
        context=body.context,
        created_by="web",
        source="manual",
        board_column=body.board_column,
    )
    if row_id is None:
        raise HTTPException(status_code=500, detail="Could not create parked item")
    return {"ok": True, "id": row_id}


class ParkingUpdate(BaseModel):
    """PATCH /api/parking/item/{id} — in-place edit of one card.

    Every field is optional: the UI sends only what the user actually changed,
    so two people editing different fields of the same card don't clobber each
    other's work.
    """

    question: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    tech_area: str | None = None
    context: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    board_column: str | None = None


@router.patch("/parking/item/{item_id}")
def patch_parking_item(item_id: int, body: ParkingUpdate) -> dict:
    """Edit a card in place. Returns the updated card (decorated)."""
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=422, detail="No editable fields supplied")
    if "board_column" in fields:
        _require_known_column(fields["board_column"])
    if "question" in fields:
        fields["question"] = _require_question(fields["question"])
    try:
        updated = update_parked_topic(item_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No parked item with id {item_id}")
    return {"ok": True, "item": _decorate(updated)}


class ParkingMove(BaseModel):
    """POST /api/parking/item/{id}/move — drag-and-drop / keyboard move."""

    board_column: str
    position: int | None = Field(default=None, ge=0)


@router.post("/parking/item/{item_id}/move")
def move_parking_item(item_id: int, body: ParkingMove) -> dict:
    """Move a card to a column (and optional index within it)."""
    if not move_parked_topic(item_id, body.board_column, body.position):
        raise HTTPException(
            status_code=404,
            detail=f"Could not move item {item_id} to column {body.board_column!r}",
        )
    return {"ok": True}


class ParkingClear(BaseModel):
    """POST /api/parking/clear — clear one, a chosen subset, or all.

    ``ids`` is whatever the user selected: a single id, an arbitrary subset, or
    nothing at all when ``all`` is set. Deliberately not "clear column X" —
    selection is user-driven, not structural.
    """

    ids: list[int] = Field(default_factory=list)
    all: bool = False
    hard: bool = False


@router.post("/parking/clear")
def clear_parking(body: ParkingClear) -> dict:
    """Clear parked items. Soft by default (recoverable), hard on request."""
    if body.all:
        cleared = clear_all_parked_topics(hard=body.hard)
        return {"ok": True, "cleared": cleared, "scope": "all", "hard": body.hard}
    if not body.ids:
        raise HTTPException(status_code=422, detail="Supply ids, or set all=true")
    cleared = clear_parked_topics(body.ids, hard=body.hard)
    return {
        "ok": True,
        "cleared": cleared,
        "scope": "selection",
        "requested": len(body.ids),
        "hard": body.hard,
    }


class ParkingRestore(BaseModel):
    """POST /api/parking/restore — undo a soft clear."""

    ids: list[int] = Field(min_length=1)


@router.post("/parking/restore")
def restore_parking(body: ParkingRestore) -> dict:
    """Put soft-cleared items back on the board (undo)."""
    restored = [i for i in body.ids if restore_parked_topic(i)]
    return {"ok": True, "restored": len(restored), "ids": restored}


class ColumnCreate(BaseModel):
    """POST /api/parking/columns — user-defined board column."""

    name: str = Field(min_length=1, max_length=48)


@router.get("/parking/columns")
def list_columns() -> dict:
    """Return the board's columns (without their items)."""
    return {"columns": get_board_columns()}


@router.post("/parking/columns", status_code=201)
def create_column(body: ColumnCreate) -> dict:
    """Add a column — the board shape is the user's, not ours."""
    created = add_board_column(body.name)
    if created is None:
        raise HTTPException(status_code=422, detail="Invalid column name")
    return {"ok": True, "column": created}


class ColumnRename(BaseModel):
    """PATCH /api/parking/columns/{key}."""

    name: str = Field(min_length=1, max_length=48)


@router.patch("/parking/columns/{key}")
def patch_column(key: str, body: ColumnRename) -> dict:
    """Rename a column (its key — and card links — stay stable)."""
    if not rename_board_column(key, body.name):
        raise HTTPException(status_code=404, detail=f"No column {key!r}")
    return {"ok": True}


@router.delete("/parking/columns/{key}")
def delete_column(key: str, move_items_to: str | None = None) -> dict:
    """Delete a column. Its cards are relocated, never deleted."""
    if not delete_board_column(key, move_items_to=move_items_to):
        raise HTTPException(
            status_code=409,
            detail=f"Could not delete column {key!r} (unknown, or it is the last column)",
        )
    return {"ok": True}


class ColumnOrder(BaseModel):
    """POST /api/parking/columns/reorder."""

    keys: list[str] = Field(min_length=1)


@router.post("/parking/columns/reorder")
def reorder_columns(body: ColumnOrder) -> dict:
    """Persist a new left-to-right column order."""
    if not reorder_board_columns(body.keys):
        raise HTTPException(status_code=422, detail="No column keys supplied")
    return {"ok": True}
