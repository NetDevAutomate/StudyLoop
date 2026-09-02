"""Tests for session/start.py — start_session orchestration and helpers.

No conftest.py (pluggy conflict with agent-session-tools). All fixtures inline.
"""

from __future__ import annotations

import os
import time
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


class TestNoTtydSpawnOnStudyPath:
    """R-03: plain ``studyloop study`` must never spawn ttyd, even when installed.

    Puts a working ``ttyd`` shim on PATH and proves the CLI study path never
    invokes it. Before stage 2 of the ttyd retirement, ``start_session()``
    unconditionally called ``start_ttyd_background()``, which shelled out to
    whatever ``ttyd`` it found on PATH with an empty password whenever neither
    ``--web`` nor ``--lan`` was passed (R-03: a writable, unauthenticated
    terminal on ``127.0.0.1:7681``).
    """

    def test_fake_ttyd_on_path_is_never_invoked(self, tmp_path, monkeypatch):
        marker = tmp_path / "ttyd-was-spawned"
        bin_dir = tmp_path / "fakebin"
        bin_dir.mkdir()
        fake_ttyd = bin_dir / "ttyd"
        fake_ttyd.write_text(f"#!/bin/sh\ntouch {marker}\n")
        fake_ttyd.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.tmux.os.execvp"),
            # NOTE: this patches the process-wide `shutil.which` (all modules
            # share the one `shutil` module object), so it must resolve "ttyd"
            # for real — not just stub "claude" — or this test cannot tell
            # apart "ttyd was never looked up" from "the patch masked it".
            patch(
                "studyloop.agent_launcher.shutil.which",
                side_effect=lambda name: str(fake_ttyd) if name == "ttyd" else "/usr/bin/claude",
            ),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
        ):
            start_session("Python Decorators", "claude", "study", "elapsed", 7, False)

        # Poll rather than check once: a real spawn is an async subprocess, so
        # a single immediate check could pass by luck even with the spawn
        # still present and merely slow to touch the marker.
        for _ in range(20):
            if marker.exists():
                break
            time.sleep(0.05)
        assert not marker.exists(), (
            "ttyd was spawned from the CLI study path even with no --web/--lan; "
            "this is exactly the unauthenticated-terminal regression R-03 describes."
        )


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
