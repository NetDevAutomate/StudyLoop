"""File-first persistence for exercise sets.

Mirrors :mod:`studyloop.planning.store`: Markdown documents on disk are the
source of truth, so exercises stay git-diffable and hand-editable, and losing the
sessions DB never loses an exercise.

Directory resolution order:

1. ``STUDYLOOP_EXERCISES_DIR`` environment variable.
2. ``<plans_dir>/exercises`` — kept beside the plans they belong to.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .markdown import parse_exercise_set, render_exercise_set
from .models import ExerciseSet, utc_now_iso

logger = logging.getLogger(__name__)

EXERCISES_DIR_ENV = "STUDYLOOP_EXERCISES_DIR"

#: Rejects path traversal and separators before touching the disk.
_SAFE_ID_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,159}\Z")


class ExerciseSetNotFoundError(LookupError):
    """Raised when a set id does not resolve to a document on disk."""


class ExerciseSetExistsError(FileExistsError):
    """Raised when creating a set whose id is already taken."""


class InvalidSetIdError(ValueError):
    """Raised when a set id could contain a path traversal."""


def exercises_dir() -> Path:
    """Return the directory holding exercise documents (created lazily)."""
    override = os.environ.get(EXERCISES_DIR_ENV, "").strip()
    if override:
        base = Path(override).expanduser()
    else:
        try:
            from ..store import plans_dir

            base = plans_dir() / "exercises"
        except Exception:  # pragma: no cover - settings should always load
            logger.warning("Falling back to default exercises dir; settings unavailable")
            base = Path.home() / ".local" / "share" / "studyloop" / "study-plans" / "exercises"
    base.mkdir(parents=True, exist_ok=True)
    return base


def validate_set_id(set_id: str) -> str:
    """Return a normalised set id, or raise :class:`InvalidSetIdError`."""
    cleaned = (set_id or "").strip().lower()
    if not _SAFE_ID_RE.match(cleaned) or ".." in cleaned:
        msg = f"invalid exercise set id: {set_id!r}"
        raise InvalidSetIdError(msg)
    return cleaned


def set_path(set_id: str) -> Path:
    """On-disk path for ``set_id`` (no existence check).

    Defence in depth, as in the plan store: a symlink planted inside the
    directory must not let the raw-Markdown endpoint serve an arbitrary file.
    """
    base = exercises_dir()
    candidate = base / f"{validate_set_id(set_id)}.md"
    try:
        resolved_base = base.resolve()
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - broken symlink or unreadable mount
        msg = f"invalid exercise path for id: {set_id!r}"
        raise InvalidSetIdError(msg) from None
    if resolved != resolved_base / candidate.name and resolved.parent != resolved_base:
        msg = f"exercise set id {set_id!r} resolves outside the exercises directory"
        raise InvalidSetIdError(msg)
    return candidate


def list_set_ids() -> list[str]:
    """Every exercise set id on disk, alphabetically."""
    return sorted(p.stem for p in exercises_dir().glob("*.md") if p.is_file())


def load_set(set_id: str) -> ExerciseSet:
    """Load and parse one exercise set."""
    path = set_path(set_id)
    if not path.is_file():
        msg = f"no exercise set with id {set_id!r}"
        raise ExerciseSetNotFoundError(msg)
    return parse_exercise_set(path.read_text(encoding="utf-8"), set_id=path.stem)


def load_set_text(set_id: str) -> str:
    """Raw Markdown for one exercise set — the download / copy-to-agent path."""
    path = set_path(set_id)
    if not path.is_file():
        msg = f"no exercise set with id {set_id!r}"
        raise ExerciseSetNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def list_sets(*, plan_id: str = "", topic: str = "") -> list[ExerciseSet]:
    """Load every set, optionally filtered by plan and/or topic.

    One unparseable document is skipped with a warning rather than taking the
    whole listing down.
    """
    out: list[ExerciseSet] = []
    wanted_topic = topic.strip().lower()
    for set_id in list_set_ids():
        try:
            item = load_set(set_id)
        except Exception:
            logger.warning("Skipping unparseable exercise set: %s", set_id, exc_info=True)
            continue
        if plan_id and item.plan_id != plan_id:
            continue
        if wanted_topic and item.topic.strip().lower() != wanted_topic:
            continue
        out.append(item)
    out.sort(key=lambda s: (s.plan_id, s.topic))
    return out


def save_set(exercise_set: ExerciseSet, *, touch_updated: bool = True) -> Path:
    """Write ``exercise_set`` to disk atomically, returning the path written."""
    exercise_set.set_id = validate_set_id(exercise_set.set_id)
    if touch_updated:
        exercise_set.updated = utc_now_iso()
    path = set_path(exercise_set.set_id)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(render_exercise_set(exercise_set), encoding="utf-8")
    tmp.replace(path)
    return path


def create_set(exercise_set: ExerciseSet, *, overwrite: bool = False) -> Path:
    """Persist a new set, refusing to clobber an existing id unless told to."""
    exercise_set.set_id = validate_set_id(exercise_set.set_id)
    if not overwrite and set_path(exercise_set.set_id).exists():
        msg = f"exercise set {exercise_set.set_id!r} already exists"
        raise ExerciseSetExistsError(msg)
    return save_set(exercise_set, touch_updated=False)


def delete_set(set_id: str) -> bool:
    """Delete a set document. False when it was already absent."""
    path = set_path(set_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def unique_set_id(plan_id: str, topic: str) -> str:
    """A free set id derived from plan + topic (``-2``, ``-3``… on clash)."""
    from ..models import slugify

    base = slugify(f"{plan_id}--{topic}" if plan_id else topic)
    candidate = base
    counter = 2
    while set_path(candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate
