"""Gate + isolation fixtures shared by every test under tests/acceptance/.

Autouse, function-scoped skip guard: nothing under this directory runs
without ``STUDYLOOP_ACC=1`` (the AWS Terraform Provider ``TF_ACC`` analogy
the owner asked for). Missing/unknown ``STUDYLOOP_ACC_HARNESS`` or
``STUDYLOOP_ACC_ACTOR`` values fail loudly once opted in (council D-13) —
they never silently no-op. See docs/acceptance-testing.md.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from studyloop.harnesses import RELEASE_HARNESSES

from .actors.factory import KNOWN_ACTORS as _FACTORY_KNOWN_ACTORS
from .isolation import create_scratch_environment, sweep_scratch

if TYPE_CHECKING:
    from collections.abc import Generator

    from .isolation import ScratchEnv

#: Imported, not re-declared: ``acceptance/actors/factory.py`` owns the one
#: list of actor names, so this gate and the factory can never disagree
#: about which ``STUDYLOOP_ACC_ACTOR`` values exist (B1 had a local
#: ``frozenset({"scripted"})`` here because no factory existed yet).
KNOWN_ACTORS = _FACTORY_KNOWN_ACTORS

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
        pytest.fail(f"unknown {_ACTOR_ENV} value: {actor!r}; known actors: {sorted(KNOWN_ACTORS)}")


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


@pytest.fixture()
def actor_socket_dir() -> Generator[Path, None, None]:
    """A dedicated, SHORT-path tmux socket directory for ``ACTOR=harness``.

    Council D-11 gives the harness actor its own isolation: a second harness
    process must never share a tmux server with the mentor's, so it gets its
    own socket directory rather than the ``ScratchEnv``'s ``TMUX_TMPDIR``.

    Not under the pytest ``tmp_path`` this tier otherwise uses, and not
    under the scratch ``HOME``, for a mechanical reason: a unix socket path
    is capped at 104 bytes (macOS), and both of those paths are long enough
    that tmux cannot build a socket beneath them. ``HarnessActor`` reports
    that limit by name; this fixture avoids hitting it.
    """
    root = Path(tempfile.mkdtemp(prefix="sl-acc-actor-", dir="/tmp"))
    try:
        yield root / "sock"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def learner_actor_factory(actor_socket_dir: Path):
    """Build the selected ``STUDYLOOP_ACC_ACTOR`` backend, or skip by name.

    The one place an acceptance test should get its learner from: it applies
    the contract's credential rule (council D-15) -- "no key -> skip naming
    the variable; never fail, never prompt" -- BEFORE constructing anything,
    so a run on a machine without a gateway key skips with
    ``missing LITELLM_API_KEY`` rather than raising from a constructor.

    It also supplies the per-actor resources a caller should not have to
    know about -- notably the harness actor's own tmux socket directory
    (D-11) -- so a test body reads the same for every actor.

    An unknown actor name still fails loudly; the ``_acceptance_gate``
    fixture above has already rejected one by then.
    """
    from .actors.factory import get_actor, skip_reason

    def build(**kwargs):
        actor = selected_actor()
        reason = skip_reason(actor, env=dict(os.environ), turn_script=kwargs.get("turn_script"))
        if reason is not None:
            pytest.skip(f"actor {actor!r} unavailable: {reason}")
        kwargs.setdefault("harness_socket_dir", actor_socket_dir)
        return get_actor(actor, **kwargs)

    return build
