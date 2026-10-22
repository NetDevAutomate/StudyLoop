"""Guards for the suite's own isolation wiring.

The fixtures and import-time environment that keep tests away from the
learner's real state live in the conftest files. The checks that prove that
wiring still holds live here, because pytest collects only ``test_*.py``
modules: a ``def test_*`` inside a ``conftest.py`` is loaded as plugin code and
never runs.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _TESTS_DIR.parents[2]


def _conftest_files() -> list[Path]:
    """Every conftest.py pytest can load for the workspace's default run."""
    files = [_WORKSPACE_ROOT / "conftest.py"]
    for package_tests in sorted((_WORKSPACE_ROOT / "packages").glob("*/tests")):
        files.extend(sorted(package_tests.rglob("conftest.py")))
    return [path for path in files if path.is_file()]


def test_no_test_functions_are_defined_in_conftest() -> None:
    """A test defined in a conftest is never collected, so it can never fail.

    Three isolation guards lived in ``packages/studyloop/tests/conftest.py`` and
    their docstrings promised they would "fail loudly in CI"; none had ever run.
    """
    conftests = _conftest_files()
    assert _WORKSPACE_ROOT / "conftest.py" in conftests
    assert _TESTS_DIR / "conftest.py" in conftests

    offenders: list[str] = []
    for path in conftests:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                collectable = node.name.startswith("test")
            elif isinstance(node, ast.ClassDef):
                collectable = node.name.startswith("Test")
            else:
                continue
            if collectable:
                offenders.append(f"{path.relative_to(_WORKSPACE_ROOT)}:{node.lineno} {node.name}")

    assert offenders == [], (
        "pytest never collects tests defined in a conftest.py; move these into a "
        "test_*.py module:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Guards moved out of conftest.py, where pytest never collected them.
#
# They read the conftest's names from the module pytest actually loaded as a
# plugin, not through ``from conftest import ...``. Under the workspace default
# ``--import-mode=importlib`` that import executes the file a second time as a
# separate module, so its mkdtemp'd ``_TMUX_TMPDIR_ROOT`` is a different
# directory from the one ``pytest_sessionstart`` exported -- the tmux guard,
# copied verbatim, failed for that reason alone the first time it was collected.
# ---------------------------------------------------------------------------


def _loaded_package_conftest(config: pytest.Config) -> ModuleType:
    """Return the ``packages/studyloop/tests/conftest.py`` module whose hooks run."""
    target = _TESTS_DIR / "conftest.py"
    for plugin in config.pluginmanager.get_plugins():
        location = getattr(plugin, "__file__", None)
        if isinstance(plugin, ModuleType) and location and Path(location).resolve() == target:
            return plugin
    raise AssertionError(f"pytest did not load {target} as a plugin")


def test_session_dir_is_isolated_from_the_real_config_dir(pytestconfig: pytest.Config) -> None:
    """Guard: every session-dir constant the conftest's autouse fixture patches
    must actually point away from ~/.config/studyloop, in every module that
    binds its own copy.

    Companion to test_no_test_writes_to_real_user_state below -- same shape,
    different subsystem (session_state.py's SESSION_DIR family rather than
    load_settings().state_dir). Assertion-only: never itself writes
    anywhere, so it cannot trip the session-runtime snapshot guard.
    """
    import importlib

    conftest = _loaded_package_conftest(pytestconfig)
    real = str(Path.home() / ".config" / "studyloop")
    for module_name in conftest._SESSION_DIR_CONSTANT_MODULES:
        module = importlib.import_module(module_name)
        for attr, _filename in conftest._SESSION_DIR_CONSTANT_FILENAMES:
            if not hasattr(module, attr):
                continue
            value = str(getattr(module, attr))
            assert not value.startswith(real), (
                f"{module_name}.{attr} == {value!r} still resolves under the real "
                "config dir -- the autouse isolation fixture did not retarget it"
            )


def test_tmux_socket_is_isolated_from_the_real_tmux_server(pytestconfig: pytest.Config) -> None:
    """Guard (C11/R-49e): TMUX_TMPDIR must actually point at the private
    directory pytest_sessionstart created, and TMUX must be unset.

    Assertion-only: never itself starts a tmux session, so it cannot trip
    the private-socket guard in pytest_sessionfinish.
    """
    conftest = _loaded_package_conftest(pytestconfig)
    assert os.environ.get("TMUX_TMPDIR") == str(conftest._TMUX_TMPDIR_ROOT)
    assert "TMUX" not in os.environ


def test_no_test_writes_to_real_user_state() -> None:
    """Guard: the suite must never resolve writable state to the real dirs.

    Asserted as a test, not just a fixture, so the invariant fails loudly in
    CI if the env-var wiring in conftest.py is ever removed or reordered.

    Both resolvers are checked. ``studyloop.settings`` and
    ``agent_session_tools.config_loader`` compute the session DB path
    independently, and covering only one of them left the real database being
    migrated by test runs.
    """
    from agent_session_tools.config_loader import DEFAULT_CONFIG
    from agent_session_tools.config_loader import get_db_path as ast_get_db_path
    from studyloop.settings import (
        CONFIG_DIR,
        DEFAULT_DB,
        DEFAULT_STATE_DIR,
        get_config_path,
        get_db_path,
        get_state_dir,
        load_settings,
    )

    assert get_state_dir() != DEFAULT_STATE_DIR, "state_dir escaped test isolation"
    assert get_db_path() != DEFAULT_DB, "studyloop session DB escaped test isolation"
    assert load_settings().session_db != DEFAULT_DB, (
        "Settings.session_db escaped test isolation (history/_connection.py reads this one)"
    )
    assert str(ast_get_db_path()) != DEFAULT_CONFIG["database"]["path"], (
        "agent_session_tools session DB escaped test isolation"
    )
    from studyloop import settings as _settings_mod

    real_config = CONFIG_DIR / "config.yaml"
    assert get_config_path() != real_config, (
        "config.yaml escaped test isolation -- STUDYLOOP_CONFIG was not set "
        "before studyloop imports (this is how a test overwrote the real "
        "learner config on 2026-09-05)"
    )
    assert real_config != _settings_mod._CONFIG_PATH, (
        "the import-time _CONFIG_PATH constant still points at the real "
        "config.yaml -- STUDYLOOP_CONFIG must be exported at conftest import "
        "time, not per-test, or legacy call sites write to the real file"
    )


# ---------------------------------------------------------------------------
# Ambient STUDYLOOP_* variables must not reach the suite.
# ---------------------------------------------------------------------------

# A ``-p`` plugin the child pytest loads. Once collection has finished (every
# conftest imported, no test yet run) it writes through the same resolvers any
# test would use, so whichever paths the suite resolved -- the sandbox or the
# caller's ambient ones -- receive the writes. It refuses to write anywhere under
# the real StudyLoop directories, so a broken sandbox can only hit the decoys.
_PROBE_PLUGIN = '''
"""Write through StudyLoop's state resolvers after the conftests have loaded."""

import contextlib
import json
import os
import sqlite3
from pathlib import Path


def pytest_collection_finish(session):
    from agent_session_tools.config_loader import get_db_path as ast_get_db_path
    from studyloop.settings import get_config_path, get_db_path, get_state_dir

    resolved = {
        "STUDYLOOP_DB (studyloop.settings)": Path(get_db_path()),
        "STUDYLOOP_DB (agent_session_tools)": Path(ast_get_db_path()),
        "STUDYLOOP_STATE_DIR": Path(get_state_dir()),
        "STUDYLOOP_CONFIG": Path(get_config_path()),
    }
    # Only the studyloop package conftest isolates the second-brain vault (no
    # agent-session-tools code reads it), so the vault is probed only where
    # that conftest is loaded.
    probe_vault = os.environ.get("SUITE_ISOLATION_PROBE_VAULT") == "1"
    if probe_vault:
        from studyloop.settings import load_settings

        resolved["STUDYLOOP_SECOND_BRAIN_VAULT"] = Path(load_settings().second_brain.vault_path)
    Path(os.environ["SUITE_ISOLATION_PROBE_REPORT"]).write_text(
        json.dumps({name: str(path) for name, path in resolved.items()})
    )

    home = Path.home().resolve()
    real_roots = [
        home / ".config" / "studyloop",
        home / ".local" / "share" / "studyloop",
        home / ".studyloop",
        home / "Obsidian",
    ]
    for name, path in resolved.items():
        target = path.expanduser().resolve()
        if any(target == root or target.is_relative_to(root) for root in real_roots):
            raise RuntimeError(f"probe refuses to write real state: {name} -> {target}")

    for name in ("STUDYLOOP_DB (studyloop.settings)", "STUDYLOOP_DB (agent_session_tools)"):
        db = resolved[name]
        db.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(db)) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS suite_isolation_probe (x)")
            connection.commit()
    state = resolved["STUDYLOOP_STATE_DIR"]
    state.mkdir(parents=True, exist_ok=True)
    (state / "suite-isolation-probe").write_text("probe\\n")
    config = resolved["STUDYLOOP_CONFIG"]
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("# suite-isolation probe\\n")
    if probe_vault:
        vault = resolved["STUDYLOOP_SECOND_BRAIN_VAULT"]
        vault.mkdir(parents=True, exist_ok=True)
        (vault / "suite-isolation-probe.md").write_text("probe\\n")
'''

_SQLITE_HEADER = b"SQLite format 3\x00"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (or ``root`` itself) mapped to its contents."""
    if root.is_file():
        return {root.name: root.read_bytes()}
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.mark.timeout(180)
def test_ambient_studyloop_env_cannot_reach_real_state(tmp_path: Path) -> None:
    """An exported ``STUDYLOOP_DB`` / ``STATE_DIR`` / ``CONFIG`` must not reach tests.

    The setup guide tells learners to ``export STUDYLOOP_CONFIG=...`` for an
    alternate profile, and the same variables point at their real sessions.db
    and state dir. With ``os.environ.setdefault`` in the conftests, a suite run
    from such a shell resolved -- and wrote -- the learner's own files.

    A child pytest loads the conftests with the three variables pointing at
    decoys, in each configuration a developer runs: the workspace root, the
    studyloop package alone, and the workspace root over agent-session-tools
    alone. The probe plugin above then writes through the resolvers; the decoys
    must come out byte-identical and must never have been opened as a database.

    ``STUDYLOOP_SECOND_BRAIN_VAULT`` gets the same decoy treatment wherever the
    studyloop package conftest loads: a vault holds notes the learner wrote by
    hand, and an import-time ``setdefault`` kept an exported value until the
    first per-test fixture ran, so collection and session-scoped code saw it.
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
    decoy_vault = ambient / "vault"
    (decoy_vault / "Study").mkdir(parents=True)
    (decoy_vault / "Study" / "note.md").write_bytes(b"a note the learner wrote\n")
    before = _tree_bytes(ambient)

    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "suite_isolation_probe.py").write_text(_PROBE_PLUGIN, encoding="utf-8")

    trivial_test = (
        f"{Path(__file__).resolve()}::test_tmux_socket_is_isolated_from_the_real_tmux_server"
    )
    workspace_config = [
        "-c",
        str(_WORKSPACE_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_WORKSPACE_ROOT),
    ]
    # label -> (pytest arguments, expected exit code, probe the vault)
    invocations: dict[str, tuple[list[str], int, bool]] = {
        # Root conftest, then this package's conftest.
        "workspace": ([*workspace_config, trivial_test], 0, True),
        # packages/studyloop/pyproject.toml: this package's conftest alone.
        "package-scoped": ([trivial_test], 0, True),
        # Root conftest plus the agent-session-tools conftest, which redirects
        # per test but sets nothing at import time: the root conftest is the
        # only import-time guard here. Collect only and select nothing (exit 5),
        # so no test of that package is coupled to this one.
        "workspace, agent-session-tools only": (
            [
                *workspace_config,
                "--collect-only",
                "-m",
                "suite_isolation_probe_selects_nothing",
                str(_WORKSPACE_ROOT / "packages" / "agent-session-tools" / "tests"),
            ],
            5,
            False,
        ),
    }

    for label, (pytest_args, expected_exit, probe_vault) in invocations.items():
        report = tmp_path / f"probe-report-{label}.json"
        env = {
            **os.environ,
            "STUDYLOOP_DB": str(decoy_db),
            "STUDYLOOP_STATE_DIR": str(decoy_state),
            "STUDYLOOP_CONFIG": str(decoy_config),
            "STUDYLOOP_SECOND_BRAIN_VAULT": str(decoy_vault),
            "SUITE_ISOLATION_PROBE_VAULT": "1" if probe_vault else "0",
            "SUITE_ISOLATION_PROBE_REPORT": str(report),
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
                "suite_isolation_probe",
                *pytest_args,
            ],
            cwd=_WORKSPACE_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
        output = (result.stdout + result.stderr)[-4000:]
        assert result.returncode == expected_exit, (
            f"[{label}] child pytest exited {result.returncode}, "
            f"expected {expected_exit}:\n{output}"
        )
        assert report.is_file(), f"[{label}] the probe plugin never ran:\n{output}"

        resolved = json.loads(report.read_text(encoding="utf-8"))
        leaked = {
            name: path for name, path in resolved.items() if Path(path).is_relative_to(ambient)
        }
        assert _tree_bytes(ambient) == before, (
            f"[{label}] the decoy learner files were modified by the test run; the suite "
            f"resolved these to the caller's ambient paths instead of its sandbox: {leaked}"
        )
        assert not decoy_db.read_bytes().startswith(_SQLITE_HEADER), (
            f"[{label}] the decoy sessions.db was opened and written as a database"
        )
        assert leaked == {}, (
            f"[{label}] the suite resolved the caller's ambient paths instead of its "
            f"sandbox: {leaked}"
        )


# ---------------------------------------------------------------------------
# A path-scoped run must deselect the same opt-in tiers as a workspace run.
# ---------------------------------------------------------------------------

_OPT_IN_TIERS = (
    "integration",
    "e2e",
    "live_kiro",
    "live_provider",
    "live_obsidian",
    "live_xtiles",
    "acceptance",
    "uat",
)


def _addopts_marker_expression(pyproject: Path) -> str | None:
    """The ``-m`` expression in a pyproject's pytest ``addopts``, if any."""
    options = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["pytest"]
    args = shlex.split(options["ini_options"].get("addopts", ""))
    for index, arg in enumerate(args):
        if arg == "-m" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:]
    return None


def test_agent_session_tools_default_run_deselects_integration() -> None:
    """``pytest packages/agent-session-tools/...`` must not run the opt-in tiers.

    pytest takes its configfile from the rootdir it derives from the arguments,
    so a path under that package reads only its own pyproject. Without a ``-m``
    filter there, a focused run of test_query_encoders.py ran the
    integration-marked torch-vs-onnx parity class.
    """
    root = _addopts_marker_expression(_WORKSPACE_ROOT / "pyproject.toml")
    assert root is not None, "the workspace pyproject lost its default -m filter"

    packages = _WORKSPACE_ROOT / "packages"
    for package in ("agent-session-tools", "studyloop"):
        expression = _addopts_marker_expression(packages / package / "pyproject.toml")
        assert expression is not None, f"packages/{package}/pyproject.toml has no -m filter"
        missing = [tier for tier in _OPT_IN_TIERS if f"not {tier}" not in expression]
        assert missing == [], f"packages/{package} default run selects: {missing}"
        assert expression == root, (
            f"packages/{package}/pyproject.toml deselects {expression!r}, "
            f"the workspace root deselects {root!r}"
        )
