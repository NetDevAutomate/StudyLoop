"""Dry-run ingest planning for study content workflows."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.content.discovery import DiscoveredMaterial, discover_materials
from studyctl.content.storage import load_course_metadata, slugify

IngestAction = Literal["create", "update", "skip"]


@dataclass(frozen=True)
class IngestPlanItem:
    """One planned source action for content ingest."""

    course_slug: str
    course_dir: Path
    action: IngestAction
    material: DiscoveredMaterial
    content_hash: str

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        data = asdict(self)
        data["course_dir"] = str(self.course_dir)
        data["material"] = self.material.to_json_dict()
        return data


def build_ingest_plan(
    *,
    source_roots: list[Path],
    base_path: Path,
    course: str | None = None,
) -> list[IngestPlanItem]:
    """Build a dry-run ingest plan without mutating local or NotebookLM state."""
    materials = discover_materials(source_roots)
    metadata_cache: dict[str, dict] = {}
    plan: list[IngestPlanItem] = []

    for material in materials:
        course_slug = _course_slug_for_material(material, course)
        course_dir = base_path.expanduser() / course_slug
        metadata = metadata_cache.setdefault(course_slug, load_course_metadata(course_dir))
        source_metadata = _source_metadata_by_path(metadata)
        content_hash = _sha256(material.path)
        existing = source_metadata.get(str(material.path))
        if existing is None:
            action: IngestAction = "create"
        elif existing.get("hash") == content_hash:
            action = "skip"
        else:
            action = "update"
        plan.append(
            IngestPlanItem(
                course_slug=course_slug,
                course_dir=course_dir,
                action=action,
                material=material,
                content_hash=content_hash,
            )
        )

    return plan


def _source_metadata_by_path(metadata: dict) -> dict[str, dict]:
    sources = metadata.get("sources", [])
    if not isinstance(sources, list):
        return {}
    return {
        str(source["path"]): source
        for source in sources
        if isinstance(source, dict) and "path" in source
    }


def _course_slug_for_material(material: DiscoveredMaterial, course: str | None) -> str:
    if course:
        return slugify(course)
    return slugify(material.source_root.name) or "course"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
