"""HerdrBackend — herdr workspace-per-study implementation of Multiplexer.

Implements the Multiplexer Protocol using herdr's workspace model:
- Each study session = one herdr workspace (labelled ``study-<topic>``)
- Panes are created via ``pane split`` within the workspace
- IDs are OPAQUE strings — never constructed or parsed, always read from JSON
- The default herdr session is reused (no named-session lifecycle management)

Requires herdr >= 0.7.4. Falls back to tmux if herdr is unavailable
(selection handled by ``get_backend()`` in multiplexer.py).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time

from studyloop.multiplexer import MultiplexerError

logger = logging.getLogger(__name__)

# Special key prefixes that should use send-keys instead of send-text
_SPECIAL_KEYS = frozenset(
    {
        "C-",
        "M-",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "F7",
        "F8",
        "F9",
        "F10",
        "F11",
        "F12",
        "Up",
        "Down",
        "Left",
        "Right",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Tab",
        "Escape",
        "Enter",
        "Space",
        "BSpace",
        "DC",
        "IC",
    }
)

# Timeout for herdr subprocess calls (seconds)
_CMD_TIMEOUT = 30
_PANE_READY_TIMEOUT = 5.0
_PANE_READY_POLL = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_session_start_time(session_name: str) -> float | None:
    """Get session start time from StudyLoop's session database.

    Returns epoch timestamp or None if not found.
    Used for zombie detection (herdr doesn't expose creation timestamps).
    """
    try:
        from studyloop.session_state import read_session_state

        state = read_session_state()
        started_at = state.get("started_at")
        if started_at is not None:
            return float(started_at)
    except Exception:
        pass
    return None


def _is_special_key(keys: str) -> bool:
    """Check if a key string is a special key (needs send-keys, not send-text)."""
    return any(keys.startswith(prefix) or keys == prefix.rstrip("-") for prefix in _SPECIAL_KEYS)


# ---------------------------------------------------------------------------
# HerdrBackend
# ---------------------------------------------------------------------------


class HerdrBackend:
    """herdr workspace-per-study implementation of Multiplexer.

    Uses the default herdr session with workspace isolation (D2).
    Each study session creates a workspace; cleanup closes the workspace.
    StudyLoop does not own the Herdr server lifecycle. The server must already
    be running before this backend sends workspace commands.
    """

    # Cache: label → workspace_id mapping (invalidated on kill/create)
    _workspace_cache: dict[str, str]

    def __init__(self) -> None:
        # Reset cache per instance to avoid stale state in tests
        self._workspace_cache = {}

    # ------------------------------------------------------------------
    # Internal: herdr CLI execution
    # ------------------------------------------------------------------

    def _herdr(
        self,
        *args: str,
        json_output: bool = True,
        check: bool = True,
        timeout: float = _CMD_TIMEOUT,
    ) -> dict | list | str:
        """Run a herdr CLI command and return parsed output.

        Args:
            *args: Command arguments (e.g. "workspace", "create", "--label", "x")
            json_output: If True, parse stdout as JSON. If False, return raw stdout.
            check: If True, raise on non-zero exit code.
            timeout: Subprocess timeout in seconds.

        Returns:
            Parsed JSON (dict or list) when json_output=True, raw string otherwise.

        Raises:
            MultiplexerError: On any failure (timeout, bad exit, invalid JSON,
                binary not found).
        """
        cmd = ["herdr", *args]
        logger.debug("herdr: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            raise MultiplexerError(
                f"herdr command failed (exit {e.returncode}): {' '.join(cmd)}\nstderr: {stderr}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise MultiplexerError(
                f"herdr command timed out after {timeout}s: {' '.join(cmd)}"
            ) from e
        except FileNotFoundError as e:
            raise MultiplexerError(
                f"herdr binary not found. Is herdr installed and on PATH?\nCommand: {' '.join(cmd)}"
            ) from e

        if not json_output:
            return result.stdout

        # Parse JSON
        stdout = result.stdout.strip()
        if not stdout:
            return {}

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise MultiplexerError(
                f"herdr returned invalid JSON response.\n"
                f"Command: {' '.join(cmd)}\n"
                f"stdout: {stdout[:200]}\n"
                f"Error: {e}"
            ) from e

        # herdr wraps all responses in {"id": "...", "result": {...}}.
        # Unwrap the envelope so callers get the payload directly.
        if isinstance(parsed, dict) and "result" in parsed and "id" in parsed:
            return parsed["result"]
        return parsed

    def _herdr_nofail(
        self, *args: str, json_output: bool = True, timeout: float = _CMD_TIMEOUT
    ) -> dict | list | str | None:
        """Run herdr, return None on any failure (no raise)."""
        try:
            return self._herdr(*args, json_output=json_output, timeout=timeout)
        except (MultiplexerError, Exception):
            return None

    def _wait_for_pane_ready(self, pane_id: str, *, timeout: float = _PANE_READY_TIMEOUT) -> None:
        """Wait until a new interactive pane has produced its first render.

        Herdr can accept text immediately after ``workspace create`` or
        ``pane split``, before the shell's line editor is ready. In that
        window the text is buffered but the Enter key is lost, leaving the
        launch command visibly stranded at the prompt.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rendered = self._herdr_nofail(
                "pane",
                "read",
                pane_id,
                "--source",
                "visible",
                "--lines",
                "1",
                "--format",
                "text",
                json_output=False,
                timeout=1,
            )
            if isinstance(rendered, str) and rendered.strip():
                return
            time.sleep(_PANE_READY_POLL)
        raise MultiplexerError(
            f"herdr pane {pane_id} did not render before command launch (timeout {timeout:.1f}s)"
        )

    def _find_workspace_id(self, label: str) -> str | None:
        """Find workspace_id by label. Returns None if not found."""
        if label in self._workspace_cache:
            return self._workspace_cache[label]

        try:
            result = self._herdr("workspace", "list")
        except MultiplexerError:
            return None

        # Extract workspace list from response (may be a list or dict with 'workspaces')
        workspaces: list = []
        if isinstance(result, list):
            workspaces = result
        elif isinstance(result, dict):
            workspaces = result.get("workspaces", [])

        for ws in workspaces:
            if isinstance(ws, dict) and ws.get("label") == label:
                ws_id = ws["workspace_id"]
                self._workspace_cache[label] = ws_id
                return ws_id
        return None

    def _get_workspace_panes(self, label: str) -> list[str]:
        """Get pane IDs for a workspace by label."""
        try:
            result = self._herdr("workspace", "list")
        except MultiplexerError:
            return []

        # Extract workspace list
        workspaces: list = []
        if isinstance(result, list):
            workspaces = result
        elif isinstance(result, dict):
            workspaces = result.get("workspaces", [])

        for ws in workspaces:
            if isinstance(ws, dict) and ws.get("label") == label:
                panes = ws.get("panes", [])
                if isinstance(panes, list):
                    return panes
        return []

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if herdr binary is on PATH and responds."""
        if not shutil.which("herdr"):
            return False
        try:
            subprocess.run(
                ["herdr", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def is_inside_session(self) -> bool:
        """Check if currently running inside a herdr session (HERDR_ENV=1)."""
        return os.environ.get("HERDR_ENV") == "1"

    def is_server_running(self) -> bool:
        """Check if a herdr server is responding."""
        try:
            result = self._herdr("session", "list", "--json", check=False)
            # After unwrapping, this is either a list or dict with session data
            return result is not None and isinstance(result, (list, dict))
        except MultiplexerError:
            return False

    # ------------------------------------------------------------------
    # Session Lifecycle
    # ------------------------------------------------------------------

    def session_exists(self, name: str) -> bool:
        """Check if a workspace with this label exists (always fresh, no cache)."""
        # Bypass the cache — another process (e.g. --end subprocess) may have
        # closed the workspace. Always query herdr for authoritative state.
        try:
            result = self._herdr("workspace", "list")
        except MultiplexerError:
            return False

        workspaces: list = []
        if isinstance(result, list):
            workspaces = result
        elif isinstance(result, dict):
            workspaces = result.get("workspaces", [])

        for ws in workspaces:
            if isinstance(ws, dict) and ws.get("label") == name:
                # Update cache as a side effect
                ws_id = ws.get("workspace_id")
                if ws_id:
                    self._workspace_cache[name] = ws_id
                return True

        # Not found — remove from cache if present
        self._workspace_cache.pop(name, None)
        return False

    def create_session(
        self,
        name: str,
        *,
        command: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Create a herdr workspace labelled ``name``.

        Returns the workspace_id (opaque string). The initial pane is
        accessible via the JSON response's ``pane_id`` field.

        Args:
            name: Workspace label (e.g. "study-decorators").
            command: Optional command to run in the initial pane.
            cwd: Working directory for the workspace.
            env: Environment variables to set at creation time.

        Returns:
            workspace_id string.

        Raises:
            MultiplexerError: If creation fails or response is malformed.
        """
        args = ["workspace", "create", "--label", name, "--no-focus"]
        if cwd:
            args.extend(["--cwd", cwd])
        if env:
            for key, value in env.items():
                args.extend(["--env", f"{key}={value}"])

        result = self._herdr(*args)

        if not isinstance(result, dict):
            raise MultiplexerError(
                f"herdr workspace create returned unexpected type: {type(result).__name__}"
            )

        # Response structure: {"root_pane": {...}, "workspace": {...}, ...}
        workspace_data = result.get("workspace", result)
        root_pane_data = result.get("root_pane", result)

        workspace_id = workspace_data.get("workspace_id") or result.get("workspace_id")
        if not workspace_id:
            raise MultiplexerError(
                f"herdr workspace create response missing workspace_id key. Response: {result}"
            )

        pane_id = root_pane_data.get("pane_id") or result.get("pane_id")

        # Cache the mapping
        self._workspace_cache[name] = workspace_id

        # If a command was requested, run it in the initial pane
        if command and pane_id:
            self._wait_for_pane_ready(pane_id)
            self._herdr("pane", "run", pane_id, command, json_output=False)

        # Protocol contract: return the initial pane_id (like tmux does).
        # Fall back to workspace_id if pane_id couldn't be extracted.
        return pane_id or workspace_id

    def kill_session(self, name: str) -> bool:
        """Close the workspace with this label.

        Returns True if found and closed, False if not found.
        """
        workspace_id = self._find_workspace_id(name)
        if not workspace_id:
            return False

        try:
            self._herdr("workspace", "close", workspace_id)
        except MultiplexerError:
            return False

        # Invalidate cache
        self._workspace_cache.pop(name, None)
        return True

    def list_study_sessions(self) -> list[str]:
        """List workspace labels matching the 'study-' prefix."""
        try:
            result = self._herdr("workspace", "list")
        except MultiplexerError:
            return []

        # Extract workspace list
        workspaces: list = []
        if isinstance(result, list):
            workspaces = result
        elif isinstance(result, dict):
            workspaces = result.get("workspaces", [])

        return [
            ws["label"]
            for ws in workspaces
            if isinstance(ws, dict)
            and isinstance(ws.get("label"), str)
            and ws["label"].startswith("study-")
        ]

    def kill_all_study_sessions(self, current_session: str | None = None) -> None:
        """Close all study-* workspaces.

        Kills other sessions first, then current_session last — matching
        the tmux implementation. If we're running inside the current session,
        killing it last ensures cleanup completes before SIGHUP.
        """
        try:
            result = self._herdr("workspace", "list")
        except MultiplexerError:
            return

        # Extract workspace list
        workspaces: list = []
        if isinstance(result, list):
            workspaces = result
        elif isinstance(result, dict):
            workspaces = result.get("workspaces", [])

        current_ws_id: str | None = None
        for ws in workspaces:
            if not isinstance(ws, dict):
                continue
            label = ws.get("label", "")
            if not label.startswith("study-"):
                continue
            ws_id = ws.get("workspace_id")
            if not ws_id:
                continue
            # Kill current session last
            if label == current_session:
                current_ws_id = ws_id
                continue
            try:
                self._herdr("workspace", "close", ws_id)
            except MultiplexerError:
                logger.warning("Failed to close workspace %s (%s)", ws_id, label)

        # Now kill the current session (if any)
        if current_ws_id:
            try:
                self._herdr("workspace", "close", current_ws_id)
            except MultiplexerError:
                logger.warning(
                    "Failed to close current workspace %s (%s)",
                    current_ws_id,
                    current_session,
                )

        # Invalidate cache
        self._workspace_cache.clear()

    # ------------------------------------------------------------------
    # Pane Management
    # ------------------------------------------------------------------

    def split_pane(
        self,
        target: str,
        *,
        direction: str = "right",
        size: int = 30,
        percentage: bool = False,
        command: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Split a pane, return the new pane_id.

        Args:
            target: Pane ID to split.
            direction: "right" (horizontal) or "down" (vertical).
            size: Size of new pane. If percentage=True, interpreted as %;
                  otherwise as absolute cell count (converted to ratio).
            percentage: Whether size is a percentage (0-100).
            command: Optional command to run in the new pane.
            env: Environment variables for the new pane.

        Returns:
            New pane_id (opaque string).
        """
        # Convert size to ratio (0.0-1.0) for herdr.
        # Whether percentage=True or not, herdr always uses ratios.
        ratio = size / 100.0

        args = [
            "pane",
            "split",
            target,
            "--direction",
            direction,
            "--ratio",
            str(ratio),
            "--no-focus",
        ]
        if env:
            for key, value in env.items():
                args.extend(["--env", f"{key}={value}"])

        result = self._herdr(*args)

        if not isinstance(result, dict):
            raise MultiplexerError(
                f"herdr pane split returned unexpected type: {type(result).__name__}"
            )

        # Response structure: {"pane": {"pane_id": "...", ...}, "type": "pane_info"}
        pane_data = result.get("pane", result)
        pane_id = pane_data.get("pane_id") or result.get("pane_id")
        if not pane_id:
            raise MultiplexerError(f"herdr pane split response missing pane_id. Response: {result}")

        # Run command in the new pane if requested
        if command:
            self._wait_for_pane_ready(pane_id)
            self._herdr("pane", "run", pane_id, command, json_output=False)

        return pane_id

    def send_keys(self, target: str, keys: str, *, enter: bool = True) -> None:
        """Send keys to a pane.

        Behaviour:
        - enter=True + regular text → ``herdr pane run`` (sends text + Enter)
        - enter=False + regular text → ``herdr pane send-text``
        - Special keys (C-c, F1, etc.) → ``herdr pane send-keys``
        """
        if _is_special_key(keys):
            # Special key — use send-keys
            self._herdr("pane", "send-keys", target, keys, json_output=False)
        elif enter:
            # Text with Enter — use pane run (sends text + executes)
            self._herdr("pane", "run", target, keys, json_output=False)
        else:
            # Text without Enter — use send-text
            self._herdr("pane", "send-text", target, keys, json_output=False)

    def select_pane(self, target: str) -> None:
        """Focus a pane (within the current workspace).

        herdr pane focus is directional only (--direction left|right|up|down),
        not by pane ID. Since split_pane uses --no-focus, the original pane
        remains focused after a split. select_pane is effectively a no-op.
        """
        # herdr has no "focus pane by ID" command. The split_pane method
        # uses --no-focus so the original (main) pane stays focused.
        # This is safe as a no-op because the orchestrator only calls
        # select_pane(main_pane) after splitting the sidebar.
        logger.debug("select_pane(%s): no-op for herdr (splits use --no-focus)", target)

    # ------------------------------------------------------------------
    # Session Configuration
    # ------------------------------------------------------------------

    def configure_session_defaults(self, session: str) -> None:
        """Apply herdr-specific session defaults.

        herdr has no runtime session options (unlike tmux's set_option).
        Instead, we set workspace metadata via report-metadata. This is
        a best-effort operation — failure is logged but not raised.

        Per design.md D8: herdr uses workspace labels + pane report-metadata.
        """
        # herdr's workspace was already created with the label (in create_session).
        # configure_session_defaults is mostly a no-op for herdr.
        # We could report agent metadata here if the pane_id is known,
        # but the Protocol doesn't pass it. Accept as no-op.
        logger.debug(
            "configure_session_defaults(%s): no-op for herdr (workspace labels "
            "set at creation time, pane metadata set via report-agent)",
            session,
        )

    # ------------------------------------------------------------------
    # Client / Attach
    # ------------------------------------------------------------------

    def switch_client(self, name: str) -> None:
        """Focus the workspace with this label (already inside herdr).

        Equivalent to tmux's switch-client — makes the named session visible.
        """
        workspace_id = self._find_workspace_id(name)
        if not workspace_id:
            raise MultiplexerError(f"Cannot switch to '{name}': workspace not found")
        self._herdr("workspace", "focus", workspace_id, json_output=False)

    def attach(self, name: str) -> None:
        """Replace the current process with herdr TUI (os.execvp).

        This hands control to herdr's terminal UI. The workspace should
        already be created and focused.
        """
        # For the default session model, just exec into herdr
        # The workspace is already created; herdr will show it
        os.execvp("herdr", ["herdr"])

    # ------------------------------------------------------------------
    # Process Introspection
    # ------------------------------------------------------------------

    def pane_has_child_process(self, pane_id: str) -> bool:
        """Check if a pane has foreground child processes.

        Uses herdr's structured process-info (single call, no PID parsing).
        Response structure (after envelope unwrap):
          {"process_info": {"foreground_processes": [...], ...}}
        """
        try:
            result = self._herdr("pane", "process-info", "--pane", pane_id)
        except MultiplexerError:
            return False

        if not isinstance(result, dict):
            return False

        # Navigate into the process_info wrapper
        process_info = result.get("process_info", result)
        foreground = process_info.get("foreground_processes", [])
        return isinstance(foreground, list) and len(foreground) > 0

    def is_zombie_session(self, name: str, min_age_seconds: float = 60.0) -> bool:
        """Detect zombie study sessions.

        A session is zombie if:
        1. Its workspace exists
        2. No panes have foreground child processes
        3. It's older than min_age_seconds (from StudyLoop DB, since herdr
           doesn't expose creation timestamps — Gap 5 workaround)

        Returns False if the session isn't found or determination fails.
        """
        # Find workspace and its panes
        panes = self._get_workspace_panes(name)
        if not panes:
            # Workspace doesn't exist or has no panes
            # Try finding by workspace_id directly
            ws_id = self._find_workspace_id(name)
            if not ws_id:
                return False
            # Re-fetch panes from workspace list
            panes = self._get_workspace_panes(name)
            if not panes:
                return False

        # Check if ANY pane has children — if so, not zombie
        for pane_id in panes:
            if self.pane_has_child_process(pane_id):
                return False

        # No children in any pane — check age
        start_time = _get_session_start_time(name)
        if start_time is None:
            # Can't determine age — be conservative, not zombie
            return False

        age = time.time() - start_time
        return age >= min_age_seconds

    # ------------------------------------------------------------------
    # Test Harness Support
    # ------------------------------------------------------------------

    def capture_pane(self, pane_id: str, lines: int = 50) -> str:
        """Read recent pane content.

        Uses ``herdr pane read`` with --source recent-unwrapped to get
        the original line content without column-width re-wrapping.
        This matches what the user typed/saw rather than the visual
        layout of a (potentially narrow) pane.
        """
        try:
            result = self._herdr(
                "pane",
                "read",
                pane_id,
                "--source",
                "recent-unwrapped",
                "--lines",
                str(lines),
                json_output=False,
            )
            return result if isinstance(result, str) else ""
        except MultiplexerError:
            return ""

    def wait_for_content(self, pane_id: str, pattern: str, timeout_ms: int = 10000) -> str:
        """Wait for pattern to appear in pane output.

        Uses herdr's native ``wait output`` command with --regex — a single
        blocking call that replaces tmux's polling loop. This is one of
        herdr's genuine improvements over tmux.

        Args:
            pane_id: Target pane.
            pattern: Regex pattern to match.
            timeout_ms: Maximum wait time in milliseconds.

        Returns:
            The matched text.

        Raises:
            MultiplexerError: If timeout or other failure occurs.
        """
        try:
            result = self._herdr(
                "wait",
                "output",
                pane_id,
                "--match",
                pattern,
                "--regex",
                "--timeout",
                str(timeout_ms),
            )
        except MultiplexerError as e:
            raise MultiplexerError(
                f"Timed out or failed waiting for pattern {pattern!r} in pane {pane_id}: {e}"
            ) from e

        if isinstance(result, dict):
            # Extract matched text from response
            read_data = result.get("read", {})
            if isinstance(read_data, dict):
                return read_data.get("text", "")
            return str(read_data)
        return str(result) if result else ""
