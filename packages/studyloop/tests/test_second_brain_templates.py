"""T3: one source of truth for plan headings, and the template that mirrors it.

Three artefacts describe the same shape — ``render_plan``'s output, the Obsidian
projection, and the vault template a learner writes notes from. Three copies of a
heading list drift, and the drift is invisible: a template whose sections no
longer match the plan document still looks fine on its own. So they derive from
one constant and this file is the guard.

The heading constants land first (clause C1); the templates and the rest of the
clauses follow in the same task.
"""

from __future__ import annotations

import re

import pytest

from studyloop.planning import (
    MISSION_SUBSECTION_HEADINGS,
    PLAN_SECTION_HEADINGS,
    render_plan,
)
from studyloop.planning.models import (
    Checkpoint,
    LearningRecord,
    Milestone,
    Mission,
    Resource,
    StudyPlan,
)

_HEADING_RE = re.compile(r"^(#{2,3}) (.+?)\s*$", re.MULTILINE)


def headings(text: str) -> list[tuple[int, str]]:
    """``(level, text)`` for every ``##`` and ``###`` heading, in order."""
    return [(len(m.group(1)), m.group(2)) for m in _HEADING_RE.finditer(text)]


def full_plan() -> StudyPlan:
    """A plan with every section populated.

    Every section, deliberately: a plan with empty sections renders placeholder
    prose instead of some content, and a heading comparison against it would
    pass while the populated form drifted.
    """
    return StudyPlan(
        plan_id="python-decorators",
        title="Master Python Decorators",
        status="active",
        topics=["python"],
        target_date="2026-10-01",
        review_cadence_days=3,
        mission=Mission(
            why="Decorators keep showing up in code I have to read.",
            success=["Explain a decorator's closure unprompted"],
            constraints=["45 minutes a day"],
            out_of_scope=["Metaclasses"],
        ),
        milestones=[Milestone(title="Closures", concepts=["closures", "cell-vars"])],
        learning_records=[LearningRecord(number=1, title="Closures clicked", body="Cells.")],
        resources=[Resource(label="PEP 318", url="https://peps.python.org/pep-0318/")],
        checkpoints=[Checkpoint(phase="mid", verdict="on-track", at="2026-09-03", summary="Good")],
        notes="Nothing yet.",
    )


def test_render_plan_headings_equal_constants() -> None:
    """The renderer's ``##`` headings ARE the constant, in order."""
    level_two = [text for level, text in headings(render_plan(full_plan())) if level == 2]
    assert tuple(level_two) == PLAN_SECTION_HEADINGS


def test_mission_subsection_headings_equal_constants() -> None:
    rendered = headings(render_plan(full_plan()))
    mission_index = rendered.index((2, "Mission"))
    subsections = []
    for level, text in rendered[mission_index + 1 :]:
        if level == 2:
            break
        subsections.append(text)
    assert tuple(subsections) == MISSION_SUBSECTION_HEADINGS


def test_known_sections_is_derived_from_the_constant() -> None:
    """The parser and the renderer must not be able to disagree.

    A section the renderer emits but the parser does not recognise is silently
    swept into ``notes`` on the next round trip, which loses structure without
    any error.
    """
    from studyloop.planning.markdown import _KNOWN_SECTIONS

    assert {heading.lower() for heading in PLAN_SECTION_HEADINGS} == _KNOWN_SECTIONS


def test_constants_are_immutable_tuples() -> None:
    """A list would let a caller mutate the shared source of truth in place."""
    assert isinstance(PLAN_SECTION_HEADINGS, tuple)
    assert isinstance(MISSION_SUBSECTION_HEADINGS, tuple)


# ---------------------------------------------------------------------------
# C2/C3/C4/C5/C6 — the packaged templates
# ---------------------------------------------------------------------------


TEMPLATE_NAMES = (
    "Study Plan.md",
    "Today.md",
    "README.md",
    "Due reviews (Dataview).md",
)


def test_list_templates_returns_every_packaged_file() -> None:
    from studyloop.second_brain.templates import list_templates

    assert sorted(list_templates()) == sorted(TEMPLATE_NAMES)


def test_templates_are_readable_as_package_resources() -> None:
    """Read through ``importlib.resources``, not a filesystem path.

    The wheel ships ``src/studyloop`` only, so a template found by walking up from
    ``__file__`` works in a checkout and fails for an installed user — the class of
    bug that only shows up after release.
    """
    from studyloop.second_brain.templates import read_template

    for name in TEMPLATE_NAMES:
        assert read_template(name).strip(), name


def test_an_unknown_template_name_is_a_clear_error() -> None:
    from studyloop.second_brain.core import SecondBrainError
    from studyloop.second_brain.templates import read_template

    with pytest.raises(SecondBrainError, match="Unknown template"):
        read_template("Nope.md")


def test_a_template_name_cannot_escape_the_package(tmp_path) -> None:
    """``read_template`` takes a name, not a path.

    It is reachable from a CLI argument, so a traversal here would let
    ``--print ../../../../etc/passwd`` read an arbitrary file.
    """
    from studyloop.second_brain.core import SecondBrainError
    from studyloop.second_brain.templates import read_template

    for attempt in ("../settings.py", "/etc/passwd", "sub/dir.md"):
        with pytest.raises(SecondBrainError, match="Unknown template"):
            read_template(attempt)


def test_study_plan_template_headings_match_render_plan() -> None:
    """The template and the plan document have the same shape.

    Per-record heading text is normalised away on both sides: the template has a
    blank ``LR-0001 — `` placeholder while a real plan names its record, and that
    difference is not drift.
    """
    from studyloop.second_brain.templates import read_template

    def normalised(text: str) -> list[tuple[int, str]]:
        # Split on the dash alone, not " — ": the template's placeholder heading is
        # `LR-0001 — ` with nothing after it, so the surrounding spaces differ.
        return [(level, heading.split("—")[0].strip()) for level, heading in headings(text)]

    assert normalised(read_template("Study Plan.md")) == normalised(render_plan(full_plan()))


def test_today_template_headings_match_projection() -> None:
    from studyloop.second_brain.projection import TODAY_SECTION_HEADINGS
    from studyloop.second_brain.templates import read_template

    level_two = [text for level, text in headings(read_template("Today.md")) if level == 2]
    assert tuple(level_two) == TODAY_SECTION_HEADINGS


def test_dataview_snippet_uses_only_projected_keys() -> None:
    """A key the projection does not write makes the learner's table go blank.

    Silently: Dataview shows an empty column rather than an error, so nothing
    fails and nobody notices until the table is useless.
    """
    import re as _re

    from studyloop.second_brain.projection import OWNERSHIP_KEY, PROJECTED_PLAN_KEYS
    from studyloop.second_brain.templates import read_template

    body = read_template("Due reviews (Dataview).md")
    block = body.split("```dataview")[1].split("```")[0]

    allowed = set(PROJECTED_PLAN_KEYS) | {"file", OWNERSHIP_KEY}
    identifiers = set(_re.findall(r"\b[a-z_][a-z0-9_]*\b", block))
    keywords = {
        "table",
        "from",
        "where",
        "sort",
        "as",
        "desc",
        "asc",
        "and",
        "or",
        "not",
        "plan",
        "projection",
        "kind",
        "study",
        "plans",
        "progress",
        "target",
    }
    unexpected = identifiers - allowed - keywords
    assert not unexpected, f"Dataview snippet references unprojected keys: {sorted(unexpected)}"

    # And the positive half: the keys it does use are really written.
    for key in ("status", "progress_pct", "target_date", "updated"):
        assert key in block
        assert key in PROJECTED_PLAN_KEYS


def test_templates_have_no_ownership_marker() -> None:
    """A note made from a template is the learner's, forever.

    The absence of the marker is what makes that mechanical: the writer refuses
    any file without one, so a template that carried a marker would turn every note
    made from it into something StudyLoop overwrites.
    """
    from studyloop.second_brain.obsidian_writer import marker_from_text
    from studyloop.second_brain.templates import read_template

    for name in TEMPLATE_NAMES:
        # Checked through the same parser the writer uses, not a substring search:
        # README.md legitimately EXPLAINS the marker in prose, and a text match
        # would fail on the very document that teaches the rule.
        assert marker_from_text(read_template(name)) is None, name


def test_the_readme_explains_the_ownership_split() -> None:
    """The one thing a learner must understand before using these."""
    from studyloop.second_brain.templates import read_template

    readme = read_template("README.md")
    assert "studyloop:" in readme
    assert ".notes.md" in readme
    assert "studyloop brain template --install" in readme


# ---------------------------------------------------------------------------
# C7 — installing into a vault
# ---------------------------------------------------------------------------


def test_templates_folder_defaults_to_the_conventional_name(tmp_path) -> None:
    from studyloop.second_brain.templates import templates_folder

    (tmp_path / ".obsidian").mkdir()
    assert templates_folder(tmp_path) == "Templates"


def test_templates_folder_reads_obsidian_config(tmp_path) -> None:
    """Honour the learner's own templates folder when Obsidian records one."""
    import json as _json

    from studyloop.second_brain.templates import templates_folder

    obsidian = tmp_path / ".obsidian"
    obsidian.mkdir()
    (obsidian / "templates.json").write_text(_json.dumps({"folder": "99 Meta/Templates"}))
    assert templates_folder(tmp_path) == "99 Meta/Templates"


def test_templates_folder_ignores_unusable_config(tmp_path) -> None:
    """A corrupt or hostile config falls back rather than failing a publish."""
    from studyloop.second_brain.templates import templates_folder

    obsidian = tmp_path / ".obsidian"
    obsidian.mkdir()
    for bad in ("not json at all", '{"folder": ""}', '{"folder": "/etc"}', '{"folder": ".."}'):
        (obsidian / "templates.json").write_text(bad)
        assert templates_folder(tmp_path) == "Templates", bad


def test_install_templates_creates_only(tmp_path) -> None:
    from studyloop.second_brain.templates import install_templates

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    installed = install_templates(vault)
    assert sorted(installed) == sorted(f"Templates/StudyLoop/{name}" for name in TEMPLATE_NAMES)
    for name in TEMPLATE_NAMES:
        assert (vault / "Templates" / "StudyLoop" / name).is_file()


def test_install_templates_refuses_existing(tmp_path) -> None:
    """Never clobber. A template the learner edited is theirs."""
    from studyloop.second_brain.core import SecondBrainError
    from studyloop.second_brain.templates import install_templates

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    target = vault / "Templates" / "StudyLoop" / "Today.md"
    target.parent.mkdir(parents=True)
    target.write_text("# My edited version\n")

    with pytest.raises(SecondBrainError, match="nothing was installed"):
        install_templates(vault)
    assert target.read_text() == "# My edited version\n"
    # All-or-nothing: no OTHER template landed either.
    assert sorted(p.name for p in target.parent.iterdir()) == ["Today.md"]


def test_install_templates_uses_the_configured_folder(tmp_path) -> None:
    import json as _json

    from studyloop.second_brain.templates import install_templates

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "templates.json").write_text(_json.dumps({"folder": "Meta/T"}))
    installed = install_templates(vault)
    assert all(path.startswith("Meta/T/StudyLoop/") for path in installed)


def test_install_templates_stays_inside_the_vault(tmp_path) -> None:
    """Installation goes through the same writer as a publish.

    One writer, one set of containment rules. A second copy-loop here would be a
    second place for the vault boundary to be forgotten.
    """
    from studyloop.second_brain.core import SecondBrainError
    from studyloop.second_brain.templates import install_templates

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (vault / "Templates").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SecondBrainError, match="outside the vault"):
        install_templates(vault)
    assert list(outside.iterdir()) == []
