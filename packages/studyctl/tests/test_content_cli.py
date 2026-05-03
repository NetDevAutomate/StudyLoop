"""CLI tests for studyctl content commands."""

from __future__ import annotations

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
