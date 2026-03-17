"""Config health checks: Obsidian vault, review directories, pandoc."""

from __future__ import annotations

import shutil
from pathlib import Path

from studyctl.doctor.models import CheckResult


def _load_settings():
    from studyctl.settings import load_settings

    return load_settings()


def check_obsidian_vault() -> list[CheckResult]:
    """Check that the configured Obsidian vault path exists."""
    settings = _load_settings()
    vault = settings.obsidian_base
    if not vault:
        return [
            CheckResult(
                "config",
                "obsidian_vault",
                "info",
                "Obsidian vault not configured",
                "studyctl config init",
                False,
            )
        ]
    vault_path = Path(vault).expanduser()
    if not vault_path.is_dir():
        return [
            CheckResult(
                "config",
                "obsidian_vault",
                "warn",
                f"Obsidian vault not found: {vault_path}",
                f"Create directory or update config: {vault_path}",
                False,
            )
        ]
    return [
        CheckResult(
            "config",
            "obsidian_vault",
            "pass",
            f"Obsidian vault: {vault_path}",
            "",
            False,
        )
    ]


def check_review_directories() -> list[CheckResult]:
    """Check that all configured topic review directories exist."""
    settings = _load_settings()
    topics = settings.topics
    if not topics:
        return [
            CheckResult(
                "config",
                "review_directories",
                "info",
                "No review topics configured",
                "studyctl config init",
                False,
            )
        ]
    results = []
    for topic in topics:
        # Support real TopicConfig (.obsidian_path) and test mocks (.directory)
        raw_dir = getattr(topic, "directory", None) or getattr(topic, "obsidian_path", "")
        d = Path(str(raw_dir)).expanduser()
        if d.is_dir():
            results.append(
                CheckResult(
                    "config",
                    f"review_dir_{topic.name}",
                    "pass",
                    f"Review dir exists: {d}",
                    "",
                    False,
                )
            )
        else:
            results.append(
                CheckResult(
                    "config",
                    f"review_dir_{topic.name}",
                    "warn",
                    f"Review dir missing: {d}",
                    f"mkdir -p {d}",
                    fix_auto=True,
                )
            )
    return results


def check_pandoc() -> list[CheckResult]:
    """Check that pandoc is available on PATH."""
    if shutil.which("pandoc"):
        return [
            CheckResult(
                "config",
                "pandoc",
                "pass",
                "pandoc available",
                "",
                False,
            )
        ]
    return [
        CheckResult(
            "config",
            "pandoc",
            "info",
            "pandoc not installed (needed for content pipeline)",
            "brew install pandoc",
            False,
        )
    ]
