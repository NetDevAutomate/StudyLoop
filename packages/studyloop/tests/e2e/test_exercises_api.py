"""Exercise-set API lifecycle — the whole surface against a real server.

WHY THIS FILE EXISTS
--------------------
``tests/test_web_exercises.py`` covers these endpoints with a ``TestClient``,
which proves the handlers work in-process. The mandatory coverage gate
(``tests/test_e2e_coverage_gate.py``) asks for more: that each route survives
real ASGI serving, real config loading, real middleware and a real event loop.

Until 0.1.0 that full-stack coverage came from
``tests/e2e/test_journey_exercises.py``, which drove the exercises WEB PANEL.
That panel is not part of 0.1.0 — none of the five testids it used exist in
``web/static`` — so the journey is quarantined and its coverage went with it.
The API itself still ships, so it still needs walking; it just no longer needs
a browser to do it. This module is that walk, and it is the reason the gate
stayed green without a single entry being added to
``ROUTE_NO_FULL_STACK_WAIVERS``.

Ordering matters — the tests share one server and one set, each phase building
on the previous, so they are numbered.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_exercises_api.py -m e2e
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

PORT = 18617
TOPIC = "closure state"
REFERENCE = """def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
"""


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    """Server with an isolated exercises directory; yields a request helper."""
    import requests

    root = tmp_path_factory.mktemp("exercises-api")

    # launch_env builds a hermetic world rooted here and redirects
    # STUDYLOOP_SESSION_DIR with it, so exercise documents land under this
    # tmp root rather than the learner's real ~/.config/studyloop. There is no
    # exercises_dir parameter and none is needed.
    env = launch_env(root, PORT, extra_args=["--dev"])

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


#: Set id created by test_02 and used by every later phase.
_STATE: dict[str, str] = {}


def test_01_listing_is_served(api) -> None:
    """GET /api/exercises — the list endpoint answers over real HTTP."""
    res = api.get("/api/exercises")
    assert res.status_code == 200, res.text
    assert "sets" in res.json(), res.text


def test_02_create_a_set(api) -> None:
    """POST /api/exercises — authoring a set with a rubric and a reference."""
    res = api.post(
        "/api/exercises",
        json={
            "topic": TOPIC,
            "plan_id": "python",
            "concepts": ["closures"],
            "requirements": ["`make_counter()` returns a callable"],
            "rubric": [
                {
                    "title": "Defines the factory function",
                    "weight": 1,
                    "check": r"def\s+make_counter",
                    "ask": "What has to exist before anything can be returned",
                },
                {
                    "title": "Keeps state in the enclosing scope",
                    "weight": 3,
                    "check": r"nonlocal\s+\w+",
                    "ask": "Where does the count have to live to survive between calls",
                },
            ],
            "reference_solution": REFERENCE,
            "questions": [
                {
                    "prompt": "What keeps a closure's variable alive?",
                    "choices": [
                        {"text": "The global namespace", "why": "globals are shared"},
                        {"text": "A cell object referenced by the function", "correct": True},
                    ],
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()["set"]
    assert created["set_id"], created
    _STATE["set_id"] = created["set_id"]


def test_03_read_it_back_without_the_answer_key(api) -> None:
    """GET /api/exercises/{set_id} — the default read withholds the answers.

    The in-process suite asserts this too. Re-asserting it here is deliberate:
    the guarantee is about what leaves the process over the wire, so proving it
    through real ASGI serving is the form that actually matters.
    """
    res = api.get(f"/api/exercises/{_STATE['set_id']}")
    assert res.status_code == 200, res.text
    text = res.text
    assert "nonlocal count" not in text, "reference solution crossed the network"
    assert '"correct"' not in text, "correct flag crossed the network"


def test_04_authors_can_ask_for_the_reference(api) -> None:
    """GET /api/exercises/{set_id}?include_reference=true — the author path."""
    res = api.get(f"/api/exercises/{_STATE['set_id']}", params={"include_reference": "true"})
    assert res.status_code == 200, res.text
    assert "nonlocal" in res.text, "author read should carry the reference"


def test_05_markdown_is_redacted_by_default(api) -> None:
    """GET /api/exercises/{set_id}/markdown — not a one-click answer key."""
    res = api.get(f"/api/exercises/{_STATE['set_id']}/markdown")
    assert res.status_code == 200, res.text
    assert "nonlocal count" not in res.text, "markdown leaked the reference"


def test_06_review_scores_an_attempt(api) -> None:
    """POST /api/exercises/{set_id}/review — scoring over real HTTP.

    Submitting the reference itself must score at the top of the band: it
    satisfies every rubric check by construction, so anything less would mean
    the rubric never ran.
    """
    res = api.post(
        f"/api/exercises/{_STATE['set_id']}/review",
        json={"kind": "blank_slate", "submission": REFERENCE},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    review = body["review"]
    assert review["band"] == "strong", review
    assert review["confidence"] == "mastered", review
    assert "Exercise review" in body["markdown"], body["markdown"][:120]


def test_07_review_rejects_an_unknown_kind(api) -> None:
    """The 400 path is part of the contract, so walk it too."""
    res = api.post(
        f"/api/exercises/{_STATE['set_id']}/review",
        json={"kind": "not-a-kind", "submission": ""},
    )
    assert res.status_code == 400, res.text


def test_08_patch_updates_notes(api) -> None:
    """PATCH /api/exercises/{set_id} — accepts notes without a full rewrite."""
    res = api.patch(
        f"/api/exercises/{_STATE['set_id']}",
        json={"notes": "Revisit after the decorators milestone."},
    )
    assert res.status_code == 200, res.text


def test_09_the_set_appears_in_the_listing(api) -> None:
    """GET /api/exercises — the created set is really listed."""
    res = api.get("/api/exercises")
    assert res.status_code == 200, res.text
    ids = [s.get("set_id") for s in res.json().get("sets", [])]
    assert _STATE["set_id"] in ids, ids


def test_10_delete_removes_it(api) -> None:
    """DELETE /api/exercises/{set_id} — and a second delete is a 404."""
    res = api.delete(f"/api/exercises/{_STATE['set_id']}")
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is True

    again = api.delete(f"/api/exercises/{_STATE['set_id']}")
    assert again.status_code == 404, again.text
