"""The three arms of stage 1: the real MCP tool, the CLI, and a frozen replica.

* :class:`McpArm` calls the shipped ``session_search`` tool **through FastMCP**
  (``mcp.call_tool``) -- the agent's own interface, and the arm acceptance is
  gated on. It is the only arm whose failures are the failures a user meets.
* :class:`CliArm` runs ``session-query search`` as a subprocess: the second
  real interface, and a check that the two agree.
* :class:`FrozenShippedArm` is a *frozen* copy of today's query planning and
  today's ``session_search`` SQL. Today it must return exactly what
  :class:`McpArm` returns -- that equality is what proves the copy faithful.
  Later stages change the shipped path and pair against this frozen control,
  so it deliberately duplicates the planner instead of importing it: an
  import would move with the fix and stop being a control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .seam import ArmError, classify_failure, collapse_to_sessions

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterator, Sequence

    from .seam import Hit, Query

#: Message-row limit the shipped tool applies *before* sessions are collapsed.
DEFAULT_ROWS = 10


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _git_head() -> str:
    """``git rev-parse HEAD`` of the checkout this arm's code came from."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(_repo_root()), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


@contextmanager
def _quiet_errors() -> Iterator[None]:
    """Silence FastMCP's error logging for the duration of one tool call.

    A crashing query is *expected* data for the crash census (42 of 91 gold
    questions raise today); letting FastMCP log a rich traceback panel per
    call would bury the run's own output in noise.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.ERROR)
    try:
        yield
    finally:
        logging.disable(previous)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine whether or not this thread already drives a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _message_id(row: dict[str, Any], index: int) -> str:
    """A stable id for one returned message row.

    The shipped ``session_search`` projection carries no message id (checked:
    it returns ``session_id, source, project_path, updated_at, role,
    timestamp, preview``), so a positional id keyed to the session is
    synthesised. If the projection ever gains a real id this picks it up.
    """
    for key in ("message_id", "msg_id", "id"):
        value = row.get(key)
        if value:
            return str(value)
    return f"{row.get('session_id', '?')}#{index}:{row.get('timestamp', '')}"


class McpArm:
    """The shipped ``session_search`` tool, driven through FastMCP ``call_tool``."""

    name = "mcp"
    supports_exclusion = False

    def __init__(self, db_path: Path | str, rows: int = DEFAULT_ROWS) -> None:
        self.db_path = Path(db_path).expanduser()
        self.rows = rows

    def _rows(self, query: Query) -> list[dict[str, Any]]:
        from unittest.mock import patch

        from agent_session_tools import mcp_server

        arguments: dict[str, Any] = {"query": query.text, "limit": self.rows}
        if query.source is not None:
            arguments["source"] = query.source
        if query.project is not None:
            arguments["project"] = query.project
        with (
            patch(
                "agent_session_tools.mcp_server._get_db_path",
                return_value=self.db_path,
            ),
            _quiet_errors(),
        ):
            result = _run(mcp_server.mcp.call_tool("session_search", arguments))
        structured = getattr(result, "structured_content", None)
        if not isinstance(structured, dict):
            return []
        payload = structured.get("result", [])
        return [row for row in payload if isinstance(row, dict)]

    def search(self, query: Query, k: int) -> list[Hit]:
        try:
            rows = self._rows(query)
        except Exception as exc:
            raise ArmError(classify_failure(exc), str(exc)) from exc
        pairs = [
            (str(row["session_id"]), _message_id(row, i)) for i, row in enumerate(rows)
        ]
        return collapse_to_sessions(pairs, k, method="mcp")

    def describe(self) -> dict[str, Any]:
        return {
            "arm": self.name,
            "interface": "fastmcp call_tool(session_search)",
            "rows": self.rows,
            "db_path": str(self.db_path),
            "git_commit": _git_head(),
        }


class CliArm:
    """``session-query search`` as a subprocess -- the other real interface."""

    name = "cli"
    supports_exclusion = False

    def __init__(self, db_path: Path | str, rows: int = DEFAULT_ROWS) -> None:
        self.db_path = Path(db_path).expanduser()
        self.rows = rows
        self.argv_prefix, self.invocation = self._resolve()

    @staticmethod
    def _resolve() -> tuple[list[str], str]:
        """Prefer the installed console script; fall back to ``uv run``."""
        found = shutil.which("session-query")
        if found:
            return [found], "session-query"
        module = [sys.executable, "-m", "agent_session_tools.query_sessions"]
        if shutil.which("uv"):
            return ["uv", "run", "session-query"], "uv run session-query"
        return module, "python -m agent_session_tools.query_sessions"

    @property
    def available(self) -> bool:
        return bool(shutil.which(self.argv_prefix[0]))

    def search(self, query: Query, k: int) -> list[Hit]:
        argv = [
            *self.argv_prefix,
            "search",
            query.text,
            "--db",
            str(self.db_path),
            "--output-format",
            "json",
            "-n",
            str(self.rows),
        ]
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv built here, no shell
                argv,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                cwd=str(_repo_root()),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ArmError(classify_failure(exc), str(exc)) from exc
        if done.returncode != 0 or "Traceback (most recent call last)" in done.stderr:
            detail = (done.stderr or done.stdout).strip()
            raise ArmError(classify_failure(RuntimeError(detail)), detail)
        text = done.stdout.strip()
        if not text:
            return []
        try:
            payload = json.loads(
                text[text.index("[") :] if text.startswith("[") else text
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise ArmError("other", f"unparsable CLI output: {exc}") from exc
        rows = (
            [row for row in payload if isinstance(row, dict)]
            if isinstance(payload, list)
            else []
        )
        pairs = [
            (str(row["session_id"]), _message_id(row, i)) for i, row in enumerate(rows)
        ]
        return collapse_to_sessions(pairs, k, method="cli")

    def describe(self) -> dict[str, Any]:
        return {
            "arm": self.name,
            "interface": f"{self.invocation} search --output-format json",
            "rows": self.rows,
            "db_path": str(self.db_path),
            "git_commit": _git_head(),
        }


# --------------------------------------------------------------------------- frozen replica
# Verbatim copies of today's query planning (query_planner.STOP / plan,
# query_utils.escape_fts_query, mcp_server._session_search_queries) and today's
# session_search SQL. Frozen on purpose: a later stage fixes the shipped path,
# and a control that imported the fix would move with it.

_FROZEN_STOP = frozenset(
    "a an the is are was were be been being do does did to of in on for with"
    " and or not what which who why how when where whose that this these those"
    " it its during every any can cant can't could should would will shall"
    " about into from as at by we our your my i you they them he she his her".split()
)
_FROZEN_TERM = re.compile(r"[a-zA-Z0-9_./-]+")


def _frozen_escape_fts_query(query: str) -> str:
    query = query.strip().strip('"').strip("'")
    if any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
        return query
    escaped = query.replace('"', '""')
    if " " in escaped:
        return f'"{escaped}"'
    return escaped


def _frozen_plan(question: str) -> tuple[str, str]:
    terms = tuple(
        token
        for token in _FROZEN_TERM.findall(question.lower())
        if token not in _FROZEN_STOP and len(token) > 2
    )
    quoted = tuple(f'"{term}"' for term in terms)
    return " AND ".join(quoted), " OR ".join(quoted)


def frozen_session_search_queries(query: str) -> tuple[str, ...]:
    """Frozen copy of ``mcp_server._session_search_queries`` as it ships today."""
    upper = query.upper()
    explicit = any(operator in upper for operator in (" AND ", " OR ", " NOT "))
    stripped = query.strip()
    explicitly_quoted = '"' in query or (
        len(stripped) >= 2 and stripped.startswith("'") and stripped.endswith("'")
    )
    if explicit or explicitly_quoted:
        return (_frozen_escape_fts_query(query),)
    and_query, or_query = _frozen_plan(query)
    if not and_query:
        return ()
    if and_query == or_query:
        return (and_query,)
    return and_query, or_query


class FrozenShippedArm:
    """Today's shipped lexical path, pinned in this file as the stage-1 control."""

    name = "frozen"
    supports_exclusion = False

    def __init__(self, db_path: Path | str, rows: int = DEFAULT_ROWS) -> None:
        self.db_path = Path(db_path).expanduser()
        self.rows = rows

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        return conn

    def _rows(self, query: Query) -> Sequence[sqlite3.Row]:
        from agent_session_tools.context.scope import visibility_sql
        from agent_session_tools.query_utils import build_project_filter
        from agent_session_tools.sources import is_supported

        conn = self._connect()
        try:
            for fts_query in frozen_session_search_queries(query.text):
                sql = """
                    SELECT s.id as session_id, s.source, s.project_path,
                           s.updated_at, m.role, m.timestamp,
                           substr(m.content, 1, 300) as preview
                    FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    JOIN messages_fts ON messages_fts.rowid = m.rowid
                    WHERE messages_fts MATCH ?
                """
                visible, scope_params = visibility_sql(
                    conn,
                    "s.id",
                    include_retired_sources=bool(query.source)
                    and not is_supported(query.source),
                )
                sql += " AND " + visible
                params: list[Any] = [fts_query, *scope_params]
                if query.source:
                    sql += " AND s.source = ?"
                    params.append(query.source)
                if query.project:
                    project_clause, project_params = build_project_filter(query.project)
                    sql += " AND " + project_clause
                    params.extend(project_params)
                sql += " ORDER BY bm25(messages_fts), m.timestamp DESC LIMIT ?"
                params.append(self.rows)
                rows = conn.execute(sql, params).fetchall()
                if rows:
                    return rows
            return []
        finally:
            with suppress(sqlite3.Error):
                conn.close()

    def search(self, query: Query, k: int) -> list[Hit]:
        try:
            rows = self._rows(query)
        except Exception as exc:
            raise ArmError(classify_failure(exc), str(exc)) from exc
        pairs = [
            (str(row["session_id"]), _message_id(dict(row), i))
            for i, row in enumerate(rows)
        ]
        return collapse_to_sessions(pairs, k, method="frozen")

    def describe(self) -> dict[str, Any]:
        return {
            "arm": self.name,
            "interface": "frozen replica of mcp_server.session_search SQL",
            "rows": self.rows,
            "db_path": str(self.db_path),
            "git_commit": _git_head(),
            "frozen_at": "3826a9b4 (stage 1)",
        }


#: Arm name -> constructor, for ``--arms mcp,cli,frozen``.
ARMS = {
    McpArm.name: McpArm,
    CliArm.name: CliArm,
    FrozenShippedArm.name: FrozenShippedArm,
}


def build_arm(name: str, db_path: Path | str, rows: int = DEFAULT_ROWS) -> Any:
    """Construct one arm by name."""
    try:
        factory = ARMS[name]
    except KeyError:
        raise ValueError(
            f"unknown arm {name!r}; known: {', '.join(sorted(ARMS))}"
        ) from None
    return factory(db_path, rows)


__all__ = [
    "ARMS",
    "DEFAULT_ROWS",
    "CliArm",
    "FrozenShippedArm",
    "McpArm",
    "build_arm",
    "frozen_session_search_queries",
]
