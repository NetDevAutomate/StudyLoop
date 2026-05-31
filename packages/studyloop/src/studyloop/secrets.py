"""Encrypted local API key store for StudyLoop provider credentials.

Threat model
------------
Encryption-at-rest for dotfile exposure: someone who can read
``~/.config/studyloop/`` but does NOT have code execution on the machine.
This covers accidental cloud-sync of dotfiles, screenshots, and nosy
shoulder-surfers.  It does NOT protect against an attacker who has a shell
on the machine — they can read the key seed file just as easily.  This is
the same threat model as 1Password's emergency-kit or SSH keys protected by
a passphrase that is stored next to the key.

Key derivation
--------------
A 32-byte random seed is generated on first use and stored at
``~/.config/studyloop/.secrets-key`` (mode 0600). The seed is passed through
HKDF-SHA256 to produce a Fernet-compatible 32-byte key (URL-safe base64
encoded). HKDF adds negligible overhead but keeps the raw seed out of the
Fernet key slot and makes future key rotation easier.

Storage format
--------------
``~/.config/studyloop/secrets.bin`` is a Fernet token containing a
JSON UTF-8 payload: ``{"provider_name": "raw_key_value", ...}``.  The
token is a self-contained authenticated ciphertext (AES-128-CBC + HMAC-SHA256
via Fernet spec).  The whole file is rewritten on every mutation — the
payload is small (< 10 provider keys) so this is fine.

Resolution order (when a provider requests a key)
--------------------------------------------------
1. Encrypted store (returns first if the name is present)
2. OS environment variable (e.g. ``OPENAI_API_KEY``)
3. Neither → caller receives ``None``; the UI prompts for key entry.

Provider name conventions
-------------------------
``openai``, ``anthropic``, ``openrouter``, ``gemini``, ``minimax``.
``bedrock`` is handled by AWS SDK credentials, NOT API keys — skip it here.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------

_CONFIG_DIR_ENV = "STUDYLOOP_CONFIG"

# Providers selected by SLUG that must NOT be stored under that slug via the
# secrets routes. ``bedrock`` uses AWS SDK / bearer-token auth (the bearer token
# is stored under the distinct key ``bedrock_bearer_token``, not ``bedrock``);
# ``ollama`` is local and keyless (its endpoint is stored under
# ``ollama_base_url``).
KEYLESS_PROVIDERS: frozenset[str] = frozenset({"bedrock", "ollama"})

# Auth kind drives what the admin UI renders and how a credential is tested.
#   api_key        — a typed key, checked with a cheap HTTP auth call
#   bedrock_bearer — optional AWS bearer token (else falls back to AWS profile)
#   local_keyless  — no credential; local endpoint (Ollama)
AuthKind = Literal["api_key", "bedrock_bearer", "local_keyless"]

_AUTH_KIND_MAP: dict[str, AuthKind] = {
    "openai": "api_key",
    "anthropic": "api_key",
    "openrouter": "api_key",
    "gemini": "api_key",
    "minimax": "api_key",
    "bedrock": "bedrock_bearer",
    "ollama": "local_keyless",
}

# Mapping from secret name → OS env variable name. The bedrock bearer token and
# ollama base-url are stored under their own names (not the provider slug) so
# the slug-level KEYLESS guard still holds. ``ollama_base_url`` has no env
# fallback (store-only).
_ENV_VAR_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "bedrock_bearer_token": "AWS_BEARER_TOKEN_BEDROCK",
    "ollama_base_url": "",
}


def get_auth_kind(provider: str) -> AuthKind | None:
    """Return the auth kind for a provider slug, or ``None`` if unknown."""
    return _AUTH_KIND_MAP.get(provider.lower().strip())


def _config_dir() -> Path:
    """Return the active config directory, respecting STUDYLOOP_CONFIG env override."""
    env = os.environ.get(_CONFIG_DIR_ENV)
    if env:
        return Path(env).expanduser().parent
    return Path.home() / ".config" / "studyloop"


def _secrets_file() -> Path:
    return _config_dir() / "secrets.bin"


def _seed_file() -> Path:
    return _config_dir() / ".secrets-key"


# ---------------------------------------------------------------------------
# Fernet key management
# ---------------------------------------------------------------------------


def _derive_key(seed: bytes) -> bytes:
    """Derive a Fernet key from the 32-byte random seed using HKDF-SHA256.

    Returns URL-safe base64-encoded 32 bytes (Fernet's key format).
    """
    from base64 import urlsafe_b64encode

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"studyloop-secrets-v1",
        info=b"fernet-key",
    )
    raw = hkdf.derive(seed)
    return urlsafe_b64encode(raw)


def _ensure_dirs() -> None:
    """Create config dir with mode 0700 if it does not exist."""
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    # Enforce 0700 on the directory itself.
    try:
        config_dir.chmod(0o700)
    except OSError:
        pass  # best-effort on some systems


def _load_or_create_fernet():  # type: ignore[no-untyped-def]
    """Load (or create) the Fernet instance backed by the seed file.

    Creates the seed file with mode 0600 on first use.
    Raises ``RuntimeError`` if the seed file exists but cannot be read.
    """
    from cryptography.fernet import Fernet

    _ensure_dirs()
    seed_path = _seed_file()

    if seed_path.exists():
        try:
            raw_seed = seed_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"Cannot read secrets seed from {seed_path}: {exc}. "
                "Check file permissions (should be mode 0600 owned by your user)."
            ) from exc
    else:
        raw_seed = os.urandom(32)
        seed_path.write_bytes(raw_seed)
        seed_path.chmod(0o600)

    fernet_key = _derive_key(raw_seed)
    return Fernet(fernet_key)


# ---------------------------------------------------------------------------
# Low-level read/write (encrypted payload)
# ---------------------------------------------------------------------------


def _read_store() -> dict[str, str]:
    """Load and decrypt the secrets store.

    Returns an empty dict if the file does not exist.
    Raises ``ValueError`` with a user-friendly message on decrypt failure.
    """
    from cryptography.fernet import InvalidToken

    secrets_path = _secrets_file()
    if not secrets_path.exists():
        return {}

    fernet = _load_or_create_fernet()
    try:
        ciphertext = secrets_path.read_bytes()
        plaintext = fernet.decrypt(ciphertext)
    except InvalidToken as exc:
        raise ValueError(
            f"Could not decrypt {secrets_path}. "
            "The file may be corrupt or the seed key has changed. "
            "Delete it to reset (all stored keys will be lost)."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Cannot read secrets file {secrets_path}: {exc}") from exc

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"Secrets file {secrets_path} is not valid JSON after decrypt: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(f"Secrets file {secrets_path} decoded to non-dict type: {type(data)}")
    return data  # type: ignore[return-value]


def _write_store(data: dict[str, str]) -> None:
    """Encrypt and persist the secrets dict, creating the file with mode 0600."""
    _ensure_dirs()
    fernet = _load_or_create_fernet()
    plaintext = json.dumps(data, sort_keys=True).encode("utf-8")
    ciphertext = fernet.encrypt(plaintext)

    secrets_path = _secrets_file()
    # Write to a tmp file first, then rename atomically.
    tmp_path = secrets_path.with_suffix(".tmp")
    try:
        tmp_path.write_bytes(ciphertext)
        tmp_path.chmod(0o600)
        tmp_path.rename(secrets_path)
    except OSError:
        # Clean up tmp file on failure.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_secret(name: str) -> str | None:
    """Resolve a named secret using the priority order.

    Resolution order:
    1. Encrypted store (``~/.config/studyloop/secrets.bin``)
    2. OS environment variable (from ``_ENV_VAR_MAP``)
    3. ``None``

    If the encrypted store is corrupt or unreadable, logs a warning and
    falls through to the environment variable rather than raising — this
    prevents a corrupt store from blocking the application entirely.

    Args:
        name: Provider name, e.g. ``"openai"``.

    Returns:
        The raw API key string, or ``None`` if not configured.
    """
    # 1. Encrypted store
    try:
        store = _read_store()
        if name in store:
            return store[name]
    except (ValueError, RuntimeError) as exc:
        logger.warning("Encrypted secrets store unreadable (%s), falling through to env", exc)

    # 2. OS environment variable
    env_var = _ENV_VAR_MAP.get(name.lower())
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value

    return None


def set_secret(name: str, value: str) -> None:
    """Encrypt and store a named secret.

    Overwrites any existing value for ``name``. File is written with
    mode 0600.

    Args:
        name: Provider name, e.g. ``"openai"``.
        value: Raw API key. Never logged; truncated to ``key[:6]...`` in
               any diagnostic messages.
    """
    store = {}
    try:
        store = _read_store()
    except ValueError:
        # Corrupt store: overwrite rather than propagate.
        logger.warning("Corrupt secrets store, overwriting with new entry for %r", name)

    store[name] = value
    _write_store(store)
    logger.debug("Secret stored for provider %r (key=%s…)", name, value[:6])


def delete_secret(name: str) -> None:
    """Remove a named secret from the encrypted store.

    No-op if the name is not present.

    Args:
        name: Provider name, e.g. ``"openai"``.
    """
    try:
        store = _read_store()
    except ValueError:
        return  # nothing to delete from a corrupt store

    if name not in store:
        return

    del store[name]
    _write_store(store)
    logger.debug("Secret deleted for provider %r", name)


def list_secret_names() -> list[str]:
    """Return the names of all stored secrets.

    NEVER returns the secret values — names only.

    Returns:
        Sorted list of provider names that have encrypted entries.
    """
    try:
        store = _read_store()
        return sorted(store.keys())
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# Provider auth-test
# ---------------------------------------------------------------------------

# Auth-test endpoints per provider.  Chosen as the cheapest GET/list call.
_AUTH_TEST_PROVIDERS: dict[str, dict[str, object]] = {
    "openai": {
        "url": "https://api.openai.com/v1/models",
        "auth": "bearer",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/models",
        "auth": "x-api-key",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/models",
        "auth": "bearer",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        # Header, NOT ?key=<key>: a query-param key is echoed verbatim in
        # httpx error messages and would leak into a client-visible response if
        # raise_for_status() were ever added. The header keeps the secret out
        # of the URL. Google accepts x-goog-api-key as an alternative to the
        # key query param.
        "auth": "x-goog-api-key",
    },
    "minimax": {
        # Smallest non-destructive endpoint; token must be in Authorization header.
        "url": "https://api.minimax.io/v1/text/chatcompletion_v2",
        "auth": "bearer",
        "method": "post",
        # Minimal valid body to avoid a 422 — not actually generating.
        "body": {
            "model": "abab5.5s-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        },
    },
}

_AUTH_TIMEOUT = httpx.Timeout(10.0)


def test_provider_auth(provider: str, key: str = "", base_url: str = "") -> tuple[bool, str]:
    """Test a provider credential.

    For API-key providers this performs an inexpensive HTTP call
    (``GET /v1/models`` or equivalent) — no generation tokens are consumed.

    Special dispatch:

    - ``bedrock`` / ``bedrock_bearer_token`` with a non-empty ``key`` →
      a minimal Bedrock Converse call to verify the bearer token
      (delegates to :func:`studyloop.provider_auth.test_bedrock_bearer`).
    - ``bedrock`` with no ``key`` → the AWS SDK / profile path is used at
      generation time; returns an informational ``(True, …)``.
    - ``ollama`` → a real local generation validated against the quality bar
      (delegates to :func:`studyloop.provider_auth.test_ollama_generate`).

    The heavy delegations import their deps locally so this module stays
    importable on a minimal install.

    Args:
        provider: Provider name (``"openai"``, ``"bedrock"``, ``"ollama"``, …).
        key: Raw credential to test (API key or Bedrock bearer token).
        base_url: Ollama endpoint override (ignored for other providers).

    Returns:
        ``(True, success_message)`` or ``(False, error_message)``.
    """
    provider = provider.lower().strip()

    # The bearer token is stored under its own name; normalise to the slug
    # so the dispatch below is single-pathed.
    if provider == "bedrock_bearer_token":
        provider = "bedrock"

    if provider == "bedrock":
        if key.strip():
            from studyloop.provider_auth import test_bedrock_bearer

            return test_bedrock_bearer(key)
        return True, "Bedrock uses AWS SDK credentials, not API keys — no key needed"

    if provider == "ollama":
        from studyloop.provider_auth import test_ollama_generate

        return test_ollama_generate(base_url=base_url or "http://localhost:11434")

    spec = _AUTH_TEST_PROVIDERS.get(provider)
    if spec is None:
        return False, f"Unknown provider {provider!r}. Known: {', '.join(_AUTH_TEST_PROVIDERS)}"

    try:
        ok, msg = _run_auth_test(provider, key, spec)
        return ok, msg
    except httpx.TimeoutException:
        return False, f"Timeout contacting {spec['url']} — check network connectivity"
    except httpx.HTTPError as exc:
        return False, f"Network error testing {provider}: {exc}"


def _run_auth_test(provider: str, key: str, spec: dict[str, object]) -> tuple[bool, str]:
    """Execute the HTTP call described by *spec* and classify the response."""
    url = str(spec["url"])
    auth_style = str(spec["auth"])
    method = str(spec.get("method", "get"))

    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    body = spec.get("body")

    if auth_style == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif auth_style == "x-api-key":
        headers["x-api-key"] = key
        # Anthropic requires this header to be present
        headers["anthropic-version"] = "2023-06-01"
    elif auth_style == "x-goog-api-key":
        # Gemini: header keeps the key out of the URL (see spec comment).
        headers["x-goog-api-key"] = key

    with httpx.Client(timeout=_AUTH_TIMEOUT) as client:
        if method == "post":
            response = client.post(url, headers=headers, params=params, json=body)
        else:
            response = client.get(url, headers=headers, params=params)

    key_hint = key[:6] + "…"

    if response.status_code in (200, 201):
        return True, f"Authentication successful for {provider} (key={key_hint})"

    if response.status_code == 401:
        return False, f"Invalid API key for {provider} (HTTP 401) — check the key value"

    if response.status_code == 403:
        return False, (
            f"API key for {provider} is valid but lacks permission (HTTP 403) — "
            "check your account's enabled models/capabilities"
        )

    if response.status_code == 429:
        # Rate-limited — the key is valid, the account is just busy.
        return True, f"Key accepted for {provider} (HTTP 429 rate-limited — key is valid)"

    # Any other non-2xx is treated as a failure.
    body_snippet = response.text[:200]
    return (
        False,
        f"Unexpected HTTP {response.status_code} from {provider}: {body_snippet}",
    )


__all__ = [
    "KEYLESS_PROVIDERS",
    "AuthKind",
    "delete_secret",
    "get_auth_kind",
    "get_secret",
    "list_secret_names",
    "set_secret",
    "test_provider_auth",
]
