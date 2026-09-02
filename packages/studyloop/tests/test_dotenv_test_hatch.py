"""R-09: a planted `.env` must not be able to set a STUDYLOOP_TEST_* hatch.

``STUDYLOOP_TEST_AGENT_CMD`` / ``STUDYLOOP_TEST_ACP_CMD`` are shell=True-executed
test-only escape hatches, honoured unconditionally in the production
``/api/session/start`` path. The package auto-loads a `.env` on import, walking
up to six parent directories from ``cwd`` with ``override=False`` -- which
skips a name the shell has already exported, but NOT a name that is simply
absent. A `.env` planted in or above wherever a user runs `studyloop` from
could therefore set the hatch itself and get shell execution on the next
session start, through the Web UI too.

The fix (studyloop/__init__.py, snapshot-before-dotenv) is a package-import-time
side effect, so it can only be observed honestly in a FRESH interpreter --
importing `studyloop` a second time in the same process is a no-op. Every test
here spawns a subprocess with a controlled `cwd` and a controlled environment,
exactly as the review's own test recipe specifies.
"""

import os
import subprocess
import sys
from pathlib import Path

_IMPORT_AND_PRINT_HATCH = (
    "import studyloop, os; print(repr(os.environ.get('STUDYLOOP_TEST_AGENT_CMD')))"
)


def _write_env_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "STUDYLOOP_TEST_AGENT_CMD=/bin/false\nSTUDYLOOP_OTHER_THING=hello-from-dotenv\n"
    )


def _run(tmp_path: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), **extra_env}
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_AND_PRINT_HATCH],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_dotenv_cannot_set_the_test_hatch_in_a_clean_environment(tmp_path: Path) -> None:
    """The whole point of R-09: a real user's shell has no reason to export
    STUDYLOOP_TEST_AGENT_CMD, so a `.env` planted in their cwd must not be
    able to set it on their behalf."""
    _write_env_file(tmp_path)

    proc = _run(tmp_path, extra_env={})

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "None"


def test_dotenv_warns_once_naming_the_key_and_the_env_path(tmp_path: Path) -> None:
    _write_env_file(tmp_path)

    proc = _run(tmp_path, extra_env={})

    assert "STUDYLOOP_TEST_AGENT_CMD" in proc.stderr
    assert str(tmp_path / ".env") in proc.stderr


def test_harness_exported_hatch_still_works(tmp_path: Path) -> None:
    """The e2e harness exports the hatch for real, in the process's actual
    environment, before studyloop is even imported -- R-09 must not break
    that path. A name present BEFORE the dotenv load is trusted and kept,
    even though the SAME `.env` also tries to set it to a different value
    (override=False already means the real export wins over the file)."""
    _write_env_file(tmp_path)

    proc = _run(tmp_path, extra_env={"STUDYLOOP_TEST_AGENT_CMD": "from-parent-env"})

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == repr("from-parent-env")
    assert proc.stderr == ""


def test_dotenv_other_keys_still_load(tmp_path: Path) -> None:
    """Only the STUDYLOOP_TEST_* hatch is refused; an ordinary key from the
    same `.env` file (e.g. a provider API key) still loads normally."""
    _write_env_file(tmp_path)

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import studyloop, os; print(repr(os.environ.get('STUDYLOOP_OTHER_THING')))",
        ],
        cwd=str(tmp_path),
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == repr("hello-from-dotenv")


def test_no_env_file_is_a_silent_no_op(tmp_path: Path) -> None:
    """No `.env` at all: nothing to scrub, nothing to warn about."""
    proc = _run(tmp_path, extra_env={})

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "None"
    assert proc.stderr == ""
