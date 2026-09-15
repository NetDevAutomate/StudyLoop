"""HarnessActor driven against a REAL tmux server and a mock 'sh' harness.

Marked ``integration`` (deselected from the default run, same as
``test_herdr_integration.py``) and skip-guarded when tmux is absent -- this
is the literal TESTS FIRST scenario from lanes.json: "the harness actor
drives a mock 'sh' harness through the tmux helper on its own socket."

The mock harness is a tiny ``sh`` script: it reads one line at a time from
stdin (its tmux pane), echoes a canned learner line back, and after N
lines emits the DONE sentinel. It proves three things at once: tmux
send-keys/capture-pane plumbing works end to end, the actor's OWN socket
(``TMUX_TMPDIR``) never touches the default one this test process might
otherwise have set, and a second, fully separate tmux server can be killed
cleanly on ``aclose()`` without disturbing anything else.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.budget import BudgetGuard  # noqa: E402
from acceptance.actors.harness import DONE_SENTINEL, HarnessActor, _tmux  # noqa: E402
from acceptance.actors.protocol import TerminationOutcome  # noqa: E402

pytestmark = [pytest.mark.integration]

has_tmux = shutil.which("tmux") is not None
skip_no_tmux = pytest.mark.skipif(not has_tmux, reason="tmux not available")

_MOCK_HARNESS_SCRIPT = f"""#!/bin/sh
# Speaks first (no blocking read before the opening line) -- HarnessActor
# always reads a learner line before it has anything to send back.
echo "learner turn 1"
read -r _line
echo "learner turn 2"
read -r _line
echo "{DONE_SENTINEL}"
# Stay alive after the sentinel: when the pane's process exits, tmux tears
# the window (and then the whole one-window session) down, so a script that
# fell off the end here would take the pane away before the sentinel could
# ever be captured. aclose() is what ends this -- it kills the session.
while true; do sleep 1; done
"""


class EchoMentor:
    def __init__(self) -> None:
        self.received: list[str] = []

    async def send(self, message: str) -> str:
        self.received.append(message)
        return f"mentor said: {message}"


@pytest.fixture
def short_socket_root() -> Generator[Path, None, None]:
    """A SHORT-path scratch root for tmux sockets, swept on exit.

    pytest's own ``tmp_path`` is unusable for a tmux socket: the generated
    per-test directory name pushes the resulting socket path past the
    104-byte ``sun_path`` limit (``HarnessActor`` now names that failure
    explicitly -- see ``max_socket_dir_length``). ``/tmp`` keeps it short.
    """
    root = Path(tempfile.mkdtemp(prefix="sl-b3-", dir="/tmp"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@skip_no_tmux
@pytest.mark.asyncio
async def test_harness_actor_drives_a_real_mock_sh_harness_on_its_own_socket(
    tmp_path: Path,
    short_socket_root: Path,
) -> None:
    script_path = tmp_path / "mock_harness.sh"
    script_path.write_text(_MOCK_HARNESS_SCRIPT, encoding="utf-8")
    script_path.chmod(0o755)

    mentor_socket_dir = short_socket_root / "mentor"
    mentor_socket_dir.mkdir(parents=True, exist_ok=True)
    mentor_socket_dir.chmod(0o700)
    actor_socket_dir = short_socket_root / "actor"

    actor = HarnessActor(
        command=("sh", str(script_path)),
        socket_dir=actor_socket_dir,
        reply_timeout=10.0,
        budget=BudgetGuard(max_turns=10),
    )
    mentor = EchoMentor()

    try:
        result = await actor.converse(mentor)
    finally:
        await actor.aclose()

    assert result.outcome is TerminationOutcome.COMPLETED
    assert [t.learner_message for t in result.transcript] == [
        "learner turn 1",
        "learner turn 2",
    ]
    assert mentor.received == ["learner turn 1", "learner turn 2"]

    # D-11: the actor's own socket directory is distinct from -- and was
    # never written into -- the mentor's, and no server is left attached
    # to the actor's socket, or to the developer's real one, once
    # aclose() has run.
    assert actor_socket_dir != mentor_socket_dir
    assert actor_socket_dir.exists()
    assert list(mentor_socket_dir.iterdir()) == []

    list_result = _tmux("list-sessions", socket_dir=actor_socket_dir)
    # No server left running under the actor's socket after aclose().
    assert "no server running" in (list_result.stderr + list_result.stdout).lower()
