"""Encrypted provider credential store HTTP routes."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from pydantic import BaseModel, Field

from studyloop.web.routes.content_gen._router import router

logger = logging.getLogger(__name__)

# The complete set of secret NAMES the store manages. These are not all
# provider slugs: ``bedrock`` (the slug) uses AWS auth and is keyless, but its
# optional bearer token is stored under ``bedrock_bearer_token``; ``ollama``
# (the slug) is keyless but its endpoint override is stored under
# ``ollama_base_url``. Keeping the store names distinct from the keyless slugs
# lets the slug-level KEYLESS_PROVIDERS guard stay correct.
_SECRETS_PROVIDERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "openrouter",
    "gemini",
    "bedrock_bearer_token",
    "ollama_base_url",
)

# Store names that are config values, not credentials — skip the live
# auth-test on store (there is nothing to authenticate; it's a URL).
_NON_CREDENTIAL_SECRETS: frozenset[str] = frozenset({"ollama_base_url"})


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
            detail=(f"Unknown provider {provider!r}. Supported: {', '.join(_SECRETS_PROVIDERS)}"),
        )

    key = body.key

    # Config values (e.g. the Ollama endpoint URL) are stored without a live
    # auth-test — there is no credential to verify.
    if provider in _NON_CREDENTIAL_SECRETS:
        set_secret(provider, key)
        logger.info("Config value stored for %r", provider)
        return StoreKeyResponse(ok=True)

    logger.info("Testing credential for %r", provider)
    # test_provider_auth normalises bedrock_bearer_token → bedrock (real
    # bearer-token Converse probe).
    ok, message = test_provider_auth(provider, key)
    if not ok:
        logger.warning("Credential test failed for %r: %s", provider, message)
        raise HTTPException(status_code=400, detail=message)

    set_secret(provider, key)
    logger.info("Credential stored for %r", provider)
    return StoreKeyResponse(ok=True)


@router.delete("/content/secrets/{provider}", response_model=StoreKeyResponse)
def delete_key(provider: str) -> StoreKeyResponse:
    """Delete the stored key for a provider. No-op if no key was stored."""
    from studyloop.secrets import delete_secret

    provider = provider.lower().strip()
    if provider not in _SECRETS_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=(f"Unknown provider {provider!r}. Supported: {', '.join(_SECRETS_PROVIDERS)}"),
        )
    delete_secret(provider)
    logger.info("Secret deleted for provider %r", provider)
    return StoreKeyResponse(ok=True)
