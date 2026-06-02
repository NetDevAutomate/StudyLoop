"""Content-generation HTTP routes (U5 + U7 + U10.5).

Exposes the orchestrator (``content/job.py``) over HTTP+WS:

- ``POST /api/content/generate``         → 202 + ``job_id`` (U5)
- ``WS   /api/content/generate/ws``      → progress frames    (U7)
- ``GET  /api/content/providers``        → registry availability (U10.5)

The REST handler validates inputs, acquires the active-generation
singleton, spawns a background asyncio task that runs the orchestrator
in a thread executor, and pushes events into a per-``job_id``
:class:`asyncio.Queue`. The WS handler subscribes to that queue and
forwards JSON frames to the browser client.

Design notes
------------

- **One queue per job, not a shared bus.** Cheaper than a pub/sub for
  the v1 single-generation invariant, and lets the WS handler drop
  cleanly when the queue is exhausted.
- **Singleton acquired in the REST handler, released by the background
  task's async ``finally``.** The 409 path never spawns a task and
  never touches the queue, so clean-up is symmetric: every successful
  202 is followed by exactly one ``release()``.
- **The 202 response includes the resolved sources.** The orchestrator
  resolves scope first thing; we mirror that resolution synchronously
  in the REST handler so the form sees ``"this scope resolved to N
  sources"`` before the WS opens. Any scope error becomes a 4xx
  immediately, no spawn cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from studyloop.content import active_gen
from studyloop.content.job import JobRequest, run_job
from studyloop.content.scope import (
    ResolvedSource,
    ScopeRequest,
    ScopeResolutionError,
    resolve_scope,
)

# Module-level so the providers route can OR the encrypted store into its
# availability flag. Named import (not `import studyloop.secrets`) avoids the
# clash with the stdlib `secrets` module already imported above for token_hex.

if TYPE_CHECKING:
    from studyloop.settings import Settings


from studyloop.web.routes.content_gen._router import router

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-job event queues
# ---------------------------------------------------------------------------
#
# Module-level dict is fine for a single-process, single-generation
# server. Each entry is created when the REST handler accepts a job
# and removed by the WS handler once the consumer drains all frames.
# Bounded queue (``maxsize=256``) caps memory if a WS client never
# connects -- the orchestrator backs off on full queues by dropping the
# oldest frame, so a job is never blocked on a non-consuming subscriber.

_JOB_QUEUES: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_JOB_QUEUE_MAX = 256

# Strong references to in-flight background job tasks. Without this, the event
# loop only holds a weak reference and may garbage-collect a running task
# mid-flight (see RUF006). Tasks remove themselves on completion.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _get_or_create_queue(job_id: str) -> asyncio.Queue[dict[str, Any]]:
    queue = _JOB_QUEUES.get(job_id)
    if queue is None:
        queue = asyncio.Queue(maxsize=_JOB_QUEUE_MAX)
        _JOB_QUEUES[job_id] = queue
    return queue


def _drop_queue(job_id: str) -> None:
    """Remove a job's queue (called by the WS handler after drain)."""
    _JOB_QUEUES.pop(job_id, None)


# ---------------------------------------------------------------------------
# Pydantic models — wire shape for POST body / response
# ---------------------------------------------------------------------------


class _ScopeBody(BaseModel):
    """Inbound ``scope`` sub-object on the generate request.

    ``publisher`` is the study-tree top level (e.g. "CodeWithMosh"); ``course``
    the level below it (e.g. "Complete_SQL_Mastery"); ``section`` an individual
    lesson file within the course. ``publisher`` is optional for the legacy
    flat layout (courses directly under ``content.base_path``).
    """

    kind: Literal["course", "section", "topic_struggles"]
    publisher: str = ""
    course: str
    section: str = ""
    topic_slug: str = ""
    window_days: int = 14


class GenerateRequest(BaseModel):
    """Validated body of ``POST /api/content/generate``.

    Mirrors the contract documented in the plan. Field-level validation
    is intentionally light here -- the heavy "does this section exist"
    checks happen in the scope resolver, where the disk is the truth.
    """

    publisher: str = ""
    course: str
    scope: _ScopeBody
    kinds: list[Literal["flashcards", "quizzes"]] = Field(min_length=1)
    count_per_source: Literal[5, 10, 15, 20, 25, 50] = 10
    on_existing: Literal["overwrite", "merge", "suffix"] = "merge"
    backend: str = ""
    provider: str = ""
    model: str = ""


class _ResolvedSourceOut(BaseModel):
    identifier: str
    title: str


class _PlanOut(BaseModel):
    sources: list[_ResolvedSourceOut]
    task_count: int
    kinds: list[str]
    backend: str


class GenerateResponse(BaseModel):
    """Body returned with the 202 status."""

    job_id: str
    plan: _PlanOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_job_id() -> str:
    """Caller-friendly opaque id, e.g. ``"gen-7c3f1a8b"``."""
    return f"gen-{secrets.token_hex(4)}"


def _build_job_request(req: GenerateRequest) -> JobRequest:
    """Translate the wire-shape pydantic model to the orchestrator's dataclass."""
    # publisher may arrive at the top level or on the scope object; prefer
    # the scope's value, falling back to the request-level one.
    publisher = req.scope.publisher or req.publisher
    return JobRequest(
        publisher=publisher,
        course=req.course,
        scope=ScopeRequest(
            kind=req.scope.kind,
            publisher=publisher,
            course=req.scope.course,
            section=req.scope.section,
            topic_slug=req.scope.topic_slug,
            window_days=req.scope.window_days,
        ),
        kinds=tuple(req.kinds),
        count_per_source=req.count_per_source,
        on_existing=req.on_existing,
        backend=req.backend,
        provider=req.provider,
        model=req.model,
    )


def _resolved_backend(settings: Settings, req: GenerateRequest) -> str:
    """Return the backend the orchestrator will actually use.

    The request may override; otherwise we surface the configured
    default so the 202 response is honest about what's running.
    """
    return req.backend or settings.card_generator.backend


def _expected_task_count(sources: list[ResolvedSource], kinds: list[str]) -> int:
    """Sources x kinds = expected runner tasks. Used in the 202 plan summary."""
    return len(sources) * len(kinds)


# ---------------------------------------------------------------------------
# Background runner — bridges the sync orchestrator to the asyncio queue
# ---------------------------------------------------------------------------


async def _run_job_background(
    job_id: str,
    job_req: JobRequest,
    settings: Settings,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Run the orchestrator in a thread and forward its events to the queue.

    The orchestrator is sync (httpx + boto3 + the runner's
    ThreadPoolExecutor are all sync). We hop to a thread via
    ``asyncio.to_thread`` and bridge ordered ``on_event`` callbacks back
    to the asyncio queue with ``loop.call_soon_threadsafe``.
    """
    loop = asyncio.get_running_loop()

    def enqueue(event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            queue.put_nowait(event)

    def push(event: dict[str, Any]) -> None:
        # Called from the thread executor. ``call_soon_threadsafe`` preserves
        # callback ordering, so the WS sees the orchestrator's event order.
        try:
            loop.call_soon_threadsafe(enqueue, event)
        except RuntimeError:
            # Loop closed -- swallow, job is shutting down anyway.
            logger.debug("queue push after loop close, dropping event")

    try:
        await asyncio.to_thread(run_job, job_id, job_req, settings, push)
    except ScopeResolutionError as exc:
        # Shouldn't reach here because we resolve up-front in the REST
        # handler -- but the orchestrator re-resolves so we cover both
        # paths defensively.
        await queue.put({"type": "transport_error", "message": str(exc)})
    except Exception as exc:
        logger.exception("job %s failed unexpectedly", job_id)
        await queue.put({"type": "transport_error", "message": repr(exc)})
    finally:
        await active_gen.release()


# ---------------------------------------------------------------------------
# REST endpoint
# ---------------------------------------------------------------------------


@router.post("/content/generate", status_code=202)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """Kick off a generation job; return ``job_id`` and the resolved plan.

    Status codes:

    - **202** — job accepted, ``job_id`` returned. Subscribe via WS.
    - **400** — invalid scope (missing section, bad window, etc.).
    - **404** — scope resolved to zero sources (e.g. no struggling
      topics in the window).
    - **409** — another generation is in flight; only one at a time.
    """
    from studyloop.settings import load_settings

    settings = load_settings()

    # 1. Resolve scope synchronously so we can fail fast and feed the
    #    "plan" summary back to the form. The orchestrator will resolve
    #    again at run-time -- duplicate cost is cheap (filesystem walk
    #    or a single SELECT) and the second resolve is the source of
    #    truth for the actual generation.
    job_req = _build_job_request(req)
    try:
        sources = resolve_scope(job_req.scope, settings)
    except ScopeResolutionError as exc:
        # 404 if there's "no data here"; 400 if the request was
        # ill-formed (bad section name, out-of-range window).
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    # 2. Acquire the singleton. 409 if someone else is already running.
    job_id = _new_job_id()
    try:
        await active_gen.acquire(job_id=job_id, request=req)
    except active_gen.GenerationAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # 3. Spawn the background task. The orchestrator releases the
    #    singleton in its ``finally`` -- we don't need to here.
    queue = _get_or_create_queue(job_id)
    job_req = _build_job_request(req)
    task = asyncio.create_task(
        _run_job_background(job_id, job_req, settings, queue),
        name=f"content-gen-{job_id}",
    )
    # Hold a strong reference until the task finishes so the event loop does
    # not GC it mid-flight (RUF006), then drop it to avoid unbounded growth.
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return GenerateResponse(
        job_id=job_id,
        plan=_PlanOut(
            sources=[_ResolvedSourceOut(identifier=s.identifier, title=s.title) for s in sources],
            task_count=_expected_task_count(sources, list(req.kinds)),
            kinds=list(req.kinds),
            backend=_resolved_backend(settings, req),
        ),
    )
