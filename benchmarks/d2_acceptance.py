"""D2 acceptance + benchmark harness.

Generates flashcards (and a quiz for one note) for 3 AWS DE study-notes
against the configured Ollama, times each call, and writes the decks to
``benchmarks/d2-output/<model>/`` for manual quality rating.

Run with:

    uv run python benchmarks/d2_acceptance.py --model qwen2.5:7b
    uv run python benchmarks/d2_acceptance.py --model qwen2.5:14b

Results append to ``benchmarks/d2-ollama.md``.

Not a pytest test -- this is an interactive acceptance driver that
writes real files. Keeping it separate from the CI suite.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

# Add the src path so this runs without install.
PKG_ROOT = Path(__file__).resolve().parent.parent / "packages" / "studyloop"
sys.path.insert(0, str(PKG_ROOT / "src"))

from studyloop.content.generators import CardGenerationError, get_generator  # noqa: E402
from studyloop.content.generators.runner import (  # noqa: E402
    GenerationTask,
    generate_concurrently,
)
from studyloop.settings import (  # noqa: E402
    BedrockBackendConfig,
    CardGeneratorConfig,
    OllamaBackendConfig,
)

# Study-notes directory on local MacBook. Long slug trips detect-secrets'
# base64 entropy heuristic; not a secret.
_OBSIDIAN_BASE = "/Users/user/Obsidian/Personal/2-Areas/Study/Courses/Udemy"
_COURSE_SLUG = (
    "Ultimate_AWS_Data_Engineering_Bootcamp_with_Real_World_Labs"  # pragma: allowlist secret
)
STUDY_NOTES_DIR = Path(_OBSIDIAN_BASE) / _COURSE_SLUG / "study-notes"
NOTES = [
    "section-2-lab-batch-data-processing-of-music-streams-using-airflow-redshift.md",
    "section-4-lab-etl-for-rental-apartments-using-step-functionsaws-glue-and-redshift.md",
    "section-7-lab-build-a-lakehouse-for-an-e-commerce-store-using-pyspark-delta-tables-and-s3.md",
]

OUTPUT_ROOT = Path(__file__).resolve().parent / "d2-output"
BENCHMARK_MD = Path(__file__).resolve().parent / "d2-ollama.md"


def _peak_rss_mb() -> float:
    """Peak RSS of this process in MB (macOS reports in bytes)."""
    # ru_maxrss is bytes on macOS, kilobytes on Linux.
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def _slug_from_filename(name: str) -> str:
    return name.removesuffix(".md")


def _title_from_filename(name: str) -> str:
    """Turn 'section-2-lab-batch-data-...md' into 'Section 2: Batch data...'."""
    slug = _slug_from_filename(name)
    parts = slug.split("-")
    if len(parts) >= 2 and parts[0] == "section" and parts[1].isdigit():
        prefix = f"Section {parts[1]}"
        rest = " ".join(parts[2:]).replace("  ", " ").strip()
        return f"{prefix}: {rest}".title()
    return slug.replace("-", " ").title()


def run_for_model(
    model: str,
    *,
    run_quiz_on_first: bool = True,
    parallel: bool = False,
    max_workers: int = 4,
) -> None:
    if model.startswith("bedrock:"):
        backend = "bedrock"
        bedrock_model = model.removeprefix("bedrock:")
        cfg = CardGeneratorConfig(
            backend=backend,
            temperature=0.1,
            max_retries=2,
            request_timeout=600.0,
            bedrock=BedrockBackendConfig(
                model=bedrock_model,
                region="us-east-1",
                profile="bedrock-prod",
                profile_fallback="bedrock-local",
            ),
        )
        out_label = bedrock_model.replace(":", "_").replace(".", "_").replace("/", "_")
    else:
        backend = "ollama"
        cfg = CardGeneratorConfig(
            backend=backend,
            temperature=0.1,
            max_retries=2,
            request_timeout=600.0,  # 14b can be slow on cold start
            ollama=OllamaBackendConfig(
                base_url="http://localhost:11434",
                model=model,
            ),
        )
        out_label = model.replace(":", "_")

    out_dir = OUTPUT_ROOT / out_label
    out_dir.mkdir(parents=True, exist_ok=True)

    per_note_stats: list[dict] = []

    gen = get_generator(cfg)
    overall_t0 = time.monotonic()
    try:
        if parallel:
            # Build all tasks up front (flashcards for every note + quiz on first).
            tasks: list[GenerationTask] = []
            task_slugs: dict[str, str] = {}  # identifier -> output slug
            for i, note_name in enumerate(NOTES):
                note_path = STUDY_NOTES_DIR / note_name
                source = note_path.read_text(encoding="utf-8")
                title = _title_from_filename(note_name)
                slug = _slug_from_filename(note_name)
                fc_id = f"fc:{slug}"
                tasks.append(
                    GenerationTask(
                        identifier=fc_id,
                        kind="flashcards",
                        source=source,
                        title=title,
                    )
                )
                task_slugs[fc_id] = slug
                if i == 0 and run_quiz_on_first:
                    qz_id = f"qz:{slug}"
                    tasks.append(
                        GenerationTask(
                            identifier=qz_id,
                            kind="quiz",
                            source=source,
                            title=title,
                        )
                    )
                    task_slugs[qz_id] = slug

            print(
                f"\n[{model}] Running {len(tasks)} tasks concurrently "
                f"(max_workers={max_workers})...",
                flush=True,
            )

            def _report(result):  # type: ignore[no-untyped-def]
                ident = result.task.identifier
                if result.ok:
                    if result.task.kind == "flashcards":
                        n = len(result.deck.cards)
                        print(
                            f"  [{ident}] {n} cards in {result.elapsed_s:.1f}s",
                            flush=True,
                        )
                    else:
                        n = len(result.deck.questions)
                        print(
                            f"  [{ident}] {n} questions in {result.elapsed_s:.1f}s",
                            flush=True,
                        )
                else:
                    print(
                        f"  [{ident}] FAILED in {result.elapsed_s:.1f}s: {result.error}",
                        flush=True,
                    )

            results = generate_concurrently(
                gen, tasks, max_workers=max_workers, on_complete=_report
            )

            for r in results:
                slug = task_slugs[r.task.identifier]
                if r.ok and r.deck is not None:
                    path = r.deck.write_json(out_dir, slug)
                    if r.task.kind == "flashcards":
                        per_note_stats.append(
                            {
                                "note": slug,
                                "kind": "flashcards",
                                "cards": len(r.deck.cards),  # type: ignore[union-attr]
                                "elapsed_s": round(r.elapsed_s, 2),
                            }
                        )
                    else:
                        per_note_stats.append(
                            {
                                "note": slug,
                                "kind": "quiz",
                                "questions": len(r.deck.questions),  # type: ignore[union-attr]
                                "elapsed_s": round(r.elapsed_s, 2),
                            }
                        )
                else:
                    per_note_stats.append(
                        {
                            "note": slug,
                            "kind": r.task.kind,
                            "error": str(r.error),
                            "elapsed_s": round(r.elapsed_s, 2),
                        }
                    )
        else:
            for i, note_name in enumerate(NOTES):
                note_path = STUDY_NOTES_DIR / note_name
                source = note_path.read_text(encoding="utf-8")
                title = _title_from_filename(note_name)
                slug = _slug_from_filename(note_name)

                print(
                    f"\n[{model}] Generating flashcards for {title} ({len(source)} chars)...",
                    flush=True,
                )
                t0 = time.monotonic()
                try:
                    deck = gen.generate_flashcards(source=source, title=title)
                    elapsed = time.monotonic() - t0
                    path = deck.write_json(out_dir, slug)
                    n_cards = len(deck.cards)
                    cards_per_min = (n_cards / elapsed) * 60 if elapsed else 0
                    print(
                        f"  -> {n_cards} cards in {elapsed:.1f}s "
                        f"({cards_per_min:.1f} cards/min) -> {path.name}"
                    )
                    per_note_stats.append(
                        {
                            "note": slug,
                            "kind": "flashcards",
                            "cards": n_cards,
                            "elapsed_s": round(elapsed, 2),
                            "cards_per_min": round(cards_per_min, 2),
                        }
                    )
                except CardGenerationError as exc:
                    elapsed = time.monotonic() - t0
                    print(f"  !! FAILED after {elapsed:.1f}s: {exc}", flush=True)
                    per_note_stats.append(
                        {
                            "note": slug,
                            "kind": "flashcards",
                            "error": str(exc),
                            "elapsed_s": round(elapsed, 2),
                        }
                    )

                if i == 0 and run_quiz_on_first:
                    print(f"[{model}] Generating quiz for {title}...")
                    t0 = time.monotonic()
                    try:
                        quiz = gen.generate_quiz(source=source, title=title)
                        elapsed = time.monotonic() - t0
                        path = quiz.write_json(out_dir, slug)
                        n_q = len(quiz.questions)
                        print(f"  -> {n_q} questions in {elapsed:.1f}s -> {path.name}", flush=True)
                        per_note_stats.append(
                            {
                                "note": slug,
                                "kind": "quiz",
                                "questions": n_q,
                                "elapsed_s": round(elapsed, 2),
                            }
                        )
                    except CardGenerationError as exc:
                        elapsed = time.monotonic() - t0
                        print(f"  !! quiz FAILED after {elapsed:.1f}s: {exc}", flush=True)
                        per_note_stats.append(
                            {
                                "note": slug,
                                "kind": "quiz",
                                "error": str(exc),
                                "elapsed_s": round(elapsed, 2),
                            }
                        )
    finally:
        gen.close()

    total_elapsed = time.monotonic() - overall_t0
    per_note_stats.append({"total_elapsed_s": round(total_elapsed, 2)})
    peak_rss = _peak_rss_mb()
    summary_path = out_dir / "_summary.json"
    summary_path.write_text(
        json.dumps(
            {"model": model, "peak_rss_mb_python": round(peak_rss, 1), "stats": per_note_stats},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSummary -> {summary_path}")
    print(f"Peak Python RSS: {peak_rss:.1f} MB (Ollama server RAM separate -- use `ollama ps`)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "Either an Ollama model tag (e.g. qwen2.5:7b, qwen2.5:14b) or "
            "a Bedrock model prefixed with 'bedrock:' "
            "(e.g. bedrock:us.anthropic.claude-sonnet-4-6)"
        ),
    )
    parser.add_argument(
        "--skip-quiz",
        action="store_true",
        help="Skip the quiz generation (flashcards only)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run tasks concurrently via the runner (faster for Bedrock)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Thread-pool size when --parallel is set (default 4)",
    )
    args = parser.parse_args()
    run_for_model(
        args.model,
        run_quiz_on_first=not args.skip_quiz,
        parallel=args.parallel,
        max_workers=args.max_workers,
    )


if __name__ == "__main__":
    main()
