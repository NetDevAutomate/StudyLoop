"""Send/expect helper for driving a mentor process over one tmux pane.

Acceptance validators stay DB-only (B1 council ruling D-17): pane text
captured here is EVIDENCE attached to a run's bundle, never itself an
assertion target. This module's job is purely mechanical -- send one
learner turn, wait for the pane's visible output to grow past a captured
baseline, record what came back, and stop -- with a hard per-turn timeout
AND a total per-run turn budget (grok F9) so a runaway harness, real or
fake, can never hang an acceptance run indefinitely.

Used by the CLI/tmux harness-matrix acceptance lane
(tests/acceptance/test_harness_matrix_live.py) and unit-tested here against
a scripted ``sh`` "harness" rather than any real coding-agent binary --
that scripted-harness contract is this module's own TESTS FIRST item, from
B2's brief.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tmux import TmuxHarness


class TurnBudgetExceededError(RuntimeError):
    """Raised when a driven conversation exceeds its turn or time budget.

    Two distinct causes collapse into one exception because a caller's
    response is the same either way: stop driving turns, capture whatever
    evidence exists so far, and treat the run as budget-exhausted rather
    than silently retrying (B1 council ruling D-17's sibling for live runs:
    "a missing tool call ... is a FAILURE, not a flake to retry").
    """


@dataclass(slots=True)
class TurnRecord:
    """One completed turn: what was sent, what came back, how long it took."""

    prompt: str
    pane_output: str
    elapsed: float


@dataclass(slots=True)
class PaneDriver:
    """Drives scripted learner turns against one tmux pane, budget-guarded."""

    tmux: TmuxHarness
    pane_id: str
    max_turns: int
    per_turn_timeout: float = 30.0
    poll_interval: float = 0.5
    records: list[TurnRecord] = field(default_factory=list, init=False)

    def send_turn(self, prompt: str) -> TurnRecord:
        """Send one learner turn and wait for a REPLY, not just an echo.

        A naive "did the pane's raw content change at all" check fires the
        instant the tty echoes the keystrokes/Enter we just sent -- before
        the mentor process has produced a single character of its own
        reply. That false-positive would make a genuinely silent, hung
        harness look answered. Instead this counts non-blank lines: the
        keystroke echo of a (single-line) prompt adds exactly one non-blank
        line, so a real reply is anything that pushes the count past
        ``baseline + 1``. ACKNOWLEDGED LIMITATION: this assumes a
        single-line prompt and a harness that echoes input to the pane
        (true for the scripted `sh` harness this module is unit-tested
        against and every terminal-attached CLI observed so far); a harness
        with a fundamentally different rendering model may need its own
        reply-detection quirk as a fixture, not a rewrite of this method
        (this lane's brief: "per-harness quirks as fixtures, not if/else
        soup") -- tracked as a left-out item, not silently assumed away.

        Raises :class:`TurnBudgetExceededError` if this call would exceed
        ``max_turns`` (checked BEFORE sending anything -- a runaway
        conversation never gets one turn further than its budget allows)
        or if ``per_turn_timeout`` elapses with no reply.
        """
        if len(self.records) >= self.max_turns:
            raise TurnBudgetExceededError(
                f"turn budget exhausted: {self.max_turns} turn(s) already sent "
                f"to pane {self.pane_id!r}"
            )

        baseline = self.tmux.capture_pane(self.pane_id, lines=400)
        baseline_lines = _non_blank_line_count(baseline)
        start = time.monotonic()
        self.tmux.send_keys(self.pane_id, prompt, enter=True)

        def _replied() -> bool:
            current = self.tmux.capture_pane(self.pane_id, lines=400)
            return _non_blank_line_count(current) > baseline_lines + 1

        turn_number = len(self.records) + 1
        try:
            self.tmux.wait_for(
                _replied,
                timeout=self.per_turn_timeout,
                interval=self.poll_interval,
                msg=f"reply on pane {self.pane_id!r} after turn {turn_number}",
            )
        except TimeoutError as exc:
            # Capture and record whatever the pane shows RIGHT NOW, before
            # raising -- this is exactly the run where evidence matters
            # most (a hung/silent harness), and a bundle writer that only
            # sees `driver.records` (evidence.py's caller does) must not
            # find it empty just because the turn that hung never got a
            # normal return (review finding, B2 fix round 1).
            elapsed = time.monotonic() - start
            output = self.tmux.capture_pane(self.pane_id, lines=400)
            self.records.append(TurnRecord(prompt=prompt, pane_output=output, elapsed=elapsed))
            raise TurnBudgetExceededError(
                f"turn {turn_number} exceeded {self.per_turn_timeout}s "
                f"with no reply on pane {self.pane_id!r} -- treating the runaway "
                "harness as budget-exhausted, not retrying"
            ) from exc

        elapsed = time.monotonic() - start
        output = self.tmux.capture_pane(self.pane_id, lines=400)
        record = TurnRecord(prompt=prompt, pane_output=output, elapsed=elapsed)
        self.records.append(record)
        return record


def _non_blank_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())
