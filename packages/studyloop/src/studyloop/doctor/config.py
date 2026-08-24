"""Config health checks: Obsidian vault, review directories, pandoc, tmux-resurrect."""

from __future__ import annotations

import shutil
from pathlib import Path

from studyloop.doctor.models import CheckResult


def _load_settings():
    from studyloop.settings import load_settings

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
                "studyloop setup",
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
    obsidian_marker = vault_path / ".obsidian"
    if not obsidian_marker.is_dir():
        return [
            CheckResult(
                "config",
                "obsidian_vault",
                "warn",
                "Vault path exists but .obsidian/ not found",
                "Ensure this is your Obsidian vault root",
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
                "studyloop setup",
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


def check_active_topic_limit() -> list[CheckResult]:
    """Warn when config exceeds the AuDHD-friendly active-topic limit."""
    try:
        from studyloop.settings import MAX_ACTIVE_TOPICS, load_raw_config

        raw = load_raw_config()
    except Exception:
        return []

    topics = raw.get("topics", [])
    if topics is None:
        return []
    if not isinstance(topics, list):
        return [
            CheckResult(
                "config",
                "active_topic_limit",
                "fail",
                "Invalid topics config: expected a list",
                "Fix config.yaml so 'topics' is a list of topic names or topic mappings.",
                False,
            )
        ]

    if len(topics) <= MAX_ACTIVE_TOPICS:
        return []

    return [
        CheckResult(
            "config",
            "active_topic_limit",
            "warn",
            f"{len(topics)} study topics configured; StudyLoop activates the first "
            f"{MAX_ACTIVE_TOPICS}",
            'Move extra study ideas to the backlog with: studyloop backlog add "topic"',
            False,
        )
    ]


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


def check_obsidian_export() -> list[CheckResult]:
    """Check Obsidian export configuration and vault writability.

    If export is enabled, verify that the resolved vault_path/memory_dir
    is present (or at least that the vault exists).  If export is disabled,
    return an informational result.
    """
    settings = _load_settings()
    obsidian = getattr(settings, "obsidian", None)
    if obsidian is None:
        return [
            CheckResult(
                "config",
                "obsidian_export",
                "info",
                "Obsidian export disabled",
                "",
                False,
            )
        ]

    if not obsidian.export_enabled:
        return [
            CheckResult(
                "config",
                "obsidian_export",
                "info",
                "Obsidian export disabled",
                "",
                False,
            )
        ]

    # Export is enabled — verify vault_path / memory_dir is accessible.
    vault_path = Path(obsidian.vault_path).expanduser()
    memory_dir = vault_path / obsidian.memory_dir
    if vault_path.is_dir():
        return [
            CheckResult(
                "config",
                "obsidian_export",
                "pass",
                f"Obsidian export enabled; memory dir: {memory_dir}",
                "",
                False,
            )
        ]
    return [
        CheckResult(
            "config",
            "obsidian_export",
            "warn",
            f"Obsidian export enabled but vault not found: {vault_path}",
            f"Create directory or update config: {vault_path}",
            False,
        )
    ]
