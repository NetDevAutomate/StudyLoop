"""Gate + isolation fixtures shared by every test under tests/acceptance/.

Autouse, function-scoped skip guard: nothing under this directory runs
without ``STUDYLOOP_ACC=1`` (the AWS Terraform Provider ``TF_ACC`` analogy
the owner asked for). Missing/unknown ``STUDYLOOP_ACC_HARNESS`` or
``STUDYLOOP_ACC_ACTOR`` values fail loudly once opted in (council D-13) —
they never silently no-op. See docs/acceptance-testing.md.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from studyloop.harnesses import RELEASE_HARNESSES

from .isolation import create_scratch_environment, sweep_scratch

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from .isolation import ScratchEnv

#: ACTOR=scripted is the only backend B1 implements (D-16 scoping). B3 adds
#: gateway/direct/harness behind the same env var; extend this set there.
KNOWN_ACTORS = frozenset({"scripted"})

_ACC_ENV = "STUDYLOOP_ACC"
_HARNESS_ENV = "STUDYLOOP_ACC_HARNESS"
_ACTOR_ENV = "STUDYLOOP_ACC_ACTOR"


def selected_harnesses() -> tuple[str, ...]:
    """Parse ``STUDYLOOP_ACC_HARNESS`` — a comma list, default ALL SIX (O-7)."""
    raw = os.environ.get(_HARNESS_ENV, "").strip()
    if not raw:
        return tuple(RELEASE_HARNESSES)
    return tuple(h.strip() for h in raw.split(",") if h.strip())


def selected_actor() -> str:
    """Parse ``STUDYLOOP_ACC_ACTOR`` — default ``scripted``, the CI-safe actor."""
    return os.environ.get(_ACTOR_ENV, "scripted").strip() or "scripted"


def require_harness(harness: str) -> None:
    """Named-skip a harness-specific acceptance test that was not selected.

    ``STUDYLOOP_ACC_HARNESS`` is parsed and validated (see
    :func:`selected_harnesses` and the ``_acceptance_gate`` fixture above)
    but nothing previously acted on the selection: a harness-specific lane
    test ran regardless of which harnesses were selected. Call this at the
    top of a lane test (or, better, from an autouse per-module fixture, so
    it runs before any other fixture in that test builds a scratch env or a
    browser context) to turn "not selected" into a named skip rather than
    an unconditionally-live run — e.g. ``STUDYLOOP_ACC_HARNESS=codex`` must
    never start a real, billed Kiro session it was not asked to select.
    """
    selected = selected_harnesses()
    if harness not in selected:
        pytest.skip(f"{harness} not selected via {_HARNESS_ENV} (selected: {', '.join(selected)})")


@pytest.fixture(autouse=True)
def _acceptance_gate() -> None:
    if os.environ.get(_ACC_ENV) != "1":
        pytest.skip(f"acceptance tests require {_ACC_ENV}=1 (see docs/acceptance-testing.md)")

    unknown_harnesses = set(selected_harnesses()) - set(RELEASE_HARNESSES)
    if unknown_harnesses:
        pytest.fail(
            f"unknown {_HARNESS_ENV} value(s): {sorted(unknown_harnesses)}; "
            f"known harnesses: {sorted(RELEASE_HARNESSES)}"
        )

    actor = selected_actor()
    if actor not in KNOWN_ACTORS:
        pytest.fail(
            f"unknown {_ACTOR_ENV} value: {actor!r}; known actors: "
            f"{sorted(KNOWN_ACTORS)} (gateway/direct/harness ship in a later lane)"
        )


@pytest.fixture()
def scratch_env(tmp_path: Path) -> Generator[ScratchEnv, None, None]:
    """A fresh, guard-swept scratch world for one acceptance test.

    Swept in teardown even when the test body fails — the guard runs on
    every exit path, never only the happy one.
    """
    scratch = create_scratch_environment(tmp_path)
    try:
        yield scratch
    finally:
        sweep_scratch(scratch)
