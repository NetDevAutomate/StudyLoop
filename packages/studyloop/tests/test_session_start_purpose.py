"""``POST /api/session/start`` with ``purpose`` (design §5, D-10, D-11; T3.8).

A start request carries a *purpose*: ``focus`` (the default — today's study
session, byte-for-byte) or ``planning`` (a study-plan-architect interview).
One resolver, :func:`studyloop.agent_launcher.persona_mode_for`, maps the
purpose to the persona mode for BOTH transports, and a planning launch carries
the seam's :class:`PlanningBrief` rendered to Markdown as its own
``## Planning brief`` persona section — never as ``previous_notes`` (which
renders "Resuming Previous Session", wrong for a fresh interview) and never by
overloading ``topic`` (D-10). Only ``purpose`` is persisted on the live-session
state, for the reconnect label; no plan is created and no plan id is stored
(D-11).

Transport factories are swapped for :class:`StubTransport` exactly as the
sibling ``test_web_session_start_{pty,acp}.py`` files do, and the vendor-binary
preflight is bypassed through the ``STUDYLOOP_TEST_AGENT_CMD`` /
``STUDYLOOP_TEST_ACP_CMD`` hatch accessor, so nothing here spawns a real agent
or makes a paid call.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.planning import store
from studyloop.planning.application import PlanApplication
from studyloop.planning.intents import CreatePlan
from studyloop.session import active
from studyloop.session.transport import Started
from studyloop.web.app import create_app

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

# The persona file the ``plan-architect`` mode renders — the test reads the
# canonical body from the checkout so the assertion is about the mode being
# selected, not about any particular sentence in the persona.
_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "agents/manifest.json").exists():
    _REPO_ROOT = _REPO_ROOT.parent
_ARCHITECT_PERSONA = (_REPO_ROOT / "agents/shared/personas/plan-architect.md").read_text(
    encoding="utf-8"
)

# One of the interview prompts (planning/authoring.py INTERVIEW). The brief must
# carry the questions verbatim — the architect asks them, one per turn.
_FIRST_INTERVIEW_PROMPT = "What changes in your work or life once you have this skill?"

READY_ANSWERS: dict[str, object] = {
    "why": "Ship analytics queries without help",
    "success": ["Write a RANK() query unaided"],
    "topics": ["sql"],
    "milestones": [
        {"title": "OVER clause", "concepts": ["window function"]},
        {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
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
def isolated_plans_dir(tmp_path, monkeypatch):
    """A plans directory of this test's own, so "no plan was created" is a fact
    about the request under test, not about the developer's real plans."""
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]), raise_server_exceptions=False)


@pytest.fixture()
def personas(monkeypatch) -> list[str]:
    """Route both transports through StubTransport and record every canonical
    persona the PTY adapter's ``setup`` receives.

    The vendor binaries are declared present through the test hatch (the fake
    agent), not through ``shutil.which`` — same bypass the e2e harness uses.
    """
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

    def _pty_factory():
        return StubTransport(events=[Started(agent="claude")])

    def _acp_factory():
        return StubTransport(events=[Started(agent="kiro")])

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: _pty_factory,
        raising=False,
    )
    monkeypatch.setattr(
        "studyloop.web.routes.session._build_acp_transport",
        lambda config: _acp_factory,
        raising=False,
    )
    return seen


@pytest.fixture()
def _stub_db(monkeypatch):
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-purpose-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash",
        lambda study_id, persona_hash: None,
    )


def _start(client: TestClient, **body: object):
    payload: dict[str, object] = {"energy": 5, "agent": "claude", "transport": "pty"}
    payload.update(body)
    with patch("studyloop.web.routes.session.is_session_active", return_value=False):
        return client.post("/api/session/start", json=payload)


def _persona_for(client: TestClient, personas: list[str], **body: object) -> str:
    """The persona the launch shipped: the ACP response carries it inline, the
    PTY adapter received it through ``setup``."""
    resp = _start(client, **body)
    assert resp.status_code == 201, resp.text
    if body.get("transport") == "acp":
        return resp.json()["persona_text"]
    assert len(personas) == 1, "the PTY adapter must receive exactly one persona"
    return personas[0]


# ---------------------------------------------------------------------------
# The resolver and the brief section (agent_launcher)
# ---------------------------------------------------------------------------


class TestResolver:
    def test_persona_mode_for_maps_planning_to_plan_architect_and_else_to_focus(self) -> None:
        # RED (T3.8): the resolver does not exist yet; suppression removed in GREEN.
        from studyloop.agent_launcher import (
            persona_mode_for,  # pyright: ignore[reportAttributeAccessIssue]
        )

        assert persona_mode_for("planning") == "plan-architect"
        assert persona_mode_for("focus") == "focus"

    def test_brief_renders_its_own_section_not_a_resume(self) -> None:
        from studyloop.agent_launcher import build_canonical_persona

        # RED (T3.8): ``brief=`` does not exist yet; suppression removed in GREEN.
        content = build_canonical_persona(
            "plan-architect",
            "Study plan",
            5,
            brief="- interview item one",  # pyright: ignore[reportCallIssue]
        )

        assert "## Planning brief" in content
        assert "- interview item one" in content
        assert "Resuming Previous Session" not in content
        assert _ARCHITECT_PERSONA.strip() in content

    def test_no_brief_renders_no_brief_section(self) -> None:
        from studyloop.agent_launcher import build_canonical_persona

        assert "## Planning brief" not in build_canonical_persona("focus", "Python", 5)


# ---------------------------------------------------------------------------
# POST /session/start with purpose
# ---------------------------------------------------------------------------


class TestPlanningPurpose:
    def test_planning_purpose_selects_plan_architect_persona_with_brief_section(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        PlanApplication().apply(CreatePlan(title="SQL Window Functions", answers=READY_ANSWERS))

        persona = _persona_for(client, personas, topic="", purpose="planning")

        assert "**Mode:** plan-architect" in persona
        assert _ARCHITECT_PERSONA.strip() in persona, "the plan-architect persona is the mode"
        assert "## Planning brief" in persona, "the brief is its own section (D-10)"
        # The interview questions and the plans that already exist are the
        # brief's data; the architect asks the former and must not duplicate
        # the latter.
        assert _FIRST_INTERVIEW_PROMPT in persona
        assert "SQL Window Functions" in persona
        assert "sql-window-functions" in persona
        # Not previous_notes: that section is for a RESUMED study session.
        assert "Resuming Previous Session" not in persona
        # Not by overloading topic: the fixed architect label stands alone.
        assert "**Topic:** Study plan" in persona

    def test_planning_purpose_keeps_a_user_supplied_subject_as_the_topic(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        persona = _persona_for(client, personas, topic="Spark", purpose="planning")

        assert "**Topic:** Spark" in persona
        assert "**Mode:** plan-architect" in persona

        from studyloop.session_state import read_session_state

        assert read_session_state()["topic"] == "Spark"

    def test_default_purpose_is_focus_and_unchanged(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        """A request without ``purpose`` is today's focus session, byte for byte:
        same persona (so the same ``persona_hash``), same state ``mode``."""
        from studyloop.agent_launcher import build_canonical_persona
        from studyloop.web.routes.session._models import StartSessionRequest

        assert StartSessionRequest.model_fields["purpose"].default == "focus"

        persona = _persona_for(client, personas, topic="Python")

        expected = build_canonical_persona("focus", "Python", 5)
        assert persona == expected
        assert (
            hashlib.sha256(persona.encode()).hexdigest()[:16]
            == hashlib.sha256(expected.encode()).hexdigest()[:16]
        )
        assert "## Planning brief" not in persona
        assert "**Mode:** focus" in persona

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state["mode"] == "focus"
        assert state["purpose"] == "focus"

    def test_unknown_purpose_is_rejected_structurally(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        resp = _start(client, topic="Python", purpose="revision")

        assert resp.status_code == 422
        assert run_async(active.current()) is None

    def test_planning_launch_creates_no_plan_and_no_plan_id(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        PlanApplication().apply(CreatePlan(title="Existing", answers=READY_ANSWERS))
        before = store.list_plan_ids()
        assert before == ["existing"]

        resp = _start(client, topic="", purpose="planning")

        assert resp.status_code == 201, resp.text
        assert store.list_plan_ids() == before, "the architect creates plans, the launch does not"
        assert "plan_id" not in resp.json()

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state["study_session_id"] == "study-purpose-1"
        assert state["purpose"] == "planning", "this was a planning launch, not a downgraded focus"
        assert "plan_id" not in state, "no plan id is stored on the session (D-11)"

    def test_purpose_persisted_for_reconnect_label(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        resp = _start(client, topic="", purpose="planning")
        assert resp.status_code == 201, resp.text

        from studyloop.session_state import read_session_state

        assert read_session_state()["purpose"] == "planning"

        # The dashboard/reconnect payload exposes it, overlaid on the live slot.
        state = client.get("/api/session/state").json()
        assert state["study_session_id"] == "study-purpose-1"
        assert state["purpose"] == "planning"
        assert state["topic"] == "Study plan"
        assert "plan_id" not in state

    def test_brief_failure_releases_session_claim(
        self, client: TestClient, personas: list[str], monkeypatch
    ) -> None:
        """If the brief cannot be built, the learner gets a structured error and
        the single-session slot is free again — no reservation, no live slot,
        no orphaned DB row."""

        def _boom(self):
            raise RuntimeError("plans directory unreadable")

        monkeypatch.setattr(PlanApplication, "prepare_planning", _boom)

        with (
            patch("studyloop.history.start_study_session") as mock_start,
            patch("studyloop.history.abort_study_session") as mock_abort,
        ):
            resp = _start(client, topic="", purpose="planning")

        assert resp.status_code == 500, resp.text
        body = resp.json()
        assert "error" in body
        assert "brief" in body["error"].lower()
        assert body.get("purpose") == "planning"

        from studyloop.session_state import read_session_state

        assert read_session_state() == {}, "the reservation must be cleared"
        assert run_async(active.current()) is None
        # The brief is built before the DB record exists, so there is nothing to
        # abort — and nothing was left behind either way.
        assert mock_start.call_count == mock_abort.call_count

        # And the slot really is free: a focus start now succeeds.
        with (
            patch("studyloop.history.start_study_session", return_value="study-after"),
            patch("studyloop.history.sessions.update_persona_hash"),
        ):
            again = _start(client, topic="Python")
        assert again.status_code == 201, again.text

    @pytest.mark.parametrize(
        ("transport", "agent"),
        [("pty", "claude"), ("acp", "kiro")],
    )
    def test_pty_and_acp_use_one_resolver(
        self,
        client: TestClient,
        personas: list[str],
        _stub_db,
        monkeypatch,
        transport: str,
        agent: str,
    ) -> None:
        """Both start paths resolve the persona mode through
        ``agent_launcher.persona_mode_for`` — one resolver, not two literals."""
        import studyloop.agent_launcher as launcher

        calls: list[str] = []
        real = launcher.persona_mode_for  # pyright: ignore[reportAttributeAccessIssue]  # RED (T3.8)

        def _spy(purpose: str) -> str:
            calls.append(purpose)
            return real(purpose)

        monkeypatch.setattr(launcher, "persona_mode_for", _spy)

        persona = _persona_for(
            client, personas, topic="", purpose="planning", transport=transport, agent=agent
        )

        assert calls == ["planning"], f"{transport} must call persona_mode_for exactly once"
        assert "**Mode:** plan-architect" in persona
        assert "## Planning brief" in persona
        assert _FIRST_INTERVIEW_PROMPT in persona

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state["transport"] == transport
        assert state["purpose"] == "planning"
