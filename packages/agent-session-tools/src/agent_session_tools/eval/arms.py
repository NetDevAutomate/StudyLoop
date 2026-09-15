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

A second, orthogonal axis (§5 stream, council D-12) is the **planner
variant**: which natural-language planner the retrieval service runs behind
the same tool. ``mcp:and_then_prose_or`` is the real ``session_search`` with
one planner function substituted for the duration of the call, after
``plan_query`` has classified the string, so the explicit door is identical
across variants. Variants are in-process by construction (a substituted
function), so the subprocess CLI arm and the frozen control refuse one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_session_tools import retrieval
from agent_session_tools.query_planner import (
    _quote_term,
    _terms,
    prose_or_query,
    prose_tokens,
)
from agent_session_tools.retrieval import QueryPlan, _phrase_terms

from .seam import ArmError, classify_failure, collapse_to_sessions

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterator, Sequence

    from .seam import Hit, Query

#: Message-row limit the shipped tool applies *before* sessions are collapsed.
DEFAULT_ROWS = 10


# --------------------------------------------------------------------------- planner variants (§5)
# The shipped natural-language planner, captured at import. The variants below
# replace ``retrieval.plan_natural_language`` for the duration of one tool call,
# so the candidate must build on THIS reference, never on the module attribute
# it is temporarily standing in for.
_SHIPPED_PLAN_NATURAL_LANGUAGE = retrieval.plan_natural_language

PLANNER_SHIPPED = "shipped"
PLANNER_OR_FIRST_FILTERED = "or_first_filtered"
PLANNER_AND_FIRST_UNFILTERED = "and_first_unfiltered"
PLANNER_OR_ONLY_UNFILTERED = "or_only_unfiltered"
PLANNER_AND_THEN_PROSE_OR = "and_then_prose_or"

_NO_CONTENT_TERMS_NOTE = (
    "the query has no content terms once stop words and tokens shorter "
    "than three characters are removed; nothing was searched"
)
_NO_RAW_TOKENS_NOTE = (
    "the query has no token carrying an alphanumeric character; nothing was searched"
)


def _empty_plan(note: str) -> QueryPlan:
    return QueryPlan(explicit=False, terms=(), queries=(), note=note)


def _filtered(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The shipped planner's terms and their quoted forms: phrases, then ``_terms``."""
    phrases, remainder = _phrase_terms(query.strip())
    terms = (*phrases, *_terms(remainder))
    quoted = tuple(t if t.startswith('"') else _quote_term(t) for t in terms)
    return terms, quoted


def _unfiltered(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The candidate's tokenisation: every raw token, quoted the FTS5 way."""
    tokens = prose_tokens(query)
    return tokens, tuple('"' + t.replace('"', '""') + '"' for t in tokens)


def _and_then_or(
    terms: tuple[str, ...], quoted: tuple[str, ...], note: str
) -> QueryPlan:
    if not terms:
        return _empty_plan(note)
    and_query, or_query = " AND ".join(quoted), " OR ".join(quoted)
    queries = (and_query,) if and_query == or_query else (and_query, or_query)
    return QueryPlan(explicit=False, terms=terms, queries=queries)


def plan_or_first_filtered(query: str) -> QueryPlan:
    """Arm 2: the shipped OR form alone -- filtered terms, no AND pass first."""
    terms, quoted = _filtered(query)
    if not terms:
        return _empty_plan(_NO_CONTENT_TERMS_NOTE)
    return QueryPlan(explicit=False, terms=terms, queries=(" OR ".join(quoted),))


def plan_and_first_unfiltered(query: str) -> QueryPlan:
    """Arm 3: AND of every raw token, widened to OR of the same -- no stop list."""
    terms, quoted = _unfiltered(query)
    return _and_then_or(terms, quoted, _NO_RAW_TOKENS_NOTE)


def plan_or_only_unfiltered(query: str) -> QueryPlan:
    """Arm 4: the archived branch's ``plan_prose_query`` exactly as it stood."""
    terms, _quoted = _unfiltered(query)
    if not terms:
        return _empty_plan(_NO_RAW_TOKENS_NOTE)
    return QueryPlan(explicit=False, terms=terms, queries=(prose_or_query(query),))


def plan_and_then_prose_or(query: str) -> QueryPlan:
    """Arm 5, the candidate: the shipped AND arm, then the prose-OR as the widen.

    Everything but the widen string is the shipped plan: its terms (STOP set,
    ``len > 2``), its no-content-terms return (the widen is never reached
    without an AND arm in front of it) and its de-duplication when the two
    strings coincide.
    """
    shipped = _SHIPPED_PLAN_NATURAL_LANGUAGE(query)
    if not shipped.terms:
        return shipped
    and_query = shipped.queries[0]
    widen = prose_or_query(query)
    queries = (and_query,) if not widen or widen == and_query else (and_query, widen)
    return QueryPlan(
        explicit=False, terms=shipped.terms, queries=queries, note=shipped.note
    )


#: Planner name -> the function that stands in for ``retrieval.plan_natural_language``
#: (``None`` = the shipped planner, nothing substituted).
PLANNERS: dict[str, Callable[[str], QueryPlan] | None] = {
    PLANNER_SHIPPED: None,
    PLANNER_OR_FIRST_FILTERED: plan_or_first_filtered,
    PLANNER_AND_FIRST_UNFILTERED: plan_and_first_unfiltered,
    PLANNER_OR_ONLY_UNFILTERED: plan_or_only_unfiltered,
    PLANNER_AND_THEN_PROSE_OR: plan_and_then_prose_or,
}

#: Where the substitution lands: the one entry into natural-language planning.
_PLANNER_ENTRY = "agent_session_tools.retrieval.plan_natural_language"


def _planner_context(planner: str) -> Any:
    """A context that runs the service under ``planner``; a no-op for the shipped one."""
    variant = PLANNERS[planner]
    if variant is None:
        return nullcontext()
    from unittest.mock import patch

    return patch(_PLANNER_ENTRY, variant)


def _validate_planner(planner: str) -> str:
    if planner not in PLANNERS:
        raise ValueError(f"unknown planner {planner!r}; known: {', '.join(PLANNERS)}")
    return planner


def _arm_name(transport: str, planner: str) -> str:
    """``mcp`` for the shipped planner, ``mcp:<planner>`` for a variant."""
    return transport if planner == PLANNER_SHIPPED else f"{transport}:{planner}"


def split_arm_name(name: str) -> tuple[str, str]:
    """``"mcp:and_then_prose_or"`` -> ``("mcp", "and_then_prose_or")``; bare -> shipped."""
    transport, _, planner = name.partition(":")
    return transport, planner or PLANNER_SHIPPED


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

    ``planner`` selects a natural-language planner variant (:data:`PLANNERS`)
    substituted into the service for the duration of each call; the shipped
    planner is the default and substitutes nothing. The arm's ``name`` carries
    the variant (``mcp:and_then_prose_or``) so receipts and comparisons do.
    """

    name = "mcp"
    #: The tool argument that lets the census exclude a question's own message.
    EXCLUDE_ARG = "exclude_message_ids"

    #: Which retrieval mode this arm pins through ``STUDYLOOP_RETRIEVAL_MODE``.
    mode = "lexical"

    def __init__(
        self,
        db_path: Path | str,
        rows: int = DEFAULT_ROWS,
        planner: str = PLANNER_SHIPPED,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.rows = rows
        self.planner = _validate_planner(planner)
        self.name = _arm_name(type(self).name, self.planner)
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
            _planner_context(self.planner),
        ):
            with patch.dict(os.environ, {"STUDYLOOP_RETRIEVAL_MODE": self.mode}):
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
            "mode": self.mode,
            "planner": self.planner,
            "rows": self.rows,
            "db_path": str(self.db_path),
            "git_commit": _git_head(),
            "supports_exclusion": self.supports_exclusion,
        }


class HybridMcpArm(McpArm):
    """The same tool with the hybrid mode pinned (Stage 4)."""

    name = "hybrid"
    mode = "hybrid"


class CliArm:
    """``session-query search`` as a subprocess -- the other real interface."""

    name = "cli"
    #: The CLI has no exclusion flag, so the ruler filters this arm's hits.
    supports_exclusion = False
    #: Which retrieval mode the subprocess is pinned to.
    mode = "lexical"

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
                env={**os.environ, "STUDYLOOP_RETRIEVAL_MODE": self.mode},
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
            "mode": self.mode,
            "rows": self.rows,
            "db_path": str(self.db_path),
            "git_commit": _git_head(),
        }


class HybridCliArm(CliArm):
    """The CLI with the hybrid mode pinned; pays the model load per invocation."""

    name = "cli-hybrid"
    mode = "hybrid"


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
    HybridMcpArm.name: HybridMcpArm,
    CliArm.name: CliArm,
    HybridCliArm.name: HybridCliArm,
    FrozenShippedArm.name: FrozenShippedArm,
}

#: The transport arms a planner variant can be applied to: in-process, through
#: the retrieval service. The CLI is a subprocess and the frozen replica is a
#: control that must not move, so neither takes one.
PLANNER_TRANSPORTS = frozenset({McpArm.name, HybridMcpArm.name})


def build_arm(name: str, db_path: Path | str, rows: int = DEFAULT_ROWS) -> Any:
    """Construct one arm by name; ``<transport>:<planner>`` selects a planner variant."""
    transport, planner = split_arm_name(name)
    try:
        factory = ARMS[transport]
    except KeyError:
        raise ValueError(
            f"unknown arm {transport!r}; known: {', '.join(sorted(ARMS))}"
        ) from None
    _validate_planner(planner)
    if planner == PLANNER_SHIPPED:
        return factory(db_path, rows)
    if transport not in PLANNER_TRANSPORTS:
        raise ValueError(
            f"arm {transport!r} cannot take a planner variant; planner variants run "
            f"in-process through the retrieval service ({', '.join(sorted(PLANNER_TRANSPORTS))})"
        )
    return factory(db_path, rows, planner=planner)


__all__ = [
    "ARMS",
    "DEFAULT_ROWS",
    "PLANNERS",
    "PLANNER_AND_FIRST_UNFILTERED",
    "PLANNER_AND_THEN_PROSE_OR",
    "PLANNER_OR_FIRST_FILTERED",
    "PLANNER_OR_ONLY_UNFILTERED",
    "PLANNER_SHIPPED",
    "PLANNER_TRANSPORTS",
    "CliArm",
    "FrozenShippedArm",
    "McpArm",
    "build_arm",
    "frozen_session_search_queries",
    "plan_and_first_unfiltered",
    "plan_and_then_prose_or",
    "plan_or_first_filtered",
    "plan_or_only_unfiltered",
    "split_arm_name",
]
