"""Reach the package conftest pytest actually loaded, without executing it again.

Under the workspace's ``--import-mode=importlib`` a test module's
``from conftest import ...`` executes ``packages/studyloop/tests/conftest.py`` a
second time as a separate module object: a second mkdtemp'd
``_TMUX_TMPDIR_ROOT``, a second ``_SESSION_SCALE``, hook functions that are not
the ones pytest calls. The pid markers inside that conftest keep the re-run from
re-pointing the sandbox, but a test that patches or calls the copy is testing a
module nothing else runs. :func:`loaded_package_conftest` returns the module
pytest registered as a plugin, so tests of the conftest's hooks exercise the
real ones -- and ``test_suite_isolation.py`` proves the conftest is loaded once.

Not a test module (leading underscore, per ``docs/contributor-conventions.md``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

#: The one conftest this helper resolves; the workspace root has another.
PACKAGE_CONFTEST = Path(__file__).resolve().parent / "conftest.py"


def loaded_package_conftest(config: pytest.Config) -> ModuleType:
    """Return the ``packages/studyloop/tests/conftest.py`` module whose hooks run."""
    for plugin in config.pluginmanager.get_plugins():
        location = getattr(plugin, "__file__", None)
        if (
            isinstance(plugin, ModuleType)
            and location
            and Path(location).resolve() == PACKAGE_CONFTEST
        ):
            return plugin
    raise AssertionError(f"pytest did not load {PACKAGE_CONFTEST} as a plugin")


def modules_loaded_from_package_conftest() -> list[str]:
    """Names under which ``sys.modules`` holds a module executed from the package conftest.

    Exactly one entry is expected: the plugin pytest registered. A second entry
    (``conftest``) means some test module imported the file by name and ran it
    again.
    """
    return [
        name
        for name, module in list(sys.modules.items())
        if isinstance(module, ModuleType)
        and getattr(module, "__file__", None)
        and Path(str(module.__file__)).resolve() == PACKAGE_CONFTEST
    ]
