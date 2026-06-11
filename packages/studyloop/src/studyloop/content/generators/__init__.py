"""Card generation backends.

This package defines the :class:`CardGenerator` Protocol and a
:func:`get_generator` factory that returns a backend instance based on
``settings.card_generator.backend``.

The Protocol is the seam that lets studyloop swap LLM providers
(Ollama now, LM Studio / LiteLLM / NotebookLM later) without touching
the CLI or the review-loader read path. Any implementation that
produces valid ``FlashcardDeck`` / ``QuizDeck`` pydantic models is a
first-class producer.

Error handling contract
-----------------------

All backends raise :class:`CardGenerationError` on failure. Callers
(CLI, MCP tools) catch this and surface a user-friendly message rather
than letting HTTP / JSON / Pydantic exceptions leak through. Transport
errors, JSON parse errors, and schema validation failures all map to
``CardGenerationError`` with a descriptive message.

The Protocol itself is purely structural -- implementations do not need
to inherit from it, they just need to match the method signatures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from studyloop.content.schemas import FlashcardDeck, PracticeDeck, QuizDeck
    from studyloop.settings import CardGeneratorConfig


class CardGenerationError(RuntimeError):
    """Raised when a generator fails to produce a valid deck.

    Wraps transport errors (Ollama unreachable), parse errors (model
    returned non-JSON), and schema-validation errors (JSON didn't match
    the expected shape). Callers should display ``str(exc)`` to the
    user rather than the underlying exception.
    """


@runtime_checkable
class CardGenerator(Protocol):
    """Protocol for backends that produce flashcards and quizzes.

    Implementations take a markdown source string plus a title and
    return a validated pydantic deck. They do not write to disk --
    callers are responsible for persistence via
    :meth:`FlashcardDeck.write_json` / :meth:`QuizDeck.write_json`.
    """

    def generate_flashcards(self, source: str, title: str) -> FlashcardDeck:
        """Produce a :class:`FlashcardDeck` from a markdown source chunk.

        Args:
            source: Markdown content to turn into flashcards. Typically
                one chapter or one Obsidian-note section.
            title: Human-readable deck title, e.g. the chapter name.

        Returns:
            A validated :class:`FlashcardDeck`. The caller decides
            where/whether to persist it.

        Raises:
            CardGenerationError: On transport failure, invalid JSON, or
                schema-validation failure after all retries exhausted.
        """
        ...

    def generate_quiz(self, source: str, title: str) -> QuizDeck:
        """Produce a :class:`QuizDeck` from a markdown source chunk.

        Args:
            source: Markdown content to turn into a multiple-choice quiz.
            title: Human-readable deck title.

        Returns:
            A validated :class:`QuizDeck`.

        Raises:
            CardGenerationError: As for :meth:`generate_flashcards`.
        """
        ...

    def generate_practice(self, source: str, title: str) -> PracticeDeck:
        """Produce a :class:`PracticeDeck` from a markdown source chunk.

        Practice tasks are hands-on exercises: build, debug, trace, diagram,
        or transfer prompts that create active evidence of understanding.
        """
        ...


def get_generator(config: CardGeneratorConfig) -> CardGenerator:
    """Return a concrete :class:`CardGenerator` for the configured backend.

    Reads ``config.backend`` and returns the matching implementation.
    The only backend supported today is ``"ollama"``; additional
    backends slot in here without interface changes.

    Raises:
        ValueError: If ``config.backend`` is not a known backend name.
    """
    backend = config.backend.lower().strip()
    if backend == "ollama":
        # Local import so importing the package root doesn't pull httpx
        # for users who only use the NotebookLM or MCP paths.
        from studyloop.content.generators.ollama import OllamaGenerator

        return OllamaGenerator(config)
    if backend == "bedrock":
        # Local import so importing the package root doesn't pull boto3
        # for users who only use the Ollama path.
        from studyloop.content.generators.bedrock import BedrockGenerator

        return BedrockGenerator(config)
    if backend == "stub":
        # Test/dogfood-only backend: deterministic, offline, free.
        # Wired in U1 ahead of the real `*_compat` adapters in U1.5.
        from studyloop.content.generators.stub import StubGenerator

        return StubGenerator(config)
    if backend in ("openai_compat", "anthropic_compat"):
        # Pluggable adapter path: registry profile + curated model entry
        # drive a generic adapter. New providers = registry rows, no
        # new code. See content/generators/provider_profiles.py.
        from studyloop.content.generators.provider_profiles import (
            default_model,
            get_model,
            get_profile,
        )

        if not config.provider:
            raise ValueError(
                f"backend={backend!r} requires card_generator.provider "
                "to be set (e.g. 'openrouter', 'gemini', 'anthropic', 'openai')."
            )
        profile = get_profile(config.provider)
        if profile.adapter != backend:
            raise ValueError(
                f"Provider {profile.slug!r} uses adapter {profile.adapter!r}, "
                f"but config has backend={backend!r}. Change one to match."
            )
        model_entry = (
            get_model(profile, config.model) if config.model else default_model(profile)
        )
        if backend == "openai_compat":
            from studyloop.content.generators.openai_compat import OpenAICompatGenerator

            return OpenAICompatGenerator(config, profile, model_entry)
        from studyloop.content.generators.anthropic_compat import (
            AnthropicCompatGenerator,
        )

        return AnthropicCompatGenerator(config, profile, model_entry)
    raise ValueError(
        f"Unknown card_generator.backend: {config.backend!r}. "
        "Supported backends: 'ollama', 'bedrock', 'stub', "
        "'openai_compat', 'anthropic_compat'."
    )


__all__ = ["CardGenerationError", "CardGenerator", "get_generator"]
