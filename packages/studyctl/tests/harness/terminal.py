"""Terminal UAT harness — drives real terminal sessions via pexpect.

Simulates a real user: spawns processes, reads terminal output, sends
keystrokes. Catches bugs that mock-agent tests miss (session kill races,
tmux client attachment, nested sessions).
"""

from __future__ import annotations

import subprocess
import sys

import pexpect


class TerminalSession:
    """Drive a real terminal session for UAT testing.

    Spawns studyctl commands via pexpect, attaches to tmux sessions,
    and sends keystrokes exactly as a user would.
    """

    def __init__(self) -> None:
        self._child: pexpect.spawn | None = None
        self._session_name: str | None = None

    @property
    def session_name(self) -> str | None:
        return self._session_name

    def spawn_study(
        self,
        topic: str,
        *,
        energy: int = 5,
        agent_cmd: str | None = None,
        timeout: int = 15,
    ) -> None:
        """Spawn studyctl study in a real terminal via pexpect.

        This creates the tmux session in detached mode (pexpect doesn't
        have a terminal for tmux to attach to), then we attach separately.
        """
        cmd = f"{sys.executable} -m studyctl.cli study '{topic}' --energy {energy} --agent claude"

        env = dict(__import__("os").environ)
        if agent_cmd:
            env["STUDYCTL_TEST_AGENT_CMD"] = agent_cmd
        # Remove TMUX so studyctl uses attach mode (which fails gracefully
        # in pexpect since there's no real tmux client — the session is
        # created detached and we attach separately).
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)

        self._child = pexpect.spawn(cmd, env=env, timeout=timeout, encoding="utf-8")
        # Wait for session creation — the command will try to exec tmux attach
        # which will fail/exit since pexpect isn't a tmux client. But the
        # detached session is already created.
        self._child.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=10)

        # Read session name from state file
        import json
        from pathlib import Path

        state_file = Path.home() / ".config" / "studyctl" / "session-state.json"
        for _ in range(20):
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text())
                    if state.get("tmux_session"):
                        self._session_name = state["tmux_session"]
                        return
                except (json.JSONDecodeError, OSError):
                    pass
            import time

            time.sleep(0.5)
        raise TimeoutError("Session state file not created after spawn")

    def attach_and_send_q(self, *, timeout: int = 15) -> bool:
        """Attach to the tmux session and send Q to the sidebar pane.

        Returns True if the session was killed.

        Attaches a real tmux client (simulating a user), then sends Q.
        Checks session existence directly because when tmux kills a session
        with a client attached, the client may switch to another session
        instead of exiting (so pexpect EOF is unreliable).
        """
        import json
        import time
        from pathlib import Path

        assert self._session_name, "No session — call spawn_study first"

        # Attach to tmux session — this simulates a real user
        child = pexpect.spawn(
            f"tmux attach-session -t {self._session_name}",
            timeout=timeout,
            encoding="utf-8",
        )

        # Wait for the session to render
        time.sleep(2)

        # Read sidebar pane ID from state file
        state_file = Path.home() / ".config" / "studyctl" / "session-state.json"
        state = json.loads(state_file.read_text())
        sidebar_pane = state.get("tmux_sidebar_pane")

        if sidebar_pane:
            subprocess.run(
                ["tmux", "send-keys", "-t", sidebar_pane, "Q"],
                capture_output=True,
            )

        # Poll until the session is destroyed (don't rely on pexpect EOF —
        # tmux may switch the client to another session instead of exiting).
        deadline = time.monotonic() + timeout
        killed = False
        while time.monotonic() < deadline:
            if not self.session_exists():
                killed = True
                break
            time.sleep(0.5)

        # Clean up the pexpect child
        if child.isalive():
            child.close(force=True)
        else:
            child.close()

        if not killed:
            self._dump_diagnostics()

        return killed

    def _dump_diagnostics(self) -> None:
        """Dump tmux session state for debugging test failures."""
        import sys

        if not self._session_name:
            return

        print(f"\n=== UAT DIAGNOSTICS: {self._session_name} ===", file=sys.stderr)

        # List panes
        result = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-t",
                self._session_name,
                "-F",
                "#{pane_id} #{pane_current_command} #{pane_pid} dead=#{pane_dead}",
            ],
            capture_output=True,
            text=True,
        )
        print(f"Panes: {result.stdout.strip()}", file=sys.stderr)

        # Capture each pane's content
        for line in result.stdout.strip().splitlines():
            pane_id = line.split()[0]
            cap = subprocess.run(
                ["tmux", "capture-pane", "-t", pane_id, "-p", "-S", "-10"],
                capture_output=True,
                text=True,
            )
            print(f"\n--- Pane {pane_id} scrollback ---", file=sys.stderr)
            print(cap.stdout, file=sys.stderr)

        # Check state file
        import json
        from pathlib import Path

        state_file = Path.home() / ".config" / "studyctl" / "session-state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            print(f"\nState mode: {state.get('mode')}", file=sys.stderr)

        # Check remain-on-exit
        result = subprocess.run(
            ["tmux", "show-option", "-t", self._session_name, "remain-on-exit"],
            capture_output=True,
            text=True,
        )
        print(f"remain-on-exit: {result.stdout.strip()}", file=sys.stderr)
        print("=== END DIAGNOSTICS ===\n", file=sys.stderr)

    def session_exists(self) -> bool:
        """Check if the tmux session still exists."""
        if not self._session_name:
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", self._session_name],
            capture_output=True,
        )
        return result.returncode == 0

    def cleanup(self) -> None:
        """Kill any remaining processes and sessions."""
        if self._child and self._child.isalive():
            self._child.close(force=True)
        if self._session_name:
            subprocess.run(
                ["tmux", "kill-session", "-t", self._session_name],
                capture_output=True,
            )
        # Clean IPC files
        from pathlib import Path

        config_dir = Path.home() / ".config" / "studyctl"
        for name in (
            "session-state.json",
            "session-topics.md",
            "session-parking.md",
            "session-oneline.txt",
        ):
            f = config_dir / name
            if f.exists():
                f.unlink()
