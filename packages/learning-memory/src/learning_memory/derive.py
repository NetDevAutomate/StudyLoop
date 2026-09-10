"""Deterministic derivation: exchanges, flags, concepts (ADR-0011 v1.1, "Derivation rules").

The $0 pass. Every rule here is a pure function of one session's events, so a
derivation is replayable from the store alone, and every row it writes is tagged
with :data:`DERIVATION_VERSION` -- council finding 8/10: derivation output is
rebuilt per version rather than assumed stable across a renumbering.

Re-running is safe: :func:`derive_session` deletes and rewrites only the rows
carrying its own version for that session.

What the corpus forced, and the choices the spec left open (all listed in the
Stage D report):

1. **Rules operate on** :class:`StoredEvent`, not ``model.Event``. ``exchanges``
   records ``question_event_id`` and ``answer_event_ids``, which are row ids that
   ``model.Event`` deliberately does not carry.
2. **``retried`` compares tool NAMES on the archive.** 39,620 of 39,796
   ``tool_call`` rows have empty text -- the archive stored that a tool ran and its
   name, never its arguments -- so a signature is ``(tool_name, normalised text)``
   only when text exists, and ``tool_name`` alone otherwise.
3. **Quarantine reason is not a column.** Schema v2's ``exchanges`` has no
   ``quarantine_reason``, and adding one means SCHEMA_VERSION 3, which would make
   ``install()`` refuse the existing store and force a re-ingest. The reason is on
   the receipt and is still recoverable from the rows: ``resolved IS NULL`` marks a
   quarantine, and ``question_event_id IS NULL`` separates ``pre_first_user`` (no
   user event to anchor to) from ``empty_user_text`` (a user event with no text).
4. **A ``pre_first_user`` block is one row at ``turn_id`` 0**, which is free
   because real turns start at 1 (turn_id is the running user count).
5. **``concepts.id`` is ``"c-" + sha256(canonical)[:16]``** -- deterministic, so a
   re-derivation reproduces the same ids without reading the old rows.
6. **The vocabulary's 7 areas are concepts too**, per spec, giving 110 concepts
   from 103 distinct terms (5 terms appear in two areas each; the file holds 108
   term entries).
7. **``day_gap_basis``** is recorded per recurrence candidate. ``sessions.started_at``
   is never NULL in this store, so ``unknown`` is unreachable today and is kept only
   so a future harness without timestamps is visible rather than silently bucketed.
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence

    from learning_memory.store import Store

__all__ = [
    "DERIVATION_VERSION",
    "FAILURE_LEXICON",
    "INTERROGATIVES",
    "VOCAB_PATH",
    "DerivedExchange",
    "StoredEvent",
    "Vocabulary",
    "derive_all",
    "derive_session",
    "exchange_flags",
    "had_error",
    "is_question",
    "load_vocabulary",
    "retried",
    "split_exchanges",
    "strip_user_wrapper",
    "vocab_sha256",
]

DERIVATION_VERSION: Final = "derive-v1"

VOCAB_PATH: Final = Path(__file__).parent / "data" / "topic_vocab.v1.json"

INTERROGATIVES: Final[frozenset[str]] = frozenset(
    {
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "can",
        "could",
        "should",
        "would",
        "does",
        "do",
        "is",
        "are",
        "will",
    }
)
"""Versioned: a change here is a new DERIVATION_VERSION, not a tweak."""

FAILURE_LEXICON: Final[tuple[str, ...]] = (
    r"\btraceback\b",
    r"\bexception\b",
    r"\berror:",
    r"\bfailed\b",
    r"\bcannot\b",
    r"\bnot found\b",
    r"\bpermission denied\b",
    r"\bno such\b",
    r"\bsyntax error\b",
    r"\btimed out\b",
    r"\bexit code [1-9][0-9]*\b",
)
"""Versioned failure lexicon, word-bounded and applied to casefolded text."""

_FAILURE_RE: Final = re.compile("|".join(FAILURE_LEXICON))

_USER_WRAPPERS: Final = re.compile(
    r"^\s*<(task|user_query)\b[^>]*>(?P<inner>.*?)</\1>", re.DOTALL | re.IGNORECASE
)
"""Kilocode/grok wrap the learner's own words; the wrapper is not their sentence."""

_WORD: Final = re.compile(r"[a-z0-9]+(?:[-_'][a-z0-9]+)*")
_WHITESPACE: Final = re.compile(r"\s+")

NEAR_REPEAT_RATIO: Final = 0.9

QuarantineReason = Literal["pre_first_user", "empty_user_text"]
DayGapBasis = Literal["event_ts", "session_started_at", "unknown"]


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """One event row as derivation needs it: the model's Event plus its row id."""

    id: int
    turn_id: int
    seq: int
    kind: str
    text: str
    tool_name: str | None = None
    ts: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedExchange:
    """One derived exchange, ready to write."""

    turn_id: int
    question_event_id: int | None
    answer_event_ids: tuple[int, ...]
    is_question: bool
    had_error: bool
    retried: bool
    resolved: bool | None
    quarantine_reason: QuarantineReason | None = None
    events: tuple[StoredEvent, ...] = ()

    @property
    def quarantined(self) -> bool:
        return self.resolved is None


# --------------------------------------------------------------------- vocabulary


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The learner's topic vocabulary as canonical concepts plus alias forms."""

    sha256: str
    concepts: dict[str, str]
    """canonical -> concept id."""
    areas: tuple[str, ...]
    alias_to_concept: dict[str, str]
    """matchable surface form (casefolded) -> canonical."""
    surface_matcher: re.Pattern[str]
    """One alternation over every surface form, longest first."""
    alias_collisions: tuple[tuple[str, str, str], ...] = ()
    """(alias, kept canonical, dropped canonical) -- first writer wins."""

    def tag(self, texts: Iterable[str]) -> set[tuple[str, str]]:
        """Return ``{(canonical, source)}`` for whole-word casefolded matches."""
        found: set[tuple[str, str]] = set()
        for text in texts:
            for match in self.surface_matcher.finditer(text.casefold()):
                form = match.group(0)
                canonical = self.alias_to_concept[form]
                found.add((canonical, "vocab" if form == canonical else "alias"))
        return found


def concept_id(canonical: str) -> str:
    return "c-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def vocab_sha256(path: Path = VOCAB_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alias_forms(term: str) -> list[str]:
    """The term itself, plus hyphen->space and hyphen->nothing."""
    return list(dict.fromkeys([term, term.replace("-", " "), term.replace("-", "")]))


def load_vocabulary(path: Path = VOCAB_PATH) -> Vocabulary:
    """Load the vocabulary. Areas are concepts too, per the derivation spec."""
    payload: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    canonicals: list[str] = []
    for area, terms in payload.items():
        canonicals.append(area.casefold())
        canonicals.extend(term.casefold() for term in terms)
    ordered = list(dict.fromkeys(canonicals))

    alias_to_concept: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    for canonical in ordered:
        for form in _alias_forms(canonical):
            existing = alias_to_concept.get(form)
            if existing is None:
                alias_to_concept[form] = canonical
            elif existing != canonical:
                collisions.append((form, existing, canonical))
    forms = sorted(alias_to_concept, key=lambda form: (-len(form), form))
    matcher = re.compile(r"\b(?:" + "|".join(re.escape(form) for form in forms) + r")\b")
    return Vocabulary(
        sha256=vocab_sha256(path),
        concepts={canonical: concept_id(canonical) for canonical in ordered},
        areas=tuple(area.casefold() for area in payload),
        alias_to_concept=alias_to_concept,
        surface_matcher=matcher,
        alias_collisions=tuple(collisions),
    )


# -------------------------------------------------------------------- pure rules


def strip_user_wrapper(text: str) -> str:
    """Return the learner's own sentence, without a harness ``<task>`` wrapper."""
    match = _USER_WRAPPERS.match(text)
    return match.group("inner").strip() if match else text.strip()


def is_question(user_text: str) -> bool:
    """A '?' anywhere, or an interrogative first word."""
    stripped = strip_user_wrapper(user_text)
    if "?" in stripped:
        return True
    first = _WORD.search(stripped.casefold())
    return first is not None and first.group(0) in INTERROGATIVES


def had_error(events: Sequence[StoredEvent]) -> bool:
    """An ``error`` event, or failure language in tool output or assistant prose."""
    for event in events:
        if event.kind == "error":
            return True
        if event.kind in ("tool_result", "assistant_prose") and _FAILURE_RE.search(
            event.text.casefold()
        ):
            return True
    return False


def _tool_signature(event: StoredEvent) -> tuple[str, str]:
    name = (event.tool_name or "").casefold()
    if event.text:
        return (name, _WHITESPACE.sub(" ", event.text.strip()).casefold())
    return (name, "")


def retried(events: Sequence[StoredEvent]) -> bool:
    """The same tool called twice in one exchange.

    Arguments are compared only where the archive kept them (176 of 39,796 rows);
    everywhere else this is necessarily name-only, which is what the corpus allows.
    """
    seen: set[tuple[str, str]] = set()
    for event in events:
        if event.kind != "tool_call":
            continue
        signature = _tool_signature(event)
        if signature in seen:
            return True
        seen.add(signature)
    return False


def _normalise_for_repeat(text: str) -> str:
    return _WHITESPACE.sub(" ", strip_user_wrapper(text)).strip().casefold()


def is_near_repeat(first: str, second: str) -> bool:
    """Two user turns that say the same thing (difflib ratio >= 0.9)."""
    left = _normalise_for_repeat(first)
    right = _normalise_for_repeat(second)
    if not left or not right:
        return False
    if left == right:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= NEAR_REPEAT_RATIO


def ends_with_prose(events: Sequence[StoredEvent]) -> bool:
    return bool(events) and events[-1].kind == "assistant_prose"


def split_exchanges(events: Sequence[StoredEvent]) -> list[DerivedExchange]:
    """Thread events into exchanges, quarantining what cannot be threaded.

    Exchange = a ``user`` event plus every following non-``user`` event. Anything
    before the first user event has no question to belong to, and a user event with
    no text is not a turn; both are quarantined (``resolved=None``) rather than
    guessed at.
    """
    ordered = sorted(events, key=lambda event: (event.seq, event.id))
    preamble: list[StoredEvent] = []
    groups: list[tuple[StoredEvent, list[StoredEvent]]] = []
    for event in ordered:
        if event.kind == "user":
            groups.append((event, []))
        elif groups:
            groups[-1][1].append(event)
        else:
            preamble.append(event)

    derived: list[DerivedExchange] = []
    if preamble:
        derived.append(
            DerivedExchange(
                turn_id=0,
                question_event_id=None,
                answer_event_ids=tuple(event.id for event in preamble),
                is_question=False,
                had_error=had_error(preamble),
                retried=retried(preamble),
                resolved=None,
                quarantine_reason="pre_first_user",
                events=tuple(preamble),
            )
        )

    for index, (question, answers) in enumerate(groups):
        body = [question, *answers]
        if not question.text.strip():
            derived.append(
                DerivedExchange(
                    turn_id=question.turn_id,
                    question_event_id=question.id,
                    answer_event_ids=tuple(event.id for event in answers),
                    is_question=False,
                    had_error=had_error(body),
                    retried=retried(body),
                    resolved=None,
                    quarantine_reason="empty_user_text",
                    events=tuple(body),
                )
            )
            continue
        next_user = groups[index + 1][0].text if index + 1 < len(groups) else None
        derived.append(exchange_flags(question, answers, next_user_text=next_user))
    return derived


def exchange_flags(
    question: StoredEvent,
    answers: Sequence[StoredEvent],
    *,
    next_user_text: str | None,
) -> DerivedExchange:
    """Every flag for one non-quarantined exchange."""
    body = [question, *answers]
    closed = ends_with_prose(body)
    if next_user_text is None:
        resolved = closed
    else:
        resolved = closed and not is_near_repeat(question.text, next_user_text)
    return DerivedExchange(
        turn_id=question.turn_id,
        question_event_id=question.id,
        answer_event_ids=tuple(event.id for event in answers),
        is_question=is_question(question.text),
        had_error=had_error(body),
        retried=retried(body),
        resolved=resolved,
        events=tuple(body),
    )


def taggable_texts(exchange: DerivedExchange) -> list[str]:
    """Concepts are tagged from the learner's and the agent's prose only."""
    return [event.text for event in exchange.events if event.kind in ("user", "assistant_prose")]


def intent_of(exchanges: Sequence[DerivedExchange], limit: int = 200) -> str | None:
    """First real user turn, wrapper stripped."""
    for exchange in exchanges:
        if exchange.quarantine_reason is None and exchange.question_event_id is not None:
            text = strip_user_wrapper(exchange.events[0].text)
            if text:
                return text[:limit]
    return None


def outcome_of(exchanges: Sequence[DerivedExchange], limit: int = 500) -> str | None:
    """Last assistant_prose of the last resolved exchange."""
    for exchange in reversed(exchanges):
        if exchange.resolved:
            for event in reversed(exchange.events):
                if event.kind == "assistant_prose" and event.text.strip():
                    return event.text.strip()[:limit]
    return None


# ------------------------------------------------------------------- persistence


@dataclass(slots=True)
class SessionDerivation:
    """What one session's derivation produced, before or after writing."""

    session_id: str
    exchanges: list[DerivedExchange] = field(default_factory=list)
    concept_hits: dict[str, set[str]] = field(default_factory=dict)
    """canonical -> {sources}, for the session as a whole."""
    observed_at: dict[str, str] = field(default_factory=dict)
    """canonical -> earliest observation timestamp."""
    day_gap_basis: dict[str, str] = field(default_factory=dict)
    intent: str | None = None
    outcome: str | None = None


def _load_events(conn: sqlite3.Connection, session_id: str) -> list[StoredEvent]:
    return [
        StoredEvent(
            id=int(row["id"]),
            turn_id=int(row["turn_id"]),
            seq=int(row["seq"]),
            kind=str(row["kind"]),
            text=str(row["text"]),
            tool_name=row["tool_name"],
            ts=row["ts"],
        )
        for row in conn.execute(
            "SELECT id, turn_id, seq, kind, text, tool_name, ts FROM events"
            " WHERE session_id = ? ORDER BY seq, id",
            (session_id,),
        )
    ]


def ensure_vocabulary(store: Store, vocab: Vocabulary) -> None:
    """Upsert the concept and alias rows. Version-free: the vocabulary is the vocabulary."""
    conn = store.connection
    conn.execute("BEGIN IMMEDIATE")
    try:
        for canonical, identifier in vocab.concepts.items():
            conn.execute(
                "INSERT INTO concepts(id, canonical) VALUES (?, ?)"
                " ON CONFLICT(canonical) DO NOTHING",
                (identifier, canonical),
            )
        for alias, canonical in vocab.alias_to_concept.items():
            conn.execute(
                "INSERT INTO concept_aliases(alias, concept_id) VALUES (?, ?)"
                " ON CONFLICT(alias) DO NOTHING",
                (alias, vocab.concepts[canonical]),
            )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _vocabulary_present(conn: sqlite3.Connection, vocab: Vocabulary) -> bool:
    row = conn.execute("SELECT count(*) AS n FROM concepts").fetchone()
    return int(row["n"]) >= len(vocab.concepts)


def _clear_version(conn: sqlite3.Connection, session_id: str) -> None:
    """Delete only this version's rows for this session, tags included."""
    conn.execute(
        """
        DELETE FROM concept_tags WHERE exchange_id IN (
            SELECT id FROM exchanges WHERE session_id = ? AND derivation_version = ?
        )
        """,
        (session_id, DERIVATION_VERSION),
    )
    conn.execute(
        "DELETE FROM exchanges WHERE session_id = ? AND derivation_version = ?",
        (session_id, DERIVATION_VERSION),
    )
    conn.execute(
        "DELETE FROM concept_occurrences WHERE session_id = ? AND derivation_version = ?",
        (session_id, DERIVATION_VERSION),
    )


def derive_session(
    store: Store, session_id: str, vocab: Vocabulary, *, ensure_vocab: bool = True
) -> SessionDerivation:
    """Derive one session in one transaction, replacing this version's rows.

    ``concept_tags.concept_id`` is a real FK, so the vocabulary rows have to exist
    before any tag can be written. ``derive_all`` seeds them once and passes
    ``ensure_vocab=False``; a standalone call checks and seeds them itself rather
    than failing with a foreign-key error.
    """
    conn = store.connection
    if ensure_vocab and not _vocabulary_present(conn, vocab):
        ensure_vocabulary(store, vocab)
    row = conn.execute("SELECT started_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise KeyError(f"no session {session_id!r} in the store")
    session_started_at = row["started_at"]

    events = _load_events(conn, session_id)
    exchanges = split_exchanges(events)
    result = SessionDerivation(session_id=session_id, exchanges=exchanges)
    result.intent = intent_of(exchanges)
    result.outcome = outcome_of(exchanges)

    conn.execute("BEGIN IMMEDIATE")
    try:
        _clear_version(conn, session_id)
        for exchange in exchanges:
            cursor = conn.execute(
                """
                INSERT INTO exchanges(session_id, derivation_version, turn_id,
                                      question_event_id, answer_event_ids,
                                      is_question, had_error, retried, resolved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    DERIVATION_VERSION,
                    exchange.turn_id,
                    exchange.question_event_id,
                    json.dumps(list(exchange.answer_event_ids)),
                    int(exchange.is_question),
                    int(exchange.had_error),
                    int(exchange.retried),
                    None if exchange.resolved is None else int(exchange.resolved),
                ),
            )
            exchange_id = cursor.lastrowid
            for canonical, source in sorted(vocab.tag(taggable_texts(exchange))):
                conn.execute(
                    "INSERT INTO concept_tags(exchange_id, concept_id, source)"
                    " VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    (exchange_id, vocab.concepts[canonical], source),
                )
                result.concept_hits.setdefault(canonical, set()).add(source)
                stamp, basis = _observation(exchange, session_started_at)
                if canonical not in result.observed_at or stamp < result.observed_at[canonical]:
                    result.observed_at[canonical] = stamp
                    result.day_gap_basis[canonical] = basis

        for canonical in sorted(result.concept_hits):
            conn.execute(
                "INSERT INTO concept_occurrences(concept_id, session_id, derivation_version,"
                " observed_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (
                    vocab.concepts[canonical],
                    session_id,
                    DERIVATION_VERSION,
                    result.observed_at[canonical],
                ),
            )
        conn.execute(
            "UPDATE sessions SET intent = ?, outcome = ? WHERE id = ?",
            (result.intent, result.outcome, session_id),
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return result


def _observation(exchange: DerivedExchange, session_started_at: str | None) -> tuple[str, str]:
    """Earliest event ts in the exchange, else the session's start."""
    stamps = [event.ts for event in exchange.events if event.ts]
    if stamps:
        return min(stamps), "event_ts"
    if session_started_at:
        return str(session_started_at), "session_started_at"
    return "", "unknown"


def _day(stamp: str) -> str:
    return stamp[:10]


def derive_all(store: Store, *, limit: int = 0, progress_every: int = 0) -> dict[str, Any]:
    """Derive every session and return the receipt."""
    started = time.monotonic()
    vocab = load_vocabulary()
    ensure_vocabulary(store, vocab)
    conn = store.connection
    session_ids = [
        str(row["id"]) for row in conn.execute("SELECT id FROM sessions ORDER BY started_at, id")
    ]
    if limit:
        session_ids = session_ids[:limit]

    flag_combos: dict[str, int] = {}
    quarantined: dict[str, int] = {"pre_first_user": 0, "empty_user_text": 0}
    quarantine_sample: dict[str, list[str]] = {"pre_first_user": [], "empty_user_text": []}
    concept_sessions: dict[str, set[str]] = {}
    concept_tag_totals: dict[str, int] = {}
    concept_days: dict[str, dict[str, str]] = {}
    basis_counts: dict[str, int] = {"event_ts": 0, "session_started_at": 0, "unknown": 0}
    exchanges_total = 0
    derived_sessions = 0
    intent_filled = outcome_filled = 0
    failures: list[dict[str, str]] = []

    for index, session_id in enumerate(session_ids, start=1):
        try:
            result = derive_session(store, session_id, vocab, ensure_vocab=False)
        except Exception as err:
            failures.append({"session_id": session_id, "error": f"{type(err).__name__}: {err}"})
            continue
        derived_sessions += 1
        intent_filled += bool(result.intent)
        outcome_filled += bool(result.outcome)
        for exchange in result.exchanges:
            exchanges_total += 1
            if exchange.quarantine_reason:
                quarantined[exchange.quarantine_reason] += 1
                sample = quarantine_sample[exchange.quarantine_reason]
                if len(sample) < 5:
                    sample.append(session_id)
                continue
            key = (
                f"q={int(exchange.is_question)} e={int(exchange.had_error)} "
                f"r={int(exchange.retried)} s={int(bool(exchange.resolved))}"
            )
            flag_combos[key] = flag_combos.get(key, 0) + 1
        for canonical, sources in result.concept_hits.items():
            concept_sessions.setdefault(canonical, set()).add(session_id)
            concept_tag_totals[canonical] = concept_tag_totals.get(canonical, 0) + len(sources)
            basis = result.day_gap_basis.get(canonical, "unknown")
            basis_counts[basis] += 1
            day = _day(result.observed_at.get(canonical, ""))
            concept_days.setdefault(canonical, {})[session_id] = day
        if progress_every and index % progress_every == 0:
            print(f"  ... {index}/{len(session_ids)} sessions", flush=True)

    recurrence = _recurrence(concept_sessions, concept_days, basis_counts)
    elapsed = time.monotonic() - started
    return {
        "receipt": "derive",
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "derivation_version": DERIVATION_VERSION,
        "vocab": {
            "path": str(VOCAB_PATH),
            "sha256": vocab.sha256,
            "areas": len(vocab.areas),
            "concepts": len(vocab.concepts),
            "surface_forms": len(vocab.alias_to_concept),
            "alias_collisions": [
                {"alias": alias, "kept": kept, "dropped": dropped}
                for alias, kept, dropped in vocab.alias_collisions
            ],
        },
        "sessions": {
            "in_store": len(session_ids),
            "derived": derived_sessions,
            "failed": len(failures),
            "failures": failures,
        },
        "exchanges": {
            "total": exchanges_total,
            "threaded": exchanges_total - sum(quarantined.values()),
            "by_flags": dict(sorted(flag_combos.items(), key=lambda kv: -kv[1])),
            "quarantined": quarantined,
            "quarantine_sample_sessions": quarantine_sample,
        },
        "concepts": {
            "distinct_tagged": len(concept_sessions),
            "total_tags": sum(concept_tag_totals.values()),
            "top_15": [
                {
                    "concept": canonical,
                    "sessions": len(concept_sessions[canonical]),
                    "tags": concept_tag_totals[canonical],
                }
                for canonical in sorted(
                    concept_sessions, key=lambda c: (-len(concept_sessions[c]), c)
                )[:15]
            ],
        },
        "recurrence": recurrence,
        "intent_outcome": {
            "intent_filled": intent_filled,
            "outcome_filled": outcome_filled,
            "intent_fill_rate": round(intent_filled / max(derived_sessions, 1), 4),
            "outcome_fill_rate": round(outcome_filled / max(derived_sessions, 1), 4),
        },
        "wall_seconds": round(elapsed, 2),
    }


def _recurrence(
    concept_sessions: dict[str, set[str]],
    concept_days: dict[str, dict[str, str]],
    basis_counts: dict[str, int],
) -> dict[str, Any]:
    """Concepts seen in >= 2 distinct sessions at least a day apart. Receipt only.

    ADR-0011 writes a ``struggled`` backlog item from this; Stage D deliberately
    does not, because the backlog lives in StudyLoop's own store, not the PoC.
    """
    candidates: list[dict[str, Any]] = []
    for canonical, sessions in concept_sessions.items():
        if len(sessions) < 2:
            continue
        days = sorted({day for day in concept_days.get(canonical, {}).values() if day})
        if len(days) < 2 or days[0] == days[-1]:
            continue
        candidates.append(
            {
                "concept": canonical,
                "sessions": len(sessions),
                "first_day": days[0],
                "last_day": days[-1],
                "distinct_days": len(days),
            }
        )
    candidates.sort(key=lambda item: (-int(item["sessions"]), str(item["concept"])))
    return {
        "candidates": len(candidates),
        "day_gap_basis": basis_counts,
        "top_15": candidates[:15],
    }


def derivation_fingerprint(store: Store) -> dict[str, str]:
    """Content hash of everything this version wrote. Used to prove idempotence."""
    conn = store.connection
    hashes: dict[str, str] = {}
    rows = conn.execute(
        """
        SELECT session_id, turn_id, question_event_id, answer_event_ids,
               is_question, had_error, retried, resolved
        FROM exchanges WHERE derivation_version = ?
        ORDER BY session_id, turn_id
        """,
        (DERIVATION_VERSION,),
    ).fetchall()
    hashes["exchanges"] = _hash_rows(rows)
    hashes["concept_tags"] = _hash_rows(
        conn.execute(
            """
            SELECT e.session_id, e.turn_id, t.concept_id, t.source
            FROM concept_tags t JOIN exchanges e ON e.id = t.exchange_id
            WHERE e.derivation_version = ?
            ORDER BY e.session_id, e.turn_id, t.concept_id, t.source
            """,
            (DERIVATION_VERSION,),
        ).fetchall()
    )
    hashes["concept_occurrences"] = _hash_rows(
        conn.execute(
            "SELECT concept_id, session_id, observed_at FROM concept_occurrences"
            " WHERE derivation_version = ? ORDER BY concept_id, session_id",
            (DERIVATION_VERSION,),
        ).fetchall()
    )
    hashes["session_intent_outcome"] = _hash_rows(
        conn.execute("SELECT id, intent, outcome FROM sessions ORDER BY id").fetchall()
    )
    return hashes


def _hash_rows(rows: Sequence[sqlite3.Row]) -> str:
    hasher = hashlib.sha256()
    for row in rows:
        hasher.update(json.dumps(list(row), ensure_ascii=False, default=str).encode("utf-8"))
    return hasher.hexdigest()


def as_dict(exchange: DerivedExchange) -> dict[str, Any]:
    """Flags only, for fixtures and reports."""
    payload = dataclasses.asdict(exchange)
    payload.pop("events", None)
    payload["answer_event_ids"] = list(exchange.answer_event_ids)
    return payload
