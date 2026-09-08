"""Package-scoped pytest invocations must deselect opt-in live markers.

pytest resolves ``rootdir`` (and therefore its configfile) from the paths it
is given, so any package-scoped invocation -- ``pytest
packages/agent-session-tools/tests/...`` -- reads *this package's*
``pyproject.toml``, never the workspace root's. If the package config lacks
the root's ``-m`` live-marker exclusions, a plain package-scoped run silently
executes the ``live_concepts`` suites: two 1 GB SQLite Online Backups, a
140-second OKF import, and two committed evidence files rewritten (B3 review
round 1, Important #2).

This regression proves, in a subprocess against the real package config, that
package-scoped *collection* deselects every opt-in live test by default while
still selecting ordinary tests. ``--collect-only`` guarantees nothing live
can run even while this test is RED.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]

# Every opt-in (live/infrastructure) suite in this package; keep in step with
# the ``markers`` list in ``pyproject.toml``.
LIVE_TEST_FILES = (
    "test_concept_sidecar_live.py",
    "test_concept_replication_live.py",
    "test_okf_import_live.py",
    "test_ontology_live.py",
)


def _collect(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``pytest --collect-only`` the way a package-scoped caller would."""
    env = dict(os.environ)
    # The point is what the *config file* does; an inherited PYTEST_ADDOPTS
    # would let the environment mask a broken config.
    env.pop("PYTEST_ADDOPTS", None)
    # Two -q: the package addopts carry -v, and node-id parsing below needs
    # the quiet listing, not the verbose collection tree.
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-q",
            "--no-cov",
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=PACKAGE_DIR,
        env=env,
        check=False,
        timeout=120,
    )


def _node_ids(stdout: str) -> set[str]:
    return set(re.findall(r"^\S+::\S+$", stdout, flags=re.MULTILINE))


def test_package_scoped_collection_deselects_live_markers():
    """No live-marked test may be selected by a package-scoped default run.

    ``test_ontology_live.py`` mixes live-marked and ordinary fixture tests,
    so the proof compares node-id sets rather than exit codes: everything an
    explicit ``-m`` opt-in selects (which is also how the live suites are
    meant to be run -- the command line ``-m`` overrides the addopts default)
    must be deselected when the same paths are collected with no ``-m``.
    """
    files = [str(PACKAGE_DIR / "tests" / name) for name in LIVE_TEST_FILES]

    opted_in = _collect(["-m", "live_concepts or live_ontology", *files])
    live_ids = _node_ids(opted_in.stdout)
    # Non-vacuous: the markers still exist and still select the live suites.
    assert len(live_ids) >= len(LIVE_TEST_FILES), opted_in.stdout + opted_in.stderr

    default = _collect(files)
    selected = _node_ids(default.stdout)
    leaked = selected & live_ids
    assert leaked == set(), f"live tests selected by package config: {sorted(leaked)}"
    assert re.search(r"\d+ deselected", default.stdout), default.stdout + default.stderr


def test_package_scoped_collection_still_selects_ordinary_tests():
    """The exclusion must not deselect unmarked tests."""
    result = _collect([str(PACKAGE_DIR / "tests" / "test_migrations.py")])

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(
        r"^\S*test_migrations\.py::\S+", result.stdout, flags=re.MULTILINE
    ), result.stdout
