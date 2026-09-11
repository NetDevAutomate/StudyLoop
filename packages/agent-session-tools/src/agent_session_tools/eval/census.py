"""Paraphrase census over REAL learner questions, adapted to ``sessions.db``.

The design question, unchanged from the original census
(``scripts/knowledge_proof/paraphrase_census.py`` on ``feat/knowledge-proof``):
when a learner asks about something discussed in a past session, how often are
the question's words absent from the transcript -- i.e. how often would a
lexical retriever fail for *vocabulary* reasons rather than *ranking* reasons?

Proxy: every learner turn in a human-driven session (session id not
``agent-*``) is treated as a real question about its own session. For each one:

1. **Vocabulary overlap** -- the share of the question's stemmed content tokens
   that occur anywhere in the *rest* of the same session's prose (the question
   row itself and byte-identical re-asks excluded). ``0.0`` means the
   transcript never used any of the question's words.
2. **Self-retrieval without self** -- the arm is asked the question with the
   question's own message (and its identical re-asks in that session) excluded,
   and we record whether the question's own session is still among the first
   ``k`` distinct sessions returned. A miss is classed ``vocabulary_gap`` when
   overlap is ``0.0`` (no token could have matched) and ``ranking`` otherwise.

**Twin-aware untied_share (plan council F6).** Some questions cannot be won by any
ranker. When the same question text appears verbatim in more than ``k``
sessions, every one of those sessions is an equally good lexical *and* semantic
match -- identical text ties any text ranker and any embedding -- so the own
session's presence in the top ``k`` is a coin toss, not retrieval quality. A
question is therefore *tied* iff ``twins + 1 > k``, where ``twins`` is
the number of OTHER visible sessions holding a user message with the same
(whitespace-normalised) text. ``hit_rate_untied`` divides hits on
*untied* questions by the untied population -- the number an arm is
actually accountable for -- and ``miss_ranking_untied`` is the real headroom.

Limits, stated up front: this compares a question with its OWN session, where
the assistant usually echoes the learner's terms. A real cross-session lookup
targets a *different* past session, where vocabulary drift is larger, so every
paraphrase rate here is a LOWER bound. Numbers are **not** comparable with the
61.08% the original census reported against the knowledge-proof store: that
store has different rows, a different prose definition and a different arm.

Adaptations to ``sessions.db``, all of them database shape rather than method:

* questions are ``messages.role = 'user'`` rows in sessions **visible** under
  the local scope policy (:func:`~agent_session_tools.context.scope.visibility_sql`,
  which also withholds retired harness labels), minus ``agent-*`` session ids;
* prose for the overlap statistic is ``role IN ('user', 'assistant')`` in the
  same visible population;
* self-exclusion goes through the seam's :class:`~.seam.Query` contract, and
  is applied ruler-side with :func:`~.seam.apply_exclusions` for an arm that
  reports ``supports_exclusion = False``.

The tokenizer, the stop list and the suffix stemmer below are the original
census's, unchanged. They define the overlap statistic only -- retrieval always
goes through the arm and never through them.
"""

from __future__ import annotations

import collections
import hashlib
import random
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_session_tools.context.scope import visibility_sql

from . import K, RECEIPT_SCHEMA, SEED
from .seam import ArmError, Query, apply_exclusions, classify_failure

if TYPE_CHECKING:
    import sqlite3

    from .seam import Retriever

#: A question needs at least this many distinct stemmed content tokens.
MIN_TOKENS = 3
#: Longer learner turns are pasted material (logs, docs, briefs), not questions.
MAX_WORDS = 200
#: How many worked examples of each miss shape a result carries.
EXAMPLES = 12
#: How many characters of a question an example quotes.
EXAMPLE_CHARS = 160

# The original census's stop list, verbatim and in its original order (141
# words). Held as a split string rather than a set literal purely so the module
# stays readable; the membership is byte-for-byte the same.
STOP = frozenset(
    """
    a an the and or but if then than that this these those it its is are was
    were be been being have has had do does did doing will would shall
    should can could may might must of in on at to for from with by as into
    onto about over under after before between during without within i me my
    we our you your he she they them their what which who whom whose why how
    when where not no yes so up out off just also only very too more most
    some any each all both few many there here now please want need like get
    got make made use used using let lets ok okay thanks thank yeah right
    sure well still again back new one two way thing things something
    anything done go going come went
    """.split()
)
TOKEN_RE = re.compile(r"[a-z0-9_][a-z0-9_./-]{1,}")

_MISS_VOCABULARY = "vocabulary_gap"
_MISS_RANKING = "ranking"
_MISS_CRASH = "crash"

_METHOD = (
    "Every learner turn in a visible non-agent session is treated as a question "
    "about its own session. Overlap is the share of the question's stemmed "
    "content tokens present in some OTHER prose message of the same session; "
    "self-retrieval@k asks the arm the question with the question's own message "
    "and its identical re-asks excluded, and records whether the own session is "
    "among the first k distinct sessions returned."
)
_LIMITS = (
    "Own-session comparison: the assistant usually echoes the learner's terms, "
    "and cross-session vocabulary drift is larger, so every paraphrase rate is "
    "a LOWER bound. Not comparable with the knowledge-proof store's census."
)


def _stem(tok: str) -> str:
    """A cheap Porter-ish stem: enough to make 'planner'/'planners' agree.

    An approximation of SQLite's porter tokenizer, used only for the overlap
    statistic and never for retrieval (retrieval goes through the arm).
    """
    for suf in (
        "ings",
        "ing",
        "edly",
        "ed",
        "ies",
        "es",
        "s",
        "ly",
        "er",
        "ers",
        "tion",
        "tions",
    ):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            return tok[: -len(suf)]
    return tok


def content_tokens(text: str) -> set[str]:
    """Stemmed, stop-filtered, non-numeric tokens of ``text``."""
    toks = TOKEN_RE.findall(text.lower())
    return {_stem(t) for t in toks if t not in STOP and not t.isdigit()}


def _normalise(text: str) -> str:
    """Whitespace-normalised text, the identity used for twins and re-asks."""
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class CensusQuestion:
    """One eligible learner turn and what the untied_share needs to know about it."""

    message_id: str
    session_id: str
    source: str
    text: str
    tokens: frozenset[str]
    #: Other VISIBLE sessions holding a user message with the same text.
    twins: int

    def tied(self, k: int) -> bool:
        """True when identical text in more than ``k`` sessions ties any ranker."""
        return self.twins + 1 > k


@dataclass(frozen=True, slots=True)
class CensusRow:
    """The per-question record the aggregate numbers are folded from."""

    message_id: str
    session_id: str
    source: str
    text: str
    twins: int
    tied: bool
    overlap: float
    hit: bool
    rank: int | None
    #: ``None`` on a hit, else ``vocabulary_gap`` or ``ranking``.
    miss_class: str | None


@dataclass(frozen=True, slots=True)
class CensusResult:
    """Aggregate census numbers for one arm, plus every per-question row."""

    arm: str
    k: int
    n_eligible: int
    n_tied: int
    #: Winnable share of the population -- the highest hit rate any arm can reach.
    untied_share: float
    hits: int
    hit_rate: float
    #: Hits on questions no text ranker can win (a tie broken the arm's way).
    #: Reported, never credited: they are luck, not retrieval.
    hits_tied: int
    #: ``(hits - hits_tied) / (n_eligible - n_tied)`` -- the share
    #: of the *untied* population the arm actually won. Bounded by 1.0.
    hit_rate_untied: float
    miss_vocab: int
    #: Questions the arm never ranked because it raised. Never folded into
    #: ``miss_ranking``: a crash says nothing about ranking.
    miss_crash: int
    miss_ranking: int
    #: Ranking misses on untied questions -- the real headroom.
    miss_ranking_untied: int
    overlap_mean: float
    overlap_median: float
    by_source: dict[str, dict[str, Any]]
    twin_histogram: dict[int, int]
    zero_overlap_examples: list[dict[str, Any]]
    untied_ranking_miss_examples: list[dict[str, Any]]
    crashes: dict[str, int]
    rows: tuple[CensusRow, ...] = field(repr=False, default=())
    elapsed_seconds: float = 0.0


def _visible_prose_predicate(conn: sqlite3.Connection) -> tuple[str, list[Any]]:
    """The scope predicate for a query that aliases ``sessions`` as ``s``.

    ``visibility_sql`` pins a read snapshot; the caller ends the transaction or
    closes the connection when the census is done.
    """
    return visibility_sql(conn, "s.id")


def collect_questions(
    conn: sqlite3.Connection,
    k: int = K,
    max_words: int = MAX_WORDS,
    min_tokens: int = MIN_TOKENS,
    sample: int | None = None,
    seed: int = SEED,
) -> list[CensusQuestion]:
    """Eligible learner questions in visible non-agent sessions, with twin counts.

    Eligibility is the original census's: at most ``max_words`` whitespace words
    (longer turns are pasted material) and at least ``min_tokens`` distinct
    stemmed content tokens. ``twins`` is counted over every visible user message,
    not only the eligible ones -- a twin ties the ranker whether or not the twin
    itself is a measurable question.

    ``k`` is accepted so a caller collects and scores against one cut-off; the
    twin untied_share is only meaningful relative to it (see
    :meth:`CensusQuestion.tied`). ``sample`` draws deterministically with
    ``random.Random(seed).sample`` over the id-ordered eligible list.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    visible, params = _visible_prose_predicate(conn)
    rows = conn.execute(
        "SELECT m.id, m.session_id, s.source, m.content "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.role = 'user' AND m.content IS NOT NULL "
        "AND m.session_id NOT LIKE 'agent-%' "
        f"AND {visible} ORDER BY m.id",
        params,
    ).fetchall()

    # Twins over the whole visible user population, keyed by normalised text.
    sessions_by_text: dict[str, set[str]] = collections.defaultdict(set)
    for _mid, sid, _source, content in rows:
        sessions_by_text[_normalise(content)].add(sid)

    eligible: list[CensusQuestion] = []
    for mid, sid, source, content in rows:
        if len(content.split()) > max_words:
            continue
        tokens = content_tokens(content)
        if len(tokens) < min_tokens:
            continue
        twins = len(sessions_by_text[_normalise(content)] - {sid})
        eligible.append(
            CensusQuestion(
                message_id=mid,
                session_id=sid,
                source=source or "",
                text=content,
                tokens=frozenset(tokens),
                twins=twins,
            )
        )
    if sample is not None and 0 < sample < len(eligible):
        rng = random.Random(seed)  # nosec B311 - deterministic sampling, not cryptography
        eligible = rng.sample(eligible, sample)
    return eligible


def _overlap_and_self_ids(
    conn: sqlite3.Connection, questions: list[CensusQuestion]
) -> tuple[dict[str, float], dict[str, frozenset[str]]]:
    """Per-question vocabulary overlap and the message ids that are "self".

    Streams visible prose grouped by session so only one session's token
    counters are ever resident. Every self row (the question's own row plus its
    identical re-asks) has the same normalised text and therefore the same
    token set as the question, so the count of self rows is all the
    session-level counter needs subtracting.
    """
    wanted: dict[str, list[CensusQuestion]] = collections.defaultdict(list)
    for question in questions:
        wanted[question.session_id].append(question)
    overlaps: dict[str, float] = {}
    self_ids: dict[str, frozenset[str]] = {}

    visible, params = _visible_prose_predicate(conn)
    cursor = conn.execute(
        "SELECT m.session_id, m.id, m.content "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.role IN ('user', 'assistant') AND m.content IS NOT NULL "
        "AND m.session_id NOT LIKE 'agent-%' "
        f"AND {visible} ORDER BY m.session_id, m.id",
        params,
    )

    def flush(
        sid: str, counter: collections.Counter[str], by_text: dict[str, list[str]]
    ) -> None:
        for question in wanted.get(sid, ()):
            same = list(by_text.get(_normalise(question.text), ()))
            if question.message_id not in same:
                same.append(question.message_id)
            self_ids[question.message_id] = frozenset(same)
            present = sum(1 for t in question.tokens if counter[t] - len(same) > 0)
            overlaps[question.message_id] = present / len(question.tokens)

    current: str | None = None
    counter: collections.Counter[str] = collections.Counter()
    by_text: dict[str, list[str]] = collections.defaultdict(list)
    for sid, mid, content in cursor:
        if sid != current:
            if current is not None:
                flush(current, counter, by_text)
            current = sid
            counter = collections.Counter()
            by_text = collections.defaultdict(list)
        if sid in wanted:
            counter.update(content_tokens(content))
            by_text[_normalise(content)].append(mid)
    if current is not None:
        flush(current, counter, by_text)

    # A question whose session yielded no prose rows cannot happen (the question
    # is itself one), but never let a missing key become a silent zero overlap.
    for question in questions:
        if question.message_id not in overlaps:
            raise LookupError(f"No visible prose for question {question.message_id}")
    return overlaps, self_ids


def _ranked_sessions(
    arm: Retriever, question: CensusQuestion, exclude: frozenset[str], k: int
) -> list[str]:
    """The arm's first ``k`` distinct sessions, self-excluded either way."""
    query = Query(text=question.text, exclude_message_ids=exclude)
    if arm.supports_exclusion:
        return [hit.session_id for hit in arm.search(query, k)][:k]
    hits = arm.search(query, 4 * k)
    return [hit.session_id for hit in apply_exclusions(hits, query, k)]


def run_census(
    conn: sqlite3.Connection,
    arm: Retriever,
    questions: list[CensusQuestion],
    k: int = K,
) -> CensusResult:
    """Score ``arm`` on ``questions``: overlap, self-retrieval@k and the untied_share.

    ``n_eligible`` is ``len(questions)`` -- the whole eligible population, or the
    sample :func:`collect_questions` drew. An arm crash is a miss, never a skip:
    it is counted by :func:`~.seam.classify_failure` class and the question is
    classified from its overlap like any other miss.
    """
    if not questions:
        raise ValueError("The census needs at least one eligible question")
    if not getattr(arm, "supports_exclusion", False):
        raise ValueError(
            f"arm {arm.name!r} cannot exclude the question's own message at query time; "
            "a self-retrieval census through it would credit finding the question itself. "
            "Use an arm with supports_exclusion=True (frozen, or the Stage 2 service)."
        )
    overlaps, self_ids = _overlap_and_self_ids(conn, questions)

    rows: list[CensusRow] = []
    crashes: collections.Counter[str] = collections.Counter()
    started = time.monotonic()
    for question in questions:
        overlap = overlaps[question.message_id]
        crashed = False
        try:
            ranked = _ranked_sessions(arm, question, self_ids[question.message_id], k)
        except ArmError as exc:
            crashes[exc.kind] += 1
            ranked, crashed = [], True
        except Exception as exc:  # a crash is a miss, never an aborted census
            crashes[classify_failure(exc)] += 1
            ranked, crashed = [], True
        hit = question.session_id in ranked
        rank = ranked.index(question.session_id) + 1 if hit else None
        miss_class = None
        if crashed:
            miss_class = _MISS_CRASH  # never folded into ranking: the arm never ranked
        elif not hit:
            miss_class = _MISS_VOCABULARY if overlap == 0.0 else _MISS_RANKING
        rows.append(
            CensusRow(
                message_id=question.message_id,
                session_id=question.session_id,
                source=question.source,
                text=question.text,
                twins=question.twins,
                tied=question.tied(k),
                overlap=overlap,
                hit=hit,
                rank=rank,
                miss_class=miss_class,
            )
        )
    elapsed = time.monotonic() - started
    return _fold(arm, k, rows, crashes, elapsed)


def _fold(
    arm: Retriever,
    k: int,
    rows: list[CensusRow],
    crashes: collections.Counter[str],
    elapsed: float,
) -> CensusResult:
    """Aggregate per-question rows into the reported numbers."""
    n = len(rows)
    n_tied = sum(1 for r in rows if r.tied)
    untied = n - n_tied
    hits_tied = sum(1 for r in rows if r.hit and r.tied)
    hits = sum(1 for r in rows if r.hit)
    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_source.setdefault(
            row.source,
            {
                "n": 0,
                "tied": 0,
                "hits": 0,
                "miss_vocab": 0,
                "miss_crash": 0,
                "miss_ranking": 0,
                "miss_ranking_untied": 0,
            },
        )
        bucket["n"] += 1
        bucket["tied"] += int(row.tied)
        bucket["hits"] += int(row.hit)
        if row.miss_class == _MISS_VOCABULARY:
            bucket["miss_vocab"] += 1
        elif row.miss_class == _MISS_CRASH:
            bucket["miss_crash"] += 1
        elif row.miss_class == _MISS_RANKING:
            bucket["miss_ranking"] += 1
            bucket["miss_ranking_untied"] += int(not row.tied)
    for bucket in by_source.values():
        bucket["hit_rate"] = bucket["hits"] / bucket["n"]
    overlaps = [r.overlap for r in rows]
    return CensusResult(
        arm=arm.name,
        k=k,
        n_eligible=n,
        n_tied=n_tied,
        untied_share=untied / n,
        hits=hits,
        hit_rate=hits / n,
        hits_tied=hits_tied,
        hit_rate_untied=((hits - hits_tied) / untied) if untied else 0.0,
        miss_vocab=sum(1 for r in rows if r.miss_class == _MISS_VOCABULARY),
        miss_crash=sum(1 for r in rows if r.miss_class == _MISS_CRASH),
        miss_ranking=sum(1 for r in rows if r.miss_class == _MISS_RANKING),
        miss_ranking_untied=sum(
            1 for r in rows if r.miss_class == _MISS_RANKING and not r.tied
        ),
        overlap_mean=statistics.fmean(overlaps),
        overlap_median=statistics.median(overlaps),
        by_source=dict(sorted(by_source.items(), key=lambda kv: (-kv[1]["n"], kv[0]))),
        twin_histogram=dict(sorted(collections.Counter(r.twins for r in rows).items())),
        zero_overlap_examples=[_example(r) for r in rows if r.overlap == 0.0][
            :EXAMPLES
        ],
        untied_ranking_miss_examples=[
            _example(r) for r in rows if r.miss_class == _MISS_RANKING and not r.tied
        ][:EXAMPLES],
        crashes=dict(sorted(crashes.items())),
        rows=tuple(rows),
        elapsed_seconds=elapsed,
    )


def _example(row: CensusRow) -> dict[str, Any]:
    """One worked example: enough to read the question and find the session."""
    return {
        "session_id": row.session_id,
        "message_id": row.message_id,
        "source": row.source,
        "twins": row.twins,
        "overlap": round(row.overlap, 4),
        "text": row.text[:EXAMPLE_CHARS],
    }


def _file_digest(path: Path) -> tuple[str, int]:
    """Streaming SHA-256 and byte size of a database file."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def census_receipt(
    result: CensusResult,
    *,
    db_path: Path | str,
    arm_describe: dict[str, object],
) -> dict[str, Any]:
    """A JSON-able receipt: method, metrics, examples and timings kept apart.

    Timings live in their own block so a metric never sits next to a wall-clock
    number that varies between runs of the same measurement.
    """
    path = Path(db_path)
    sha256, size = _file_digest(path) if path.is_file() else ("", 0)
    return {
        "artefact": "paraphrase-census",
        "schema": RECEIPT_SCHEMA,
        "method": _METHOD,
        "limits": _LIMITS,
        "database": {"path": str(path), "sha256": sha256, "size_bytes": size},
        "arm": {"name": result.arm, "config": dict(arm_describe)},
        "parameters": {
            "k": result.k,
            "min_content_tokens": MIN_TOKENS,
            "max_words": MAX_WORDS,
            "tokenizer": TOKEN_RE.pattern,
            "stop_words": len(STOP),
        },
        "metrics": {
            "n_eligible": result.n_eligible,
            "n_tied": result.n_tied,
            "untied_share": round(result.untied_share, 4),
            "hits": result.hits,
            "hit_rate": round(result.hit_rate, 4),
            "hits_tied": result.hits_tied,
            "hit_rate_untied": round(result.hit_rate_untied, 4),
            "miss_vocab": result.miss_vocab,
            "miss_crash": result.miss_crash,
            "miss_ranking": result.miss_ranking,
            "miss_ranking_untied": result.miss_ranking_untied,
            "overlap": {
                "mean": round(result.overlap_mean, 4),
                "median": round(result.overlap_median, 4),
            },
            "by_source": {
                source: {
                    key: (round(value, 4) if isinstance(value, float) else value)
                    for key, value in bucket.items()
                }
                for source, bucket in result.by_source.items()
            },
            "twin_histogram": {
                str(twins): count for twins, count in result.twin_histogram.items()
            },
            "crashes": dict(result.crashes),
        },
        "examples": {
            "zero_overlap": result.zero_overlap_examples,
            "winnable_ranking_miss": result.untied_ranking_miss_examples,
        },
        "timings": {
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "questions_per_second": (
                round(result.n_eligible / result.elapsed_seconds, 2)
                if result.elapsed_seconds > 0
                else None
            ),
        },
    }


__all__ = [
    "EXAMPLES",
    "EXAMPLE_CHARS",
    "MAX_WORDS",
    "MIN_TOKENS",
    "STOP",
    "TOKEN_RE",
    "CensusQuestion",
    "CensusResult",
    "CensusRow",
    "census_receipt",
    "collect_questions",
    "content_tokens",
    "run_census",
]
