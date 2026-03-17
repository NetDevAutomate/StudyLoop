"""PyPI version checks with 1-hour file cache."""

from __future__ import annotations

import importlib.metadata
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from studyctl.doctor.models import CheckResult

CACHE_TTL_SECONDS = 3600  # 1 hour
PACKAGES_TO_CHECK = ["studyctl", "agent-session-tools"]


def _get_cache_path() -> Path:
    cache_dir = Path.home() / ".cache" / "studyctl"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "pypi-check.json"


def _read_cache() -> dict[str, str] | None:
    path = _get_cache_path()
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(data: dict[str, str]) -> None:
    path = _get_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _get_installed_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _fetch_pypi_version(package: str) -> str | None:
    url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "studyctl-doctor/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data["info"]["version"]


def check_pypi_versions() -> list[CheckResult]:
    cached = _read_cache()
    latest_versions: dict[str, str] = {}

    if cached is None:
        try:
            for pkg in PACKAGES_TO_CHECK:
                v = _fetch_pypi_version(pkg)
                if v:
                    latest_versions[pkg] = v
            _write_cache(latest_versions)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return [
                CheckResult(
                    "updates",
                    "pypi_check",
                    "info",
                    "Could not reach PyPI (offline?)",
                    "Check network connection",
                    False,
                )
            ]
    else:
        latest_versions = cached

    results: list[CheckResult] = []
    for pkg in PACKAGES_TO_CHECK:
        installed = _get_installed_version(pkg)
        if installed is None:
            continue
        latest = latest_versions.get(pkg)
        if latest is None:
            results.append(
                CheckResult(
                    "updates", f"update_{pkg}", "info", f"{pkg} not found on PyPI", "", False
                )
            )
            continue
        if installed == latest:
            results.append(
                CheckResult(
                    "updates", f"update_{pkg}", "pass", f"{pkg} {installed} (latest)", "", False
                )
            )
        else:
            results.append(
                CheckResult(
                    "updates",
                    f"update_{pkg}",
                    "warn",
                    f"{pkg} {installed} -> {latest} available",
                    "studyctl upgrade --component packages",
                    fix_auto=True,
                )
            )
    return results
