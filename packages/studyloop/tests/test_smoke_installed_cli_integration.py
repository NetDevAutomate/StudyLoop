"""Executable smoke tests for the installed CLI smoke script."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "smoke-installed-cli.sh"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_fake_studyloop(bin_dir: Path) -> None:
    executable = bin_dir / "studyloop"
    _write_executable(
        executable,
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
      if [ -n "${SELF_TEST_JSON+x}" ]; then
        printf '%s\\n' "$SELF_TEST_JSON"
      else
        printf '[{"status": "pass"}]\\n'
      fi
      exit "${SELF_TEST_STATUS:-0}"
    fi
    ;;
  doctor)
    if [ "${2:-}" = "--json" ]; then
      if [ -n "${DOCTOR_JSON+x}" ]; then
        printf '%s\\n' "$DOCTOR_JSON"
      else
        printf '[{"status": "pass"}]\\n'
      fi
      exit "${DOCTOR_STATUS:-0}"
    fi
    ;;
esac

echo "unexpected command: $*" >&2
exit 64
""",
    )


def _write_fake_session_export(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "session-export",
        """#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  --help)
    echo "session-export help"
    exit 0
    ;;
esac

echo "unexpected command: $*" >&2
exit 64
""",
    )


def _write_fake_python3(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "python3",
        f"""#!/usr/bin/env bash
exec {sys.executable!r} "$@"
""",
    )


def _run_smoke(
    tmp_path: Path,
    *,
    write_session_export: bool = True,
    include_user_path: bool = True,
    path_prefix: str | None = None,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    _write_fake_studyloop(tmp_path)
    if write_session_export:
        _write_fake_session_export(tmp_path)
    env = os.environ.copy()
    env.update(overrides)
    path_entries = [str(path_prefix or tmp_path)]
    if include_user_path:
        path_entries.append(env["PATH"])
    else:
        tools_dir = tmp_path / "_tools"
        tools_dir.mkdir()
        _write_fake_python3(tools_dir)
        path_entries.append(str(tools_dir))
        path_entries.extend(["/usr/bin", "/bin"])
    env["PATH"] = os.pathsep.join(dict.fromkeys(path_entries))

    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
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


def test_smoke_installed_cli_requires_session_export(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, write_session_export=False, include_user_path=False)

    assert result.returncode == 127
    assert "session-export is not on PATH" in result.stderr


def test_smoke_installed_cli_accepts_expected_bin_dir(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, STUDYLOOP_EXPECT_BIN_DIR=str(tmp_path))

    assert result.returncode == 0


def test_smoke_installed_cli_rejects_studyloop_outside_expected_bin_dir(
    tmp_path: Path,
) -> None:
    expected_bin = tmp_path / "expected-bin"
    expected_bin.mkdir()

    result = _run_smoke(tmp_path, STUDYLOOP_EXPECT_BIN_DIR=str(expected_bin))

    assert result.returncode == 127
    assert "studyloop resolves outside expected bin dir" in result.stderr


def test_smoke_installed_cli_rejects_session_export_outside_expected_bin_dir(
    tmp_path: Path,
) -> None:
    expected_bin = tmp_path / "expected-bin"
    expected_bin.mkdir()
    _write_fake_studyloop(expected_bin)
    _write_fake_session_export(tmp_path)

    result = _run_smoke(
        tmp_path,
        write_session_export=False,
        path_prefix=f"{expected_bin}{os.pathsep}{tmp_path}",
        STUDYLOOP_EXPECT_BIN_DIR=str(expected_bin),
    )

    assert result.returncode == 127
    assert "session-export resolves outside expected bin dir" in result.stderr


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


def test_smoke_installed_cli_accepts_doctor_warning_status(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        DOCTOR_STATUS="1",
        DOCTOR_JSON='[{"status": "warn"}]',
    )

    assert result.returncode == 0


def test_smoke_installed_cli_rejects_unexpected_doctor_exit_status(
    tmp_path: Path,
) -> None:
    result = _run_smoke(
        tmp_path,
        DOCTOR_STATUS="2",
        DOCTOR_JSON='[{"status": "fail"}]',
    )

    assert result.returncode == 2
    assert '{"status": "fail"}' in result.stderr


def test_smoke_installed_cli_rejects_invalid_doctor_json(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, DOCTOR_STATUS="0", DOCTOR_JSON="not-json")

    assert result.returncode == 1
    assert "Expecting value" in result.stderr


def test_smoke_installed_cli_rejects_unexpected_doctor_json_status(
    tmp_path: Path,
) -> None:
    result = _run_smoke(
        tmp_path,
        DOCTOR_STATUS="0",
        DOCTOR_JSON='[{"status": "mystery"}]',
    )

    assert result.returncode == 1
    assert "unexpected doctor status: mystery" in result.stderr
