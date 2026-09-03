"""Tmux environment orchestration — session creation, pane layout, agent launch.

Ordering is critical:
  1. Create tmux session (detached, with agent command)
  2. Set environment + options on the session
  3. Switch/attach FIRST so terminal size is correct
  4. Split pane for sidebar (percentage is relative to actual terminal)
  5. Focus main pane
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _ensure_claude_trust(directory: Path) -> None:
    """Add a directory to Claude Code's trusted projects in ~/.claude/settings.json.

    Trust is checked by walking up the directory tree, so trusting the
    sessions parent dir covers all future session directories.
    """
    import json
    from pathlib import Path as _Path

    claude_settings = _Path.home() / ".claude" / "settings.json"
    if not claude_settings.exists():
        return  # No Claude Code installed

    try:
        data = json.loads(claude_settings.read_text())
    except (json.JSONDecodeError, OSError):
        return

    projects = data.setdefault("projects", {})
    dir_key = str(directory)

    if projects.get(dir_key, {}).get("hasTrustDialogAccepted"):
        return  # Already trusted

    projects.setdefault(dir_key, {})["hasTrustDialogAccepted"] = True

    # Atomic write via temp file
    import tempfile

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(claude_settings.parent), suffix=".json")
    except OSError:
        return

    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, claude_settings)
    except Exception:
        with __import__("contextlib").suppress(OSError):
            os.unlink(tmp_path)


def setup_session_dir(
    session_dir: Path,
    topic: str,
) -> Path:
    """Create session directory with CLAUDE.md and studyloop wrapper.

    Returns the path to the studyloop wrapper script.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write a CLAUDE.md so Claude knows this is a study session directory
    # and doesn't waste time exploring for project context.
    claude_md = session_dir / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            f"# Study Session: {topic}\n\n"
            "This is a studyloop study session directory. "
            "Do not search for code or project files here.\n\n"
            "Use `studyloop topic` to log topics and `studyloop park` to park questions.\n"
        )

    # Pre-trust the session directory for Claude Code so the workspace
    # trust prompt doesn't block automated (non-interactive) sessions.
    # Trust is stored in ~/.claude/settings.json under projects[path].hasTrustDialogAccepted.
    # Trust both the parent (for future sessions) AND the specific session dir
    # (Claude Code may not walk up the tree for all trust checks).
    _ensure_claude_trust(session_dir.parent)
    _ensure_claude_trust(session_dir)

    # Create a studyloop wrapper in the session directory that uses the
    # correct Python (the one running this process). Without this, any
    # globally installed older studyloop may shadow the dev version and
    # `studyloop topic` fails with "unknown command".
    wrapper = session_dir / "studyloop"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} -m studyloop.cli "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return wrapper


def build_wrapped_agent_cmd(
    session_dir: Path,
    agent_cmd: str,
) -> str:
    """Wrap the agent command with PATH prefix and exit cleanup.

    When the agent exits (user quits, types /exit, or Ctrl+C), the
    session cleans up automatically via cleanup_on_exit().
    """
    python = sys.executable
    path_prefix = f"export PATH={session_dir}:$PATH; "

    # Propagate STUDYLOOP_* env vars so cleanup_on_exit() (which runs as
    # a fresh Python subprocess) inherits overrides like STUDYLOOP_KIRO_AGENTS_DIR.
    # These must be exported in the shell command because tmux set-environment
    # only affects NEW panes, not the already-running shell.
    env_exports = ""
    for key, value in os.environ.items():
        if key.startswith("STUDYLOOP_") and key != "STUDYLOOP_TEST_AGENT_CMD":
            env_exports += f"export {key}={shlex.quote(value)}; "

    return (
        f"{path_prefix}"
        f"{env_exports}"
        f"{agent_cmd}; "
        f'{python} -c "'
        f"from studyloop.session.cleanup import cleanup_on_exit; "
        f"cleanup_on_exit()"
        f'"'
    )


def create_tmux_environment(
    *,
    session_name: str,
    session_dir: Path,
    wrapped_agent_cmd: str,
    session_state_dir: Path,
    sidebar: bool = True,
) -> dict:
    """Create multiplexer session with agent and sidebar panes.

    Returns dict with mux_main_pane and mux_sidebar_pane IDs.
    Also writes legacy tmux_main_pane/tmux_sidebar_pane for backwards compat.
    """
    from studyloop.multiplexer import get_backend

    mux = get_backend()
    python = sys.executable
    sidebar_cmd = f"{python} -m studyloop.tui.sidebar"

    # Create session in the session directory -- agent conversation history
    # (.claude/, .kiro/, etc.) is preserved here across sessions.
    main_pane = mux.create_session(
        session_name,
        command=wrapped_agent_cmd,
        cwd=str(session_dir),
        env={"PATH": f"{session_dir}:{os.environ.get('PATH', '')}"},
    )

    # Configure backend-specific session defaults (encapsulates set_option
    # calls for tmux, workspace labels for herdr, etc.)
    mux.configure_session_defaults(session_name)

    if not sidebar:
        # Web sessions render activity/progress in native StudyLoop panels.
        # Hide tmux chrome so the learner sees only the agent terminal.
        # This is tmux-specific — other backends handle it in configure_session_defaults.
        from studyloop.multiplexer import TmuxBackend

        if isinstance(mux, TmuxBackend):
            from studyloop.tmux import set_option

            set_option(session_name, "status", "off")

    # --- Switch/attach FIRST so the multiplexer resizes to the actual terminal ---
    # This ensures the split percentage is calculated against the real
    # terminal width, not the detached default (80x24).
    already_in_session = mux.is_inside_session()
    if already_in_session:
        mux.switch_client(session_name)

    sidebar_pane = ""
    if sidebar:
        # Split for sidebar (right pane, 25% width)
        sidebar_pane = mux.split_pane(
            main_pane,
            direction="right",
            size=25,
            percentage=True,
            command=sidebar_cmd,
        )

    # Focus main pane (agent)
    mux.select_pane(main_pane)

    return {
        "tmux_main_pane": main_pane,  # legacy key for backwards compat
        "tmux_sidebar_pane": sidebar_pane,  # legacy key for backwards compat
        "mux_main_pane": main_pane,
        "mux_sidebar_pane": sidebar_pane,
        "already_in_tmux": already_in_session,  # legacy key name preserved
    }


def attach_if_needed(session_name: str, already_in_tmux: bool) -> None:
    """Attach to multiplexer session if not already inside one.

    If already in a session, switch_client was called during create_tmux_environment.
    If not, this replaces the current process via the backend's attach method.
    """
    if not already_in_tmux:
        from studyloop.multiplexer import get_backend

        mux = get_backend()
        # Replaces this process via os.execvp -- no code runs after this
        mux.attach(session_name)


def start_web_background(session_name: str, *, lan: bool = False, password: str = "") -> None:
    """Start the web dashboard as a background process and open browser."""
    from studyloop.output import console

    port = _get_web_port()

    # Kill any stale web server left over from a previous session
    _kill_port_occupant(port, expected_cmd="studyloop")

    studyloop_bin = shutil.which("studyloop")
    cmd = (
        [studyloop_bin, "web", "--port", str(port)]
        if studyloop_bin
        else [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)]
    )
    if lan:
        cmd.append("--lan")
    # R-10: the password goes to the child via environment, not argv. Argv is
    # visible to any other local user for the process's whole lifetime via
    # `ps`/`/proc/<pid>/cmdline`; an env var is only readable by that user or
    # root reading /proc/<pid>/environ, which is the same access level `--lan`
    # already grants to this machine's owner. `cli/_web.py`'s `--password`
    # option reads this env var itself (Click `envvar=`) when the flag is
    # absent, so the child needs no special-casing.
    child_env = {**os.environ, "STUDYLOOP_WEB_PASSWORD": password} if password else None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env,
        )
        from studyloop.session_state import write_session_state

        write_session_state({"web_pid": proc.pid, "web_port": port})
        _open_browser(f"http://127.0.0.1:{port}/session")
    except Exception:
        console.print("[yellow]Could not start web dashboard.[/yellow]")


def _kill_port_occupant(port: int, expected_cmd: str = "") -> None:
    """Kill any process listening on *port*.

    If *expected_cmd* is given, only kill when the process command contains
    that string (safety guard against killing unrelated processes).
    """
    import signal
    import time as _time

    killed = False
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if not result.stdout.strip():
            return
        for pid_str in result.stdout.strip().splitlines():
            pid = int(pid_str)
            if expected_cmd:
                ps_result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if expected_cmd not in ps_result.stdout:
                    continue
            with __import__("contextlib").suppress(OSError):
                os.kill(pid, signal.SIGTERM)
                killed = True
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass

    # Wait for the port to be released after killing
    if killed:
        _time.sleep(0.5)


def _get_web_port() -> int:
    """Read web port from config, default 8567."""
    try:
        from studyloop.settings import load_settings

        return getattr(load_settings(), "web_port", 8567)
    except Exception:
        return 8567


def _open_browser(url: str) -> None:
    """Open URL in the configured browser after polling for server readiness.

    Uses os.fork() to create a child process that survives the parent's
    os.execvp(tmux attach). Daemon threads don't survive exec, but forked
    children do (reparented to PID 1).
    """
    pid = os.fork()
    if pid != 0:
        return  # Parent continues with session startup

    # Child process — poll then open browser
    try:
        import time
        import urllib.request
        import webbrowser

        # Poll until server is ready (up to 10 seconds)
        for _ in range(20):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            os._exit(0)  # Server never started

        browser_name = ""
        try:
            from studyloop.settings import load_settings

            browser_name = getattr(load_settings(), "browser", "")
        except Exception:
            pass

        browser_map = {
            "chrome": "Google Chrome",
            "safari": "Safari",
            "firefox": "Firefox",
            "brave": "Brave Browser",
        }

        if browser_name and browser_name.lower() in browser_map:
            app = browser_map[browser_name.lower()]
            # macOS: use open -a for specific browser
            subprocess.Popen(
                ["open", "-a", app, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            webbrowser.open(url)
    except Exception:
        pass
    finally:
        os._exit(0)  # Child must exit, never return to caller
