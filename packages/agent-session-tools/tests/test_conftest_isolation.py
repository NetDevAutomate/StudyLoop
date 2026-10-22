"""An exported ``STUDYLOOP_*`` must not reach a path-scoped run of this package.

``pytest packages/agent-session-tools/tests`` (or ``pytest tests`` from this
package) takes this package's ``pyproject.toml`` as its config, so the
workspace-root ``conftest.py`` -- which hard-assigns ``STUDYLOOP_DB``,
``STUDYLOOP_STATE_DIR`` and ``STUDYLOOP_CONFIG`` at import time -- is never
loaded. This package's conftest redirects all three per test, in autouse
fixtures, but anything that runs before the first test (test-module import,
collection hooks, session-scoped fixtures) saw the caller's values: a learner's
shell that exports them points at their real sessions.db, state dir and config.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE_ROOT = _PACKAGE_ROOT.parents[1]

# A ``-p`` plugin the child pytest loads. Once collection has finished (every
# conftest and test module imported, no test yet run) it writes through this
# package's own resolvers, so whichever paths collection-time code resolved --
# the sandbox or the caller's ambient ones -- receive the writes. It refuses to
# write under the real StudyLoop directories, so a broken sandbox can only hit
# the decoys.
_PROBE_PLUGIN = '''
"""Write through agent_session_tools' state resolvers after collection."""

import contextlib
import json
import os
import sqlite3
from pathlib import Path


def pytest_collection_finish(session):
    from agent_session_tools.config_loader import get_config_file, get_db_path
    from agent_session_tools.load_indicator import state_dir

    resolved = {
        "STUDYLOOP_DB": Path(get_db_path()),
        "STUDYLOOP_STATE_DIR": Path(state_dir()),
        "STUDYLOOP_CONFIG": Path(get_config_file()),
    }
    Path(os.environ["CONFTEST_ISOLATION_PROBE_REPORT"]).write_text(
        json.dumps({name: str(path) for name, path in resolved.items()})
    )

    home = Path.home().resolve()
    real_roots = [
        home / ".config" / "studyloop",
        home / ".local" / "share" / "studyloop",
        home / ".studyloop",
    ]
    for name, path in resolved.items():
        target = path.expanduser().resolve()
        if any(target == root or target.is_relative_to(root) for root in real_roots):
            raise RuntimeError(f"probe refuses to write real state: {name} -> {target}")

    db = resolved["STUDYLOOP_DB"]
    db.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(db)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS conftest_isolation_probe (x)")
        connection.commit()
    state = resolved["STUDYLOOP_STATE_DIR"]
    state.mkdir(parents=True, exist_ok=True)
    (state / "conftest-isolation-probe").write_text("probe\\n")
    config = resolved["STUDYLOOP_CONFIG"]
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("# conftest-isolation probe\\n")
'''

_SQLITE_HEADER = b"SQLite format 3\x00"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.mark.timeout(240)
def test_path_scoped_collection_never_resolves_ambient_studyloop_paths(
    tmp_path: Path,
) -> None:
    """Collect this package path-scoped with the three variables at decoys.

    Two spellings of a path-scoped run: from this package's directory, and from
    the workspace root naming this package's tests. Collect only and select
    nothing (exit 5), so no test is coupled to this one. The decoys must come
    out byte-identical and the decoy sessions.db must never become a database.
    """
    ambient = tmp_path / "ambient-learner"
    ambient.mkdir()
    decoy_db = ambient / "sessions.db"
    decoy_db.write_bytes(b"")  # empty: sqlite would adopt it and write a header
    decoy_state = ambient / "state"
    decoy_state.mkdir()
    (decoy_state / "sentinel.txt").write_bytes(b"ambient learner state\n")
    decoy_config = ambient / "config.yaml"
    decoy_config.write_bytes(b"# ambient learner config\n")
    before = _tree_bytes(ambient)

    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "conftest_isolation_probe.py").write_text(
        _PROBE_PLUGIN, encoding="utf-8"
    )

    collect_nothing = [
        "--collect-only",
        "-m",
        "conftest_isolation_probe_selects_nothing",
    ]
    # label -> (working directory, pytest arguments)
    invocations: dict[str, tuple[Path, list[str]]] = {
        "from the package directory": (_PACKAGE_ROOT, [*collect_nothing, "tests"]),
        "from the workspace root": (
            _WORKSPACE_ROOT,
            [*collect_nothing, str(_PACKAGE_ROOT / "tests")],
        ),
    }

    for label, (cwd, pytest_args) in invocations.items():
        report = tmp_path / f"probe-report-{label}.json"
        env = {
            **os.environ,
            "STUDYLOOP_DB": str(decoy_db),
            "STUDYLOOP_STATE_DIR": str(decoy_state),
            "STUDYLOOP_CONFIG": str(decoy_config),
            "CONFTEST_ISOLATION_PROBE_REPORT": str(report),
            "PYTHONPATH": os.pathsep.join(
                p for p in (str(probe_dir), os.environ.get("PYTHONPATH", "")) if p
            ),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                "-p",
                "conftest_isolation_probe",
                *pytest_args,
            ],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=200,
            check=False,
        )
        output = (result.stdout + result.stderr)[-4000:]
        assert result.returncode == 5, (
            f"[{label}] child pytest exited {result.returncode}, expected 5:\n{output}"
        )
        assert report.is_file(), f"[{label}] the probe plugin never ran:\n{output}"

        resolved = json.loads(report.read_text(encoding="utf-8"))
        leaked = {
            name: path
            for name, path in resolved.items()
            if Path(path).is_relative_to(ambient)
        }
        assert _tree_bytes(ambient) == before, (
            f"[{label}] the decoy learner files were modified; collection resolved "
            f"the caller's ambient paths instead of a sandbox: {leaked}"
        )
        assert not decoy_db.read_bytes().startswith(_SQLITE_HEADER), (
            f"[{label}] the decoy sessions.db was opened and written as a database"
        )
        assert leaked == {}, (
            f"[{label}] collection resolved the caller's ambient paths: {leaked}"
        )
