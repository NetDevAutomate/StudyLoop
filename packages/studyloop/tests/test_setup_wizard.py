"""Tests for the studyloop setup wizard.

Uses Click's CliRunner with scripted input. Every test redirects CONFIG_DIR to a
tmp_path so the real user config is never touched, and every test pins harness
detection: the wizard reads PATH, so without pinning these would pass on a
developer machine with six CLIs installed and fail in CI with none.

The design under test is deliberately small -- two prompts on the happy path,
three at most -- so most of these assert what is NOT asked as much as what is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner

from studyloop.cli import cli

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def _patch_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect CONFIG_DIR in _setup.py to a temp directory."""
    import studyloop.cli._setup as setup_mod

    config_dir = tmp_path / "config"
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(setup_mod, "_detect_planning_profile", lambda: None)
    monkeypatch.setattr(setup_mod, "_probe_planning_profile", lambda _profile: False)
    monkeypatch.delenv("STUDYLOOP_CONFIG", raising=False)
    return config_dir


@pytest.fixture
def _no_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin harness detection to 'none found'.

    Without this the wizard's third question depends on which CLIs happen to be
    installed on the machine running the suite, so the number of prompts -- and
    therefore the input script -- would differ between a developer laptop and CI.
    """
    import studyloop.cli._setup as setup_mod

    monkeypatch.setattr(setup_mod, "_detect_harness", lambda: [])


@pytest.fixture
def _one_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin detection to exactly one harness, which must NOT prompt."""
    import studyloop.cli._setup as setup_mod

    monkeypatch.setattr(setup_mod, "_detect_harness", lambda: ["kiro"])


def _written(config_dir: Path) -> dict:
    path = config_dir / "config.yaml"
    assert path.exists(), f"wizard wrote no config to {path}"
    return yaml.safe_load(path.read_text()) or {}


def _notes_dir(tmp_path: Path, layout: dict[str, int]) -> Path:
    """Build a notes folder: {subfolder: note_count}. Root-level notes use ''."""
    root = tmp_path / "notes"
    root.mkdir(parents=True, exist_ok=True)
    for folder, count in layout.items():
        target = root / folder if folder else root
        target.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (target / f"note{i}.md").write_text(f"# Note {i}\n\nbody\n")
    return root


# ---------------------------------------------------------------------------
# DoD item 5 -- Andy's correction. A learner with no notes is a supported user,
# not a degraded one, because "collecting notes" is the habit this tool exists
# to replace. Skipping the notes question must still produce a usable config.
# ---------------------------------------------------------------------------


class TestNotesAreOptional:
    def test_blank_notes_answer_still_writes_valid_config(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0, result.output
        config = _written(_patch_config_dir)
        assert "notes_path" not in config, "blank answer must not invent a notes folder"
        assert config.get("content", {}).get("note_extensions") == [".md", ".txt"]

    def test_blank_notes_answer_points_at_sessions_instead(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        """The no-notes path must name the alternative, not just fall silent."""
        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0
        assert "study sessions" in result.output.lower()
        assert "studyloop study" in result.output

    def test_no_notes_means_a_single_prompt(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        """One Enter is enough. Every extra prompt is a chance to lose someone."""
        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0
        # Two questions would leave a second unconsumed prompt in the output.
        assert result.output.count("Notes folder") == 1
        assert "Focus on up to" not in result.output


class TestNotesFolderIsUsed:
    def test_notes_path_written_and_scanned(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        notes = _notes_dir(tmp_path, {"Python": 3, "SQL": 2})
        result = runner.invoke(cli, ["setup"], input=f"{notes}\n\n")
        assert result.exit_code == 0, result.output
        config = _written(_patch_config_dir)
        assert config["notes_path"] == str(notes)
        assert "Found 5 notes" in result.output

    def test_topics_are_offered_ranked_and_capped_at_three(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        """DoD item 3. Five candidate folders, at most three active."""
        notes = _notes_dir(tmp_path, {"Python": 9, "SQL": 7, "Spark": 5, "Terraform": 3, "Rust": 1})
        result = runner.invoke(cli, ["setup"], input=f"{notes}\n\n")
        assert result.exit_code == 0, result.output
        topics = _written(_patch_config_dir)["topics"]
        assert len(topics) == 3, topics
        # Ranked by note count, so the busiest folders are offered first.
        assert [t["name"] for t in topics] == ["Python", "SQL", "Spark"]
        assert "2 more folders found" in result.output

    def test_txt_notes_are_recognised(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        """DoD item 4, .txt half. Format is scanned, never asked."""
        notes = tmp_path / "notes"
        (notes / "Ops").mkdir(parents=True)
        (notes / "Ops" / "a.txt").write_text("plain text note")
        result = runner.invoke(cli, ["setup"], input=f"{notes}\n\n")
        assert result.exit_code == 0, result.output
        assert ".txt" in result.output
        assert "Found 1 notes" in result.output

    def test_pdf_is_not_a_note(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        notes = tmp_path / "notes"
        notes.mkdir(parents=True)
        (notes / "slides.pdf").write_bytes(b"%PDF-1.4")
        result = runner.invoke(cli, ["setup"], input=f"{notes}\n")
        assert result.exit_code == 0, result.output
        assert "No .md or .txt files found" in result.output


class TestScanIsBounded:
    def test_template_and_attachment_folders_are_not_offered_as_topics(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        """A real vault is full of these. Suggesting `Templates` as a study
        topic is the thing that makes the whole suggestion untrustworthy."""
        notes = _notes_dir(
            tmp_path,
            {"Templates": 20, "Archive": 15, "attachments": 10, "Python": 2},
        )
        result = runner.invoke(cli, ["setup"], input=f"{notes}\n\n")
        assert result.exit_code == 0, result.output
        names = [t["name"] for t in _written(_patch_config_dir)["topics"]]
        assert names == ["Python"], f"excluded folders leaked into topics: {names}"

    def test_obsidian_vault_is_treated_as_a_plain_folder(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        """Obsidian users must not feel demoted; non-users must not see the word."""
        notes = _notes_dir(tmp_path, {"Python": 2})
        (notes / ".obsidian").mkdir()
        result = runner.invoke(cli, ["setup"], input=f"{notes}\n\n")
        assert result.exit_code == 0, result.output
        assert "treated as a plain markdown folder" in result.output
        assert "obsidian_base" not in _written(_patch_config_dir)


class TestRetiredQuestions:
    """The wizard must not ask about optional third-party integrations."""

    def test_notebooklm_is_not_asked(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        result = runner.invoke(cli, ["setup"], input="\n")
        assert "Enable NotebookLM integration?" not in result.output
        assert "Do you use Google NotebookLM" not in result.output

    def test_obsidian_is_not_asked(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        result = runner.invoke(cli, ["setup"], input="\n")
        assert "Configure Obsidian integration?" not in result.output
        assert "Obsidian vault path" not in result.output
        assert "Where is your Obsidian vault" not in result.output

    def test_web_ui_launch_is_not_offered(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        """It was a fourth question that spawned a process; a hint does the job."""
        result = runner.invoke(cli, ["setup"], input="\n")
        assert "Launch the studyloop web UI" not in result.output


class TestHarnessDetection:
    def test_single_detected_harness_is_not_asked_about(
        self, runner: CliRunner, _patch_config_dir: Path, _one_harness: None
    ) -> None:
        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0, result.output
        assert _written(_patch_config_dir)["ai_assistant"] == "kiro"
        assert "Which AI assistant" not in result.output

    def test_ambiguous_detection_asks(
        self, runner: CliRunner, _patch_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import studyloop.cli._setup as setup_mod

        monkeypatch.setattr(setup_mod, "_detect_harness", lambda: ["kiro", "codex"])
        result = runner.invoke(cli, ["setup"], input="\ncodex\n")
        assert result.exit_code == 0, result.output
        assert _written(_patch_config_dir)["ai_assistant"] == "codex"


class TestLegacyConfigSurvives:
    def test_twenty_topic_config_is_not_truncated_or_reordered(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        """load_settings() slices to 3 at READ time. The stored config must keep
        all 20, or re-running setup would silently destroy 17 of them."""
        _patch_config_dir.mkdir(parents=True, exist_ok=True)
        legacy = {
            "obsidian_base": "~/Obsidian",
            "topics": [{"name": f"Topic{i}", "notebook_id": f"nb-{i}"} for i in range(20)],
            "notebooklm": {"enabled": True},
            "some_hand_edited_key": "keep me",
        }
        (_patch_config_dir / "config.yaml").write_text(yaml.dump(legacy))

        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0, result.output
        config = _written(_patch_config_dir)
        assert len(config["topics"]) == 20, "legacy topics were truncated"
        assert [t["name"] for t in config["topics"]] == [f"Topic{i}" for i in range(20)]
        assert config["topics"][7]["notebook_id"] == "nb-7", "notebook IDs were dropped"
        assert config["some_hand_edited_key"] == "keep me"
        assert config["notebooklm"] == {"enabled": True}
        assert config["obsidian_base"] == "~/Obsidian", "legacy key must never be deleted"

    def test_rerun_with_all_enter_is_a_no_op(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None, tmp_path: Path
    ) -> None:
        notes = _notes_dir(tmp_path, {"Python": 2})
        first = runner.invoke(cli, ["setup"], input=f"{notes}\n\n")
        assert first.exit_code == 0, first.output
        before = _written(_patch_config_dir)

        second = runner.invoke(cli, ["setup"], input="\n\n")
        assert second.exit_code == 0, second.output
        assert _written(_patch_config_dir) == before, "re-run changed the config"


class TestSetupBasics:
    def test_config_dir_is_created(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        assert not _patch_config_dir.exists()
        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0, result.output
        assert _patch_config_dir.is_dir()

    def test_honors_studyloop_config_env(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _no_harness: None
    ) -> None:
        target = tmp_path / "custom" / "config.yaml"
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(target))
        result = runner.invoke(cli, ["setup"], input="\n")
        assert result.exit_code == 0, result.output
        assert target.exists()

    def test_banner_does_not_assume_obsidian_or_notebooklm(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        """The old banner's first sentence named both. That is the bug."""
        result = runner.invoke(cli, ["setup"], input="\n")
        assert "turns a folder of notes into a study system" in result.output

    def test_saved_confirmation_shown(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        result = runner.invoke(cli, ["setup"], input="\n")
        assert "Configuration saved to" in result.output

    def test_help_text(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "setup" in result.output.lower()


class TestPlanningSetup:
    def test_no_notes_or_harness_still_runs_scripted_planning_preflight(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        """Treating missing notes or a coding harness as planning failure breaks onboarding."""
        result = runner.invoke(cli, ["setup"], input="\n")

        assert result.exit_code == 0, result.output
        planning = _written(_patch_config_dir)["planning"]
        assert planning["prompt_version"] == "architect-v1"
        assert planning["capability_schema_version"] == 1
        assert planning["readiness"] == "scripted_only"
        assert "Planning protocol preflight passed" in result.output
        assert "No live planning model detected" in result.output
        normalized = " ".join(result.output.split())
        assert "The browser Architect needs a live planning model" in normalized
        assert "studyloop setup --planning-base-url URL --planning-model MODEL" in normalized

    def test_local_litellm_detection_records_server_owned_profile_without_a_question(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
        _no_harness: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import studyloop.cli._setup as setup_mod
        from studyloop.planning.model_config import PlanningModelProfile

        profile = PlanningModelProfile.from_explicit(
            base_url="http://127.0.0.1:4000/v1", model="planner-model"
        )
        monkeypatch.setattr(setup_mod, "_detect_planning_profile", lambda: profile)

        result = runner.invoke(cli, ["setup"], input="\n")

        assert result.exit_code == 0, result.output
        planning = _written(_patch_config_dir)["planning"]
        assert planning["model"]["base_url"] == "http://127.0.0.1:4000/v1"
        assert planning["model"]["model"] == "planner-model"
        assert planning["readiness"] == "live_configured"
        assert result.output.count("Notes folder") == 1
        assert "planning model" not in result.output.casefold().split("notes folder", 1)[0]
        normalized = " ".join(result.output.split())
        assert "Study Plans" in normalized
        assert "Create with Architect" in normalized
        assert "Type or dictate one brain dump" in normalized

    def test_explicit_profile_uses_options_and_adds_no_curriculum_questions(
        self, runner: CliRunner, _patch_config_dir: Path, _no_harness: None
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "setup",
                "--planning-base-url",
                "https://gateway.example.test/v1/",
                "--planning-model",
                "chosen-model",
                "--planning-api-key-ref",
                "env:PLANNING_KEY",
            ],
            input="\n",
        )

        assert result.exit_code == 0, result.output
        model = _written(_patch_config_dir)["planning"]["model"]
        assert model["base_url"] == "https://gateway.example.test/v1"
        assert model["model"] == "chosen-model"
        assert model["api_key_ref"] == "env:PLANNING_KEY"  # pragma: allowlist secret
        assert result.output.count("Notes folder") == 1
        assert "Which planning" not in result.output

    def test_detected_study_harness_never_claims_agentic_planning_support(
        self, runner: CliRunner, _patch_config_dir: Path, _one_harness: None
    ) -> None:
        result = runner.invoke(cli, ["setup"], input="\n")

        assert result.exit_code == 0, result.output
        assert "using it for study sessions" in result.output
        normalized = " ".join(result.output.casefold().split())
        assert "do not provide agentic planning" in normalized
