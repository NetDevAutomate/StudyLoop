"""Quality-eval harness for the LLM struggle extractor (P4 baseline + P6 loop).

Loads the frozen golden labels + train/held-out split, runs the extractor on
the chosen split's sessions (reading transcripts from the live sessions.db,
read-only), and computes pure-Python metrics against the human labels:

- Topic Jaccard: |pred ∩ exp| / |pred ∪ exp| on normalised (topic, concept) keys
- Confidence precision: of predicted struggling pairs, fraction that match a
  human struggling label
- Confidence recall: of human struggling pairs, fraction predicted
- False-positive rate on negatives: rows produced for is_negative sessions
  (MUST be 0 — non-negotiable gate)

Appends one row per run to results.tsv (the experiment ledger).  The score
functions are the FIXED boundary the P6 hill-climber may not mutate.

This module makes LIVE Bedrock calls. It NEVER writes to study_progress — the
extractor output is scored in memory only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studyloop.extractors import ExtractorResult
from studyloop.extractors.llm import (
    DEFAULT_MODEL,
    INITIAL_PROMPT,
    extract_struggles,
)
from studyloop.extractors.pipeline import pre_filter

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
_GOLDEN_PATH = _FIXTURES / "eval_golden.json"
_SPLIT_PATH = _FIXTURES / "eval_split.json"
_RESULTS_PATH = Path(__file__).resolve().parent / "results.tsv"

# Sonnet 4.6 Bedrock pricing (USD per token). Update if the rate card moves.
_PRICE_IN = 3.0 / 1_000_000
_PRICE_OUT = 15.0 / 1_000_000


def _norm(topic: str, concept: str) -> tuple[str, str]:
    """Canonical (topic, concept) key for set comparison."""
    return (topic.strip().lower(), concept.strip().lower())


@dataclass
class SessionScore:
    session_id: str
    is_negative: bool
    jaccard: float
    tp: int  # predicted struggling that matched a human struggling pair
    fp: int  # predicted struggling not in human struggling pairs
    fn: int  # human struggling pairs not predicted
    fp_on_negative: int  # any row produced for a negative session


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fetch_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY seq",
        (session_id,),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _session_source(conn: sqlite3.Connection, session_id: str) -> str | None:
    row = conn.execute(
        "SELECT source FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return row["source"] if row else None


def _expected_keys(entry: dict[str, Any]) -> set[tuple[str, str]]:
    return {_norm(t["topic"], t["concept"]) for t in entry.get("expected_topics", [])}


def _expected_struggling(entry: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        _norm(t["topic"], t["concept"])
        for t in entry.get("expected_topics", [])
        if t.get("confidence") == "struggling"
    }


def _predicted_keys(results: Iterable[ExtractorResult]) -> set[tuple[str, str]]:
    return {_norm(r.topic, r.concept) for r in results}


def _predicted_struggling(results: Iterable[ExtractorResult]) -> set[tuple[str, str]]:
    return {_norm(r.topic, r.concept) for r in results if r.confidence == "struggling"}


def score_session(
    entry: dict[str, Any], results: list[ExtractorResult]
) -> SessionScore:
    """Score one session's extractor output against its golden entry (pure Python)."""
    is_neg = entry.get("is_negative", False)
    if is_neg:
        return SessionScore(
            session_id=entry["session_id"],
            is_negative=True,
            jaccard=1.0 if not results else 0.0,
            tp=0,
            fp=0,
            fn=0,
            fp_on_negative=len(results),
        )

    exp_all = _expected_keys(entry)
    pred_all = _predicted_keys(results)
    inter = exp_all & pred_all
    union = exp_all | pred_all
    jaccard = len(inter) / len(union) if union else 1.0

    exp_str = _expected_struggling(entry)
    pred_str = _predicted_struggling(results)
    tp = len(exp_str & pred_str)
    fp = len(pred_str - exp_str)
    fn = len(exp_str - pred_str)
    return SessionScore(
        session_id=entry["session_id"],
        is_negative=False,
        jaccard=jaccard,
        tp=tp,
        fp=fp,
        fn=fn,
        fp_on_negative=0,
    )


def aggregate(scores: list[SessionScore]) -> dict[str, float]:
    """Roll session scores into the gate metrics."""
    studies = [s for s in scores if not s.is_negative]
    mean_jaccard = sum(s.jaccard for s in studies) / len(studies) if studies else 0.0
    tp = sum(s.tp for s in scores)
    fp = sum(s.fp for s in scores)
    fn = sum(s.fn for s in scores)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fp_on_neg = sum(s.fp_on_negative for s in scores)
    return {
        "mean_jaccard": round(mean_jaccard, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate_on_negatives": fp_on_neg,
    }


def run_eval(
    split: str,
    *,
    db_path: Path,
    prompt_template: str = INITIAL_PROMPT,
    model: str = DEFAULT_MODEL,
    client: Any | None = None,
) -> tuple[dict[str, float], float, list[SessionScore]]:
    """Run the extractor over the chosen split; return (metrics, cost_usd, scores)."""
    golden = {e["session_id"]: e for e in _load(_GOLDEN_PATH)}
    split_cfg = _load(_SPLIT_PATH)
    session_ids = split_cfg[split]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    scores: list[SessionScore] = []
    cost = 0.0
    try:
        for sid in session_ids:
            entry = golden.get(sid)
            if entry is None:
                continue
            messages = _fetch_messages(conn, sid)
            source = _session_source(conn, sid)
            # Mirror production exactly: the real pipeline only extracts from
            # sessions that pass pre_filter (kiro_cli source + <50% tool-noise).
            # Sessions the pipeline would skip produce zero rows here too — and
            # skip the API call (a cost saving), so the eval measures the
            # SYSTEM that ships, not the raw prompt on inputs it never sees.
            if pre_filter(sid, source, messages):
                results = extract_struggles(
                    messages, sid, client=client, model=model, prompt_template=prompt_template
                )
                usage = getattr(extract_struggles, "last_usage", {}) or {}
                cost += usage.get("inputTokens", 0) * _PRICE_IN
                cost += usage.get("outputTokens", 0) * _PRICE_OUT
            else:
                results = []
            scores.append(score_session(entry, results))
    finally:
        conn.close()

    return aggregate(scores), round(cost, 6), scores


def append_results_row(
    *,
    prompt_template: str,
    metrics: dict[str, float],
    cost_usd: float,
    status: str,
    mutation_description: str,
    f1_held_out: str = "",
) -> None:
    """Append one TSV row to the experiment ledger (creates header if new)."""
    header = (
        "prompt_hash\tf1_train\tprecision_train\trecall_train\tjaccard_train"
        "\tf1_held_out\tfp_on_negatives\tcost_usd\tstatus\tmutation_description"
    )
    prompt_hash = hashlib.sha256(prompt_template.encode()).hexdigest()[:8]
    row = "\t".join(
        [
            prompt_hash,
            str(metrics["f1"]),
            str(metrics["precision"]),
            str(metrics["recall"]),
            str(metrics["mean_jaccard"]),
            str(f1_held_out),
            str(metrics["false_positive_rate_on_negatives"]),
            str(cost_usd),
            status,
            mutation_description,
        ]
    )
    new_file = not _RESULTS_PATH.exists()
    with open(_RESULTS_PATH, "a", encoding="utf-8") as f:
        if new_file:
            f.write(header + "\n")
        f.write(row + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Struggle-extractor quality eval.")
    ap.add_argument("--split", choices=["train", "held_out"], default="train")
    ap.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".config" / "studyloop" / "sessions.db",
        help="Path to sessions.db (read-only).",
    )
    ap.add_argument("--status", default="baseline", help="Ledger status label.")
    ap.add_argument("--note", default="initial", help="Mutation description for the ledger.")
    args = ap.parse_args()

    metrics, cost, scores = run_eval(args.split, db_path=args.db)
    append_results_row(
        prompt_template=INITIAL_PROMPT,
        metrics=metrics,
        cost_usd=cost,
        status=args.status,
        mutation_description=args.note,
    )
    print(f"split={args.split}  metrics={json.dumps(metrics)}  cost_usd=${cost:.4f}")
    for s in scores:
        kind = "NEG" if s.is_negative else "   "
        print(
            f"  {kind} {s.session_id[:40]:40} "
            f"jaccard={s.jaccard:.2f} tp={s.tp} fp={s.fp} fn={s.fn} fp_neg={s.fp_on_negative}"
        )


if __name__ == "__main__":
    main()
