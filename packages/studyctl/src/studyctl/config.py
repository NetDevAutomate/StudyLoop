"""Topic→notebook mapping and path configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .settings import load_settings

_settings = load_settings()

HOME = Path.home()
OBSIDIAN_BASE = _settings.obsidian_base
OBSIDIAN_COURSES = OBSIDIAN_BASE / "Personal" / "2-Areas" / "Study" / "Courses"
OBSIDIAN_STUDY_PLANS = OBSIDIAN_BASE / "Personal" / "2-Areas" / "Study" / "Study-Plans"
OBSIDIAN_MENTORING = OBSIDIAN_BASE / "Personal" / "2-Areas" / "Study" / "Mentoring"
STATE_DIR = _settings.state_dir
STATE_FILE = STATE_DIR / "state.json"
MEDIA_DIR = OBSIDIAN_BASE / "Personal" / "2-Areas" / "Study" / "media"

# File extensions we sync as sources
SYNCABLE_EXTENSIONS = {".md", ".pdf", ".txt"}

# Skip patterns — files/dirs that are never worth syncing
SKIP_PATTERNS = {
    ".space",
    ".checkpoint.json",
    "def.json",
    ".obsidian",
    "node_modules",
    "__pycache__",
}

# Files that are low-value noise (Obsidian metadata, empty templates, etc.)
SKIP_FILENAMES = {
    "Courses.md",  # Index file, not content
}

# Minimum file size to sync (skip empty/stub files)
MIN_FILE_SIZE = 100  # bytes


@dataclass
class Topic:
    """A study topic maps to one NotebookLM notebook."""

    name: str
    display_name: str
    notebook_id: str | None  # Pre-mapped to existing NotebookLM notebook
    obsidian_paths: list[Path]
    tags: list[str] = field(default_factory=list)


def get_topics() -> list[Topic]:
    """Load topics from settings, falling back to defaults (without notebook IDs)."""
    settings = load_settings()
    if settings.topics:
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

    # Defaults — no hardcoded notebook IDs
    return [
        Topic(
            name="python",
            display_name="Python Study",
            notebook_id=None,
            obsidian_paths=[OBSIDIAN_COURSES / "ArjanCodes", OBSIDIAN_MENTORING / "Python"],
            tags=["python", "patterns", "oop", "architecture"],
        ),
        Topic(
            name="sql",
            display_name="SQL & Database Design",
            notebook_id=None,
            obsidian_paths=[OBSIDIAN_COURSES / "DataCamp", OBSIDIAN_MENTORING / "Databases"],
            tags=["sql", "postgresql", "athena", "redshift", "database"],
        ),
        Topic(
            name="data-engineering",
            display_name="Data Engineering",
            notebook_id=None,
            obsidian_paths=[
                OBSIDIAN_COURSES / "ZTM" / "transcripts" / "data-engineering-bootcamp",
                OBSIDIAN_MENTORING / "Data-Engineering",
            ],
            tags=["etl", "spark", "glue", "airflow", "dbt", "pipeline", "lakehouse"],
        ),
        Topic(
            name="aws-analytics",
            display_name="AWS Analytics Services",
            notebook_id=None,
            obsidian_paths=[
                OBSIDIAN_COURSES / "ZTM" / "Ai-Engineering-Aws-Sagemaker",
                OBSIDIAN_MENTORING / "AWS",
            ],
            tags=["athena", "redshift", "glue", "sagemaker", "lake-formation", "emr"],
        ),
    ]


# Keep DEFAULT_TOPICS for backward compatibility with cli.py
DEFAULT_TOPICS = get_topics()
