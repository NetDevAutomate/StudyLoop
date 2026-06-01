"""Content discovery and provider registry HTTP routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from studyloop.web.routes.content_gen._router import router
from studyloop.web.services.content_generation import (
    ProviderAvailabilityInput,
    provider_is_available,
)


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
    from studyloop.web.routes import content_gen as content_gen_pkg

    out: list[dict[str, Any]] = []
    for slug, profile in PROFILES.items():
        auth_kind = get_auth_kind(slug)

        stored_secret_name = "bedrock_bearer_token" if slug == "bedrock" else slug
        available = provider_is_available(
            ProviderAvailabilityInput(
                slug=slug,
                auth_env=profile.auth_env,
                env_value=os.environ.get(profile.auth_env, ""),
                stored_secret=content_gen_pkg.get_secret(stored_secret_name),
                bedrock_credentials=content_gen_pkg._bedrock_credentials_available(),
                ollama_reachable=content_gen_pkg._ollama_reachable(
                    content_gen_pkg._ollama_base_url()
                ),
            )
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
            entry["base_url"] = content_gen_pkg._ollama_base_url()
        out.append(entry)

    return out


class TestProviderRequest(BaseModel):
    """Body for POST /api/content/providers/{slug}/test.

    ``key`` carries the credential to test (API key or Bedrock bearer token).
    It is empty for local/keyless providers (Ollama) and for testing Bedrock's
    AWS-profile path.
    """

    key: str = ""


class TestProviderResponse(BaseModel):
    ok: bool
    message: str = ""


@router.post("/content/providers/{slug}/test", response_model=TestProviderResponse)
async def test_provider(slug: str, body: TestProviderRequest) -> TestProviderResponse:
    """Test a provider's credentials without persisting anything.

    - ``ollama``  → a real local generation (validated against the quality
      bar); run in a worker thread so it never blocks the event loop.
    - ``bedrock`` with a key → a minimal Converse probe of the bearer token
      (also off-thread).
    - ``bedrock`` with no key → the AWS-SDK/profile path; informational.
    - api-key providers → the cheap HTTP auth check.

    Unknown slug → 404. The raw key is never logged or echoed.
    """
    from studyloop import secrets as secrets_mod
    from studyloop.content.generators.provider_profiles import PROFILES
    from studyloop.web.routes import content_gen as content_gen_pkg

    slug = slug.lower().strip()
    if slug not in PROFILES:
        raise HTTPException(status_code=404, detail=f"Unknown provider {slug!r}.")

    if slug == "ollama":
        ok, message = await asyncio.to_thread(
            secrets_mod.test_provider_auth, "ollama", "", content_gen_pkg._ollama_base_url()
        )
        return TestProviderResponse(ok=ok, message=message)

    if slug == "bedrock":
        # Prefer the typed token; else the stored one. With neither, fall to the
        # AWS-SDK/profile path (test_provider_auth returns the informational msg).
        token = body.key.strip() or (secrets_mod.get_secret("bedrock_bearer_token") or "")
        ok, message = await asyncio.to_thread(secrets_mod.test_provider_auth, "bedrock", token)
        return TestProviderResponse(ok=ok, message=message)

    # API-key providers. The "Test" button sends an empty key (the browser
    # never holds the stored secret), so fall back to the stored key. With no
    # key anywhere there is nothing to test — say so rather than make an
    # empty-credential HTTP call.
    key = body.key.strip() or (secrets_mod.get_secret(slug) or "")
    if not key:
        return TestProviderResponse(
            ok=False, message=f"No stored key for {slug}. Enter a key and Test & save."
        )
    ok, message = secrets_mod.test_provider_auth(slug, key)
    return TestProviderResponse(ok=ok, message=message)


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
            import boto3  # pyright: ignore[reportMissingImports]

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
        frozen = creds.get_frozen_credentials()
        return bool(frozen.access_key)
    except (ImportError, NoCredentialsError, Exception):
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
