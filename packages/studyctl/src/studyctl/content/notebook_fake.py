"""In-memory NotebookLM client for local simulation and contract tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from studyctl.content.notebook_client import (
    NotebookAuthError,
    NotebookRef,
    NotebookSource,
    SourceUpload,
)


@dataclass
class _NotebookState:
    notebook: NotebookRef
    sources: list[NotebookSource] = field(default_factory=list)


class InMemoryNotebookClient:
    """Deterministic Notebook client fake with NotebookLM-like semantics."""

    def __init__(self, *, authenticated: bool = True) -> None:
        self._authenticated = authenticated
        self._notebooks: dict[str, _NotebookState] = {}
        self._next_notebook_id = 1
        self._next_source_id = 1

    async def ensure_notebook(self, title: str) -> NotebookRef:
        """Return an existing notebook by title, creating it when needed."""
        self._require_auth()
        for state in self._notebooks.values():
            if state.notebook.title == title:
                return state.notebook

        notebook = NotebookRef(id=f"nb-{self._next_notebook_id}", title=title)
        self._next_notebook_id += 1
        self._notebooks[notebook.id] = _NotebookState(notebook=notebook)
        return notebook

    async def list_sources(self, notebook_id: str) -> list[NotebookSource]:
        """List sources currently attached to the notebook."""
        self._require_auth()
        return list(self._state(notebook_id).sources)

    async def add_source(self, notebook_id: str, upload: SourceUpload) -> NotebookSource:
        """Add a new local source to the notebook."""
        self._require_auth()
        state = self._state(notebook_id)
        source = NotebookSource(
            id=f"src-{self._next_source_id}",
            title=upload.title,
            path=upload.path,
            content_hash=upload.content_hash,
        )
        self._next_source_id += 1
        state.sources.append(source)
        return source

    async def replace_source(
        self,
        notebook_id: str,
        source_id: str,
        upload: SourceUpload,
    ) -> NotebookSource:
        """Replace an existing source with changed local content."""
        self._require_auth()
        state = self._state(notebook_id)
        replacement = NotebookSource(
            id=source_id,
            title=upload.title,
            path=upload.path,
            content_hash=upload.content_hash,
        )
        for index, source in enumerate(state.sources):
            if source.id == source_id:
                state.sources[index] = replacement
                return replacement
        raise KeyError(f"Source not found: {source_id}")

    def _require_auth(self) -> None:
        if not self._authenticated:
            raise NotebookAuthError("NotebookLM client is not authenticated.")

    def _state(self, notebook_id: str) -> _NotebookState:
        return self._notebooks[notebook_id]
