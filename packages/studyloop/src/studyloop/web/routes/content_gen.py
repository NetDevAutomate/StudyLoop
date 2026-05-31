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
- **Singleton acquired in the REST handler, released in the
  orchestrator's ``finally``.** The 409 path never spawns a task and
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
import logging
import secrets
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from studyloop.content import active_gen
from studyloop.content.job import JobRequest, run_job
# Module-level so the providers route can OR the encrypted store into its
# availability flag. Named import (not `import studyloop.secrets`) avoids the
# clash with the stdlib `secrets` module already imported above for token_hex.
from studyloop.secrets import get_secret
from studyloop.content.scope import (
    ResolvedSource,
    ScopeRequest,
    ScopeResolutionError,
    resolve_scope,
)

if TYPE_CHECKING:
    from studyloop.settings import Settings


logger = logging.getLogger(__name__)
router = APIRouter()


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
    """Sources × kinds = expected runner tasks. Used in the 202 plan summary."""
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
    ``asyncio.to_thread`` and bridge ``on_event`` callbacks back to the
    asyncio queue with ``run_coroutine_threadsafe``.
    """
    loop = asyncio.get_running_loop()

    def push(event: dict[str, Any]) -> None:
        # Called from the thread executor. ``run_coroutine_threadsafe``
        # is the canonical bridge; we don't await the result -- the
        # queue is fire-and-forget from the orchestrator's perspective.
        try:
            asyncio.run_coroutine_threadsafe(queue.put(event), loop)
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
    except Exception as exc:  # noqa: BLE001 -- forward then close
        logger.exception("job %s failed unexpectedly", job_id)
        await queue.put({"type": "transport_error", "message": repr(exc)})


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
    asyncio.create_task(
        _run_job_background(job_id, job_req, settings, queue),
        name=f"content-gen-{job_id}",
    )

    return GenerateResponse(
        job_id=job_id,
        plan=_PlanOut(
            sources=[_ResolvedSourceOut(identifier=s.identifier, title=s.title) for s in sources],
            task_count=_expected_task_count(sources, list(req.kinds)),
            kinds=list(req.kinds),
            backend=_resolved_backend(settings, req),
        ),
    )


# ---------------------------------------------------------------------------
# Course discovery endpoint (drives the Generate panel's course dropdown)
# ---------------------------------------------------------------------------


def _content_base():
    """Return the expanded content.base_path, or None if it isn't a dir."""
    from pathlib import Path

    from studyloop.settings import load_settings

    base = load_settings().content.base_path
    try:
        base = base.expanduser()
    except AttributeError:
        base = Path(str(base)).expanduser()
    return base if base.is_dir() else None


def _listable_subdirs(parent) -> list[str]:
    """Names of real, non-output, non-dot subdirs under ``parent``, sorted."""
    return [
        c.name
        for c in sorted(parent.iterdir())
        if c.is_dir() and not c.name.startswith(".") and c.name not in {"flashcards", "quizzes"}
    ]


@router.get("/content/publishers")
async def list_content_publishers() -> list[dict[str, Any]]:
    """Return the study-tree top level (publishers) under ``content.base_path``.

    The tree is ``base/<publisher>/<course>/<lesson>.md``. This drives the
    Generate panel's Publisher dropdown (e.g. ArjanCodes, CodeWithMosh,
    Udemy). Courses are fetched per-publisher via ``/content/courses?publisher=``.
    """
    base = _content_base()
    if base is None:
        return []
    return [{"name": name} for name in _listable_subdirs(base)]


@router.get("/content/courses")
async def list_content_courses(publisher: str = "") -> list[dict[str, Any]]:
    """Return source courses for the Generate panel's Course dropdown.

    With ``?publisher=X`` (the normal 3-level case) returns the courses
    under ``base/<publisher>/``. Without it (legacy flat layout) returns
    the top-level dirs under ``base`` directly.

    Distinct from ``/api/courses`` (which lists courses that already have
    flashcards/quizzes JSON for the reviewer): this lists *source* courses
    on disk so a fresh course can appear in the form before any decks exist.
    """
    base = _content_base()
    if base is None:
        return []
    parent = base / publisher if publisher else base
    if not parent.is_dir():
        return []
    return [{"name": name} for name in _listable_subdirs(parent)]


# ---------------------------------------------------------------------------
# Provider list endpoint (U10.5)
# ---------------------------------------------------------------------------


@router.get("/content/providers")
async def list_providers() -> list[dict[str, Any]]:
    """Return the curated provider registry, augmented with availability.

    A provider is **available** if its ``auth_env`` is set in the
    process environment (any non-empty string). The WebUI uses this
    flag to grey out unconfigured providers in the dropdown and show
    "set ``OPENROUTER_API_KEY`` to enable" tooltips.

    Bedrock is a special case: it uses boto3 + AWS credential profiles
    rather than an API-key env var. Its availability is determined by
    whether boto3 can resolve credentials. It is appended after the
    registry entries so the dropdown order is: registry providers first,
    then Bedrock.

    Each entry is a flat object the front-end can render directly --
    no nested adapter detail (the front-end doesn't care which adapter
    handles the wire spec, only which models it can pick).
    """
    import os

    from studyloop.content.generators.provider_profiles import PROFILES
    from studyloop.secrets import get_auth_kind

    out: list[dict[str, Any]] = []
    for slug, profile in PROFILES.items():
        auth_kind = get_auth_kind(slug)

        if slug == "bedrock":
            # Bearer token (encrypted store / env) OR an AWS profile/SigV4 signal.
            available = bool(
                get_secret("bedrock_bearer_token") or _bedrock_credentials_available()
            )
        elif slug == "ollama":
            # Local + keyless: available iff the endpoint responds.
            available = _ollama_reachable(_ollama_base_url())
        else:
            # API-key providers: get_secret already resolves store -> env; the
            # explicit env check is defensive belt-and-braces.
            available = bool(
                get_secret(slug) or os.environ.get(profile.auth_env, "").strip()
            )

        entry: dict[str, Any] = {
            "slug": slug,
            "label": profile.label,
            "adapter": profile.adapter,
            "auth_env": profile.auth_env,
            "auth_kind": auth_kind,
            "available": available,
            "models": [
                {
                    "id": m.id,
                    "label": m.label,
                    "cost_tier": m.cost_tier,
                    "thinking": m.thinking,
                    "notes": m.notes,
                }
                for m in profile.models
            ],
        }
        if slug == "ollama":
            entry["base_url"] = _ollama_base_url()
        out.append(entry)

    return out


def _bedrock_credentials_available() -> bool:
    """Return True if boto3 is importable and AWS credentials are likely present.

    Checks the three most common signals in order of cheapness: env vars
    (no I/O), then a boto3 session resolve attempt. Does not make any
    network call (Session() is offline; instance metadata is not contacted).
    """
    import os

    if (
        os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        or os.environ.get("AWS_PROFILE", "").strip()
        or os.environ.get("AWS_DEFAULT_PROFILE", "").strip()
    ):
        try:
            import boto3  # noqa: F401  # pyright: ignore[reportMissingImports]

            return True
        except ImportError:
            return False

    try:
        import boto3  # pyright: ignore[reportMissingImports]
        from botocore.exceptions import (  # pyright: ignore[reportMissingImports]
            NoCredentialsError,
        )

        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            return False
        resolved = creds.resolve()
        return resolved is not None
    except (ImportError, NoCredentialsError, Exception):  # noqa: BLE001
        return False


def _ollama_base_url() -> str:
    """Resolve the Ollama endpoint: stored override → settings → default."""
    from studyloop.secrets import get_secret

    stored = get_secret("ollama_base_url")
    if stored:
        return stored
    try:
        from studyloop.settings import load_settings

        return load_settings().card_generator.ollama.base_url
    except Exception:  # fall back to the well-known default
        return "http://localhost:11434"


def _ollama_reachable(base_url: str) -> bool:
    """Return True if the Ollama server answers ``GET /api/tags`` quickly.

    A cheap liveness probe (1s timeout); does not list or validate models —
    that is what the explicit ``/providers/ollama/test`` endpoint does.
    """
    import httpx

    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=1.0)
        return resp.status_code == 200
    except Exception:  # unreachable / bad URL → not available
        return False


# ---------------------------------------------------------------------------
# WebSocket endpoint (U7)
# ---------------------------------------------------------------------------

# RFC 6455 close codes. 1008 is "policy violation" (origin mismatch);
# 4404 is in the application range (4000-4999) and reads as "job not
# found" -- consistent with the HTTP 404 idiom the WS would otherwise
# have to encode in a transport_error frame.
_WS_CLOSE_POLICY = 1008
_WS_CLOSE_NOT_FOUND = 4404


def _origin_allowed(origin: str) -> bool:
    """Same allowlist as ``/session/ws`` -- localhost-by-default, env override.

    Re-implemented here (instead of importing from ``session.py``) to
    keep the route module self-contained; the helper is tiny and
    diverging it later would be a feature, not a bug.
    """
    import os

    if not origin:
        return False
    extra = os.environ.get("STUDYLOOP_ALLOWED_ORIGINS", "").strip()
    allowed: set[str] = {
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "http://127.0.0.1",
        "http://localhost",
    }
    if extra:
        allowed |= {o.strip() for o in extra.split(",") if o.strip()}
    if origin in allowed:
        return True
    for prefix in ("http://127.0.0.1", "http://localhost"):
        if origin.startswith(prefix + ":") or origin == prefix:
            return True
    return False


_TERMINAL_FRAMES = frozenset({"all_done", "transport_error"})


@router.websocket("/content/generate/ws")
async def content_generate_socket(websocket: WebSocket) -> None:
    """Stream generation progress for a given ``job_id``.

    Pre-accept guards (origin + queue lookup) follow the same shape as
    ``/session/ws`` so the two WS endpoints feel consistent. After
    ``accept()``, the handler is a pure consumer: pull from the queue,
    forward to the client, exit on a terminal frame.

    Close codes:

    - ``1008`` — disallowed origin.
    - ``4404`` — no queue for the requested ``job_id``.
    - ``1000`` — normal close after the orchestrator's ``all_done`` /
      ``transport_error`` frame.
    """
    origin = websocket.headers.get("origin", "")
    if not _origin_allowed(origin):
        logger.warning("WS /content/generate/ws rejected: origin=%r", origin)
        await websocket.close(code=_WS_CLOSE_POLICY)
        return

    job_id = websocket.query_params.get("job_id", "")
    queue = _JOB_QUEUES.get(job_id)
    if queue is None:
        await websocket.close(code=_WS_CLOSE_NOT_FOUND)
        return

    await websocket.accept()
    try:
        while True:
            frame = await queue.get()
            try:
                await websocket.send_json(frame)
            except WebSocketDisconnect:
                # Client gone -- keep draining the queue silently so
                # the orchestrator's push side never blocks. The job
                # itself is unaffected; its writes still hit disk.
                logger.debug("WS client disconnected job_id=%s; draining queue", job_id)
                await _drain_queue_quietly(queue)
                return
            if frame.get("type") in _TERMINAL_FRAMES:
                return
    finally:
        # Drop the queue once the consumer exits. The orchestrator's
        # background task has already released the singleton; the
        # queue is no longer reachable from a future WS client.
        _drop_queue(job_id)


async def _drain_queue_quietly(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Pull and discard remaining items so the producer never blocks.

    Stops when a terminal frame is seen, capping wait time even if the
    job runs long.
    """
    while True:
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            return
        if frame.get("type") in _TERMINAL_FRAMES:
            return



# ---------------------------------------------------------------------------
# Secrets management — encrypted local store for provider API keys
# ---------------------------------------------------------------------------
#
# Endpoints:
#   GET    /api/content/secrets               → which providers are configured
#   POST   /api/content/secrets               → test + persist a provider key
#   DELETE /api/content/secrets/{provider}    → remove a stored key
#
# Security invariants:
#   - Raw key values are NEVER returned in any response.
#   - Raw key values are NEVER logged. Diagnostics use ``key[:6] + "…"``.
#   - On auth-test failure the key is NOT persisted.

# The complete set of providers StudyLoop knows about for secrets.
# ``bedrock`` uses AWS SDK auth, not API keys — excluded from the secrets store.
_SECRETS_PROVIDERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "openrouter",
    "gemini",
    "minimax",
)


class StoreKeyRequest(BaseModel):
    """Body for POST /api/content/secrets."""

    provider: str = Field(..., min_length=1, max_length=64)
    key: str = Field(..., min_length=1, max_length=512)


class StoreKeyResponse(BaseModel):
    ok: bool
    error: str = ""


class SecretsStatusResponse(BaseModel):
    configured: list[str]
    missing_for_providers: list[str]


@router.get("/content/secrets", response_model=SecretsStatusResponse)
def list_secrets() -> SecretsStatusResponse:
    """Return which providers have a stored key. Names only — never values."""
    from studyloop.secrets import get_secret

    configured: list[str] = []
    missing: list[str] = []
    for provider in _SECRETS_PROVIDERS:
        if get_secret(provider):
            configured.append(provider)
        else:
            missing.append(provider)
    return SecretsStatusResponse(configured=configured, missing_for_providers=missing)


@router.post("/content/secrets", response_model=StoreKeyResponse)
def store_key(body: StoreKeyRequest) -> StoreKeyResponse:
    """Test a provider key and persist it on success.

    The key is tested against the provider's auth endpoint before being
    stored. If the test fails, the key is NOT stored and the error message
    is returned. The raw key value is never logged or returned.

    Status codes:
    - 422: unknown provider OR keyless provider (Bedrock).
    - 400: key is structurally valid but rejected by the provider.
    - 200: tested + persisted.
    """
    from studyloop.secrets import KEYLESS_PROVIDERS, set_secret, test_provider_auth

    provider = body.provider.lower().strip()
    if provider in KEYLESS_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Provider {provider!r} uses AWS SDK credentials, not API keys. "
                "Configure AWS profiles instead."
            ),
        )
    if provider not in _SECRETS_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown provider {provider!r}. "
                f"Supported: {', '.join(_SECRETS_PROVIDERS)}"
            ),
        )

    key = body.key
    key_hint = key[:6] + "…"
    logger.info("Testing API key for provider %r (key=%s)", provider, key_hint)
    ok, message = test_provider_auth(provider, key)
    if not ok:
        logger.warning(
            "API key test failed for provider %r (key=%s): %s",
            provider,
            key_hint,
            message,
        )
        raise HTTPException(status_code=400, detail=message)

    set_secret(provider, key)
    logger.info("API key stored for provider %r", provider)
    return StoreKeyResponse(ok=True)


@router.delete("/content/secrets/{provider}", response_model=StoreKeyResponse)
def delete_key(provider: str) -> StoreKeyResponse:
    """Delete the stored key for a provider. No-op if no key was stored."""
    from studyloop.secrets import delete_secret

    provider = provider.lower().strip()
    if provider not in _SECRETS_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown provider {provider!r}. "
                f"Supported: {', '.join(_SECRETS_PROVIDERS)}"
            ),
        )
    delete_secret(provider)
    logger.info("Secret deleted for provider %r", provider)
    return StoreKeyResponse(ok=True)


__all__ = ["router", "GenerateRequest", "GenerateResponse"]
