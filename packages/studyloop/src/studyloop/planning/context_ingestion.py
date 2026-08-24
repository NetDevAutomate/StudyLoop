"""Bounded learner-selected text ingestion for planning conversations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .conversation_contracts import AttachContext, ContextAttachment, ConversationRefusedError

if TYPE_CHECKING:
    from .conversation_store import ConversationStore

MAX_CONTEXT_BYTES = 100_000
PLAIN_TEXT_MEDIA_TYPES = frozenset(
    {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}
)


@dataclass(frozen=True, slots=True)
class IngestedContext:
    context_id: str
    label: str
    content_digest: str
    size: int
    tier: int = 4


class PlanningContextIngestor:
    """Accept only explicit text; paths and URLs are never dereferenced."""

    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def ingest(
        self,
        conversation_id: str,
        *,
        label: str,
        content: str,
        media_type: str = "text/plain",
        context_id: str | None = None,
    ) -> IngestedContext:
        normalized_type = media_type.partition(";")[0].strip().casefold()
        if normalized_type not in PLAIN_TEXT_MEDIA_TYPES:
            raise ConversationRefusedError("planning context must be a plain-text file")
        encoded = content.encode("utf-8")
        if not content.strip():
            raise ConversationRefusedError("planning context cannot be empty")
        if len(encoded) > MAX_CONTEXT_BYTES:
            raise ConversationRefusedError("planning context exceeds the upload bound")
        attachment = self.store.attach_context(
            AttachContext(
                conversation_id,
                context_id or f"context-{uuid.uuid4().hex}",
                label.strip() or "pasted text",
                content,
            )
        )
        return self._public(attachment, len(encoded))

    @staticmethod
    def _public(attachment: ContextAttachment, size: int) -> IngestedContext:
        return IngestedContext(
            attachment.context_id,
            attachment.label,
            attachment.content_digest,
            size,
        )
