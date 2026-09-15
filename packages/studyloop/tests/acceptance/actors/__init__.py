"""LearnerActor: the pluggable learner side of an acceptance conversation.

Council D-15 (unanimous): ``CardGenerator`` is a FLASHCARD protocol and must
never be reused for conversation. This package defines a separate,
test-side :class:`~.protocol.LearnerActor` Protocol -- same repo idiom as
``CardGenerator`` (a ``runtime_checkable`` Protocol plus a factory), but its
own shape: async/cancellable, a normalized transcript, honest "unknown"
token accounting, and an explicit termination outcome.

Four backends implement it, selected by ``STUDYLOOP_ACC_ACTOR``
(see :mod:`.factory` and ``docs/acceptance-testing.md``):

- ``scripted`` (:mod:`.scripted`) -- B1's deterministic, CI-safe default.
- ``gateway`` (:mod:`.gateway`) -- the openai-compatible client at the
  owner's local LiteLLM proxy.
- ``direct`` (:mod:`.direct`) -- a plain OpenAI/Anthropic HTTP client, for
  contributors without the gateway.
- ``harness`` (:mod:`.harness`) -- a second harness instance plays the
  learner over its own, isolated tmux socket (council D-11).

The mentor side is never simulated in a live acceptance test (council
D-16) -- these backends only ever produce the LEARNER's turns.
"""

from __future__ import annotations
