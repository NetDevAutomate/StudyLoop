"""CLI integration tests for content generate and content download commands.

Tests the full chain: CLI argument parsing → async function invocation → mocked backend.
The async functions themselves are unit-tested in test_content_notebooklm.py;
these tests verify the CLI layer (Click options, chapter range parsing, error handling).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from studyctl.cli._content import content_group

# Inline fixtures only (no conftest.py — pluggy conflict)


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def mock_generate():
    """Patch generate_for_chapters where the CLI imports it."""
    with patch(
        "studyctl.content.notebooklm_client.generate_for_chapters",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture()
def mock_download():
    """Patch download_artifacts where the CLI imports it."""
    with patch(
        "studyctl.content.notebooklm_client.download_artifacts",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


# ---------------------------------------------------------------------------
# content generate
# ---------------------------------------------------------------------------


class TestContentGenerate:
    """CLI integration tests for `studyctl content generate`."""

    def test_happy_path_generates_audio_and_video(self, runner, mock_generate):
        result = runner.invoke(content_group, ["generate", "-n", "nb-123", "-c", "1-3"])
        assert result.exit_code == 0
        assert "Generation complete" in result.output
        mock_generate.assert_called_once_with(
            "nb-123",
            (1, 3),
            generate_audio=True,
            generate_video=True,
            timeout=900,
        )

    def test_no_video_flag_skips_video(self, runner, mock_generate):
        result = runner.invoke(
            content_group, ["generate", "-n", "nb-123", "-c", "2-5", "--no-video"]
        )
        assert result.exit_code == 0
        mock_generate.assert_called_once()
        _, kwargs = mock_generate.call_args
        # Positional args
        args = mock_generate.call_args[0]
        assert args == ("nb-123", (2, 5))
        assert kwargs["generate_audio"] is True
        assert kwargs["generate_video"] is False

    def test_no_audio_flag_skips_audio(self, runner, mock_generate):
        result = runner.invoke(
            content_group, ["generate", "-n", "nb-123", "-c", "1-1", "--no-audio"]
        )
        assert result.exit_code == 0
        mock_generate.assert_called_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["generate_audio"] is False
        assert kwargs["generate_video"] is True

    def test_both_disabled_exits_with_error(self, runner, mock_generate):
        result = runner.invoke(
            content_group,
            ["generate", "-n", "nb-123", "-c", "1-3", "--no-audio", "--no-video"],
        )
        assert result.exit_code != 0
        assert "Nothing to generate" in result.output
        mock_generate.assert_not_called()

    def test_invalid_chapter_range_format(self, runner, mock_generate):
        result = runner.invoke(content_group, ["generate", "-n", "nb-123", "-c", "abc"])
        assert result.exit_code != 0
        assert "Invalid chapter range" in result.output
        mock_generate.assert_not_called()

    def test_reversed_chapter_range(self, runner, mock_generate):
        result = runner.invoke(content_group, ["generate", "-n", "nb-123", "-c", "5-2"])
        assert result.exit_code != 0
        assert "Invalid range" in result.output
        mock_generate.assert_not_called()

    def test_missing_notebook_id(self, runner, mock_generate):
        result = runner.invoke(content_group, ["generate", "-c", "1-3"])
        assert result.exit_code != 0
        mock_generate.assert_not_called()

    def test_custom_timeout(self, runner, mock_generate):
        result = runner.invoke(
            content_group,
            ["generate", "-n", "nb-123", "-c", "1-2", "-t", "300"],
        )
        assert result.exit_code == 0
        mock_generate.assert_called_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["timeout"] == 300


# ---------------------------------------------------------------------------
# content download
# ---------------------------------------------------------------------------


class TestContentDownload:
    """CLI integration tests for `studyctl content download`."""

    def test_happy_path_downloads_artifacts(self, runner, mock_download, tmp_path):
        out = tmp_path / "overviews"
        result = runner.invoke(content_group, ["download", "-n", "nb-456", "-o", str(out)])
        assert result.exit_code == 0
        assert "Artifacts saved" in result.output
        mock_download.assert_called_once_with("nb-456", out, None)

    def test_with_chapter_range(self, runner, mock_download, tmp_path):
        out = tmp_path / "overviews"
        result = runner.invoke(
            content_group, ["download", "-n", "nb-456", "-o", str(out), "-c", "1-3"]
        )
        assert result.exit_code == 0
        mock_download.assert_called_once_with("nb-456", out, (1, 3))

    def test_without_chapter_label(self, runner, mock_download, tmp_path):
        out = tmp_path / "overviews"
        result = runner.invoke(content_group, ["download", "-n", "nb-456", "-o", str(out)])
        assert result.exit_code == 0
        # chapter_range should be None
        mock_download.assert_called_once_with("nb-456", out, None)

    def test_creates_output_directory(self, runner, mock_download, tmp_path):
        out = tmp_path / "deep" / "nested" / "dir"
        assert not out.exists()
        result = runner.invoke(content_group, ["download", "-n", "nb-456", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_missing_notebook_id(self, runner, mock_download):
        result = runner.invoke(content_group, ["download"])
        assert result.exit_code != 0
        mock_download.assert_not_called()


# ---------------------------------------------------------------------------
# content from-obsidian
# ---------------------------------------------------------------------------


def _mock_upload_result(notebook_id: str = "nb-new-123", chapters: int = 3):
    """Build a mock return value for upload_chapters."""
    result = MagicMock()
    result.id = notebook_id
    result.chapters = chapters
    return result


@pytest.fixture()
def obsidian_dir(tmp_path):
    """Create a minimal Obsidian-like directory with markdown files."""
    src = tmp_path / "my-notes"
    src.mkdir()
    (src / "chapter-01.md").write_text("# Chapter 1\nContent here.")
    (src / "chapter-02.md").write_text("# Chapter 2\nMore content.")
    return src


@pytest.fixture()
def obsidian_mocks():
    """Patch all four functions used by from-obsidian: convert, upload, generate, download."""
    upload_result = _mock_upload_result()
    with (
        patch(
            "studyctl.content.markdown_converter.convert_directory",
        ) as mock_convert,
        patch(
            "studyctl.content.notebooklm_client.upload_chapters",
            new_callable=AsyncMock,
            return_value=upload_result,
        ) as mock_upload,
        patch(
            "studyctl.content.notebooklm_client.generate_for_chapters",
            new_callable=AsyncMock,
        ) as mock_gen,
        patch(
            "studyctl.content.notebooklm_client.download_artifacts",
            new_callable=AsyncMock,
        ) as mock_dl,
    ):
        # Make convert_directory create fake PDFs so the glob finds them
        def _fake_convert(src_dir, pdf_dir):
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "chapter-01.pdf").write_bytes(b"%PDF-fake")
            (pdf_dir / "chapter-02.pdf").write_bytes(b"%PDF-fake")

        mock_convert.side_effect = _fake_convert
        yield {
            "convert": mock_convert,
            "upload": mock_upload,
            "generate": mock_gen,
            "download": mock_dl,
        }


class TestFromObsidian:
    """CLI integration tests for `studyctl content from-obsidian`."""

    def test_full_pipeline(self, runner, obsidian_dir, obsidian_mocks):
        """Happy path: convert → upload → generate → download."""
        result = runner.invoke(content_group, ["from-obsidian", str(obsidian_dir)])
        assert result.exit_code == 0, result.output

        # All four steps should have been called
        obsidian_mocks["convert"].assert_called_once()
        obsidian_mocks["upload"].assert_called_once()
        obsidian_mocks["generate"].assert_called_once()
        obsidian_mocks["download"].assert_called_once()

        # Upload should receive 2 PDF paths and derived notebook name
        args, _kwargs = obsidian_mocks["upload"].call_args
        pdf_paths = args[0]
        assert len(pdf_paths) == 2
        assert all(p.suffix == ".pdf" for p in pdf_paths)
        # Name derived from dir: "my-notes" → "My Notes"
        assert args[1] == "My Notes"

        # Generate should cover chapters 1-2 (2 PDFs)
        gen_args = obsidian_mocks["generate"].call_args
        assert gen_args[0][1] == (1, 2)  # chapter range

    def test_skip_convert_uses_existing_pdfs(self, runner, obsidian_dir, obsidian_mocks):
        """--skip-convert skips markdown conversion, looks for existing PDFs."""
        # Pre-create the PDF dir with existing files
        pdf_dir = obsidian_dir / "downloads" / "pdfs"
        pdf_dir.mkdir(parents=True)
        (pdf_dir / "existing.pdf").write_bytes(b"%PDF-pre")

        result = runner.invoke(
            content_group, ["from-obsidian", str(obsidian_dir), "--skip-convert"]
        )
        assert result.exit_code == 0, result.output
        obsidian_mocks["convert"].assert_not_called()
        obsidian_mocks["upload"].assert_called_once()

    def test_no_generate_stops_after_upload(self, runner, obsidian_dir, obsidian_mocks):
        """--no-generate uploads but skips generation and download."""
        result = runner.invoke(content_group, ["from-obsidian", str(obsidian_dir), "--no-generate"])
        assert result.exit_code == 0, result.output
        obsidian_mocks["convert"].assert_called_once()
        obsidian_mocks["upload"].assert_called_once()
        obsidian_mocks["generate"].assert_not_called()
        obsidian_mocks["download"].assert_not_called()

    def test_no_download_skips_download(self, runner, obsidian_dir, obsidian_mocks):
        """--no-download generates but doesn't download artifacts."""
        result = runner.invoke(content_group, ["from-obsidian", str(obsidian_dir), "--no-download"])
        assert result.exit_code == 0, result.output
        obsidian_mocks["generate"].assert_called_once()
        obsidian_mocks["download"].assert_not_called()

    def test_no_audio_flag(self, runner, obsidian_dir, obsidian_mocks):
        """--no-audio passes generate_audio=False to generate_for_chapters."""
        result = runner.invoke(content_group, ["from-obsidian", str(obsidian_dir), "--no-audio"])
        assert result.exit_code == 0, result.output
        _, kwargs = obsidian_mocks["generate"].call_args
        assert kwargs["generate_audio"] is False

    def test_custom_notebook_name(self, runner, obsidian_dir, obsidian_mocks):
        """--name overrides the auto-derived notebook name."""
        result = runner.invoke(
            content_group,
            ["from-obsidian", str(obsidian_dir), "--name", "Custom Course"],
        )
        assert result.exit_code == 0, result.output
        args, _ = obsidian_mocks["upload"].call_args
        assert args[1] == "Custom Course"

    def test_existing_notebook_id(self, runner, obsidian_dir, obsidian_mocks):
        """Providing -n uses existing notebook instead of creating one."""
        result = runner.invoke(
            content_group,
            ["from-obsidian", str(obsidian_dir), "-n", "existing-nb-id"],
        )
        assert result.exit_code == 0, result.output
        _, kwargs = obsidian_mocks["upload"].call_args
        assert kwargs["notebook_id"] == "existing-nb-id"
        # Should NOT print "Creating notebook"
        assert "Creating notebook" not in result.output

    def test_subdir_option(self, runner, obsidian_dir, obsidian_mocks):
        """-s/--subdir targets a subdirectory within source."""
        sub = obsidian_dir / "week-1"
        sub.mkdir()
        (sub / "notes.md").write_text("# Week 1 Notes")
        result = runner.invoke(
            content_group,
            ["from-obsidian", str(obsidian_dir), "-s", "week-1"],
        )
        assert result.exit_code == 0, result.output
        # convert_directory should receive the subdirectory
        args, _ = obsidian_mocks["convert"].call_args
        assert args[0] == sub

    def test_no_pdfs_exits_early(self, runner, obsidian_dir):
        """If conversion produces no PDFs, exits gracefully with message."""
        with patch(
            "studyctl.content.markdown_converter.convert_directory",
        ) as mock_convert:
            # convert_directory does nothing → no PDFs created
            mock_convert.return_value = None
            result = runner.invoke(content_group, ["from-obsidian", str(obsidian_dir)])
        assert result.exit_code == 0
        assert "No PDFs to upload" in result.output

    def test_nonexistent_subdir_fails(self, runner, obsidian_dir):
        """A subdir that doesn't exist raises ClickException."""
        result = runner.invoke(
            content_group,
            ["from-obsidian", str(obsidian_dir), "-s", "nonexistent"],
        )
        assert result.exit_code != 0
        assert "Directory not found" in result.output
