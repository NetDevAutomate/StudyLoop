"""Executable guards for tests that spawn real local processes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_no_test_writes_to_real_user_state() -> None:
    """Every writable StudyLoop resolver must point away from learner data."""
    from agent_session_tools.config_loader import DEFAULT_CONFIG
    from agent_session_tools.config_loader import get_db_path as ast_get_db_path
    from studyloop.settings import (
        DEFAULT_DB,
        DEFAULT_STATE_DIR,
        get_db_path,
        get_state_dir,
        load_settings,
    )

    assert get_state_dir() != DEFAULT_STATE_DIR, "state_dir escaped test isolation"
    assert get_db_path() != DEFAULT_DB, "studyloop session DB escaped test isolation"
    assert load_settings().session_db != DEFAULT_DB, (
        "Settings.session_db escaped test isolation (history/_connection.py reads this one)"
    )
    assert str(ast_get_db_path()) != DEFAULT_CONFIG["database"]["path"], (
        "agent_session_tools session DB escaped test isolation"
    )

    process_root = Path(os.environ["TMUX_TMPDIR"]).resolve().parent
    for variable in ("TMUX_TMPDIR", "HERDR_SOCKET_PATH", "HERDR_CONFIG_PATH"):
        isolated_path = Path(os.environ[variable]).resolve()
        assert isolated_path.is_relative_to(process_root), (
            f"{variable} escaped test isolation: {isolated_path}"
        )


def test_test_helpers_do_not_bind_real_user_session_dir() -> None:
    """Executable browser/lifecycle helpers must honour the isolated IPC root."""
    tests_root = Path(__file__).parent
    unsafe_expression = "Path.home()" + ' / ".config"' + ' / "studyloop"'
    allowed_live_readers = {"test_extractor_llm_live.py"}
    offenders = [
        str(path.relative_to(tests_root))
        for path in tests_root.rglob("*.py")
        if path.name not in allowed_live_readers
        and unsafe_expression in path.read_text(encoding="utf-8")
    ]

    assert not offenders, f"test IPC paths bypass STUDYLOOP_SESSION_DIR: {offenders}"


@pytest.mark.integration
def test_herdr_integration_uses_private_xdg_config() -> None:
    """A live Herdr test server must never restore the user's session snapshot."""
    process_root = Path(os.environ["TMUX_TMPDIR"]).resolve().parent
    xdg_config = Path(os.environ["XDG_CONFIG_HOME"]).resolve()

    assert xdg_config.is_relative_to(process_root)
