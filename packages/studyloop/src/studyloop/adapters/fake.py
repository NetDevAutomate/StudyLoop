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
import shutil
from typing import TYPE_CHECKING

from studyloop.adapters._protocol import AgentAdapter
from studyloop.adapters._strategies import cli_flag_setup

if TYPE_CHECKING:
    from pathlib import Path


def _fake_launch(persona_path: Path, resume: bool) -> str:
    binary = shutil.which("studyloop-fake-agent") or "studyloop-fake-agent"
    # The fake agent takes the persona path as argv[1] and ignores it —
    # passing it keeps the launch shape identical to real adapters.
    return f"{binary} {persona_path}"


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
