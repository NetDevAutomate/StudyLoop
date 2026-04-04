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

    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(claude_settings.parent), suffix=".json")
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
    """Create session directory with CLAUDE.md and studyctl wrapper.

    Returns the path to the studyctl wrapper script.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write a CLAUDE.md so Claude knows this is a study session directory
    # and doesn't waste time exploring for project context.
    claude_md = session_dir / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            f"# Study Session: {topic}\n\n"
            "This is a studyctl study session directory. "
            "Do not search for code or project files here.\n\n"
            "Use `studyctl topic` to log topics and `studyctl park` to park questions.\n"
        )

    # Pre-trust the session directory for Claude Code so the workspace
    # trust prompt doesn't block automated/ttyd sessions.
    # Trust is stored in ~/.claude/settings.json under projects[path].hasTrustDialogAccepted.
    # We trust the sessions parent dir so all future sessions inherit trust.
    _ensure_claude_trust(session_dir.parent)

    # Create a studyctl wrapper in the session directory that uses the
    # correct Python (the one running this process). Without this, the
    # Homebrew-installed studyctl (old version) shadows the dev version
    # and `studyctl topic` fails with "unknown command".
    wrapper = session_dir / "studyctl"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} -m studyctl.cli "$@"\n')
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

    return (
        f"{path_prefix}"
        f"{agent_cmd}; "
        f'{python} -c "'
        f"from studyctl.session.cleanup import cleanup_on_exit; "
        f"cleanup_on_exit()"
        f'"'
    )


def create_tmux_environment(
    *,
    session_name: str,
    session_dir: Path,
    wrapped_agent_cmd: str,
    session_state_dir: Path,
) -> dict:
    """Create tmux session with agent and sidebar panes.

    Returns dict with tmux_main_pane and tmux_sidebar_pane IDs.
    """
    import contextlib

    from studyctl.tmux import (
        create_session,
        is_in_tmux,
        load_config,
        select_pane,
        set_environment,
        set_option,
        split_pane,
        switch_client,
    )

    python = sys.executable
    sidebar_cmd = f"{python} -m studyctl.tui.sidebar"

    # Create session in the session directory -- agent conversation history
    # (.claude/, .kiro/, etc.) is preserved here across sessions.
    main_pane = create_session(
        session_name,
        command=wrapped_agent_cmd,
        cwd=str(session_dir),
    )

    # Set PATH for all panes in this session so the studyctl wrapper
    # in the session dir is found first (before any globally installed
    # older version). Uses tmux set-environment so ALL panes inherit it.
    current_path = os.environ.get("PATH", "")
    set_environment(session_name, "PATH", f"{session_dir}:{current_path}")

    # Ensure panes are destroyed when their commands exit. Without this,
    # user/plugin tmux configs may keep dead panes alive (remain-on-exit on),
    # preventing the session from auto-destroying after Q.
    set_option(session_name, "remain-on-exit", "off")
    # When the session is destroyed, detach the client (return to original
    # shell) rather than switching to another tmux session. Critical for
    # non-technical users who don't want to be stranded in tmux.
    set_option(session_name, "detach-on-destroy", "on")

    # Load user's studyctl tmux overlay if they've explicitly created one.
    user_conf = session_state_dir / "tmux-studyctl.conf"
    if user_conf.exists():
        with contextlib.suppress(Exception):
            load_config(user_conf)

    # --- Switch/attach FIRST so tmux resizes to the actual terminal ---
    # This ensures the split percentage is calculated against the real
    # terminal width, not the detached default (80x24).
    already_in_tmux = is_in_tmux()
    if already_in_tmux:
        switch_client(session_name)

    # Split for sidebar (right pane, 25% width)
    sidebar_pane = split_pane(
        main_pane,
        direction="right",
        size=25,
        percentage=True,
        command=sidebar_cmd,
    )

    # Focus main pane (agent)
    select_pane(main_pane)

    return {
        "tmux_main_pane": main_pane,
        "tmux_sidebar_pane": sidebar_pane,
        "already_in_tmux": already_in_tmux,
    }


def attach_if_needed(session_name: str, already_in_tmux: bool) -> None:
    """Attach to tmux session if not already inside tmux.

    If already in tmux, switch_client was called during create_tmux_environment.
    If not, this replaces the current process via os.execvp.
    """
    if not already_in_tmux:
        from studyctl.tmux import attach

        # Replaces this process via os.execvp -- no code runs after this
        attach(session_name)


def start_web_background(session_name: str, *, lan: bool = False) -> None:
    """Start the web dashboard as a background process and open browser."""
    from studyctl.cli._shared import console

    port = _get_web_port()

    studyctl_bin = shutil.which("studyctl")
    cmd = (
        [studyctl_bin, "web", "--port", str(port)]
        if studyctl_bin
        else [sys.executable, "-m", "studyctl.cli", "web", "--port", str(port)]
    )
    if lan:
        cmd.append("--lan")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        from studyctl.session_state import write_session_state

        write_session_state({"web_pid": proc.pid})
        _open_browser(f"http://127.0.0.1:{port}/session")
    except Exception:
        console.print("[yellow]Could not start web dashboard.[/yellow]")


def _get_web_port() -> int:
    """Read web port from config, default 8567."""
    try:
        from studyctl.settings import load_settings

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
            from studyctl.settings import load_settings

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


def _get_ttyd_port() -> int:
    """Read ttyd port from config, default 7681."""
    try:
        from studyctl.settings import load_settings

        return getattr(load_settings(), "ttyd_port", 7681)
    except Exception:
        return 7681


def start_ttyd_background(session_name: str, *, lan: bool = False) -> None:
    """Start ttyd to expose the tmux session over HTTP.

    Attaches a writable ttyd client to the study tmux session.
    Skips silently if ttyd is not installed.
    """
    from studyctl.session_state import write_session_state

    ttyd_bin = shutil.which("ttyd")
    if not ttyd_bin:
        return

    host = "0.0.0.0" if lan else "127.0.0.1"
    port = _get_ttyd_port()

    cmd = [
        ttyd_bin,
        "-W",  # writable (user interacts with the agent)
        "-i",
        host,
        "-p",
        str(port),
        "tmux",
        "new-session",
        "-t",
        session_name,  # grouped session: shares windows, independent sizing
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        write_session_state({"ttyd_pid": proc.pid, "ttyd_port": port})
    except Exception:
        pass  # ttyd failed to start — non-fatal
