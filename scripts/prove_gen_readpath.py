"""STEP-1 proof: generate a real deck and confirm the panels' read path finds it.

Drives the EXACT production write path (job.run_job -> _course_output_dir ->
storage.get_course_dir) with the locally-proven Ollama backend, then exercises
the EXACT read path (settings.resolve_study_dirs -> review_loader.discover_directories
-> services.review.get_cards) the Quiz/Flashcard panels use.

Run: uv run --project packages/studyloop python scripts/prove_gen_readpath.py
Exit 0 = write root and read root reconciled and decks are discoverable.
"""

from __future__ import annotations

import sys
from dataclasses import replace

from studyloop.content.job import JobRequest, run_job
from studyloop.content.scope import ScopeRequest
from studyloop.review_loader import discover_directories, find_content_dirs
from studyloop.services.review import get_cards
from studyloop.settings import load_settings, resolve_study_dirs

PUBLISHER = "CodeWithMosh"
COURSE = "Complete_SQL_Mastery"
SECTION = "study-notes/getting-started-0025"  # one lesson file, suffix stripped


def main() -> int:
    settings = load_settings()
    # Force Ollama gemma4:latest (installed + passes quality bar on this box).
    cg = settings.card_generator
    cg = replace(
        cg,
        backend="ollama",
        ollama=replace(cg.ollama, model="gemma4:latest", base_url="http://localhost:11434"),
    )
    settings = replace(settings, card_generator=cg)

    req = JobRequest(
        course=COURSE,
        publisher=PUBLISHER,
        scope=ScopeRequest(kind="section", course=COURSE, publisher=PUBLISHER, section=SECTION),
        kinds=("flashcards", "quizzes"),
        on_existing="overwrite",
        backend="ollama",
    )

    events: list[dict] = []
    print(f"[gen] {PUBLISHER}/{COURSE}::{SECTION} via ollama:gemma4:latest ...", flush=True)
    result = run_job("prove-readpath", req, settings, on_event=events.append)
    print(f"[gen] written={result.written} failed={result.failed}", flush=True)
    for o in result.outcomes:
        status = "OK " if o.ok else "ERR"
        print(f"      {status} {o.kind:10} -> {o.path or o.error}", flush=True)

    if result.failed or result.written == 0:
        print("[FAIL] generation produced errors / no files", flush=True)
        return 1

    # ---- READ PATH (exactly what the panels do) -------------------------
    study_dirs = resolve_study_dirs()
    print(f"\n[read] resolve_study_dirs() -> {study_dirs}", flush=True)
    courses = discover_directories(study_dirs)
    names = {n for n, _ in courses}
    print(
        f"[read] discover_directories found {len(courses)} courses; "
        f"{COURSE} present: {COURSE in names}",
        flush=True,
    )

    match = next((p for n, p in courses if n == COURSE), None)
    if match is None:
        print(f"[FAIL] read path did NOT discover {COURSE}", flush=True)
        return 1

    fc_dir, quiz_dir = find_content_dirs(match)
    flashcards, quizzes = get_cards(COURSE, match)
    print(f"[read] course path: {match}", flush=True)
    print(f"[read] fc_dir={fc_dir} quiz_dir={quiz_dir}", flush=True)
    print(f"[read] loaded {len(flashcards)} flashcards, {len(quizzes)} quiz questions", flush=True)

    if not flashcards or not quizzes:
        print("[FAIL] panels would load empty content", flush=True)
        return 1

    print(
        "\n[PASS] write root and read root reconciled; decks discoverable + loadable.", flush=True
    )
    print(f"       sample flashcard front: {flashcards[0].front[:80]!r}", flush=True)
    print(f"       sample quiz question:   {quizzes[0].question[:80]!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
