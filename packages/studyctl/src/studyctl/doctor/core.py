"""Core health checks: Python version, packages installed, config file."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.doctor.models import CheckResult


def _get_config_path() -> Path:
    from studyctl.settings import _CONFIG_PATH

    return _CONFIG_PATH


def _get_package_version(name: str) -> str:
    return importlib.metadata.version(name)


def check_python_version() -> list[CheckResult]:
    major, minor = sys.version_info[:2]
    version_str = f"{major}.{minor}.{sys.version_info[2]}"
    if (major, minor) >= (3, 12):
        return [CheckResult("core", "python_version", "pass", f"Python {version_str}", "", False)]
    return [
        CheckResult(
            "core",
            "python_version",
            "fail",
            f"Python {version_str} (requires >= 3.12)",
            "Install Python 3.12+: https://www.python.org/downloads/",
            fix_auto=False,
        )
    ]


def check_studyctl_installed() -> list[CheckResult]:
    try:
        version = _get_package_version("studyctl")
        return [CheckResult("core", "studyctl_installed", "pass", f"studyctl {version}", "", False)]
    except importlib.metadata.PackageNotFoundError:
        return [
            CheckResult(
                "core",
                "studyctl_installed",
                "fail",
                "studyctl not found as installed package",
                "uv tool install studyctl",
                fix_auto=False,
            )
        ]


def check_agent_session_tools() -> list[CheckResult]:
    spec = importlib.util.find_spec("agent_session_tools")
    if spec is None:
        return [
            CheckResult(
                "core",
                "agent_session_tools",
                "warn",
                "agent-session-tools not installed (sessions DB unavailable)",
                "uv pip install agent-session-tools",
                fix_auto=True,
            )
        ]
    try:
        version = _get_package_version("agent-session-tools")
        return [
            CheckResult(
                "core", "agent_session_tools", "pass", f"agent-session-tools {version}", "", False
            )
        ]
    except importlib.metadata.PackageNotFoundError:
        return [
            CheckResult(
                "core",
                "agent_session_tools",
                "pass",
                "agent-session-tools (version unknown)",
                "",
                False,
            )
        ]


def check_config_file() -> list[CheckResult]:
    config_path = _get_config_path()
    if not config_path.exists():
        return [
            CheckResult(
                "core",
                "config_file",
                "fail",
                f"Config not found: {config_path}",
                "studyctl config init",
                fix_auto=True,
            )
        ]
    try:
        text = config_path.read_text()
        yaml.safe_load(text)
        return [
            CheckResult("core", "config_file", "pass", f"Config valid: {config_path}", "", False)
        ]
    except yaml.YAMLError as exc:
        return [
            CheckResult(
                "core",
                "config_file",
                "fail",
                f"Invalid YAML in config: {exc}",
                f"Fix syntax errors in {config_path}",
                fix_auto=False,
            )
        ]
