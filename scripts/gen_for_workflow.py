"""Parameterised generation harness for the autonomous gen+judge workflow.

Drives the production write path (job.run_job) for ONE provider, generating
BOTH flashcards and quizzes for a course/section scope with a controllable
target card count and optional judge-feedback guidance injected into the
prompts. Emits a single JSON object on stdout describing what was written so
the orchestrating workflow can parse it.

Card count + guidance are injected by patching the prompt constants in each
generator module's namespace (the generators read them at call time). Safe
because StudyLoop generates one deck at a time (active_gen singleton) and this
process is single-threaded per provider.

Usage:
  uv run --project packages/studyloop python scripts/gen_for_workflow.py \
      --backend ollama --provider "" --model "gemma4:latest" \
      --publisher CodeWithMosh --course Complete_SQL_Mastery \
      --sections study-notes/getting-started-0025,study-notes/data-types-0035 \
      --target-count 5 --guidance "" --tag round1

Exit 0 always (even on per-task gen errors); the JSON `failed` count and
`errors` list carry the outcome so the workflow can decide retry vs reject.
Exit 2 only on a whole-job failure (scope miss, generator construction error).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from studyloop.content.generators import anthropic_compat, bedrock, ollama, openai_compat
from studyloop.content.job import JobRequest, run_job
from studyloop.content.scope import ScopeRequest
from studyloop.settings import load_settings

# Generator modules whose prompt globals we patch. Each binds the prompt
# constants at import; they read them at call time from their own namespace.
_PROMPT_MODULES = (ollama, bedrock, anthropic_compat, openai_compat)


def _count_line(kind: str, n: int) -> str:
    if kind == "flashcards":
        return (
            f"Produce exactly {n} cards per source chunk. Each must be distinct "
            f"and test a different concept -- no padding, no near-duplicates."
        )
    return (
        f"Produce exactly {n} questions per source chunk. Each must probe a "
        f"different concept -- no padding, no near-duplicates."
    )


def _patch_prompts(target_count: int, guidance: str) -> None:
    """Rewrite the system prompts in-place across all generator modules.

    Replaces the soft "Produce 6 to 12 / 4 to 8" line with a hard target, and
    appends judge guidance (if any) so the next round can act on prior feedback.
    """
    from studyloop.content.generators import prompts as _p

    fc = _p.FLASHCARD_SYSTEM_PROMPT
    qz = _p.QUIZ_SYSTEM_PROMPT

    # Drop the original soft-count sentences (kept generic so a prompt edit
    # upstream doesn't silently break this) and append the hard target.
    fc_new = fc.replace(
        "Produce 6 to 12 cards per source chunk. Fewer is acceptable if the source\n"
        "is short; more is acceptable if the source genuinely covers that many\n"
        "distinct ideas.",
        _count_line("flashcards", target_count),
    )
    qz_new = qz.replace(
        "Produce 4 to 8 questions per source chunk.",
        _count_line("quizzes", target_count),
    )
    if guidance.strip():
        suffix = (
            "\n\nA reviewer assessed a previous attempt and asked for these "
            f"improvements -- apply them:\n{guidance.strip()}\n"
        )
        fc_new += suffix
        qz_new += suffix

    for mod in _PROMPT_MODULES:
        if hasattr(mod, "FLASHCARD_SYSTEM_PROMPT"):
            mod.FLASHCARD_SYSTEM_PROMPT = fc_new
        if hasattr(mod, "QUIZ_SYSTEM_PROMPT"):
            mod.QUIZ_SYSTEM_PROMPT = qz_new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--provider", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--publisher", required=True)
    ap.add_argument("--course", required=True, help="SOURCE course (where study-notes live)")
    ap.add_argument(
        "--output-course",
        default="",
        help="OUTPUT course dir for the decks (defaults to --course). Use a "
        "per-provider name to isolate concurrent providers' decks.",
    )
    ap.add_argument("--sections", required=True, help="comma-separated section slugs")
    ap.add_argument("--target-count", type=int, default=5)
    ap.add_argument("--guidance", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument(
        "--max-retries",
        type=int,
        default=-1,
        help="Override generator max_retries. Flaky providers (MiniMax) benefit "
        "from a higher budget so consecutive bad emissions don't exhaust it. "
        "-1 = use the settings default.",
    )
    args = ap.parse_args()

    _patch_prompts(args.target_count, args.guidance)

    settings = load_settings()
    cg = settings.card_generator
    overrides: dict = {"backend": args.backend}
    if args.max_retries >= 0:
        overrides["max_retries"] = args.max_retries
    if args.backend == "ollama":
        overrides["ollama"] = replace(
            cg.ollama,
            model=args.model or cg.ollama.model,
            base_url=cg.ollama.base_url or "http://localhost:11434",
        )
    elif args.backend == "bedrock":
        overrides["bedrock"] = replace(cg.bedrock, model=args.model or cg.bedrock.model)
    cg = replace(cg, **overrides)
    if args.provider:
        cg = replace(cg, provider=args.provider)
    if args.model and args.backend not in ("ollama", "bedrock"):
        cg = replace(cg, model=args.model)
    settings = replace(settings, card_generator=cg)

    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    output_course = args.output_course or args.course
    all_outcomes: list[dict] = []
    job_error: str | None = None

    for section in sections:
        # ScopeRequest.course drives SOURCE resolution (study-notes); the
        # JobRequest.course drives the OUTPUT dir. Keeping them separate lets
        # each provider write to an isolated course dir while reading the same
        # real source material.
        req = JobRequest(
            course=output_course,
            publisher=args.publisher,
            scope=ScopeRequest(
                kind="section",
                course=args.course,
                publisher=args.publisher,
                section=section,
            ),
            kinds=("flashcards", "quizzes"),
            on_existing="overwrite",
            backend=args.backend,
            provider=args.provider,
            model=args.model,
        )
        try:
            result = run_job(f"wf-{args.tag}-{section}", req, settings, on_event=None)
        except Exception as exc:  # whole-job failure captured for workflow
            job_error = f"{type(exc).__name__}: {exc}"
            break
        for o in result.outcomes:
            all_outcomes.append(
                {
                    "section": section,
                    "kind": o.kind,
                    "ok": o.ok,
                    "path": o.path,
                    "error": o.error,
                    "elapsed_s": round(o.elapsed_s, 1),
                }
            )

    written = sum(1 for o in all_outcomes if o["ok"])
    failed = sum(1 for o in all_outcomes if not o["ok"])
    # Count cards actually written so the workflow can assert >=5/source.
    card_counts: list[dict] = []
    for o in all_outcomes:
        if o["ok"] and o["path"]:
            try:
                with open(o["path"]) as fh:
                    data = json.load(fh)
                n = len(data.get("cards", data.get("questions", [])))
            except Exception:  # count is best-effort; -1 signals unreadable
                n = -1
            card_counts.append({"path": o["path"], "kind": o["kind"], "count": n})

    out = {
        "backend": args.backend,
        "provider": args.provider,
        "model": args.model,
        "tag": args.tag,
        "output_course": output_course,
        "publisher": args.publisher,
        "written": written,
        "failed": failed,
        "job_error": job_error,
        "outcomes": all_outcomes,
        "card_counts": card_counts,
    }
    print("WF_RESULT_JSON:" + json.dumps(out))
    # Whole-job failure (cred/scope) → exit 2 so the workflow's ERROR path fires.
    return 2 if job_error else 0


if __name__ == "__main__":
    sys.exit(main())
