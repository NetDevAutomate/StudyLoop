"""PTY and ACP transport factories for web session start."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class _PermissionResponder(Protocol):
    async def send_permission_response(self, request_id: str, outcome: dict[str, Any]) -> None: ...


class UnsupportedTransportError(ValueError):
    """Raised when ``STUDYLOOP_TRANSPORT`` names a transport that does not exist.

    Ttyd retirement stage 3 (R-05): a naive deletion of the ttyd arm left this
    function silently downgrading any unrecognised value to ``"pty"``, so
    ``STUDYLOOP_TRANSPORT=ttyd`` kept "working" — just as a different
    transport than the operator asked for. The fix is structural rejection,
    not a wider allow-list: the caller gets an error, never a substitution.
    """


def _resolve_transport(body_transport: str | None) -> str:
    """Decide between 'pty' and 'acp'. Env var wins for operator kill-switch.

    The ``STUDYLOOP_TRANSPORT`` env var only accepts ``pty`` — ACP is
    body-only, intentionally kept out of the operator kill-switch surface
    because the env var is the "force the safe path" lever, not a general
    transport selector. Any other non-empty value (including the retired
    ``ttyd``) raises :class:`UnsupportedTransportError` rather than silently
    resolving to ``pty``.
    """
    import os

    env_override = os.environ.get("STUDYLOOP_TRANSPORT", "").strip().lower()
    if env_override:
        if env_override != "pty":
            raise UnsupportedTransportError(env_override)
        return env_override
    if body_transport in {"pty", "acp"}:
        return body_transport
    return "pty"


def _build_pty_transport(config):  # type: ignore[no-untyped-def]
    """Return a zero-arg factory that constructs a ``PTYTransport`` for ``config``.

    Split out from ``_start_pty_session`` so tests can monkeypatch the
    whole factory without spawning a real PTY child. The production
    factory wraps the adapter's shell-string ``launch_cmd`` in
    ``/bin/sh -c``, since ``os.execvpe`` needs argv and our adapters
    return shell strings (with pipes, ``&&``, etc).
    """
    import shutil as _shutil
    from pathlib import Path

    from studyloop.agent_launcher import AGENTS
    from studyloop.session.transports.pty import PTYTransport

    adapter = AGENTS[config.agent]

    def _resolve_binary(_agent_name: str) -> str | None:
        # PTYTransport uses this to set the child's argv[0]. We pass argv
        # directly via build_launch_cmd, so the resolved binary is just
        # the shell — it does NOT need to match the agent binary.
        return _shutil.which("sh") or "/bin/sh"

    def _build_launch_cmd(_config) -> list[str]:  # type: ignore[no-untyped-def]
        # Test hatch: STUDYLOOP_TEST_AGENT_CMD lets CI / Playwright force a
        # known-good shell command (e.g. `/bin/sh -c 'echo ready; cat'`)
        # without needing the real agent binary installed. The hatch is
        # stripped from the child env by _build_child_env() so the child
        # cannot observe its own override key. Reads the import-time
        # snapshot (R-09c), not os.environ directly, so a dotenv loader
        # that runs later in the process cannot re-inject this key.
        from studyloop import test_hatch_env

        test_cmd = test_hatch_env("STUDYLOOP_TEST_AGENT_CMD")
        if test_cmd:
            shell_cmd = test_cmd.format(persona_file=_config.persona_file)
        else:
            claude_project_key = str(_config.cwd).replace("/", "-").lstrip("-")
            is_resuming = (Path.home() / ".claude" / "projects" / claude_project_key).exists()
            shell_cmd = adapter.launch_cmd(Path(_config.persona_file), is_resuming)
        return ["/bin/sh", "-c", shell_cmd]

    return lambda: PTYTransport(
        resolve_binary=_resolve_binary,
        build_launch_cmd=_build_launch_cmd,
    )


def _build_acp_transport(config):  # type: ignore[no-untyped-def]
    """Return a zero-arg factory that constructs an ``ACPTransport`` for ``config``.

    Mirrors ``_build_pty_transport`` but builds ACP argv instead of a
    shell command:

    - Kiro: ``["kiro-cli", "acp"]``

    The ``STUDYLOOP_TEST_ACP_CMD`` env var overrides the argv entirely,
    matching the shape of ``STUDYLOOP_TEST_AGENT_CMD`` on the PTY side.
    Splits the override with ``shlex.split`` so tests can script real
    argv (``"python3 /path/to/test_agent.py"``) without shell expansion.
    """
    import shlex
    import shutil as _shutil

    from studyloop.agent_launcher import AGENTS
    from studyloop.session.transports.acp import ACPTransport

    adapter = AGENTS[config.agent]

    def _resolve_binary(_agent_name: str) -> str | None:
        # ACPTransport uses this to fail start() with FileNotFoundError
        # before the handshake. We consult the adapter's declared binary
        # since PATH lookup semantics match ``shutil.which`` in the
        # route's pre-flight 503 guard.
        #
        # When STUDYLOOP_TEST_ACP_CMD is set, the argv is a full command
        # (e.g. "python3 /path/to/test_agent.py"); return the first token
        # resolved so ``asyncio.create_subprocess_exec`` gets a real
        # path — ``shutil.which`` on an absolute path returns it
        # unchanged when executable. Reads the import-time snapshot
        # (R-09c), not os.environ directly -- see _build_launch_cmd above.
        from studyloop import test_hatch_env

        test_cmd = test_hatch_env("STUDYLOOP_TEST_ACP_CMD")
        if test_cmd:
            first = shlex.split(test_cmd)[0] if test_cmd.strip() else ""
            return _shutil.which(first) or first or None
        return _shutil.which(adapter.binary)

    def _build_argv(_config) -> list[str]:  # type: ignore[no-untyped-def]
        from studyloop import test_hatch_env

        test_cmd = test_hatch_env("STUDYLOOP_TEST_ACP_CMD")
        if test_cmd:
            return shlex.split(test_cmd)
        if _config.agent == "kiro":
            return ["kiro-cli", "acp"]
        raise ValueError(f"ACP is not supported for agent {_config.agent!r}")

    return lambda: ACPTransport(
        resolve_binary=_resolve_binary,
        build_argv=_build_argv,
    )
