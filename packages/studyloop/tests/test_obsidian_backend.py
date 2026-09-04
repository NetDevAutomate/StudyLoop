"""T2 C7/C8/C10/C12/C14: the Obsidian backend end to end, on a tmp_path vault.

What these tests are really about is the promise a learner has to be able to
trust: *StudyLoop writes its own files in your vault and leaves yours alone.*
The writer tests prove the mechanism; these prove the backend uses it for every
note it produces, including the ones it produces in a loop.
"""

from __future__ import annotations

import pytest

from studyloop.planning import Mission, StudyPlan, create_plan, load_plan, save_plan
from studyloop.planning.models import LearningRecord
from studyloop.planning.store import plan_path
from studyloop.second_brain import get_backend
from studyloop.second_brain.core import SecondBrainError
from studyloop.second_brain.obsidian_writer import read_marker
from studyloop.settings import SecondBrainConfig, Settings

PLAN_ID = "python-decorators"


@pytest.fixture()
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


@pytest.fixture()
def plans_dir(tmp_path, monkeypatch):
    directory = tmp_path / "plans"
    directory.mkdir()
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(directory))
    return directory


@pytest.fixture()
def backend(vault, plans_dir, monkeypatch):
    """An Obsidian backend writing files directly.

    There is no other path: the adapter for the official Obsidian CLI was
    withdrawn before release, so a developer who happens to have that binary
    installed gets exactly the same results as one who does not.
    """
    settings = Settings()
    settings.second_brain = SecondBrainConfig(
        provider="obsidian", vault_path=vault, backlinks=False
    )
    return get_backend(settings)


def _seed(plan_id: str = PLAN_ID, *, records: int = 0) -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title="Master Python Decorators",
        status="active",
        topics=["python"],
        mission=Mission(why="Decorators keep showing up in code I have to read."),
        learning_records=[
            LearningRecord(number=n, title=f"Insight {n}", body=f"Body {n}")
            for n in range(1, records + 1)
        ],
    )
    create_plan(plan)
    return plan


# ---------------------------------------------------------------------------
# publish_plan
# ---------------------------------------------------------------------------


def test_publish_plan_writes_a_marked_projection(backend, vault) -> None:
    _seed()
    result = backend.publish_plan(PLAN_ID)
    assert result.written == ("Study/Plans/python-decorators.md",)
    note = vault / "Study" / "Plans" / "python-decorators.md"
    assert "Master Python Decorators" in note.read_text()
    marker = read_marker(note)
    assert marker is not None
    assert marker["kind"] == "plan-projection"
    assert marker["plan_id"] == PLAN_ID


def test_publish_plan_reports_vault_relative_paths_only(backend) -> None:
    """An absolute path here would end up in JSON an agent may echo or log."""
    _seed()
    payload = backend.publish_plan(PLAN_ID).to_json_dict()
    for path in payload["written"]:
        assert not path.startswith("/")


def test_publish_plan_leaves_source_plan_byte_identical(backend) -> None:
    _seed(records=2)
    source = plan_path(PLAN_ID)
    before = source.read_bytes()
    backend.publish_plan(PLAN_ID)
    assert source.read_bytes() == before


def test_unchanged_projection_does_not_write_or_change_mtime(backend, vault) -> None:
    _seed()
    backend.publish_plan(PLAN_ID)
    note = vault / "Study" / "Plans" / "python-decorators.md"
    before = note.stat().st_mtime_ns

    second = backend.publish_plan(PLAN_ID)
    assert second.written == ()
    assert second.unchanged == ("Study/Plans/python-decorators.md",)
    assert note.stat().st_mtime_ns == before


def test_a_changed_plan_is_republished(backend, vault) -> None:
    _seed()
    backend.publish_plan(PLAN_ID)

    plan = load_plan(PLAN_ID)
    plan.mission.why = "Because a colleague asked me to explain one."
    save_plan(plan)

    result = backend.publish_plan(PLAN_ID)
    assert result.written == ("Study/Plans/python-decorators.md",)
    note = vault / "Study" / "Plans" / "python-decorators.md"
    assert "a colleague asked me" in note.read_text()


def test_publish_plan_writes_one_note_per_learning_record(backend, vault) -> None:
    _seed(records=2)
    result = backend.publish_plan(PLAN_ID)
    assert result.written == (
        "Study/Plans/python-decorators.md",
        "Study/Learning Records/python-decorators/LR-0001.md",
        "Study/Learning Records/python-decorators/LR-0002.md",
    )
    assert (vault / "Study" / "Learning Records" / PLAN_ID / "LR-0002.md").exists()


def test_edited_projection_is_replaced_from_source(backend, vault) -> None:
    """A learner may edit a projection; the next publish restores it.

    Deliberate: the plan document is the source of truth, so an edit made in the
    vault has nowhere to live. What matters is that it is only true for files
    StudyLoop marked as its own.
    """
    _seed()
    backend.publish_plan(PLAN_ID)
    note = vault / "Study" / "Plans" / "python-decorators.md"
    note.write_text(note.read_text() + "\nI typed this here.\n")

    result = backend.publish_plan(PLAN_ID)
    assert result.written == ("Study/Plans/python-decorators.md",)
    assert "I typed this here." not in note.read_text()


def test_a_user_note_at_the_target_path_is_refused(backend, vault) -> None:
    _seed()
    note = vault / "Study" / "Plans" / "python-decorators.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Mine\n")
    before = note.read_bytes()

    with pytest.raises(SecondBrainError, match="not marked as StudyLoop-owned"):
        backend.publish_plan(PLAN_ID)
    assert note.read_bytes() == before


def test_renamed_projection_is_left_untouched_and_the_canonical_one_recreated(
    backend, vault
) -> None:
    """Renaming a projection makes it the learner's copy, not a lost file."""
    _seed()
    backend.publish_plan(PLAN_ID)
    note = vault / "Study" / "Plans" / "python-decorators.md"
    renamed = note.with_name("my-copy.md")
    note.rename(renamed)
    renamed_bytes = renamed.read_bytes()

    result = backend.publish_plan(PLAN_ID)
    assert result.written == ("Study/Plans/python-decorators.md",)
    assert renamed.read_bytes() == renamed_bytes


def test_case_only_plan_ids_resolve_to_one_projection(backend, vault) -> None:
    """``Python-Decorators`` and ``python-decorators`` are one plan, one note."""
    _seed()
    backend.publish_plan(PLAN_ID)
    second = backend.publish_plan("Python-Decorators")
    assert second.unchanged == ("Study/Plans/python-decorators.md",)
    plans = list((vault / "Study" / "Plans").glob("*.md"))
    assert len(plans) == 1


def test_an_unknown_plan_is_a_one_line_error(backend) -> None:
    with pytest.raises(SecondBrainError, match="No such plan"):
        backend.publish_plan("no-such-plan")


def test_a_missing_vault_is_refused_before_anything_is_written(plans_dir, tmp_path) -> None:
    settings = Settings()
    settings.second_brain = SecondBrainConfig(
        provider="obsidian", vault_path=tmp_path / "not-mounted"
    )
    _seed()
    with pytest.raises(SecondBrainError, match="does not exist or is not writable"):
        get_backend(settings).publish_plan(PLAN_ID)
    assert not (tmp_path / "not-mounted").exists()


# ---------------------------------------------------------------------------
# publish_today
# ---------------------------------------------------------------------------


def test_publish_today_writes_a_single_replaced_note(backend, vault) -> None:
    result = backend.publish_today()
    assert result.written == ("Study/Today.md",)
    today = vault / "Study" / "Today.md"
    assert today.read_text().startswith("---\n")
    marker = read_marker(today)
    assert marker is not None
    assert marker["kind"] == "today-projection"


def test_today_republish_does_not_accumulate_content(backend, vault) -> None:
    """Replaced, never appended: Today has to stay a one-glance note."""
    backend.publish_today()
    today = vault / "Study" / "Today.md"
    first = today.read_text()
    backend.publish_today()
    assert today.read_text() == first
    assert first.count("# Today") == 1


def test_today_survives_a_completely_empty_machine(backend, vault) -> None:
    """No history, no review DB, no focus filter — still a usable note.

    Today's job is to lower the cost of starting. Failing because there is nothing
    to review would make it useless on precisely the day a learner most needs it.
    """
    result = backend.publish_today()
    assert result.written == ("Study/Today.md",)
    text = (vault / "Study" / "Today.md").read_text()
    for heading in ("## Next action", "## Due reviews", "## Active topics"):
        assert heading in text


def test_publish_today_never_spawns_a_subprocess(backend, monkeypatch) -> None:
    """Nothing in this feature runs an external program any more.

    The Obsidian CLI adapter was withdrawn before release: it could send notes to a
    vault other than the configured one, and it passed the whole plan text as a
    command-line argument where any other user on the machine could read it from the
    process table. This is the guard that keeps it out.
    """
    import subprocess

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the second-brain layer spawned a subprocess")

    monkeypatch.setattr(subprocess, "run", _explode)
    monkeypatch.setattr(subprocess, "Popen", _explode)
    backend.publish_today()


# ---------------------------------------------------------------------------
# publish_learning_record
# ---------------------------------------------------------------------------


def test_publish_learning_record_writes_one_note(backend, vault) -> None:
    _seed(records=1)
    result = backend.publish_learning_record(PLAN_ID, 1)
    assert result.written == ("Study/Learning Records/python-decorators/LR-0001.md",)
    assert (vault / "Study" / "Learning Records" / PLAN_ID / "LR-0001.md").exists()


def test_publish_learning_record_rejects_a_missing_record(backend) -> None:
    _seed(records=1)
    with pytest.raises(SecondBrainError, match="LR-0009"):
        backend.publish_learning_record(PLAN_ID, 9)


# ---------------------------------------------------------------------------
# pull_notes
# ---------------------------------------------------------------------------


def test_pull_notes_reads_user_owned_sibling_without_writing(backend, vault) -> None:
    _seed()
    sibling = vault / "Study" / "Plans" / "python-decorators.notes.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("My own half of this.\n")
    before = sibling.stat().st_mtime_ns

    result = backend.pull_notes(PLAN_ID)
    assert result.found is True
    assert result.notes == "My own half of this.\n"
    assert result.sources == ("Study/Plans/python-decorators.notes.md",)
    assert sibling.stat().st_mtime_ns == before


def test_pull_notes_missing_sibling_is_found_false_without_error(backend, vault) -> None:
    """A learner with no notes yet is a normal state, not a failure.

    Nothing is created either: an empty file made "helpfully" is one more piece of
    StudyLoop clutter in someone else's vault.
    """
    _seed()
    result = backend.pull_notes(PLAN_ID)
    assert result.found is False
    assert result.notes == ""
    assert result.warnings
    assert not (vault / "Study" / "Plans").exists()


def test_pull_notes_never_reads_the_projection_itself(backend, vault) -> None:
    """The sibling, not the projection: pulling StudyLoop's own output back in
    would fold generated text into the plan as if the learner had written it."""
    _seed()
    backend.publish_plan(PLAN_ID)
    result = backend.pull_notes(PLAN_ID)
    assert result.found is False


# ---------------------------------------------------------------------------
# Backlinks, when enabled
# ---------------------------------------------------------------------------


def test_backlinks_are_appended_when_enabled(vault, plans_dir, monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.build_topic_index",
        lambda vault_path: {"python": "Python"},
        raising=True,
    )
    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.inject_backlinks",
        lambda topics, index: [f"[[{index[t.lower()]}]]" for t in topics if t.lower() in index],
        raising=True,
    )
    settings = Settings()
    settings.second_brain = SecondBrainConfig(provider="obsidian", vault_path=vault, backlinks=True)
    _seed()
    get_backend(settings).publish_plan(PLAN_ID)
    text = (vault / "Study" / "Plans" / "python-decorators.md").read_text()
    assert "## Related notes" in text
    assert "[[Python]]" in text
