"""T1 C11: one contract table, run against every registered backend.

The invariant that matters most is the last one: **the plan file is never
written.** It is asserted as a byte snapshot around every operation of every
backend, because "projections, not sync" (ADR-0010) is the decision the whole
feature rests on and it is the one a well-meaning future change would break
first — a backend that "helpfully" writes a published-at timestamp back into
the plan would look reasonable in review.

New backends register by adding a case to ``BACKEND_CASES``. Registration is
lazy (a factory callable, not an instance) so selecting a backend never imports
a provider module for a test that does not use it.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from studyloop.planning import Mission, StudyPlan, create_plan
from studyloop.second_brain.core import (
    BrainDescription,
    PublishResult,
    PullNotesResult,
    SecondBrain,
    SecondBrainError,
)
from studyloop.settings import SecondBrainConfig, Settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PLAN_ID = "python-decorators"


@dataclass(frozen=True)
class BackendCase:
    """One backend under the shared contract.

    ``writes`` records whether this backend is expected to produce files at all,
    so the table can hold both inert and active backends without a second copy
    of every test.
    """

    name: str
    build: Callable[[Path], SecondBrain]
    writes: bool


def _null(_vault: Path) -> SecondBrain:
    from studyloop.second_brain import get_backend

    settings = Settings()
    settings.second_brain = SecondBrainConfig(provider="none")
    return get_backend(settings)


def _xtiles(_vault: Path) -> SecondBrain:
    from studyloop.second_brain import get_backend

    settings = Settings()
    settings.second_brain = SecondBrainConfig(provider="xtiles")
    return get_backend(settings)


def _obsidian(vault: Path) -> SecondBrain:
    """The writing backend, with the CLI adapter off.

    ``use_cli="off"`` so the contract table gives the same answers on a machine
    with the real Obsidian CLI installed as on one without; the adapter has its
    own tests. ``backlinks=False`` for the same reason — the matcher lives in a
    sibling package that may or may not be present.
    """
    from studyloop.second_brain import get_backend

    settings = Settings()
    settings.second_brain = SecondBrainConfig(
        provider="obsidian", vault_path=vault, use_cli="off", backlinks=False
    )
    return get_backend(settings)


#: Registered backends. A new provider adds one row and inherits every invariant.
BACKEND_CASES: list[BackendCase] = [
    BackendCase("null", _null, writes=False),
    BackendCase("xtiles", _xtiles, writes=False),
    BackendCase("obsidian", _obsidian, writes=True),
]


@pytest.fixture(params=BACKEND_CASES, ids=lambda case: case.name)
def backend_case(request, tmp_path, monkeypatch):
    """A backend plus an isolated vault and plans dir.

    The plans dir is a ``tmp_path`` and is created through the real store, so the
    byte-snapshot assertions below compare against a genuinely rendered plan
    document rather than a hand-written approximation of one.
    """
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(plans_dir))
    vault = tmp_path / "vault"
    vault.mkdir()
    case: BackendCase = request.param
    return case, case.build(vault), vault, plans_dir


def _seed_plan() -> Path:
    from studyloop.planning.store import plan_path

    plan = StudyPlan(
        plan_id=PLAN_ID,
        title="Master Python Decorators",
        status="active",
        topics=["python"],
        mission=Mission(why="Decorators keep showing up in code I have to read."),
    )
    create_plan(plan)
    return plan_path(PLAN_ID)


def test_describe_shape(backend_case) -> None:
    _case, backend, _vault, _plans = backend_case
    description = backend.describe()
    assert isinstance(description, BrainDescription)
    payload = description.to_json_dict()
    assert len(payload) == 9
    for key in ("configured", "available", "supports_publish", "supports_pull_notes"):
        assert isinstance(payload[key], bool), key
    assert isinstance(backend.is_available(), bool)


def test_unknown_plan(backend_case) -> None:
    """An unknown plan id either raises ``SecondBrainError`` or is skipped.

    Never a ``KeyError``, never a traceback: the CLI turns the former into one
    line and exits 1, and has nothing to do with the latter.
    """
    _case, backend, _vault, plans_dir = backend_case
    before = sorted(p.name for p in plans_dir.rglob("*"))
    try:
        result = backend.publish_plan("no-such-plan")
    except SecondBrainError:
        pass
    else:
        assert isinstance(result, PublishResult)
        assert result.written == ()
    assert sorted(p.name for p in plans_dir.rglob("*")) == before


def test_publish_valid_plan_twice(backend_case) -> None:
    """Republishing is free: the second run writes nothing new.

    For an inert backend both runs are skipped; for a writing backend the second
    run reports the path under ``unchanged``. Either way nothing is written
    twice, which is what makes this safe to run at every wind-down.
    """
    case, backend, _vault, _plans = backend_case
    _seed_plan()
    first = backend.publish_plan(PLAN_ID)
    second = backend.publish_plan(PLAN_ID)
    assert isinstance(first, PublishResult)
    assert isinstance(second, PublishResult)
    if case.writes:
        assert first.written
        assert second.written == ()
        assert second.unchanged == first.written
    else:
        assert first.written == ()
        assert second.written == ()


def test_pull_when_user_note_is_absent(backend_case) -> None:
    """A learner with no notes yet has nothing to pull, and that is fine."""
    _case, backend, vault, _plans = backend_case
    _seed_plan()
    before = sorted(p.as_posix() for p in vault.rglob("*"))
    result = backend.pull_notes(PLAN_ID)
    assert isinstance(result, PullNotesResult)
    assert result.found is False
    assert result.notes == ""
    assert sorted(p.as_posix() for p in vault.rglob("*")) == before


def test_operations_never_modify_plan_source(backend_case) -> None:
    """The load-bearing invariant of ADR-0010, asserted for every backend."""
    _case, backend, _vault, _plans = backend_case
    path = _seed_plan()
    before = path.read_bytes()

    for operation in (
        lambda: backend.publish_plan(PLAN_ID),
        lambda: backend.publish_today(),
        lambda: backend.publish_learning_record(PLAN_ID, 1),
        lambda: backend.pull_notes(PLAN_ID),
    ):
        with contextlib.suppress(SecondBrainError):
            operation()
        assert path.read_bytes() == before, "a backend operation rewrote the plan document"
