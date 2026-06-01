"""Live MVD smoke tests for the provider adapters (U1.5).

These tests hit real LLM providers and burn quota. They are gated by
``@pytest.mark.live_provider`` and excluded from the default run via
``addopts = -m 'not live_provider'`` in ``pyproject.toml``. Opt in with::

    uv run pytest -m live_provider

The MVD policy from the plan:
- ≤ 500 char source (photosynthesis fixture)
- 3 cards / 3 quiz questions per request (lowest count that exercises
  array-of-objects schema validation)
- 2 tests per provider (one flashcard, one quiz)
- Total budget cap < $0.05 across all five providers per full run

Tests skip cleanly when the provider's env var is unset, so an
incomplete `.env` doesn't fail the smoke run.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from studyloop.content.generators import get_generator
from studyloop.content.generators.provider_profiles import (
    PROFILES,
    default_model,
    get_profile,
)
from studyloop.content.schemas import FlashcardDeck, QuizDeck
from studyloop.settings import CardGeneratorConfig

pytestmark = pytest.mark.live_provider


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mvd_source.md"


@pytest.fixture(scope="module")
def mvd_source() -> str:
    text = _FIXTURE_PATH.read_text(encoding="utf-8")
    # Plan-mandated boundary -- keeps live spend predictable.
    assert len(text) <= 500, f"MVD source must stay <=500 chars, got {len(text)}"
    return text


def _provider_params() -> list[Any]:
    """Build one parametrise entry per registered provider.

    Each entry carries the slug + the default cheap-tier model so we
    don't accidentally hit a premium thinking model on a smoke run.
    """
    params = []
    for slug in sorted(PROFILES):
        profile = get_profile(slug)
        entry = default_model(profile)
        params.append(pytest.param(slug, entry.id, profile.adapter, id=f"{slug}:{entry.id}"))
    return params


@pytest.mark.parametrize("provider_slug,model_id,adapter", _provider_params())
def test_flashcards_minimum_viable(
    provider_slug: str, model_id: str, adapter: str, mvd_source: str
) -> None:
    """One real flashcard generation per provider, capped at 3 cards."""
    profile = get_profile(provider_slug)
    if not os.environ.get(profile.auth_env):
        pytest.skip(f"{profile.auth_env} not set; skipping live smoke for {provider_slug}")

    cfg = CardGeneratorConfig(
        backend=adapter,
        provider=provider_slug,
        model=model_id,
        temperature=0.1,
        max_retries=1,
        request_timeout=60.0,
    )
    gen = get_generator(cfg)
    try:
        deck = gen.generate_flashcards(source=mvd_source, title="Photosynthesis basics")
    finally:
        close = getattr(gen, "close", None)
        if close is not None:
            close()

    assert isinstance(deck, FlashcardDeck)
    assert deck.title == "Photosynthesis basics"
    # MVD: 1+ cards is enough to confirm wire shape works. The model
    # is allowed to produce more; we don't enforce an upper bound here
    # because constraining count via prompt is unreliable across
    # providers and that's not the wire-shape signal we're testing.
    assert len(deck.cards) >= 1
    # Content sanity -- the model engaged with the source rather than
    # echoing schema/template noise.
    joined = " ".join(c.front + " " + c.back for c in deck.cards).lower()
    assert any(
        keyword in joined for keyword in ("photo", "chloro", "glucose", "oxygen", "light")
    ), "no photosynthesis-related keyword found in any card -- model ignored source?"


@pytest.mark.parametrize("provider_slug,model_id,adapter", _provider_params())
def test_quiz_minimum_viable(
    provider_slug: str, model_id: str, adapter: str, mvd_source: str
) -> None:
    """One real quiz generation per provider."""
    profile = get_profile(provider_slug)
    if not os.environ.get(profile.auth_env):
        pytest.skip(f"{profile.auth_env} not set; skipping live smoke for {provider_slug}")

    cfg = CardGeneratorConfig(
        backend=adapter,
        provider=provider_slug,
        model=model_id,
        temperature=0.1,
        max_retries=1,
        request_timeout=60.0,
    )
    gen = get_generator(cfg)
    try:
        deck = gen.generate_quiz(source=mvd_source, title="Photosynthesis basics")
    finally:
        close = getattr(gen, "close", None)
        if close is not None:
            close()

    assert isinstance(deck, QuizDeck)
    assert deck.title == "Photosynthesis basics"
    assert len(deck.questions) >= 1
    # Schema invariant -- exactly one correct answer per question is
    # already validated by pydantic; this assertion is here as a smoke-
    # readable proof that the model produced answerable questions.
    for q in deck.questions:
        correct = sum(1 for opt in q.answer_options if opt.is_correct)
        assert correct == 1
