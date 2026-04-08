"""Artefact serving routes with path traversal protection."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — used at runtime for resolve/is_relative_to

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from studyctl.settings import load_settings

router = APIRouter()


def _validate_artefact_path(course: str, artefact_type: str, filename: str) -> Path:
    """Resolve and validate artefact path against directory traversal.

    Ensures the resolved path is a child of content.base_path.
    Raises 404 if path escapes the base or file doesn't exist.
    """
    base = load_settings().content.base_path
    resolved = (base / course / artefact_type / filename).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise HTTPException(status_code=404)
    if not resolved.is_file():
        raise HTTPException(status_code=404)
    return resolved


@router.get("/artefacts/{course}/{artefact_type}/{filename:path}")
def serve_artefact(course: str, artefact_type: str, filename: str) -> FileResponse:
    """Serve an artefact file (audio, video, slides, etc.) with path validation."""
    path = _validate_artefact_path(course, artefact_type, filename)
    return FileResponse(path)


@router.get("/api/artefacts/{course}")
def list_artefacts(course: str) -> list[dict]:
    """List all artefacts for a course grouped by type."""
    base = load_settings().content.base_path
    course_dir = (base / course).resolve()
    if not course_dir.is_relative_to(base.resolve()):
        raise HTTPException(status_code=404)
    if not course_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Course '{course}' not found")

    result = []
    for type_dir in sorted(course_dir.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        files = sorted(f.name for f in type_dir.iterdir() if f.is_file())
        if files:
            result.append(
                {
                    "type": type_dir.name,
                    "files": files,
                }
            )
    return result
