"""Tests for POST /api/session/start with the transport=acp branch (§2.2).

Mirrors ``test_web_session_start_pty.py``. Swaps out the real
``_build_acp_transport`` factory with a ``StubTransport`` so no real
subprocess is spawned here — genuine ACP coverage lives in
``test_acp_transport.py``.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §2.2
(Amendment #10).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.session import active
from studyloop.session.transport import Started
from studyloop.web.app import create_app

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_state():
    asyncio.run(active.release())
    yield
    asyncio.run(active.release())


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


@pytest.fixture()
def _stub_acp_factory(monkeypatch):
    """Replace the route's ACPTransport factory with a StubTransport builder.

    The route exposes ``_build_acp_transport()`` so tests can swap it out
    without spawning a real ACP subprocess. The returned list captures
    each StubTransport instance for post-hoc assertions.
    """
    stubs: list[StubTransport] = []

    def factory():
        stub = StubTransport(events=[Started(agent="kiro")])
        stubs.append(stub)
        return stub

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_acp_transport",
        lambda config: factory,
        raising=False,
    )
    return stubs


@pytest.fixture()
def _stub_pty_factory(monkeypatch):
    """PTY factory stub used by tests that assert the PTY branch is NOT taken."""
    pty_stubs: list[StubTransport] = []

    def factory():
        stub = StubTransport(events=[Started(agent="claude")])
        pty_stubs.append(stub)
        return stub

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: factory,
        raising=False,
    )
    return pty_stubs


@pytest.fixture()
def _mock_kiro_available(monkeypatch):
    """Pretend the Kiro agent binary is installed and adapter.setup is cheap."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    from studyloop.adapters._protocol import AgentAdapter
    from studyloop.agent_launcher import AGENTS

    real_kiro = AGENTS["kiro"]
    fake_kiro = AgentAdapter(
        name=real_kiro.name,
        binary=real_kiro.binary,
        setup=lambda canonical, session_dir: session_dir / "persona.md",
        launch_cmd=lambda persona, resume: f"kiro-cli {persona}",
        teardown=None,
        mcp_setup=None,
    )
    monkeypatch.setitem(AGENTS, "kiro", fake_kiro)


@pytest.fixture()
def _stub_db(monkeypatch):
    """Bypass the real DB write."""
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-acp-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash",
        lambda study_id, persona_hash: None,
    )


# ---------------------------------------------------------------------------
# ACP branch — happy path
# ---------------------------------------------------------------------------


class TestAcpStartHappyPath:
    def test_acp_start_returns_ws_url_and_no_tmux(
        self,
        client: TestClient,
        _stub_acp_factory,
        _mock_kiro_available,
        _stub_db,
    ) -> None:
        """POST with transport=acp returns 201 + ws_url referencing the study_session_id.

        Must NOT consult tmux or fall into the PTY branch.
        """
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch(
                "studyloop.tmux.is_tmux_available",
                side_effect=AssertionError("tmux must not be consulted on the ACP path"),
            ),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "kiro", "transport": "acp"},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["transport"] == "acp"
        assert body["agent"] == "kiro"
        assert body["study_session_id"] == "study-acp-1"
        assert body["ws_url"] == "/api/session/ws?study_session_id=study-acp-1"
        # active.acquire should have run against the ACP factory.
        assert asyncio.run(active.current()) is not None


# ---------------------------------------------------------------------------
# ACP branch — 409 when a session is already active
# ---------------------------------------------------------------------------


class TestAcpStartSingleSession:
    def test_acp_start_refuses_when_session_already_active(
        self,
        client: TestClient,
        _stub_acp_factory,
        _mock_kiro_available,
        _stub_db,
    ) -> None:
        """active.acquire raises SessionAlreadyActiveError → 409."""
        from studyloop.session.transport import SessionConfig

        pre_stub = StubTransport(events=[Started(agent="kiro")])
        asyncio.run(
            active.acquire(
                SessionConfig(
                    study_session_id="pre-existing",
                    agent="kiro",
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
                json={"topic": "Python", "energy": 5, "agent": "kiro", "transport": "acp"},
            )
        assert resp.status_code == 409
        assert "already active" in resp.json()["error"]
        # active.acquire should raise before the factory is ever called —
        # the ACP branch must not leak a partially-constructed transport.
        assert len(_stub_acp_factory) == 0


# ---------------------------------------------------------------------------
# ACP branch — 503 when agent binary is missing, includes install_hint
# ---------------------------------------------------------------------------


class TestAcpStartBinaryMissing:
    def test_acp_start_returns_install_hint_when_binary_missing(
        self,
        client: TestClient,
        _stub_db,
    ) -> None:
        """503 payload must include ``install_hint`` so the UI can surface a next step."""
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "kiro", "transport": "acp"},
            )
        assert resp.status_code == 503
        body = resp.json()
        assert "kiro" in body["error"]
        assert "install_hint" in body
        assert body["install_hint"]  # non-empty string


# ---------------------------------------------------------------------------
# ACP routed through its own factory (not PTY)
# ---------------------------------------------------------------------------


class TestAcpRoutingIsolation:
    def test_acp_is_routed_through_separate_factory(
        self,
        client: TestClient,
        _stub_acp_factory,
        _stub_pty_factory,
        _mock_kiro_available,
        _stub_db,
    ) -> None:
        """transport=acp must build via _build_acp_transport, never _build_pty_transport."""
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch(
                "studyloop.tmux.is_tmux_available",
                side_effect=AssertionError("tmux must not be consulted on the ACP path"),
            ),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "kiro", "transport": "acp"},
            )
        assert resp.status_code == 201, resp.text
        # ACP factory was called exactly once; PTY factory never called.
        assert len(_stub_acp_factory) == 1
        assert len(_stub_pty_factory) == 0


# ---------------------------------------------------------------------------
# Env override — STUDYLOOP_TRANSPORT beats body transport=acp
# ---------------------------------------------------------------------------


class TestAcpEnvOverride:
    def test_env_pty_forces_pty_even_when_body_says_acp(
        self,
        client: TestClient,
        _stub_acp_factory,
        _stub_pty_factory,
        _mock_kiro_available,
        _stub_db,
        monkeypatch,
    ) -> None:
        """STUDYLOOP_TRANSPORT=pty forces the PTY branch even when the body asks for
        acp — operator-level kill switch (plan §1.9 parity)."""
        monkeypatch.setenv("STUDYLOOP_TRANSPORT", "pty")
        with (
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch(
                "studyloop.tmux.is_tmux_available",
                side_effect=AssertionError("tmux must not be consulted on the PTY path"),
            ),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "kiro", "transport": "acp"},
            )
        # PTY branch wins — returns transport=pty, and the PTY factory saw a call.
        assert resp.status_code == 201, resp.text
        assert resp.json()["transport"] == "pty"
        assert len(_stub_pty_factory) == 1
        assert len(_stub_acp_factory) == 0


# ---------------------------------------------------------------------------
# Persona is built and returned inline so the browser can ship it as the
# first invisible session/prompt frame after WS open. ACP agents have no
# argv/env hook for system context — this is the only injection point.
# ---------------------------------------------------------------------------


class TestAcpStartPersonaInjection:
    def test_response_includes_persona_text_and_hash(
        self,
        client: TestClient,
        _stub_acp_factory,
        _mock_kiro_available,
        _stub_db,
    ) -> None:
        with patch(
            "studyloop.web.routes.session.is_session_active", return_value=False
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "SQL", "energy": 5, "agent": "kiro", "transport": "acp"},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()

        assert "persona_text" in body, "persona_text must be inline in /start response"
        persona = body["persona_text"]
        assert isinstance(persona, str) and persona.strip(), (
            "persona_text must be a non-empty string"
        )
        # Sanity: persona_text must reflect the topic the user picked, otherwise
        # the wrong persona was assembled.
        assert "SQL" in persona, "persona_text should mention the chosen topic"

        assert "persona_hash" in body
        assert isinstance(body["persona_hash"], str)
        assert len(body["persona_hash"]) == 16, (
            "persona_hash should be the 16-char sha256 prefix used by PTY parity"
        )

        # Hash must actually match the persona_text shipped (no drift).
        import hashlib

        recomputed = hashlib.sha256(persona.encode()).hexdigest()[:16]
        assert recomputed == body["persona_hash"]

    def test_session_state_records_persona_hash(
        self,
        client: TestClient,
        _stub_acp_factory,
        _mock_kiro_available,
        _stub_db,
    ) -> None:
        with patch(
            "studyloop.web.routes.session.is_session_active", return_value=False
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "SQL", "energy": 5, "agent": "kiro", "transport": "acp"},
            )

        assert resp.status_code == 201, resp.text

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state.get("persona_hash") == resp.json()["persona_hash"]
        # Path field stays absent — nothing is written to disk on the ACP path.
        assert "persona_file" not in state
