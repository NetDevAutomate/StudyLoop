"""The combined Web + MCP plan journey in ONE process (#15, T6.3).

Issue #15's definition of done asks for "representative Web and MCP integration
journeys" that pass "independently and in the combined run" with "no
nested-event-loop ordering regression". This module is that journey: a
planning-purpose Web session (the real ``/api/session/start`` route through
``TestClient``, the fake agent, the real ``PlanApplication`` seam) and the plan
tools dispatched through the same production ``FastMCP`` registry the stdio
server serves — in one pytest process, one isolated scope, with the two
transports' event loops living side by side:

* ``TestClient`` runs the ASGI app on anyio's blocking portal (a thread);
* ``FastMCP.call_tool`` is a coroutine, run here on ``_helpers.run_async``'s
  shared background loop — the same loop every sync fixture in this suite
  uses for ``active.release()``.

Neither may ever call ``asyncio.run`` on a thread that already has a running
loop: the journey asserts that no "event loop is already running" /
"cannot be called from a running event loop" text reaches the log, the
responses or the tool results. Run alone::

    uv run --group dev pytest packages/studyloop/tests/test_plan_journey_combined.py -m integration

and in the combined run, after the stdio smoke's pytest-asyncio tests have
left their loop state behind::

    uv run --group dev pytest packages/studyloop/tests/test_mcp_stdio_smoke.py \
        packages/studyloop/tests/test_plan_journey_combined.py -m integration

Marked ``integration`` like the stdio smoke, so the default run deselects it;
``scripts/verify/plan_integration.py`` runs both forms.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from _sessions_db_template import seed_sessions_db
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.planning import store
from studyloop.session import active
from studyloop.session.transport import Started
from studyloop.web.app import create_app

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

pytestmark = pytest.mark.integration

#: The interview answers the architect would gather; enough for a READY plan.
ANSWERS: dict[str, object] = {
    "why": "Ship analytics queries without help",
    "success": ["Write a RANK() query unaided"],
    "topics": ["sql"],
    "milestones": [
        {"title": "OVER clause", "concepts": ["window function"]},
        {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
    ],
}

#: Text that a nested ``asyncio.run`` produces on either side of the seam.
NESTED_LOOP_SIGNATURES = (
    "event loop is already running",
    "cannot be called from a running event loop",
    "bound to a different event loop",
)


# ---------------------------------------------------------------------------
# One isolated scope for both transports
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_state():
    run_async(active.release())
    yield
    run_async(active.release())


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    from studyloop import session_state as ss
    from studyloop.web.routes.session import _start

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")
    monkeypatch.setattr(_start, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(_start, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(_start, "PARKING_FILE", tmp_path / "session-parking.md")


@pytest.fixture(autouse=True)
def plans_dir(tmp_path, monkeypatch) -> Path:
    """One plans directory for BOTH the Web routes and the MCP tools — the
    point of the journey is that they see the same documents."""
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    seed_sessions_db(tmp_path / "sessions.db", monkeypatch)
    return tmp_path / "study-plans"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]), raise_server_exceptions=False)


@pytest.fixture()
def personas(monkeypatch) -> list[str]:
    """The fake agent: StubTransport on both transports, the vendor preflight
    bypassed through the test hatch, every persona the PTY adapter receives
    recorded (the same seam ``test_session_start_purpose.py`` uses)."""
    seen: list[str] = []

    def _fake_hatch(name: str) -> str | None:
        if name == "STUDYLOOP_TEST_AGENT_CMD":
            return "test-agent {persona_file}"
        if name == "STUDYLOOP_TEST_ACP_CMD":
            return "python3 -m tests._stub_acp_agent"
        return None

    monkeypatch.setattr("studyloop.test_hatch_env", _fake_hatch)

    from studyloop.adapters._protocol import AgentAdapter
    from studyloop.agent_launcher import AGENTS

    def _record(canonical: str, session_dir: Path) -> Path:
        seen.append(canonical)
        return session_dir / "persona.md"

    for name in ("claude", "kiro"):
        real = AGENTS[name]
        monkeypatch.setitem(
            AGENTS,
            name,
            AgentAdapter(
                name=real.name,
                binary=real.binary,
                setup=_record,
                launch_cmd=lambda persona, resume: f"fake {persona}",
                teardown=None,
                mcp_setup=None,
            ),
        )

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: lambda: StubTransport(events=[Started(agent="claude")]),
        raising=False,
    )
    monkeypatch.setattr(
        "studyloop.web.routes.session._build_acp_transport",
        lambda config: lambda: StubTransport(events=[Started(agent="kiro")]),
        raising=False,
    )
    return seen


@pytest.fixture()
def _stub_history(monkeypatch):
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-combined-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash",
        lambda study_id, persona_hash: None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mcp(name: str, **arguments: Any) -> dict[str, Any]:
    """Dispatch one tool through the production ``FastMCP`` registry — schema
    validation, the adapter, the seam — on the shared background loop, and
    return the structured result the server would serialise."""
    from studyloop.mcp.server import mcp

    content, structured = run_async(mcp.call_tool(name, arguments))
    assert isinstance(structured, dict), structured
    # The unstructured text is the same JSON: one payload, two encodings.
    assert json.loads(content[0].text) == structured
    return structured


def _start_planning(client: TestClient, **body: object):
    payload: dict[str, object] = {
        "energy": 5,
        "agent": "claude",
        "transport": "pty",
        "purpose": "planning",
        "topic": "",
    }
    payload.update(body)
    with patch("studyloop.web.routes.session.is_session_active", return_value=False):
        return client.post("/api/session/start", json=payload)


def _no_nested_loop_text(*blobs: str) -> None:
    for blob in blobs:
        for signature in NESTED_LOOP_SIGNATURES:
            assert signature not in blob, f"nested event loop: {signature!r} in {blob[:200]!r}"


# ---------------------------------------------------------------------------
# The journey
# ---------------------------------------------------------------------------


class TestCombinedJourney:
    def test_planning_session_then_mcp_plan_lifecycle_in_one_process(
        self,
        client: TestClient,
        personas: list[str],
        plans_dir: Path,
        _stub_history,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING)

        # 1. The Web door: a planning-purpose session, fake agent, real brief.
        resp = _start_planning(client)
        assert resp.status_code == 201, resp.text
        started = resp.json()
        assert started["purpose"] == "planning"
        assert started["topic"] == "Study plan"
        assert "plan_id" not in started
        assert len(personas) == 1, "the PTY adapter must receive exactly one persona"
        persona = personas[0]
        assert persona.count("## Planning brief") == 1
        assert "### Interview" in persona and "### Existing plans" in persona
        assert not plans_dir.exists() or not list(plans_dir.glob("*.md")), (
            "starting the architect must create no plan"
        )

        # 2. The MCP door, same scope: the brief's interview through the tools.
        interview = _mcp("get_planning_interview")
        assert interview["existing_plans"] == []
        questions = [item["prompt"] for item in interview["questions"]]
        assert questions, interview
        for prompt in questions:
            assert prompt in persona, "the Web brief and the MCP interview must be one seed"

        created = _mcp(
            "create_study_plan", title="SQL Windows", answers=ANSWERS, plan_id="sql-windows"
        )
        assert created["plan"]["plan_id"] == "sql-windows"
        assert created["plan"]["status"] == "draft"
        assert created["readiness"]["ready"] is True
        assert (plans_dir / "sql-windows.md").exists()

        # 3. The draft is visible through the Web routes — one store, one seam.
        listed = client.get("/api/plans")
        assert listed.status_code == 200, listed.text
        assert [row["plan_id"] for row in listed.json()["plans"]] == ["sql-windows"]

        # 4. A preview evaluation writes to neither sink: the document's bytes
        #    are unchanged and the checkpoint log stays empty.
        before_preview = (plans_dir / "sql-windows.md").read_bytes()
        preview = _mcp("evaluate_study_plan", plan_id="sql-windows", phase="start")
        assert preview["db_write"] == "not_requested"
        assert preview["document_write"] == "not_requested"
        assert preview["evaluation"]["phase"] == "start"
        assert (plans_dir / "sql-windows.md").read_bytes() == before_preview
        history = _mcp("get_study_plan", plan_id="sql-windows", include_history=True)
        assert history["checkpoints"] == []

        # 5. Activation through MCP is readiness-gated and, being ready, succeeds;
        #    the Web detail route reports the same lifecycle state.
        activated = _mcp("set_study_plan_status", plan_id="sql-windows", status="active")
        assert activated["plan"]["status"] == "active"
        detail = client.get("/api/plans/sql-windows")
        assert detail.status_code == 200, detail.text
        assert detail.json()["plan"]["status"] == "active"

        # 6. Reconnect keeps the planning label, and still stores no plan id.
        state = client.get("/api/session/state").json()
        assert state["purpose"] == "planning"
        assert state["topic"] == "Study plan"
        assert "plan_id" not in state

        # 7. No nested event loop anywhere along the way.
        _no_nested_loop_text(caplog.text, resp.text, json.dumps(created), json.dumps(preview))

    def test_planning_session_on_the_acp_transport_carries_one_brief(
        self,
        client: TestClient,
        personas: list[str],
        plans_dir: Path,
        _stub_history,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING)
        resp = _start_planning(client, agent="kiro", transport="acp")
        assert resp.status_code == 201, resp.text
        assert resp.json()["purpose"] == "planning"
        assert resp.json()["persona_text"].count("## Planning brief") == 1
        assert _mcp("list_study_plans")["count"] == 0
        assert not plans_dir.exists() or not list(plans_dir.glob("*.md"))
        _no_nested_loop_text(caplog.text, resp.text)

    def test_mcp_refusal_after_a_web_start_is_a_structured_tool_error(
        self,
        client: TestClient,
        personas: list[str],
        plans_dir: Path,
        _stub_history,
    ) -> None:
        """The refusal kinds the install doc promises survive the combined
        process: a not-ready activation names its blockers, a deletion without
        confirmation is refused, and neither writes."""
        from mcp.server.fastmcp.exceptions import ToolError

        from studyloop.mcp.server import mcp

        assert _start_planning(client).status_code == 201
        husk = _mcp("create_study_plan", title="Husk", answers={}, plan_id="husk")
        assert husk["readiness"]["ready"] is False

        with pytest.raises(ToolError, match=r"not_ready: .*blocker|not_ready:"):
            run_async(
                mcp.call_tool("set_study_plan_status", {"plan_id": "husk", "status": "active"})
            )
        assert _mcp("get_study_plan", plan_id="husk")["plan"]["status"] == "draft"

        with pytest.raises(ToolError, match=r"invalid: .*confirmed=True"):
            run_async(mcp.call_tool("delete_study_plan", {"plan_id": "husk"}))
        assert (plans_dir / "husk.md").exists()

        deleted = _mcp("delete_study_plan", plan_id="husk", confirmed=True)
        assert deleted["deleted"] is True
        assert not (plans_dir / "husk.md").exists()
        assert client.get("/api/plans/husk").status_code == 404
