"""Study notes + body-double focus: persistence, API contract, and the rule of 3.

These are the guarantees the Body Double surface leans on, so they are asserted
directly rather than only through the browser journey:

* a note body is stored as *clean* Markdown, whatever the client sent;
* ``kind`` is a closed set, and a bad one is a 422 rather than a 500 from a
  CHECK constraint;
* clearing is soft and undoable by default, per-selection or wholesale;
* the Markdown export is a valid heading tree (an agent parses it by depth);
* the focus endpoint never lets more than ``MAX_ACTIVE_TOPICS`` topics be live,
  and says so with ``at_capacity`` instead of making the caller re-derive it.
"""

from __future__ import annotations

import re
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from studyloop.settings import MAX_ACTIVE_TOPICS


@pytest.fixture
def notes_env(tmp_path, monkeypatch):
    """Point every DB/config read at a temp instance for the whole test.

    Belt AND braces, deliberately. Setting ``STUDYLOOP_CONFIG`` is the honest
    mechanism — it is what a user or subprocess would set, and it is what the
    lazy ``get_config_path()`` reads. But the module-level ``get_db_path``
    references are pinned too, because they are *not* reliably clean: at least
    one other module in this suite (``test_cli_session.py``) patches
    ``studyloop.parking.get_db_path`` with a local lambda that is still bound
    when later modules run, so a test that trusted the global would silently
    read a different database — which is exactly the failure this fixture was
    written to stop.
    """
    config = tmp_path / "config.yaml"
    db_path = tmp_path / "sessions.db"
    config.write_text(f"session_db: {db_path}\n", encoding="utf-8")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

    # Import the modules first so the attributes exist to be pinned.
    import studyloop.history._connection as history_conn
    import studyloop.notes as notes_mod
    import studyloop.parking as parking_mod
    import studyloop.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_db_path", lambda: db_path)
    monkeypatch.setattr(parking_mod, "get_db_path", lambda: db_path)
    monkeypatch.setattr(notes_mod, "get_db_path", lambda: db_path)
    monkeypatch.setattr(history_conn, "_get_db_path", lambda: db_path)
    return tmp_path


@pytest.fixture
def client(notes_env):
    from studyloop.web.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Persistence layer
# ---------------------------------------------------------------------------


def test_body_is_normalised_to_clean_markdown(notes_env):
    """CRLF, trailing spaces, blank-line runs and an open fence are all fixed."""
    from studyloop import notes

    note_id = notes.add_note(
        "Messy capture",
        body="## Heading\r\n\r\n\r\n- item   \n\n```python\nx = 1\n",
        topic="Python Decorators",
    )
    stored = notes.get_note(note_id)
    body = stored["body"]
    assert "\r" not in body
    assert "   \n" not in body
    assert "\n\n\n" not in body
    assert body.endswith("```\n"), f"unterminated fence not closed: {body!r}"


def test_unknown_kind_falls_back_on_write_and_raises_on_update(notes_env):
    from studyloop import notes

    note_id = notes.add_note("Kind check", kind="not-a-kind")
    assert notes.get_note(note_id)["kind"] == "note"
    with pytest.raises(ValueError, match="Unknown note kind"):
        notes.update_note(note_id, kind="also-bogus")


def test_empty_title_is_refused(notes_env):
    from studyloop import notes

    assert notes.add_note("   ") is None


def test_clear_is_soft_and_restorable(notes_env):
    from studyloop import notes

    keep = notes.add_note("Keep me")
    drop = notes.add_note("Drop me")
    assert notes.clear_notes([drop]) == 1
    active_ids = {n["id"] for n in notes.list_notes()}
    assert active_ids == {keep}
    # the row is still there, just dismissed — which is what makes undo possible
    assert {n["id"] for n in notes.list_notes(status="all")} == {keep, drop}
    assert notes.restore_note(drop) is True
    assert {n["id"] for n in notes.list_notes()} == {keep, drop}


def test_hard_clear_actually_deletes(notes_env):
    from studyloop import notes

    note_id = notes.add_note("Gone for good")
    assert notes.clear_notes([note_id], hard=True) == 1
    assert notes.list_notes(status="all") == []
    assert notes.restore_note(note_id) is False


def test_markdown_export_is_a_valid_heading_tree(notes_env):
    """No skipped heading levels, and body headings nest under their note title."""
    from studyloop import notes

    notes.add_note("Week plan", body="## Goal\n\n- ship it\n", kind="plan", topic="SQL")
    notes.add_note(
        "Window functions",
        body="## What I worked out\n\n```python\n# not a heading\n```\n",
        kind="note",
        topic="SQL",
    )
    doc = notes.notes_markdown(topic="SQL")

    depths: list[int] = []
    in_fence = False
    for line in doc.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+\S", line)
        if match:
            depths.append(len(match.group(1)))

    assert depths, "export produced no headings"
    assert depths[0] == 1, "export should start at a single h1"
    for previous, current in pairwise(depths):
        assert current - previous <= 1, f"heading level jumped {previous} -> {current}"
    # a `#` inside the fenced block must NOT have been treated as a heading
    assert "#### not a heading" not in doc


def test_markdown_export_groups_intent_before_evidence(notes_env):
    from studyloop import notes

    notes.add_note("Raw thought", body="- something\n", kind="note", topic="SQL")
    notes.add_note("The plan", body="- step\n", kind="plan", topic="SQL")
    notes.add_note("Where I am", body="- ok\n", kind="assessment", topic="SQL")
    doc = notes.notes_markdown(topic="SQL")
    assert doc.index("## Study plan") < doc.index("## Assessment") < doc.index("## Notes")


def test_export_with_no_notes_is_still_valid_markdown(notes_env):
    from studyloop import notes

    assert notes.notes_markdown().startswith("# Study notes")


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------


def test_post_note_echoes_the_normalised_row(client):
    """The editor must see what was *stored*, not what was typed."""
    response = client.post(
        "/api/notes",
        json={"title": "Echo", "body": "## H\r\n\r\n- a\n", "topic": "T", "kind": "note"},
    )
    assert response.status_code == 201
    note = response.json()["note"]
    assert "\r" not in note["body"]
    assert note["preview"]
    assert note["kind"] == "note"


def test_get_notes_ships_composer_metadata_in_one_request(client):
    payload = client.get("/api/notes").json()
    assert payload["kinds"] == [
        "note",
        "question",
        "plan",
        "assessment",
        "win",
        "struggle",
    ]
    assert set(payload["templates"]) == set(payload["kinds"])
    assert "mermaid" in payload["diagram_template"]


def test_bad_kind_is_422_not_500(client):
    assert client.post("/api/notes", json={"title": "x", "kind": "nope"}).status_code == 422
    assert client.get("/api/notes", params={"kind": "nope"}).status_code == 422


def test_patch_requires_at_least_one_field_and_404s_on_missing(client):
    created = client.post("/api/notes", json={"title": "Patchable"}).json()["id"]
    assert client.patch(f"/api/notes/{created}", json={}).status_code == 422
    assert client.patch("/api/notes/999999", json={"title": "ghost"}).status_code == 404
    assert client.patch(f"/api/notes/{created}", json={"confidence": 4}).status_code == 200


def test_clear_all_then_restore_round_trip_over_http(client):
    first = client.post("/api/notes", json={"title": "One"}).json()["id"]
    second = client.post("/api/notes", json={"title": "Two"}).json()["id"]
    cleared = client.post("/api/notes/clear", json={"all": True}).json()
    assert cleared["cleared"] == 2
    assert client.get("/api/notes").json()["total"] == 0
    restored = client.post("/api/notes/restore", json={"ids": [first, second]}).json()
    assert restored["restored"] == 2
    assert client.get("/api/notes").json()["total"] == 2


def test_clear_without_ids_or_all_is_refused(client):
    assert client.post("/api/notes/clear", json={}).status_code == 422


def test_markdown_endpoint_returns_plain_text(client):
    client.post("/api/notes", json={"title": "Plan", "body": "- do it\n", "kind": "plan"})
    response = client.get("/api/notes/markdown")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "## Study plan" in response.text


# ---------------------------------------------------------------------------
# The rule of 3
# ---------------------------------------------------------------------------


def test_focus_endpoint_caps_live_slots_at_three(client):
    """A 4th parked topic goes to the parking lot, never into a 4th slot."""
    for topic in ("Decorators", "SQL windows", "Spark shuffles", "dbt tests"):
        assert client.post("/api/backlog/park", json={"question": topic}).status_code == 200

    payload = client.get("/api/body-double/focus").json()
    assert payload["max_active"] == MAX_ACTIVE_TOPICS
    assert len(payload["slots"]) == MAX_ACTIVE_TOPICS
    assert payload["slots_used"] == MAX_ACTIVE_TOPICS
    assert payload["slots_free"] == 0
    assert payload["at_capacity"] is True
    assert payload["parking_lot_count"] == 1


def test_focus_endpoint_is_empty_and_calm_on_a_fresh_machine(client):
    payload = client.get("/api/body-double/focus").json()
    assert payload["slots"] == []
    assert payload["at_capacity"] is False
    assert payload["slots_free"] == MAX_ACTIVE_TOPICS


def test_live_slots_are_the_most_recent_topics_even_within_one_second(client):
    """Four rapid parks must still give a deterministic, recency-ordered split.

    ``parked_at`` only has second granularity, so parks in the same second tie.
    Without a total ordering the live set was arbitrary — "which three am I
    focused on" could change between two reads, and the park-first modal could
    demote a row that was not occupying a slot.
    """
    ordered = ["first parked", "second parked", "third parked", "fourth parked"]
    for topic in ordered:
        client.post("/api/backlog/park", json={"question": topic})

    live = [slot["topic"] for slot in client.get("/api/body-double/focus").json()["slots"]]
    assert live == ["fourth parked", "third parked", "second parked"], (
        f"live slots are not the three most recent: {live}"
    )
    # Stable across reads, not merely correct once.
    assert live == [slot["topic"] for slot in client.get("/api/body-double/focus").json()["slots"]]


def test_demoting_a_live_topic_frees_its_slot(client):
    """The park-first lever must actually work: demote swaps a topic out.

    Four topics, not three: with exactly ``MAX_ACTIVE_TOPICS`` parked there is
    nothing to promote, so demoting cannot change the live set. The swap is only
    observable when something is waiting in the parking lot.
    """
    for topic in ("oldest", "middle", "newer", "newest"):
        client.post("/api/backlog/park", json={"question": topic})
    payload = client.get("/api/body-double/focus").json()
    assert [slot["topic"] for slot in payload["slots"]] == ["newest", "newer", "middle"]
    assert payload["at_capacity"] is True
    assert [item["question"] for item in payload["parking_lot"]] == ["oldest"]

    victim = next(slot for slot in payload["slots"] if slot["topic"] == "newest")
    assert client.post("/api/backlog/demote", json={"id": victim["id"]}).status_code == 200

    after = client.get("/api/body-double/focus").json()
    live = [slot["topic"] for slot in after["slots"]]
    assert "newest" not in live, f"demote did not free the slot: {live}"
    assert "oldest" in live, f"the waiting topic was not promoted: {live}"
    assert [item["question"] for item in after["parking_lot"]] == ["newest"]


def test_setting_more_than_three_focus_topics_is_refused(client):
    response = client.post("/api/body-double/focus", json={"topics": ["a", "b", "c", "d"]})
    assert response.status_code == 422
    assert "Maximum 3" in response.json()["detail"]


def test_committed_focus_topics_take_the_slots_and_carry_note_counts(client):
    client.post("/api/backlog/park", json={"question": "Ambient parked topic"})
    client.post("/api/body-double/focus", json={"topics": ["Python Decorators"]})
    client.post("/api/notes", json={"title": "n1", "topic": "Python Decorators"})
    client.post("/api/notes", json={"title": "n2", "topic": "Python Decorators"})

    slots = client.get("/api/body-double/focus").json()["slots"]
    by_topic = {s["topic"]: s for s in slots}
    assert by_topic["Python Decorators"]["source"] == "focus"
    assert by_topic["Python Decorators"]["note_count"] == 2
    # the parked topic still fills a remaining slot — the panel is never empty
    # just because `studyloop focus set` was never run
    assert "Ambient parked topic" in by_topic
    assert by_topic["Ambient parked topic"]["source"] == "active"


def test_session_types_no_longer_offers_body_double(client):
    """Body doubling is a surface, not a study-session type (the key stays)."""
    options = client.get("/api/session/options").json()
    values = {entry["value"] for entry in options["session_types"]}
    assert values == {"study"}
