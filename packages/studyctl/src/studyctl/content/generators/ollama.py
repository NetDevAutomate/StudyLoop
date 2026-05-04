"""Ollama-backed :class:`CardGenerator`.

Calls Ollama's ``/api/chat`` endpoint with the ``format`` parameter set
to the pydantic JSON schema so the model is constrained to produce
schema-conformant output.

Failure model
-------------

- Transport errors (Ollama unreachable, timeout) → immediate
  :class:`CardGenerationError`; no retry, because the next call will
  fail the same way.
- Parse / validation errors (model returned malformed JSON or JSON
  that doesn't match the schema) → retry up to ``max_retries`` times,
  each time feeding the error back as a follow-up user turn so the
  model can self-correct. If retries exhaust, raise
  :class:`CardGenerationError`.

Networking analogy
------------------

This is the same shape as **BGP session keepalive vs. NLRI validation**:
TCP RST (transport) kills the session immediately -- no retry on the
same peer. Malformed NLRI (parse/validation) gets rejected, but the
session stays up; the peer re-advertises. Here Ollama is the peer:
transport failure aborts, content failure retries on the same
connection.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import ValidationError

from studyctl.content.generators import CardGenerationError
from studyctl.content.generators.prompts import (
    FLASHCARD_SYSTEM_PROMPT,
    FLASHCARD_USER_PROMPT_TEMPLATE,
    QUIZ_SYSTEM_PROMPT,
    QUIZ_USER_PROMPT_TEMPLATE,
)
from studyctl.content.schemas import (
    FlashcardDeck,
    QuizDeck,
    flashcard_deck_json_schema,
    quiz_deck_json_schema,
)

if TYPE_CHECKING:
    from studyctl.settings import CardGeneratorConfig


# Type alias for either deck type; keeps the generic helper type-clean.
_DECK_MODELS = FlashcardDeck | QuizDeck


class OllamaGenerator:
    """Card generator backed by a local Ollama instance.

    Satisfies the :class:`studyctl.content.generators.CardGenerator`
    Protocol structurally (duck-typed); does not inherit from it.
    """

    def __init__(self, config: CardGeneratorConfig) -> None:
        self._config = config
        self._ollama = config.ollama
        self._client = httpx.Client(
            base_url=self._ollama.base_url,
            timeout=httpx.Timeout(config.request_timeout),
        )

    def __enter__(self) -> OllamaGenerator:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        self._client.close()

    # ------------------------------------------------------------------
    # Public Protocol surface
    # ------------------------------------------------------------------

    def generate_flashcards(self, source: str, title: str) -> FlashcardDeck:
        user_prompt = FLASHCARD_USER_PROMPT_TEMPLATE.format(title=title, source=source)
        deck = self._generate(
            system_prompt=FLASHCARD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=flashcard_deck_json_schema(),
            model_cls=FlashcardDeck,
        )
        # If the model produced a different title, overwrite with the
        # caller's title -- generators are responsible for the content,
        # callers own the deck identity.
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    def generate_quiz(self, source: str, title: str) -> QuizDeck:
        user_prompt = QUIZ_USER_PROMPT_TEMPLATE.format(title=title, source=source)
        deck = self._generate(
            system_prompt=QUIZ_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=quiz_deck_json_schema(),
            model_cls=QuizDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate[T: _DECK_MODELS](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        model_cls: type[T],
    ) -> T:
        """Call Ollama with retry-on-parse-failure semantics.

        Returns a validated model of ``model_cls`` or raises
        :class:`CardGenerationError`.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: str | None = None

        for attempt in range(self._config.max_retries + 1):
            raw = self._chat_once(messages=messages, schema=schema)

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                last_error = f"Response was not valid JSON: {exc}"
            else:
                try:
                    return model_cls.model_validate(parsed)
                except ValidationError as exc:
                    last_error = f"JSON did not match schema: {exc.errors()!r}"

            # Feed the error back as a correction turn so the model can
            # self-correct on the next attempt.
            if attempt < self._config.max_retries:
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            f"That response was invalid. {last_error} "
                            "Return only the JSON object conforming to the schema."
                        ),
                    },
                ]

        raise CardGenerationError(
            f"Ollama failed to produce valid output after "
            f"{self._config.max_retries + 1} attempts. Last error: {last_error}"
        )

    def _chat_once(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
    ) -> str:
        """Make a single ``/api/chat`` call and return the model's raw content.

        Transport failures raise :class:`CardGenerationError` with a
        user-friendly message. HTTP non-2xx responses are treated as
        transport failures (no point retrying a 404 model-not-found).
        """
        payload = {
            "model": self._ollama.model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "options": {"temperature": self._config.temperature},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise CardGenerationError(
                f"Ollama returned HTTP {exc.response.status_code} "
                f"(model={self._ollama.model!r}, url={self._ollama.base_url}). "
                f"Body: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise CardGenerationError(
                f"Could not reach Ollama at {self._ollama.base_url}: {exc}. "
                f"Is `ollama serve` running? Try `studyctl doctor`."
            ) from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise CardGenerationError(
                f"Ollama returned non-JSON response (status {response.status_code}): "
                f"{response.text[:500]}"
            ) from exc
        message = data.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise CardGenerationError(f"Ollama response missing string 'message.content': {data!r}")
        content = message["content"]
        if not isinstance(content, str):
            raise CardGenerationError(f"Ollama response missing string 'message.content': {data!r}")
        return content


__all__ = ["OllamaGenerator"]
