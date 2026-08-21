"""Study-plan REST API contract."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyloop.planning import store
from studyloop.web.app import create_app


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


PAYLOAD = {
    "title": "SQL Window Functions",
    "status": "draft",
    "answers": {
        "why": "Ship analytics queries without help",
        "success": ["Write a RANK() query unaided"],
        "topics": ["sql"],
        "out_of_scope": ["Query planner internals"],
        "milestones": [
            {"title": "OVER clause", "concepts": ["window function"]},
            {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
        ],
        "resources": [{"label": "PostgreSQL docs", "url": "https://www.postgresql.org/docs/"}],
    },
}


def _create(client: TestClient, **overrides) -> str:
    payload = {**PAYLOAD, **overrides}
    response = client.post("/api/plans", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["plan"]["plan_id"]


def test_empty_listing_is_well_formed(client: TestClient) -> None:
    body = client.get("/api/plans").json()
    assert body["plans"] == []
    assert body["count"] == 0
    assert "draft" in body["statuses"]


def test_create_and_fetch(client: TestClient) -> None:
    plan_id = _create(client)
    assert plan_id == "sql-window-functions"

    body = client.get(f"/api/plans/{plan_id}").json()
    assert body["plan"]["milestone_total"] == 2
    assert body["mission"]["why"] == "Ship analytics queries without help"
    assert body["milestones"][0]["concepts"] == ["window function"]
    assert body["readiness"]["ready"] is True
    assert "## Mission" in body["markdown"]


def test_create_requires_a_title(client: TestClient) -> None:
    assert client.post("/api/plans", json={"answers": {}}).status_code == 400


def test_create_rejects_non_object_answers(client: TestClient) -> None:
    response = client.post("/api/plans", json={"title": "X", "answers": ["nope"]})
    assert response.status_code == 400


def test_duplicate_title_gets_a_distinct_id(client: TestClient) -> None:
    first = _create(client)
    second = _create(client)
    assert first != second


def test_create_from_raw_markdown(client: TestClient) -> None:
    doc = (
        "---\nid: imported\ntitle: Imported Plan\nstatus: draft\n---\n\n"
        "# Imported Plan\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n"
    )
    response = client.post("/api/plans", json={"markdown": doc})
    assert response.status_code == 201, response.text
    assert response.json()["plan"]["plan_id"] == "imported"


def test_markdown_endpoint_returns_plain_text(client: TestClient) -> None:
    plan_id = _create(client)
    response = client.get(f"/api/plans/{plan_id}/markdown")
    assert response.status_code == 200
    assert response.text.startswith("---")
    assert "text/plain" in response.headers["content-type"]


def test_interview_endpoint(client: TestClient) -> None:
    body = client.get("/api/plans/interview").json()
    assert len(body["questions"]) >= 6
    assert "struggling_topics" in body["seed"]


@pytest.mark.parametrize("phase", ["start", "mid", "end"])
def test_evaluate_preview_does_not_record(client: TestClient, phase: str) -> None:
    plan_id = _create(client)
    body = client.get(f"/api/plans/{plan_id}/evaluate", params={"phase": phase}).json()
    assert body["evaluation"]["phase"] == phase
    assert body["evaluation"]["verdict"] in {"on-track", "at-risk", "stalled", "complete"}
    assert "Plan checkpoint" in body["markdown"]

    fetched = client.get(f"/api/plans/{plan_id}").json()
    assert fetched["checkpoints"] == [], "preview must not append a checkpoint"


def test_evaluate_rejects_an_unknown_phase(client: TestClient) -> None:
    plan_id = _create(client)
    assert client.get(f"/api/plans/{plan_id}/evaluate", params={"phase": "nope"}).status_code == 422
    response = client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "nope"})
    assert response.status_code == 400


def test_record_checkpoint_persists_to_document_and_history(client: TestClient) -> None:
    plan_id = _create(client)
    response = client.post(
        f"/api/plans/{plan_id}/evaluate", json={"phase": "start", "study_id": "sess-9"}
    )
    assert response.status_code == 201
    assert response.json()["recorded"] is True

    fetched = client.get(f"/api/plans/{plan_id}").json()
    assert len(fetched["checkpoints"]) == 1
    assert fetched["checkpoints"][0]["phase"] == "start"
    assert fetched["checkpoints"][0]["study_id"] == "sess-9"

    history = client.get(f"/api/plans/{plan_id}/history").json()
    assert history["checkpoints"], "checkpoint should be in the durable log"


def test_toggle_milestone(client: TestClient) -> None:
    plan_id = _create(client)
    body = client.post(f"/api/plans/{plan_id}/milestones/0/toggle").json()
    assert body["done"] is True
    assert body["plan"]["milestone_done"] == 1
    assert body["plan"]["progress_pct"] == 50

    again = client.post(f"/api/plans/{plan_id}/milestones/0/toggle").json()
    assert again["done"] is False


def test_toggle_out_of_range_is_404(client: TestClient) -> None:
    plan_id = _create(client)
    assert client.post(f"/api/plans/{plan_id}/milestones/42/toggle").status_code == 404


def test_patch_activates_a_ready_plan(client: TestClient) -> None:
    plan_id = _create(client)
    response = client.patch(f"/api/plans/{plan_id}", json={"status": "active"})
    assert response.status_code == 200
    assert response.json()["plan"]["status"] == "active"


def test_patch_refuses_to_activate_an_incomplete_plan(client: TestClient) -> None:
    response = client.post("/api/plans", json={"title": "Vague", "answers": {}})
    plan_id = response.json()["plan"]["plan_id"]

    refused = client.patch(f"/api/plans/{plan_id}", json={"status": "active"})
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["ready"] is False
    assert any("ission" in blocker for blocker in detail["blockers"])

    assert client.get(f"/api/plans/{plan_id}").json()["plan"]["status"] == "draft"


def test_patch_updates_metadata_and_milestones(client: TestClient) -> None:
    plan_id = _create(client)
    response = client.patch(
        f"/api/plans/{plan_id}",
        json={
            "title": "Renamed",
            "topics": ["sql", "analytics"],
            "energy_floor": 99,
            "review_cadence_days": 0,
            "milestones": [{"title": "Only one", "concepts": ["x"], "done": True}],
        },
    )
    assert response.status_code == 200
    plan = response.json()["plan"]
    assert plan["title"] == "Renamed"
    assert plan["topics"] == ["sql", "analytics"]
    # Out-of-range values are clamped, not rejected.
    assert plan["energy_floor"] == 10
    assert plan["review_cadence_days"] == 1
    assert plan["milestone_total"] == 1
    assert plan["milestone_done"] == 1


def test_patch_rejects_bad_values(client: TestClient) -> None:
    plan_id = _create(client)
    assert client.patch(f"/api/plans/{plan_id}", json={"status": "banana"}).status_code == 400
    assert client.patch(f"/api/plans/{plan_id}", json={"title": "   "}).status_code == 400
    assert client.patch(f"/api/plans/{plan_id}", json={"milestones": "nope"}).status_code == 400
    assert client.patch(f"/api/plans/{plan_id}", json={"energy_floor": "high"}).status_code == 400


def test_patch_whole_markdown_document(client: TestClient) -> None:
    plan_id = _create(client)
    doc = client.get(f"/api/plans/{plan_id}/markdown").text
    edited = doc.replace("OVER clause", "OVER clause (edited)")
    response = client.patch(f"/api/plans/{plan_id}", json={"markdown": edited})
    assert response.status_code == 200
    fetched = client.get(f"/api/plans/{plan_id}").json()
    assert "edited" in fetched["milestones"][0]["title"]


def test_patch_rejects_unparseable_markdown(client: TestClient) -> None:
    plan_id = _create(client)
    response = client.patch(f"/api/plans/{plan_id}", json={"markdown": "---\n[bad: yaml: {\n---\n"})
    assert response.status_code in {200, 400}, response.text


def test_missing_plan_is_404_everywhere(client: TestClient) -> None:
    for path in (
        "/api/plans/nope",
        "/api/plans/nope/markdown",
        "/api/plans/nope/history",
        "/api/plans/nope/evaluate",
    ):
        assert client.get(path).status_code == 404, path


def test_path_traversal_is_refused(client: TestClient) -> None:
    assert client.get("/api/plans/..%2F..%2Fetc%2Fpasswd").status_code in {400, 404}


def test_delete_removes_the_plan_but_keeps_history(client: TestClient) -> None:
    plan_id = _create(client)
    client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "start"})
    assert client.delete(f"/api/plans/{plan_id}").status_code == 200
    assert client.get(f"/api/plans/{plan_id}").status_code == 404
    assert client.delete(f"/api/plans/{plan_id}").status_code == 404


def test_status_filter(client: TestClient) -> None:
    plan_id = _create(client)
    client.patch(f"/api/plans/{plan_id}", json={"status": "active"})
    client.post("/api/plans", json={"title": "Another Draft", "answers": {}})

    active = client.get("/api/plans", params={"status": "active"}).json()
    assert [p["plan_id"] for p in active["plans"]] == [plan_id]
    assert client.get("/api/plans", params={"status": "bogus"}).status_code == 422
