"""A set-but-unregistered ``STUDYLOOP_AGENT`` is named, not reported as "no agent".

``detect_agents`` honours the override by returning nothing rather than falling
through to a different harness, so a typo (``STUDYLOOP_AGENT=codx``) used to
surface at every start door as the generic "No AI agent found" with no clue that
the environment variable was the cause (review 4 lane O, found-not-fixed #3).
Three doors share the rule: the launcher in ``session/start.py`` and the PTY and
ACP routes in ``web/routes/session/_start.py``. The unset case keeps today's
message on each.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from studyloop.session.start import SessionStartError, start_session

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)


def _start_with_no_harness_on_path() -> SessionStartError:
    with (
        patch("studyloop.tmux.is_tmux_available", return_value=True),
        patch("studyloop.agent_launcher.shutil.which", return_value=None),
        patch("studyloop.session_state.read_session_state", return_value={}),
        patch("studyloop.session.cleanup.auto_clean_zombies"),
        pytest.raises(SessionStartError) as exc_info,
    ):
        start_session("Test Topic", None, "study", "elapsed", 5, False)
    return exc_info.value


class TestLauncherNamesTheOverride:
    def test_an_unknown_value_is_named_with_the_known_harnesses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyloop.agent_launcher import AGENTS

        monkeypatch.setenv("STUDYLOOP_AGENT", "codx")

        message = _start_with_no_harness_on_path().message

        assert "STUDYLOOP_AGENT=codx is not a known harness" in message, message
        assert "(known: " in message, message
        for name in AGENTS:
            assert name in message, (name, message)

    def test_unset_keeps_todays_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STUDYLOOP_AGENT", raising=False)

        message = _start_with_no_harness_on_path().message

        assert "No AI agent found" in message, message
        assert "STUDYLOOP_AGENT" not in message, message


# ---------------------------------------------------------------------------
# The two web start doors
# ---------------------------------------------------------------------------

pytest.importorskip("fastapi")


@pytest.fixture()
def client():
    from _helpers import run_async
    from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

    from studyloop.session import active
    from studyloop.web.app import create_app

    run_async(active.release())
    try:
        yield TestClient(create_app(study_dirs=[]))
    finally:
        run_async(active.release())


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from studyloop import session_state as ss
    from studyloop.web.routes.session import _start

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")
    monkeypatch.setattr(_start, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(_start, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(_start, "PARKING_FILE", tmp_path / "session-parking.md")


def _post_start_without_an_agent(client, transport: str):
    with (
        patch("studyloop.web.routes.session.is_session_active", return_value=False),
        patch("shutil.which", return_value=None),
    ):
        return client.post(
            "/api/session/start",
            json={"topic": "Python", "energy": 5, "transport": transport},
        )


class TestWebDoorsNameTheOverride:
    @pytest.mark.parametrize("transport", ["pty", "acp"])
    def test_an_unknown_value_is_named_with_the_known_harnesses(
        self, client, monkeypatch: pytest.MonkeyPatch, transport: str
    ) -> None:
        from studyloop.agent_launcher import AGENTS

        monkeypatch.setenv("STUDYLOOP_AGENT", "codx")

        resp = _post_start_without_an_agent(client, transport)

        assert resp.status_code == 503, resp.text
        error = resp.json()["error"]
        assert "STUDYLOOP_AGENT=codx is not a known harness" in error, error
        assert "(known: " in error, error
        for name in AGENTS:
            assert name in error, (name, error)

    @pytest.mark.parametrize("transport", ["pty", "acp"])
    def test_unset_keeps_todays_message(
        self, client, monkeypatch: pytest.MonkeyPatch, transport: str
    ) -> None:
        monkeypatch.delenv("STUDYLOOP_AGENT", raising=False)

        resp = _post_start_without_an_agent(client, transport)

        assert resp.status_code == 503, resp.text
        assert resp.json()["error"] == "No AI agent found on this machine"
