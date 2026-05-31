"""autoagent-derivative hill-climber — improve the extractor prompt to thresholds.

~200 lines of pure Python pattern-matching autoagent's architecture at the
concept level (NOT importing it).  Iteratively mutates the extractor's system
prompt to raise F1 on the train split, with hard safety rails.

EDITABLE SURFACE (what the loop mutates):
- the EXTRACTOR_PROMPT string (the system prompt sent to the extractor)

FIXED BOUNDARY (the loop must never mutate):
- eval_runner.run_eval / score functions (the scorer)
- record_progress / study_progress (NEVER written during the loop)
- eval_golden.json + eval_split.json (frozen ground truth)

SAFETY RAILS (all enforced here):
- baseline-first: score the initial prompt before any mutation
- budget checked BEFORE every iteration (hard stop) + MAX_ITERATIONS
- temperature=0 on the extractor (deterministic, verified live); 0.7 on the
  meta-agent (diverse mutations)
- per-session error isolation lives in run_eval, so one crash can't kill the loop
- NEVER writes study_progress; eval scores in memory against frozen labels
- on any stop reason, writes extractor_candidate.py with the best prompt

Run:
    AWS_PROFILE=... uv run --with boto3 python -m studyloop.extractors.improve_extractor \\
        --budget-usd 2.0 --max-iterations 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from studyloop.extractors.eval_runner import (
    _GOLDEN_PATH,
    _PRICE_IN,
    _PRICE_OUT,
    SessionScore,
    append_results_row,
    run_eval,
)
from studyloop.extractors.llm import DEFAULT_MODEL, DEFAULT_REGION, INITIAL_PROMPT

_CANDIDATE_PATH = Path(__file__).resolve().parent / "extractor_candidate.py"
_META_MODEL = DEFAULT_MODEL  # sonnet for mutation quality (this run, per user)
_META_TEMPERATURE = 0.7

_META_SYSTEM = """\
You improve the SYSTEM PROMPT of an LLM that extracts learning 'struggles' from \
study-session transcripts. You are given the current prompt, its F1 score, and \
concrete failure examples: struggles it MISSED (false negatives) and non-struggles \
it HALLUCINATED (false positives).

Rewrite the prompt to fix those specific failure modes. Keep it focused. The \
prompt MUST keep the literal token {vocab} exactly once (it is substituted with \
the canonical vocabulary at runtime) and MUST instruct the model to call the \
emit_struggle_extractions tool once. Prefer the SHORTER prompt when quality is \
equal.

Return ONLY the new prompt text between <prompt> and </prompt> tags, nothing else."""


def _build_client(profile: str, region: str = DEFAULT_REGION) -> Any:
    import boto3

    return boto3.Session(profile_name=profile).client("bedrock-runtime", region_name=region)


def _format_failures(scores: list[SessionScore], limit: int = 5) -> str:
    """Render up to `limit` FN and FP pairs across sessions for the meta-agent."""
    fns: list[str] = []
    fps: list[str] = []
    for s in scores:
        for t, c in s.fn_pairs:
            fns.append(f"  - {t}/{c}  (session {s.session_id[:24]})")
        for t, c in s.fp_pairs:
            fps.append(f"  - {t}/{c}  (session {s.session_id[:24]})")
    errs = [f"  - {s.session_id[:24]}: {s.error}" for s in scores if s.error]
    parts = []
    parts.append("MISSED struggles (false negatives — the prompt should have caught these):")
    parts.append("\n".join(fns[:limit]) or "  (none)")
    parts.append("\nHALLUCINATED struggles (false positives — the prompt over-flagged these):")
    parts.append("\n".join(fps[:limit]) or "  (none)")
    if errs:
        parts.append("\nEXTRACTION ERRORS (the model crashed on these — keep output well-formed):")
        parts.append("\n".join(errs[:limit]))
    return "\n".join(parts)


def _mutate_prompt(
    client: Any, current_prompt: str, f1: float, failures: str
) -> tuple[str | None, float]:
    """Call the meta-agent to rewrite the prompt. Returns (new_prompt|None, cost)."""
    user = (
        f"Current F1 on the train split: {f1:.3f}\n\n"
        f"Current prompt:\n<prompt>\n{current_prompt}\n</prompt>\n\n"
        f"Failure analysis:\n{failures}\n\n"
        "Rewrite the prompt to fix these failures. Return only the new prompt "
        "between <prompt> and </prompt>."
    )
    resp = client.converse(
        modelId=_META_MODEL,
        system=[{"text": _META_SYSTEM}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"temperature": _META_TEMPERATURE, "maxTokens": 4096},
    )
    usage = resp.get("usage", {})
    cost = usage.get("inputTokens", 0) * _PRICE_IN + usage.get("outputTokens", 0) * _PRICE_OUT

    text = ""
    for block in resp.get("output", {}).get("message", {}).get("content", []):
        text += block.get("text", "")
    start, end = text.find("<prompt>"), text.find("</prompt>")
    if start == -1 or end == -1 or end <= start:
        return None, cost
    new_prompt = text[start + len("<prompt>") : end].strip()
    # Guard the loop's own contract: the {vocab} sentinel must survive.
    if "{vocab}" not in new_prompt or "emit_struggle_extractions" not in new_prompt:
        return None, cost
    return new_prompt, cost


def _write_candidate(prompt: str, metrics: dict[str, float]) -> None:
    """Persist the best prompt as an importable module."""
    content = (
        '"""Best extractor prompt found by the P6 hill-climber. Generated — do not hand-edit."""\n\n'
        f"# Train metrics at write time: {json.dumps(metrics)}\n\n"
        "EXTRACTOR_PROMPT = '''" + prompt.replace("'''", "\\'\\'\\'") + "'''\n"
    )
    _CANDIDATE_PATH.write_text(content, encoding="utf-8")


def hill_climb(
    *,
    db_path: Path,
    profile: str,
    budget_usd: float,
    max_iterations: int,
) -> dict[str, Any]:
    """Run the loop. Returns a summary dict. Writes extractor_candidate.py on exit."""
    client = _build_client(profile)
    cumulative_cost = 0.0

    # ── baseline-first ────────────────────────────────────────────────
    best_prompt = INITIAL_PROMPT
    metrics, cost, scores = run_eval("train", db_path=db_path, prompt_template=best_prompt, client=client)
    cumulative_cost += cost
    best_f1 = metrics["f1"]
    append_results_row(
        prompt_template=best_prompt, metrics=metrics, cost_usd=cost,
        status="baseline", mutation_description="hill-climb baseline",
    )
    print(f"[baseline] F1={best_f1:.3f} prec={metrics['precision']:.3f} "
          f"rec={metrics['recall']:.3f} fp_neg={metrics['false_positive_rate_on_negatives']} "
          f"cost=${cost:.4f} cum=${cumulative_cost:.4f}")

    best_metrics = metrics
    stop_reason = "max_iterations"

    for i in range(1, max_iterations + 1):
        # budget checked BEFORE the iteration's spend (hard stop)
        if cumulative_cost >= budget_usd:
            stop_reason = "budget_stop"
            break

        failures = _format_failures(scores)
        new_prompt, mut_cost = _mutate_prompt(client, best_prompt, best_f1, failures)
        cumulative_cost += mut_cost
        if new_prompt is None:
            print(f"[iter {i}] meta-agent produced no valid prompt; skipping")
            continue

        metrics, eval_cost, new_scores = run_eval(
            "train", db_path=db_path, prompt_template=new_prompt, client=client
        )
        cumulative_cost += eval_cost
        f1 = metrics["f1"]
        recall = metrics["recall"]
        best_recall = best_metrics["recall"]
        # Anti-Goodhart recall floor: never accept a prompt that improves F1 by
        # SUPPRESSING output (the failure mode of the first run — precision
        # climbed to 1.0 while recall stayed pinned). A candidate must not drop
        # recall by more than a small tolerance vs the current best.
        recall_ok = recall >= best_recall - 0.02
        f1_better = f1 > best_f1 or (
            abs(f1 - best_f1) < 1e-9 and len(new_prompt) < len(best_prompt)
        )
        improved = f1_better and recall_ok
        status = "keep" if improved else "discard"
        append_results_row(
            prompt_template=new_prompt, metrics=metrics,
            cost_usd=mut_cost + eval_cost, status=status,
            mutation_description=f"iter {i}: F1 {best_f1:.3f}->{f1:.3f}",
        )
        floor_note = "" if recall_ok else " [recall-floor blocked]"
        print(f"[iter {i}] F1={f1:.3f} ({status}{floor_note}) prec={metrics['precision']:.3f} "
              f"rec={metrics['recall']:.3f} fp_neg={metrics['false_positive_rate_on_negatives']} "
              f"cum=${cumulative_cost:.4f}")
        if improved:
            best_prompt, best_f1, best_metrics, scores = new_prompt, f1, metrics, new_scores

    _write_candidate(best_prompt, best_metrics)
    print(f"\n[stop: {stop_reason}] best F1={best_f1:.3f} cum_cost=${cumulative_cost:.4f}")
    print(f"wrote {_CANDIDATE_PATH}")
    return {
        "stop_reason": stop_reason,
        "best_f1": best_f1,
        "best_metrics": best_metrics,
        "cumulative_cost_usd": round(cumulative_cost, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Hill-climb the extractor prompt to thresholds.")
    ap.add_argument("--db", type=Path, default=Path.home() / ".config" / "studyloop" / "sessions.db")
    ap.add_argument("--profile", default="arraafat+prod-user")
    ap.add_argument("--budget-usd", type=float, default=2.0)
    ap.add_argument("--max-iterations", type=int, default=20)
    args = ap.parse_args()

    if not _GOLDEN_PATH.exists():
        raise SystemExit(f"golden labels missing at {_GOLDEN_PATH} — run P2 first.")

    summary = hill_climb(
        db_path=args.db,
        profile=args.profile,
        budget_usd=args.budget_usd,
        max_iterations=args.max_iterations,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
