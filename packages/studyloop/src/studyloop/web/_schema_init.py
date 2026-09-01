"""Prepare every database schema once, at server startup.

Before this existed the database was only ever built lazily, on first request.
Four separate bootstraps each did part of the job the first time something needed
it, which had two consequences.

The first was correctness. ``migrate()`` ran from ordinary GET handlers, and the
SPA fires ``/api/now``, ``/api/backlog``, ``/api/session/last`` and
``/api/history`` in parallel on page load, so several requests could read the same
stale ``PRAGMA user_version`` and apply the same migrations concurrently --
producing ``duplicate column name`` and ``index already exists`` errors on a
first boot. ``migrate()`` itself is serialised now, but the right answer is for
the schema to be ready before anything serves a request at all.

The second is cost, which remains regardless. ``GET /api/due/{course}`` executes
four DDL statements per request. ``GET /api/body-double/focus`` is the worst
single case: one request runs the parking migration and its column probes, the
board seeding, the notes probe, and a ``schema.sql`` apply plus ``migrate()`` from
the history layer.

Deliberately ADDITIVE. The lazy bootstraps stay exactly where they are, because
the web server is not the only entry point -- the CLI, the MCP server and the test
suite all open the database directly and rely on it building itself. Removing
their self-healing is a separate change with a much wider blast radius. What this
guarantees is narrower and still worth having: by the time the server accepts its
first request, every lazy path finds its work already done and becomes a cheap
no-op probe.

Failure here is logged, never fatal. A server that cannot pre-build its schema is
no worse off than it was before this module existed -- it falls back to building
lazily -- so refusing to start would trade a recoverable condition for an outage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def prepare_schema() -> None:
    """Build the base schema, run migrations, and pre-build every feature table.

    Order matters. ``init_db`` applies ``schema.sql`` and the migrations, creating
    ``sessions`` and ``study_sessions``; ``parked_topics`` carries foreign keys to
    both, so the parking bootstrap must not run first. It also puts the database
    in WAL and sets ``busy_timeout`` before anything else connects.
    """
    steps: list[tuple[str, bool]] = []

    try:
        from agent_session_tools.export_sessions import init_db
        from studyloop.settings import get_db_path

        # Returns an open connection; the caller owns closing it.
        init_db(str(get_db_path())).close()
        steps.append(("base schema + migrations", True))
    except Exception:
        logger.warning("startup: base schema init failed; falling back to lazy", exc_info=True)
        steps.append(("base schema + migrations", False))
        # The feature bootstraps below each call init_db themselves when the base
        # tables are missing, so there is still a route to a working database.

    for label, prepare in _feature_steps():
        try:
            prepare()
            steps.append((label, True))
        except Exception:
            logger.warning("startup: %s init failed; falling back to lazy", label, exc_info=True)
            steps.append((label, False))

    failed = [label for label, ok in steps if not ok]
    if failed:
        logger.warning("startup schema prep incomplete: %s", ", ".join(failed))
    else:
        logger.info("startup schema prep complete (%d steps)", len(steps))


def _feature_steps() -> list[tuple[str, Callable[[], None]]]:
    """The per-feature bootstraps, imported lazily to keep app import cheap."""
    from studyloop import notes, parking, review_db

    return [
        ("review tables", review_db.ensure_tables),
        ("notes schema", notes.ensure_schema),
        ("parking schema", parking.ensure_schema),
    ]
