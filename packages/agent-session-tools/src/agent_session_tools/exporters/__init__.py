"""Modular session exporters for different AI tools."""

from .aider import AiderExporter
from .base import ExportStats, SessionExporter, commit_batch
from .bedrock import BedrockProxyExporter
from .claude import ClaudeCodeExporter
from .gemini import GeminiCliExporter
from .kiro import KiroCliExporter
from .litellm import LitellmExporter
from .opencode import OpenCodeExporter
from .repoprompt import RepoPromptExporter

__all__ = [
    "ExportStats",
    "SessionExporter",
    "commit_batch",
    "ClaudeCodeExporter",
    "KiroCliExporter",
    "GeminiCliExporter",
    "AiderExporter",
    "BedrockProxyExporter",
    "LitellmExporter",
    "RepoPromptExporter",
    "OpenCodeExporter",
]

# Registry of available exporters
EXPORTERS = {
    "claude": ClaudeCodeExporter(),
    "kiro": KiroCliExporter(),
    "gemini": GeminiCliExporter(),
    "opencode": OpenCodeExporter(),
    "aider": AiderExporter(),
    "bedrock": BedrockProxyExporter(),
    "litellm": LitellmExporter(),
    "repoprompt": RepoPromptExporter(),
}


def get_exporter(source_key: str) -> SessionExporter:
    """Get exporter by source key."""
    if source_key not in EXPORTERS:
        raise ValueError(f"Unknown exporter: {source_key}")
    return EXPORTERS[source_key]


def get_all_exporters() -> dict[str, SessionExporter]:
    """Get all available exporters."""
    return EXPORTERS.copy()
