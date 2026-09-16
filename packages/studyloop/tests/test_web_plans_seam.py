"""Web plan routes that Phase 2 moved onto the seam: evaluate, toggle, delete.

``tests/test_web_plans.py`` is frozen at its pre-seam assertions (its bodies
must not change: D-3). This file pins what is *new* once those routes
delegate to ``PlanApplication``:

* ``POST /plans/{id}/evaluate`` reports each recording sink and an honest
  ``recorded`` — Bug B (issue #7) was a bare ``true`` over a failed write;
* the milestone checkbox is one idempotent ``SetMilestone`` behind the route —
  but the legacy no-body toggle *request* is read-invert-write, so replaying
  it flips the box twice (council review 2, F3: the earlier "a retried request
  cannot flip a box twice" claim was false and is withdrawn);
* ``DELETE`` is a confirmed ``DeletePlan``: the document and its index row go,
  the durable checkpoint log stays.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyloop.planning import PlanApplication, store
from studyloop.planning import index as index_module
from studyloop.web.app import create_app


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


PAYLOAD = {
    "title": "SQL Window Functions",
    "answers": {
        "why": "Ship analytics queries without help",
        "success": ["Write a RANK() query unaided"],
        "topics": ["sql"],
        "milestones": [
            {"title": "OVER clause", "concepts": ["window function"]},
            {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
        ],
    },
}


def _create(client: TestClient) -> str:
    response = client.post("/api/plans", json=PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["plan"]["plan_id"]


# --- evaluate: both sinks reported, ``recorded`` is honest ---


def test_record_reports_both_sinks_saved(client: TestClient) -> None:
    plan_id = _create(client)
    body = client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "start"}).json()
    assert body["recorded"] is True
    assert body["db_write"] == "saved"
    assert body["document_write"] == "saved"
    assert body["evaluation"]["phase"] == "start"
    assert "Plan checkpoint" in body["markdown"]


def test_record_with_failed_database_write_reports_it_instead_of_lying(
    client: TestClient, monkeypatch
) -> None:
    plan_id = _create(client)
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    response = client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "mid"})

    assert response.status_code == 201, "the evaluation itself succeeded and is returned"
    body = response.json()
    assert body["recorded"] is False
    assert body["db_write"] == "failed"
    assert body["document_write"] == "saved"
    assert "checkpoint not saved to the database" in body["evaluation"]["warnings"]
    fetched = client.get(f"/api/plans/{plan_id}").json()
    assert [c["phase"] for c in fetched["checkpoints"]] == ["mid"], "the document sink was written"


def test_record_without_append_reports_document_sink_not_requested(client: TestClient) -> None:
    plan_id = _create(client)
    body = client.post(
        f"/api/plans/{plan_id}/evaluate", json={"phase": "end", "append_to_plan": False}
    ).json()
    assert body["recorded"] is True
    assert body["db_write"] == "saved"
    assert body["document_write"] == "not_requested"
    assert client.get(f"/api/plans/{plan_id}").json()["checkpoints"] == []
    assert client.get(f"/api/plans/{plan_id}/history").json()["checkpoints"]


def test_preview_is_a_seam_assessment_that_writes_nothing(client: TestClient, monkeypatch) -> None:
    plan_id = _create(client)

    def must_not_be_called(evaluation, *, study_id=""):
        raise AssertionError("a preview must not touch the checkpoint log")

    monkeypatch.setattr(index_module, "record_checkpoint", must_not_be_called)
    body = client.get(f"/api/plans/{plan_id}/evaluate", params={"phase": "end"}).json()
    assert body["evaluation"]["phase"] == "end"
    assert client.get(f"/api/plans/{plan_id}").json()["checkpoints"] == []
    assert client.get(f"/api/plans/{plan_id}/history").json()["checkpoints"] == []


def test_record_on_unready_active_document_is_422_with_nothing_in_either_sink(
    client: TestClient, isolated_plans_dir
) -> None:
    """Council review 2, GPT F2: recording appends to and re-saves the active
    document, so an active-but-unready husk gets the same 422 every other
    write gives, before the database sink is touched."""
    store.plans_dir()
    (isolated_plans_dir / "husk.md").write_text(
        "---\nid: husk\ntitle: Husk\nstatus: active\ntopics: [sql]\n---\n\n"
        "# Husk\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )
    before = client.get("/api/plans/husk/markdown").text

    refused = client.post("/api/plans/husk/evaluate", json={"phase": "start"})

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["ready"] is False
    assert client.get("/api/plans/husk/markdown").text == before
    assert client.get("/api/plans/husk/history").json()["checkpoints"] == []
    # Preview is still allowed: it persists no document.
    assert client.get("/api/plans/husk/evaluate", params={"phase": "start"}).status_code == 200


def test_record_unknown_phase_is_the_seams_400_after_the_404(client: TestClient) -> None:
    assert client.post("/api/plans/nope/evaluate", json={"phase": "nope"}).status_code == 404
    plan_id = _create(client)
    assert client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "nope"}).status_code == 400


# --- toggle: one SetMilestone behind the checkbox; the request itself is not replay-safe ---


def test_legacy_toggle_repeated_requests_flip_twice(client: TestClient, monkeypatch) -> None:
    """Each request applies exactly one ``SetMilestone`` whose ``done`` is the
    opposite of the state it read. That is what makes the *intent* idempotent
    and the *request* not: the same POST twice flips the box and flips it back
    — the legacy toggle contract, pinned here so nobody claims replay safety
    for it again (council review 2, F3). Replay safety needs a desired-state
    request (``PATCH`` ``milestones`` / CLI ``--done``), not this route."""
    plan_id = _create(client)
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    first = client.post(f"/api/plans/{plan_id}/milestones/1/toggle").json()
    assert first["done"] is True
    assert first["plan"]["milestone_done"] == 1
    (intent,) = seen
    assert type(intent).__name__ == "SetMilestone"
    assert (intent.plan_id, intent.index, intent.done) == (plan_id, 1, True)  # type: ignore[attr-defined]

    second = client.post(f"/api/plans/{plan_id}/milestones/1/toggle").json()
    assert second["done"] is False, "a replayed toggle flips again — it is not retry-safe"
    assert second["plan"]["milestone_done"] == 0
    assert seen[1].done is False  # type: ignore[attr-defined]
    assert len(seen) == 2, "one SetMilestone per request, no route-side write"


@pytest.mark.parametrize("index", [42, -1])
def test_toggle_out_of_range_is_the_seams_404_and_writes_nothing(
    client: TestClient, index: int
) -> None:
    plan_id = _create(client)
    before = client.get(f"/api/plans/{plan_id}/markdown").text
    assert client.post(f"/api/plans/{plan_id}/milestones/{index}/toggle").status_code == 404
    assert client.get(f"/api/plans/{plan_id}/markdown").text == before


# --- delete: confirmed by the verb, history retained ---


def test_delete_is_a_confirmed_delete_plan_that_keeps_history(
    client: TestClient, monkeypatch
) -> None:
    plan_id = _create(client)
    assert client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "start"}).json()["recorded"]
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    response = client.delete(f"/api/plans/{plan_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "plan_id": plan_id}
    (intent,) = seen
    assert type(intent).__name__ == "DeletePlan"
    assert intent.confirmed is True  # type: ignore[attr-defined]
    assert client.get(f"/api/plans/{plan_id}").status_code == 404
    assert client.delete(f"/api/plans/{plan_id}").status_code == 404
    assert [row["phase"] for row in index_module.checkpoint_history(plan_id)] == ["start"]
    assert [row["plan_id"] for row in index_module.indexed_plans()] == []


def test_delete_malformed_id_is_the_seams_400(client: TestClient) -> None:
    # A space fails the store's id grammar; the seam raises InvalidPlanId and the
    # route maps it — the same 400 every other route gives a malformed id.
    assert client.delete("/api/plans/not%20an%20id").status_code == 400
