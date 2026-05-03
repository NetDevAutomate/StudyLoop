"""Discover study materials in configured Obsidian/course source paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.settings import MIN_FILE_SIZE, SKIP_FILENAMES, SKIP_PATTERNS, SYNCABLE_EXTENSIONS

MaterialKind = Literal["markdown", "pdf", "text"]


@dataclass(frozen=True)
class DiscoveredMaterial:
    """One source file that can contribute to study material generation."""

    source_root: Path
    path: Path
    title: str
    kind: MaterialKind
    size_bytes: int
    modified_at: str

    def to_json_dict(self) -> dict[str, str | int]:
        """Return a JSON-serializable representation."""
        data = asdict(self)
        data["source_root"] = str(self.source_root)
        data["path"] = str(self.path)
        return data


def discover_materials(source_roots: list[Path]) -> list[DiscoveredMaterial]:
    """Discover syncable study materials under source roots."""
    materials: list[DiscoveredMaterial] = []
    seen: set[Path] = set()

    for source_root in source_roots:
        root = source_root.expanduser()
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or _should_skip_path(path, root):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            stat = path.stat()
            materials.append(
                DiscoveredMaterial(
                    source_root=root,
                    path=path,
                    title=_title_for_path(path),
                    kind=_kind_for_path(path),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                )
            )

    return materials


def _should_skip_path(path: Path, source_root: Path) -> bool:
    """Return True when a path is low-value or unsupported for study ingestion."""
    if path.suffix.lower() not in SYNCABLE_EXTENSIONS:
        return True
    if path.name in SKIP_FILENAMES:
        return True
    if path.stat().st_size < MIN_FILE_SIZE:
        return True

    relative_parts = path.relative_to(source_root).parts
    return any(part in SKIP_PATTERNS for part in relative_parts)


def _kind_for_path(path: Path) -> MaterialKind:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    return "text"


def _title_for_path(path: Path) -> str:
    """Return a human-readable title for a material path."""
    return path.stem.replace("-", " ").replace("_", " ").strip().title()
