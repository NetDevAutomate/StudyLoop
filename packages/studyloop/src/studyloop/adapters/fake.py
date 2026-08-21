"""Fake adapter — deterministic harness agent, gated behind STUDYLOOP_TEST_AGENT.

Registers the ``studyloop-fake-agent`` console script (see
``studyloop/testing/fake_agent.py``) as a spawnable agent so the e2e journey
can walk the REAL spawn → PTY → WebSocket → terminal path without an LLM or
a vendor CLI installed.

Gating: the module exposes ``ADAPTER = None`` unless ``STUDYLOOP_TEST_AGENT=1``
is set when the registry builds. The registry skips non-AgentAdapter values,
so in normal operation the 'fake' agent simply does not exist — it can never
appear in a real user's picker.
"""

from __future__ import annotations

import os
import shlex
import shutil
from typing import TYPE_CHECKING

from studyloop.adapters._protocol import AgentAdapter
from studyloop.adapters._strategies import cli_flag_setup

if TYPE_CHECKING:
    from pathlib import Path


def _fake_launch(persona_path: Path, resume: bool) -> str:
    binary = shutil.which("studyloop-fake-agent") or "studyloop-fake-agent"
    # The fake agent reads the persona file at argv[1] to resolve the study
    # topic and pick its question bank, so this path is load-bearing, not
    # decorative. It MUST be shell-quoted: this string is handed to a shell, and
    # an unquoted path containing a space would split into two arguments, leaving
    # argv[1] a fragment. The agent would then fail to read it and fall back to
    # echo mode -- teaching silently replaced by an echo, with nothing logged.
    return f"{binary} {shlex.quote(str(persona_path))}"


ADAPTER = (
    AgentAdapter(
        name="fake",
        binary="studyloop-fake-agent",
        setup=cli_flag_setup,
        launch_cmd=_fake_launch,
    )
    if os.environ.get("STUDYLOOP_TEST_AGENT") == "1"
    else None
)
