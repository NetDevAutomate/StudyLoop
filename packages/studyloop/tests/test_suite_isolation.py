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

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _TESTS_DIR.parents[2]

if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from _conftest_access import (  # noqa: E402
    loaded_package_conftest,
    modules_loaded_from_package_conftest,
)

#: The run-level pass floor the package conftest enforces at session finish
#: (``MIN_PASSED_ENV`` there). Every child pytest below runs one test or none,
#: so a floor inherited from the outer run makes it a HOLLOW RUN by
#: construction: an exported ``STUDYLOOP_MIN_PASSED=450`` turned each of these
#: tests red for a reason that has nothing to do with isolation. The children
#: drop it; the outer run still enforces it.
_RUN_FLOOR_ENV = "STUDYLOOP_MIN_PASSED"


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
# separate module with its own state: when ``_TMUX_TMPDIR_ROOT`` was still a
# fresh ``mkdtemp`` per execution, the tmux guard, copied verbatim, failed for
# that reason alone the first time it was collected (the root is now read back
# from the environment, so both copies agree; the hooks and ``_SESSION_SCALE``
# still do not). The lookup lives in ``_conftest_access.py`` so the tests of the
# conftest's own hooks (test_readiness_scaling.py) reach the same module; the
# two tests below prove no test module re-imports the file by name and that the
# run holds one copy of it.
# ---------------------------------------------------------------------------


def _test_modules() -> list[Path]:
    """Every test module and test helper under this package's tests directory."""
    return sorted(
        path
        for pattern in ("test_*.py", "_*.py")
        for path in _TESTS_DIR.rglob(pattern)
        if path.is_file() and ".venv" not in path.parts and "__pycache__" not in path.parts
    )


def test_no_test_module_imports_the_conftest_by_name() -> None:
    """``import conftest`` / ``from conftest import`` executes the conftest again.

    Under ``--import-mode=importlib`` the plugin pytest registered is
    ``packages.studyloop.tests.conftest``; a bare-name import is a second,
    separate execution of the same file (a second ``_SESSION_SCALE``, hooks
    nothing calls). ``_conftest_access.loaded_package_conftest`` is the way to
    reach the real one.
    """
    offenders: list[str] = []
    for path in _test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "conftest" for a in node.names):
                offenders.append(f"{path.relative_to(_TESTS_DIR)}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module == "conftest" and node.level == 0:
                offenders.append(f"{path.relative_to(_TESTS_DIR)}:{node.lineno}")
    assert not offenders, (
        "these sites import the package conftest by name, which executes it a second time "
        "under --import-mode=importlib; use _conftest_access.loaded_package_conftest(config): "
        + ", ".join(offenders)
    )


def test_the_package_conftest_is_loaded_exactly_once(pytestconfig: pytest.Config) -> None:
    """One module object executed from ``conftest.py``: the plugin pytest registered.

    Under the package rootdir (``pytest packages/studyloop``, prepend mode) that
    module is ``sys.modules["conftest"]`` and a bare import would return it; under
    the workspace rootdir (``just test``, importlib mode) it is
    ``packages.studyloop.tests.conftest`` and a bare import adds a second copy
    named ``conftest``. This file sorts after ``test_readiness_scaling.py``, the
    last module that used to import by name, so a regression there shows up here
    in the same run.
    """
    loaded = modules_loaded_from_package_conftest()
    assert len(loaded) == 1, f"the package conftest was executed more than once: {loaded}"
    assert sys.modules[loaded[0]] is loaded_package_conftest(pytestconfig)


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

    conftest = loaded_package_conftest(pytestconfig)
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
    directory the conftests claimed at import time, and TMUX must be unset.

    Assertion-only: never itself starts a tmux session, so it cannot trip
    the private-socket guard in pytest_sessionfinish.
    """
    conftest = loaded_package_conftest(pytestconfig)
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
        env.pop(_RUN_FLOOR_ENV, None)
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
# The isolation must not depend on how pytest is invoked.
# ---------------------------------------------------------------------------
#
# pytest loads a conftest as an INITIAL plugin only when a path argument is its
# directory or a file under it (``testpaths`` makes both package conftests
# initial). Hand it a directory ABOVE the tests -- ``pytest packages`` -- and
# the package conftest is imported lazily during collection, after
# ``pytest_sessionstart`` has already fired, so anything that conftest did in a
# session hook simply never happens. On 2026-10-24 two full gates ran that way:
# the suite addressed the developer's real tmux server for 25 minutes and the
# end-of-run guards reported every pre-existing file under ~/.config/studyloop
# and the vault as a violation, because their "before" snapshot was empty.
# The guard test caught the first; nothing caught the second until the banner
# was read. The wiring now runs at conftest import time, which has no such
# dependency, and the two tests below hold that in a child process.

# A ``-p`` plugin the child pytest loads. At ``pytest_sessionstart`` -- the
# moment the package conftest's own session hook used to run -- it records
# whether that conftest is loaded yet and what the tmux variables hold. Once
# collection has finished it records the conftest again and, when asked, writes
# into the watched surfaces of the child's HOME so the end-of-run guards have
# something real to find. It refuses to write unless HOME is the decoy.
_LAZY_PROBE_PLUGIN = '''
"""Observe the moment pytest_sessionstart fires; optionally plant writes later."""

import json
import os
import sys
from pathlib import Path

PACKAGE_CONFTEST = Path(os.environ["SUITE_ISOLATION_PACKAGE_CONFTEST"]).resolve()
REPORT = Path(os.environ["SUITE_ISOLATION_LAZY_REPORT"])
DECOY_HOME = Path(os.environ["SUITE_ISOLATION_DECOY_HOME"]).resolve()


def _package_conftest_is_loaded() -> bool:
    for module in list(sys.modules.values()):
        location = getattr(module, "__file__", None)
        if location and Path(str(location)).resolve() == PACKAGE_CONFTEST:
            return True
    return False


def pytest_sessionstart(session):
    REPORT.write_text(
        json.dumps(
            {
                "package_conftest_loaded_at_sessionstart": _package_conftest_is_loaded(),
                "TMUX_TMPDIR_at_sessionstart": os.environ.get("TMUX_TMPDIR"),
                "TMUX_at_sessionstart": os.environ.get("TMUX"),
            }
        )
    )


def pytest_collection_finish(session):
    report = json.loads(REPORT.read_text())
    report["package_conftest_loaded_at_collection_finish"] = _package_conftest_is_loaded()
    REPORT.write_text(json.dumps(report))
    if os.environ.get("SUITE_ISOLATION_PLANT_WRITES") != "1":
        return
    home = Path.home().resolve()
    if home != DECOY_HOME:
        raise RuntimeError(f"probe refuses to write: HOME is {home}, not the decoy {DECOY_HOME}")
    runtime = home / ".config" / "studyloop" / "sessions" / "suite-isolation-probe"
    runtime.mkdir(parents=True)
    (runtime / "session-state.json").write_text("{}\\n")
    (home / "Obsidian" / "Personal" / "Study" / "suite-isolation-probe.md").write_text("probe\\n")
'''

_TMUX_GUARD = "test_tmux_socket_is_isolated_from_the_real_tmux_server"

# The path argument that loads the package conftest lazily. pytest makes a
# conftest initial for each path argument's own directory AND for that
# directory's immediate ``test*`` subdirectories (``_try_load_conftest``), which
# is why ``pytest packages/studyloop`` and a ``pytest .`` from inside the package
# are NOT lazy forms: ``tests/`` is a direct child there. ``packages/`` has no
# ``test*`` child, so ``pytest packages`` reaches
# ``packages/studyloop/tests/conftest.py`` only during collection. ``pytest .``
# from the workspace root is lazy by the same route but is not exercised here:
# it walks the whole working tree, gitignored directories included, so its cost
# and outcome would depend on what happens to sit in a given checkout. The probe
# asserts the premise on every run, so a change in pytest's rule shows up as a
# failed premise rather than a vacuous pass.
_LAZY_PATH_ARG = "packages"


def _decoy_home(root: Path) -> Path:
    """A HOME whose watched surfaces already hold files, as a developer's does.

    An empty surface cannot tell a baseline that was taken from one that was
    not: both compare equal to an empty "after". Pre-existing files can.
    """
    home = root / "home"
    config = home / ".config" / "studyloop"
    session = config / "sessions" / "acp-decoy-1234"
    session.mkdir(parents=True)
    (config / "config.yaml").write_text("# decoy learner config\n", encoding="utf-8")
    (session / "session-state.json").write_text("{}\n", encoding="utf-8")
    study = home / "Obsidian" / "Personal" / "Study"
    study.mkdir(parents=True)
    (study / "2026-01-01 - a note the learner wrote.md").write_text("notes\n", encoding="utf-8")
    return home


def _run_pytest_from_above_the_tests_dir(
    tmp_path: Path, *, plant_writes: bool
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    """Run the tmux guard in a child pytest whose path argument is ``packages``.

    ``python_files`` is narrowed to this module so the child imports one test
    module instead of four hundred; conftest loading does not depend on it, so
    the package conftest is still reached lazily, during collection. ``TMUX`` is
    exported as a shell inside a real tmux session would export it, and
    ``TMUX_TMPDIR`` is dropped as a developer's shell would leave it.
    """
    home = _decoy_home(tmp_path)
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    (probe_dir / "suite_isolation_lazy_probe.py").write_text(_LAZY_PROBE_PLUGIN, encoding="utf-8")
    report = tmp_path / "lazy-probe-report.json"

    env = {
        **os.environ,
        "HOME": str(home),
        # The shape a shell inside tmux exports: ``<socket path>,<pid>,<index>``.
        # The socket path is deliberately one that cannot exist: tmux resolves
        # its server from this variable when it is set, and under a RED run
        # nothing has dropped it when session-finish runs ``tmux kill-server``.
        "TMUX": f"{tmp_path / 'not-a-socket'},4242,0",
        "SUITE_ISOLATION_PACKAGE_CONFTEST": str(_TESTS_DIR / "conftest.py"),
        "SUITE_ISOLATION_LAZY_REPORT": str(report),
        "SUITE_ISOLATION_DECOY_HOME": str(home),
        "SUITE_ISOLATION_PLANT_WRITES": "1" if plant_writes else "0",
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(probe_dir), os.environ.get("PYTHONPATH", "")) if p
        ),
    }
    env.pop("TMUX_TMPDIR", None)
    env.pop(_RUN_FLOOR_ENV, None)

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
            "suite_isolation_lazy_probe",
            "-c",
            str(_WORKSPACE_ROOT / "pyproject.toml"),
            "--rootdir",
            str(_WORKSPACE_ROOT),
            "-o",
            f"python_files={Path(__file__).name}",
            _LAZY_PATH_ARG,
            "-k",
            _TMUX_GUARD,
        ],
        cwd=_WORKSPACE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=150,
        check=False,
    )
    output = (result.stdout + result.stderr)[-6000:]
    assert report.is_file(), f"the probe plugin never ran:\n{output}"
    return result, json.loads(report.read_text(encoding="utf-8"))


@pytest.mark.timeout(180)
def test_a_directory_above_the_tests_still_isolates_tmux_and_baselines_the_guards(
    tmp_path: Path,
) -> None:
    """``pytest packages`` must leave the suite exactly as isolated as ``just test``.

    Premise, asserted so the test cannot pass vacuously: at sessionstart the
    package conftest is NOT loaded yet (this is the lazy form), and it IS loaded
    by the end of collection (so the guard that runs is the real one). Then:
    ``TMUX_TMPDIR`` is already private before any hook has fired, ``TMUX`` is
    gone, the tmux guard passes, and neither end-of-run guard reports the
    decoy's pre-existing files -- their baseline was taken when the conftest
    loaded, not in a session hook that never ran.
    """
    result, report = _run_pytest_from_above_the_tests_dir(tmp_path, plant_writes=False)
    output = (result.stdout + result.stderr)[-6000:]

    assert report["package_conftest_loaded_at_sessionstart"] is False, (
        f"`pytest {_LAZY_PATH_ARG}` now loads the package conftest before sessionstart; the "
        "test's premise (a lazily loaded conftest) no longer holds and needs a new reproduction"
    )
    assert report["package_conftest_loaded_at_collection_finish"] is True, (
        "the package conftest was never loaded, so the guard below is not the one under test"
    )
    assert report["TMUX_TMPDIR_at_sessionstart"] is not None, (
        "TMUX_TMPDIR was still unset when pytest_sessionstart fired: the root conftest did "
        "not claim the tmux socket directory at import time"
    )
    assert report["TMUX_at_sessionstart"] is None, (
        "TMUX survived to pytest_sessionstart: the root conftest did not drop it at import time"
    )
    assert result.returncode == 0, f"child pytest exited {result.returncode}:\n{output}"
    assert "1 passed" in output, output
    for banner in ("R-49d", "R-84"):
        assert banner not in output, (
            f"the {banner} guard reported the decoy's PRE-EXISTING files as a violation: its "
            f"baseline snapshot was never taken under this invocation\n{output}"
        )


@pytest.mark.timeout(180)
def test_the_end_of_run_guards_still_watch_under_a_directory_argument(tmp_path: Path) -> None:
    """Control for the test above: the quiet run is quiet because nothing changed.

    The same child, with one file planted under each watched surface after
    collection, must fail with both banners naming the planted files while the
    tmux guard itself still passes.
    """
    result, report = _run_pytest_from_above_the_tests_dir(tmp_path, plant_writes=True)
    output = (result.stdout + result.stderr)[-6000:]

    assert report["package_conftest_loaded_at_collection_finish"] is True
    assert "1 passed" in output, output
    assert result.returncode == 1, f"child pytest exited {result.returncode}:\n{output}"
    assert "R-49d" in output and "sessions/suite-isolation-probe" in output, output
    assert "R-84" in output and "suite-isolation-probe.md" in output, output


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
