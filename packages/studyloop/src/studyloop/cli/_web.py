"""Web server command — study PWA."""

from __future__ import annotations

import contextlib

import click

from studyloop.cli._shared import console


@click.command()
@click.option("--port", "-p", default=8567, help="Port for web server")
@click.option("--lan", is_flag=True, help="Expose to LAN (default: localhost only)")
@click.option("--password", default="", help="Password for HTTP Basic Auth (LAN protection)")
@click.option("--ttyd-port", default=0, help="Port where ttyd is running (0 = read from config)")
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Developer experiment mode: swap xterm.js for wterm (DOM renderer).",
)
def web(port: int, lan: bool, password: str, ttyd_port: int, dev: bool) -> None:
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
        console.print(
            f"[bold yellow]LAN credentials:[/bold yellow] "
            f"[green]{username}[/green] / [green]{password}[/green]"
        )
        console.print(
            "[dim]Set lan_username and lan_password in config.yaml "
            "to avoid auto-generated passwords.[/dim]"
        )

    if not ttyd_port:
        from studyloop.settings import load_settings as _ls

        try:
            ttyd_port = _ls().ttyd_port
        except Exception:
            ttyd_port = 7681

    from studyloop.web.app import create_app

    if dev:
        console.print(
            "[yellow]--dev mode:[/yellow] xterm.js swapped for wterm (experimental DOM renderer)"
        )

    host = "0.0.0.0" if lan else "127.0.0.1"
    app = create_app(
        study_dirs=study_dirs,
        ttyd_port=ttyd_port,
        username=username,
        password=password,
        dev_mode=dev,
    )
    console.print(f"[bold]Study PWA at http://{host}:{port}[/bold]")
    if not lan:
        console.print("[dim]Use --lan to expose to network[/dim]")
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
    from types import FrameType as _FrameType

    class _StudyLoopServer(uvicorn.Server):
        _watchdog_started: bool = False

        def handle_exit(self, sig: int, frame: _FrameType | None) -> None:
            if not self._watchdog_started:
                self._watchdog_started = True
                console.print(
                    "\n[yellow]Shutting down… (Ctrl-C again to force)[/yellow]"
                )
                _threading.Thread(
                    target=_force_exit_watchdog,
                    args=(5.0,),
                    daemon=True,
                ).start()
            super().handle_exit(sig, frame)

    def _force_exit_watchdog(grace: float) -> None:
        _time.sleep(grace)
        console.print(
            "\n[red]Force-exiting after %.0fs (uvicorn shutdown hung).[/red]" % grace
        )
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
