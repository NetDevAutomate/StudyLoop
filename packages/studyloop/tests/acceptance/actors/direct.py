"""``ACTOR=direct`` -- a plain OpenAI/Anthropic HTTP client, no gateway needed.

The owner's explicit requirement: a contributor without the LiteLLM proxy
must still be able to run the learner side, straight against the vendor's
own API. Reuses ``content/generators/provider_profiles`` PARSING --
``get_profile``/``get_model``/``default_model`` and each profile's
``base_url``/``auth_env`` -- because that data (a public, fixed vendor
endpoint) is exactly what this backend needs and is already curated there.
It never reuses the ``OpenAICompatGenerator``/``AnthropicCompatGenerator``
HTTP CALL code: those force a tool call to emit a flashcard/quiz JSON
payload (council D-15's "never the card-generation semantics"); this
backend issues a plain chat/messages call and reads back message text.

Only the two HTTP-adapter providers (``openai_compat``, ``anthropic_compat``)
are supported -- ``bedrock`` (boto3/SigV4) and ``ollama`` (no key, not
"direct" in the sense the owner meant: it needs no gateway because it needs
no network account at all) are out of scope for a backend whose whole
point is "I have a vendor API key but no gateway".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from acceptance.actors._loop import run_llm_conversation
from acceptance.actors.budget import BudgetGuard
from acceptance.actors.protocol import ActorError, ConversationResult, TokenUsage
from studyloop.content.generators.provider_profiles import (
    ModelEntry,
    ProviderProfile,
    ProviderProfileError,
    default_model,
    get_model,
    get_profile,
)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping, Sequence

    from acceptance.actors.protocol import MentorTransport

#: Provider slugs this backend can drive -- the two generic HTTP adapters.
#: ``bedrock``/``ollama`` are curated out (see module docstring).
SUPPORTED_ADAPTERS = frozenset({"openai_compat", "anthropic_compat"})

DEFAULT_PROVIDER = "openai"

DEFAULT_SYSTEM_PROMPT = (
    "You are a curious student in a tutoring conversation. Given the "
    "tutor's latest message (or, on the first turn, nothing yet), reply as "
    "the student would: a short, specific question or answer, one to three "
    "plain-text sentences. Never mention that you are an AI or a test."
)

DEFAULT_MAX_OUTPUT_TOKENS_PER_TURN = 200

_ANTHROPIC_API_VERSION = "2023-06-01"

ENV_PROVIDER = "STUDYLOOP_ACC_DIRECT_PROVIDER"
ENV_MODEL = "STUDYLOOP_ACC_DIRECT_MODEL"


def resolve_direct_profile(provider: str) -> ProviderProfile:
    """Return the :class:`ProviderProfile` for ``provider``, restricted to
    the two adapters this backend supports.

    Raises :class:`ActorError` (never :class:`ProviderProfileError`) so
    every failure this package's callers see is one exception type -- an
    unknown provider slug, or a known slug this backend cannot drive
    (``bedrock``, ``ollama``), is a loud, non-skippable configuration error
    (a typo or a misunderstanding of what "direct" covers), never a named
    skip.
    """
    try:
        profile = get_profile(provider)
    except ProviderProfileError as exc:
        raise ActorError(str(exc)) from exc
    if profile.adapter not in SUPPORTED_ADAPTERS:
        raise ActorError(
            f"direct actor supports {sorted(SUPPORTED_ADAPTERS)} providers only; "
            f"{provider!r} uses adapter {profile.adapter!r}"
        )
    return profile


class DirectActor:
    """Drives the learner side straight against OpenAI or Anthropic's API."""

    name = "direct"

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        model: ModelEntry,
        api_key: str,
        budget: BudgetGuard | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_output_tokens_per_turn: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_TURN,
        timeout: float = 30.0,
    ) -> None:
        self._profile = profile
        self._model = model
        self._system_prompt = system_prompt
        self._max_output_tokens_per_turn = max_output_tokens_per_turn
        self._budget = budget or BudgetGuard(max_turns=8, max_output_tokens=4000)
        headers = {"Content-Type": "application/json"}
        if profile.adapter == "anthropic_compat":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = _ANTHROPIC_API_VERSION
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=profile.base_url.rstrip("/"), timeout=timeout, headers=headers
        )

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        budget: BudgetGuard | None = None,
        system_prompt: str | None = None,
    ) -> DirectActor:
        """Build from ``STUDYLOOP_ACC_DIRECT_PROVIDER``/``_MODEL`` plus the
        resolved provider's own ``auth_env``.

        Raises :class:`ActorError` if the resolved provider's key is
        missing -- callers should call
        :func:`acceptance.actors.factory.skip_reason` first and skip by
        name instead of reaching this constructor.
        """
        provider = (env.get(ENV_PROVIDER) or DEFAULT_PROVIDER).strip()
        profile = resolve_direct_profile(provider)
        api_key = (env.get(profile.auth_env) or "").strip()
        if not api_key:
            raise ActorError(
                f"DirectActor requires {profile.auth_env} -- call "
                "skip_reason('direct', env=...) before constructing this backend"
            )
        model_id = (env.get(ENV_MODEL) or "").strip()
        try:
            model = get_model(profile, model_id) if model_id else default_model(profile)
        except ProviderProfileError as exc:
            raise ActorError(str(exc)) from exc
        kwargs: dict = {"profile": profile, "model": model, "api_key": api_key, "budget": budget}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        return cls(**kwargs)

    async def converse(
        self,
        mentor: MentorTransport,
        *,
        cancel: asyncio.Event | None = None,
    ) -> ConversationResult:
        return await run_llm_conversation(
            generate=self._generate, mentor=mentor, budget=self._budget, cancel=cancel
        )

    async def _generate(self, history: Sequence[dict[str, str]]) -> tuple[str, TokenUsage]:
        if self._profile.adapter == "anthropic_compat":
            return await self._generate_anthropic(history)
        return await self._generate_openai(history)

    async def _generate_openai(self, history: Sequence[dict[str, str]]) -> tuple[str, TokenUsage]:
        messages = [{"role": "system", "content": self._system_prompt}, *history]
        payload = {
            "model": self._model.id,
            "messages": messages,
            "max_tokens": self._max_output_tokens_per_turn,
        }
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        body = resp.json()
        message = body["choices"][0]["message"]
        content = message.get("content") or ""
        usage_body = body.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_body.get("prompt_tokens"),
            output_tokens=usage_body.get("completion_tokens"),
        )
        return content, usage

    async def _generate_anthropic(
        self, history: Sequence[dict[str, str]]
    ) -> tuple[str, TokenUsage]:
        # Anthropic's Messages API requires a non-empty messages list that
        # starts with a "user" turn -- on the opening turn there is no
        # mentor reply yet to seed it with, so a fixed placeholder stands
        # in. It is never sent to the mentor; it exists only to make the
        # first API call well-formed.
        messages = list(history) or [{"role": "user", "content": "(conversation start)"}]
        payload = {
            "model": self._model.id,
            "system": self._system_prompt,
            "messages": messages,
            "max_tokens": self._max_output_tokens_per_turn,
        }
        resp = await self._client.post("/v1/messages", json=payload)
        resp.raise_for_status()
        body = resp.json()
        content_blocks = body.get("content") or []
        text = "".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
        usage_body = body.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_body.get("input_tokens"),
            output_tokens=usage_body.get("output_tokens"),
        )
        return text, usage

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS_PER_TURN",
    "DEFAULT_PROVIDER",
    "DEFAULT_SYSTEM_PROMPT",
    "ENV_MODEL",
    "ENV_PROVIDER",
    "SUPPORTED_ADAPTERS",
    "DirectActor",
    "resolve_direct_profile",
]
