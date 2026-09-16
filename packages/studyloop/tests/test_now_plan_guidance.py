"""Plan-aware ``now`` — issue #10 (design §3; decisions D-5, D-16).

The one non-negotiable in this module is the golden: with **no active plan**
the JSON ``studyloop now --json`` / ``GET /api/now`` emit must be byte for
byte what it was before any plan-awareness existed
(``tests/golden/now_plan_no_active.json``, captured on the pre-#10 tree). The
additive ``NowPlan`` keys and ``plan_refs`` are therefore emitted only when
non-empty (D-5).

Everything the engine reads is isolated here — an empty sessions database, an
empty plans directory, empty content roots, a config with no topics and no
focus — and the engine's clock is frozen, so the emit is a function of the
fixtures alone and the golden holds on any machine.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from studyloop.learning import decision
from studyloop.learning.decision import build_now_plan
from studyloop.planning import store

if TYPE_CHECKING:
    from studyloop.learning.decision import NowPlan

GOLDEN = Path(__file__).parent / "golden" / "now_plan_no_active.json"

#: One frozen instant for ``generated_at`` and for every date derived from it.
FROZEN_NOW = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
TODAY = FROZEN_NOW.date()


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` always answers :data:`FROZEN_NOW`."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return FROZEN_NOW if tz is None else FROZEN_NOW.astimezone(tz)


def isolate_now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every input of ``build_now_plan`` at an empty world and freeze its clock.

    A plain function (not a fixture) so the golden capture script could call
    it the same way the tests do; the fixture below is its pytest face.
    """
    content = tmp_path / "content"
    study = tmp_path / "study"
    content.mkdir()
    study.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(
        "content:\n"
        f"  base_path: {content}\n"
        f"  study_paths: [{study}]\n"
        "review:\n"
        f"  directories: [{content}]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("STUDYLOOP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    monkeypatch.setattr(decision, "datetime", _FrozenDatetime)
    return tmp_path


@pytest.fixture(autouse=True)
def now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_now_world(tmp_path, monkeypatch)


def serialise(plan: NowPlan) -> bytes:
    """The exact bytes the golden file holds for a plan."""
    return (json.dumps(plan.to_json_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# T3.1 — the golden: no active plans → the pre-#10 emit, byte for byte
# ---------------------------------------------------------------------------


def test_no_active_plans_json_byte_identical_to_golden() -> None:
    plan = build_now_plan()

    assert plan.starter is True, "an empty world must still yield the starter recommendation"
    assert serialise(plan) == GOLDEN.read_bytes()
