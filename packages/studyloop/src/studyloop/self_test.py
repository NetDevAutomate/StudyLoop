"""Lightweight post-install self-tests for studyloop.

These checks are intentionally smaller and safer than ``studyloop doctor``:
they validate basic imports, config readability, and the sessions DB path
without starting services, contacting external systems, or installing files.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_STATUSES = frozenset({"pass", "warn", "fail"})


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    """Single self-test result for CLI and JSON output."""

    name: str
    status: str
    message: str

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            msg = f"status must be one of {sorted(VALID_STATUSES)}, got {self.status!r}"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-serializable representation."""
        return {"name": self.name, "status": self.status, "message": self.message}


def _read_config() -> tuple[Path, dict[str, Any] | None, SelfTestResult]:
    from studyloop.settings import get_config_path

    config_path = get_config_path()
    if not config_path.exists():
        return (
            config_path,
            None,
            SelfTestResult(
                "config_read",
                "warn",
                f"Config not found: {config_path}. Run 'studyloop setup' when ready.",
            ),
        )

    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return (
            config_path,
            None,
            SelfTestResult("config_read", "fail", f"Could not read config: {exc}"),
        )
    except yaml.YAMLError as exc:
        return (
            config_path,
            None,
            SelfTestResult("config_read", "fail", f"Invalid YAML in config: {exc}"),
        )

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return (
            config_path,
            None,
            SelfTestResult("config_read", "fail", "Config must be a YAML mapping."),
        )

    return (
        config_path,
        loaded,
        SelfTestResult("config_read", "pass", f"Config readable: {config_path}"),
    )


def _database_path_from_config(config_path: Path, raw_config: dict[str, Any] | None) -> Path:
    raw_config = raw_config or {}
    db_value = raw_config.get("session_db")
    if not db_value:
        database_section = raw_config.get("database", {})
        if isinstance(database_section, dict):
            db_value = database_section.get("path")

    if db_value:
        return Path(str(db_value)).expanduser()
    return config_path.parent / "sessions.db"


def _check_import(name: str, module_name: str) -> SelfTestResult:
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        return SelfTestResult(name, "fail", f"Could not import {module_name}: {exc}")
    return SelfTestResult(name, "pass", f"Imported {module_name}")


def _check_web_import() -> SelfTestResult:
    try:
        importlib.import_module("studyloop.web.app")
    except ImportError as exc:
        return SelfTestResult(
            "web_import",
            "warn",
            f"Web extra unavailable or incomplete: {exc}",
        )
    return SelfTestResult("web_import", "pass", "Imported studyloop.web.app")


def _check_database_path(config_path: Path, raw_config: dict[str, Any] | None) -> SelfTestResult:
    db_path = _database_path_from_config(config_path, raw_config)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return SelfTestResult(
            "database_path",
            "fail",
            f"Could not create database directory {db_path.parent}: {exc}",
        )
    return SelfTestResult("database_path", "pass", f"Database path usable: {db_path}")


def run_self_tests() -> list[SelfTestResult]:
    """Run lightweight checks that are safe immediately after installation."""
    config_path, raw_config, config_result = _read_config()
    return [
        _check_import("cli_import", "studyloop.cli"),
        config_result,
        _check_database_path(config_path, raw_config),
        _check_web_import(),
    ]


def exit_code_for(results: list[SelfTestResult]) -> int:
    """Return process exit code for self-test results."""
    if any(result.status == "fail" for result in results):
        return 2
    if any(result.status == "warn" for result in results):
        return 1
    return 0


def results_as_json(results: list[SelfTestResult]) -> str:
    """Render self-test results as formatted JSON."""
    return json.dumps([result.to_dict() for result in results], indent=2)
