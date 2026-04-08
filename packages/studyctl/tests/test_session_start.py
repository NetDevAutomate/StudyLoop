"""Tests for session/start.py — start_session orchestration and helpers.

No conftest.py (pluggy conflict with agent-session-tools). All fixtures inline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from studyctl.session.start import (
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
            patch("studyctl.session.start._gather_review_context", return_value=None),
            patch("studyctl.session.start._gather_content_context", return_value=None),
            patch("studyctl.settings.load_settings", side_effect=Exception("no config")),
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
            patch("studyctl.tmux.shutil.which", return_value=None),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Test Topic", None, "study", "elapsed", 5, False)
        assert "tmux" in exc_info.value.message.lower()

    def test_raises_when_no_agent_found(self):
        with (
            patch("studyctl.tmux.is_tmux_available", return_value=True),
            patch("studyctl.agent_launcher.shutil.which", return_value=None),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Test Topic", None, "study", "elapsed", 5, False)
        assert "No AI agent" in exc_info.value.message

    def test_raises_when_session_already_active(self):
        active_state = {"study_session_id": "x"}
        with (
            patch("studyctl.tmux.is_tmux_available", return_value=True),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value=active_state),
            patch("studyctl.session_state.STATE_FILE") as sf,
            patch("studyctl.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            sf.exists.return_value = True
            start_session("Test Topic", "claude", "study", "elapsed", 5, False)
        assert "already active" in exc_info.value.message

    def test_raises_when_db_session_creation_fails(self, tmp_path):
        with (
            patch("studyctl.tmux.is_tmux_available", return_value=True),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session.cleanup.auto_clean_zombies"),
            patch("studyctl.history.start_study_session", return_value=None),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Test Topic", "claude", "study", "elapsed", 5, False)
        assert "Failed to start session" in exc_info.value.message


# ---------------------------------------------------------------------------
# start_session — happy path (mocked tmux + DB)
# ---------------------------------------------------------------------------


class TestStartSessionHappyPath:
    def test_session_starts_successfully(self, tmp_path):
        with (
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyctl.tmux.os.execvp"),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.history.start_study_session", return_value="abc12345"),
            patch("studyctl.session.cleanup.auto_clean_zombies"),
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
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyctl.tmux.os.execvp"),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.history.start_study_session", return_value="deadbeef12345678"),
            patch("studyctl.session.cleanup.auto_clean_zombies"),
            patch("studyctl.tmux.create_session", side_effect=mock_create_session),
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
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyctl.tmux.os.execvp"),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.history.start_study_session", return_value="abc12345"),
            patch("studyctl.session.cleanup.auto_clean_zombies"),
            patch("studyctl.tmux.create_session", side_effect=mock_create_session),
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


# ---------------------------------------------------------------------------
# CLI wrapper: _handle_start delegates and translates errors
# ---------------------------------------------------------------------------


class TestHandleStartCLIWrapper:
    """Test that the CLI wrapper properly translates SessionStartError to ctx.exit(1)."""

    def test_handle_start_exits_on_tmux_missing(self):
        from click.testing import CliRunner

        from studyctl.cli._study import study

        runner = CliRunner()
        with patch("studyctl.tmux.shutil.which", return_value=None):
            result = runner.invoke(study, ["Test Topic"])
        assert result.exit_code != 0
        assert "tmux" in result.output.lower()

    def test_handle_start_exits_on_no_agent(self):
        from click.testing import CliRunner

        from studyctl.cli._study import study

        runner = CliRunner()
        with (
            patch("studyctl.tmux.is_tmux_available", return_value=True),
            patch("studyctl.agent_launcher.shutil.which", return_value=None),
            patch("studyctl.session_state.read_session_state", return_value={}),
        ):
            result = runner.invoke(study, ["Test Topic"])
        assert result.exit_code != 0
        assert "No AI agent" in result.output
