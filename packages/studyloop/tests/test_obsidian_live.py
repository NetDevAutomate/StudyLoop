"""Opt-in tests that drive the REAL Obsidian CLI against a dedicated test vault.

Deselected by default (``-m live_obsidian``, see both pyproject files). These are
the only tests in the suite that touch a real vault, and they refuse to run
against any vault but a dedicated throwaway one — a mistyped name here would
write into the learner's actual notes, which no other test in this repository is
able to do.

Three gates, all required:

* ``STUDYLOOP_LIVE_OBSIDIAN=1`` — the learner opted in for this run.
* ``STUDYLOOP_LIVE_OBSIDIAN_VAULT`` — names the vault, and it must be in
  :data:`ALLOWED_LIVE_VAULTS`. A vault named anything else is refused, not
  skipped: skipping would hide a typo, and the typo is the dangerous case.
* the ``obsidian`` binary answers a probe, i.e. the desktop app is running.

The test cleans up after itself, and asserts the cleanup.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from studyloop.planning import Mission, StudyPlan, create_plan
from studyloop.second_brain import get_backend
from studyloop.settings import SecondBrainConfig, Settings

pytestmark = pytest.mark.live_obsidian

#: The only vault names these tests will write into. Not configurable: the whole
#: point is that the allowed set is reviewed in a diff, not supplied at run time.
ALLOWED_LIVE_VAULTS = ("StudyLoop-Live-Test",)

PLAN_ID = "live-obsidian-probe"


@pytest.fixture()
def live_vault(tmp_path, monkeypatch) -> Path:
    if os.environ.get("STUDYLOOP_LIVE_OBSIDIAN") != "1":
        pytest.skip("set STUDYLOOP_LIVE_OBSIDIAN=1 to run the live Obsidian tests")

    name = os.environ.get("STUDYLOOP_LIVE_OBSIDIAN_VAULT", "")
    if name not in ALLOWED_LIVE_VAULTS:
        pytest.fail(
            "STUDYLOOP_LIVE_OBSIDIAN_VAULT must name a dedicated throwaway vault "
            f"({', '.join(ALLOWED_LIVE_VAULTS)}); got {name!r}. Refusing to run."
        )

    root = os.environ.get("STUDYLOOP_LIVE_OBSIDIAN_VAULT_PATH", "")
    if not root:
        pytest.skip("set STUDYLOOP_LIVE_OBSIDIAN_VAULT_PATH to the test vault's path")
    path = Path(root).expanduser()
    if not (path / ".obsidian").is_dir():
        pytest.fail(f"{path} does not look like an Obsidian vault; refusing to run.")
    if path.name not in ALLOWED_LIVE_VAULTS:
        pytest.fail(f"{path} is not one of the allowed throwaway vaults; refusing to run.")

    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(tmp_path / "plans"))
    (tmp_path / "plans").mkdir()
    return path


def _backend(vault: Path, name: str):
    settings = Settings()
    settings.second_brain = SecondBrainConfig(
        provider="obsidian",
        vault_path=vault,
        use_cli="on",
        vault_name=name,
        backlinks=False,
    )
    return get_backend(settings)


def test_publish_to_dedicated_live_vault(live_vault: Path) -> None:
    """A real end-to-end publish, then a republish that must not rewrite."""
    create_plan(
        StudyPlan(
            plan_id=PLAN_ID,
            title="Live Obsidian probe",
            status="active",
            topics=["python"],
            mission=Mission(why="Confirm the CLI grammar against a running app."),
        )
    )
    backend = _backend(live_vault, os.environ["STUDYLOOP_LIVE_OBSIDIAN_VAULT"])
    note = live_vault / "Study" / "Plans" / f"{PLAN_ID}.md"

    try:
        first = backend.publish_plan(PLAN_ID)
        assert first.written == (f"Study/Plans/{PLAN_ID}.md",)
        assert note.is_file()
        mtime = note.stat().st_mtime_ns

        second = backend.publish_plan(PLAN_ID)
        assert second.written == ()
        assert second.unchanged == (f"Study/Plans/{PLAN_ID}.md",)
        assert note.stat().st_mtime_ns == mtime
    finally:
        note.unlink(missing_ok=True)
    assert not note.exists()


def test_the_probe_answers_when_the_app_is_running(live_vault: Path) -> None:
    """Records what the unit tests can only assume: the real grammar works."""
    from studyloop.second_brain.obsidian_cli import resolve_cli_mode

    config = SecondBrainConfig(
        provider="obsidian",
        vault_path=live_vault,
        use_cli="on",
        vault_name=os.environ["STUDYLOOP_LIVE_OBSIDIAN_VAULT"],
    )
    assert resolve_cli_mode(config) == "cli", (
        "the obsidian CLI did not answer -- is the desktop app running, and is the "
        "test vault the open one?"
    )
