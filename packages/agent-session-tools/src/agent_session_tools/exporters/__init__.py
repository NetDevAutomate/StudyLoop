"""Modular session exporters for different AI tools."""

from .base import ExportStats, SessionExporter, commit_batch
from .claude import ClaudeCodeExporter
from .codex import CodexExporter
from .kiro import KiroCliExporter
from .opencode import OpenCodeExporter
from .pi import PiExporter, PiFamilyExporter

__all__ = [
    "ExportStats",
    "SessionExporter",
    "commit_batch",
    "ClaudeCodeExporter",
    "CodexExporter",
    "KiroCliExporter",
    "OpenCodeExporter",
    "PiFamilyExporter",
    "PiExporter",
]

# Registry of available exporters
EXPORTERS = {
    "claude": ClaudeCodeExporter(),
    "codex": CodexExporter(),
    "kiro": KiroCliExporter(),
    "opencode": OpenCodeExporter(),
    "pi": PiExporter,
}


def get_exporter(source_key: str) -> SessionExporter:
    """Get exporter by source key."""
    if source_key not in EXPORTERS:
        raise ValueError(f"Unknown exporter: {source_key}")
    return EXPORTERS[source_key]


def get_all_exporters() -> dict[str, SessionExporter]:
    """Get all available exporters."""
    return EXPORTERS.copy()
