"""The session ``source`` labels this product still admits, and what it hides.

Ruling (Andy, 2026-09-10), recorded in
``docs/architecture/session-memory/receipts/adapter-scope-2026-09-10.md``
(§4.4-4.5 and §5 "Stage 4"): the supported adapters are exactly kiro-cli,
Claude Code, Codex, OpenCode, pi and Grok Build. The live database holds 5,879
sessions, of which 1,279 carry seven retired labels — ``repoprompt``,
``aider``, ``kilocode_cli``, ``litellm-proxy``, ``gemini_cli``,
``bedrock_proxy``, ``omp``. Those rows are **hidden at product read paths and
never deleted**: the database is the only surviving copy of most of that
history, so a hard deletion needs an explicit per-run instruction and a backup
first. ``retired_source_counts`` exists so a stats surface can say what is
hidden rather than let the rows vanish silently.

The admitted set is *derived* from the exporters' own ``source_name`` values,
so a harness cannot be added to the registry and forgotten here, plus
``study_mentor``: a first-party checkpoint label written live by
``tutor_checkpoint`` (receipt §4.4), which no exporter declares because it is
not a harness.

Import direction (do not reverse): ``context.scope`` imports this module
*inside* its predicate function. ``agent_session_tools.exporters`` reaches
``context.capture`` -> ``context.scope`` at import time, so a module-level
``from ..sources import ...`` in ``context.scope`` would close that cycle.
"""

from __future__ import annotations

import re
import sqlite3

from .exporters import EXPORTERS

# Written directly by ``tutor_checkpoint`` (``tutor_checkpoint.py:42``) as a
# first-party checkpoint source, not by an exporter and not by a harness.
FIRST_PARTY_SOURCES: frozenset[str] = frozenset({"study_mentor"})

#: Every ``sessions.source`` value a product read path will return.
SUPPORTED_SOURCES: frozenset[str] = (
    frozenset(exporter.source_name for exporter in EXPORTERS.values())
    | FIRST_PARTY_SOURCES
)


def supported_sources() -> frozenset[str]:
    """Return the admitted ``sessions.source`` labels."""
    return SUPPORTED_SOURCES


def is_supported(source: str | None) -> bool:
    """True when a caller-supplied source filter names an admitted label.

    A caller that names a retired label is asking for it deliberately, which is
    the one way hidden history is still reachable.
    """
    return source in SUPPORTED_SOURCES


def retired_source_counts(
    conn: sqlite3.Connection, *, schema: str = "main"
) -> dict[str, int]:
    """Count stored sessions per retired ``source`` label, largest first.

    Reports exactly what the read predicate withholds. This is a count over
    rows that are still present: nothing here has been deleted, and the numbers
    are the evidence of that. The schema name is an internal SQL identifier,
    never user-supplied query text.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*", schema):
        raise ValueError("Invalid internal schema identifier")
    admitted = sorted(SUPPORTED_SOURCES)
    placeholders = ",".join("?" for _ in admitted)
    rows = conn.execute(
        f"SELECT source, COUNT(*) AS cnt FROM {schema}.sessions "
        f"WHERE source NOT IN ({placeholders}) "
        "GROUP BY source ORDER BY cnt DESC, source",
        admitted,
    ).fetchall()
    return {row[0]: row[1] for row in rows}
