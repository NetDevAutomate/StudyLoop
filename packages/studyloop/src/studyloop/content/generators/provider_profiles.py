"""Provider profile registry for the pluggable generator backends.

Two adapter classes (``OpenAICompatGenerator``,
``AnthropicCompatGenerator``) cover seven providers because almost every
modern LLM service speaks one of two specs:

- **OpenAI Chat Completions** (with ``tool_choice``): OpenAI itself,
  OpenRouter, Google Gemini's OpenAI-compat endpoint, MiniMax's
  OpenAI-compat endpoint... most "we host an OpenAI-compatible API"
  services slot in here with just a different ``base_url``.
- **Anthropic Messages** (with ``tool_use``): Anthropic itself, plus
  shims like MiniMax's ``/anthropic`` endpoint that speak the Messages
  protocol natively. Bedrock's Converse API is *similar* but we keep
  the existing :class:`BedrockGenerator` as a separate path because it
  uses boto3, profile fallback, and the Converse-specific shape.

Adding a new provider is a registry row plus a curated model list -- no
new generator class, no new tests beyond the live smoke.

Curation policy
---------------

The ``models`` list is **not** "every model the provider exposes". It is
the curated subset that:

1. Supports tool-use / structured-output mode (no JSON-mode-only models;
   the deck schema needs the strict tool-call constraint).
2. Has a viable cost-per-deck. Cheap tier targets <$0.05 per deck;
   balanced <$0.25; premium uncapped.
3. Is reasonably current and not deprecated.

The list lives in code so it is PR-edit-able by anyone. It is **not** a
config file -- letting users add arbitrary model IDs would invite quiet
failures (wrong tool-use shape, unsupported features, surprise costs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ModelEntry:
    """One curated model within a provider profile.

    The ``id`` string is what we send in the API request body's
    ``model`` field. The ``label`` is what the WebUI displays. The
    ``cost_tier`` and ``thinking`` flags drive UI badges and adapter
    behaviour (thinking models get a 3x request_timeout multiplier).
    """

    id: str
    label: str
    cost_tier: Literal["cheap", "balanced", "premium"]
    thinking: bool = False
    notes: str = ""


@dataclass(frozen=True)
class ProviderProfile:
    """One provider in the registry.

    ``adapter`` selects which generic adapter class handles this
    provider. ``base_url`` is passed to the adapter's HTTP client.
    ``auth_env`` names the environment variable carrying the API key
    (header injection differs per spec: ``Authorization: Bearer ...``
    for OpenAI-compat, ``x-api-key`` for Anthropic-compat).
    """

    slug: str
    label: str
    adapter: Literal["openai_compat", "anthropic_compat", "bedrock", "ollama"]
    base_url: str
    auth_env: str
    models: list[ModelEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Registry data
# ---------------------------------------------------------------------------

# IMPORTANT: preview model IDs (Gemini 3.x, MiniMax M2.7) are subject to
# drift. Verify against the provider's /models endpoint before assuming a
# given ID is current. See the plan's "preview ID verification" pre-flight.

PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        slug="openai",
        label="OpenAI",
        adapter="openai_compat",
        base_url="https://api.openai.com/v1",
        auth_env="OPENAI_API_KEY",
        models=[
            ModelEntry(id="gpt-4o-mini", label="GPT-4o mini", cost_tier="cheap"),
            ModelEntry(id="gpt-4o", label="GPT-4o", cost_tier="balanced"),
            ModelEntry(
                id="o3-mini",
                label="o3 mini",
                cost_tier="premium",
                thinking=True,
                notes="Reasoning model -- 3x request_timeout",
            ),
        ],
    ),
    "openrouter": ProviderProfile(
        slug="openrouter",
        label="OpenRouter",
        adapter="openai_compat",
        base_url="https://openrouter.ai/api/v1",
        auth_env="OPENROUTER_API_KEY",
        models=[
            ModelEntry(
                id="anthropic/claude-haiku-4-5",
                label="Claude Haiku 4.5 (via OpenRouter)",
                cost_tier="cheap",
            ),
            ModelEntry(
                id="anthropic/claude-sonnet-4-6",
                label="Claude Sonnet 4.6 (via OpenRouter)",
                cost_tier="balanced",
            ),
            ModelEntry(
                id="google/gemini-3.5-flash",
                label="Gemini 3.5 Flash (via OpenRouter)",
                cost_tier="cheap",
            ),
            ModelEntry(
                id="qwen/qwq-32b-preview",
                label="Qwen QwQ 32B",
                cost_tier="balanced",
                thinking=True,
                notes="Reasoning model",
            ),
        ],
    ),
    "gemini": ProviderProfile(
        slug="gemini",
        label="Google Gemini",
        adapter="openai_compat",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        auth_env="GEMINI_API_KEY",
        models=[
            ModelEntry(
                id="gemini-3.5-flash",
                label="Gemini 3.5 Flash",
                cost_tier="cheap",
                notes="2.x deprecated; verify slug at /v1beta/models",
            ),
            ModelEntry(
                id="gemini-3.1-flash-lite",
                label="Gemini 3.1 Flash Lite",
                cost_tier="cheap",
                notes="Fastest/cheapest Gemini",
            ),
            ModelEntry(
                id="gemini-3.1-pro-preview",
                label="Gemini 3.1 Pro (preview)",
                cost_tier="balanced",
            ),
        ],
    ),
    "minimax": ProviderProfile(
        slug="minimax",
        label="MiniMax",
        # MiniMax exposes both an OpenAI-compat and an Anthropic-compat
        # endpoint. We use the Anthropic shim at /anthropic per the
        # vendor's recommended path (matches their tool-use shape and
        # avoids OpenAI-compat schema-mode quirks).
        adapter="anthropic_compat",
        base_url="https://api.minimax.io/anthropic",
        auth_env="MINIMAX_API_KEY",
        models=[
            ModelEntry(
                id="MiniMax-M2.7",
                label="MiniMax M2.7",
                cost_tier="balanced",
                notes="Anthropic-compat shim; requires token plan",
            ),
        ],
    ),
    "anthropic": ProviderProfile(
        slug="anthropic",
        label="Anthropic",
        adapter="anthropic_compat",
        base_url="https://api.anthropic.com",
        auth_env="ANTHROPIC_API_KEY",
        models=[
            ModelEntry(
                id="claude-haiku-4-5",
                label="Claude Haiku 4.5",
                cost_tier="cheap",
            ),
            ModelEntry(
                id="claude-sonnet-4-6",
                label="Claude Sonnet 4.6",
                cost_tier="balanced",
            ),
            ModelEntry(
                id="claude-opus-4-7",
                label="Claude Opus 4.7",
                cost_tier="premium",
            ),
        ],
    ),
    # Bedrock uses boto3 + the Converse API, handled by the separate
    # BedrockGenerator (not one of the two HTTP adapters). It authenticates
    # with an AWS profile/SigV4 OR an AWS_BEARER_TOKEN_BEDROCK bearer token —
    # availability is computed in the providers route, not via auth_env alone.
    # Model IDs are cross-region inference profiles; verify in the Bedrock
    # console before relying on them.
    "bedrock": ProviderProfile(
        slug="bedrock",
        label="AWS Bedrock",
        adapter="bedrock",
        base_url="",
        auth_env="AWS_PROFILE",
        models=[
            ModelEntry(
                id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                label="Claude Haiku 4.5 (Bedrock)",
                cost_tier="cheap",
                notes="Cross-region inference profile",
            ),
            ModelEntry(
                id="us.anthropic.claude-sonnet-4-6-20251101-v1:0",
                label="Claude Sonnet 4.6 (Bedrock)",
                cost_tier="balanced",
                notes="Cross-region inference profile",
            ),
        ],
    ),
    # Ollama is local and keyless. Handled by OllamaGenerator. The model list
    # is a modest-footprint recommendation for machines without a large
    # unified-memory GPU; the endpoint is user-editable (stored as the
    # ``ollama_base_url`` secret). Per-host-profile model suggestions via the
    # autoagent harness are a future phase.
    "ollama": ProviderProfile(
        slug="ollama",
        label="Ollama (local)",
        adapter="ollama",
        base_url="http://localhost:11434",
        auth_env="",
        models=[
            ModelEntry(
                id="qwen2.5:7b",
                label="Qwen 2.5 7B",
                cost_tier="cheap",
                notes="Default; good structured output",
            ),
            ModelEntry(
                id="llama3.2:3b",
                label="Llama 3.2 3B",
                cost_tier="cheap",
                notes="Fast, low RAM",
            ),
            ModelEntry(
                id="gemma3:4b",
                label="Gemma 3 4B",
                cost_tier="cheap",
                notes="Google; efficient",
            ),
            ModelEntry(
                id="phi3.5:3.8b",
                label="Phi-3.5 3.8B",
                cost_tier="cheap",
                notes="Microsoft; efficient",
            ),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


class ProviderProfileError(ValueError):
    """Raised on unknown provider slug or unknown model id within a profile.

    Subclassing :class:`ValueError` so callers that already trap
    ``ValueError`` (e.g. ``get_generator``) keep working without
    additional except clauses, while letting tests assert on the
    specific subclass.
    """


def get_profile(slug: str) -> ProviderProfile:
    """Return the profile for ``slug``, or raise with the available list.

    The error message lists the available slugs because typos are the
    most common cause and a one-shot fix beats a search.
    """
    profile = PROFILES.get(slug)
    if profile is None:
        available = ", ".join(sorted(PROFILES))
        raise ProviderProfileError(
            f"Unknown provider slug {slug!r}. Available: {available}."
        )
    return profile


def get_model(profile: ProviderProfile, model_id: str) -> ModelEntry:
    """Return the curated model entry for ``model_id`` within ``profile``.

    Raises :class:`ProviderProfileError` listing the profile's curated
    model IDs on a miss.
    """
    for entry in profile.models:
        if entry.id == model_id:
            return entry
    available = ", ".join(m.id for m in profile.models)
    raise ProviderProfileError(
        f"Unknown model {model_id!r} for provider {profile.slug!r}. "
        f"Available: {available}."
    )


def default_model(profile: ProviderProfile) -> ModelEntry:
    """Return the first cheap-tier model, or the first model if none cheap.

    Used by ``get_generator()`` when the user supplies a provider but no
    model id; default to the cheapest viable option to minimise surprise
    spend on first run.
    """
    for entry in profile.models:
        if entry.cost_tier == "cheap":
            return entry
    if not profile.models:
        raise ProviderProfileError(
            f"Provider {profile.slug!r} has no curated models -- cannot pick default."
        )
    return profile.models[0]


__all__ = [
    "PROFILES",
    "ModelEntry",
    "ProviderProfile",
    "ProviderProfileError",
    "default_model",
    "get_model",
    "get_profile",
]
