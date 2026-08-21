"""Tests for GET /api/backlog — 3-topic active/parking-lot split."""

from __future__ import annotations

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.settings import MAX_ACTIVE_TOPICS  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402


def _client() -> TestClient:
    return TestClient(create_app(study_dirs=[]))


def test_backlog_splits_active_and_parking_lot(monkeypatch) -> None:
    """More than MAX_ACTIVE_TOPICS pending → first N active, rest parked."""
    pending = [
        {"id": i, "question": f"q{i}", "status": "pending"} for i in range(MAX_ACTIVE_TOPICS + 2)
    ]
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": list(pending),
    )
    resp = _client().get("/api/backlog")
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_active"] == MAX_ACTIVE_TOPICS
    assert body["active_count"] == MAX_ACTIVE_TOPICS
    assert body["parking_lot_count"] == 2
    assert len(body["active"]) == MAX_ACTIVE_TOPICS
    # No overlap: active + parking_lot partitions the pending set.
    active_ids = {t["id"] for t in body["active"]}
    parked_ids = {t["id"] for t in body["parking_lot"]}
    assert active_ids.isdisjoint(parked_ids)
    assert active_ids | parked_ids == {t["id"] for t in pending}


def test_backlog_under_limit_has_empty_parking_lot(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": [{"id": 1, "question": "q1", "status": "pending"}],
    )
    body = _client().get("/api/backlog").json()
    assert body["active_count"] == 1
    assert body["parking_lot_count"] == 0
    assert body["parking_lot"] == []


def test_backlog_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": [],
    )
    body = _client().get("/api/backlog").json()
    assert body["active_count"] == 0
    assert body["parking_lot_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/backlog/park — quick-park brain-dump
# ---------------------------------------------------------------------------


def test_park_happy_path(monkeypatch) -> None:
    captured: dict = {}

    def _fake_park(question, **kw):
        captured["question"] = question
        captured.update(kw)
        return 42

    monkeypatch.setattr("studyloop.web.routes.backlog.park_topic", _fake_park)
    resp = _client().post("/api/backlog/park", json={"question": "  What is MVCC?  "})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "id": 42}
    assert captured["question"] == "What is MVCC?"  # stripped
    assert captured["created_by"] == "web"
    assert captured["source"] == "parked"


def test_park_with_tech_area_and_context(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.park_topic",
        lambda q, **kw: captured.update({"q": q, **kw}) or 7,
    )
    resp = _client().post(
        "/api/backlog/park",
        json={"question": "CTE vs subquery", "tech_area": "SQL", "context": "during flashcards"},
    )
    assert resp.status_code == 200
    assert captured["tech_area"] == "SQL"
    assert captured["context"] == "during flashcards"


def test_park_failure_returns_500(monkeypatch) -> None:
    monkeypatch.setattr("studyloop.web.routes.backlog.park_topic", lambda q, **kw: None)
    resp = _client().post("/api/backlog/park", json={"question": "x"})
    assert resp.status_code == 500


def test_park_empty_question_rejected() -> None:
    resp = _client().post("/api/backlog/park", json={"question": ""})
    assert resp.status_code == 422  # pydantic min_length


# ---------------------------------------------------------------------------
# GET /api/session/last — resume source
# ---------------------------------------------------------------------------


def test_session_last_returns_latest_row(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.history.sessions.get_last_study_session",
        lambda: {
            "topic": "Python decorators",
            "topic_slug": "python",
            "energy_level": "medium",
            "started_at": "2026-07-12T10:00:00",
            "ended_at": "2026-07-12T10:45:00",
        },
    )
    body = _client().get("/api/session/last").json()
    assert body["topic"] == "Python decorators"
    assert body["energy_level"] == "medium"


def test_session_last_empty_when_no_history(monkeypatch) -> None:
    monkeypatch.setattr("studyloop.history.sessions.get_last_study_session", lambda: None)
    assert _client().get("/api/session/last").json() == {}


# ---------------------------------------------------------------------------
# POST /api/backlog/demote — free a 3-topic slot (park-first friction modal)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /api/backlog/dismiss — mark a parked thought as "not worth it"
# ---------------------------------------------------------------------------


def test_dismiss_happy_path(monkeypatch) -> None:
    """Dismiss sets status='dismissed' and item vanishes from GET /api/backlog."""
    captured: dict = {}
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.dismiss_parked_topic",
        lambda pid: captured.update({"id": pid}) or True,
    )
    resp = _client().post("/api/backlog/dismiss", json={"id": 42})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured["id"] == 42


def test_dismiss_unknown_id_returns_500(monkeypatch) -> None:
    """Dismissing a non-existent id returns 500 (mirrors demote behaviour)."""
    monkeypatch.setattr("studyloop.web.routes.backlog.dismiss_parked_topic", lambda pid: False)
    assert _client().post("/api/backlog/dismiss", json={"id": 9999}).status_code == 500


def test_dismiss_removes_from_backlog(monkeypatch) -> None:
    """Park -> dismiss -> absent from GET /api/backlog round-trip."""
    parked_id = 55
    store: list[dict] = []

    def _fake_park(question, **kw):
        store.append({"id": parked_id, "question": question, "status": "pending"})
        return parked_id

    def _fake_dismiss(pid):
        store[:] = [t for t in store if t["id"] != pid]
        return True

    monkeypatch.setattr("studyloop.web.routes.backlog.park_topic", _fake_park)
    monkeypatch.setattr("studyloop.web.routes.backlog.dismiss_parked_topic", _fake_dismiss)
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": [t for t in store if t["status"] == "pending"],
    )

    client = _client()
    # Park it
    resp = client.post("/api/backlog/park", json={"question": "Learn about MVCC"})
    assert resp.status_code == 200
    # Dismiss it
    resp = client.post("/api/backlog/dismiss", json={"id": parked_id})
    assert resp.status_code == 200
    # Gone from backlog
    body = client.get("/api/backlog").json()
    assert body["active_count"] == 0
    assert body["parking_lot_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/backlog/resolve — mark a parked thought as "I covered this"
# ---------------------------------------------------------------------------


def test_resolve_happy_path(monkeypatch) -> None:
    """Resolve sets status='resolved' — the thought was eventually addressed."""
    captured: dict = {}
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.resolve_parked_topic",
        lambda pid: captured.update({"id": pid}) or True,
    )
    resp = _client().post("/api/backlog/resolve", json={"id": 10})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured["id"] == 10


def test_resolve_unknown_id_returns_500(monkeypatch) -> None:
    monkeypatch.setattr("studyloop.web.routes.backlog.resolve_parked_topic", lambda pid: False)
    assert _client().post("/api/backlog/resolve", json={"id": 9999}).status_code == 500


def test_resolve_removes_from_backlog(monkeypatch) -> None:
    """Park -> resolve -> absent from GET /api/backlog round-trip."""
    parked_id = 77
    store: list[dict] = []

    def _fake_park(question, **kw):
        store.append({"id": parked_id, "question": question, "status": "pending"})
        return parked_id

    def _fake_resolve(pid):
        store[:] = [t for t in store if t["id"] != pid]
        return True

    monkeypatch.setattr("studyloop.web.routes.backlog.park_topic", _fake_park)
    monkeypatch.setattr("studyloop.web.routes.backlog.resolve_parked_topic", _fake_resolve)
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": [t for t in store if t["status"] == "pending"],
    )

    client = _client()
    resp = client.post("/api/backlog/park", json={"question": "CTE recursion"})
    assert resp.status_code == 200
    resp = client.post("/api/backlog/resolve", json={"id": parked_id})
    assert resp.status_code == 200
    body = client.get("/api/backlog").json()
    assert body["active_count"] == 0
    assert body["parking_lot_count"] == 0


# ---------------------------------------------------------------------------
# Route registration — dismiss and resolve are discoverable
# ---------------------------------------------------------------------------


def test_dismiss_route_registered() -> None:
    """POST /api/backlog/dismiss is a registered route."""
    from studyloop.web.app import create_app

    app = create_app(study_dirs=[])
    routes = {
        (r.path, ",".join(r.methods)) for r in app.routes if hasattr(r, "methods") and r.methods
    }
    assert ("/api/backlog/dismiss", "POST") in routes


def test_resolve_route_registered() -> None:
    """POST /api/backlog/resolve is a registered route."""
    from studyloop.web.app import create_app

    app = create_app(study_dirs=[])
    routes = {
        (r.path, ",".join(r.methods)) for r in app.routes if hasattr(r, "methods") and r.methods
    }
    assert ("/api/backlog/resolve", "POST") in routes


# ---------------------------------------------------------------------------
# POST /api/backlog/demote — free a 3-topic slot (park-first friction modal)
# ---------------------------------------------------------------------------


def test_demote_happy_path(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.demote_parked_topic",
        lambda pid: captured.update({"id": pid}) or True,
    )
    resp = _client().post("/api/backlog/demote", json={"id": 7})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured["id"] == 7


def test_demote_failure_returns_500(monkeypatch) -> None:
    monkeypatch.setattr("studyloop.web.routes.backlog.demote_parked_topic", lambda pid: False)
    assert _client().post("/api/backlog/demote", json={"id": 7}).status_code == 500
