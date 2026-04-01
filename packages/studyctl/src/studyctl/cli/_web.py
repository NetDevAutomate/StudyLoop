"""Web server command — study PWA."""

from __future__ import annotations

from pathlib import Path

import click

from studyctl.cli._shared import console


@click.command()
@click.option("--port", "-p", default=8567, help="Port for web server")
@click.option("--lan", is_flag=True, help="Expose to LAN (default: localhost only)")
def web(port: int, lan: bool) -> None:
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

    import yaml

    config_path = Path.home() / ".config" / "studyctl" / "config.yaml"
    study_dirs: list[str] = []
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            study_dirs = data.get("review", {}).get("directories", [])
        except Exception:
            pass

    from studyctl.web.app import create_app

    host = "0.0.0.0" if lan else "127.0.0.1"
    app = create_app(study_dirs=study_dirs)
    console.print(f"[bold]Study PWA at http://{host}:{port}[/bold]")
    if not lan:
        console.print("[dim]Use --lan to expose to network[/dim]")
    uvicorn.run(app, host=host, port=port, workers=1, log_level="warning")
