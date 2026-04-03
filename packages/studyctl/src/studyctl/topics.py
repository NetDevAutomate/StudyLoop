"""Study topic definitions loaded from config.

Separated from settings.py to keep config infrastructure (loading, paths,
dataclasses) distinct from domain-specific topic mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .settings import load_settings

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Topic:
    """A study topic maps to one NotebookLM notebook."""

    name: str
    display_name: str
    notebook_id: str | None  # Pre-mapped to existing NotebookLM notebook
    obsidian_paths: list[Path]
    tags: list[str] = field(default_factory=list)


def get_topics() -> list[Topic]:
    """Load topics from settings. Returns empty list if none configured.

    Topics are defined in ~/.config/studyctl/config.yaml under the 'topics'
    key. Run 'studyctl config init' for interactive setup.
    """
    settings = load_settings()
    return [
        Topic(
            name=t.slug,
            display_name=t.name,
            notebook_id=t.notebook_id or None,
            obsidian_paths=[t.obsidian_path],
            tags=t.tags,
        )
        for t in settings.topics
    ]
