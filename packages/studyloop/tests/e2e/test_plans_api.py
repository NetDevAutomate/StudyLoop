"""Study-plan API lifecycle — the whole surface against a real server.

WHY THIS FILE EXISTS
--------------------
``tests/test_web_plans.py`` covers these endpoints with a ``TestClient``, which
proves the handlers work in-process. The mandatory coverage gate
(``tests/test_e2e_coverage_gate.py``) asks for more: that each route survives
real ASGI serving, real config loading, real middleware and a real event loop —
which is where StudyLoop's session-start bugs have historically lived.

So this module walks the same surface the way a client does, over HTTP, against
a subprocess server with an isolated config and plans directory: create a plan,
read it back as structure and as Markdown, evaluate it at all three checkpoints,
record one, tick a milestone, activate it, then delete it.

Ordering matters — the tests share one server and one plan, and each phase
builds on the previous, so they are numbered.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_plans_api.py -m e2e
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

PORT = 18612
PLAN_TITLE = "Ship a Glue ETL Job"
PLAN_ID = "ship-a-glue-etl-job"


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    """Server with an isolated plans directory; yields a request helper."""
    import requests

    root = tmp_path_factory.mktemp("plans-api")
    plans_dir = root / "study-plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    env = launch_env(root, PORT, plans_dir=plans_dir)

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


def test_01_listing_starts_empty(api) -> None:
    """GET /api/plans — an isolated plans dir really is isolated."""
    res = api.get("/api/plans")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plans"] == [], f"plans dir not isolated: {body}"
    assert "draft" in body["statuses"]


def test_02_interview_is_served(api) -> None:
    """GET /api/plans/interview — questions plus history-derived seeds."""
    res = api.get("/api/plans/interview")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["questions"]) >= 6
    assert {"key", "prompt", "why", "required", "multi"} <= set(body["questions"][0])
    assert "struggling_topics" in body["seed"]


def test_03_create_a_plan(api) -> None:
    """POST /api/plans — create from interview answers."""
    res = api.post(
        "/api/plans",
        json={
            "title": PLAN_TITLE,
            "status": "draft",
            "answers": {
                "why": "Own the nightly customer-events pipeline without pairing.",
                "success": ["Deploy a Glue job unaided"],
                "topics": ["data-engineering"],
                "out_of_scope": ["EMR tuning"],
                "milestones": [
                    {"title": "Job anatomy", "concepts": ["glue job", "job bookmark"]},
                    {"title": "Write the transform", "concepts": ["dynamicframe"]},
                ],
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["plan"]["plan_id"] == PLAN_ID
    assert body["plan"]["milestone_total"] == 2
    assert body["readiness"]["ready"] is True


def test_04_read_structure_and_markdown(api) -> None:
    """GET /api/plans/{id} and /markdown — both projections of one document."""
    res = api.get(f"/api/plans/{PLAN_ID}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mission"]["why"].startswith("Own the nightly")
    assert [m["title"] for m in body["milestones"]] == ["Job anatomy", "Write the transform"]
    assert "## Mission" in body["markdown"]

    raw = api.get(f"/api/plans/{PLAN_ID}/markdown")
    assert raw.status_code == 200
    assert "text/plain" in raw.headers["content-type"]
    assert raw.text.startswith("---"), "frontmatter missing from the raw document"


@pytest.mark.parametrize("phase", ["start", "mid", "end"])
def test_05_evaluate_each_checkpoint(api, phase: str) -> None:
    """GET /api/plans/{id}/evaluate — preview must not mutate the plan."""
    res = api.get(f"/api/plans/{PLAN_ID}/evaluate", params={"phase": phase})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["evaluation"]["phase"] == phase
    assert body["evaluation"]["verdict"] in {"on-track", "at-risk", "stalled", "complete"}
    assert "Plan checkpoint" in body["markdown"]

    after = api.get(f"/api/plans/{PLAN_ID}").json()
    assert after["checkpoints"] == [], "a preview recorded a checkpoint"


def test_06_record_a_checkpoint_and_read_history(api) -> None:
    """POST /api/plans/{id}/evaluate then GET /history — durable both sides."""
    res = api.post(
        f"/api/plans/{PLAN_ID}/evaluate", json={"phase": "start", "study_id": "e2e-sess"}
    )
    assert res.status_code == 201, res.text
    assert res.json()["recorded"] is True

    doc = api.get(f"/api/plans/{PLAN_ID}").json()
    assert len(doc["checkpoints"]) == 1
    assert doc["checkpoints"][0]["phase"] == "start"
    assert doc["checkpoints"][0]["study_id"] == "e2e-sess"

    history = api.get(f"/api/plans/{PLAN_ID}/history")
    assert history.status_code == 200
    assert history.json()["checkpoints"], "checkpoint missing from the durable log"


def test_07_toggle_a_milestone(api) -> None:
    """POST /api/plans/{id}/milestones/{index}/toggle — progress moves."""
    res = api.post(f"/api/plans/{PLAN_ID}/milestones/0/toggle")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["done"] is True
    assert body["plan"]["milestone_done"] == 1
    assert body["plan"]["progress_pct"] == 50

    assert api.post(f"/api/plans/{PLAN_ID}/milestones/99/toggle").status_code == 404


def test_08_patch_activates_only_a_ready_plan(api) -> None:
    """PATCH /api/plans/{id} — the readiness refusal survives real serving."""
    ok = api.patch(f"/api/plans/{PLAN_ID}", json={"status": "active"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["plan"]["status"] == "active"

    vague = api.post("/api/plans", json={"title": "Vague Plan", "answers": {}})
    assert vague.status_code == 201
    vague_id = vague.json()["plan"]["plan_id"]

    refused = api.patch(f"/api/plans/{vague_id}", json={"status": "active"})
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["ready"] is False
    assert any("ission" in b for b in detail["blockers"])
    assert api.get(f"/api/plans/{vague_id}").json()["plan"]["status"] == "draft"


def test_09_status_filter_and_missing_plan(api) -> None:
    """GET /api/plans?status= narrows; an unknown id is a clean 404."""
    active = api.get("/api/plans", params={"status": "active"}).json()
    assert [p["plan_id"] for p in active["plans"]] == [PLAN_ID]

    for path in (
        "/api/plans/does-not-exist",
        "/api/plans/does-not-exist/markdown",
        "/api/plans/does-not-exist/history",
        "/api/plans/does-not-exist/evaluate",
    ):
        assert api.get(path).status_code == 404, path


def test_10_delete_removes_the_plan(api) -> None:
    """DELETE /api/plans/{id} — gone, and idempotent thereafter."""
    assert api.delete(f"/api/plans/{PLAN_ID}").status_code == 200
    assert api.get(f"/api/plans/{PLAN_ID}").status_code == 404
    assert api.delete(f"/api/plans/{PLAN_ID}").status_code == 404
