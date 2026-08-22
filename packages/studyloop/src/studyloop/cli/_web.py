"""Web server command — study PWA."""

from __future__ import annotations

import contextlib
import socket
from typing import TYPE_CHECKING

import click

from studyloop.cli._shared import console
from studyloop.web.runtime_feedback import (
    LanCredentialFeedback,
    build_web_access_info,
    format_lan_credential_lines,
    format_web_access_lines,
)

if TYPE_CHECKING:
    from types import FrameType as _FrameType


def _candidate_lan_hosts() -> tuple[str, ...]:
    """Best-effort LAN address discovery for runtime feedback."""
    hosts: list[str] = []
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        hosts.append(sock.getsockname()[0])
    with contextlib.suppress(OSError):
        hosts.append(socket.gethostbyname(socket.gethostname()))
    return tuple(hosts)


@click.command()
@click.option("--port", "-p", default=8567, help="Port for web server")
@click.option("--lan", is_flag=True, help="Expose to LAN (default: localhost only)")
@click.option("--password", default="", help="Password for HTTP Basic Auth (LAN protection)")
@click.option("--ttyd-port", default=0, help="Port where ttyd is running (0 = read from config)")
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Developer experiment mode: swap xterm.js for an alternative renderer.",
)
@click.option(
    "--dev-renderer",
    type=click.Choice(["ghostty"], case_sensitive=False),
    default=None,
    help="Select the dev-mode renderer (default: ghostty). Implies --dev.",
)
def web(
    port: int, lan: bool, password: str, ttyd_port: int, dev: bool, dev_renderer: str | None,
) -> None:
    """Launch the study PWA in your browser.

    Serves flashcard and quiz review as a web app accessible from any
    device on the network. Installable as a PWA (add to home screen).
    Includes OpenDyslexic font toggle for accessibility.

    Requires: uv pip install 'studyloop[web]'
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]The web server requires FastAPI.[/red]\nInstall: uv pip install 'studyloop[web]'"
        )
        return

    import secrets

    from studyloop.settings import resolve_study_dirs

    study_dirs: list[str] = []
    with contextlib.suppress(Exception):
        # Falls back to content.base_path when review.directories is unset, so
        # the review panels discover decks the generator just wrote.
        study_dirs = resolve_study_dirs()

    # Resolve credentials: always read username from config; password from CLI > config > auto
    username = "study"
    password_generated = False
    try:
        from studyloop.settings import load_settings

        _settings = load_settings()
        username = _settings.lan_username or "study"
        if not password:
            password = _settings.lan_password
    except Exception:
        pass

    if lan and not password:
        password = secrets.token_urlsafe(16)
        password_generated = True

    if lan and password:
        for line in format_lan_credential_lines(
            LanCredentialFeedback(
                username=username,
                password=password,
                password_generated=password_generated,
            )
        ):
            console.print(line)

    if not ttyd_port:
        from studyloop.settings import load_settings as _ls

        try:
            ttyd_port = _ls().ttyd_port
        except Exception:
            ttyd_port = 7681

    from studyloop.web.app import create_app

    # --dev-renderer implies --dev
    if dev_renderer is not None:
        dev = True

    # Bare `--dev` must go through the dev_engines REGISTRY, not the deprecated
    # `dev_renderer` inline path. Defaulting dev_renderer to "ghostty" here (as
    # this did) forced every plain `--dev` down the legacy branch, which injects
    # materially different markup: content="ghostty-web" plus the
    # *.umd.js/bootstrap pair, instead of content="ghostty" plus
    # ghostty-web-0.4.0.js + ghostty-adapter-0.4.0.js. app.py's own comment
    # states the intent — "Every other dev_mode=True call — including the new
    # default — goes through the dev_engines registry below" — but this default
    # defeated it, so the registry path was unreachable from the CLI and the
    # adapter, window.GhosttyWeb and __studyloopGhostty were never loaded.
    # dev_renderer now stays None unless the user explicitly asked for it.
    dev_engine = "ghostty" if dev and dev_renderer is None else None

    if dev:
        # One engine since wterm was removed, so no branch is needed. Kept as a
        # named variable so adding a second engine later reintroduces the choice
        # in one obvious place.
        renderer_label = "ghostty-web (canvas renderer)"
        console.print(
            f"[yellow]--dev mode:[/yellow] xterm.js swapped for {renderer_label}"
        )

    host = "0.0.0.0" if lan else "127.0.0.1"
    app = create_app(
        study_dirs=study_dirs,
        ttyd_port=ttyd_port,
        username=username,
        password=password,
        dev_mode=dev,
        dev_renderer=dev_renderer,
        dev_engine=dev_engine,
    )
    access_info = build_web_access_info(
        bind_host=host,
        port=port,
        lan_enabled=lan,
        lan_hosts=_candidate_lan_hosts() if lan else (),
    )
    for line in format_web_access_lines(access_info):
        console.print(line)
    # loop="asyncio" is required for PTYTransport: uvloop reserves SIGCHLD
    # for its own subprocess tracking and refuses to install a user handler,
    # which our PTY child-exit detection depends on. The standard asyncio
    # loop allows add_signal_handler(SIGCHLD, ...) to coexist with subprocess
    # watching. See plan Blocker B6 + Amendment #7.
    #
    # Ctrl-C hardening: uvicorn's graceful shutdown can hang when a PTY/ACP
    # subprocess is wedged (e.g. Kiro MCP bootstrap stuck, child not reaping).
    # uvicorn's own handler escalates to ``force_exit=True`` only on a *second*
    # SIGINT — and even ``force_exit`` waits on hung tasks. We subclass
    # ``Server`` so the first SIGINT also kicks off a watchdog thread that
    # ``os._exit()``s after a grace window. Result: one Ctrl-C is enough,
    # operator never has to hunt PIDs.
    import os as _os
    import threading as _threading
    import time as _time

    class _StudyLoopServer(uvicorn.Server):
        _watchdog_started: bool = False

        def handle_exit(self, sig: int, frame: _FrameType | None) -> None:
            if not self._watchdog_started:
                self._watchdog_started = True
                console.print("\n[yellow]Shutting down… (Ctrl-C again to force)[/yellow]")
                _threading.Thread(
                    target=_force_exit_watchdog,
                    args=(5.0,),
                    daemon=True,
                ).start()
            super().handle_exit(sig, frame)

    def _force_exit_watchdog(grace: float) -> None:
        _time.sleep(grace)
        console.print(f"\n[red]Force-exiting after {grace:.0f}s (uvicorn shutdown hung).[/red]")
        _os._exit(130)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        workers=1,
        log_level="warning",
        loop="asyncio",
    )
    _StudyLoopServer(config).run()
