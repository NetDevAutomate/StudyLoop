"""Content-generation job orchestrator (U4).

The orchestrator glues together the singleton (U2), scope resolver
(U3), generator factory (U1/U1.5), concurrent runner, and
existing-file policy helpers (U6). It exposes one public function:

    run_job(job_id, request, settings, on_event) -> JobResult

The HTTP layer (U5/U7) calls this from a background asyncio task and
forwards ``on_event`` callbacks to the per-job WS queue. The
orchestrator itself is sync at heart -- httpx + boto3 + the runner
are all sync -- so it runs in a thread executor.

Failure model
-------------

- Per-task failures (one source / one kind raises CardGenerationError)
  do NOT abort the run. The runner already gives us per-task results;
  the orchestrator emits a ``task_complete`` with ``ok=False`` and
  carries on.
- Whole-job failures (scope resolution miss, singleton ill-acquired,
  on-existing policy collision) raise out of ``run_job``. The
  caller turns that into a ``transport_error`` frame and a 4xx if
  it happens before the 202 was returned.
- The HTTP background task releases the singleton on the server event
  loop after ``run_job`` returns or raises.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from studyloop.content.generators import get_generator
from studyloop.content.generators.runner import (
    GenerationResult,
    GenerationTask,
    generate_concurrently,
)
from studyloop.content.schemas import FlashcardDeck, QuizDeck
from studyloop.content.scope import ResolvedSource, ScopeRequest, resolve_scope

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from studyloop.settings import Settings


logger = logging.getLogger(__name__)


OnExisting = Literal["overwrite", "merge", "suffix"]
DeckKind = Literal["flashcards", "quizzes"]


@dataclass(frozen=True, slots=True)
class JobRequest:
    """Validated inputs the orchestrator needs.

    The HTTP layer (U5) builds this from its pydantic ``GenerateRequest``
    -- keeping the orchestrator's request type framework-free means
    the same orchestrator is reusable from a future CLI command.
    """

    course: str
    scope: ScopeRequest
    kinds: tuple[DeckKind, ...]
    publisher: str = ""  # study-tree top level; empty = legacy flat layout
    count_per_source: int | None = None
    on_existing: OnExisting = "suffix"
    backend: str = ""  # empty = use settings.card_generator.backend
    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """One source x one deck-kind result."""

    identifier: str
    kind: DeckKind
    ok: bool
    elapsed_s: float
    path: str | None = None  # set when ok=True
    error: str | None = None  # set when ok=False


@dataclass(frozen=True, slots=True)
class JobResult:
    """Aggregate result returned from ``run_job``."""

    job_id: str
    written: int
    failed: int
    outcomes: list[TaskOutcome]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_job(
    job_id: str,
    request: JobRequest,
    settings: Settings,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> JobResult:
    """Execute one generation job synchronously.

    Args:
        job_id: Caller-assigned job id, echoed in events.
        request: Validated job inputs.
        settings: Loaded studyloop settings.
        on_event: Optional callback invoked once per event:
            ``{"type": "started", ...}``, ``{"type": "task_complete", ...}``,
            ``{"type": "all_done", ...}``. Exceptions raised by this
            callback are caught and logged so a noisy WS consumer
            can't break the job.

    Returns:
        Aggregate :class:`JobResult` once all tasks complete.

    Raises:
        ScopeResolutionError: scope didn't resolve to ≥1 source.
        ValueError: invalid backend / provider / model selection.
        CardGenerationError: generator construction failed (e.g.
            missing API key) before any task ran.

    Note: the singleton is acquired and released by the *caller* (REST
    handler/background task in U5) so a 409 can be returned synchronously
    before the job task spawns, and release happens on the server event loop.
    """

    def emit(event: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:
            logger.exception("on_event callback raised; continuing")

    # Resolve sources up-front so the user sees "0 sources"
    # before any generator API key cost.
    sources = resolve_scope(request.scope, settings)
    tasks = _build_tasks(sources, request.kinds, request.count_per_source)
    gen_config = _resolve_generator_config(settings, request)
    emit(
        {
            "type": "started",
            "job_id": job_id,
            "task_count": len(tasks),
            "kinds": list(request.kinds),
            "count_per_source": request.count_per_source,
            "backend": gen_config.backend,
            "provider": _progress_provider(gen_config),
            "model": _progress_model(gen_config),
            "sources": [{"identifier": s.identifier, "title": s.title} for s in sources],
        }
    )

    course_dir = _course_output_dir(settings, request.publisher, request.course)

    outcomes: list[TaskOutcome] = []

    def on_complete(result: GenerationResult) -> None:
        outcome = _handle_result(
            result=result,
            course_dir=course_dir,
            on_existing=request.on_existing,
        )
        outcomes.append(outcome)
        emit(
            {
                "type": "task_complete",
                "identifier": outcome.identifier,
                "kind": outcome.kind,
                "ok": outcome.ok,
                "elapsed_s": outcome.elapsed_s,
                "path": outcome.path,
                "error": outcome.error,
            }
        )

    with _maybe_inject_bearer(gen_config):
        generator = get_generator(gen_config)
        try:
            generate_concurrently(
                generator,
                tasks,
                max_workers=gen_config.max_workers,
                on_complete=on_complete,
            )
        finally:
            close = getattr(generator, "close", None)
            if close is not None:
                close()

    # Stable ordering for downstream consumers (tests, audit logs).
    outcomes.sort(key=lambda o: (o.identifier, o.kind))
    written = sum(1 for o in outcomes if o.ok)
    failed = len(outcomes) - written
    emit({"type": "all_done", "job_id": job_id, "written": written, "failed": failed})
    return JobResult(job_id=job_id, written=written, failed=failed, outcomes=outcomes)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_tasks(
    sources: list[ResolvedSource], kinds: tuple[DeckKind, ...], count_per_source: int | None
) -> list[GenerationTask]:
    """Cross-product sources x kinds into runner tasks."""
    tasks: list[GenerationTask] = []
    for src in sources:
        if "flashcards" in kinds:
            tasks.append(
                GenerationTask(
                    identifier=src.identifier,
                    kind="flashcards",
                    source=src.markdown_text,
                    title=src.title,
                    count=count_per_source,
                )
            )
        if "quizzes" in kinds:
            tasks.append(
                GenerationTask(
                    identifier=src.identifier,
                    kind="quiz",
                    source=src.markdown_text,
                    title=src.title,
                    count=count_per_source,
                )
            )
    if not tasks:
        raise ValueError("kinds must include at least one of 'flashcards' or 'quizzes'.")
    return tasks


def _resolve_generator_config(settings: Settings, request: JobRequest):
    """Apply per-request overrides on top of settings.card_generator.

    The request can override backend / provider / model independently.
    Returns a fresh ``CardGeneratorConfig`` so we don't mutate the
    user's settings.
    """
    from dataclasses import replace

    cfg = settings.card_generator
    overrides: dict[str, Any] = {}
    if request.backend:
        overrides["backend"] = request.backend
    if request.provider:
        overrides["provider"] = request.provider
    if request.model:
        overrides["model"] = request.model
    return replace(cfg, **overrides) if overrides else cfg


def _progress_provider(config: Any) -> str:
    """Best-effort provider label for progress frames."""
    provider = getattr(config, "provider", "")
    if provider:
        return provider
    backend = getattr(config, "backend", "")
    if backend in {"ollama", "bedrock", "stub"}:
        return backend
    return ""


def _progress_model(config: Any) -> str:
    """Best-effort model id for progress frames."""
    model = getattr(config, "model", "")
    if model:
        return model
    backend = getattr(config, "backend", "")
    if backend == "ollama":
        return getattr(getattr(config, "ollama", None), "model", "")
    if backend == "bedrock":
        return getattr(getattr(config, "bedrock", None), "model", "")
    provider = getattr(config, "provider", "")
    if backend in {"openai_compat", "anthropic_compat"} and provider:
        return _default_profile_model(provider)
    return ""


def _default_profile_model(provider: str) -> str:
    """Return the registry default model for a provider, or blank if unknown."""
    from studyloop.content.generators.provider_profiles import default_model, get_profile

    try:
        return default_model(get_profile(provider)).id
    except ValueError:
        return ""


@contextlib.contextmanager
def _maybe_inject_bearer(config: Any) -> Iterator[None]:
    """Inject a stored Bedrock bearer token into the env for one generation.

    If the backend is Bedrock and a ``bedrock_bearer_token`` secret exists,
    set ``AWS_BEARER_TOKEN_BEDROCK`` for the duration of the generation so
    ``BedrockGenerator`` takes the profile-less bearer path; restore the prior
    value afterwards. No-op for other backends or when no token is stored.

    Mutates process-global ``os.environ`` — safe here because StudyLoop runs
    one active generation at a time (the active_gen singleton).
    """
    if getattr(config, "backend", "") != "bedrock":
        yield
        return

    from studyloop.secrets import get_secret

    token = get_secret("bedrock_bearer_token")
    if not token:
        yield
        return

    key = "AWS_BEARER_TOKEN_BEDROCK"
    previous = os.environ.get(key)
    os.environ[key] = token
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _course_output_dir(settings: Settings, publisher: str, course: str) -> Path:
    """Resolve the on-disk output dir for ``publisher``/``course``.

    The tree is 3-level (``base/<publisher>/<course>/``), so decks must land
    under the course dir — NOT ``base/<publisher>/`` (the prior bug, which
    wrote every publisher's decks into one shared flashcards/ dir). When
    ``publisher`` is empty (legacy flat layout) the output dir is
    ``base/<course>/`` as before.

    We DO NOT re-slugify the names: they come from the on-disk directory
    listing (auto-discovered), so they are already valid filesystem names —
    slugifying would lowercase "DataCamp" to "datacamp" and create a
    parallel tree on case-sensitive filesystems.
    """
    from pathlib import Path

    from studyloop.content.storage import get_course_dir

    base = Path(settings.content.base_path)
    parent = base / publisher if publisher else base
    return get_course_dir(parent, course)


def _handle_result(
    *,
    result: GenerationResult,
    course_dir: Path,
    on_existing: OnExisting,
) -> TaskOutcome:
    """Translate one runner result into a written file + outcome record."""
    task = result.task
    if not result.ok or result.deck is None:
        err = str(result.error) if result.error else "no deck returned"
        return TaskOutcome(
            identifier=task.identifier,
            kind=_normalise_kind(task.kind),
            ok=False,
            elapsed_s=result.elapsed_s,
            error=err,
        )

    target_dir = course_dir / ("flashcards" if task.kind == "flashcards" else "quizzes")
    # ``write_json`` itself appends the kind-specific tail
    # (-flashcards.json / -quiz.json), so we only manage the IDENTIFIER
    # part here. The ``stem_suffix`` carries the kind tail for
    # next_unique_path's collision check.
    stem_suffix = "-flashcards.json" if task.kind == "flashcards" else "-quiz.json"
    stem = task.identifier
    base_path = target_dir / f"{stem}{stem_suffix}"

    try:
        write_path = _write_with_policy(
            deck=result.deck,
            base_path=base_path,
            target_dir=target_dir,
            stem=stem,
            stem_suffix=stem_suffix,
            on_existing=on_existing,
        )
    except Exception as exc:
        return TaskOutcome(
            identifier=task.identifier,
            kind=_normalise_kind(task.kind),
            ok=False,
            elapsed_s=result.elapsed_s,
            error=f"write failed: {exc!r}",
        )

    return TaskOutcome(
        identifier=task.identifier,
        kind=_normalise_kind(task.kind),
        ok=True,
        elapsed_s=result.elapsed_s,
        path=str(write_path),
    )


def _write_with_policy(
    *,
    deck: FlashcardDeck | QuizDeck,
    base_path: Path,
    target_dir: Path,
    stem: str,
    stem_suffix: str,
    on_existing: OnExisting,
) -> Path:
    """Apply on_existing policy and write the deck to disk.

    ``base_path`` = ``target_dir/<stem><stem_suffix>``; we either
    overwrite that, merge with it, or pick the next free path with an
    incremented integer between stem and stem_suffix.
    """
    if on_existing == "overwrite" or not base_path.exists():
        return deck.write_json(target_dir, stem)

    if on_existing == "suffix":
        # Find the next free <stem>-N<stem_suffix>. write_json's tail
        # is fixed, so we can't reuse next_unique_path -- the increment
        # has to land between stem and the kind tail.
        new_stem = _next_unique_stem(target_dir, stem, stem_suffix)
        return deck.write_json(target_dir, new_stem)

    if on_existing == "merge":
        return _merge_into_existing(deck, base_path, target_dir, stem)

    raise ValueError(f"Unknown on_existing policy: {on_existing!r}")


def _next_unique_stem(target_dir: Path, stem: str, stem_suffix: str) -> str:
    """Return ``<stem>-N`` such that ``<stem>-N<stem_suffix>`` is free.

    Used by the suffix on-existing policy. Caller passes the kind tail
    as ``stem_suffix`` (e.g. ``"-flashcards.json"``); we try
    ``stem-1``, ``stem-2``, ... until ``target_dir / f"{candidate}{stem_suffix}"``
    doesn't exist. 9999 ceiling matches ``next_unique_path`` for
    consistency.
    """
    for n in range(1, 10000):
        candidate = f"{stem}-{n}"
        if not (target_dir / f"{candidate}{stem_suffix}").exists():
            return candidate
    raise RuntimeError(f"_next_unique_stem exhausted 9999 attempts for {target_dir}/{stem}")


def _merge_into_existing(
    deck: FlashcardDeck | QuizDeck, base_path: Path, target_dir: Path, stem: str
) -> Path:
    """Load the existing deck file, merge_dedupe with ``deck``, write back."""
    raw = json.loads(base_path.read_text(encoding="utf-8"))
    if isinstance(deck, FlashcardDeck):
        existing = FlashcardDeck.model_validate(raw)
        merged = deck.merge_dedupe(existing)
    else:
        existing = QuizDeck.model_validate(raw)
        merged = deck.merge_dedupe(existing)
    return merged.write_json(target_dir, stem)


def _normalise_kind(runner_kind: str) -> DeckKind:
    """Map runner's ``"quiz"`` to the panel's ``"quizzes"``.

    The runner uses singular ``"quiz"`` (matches its ``GenerationTask``
    Literal) but the panel API uses plural ``"quizzes"`` for parity
    with the sidebar tab name. The mapping is one-line and lives here
    rather than spreading the inconsistency across the orchestrator.
    """
    if runner_kind == "quiz":
        return "quizzes"
    return "flashcards"


__all__ = [
    "DeckKind",
    "JobRequest",
    "JobResult",
    "OnExisting",
    "TaskOutcome",
    "run_job",
]
