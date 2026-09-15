"""Cross-surface parity: the CLI and the Web API refuse activation identically.

Issue #7's invariant is that activation is readiness-gated on *every* entry
path. The seam makes that true by construction; this file checks it from the
outside, the way a learner or an agent would meet it — one refusal through
``studyloop plan status … active``, one through ``PATCH /api/plans/{id}`` —
and asserts the two are the same refusal: the same blockers in the same
order, the same nudges, and no write on either side.
"""

from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("fastapi")

from click.testing import CliRunner
from fastapi.testclient import TestClient

from studyloop.cli import cli
from studyloop.planning import store
from studyloop.web.app import create_app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture
def web() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def shell() -> CliRunner:
    return CliRunner()


def _terminal_bullets(output: str) -> list[str]:
    """The ``•`` lines the CLI prints under "Not ready to activate:", de-styled."""
    bullets: list[str] = []
    for line in _ANSI.sub("", output).splitlines():
        stripped = line.strip()
        if stripped.startswith("•"):
            bullets.append(stripped[1:].strip())
    return bullets


def test_activation_refusal_is_identical_via_cli_and_web(web: TestClient, shell: CliRunner) -> None:
    # One unready draft, created through the Web so both surfaces see the
    # same document.
    created = web.post("/api/plans", json={"title": "Vague", "answers": {}})
    assert created.status_code == 201, created.text
    plan_id = created.json()["plan"]["plan_id"]
    document_before = store.load_plan_text(plan_id)

    # --- Web: PATCH status ------------------------------------------------
    via_web = web.patch(f"/api/plans/{plan_id}", json={"status": "active"})
    assert via_web.status_code == 422, via_web.text
    web_detail = via_web.json()["detail"]
    assert web_detail["message"] == "plan is not ready to activate"
    assert web_detail["ready"] is False
    assert web_detail["plan_id"] == plan_id

    # --- CLI: plan status … active ----------------------------------------
    via_cli = shell.invoke(cli, ["plan", "status", plan_id, "active"])
    assert via_cli.exit_code == 1, via_cli.output
    assert "Cannot activate" in via_cli.output
    assert "Traceback" not in via_cli.output

    # Same blockers, same nudges, same order: the CLI prints blockers then
    # nudges as bullets, so the bullet list is the Web body's two lists joined.
    assert _terminal_bullets(via_cli.output) == web_detail["blockers"] + web_detail["nudges"]
    assert web_detail["blockers"], "the fixture must actually be unready"

    # --- No mutation on either side ---------------------------------------
    assert store.load_plan_text(plan_id) == document_before
    shown = json.loads(shell.invoke(cli, ["plan", "show", plan_id, "--json"]).output)
    assert shown["plan"]["status"] == "draft"
    # And the readiness the CLI reports afterwards is the Web refusal, minus
    # the HTTP-only message key.
    assert shown["readiness"] == {k: v for k, v in web_detail.items() if k != "message"}
    assert web.get("/api/plans", params={"status": "active"}).json()["count"] == 0


def test_every_web_door_into_active_refuses_with_the_same_body(web: TestClient) -> None:
    """Create-with-status, document replacement and status transition agree."""
    refused_create = web.post(
        "/api/plans", json={"title": "Vague", "status": "active", "answers": {}, "plan_id": "vague"}
    )
    assert refused_create.status_code == 422, refused_create.text
    assert store.list_plan_ids() == []

    draft = web.post("/api/plans", json={"title": "Vague", "answers": {}, "plan_id": "vague"})
    assert draft.status_code == 201, draft.text

    refused_transition = web.patch("/api/plans/vague", json={"status": "active"})
    assert refused_transition.status_code == 422, refused_transition.text

    active_doc = store.load_plan_text("vague").replace("status: draft", "status: active")
    refused_replace = web.patch("/api/plans/vague", json={"markdown": active_doc})
    assert refused_replace.status_code == 422, refused_replace.text

    refused_import = web.post("/api/plans", json={"markdown": active_doc, "plan_id": "vague-2"})
    assert refused_import.status_code == 422, refused_import.text

    bodies = [
        r.json()["detail"]
        for r in (refused_create, refused_transition, refused_replace, refused_import)
    ]
    for body in bodies:
        body.pop("plan_id")  # the import names its own id; everything else must match
    assert bodies[0] == bodies[1] == bodies[2] == bodies[3]
    assert bodies[0]["message"] == "plan is not ready to activate"

    assert store.list_plan_ids() == ["vague"]
    assert web.get("/api/plans/vague").json()["plan"]["status"] == "draft"
