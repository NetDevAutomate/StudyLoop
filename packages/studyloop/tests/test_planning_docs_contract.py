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


def test_public_docs_match_browser_only_architect_and_reload_recovery() -> None:
    release_notes = _read("releases/v0.1.0.md")
    design = _read("docs/designs/agentic-study-planning.md")
    guide = _read("docs/study-plans.md")

    assert "Available in both the CLI and the browser" not in release_notes
    assert "studyloop plan start" not in design
    assert "AP-CLI-01" not in design
    normalized_release = " ".join(release_notes.casefold().split())
    normalized_guide = " ".join(guide.casefold().split())
    assert "full browser reload cannot yet reattach" not in normalized_release
    assert "same browser tab restores the conversation" in normalized_release
    assert "same browser tab, studyloop automatically restores" in normalized_guide
    assert "a separate tab does not silently adopt" in normalized_guide


def test_first_week_does_not_recommend_phone_use() -> None:
    first_week = _read("docs/first-week.md")
    roadmap = _read("docs/roadmap.md")
    troubleshooting = _read("docs/troubleshooting.md")

    assert "review from a phone" not in first_week
    assert "tablet or computer" in first_week
    assert "Study from any device (iPad, laptop, phone)" not in roadmap
    assert "Phone-sized screens are deferred" in roadmap
    assert "If a phone or tablet cannot connect" not in troubleshooting
    assert "If a tablet or laptop cannot connect" in troubleshooting


def test_release_notes_distinguish_supported_harnesses_from_other_integrations() -> None:
    release_notes = _read("releases/v0.1.0.md")
    normalized = " ".join(release_notes.casefold().split())

    assert "claude code, codex, gemini cli, kiro cli, and opencode" in normalized
    assert "five release-gated live browser harnesses" in normalized
    assert "nine agent platforms are supported" not in normalized
    assert "pyright` reports 47 pre-existing errors" not in normalized
    assert "12 failed, 8 errors" not in normalized
    assert "does not pass, because the surface" not in normalized
    assert "no packaged distribution" not in normalized


def test_setup_guide_treats_notes_as_optional_context_not_progress() -> None:
    guide = _read("docs/setup-guide.md")
    normalized = " ".join(guide.casefold().split())

    assert "obsidian — for study notes" not in normalized
    assert "notes are optional" in normalized
    assert "sessions are evidence" in normalized
    assert "notes and course files show access, not completed study" in normalized
    assert "topics[].notes_path" in guide
    assert "topics[].obsidian_path" in guide
    assert "legacy alias" in normalized
    assert "the default study material source is `~/obsidian/personal/study`" not in normalized


def test_public_docs_do_not_treat_notes_or_reading_as_learning_evidence() -> None:
    readme = " ".join(_read("README.md").casefold().split())
    home = " ".join(_read("docs/index.md").casefold().split())
    learning_loop = " ".join(_read("docs/audhd-learning-loop-implementation.md").casefold().split())

    assert "how notes become recall" not in readme
    assert "optional notes feed recall and practice" in readme
    assert "opening the docs is orientation, not progress evidence" in home
    assert "notes are never progress evidence on their own" in learning_loop
    assert "evidence comes from recorded sessions" in learning_loop


def test_setup_guide_describes_the_actual_bounded_wizard() -> None:
    guide = _read("docs/setup-guide.md")
    normalized = " ".join(guide.casefold().split())

    assert "this walks you through three core questions" not in normalized
    assert "knowledge bridging — do you want" not in normalized
    assert "setup asks whether to enable export" not in normalized
    assert "one prompt on the no-notes path" in normalized
    assert "only when" in normalized
    assert "`studyloop config init` is a deprecated alias" in normalized


def test_public_content_guides_use_neutral_notes_defaults() -> None:
    content = _read("docs/content-pipeline.md")
    web_guide = _read("docs/web-ui-guide.md")
    export_guide = _read("docs/obsidian-export.md")

    assert "~/study-materials" in content
    assert "~/Obsidian/Personal/Study" not in content
    assert "default `~/study-materials`" in web_guide
    assert "Setup wizard:** `studyloop setup` asks" not in export_guide
    assert "first-run setup wizard deliberately does not ask" in export_guide


def test_current_changelog_describes_the_released_architect_conversation() -> None:
    changelog = _read("CHANGELOG.md")
    release_entry = changelog.split("## [0.1.0]", 1)[1]
    normalized = " ".join(release_entry.casefold().split())

    assert "create with architect" in normalized
    assert "server-owned architect" in normalized
    assert "exact markdown proposal" in normalized
    assert "at most three plans" in normalized
    assert "five structured fields" not in normalized
    assert "study-plan-architect` agent already existed" not in normalized
    assert "create/interview wizard" not in normalized
