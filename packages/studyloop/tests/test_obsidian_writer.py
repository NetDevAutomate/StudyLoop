"""T2 C4/C5/C6: the vault boundary, the ownership marker, and atomic writes.

This is the file that decides whether the feature is safe to ship. Everything
else can be wrong and produce a bad note; a mistake here destroys something the
learner wrote by hand.

Three separate properties, each with its own way of going wrong:

* **Containment.** ``..``, an absolute folder and a symlinked directory are three
  different escapes and each is tested, because only the first is caught by naive
  string checks.
* **Ownership.** A file without StudyLoop's marker is never replaced. Neither is
  one carrying a marker for a different projection — a learner who renamed a plan
  must not lose the note under the old name.
* **Atomicity.** A note is replaced whole or not at all. A vault is a directory
  Obsidian is watching, so a half-written file is visible in the UI.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from test_second_brain_templates import full_plan

from studyloop.second_brain.core import SecondBrainError
from studyloop.second_brain.obsidian_writer import (
    WriteOutcome,
    projection_path,
    read_marker,
    write_projection,
)
from studyloop.second_brain.projection import (
    ProjectionIdentity,
    render_plan_projection,
)


def _identity(plan_id: str = "python-decorators", **overrides) -> ProjectionIdentity:
    base = {
        "kind": "plan-projection",
        "plan_id": plan_id,
        "learning_record": None,
        "source": f"STUDYLOOP_PLANS_DIR/{plan_id}.md",
    }
    base.update(overrides)
    return ProjectionIdentity(**base)


@pytest.fixture()
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


def _rendered(plan_id: str = "python-decorators") -> str:
    plan = full_plan()
    plan.plan_id = plan_id
    return render_plan_projection(plan, _identity(plan_id))


# ---------------------------------------------------------------------------
# C5 — the vault boundary
# ---------------------------------------------------------------------------


def test_projection_path_resolves_inside_the_vault(vault) -> None:
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    assert target.path == vault.resolve() / "Study" / "Plans" / "python-decorators.md"
    assert target.relative == "Study/Plans/python-decorators.md"
    assert target.root == vault.resolve()


def test_path_rejects_dot_dot_component(vault) -> None:
    with pytest.raises(SecondBrainError, match="outside the vault"):
        projection_path(vault, "Study", "../../escaped.md")


def test_path_rejects_absolute_relative_argument(vault, tmp_path) -> None:
    with pytest.raises(SecondBrainError, match="outside the vault"):
        projection_path(vault, "Study", str(tmp_path / "escaped.md"))


def test_path_rejects_absolute_folder_config(vault) -> None:
    """``folder`` is validated at config load; the writer refuses it again.

    Two checks rather than one because the writer is also reachable from a
    hand-built ``SecondBrainConfig`` that never passed through the loader.
    """
    with pytest.raises(SecondBrainError, match="outside the vault"):
        projection_path(vault, "/etc", "Plans/x.md")


def test_path_rejects_symlinked_folder_outside_vault(vault, tmp_path) -> None:
    """The escape a string check cannot see.

    ``<vault>/Study`` as a symlink to somewhere else is a perfectly ordinary
    thing for a learner to have done, and it means every "relative" write lands
    outside the vault they pointed StudyLoop at.
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (vault).mkdir(exist_ok=True)
    (vault / "Study").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecondBrainError, match="outside the vault"):
        projection_path(vault, "Study", "Plans/python-decorators.md")


def test_path_rejects_a_vault_that_is_not_a_directory(tmp_path) -> None:
    missing = tmp_path / "no-such-vault"
    with pytest.raises(SecondBrainError, match=r"[Vv]ault"):
        projection_path(missing, "Study", "Plans/x.md")


# ---------------------------------------------------------------------------
# C4 — the ownership marker
# ---------------------------------------------------------------------------


def test_first_write_creates_the_file_and_its_parents(vault) -> None:
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    outcome = write_projection(target, _rendered(), _identity())
    assert outcome is WriteOutcome.WRITTEN
    assert target.path.read_text().startswith("---\n")
    marker = read_marker(target.path)
    assert marker is not None
    assert marker["plan_id"] == "python-decorators"


def test_existing_target_without_marker_is_refused(vault) -> None:
    """The learner's own note in the way is never replaced."""
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    target.path.write_text("# My own notes\n\nI wrote this.\n")
    before = target.path.read_bytes()

    with pytest.raises(SecondBrainError) as excinfo:
        write_projection(target, _rendered(), _identity())
    message = str(excinfo.value)
    assert "not marked as StudyLoop-owned" in message
    assert "Study/Plans/python-decorators.md" in message
    assert target.path.read_bytes() == before


def test_marker_for_a_different_projection_is_refused(vault) -> None:
    """A renamed plan must not silently consume the old plan's note."""
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    write_projection(target, _rendered("python-decorators"), _identity("python-decorators"))
    before = target.path.read_bytes()

    with pytest.raises(SecondBrainError, match="different projection"):
        write_projection(target, _rendered("sql-windows"), _identity("sql-windows"))
    assert target.path.read_bytes() == before


def test_a_file_whose_frontmatter_is_unparseable_is_refused(vault) -> None:
    """Unreadable frontmatter means unknown ownership, which means hands off."""
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    target.path.write_text("---\nthis: [is: not: yaml\n---\n\nbody\n")
    with pytest.raises(SecondBrainError, match="not marked as StudyLoop-owned"):
        write_projection(target, _rendered(), _identity())


def test_read_marker_returns_none_for_an_unowned_file(vault) -> None:
    target = vault / "note.md"
    target.write_text("# Just a note\n")
    assert read_marker(target) is None


# ---------------------------------------------------------------------------
# C6/C7 — atomic and idempotent
# ---------------------------------------------------------------------------


def test_unchanged_content_is_not_rewritten(vault) -> None:
    """Republishing must not touch mtime.

    In a synced vault, a rewrite with identical bytes is still a change: it
    propagates to every device and can produce a conflict file for content that
    did not change.
    """
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    rendered = _rendered()
    write_projection(target, rendered, _identity())
    before = target.path.stat().st_mtime_ns

    outcome = write_projection(target, rendered, _identity())
    assert outcome is WriteOutcome.UNCHANGED
    assert target.path.stat().st_mtime_ns == before


def test_changed_content_is_replaced(vault) -> None:
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    write_projection(target, _rendered(), _identity())

    plan = full_plan()
    plan.mission.why = "A different reason entirely."
    changed = render_plan_projection(plan, _identity())
    assert write_projection(target, changed, _identity()) is WriteOutcome.WRITTEN
    assert "A different reason entirely." in target.path.read_text()


def test_atomic_replace_occurs_in_target_directory(vault, monkeypatch) -> None:
    """The temp file must be a sibling, not in ``/tmp``.

    ``os.replace`` is only atomic within one filesystem. A vault on an external
    drive or a network share is a different filesystem from the temp directory,
    so writing there first and moving would silently become a copy — with a
    window where the note is truncated.
    """
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def _recording_replace(src, dst, **kwargs):
        seen.append((str(src), str(dst)))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", _recording_replace)
    write_projection(target, _rendered(), _identity())

    assert len(seen) == 1
    src, dst = seen[0]
    assert dst == str(target.path)
    assert Path(src).parent == target.path.parent


def test_a_failed_write_leaves_no_temp_file_and_no_damage(vault, monkeypatch) -> None:
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    write_projection(target, _rendered(), _identity())
    before = target.path.read_bytes()

    def _boom(*args: object, **kwargs: object):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    plan = full_plan()
    plan.mission.why = "Changed."
    with pytest.raises(SecondBrainError, match=r"[Cc]ould not write"):
        write_projection(target, render_plan_projection(plan, _identity()), _identity())

    assert target.path.read_bytes() == before
    assert [p.name for p in target.path.parent.iterdir()] == [target.path.name]


def test_new_files_are_created_owner_readable_only_of_the_umask(vault) -> None:
    """A projection is ordinary content, so 0644 -- not the 0600 a secret gets."""
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    write_projection(target, _rendered(), _identity())
    assert stat.S_IMODE(target.path.stat().st_mode) == 0o644


def test_republish_preserves_existing_mode(vault) -> None:
    """A learner who tightened a note's permissions keeps them.

    Replace-by-rename creates a NEW inode, so the temp file's mode becomes the
    note's mode unless it is copied across first.
    """
    target = projection_path(vault, "Study", "Plans/python-decorators.md")
    write_projection(target, _rendered(), _identity())
    target.path.chmod(0o600)

    plan = full_plan()
    plan.mission.why = "Changed."
    write_projection(target, render_plan_projection(plan, _identity()), _identity())
    assert stat.S_IMODE(target.path.stat().st_mode) == 0o600


def test_create_only_write_refuses_an_existing_file(vault) -> None:
    """Used by template installation: never clobber, even a StudyLoop-owned file."""
    target = projection_path(vault, "Templates", "StudyLoop/Study Plan.md")
    write_projection(target, "# Template\n", _identity(), create_only=True)
    with pytest.raises(SecondBrainError, match="already exists"):
        write_projection(target, "# Template\n", _identity(), create_only=True)
