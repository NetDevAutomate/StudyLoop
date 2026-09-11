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

import logging
import os
import re
import sqlite3
from collections.abc import Iterable, Sequence
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

logger = logging.getLogger(__name__)

MODE_LEXICAL = "lexical"
MODE_HYBRID = "hybrid"
MODES = (MODE_LEXICAL, MODE_HYBRID)
MODE_ENV = "STUDYLOOP_RETRIEVAL_MODE"
"""Per-process override of the configured mode; the eval harness pins arms with it."""

# Stage 4 pre-registration (receipts/semantic-layer/stage4-preregistration-
# 2026-09-11.md): two message-level lists of FUSION_DEPTH, Reciprocal Rank
# Fusion with k = RRF_K, no weights, k not tuned. The semantic arm asks the
# filtered candidate call for SEMANTIC_CANDIDATE_ROWS chunk rows and keeps a
# message's best (smallest) distance.
FUSION_DEPTH = 50
RRF_K = 60
SEMANTIC_CANDIDATE_ROWS = 100

# Query-side instruction per model, from the model card. Passages were embedded
# bare in every case; only bge documents a query prefix.
QUERY_PREFIXES: dict[str, str] = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
}

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

    ``mode`` is ``"hybrid"`` when the lexical and semantic arms both ran and
    were fused, ``"lexical"`` otherwise (the note says why when hybrid was
    asked for); ``plan`` names the lexical form that produced the hits
    (``and``, ``or`` after widening, ``explicit`` FTS5, or ``none`` when
    nothing could be searched); ``queries`` lists every ``MATCH`` string
    tried, in order; ``note`` explains any departure from what the caller
    literally asked for; ``semantic`` names the model and how many fused hits
    the semantic arm alone contributed.
    """

    mode: str
    plan: str
    terms: tuple[str, ...]
    queries: tuple[str, ...]
    widened: bool = False
    note: str | None = None
    semantic: dict[str, Any] | None = None

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


def _split_quotes(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split ``text`` into the spans inside double quotes and the text outside them.

    A scanner, not a regex: ``"" OR "alpha"`` has an empty phrase, an ``OR``
    outside every quote and one real phrase, where the regex ``"([^"]+)"``
    skipped the empty pair and read ``" OR "`` as the phrase. An unbalanced
    trailing quote opens no phrase; what follows it is outside text.
    """
    parts = text.split('"')
    if len(parts) % 2 == 0:  # odd number of quotes: the last opener is unmatched
        parts[-2] = parts[-2] + " " + parts[-1]
        parts = parts[:-1]
    inside = tuple(parts[1::2])
    outside = tuple(parts[0::2])
    return inside, outside


def _phrase_terms(text: str) -> tuple[tuple[str, ...], str]:
    """Lift double-quoted spans out as phrase terms; return them and the remainder."""
    inside, outside = _split_quotes(text)
    phrases = tuple(
        f'"{cleaned}"' for span in inside if (cleaned := " ".join(span.split()))
    )
    return phrases, " ".join(outside)


def _has_operator_outside_quotes(text: str) -> bool:
    """True when an uppercase FTS5 operator appears outside every double-quoted span.

    ``"error OR warning" recovery`` is a phrase plus a word, not an explicit
    query: an operator inside quotes is part of the phrase. ``"alpha"AND"bravo"``
    is explicit: the operator sits between two phrases, outside both.
    """
    _, outside = _split_quotes(text)
    return bool(_EXPLICIT_OPERATOR.search(" ".join(outside)))


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


def _filter_clauses(
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
) -> tuple[str, list[Any]]:
    """The WHERE clauses both arms share, starting with visibility.

    One function on purpose: whatever the semantic arm finds is hydrated
    through exactly these clauses, so a session the lexical arm may not return
    (retired source, other project, excluded id) is not returned by the
    semantic arm either.
    """
    visible, scope_params = visibility_sql(
        conn,
        "s.id",
        schema=schema,
        policy=scope_policy,
        include_retired_sources=include_retired_sources,
    )
    sql = " AND " + visible
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
    return sql, params


def _select_columns(include_content: bool) -> str:
    content_column = ", m.content AS full_content" if include_content else ""
    return (
        "SELECT m.id AS message_id, s.id AS session_id, s.source, s.project_path, "
        "s.updated_at, m.role, m.timestamp, "
        f"substr(m.content, 1, {PREVIEW_CHARS}) AS preview"
        f"{content_column}"
    )


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
    # bm25() and MATCH need an unqualified FTS table reference, so the FTS pass
    # runs in a subquery whose FROM names the schema -- this is what lets the
    # CLI federate over the attached full-history database.
    sql = f"""
        {_select_columns(include_content)}, fx.rank AS rank
        FROM (
            SELECT rowid AS fts_rowid, bm25(messages_fts) AS rank
            FROM {schema}.messages_fts
            WHERE messages_fts MATCH ?
        ) fx
        JOIN {schema}.messages m ON m.rowid = fx.fts_rowid
        JOIN {schema}.sessions s ON m.session_id = s.id
        WHERE 1=1
    """
    clauses, params = _filter_clauses(
        conn,
        schema=schema,
        source=source,
        project=project,
        since=since,
        before=before,
        exclude_main_sessions=exclude_main_sessions,
        scope_policy=scope_policy,
        include_retired_sources=include_retired_sources,
        exclude_message_ids=exclude_message_ids,
        exclude_session_ids=exclude_session_ids,
    )
    sql += clauses + " ORDER BY rank, m.timestamp DESC LIMIT ?"
    params.append(limit)
    return sql, params


def _hydrate_sql(
    conn: sqlite3.Connection,
    message_ids: Sequence[str],
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
) -> tuple[str, list[Any]]:
    """The semantic arm's rows: the candidate ids, through the lexical arm's filters."""
    sql = f"""
        {_select_columns(include_content)}, 0.0 AS rank
        FROM {schema}.messages m
        JOIN {schema}.sessions s ON m.session_id = s.id
        WHERE m.id IN ({",".join("?" * len(message_ids))})
    """
    clauses, params = _filter_clauses(
        conn,
        schema=schema,
        source=source,
        project=project,
        since=since,
        before=before,
        exclude_main_sessions=exclude_main_sessions,
        scope_policy=scope_policy,
        include_retired_sources=include_retired_sources,
        exclude_message_ids=exclude_message_ids,
        exclude_session_ids=exclude_session_ids,
    )
    return sql + clauses, [*message_ids, *params]


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


def resolve_mode(requested: str | None = None) -> str:
    """Which mode a search runs in: the argument, else ``STUDYLOOP_RETRIEVAL_MODE``,
    else ``semantic_search.hybrid`` in the config, else lexical.

    An unknown value is a caller error, not a silent fallback."""
    if requested is None:
        requested = os.environ.get(MODE_ENV) or None
    if requested is None:
        try:
            from agent_session_tools.config_loader import get_semantic_config

            requested = (
                MODE_HYBRID if get_semantic_config().get("hybrid") else MODE_LEXICAL
            )
        except Exception:  # config unreadable: the lexical arm always works
            requested = MODE_LEXICAL
    if requested not in MODES:
        raise ValueError(
            f"unknown retrieval mode {requested!r}; expected one of {MODES}"
        )
    return requested


_ENCODERS: dict[str, Any] = {}


def _encoder(model: str) -> Any:
    """One loaded model per process; a search never downloads (offline)."""
    encoder = _ENCODERS.get(model)
    if encoder is None:
        from agent_session_tools import embedding_store

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        encoder = embedding_store.SentenceTransformerEncoder(model)
        _ENCODERS[model] = encoder
    return encoder


def _semantic_ranking(
    conn: sqlite3.Connection, query: str, *, schema: str
) -> tuple[list[str], dict[str, Any] | None, str | None]:
    """The semantic arm: ``(ranked message ids, description, reason it could not run)``.

    Reads the pin from ``message_embeddings`` (one model per database), encodes
    the query with that model (plus its documented query instruction, if any),
    asks the filtered candidate call for chunk rows and keeps each message's
    best distance. Anything that stops the arm is returned as a reason and the
    caller stays lexical -- a search never fails because the semantic layer is
    not there.
    """
    if schema != "main":
        return [], None, "semantic arm runs on the main database only"
    try:
        from agent_session_tools import embedding_store

        # One row names the pin (one model per database, kept by the store);
        # rows of any other model can never match the sidecar's (sha, model)
        # pair in candidates(), so no per-call census of the table is needed.
        pin = conn.execute(
            "SELECT model, dim FROM message_embeddings LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        return [], None, f"no embeddings table ({exc})"
    if pin is None:
        return [], None, "no vectors in message_embeddings"
    model, dim = str(pin[0]), int(pin[1])
    if model not in _ENCODERS:  # first call in this process: is the layer even here?
        ready = embedding_store.availability(model)
        if not ready.ready:
            return [], None, ready.reason or "semantic layer unavailable"
    try:
        encoder = _encoder(model)
        if int(encoder.dim) != dim:
            return (
                [],
                None,
                f"model {model} is {encoder.dim}-d but the table holds {dim}-d rows",
            )
        vector = encoder.encode([QUERY_PREFIXES.get(model, "") + query])[0]
        chunk_rows = embedding_store.candidates(conn, vector, SEMANTIC_CANDIDATE_ROWS)
    except (
        Exception
    ) as exc:  # the arm is optional; the reason is reported, never raised
        logger.warning("semantic arm skipped: %s", exc)
        return [], None, f"semantic arm failed ({type(exc).__name__}: {exc})"
    best: dict[str, float] = {}
    for message_id, _session_id, _chunk_ix, distance in chunk_rows:
        if distance < best.get(message_id, float("inf")):
            best[message_id] = distance
    ranked = sorted(best, key=lambda m: best[m])[:FUSION_DEPTH]
    return ranked, {"model": model, "dim": dim}, None


def _newest_first(timestamp: str | None) -> tuple[bool, str]:
    """A key that sorts ISO timestamps newest first inside an ascending sort; None last."""
    if timestamp is None:
        return (True, "")
    return (False, "".join(chr(0x10FFFF - ord(c)) for c in str(timestamp)))


def _fuse(
    lexical: Sequence[RetrievalHit],
    semantic_ids: Sequence[str],
    semantic_rows: dict[str, RetrievalHit],
    *,
    limit: int,
) -> tuple[tuple[RetrievalHit, ...], int]:
    """Reciprocal Rank Fusion of the two message lists; ``(hits, semantic-only count)``.

    ``score(m) = sum over arms of 1 / (RRF_K + rank)``, rank starting at 1.
    Ties: present in both arms first, then lexical rank, then newest
    timestamp. ``RetrievalHit.rank`` on a fused hit is ``-score`` so that
    "lower is better" still holds for every caller that sorts by it.
    """
    score: dict[str, float] = {}
    lexical_rank: dict[str, int] = {}
    rows: dict[str, RetrievalHit] = {}
    for rank, hit in enumerate(lexical, 1):
        lexical_rank[hit.message_id] = rank
        rows[hit.message_id] = hit
        score[hit.message_id] = score.get(hit.message_id, 0.0) + 1.0 / (RRF_K + rank)
    semantic_seen: set[str] = set()
    for rank, message_id in enumerate(semantic_ids, 1):
        hit = semantic_rows.get(message_id)
        if hit is None:  # filtered out by the shared clauses
            continue
        semantic_seen.add(message_id)
        rows.setdefault(message_id, hit)
        score[message_id] = score.get(message_id, 0.0) + 1.0 / (RRF_K + rank)

    def key(message_id: str) -> tuple[float, int, int, bool, str]:
        in_both = message_id in lexical_rank and message_id in semantic_seen
        return (
            -score[message_id],
            0 if in_both else 1,
            lexical_rank.get(message_id, FUSION_DEPTH + 1),
            *_newest_first(rows[message_id].timestamp),
        )

    ordered = sorted(score, key=key)[:limit]
    fused = tuple(
        RetrievalHit(**{**asdict(rows[m]), "rank": -score[m]}) for m in ordered
    )
    semantic_only = sum(1 for m in ordered if m not in lexical_rank)
    return fused, semantic_only


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
    mode: str | None = None,
) -> RetrievalResult:
    """Search message content for ``query`` and say how it was searched.

    ``mode`` is ``"lexical"`` or ``"hybrid"``; ``None`` resolves through
    :func:`resolve_mode`. Hybrid runs the lexical plan exactly as lexical does,
    then the semantic arm, and fuses the two message lists (Stage 4
    pre-registration). When the semantic arm cannot run, the result is the
    lexical one with ``status.mode == "lexical"`` and the reason in ``note``.

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
    resolved_mode = resolve_mode(mode)
    excluded_messages = tuple(str(m) for m in exclude_message_ids)
    excluded_sessions = tuple(str(s) for s in exclude_session_ids)
    filters: dict[str, Any] = dict(
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
    )
    lexical_depth = max(limit, FUSION_DEPTH) if resolved_mode == MODE_HYBRID else limit

    def finish(
        rows: Iterable[Any],
        *,
        plan: str,
        terms: tuple[str, ...],
        widened: bool,
        note: str | None,
    ) -> RetrievalResult:
        lexical_hits = _hits(rows)
        status_mode = MODE_LEXICAL
        semantic_info: dict[str, Any] | None = None
        hits: tuple[RetrievalHit, ...] = lexical_hits[:limit]
        if resolved_mode == MODE_HYBRID and plan != PLAN_EXPLICIT:
            ranked, semantic_info, reason = _semantic_ranking(
                conn, query, schema=schema
            )
            if reason is not None:
                note = f"{note}; " if note else ""
                note += f"hybrid requested but lexical only: {reason}"
            else:
                semantic_rows: dict[str, RetrievalHit] = {}
                if ranked:
                    hydrate_sql, hydrate_params = _hydrate_sql(
                        conn, ranked, include_content=include_content, **filters
                    )
                    semantic_rows = {
                        hit.message_id: hit
                        for hit in _hits(
                            conn.execute(hydrate_sql, hydrate_params).fetchall()
                        )
                    }
                hits, semantic_only = _fuse(
                    lexical_hits, ranked, semantic_rows, limit=limit
                )
                status_mode = MODE_HYBRID
                assert semantic_info is not None
                semantic_info = {
                    **semantic_info,
                    "candidates": len(ranked),
                    "after_filters": len(semantic_rows),
                    "semantic_only_in_result": semantic_only,
                }
        elif resolved_mode == MODE_HYBRID:
            note = f"{note}; " if note else ""
            note += "explicit FTS5 syntax is searched lexically"
        return RetrievalResult(
            hits=hits,
            status=RetrievalStatus(
                mode=status_mode,
                plan=plan,
                terms=terms,
                queries=tuple(tried),
                widened=widened,
                note=note,
                semantic=semantic_info if status_mode == MODE_HYBRID else None,
            ),
        )

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
        limit=lexical_depth,
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
            return finish(rows, plan=PLAN_EXPLICIT, terms=(), widened=False, note=None)

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
            return finish(
                rows,
                plan=PLAN_OR if widened else PLAN_AND,
                terms=query_plan.terms,
                widened=widened,
                note=note,
            )
    raise AssertionError("unreachable: the planner returned queries but none ran")
