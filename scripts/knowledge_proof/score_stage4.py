"""Stage 4 re-score: keep-half (B1 = this checkout) vs scoped main (B0 = pinned src), same DB.

The committed harness (``score.py``) builds the shipped-path arm by importing
``mcp_server._session_search_queries`` -- a helper that only exists once PR #18's
``4fe2e4cd`` has landed. Today's ``main`` (the B0 pin for this look) predates it and
issues a single ``escape_fts_query`` AND query. This wrapper swaps in an arm builder
that mirrors *whichever* shape the imported package has, so both arms are scored by
exactly the code they ship, on one read-only snapshot, under the same scope rules.
Everything else -- gold, bootstrap, receipt shape, hash chaining -- is the harness's.

Usage (from the checkout under test, so ``agent_session_tools`` resolves to B1)::

    uv run python <worktree>/scripts/knowledge_proof/score_stage4.py \\
        --gold <gold-v2-dev.json> --b0-src <pinned main>/packages/agent-session-tools/src \\
        --out <receipt.json> --label stage4
"""

from __future__ import annotations

import importlib
import pathlib
import sys
from typing import TYPE_CHECKING

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import score  # the committed harness

if TYPE_CHECKING:
    import sqlite3


def _shipped_fts_arm_any_shape(pkg_src: pathlib.Path | None) -> score.Arm:
    """Shipped session_search ranking as a session-id arm, for either query shape."""
    # Purge on EVERY build: the harness only purged when a pin was given, so the arm
    # built second silently reused the first arm's modules and both arms scored one code.
    for mod in list(sys.modules):
        if mod.startswith("agent_session_tools"):
            del sys.modules[mod]
    if pkg_src is not None:
        sys.path.insert(0, str(pkg_src))
    mcp_server = importlib.import_module("agent_session_tools.mcp_server")
    public = importlib.import_module("agent_session_tools.context.public")
    visibility_sql = public.visibility_sql
    if hasattr(mcp_server, "_session_search_queries"):
        queries = mcp_server._session_search_queries
        shape = "planner"
    else:
        escape = importlib.import_module("agent_session_tools.query_utils").escape_fts_query

        def queries(question: str) -> tuple[str, ...]:
            return (escape(question),)

        shape = "pre-planner"
    if pkg_src is not None:
        sys.path.pop(0)
    print(
        f"  shipped arm from {pkg_src or 'this checkout'}: {shape} query shape "
        f"({pathlib.Path(mcp_server.__file__).parents[1]})",
        file=sys.stderr,
    )

    def arm(conn: sqlite3.Connection, question: str) -> list[str]:
        for fts_query in queries(question):
            visible, scope_params = visibility_sql(conn, "s.id")
            rows = conn.execute(
                "SELECT s.id FROM messages m JOIN sessions s ON m.session_id = s.id "
                "JOIN messages_fts ON messages_fts.rowid = m.rowid "
                f"WHERE messages_fts MATCH ? AND {visible} "
                "ORDER BY bm25(messages_fts), m.timestamp DESC LIMIT 200",
                [fts_query, *scope_params],
            ).fetchall()
            if rows:
                seen: list[str] = []
                for (sid,) in rows:
                    if sid not in seen:
                        seen.append(sid)
                    if len(seen) == score.K:
                        break
                return seen
        return []

    return arm


score._shipped_fts_arm = _shipped_fts_arm_any_shape

if __name__ == "__main__":
    raise SystemExit(score.main())
