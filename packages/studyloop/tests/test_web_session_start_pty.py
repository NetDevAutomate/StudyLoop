"""Tests for POST /api/session/start with the new transport=pty branch (§1.5b).

Covers: transport selection (body + env override + default), single-session
invariant via active.acquire, binary-missing 503 with install_hint, response
body shape including ws_url, and that the ttyd branch stays reachable
untouched. Uses a factory-swap so we never spawn a real PTY child — real
PTY coverage lives in test_pty_transport.py.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §1.5b
(Amendment #5).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.session import active
from studyloop.session.transport import Started
from studyloop.web.app import create_app

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

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

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")


@pytest.fixture()
def client() -> TestClient:
    app = create_app(study_dirs=[])
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_transport_factory(monkeypatch):
    """Replace the route's PTYTransport factory with a StubTransport builder.

    The route is expected to call a ``_build_pty_transport()`` helper
    (exported from ``studyloop.web.routes.session``). Swapping it here
    means the route exercises the real ``active.acquire`` + ``SessionConfig``
    path without ever touching ``pty.fork()``.
    """
    stubs: list[StubTransport] = []

    def factory():
        stub = StubTransport(events=[Started(agent="claude")])
        stubs.append(stub)
        return stub

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: factory,
        raising=False,
    )
    return stubs


@pytest.fixture()
def _mock_agent_available(monkeypatch):
    """Pretend the 'claude' agent binary is installed and expose a test
    adapter that skips real persona / MCP writes."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    # AgentAdapter is a frozen dataclass so monkeypatch.setattr on fields
    # would trip FrozenInstanceError. Replace the whole entry in AGENTS
    # with a test adapter that satisfies the Protocol.
    from studyloop.adapters._protocol import AgentAdapter
    from studyloop.agent_launcher import AGENTS

    real_claude = AGENTS["claude"]
    fake_claude = AgentAdapter(
        name=real_claude.name,
        binary=real_claude.binary,
        setup=lambda canonical, session_dir: session_dir / "persona.md",
        launch_cmd=lambda persona, resume: f"claude {persona}",
        teardown=None,
        mcp_setup=None,
    )
    monkeypatch.setitem(AGENTS, "claude", fake_claude)


@pytest.fixture()
def _stub_db(monkeypatch):
    """Bypass the real DB write."""
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-pty-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash",
        lambda study_id, persona_hash: None,
    )


# ---------------------------------------------------------------------------
# PTY branch — happy path
# ---------------------------------------------------------------------------


class TestPtyStartHappyPath:
    def test_pty_start_returns_ws_url_and_no_tmux(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
    ) -> None:
        """POST with transport=pty returns 201 + ws_url referencing the study_session_id.

        Must NOT start tmux, ttyd, or attempt to read is_tmux_available.
        """
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            # Tmux must not be consulted on the PTY path.
            patch(
                "studyloop.tmux.is_tmux_available",
                side_effect=AssertionError("tmux must not be consulted on the PTY path"),
            ),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "claude", "transport": "pty"},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["transport"] == "pty"
        assert body["agent"] == "claude"
        assert body["study_session_id"] == "study-pty-1"
        assert body["ws_url"] == "/api/session/ws?study_session_id=study-pty-1"
        # active.acquire should have run.
        assert run_async(active.current()) is not None

    def test_pty_is_default_when_body_and_env_unset(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        monkeypatch,
    ) -> None:
        """No transport in body, no STUDYLOOP_TRANSPORT env → pty."""
        monkeypatch.delenv("STUDYLOOP_TRANSPORT", raising=False)
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch(
                "studyloop.tmux.is_tmux_available",
                side_effect=AssertionError("tmux must not be consulted"),
            ),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "claude"},
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["transport"] == "pty"


# ---------------------------------------------------------------------------
# PTY branch — 409 when a session is already active
# ---------------------------------------------------------------------------


class TestPtyStartSingleSession:
    def test_pty_start_refuses_when_session_already_active(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
    ) -> None:
        """active.acquire raises SessionAlreadyActiveError → 409."""
        from studyloop.session.transport import SessionConfig

        pre_stub = StubTransport(events=[Started(agent="claude")])
        run_async(
            active.acquire(
                SessionConfig(
                    study_session_id="pre-existing",
                    agent="claude",
                    persona_file="",
                    cwd="/tmp",
                    env={},
                    cols=80,
                    rows=24,
                ),
                lambda: pre_stub,
            )
        )

        with patch("studyloop.web.routes.session.is_session_active", return_value=True):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "claude", "transport": "pty"},
            )
        assert resp.status_code == 409
        assert "already active" in resp.json()["error"]


# ---------------------------------------------------------------------------
# PTY branch — 503 when agent binary is missing, includes install_hint
# ---------------------------------------------------------------------------


class TestPtyStartBinaryMissing:
    def test_pty_start_returns_install_hint_when_binary_missing(
        self,
        client: TestClient,
        _stub_db,
    ) -> None:
        """503 payload must include ``install_hint`` so the UI (or an
        agent orchestrating installs) can surface a next step."""
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "gemini", "transport": "pty"},
            )
        assert resp.status_code == 503
        body = resp.json()
        assert "gemini" in body["error"]
        assert "install_hint" in body
        assert body["install_hint"]  # non-empty string


# ---------------------------------------------------------------------------
# Env override
# ---------------------------------------------------------------------------


class TestPtyEnvOverride:
    def test_env_ttyd_routes_through_legacy(
        self,
        client: TestClient,
        _mock_agent_available,
        monkeypatch,
    ) -> None:
        """STUDYLOOP_TRANSPORT=ttyd forces the legacy branch even when the
        body asks for pty — operator-level kill switch (plan §1.9)."""
        monkeypatch.setenv("STUDYLOOP_TRANSPORT", "ttyd")
        with (
            patch("studyloop.tmux.is_tmux_available", return_value=False),
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "claude", "transport": "pty"},
            )
        # Legacy branch hits the tmux check first → 503
        assert resp.status_code == 503
        assert "tmux" in resp.json()["error"]
