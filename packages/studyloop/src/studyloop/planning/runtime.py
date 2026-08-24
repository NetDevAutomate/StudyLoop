"""Production construction for the one planning repository and lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conversation_runtime import PlanningConversationRuntime
from .conversation_store import ConversationStore
from .evidence import EvidenceCatalogue
from .lifecycle import PlanningLifecycle
from .repository import PlanningPaths, PlanningRepository
from .store import plans_dir

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from .contracts import IdGenerator
    from .conversation_contracts import PlanningConversationBounds
    from .model_port import PlanningModelPort
    from .models import EvidenceRef


def planning_paths(document_dir: Path | None = None) -> PlanningPaths:
    """Resolve every durable planning path from the canonical document directory.

    ``STUDYLOOP_PLANS_DIR`` already names the Markdown directory.  It must not
    be passed to :meth:`PlanningPaths.in_root`, which would silently add a
    second ``plans/`` component and give old readers and new writers different
    sources of truth.
    """
    documents = document_dir if document_dir is not None else plans_dir()
    root = documents.parent
    return PlanningPaths(
        root=root,
        plans=documents,
        journal=root / "planning-journal.jsonl",
        private_runs=root / "private-runs",
        lock_file=root / ".planning.lock",
    )


def planning_repository(document_dir: Path | None = None) -> PlanningRepository:
    """Construct the production repository with derived-index refresh enabled."""
    return PlanningRepository(planning_paths(document_dir))


def planning_lifecycle(
    *,
    document_dir: Path | None = None,
    evidence: Iterable[EvidenceRef] = (),
    ids: IdGenerator | None = None,
) -> PlanningLifecycle:
    """Construct the sole normal-product planning mutation service."""
    return PlanningLifecycle(
        planning_repository(document_dir),
        evidence=EvidenceCatalogue(evidence),
        ids=ids,
    )


def planning_conversation_store(document_dir: Path | None = None) -> ConversationStore:
    """Construct the dedicated private conversation database under the planning root."""
    paths = planning_paths(document_dir)
    return ConversationStore(paths.root / "planning-conversations.sqlite3")


def planning_conversation_runtime(
    model: PlanningModelPort,
    *,
    document_dir: Path | None = None,
    evidence: Iterable[EvidenceRef] = (),
    ids: IdGenerator | None = None,
    bounds: PlanningConversationBounds | None = None,
    configured_secret_values: Iterable[str] = (),
) -> PlanningConversationRuntime:
    """Bind one confined model to the canonical lifecycle and conversation root."""
    lifecycle = planning_lifecycle(document_dir=document_dir, evidence=evidence, ids=ids)
    return PlanningConversationRuntime(
        planning_conversation_store(document_dir),
        model,
        lifecycle,
        bounds=bounds,
        configured_secret_values=configured_secret_values,
    )
