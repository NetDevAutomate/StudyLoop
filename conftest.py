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
_TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-state-"))
os.environ.setdefault("STUDYLOOP_STATE_DIR", str(_TEST_STATE_ROOT / "state"))
os.environ.setdefault("STUDYLOOP_DB", str(_TEST_STATE_ROOT / "sessions.db"))
