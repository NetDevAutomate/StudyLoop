"""Config health checks: Obsidian vault, review directories, pandoc, tmux-resurrect."""

from __future__ import annotations

import os
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
                "studyloop config init",
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
                "studyloop config init",
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


def check_second_brain() -> list[CheckResult]:
    """Report the optional second-brain layer, when one is configured.

    Returns ``[]`` when there is no ``second_brain`` section or the provider is
    ``none``. A learner who has never configured a second brain must not see rows
    about software they do not use — the setup wizard does not ask about it, so
    reporting on it would be reporting on nothing. Same reasoning the Obsidian
    export checks above are registered conditionally for; the registration in
    ``cli/_doctor.py`` enforces it, and this early return makes the function safe
    to call unconditionally.

    Nothing here is ever ``fail``. A vault on an unmounted drive deserves a
    warning, but it is not a broken installation, and ``doctor`` is what a learner
    runs when something ELSE is wrong.
    """
    try:
        settings = _load_settings()
    except Exception as exc:
        # A malformed section must not take down every other check with it.
        return [
            CheckResult(
                "config",
                "second_brain_config",
                "warn",
                f"The second_brain section does not load: {exc}",
                "Fix the second_brain section in config.yaml, or remove it.",
                False,
            )
        ]

    config = getattr(settings, "second_brain", None)
    if config is None or config.provider == "none":
        return []

    if config.provider == "xtiles":
        return [
            CheckResult(
                "config",
                "second_brain_provider",
                "info",
                "Second brain: xTiles (no programmatic backend; prompts and an "
                "opt-in assistant skill)",
                "See docs/second-brain.md for the xTiles setup and the three prompts.",
                False,
            )
        ]

    results = [
        CheckResult(
            "config",
            "second_brain_provider",
            "info",
            f"Second brain: {config.provider}",
            "",
            False,
        )
    ]

    vault = Path(config.vault_path).expanduser()
    if vault.is_dir() and os.access(vault, os.W_OK):
        results.append(
            CheckResult("config", "second_brain_vault", "pass", f"Vault: {vault}", "", False)
        )
    elif vault.is_dir():
        results.append(
            CheckResult(
                "config",
                "second_brain_vault",
                "warn",
                f"Vault is not writable: {vault}",
                f"Check the permissions on {vault}",
                False,
            )
        )
    else:
        results.append(
            CheckResult(
                "config",
                "second_brain_vault",
                "warn",
                f"Vault not found: {vault}",
                "Mount it, or run: studyloop brain enable obsidian --vault <path>",
                False,
            )
        )

    results.append(
        CheckResult(
            "config",
            "second_brain_folder",
            "info",
            f"StudyLoop writes into {config.folder}/ inside the vault",
            "",
            False,
        )
    )

    # The EFFECTIVE mode, not the configured one: `auto` is not an answer a learner
    # can act on. resolve_cli_mode never probes when the mode is `off`, so this
    # cannot spawn Obsidian for someone who switched it off.
    from studyloop.second_brain.obsidian_cli import resolve_cli_mode

    effective = resolve_cli_mode(config)
    binary = "yes" if shutil.which("obsidian") else "no"
    results.append(
        CheckResult(
            "config",
            "second_brain_cli",
            "info",
            f"Obsidian CLI: configured {config.use_cli}, binary on PATH {binary}, "
            f"in use now: {effective}",
            ""
            if effective == "cli" or config.use_cli == "off"
            else "The Obsidian desktop app must be running for the CLI adapter; "
            "notes are written directly otherwise.",
            False,
        )
    )
    return results
