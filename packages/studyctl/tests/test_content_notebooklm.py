"""Unit tests for studyctl.content.notebooklm_client."""

pytest = __import__("pytest")
pytest.importorskip("notebooklm")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest as _pytest  # noqa: E402

from studyctl.content.notebooklm_client import (  # noqa: E402
    create_syllabus,
    delete_notebook,
    download_artifacts,
    generate_for_chapters,
    list_notebooks,
    list_sources,
    upload_chapters,
)


@_pytest.fixture
def mock_notebooklm_client():
    client = AsyncMock()
    mock_notebook = MagicMock()
    mock_notebook.id = "test-notebook-id"
    mock_notebook.title = "Test Book"
    client.notebooks.list.return_value = [mock_notebook]
    client.notebooks.create.return_value = mock_notebook
    client.notebooks.delete.return_value = None
    mock_source = MagicMock()
    mock_source.id = "test-source-id"
    mock_source.title = "chapter_01"
    client.sources.list.return_value = [mock_source]
    client.sources.add_file.return_value = mock_source
    mock_status = MagicMock()
    mock_status.task_id = "test-task-id"
    mock_status.is_complete = True
    mock_status.is_failed = False
    client.artifacts.generate_audio.return_value = mock_status
    client.artifacts.generate_video.return_value = mock_status
    client.artifacts.poll_status.return_value = mock_status
    mock_audio = MagicMock()
    mock_audio.id = "audio-artifact-id"
    client.artifacts.list_audio.return_value = [mock_audio]
    mock_video = MagicMock()
    mock_video.id = "video-artifact-id"
    client.artifacts.list_video.return_value = [mock_video]
    client.artifacts.download_audio.return_value = None
    client.artifacts.download_video.return_value = None
    client.artifacts.rename.return_value = None
    mock_ask_result = MagicMock()
    mock_ask_result.answer = 'Episode 1: "Test Episode"\nChapters: 1\nSummary: Test.'
    mock_ask_result.conversation_id = "test-conv-id"
    client.chat.ask.return_value = mock_ask_result
    return client


@_pytest.fixture
def patch_notebooklm(mock_notebooklm_client):
    acm = AsyncMock()
    acm.__aenter__.return_value = mock_notebooklm_client
    acm.__aexit__.return_value = None
    with patch(
        "studyctl.content.notebooklm_client.NotebookLMClient.from_storage",
        return_value=acm,
    ) as mock_from_storage:
        yield mock_notebooklm_client, mock_from_storage


class TestUploadChapters:
    """Tests for upload_chapters."""

    async def test_creates_new_notebook(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm
        client.notebooks.list.return_value = []  # no existing match

        pdf = tmp_path / "ch1.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = await upload_chapters([pdf], "New Book")
        client.notebooks.create.assert_called_once_with(title="New Book")
        assert result.id == "test-notebook-id"
        assert result.chapters == 1

    async def test_reuses_existing_notebook(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm
        existing = MagicMock()
        existing.id = "existing-id"
        existing.title = "My Book"
        client.notebooks.list.return_value = [existing]

        pdf = tmp_path / "ch1.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = await upload_chapters([pdf], "My Book")
        client.notebooks.create.assert_not_called()
        assert result.id == "existing-id"

    async def test_uses_provided_notebook_id(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm

        pdf = tmp_path / "ch1.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        result = await upload_chapters([pdf], "Book", notebook_id="custom-id")
        client.notebooks.list.assert_not_called()
        assert result.id == "custom-id"

    async def test_uploads_all_chapters(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm
        client.notebooks.list.return_value = []

        pdfs = []
        for i in range(3):
            pdf = tmp_path / f"ch{i}.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake")
            pdfs.append(pdf)

        result = await upload_chapters(pdfs, "Book")
        assert client.sources.add_file.call_count == 3
        assert result.chapters == 3


class TestListNotebooks:
    """Tests for list_notebooks."""

    async def test_returns_notebook_list(self, patch_notebooklm):
        _client, _ = patch_notebooklm
        result = await list_notebooks()
        assert len(result) == 1
        assert result[0].id == "test-notebook-id"
        assert result[0].title == "Test Book"

    async def test_includes_source_count(self, patch_notebooklm):
        _client, _ = patch_notebooklm
        result = await list_notebooks()
        assert hasattr(result[0], "sources_count")


class TestListSources:
    """Tests for list_sources."""

    async def test_returns_source_list(self, patch_notebooklm):
        _client, _ = patch_notebooklm
        result = await list_sources("test-notebook-id")
        assert len(result) == 1
        assert result[0].id == "test-source-id"


class TestGenerateForChapters:
    """Tests for generate_for_chapters."""

    async def test_generates_audio_and_video(self, patch_notebooklm):
        client, _ = patch_notebooklm
        await generate_for_chapters("test-notebook-id", (1, 1))
        client.artifacts.generate_audio.assert_called_once()
        client.artifacts.generate_video.assert_called_once()

    async def test_skip_audio(self, patch_notebooklm):
        client, _ = patch_notebooklm
        await generate_for_chapters("test-notebook-id", (1, 1), generate_audio=False)
        client.artifacts.generate_audio.assert_not_called()
        client.artifacts.generate_video.assert_called_once()

    async def test_skip_video(self, patch_notebooklm):
        client, _ = patch_notebooklm
        await generate_for_chapters("test-notebook-id", (1, 1), generate_video=False)
        client.artifacts.generate_audio.assert_called_once()
        client.artifacts.generate_video.assert_not_called()

    async def test_empty_source_range(self, patch_notebooklm):
        client, _ = patch_notebooklm
        client.sources.list.return_value = []
        await generate_for_chapters("test-notebook-id", (1, 3))
        client.artifacts.generate_audio.assert_not_called()

    @patch("studyctl.content.notebooklm_client.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_failure_then_succeeds(self, _mock_sleep, patch_notebooklm):
        client, _ = patch_notebooklm

        failed = MagicMock(is_complete=False, is_failed=True, error="transient")
        complete = MagicMock(is_complete=True, is_failed=False)
        client.artifacts.poll_status.side_effect = [failed, complete]

        await generate_for_chapters(
            "test-notebook-id", (1, 1), generate_audio=True, generate_video=False, timeout=120
        )
        # Should have retried: 2 generate_audio calls (initial + retry)
        assert client.artifacts.generate_audio.call_count == 2

    @patch("studyctl.content.notebooklm_client.asyncio.sleep", new_callable=AsyncMock)
    async def test_gives_up_after_max_retries(self, _mock_sleep, patch_notebooklm):
        client, _ = patch_notebooklm

        failed = MagicMock(is_complete=False, is_failed=True, error="persistent error")
        client.artifacts.poll_status.return_value = failed

        await generate_for_chapters(
            "test-notebook-id", (1, 1), generate_audio=True, generate_video=False, timeout=600
        )
        # Initial request + MAX_RETRIES (3) retries = 4 total
        assert client.artifacts.generate_audio.call_count == 4

    @patch("studyctl.content.notebooklm_client.asyncio.sleep", new_callable=AsyncMock)
    async def test_timeout_with_pending_tasks(self, _mock_sleep, patch_notebooklm):
        client, _ = patch_notebooklm

        in_progress = MagicMock(is_complete=False, is_failed=False)
        client.artifacts.poll_status.return_value = in_progress

        # Short timeout so it exits the loop quickly (1 poll cycle of 30s)
        await generate_for_chapters(
            "test-notebook-id", (1, 1), generate_audio=True, generate_video=False, timeout=30
        )
        # Should have polled once, then timed out
        assert client.artifacts.poll_status.call_count == 1

    @patch("studyctl.content.notebooklm_client.asyncio.sleep", new_callable=AsyncMock)
    async def test_poll_error_continues(self, _mock_sleep, patch_notebooklm):
        client, _ = patch_notebooklm

        complete = MagicMock(is_complete=True, is_failed=False)
        client.artifacts.poll_status.side_effect = [RuntimeError("network"), complete]

        await generate_for_chapters(
            "test-notebook-id", (1, 1), generate_audio=True, generate_video=False, timeout=120
        )
        # First poll raised error, second succeeded
        assert client.artifacts.poll_status.call_count == 2

    async def test_initial_request_failure(self, patch_notebooklm):
        client, _ = patch_notebooklm
        client.artifacts.generate_audio.side_effect = RuntimeError("API down")

        # Should not raise -- error is logged and generation proceeds without audio
        await generate_for_chapters(
            "test-notebook-id", (1, 1), generate_audio=True, generate_video=False
        )
        client.artifacts.generate_audio.assert_called_once()

    @patch("studyctl.content.notebooklm_client.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_request_failure_removes_task(self, _mock_sleep, patch_notebooklm):
        client, _ = patch_notebooklm

        failed = MagicMock(is_complete=False, is_failed=True, error="fail")
        client.artifacts.poll_status.return_value = failed
        # First generate_audio succeeds, retry raises
        client.artifacts.generate_audio.side_effect = [
            MagicMock(task_id="task-1", is_failed=False),
            RuntimeError("retry failed"),
        ]

        await generate_for_chapters(
            "test-notebook-id", (1, 1), generate_audio=True, generate_video=False, timeout=120
        )
        # Initial + 1 failed retry = 2 calls, then task is removed
        assert client.artifacts.generate_audio.call_count == 2


class TestDownloadArtifacts:
    """Tests for download_artifacts."""

    async def test_downloads_audio_and_video(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm
        await download_artifacts("test-notebook-id", tmp_path)
        client.artifacts.download_audio.assert_called_once()
        client.artifacts.download_video.assert_called_once()

    async def test_chapter_range_in_filenames(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm
        await download_artifacts("test-notebook-id", tmp_path, chapter_range=(1, 3))
        audio_call = client.artifacts.download_audio.call_args
        assert "ch1-3" in audio_call.args[1]

    async def test_sequential_naming_without_range(self, patch_notebooklm, tmp_path):
        client, _ = patch_notebooklm
        await download_artifacts("test-notebook-id", tmp_path)
        audio_call = client.artifacts.download_audio.call_args
        assert "audio_01" in audio_call.args[1]


class TestDeleteNotebook:
    """Tests for delete_notebook."""

    async def test_deletes_by_id(self, patch_notebooklm):
        client, _ = patch_notebooklm
        await delete_notebook("test-notebook-id")
        client.notebooks.delete.assert_called_once_with("test-notebook-id")


class TestCreateSyllabus:
    """Tests for create_syllabus."""

    async def test_returns_answer(self, patch_notebooklm):
        client, _ = patch_notebooklm
        result = await create_syllabus(client, "nb-123", "Create a syllabus")
        assert "Episode 1" in result
        client.chat.ask.assert_called_once_with("nb-123", "Create a syllabus")

    async def test_empty_response(self, patch_notebooklm):
        client, _ = patch_notebooklm
        mock_result = MagicMock()
        mock_result.answer = ""
        client.chat.ask.return_value = mock_result
        result = await create_syllabus(client, "nb-123", "prompt")
        assert result == ""

    async def test_passes_notebook_id(self, patch_notebooklm):
        client, _ = patch_notebooklm
        await create_syllabus(client, "my-nb-id", "prompt")
        call_args = client.chat.ask.call_args
        assert call_args.args[0] == "my-nb-id"
