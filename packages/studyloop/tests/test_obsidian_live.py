"""Opt-in round trip against a REAL Obsidian vault: create, validate, remove.

Deselected by default (``-m live_obsidian``, see both pyproject files). Run it:

```bash
STUDYLOOP_LIVE_OBSIDIAN=1 \
STUDYLOOP_LIVE_OBSIDIAN_VAULT=StudyLoop-Live-Test \
STUDYLOOP_LIVE_OBSIDIAN_VAULT_PATH=~/Obsidian/StudyLoop-Live-Test \
env -u VIRTUAL_ENV uv run --group dev pytest -m live_obsidian -v
```

These are the only tests in the suite that touch a real vault, and they refuse to
run against any vault but a dedicated throwaway one. Three gates, all required:

* ``STUDYLOOP_LIVE_OBSIDIAN=1`` — opted in for this run.
* ``STUDYLOOP_LIVE_OBSIDIAN_VAULT`` names the vault, and it must be in
  :data:`ALLOWED_LIVE_VAULTS`. A vault named anything else is **failed, not
  skipped** — skipping would hide a typo, and the typo is the dangerous case.

Every test cleans up what it created and then asserts the cleanup, so a run leaves
the vault as it found it. The session-finish guard in ``conftest.py`` watches the
learner's REAL vault throughout and fails the run if it changed, so a mistake here
is loud rather than silent.

The run also writes a documentation-evidence bundle (see :func:`evidence_dir`):
the real files produced, their real rendered content, and a listing. Those are the
samples the guide's examples are checked against, so the documentation shows what
the code actually writes rather than what someone remembered it writing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from studyloop.planning import Mission, StudyPlan, create_plan
from studyloop.planning.models import LearningRecord
from studyloop.second_brain import get_backend
from studyloop.second_brain.obsidian_writer import read_marker
from studyloop.settings import SecondBrainConfig, Settings

pytestmark = pytest.mark.live_obsidian

#: The only vault names these tests will write into.
#:
#: Not configurable: the point is that the allowed set is reviewed in a diff, not
#: supplied at run time by whoever is running the tests.
ALLOWED_LIVE_VAULTS = ("StudyLoop-Live-Test",)

PLAN_ID = "live-obsidian-probe"

#: Where the round trip files its documentation evidence.
#:
#: Inside the gitignored review tree, because it contains real rendered notes.
_EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "reviews"
    / "2026-09-03-second-brain"
    / "evidence"
    / "m7"
    / "live-obsidian"
)


@pytest.fixture(scope="module")
def evidence_dir() -> Path:
    _EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    return _EVIDENCE_ROOT


@pytest.fixture()
def live_vault(tmp_path, monkeypatch) -> Path:
    """The dedicated throwaway vault, or a skip/failure explaining which gate stopped us."""
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

    # The plans directory stays a tmp_path even here: this exercises a real vault,
    # never the learner's real plans.
    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(plans))
    return path


@pytest.fixture()
def backend(live_vault: Path):
    settings = Settings()
    settings.second_brain = SecondBrainConfig(
        provider="obsidian",
        vault_path=live_vault,
        backlinks=False,
    )
    return get_backend(settings)


def _seed(records: int = 2) -> StudyPlan:
    plan = StudyPlan(
        plan_id=PLAN_ID,
        title="Live Obsidian probe",
        status="active",
        topics=["python"],
        mission=Mission(
            why="Confirm the real write path against a real vault, end to end.",
            success=["A projection appears in the vault and republishing is a no-op"],
            constraints=["Throwaway vault only"],
            out_of_scope=["The learner's real vault"],
        ),
        learning_records=[
            LearningRecord(
                number=n,
                title=f"Live probe record {n}",
                body="Written by the live round trip; removed at the end of it.",
            )
            for n in range(1, records + 1)
        ],
    )
    create_plan(plan)
    return plan


def _remove(paths: list[Path], vault: Path) -> None:
    """Delete what the round trip created, deepest first, and prune empty dirs."""
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        path.unlink(missing_ok=True)
    for directory in sorted({p.parent for p in paths}, key=lambda p: len(p.parts), reverse=True):
        while directory != vault and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent


def test_full_round_trip_create_validate_remove(
    backend, live_vault: Path, evidence_dir: Path
) -> None:
    """The whole contract, end to end, against a real vault.

    Create every kind of note, validate each one on disk, prove republishing is a
    genuine no-op, prove a note the learner owns is refused, then remove everything
    and assert the vault is as it was.

    One test rather than several, deliberately: a partial run that created notes and
    then failed before its cleanup would leave a real vault dirty, so create and
    remove belong in the same ``try``/``finally``.
    """
    plan = _seed(records=2)
    created: list[Path] = []

    lines: list[str] = [
        "# Live Obsidian round trip",
        "",
        "Write path: the guarded file writer. There is no other path -- the optional "
        "Obsidian CLI adapter was withdrawn before release.",
        "",
    ]

    try:
        # -- create ---------------------------------------------------------
        published = backend.publish_plan(PLAN_ID)
        today = backend.publish_today()

        expected = (
            f"Study/Plans/{PLAN_ID}.md",
            f"Study/Learning Records/{PLAN_ID}/LR-0001.md",
            f"Study/Learning Records/{PLAN_ID}/LR-0002.md",
        )
        assert published.written == expected, published
        assert today.written == ("Study/Today.md",), today

        created = [live_vault / rel for rel in (*expected, "Study/Today.md")]
        lines.append("## Created")
        lines.append("")
        lines.extend(f"- `{rel}`" for rel in (*expected, "Study/Today.md"))
        lines.append("")

        # -- validate -------------------------------------------------------
        for path in created:
            assert path.is_file(), path
            marker = read_marker(path)
            assert marker is not None, f"{path} carries no ownership marker"
            assert marker["owned"] is True
            assert marker["schema"] == 1

        plan_note = live_vault / f"Study/Plans/{PLAN_ID}.md"
        body = plan_note.read_text(encoding="utf-8")
        assert plan.title in body
        assert plan.mission.why in body
        assert "LR-0001" in body

        record_note = live_vault / f"Study/Learning Records/{PLAN_ID}/LR-0001.md"
        assert "Live probe record 1" in record_note.read_text(encoding="utf-8")

        today_note = live_vault / "Study/Today.md"
        for heading in ("## Next action", "## Due reviews", "## Active topics"):
            assert heading in today_note.read_text(encoding="utf-8")

        # -- republishing is a real no-op -----------------------------------
        mtimes = {path: path.stat().st_mtime_ns for path in created}
        again = backend.publish_plan(PLAN_ID)
        assert again.written == ()
        assert again.unchanged == expected
        for path, before in mtimes.items():
            if path.name != "Today.md":
                assert path.stat().st_mtime_ns == before, f"{path} was rewritten"

        # -- a note the learner owns is refused -----------------------------
        from studyloop.second_brain.core import SecondBrainError

        intruder = live_vault / "Study" / "Plans" / "live-obsidian-mine.md"
        intruder.write_text("# Mine\n\nWritten by hand.\n", encoding="utf-8")
        created.append(intruder)
        mine_before = intruder.read_bytes()
        settings = Settings()
        settings.second_brain = SecondBrainConfig(
            provider="obsidian", vault_path=live_vault, backlinks=False
        )
        renamed = _seed_second_plan()
        try:
            with pytest.raises(SecondBrainError, match="not marked as StudyLoop-owned"):
                _publish_over(settings, renamed, intruder)
        finally:
            assert intruder.read_bytes() == mine_before

        # -- collect the documentation evidence, write it after cleanup ------
        lines.append("## Validated on disk")
        lines.append("")
        lines.append("- every created file carries the `studyloop:` ownership marker")
        lines.append("- the plan projection contains the title, the mission and `LR-0001`")
        lines.append("- `Today.md` contains all three headings")
        lines.append("- republishing wrote nothing and left every mtime unchanged")
        lines.append(
            "- a hand-written `Study/Plans/live-obsidian-mine.md` was refused, byte-for-byte intact"
        )
        lines.append("")
        lines.append("## Rendered plan projection")
        lines.append("")
        lines.append("```markdown")
        lines.append(body.rstrip())
        lines.append("```")
        lines.append("")
        lines.append("## Rendered Today")
        lines.append("")
        lines.append("```markdown")
        lines.append(today_note.read_text(encoding="utf-8").rstrip())
        lines.append("```")
        lines.append("")
        tree_before_removal = (
            "\n".join(
                sorted(
                    p.relative_to(live_vault).as_posix() for p in (live_vault / "Study").rglob("*")
                )
            )
            + "\n"
        )
    finally:
        # -- remove ---------------------------------------------------------
        _remove(created, live_vault)

    for path in created:
        assert not path.exists(), f"{path} survived cleanup"
    assert not (live_vault / "Study" / "Learning Records" / PLAN_ID).exists()

    # Written only now, so evidence exists for a run that completed the WHOLE
    # round trip. A bundle written before cleanup would have described a passing
    # create-and-validate even when removal then failed, which is the half of
    # this test that protects a real vault.
    lines.append("## Removed")
    lines.append("")
    lines.append("Every file above was deleted and its absence asserted; the empty")
    lines.append("`Study/Learning Records/<plan>/` directory was pruned. The vault is as")
    lines.append("the run found it.")
    lines.append("")
    (evidence_dir / "round-trip.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (evidence_dir / "tree.txt").write_text(
        "# Vault contents at the validation step, BEFORE the round trip removed them.\n"
        "# Nothing here survives the test; see the Removed section of round-trip.md.\n"
        + tree_before_removal,
        encoding="utf-8",
    )


def _seed_second_plan() -> StudyPlan:
    plan = StudyPlan(
        plan_id="live-obsidian-mine",
        title="A plan whose target path is already taken",
        status="active",
        mission=Mission(why="Prove the refusal against a real file."),
    )
    create_plan(plan)
    return plan


def _publish_over(settings: Settings, plan: StudyPlan, _target: Path) -> None:
    get_backend(settings).publish_plan(plan.plan_id)


def test_template_install_round_trip(backend, live_vault: Path) -> None:
    """Installing templates into a real vault, then removing them."""
    from studyloop.second_brain.templates import TEMPLATE_NAMES, install_templates

    installed = install_templates(live_vault)
    paths = [live_vault / rel for rel in installed]
    try:
        assert len(installed) == len(TEMPLATE_NAMES)
        for path in paths:
            assert path.is_file(), path
            # A template must NOT be claimed by StudyLoop: a note the learner makes
            # from one has to stay theirs forever.
            assert read_marker(path) is None, f"{path} carries an ownership marker"
    finally:
        _remove(paths, live_vault)

    for path in paths:
        assert not path.exists()
