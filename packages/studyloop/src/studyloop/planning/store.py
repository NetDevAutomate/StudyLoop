"""File-first persistence for study plans.

Plans live as Markdown documents in a single directory so they stay
git-diffable, hand-editable, and readable without StudyLoop running.  The
sessions DB holds only a derived index (see :mod:`studyloop.planning.index`),
which means a lost DB never loses a plan.

Directory resolution order:

1. ``STUDYLOOP_PLANS_DIR`` environment variable (used by tests and by
   ``studyloop plan --dir``).
2. ``<settings.state_dir>/study-plans``.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .markdown import parse_plan, render_plan
from .models import LearningRecord, StudyPlan, slugify, utc_now_iso

logger = logging.getLogger(__name__)

PLANS_DIR_ENV = "STUDYLOOP_PLANS_DIR"

#: Rejects path traversal and separators in plan ids before touching the disk.
_SAFE_ID_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,119}\Z")


class PlanNotFoundError(LookupError):
    """Raised when a plan id does not resolve to a document on disk."""


class PlanExistsError(FileExistsError):
    """Raised when creating a plan whose id is already taken."""


class InvalidPlanIdError(ValueError):
    """Raised when a plan id could contain a path traversal."""


def plans_dir() -> Path:
    """Return the directory holding plan Markdown documents (created lazily)."""
    override = os.environ.get(PLANS_DIR_ENV, "").strip()
    if override:
        base = Path(override).expanduser()
    else:
        try:
            from studyloop.settings import load_settings

            base = Path(load_settings().state_dir).expanduser() / "study-plans"
        except Exception:  # pragma: no cover - settings should always load
            logger.warning("Falling back to default plans dir; settings unavailable")
            base = Path.home() / ".local" / "share" / "studyloop" / "study-plans"
    base.mkdir(parents=True, exist_ok=True)
    return base


def validate_plan_id(plan_id: str) -> str:
    """Return a normalised plan id, or raise :class:`InvalidPlanIdError`.

    Guards the filesystem boundary: ``..``, ``/`` and absolute paths are all
    rejected rather than sanitised, so a caller never silently reads or writes
    outside the plans directory.
    """
    cleaned = (plan_id or "").strip().lower()
    if not _SAFE_ID_RE.match(cleaned) or ".." in cleaned:
        msg = f"invalid plan id: {plan_id!r}"
        raise InvalidPlanIdError(msg)
    return cleaned


def plan_path(plan_id: str) -> Path:
    """Return the on-disk path for ``plan_id`` (no existence check).

    Defence in depth: ``validate_plan_id`` already rejects separators and ``..``,
    but a *symlink* planted inside the plans directory could still point outside
    it — which would let ``/api/plans/{id}/markdown`` serve an arbitrary file.
    So the resolved path is also required to stay within the resolved plans
    directory. Requires local write access to exploit, hence a guard rather than
    an active vulnerability.
    """
    base = plans_dir()
    candidate = base / f"{validate_plan_id(plan_id)}.md"
    try:
        resolved_base = base.resolve()
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - broken symlink or unreadable mount
        msg = f"invalid plan path for id: {plan_id!r}"
        raise InvalidPlanIdError(msg) from None
    if resolved != resolved_base / candidate.name and resolved.parent != resolved_base:
        msg = f"plan id {plan_id!r} resolves outside the plans directory"
        raise InvalidPlanIdError(msg)
    return candidate


def list_plan_ids() -> list[str]:
    """Return every plan id present on disk, alphabetically."""
    return sorted(p.stem for p in plans_dir().glob("*.md") if p.is_file())


def load_plan(plan_id: str) -> StudyPlan:
    """Load and parse one plan. Raises :class:`PlanNotFoundError` if absent."""
    path = plan_path(plan_id)
    if not path.is_file():
        msg = f"no study plan with id {plan_id!r}"
        raise PlanNotFoundError(msg)
    return parse_plan(path.read_text(encoding="utf-8"), plan_id=path.stem)


def load_plan_text(plan_id: str) -> str:
    """Return the raw Markdown for one plan — what the web UI renders."""
    path = plan_path(plan_id)
    if not path.is_file():
        msg = f"no study plan with id {plan_id!r}"
        raise PlanNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def list_plans(*, status: str = "") -> list[StudyPlan]:
    """Load every plan, optionally filtered by status.

    A plan that fails to parse is skipped with a warning rather than taking the
    whole listing down — one malformed document must not hide the others.
    """
    out: list[StudyPlan] = []
    for plan_id in list_plan_ids():
        try:
            plan = load_plan(plan_id)
        except Exception:
            logger.warning("Skipping unparseable study plan: %s", plan_id, exc_info=True)
            continue
        if status and plan.status != status:
            continue
        out.append(plan)
    # Active plans first, then most recently updated.
    out.sort(key=lambda p: (p.status != "active", p.updated), reverse=False)
    return out


def save_plan(plan: StudyPlan, *, touch_updated: bool = True) -> Path:
    """Write ``plan`` to disk atomically, returning the path written.

    The write goes to a temp file in the same directory and is then renamed, so
    a crash mid-write cannot truncate an existing plan.
    """
    plan.plan_id = validate_plan_id(plan.plan_id)
    if touch_updated:
        plan.updated = utc_now_iso()
    path = plan_path(plan.plan_id)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(render_plan(plan), encoding="utf-8")
    tmp.replace(path)

    try:
        from .index import index_plan

        index_plan(plan)
    except Exception:
        # The Markdown file is the source of truth; a failed index refresh is
        # recoverable via `studyloop plan reindex` and must not fail the save.
        logger.debug("Plan index refresh failed for %s", plan.plan_id, exc_info=True)
    return path


def create_plan(plan: StudyPlan, *, overwrite: bool = False) -> Path:
    """Persist a new plan, refusing to clobber an existing id unless told to."""
    plan.plan_id = validate_plan_id(plan.plan_id or slugify(plan.title))
    if not overwrite and plan_path(plan.plan_id).exists():
        msg = f"study plan {plan.plan_id!r} already exists"
        raise PlanExistsError(msg)
    return save_plan(plan, touch_updated=False)


def delete_plan(plan_id: str) -> bool:
    """Delete a plan document. Returns False when it was already absent."""
    path = plan_path(plan_id)
    if not path.is_file():
        return False
    path.unlink()
    try:
        from .index import forget_plan

        forget_plan(plan_id)
    except Exception:
        logger.debug("Plan index cleanup failed for %s", plan_id, exc_info=True)
    return True


def unique_plan_id(title: str) -> str:
    """Return a free plan id derived from ``title`` (``-2``, ``-3``… on clash)."""
    base = slugify(title)
    candidate = base
    counter = 2
    while plan_path(candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def record_learning(
    plan_id: str,
    title: str,
    *,
    body: str = "",
    status: str = "active",
) -> tuple[LearningRecord, bool]:
    """Append a learning record to ``plan_id``. Returns ``(record, created)``.

    The R-93 writer: before this, :class:`LearningRecord` was constructed in
    exactly one place — the Markdown parser — so a record existed only if the
    learner typed it into the plan document by hand, and an xTiles wind-down's
    learning record lived only in xTiles (inverting ADR-0010).

    Parse → append → :func:`save_plan`, never an append of raw Markdown:
    ``save_plan`` re-renders the whole document through ``render_plan``, so the
    on-disk shape cannot drift from the renderer that the projection and
    template guards already pin (``### LR-0004 — Title`` is the renderer's
    business, not this function's).

    Idempotent the same way the vault writer is: re-recording an existing
    record (same title and body, case-preserved, whitespace-trimmed the way the
    parser trims) is a no-op that returns ``(existing, False)`` and leaves the
    file's bytes untouched. Numbering is ``max(existing) + 1`` so records can
    cite each other and be superseded rather than renumbered.

    Raises :class:`PlanNotFoundError` / :class:`InvalidPlanIdError` from the
    load, and :class:`ValueError` for an empty title.
    """
    title = title.strip()
    if not title:
        msg = "a learning record needs a title"
        raise ValueError(msg)
    body = body.strip()
    # H1-H3 lines in a body would be re-parsed as new sections or new records
    # on the next load (_split_sections / _subsection_items split on them, and
    # _subsection_items does not honour code fences), silently corrupting the
    # document's structure. Refuse rather than mangle; H4+ is safe prose.
    for line in body.splitlines():
        if re.match(r"\A#{1,3}\s", line.strip()):
            msg = (
                "a learning record body cannot contain #, ## or ### headings "
                f"(found {line.strip()!r}); use #### or deeper, or plain prose"
            )
            raise ValueError(msg)
    status = status.strip() or "active"

    plan = load_plan(plan_id)
    for existing in plan.learning_records:
        if existing.title == title and existing.body == body:
            return existing, False

    record = LearningRecord(
        number=max((r.number for r in plan.learning_records), default=0) + 1,
        title=title,
        body=body,
        status=status,
    )
    plan.learning_records.append(record)
    save_plan(plan)
    return record, True
