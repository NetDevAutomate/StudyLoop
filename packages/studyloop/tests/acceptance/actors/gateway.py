"""``ACTOR=gateway`` -- the openai-compatible client at the LiteLLM base URL.

This is the owner's own setup (``docs/contributing.md``'s "AI usage, and
models through a LiteLLM gateway" section, ``~/.claude/skills/litellm-gateway/``):
one local proxy, one key (``LITELLM_API_KEY`` -- already a name this repo
scrubs from every agent child, see ``session/child_env.py``), many model
aliases behind it.

Deliberately NOT a ``provider_profiles`` row. ``docs/contributing.md``
already names the reason: "today a row's base URL is fixed in the
registry, so a per-machine proxy address needs an environment override
that does not exist yet". Adding a `litellm` profile row here would either
hard-code a base URL that is wrong on the next machine, or require solving
that per-machine-override gap as a side effect of this lane -- out of
scope. Reads its base URL, key, and model straight from the environment
instead; see :meth:`GatewayActor.from_env`.

HTTP shape mirrors ``content/generators/openai_compat.py`` (Chat
Completions, ``Authorization: Bearer``) but calls plain chat, not the
forced-tool-call deck-generation shape -- council D-15: never reuse the
card-generation semantics, only the wire-protocol pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from acceptance.actors._loop import run_llm_conversation
from acceptance.actors.budget import BudgetGuard
from acceptance.actors.protocol import ActorError, ConversationResult, TokenUsage

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping, Sequence

    from acceptance.actors.protocol import MentorTransport

#: The local LiteLLM proxy's default address (matches
#: ``~/.claude/skills/litellm-gateway/SKILL.md``'s documented default).
DEFAULT_BASE_URL = "http://127.0.0.1:4000"

DEFAULT_SYSTEM_PROMPT = (
    "You are a curious student in a tutoring conversation. Given the "
    "tutor's latest message (or, on the first turn, nothing yet), reply as "
    "the student would: a short, specific question or answer, one to three "
    "plain-text sentences. Never mention that you are an AI or a test."
)

#: A conservative per-turn cap: this is a TEST TOOL driving a conversation
#: to prove plumbing, not a product feature that needs long student
#: replies. Keeping this small keeps the "documents estimated cost per
#: run" promise (council D-15) honest and cheap by construction.
DEFAULT_MAX_OUTPUT_TOKENS_PER_TURN = 200

#: The env vars this backend reads. Named here once so ``factory.skip_reason``
#: and this module's own ``from_env`` never drift apart.
ENV_API_KEY = "LITELLM_API_KEY"  # pragma: allowlist secret - a variable NAME, not a key
ENV_BASE_URL = "LITELLM_BASE_URL"
ENV_MODEL = "STUDYLOOP_ACC_GATEWAY_MODEL"


class GatewayActor:
    """Drives the learner side through the owner's local LiteLLM proxy.

    Estimated cost per run: ``max_turns`` * (a short prompt + up to
    ``max_output_tokens_per_turn`` completion tokens) against whatever
    ``model`` prices at the gateway -- see
    ``docs/acceptance-testing.md``'s ACTOR matrix for the per-actor cost
    warning this backend documents.
    """

    name = "gateway"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        budget: BudgetGuard | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_output_tokens_per_turn: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_TURN,
        timeout: float = 30.0,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt
        self._max_output_tokens_per_turn = max_output_tokens_per_turn
        self._budget = budget or BudgetGuard(max_turns=8, max_output_tokens=4000)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        budget: BudgetGuard | None = None,
        system_prompt: str | None = None,
    ) -> GatewayActor:
        """Build from ``LITELLM_API_KEY``/``LITELLM_BASE_URL``/``STUDYLOOP_ACC_GATEWAY_MODEL``.

        Raises :class:`ActorError` if a required variable is missing --
        callers (the factory, acceptance conftest fixtures) are expected to
        call :func:`acceptance.actors.factory.skip_reason` FIRST and skip by
        name; this constructor is the "we already decided to proceed" path.
        """
        api_key = (env.get(ENV_API_KEY) or "").strip()
        model = (env.get(ENV_MODEL) or "").strip()
        pairs = ((ENV_API_KEY, api_key), (ENV_MODEL, model))
        missing = [name for name, value in pairs if not value]
        if missing:
            raise ActorError(
                f"GatewayActor requires {', '.join(missing)} -- call "
                "skip_reason('gateway', env=...) before constructing this backend"
            )
        base_url = (env.get(ENV_BASE_URL) or DEFAULT_BASE_URL).strip()
        kwargs: dict = {"base_url": base_url, "api_key": api_key, "model": model, "budget": budget}
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
        messages = [{"role": "system", "content": self._system_prompt}, *history]
        payload = {
            "model": self._model,
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

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_OUTPUT_TOKENS_PER_TURN",
    "DEFAULT_SYSTEM_PROMPT",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "GatewayActor",
]
