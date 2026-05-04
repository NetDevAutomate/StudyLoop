"""Concurrent execution helper for multi-source card generation.

Given a :class:`CardGenerator` and multiple ``(source, title)`` pairs,
run them in parallel using a thread pool. This is a backend-agnostic
helper: any implementation of the Protocol works here, but the
concurrency benefit is backend-shaped:

- **Bedrock**: one HTTP request per chunk, all independent. Concurrency
  directly multiplies throughput up to the account's TPM limit. With
  ``max_workers=4`` and per-call latency ~60-90 s, a 3-file acceptance
  run drops from ~5 min (serial) to ~90 s (parallel).
- **Ollama (local)**: the Ollama server itself serialises decoding on
  the single GPU process. Parallel HTTP calls from the client don't
  translate to parallel decode; you still pay the sum of per-call
  latencies, minus a small overlap for HTTP + validation. Safe to
  call, just less dramatic benefit.

Threads, not asyncio
--------------------

httpx and boto3 are both sync-first. Wrapping them in an async adapter
adds complexity for no gain at this QPS. :class:`ThreadPoolExecutor`
is the right tool.

Failure model
-------------

Each task runs independently. If one raises :class:`CardGenerationError`,
the other workers continue. The result list preserves the mapping from
input index to either a :class:`FlashcardDeck` / :class:`QuizDeck` or an
exception -- callers decide how to surface partial failures.

Networking analogy
------------------

The thread pool is an **ECMP hash bucket** of size N. Each incoming
"flow" (source file) hashes into one of the buckets and stays there
until completion; there is no in-flight reordering. The fallback-on-
throttle path inside the Bedrock backend is orthogonal -- it is
**per-flow active/standby** at the request level. Compose the two and
you get ECMP-of-active/standby, which is the right model for a
workload with bursty capacity and predictable per-flow completion.
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from studyctl.content.generators import CardGenerationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from studyctl.content.generators import CardGenerator
    from studyctl.content.schemas import FlashcardDeck, QuizDeck


@dataclass(frozen=True, slots=True)
class GenerationTask:
    """One unit of work for the concurrent runner.

    ``identifier`` is an opaque key the caller uses to look up the
    result (typically a filename slug). ``kind`` selects the generator
    method; ``source`` and ``title`` flow through to it.
    """

    identifier: str
    kind: Literal["flashcards", "quiz"]
    source: str
    title: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Outcome of one task. Exactly one of ``deck`` or ``error`` is set."""

    task: GenerationTask
    deck: FlashcardDeck | QuizDeck | None
    error: CardGenerationError | None
    elapsed_s: float

    @property
    def ok(self) -> bool:
        return self.error is None


def generate_concurrently(
    generator: CardGenerator,
    tasks: list[GenerationTask],
    *,
    max_workers: int = 4,
    on_complete: Callable[[GenerationResult], None] | None = None,
) -> list[GenerationResult]:
    """Run ``tasks`` concurrently on ``generator`` using a thread pool.

    Args:
        generator: Any :class:`CardGenerator` implementation. The same
            instance is shared across threads; the concrete backends
            are thread-safe (``httpx.Client`` and ``boto3.client`` are
            both safe for concurrent use from threads).
        tasks: List of :class:`GenerationTask` to run. Empty list
            returns an empty result list without starting the pool.
        max_workers: Thread-pool size. ``1`` runs serially (useful for
            debugging). Default ``4`` matches the Bedrock per-account
            concurrency sweet spot.
        on_complete: Optional callback invoked once per task as it
            completes (in arbitrary order). Useful for live progress
            reporting in CLIs.

    Returns:
        One :class:`GenerationResult` per input task, in the SAME ORDER
        as ``tasks``. Tasks that failed have ``error`` set; tasks that
        succeeded have ``deck`` set.

    Thread-safety invariant:
        The caller MUST NOT call ``generator.close()`` until this
        function returns. Concurrent ``close()`` while worker threads
        are mid-request is undefined behaviour for both
        :class:`httpx.Client` (Ollama) and boto3 clients (Bedrock).
        The ``ThreadPoolExecutor`` context manager used internally
        guarantees all futures complete before this function returns,
        so the typical usage pattern ``with generator as gen: results
        = generate_concurrently(gen, ...)`` is safe.
    """
    if not tasks:
        return []

    results: list[GenerationResult | None] = [None] * len(tasks)

    def _run_one(idx: int, task: GenerationTask) -> tuple[int, GenerationResult]:
        t0 = time.monotonic()
        try:
            if task.kind == "flashcards":
                deck = generator.generate_flashcards(source=task.source, title=task.title)
            else:
                deck = generator.generate_quiz(source=task.source, title=task.title)
            elapsed = time.monotonic() - t0
            return idx, GenerationResult(task=task, deck=deck, error=None, elapsed_s=elapsed)
        except CardGenerationError as exc:
            elapsed = time.monotonic() - t0
            return idx, GenerationResult(task=task, deck=None, error=exc, elapsed_s=elapsed)

    workers = max(1, max_workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_run_one, i, t): i for i, t in enumerate(tasks)}
        for future in concurrent.futures.as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            if on_complete is not None:
                on_complete(result)

    final: list[GenerationResult] = []
    for r in results:
        assert r is not None
        final.append(r)
    return final


__all__ = ["GenerationResult", "GenerationTask", "generate_concurrently"]
