"""Heavy credential tests for providers whose check needs the SDK/model.

This module is deliberately separate from :mod:`studyloop.secrets`:

- ``secrets.py`` does the cheap, dependency-light work (encrypted store +
  inexpensive HTTP auth checks for API-key providers). It must import cleanly
  on a minimal install, so it must NOT pull ``boto3`` or the Ollama generator
  at module load.
- This module holds the expensive tests that *do* need those optional deps —
  a minimal Bedrock Converse call (bearer-token auth) and a real Ollama
  generation. All heavy imports are local to the functions.

Security note
-------------
``test_bedrock_bearer`` must place the bearer token in
``AWS_BEARER_TOKEN_BEDROCK`` for boto3 to pick it up. It does so via the
:func:`_with_bearer_env` context manager, which always restores the prior
value in a ``finally`` block — the token never lingers in the long-running
server's environment. This is NOT thread-safe (it mutates ``os.environ``);
StudyLoop's single-active-generation singleton makes that acceptable, and the
test endpoint is a one-at-a-time user action.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_BEARER_ENV = "AWS_BEARER_TOKEN_BEDROCK"

# Cheapest cross-region inference profile — used only to prove the token works.
BEDROCK_TEST_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Modest-footprint local models recommended for machines without a large
# unified-memory GPU. Ordered cheapest/smallest-first; the Ollama test tries
# them in order when no explicit model is given. Per-host-profile suggestions
# (via the autoagent harness) are a future phase — these are a sensible default.
OLLAMA_RECOMMENDED_MODELS: tuple[str, ...] = (
    "qwen2.5:7b",
    "llama3.2:3b",
    "gemma3:4b",
    "phi3.5:3.8b",
)

# Short, self-contained source so the test generation is fast and deterministic.
_OLLAMA_TEST_SOURCE = (
    "# Python Functions\n"
    "Functions are reusable blocks of code defined with the `def` keyword.\n"
    "They accept parameters and return values. Use them to avoid repetition.\n"
)


@contextlib.contextmanager
def _with_bearer_env(token: str) -> Iterator[None]:
    """Temporarily set ``AWS_BEARER_TOKEN_BEDROCK`` for the duration of a block.

    Restores the prior value (or removes the var) on exit, including on
    exception. NOT thread-safe — mutates process-global ``os.environ``.
    """
    previous = os.environ.get(_BEARER_ENV)
    if previous is not None:
        logger.warning(
            "%s already set in the environment; overriding for this call only",
            _BEARER_ENV,
        )
    os.environ[_BEARER_ENV] = token
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_BEARER_ENV, None)
        else:
            os.environ[_BEARER_ENV] = previous


def test_bedrock_bearer(token: str, region: str = "us-east-1") -> tuple[bool, str]:
    """Verify a Bedrock bearer token with a minimal Converse call.

    Sets ``AWS_BEARER_TOKEN_BEDROCK`` (scoped to this call) and issues a
    ``converse`` request with ``maxTokens=1`` — the cheapest call that proves
    the token authenticates. The token is never logged or returned.

    Returns ``(True, msg)`` on success, ``(False, msg)`` on auth failure,
    network error, or missing ``boto3``.
    """
    if not token.strip():
        return False, "No bearer token provided."

    try:
        import boto3
        from botocore.config import Config as BotoConfig
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return False, "boto3 not installed. Install with: pip install 'studyloop[bedrock]'."

    boto_config = BotoConfig(
        connect_timeout=10,
        read_timeout=30,
        retries={"max_attempts": 1, "mode": "standard"},
    )

    try:
        with _with_bearer_env(token):
            client = boto3.client(
                "bedrock-runtime", region_name=region, config=boto_config
            )
            client.converse(
                modelId=BEDROCK_TEST_MODEL,
                messages=[{"role": "user", "content": [{"text": "ping"}]}],
                inferenceConfig={"maxTokens": 1},
            )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        _auth_failures = (
            "UnrecognizedClientException",
            "AccessDeniedException",
            "InvalidSignatureException",
        )
        if code in _auth_failures:
            return False, f"Bedrock rejected the bearer token ({code})."
        # Other ClientErrors (e.g. ThrottlingException, ValidationException for the
        # tiny request) still prove the token authenticated.
        return True, f"Bearer token accepted (Bedrock returned {code or 'a non-auth error'})."
    except BotoCoreError as exc:
        return False, f"Could not reach Bedrock: {exc}"
    except Exception as exc:
        return False, f"Unexpected error testing Bedrock bearer token: {exc}"

    return True, "Bearer token verified against Bedrock."


def list_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return the model names actually installed on the Ollama server.

    Queries ``GET /api/tags``. Returns ``[]`` if the server is unreachable or
    returns no models. Names include the tag (e.g. ``gemma3:4b``,
    ``gemma4:latest``).
    """
    import httpx

    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    models = data.get("models", []) if isinstance(data, dict) else []
    names = [m.get("name", "") for m in models if isinstance(m, dict)]
    return [n for n in names if n]


def _ollama_test_candidates(base_url: str, model: str) -> list[str]:
    """Pick which models the test should try, preferring what's installed.

    - explicit ``model`` → just that one.
    - otherwise: installed models, recommended ones first (so a known-good
      small model is tried before a random embedding model), then any other
      installed model. Falls back to the recommended list if discovery fails
      (so the error message still names sensible models).
    """
    if model:
        return [model]
    installed = list_ollama_models(base_url)
    if not installed:
        return list(OLLAMA_RECOMMENDED_MODELS)
    # Embedding models can't generate chat/tool-use output — skip them.
    installed = [m for m in installed if "embed" not in m.lower()]
    preferred = [m for m in installed if m in OLLAMA_RECOMMENDED_MODELS]
    rest = [m for m in installed if m not in OLLAMA_RECOMMENDED_MODELS]
    return preferred + rest


def test_ollama_generate(
    base_url: str = "http://localhost:11434", model: str = ""
) -> tuple[bool, str]:
    """Run a real Ollama generation and validate the output meets the bar.

    Quality bar (Phase I): the model must return a schema-valid
    :class:`FlashcardDeck` with at least one card. This proves the local model
    can produce StudyLoop's structured tool-use output — the thing small models
    most often fail — without a second judge LLM.

    When ``model`` is empty, discovers installed models (via ``/api/tags``)
    and tries them — recommended ones first — so the test uses a model the
    user actually has. Returns ``(True, msg)`` / ``(False, msg)``.
    """
    from studyloop.content.generators import CardGenerationError
    from studyloop.content.generators.ollama import OllamaGenerator
    from studyloop.settings import CardGeneratorConfig, OllamaBackendConfig

    candidates = _ollama_test_candidates(base_url, model)
    if not candidates:
        return False, (
            f"No Ollama models installed at {base_url}. "
            "Pull one first, e.g. `ollama pull qwen2.5:7b`."
        )
    failures: list[str] = []

    for candidate in candidates:
        config = CardGeneratorConfig(
            backend="ollama",
            max_retries=0,
            request_timeout=30.0,
            ollama=OllamaBackendConfig(base_url=base_url, model=candidate),
        )
        try:
            generator = OllamaGenerator(config)
            deck = generator.generate_flashcards(_OLLAMA_TEST_SOURCE, "Test")
        except CardGenerationError as exc:
            failures.append(f"{candidate}: {exc}")
            continue
        except Exception as exc:
            failures.append(f"{candidate}: {exc}")
            continue

        # Quality bar: schema-valid, non-empty deck.
        if deck.cards:
            return True, f"Ollama model {candidate!r} produced {len(deck.cards)} cards."
        failures.append(f"{candidate}: produced a deck with no cards")

    detail = "; ".join(failures) if failures else "no models tried"
    return False, f"Ollama test failed at {base_url} ({detail})."


__all__ = [
    "BEDROCK_TEST_MODEL",
    "OLLAMA_RECOMMENDED_MODELS",
    "list_ollama_models",
    "test_bedrock_bearer",
    "test_ollama_generate",
]
