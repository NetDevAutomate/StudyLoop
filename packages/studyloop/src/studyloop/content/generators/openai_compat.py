"""OpenAI Chat Completions-compatible :class:`CardGenerator`.

Covers any provider that speaks the OpenAI Chat Completions API with
``tool_choice``: OpenAI itself, OpenRouter, Google Gemini's
``/v1beta/openai/`` endpoint, and any future "we host an OpenAI-compat
API" service. The differences are entirely:

- ``base_url`` (registry data)
- ``Authorization: Bearer ${env[auth_env]}`` (registry data)
- The model id sent in the request body (registry data)

So one class drives all of them. Spec-specific quirks (message format,
tool-result shape, retry classification) live here; provider-specific
data lives in :mod:`provider_profiles`.

Why httpx
---------

The existing Ollama backend uses ``httpx.Client`` -- staying consistent
gives us shared HTTP timeouts, transport-error semantics, and easy
``respx``-based test stubbing. The OpenAI Python SDK would also work
but adds a dependency and an SDK abstraction we don't need (we're
making one specific call shape).

Tool-use shape
--------------

We mirror :class:`BedrockGenerator`'s pattern: send the deck JSON
schema as a function tool, force the model to call exactly that tool
via ``tool_choice``, then parse the tool-call arguments into the
pydantic model. If validation fails, retry with the validation error
in a correction turn (see :mod:`._retry`).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from studyloop.content.generators import CardGenerationError
from studyloop.content.generators._retry import CallContext, call_with_correction
from studyloop.content.generators.prompts import (
    FLASHCARD_SYSTEM_PROMPT,
    FLASHCARD_USER_PROMPT_TEMPLATE,
    QUIZ_SYSTEM_PROMPT,
    QUIZ_USER_PROMPT_TEMPLATE,
)
from studyloop.content.schemas import (
    FlashcardDeck,
    QuizDeck,
    flashcard_deck_json_schema,
    quiz_deck_json_schema,
)

if TYPE_CHECKING:
    from studyloop.content.generators.provider_profiles import (
        ModelEntry,
        ProviderProfile,
    )
    from studyloop.settings import CardGeneratorConfig


_FLASHCARD_TOOL_NAME = "emit_flashcard_deck"
_QUIZ_TOOL_NAME = "emit_quiz_deck"

# Reasoning models (o1/o3, qwq) take much longer than chat models.
# Multiply the configured timeout for thinking-flagged entries.
_THINKING_TIMEOUT_MULT = 3.0


class OpenAICompatGenerator:
    """Card generator backed by any OpenAI Chat Completions-compatible API.

    Configured via a :class:`ProviderProfile` (base URL, auth env var,
    model list) plus the selected :class:`ModelEntry`.
    """

    def __init__(
        self,
        config: CardGeneratorConfig,
        profile: ProviderProfile,
        model: ModelEntry,
    ) -> None:
        self._config = config
        self._profile = profile
        self._model = model
        self._api_key = self._read_api_key()
        timeout = self._effective_timeout()
        self._client = httpx.Client(
            base_url=profile.base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenAICompatGenerator:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # CardGenerator Protocol
    # ------------------------------------------------------------------

    def generate_flashcards(self, source: str, title: str) -> FlashcardDeck:
        deck = self._generate(
            system_prompt=FLASHCARD_SYSTEM_PROMPT,
            user_prompt=FLASHCARD_USER_PROMPT_TEMPLATE.format(title=title, source=source),
            tool_name=_FLASHCARD_TOOL_NAME,
            tool_description="Emit a flashcard deck matching the provided JSON schema.",
            schema=flashcard_deck_json_schema(),
            model_cls=FlashcardDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    def generate_quiz(self, source: str, title: str) -> QuizDeck:
        deck = self._generate(
            system_prompt=QUIZ_SYSTEM_PROMPT,
            user_prompt=QUIZ_USER_PROMPT_TEMPLATE.format(title=title, source=source),
            tool_name=_QUIZ_TOOL_NAME,
            tool_description="Emit a multiple-choice quiz deck matching the provided JSON schema.",
            schema=quiz_deck_json_schema(),
            model_cls=QuizDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_api_key(self) -> str:
        # Resolution order (encrypted store -> env var -> None) lives in
        # secrets.get_secret; call it so a key added via the Generate panel
        # (encrypted store) is honoured, not just one exported in the shell.
        from studyloop.secrets import get_secret

        key = (get_secret(self._profile.slug) or "").strip()
        if not key:
            raise CardGenerationError(
                f"{self._profile.label} requires an API key. Add it in the web "
                f"Generate panel (stored encrypted), or set {self._profile.auth_env} "
                f"in your shell env / project-root .env file."
            )
        return key

    def _effective_timeout(self) -> float:
        base = self._config.request_timeout
        return base * _THINKING_TIMEOUT_MULT if self._model.thinking else base

    def _generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        schema: dict[str, Any],
        model_cls: type[FlashcardDeck] | type[QuizDeck],
    ) -> Any:
        # Initial messages -- the assistant's bad reply (if any) plus the
        # user-side correction turn are appended on each retry attempt
        # via ``history_extension``.
        base_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": schema,
                },
            }
        ]
        tool_choice = {"type": "function", "function": {"name": tool_name}}

        def call(ctx: CallContext) -> tuple[Any, list[dict[str, Any]]]:
            messages = list(base_messages) + list(ctx.history_extension)
            if ctx.last_error is not None:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"The previous tool call did not validate against the schema: "
                            f"{ctx.last_error}. Re-emit a corrected payload that conforms."
                        ),
                    }
                )

            payload = {
                "model": self._model.id,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "temperature": self._config.temperature,
            }
            resp = self._post_chat_completions(payload)
            tool_payload, assistant_turn = self._extract_tool_payload(resp, tool_name)
            new_history = [*list(ctx.history_extension), assistant_turn]
            if ctx.last_error is not None:
                # Mirror the correction turn we appended above.
                new_history.append(
                    {
                        "role": "user",
                        "content": (
                            f"The previous tool call did not validate against the schema: "
                            f"{ctx.last_error}. Re-emit a corrected payload that conforms."
                        ),
                    }
                )
            return tool_payload, new_history

        return call_with_correction(
            model_cls=model_cls,
            max_retries=self._config.max_retries,
            call_fn=call,
        )

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise CardGenerationError(f"{self._profile.label} request failed: {exc!r}") from exc

        if r.status_code >= 400:
            # Truncate body to avoid log spam from providers that echo the
            # entire prompt on error.
            body = r.text[:500]
            raise CardGenerationError(
                f"{self._profile.label} returned HTTP {r.status_code}: {body}"
            )
        try:
            return r.json()
        except ValueError as exc:
            raise CardGenerationError(
                f"{self._profile.label} returned non-JSON body: {r.text[:200]!r}"
            ) from exc

    def _extract_tool_payload(
        self, resp: dict[str, Any], expected_tool_name: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Pull the tool-call arguments out of an OpenAI Chat Completions response.

        Returns ``(arguments_dict, assistant_message_to_append)``. The
        second element preserves the model's reply for the
        correction-turn history if validation fails.
        """
        try:
            choice = resp["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CardGenerationError(
                f"{self._profile.label} response missing choices/message: {json.dumps(resp)[:300]}"
            ) from exc

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            raise CardGenerationError(
                f"{self._profile.label} response missing tool_calls "
                f"(expected {expected_tool_name!r}). "
                f"Content was: {message.get('content', '')[:200]!r}"
            )

        call = tool_calls[0]
        fn = call.get("function") or {}
        if fn.get("name") != expected_tool_name:
            raise CardGenerationError(
                f"{self._profile.label} called wrong tool: got {fn.get('name')!r}, "
                f"expected {expected_tool_name!r}"
            )

        raw_args = fn.get("arguments")
        if raw_args is None:
            raise CardGenerationError(f"{self._profile.label} tool_call missing arguments")
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise CardGenerationError(
                    f"{self._profile.label} tool arguments not valid JSON: {raw_args[:200]!r}"
                ) from exc
        else:
            args = raw_args

        return args, message


__all__ = ["OpenAICompatGenerator"]
