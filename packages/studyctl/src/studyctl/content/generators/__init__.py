"""Card generation backends.

This package defines the :class:`CardGenerator` Protocol and a
:func:`get_generator` factory that returns a backend instance based on
``settings.card_generator.backend``.

The Protocol is the seam that lets studyctl swap LLM providers
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
    from studyctl.content.schemas import FlashcardDeck, QuizDeck
    from studyctl.settings import CardGeneratorConfig


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
        from studyctl.content.generators.ollama import OllamaGenerator

        return OllamaGenerator(config)
    raise ValueError(
        f"Unknown card_generator.backend: {config.backend!r}. Supported backends: 'ollama'."
    )


__all__ = ["CardGenerationError", "CardGenerator", "get_generator"]
