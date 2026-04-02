"""Mock agent script builders for integration tests.

Each function creates a bash script in tmp_path and returns the command
string suitable for STUDYCTL_TEST_AGENT_CMD.

All agents accept {persona_file} placeholder which gets substituted
by the study command at launch time.
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _write_script(path: Path, content: str) -> Path:
    """Write a bash script with executable permissions."""
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def long_running_agent(tmp_path: Path) -> str:
    """Agent that stays alive indefinitely. Traps SIGTERM for clean exit."""
    script = _write_script(
        tmp_path / "mock-agent.sh",
        """#!/usr/bin/env bash
trap 'exit 0' TERM INT
echo "Mock agent started (persona: $1)"
while true; do sleep 1; done
""",
    )
    return f"{script} {{persona_file}}"


def topic_logger_agent(
    tmp_path: Path,
    topics: list[tuple[str, str, str]] | None = None,
) -> str:
    """Agent that logs topics via studyctl CLI then stays alive.

    Args:
        topics: List of (name, status, note) tuples to log.
            Defaults to one "Closures" learning topic.
    """
    if topics is None:
        topics = [("Closures", "learning", "exploring basics")]

    # Build the topic logging commands
    topic_cmds = ""
    for name, status_, note in topics:
        topic_cmds += f'studyctl topic "{name}" --status {status_} --note "{note}"\n'
        topic_cmds += "sleep 1\n"

    script = _write_script(
        tmp_path / "mock-agent-topics.sh",
        f"""#!/usr/bin/env bash
trap 'exit 0' TERM INT
echo "Mock agent started"
sleep 2  # wait for sidebar to initialize
{topic_cmds}
# Stay alive
while true; do sleep 1; done
""",
    )
    return f"{script} {{persona_file}}"


def fast_exit_agent(tmp_path: Path) -> str:
    """Agent that logs one topic and exits immediately.

    Useful for testing cleanup-on-exit and the wrapper command chain.
    """
    script = _write_script(
        tmp_path / "mock-agent-fast.sh",
        """#!/usr/bin/env bash
echo "Fast agent — exiting"
sleep 1
studyctl topic "Quick Topic" --status win --note "done"
sleep 1
""",
    )
    return f"{script} {{persona_file}}"


def parking_agent(tmp_path: Path) -> str:
    """Agent that parks a question then stays alive.

    Uses session-parking.md IPC file directly (more reliable than CLI
    which depends on PATH setup and DB availability in test environments).
    """
    script = _write_script(
        tmp_path / "mock-agent-park.sh",
        """#!/usr/bin/env bash
trap 'exit 0' TERM INT
echo "Mock agent started"
sleep 2
# Write to IPC file directly (sidebar polls this)
PARKING_FILE="$HOME/.config/studyctl/session-parking.md"
echo "- What about metaclasses?" >> "$PARKING_FILE"
# Stay alive
while true; do sleep 1; done
""",
    )
    return f"{script} {{persona_file}}"


def crash_agent(tmp_path: Path) -> str:
    """Agent that exits with non-zero status immediately.

    Useful for testing error handling and cleanup when agent crashes.
    """
    script = _write_script(
        tmp_path / "mock-agent-crash.sh",
        """#!/usr/bin/env bash
echo "Agent crashing!"
exit 1
""",
    )
    return f"{script} {{persona_file}}"
