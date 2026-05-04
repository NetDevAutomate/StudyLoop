"""Tests for :func:`generate_concurrently` in ``content.generators.runner``.

Uses a hand-rolled fake generator (no HTTP, no boto3) so the tests are
deterministic. The concurrency itself is verified via thread-id
observation and timing: if ``max_workers=4`` runs 4 tasks that each
sleep 100 ms, total wall time should be ~100 ms, not ~400 ms.
"""

from __future__ import annotations

import threading
import time

import pytest

pydantic = pytest.importorskip("pydantic")

from studyctl.content.generators import CardGenerationError  # noqa: E402
from studyctl.content.generators.runner import (  # noqa: E402
    GenerationResult,
    GenerationTask,
    generate_concurrently,
)
from studyctl.content.schemas import (  # noqa: E402
    FlashcardDeck,
    FlashcardItem,
    QuizDeck,
    QuizOption,
    QuizQuestion,
)


class _FakeGenerator:
    """Minimal :class:`CardGenerator` for runner tests.

    Records which thread each call ran on (to verify parallelism) and
    how long each call took (optional ``delay`` lets tests observe
    overlap). Failure cases accept an optional ``fail_titles`` set --
    any task whose title is in that set raises ``CardGenerationError``.
    """

    def __init__(
        self,
        *,
        delay: float = 0.0,
        fail_titles: set[str] | None = None,
    ) -> None:
        self.delay = delay
        self.fail_titles = fail_titles or set()
        self.thread_ids: list[int] = []
        self._lock = threading.Lock()

    def _record_thread(self) -> None:
        with self._lock:
            self.thread_ids.append(threading.get_ident())

    def generate_flashcards(self, source: str, title: str) -> FlashcardDeck:
        self._record_thread()
        if title in self.fail_titles:
            raise CardGenerationError(f"forced failure for {title}")
        if self.delay:
            time.sleep(self.delay)
        return FlashcardDeck(
            title=title,
            cards=[FlashcardItem(front=f"Q:{title}", back=f"A:{source[:20]}")],
        )

    def generate_quiz(self, source: str, title: str) -> QuizDeck:
        self._record_thread()
        if title in self.fail_titles:
            raise CardGenerationError(f"forced failure for {title}")
        if self.delay:
            time.sleep(self.delay)
        return QuizDeck(
            title=title,
            questions=[
                QuizQuestion(
                    question="Q?",
                    answer_options=[
                        QuizOption(text="a", is_correct=True, rationale="right"),
                        QuizOption(text="b", is_correct=False, rationale="wrong"),
                    ],
                )
            ],
        )


def _make_tasks(n: int, kind: str = "flashcards") -> list[GenerationTask]:
    return [
        GenerationTask(
            identifier=f"id-{i}",
            kind=kind,  # type: ignore[arg-type]
            source=f"source-{i}",
            title=f"title-{i}",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Correctness
# ---------------------------------------------------------------------------


class TestResultOrdering:
    def test_empty_task_list_returns_empty(self) -> None:
        gen = _FakeGenerator()
        assert generate_concurrently(gen, []) == []  # type: ignore[arg-type]

    def test_results_preserve_input_order(self) -> None:
        gen = _FakeGenerator()
        tasks = _make_tasks(5)
        results = generate_concurrently(gen, tasks, max_workers=4)  # type: ignore[arg-type]
        assert [r.task.identifier for r in results] == [t.identifier for t in tasks]
        assert all(r.ok for r in results)
        assert all(r.deck is not None for r in results)

    def test_task_kind_routes_to_correct_method(self) -> None:
        gen = _FakeGenerator()
        tasks = [
            GenerationTask(identifier="fc", kind="flashcards", source="s", title="t-fc"),
            GenerationTask(identifier="qz", kind="quiz", source="s", title="t-qz"),
        ]
        results = generate_concurrently(gen, tasks, max_workers=2)  # type: ignore[arg-type]
        # First result is the flashcard, second is the quiz (order preserved).
        assert isinstance(results[0].deck, FlashcardDeck)
        assert isinstance(results[1].deck, QuizDeck)


# ---------------------------------------------------------------------------
# Parallelism
# ---------------------------------------------------------------------------


class TestParallelism:
    def test_max_workers_4_runs_tasks_in_parallel(self) -> None:
        """4 tasks x 200 ms each should finish well under the serial 0.8 s."""
        gen = _FakeGenerator(delay=0.2)
        tasks = _make_tasks(4)

        t0 = time.monotonic()
        results = generate_concurrently(gen, tasks, max_workers=4)  # type: ignore[arg-type]
        elapsed = time.monotonic() - t0

        # Serial would be ~0.8 s; parallel with 4 workers is ~0.2-0.3 s
        # but leave generous head-room for loaded-CI thread-scheduling
        # jitter. The thread-id diversity assertion below is the more
        # reliable witness of parallelism.
        assert elapsed < 0.75, f"expected << 0.8 s, got {elapsed:.3f} s"
        assert all(r.ok for r in results)
        # Multiple distinct thread IDs is the primary witness of parallelism.
        assert len(set(gen.thread_ids)) >= 2

    def test_max_workers_1_runs_serially(self) -> None:
        """workers=1 is the knob for debugging; tasks run one after another."""
        gen = _FakeGenerator(delay=0.05)
        tasks = _make_tasks(4)

        t0 = time.monotonic()
        results = generate_concurrently(gen, tasks, max_workers=1)  # type: ignore[arg-type]
        elapsed = time.monotonic() - t0

        # 4 x 0.05 s = 0.2 s minimum; give it headroom.
        assert elapsed >= 0.18
        assert all(r.ok for r in results)
        # All tasks run on the same worker thread.
        assert len(set(gen.thread_ids)) == 1


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


class TestFailureHandling:
    def test_one_task_failure_does_not_cancel_others(self) -> None:
        gen = _FakeGenerator(fail_titles={"title-1"})
        tasks = _make_tasks(4)
        results = generate_concurrently(gen, tasks, max_workers=2)  # type: ignore[arg-type]

        # Task at index 1 fails; others succeed.
        assert [r.ok for r in results] == [True, False, True, True]
        assert isinstance(results[1].error, CardGenerationError)
        assert "title-1" in str(results[1].error)
        # Successful tasks produced decks.
        for i in (0, 2, 3):
            assert results[i].deck is not None
            assert results[i].error is None

    def test_all_failures_produce_error_results_not_exception(self) -> None:
        gen = _FakeGenerator(fail_titles={f"title-{i}" for i in range(3)})
        tasks = _make_tasks(3)
        results = generate_concurrently(gen, tasks, max_workers=2)  # type: ignore[arg-type]
        # Runner collects errors into GenerationResult, doesn't re-raise.
        assert all(not r.ok for r in results)
        assert all(r.error is not None for r in results)
        assert all(r.deck is None for r in results)


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


class TestOnCompleteCallback:
    def test_on_complete_called_once_per_task(self) -> None:
        gen = _FakeGenerator()
        tasks = _make_tasks(5)
        seen: list[GenerationResult] = []
        generate_concurrently(gen, tasks, max_workers=3, on_complete=seen.append)  # type: ignore[arg-type]
        assert len(seen) == 5
        # Every task appears exactly once (may be out of order).
        assert {r.task.identifier for r in seen} == {t.identifier for t in tasks}

    def test_on_complete_sees_failures_too(self) -> None:
        gen = _FakeGenerator(fail_titles={"title-2"})
        tasks = _make_tasks(3)
        seen: list[GenerationResult] = []
        generate_concurrently(gen, tasks, max_workers=2, on_complete=seen.append)  # type: ignore[arg-type]
        failures = [r for r in seen if not r.ok]
        assert len(failures) == 1
        assert failures[0].task.title == "title-2"
