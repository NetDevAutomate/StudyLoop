#!/usr/bin/env python3
"""Capture Web UI screenshots for the project website, from real seeded data.

Why a script and not a test: the output is a documentation artefact, not an
assertion. It is here rather than in the site repo because the only honest source
for a screenshot of StudyLoop is StudyLoop, running.

Why the e2e world and not a normal `studyloop web`: the developer's own server
reads the developer's own config, plans and session database, so its screenshots
would publish personal study history to a public website. ``build_test_world``
gives a complete, hermetic environment -- its own HOME, config, plans directory
and SQLite file -- and ``start_web_server`` refuses to start if any of those
still point at a real directory. The pictures are of real software with real
seeded content and nobody's private data.

Usage::

    env -u VIRTUAL_ENV uv run python scripts/capture-web-screenshots.py \\
        --out ~/code/personal/sites/StudyLoopSite/public/images

Each view is captured only if it renders something: a screenshot of an empty
panel tells a visitor the product is empty.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "packages" / "studyloop" / "tests"
for candidate in (str(TESTS), str(TESTS / "e2e")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

PORT = 8794
VIEWPORT = {"width": 1440, "height": 900}


@dataclass(frozen=True)
class Shot:
    """One screenshot: which view, what file, and what has to be on screen.

    ``expect`` is deliberately a piece of the view's CONTENT, not its heading.
    The first version of this script gated on the heading, which is present
    before any data arrives -- so it happily produced a picture of an empty
    "Today" panel reading "No decks or progress yet" and called it a success.
    """

    view: str
    filename: str
    expect: str
    #: Optional link text to click after arriving, for views whose panel is
    #: empty until you open something (Study Plans lists plans in the sidebar).
    click: str | None = None
    full_page: bool = False


SHOTS = (
    Shot("today", "web-today.png", "Your one next action"),
    Shot("study-plans", "web-study-plans.png", "Milestones", click="Python Decorators"),
    Shot("mastery", "web-mastery.png", "decorator"),
    Shot("study-session", "web-study-session.png", "Study Session"),
    Shot("body-double", "web-body-double.png", "Body Double"),
)

# Not captured: the flashcard review itself. Opening a deck needs a click on a
# row whose handler is not on the text node, and a screenshot of the deck
# PICKER would be a picture of a list, not of reviewing. Left out rather than
# faked; add it here when the deck row exposes a real control.

#: A deck in the real on-disk schema (`services/flashcard_writer.py`).
DECK = {
    "title": "Python Decorators — session cards",
    "cards": [
        {
            "front": "What does functools.wraps preserve?",
            "back": (
                "The wrapped function's __name__, __doc__, __module__ and "
                "__qualname__ — without it, the decorated function reports the "
                "wrapper's identity and help() becomes useless."
            ),
            "source": "session-2026-09-01",
        },
        {
            "front": "What is a decorator, in one sentence?",
            "back": (
                "A callable that takes a function and returns a new function, "
                "so behaviour can be added without editing the original."
            ),
            "source": "session-2026-09-01",
        },
        {
            "front": "Why does a decorator that takes arguments need three levels?",
            "back": (
                "The outer call consumes the arguments and returns the real "
                "decorator, which then wraps the function: @deco(x) is "
                "deco(x)(func)."
            ),
            "source": "session-2026-09-02",
        },
    ],
}

#: Concepts recorded through the real `studyloop progress` CLI, so the Mastery
#: graph and Today's next action are computed from real rows rather than mocked.
PROGRESS = (
    ("Closures", "confident"),
    ("First-class functions", "mastered"),
    ("functools.wraps", "learning"),
    ("Decorator factories", "struggling"),
)


def _seed_plan(world) -> None:
    """Write one study plan into the world's plans directory.

    Real plan markdown produced by the real renderer, so the screenshot shows
    what a learner's plan actually looks like rather than a mock.
    """
    from studyloop.planning import Milestone, Mission, StudyPlan
    from studyloop.planning.markdown import render_plan

    plan = StudyPlan(
        plan_id="python-decorators",
        title="Python Decorators",
        status="active",
        topics=["python"],
        target_date="2026-10-15",
        mission=Mission(
            why="Decorators keep appearing in the codebases I read, and I skip them.",
            success=[
                "I can explain what @functools.wraps preserves, without looking it up",
                "I can write a decorator that takes an argument",
            ],
            constraints=["30 minutes a day, most days"],
            out_of_scope=["Metaclasses"],
        ),
        milestones=[
            Milestone(
                title="Read and explain a decorator someone else wrote",
                done=True,
                concepts=["closures", "first-class functions"],
            ),
            Milestone(
                title="Write a timing decorator from scratch",
                done=True,
                concepts=["functools.wraps"],
            ),
            Milestone(
                title="Write a decorator that takes arguments",
                done=False,
                concepts=["decorator factories"],
            ),
            Milestone(
                title="Explain the difference to someone else",
                done=False,
                concepts=["teach-back"],
            ),
        ],
    )
    (Path(world.plans) / "python-decorators.md").write_text(render_plan(plan), encoding="utf-8")


def _seed_content(world) -> None:
    """Put a deck on disk and progress rows in the database, the real way.

    The deck goes through the same JSON schema `services/flashcard_writer.py`
    writes; the progress rows go through the real `studyloop progress` CLI, run
    against this world's environment. Nothing here fabricates a screen: every
    number in the screenshots is computed by the product from these inputs.
    """
    import json
    import subprocess

    slug = "python-decorators"
    deck_dir = Path(world.vault) / slug / "flashcards"
    deck_dir.mkdir(parents=True, exist_ok=True)
    (deck_dir / f"2026-09-02-{slug}-flashcards.json").write_text(
        json.dumps(DECK, indent=2), encoding="utf-8"
    )

    for concept, confidence in PROGRESS:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "studyloop.cli",
                "progress",
                concept,
                "--topic",
                slug,
                "--confidence",
                confidence,
            ],
            env={**world.env, "PYTHONPATH": str(REPO_ROOT / "packages" / "studyloop" / "src")},
            cwd=world.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"warning: could not record {concept}: {result.stderr.strip()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Directory for the PNGs.")
    parser.add_argument("--keep", action="store_true", help="Keep the temp world for inspection.")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    from _env import build_test_world, goto_view, start_server
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="studyloop-shots-"))
    world = build_test_world(root, PORT)
    _seed_plan(world)
    _seed_content(world)

    server = start_server(world)
    written: list[str] = []
    skipped: list[str] = []
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            page.goto(world.base_url, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => !!window.Alpine && !!window.Alpine.store('nav')", timeout=20000
            )
            for shot in SHOTS:
                goto_view(page, shot.view)
                if shot.click:
                    try:
                        page.locator(f"text={shot.click} >> visible=true").first.click(timeout=8000)
                        page.wait_for_timeout(400)
                    except Exception as exc:
                        print(f"skip {shot.filename}: could not open {shot.click!r} ({exc})")
                        skipped.append(shot.filename)
                        continue
                try:
                    # `>> visible=true` matters: the SPA keeps every view in the
                    # DOM and hides the inactive ones, so a plain text match
                    # resolves against a hidden panel and never becomes visible.
                    page.locator(f"text={shot.expect} >> visible=true").first.wait_for(
                        state="visible", timeout=8000
                    )
                except Exception as exc:
                    print(f"skip {shot.filename}: {shot.expect!r} never appeared ({exc})")
                    skipped.append(shot.filename)
                    continue
                page.wait_for_timeout(600)
                target = out / shot.filename
                page.screenshot(path=str(target), full_page=shot.full_page)
                written.append(shot.filename)
                print(f"wrote {target}")
            browser.close()
    finally:
        server.proc.terminate()
        try:
            server.proc.wait(timeout=10)
        except Exception:
            server.proc.kill()
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print(f"world kept at {root}")

    print(f"\n{len(written)}/{len(SHOTS)} screenshots written to {out}")
    if skipped:
        print("skipped: " + ", ".join(skipped))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
