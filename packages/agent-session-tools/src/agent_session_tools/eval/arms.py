"""The three arms of stage 1: the real MCP tool, the CLI, and a frozen replica.

* :class:`McpArm` calls the shipped ``session_search`` tool **through FastMCP**
  (``mcp.call_tool``) -- the agent's own interface, and the arm acceptance is
  gated on. It is the only arm whose failures are the failures a user meets.
* :class:`CliArm` runs ``session-query search`` as a subprocess: the second
  real interface, and a check that the two agree.
* :class:`FrozenShippedArm` is a *frozen* copy of stage 1's query planning and
  stage 1's ``session_search`` SQL. It is the control the fixed path is scored
  against, so it deliberately duplicates the planner instead of importing it:
  an import would move with the fix and stop being a control. Its planner is
  pinned as a fixed table in ``tests/golden/frozen_planner_pins.json``, taken
  from the shipped planner while stage 1 still shipped; the live planner has
  since changed by design, so an equality test against it would now fail for
  the right reason and prove nothing.
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

    The retrieval service projects a real ``message_id`` (a text exporter id /
    UUID) on every row, and that is the citation handle the census excludes
    by, so it is preferred. The positional fallback survives only for a row
    that carries no id at all -- the pre-Stage-2 tool, whose projection was
    ``session_id, source, project_path, updated_at, role, timestamp,
    preview`` and nothing else.
    """
    for key in ("message_id", "msg_id", "id"):
        value = row.get(key)
        if value:
            return str(value)
    return f"{row.get('session_id', '?')}#{index}:{row.get('timestamp', '')}"


def _split_payload(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Split a search payload into ``(rows, retrieval_status)``.

    Three shapes reach this, and an arm has to read all of them so the harness
    can be pointed at either side of the Stage 2 cut:

    * ``{"rows": [...], "retrieval_status": {...}}`` -- the retrieval
      service's shared payload. FastMCP returns a tool's ``dict`` as the
      structured content itself, and the CLI prints the same document.
    * ``{"result": [...]}`` -- what FastMCP wraps a ``list`` return in, i.e.
      the pre-Stage-2 ``session_search`` tool.
    * ``[...]`` -- a bare list, i.e. the pre-Stage-2 CLI's ``--output-format
      json``.

    Anything else yields no rows rather than raising: an unreadable payload is
    an empty result for the ruler, not a crash to classify.
    """

    def _rows(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, dict)]

    if isinstance(payload, list):
        return _rows(payload), None
    if not isinstance(payload, dict):
        return [], None
    if "rows" in payload:
        status = payload.get("retrieval_status")
        return _rows(payload.get("rows")), status if isinstance(status, dict) else None
    return _rows(payload.get("result")), None


def _json_document(text: str) -> str:
    """The JSON document inside CLI stdout, ignoring anything printed before it.

    The payload is an object now and was a bare array before Stage 2, so the
    document starts at whichever of ``{`` or ``[`` appears first.
    """
    starts = [pos for pos in (text.find("{"), text.find("[")) if pos != -1]
    return text[min(starts) :] if starts else text


def _tool_argument_names(tool_name: str) -> frozenset[str]:
    """The argument names the registered MCP tool accepts, from its input schema.

    Read once at arm construction so an arm knows before its first query
    whether the shipped tool can exclude at all -- cheaper and far more
    legible than provoking a pydantic validation error with a throwaway call
    and classifying the wreckage.
    """
    try:
        from agent_session_tools import mcp_server

        tools = _run(mcp_server.mcp.list_tools())
    except Exception:  # pragma: no cover - a broken server is not this arm's business
        return frozenset()
    for tool in tools:
        if getattr(tool, "name", None) != tool_name:
            continue
        schema = getattr(tool, "parameters", None)
        if isinstance(schema, dict):
            properties = schema.get("properties")
            if isinstance(properties, dict):
                return frozenset(str(key) for key in properties)
        return frozenset()
    return frozenset()


class McpArm:
    """The shipped ``session_search`` tool, driven through FastMCP ``call_tool``.

    ``supports_exclusion`` is decided at construction from the tool's own
    input schema: the retrieval service takes ``exclude_message_ids`` and
    filters inside the SQL, which is what makes a self-retrieval census
    through the real agent interface honest. Against the pre-Stage-2 tool the
    argument is absent, the flag is ``False``, and the ruler filters the
    returned hits instead.
    """

    name = "mcp"
    #: The tool argument that lets the census exclude a question's own message.
    EXCLUDE_ARG = "exclude_message_ids"

    def __init__(self, db_path: Path | str, rows: int = DEFAULT_ROWS) -> None:
        self.db_path = Path(db_path).expanduser()
        self.rows = rows
        self.tool_arguments = _tool_argument_names("session_search")
        self.supports_exclusion = self.EXCLUDE_ARG in self.tool_arguments
        #: ``retrieval_status`` from the most recent call, or ``None``.
        self.last_status: dict[str, Any] | None = None

    def _rows(self, query: Query) -> list[dict[str, Any]]:
        from unittest.mock import patch

        from agent_session_tools import mcp_server

        arguments: dict[str, Any] = {"query": query.text, "limit": self.rows}
        if query.source is not None:
            arguments["source"] = query.source
        if query.project is not None:
            arguments["project"] = query.project
        if self.supports_exclusion and query.exclude_message_ids:
            arguments[self.EXCLUDE_ARG] = sorted(query.exclude_message_ids)
        with (
            patch(
                "agent_session_tools.mcp_server._get_db_path",
                return_value=self.db_path,
            ),
            _quiet_errors(),
        ):
            result = _run(mcp_server.mcp.call_tool("session_search", arguments))
        rows, status = _split_payload(getattr(result, "structured_content", None))
        self.last_status = status
        return rows

    def search(self, query: Query, k: int) -> list[Hit]:
        try:
            rows = self._rows(query)
        except Exception as exc:
            raise ArmError(classify_failure(exc), str(exc)) from exc
        # Message ids are excluded in the tool's SQL; session ids have no tool
        # argument, so they are dropped here -- before the collapse, so ``k``
        # still bounds *surviving* sessions. When the tool cannot exclude at
        # all the ruler owns both filters and this arm must not pre-empt it.
        excluded_sessions = (
            query.exclude_session_ids if self.supports_exclusion else frozenset()
        )
        pairs = [
            (str(row["session_id"]), _message_id(row, i))
            for i, row in enumerate(rows)
            if str(row["session_id"]) not in excluded_sessions
        ]
        return collapse_to_sessions(pairs, k, method="mcp")

    def describe(self) -> dict[str, Any]:
        return {
            "arm": self.name,
            "interface": "fastmcp call_tool(session_search)",
            "rows": self.rows,
            "db_path": str(self.db_path),
            "git_commit": _git_head(),
            "supports_exclusion": self.supports_exclusion,
        }


class CliArm:
    """``session-query search`` as a subprocess -- the other real interface."""

    name = "cli"
    #: The CLI has no exclusion flag, so the ruler filters this arm's hits.
    supports_exclusion = False

    def __init__(self, db_path: Path | str, rows: int = DEFAULT_ROWS) -> None:
        self.db_path = Path(db_path).expanduser()
        self.rows = rows
        self.argv_prefix, self.invocation = self._resolve()
        #: ``retrieval_status`` from the most recent call, or ``None``.
        self.last_status: dict[str, Any] | None = None

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
            payload = json.loads(_json_document(text))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ArmError("other", f"unparsable CLI output: {exc}") from exc
        rows, status = _split_payload(payload)
        self.last_status = status
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
# Verbatim copies of stage 1's query planning (query_planner.STOP / plan,
# query_utils.escape_fts_query, mcp_server._session_search_queries) and stage 1's
# session_search SQL. Frozen on purpose: stage 2 fixed the shipped path, and a
# control that imported the fix would have moved with it. Nothing below may
# change; tests/golden/frozen_planner_pins.json is what enforces that.

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
    """Frozen copy of ``mcp_server._session_search_queries`` as stage 1 shipped it.

    Pinned by ``tests/golden/frozen_planner_pins.json``, generated from the
    shipped helper at commit 79425cbe over 96 inputs (the stage-1 arm tests
    plus every gold DEV question).
    """
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
    """Stage 1's shipped lexical path, pinned in this file as the control.

    The SQL is a verbatim copy of what ``session_search`` ran before the
    retrieval service replaced it. ``Query.exclude_*`` adds ``NOT IN`` clauses
    at query time, which is what lets the census score self-retrieval honestly
    through this arm.
    """

    name = "frozen"
    supports_exclusion = True

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
                if query.exclude_message_ids:
                    excluded = sorted(query.exclude_message_ids)
                    sql += " AND m.id NOT IN (" + ",".join("?" * len(excluded)) + ")"
                    params.extend(excluded)
                if query.exclude_session_ids:
                    excluded = sorted(query.exclude_session_ids)
                    sql += " AND s.id NOT IN (" + ",".join("?" * len(excluded)) + ")"
                    params.extend(excluded)
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
