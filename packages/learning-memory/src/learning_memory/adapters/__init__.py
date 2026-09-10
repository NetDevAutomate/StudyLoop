"""Adapters: one per harness, all satisfying :class:`learning_memory.HarnessAdapter`."""

from __future__ import annotations

from learning_memory.adapters.archive import (
    ARCHIVE_ADAPTER_VERSION,
    ARCHIVE_CLASSIFIER_VERSION,
    TOOL_XML_TAGS,
    USER_PROSE_XML_TAGS,
    ArchiveAdapter,
    Classified,
    classify,
    open_readonly,
)

__all__ = [
    "ARCHIVE_ADAPTER_VERSION",
    "ARCHIVE_CLASSIFIER_VERSION",
    "TOOL_XML_TAGS",
    "USER_PROSE_XML_TAGS",
    "ArchiveAdapter",
    "Classified",
    "classify",
    "open_readonly",
]
