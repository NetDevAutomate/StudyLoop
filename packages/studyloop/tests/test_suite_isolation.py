"""Guards for the suite's own isolation wiring.

The fixtures and import-time environment that keep tests away from the
learner's real state live in the conftest files. The checks that prove that
wiring still holds live here, because pytest collects only ``test_*.py``
modules: a ``def test_*`` inside a ``conftest.py`` is loaded as plugin code and
never runs.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
