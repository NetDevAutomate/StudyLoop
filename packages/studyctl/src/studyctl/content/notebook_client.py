"""NotebookLM client boundary used by deterministic content workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class NotebookClientError(RuntimeError):
    """Base error raised by Notebook client implementations."""


class NotebookAuthError(NotebookClientError):
    """Raised when the Notebook client is not authenticated."""


@dataclass(frozen=True)
class NotebookRef:
    """Notebook identity used by studyctl content workflows."""

    id: str
    title: str


@dataclass(frozen=True)
class NotebookSource:
    """Source identity and sync metadata stored behind the client boundary."""

    id: str
    title: str
    path: Path
    content_hash: str
    status: str = "ready"


@dataclass(frozen=True)
class SourceUpload:
    """Local source prepared for upload to a NotebookLM notebook."""

    path: Path
    title: str
    content_hash: str


@dataclass(frozen=True)
class NotebookSyncResult:
    """Result of syncing a set of local sources into one notebook."""

    notebook: NotebookRef
    created: list[str]
    updated: list[str]
    skipped: list[str]
    stale: list[str]


class NotebookClient(Protocol):
    """Minimal NotebookLM operations needed by studyctl."""

    async def ensure_notebook(self, title: str) -> NotebookRef:
        """Return an existing notebook by title, creating it when needed."""
        ...

    async def list_sources(self, notebook_id: str) -> list[NotebookSource]:
        """List sources currently attached to the notebook."""
        ...

    async def add_source(self, notebook_id: str, upload: SourceUpload) -> NotebookSource:
        """Add a new local source to the notebook."""
        ...

    async def replace_source(
        self,
        notebook_id: str,
        source_id: str,
        upload: SourceUpload,
    ) -> NotebookSource:
        """Replace an existing source with changed local content."""
        ...


async def sync_notebook_sources(
    client: NotebookClient,
    *,
    notebook_title: str,
    uploads: list[SourceUpload],
) -> NotebookSyncResult:
    """Sync local uploads into a notebook without deleting stale remote sources."""
    notebook = await client.ensure_notebook(notebook_title)
    existing = await client.list_sources(notebook.id)
    existing_by_path = {source.path: source for source in existing}
    desired_paths = {upload.path for upload in uploads}

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    for upload in uploads:
        current = existing_by_path.get(upload.path)
        if current is None:
            source = await client.add_source(notebook.id, upload)
            created.append(source.title)
            continue
        if current.content_hash == upload.content_hash:
            skipped.append(current.title)
            continue
        source = await client.replace_source(notebook.id, current.id, upload)
        updated.append(source.title)

    stale = [source.title for source in existing if source.path not in desired_paths]
    return NotebookSyncResult(
        notebook=notebook,
        created=created,
        updated=updated,
        skipped=skipped,
        stale=stale,
    )
