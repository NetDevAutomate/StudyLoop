"""Modular session exporters for different AI tools."""

from .aider import AiderExporter
from .base import ExportStats, SessionExporter, commit_batch
from .bedrock import BedrockProxyExporter
from .claude import ClaudeCodeExporter
from .codex import CodexExporter
from .gemini import GeminiCliExporter
from .grok import GrokExporter
from .kiro import KiroCliExporter
from .litellm import LitellmExporter
from .opencode import OpenCodeExporter
from .pi import OhMyPiExporter, PiExporter, PiFamilyExporter
from .repoprompt import RepoPromptExporter

__all__ = [
    "ExportStats",
    "SessionExporter",
    "commit_batch",
    "ClaudeCodeExporter",
    "CodexExporter",
    "GrokExporter",
    "KiroCliExporter",
    "GeminiCliExporter",
    "AiderExporter",
    "BedrockProxyExporter",
    "LitellmExporter",
    "RepoPromptExporter",
    "OpenCodeExporter",
    "PiFamilyExporter",
    "PiExporter",
    "OhMyPiExporter",
]

# Registry of available exporters
EXPORTERS = {
    "claude": ClaudeCodeExporter(),
    "codex": CodexExporter(),
    "grok": GrokExporter(),
    "kiro": KiroCliExporter(),
    "gemini": GeminiCliExporter(),
    "opencode": OpenCodeExporter(),
    "aider": AiderExporter(),
    "bedrock": BedrockProxyExporter(),
    "litellm": LitellmExporter(),
    "repoprompt": RepoPromptExporter(),
    "pi": PiExporter,
    "omp": OhMyPiExporter,
}


def get_exporter(source_key: str) -> SessionExporter:
    """Get exporter by source key."""
    if source_key not in EXPORTERS:
        raise ValueError(f"Unknown exporter: {source_key}")
    return EXPORTERS[source_key]


def get_all_exporters() -> dict[str, SessionExporter]:
    """Get all available exporters."""
    return EXPORTERS.copy()
