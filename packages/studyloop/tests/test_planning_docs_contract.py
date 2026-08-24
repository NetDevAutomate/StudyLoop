"""Keep public planning guidance aligned with the shipped browser workflow."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_public_docs_name_one_agentic_planning_entry_path() -> None:
    readme = _read("README.md")
    first_week = _read("docs/first-week.md")
    guide = _read("docs/study-plans.md")

    for document in (readme, first_week, guide):
        assert "Create with Architect" in document
        assert "type or dictate" in document.casefold()

    day_one = first_week.split("## Day 1", 1)[1].split("## Day 2", 1)[0]
    assert day_one.index("Create with Architect") < day_one.index("studyloop study")
    assert "start the `study-plan-architect` agent" not in guide
    assert "five structured fields" not in guide
    assert "not the browser" not in guide


def test_public_docs_do_not_claim_an_unshipped_terminal_architect() -> None:
    release_notes = _read("releases/v0.1.0.md")
    design = _read("docs/designs/agentic-study-planning.md")
    guide = _read("docs/study-plans.md")

    assert "Available in both the CLI and the browser" not in release_notes
    assert "studyloop plan start" not in design
    assert "AP-CLI-01" not in design
    normalized_release = " ".join(release_notes.casefold().split())
    normalized_guide = " ".join(guide.casefold().split())
    assert "full browser reload cannot yet reattach" in normalized_release
    assert "full browser reload does not yet offer a reattach control" in normalized_guide


def test_first_week_does_not_recommend_phone_use() -> None:
    first_week = _read("docs/first-week.md")

    assert "review from a phone" not in first_week
    assert "tablet or computer" in first_week
