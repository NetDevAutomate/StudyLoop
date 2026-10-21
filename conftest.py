"""Global pytest configuration for the studyloop test suite.

Sets environment variables BEFORE any test modules import studyloop.

The critical setup here: forcing Rich to emit plain text instead of
ANSI escape codes so CLI-output assertions (``"#42" in result.output``)
work under ``click.testing.CliRunner``, which captures stdout into a
StringIO that Rich still treats as terminal-capable.

``NO_COLOR=1`` tells Rich to drop colors. ``TERM=dumb`` is required on
top of that -- Rich keeps emitting bold/underline escape codes until
it sees a non-ANSI terminal type.

These env vars affect only the test process, never user runtime.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# These MUST be set before any `from studyloop...` import, because
# ``studyloop.output`` (and CLI submodules) construct a module-level
# ``Console()`` whose behaviour is fixed at construction time.
#
# Hard-assign, not ``setdefault`` -- the shell typically exports
# ``TERM=xterm-256color`` which Rich treats as ANSI-capable and will
# keep emitting bold/underline escape codes even under ``NO_COLOR``.
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"

# Writable-state isolation for the WHOLE repo (both workspace packages).
# Set here, at import time, and via the environment rather than a fixture:
# ``load_settings()`` and ``get_db_path()`` read these at call time, and a
# test that shells out to the CLI inherits only the environment — a
# monkeypatched function does not cross a process boundary. That gap is how
# the suite previously ran migrations against the learner's real sessions.db
# and wrote a poisoned picker cache into their real state dir. See
# docs/issues/0005-vendor-picker-lists-repo-directories.md.
#
# Hard-assign, not ``setdefault``: the setup guide tells learners to
# ``export STUDYLOOP_CONFIG=...``, and the same variables can name their real
# sessions.db and state dir, so a value exported by the caller must never
# survive into the suite. STUDYLOOP_CONFIG is set here too, not only in the
# studyloop package conftest, because that conftest leaves all three alone once
# this one has claimed them (see the marker below). A test that needs its own
# paths still ``monkeypatch.setenv``s them; that override lasts for the test and
# unwinds back to these values.
#
# Once per process, recorded by pid: under ``--import-mode=importlib`` a test
# module's ``from conftest import ...`` executes the studyloop package conftest a
# second time, and re-pointing the sandbox then would move it out from under
# code that already bound it (``studyloop.settings._CONFIG_PATH``). A child
# process inherits the marker with its parent's pid, so it redirects again.
_SANDBOX_OWNER_ENV = "_STUDYLOOP_SUITE_SANDBOX_PID"
if os.environ.get(_SANDBOX_OWNER_ENV) != str(os.getpid()):
    _TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-state-"))
    os.environ["STUDYLOOP_STATE_DIR"] = str(_TEST_STATE_ROOT / "state")
    os.environ["STUDYLOOP_DB"] = str(_TEST_STATE_ROOT / "sessions.db")
    os.environ["STUDYLOOP_CONFIG"] = str(_TEST_STATE_ROOT / "config.yaml")
    os.environ[_SANDBOX_OWNER_ENV] = str(os.getpid())
