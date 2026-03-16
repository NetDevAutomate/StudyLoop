"""Syllabus generation, parsing, and state management for chunked audio/video."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILENAME = "syllabus_state.json"

_TITLE_CLEAN_RE = re.compile(r"[^\w\s-]")


def title_case_name(name: str) -> str:
    """Clean a title for NotebookLM artifact display. Preserves Title Case.

    Unlike sanitize_filename() which lowercases for filesystem paths,
    this keeps capitalisation for readable display names in the NotebookLM UI.

    Args:
        name: Raw episode title.

    Returns:
        Cleaned title with each word capitalised, max 100 chars.
    """
    name = _TITLE_CLEAN_RE.sub("", name)
    name = " ".join(name.split())
    return name[:100].strip().title()


# Matches: Episode 1: "Title Here"\nChapters: 1, 2\nSummary: ...
_EPISODE_RE = re.compile(
    r'Episode\s+(\d+):\s*"([^"]+)"\s*\n'
    r"Chapters?:\s*([\d,\s]+)\s*\n"
    r"Summary:\s*(.+)",
    re.IGNORECASE,
)

_CHAPTER_NUM_RE = re.compile(r"chapter_(\d+)", re.IGNORECASE)

SYLLABUS_PROMPT_TEMPLATE = """\
I have uploaded several sources, each representing a sequential chapter \
from a single technical eBook. Here are the chapters:

{source_list}

Please divide these chapters into a "Podcast Syllabus" consisting of \
logical chunks. Strictly limit each chunk to at most {max_chapters} \
chapters. Group them by related technical concepts.

Format your response EXACTLY as follows, one entry per chunk:

Episode 1: "Episode Title Here"
Chapters: 1, 2
Summary: One or two sentence summary.

Episode 2: "Episode Title Here"
Chapters: 3
Summary: One or two sentence summary.

Use ONLY the chapter numbers listed above. Output ONLY the syllabus."""


class SyllabusParseError(Exception):
    """Raised when the LLM syllabus response cannot be parsed."""


class SyllabusStateError(Exception):
    """Raised when the state file is missing, corrupt, or invalid."""


class ChunkStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ChunkArtifact:
    """Tracks a single artifact (audio or video) within a chunk."""

    task_id: str = ""
    status: str = "pending"

    def to_json(self) -> dict[str, str]:
        return {"task_id": self.task_id, "status": self.status}

    @classmethod
    def from_json(cls, data: dict[str, str]) -> ChunkArtifact:
        return cls(task_id=data.get("task_id", ""), status=data.get("status", "pending"))


@dataclass
class SyllabusChunk:
    """A single episode in the syllabus plan."""

    episode: int
    title: str
    chapters: list[int]
    source_ids: list[str]
    chapter_titles: list[str] = field(default_factory=list)
    status: ChunkStatus = ChunkStatus.PENDING
    artifacts: dict[str, ChunkArtifact] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "episode": self.episode,
            "title": self.title,
            "chapters": self.chapters,
            "source_ids": self.source_ids,
            "chapter_titles": self.chapter_titles,
            "status": self.status.value,
            "artifacts": {k: v.to_json() for k, v in self.artifacts.items()},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SyllabusChunk:
        artifacts = {k: ChunkArtifact.from_json(v) for k, v in data.get("artifacts", {}).items()}
        return cls(
            episode=data["episode"],
            title=data["title"],
            chapters=data["chapters"],
            source_ids=data["source_ids"],
            chapter_titles=data.get("chapter_titles", []),
            status=ChunkStatus(data.get("status", "pending")),
            artifacts=artifacts,
        )


@dataclass
class SyllabusState:
    """Root state object for the syllabus workflow."""

    notebook_id: str
    book_name: str
    created: str
    max_chapters: int
    generate_audio: bool
    generate_video: bool
    chunks: dict[int, SyllabusChunk]

    def to_json(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "book_name": self.book_name,
            "created": self.created,
            "max_chapters": self.max_chapters,
            "generate_audio": self.generate_audio,
            "generate_video": self.generate_video,
            "chunks": [chunk.to_json() for chunk in self.chunks.values()],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SyllabusState:
        """Load state from parsed JSON with structural validation.

        Raises:
            SyllabusStateError: If required fields are missing or malformed.
        """
        try:
            chunks_list = [SyllabusChunk.from_json(c) for c in data["chunks"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SyllabusStateError(f"Corrupt state file: {exc}") from exc

        try:
            return cls(
                notebook_id=data["notebook_id"],
                book_name=data["book_name"],
                created=data.get("created", ""),
                max_chapters=data.get("max_chapters", 2),
                generate_audio=data.get("generate_audio", True),
                generate_video=data.get("generate_video", True),
                chunks={c.episode: c for c in chunks_list},
            )
        except KeyError as exc:
            raise SyllabusStateError(f"Missing required field: {exc}") from exc


def build_prompt(sources: list[tuple[str, str]], max_chapters: int) -> str:
    """Build the syllabus generation prompt with numbered source titles.

    Args:
        sources: List of (source_id, title) tuples, in chapter order.
        max_chapters: Maximum chapters per episode.

    Returns:
        Formatted prompt string.
    """
    source_list = "\n".join(f"{i}. {title}" for i, (_, title) in enumerate(sources, 1))
    return SYLLABUS_PROMPT_TEMPLATE.format(source_list=source_list, max_chapters=max_chapters)


def parse_syllabus_response(
    response: str,
    source_map: dict[int, str],
    title_map: dict[int, str] | None = None,
) -> dict[int, SyllabusChunk]:
    """Parse LLM syllabus response into chunks.

    Uses binary success/fallback: if all chapters are covered by the
    parsed episodes, accept. Otherwise raise SyllabusParseError.

    Args:
        response: Raw LLM response text.
        source_map: Mapping of chapter_number -> source_id.
        title_map: Mapping of chapter_number -> source title.

    Returns:
        Dict of episode_number -> SyllabusChunk.

    Raises:
        SyllabusParseError: If the response cannot be fully parsed.
    """
    logger.debug("Raw syllabus response: %s", response)
    title_map = title_map or {}

    matches = _EPISODE_RE.findall(response)
    if not matches:
        raise SyllabusParseError("No episodes found in LLM response")

    all_chapter_nums = set(source_map.keys())
    chunks: dict[int, SyllabusChunk] = {}
    assigned_chapters: set[int] = set()

    for ep_str, title, chapters_str, *_ in matches:
        episode = int(ep_str)
        chapter_nums = [int(c.strip()) for c in chapters_str.split(",") if c.strip()]
        source_ids = [source_map[c] for c in chapter_nums if c in source_map]
        chapter_titles = [title_map[c] for c in chapter_nums if c in title_map]
        assigned_chapters.update(chapter_nums)

        chunks[episode] = SyllabusChunk(
            episode=episode,
            title=title.strip(),
            chapters=chapter_nums,
            source_ids=source_ids,
            chapter_titles=chapter_titles,
        )

    missing = all_chapter_nums - assigned_chapters
    if missing:
        raise SyllabusParseError(f"Chapters {sorted(missing)} not assigned to any episode")

    return chunks


def build_fixed_size_chunks(
    source_map: dict[int, str],
    max_chapters: int,
    title_map: dict[int, str] | None = None,
) -> dict[int, SyllabusChunk]:
    """Build fixed-size chapter chunks as a fallback.

    Args:
        source_map: Mapping of chapter_number -> source_id.
        max_chapters: Maximum chapters per chunk.
        title_map: Mapping of chapter_number -> source title.

    Returns:
        Dict of episode_number -> SyllabusChunk.

    Raises:
        ValueError: If max_chapters < 1 or source_map is empty.
    """
    if max_chapters < 1:
        raise ValueError("max_chapters must be >= 1")
    if not source_map:
        raise ValueError("source_map is empty")

    title_map = title_map or {}
    sorted_chapters = sorted(source_map.keys())
    chunks: dict[int, SyllabusChunk] = {}
    episode = 1

    for i in range(0, len(sorted_chapters), max_chapters):
        chapter_nums = sorted_chapters[i : i + max_chapters]
        source_ids = [source_map[c] for c in chapter_nums]
        chapter_titles = [title_map[c] for c in chapter_nums if c in title_map]
        chapter_range = f"{chapter_nums[0]}-{chapter_nums[-1]}"
        chunks[episode] = SyllabusChunk(
            episode=episode,
            title=f"Chapters {chapter_range}",
            chapters=chapter_nums,
            source_ids=source_ids,
            chapter_titles=chapter_titles,
        )
        episode += 1

    return chunks


def map_sources_to_chapters(
    sources: list[tuple[str, str]],
) -> tuple[dict[int, str], dict[int, str]]:
    """Map chapter numbers to source IDs and titles by parsing source titles.

    All-or-nothing: if any source title fails to parse, falls back to
    positional indexing for all sources.

    Args:
        sources: List of (source_id, title) tuples.

    Returns:
        Tuple of (chapter_number -> source_id, chapter_number -> title).
    """
    if not sources:
        return {}, {}

    id_map: dict[int, str] = {}
    title_map: dict[int, str] = {}
    for source_id, title in sources:
        match = _CHAPTER_NUM_RE.search(title or "")
        if not match:
            logger.warning(
                "Cannot parse chapter number from '%s'; using positional fallback",
                title,
            )
            ids = {i + 1: sid for i, (sid, _) in enumerate(sources)}
            titles = {i + 1: t for i, (_, t) in enumerate(sources)}
            return ids, titles
        chapter_num = int(match.group(1))
        id_map[chapter_num] = source_id
        title_map[chapter_num] = title or ""

    return id_map, title_map


def read_state(state_path: Path) -> SyllabusState:
    """Load syllabus state from a JSON file.

    Args:
        state_path: Path to the state file.

    Returns:
        Parsed SyllabusState.

    Raises:
        SyllabusStateError: If the file is missing, corrupt, or invalid.
    """
    if not state_path.is_file():
        raise SyllabusStateError(
            f"No syllabus found at {state_path}. Run 'studyctl content syllabus' first."
        )

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SyllabusStateError(f"Cannot read state file: {exc}") from exc

    return SyllabusState.from_json(data)


def write_state(state: SyllabusState, state_path: Path) -> None:
    """Atomically write syllabus state to a JSON file.

    Uses write-to-temp-then-rename for crash safety.

    Args:
        state: The state to persist.
        state_path: Target file path.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(state.to_json(), indent=2, ensure_ascii=False)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(state_path.parent),
        suffix=".tmp",
        prefix=".syllabus_state_",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(state_path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def get_next_chunk(state: SyllabusState) -> SyllabusChunk | None:
    """Select the next chunk to generate, by priority.

    Priority: GENERATING (resume interrupted) > FAILED (retry) > PENDING (new).

    Args:
        state: Current syllabus state.

    Returns:
        The next chunk to process, or None if all are completed.
    """
    priority = [ChunkStatus.GENERATING, ChunkStatus.FAILED, ChunkStatus.PENDING]
    for target_status in priority:
        for chunk in sorted(state.chunks.values(), key=lambda c: c.episode):
            if chunk.status == target_status:
                return chunk
    return None


def has_non_pending_chunks(state: SyllabusState) -> bool:
    """Check if any chunks have progressed beyond pending."""
    return any(c.status != ChunkStatus.PENDING for c in state.chunks.values())
