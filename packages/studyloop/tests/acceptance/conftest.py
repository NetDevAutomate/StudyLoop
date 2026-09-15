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
