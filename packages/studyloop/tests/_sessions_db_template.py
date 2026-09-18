"""One migrated ``sessions.db`` template per process, copied per test.

``studyloop.history._connection._connect`` creates the sessions database from
``SCHEMA_FILE`` and runs every migration the first time any caller opens a
path that does not exist yet. A test module that points ``STUDYLOOP_DB`` at a
fresh ``tmp_path / "sessions.db"`` therefore pays that bootstrap on its first
write — ~60 ms and a 1 MB, 75-table file per test on a laptop, and on a slow
runner disk the first step to stall (CI run 35350636500 timed out two seam
tests inside ``plan new`` creating the database). Seeding the path from a
template turns the bootstrap into one buffered file copy.

This is deliberately *not* a shared live database. ``test_plan_application.py``
(council review 1, F6) needs "no history" to be a fact about the test rather
than about what a shared file holds, so every test still gets its own file at
its own path; only the schema bootstrap is shared.

The template is built through the production ``_connect`` — not a copy of its
steps — so a seeded database is what a genuine first connect would have
produced (``test_sessions_db_template.py`` pins the schema and
``user_version`` against a fresh bootstrap). ``connect_db`` sets
``journal_mode=WAL`` on it; the connection is closed before the first copy so
SQLite has checkpointed and removed the ``-wal``/``-shm`` sidecars, and the
main file is the whole database.

Kept out of ``conftest.py`` for the same reason ``_readiness.py`` and
``_vault_isolation.py`` are: the helper is the subject of a guard test, and a
test cannot import symbols from a conftest in a way a type checker resolves.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

import pytest

_TEMPLATE: Path | None = None


def _build(destination: Path) -> Path:
    """Bootstrap ``destination`` exactly as the first production connect would."""
    from studyloop.history import _connection

    with pytest.MonkeyPatch.context() as env:
        env.setenv("STUDYLOOP_DB", str(destination))
        # An absent config file falls through to defaults, so the config's own
        # ``session_db`` key — which outranks STUDYLOOP_DB by design — cannot
        # route the bootstrap at a test's or the learner's database.
        env.setenv("STUDYLOOP_CONFIG", str(destination.parent / "no-config.yaml"))
        conn = _connection._connect()
    if conn is None:  # pragma: no cover - agent-session-tools is a hard dependency here
        raise RuntimeError("could not bootstrap the sessions.db template")
    conn.close()
    return destination


def template_path() -> Path:
    """The process-wide migrated template; built on first use."""
    global _TEMPLATE
    if _TEMPLATE is None:
        root = Path(tempfile.mkdtemp(prefix="studyloop-test-sessions-template-"))
        atexit.register(shutil.rmtree, root, ignore_errors=True)
        _TEMPLATE = _build(root / "sessions.db")
    return _TEMPLATE


def seed_sessions_db(destination: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy the template to ``destination`` and point ``STUDYLOOP_DB`` at it.

    The one-line replacement for ``monkeypatch.setenv("STUDYLOOP_DB",
    str(tmp_path / "sessions.db"))``: same path, same isolation, no bootstrap
    on the test's first write.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path(), destination)
    monkeypatch.setenv("STUDYLOOP_DB", str(destination))
    return destination
