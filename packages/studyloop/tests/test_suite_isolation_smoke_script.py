"""The installed-CLI smoke must never run against the caller's own StudyLoop files.

``scripts/smoke-installed-cli.sh`` (``just smoke-installed``, ``release-check``)
runs ``studyloop self-test`` and ``studyloop doctor`` against the release under
test. Both read -- and doctor migrates -- the session database, and both resolve
the state dir and config through ``STUDYLOOP_DB``, ``STUDYLOOP_STATE_DIR`` and
``STUDYLOOP_CONFIG``. The setup guide tells learners to ``export
STUDYLOOP_CONFIG=...`` for an alternate profile, so those variables are often
already set in the shell that runs the smoke. The script has to replace them,
exactly as the conftests do for the suite (F-XCUT-01), not default them.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _WORKSPACE_ROOT / "scripts" / "smoke-installed-cli.sh"

#: The variables that name a learner's writable StudyLoop state.
_STATE_VARIABLES = ("STUDYLOOP_CONFIG", "STUDYLOOP_DB", "STUDYLOOP_STATE_DIR")

#: Inputs the script is MEANT to take from its caller. ``STUDYLOOP_EXPECT_BIN_DIR``
#: is set by the ``smoke-installed`` recipe and ``smoke-uv-tool-install.sh`` to
#: name the bin dir the CLI must resolve from; it never names learner state.
_CALLER_INPUTS = frozenset({"STUDYLOOP_EXPECT_BIN_DIR"})

_DEFAULTED_READ = re.compile(r"\$\{(STUDYLOOP_[A-Z0-9_]+):?[-=]")
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?(STUDYLOOP_[A-Z0-9_]+)=(.*)$", re.MULTILINE)
_EXPORT_LINE = re.compile(r"^\s*export\s+(.*)$", re.MULTILINE)


def test_smoke_script_assigns_studyloop_state_without_reading_the_callers_value() -> None:
    """No ``STUDYLOOP_*`` state variable may survive from the caller's shell.

    ``${STUDYLOOP_DB:-$(mktemp -d)/sessions.db}`` keeps an exported value, so a
    learner whose shell names their real sessions.db had it read and migrated by
    the smoke. Each state variable must be assigned from ``mktemp -d`` alone,
    and exported.
    """
    script = _SCRIPT.read_text(encoding="utf-8")

    defaulted = sorted(
        {name for name in _DEFAULTED_READ.findall(script) if name not in _CALLER_INPUTS}
    )
    assert defaulted == [], (
        "scripts/smoke-installed-cli.sh keeps the caller's value of these variables "
        f"through a ${{VAR:-default}} expansion: {defaulted}"
    )

    assignments: dict[str, list[str]] = {}
    for name, value in _ASSIGNMENT.findall(script):
        assignments.setdefault(name, []).append(value)
    exported = {
        word.split("=", 1)[0] for line in _EXPORT_LINE.findall(script) for word in line.split()
    }
    for name in _STATE_VARIABLES:
        assert name in assignments, f"the smoke script no longer assigns {name}"
        assert name in exported, f"the smoke script no longer exports {name}"
        for value in assignments[name]:
            assert "STUDYLOOP_" not in value, (
                f"{name} is assigned from an expression that reads a STUDYLOOP_ variable: {value!r}"
            )
            assert value.startswith('"$(mktemp -d)/'), (
                f"{name} must be assigned under a fresh mktemp -d directory: {value!r}"
            )


_FAKE_STUDYLOOP = """#!/usr/bin/env bash
set -euo pipefail
# Record the paths this invocation was handed, then write through each one the
# way the real CLI does (doctor migrates the DB, self-test persists state).
printf '%s\\t%s\\t%s\\t%s\\n' "${1:-}" "$STUDYLOOP_CONFIG" "$STUDYLOOP_DB" \\
  "$STUDYLOOP_STATE_DIR" >>"$SMOKE_ISOLATION_LOG"
for path in "$STUDYLOOP_CONFIG" "$STUDYLOOP_DB"; do
  mkdir -p "$(dirname "$path")"
  printf 'written by the fake studyloop\\n' >>"$path"
done
mkdir -p "$STUDYLOOP_STATE_DIR"
printf 'written by the fake studyloop\\n' >>"$STUDYLOOP_STATE_DIR/fake-cli-write"
case "${1:-}" in
  self-test|doctor) printf '[{"status": "pass"}]\\n' ;;
esac
"""

_FAKE_SESSION_EXPORT = """#!/usr/bin/env bash
exit 0
"""


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_smoke_script_leaves_exported_studyloop_paths_untouched(tmp_path: Path) -> None:
    """Run the script with the three variables exported at decoy learner files.

    Fake ``studyloop`` / ``session-export`` binaries record what they were handed
    and write through it. The decoys must come out byte-identical, and no path
    the CLI saw may name one of them. (Where the fresh paths land is not
    asserted: macOS ``mktemp -d`` ignores ``TMPDIR`` and always uses the per-user
    temp dir.)
    """
    ambient = tmp_path / "ambient-learner"
    (ambient / "state").mkdir(parents=True)
    (ambient / "state" / "sentinel.txt").write_bytes(b"ambient learner state\n")
    (ambient / "sessions.db").write_bytes(b"ambient learner sessions.db\n")
    (ambient / "config.yaml").write_bytes(b"# ambient learner config\n")
    before = _tree_bytes(ambient)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "studyloop", _FAKE_STUDYLOOP)
    _write_executable(bin_dir / "session-export", _FAKE_SESSION_EXPORT)
    log = tmp_path / "fake-cli.log"

    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(bin_dir), os.environ["PATH"]]),
        "STUDYLOOP_EXPECT_BIN_DIR": str(bin_dir),
        "STUDYLOOP_CONFIG": str(ambient / "config.yaml"),
        "STUDYLOOP_DB": str(ambient / "sessions.db"),
        "STUDYLOOP_STATE_DIR": str(ambient / "state"),
        "SMOKE_ISOLATION_LOG": str(log),
    }
    result = subprocess.run(
        ["/bin/bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _tree_bytes(ambient) == before, (
        "the smoke script handed the CLI the caller's exported STUDYLOOP_* paths, "
        "and the CLI wrote into them"
    )
    calls = [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines()]
    assert {call[0] for call in calls} >= {"self-test", "doctor"}
    for command, *paths in calls:
        for path in paths:
            assert not Path(path).resolve().is_relative_to(ambient.resolve()), (
                f"`studyloop {command}` was handed the caller's exported path {path!r}"
            )
