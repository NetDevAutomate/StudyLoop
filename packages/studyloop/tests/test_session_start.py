"""Tests for session/start.py — start_session orchestration and helpers.

No conftest.py (pluggy conflict with agent-session-tools). All fixtures inline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from studyloop.session.start import (
    SessionStartError,
    brief_summary,
    build_study_briefing,
    start_session,
)

# ---------------------------------------------------------------------------
# SessionStartError
# ---------------------------------------------------------------------------


class TestSessionStartError:
    def test_message_attribute(self):
        err = SessionStartError("something went wrong")
        assert err.message == "something went wrong"

    def test_is_exception(self):
        assert isinstance(SessionStartError("x"), Exception)

    def test_str_representation(self):
        err = SessionStartError("tmux missing")
        assert "tmux missing" in str(err)


# ---------------------------------------------------------------------------
# brief_summary helper
# ---------------------------------------------------------------------------


class TestBriefSummary:
    def test_returns_empty_string_for_none(self):
        assert brief_summary(None) == ""

    def test_formats_topic_config(self):
        config = MagicMock()
        config.name = "Python Decorators"
        config.slug = "python-decorators"
        result = brief_summary(config)
        assert "Python Decorators" in result
        assert "python-decorators" in result


# ---------------------------------------------------------------------------
# build_study_briefing helper
# ---------------------------------------------------------------------------


class TestBuildStudyBriefing:
    def test_returns_none_for_none_config(self):
        assert build_study_briefing(None) is None

    def test_returns_none_when_settings_unavailable(self):
        config = MagicMock()
        config.slug = "test-slug"
        with (
            patch("studyloop.session.start._gather_review_context", return_value=None),
            patch("studyloop.session.start._gather_content_context", return_value=None),
            patch("studyloop.settings.load_settings", side_effect=Exception("no config")),
        ):
            result = build_study_briefing(config)
        # Suppresses all exceptions — returns None on failure
        assert result is None


# ---------------------------------------------------------------------------
# start_session — pre-flight failure paths
# ---------------------------------------------------------------------------


def _tmux_side_effect(args, **kwargs):
    """Mock subprocess that returns tmux version for -V, success for others."""
    if "-V" in args:
        return MagicMock(returncode=0, stdout="tmux 3.4\n", stderr="")
    if "has-session" in args:
        return MagicMock(returncode=1, stdout="", stderr="")
    return MagicMock(returncode=0, stdout="%0\n", stderr="")


class TestStartSessionPreflightFailures:
    def test_raises_when_tmux_unavailable(self):
        with (
            patch("studyloop.tmux.shutil.which", return_value=None),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Test Topic", None, "study", "elapsed", 5, False)
        assert "tmux" in exc_info.value.message.lower()

    def test_raises_when_no_agent_found(self):
        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value=None),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Test Topic", None, "study", "elapsed", 5, False)
        assert "No AI agent" in exc_info.value.message

    def test_raises_when_session_already_active(self):
        active_state = {"study_session_id": "x"}
        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=active_state),
            patch("studyloop.session_state.STATE_FILE") as sf,
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            sf.exists.return_value = True
            start_session("Test Topic", "claude", "study", "elapsed", 5, False)
        assert "already active" in exc_info.value.message

    def test_raises_when_db_session_creation_fails(self, tmp_path):
        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.history.start_study_session", return_value=None),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Test Topic", "claude", "study", "elapsed", 5, False)
        assert "Failed to create session in DB" in exc_info.value.message


# ---------------------------------------------------------------------------
# start_session — happy path (mocked tmux + DB)
# ---------------------------------------------------------------------------


class TestStartSessionHappyPath:
    def test_session_starts_successfully(self, tmp_path):
        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.tmux.os.execvp"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
        ):
            # Should not raise — in-tmux path calls switch_client then returns
            start_session("Python Decorators", "claude", "study", "elapsed", 7, False)

    def test_session_name_derived_from_topic(self, tmp_path):
        """Session name slug is derived from topic (lowercase, truncated at 20 chars)."""
        created_names = []

        def mock_create_session(name, **kwargs):
            created_names.append(name)
            return "%0"

        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.tmux.os.execvp"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="deadbeef12345678"),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.tmux.create_session", side_effect=mock_create_session),
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
        ):
            start_session("Python Decorators", "claude", "study", "elapsed", 5, False)

        assert len(created_names) == 1
        name = created_names[0]
        assert name.startswith("study-python-decorators")
        assert "deadbeef" in name

    def test_resume_uses_provided_session_name(self, tmp_path):
        """When resume_session_name is provided, it is used as-is."""
        created_names = []

        def mock_create_session(name, **kwargs):
            created_names.append(name)
            return "%0"

        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.tmux.os.execvp"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.tmux.create_session", side_effect=mock_create_session),
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
        ):
            session_dir = tmp_path / "sessions" / "study-old-session-abcd1234"
            session_dir.mkdir(parents=True, exist_ok=True)
            start_session(
                "Test Topic",
                "claude",
                "study",
                "elapsed",
                5,
                False,
                resume_session_name="study-old-session-abcd1234",
                resume_session_dir=str(session_dir),
            )

        assert "study-old-session-abcd1234" in created_names

    def test_lan_password_never_crosses_agent_readable_startup_surfaces(self, tmp_path, caplog):
        import base64
        import contextlib
        import json
        import os
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        import studyloop.session_state as session_state
        from studyloop.web.app import create_app

        learner_secret = "human-only-session-value"  # pragma: allowlist secret
        adapter = MagicMock()
        adapter.setup.return_value = tmp_path / "persona.md"
        adapter.mcp_setup = None
        adapter.launch_cmd.return_value = "claude --resume"
        spawned: list[tuple[list[str], dict]] = []
        pipe_payloads: list[dict[str, str]] = []
        state_writes: list[dict] = []
        real_write_state = session_state.write_session_state

        def recording_write_state(updates: dict) -> None:
            state_writes.append(dict(updates))
            real_write_state(updates)

        def fake_popen(command, **kwargs):
            command = list(command)
            spawned.append((command, kwargs))
            for fd in kwargs.get("pass_fds", ()):
                pipe_payloads.append(json.loads(os.read(fd, 4096)))
            return SimpleNamespace(pid=1000 + len(spawned))

        tmux_result = {
            "tmux_main_pane": "%0",
            "tmux_sidebar_pane": "%1",
            "mux_main_pane": "%0",
            "mux_sidebar_pane": "%1",
            "already_in_tmux": True,
        }
        settings = SimpleNamespace(lan_username="learner", lan_password="")

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("studyloop.tmux.is_tmux_available", return_value=True))
            stack.enter_context(patch("studyloop.tmux.session_exists", return_value=False))
            stack.enter_context(patch("studyloop.session.cleanup.auto_clean_zombies"))
            stack.enter_context(
                patch("studyloop.session_state.STATE_FILE", tmp_path / "session-state.json")
            )
            stack.enter_context(patch("studyloop.session_state.SESSION_DIR", tmp_path))
            stack.enter_context(
                patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md")
            )
            stack.enter_context(
                patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md")
            )
            stack.enter_context(
                patch("studyloop.history.start_study_session", return_value="study-session-1")
            )
            stack.enter_context(
                patch("studyloop.history.sessions.update_persona_hash", return_value=True)
            )
            stack.enter_context(patch("studyloop.agent_launcher.AGENTS", {"claude": adapter}))
            stack.enter_context(
                patch("studyloop.agent_launcher.build_canonical_persona", return_value="persona")
            )
            create_tmux = stack.enter_context(
                patch(
                    "studyloop.session.orchestrator.create_tmux_environment",
                    return_value=tmux_result,
                )
            )
            stack.enter_context(
                patch("studyloop.session.orchestrator.subprocess.Popen", side_effect=fake_popen)
            )
            stack.enter_context(
                patch(
                    "studyloop.session.orchestrator.shutil.which",
                    side_effect=lambda name: f"/usr/bin/{name}",
                )
            )
            stack.enter_context(patch("studyloop.session.orchestrator._kill_port_occupant"))
            stack.enter_context(patch("studyloop.session.orchestrator._open_browser"))
            stack.enter_context(patch("studyloop.settings.load_settings", return_value=settings))
            stack.enter_context(
                patch(
                    "studyloop.session_state.write_session_state",
                    side_effect=recording_write_state,
                )
            )
            console_print = stack.enter_context(patch("studyloop.session.start.console.print"))
            stack.enter_context(
                patch(
                    "studyloop.web.routes.session._ipc._is_tmux_session_alive",
                    return_value=True,
                )
            )
            stack.enter_context(patch.dict("os.environ", {"TMUX": "/tmp/tmux"}))
            start_session(
                "Python",
                "claude",
                "study",
                "elapsed",
                5,
                True,
                lan=True,
                password=learner_secret,
            )

            assert learner_secret not in repr(state_writes)
            assert learner_secret not in (tmp_path / "session-state.json").read_text()
            assert learner_secret not in repr(create_tmux.call_args)
            assert learner_secret not in repr(console_print.call_args_list)
            assert learner_secret not in caplog.text
            for command, kwargs in spawned:
                assert learner_secret not in " ".join(command)
                assert learner_secret not in json.dumps(kwargs.get("env", {}))
            assert pipe_payloads == [{"username": "learner", "password": learner_secret}]

            app = create_app(username="learner", password=learner_secret)
            assert app.state.lan_auth_configured is True
            assert not hasattr(app.state, "lan_password")
            credentials = base64.b64encode(f"learner:{learner_secret}".encode()).decode()
            client = TestClient(app)
            try:
                response = client.get(
                    "/api/session/state",
                    headers={"Authorization": f"Basic {credentials}"},
                )
            finally:
                client.close()
            assert response.status_code == 200
            assert learner_secret not in response.text
            assert "lan_password" not in response.json()


class TestStartSessionRollback:
    def _mock_adapter(self, tmp_path):
        adapter = MagicMock()
        adapter.setup.return_value = tmp_path / "persona.md"
        adapter.mcp_setup = None
        adapter.launch_cmd.return_value = "claude --resume"
        return adapter

    def test_rolls_back_partial_startup_for_new_session(self, tmp_path):
        adapter = self._mock_adapter(tmp_path)
        session_dir = tmp_path / "sessions" / "study-python-deadbeef"

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="deadbeef12345678"),
            patch("studyloop.history.abort_study_session") as mock_abort,
            patch("studyloop.history.sessions.update_persona_hash", return_value=True),
            patch("studyloop.agent_launcher.AGENTS", {"claude": adapter}),
            patch("studyloop.agent_launcher.build_canonical_persona", return_value="persona"),
            patch(
                "studyloop.session.orchestrator.create_tmux_environment",
                side_effect=RuntimeError("tmux split failed"),
            ),
            patch("studyloop.session_state.clear_session_files") as mock_clear,
            patch("studyloop.tmux.session_exists", side_effect=[False, True]),
            patch("studyloop.tmux.kill_session") as mock_kill,
            patch("shutil.rmtree") as mock_rmtree,
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Python", "claude", "study", "elapsed", 5, False)

        assert "Failed to start study session" in exc_info.value.message
        mock_abort.assert_called_once()
        abort_reason = mock_abort.call_args.args[1]
        assert abort_reason == "Startup failed: tmux split failed"
        mock_clear.assert_called_once()
        mock_kill.assert_called_once_with("study-python-deadbeef")
        mock_rmtree.assert_called_once_with(session_dir, ignore_errors=True)

    def test_resume_failure_keeps_existing_session_dir(self, tmp_path):
        adapter = self._mock_adapter(tmp_path)
        session_dir = tmp_path / "sessions" / "study-existing-abcd1234"
        session_dir.mkdir(parents=True)

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="study-session-test-id"),
            patch("studyloop.history.abort_study_session") as mock_abort,
            patch("studyloop.history.sessions.update_persona_hash", return_value=True),
            patch("studyloop.agent_launcher.AGENTS", {"claude": adapter}),
            patch("studyloop.agent_launcher.build_canonical_persona", return_value="persona"),
            patch(
                "studyloop.session.orchestrator.create_tmux_environment",
                side_effect=RuntimeError("sidebar start failed"),
            ),
            patch("studyloop.session_state.clear_session_files"),
            patch("studyloop.tmux.session_exists", side_effect=[False, True]),
            patch("studyloop.tmux.kill_session"),
            patch("shutil.rmtree") as mock_rmtree,
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
            pytest.raises(SessionStartError),
        ):
            start_session(
                "Python",
                "claude",
                "study",
                "elapsed",
                5,
                False,
                resume_session_name="study-existing-abcd1234",
                resume_session_dir=str(session_dir),
            )

        mock_abort.assert_called_once()
        mock_rmtree.assert_not_called()


# ---------------------------------------------------------------------------
# CLI wrapper: _handle_start delegates and translates errors
# ---------------------------------------------------------------------------


class TestHandleStartCLIWrapper:
    """Test that the CLI wrapper properly translates SessionStartError to ctx.exit(1)."""

    def test_handle_start_exits_on_tmux_missing(self):
        from click.testing import CliRunner

        from studyloop.cli._study import study

        runner = CliRunner()
        with patch("studyloop.tmux.shutil.which", return_value=None):
            result = runner.invoke(study, ["Test Topic"])
        assert result.exit_code != 0
        assert "tmux" in result.output.lower()

    def test_handle_start_exits_on_no_agent(self):
        from click.testing import CliRunner

        from studyloop.cli._study import study

        runner = CliRunner()
        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value=None),
            patch("studyloop.session_state.read_session_state", return_value={}),
        ):
            result = runner.invoke(study, ["Test Topic"])
        assert result.exit_code != 0
        assert "No AI agent" in result.output
