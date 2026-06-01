"""Executable smoke tests for the installed CLI smoke script."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "smoke-installed-cli.sh"


def _write_fake_studyloop(bin_dir: Path) -> None:
    executable = bin_dir / "studyloop"
    executable.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  --help)
    echo "studyloop help"
    exit 0
    ;;
  config|content|review)
    if [ "${2:-}" = "--help" ]; then
      echo "$1 help"
      exit 0
    fi
    ;;
  self-test)
    if [ "${2:-}" = "--json" ]; then
      printf '%s\\n' "${SELF_TEST_JSON:-{\\"status\\": \\"ok\\"}}"
      exit "${SELF_TEST_STATUS:-0}"
    fi
    ;;
  doctor)
    if [ "${2:-}" = "--json" ]; then
      printf '%s\\n' "${DOCTOR_JSON:-{\\"status\\": \\"ok\\"}}"
      exit "${DOCTOR_STATUS:-0}"
    fi
    ;;
esac

echo "unexpected command: $*" >&2
exit 64
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)


def _run_smoke(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    _write_fake_studyloop(tmp_path)
    env = os.environ.copy()
    env.update(overrides)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_smoke_installed_cli_accepts_self_test_json_exit_0(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, SELF_TEST_STATUS="0")

    assert result.returncode == 0


def test_smoke_installed_cli_accepts_self_test_json_exit_1(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, SELF_TEST_STATUS="1")

    assert result.returncode == 0


def test_smoke_installed_cli_rejects_unexpected_self_test_status(
    tmp_path: Path,
) -> None:
    result = _run_smoke(
        tmp_path,
        SELF_TEST_STATUS="7",
        SELF_TEST_JSON='{"status": "unexpected"}',
    )

    assert result.returncode == 7
    assert '{"status": "unexpected"}' in result.stderr


def test_smoke_installed_cli_rejects_invalid_self_test_json(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, SELF_TEST_STATUS="0", SELF_TEST_JSON="not-json")

    assert result.returncode == 1
    assert "Expecting value" in result.stderr
