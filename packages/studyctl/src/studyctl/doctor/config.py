"""Config health checks: Obsidian vault, review directories, pandoc, tmux-resurrect."""

from __future__ import annotations

import shutil
import subprocess
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


def check_tmux_resurrect() -> list[CheckResult]:
    """Check tmux-resurrect compatibility with studyctl sessions.

    Detects whether tmux-resurrect is installed and if so, whether the
    user has configured a restore hook to exclude study-* sessions.
    """
    # Check if tmux is available at all
    if not shutil.which("tmux"):
        return []  # No tmux, no resurrect concern

    # Detect tmux-resurrect by checking for its plugin directory
    resurrect_paths = [
        Path.home() / ".tmux" / "plugins" / "tmux-resurrect",
        Path.home() / ".config" / "tmux" / "plugins" / "tmux-resurrect",
    ]
    # Also check if resurrect is loaded via tmux show-options
    resurrect_detected = any(p.is_dir() for p in resurrect_paths)

    if not resurrect_detected:
        # Check tmux options for resurrect (tpm may install elsewhere)
        result = subprocess.run(
            ["tmux", "show-options", "-g"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "resurrect" in result.stdout:
            resurrect_detected = True

    if not resurrect_detected:
        return [
            CheckResult(
                "config",
                "tmux_resurrect",
                "pass",
                "tmux-resurrect not detected",
                "",
                False,
            )
        ]

    # Resurrect is installed — check for restore hook in tmux config
    tmux_conf_paths = [
        Path.home() / ".tmux.conf",
        Path.home() / ".config" / "tmux" / "tmux.conf",
    ]
    hook_found = False
    for conf in tmux_conf_paths:
        if conf.exists():
            content = conf.read_text()
            if "resurrect-restore-hook" in content and "study-" in content:
                hook_found = True
                break

    if hook_found:
        return [
            CheckResult(
                "config",
                "tmux_resurrect",
                "pass",
                "tmux-resurrect restore hook configured",
                "",
                False,
            )
        ]

    return [
        CheckResult(
            "config",
            "tmux_resurrect",
            "warn",
            "tmux-resurrect detected but no restore hook for study-* sessions",
            "See: studyctl docs setup-guide.md#tmux-resurrect-compatibility",
            False,
        )
    ]


def check_eval_provider() -> list[CheckResult]:
    """Check if the eval judge LLM provider is reachable."""
    try:
        from studyctl.settings import load_settings

        settings = load_settings()
        eval_config = settings.eval
    except Exception:
        return [
            CheckResult(
                "eval",
                "eval-provider",
                "info",
                "No eval configuration found (optional)",
                "",
                False,
            )
        ]

    judge = eval_config.judge
    if judge.provider == "ollama":
        try:
            import urllib.request

            req = urllib.request.Request(f"{judge.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return [
                        CheckResult(
                            "eval",
                            "eval-provider",
                            "pass",
                            f"Ollama reachable at {judge.base_url}, model: {judge.model}",
                            "",
                            False,
                        )
                    ]
        except Exception:
            return [
                CheckResult(
                    "eval",
                    "eval-provider",
                    "warn",
                    f"Ollama not reachable at {judge.base_url}",
                    "Start Ollama: ollama serve",
                    False,
                )
            ]

    # openai-compat — just check config exists
    return [
        CheckResult(
            "eval",
            "eval-provider",
            "info",
            f"OpenAI-compat provider configured: {judge.base_url}",
            "",
            False,
        )
    ]
