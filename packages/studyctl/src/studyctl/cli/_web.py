"""Web server command — study PWA."""

from __future__ import annotations

import contextlib

import click

from studyctl.cli._shared import console


@click.command()
@click.option("--port", "-p", default=8567, help="Port for web server")
@click.option("--lan", is_flag=True, help="Expose to LAN (default: localhost only)")
@click.option("--password", default="", help="Password for HTTP Basic Auth (LAN protection)")
@click.option("--ttyd-port", default=0, help="Port where ttyd is running (0 = read from config)")
def web(port: int, lan: bool, password: str, ttyd_port: int) -> None:
    """Launch the study PWA in your browser.

    Serves flashcard and quiz review as a web app accessible from any
    device on the network. Installable as a PWA (add to home screen).
    Includes OpenDyslexic font toggle for accessibility.

    Requires: uv pip install 'studyctl[web]'
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]The web server requires FastAPI.[/red]\nInstall: uv pip install 'studyctl[web]'"
        )
        return

    import secrets

    from studyctl.settings import load_raw_config

    study_dirs: list[str] = []
    with contextlib.suppress(Exception):
        study_dirs = load_raw_config().get("review", {}).get("directories", [])

    # Resolve credentials: always read username from config; password from CLI > config > auto
    username = "study"
    try:
        from studyctl.settings import load_settings

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
        from studyctl.settings import load_settings as _ls

        try:
            ttyd_port = _ls().ttyd_port
        except Exception:
            ttyd_port = 7681

    from studyctl.web.app import create_app

    host = "0.0.0.0" if lan else "127.0.0.1"
    app = create_app(
        study_dirs=study_dirs, ttyd_port=ttyd_port, username=username, password=password
    )
    console.print(f"[bold]Study PWA at http://{host}:{port}[/bold]")
    if not lan:
        console.print("[dim]Use --lan to expose to network[/dim]")
    uvicorn.run(app, host=host, port=port, workers=1, log_level="warning")
