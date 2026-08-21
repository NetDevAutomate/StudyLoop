"""Study-notes API — capture, review, and selectively clear Markdown notes.

Deliberately shaped like ``parking.py`` rather than like a generic CRUD router:
the two surfaces sit side by side in the same third column of the web UI, and a
learner should not have to learn two different mental models for "clear one /
clear a subset / clear all / undo".

The one endpoint that has no parking-lot equivalent is
``GET /api/notes/markdown``. That is the agent's door: a mentor asked to build a
study plan or assess progress reads one grouped Markdown document instead of
paging the JSON list and re-deriving the grouping itself.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from studyloop.markdown_notes import MERMAID_TEMPLATE
from studyloop.notes import (
    NOTE_KINDS,
    add_note,
    clear_all_notes,
    clear_notes,
    count_notes,
    get_note,
    list_notes,
    notes_markdown,
    restore_note,
    update_note,
)

router = APIRouter()

#: Starter bodies the composer offers per kind. Shipped from the server (not
#: hardcoded in JS) so the structure an agent expects to parse and the structure
#: the learner is nudged into writing cannot drift apart.
NOTE_TEMPLATES: dict[str, str] = {
    "note": "## What I worked out\n\n- \n\n## Why it matters\n\n- \n",
    "question": "## What I don't understand yet\n\n- \n\n## What I've already tried\n\n- \n",
    "plan": ("## Goal\n\n- \n\n## Steps\n\n1. \n2. \n3. \n\n## How I'll know it worked\n\n- \n"),
    "assessment": (
        "## What I can do unaided\n\n- \n\n## What still needs notes open\n\n- \n\n"
        "## Next check\n\n- \n"
    ),
    "win": "## What clicked\n\n- \n\n## What made it click\n\n- \n",
    "struggle": (
        "## Where I got stuck\n\n- \n\n## What I tried\n\n- \n\n## Best guess why\n\n- \n"
    ),
}


@router.get("/notes")
def get_notes(
    status: str = "active",
    topic: str | None = None,
    kind: str | None = None,
    study_session_id: str | None = None,
    limit: int = 200,
) -> dict:
    """List notes newest-first, plus the metadata the composer needs.

    ``kinds``/``templates``/``diagram_template`` ride along so the client has
    everything for a first render in one request — the notes panel opens with no
    second round trip.
    """
    if kind is not None and kind not in NOTE_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown note kind: {kind!r}")
    notes = list_notes(
        status=status,
        topic=topic,
        kind=kind,
        study_session_id=study_session_id,
        limit=max(1, min(limit, 500)),
    )
    return {
        "notes": notes,
        "total": len(notes),
        "active_total": count_notes(status="active"),
        "kinds": list(NOTE_KINDS),
        "templates": NOTE_TEMPLATES,
        "diagram_template": MERMAID_TEMPLATE,
    }


class NoteCreate(BaseModel):
    """POST /api/notes — capture one note."""

    title: str = Field(min_length=1, max_length=300)
    body: str | None = None
    topic: str | None = Field(default=None, max_length=200)
    kind: str = "note"
    confidence: int | None = Field(default=None, ge=1, le=5)
    origin: str = "body-double"
    study_session_id: str | None = None


@router.post("/notes", status_code=201)
def post_note(body: NoteCreate) -> dict:
    """Create a note. Returns the stored (normalised) note, not just its id.

    Returning the full row matters: the body the server stored is *normalised*
    Markdown, which may differ from what was typed. Echoing it back means the
    editor shows the durable truth immediately rather than after a reload.
    """
    if body.kind not in NOTE_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown note kind: {body.kind!r}")
    note_id = add_note(
        body.title,
        body=body.body,
        topic=body.topic,
        kind=body.kind,
        confidence=body.confidence,
        origin=body.origin,
        study_session_id=body.study_session_id,
    )
    if note_id is None:
        raise HTTPException(status_code=500, detail="Could not store note")
    stored = get_note(note_id)
    return {"ok": True, "id": note_id, "note": stored}


class NoteUpdate(BaseModel):
    """PATCH /api/notes/{id} — partial, field-by-field edit."""

    title: str | None = Field(default=None, max_length=300)
    body: str | None = None
    topic: str | None = Field(default=None, max_length=200)
    kind: str | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)


@router.patch("/notes/{note_id}")
def patch_note(note_id: int, body: NoteUpdate) -> dict:
    """Edit a note in place; returns the updated note."""
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=422, detail="No editable fields supplied")
    try:
        updated = update_note(note_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No note with id {note_id}")
    return {"ok": True, "note": updated}


class NoteClear(BaseModel):
    """POST /api/notes/clear — clear one, a chosen subset, or all."""

    ids: list[int] = Field(default_factory=list)
    all: bool = False
    hard: bool = False


@router.post("/notes/clear")
def post_clear_notes(body: NoteClear) -> dict:
    """Clear notes. Soft by default (undoable), hard on explicit request."""
    if body.all:
        cleared = clear_all_notes(hard=body.hard)
        return {"ok": True, "cleared": cleared, "scope": "all", "hard": body.hard}
    if not body.ids:
        raise HTTPException(status_code=422, detail="Supply ids, or set all=true")
    cleared = clear_notes(body.ids, hard=body.hard)
    return {
        "ok": True,
        "cleared": cleared,
        "scope": "selection",
        "requested": len(body.ids),
        "hard": body.hard,
    }


class NoteRestore(BaseModel):
    """POST /api/notes/restore — undo a soft clear."""

    ids: list[int] = Field(min_length=1)


@router.post("/notes/restore")
def post_restore_notes(body: NoteRestore) -> dict:
    """Put soft-cleared notes back."""
    restored = [i for i in body.ids if restore_note(i)]
    return {"ok": True, "restored": len(restored), "ids": restored}


@router.get("/notes/markdown", response_class=PlainTextResponse)
def get_notes_markdown(
    topic: str | None = None,
    study_session_id: str | None = None,
    limit: int = 200,
) -> str:
    """Return all active notes as one grouped Markdown document (agent-facing)."""
    return notes_markdown(
        topic=topic,
        study_session_id=study_session_id,
        limit=max(1, min(limit, 500)),
    )
