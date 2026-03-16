"""Content commands -- PDF splitting, NotebookLM integration, syllabus workflow.

Absorbed from pdf-by-chapters. All commands are under ``studyctl content``.
Heavy imports (pymupdf, notebooklm-py) are deferred to function bodies.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _resolve_pdfs(source: Path) -> list[Path]:
    """Resolve source to a list of PDF paths (single file or directory glob)."""
    if source.is_dir():
        pdfs = sorted(source.glob("*.pdf"))
        if not pdfs:
            raise click.ClickException(f"No PDF files found in {source}")
        return pdfs
    if not source.is_file():
        raise click.ClickException(f"'{source}' does not exist")
    return [source]


def _get_notebook_id(notebook_id: str | None) -> str:
    """Resolve notebook ID from option or raise."""
    if not notebook_id:
        raise click.ClickException(
            "No notebook ID. Use -n/--notebook-id or set NOTEBOOK_ID env var."
        )
    return notebook_id


def _parse_chapter_range(raw: str) -> tuple[int, int]:
    """Parse a chapter range string like '1-3' into (start, end)."""
    try:
        parts = raw.split("-")
        start, end = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise click.ClickException(f"Invalid chapter range '{raw}'. Use format: 1-3") from None
    if start < 1 or end < start:
        raise click.ClickException(
            f"Invalid range: start must be >= 1 and <= end (got {start}-{end})"
        )
    return (start, end)


@click.group(name="content")
def content_group() -> None:
    """Content pipeline -- PDF splitting, NotebookLM, and syllabus workflow."""


# ---------------------------------------------------------------------------
# Core commands
# ---------------------------------------------------------------------------


@content_group.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="./chapters")
@click.option("-l", "--level", default=1, help="TOC level to split on (1=top-level).")
@click.option("--ranges", default=None, help="Page ranges for PDFs without TOC, e.g. '1-30,31-60'.")
def split(source: Path, output_dir: Path, level: int, ranges: str | None) -> None:
    """Split a PDF into per-chapter files by TOC bookmarks."""
    from studyctl.content.splitter import (
        sanitize_filename,
        split_pdf_by_chapters,
        split_pdf_by_ranges,
    )

    for pdf_path in _resolve_pdfs(source):
        book_name = sanitize_filename(pdf_path.stem)
        if ranges:
            paths = split_pdf_by_ranges(pdf_path, output_dir, book_name, ranges)
        else:
            paths = split_pdf_by_chapters(pdf_path, output_dir, book_name, level=level)
        console.print(f"[green]\u2713[/green] {len(paths)} chapters written to {output_dir}")


@content_group.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="./chapters")
@click.option("-l", "--level", default=1, help="TOC level to split on.")
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", default=None)
def process(source: Path, output_dir: Path, level: int, notebook_id: str | None) -> None:
    """Split PDFs by chapter, upload to NotebookLM, and show summary."""
    from studyctl.content.notebooklm_client import upload_chapters
    from studyctl.content.splitter import sanitize_filename, split_pdf_by_chapters

    for pdf_path in _resolve_pdfs(source):
        book_name = sanitize_filename(pdf_path.stem)
        chapter_paths = split_pdf_by_chapters(pdf_path, output_dir, book_name, level=level)
        console.print(f"[green]\u2713[/green] Split into {len(chapter_paths)} chapters")

        nid = _get_notebook_id(notebook_id)
        result = asyncio.run(upload_chapters(nid, chapter_paths))
        console.print(
            f"[green]\u2713[/green] Uploaded {result.chapters} chapters "
            f"to notebook {result.id[:8]}..."
        )


@content_group.command("list")
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", default=None)
def list_cmd(notebook_id: str | None) -> None:
    """List notebooks, or sources within a notebook."""
    from studyctl.content.notebooklm_client import list_notebooks, list_sources

    if notebook_id:
        sources = asyncio.run(list_sources(notebook_id))
        table = Table(title=f"Sources in {notebook_id[:8]}...")
        table.add_column("ID", style="dim")
        table.add_column("Title")
        for s in sources:
            table.add_row(s.id[:8] + "...", s.title)
        console.print(table)
    else:
        notebooks = asyncio.run(list_notebooks())
        table = Table(title="NotebookLM Notebooks")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="bold")
        table.add_column("Sources", justify="right")
        for nb in notebooks:
            table.add_row(nb.id[:8] + "...", nb.title, str(nb.sources_count))
        console.print(table)


@content_group.command()
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", required=True)
@click.option("-c", "--chapters", required=True, help="Chapter range, e.g. '1-3'.")
@click.option("--no-audio", is_flag=True, help="Skip audio generation.")
@click.option("--no-video", is_flag=True, help="Skip video generation.")
@click.option("-t", "--timeout", default=900, help="Timeout in seconds (default: 900).")
def generate(
    notebook_id: str,
    chapters: str,
    no_audio: bool,
    no_video: bool,
    timeout: int,
) -> None:
    """Generate audio/video overviews for a chapter range."""
    from studyctl.content.notebooklm_client import generate_for_chapters

    start, end = _parse_chapter_range(chapters)
    types = []
    if not no_audio:
        types.append("audio")
    if not no_video:
        types.append("video")

    if not types:
        raise click.ClickException("Nothing to generate (both audio and video disabled).")

    console.print(f"Generating {', '.join(types)} for chapters {start}-{end}...")
    asyncio.run(generate_for_chapters(notebook_id, start, end, types=types, timeout=timeout))
    console.print("[green]\u2713[/green] Generation complete")


@content_group.command()
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", required=True)
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="./overviews")
@click.option("-c", "--chapters", default=None, help="Chapter range label for filenames.")
def download(notebook_id: str, output_dir: Path, chapters: str | None) -> None:
    """Download audio and video artifacts from a notebook."""
    from studyctl.content.notebooklm_client import download_artifacts

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = asyncio.run(download_artifacts(notebook_id, output_dir, chapters))
    for p in paths:
        console.print(f"[green]\u2713[/green] {p.name}")
    if not paths:
        console.print("[dim]No artifacts to download[/dim]")


@content_group.command("delete")
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", required=True)
@click.confirmation_option(prompt="Are you sure you want to delete this notebook?")
def delete_cmd(notebook_id: str) -> None:
    """Delete a notebook and all its contents."""
    from studyctl.content.notebooklm_client import delete_notebook

    asyncio.run(delete_notebook(notebook_id))
    console.print(f"[green]\u2713[/green] Deleted notebook {notebook_id[:8]}...")


# ---------------------------------------------------------------------------
# Syllabus workflow
# ---------------------------------------------------------------------------


@content_group.command()
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", required=True)
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="./chapters")
@click.option("-m", "--max-chapters", default=2, help="Max chapters per episode.")
@click.option("-b", "--book-name", default=None, help="Book name for state file.")
@click.option("--force", is_flag=True, help="Overwrite existing syllabus.")
@click.option("--no-audio", is_flag=True, help="Skip audio generation.")
@click.option("--no-video", is_flag=True, help="Skip video generation.")
def syllabus(
    notebook_id: str,
    output_dir: Path,
    max_chapters: int,
    book_name: str | None,
    force: bool,
    no_audio: bool,
    no_video: bool,
) -> None:
    """Generate a podcast syllabus and save as a plan."""
    from studyctl.content.notebooklm_client import create_syllabus, list_sources
    from studyctl.content.syllabus import (
        build_fixed_size_chunks,
        build_prompt,
        has_non_pending_chunks,
        map_sources_to_chapters,
        parse_syllabus_response,
        read_state,
        write_state,
    )

    resolved_book_name = book_name or output_dir.resolve().name
    state_path = output_dir / f".{resolved_book_name}-syllabus.json"

    # Check for existing state
    existing = read_state(state_path)
    if existing and has_non_pending_chunks(existing) and not force:
        console.print(
            "[yellow]Syllabus already exists with in-progress chunks.[/yellow]\n"
            "Use --force to overwrite."
        )
        return

    # Get sources and build chunks
    sources = asyncio.run(list_sources(notebook_id))
    source_map = map_sources_to_chapters(sources)
    chunks = build_fixed_size_chunks(source_map, max_chapters=max_chapters)

    # Generate syllabus via NotebookLM chat
    prompt = build_prompt(chunks)
    console.print(f"Generating syllabus for {len(chunks)} episodes...")
    response = asyncio.run(create_syllabus(notebook_id, prompt))
    state = parse_syllabus_response(response, chunks, resolved_book_name)

    # Configure artifact types
    types = []
    if not no_audio:
        types.append("audio")
    if not no_video:
        types.append("video")
    state.artifact_types = types

    write_state(state_path, state)

    # Display syllabus table
    table = Table(title=f"Syllabus: {resolved_book_name}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title", style="bold")
    table.add_column("Chapters", style="cyan")
    table.add_column("Status")
    for chunk in state.chunks.values():
        ch_str = ", ".join(str(c) for c in chunk.chapters)
        table.add_row(str(chunk.episode), chunk.title, ch_str, chunk.status.value)
    console.print(table)
    console.print(f"\nState saved to {state_path}")
    console.print(f"Next: Run [bold]studyctl content autopilot -o {output_dir}[/bold]")


@content_group.command("autopilot")
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="./chapters")
@click.option("-b", "--book-name", default=None, help="Book name for state file.")
@click.option("-t", "--timeout", default=900, help="Timeout per episode in seconds.")
def autopilot(output_dir: Path, book_name: str | None, timeout: int) -> None:
    """Generate the next pending episode from the syllabus."""
    from studyctl.content.notebooklm_client import (
        download_episode_audio,
        start_chunk_generation,
    )
    from studyctl.content.syllabus import (
        ChunkStatus,
        get_next_chunk,
        read_state,
        write_state,
    )

    resolved_book_name = book_name or output_dir.resolve().name
    state_path = output_dir / f".{resolved_book_name}-syllabus.json"

    state = read_state(state_path)
    if not state:
        raise click.ClickException(
            f"No syllabus state found at {state_path}. Run 'studyctl content syllabus' first."
        )

    chunk = get_next_chunk(state)
    if not chunk:
        console.print("[green]All episodes complete![/green]")
        return

    console.print(
        f"Episode {chunk.episode}: [bold]{chunk.title}[/bold] "
        f"(chapters {', '.join(str(c) for c in chunk.chapters)})"
    )

    # Start generation
    chunk.status = ChunkStatus.GENERATING
    write_state(state_path, state)

    try:
        asyncio.run(start_chunk_generation(state.notebook_id, chunk, timeout=timeout))
        # Download audio
        downloads_dir = output_dir / "downloads" / "audio"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        asyncio.run(download_episode_audio(state.notebook_id, chunk, downloads_dir))
        chunk.status = ChunkStatus.COMPLETED
        console.print(f"[green]\u2713[/green] Episode {chunk.episode} complete")
    except Exception as exc:
        chunk.status = ChunkStatus.FAILED
        console.print(f"[red]Episode {chunk.episode} failed: {exc}[/red]")
    finally:
        write_state(state_path, state)


@content_group.command("status")
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="./chapters")
@click.option("-b", "--book-name", default=None, help="Book name for state file.")
def status_cmd(output_dir: Path, book_name: str | None) -> None:
    """Show syllabus progress for chunked generation."""
    from studyctl.content.syllabus import read_state

    resolved_book_name = book_name or output_dir.resolve().name
    state_path = output_dir / f".{resolved_book_name}-syllabus.json"

    state = read_state(state_path)
    if not state:
        raise click.ClickException(
            f"No syllabus state at {state_path}. Run 'studyctl content syllabus' first."
        )

    table = Table(title=f"Syllabus: {state.book_name}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title", style="bold")
    table.add_column("Chapters", style="cyan")
    table.add_column("Status")

    status_style = {
        "pending": "dim",
        "generating": "yellow",
        "completed": "green",
        "failed": "red",
    }

    for chunk in state.chunks.values():
        ch_str = ", ".join(str(c) for c in chunk.chapters)
        style = status_style.get(chunk.status.value, "")
        status_text = f"[{style}]{chunk.status.value}[/{style}]" if style else chunk.status.value
        table.add_row(str(chunk.episode), chunk.title, ch_str, status_text)

    console.print(table)

    completed = sum(1 for c in state.chunks.values() if c.status.value == "completed")
    total = len(state.chunks)
    console.print(f"\nProgress: {completed}/{total} episodes complete")


# ---------------------------------------------------------------------------
# Obsidian integration
# ---------------------------------------------------------------------------


@content_group.command("from-obsidian")
@click.argument("source_dir", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default=None)
@click.option("--name", "notebook_name", default=None, help="Notebook name.")
@click.option("-n", "--notebook-id", envvar="NOTEBOOK_ID", default=None)
@click.option("--no-generate", is_flag=True, help="Upload only, skip artifact generation.")
@click.option("--no-audio", is_flag=True, help="Skip audio generation.")
@click.option("--no-download", is_flag=True, help="Skip artifact download.")
@click.option("--no-quiz", is_flag=True, help="Skip quiz generation.")
@click.option("--no-flashcards", is_flag=True, help="Skip flashcard generation.")
@click.option("--skip-convert", is_flag=True, help="Skip PDF conversion, use existing PDFs.")
@click.option("-s", "--subdir", default=None, help="Subdirectory within source.")
def from_obsidian(
    source_dir: Path,
    output_dir: Path | None,
    notebook_name: str | None,
    notebook_id: str | None,
    no_generate: bool,
    no_audio: bool,
    no_download: bool,
    no_quiz: bool,
    no_flashcards: bool,
    skip_convert: bool,
    subdir: str | None,
) -> None:
    """Convert Obsidian markdown to PDFs and upload to NotebookLM."""
    from studyctl.content.markdown_converter import convert_directory
    from studyctl.content.notebooklm_client import (
        generate_for_chapters,
        upload_chapters,
    )

    actual_dir = source_dir / subdir if subdir else source_dir
    if not actual_dir.is_dir():
        raise click.ClickException(f"Directory not found: {actual_dir}")

    out = output_dir or source_dir / "downloads"
    out.mkdir(parents=True, exist_ok=True)
    name = notebook_name or source_dir.name.replace("-", " ").replace("_", " ").title()

    # Step 1: Convert markdown to PDFs
    if not skip_convert:
        console.print(f"Converting markdown in {actual_dir}...")
        pdf_dir = out / "pdfs"
        convert_directory(actual_dir, pdf_dir)
        console.print(f"[green]\u2713[/green] PDFs written to {pdf_dir}")
    else:
        pdf_dir = out / "pdfs"

    # Step 2: Upload
    pdf_files = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.is_dir() else []
    if not pdf_files:
        console.print("[yellow]No PDFs to upload[/yellow]")
        return

    nid = notebook_id
    if not nid:
        console.print(f"Creating notebook: [bold]{name}[/bold]")
    result = asyncio.run(upload_chapters(nid, pdf_files, title=name))
    nid = result.id
    console.print(
        f"[green]\u2713[/green] Uploaded {result.chapters} files to notebook {nid[:8]}..."
    )

    if no_generate:
        return

    # Step 3: Generate artifacts
    types = []
    if not no_audio:
        types.append("audio")
    if not no_quiz:
        types.append("quiz")
    if not no_flashcards:
        types.append("flashcards")

    if types:
        console.print(f"Generating {', '.join(types)}...")
        asyncio.run(generate_for_chapters(nid, 1, len(pdf_files), types=types))
        console.print("[green]\u2713[/green] Generation complete")

    if not no_download:
        from studyctl.content.notebooklm_client import download_artifacts

        console.print("Downloading artifacts...")
        paths = asyncio.run(download_artifacts(nid, out))
        for p in paths:
            console.print(f"  [green]\u2713[/green] {p.name}")
