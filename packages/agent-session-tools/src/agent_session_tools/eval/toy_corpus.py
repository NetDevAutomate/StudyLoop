"""A planted toy corpus: public data on which both rulers compute real numbers.

The live corpus is the learner's private history and never leaves the
machine, so CI needs a stand-in whose answers are known by construction.
:func:`build_toy_corpus` writes a small ``sessions.db`` through the package's
own schema and migrations (never hand-written DDL), plus a gold set in the
exact shape of ``gold-v2-dev.json``:

* **K** (keyword) questions reuse the session's own content words -- any
  working lexical arm must find them;
* **P** (paraphrase) questions share *no* content word with their session --
  the gap a lexical arm cannot close and the semantic arm exists for;
* **R** (relational) questions name a detail from the assistant's answer;
* three questions carry the raw-pass-through crash triggers (the words
  ``and``/``or`` beside a backtick, a ``?``, a comma) so the crash census
  has something to count until Stage 2 removes the defect.

For the census, two sessions share one identical learner turn (a winnable
twin pair) and six sessions share a boilerplate turn (unwinnable at K=5).
Everything is deterministic: the same call always writes the same bytes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_session_tools.migrations import migrate

_SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"

#: (session id, learner turn, assistant answer, paraphrase question, relational question)
_TOPICS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "toy-01",
        "Why does the tmux socket refuse connections after the laptop sleeps?",
        "The multiplexer server dies on suspend; recreate the socket directory and restart the "
        "server with a fresh session name.",
        "Which conversation covered the terminal multiplexer losing its link when the machine "
        "napped?",
        "Where was recreating the socket directory after suspend recommended?",
    ),
    (
        "toy-02",
        "How do I make pytest fixtures share one database across a module?",
        "Give the fixture module scope and yield the connection; tear it down once at the end.",
        "Find the chat about reusing a single test datastore for a whole file of checks.",
        "Which session said to yield the connection from a module-scoped fixture?",
    ),
    (
        "toy-03",
        "What is the difference between a decorator and a context manager in Python?",
        "A decorator wraps a callable at definition time; a context manager brackets a block "
        "with enter and exit.",
        "Where did we compare wrapping a function versus bracketing a code block?",
        "Which session described enter and exit bracketing a block?",
    ),
    (
        "toy-04",
        "My Spark job spills to disk during the shuffle stage, how do I tune it?",
        "Raise the shuffle partitions and give the executors more memory overhead.",
        "Show me the discussion about the distributed engine writing temporary data mid-exchange.",
        "Which session recommended raising executor memory overhead?",
    ),
    (
        "toy-05",
        "How should I structure an Airflow DAG so tasks retry independently?",
        "Set retries on each operator and keep tasks idempotent so a rerun is safe.",
        "Find the talk about scheduling pipeline steps that recover one at a time.",
        "Where was keeping operators idempotent for safe reruns advised?",
    ),
    (
        "toy-06",
        "Why is my SQL window function slower than the GROUP BY version?",
        "The frame spec forces a sort per partition; add an index on the partition key.",
        "Which conversation explained an analytic ranking query dragging behind aggregation?",
        "Which session suggested indexing the partition key for the frame spec?",
    ),
    (
        "toy-07",
        "What does the `session_search` planner do with the FTS index and stop words?",
        "It quotes each surviving token, drops stop words, and widens AND to OR when nothing "
        "matches.",
        "Where did we cover how the lookup tool trims filler terms before querying the text "
        "catalogue?",
        "Which session said AND widens to OR when nothing matches?",
    ),
    (
        "toy-08",
        "Should I use dbt or plain SQL scripts for the transformation layer?",
        "Use dbt for lineage and tests; plain scripts only for one-off backfills.",
        "Find the session weighing a modelling framework against handwritten queries for "
        "reshaping data.",
        "Which session reserved plain scripts for one-off backfills?",
    ),
    (
        "toy-09",
        "How do Redshift sort keys and distribution styles interact for joins?",
        "Co-locate the join key with KEY distribution and sort on the filter column.",
        "Which chat discussed how a warehouse spreads rows across nodes to speed up matching?",
        "Where was co-locating the join key with KEY distribution explained?",
    ),
    (
        "toy-10",
        "Explain Python dataclasses versus attrs versus pydantic for config objects.",
        "Dataclasses for plain records, attrs for validators without a dependency on pydantic, "
        "pydantic when parsing untrusted input.",
        "Find where we compared record-holding class helpers for settings structures.",
        "Which session recommended pydantic for parsing untrusted input?",
    ),
    (
        "toy-11",
        "please review the repo and fix the lint errors",
        "The ruff run flagged unused imports in the exporter module; removed them.",
        "Where did the style checker complain about imports nobody used?",
        "Which session removed unused imports from the exporter module?",
    ),
    (
        "toy-12",
        "please review the repo and fix the lint errors",
        "The formatter rewrapped the census docstrings; nothing else changed.",
        "Where did the code formatter reflow documentation strings?",
        "Which session said only the census docstrings were rewrapped?",
    ),
)

#: A boilerplate learner turn planted in six sessions: unwinnable at K=5.
BOILERPLATE = "Please continue with the next task in the plan"
BOILERPLATE_SESSIONS = ("toy-01", "toy-02", "toy-03", "toy-04", "toy-05", "toy-06")

#: Questions carrying the raw-pass-through crash triggers of the Stage 1 shipped code (the frozen control).
CRASH_QUESTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "C-1",
        "toy-07",
        "What did the `session_search` planner and the FTS index do with stop words?",
    ),
    ("C-2", "toy-08", "Did we pick dbt or plain SQL scripts for transformations?"),
    (
        "C-3",
        "toy-09",
        "Redshift sort keys, distribution styles and joins: how do they interact?",
    ),
)


@dataclass(frozen=True, slots=True)
class ToyCorpus:
    db_path: Path
    gold_path: Path
    #: Gold item ids whose question crashed the Stage 1 shipped code (the frozen control still does).
    crash_ids: tuple[str, ...]
    #: Session ids sharing the winnable twin turn and the unwinnable boilerplate.
    twin_sessions: tuple[str, ...]
    boilerplate_sessions: tuple[str, ...]


def _gold_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for n, (sid, keyword_q, _answer, paraphrase_q, relational_q) in enumerate(
        _TOPICS, start=1
    ):
        cluster = f"toy-cluster-{n:02d}"
        items.append(
            {
                "id": f"K-{n:02d}",
                "question": keyword_q,
                "stratum": "K",
                "cluster": cluster,
                "gold_session_ids": [sid],
                "expected_answer": "",
                "evidence": [],
                "admitted_by": "planted",
            }
        )
        items.append(
            {
                "id": f"P-{n:02d}",
                "question": paraphrase_q,
                "stratum": "P",
                "cluster": cluster,
                "gold_session_ids": [sid],
                "expected_answer": "",
                "evidence": [],
                "admitted_by": "planted",
            }
        )
        items.append(
            {
                "id": f"R-{n:02d}",
                "question": relational_q,
                "stratum": "R",
                "cluster": cluster,
                "gold_session_ids": [sid],
                "expected_answer": "",
                "evidence": [],
                "admitted_by": "planted",
            }
        )
    for item_id, sid, question in CRASH_QUESTIONS:
        items.append(
            {
                "id": item_id,
                "question": question,
                "stratum": "K",
                "cluster": f"toy-cluster-{sid[-2:]}",
                "gold_session_ids": [sid],
                "expected_answer": "",
                "evidence": [],
                "admitted_by": "planted-crash",
            }
        )
    return items


def build_toy_corpus(directory: Path | str) -> ToyCorpus:
    """Write ``sessions.db`` and ``gold.json`` under ``directory`` and describe them."""
    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "sessions.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        migrate(conn)
        for n, (sid, learner, answer, _p, _r) in enumerate(_TOPICS, start=1):
            conn.execute(
                "INSERT INTO sessions (id, source, project_path, git_branch, created_at, "
                "updated_at, session_type) VALUES (?,?,?,?,?,?,?)",
                (
                    sid,
                    "claude_code" if n % 2 else "kiro_cli",
                    f"/projects/{sid}",
                    "main",
                    f"2026-02-{n:02d}T10:00:00",
                    f"2026-02-{n:02d}T11:00:00",
                    "work",
                ),
            )
            turns = [("user", learner), ("assistant", answer)]
            if sid in BOILERPLATE_SESSIONS:
                turns.append(("user", BOILERPLATE))
                turns.append(("assistant", "Continuing with the next task now."))
            for seq, (role, content) in enumerate(turns, start=1):
                conn.execute(
                    "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        f"{sid}-m{seq}",
                        sid,
                        role,
                        content,
                        f"2026-02-{n:02d}T10:{seq:02d}:00",
                        seq,
                    ),
                )
        conn.commit()
    finally:
        conn.close()
    gold_path = root / "gold.json"
    gold = {
        "gold_version": "toy-v1",
        "set": "TOY",
        "created_utc": "2026-09-11T00:00:00+00:00",
        "split_rule": "planted",
        "split_seed": 0,
        "corpus_digest": "toy",
        "items": _gold_items(),
    }
    gold_path.write_text(
        json.dumps(gold, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return ToyCorpus(
        db_path=db_path,
        gold_path=gold_path,
        crash_ids=tuple(item_id for item_id, _sid, _q in CRASH_QUESTIONS),
        twin_sessions=("toy-11", "toy-12"),
        boilerplate_sessions=BOILERPLATE_SESSIONS,
    )


__all__ = [
    "BOILERPLATE",
    "BOILERPLATE_SESSIONS",
    "CRASH_QUESTIONS",
    "ToyCorpus",
    "build_toy_corpus",
]
