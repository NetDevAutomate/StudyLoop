"""Topic→notebook mapping and path configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()

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
    from .settings import load_settings

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

    # Compute paths from settings for defaults
    obsidian_base = settings.obsidian_base
    obsidian_courses = obsidian_base / "Personal" / "2-Areas" / "Study" / "Courses"
    obsidian_mentoring = obsidian_base / "Personal" / "2-Areas" / "Study" / "Mentoring"

    return [
        Topic(
            name="python",
            display_name="Python Study",
            notebook_id=None,
            obsidian_paths=[obsidian_courses / "ArjanCodes", obsidian_mentoring / "Python"],
            tags=["python", "patterns", "oop", "architecture"],
        ),
        Topic(
            name="sql",
            display_name="SQL & Database Design",
            notebook_id=None,
            obsidian_paths=[obsidian_courses / "DataCamp", obsidian_mentoring / "Databases"],
            tags=["sql", "postgresql", "athena", "redshift", "database"],
        ),
        Topic(
            name="data-engineering",
            display_name="Data Engineering",
            notebook_id=None,
            obsidian_paths=[
                obsidian_courses / "ZTM" / "transcripts" / "data-engineering-bootcamp",
                obsidian_mentoring / "Data-Engineering",
            ],
            tags=["etl", "spark", "glue", "airflow", "dbt", "pipeline", "lakehouse"],
        ),
        Topic(
            name="aws-analytics",
            display_name="AWS Analytics Services",
            notebook_id=None,
            obsidian_paths=[
                obsidian_courses / "ZTM" / "Ai-Engineering-Aws-Sagemaker",
                obsidian_mentoring / "AWS",
            ],
            tags=["athena", "redshift", "glue", "sagemaker", "lake-formation", "emr"],
        ),
    ]


# Lazy-loaded for backward compatibility
def __getattr__(name: str):
    if name == "DEFAULT_TOPICS":
        return get_topics()
    if name in (
        "STATE_DIR",
        "STATE_FILE",
        "OBSIDIAN_BASE",
        "OBSIDIAN_COURSES",
        "OBSIDIAN_STUDY_PLANS",
        "OBSIDIAN_MENTORING",
        "MEDIA_DIR",
    ):
        from .settings import load_settings

        settings = load_settings()
        obs = settings.obsidian_base
        _lazy = {
            "STATE_DIR": settings.state_dir,
            "STATE_FILE": settings.state_dir / "state.json",
            "OBSIDIAN_BASE": obs,
            "OBSIDIAN_COURSES": obs / "Personal" / "2-Areas" / "Study" / "Courses",
            "OBSIDIAN_STUDY_PLANS": obs / "Personal" / "2-Areas" / "Study" / "Study-Plans",
            "OBSIDIAN_MENTORING": obs / "Personal" / "2-Areas" / "Study" / "Mentoring",
            "MEDIA_DIR": obs / "Personal" / "2-Areas" / "Study" / "media",
        }
        return _lazy[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
