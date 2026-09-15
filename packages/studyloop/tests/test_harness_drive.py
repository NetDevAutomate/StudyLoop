"""Mechanics tests for harness/drive.py's PaneDriver.

(b)/budget-enforcement TESTS FIRST items from B2's brief: "the tmux drive
helper unit-tested against a scripted `sh` 'harness'" and "budget
enforcement (a runaway fake harness is cut at max-turns/timeout)". These
never launch a real coding-agent binary -- only a throwaway ``sh`` script
under tmux -- so they run under the default ``just test`` gate (marked
``integration`` like test_harness_matrix.py, not ``acceptance``), not only
under ``STUDYLOOP_ACC=1``.

Path bootstrapping mirrors test_harness_matrix.py's convention (sys.path
insert, then a plain import) rather than a conftest.py, which risks the
workspace's "two packages both named tests" pluggy registration conflict.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from harness.drive import PaneDriver, TurnBudgetExceededError  # noqa: E402
from harness.tmux import TmuxHarness  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.integration,
]


def _write_sh_harness(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / name
    script.write_text(body)
    script.chmod(0o755)
    return script


@pytest.fixture
def echo_harness(tmp_path: Path) -> Iterator[tuple[TmuxHarness, str]]:
    """A tmux session running a scripted `sh` "harness" that echoes turns.

    Stands in for a real coding-agent binary: reads one line at a time and
    replies ``reply: <line>`` -- just enough for PaneDriver's "did the pane
    grow" mechanic to observe a real turn/reply cycle without ever touching
    a real agent.
    """
    script = _write_sh_harness(
        tmp_path,
        "echo-harness.sh",
        '#!/usr/bin/env bash\nwhile IFS= read -r line; do\n  echo "reply: $line"\ndone\n',
    )
    tmux = TmuxHarness()
    session_name = f"drive-test-echo-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, str(script)],
        check=True,
        capture_output=True,
    )
    tmux.track_session(session_name)
    panes = tmux.wait_for_value(
        lambda: tmux.list_panes(session_name) or None,
        timeout=10,
        msg="echo harness pane",
    )
    pane_id = panes[0]["pane_id"]
    try:
        yield tmux, pane_id
    finally:
        tmux.cleanup()


@pytest.fixture
def silent_harness(tmp_path: Path) -> Iterator[tuple[TmuxHarness, str]]:
    """A tmux session running a scripted `sh` "harness" that NEVER replies.

    The runaway-harness case for the timeout-cutoff test: consumes input
    and produces no output, ever.
    """
    script = _write_sh_harness(
        tmp_path,
        "silent-harness.sh",
        "#!/usr/bin/env bash\ncat >/dev/null\n",
    )
    tmux = TmuxHarness()
    session_name = f"drive-test-silent-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, str(script)],
        check=True,
        capture_output=True,
    )
    tmux.track_session(session_name)
    panes = tmux.wait_for_value(
        lambda: tmux.list_panes(session_name) or None,
        timeout=10,
        msg="silent harness pane",
    )
    pane_id = panes[0]["pane_id"]
    try:
        yield tmux, pane_id
    finally:
        tmux.cleanup()


class TestPaneDriverMechanics:
    def test_send_turn_returns_the_reply_that_grew_the_pane(
        self, echo_harness: tuple[TmuxHarness, str]
    ) -> None:
        tmux, pane_id = echo_harness
        driver = PaneDriver(tmux, pane_id, max_turns=3, per_turn_timeout=10.0)

        record = driver.send_turn("hello")

        assert record.prompt == "hello"
        assert "reply: hello" in record.pane_output
        assert record.elapsed >= 0
        assert driver.records == [record]

    def test_multiple_turns_each_wait_for_their_own_growth(
        self, echo_harness: tuple[TmuxHarness, str]
    ) -> None:
        tmux, pane_id = echo_harness
        driver = PaneDriver(tmux, pane_id, max_turns=3, per_turn_timeout=10.0)

        first = driver.send_turn("what is a decorator?")
        second = driver.send_turn("and a closure?")

        assert "reply: what is a decorator?" in first.pane_output
        assert "reply: and a closure?" in second.pane_output
        assert len(driver.records) == 2


class TestBudgetEnforcement:
    def test_exceeding_max_turns_raises_without_sending_another_turn(
        self, echo_harness: tuple[TmuxHarness, str]
    ) -> None:
        tmux, pane_id = echo_harness
        driver = PaneDriver(tmux, pane_id, max_turns=1, per_turn_timeout=10.0)

        driver.send_turn("first turn")

        with pytest.raises(TurnBudgetExceededError, match="turn budget exhausted"):
            driver.send_turn("second turn should never be sent")

        # The rejected turn must not have reached the pane at all.
        assert "second turn" not in tmux.capture_pane(pane_id, lines=400)

    def test_runaway_harness_is_cut_at_the_per_turn_timeout(
        self, silent_harness: tuple[TmuxHarness, str]
    ) -> None:
        tmux, pane_id = silent_harness
        driver = PaneDriver(tmux, pane_id, max_turns=5, per_turn_timeout=1.0, poll_interval=0.1)

        start = time.monotonic()
        with pytest.raises(TurnBudgetExceededError, match="exceeded"):
            driver.send_turn("are you there?")
        elapsed = time.monotonic() - start

        # A generous ceiling, not a tight timing assertion: proves the cutoff
        # actually fired near the configured timeout rather than hanging for
        # the test's own default pytest timeout.
        assert elapsed < 5.0

    def test_timeout_still_records_a_turn_before_raising(
        self, silent_harness: tuple[TmuxHarness, str]
    ) -> None:
        """Evidence must survive the exact run where it matters most: a
        hung/silent harness. A caller that only inspects `driver.records`
        after catching TurnBudgetExceededError (as the harness-matrix live
        test's evidence-bundle writer does) must find the pane capture from
        the timed-out turn, not an empty list."""
        tmux, pane_id = silent_harness
        driver = PaneDriver(tmux, pane_id, max_turns=5, per_turn_timeout=1.0, poll_interval=0.1)

        with pytest.raises(TurnBudgetExceededError):
            driver.send_turn("are you there?")

        assert len(driver.records) == 1
        assert driver.records[0].prompt == "are you there?"
        assert driver.records[0].elapsed >= 1.0
