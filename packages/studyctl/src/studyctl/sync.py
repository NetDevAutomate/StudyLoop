"""Sync engine — Obsidian → NotebookLM via notebooklm-py CLI."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .pdf import md_to_pdf
from .settings import MIN_FILE_SIZE, SKIP_FILENAMES, SKIP_PATTERNS, SYNCABLE_EXTENSIONS
from .state import SyncState, file_hash

if TYPE_CHECKING:
    from .topics import Topic


def _should_skip(path: Path) -> bool:
    """Filter out low-value files."""
    # Skip by directory/file pattern
    for part in path.parts:
        if part in SKIP_PATTERNS or part.startswith("."):
            return True
    # Skip by filename
    if path.name in SKIP_FILENAMES:
        return True
    # Skip tiny files (stubs, empty templates)
    return path.stat().st_size < MIN_FILE_SIZE


def find_sources(topic: Topic) -> list[Path]:
    """Find all syncable files for a topic, filtered for quality."""
    sources = []
    for base in topic.obsidian_paths:
        if not base.exists():
            continue
        for ext in SYNCABLE_EXTENSIONS:
            for p in sorted(base.rglob(f"*{ext}")):
                if not _should_skip(p):
                    sources.append(p)
    return sources


def find_changed_sources(topic: Topic, state: SyncState) -> list[Path]:
    """Find sources that are new or changed since last sync."""
    return [p for p in find_sources(topic) if state.needs_sync(p)]


def _run_nlm(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a notebooklm CLI command."""
    return subprocess.run(["notebooklm", *args], capture_output=True, text=True, check=check)


def ensure_notebook(topic: Topic, state: SyncState) -> str:
    """Get or create the NotebookLM notebook for a topic. Returns notebook_id."""
    # Use pre-mapped ID if available
    if topic.notebook_id:
        state.set_notebook_id(topic.name, topic.notebook_id, topic.display_name)
        state.save()
        return topic.notebook_id

    # Check state for previously created notebook
    ts = state.get_topic(topic.name)
    if ts.notebook_id:
        return ts.notebook_id

    # Check if notebook already exists by title
    result = _run_nlm(["list", "--json"])
    try:
        notebooks = json.loads(result.stdout).get("notebooks", [])
    except json.JSONDecodeError:
        import sys

        print(f"[studyctl] Failed to parse notebook list: {result.stdout[:200]}", file=sys.stderr)
        notebooks = []
    for nb in notebooks:
        if nb["title"] == topic.display_name:
            state.set_notebook_id(topic.name, nb["id"], nb["title"])
            state.save()
            return nb["id"]

    # Create new notebook
    result = _run_nlm(["create", topic.display_name, "--json"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        import sys

        print(
            f"[studyctl] Failed to parse create response: {result.stdout[:200]}",
            file=sys.stderr,
        )
        data = {}
    notebook_id = data.get("id") or data.get("notebook", {}).get("id", "")
    state.set_notebook_id(topic.name, notebook_id, topic.display_name)
    state.save()
    return notebook_id


def sync_source(
    path: Path,
    notebook_id: str,
    topic_name: str,
    state: SyncState,
    pdf_dir: Path | None = None,
    unique_name: str | None = None,
) -> str | None:
    """Sync a single file to NotebookLM. Converts .md to PDF first. Returns source_id or None."""
    upload_path = path
    if path.suffix == ".md" and pdf_dir:
        pdf = md_to_pdf(path, pdf_dir, unique_name)
        if pdf:
            upload_path = pdf

    result = _run_nlm(
        ["source", "add", str(upload_path), "--notebook", notebook_id, "--json"],
        check=False,
    )
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    source_id = data.get("source_id") or data.get("source", {}).get("id", "")
    if not source_id:
        return None
    rel_path = str(path.relative_to(Path.home()))
    state.record_sync(topic_name, rel_path, file_hash(path), source_id, notebook_id)
    state.save()
    return source_id


def sync_topic(topic: Topic, state: SyncState, dry_run: bool = False, as_pdf: bool = True) -> dict:
    """Sync all changed sources for a topic. Returns summary."""
    changed = find_changed_sources(topic, state)
    total = len(find_sources(topic))
    if not changed:
        return {"topic": topic.name, "total": total, "changed": 0, "synced": 0, "failed": 0}

    if dry_run:
        return {
            "topic": topic.name,
            "total": total,
            "changed": len(changed),
            "synced": 0,
            "failed": 0,
            "dry_run": True,
            "files": [str(p.name) for p in changed[:10]],
        }

    notebook_id = ensure_notebook(topic, state)
    synced = failed = 0

    # Build unique names for files with duplicate stems
    name_map = _build_unique_names(changed)

    with tempfile.TemporaryDirectory(prefix="studyctl-pdf-") as pdf_dir:
        pdf_path = Path(pdf_dir) if as_pdf else None
        for path in changed:
            unique = name_map.get(str(path))
            if sync_source(
                path, notebook_id, topic.name, state, pdf_dir=pdf_path, unique_name=unique
            ):
                synced += 1
            else:
                failed += 1

    return {
        "topic": topic.name,
        "total": total,
        "changed": len(changed),
        "synced": synced,
        "failed": failed,
    }


def _build_unique_names(paths: list[Path]) -> dict[str, str]:
    """For files with duplicate stems, prefix with parent dir name.

    e.g. two 'introduction.md' files become:
      'the-software-designer-mindset--introduction'
      'pythonic-patterns--introduction'
    """
    from collections import Counter

    stem_counts = Counter(p.stem for p in paths)
    duplicated = {stem for stem, count in stem_counts.items() if count > 1}

    name_map: dict[str, str] = {}
    for p in paths:
        if p.stem in duplicated:
            # Walk up parents until we find a distinguishing name
            # e.g. .../the-software-designer-mindset/study-notes/introduction.md
            #   → "the-software-designer-mindset--introduction"
            parts = p.parts
            for i in range(len(parts) - 2, 0, -1):
                candidate = parts[i]
                if candidate != "study-notes" and candidate != "lessons":
                    name_map[str(p)] = f"{candidate}--{p.stem}"
                    break
            else:
                name_map[str(p)] = f"{p.parent.name}--{p.stem}"

    return name_map


def generate_audio(topic: Topic, state: SyncState, instructions: str = "") -> str | None:
    """Generate an audio overview for a topic. Returns artifact_id or None."""
    ts = state.get_topic(topic.name)
    if not ts.notebook_id:
        return None

    args = ["generate", "audio", "--notebook", ts.notebook_id, "--json"]
    if instructions:
        args.insert(2, instructions)

    result = _run_nlm(args, check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("task_id")
    except json.JSONDecodeError:
        import sys

        print(
            f"[studyctl] Failed to parse audio response: {result.stdout[:200]}",
            file=sys.stderr,
        )
        return None
