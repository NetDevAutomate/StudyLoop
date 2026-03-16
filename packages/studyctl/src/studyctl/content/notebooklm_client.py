"""NotebookLM integration module for uploading chapters and generating overviews."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from studyctl.content.models import NotebookInfo, SourceInfo, UploadResult

if TYPE_CHECKING:
    from pathlib import Path

    from notebooklm import NotebookLMClient

logger = logging.getLogger(__name__)


def _import_notebooklm():
    """Lazy-import notebooklm-py, raising a clear error if not installed."""
    try:
        import notebooklm
    except ImportError as exc:
        raise ImportError(
            "notebooklm-py is required for NotebookLM integration. "
            "Install with: uv pip install notebooklm-py"
        ) from exc
    return notebooklm


async def upload_chapters(
    chapter_pdfs: list[Path],
    book_name: str,
    notebook_id: str | None = None,
) -> UploadResult:
    """Upload chapter PDFs to a NotebookLM notebook.

    If no notebook_id is given, checks for an existing notebook with a
    matching title before creating a new one.
    """
    nlm = _import_notebooklm()
    async with await nlm.NotebookLMClient.from_storage() as client:
        if notebook_id:
            nb_id = notebook_id
            nb_title = book_name
            logger.info("Using existing notebook: %s", nb_id)
        else:
            notebooks = await client.notebooks.list()
            existing = next((nb for nb in notebooks if nb.title == book_name), None)
            if existing:
                nb_id = existing.id
                nb_title = existing.title
                logger.info("Found existing notebook: %s (%s)", nb_title, nb_id)
            else:
                notebook = await client.notebooks.create(title=book_name)
                nb_id = notebook.id
                nb_title = notebook.title
                logger.info("Created notebook: %s (%s)", nb_title, nb_id)

        for pdf_path in chapter_pdfs:
            await client.sources.add_file(nb_id, pdf_path)
            logger.info("Uploaded %s", pdf_path.name)
            await asyncio.sleep(2)

    return UploadResult(id=nb_id, title=nb_title, chapters=len(chapter_pdfs))


async def list_notebooks() -> list[NotebookInfo]:
    """List all NotebookLM notebooks with source counts."""
    nlm = _import_notebooklm()
    results: list[NotebookInfo] = []
    async with await nlm.NotebookLMClient.from_storage() as client:
        notebooks = await client.notebooks.list()
        for nb in notebooks:
            sources = await client.sources.list(nb.id)
            results.append(NotebookInfo(id=nb.id, title=nb.title, sources_count=len(sources)))
    return results


async def list_sources(notebook_id: str) -> list[SourceInfo]:
    """List all sources in a notebook."""
    nlm = _import_notebooklm()
    results: list[SourceInfo] = []
    async with await nlm.NotebookLMClient.from_storage() as client:
        sources = await client.sources.list(notebook_id)
        for src in sources:
            results.append(SourceInfo(id=src.id, title=src.title))
    return results


MAX_RETRIES = 3


async def _request_chapter_artifact(
    client: NotebookLMClient,
    notebook_id: str,
    label: str,
    source_ids: list[str],
    instructions: str,
) -> str:
    """Fire off a single chapter generation request. Returns task_id.

    Raises:
        RuntimeError: If the API returns a failed status (rate limit, quota, etc.)
    """
    nlm = _import_notebooklm()
    if label == "audio":
        status = await client.artifacts.generate_audio(
            notebook_id,
            source_ids=source_ids,
            instructions=instructions,
            audio_format=nlm.AudioFormat.DEEP_DIVE,
        )
    elif label == "video":
        status = await client.artifacts.generate_video(
            notebook_id,
            source_ids=source_ids,
            instructions=instructions,
            video_style=nlm.VideoStyle.WHITEBOARD,
        )
    else:
        raise ValueError(f"Unknown artifact type: {label}")

    if status.is_failed or not status.task_id:
        error_msg = status.error or "unknown error"
        error_code = status.error_code or ""
        raise RuntimeError(
            f"{label} generation rejected by API: {error_msg}"
            + (f" (code: {error_code})" if error_code else "")
        )

    return status.task_id


async def generate_for_chapters(
    notebook_id: str,
    chapter_range: tuple[int, int],
    generate_audio: bool = True,
    generate_video: bool = True,
    timeout: int = 900,
) -> None:
    """Generate audio/video overviews for a chapter range.

    Fires off requests concurrently, polls every 30s. Retries failed
    artifacts up to MAX_RETRIES times.
    """
    nlm = _import_notebooklm()
    start, end = chapter_range
    range_label = f"ch{start}-{end}"

    async with await nlm.NotebookLMClient.from_storage() as client:
        sources = await client.sources.list(notebook_id)
        sources.sort(key=lambda s: s.title)
        selected = sources[start - 1 : end]

        if not selected:
            logger.warning("No sources found in the specified range")
            return

        selected_ids = [s.id for s in selected]
        logger.info(
            "Generating for chapters %d-%d (%d sources): %s",
            start,
            end,
            len(selected),
            ", ".join(s.title for s in selected),
        )

        tasks: dict[str, str] = {}
        retries: dict[str, int] = {}
        instructions = {
            "audio": f"Create an engaging audio overview covering chapters {start} to {end}",
            "video": f"Create a visual explainer covering chapters {start} to {end}",
        }

        for label, should_gen in [("audio", generate_audio), ("video", generate_video)]:
            if not should_gen:
                continue
            retries[label] = 0
            try:
                logger.info("Requesting %s (%s)...", label, range_label)
                tasks[label] = await _request_chapter_artifact(
                    client, notebook_id, label, selected_ids, instructions[label]
                )
            except Exception as e:
                logger.error("Failed to request %s: %s", label, e)

        pending = dict(tasks)
        elapsed = 0
        poll_interval = 30

        logger.info(
            "Timeout: %ds (%dmin), max retries: %d",
            timeout,
            timeout // 60,
            MAX_RETRIES,
        )

        while pending and elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            for label, task_id in list(pending.items()):
                try:
                    result = await client.artifacts.poll_status(notebook_id, task_id)
                except Exception as e:
                    logger.warning("Poll error for %s: %s", label, e)
                    continue

                if result.is_complete:
                    logger.info("%s ready (%s)", label.capitalize(), range_label)
                    del pending[label]
                elif result.is_failed:
                    retries[label] += 1
                    if retries[label] <= MAX_RETRIES:
                        logger.warning(
                            "%s failed (%s) -- retrying (%d/%d)...",
                            label.capitalize(),
                            result.error or "unknown error",
                            retries[label],
                            MAX_RETRIES,
                        )
                        try:
                            pending[label] = await _request_chapter_artifact(
                                client,
                                notebook_id,
                                label,
                                selected_ids,
                                instructions[label],
                            )
                        except Exception as e:
                            logger.error("Retry failed: %s", e)
                            del pending[label]
                    else:
                        logger.error(
                            "%s failed after %d retries: %s",
                            label.capitalize(),
                            MAX_RETRIES,
                            result.error,
                        )
                        del pending[label]
                else:
                    logger.debug("%s still generating (%ds elapsed)", label, elapsed)

        for label in pending:
            logger.error("%s timed out (%s)", label.capitalize(), range_label)

    logger.info("Generation complete for %s", range_label)


async def download_artifacts(
    notebook_id: str,
    output_dir: Path,
    chapter_range: tuple[int, int] | None = None,
) -> None:
    """Download audio and video artifacts from a notebook.

    If chapter_range is given, files are named by range (e.g. audio_ch1-3.mp3).
    Otherwise, files are numbered sequentially.
    """
    nlm = _import_notebooklm()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    async with await nlm.NotebookLMClient.from_storage() as client:
        range_tag = f"_ch{chapter_range[0]}-{chapter_range[1]}" if chapter_range else ""

        audios = await client.artifacts.list_audio(notebook_id)
        for i, artifact in enumerate(audios, 1):
            name = f"audio{range_tag}_{i:02d}.mp3"
            path = str(output_dir / name)
            await client.artifacts.download_audio(notebook_id, path, artifact_id=artifact.id)
            logger.info("Downloaded %s", path)

        videos = await client.artifacts.list_video(notebook_id)
        for i, artifact in enumerate(videos, 1):
            name = f"video{range_tag}_{i:02d}.mp4"
            path = str(output_dir / name)
            await client.artifacts.download_video(notebook_id, path, artifact_id=artifact.id)
            logger.info("Downloaded %s", path)

    logger.info("Files saved to %s", output_dir)


async def delete_notebook(notebook_id: str) -> None:
    """Delete a notebook and all its contents."""
    nlm = _import_notebooklm()
    async with await nlm.NotebookLMClient.from_storage() as client:
        await client.notebooks.delete(notebook_id)
        logger.info("Deleted notebook %s", notebook_id)


async def delete_artifact(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_id: str,
) -> None:
    """Delete an artifact by ID. Best-effort, logs warning on failure."""
    try:
        await client.artifacts.delete(notebook_id, artifact_id)
        logger.info("Deleted artifact %s", artifact_id)
    except Exception as e:
        logger.warning("Failed to delete artifact %s: %s", artifact_id, e)


async def download_episode_audio(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_id: str,
    output_path: Path,
) -> None:
    """Download a single audio artifact to the specified path.

    Args:
        client: An open NotebookLM client.
        notebook_id: The notebook ID.
        artifact_id: The audio artifact ID (same as task_id).
        output_path: Full path to save the file (e.g. downloads/01-title.mp3).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await client.artifacts.download_audio(notebook_id, str(output_path), artifact_id=artifact_id)
    logger.info("Downloaded %s", output_path)


async def create_syllabus(
    client: NotebookLMClient,
    notebook_id: str,
    prompt: str,
) -> str:
    """Send syllabus prompt to NotebookLM chat.

    Args:
        client: An open NotebookLM client.
        notebook_id: The notebook ID.
        prompt: The syllabus generation prompt.

    Returns:
        Raw AI response text.
    """
    result = await client.chat.ask(notebook_id, prompt)
    return result.answer


def _build_instructions(episode_title: str, chapter_titles: list[str] | None) -> dict[str, str]:
    """Build scoped instructions referencing specific chapter titles."""
    if chapter_titles:
        ch_list = ", ".join(chapter_titles)
        return {
            "audio": (
                f"Focus ONLY on these specific chapters: {ch_list}. "
                f"Create an engaging audio deep-dive covering: {episode_title}. "
                "Do not discuss content from other chapters."
            ),
            "video": (
                f"Focus ONLY on these specific chapters: {ch_list}. "
                f"Create a visual explainer covering: {episode_title}. "
                "Do not discuss content from other chapters."
            ),
        }
    return {
        "audio": f"Create an engaging audio overview: {episode_title}",
        "video": f"Create a visual explainer: {episode_title}",
    }


async def start_chunk_generation(
    client: NotebookLMClient,
    notebook_id: str,
    source_ids: list[str],
    episode_title: str,
    generate_audio: bool = True,
    generate_video: bool = True,
    chapter_titles: list[str] | None = None,
) -> dict[str, str]:
    """Fire off generation requests without polling. Returns {label: task_id}.

    Args:
        client: An open NotebookLM client.
        notebook_id: The notebook ID.
        source_ids: Source IDs for this chunk's chapters.
        episode_title: Title for the episode.
        generate_audio: Whether to generate audio.
        generate_video: Whether to generate video.
        chapter_titles: Actual chapter titles for scoped instructions.

    Returns:
        Mapping of label ("audio"/"video") -> task_id for started tasks.
    """
    instructions = _build_instructions(episode_title, chapter_titles)
    tasks: dict[str, str] = {}
    for label, should_gen in [("audio", generate_audio), ("video", generate_video)]:
        if not should_gen:
            continue
        try:
            logger.info("Requesting %s for '%s'...", label, episode_title)
            tasks[label] = await _request_chapter_artifact(
                client, notebook_id, label, source_ids, instructions[label]
            )
        except Exception as e:
            logger.error("Failed to request %s: %s", label, e)
    return tasks


async def poll_chunk_status(
    client: NotebookLMClient,
    notebook_id: str,
    tasks: dict[str, str],
) -> dict[str, str]:
    """Single poll of artifact generation status. Returns {label: status_str}.

    Args:
        client: An open NotebookLM client.
        notebook_id: The notebook ID.
        tasks: Mapping of label -> task_id.

    Returns:
        Mapping of label -> status string ("completed", "failed", "in_progress", "pending").
    """
    results: dict[str, str] = {}
    for label, task_id in tasks.items():
        try:
            status = await client.artifacts.poll_status(notebook_id, task_id)
            if status.is_complete:
                results[label] = "completed"
            elif status.is_failed:
                results[label] = "failed"
            elif status.is_in_progress:
                results[label] = "in_progress"
            else:
                results[label] = "pending"
        except Exception as e:
            logger.warning("Poll error for %s: %s", label, e)
            results[label] = "unknown"
    return results
