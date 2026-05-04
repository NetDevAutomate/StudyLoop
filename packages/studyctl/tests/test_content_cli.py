"""CLI tests for studyctl content commands."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
import yaml
from click.testing import CliRunner

from studyctl.cli import cli

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_from_obsidian_defaults_to_configured_study_sources(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    python_dir = vault / "Study" / "Python"
    extra_dir = vault / "Study" / "Data Engineering"
    python_dir.mkdir(parents=True)
    extra_dir.mkdir(parents=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "obsidian_base": str(vault),
                "topics": [
                    {"name": "Python", "slug": "python", "obsidian_path": "Study/Python"},
                ],
                "content": {"study_paths": ["Study/Data Engineering"]},
            }
        )
    )
    monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_path)

    converted: list[tuple[Path, Path]] = []
    uploaded_names: list[str] = []

    def fake_convert_directory(source_dir: Path, output_dir: Path) -> list[Path]:
        converted.append((source_dir, output_dir))
        pdf_dir = output_dir / "pdfs"
        pdf_dir.mkdir(parents=True)
        pdf = pdf_dir / f"{source_dir.name}.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return [pdf]

    async def fake_upload_chapters(chapter_pdfs, book_name, notebook_id=None):
        uploaded_names.append(book_name)
        return SimpleNamespace(id=f"nb-{len(uploaded_names)}", chapters=len(chapter_pdfs))

    monkeypatch.setattr(
        "studyctl.content.markdown_converter.convert_directory", fake_convert_directory
    )
    monkeypatch.setattr("studyctl.content.notebooklm_client.upload_chapters", fake_upload_chapters)
    monkeypatch.setattr("studyctl.content.notebooklm_client.generate_for_chapters", AsyncMock())
    monkeypatch.setattr("studyctl.content.notebooklm_client.download_artifacts", AsyncMock())

    result = runner.invoke(cli, ["content", "from-obsidian", "--no-generate"])

    assert result.exit_code == 0, result.output
    assert converted == [
        (python_dir, python_dir / "downloads"),
        (extra_dir, extra_dir / "downloads"),
    ]
    assert uploaded_names == ["Python", "Data Engineering"]


def test_from_obsidian_explicit_source_overrides_configured_defaults(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_dir = tmp_path / "configured"
    explicit_dir = tmp_path / "explicit"
    configured_dir.mkdir()
    explicit_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "topics": [
                    {
                        "name": "Configured",
                        "slug": "configured",
                        "obsidian_path": str(configured_dir),
                    },
                ]
            }
        )
    )
    monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_path)

    converted: list[Path] = []

    def fake_convert_directory(source_dir: Path, output_dir: Path) -> list[Path]:
        converted.append(source_dir)
        pdf_dir = output_dir / "pdfs"
        pdf_dir.mkdir(parents=True)
        pdf = pdf_dir / "chapter.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return [pdf]

    async def fake_upload_chapters(chapter_pdfs, book_name, notebook_id=None):
        return SimpleNamespace(id="nb-1", chapters=len(chapter_pdfs))

    monkeypatch.setattr(
        "studyctl.content.markdown_converter.convert_directory", fake_convert_directory
    )
    monkeypatch.setattr("studyctl.content.notebooklm_client.upload_chapters", fake_upload_chapters)

    result = runner.invoke(cli, ["content", "from-obsidian", str(explicit_dir), "--no-generate"])

    assert result.exit_code == 0, result.output
    assert converted == [explicit_dir]


def test_from_obsidian_reports_missing_notebooklm_dependency(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "notes"
    source_dir.mkdir()

    def fake_convert_directory(source_dir: Path, output_dir: Path) -> list[Path]:
        pdf_dir = output_dir / "pdfs"
        pdf_dir.mkdir(parents=True)
        pdf = pdf_dir / "chapter.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return [pdf]

    async def fake_upload_chapters(chapter_pdfs, book_name, notebook_id=None):
        raise ImportError("notebooklm-py is required for NotebookLM integration")

    monkeypatch.setattr(
        "studyctl.content.markdown_converter.convert_directory", fake_convert_directory
    )
    monkeypatch.setattr("studyctl.content.notebooklm_client.upload_chapters", fake_upload_chapters)

    result = runner.invoke(cli, ["content", "from-obsidian", str(source_dir), "--no-generate"])

    assert result.exit_code == 1
    assert "notebooklm-py is required" in result.output


def test_discover_uses_configured_study_sources_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    python_dir = vault / "Study" / "Python"
    python_dir.mkdir(parents=True)
    note = python_dir / "decorators.md"
    note.write_text("x" * 120)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "obsidian_base": str(vault),
                "topics": [
                    {"name": "Python", "slug": "python", "obsidian_path": "Study/Python"},
                ],
            }
        )
    )
    monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_path)

    result = runner.invoke(cli, ["content", "discover", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["title"] == "Decorators"
    assert payload[0]["kind"] == "markdown"
    assert payload[0]["path"] == str(note)


def test_discover_explicit_missing_source_reports_error(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["content", "discover", str(tmp_path / "missing")])

    assert result.exit_code == 1
    assert "Study source directory not found" in result.output


def test_ingest_dry_run_outputs_plan_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    python_dir = vault / "Study" / "Python"
    python_dir.mkdir(parents=True)
    note = python_dir / "decorators.md"
    note.write_text("x" * 120)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "obsidian_base": str(vault),
                "content": {"base_path": str(tmp_path / "materials")},
                "topics": [
                    {"name": "Python", "slug": "python", "obsidian_path": "Study/Python"},
                ],
            }
        )
    )
    monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_path)

    result = runner.invoke(cli, ["content", "ingest", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["action"] == "create"
    assert payload[0]["course_slug"] == "python"
    assert payload[0]["material"]["path"] == str(note)


def test_ingest_requires_dry_run(runner: CliRunner, tmp_path: Path) -> None:
    source_dir = tmp_path / "notes"
    source_dir.mkdir()

    result = runner.invoke(cli, ["content", "ingest", str(source_dir)])

    assert result.exit_code == 1
    assert "Only 'studyctl content ingest --dry-run'" in result.output


def test_import_review_dry_run_outputs_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "downloads"
    source_dir.mkdir()
    flashcards = source_dir / "intro-flashcards.json"
    flashcards.write_text(
        json.dumps(
            {
                "title": "Intro",
                "cards": [{"front": "What is ETL?", "back": "Extract, Transform, Load"}],
            }
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"content": {"base_path": str(tmp_path / "materials")}}))
    monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_path)

    result = runner.invoke(
        cli,
        ["content", "import-review", str(source_dir), "--course", "Python", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["action"] == "imported"
    assert payload[0]["kind"] == "flashcards"
    assert not (tmp_path / "materials" / "python").exists()
