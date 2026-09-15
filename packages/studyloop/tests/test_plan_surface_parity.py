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
from studyloop.planning import PlanApplication, store
from studyloop.planning.errors import (
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    PlanConflict,
    PlanError,
    PlanNotReady,
)
from studyloop.planning.models import StudyPlan
from studyloop.planning.views import ReadinessView
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


# --- Council review 1 (2026-09-15), findings F1 / F1b / F4 ----------------------
#
# The spec's requirement is about the RESULTING document: "every Web API path
# that can leave a study plan in the active state checks the document that
# would be saved". A PATCH that combines a status transition with field edits
# is one such path; so is a field-only edit that strips the milestones from a
# plan that is already active. Both got past the Phase 1 seam because the
# route composed a seam transition with a second, unguarded save.

READY_PAYLOAD = {
    "title": "Ready Plan",
    "plan_id": "ready-plan",
    "answers": {
        "why": "Ship analytics queries without help",
        "success": ["Write a RANK() query unaided"],
        "topics": ["sql"],
        "milestones": [{"title": "OVER clause", "concepts": ["window function"]}],
    },
}


def test_mixed_patch_activation_that_strips_milestones_is_refused_without_write(
    web: TestClient,
) -> None:
    """F1: `{"status": "active", "milestones": []}` must be judged as one resulting document."""
    assert web.post("/api/plans", json=READY_PAYLOAD).status_code == 201
    before = store.load_plan_text("ready-plan")

    refused = web.patch("/api/plans/ready-plan", json={"status": "active", "milestones": []})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["ready"] is False

    assert store.load_plan_text("ready-plan") == before
    shown = web.get("/api/plans/ready-plan").json()
    assert shown["plan"]["status"] == "draft"
    assert shown["plan"]["milestone_total"] == 1


def test_mixed_patch_activation_that_adds_the_missing_milestones_succeeds(web: TestClient) -> None:
    """F1 mirror: readiness is judged on the resulting document, so adding what was
    missing in the same request activates in one write."""
    unready = {**READY_PAYLOAD, "plan_id": "nearly", "answers": {**READY_PAYLOAD["answers"]}}
    unready["answers"].pop("milestones")
    assert web.post("/api/plans", json=unready).status_code == 201
    assert web.get("/api/plans/nearly").json()["readiness"]["ready"] is False

    activated = web.patch(
        "/api/plans/nearly",
        json={"status": "active", "milestones": [{"title": "First", "concepts": ["a"]}]},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["plan"]["status"] == "active"
    assert activated.json()["readiness"]["ready"] is True


def test_field_only_patch_cannot_make_an_active_plan_unready(web: TestClient) -> None:
    """F1b: an already-active plan whose milestones are removed would be active-but-unready."""
    assert web.post("/api/plans", json=READY_PAYLOAD).status_code == 201
    assert web.patch("/api/plans/ready-plan", json={"status": "active"}).status_code == 200
    before = store.load_plan_text("ready-plan")

    refused = web.patch("/api/plans/ready-plan", json={"milestones": []})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["ready"] is False

    assert store.load_plan_text("ready-plan") == before
    assert web.get("/api/plans/ready-plan").json()["plan"]["milestone_total"] == 1


def test_duplicate_id_is_a_conflict_even_when_the_new_document_is_unready_active(
    web: TestClient,
) -> None:
    """F4: the delta spec's "Duplicate id without overwrite" scenario promises 409
    unconditionally; identity is checked before readiness."""
    assert web.post("/api/plans", json=READY_PAYLOAD).status_code == 201
    before = store.load_plan_text("ready-plan")

    clash = web.post(
        "/api/plans",
        json={"title": "Ready Plan", "plan_id": "ready-plan", "status": "active", "answers": {}},
    )
    assert clash.status_code == 409, clash.text
    assert store.load_plan_text("ready-plan") == before


# --- Council review 1, F3: the CLI maps every seam refusal, on every command ------
#
# Click's ``--status`` Choice already refuses an unknown filter, so the seam
# refusal below is simulated: the point is that a domain error reaching
# ``plan list`` is a one-line message and exit 1, never a traceback.


def test_plan_list_domain_refusal_exits_without_traceback(shell: CliRunner, monkeypatch) -> None:
    def refuse(self: PlanApplication, *, status: str | None = None):
        msg = "status must be one of ('draft', 'active', 'paused', 'complete', 'abandoned')"
        raise InvalidField(msg)

    monkeypatch.setattr(PlanApplication, "browse", refuse)

    result = shell.invoke(cli, ["plan", "list", "--status", "draft"])
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "status must be one of" in result.output


@pytest.mark.parametrize(
    ("refusal", "expected"),
    [
        (PlanConflict("study plan 'demo' already exists"), "already exists"),
        (InvalidField("title cannot be empty"), "Invalid value: title cannot be empty"),
        (InvalidPlanId("invalid plan id: 'demo'"), "Invalid plan id"),
        (InvalidMilestone("no milestone at index 7"), "No such milestone"),
        (
            PlanNotReady(ReadinessView.from_plan(StudyPlan(plan_id="demo", title="Demo"))),
            "Cannot activate 'demo'",
        ),
    ],
    ids=["conflict", "invalid-field", "invalid-id", "invalid-milestone", "not-ready"],
)
def test_cli_maps_each_seam_refusal_to_a_specific_message(
    shell: CliRunner, monkeypatch, refusal: PlanError, expected: str
) -> None:
    """Design §2: each domain error has its own CLI line; none falls through to
    the bare exception text or a traceback."""

    def refuse(self: PlanApplication, intent):
        raise refusal

    monkeypatch.setattr(PlanApplication, "apply", refuse)

    result = shell.invoke(cli, ["plan", "status", "demo", "active"])
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert expected in _ANSI.sub("", result.output)
