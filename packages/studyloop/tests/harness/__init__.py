"""Test harness for studyloop integration tests.

Provides a clean API for testing tmux-based study sessions end-to-end
with reliable polling instead of fixed sleeps.

Usage::

    @pytest.fixture
    def study_session(tmp_path):
        with StudySession(tmp_path) as session:
            yield session

    def test_start(study_session):
        study_session.start("Python Decorators", energy=7)
        study_session.assert_agent_running()
"""

from .agents import (
    fast_exit_agent,
    long_running_agent,
    matrix_agent,
    parking_agent,
    topic_logger_agent,
)
from .multiplexer import MultiplexerHarness
from .study import StudySession
from .tmux import TmuxHarness

__all__ = [
    "MultiplexerHarness",
    "StudySession",
    "TmuxHarness",
    "fast_exit_agent",
    "long_running_agent",
    "matrix_agent",
    "parking_agent",
    "topic_logger_agent",
]
