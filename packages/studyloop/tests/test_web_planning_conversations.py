"""Browser planning vertical slice: brain dump through exact learner approval."""

from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from studyloop.planning import Goal, Milestone, Mission, MutationIntent, PlanningRef, StudyPlan
from studyloop.planning.model_port import (
    MODEL_WIRE_VERSION,
    ModelTextDelta,
    ModelToolCall,
    ModelTurnCompleted,
)
from studyloop.planning.runtime import planning_repository
from studyloop.planning.store import PLANS_DIR_ENV
from studyloop.web.app import create_app
from studyloop.web.learner_auth import websocket_origin_matches
from studyloop.web.planning_services import create_planning_services


class _ProposalModel:
    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        round_number = len(self.requests)
        if round_number == 1:
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "prepare-1",
                "prepare_plan",
                {},
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                2,
                "tool_calls",
            )
            return
        prior = json.loads(request.messages[-1]["content"])["payload"]
        if round_number == 2:
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "submit-1",
                "submit_plan_proposal",
                {
                    "run_id": prior["run_id"],
                    "brief_context_digest": prior["brief_context_digest"],
                    "draft": {
                        "title": "Understand async Python",
                        "mission": {
                            "why": "Build reliable data pipelines",
                            "success": ["Explain one concurrent pipeline trace"],
                        },
                        "goals": [
                            {
                                "alias": "trace",
                                "title": "Trace async execution",
                                "reason": "The learner wants practical understanding",
                                "alignment_rationale": "Tracing makes progress observable",
                            }
                        ],
                        "milestones": [
                            {
                                "alias": "trace-one",
                                "goal_alias": "trace",
                                "title": "Trace one producer-consumer run",
                            }
                        ],
                        "evidence_dispositions": [],
                        "next_action": "Trace one producer-consumer run",
                    },
                },
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                2,
                "tool_calls",
            )
            return
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            "I have prepared one focused plan for your review.",
        )
        yield ModelTurnCompleted(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            2,
            "stop",
        )


class _HangingModel:
    async def stream(self, request):
        import asyncio

        await asyncio.sleep(30)
        yield request  # pragma: no cover


class _ClarificationModel:
    async def stream(self, request):
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            "Which practical project matters most to you?",
        )
        yield ModelTurnCompleted(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            2,
            "stop",
        )


@pytest.fixture
def planning_browser(tmp_path, monkeypatch):
    monkeypatch.setenv(PLANS_DIR_ENV, str(tmp_path / "plans"))
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    model = _ProposalModel()
    services = create_planning_services(model=model)
    app = create_app(planning_services=services)
    with TestClient(app, base_url="http://127.0.0.1:8765") as browser:
        browser.get(
            "/",
            headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none"},
        )
        browser.headers.update(
            {
                "Origin": "http://127.0.0.1:8765",
                "Sec-Fetch-Site": "same-origin",
                "X-CSRF-Token": browser.cookies.get("studyloop_csrf", ""),
            }
        )
        yield browser, services, model


def _wait_for_proposal(browser: TestClient, conversation_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = browser.get(f"/api/planning/conversations/{conversation_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["proposal"] is not None:
            return body
        time.sleep(0.02)
    raise AssertionError("proposal did not become durable")


def test_create_context_turn_proposal_and_exact_approval(planning_browser) -> None:
    browser, services, model = planning_browser
    session_db = os.environ["STUDYLOOP_DB"]
    with sqlite3.connect(session_db) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS study_progress(marker TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS sessions(marker TEXT)")
        connection.execute("INSERT INTO study_progress VALUES ('unchanged')")
        connection.execute("INSERT INTO sessions VALUES ('unchanged')")
        before_learning_state = (
            connection.execute("SELECT * FROM study_progress").fetchall(),
            connection.execute("SELECT * FROM sessions").fetchall(),
        )
    created = browser.post("/api/planning/conversations", json={"mode": "create"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["privacy_notice"]["automatic_expiry"] is False
    assert body["csrf_token"]
    conversation_id = body["conversation_id"]

    context = browser.post(
        f"/api/planning/conversations/{conversation_id}/context",
        json={
            "kind": "pasted",
            "label": "/Users/me/private/course.md",
            "content": "Course outline: coroutines, tasks, queues.",
        },
    )
    assert context.status_code == 200, context.text
    assert context.json()["label"] == "selected text context"
    assert context.json()["tier"] == 4
    upload = browser.post(
        f"/api/planning/conversations/{conversation_id}/context",
        files={"file": ("course.md", b"Queues and cancellation", "text/markdown")},
        data={"label": "course.md"},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["size"] == len(b"Queues and cancellation")

    turn_body = {
        "text": "I know Python but async feels vague. Help me make it practical.",
        "idempotency_key": "first-brain-dump",
    }
    accepted = browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json=turn_body,
    )
    assert accepted.status_code == 202, accepted.text
    turn = services.store.get_turn(conversation_id, accepted.json()["turn_id"])
    assert turn.learner_text.startswith("I know Python")

    conversation = _wait_for_proposal(browser, conversation_id)
    proposal = conversation["proposal"]
    assert proposal["title"] == "Understand async Python"
    assert "```mermaid" in proposal["markdown"]
    assert proposal["plan"]["goals"][0]["goal_id"]
    assert proposal["plan"] == proposal["structural_diff"]["after"]
    assert proposal["structural_diff"]["before"] is None
    assert proposal["summary"]["title"] == proposal["title"]
    assert conversation["messages"][-1]["role"] == "assistant"
    assert len(model.requests) == 3
    replayed_turn = browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json=turn_body,
    )
    assert replayed_turn.json()["turn_id"] == accepted.json()["turn_id"]
    assert replayed_turn.json()["status"] == "completed"
    assert len(model.requests) == 3

    decision = {
        "conversation_id": conversation_id,
        "proposal_digest": proposal["proposal_digest"],
        "outcome": "approve",
        "idempotency_key": "approve-displayed-proposal",
        "base": proposal["base"],
    }
    approved = browser.post(
        f"/api/planning/proposals/{proposal['proposal_id']}/decision",
        json=decision,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "applied"
    replay = browser.post(
        f"/api/planning/proposals/{proposal['proposal_id']}/decision",
        json=decision,
    )
    assert replay.json() == approved.json()
    assert browser.get("/api/plans").json()["capacity"]["current"] == 1
    with sqlite3.connect(session_db) as connection:
        after_learning_state = (
            connection.execute("SELECT * FROM study_progress").fetchall(),
            connection.execute("SELECT * FROM sessions").fetchall(),
        )
    assert after_learning_state == before_learning_state


def test_revise_conversation_rejection_preserves_canonical_plan(planning_browser) -> None:
    browser, _services, _model = planning_browser
    plan = StudyPlan(
        "existing-plan",
        "Existing plan",
        mission=Mission(why="Keep learning", success=["Explain the system"]),
        goals=[Goal("existing-goal", "Explain it", "Useful", "Aligned")],
        milestones=[
            Milestone(
                "Trace it",
                milestone_id="existing-milestone",
                goal_id="existing-goal",
            )
        ],
    )
    planning_repository().commit(
        MutationIntent(
            "seed-existing",
            "test",
            "seed-existing",
            operation="create",
            ref=PlanningRef(plan.plan_id),
            plan=plan,
        )
    )
    path = planning_repository().paths.plans / "existing-plan.md"
    before = path.read_bytes()
    created = browser.post(
        "/api/planning/conversations",
        json={"mode": "revise", "plan_id": "existing-plan"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation_id"]
    accepted = browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json={"text": "Make this plan more practical", "idempotency_key": "revise"},
    )
    assert accepted.status_code == 202, accepted.text
    proposal = _wait_for_proposal(browser, conversation_id)["proposal"]
    assert proposal["mode"] == "revise"
    assert proposal["structural_diff"]["before"]["plan_id"] == "existing-plan"
    assert proposal["structural_diff"]["after"] == proposal["plan"]
    assert {item["path"] for item in proposal["structural_diff"]["changes"]} >= {
        "/goals",
        "/milestones",
        "/title",
    }
    rejected = browser.post(
        f"/api/planning/proposals/{proposal['proposal_id']}/decision",
        json={
            "conversation_id": conversation_id,
            "proposal_digest": proposal["proposal_digest"],
            "outcome": "reject",
            "idempotency_key": "reject-revision",
            "base": proposal["base"],
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["outcome"] == "rejected"
    assert path.read_bytes() == before


def test_capacity_refuses_create_before_model_egress(planning_browser) -> None:
    browser, _services, model = planning_browser
    repository = planning_repository()
    for index in range(3):
        plan = StudyPlan(
            f"plan-{index}",
            f"Plan {index}",
            mission=Mission(why="Capacity fixture", success=["Exists"]),
            goals=[Goal(f"goal-{index}", "Goal", "Reason", "Aligned")],
            milestones=[
                Milestone("Step", milestone_id=f"milestone-{index}", goal_id=f"goal-{index}")
            ],
        )
        repository.commit(
            MutationIntent(
                f"seed-{index}",
                "test",
                f"seed-{index}",
                operation="create",
                ref=PlanningRef(plan.plan_id),
                plan=plan,
            )
        )

    refused = browser.post("/api/planning/conversations", json={"mode": "create"})
    assert refused.status_code == 409
    assert model.requests == []


def test_loopback_session_still_requires_same_origin(planning_browser) -> None:
    browser, _services, _model = planning_browser
    refused = browser.post(
        "/api/planning/conversations",
        json={"mode": "create"},
        headers={
            "Origin": "https://evil.example",
            "Sec-Fetch-Site": "cross-site",
            "X-CSRF-Token": browser.cookies.get("studyloop_csrf", ""),
        },
    )
    assert refused.status_code == 403


def test_safe_websocket_replay_does_not_expose_raw_capability_payload(
    planning_browser,
) -> None:
    browser, _services, _model = planning_browser
    created = browser.post("/api/planning/conversations", json={"mode": "create"}).json()
    conversation_id = created["conversation_id"]
    browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json={"text": "Help me understand async Python", "idempotency_key": "ws"},
    )
    _wait_for_proposal(browser, conversation_id)
    cookie = (
        f"studyloop_learner_session={browser.cookies.get('studyloop_learner_session')}; "
        f"studyloop_csrf={browser.cookies.get('studyloop_csrf')}"
    )

    with browser.websocket_connect(
        f"/api/planning/conversations/{conversation_id}/events?after_seq=0"
        f"&csrf_token={created['csrf_token']}",
        headers={
            "Origin": "http://127.0.0.1:8765",
            "Host": "127.0.0.1:8765",
            "Cookie": cookie,
        },
    ) as websocket:
        events = [websocket.receive_json() for _ in range(3)]
    proposal_event = next(item for item in events if item["type"] == "proposal_ready")
    assert set(proposal_event) == {"sequence", "type", "data"}
    assert set(proposal_event["data"]) <= {"name", "status", "proposal_id"}
    assert "result" not in json.dumps(proposal_event)


def test_planning_websocket_requires_exact_origin_session_and_csrf(planning_browser) -> None:
    browser, _services, _model = planning_browser
    created = browser.post("/api/planning/conversations", json={"mode": "create"}).json()
    path = (
        f"/api/planning/conversations/{created['conversation_id']}/events?after_seq=0"
        f"&csrf_token={created['csrf_token']}"
    )
    cookie = (
        f"studyloop_learner_session={browser.cookies.get('studyloop_learner_session')}; "
        f"studyloop_csrf={browser.cookies.get('studyloop_csrf')}"
    )
    with (
        pytest.raises(WebSocketDisconnect) as wrong_port,
        browser.websocket_connect(
            path,
            headers={
                "Origin": "http://127.0.0.1:9999",
                "Host": "127.0.0.1:8765",
                "Cookie": cookie,
            },
        ),
    ):
        pass
    assert wrong_port.value.code == 1008

    stranger = TestClient(browser.app, base_url="http://127.0.0.1:8765")
    with (
        pytest.raises(WebSocketDisconnect) as sessionless,
        stranger.websocket_connect(
            path,
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"},
        ),
    ):
        pass
    assert sessionless.value.code == 1008


@pytest.mark.parametrize(
    ("origin", "scheme", "host", "expected"),
    [
        ("http://127.0.0.1:8765", "ws", "127.0.0.1:8765", True),
        ("http://127.0.0.1:9999", "ws", "127.0.0.1:8765", False),
        ("https://127.0.0.1:8765", "ws", "127.0.0.1:8765", False),
        ("https://study.local", "wss", "study.local", True),
    ],
)
def test_websocket_origin_predicate_is_exact(
    origin: str, scheme: str, host: str, expected: bool
) -> None:
    assert websocket_origin_matches(origin, websocket_scheme=scheme, host=host) is expected


def test_newer_learner_turn_retires_old_proposal_and_blocks_decision(
    planning_browser,
) -> None:
    browser, services, _model = planning_browser
    created = browser.post("/api/planning/conversations", json={"mode": "create"}).json()
    conversation_id = created["conversation_id"]
    browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json={"text": "Help me learn async Python", "idempotency_key": "initial"},
    )
    old = _wait_for_proposal(browser, conversation_id)["proposal"]
    assert services.runtime is not None
    services.runtime.model = _HangingModel()
    replacement = browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json={"text": "Make the milestones more practical", "idempotency_key": "revision"},
    )
    assert replacement.status_code == 202
    snapshot = browser.get(f"/api/planning/conversations/{conversation_id}").json()
    assert snapshot["proposal"] is None
    assert snapshot["phase"] == "thinking"
    stale = browser.post(
        f"/api/planning/proposals/{old['proposal_id']}/decision",
        json={
            "conversation_id": conversation_id,
            "proposal_digest": old["proposal_digest"],
            "outcome": "approve",
            "idempotency_key": "stale-approval",
            "base": old["base"],
        },
    )
    assert stale.status_code == 409
    assert "retired" in stale.text
    browser.post(f"/api/planning/conversations/{conversation_id}/stop", json={})
    interrupted = browser.get(f"/api/planning/conversations/{conversation_id}").json()
    services.runtime.model = _ClarificationModel()
    retried = browser.post(
        f"/api/planning/conversations/{conversation_id}/retry",
        json={
            "turn_id": interrupted["latest_turn"]["turn_id"],
            "expected_turn_version": interrupted["latest_turn"]["turn_version"],
        },
    )
    assert retried.status_code == 202
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        clarified = browser.get(f"/api/planning/conversations/{conversation_id}").json()
        if clarified["latest_turn"]["status"] == "completed":
            break
        time.sleep(0.02)
    assert clarified["phase"] == "conversation"
    assert clarified["proposal"] is None


def test_stop_cancels_app_owned_task_and_retry_reaches_proposal(planning_browser) -> None:
    browser, services, _model = planning_browser
    assert services.runtime is not None
    services.runtime.model = _HangingModel()
    created = browser.post("/api/planning/conversations", json={"mode": "create"}).json()
    conversation_id = created["conversation_id"]
    accepted = browser.post(
        f"/api/planning/conversations/{conversation_id}/turns",
        json={"text": "Help me choose a path", "idempotency_key": "stop-me"},
    )
    assert accepted.status_code == 202
    stopped = browser.post(f"/api/planning/conversations/{conversation_id}/stop", json={})
    assert stopped.status_code == 200
    assert stopped.json()["stopped"] is True
    snapshot = browser.get(f"/api/planning/conversations/{conversation_id}").json()
    assert snapshot["phase"] == "retryable"
    assert snapshot["latest_turn"]["status"] == "retryable"
    services.runtime.model = _ProposalModel()
    retried = browser.post(
        f"/api/planning/conversations/{conversation_id}/retry",
        json={
            "turn_id": snapshot["latest_turn"]["turn_id"],
            "expected_turn_version": snapshot["latest_turn"]["turn_version"],
        },
    )
    assert retried.status_code == 202, retried.text
    assert _wait_for_proposal(browser, conversation_id)["proposal"] is not None
