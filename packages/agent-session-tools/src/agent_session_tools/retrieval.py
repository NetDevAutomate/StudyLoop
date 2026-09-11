"""One lexical retrieval service for every agent-facing search surface.

``session_search`` (MCP), ``session-query search`` (CLI) and the retrieval-eval
harness all call :func:`search`. The point of a single service is that the
three surfaces cannot disagree: same planner, same SQL, same ordering, same
status vocabulary.

Why this exists (Stage 1 baselines, ``docs/architecture/session-memory/
receipts/semantic-layer/stage1-freeze.md``): 42 of 91 gold questions and
43.2% of real learner turns crashed the shipped search because a lowercase
"and", "or" or "not" in a sentence was taken for an FTS5 operator and the raw
sentence -- backticks, question marks, commas and all -- was handed to
``MATCH``. FTS5 operators are uppercase by definition, so here a query is
explicit FTS5 only when it carries an uppercase operator or the ``fts:``
prefix; everything else is natural language and is planned into quoted
terms that cannot fail to parse. An explicit query that FTS5 rejects is not
an error either: it degrades to the planned form and says so in the status.

Nothing in this module raises for a user's phrasing. Empty results carry a
:class:`RetrievalStatus` that explains what was searched, so "no rows" is
never silent.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from agent_session_tools.context.scope import ScopePolicy, visibility_sql
from agent_session_tools.query_planner import _quote_term, _terms
from agent_session_tools.query_utils import build_date_filter, build_project_filter

PREVIEW_CHARS = 300
"""Preview length; pinned by ``tests/golden/session_search_pre_planner.json``."""

FTS_PREFIX = "fts:"
"""The explicit door: ``fts:error OR authentication`` is passed to FTS5 verbatim."""

# FTS5 operators are case-sensitive uppercase. Lowercase "and" in a sentence
# is a word, which is exactly the distinction the shipped code got wrong.
_EXPLICIT_OPERATOR = re.compile(r"(?<![\w\"])(AND|OR|NOT|NEAR)(?![\w\"])")
_PHRASE = re.compile(r'"([^"]+)"')

MODE_LEXICAL = "lexical"
PLAN_AND = "and"
PLAN_OR = "or"
PLAN_EXPLICIT = "explicit"
PLAN_NONE = "none"


@dataclass(frozen=True)
class RetrievalHit:
    """One matching message, with the provenance the agent needs to cite it."""

    message_id: str
    session_id: str
    source: str
    project_path: str | None
    updated_at: str | None
    role: str
    timestamp: str | None
    preview: str
    rank: float
    full_content: str | None = None

    def to_row(self) -> dict[str, Any]:
        """The ``session_search`` row: the seven golden keys, then ``message_id``."""
        return {
            "session_id": self.session_id,
            "source": self.source,
            "project_path": self.project_path,
            "updated_at": self.updated_at,
            "role": self.role,
            "timestamp": self.timestamp,
            "preview": self.preview,
            "message_id": self.message_id,
        }


@dataclass(frozen=True)
class RetrievalStatus:
    """What was actually searched. Returned with every result, empty or not.

    ``mode`` is ``"lexical"`` until the semantic arm ships; ``plan`` names the
    form that produced the hits (``and``, ``or`` after widening, ``explicit``
    FTS5, or ``none`` when nothing could be searched); ``queries`` lists every
    ``MATCH`` string tried, in order; ``note`` explains any departure from
    what the caller literally asked for.
    """

    mode: str
    plan: str
    terms: tuple[str, ...]
    queries: tuple[str, ...]
    widened: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["terms"] = list(self.terms)
        data["queries"] = list(self.queries)
        return data


@dataclass(frozen=True)
class RetrievalResult:
    hits: tuple[RetrievalHit, ...]
    status: RetrievalStatus

    def to_rows(self) -> list[dict[str, Any]]:
        return [hit.to_row() for hit in self.hits]

    def to_payload(self) -> dict[str, Any]:
        """The shared agent-facing shape for MCP and CLI JSON output."""
        return {"rows": self.to_rows(), "retrieval_status": self.status.to_dict()}


@dataclass(frozen=True)
class QueryPlan:
    """The FTS5 ``MATCH`` strings to try, in order, and how they were derived."""

    explicit: bool
    terms: tuple[str, ...]
    queries: tuple[str, ...]
    note: str | None = None


def _phrase_terms(text: str) -> tuple[tuple[str, ...], str]:
    """Lift double-quoted spans out as phrase terms; return them and the remainder."""
    phrases: list[str] = []
    for span in _PHRASE.findall(text):
        cleaned = " ".join(span.replace('"', " ").split())
        if cleaned:
            phrases.append(f'"{cleaned}"')
    remainder = _PHRASE.sub(" ", text)
    return tuple(phrases), remainder


def _has_operator_outside_quotes(text: str) -> bool:
    """True when an uppercase FTS5 operator appears outside every double-quoted span.

    ``"error OR warning" recovery`` is a phrase plus a word, not an explicit
    query: an operator inside quotes is part of the phrase.
    """
    return bool(_EXPLICIT_OPERATOR.search(_PHRASE.sub(" ", text)))


def plan_natural_language(query: str) -> QueryPlan:
    """Plan ``query`` as natural language, never as explicit FTS5.

    Double-quoted spans are kept as phrases so adjacency survives planning;
    the remaining words become quoted content terms, tried as an AND query and
    widened to OR when the AND form finds nothing (today's shipped behaviour,
    pinned by the planner golden). Nothing this returns can fail to parse.
    """
    phrases, remainder = _phrase_terms(query.strip())
    words = _terms(remainder)
    terms = (*phrases, *words)
    if not terms:
        return QueryPlan(
            explicit=False,
            terms=(),
            queries=(),
            note=(
                "the query has no content terms once stop words and tokens shorter "
                "than three characters are removed; nothing was searched"
            ),
        )
    quoted = tuple(
        term if term.startswith('"') else _quote_term(term) for term in terms
    )
    and_query = " AND ".join(quoted)
    or_query = " OR ".join(quoted)
    queries = (and_query,) if and_query == or_query else (and_query, or_query)
    return QueryPlan(explicit=False, terms=terms, queries=queries)


def plan_query(query: str) -> QueryPlan:
    """Turn what the caller typed into FTS5 ``MATCH`` strings that cannot fail to parse.

    Only the ``fts:`` prefix or an uppercase operator *outside* double quotes
    makes the query explicit FTS5, passed through verbatim; everything else
    goes to :func:`plan_natural_language`.
    """
    stripped = query.strip()
    if stripped.lower().startswith(FTS_PREFIX):
        body = stripped[len(FTS_PREFIX) :].strip()
        return QueryPlan(explicit=True, terms=(), queries=(body,) if body else ())
    if _has_operator_outside_quotes(stripped):
        return QueryPlan(explicit=True, terms=(), queries=(stripped,))
    return plan_natural_language(stripped)


def _search_sql(
    conn: sqlite3.Connection,
    *,
    schema: str,
    source: str | None,
    project: str | None,
    since: str | None,
    before: str | None,
    exclude_main_sessions: bool,
    scope_policy: ScopePolicy | None,
    include_retired_sources: bool,
    exclude_message_ids: tuple[str, ...],
    exclude_session_ids: tuple[str, ...],
    include_content: bool,
    limit: int,
) -> tuple[str, list[Any]]:
    """Build the one SQL statement every surface runs; ``MATCH`` is the first parameter."""
    content_column = ", m.content AS full_content" if include_content else ""
    # bm25() and MATCH need an unqualified FTS table reference, so the FTS pass
    # runs in a subquery whose FROM names the schema -- this is what lets the
    # CLI federate over the attached full-history database.
    sql = f"""
        SELECT m.id AS message_id, s.id AS session_id, s.source, s.project_path,
               s.updated_at, m.role, m.timestamp,
               substr(m.content, 1, {PREVIEW_CHARS}) AS preview, fx.rank AS rank
               {content_column}
        FROM (
            SELECT rowid AS fts_rowid, bm25(messages_fts) AS rank
            FROM {schema}.messages_fts
            WHERE messages_fts MATCH ?
        ) fx
        JOIN {schema}.messages m ON m.rowid = fx.fts_rowid
        JOIN {schema}.sessions s ON m.session_id = s.id
        WHERE 1=1
    """
    visible, scope_params = visibility_sql(
        conn,
        "s.id",
        schema=schema,
        policy=scope_policy,
        include_retired_sources=include_retired_sources,
    )
    sql += " AND " + visible
    params: list[Any] = [*scope_params]
    if source:
        sql += " AND s.source = ?"
        params.append(source)
    if project:
        project_clause, project_params = build_project_filter(project)
        sql += " AND " + project_clause
        params.extend(project_params)
    if exclude_main_sessions:
        sql += " AND s.id NOT IN (SELECT id FROM main.sessions)"
    date_filter, date_params = build_date_filter(since, before)
    if date_filter:
        sql += f" AND ({date_filter.replace('updated_at', 'm.timestamp')})"
        params.extend(date_params)
    if exclude_message_ids:
        sql += f" AND m.id NOT IN ({','.join('?' * len(exclude_message_ids))})"
        params.extend(exclude_message_ids)
    if exclude_session_ids:
        sql += f" AND s.id NOT IN ({','.join('?' * len(exclude_session_ids))})"
        params.extend(exclude_session_ids)
    sql += " ORDER BY rank, m.timestamp DESC LIMIT ?"
    params.append(limit)
    return sql, params


def _run(
    conn: sqlite3.Connection, sql: str, match: str, params: list[Any]
) -> list[Any]:
    return conn.execute(sql, [match, *params]).fetchall()


def _hits(rows: Iterable[Any]) -> tuple[RetrievalHit, ...]:
    hits = []
    for row in rows:
        keys = row.keys() if hasattr(row, "keys") else ()
        data = {key: row[key] for key in keys}
        hits.append(
            RetrievalHit(
                message_id=str(data["message_id"]),
                session_id=str(data["session_id"]),
                source=str(data["source"]),
                project_path=data["project_path"],
                updated_at=data["updated_at"],
                role=str(data["role"]),
                timestamp=data["timestamp"],
                preview=data["preview"] or "",
                rank=float(data["rank"]),
                full_content=data.get("full_content"),
            )
        )
    return tuple(hits)


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 10,
    source: str | None = None,
    project: str | None = None,
    since: str | None = None,
    before: str | None = None,
    schema: str = "main",
    exclude_main_sessions: bool = False,
    scope_policy: ScopePolicy | None = None,
    include_retired_sources: bool = False,
    exclude_message_ids: Iterable[str] = (),
    exclude_session_ids: Iterable[str] = (),
    include_content: bool = False,
) -> RetrievalResult:
    """Search message content for ``query`` and say how it was searched.

    ``conn`` must have ``sqlite3.Row`` rows available (``row_factory`` is set
    for the call when it is not). Results are ordered by bm25 rank then
    newest first, identically for every caller. ``exclude_message_ids`` and
    ``exclude_session_ids`` are applied inside the SQL, which is what lets the
    self-retrieval census gate this exact code path.

    Never raises for the content of ``query``: an explicit FTS5 query that
    fails to parse is re-run as a planned natural-language query, and the
    status ``note`` records the rejection.
    """
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row
    excluded_messages = tuple(str(m) for m in exclude_message_ids)
    excluded_sessions = tuple(str(s) for s in exclude_session_ids)
    sql, params = _search_sql(
        conn,
        schema=schema,
        source=source,
        project=project,
        since=since,
        before=before,
        exclude_main_sessions=exclude_main_sessions,
        scope_policy=scope_policy,
        include_retired_sources=include_retired_sources,
        exclude_message_ids=excluded_messages,
        exclude_session_ids=excluded_sessions,
        include_content=include_content,
        limit=limit,
    )

    query_plan = plan_query(query)
    tried: list[str] = []
    note = query_plan.note

    if query_plan.explicit:
        if not query_plan.queries:
            return RetrievalResult(
                hits=(),
                status=RetrievalStatus(
                    mode=MODE_LEXICAL,
                    plan=PLAN_NONE,
                    terms=(),
                    queries=(),
                    note="the fts: prefix was given with no query after it",
                ),
            )
        explicit_query = query_plan.queries[0]
        tried.append(explicit_query)
        try:
            rows = _run(conn, sql, explicit_query, params)
        except sqlite3.OperationalError as exc:
            note = (
                f"explicit FTS5 syntax was rejected ({exc}); "
                "the query was searched as natural language instead"
            )
            # Re-plan as natural language only -- never re-enter explicit
            # detection, or ``fts:fts:x?`` and a second uppercase operator
            # would run unguarded and crash. Every prefix is stripped.
            body = query.strip()
            while body.lower().startswith(FTS_PREFIX):
                body = body[len(FTS_PREFIX) :].strip()
            query_plan = plan_natural_language(body)
        else:
            return RetrievalResult(
                hits=_hits(rows),
                status=RetrievalStatus(
                    mode=MODE_LEXICAL,
                    plan=PLAN_EXPLICIT,
                    terms=(),
                    queries=tuple(tried),
                ),
            )

    if not query_plan.queries:
        return RetrievalResult(
            hits=(),
            status=RetrievalStatus(
                mode=MODE_LEXICAL,
                plan=PLAN_NONE,
                terms=query_plan.terms,
                queries=tuple(tried),
                note=note or query_plan.note,
            ),
        )

    for index, match in enumerate(query_plan.queries):
        tried.append(match)
        rows = _run(conn, sql, match, params)
        if rows or index == len(query_plan.queries) - 1:
            widened = index > 0
            return RetrievalResult(
                hits=_hits(rows),
                status=RetrievalStatus(
                    mode=MODE_LEXICAL,
                    plan=PLAN_OR if widened else PLAN_AND,
                    terms=query_plan.terms,
                    queries=tuple(tried),
                    widened=widened,
                    note=note,
                ),
            )
    raise AssertionError("unreachable: the planner returned queries but none ran")
