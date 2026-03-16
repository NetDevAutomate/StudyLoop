"""Web, TUI, and docs commands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from studyctl.cli._shared import console


def _find_docs_dir() -> Path:
    """Find the docs directory relative to the package."""
    candidate = Path(__file__).resolve().parent.parent
    for _ in range(6):
        if (candidate / "mkdocs.yml").exists():
            return candidate / "docs"
        candidate = candidate.parent
    for p in [
        Path.home() / "code" / "personal" / "tools" / "socratic-study-mentor" / "docs",
        Path.home() / ".agents" / "shared",
    ]:
        if p.exists():
            return p
    msg = "Could not find docs directory. Run from the repo or set STUDYCTL_DOCS_DIR."
    raise click.ClickException(msg)


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for TTS-friendly plain text."""
    import re

    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^!!! \w+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-|: ]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@click.command()
@click.option("--port", "-p", default=8567, help="Port for web server")
@click.option(
    "--host",
    "-H",
    default="0.0.0.0",
    help="Host to bind to (default: 0.0.0.0 for LAN access)",
)
def web(port: int, host: str) -> None:
    """Launch the study PWA in your browser.

    Serves flashcard and quiz review as a web app accessible from any
    device on the network. Installable as a PWA (add to home screen).
    Includes OpenDyslexic font toggle for accessibility.

    No extra dependencies required.
    """
    import yaml

    config_path = Path.home() / ".config" / "studyctl" / "config.yaml"
    study_dirs: list[str] = []
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            study_dirs = data.get("review", {}).get("directories", [])
        except Exception:
            pass

    from studyctl.web.server import serve

    serve(host=host, port=port, study_dirs=study_dirs)


@click.command()
def tui() -> None:
    """Launch the interactive terminal dashboard (requires textual).

    Install: uv pip install 'studyctl[tui]'

    Key bindings: f=flashcards, z=quiz, d=dashboard, q=quit, v=voice, o=OpenDyslexic

    For a web-based UI accessible from any device, use: studyctl web
    """
    try:
        from studyctl.tui.app import StudyApp
    except ImportError:
        console.print(
            "[red]The TUI requires 'textual'.[/red]\nInstall: uv pip install 'studyctl[tui]'"
        )
        return

    import yaml

    config_path = Path.home() / ".config" / "studyctl" / "config.yaml"
    study_dirs: list[str] = []
    theme: str = ""
    dyslexic: bool = False
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            study_dirs = data.get("review", {}).get("directories", [])
            tui_cfg = data.get("tui", {})
            theme = tui_cfg.get("theme", "")
            dyslexic = tui_cfg.get("dyslexic_friendly", False)
        except Exception:
            pass

    app = StudyApp(
        study_dirs=study_dirs,
        theme_name=theme,
        dyslexic_friendly=dyslexic,
    )
    app.run()


# --- Docs commands ---


@click.group(name="docs")
def docs_group() -> None:
    """Browse and read documentation."""


@docs_group.command(name="serve")
@click.option("--port", "-p", default=8000, help="Port for local server")
def docs_serve(port: int) -> None:
    """Serve documentation site locally and open in browser."""
    import subprocess

    repo_root = _find_docs_dir().parent
    console.print(f"[bold]Serving docs at http://localhost:{port}[/bold]")
    subprocess.run(["mkdocs", "serve", "-a", f"localhost:{port}"], cwd=str(repo_root), check=False)


@docs_group.command(name="open")
def docs_open() -> None:
    """Build and open documentation in browser."""
    import subprocess
    import webbrowser

    repo_root = _find_docs_dir().parent
    site_dir = repo_root / "site"
    console.print("Building docs...")
    subprocess.run(["mkdocs", "build"], cwd=str(repo_root), check=True, capture_output=True)
    index = site_dir / "index.html"
    if index.exists():
        webbrowser.open(f"file://{index}")
        console.print("[green]Opened docs in browser[/green]")
    else:
        console.print("[red]Build failed \u2014 site/index.html not found[/red]")


@docs_group.command(name="list")
def docs_list() -> None:
    """List available documentation pages."""
    docs_dir = _find_docs_dir()
    table = Table(title="Documentation Pages")
    table.add_column("Page", style="bold")
    table.add_column("Title")
    for md in sorted(docs_dir.glob("*.md")):
        title = md.stem.replace("-", " ").title()
        for line in md.read_text().splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        table.add_row(md.stem, title)
    console.print(table)


@docs_group.command(name="read")
@click.argument("page")
def docs_read(page: str) -> None:
    """Read a documentation page aloud using study-speak.

    PAGE is the doc name without .md extension (e.g. 'voice-output', 'audhd-learning-philosophy').
    Use 'studyctl docs list' to see available pages.
    """
    import subprocess

    docs_dir = _find_docs_dir()
    md_file = docs_dir / f"{page}.md"
    if not md_file.exists():
        matches = [f for f in docs_dir.glob("*.md") if page.lower() in f.stem.lower()]
        if len(matches) == 1:
            md_file = matches[0]
        else:
            console.print(
                f"[red]Page '{page}' not found.[/red] Run [bold]studyctl docs list[/bold]"
            )
            return

    text = _strip_markdown(md_file.read_text())
    if not text:
        console.print("[yellow]Page is empty after stripping markdown.[/yellow]")
        return

    speak_bin = Path.home() / ".local" / "bin" / "study-speak"
    if not speak_bin.exists():
        console.print(
            "[red]study-speak not installed.[/red]"
            " Run: uv tool install './packages/agent-session-tools[tts]'"
        )
        return

    console.print(f"[bold]\U0001f4d6 Reading: {md_file.stem}[/bold]")
    console.print(f"[dim]({len(text.split())} words \u2014 press Ctrl+C to stop)[/dim]\n")

    try:
        subprocess.run([str(speak_bin), text], check=True, timeout=300)
        console.print("\n[green]\u2713 Done reading[/green]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped reading[/yellow]")
    except subprocess.TimeoutExpired:
        console.print("\n[yellow]Reading timed out[/yellow]")
