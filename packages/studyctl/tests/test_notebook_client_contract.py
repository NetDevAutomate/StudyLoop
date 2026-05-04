"""Contract tests for the local NotebookLM simulation boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from studyctl.content.notebook_client import (
    NotebookAuthError,
    SourceUpload,
    sync_notebook_sources,
)
from studyctl.content.notebook_fake import InMemoryNotebookClient

pytestmark = pytest.mark.asyncio


def _upload(path: str, content_hash: str) -> SourceUpload:
    return SourceUpload(path=Path(path), title=Path(path).stem, content_hash=content_hash)


async def test_sync_creates_notebook_and_uploads_new_sources() -> None:
    client = InMemoryNotebookClient()

    result = await sync_notebook_sources(
        client,
        notebook_title="Python",
        uploads=[_upload("/notes/decorators.md", "hash-1")],
    )

    assert result.notebook.title == "Python"
    assert result.created == ["decorators"]
    assert result.updated == []
    assert result.skipped == []
    assert len(await client.list_sources(result.notebook.id)) == 1


async def test_sync_skips_unchanged_sources() -> None:
    client = InMemoryNotebookClient()
    await sync_notebook_sources(client, notebook_title="Python", uploads=[_upload("a.md", "same")])

    result = await sync_notebook_sources(
        client,
        notebook_title="Python",
        uploads=[_upload("a.md", "same")],
    )

    assert result.created == []
    assert result.updated == []
    assert result.skipped == ["a"]


async def test_sync_updates_changed_sources() -> None:
    client = InMemoryNotebookClient()
    await sync_notebook_sources(client, notebook_title="Python", uploads=[_upload("a.md", "old")])

    result = await sync_notebook_sources(
        client,
        notebook_title="Python",
        uploads=[_upload("a.md", "new")],
    )

    assert result.created == []
    assert result.updated == ["a"]
    assert result.skipped == []


async def test_sync_reports_stale_remote_sources_without_deleting() -> None:
    client = InMemoryNotebookClient()
    first = await sync_notebook_sources(
        client,
        notebook_title="Python",
        uploads=[_upload("a.md", "a"), _upload("b.md", "b")],
    )

    result = await sync_notebook_sources(
        client,
        notebook_title="Python",
        uploads=[_upload("a.md", "a")],
    )

    assert first.created == ["a", "b"]
    assert result.stale == ["b"]
    assert [source.title for source in await client.list_sources(result.notebook.id)] == ["a", "b"]


async def test_fake_can_simulate_auth_failure() -> None:
    client = InMemoryNotebookClient(authenticated=False)

    with pytest.raises(NotebookAuthError, match="not authenticated"):
        await sync_notebook_sources(
            client,
            notebook_title="Python",
            uploads=[_upload("a.md", "a")],
        )
