#!/usr/bin/env python3
"""Capture publishable screenshots of the notes StudyLoop writes into a vault.

These are pictures of **StudyLoop's output**, rendered for reading. They are
deliberately NOT pictures of Obsidian, and every image says so in its own pixels.

Why not a screenshot of Obsidian itself
---------------------------------------

Three model families planned this independently and the arbitration went with the
most conservative of the three. Obsidian is a desktop app with no headless mode, so
the options were:

* open the temp vault in the owner's Obsidian via an ``obsidian://`` URI — rejected,
  because registering a throwaway vault in the vault switcher of a tool someone uses
  daily is an unverified side effect on a real environment, and a documentation
  image is not worth that;
* drive the app that is already open — kept, but as a separate opt-in glance in
  ``test_obsidian_live.py``, which skips whenever the app is closed (usually);
* render the Markdown for reading and label it honestly — this script.

What it must never become is Obsidian's interface drawn from memory. An image
captioned as an app the reader can recognise, that is not that app, is a false
claim in the same family as the ones this campaign kept finding in prose. Hence the
in-pixel footer, and a guard that fails if the footer goes missing or if the page
starts imitating the app's chrome.

Usage::

    env -u VIRTUAL_ENV uv run python scripts/capture-vault-screenshots.py \\
        --out ~/code/personal/sites/StudyLoopSite/public/images

The vault is a temp directory built by the journey world, published into by the real
CLI. No real vault, config or plan is touched, and the guard tests refuse a run that
would start with the host ``HOME``.
"""

from __future__ import annotations

import argparse
import html
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "packages" / "studyloop" / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

#: Printed inside every image. Not a caption in the surrounding HTML — a caption can
#: be cropped away or recycled with new words, and the claim has to travel with the
#: pixels.
FOOTER = "Hermetic StudyLoop projections — not Obsidian"

VIEWPORT = {"width": 1100, "height": 820}

PLAN_ID = "python-decorators"
TITLE = "Python Decorators"
WHY = "Decorators keep appearing in the codebases I read, and I skip them."
LEARNER_NOTE = "I keep mixing wraps with partial."


@dataclass(frozen=True)
class Shot:
    """One image: which vault file, what it is called, and what proves it rendered."""

    source: str
    filename: str
    caption: str
    #: A string that only appears once the file has real content in it.
    #:
    #: Deliberately never a heading. The website's Web UI shots were first gated on
    #: headings and produced a proud picture of an empty panel, because a heading is
    #: present before any data arrives. A guard enforces this.
    expect: str


SHOTS = (
    Shot(
        source="Study/Today.md",
        filename="vault-today.png",
        caption="Study/Today.md — one next action, what is due, and what you are on",
        # NOT "Next action": that is a heading, present before any data arrives.
        # Gating on it produced a picture of three empty states, which is what the
        # website's first Web UI screenshots did too.
        expect="decorator factories",
    ),
    Shot(
        source=f"Study/Plans/{PLAN_ID}.md",
        filename="vault-plan.png",
        caption=f"Study/Plans/{PLAN_ID}.md — the plan, projected for reading",
        expect=WHY,
    ),
    Shot(
        source=f"Study/Plans/{PLAN_ID}.notes.md",
        filename="vault-notes.png",
        caption=(f"Study/Plans/{PLAN_ID}.notes.md — yours. StudyLoop only ever reads it."),
        expect=LEARNER_NOTE,
    ),
)

_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0;
  font-family: -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  background: #f4f4f7; color: #17192a;
}
.sheet { padding: 40px 48px 0; }
.path {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; letter-spacing: .04em; text-transform: uppercase;
  color: #6046ef; font-weight: 700; margin-bottom: 18px;
}
.note {
  background: #fff; border: 1px solid #e2e2ea; border-radius: 14px;
  padding: 30px 34px; box-shadow: 0 10px 30px rgb(23 25 42 / 7%);
}
.note h1 { font-size: 27px; margin: 0 0 18px; }
.note h2 { font-size: 18px; margin: 26px 0 10px; color: #312c73; }
.note h3 { font-size: 15px; margin: 18px 0 8px; color: #45407e; }
.note p, .note li { font-size: 14.5px; line-height: 1.62; color: #33353f; }
.note ul { padding-left: 20px; }
.note code { background: #f1f1f6; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
.note table { border-collapse: collapse; font-size: 13px; }
.note th, .note td { border: 1px solid #e2e2ea; padding: 5px 9px; text-align: left; }
.frontmatter {
  background: #f7f7fb; border: 1px dashed #cfcfe0; border-radius: 10px;
  padding: 12px 16px; margin-bottom: 22px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px; color: #5c5f70; white-space: pre-wrap;
}
.caption { font-size: 13px; color: #5f6475; margin: 16px 0 0; }
.footer {
  margin-top: 26px; padding: 12px 48px 18px;
  border-top: 1px solid #e2e2ea; background: #ecebf5;
  font-size: 12px; font-weight: 700; color: #4c3fbb; letter-spacing: .02em;
}
"""


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body).

    The frontmatter is shown rather than hidden: the ``studyloop:`` marker is what
    makes republishing safe, and a reader deciding whether to trust this feature
    should be able to see it. Hiding it would make a prettier and less honest image.
    """
    if not text.startswith("---\n"):
        return "", text
    _, _, rest = text.partition("---\n")
    front, sep, body = rest.partition("\n---\n")
    if not sep:
        return "", text
    return front.strip(), body.lstrip("\n")


def _render(shot: Shot, text: str) -> str:
    import markdown as markdown_lib

    front, body = _split_frontmatter(text)
    rendered = markdown_lib.markdown(body, extensions=["tables", "sane_lists"])
    # python-markdown has no task-list extension here, so `- [x] …` renders as the
    # literal characters. Same information, but a published image should show a box.
    rendered = rendered.replace("<li>[x] ", "<li>&#9745; ").replace("<li>[ ] ", "<li>&#9744; ")
    front_block = f'<div class="frontmatter">{html.escape(front)}</div>' if front else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<style>{_STYLE}</style></head><body>"
        "<div class='sheet'>"
        f"<div class='path'>{html.escape(shot.source)}</div>"
        f"<div class='note'>{front_block}{rendered}</div>"
        f"<p class='caption'>{html.escape(shot.caption)}</p>"
        "</div>"
        f"<div class='footer'>{html.escape(FOOTER)}</div>"
        "</body></html>"
    )


def _build_published_vault(root: Path):
    """Seed a plan, enable Obsidian, publish — all through the real CLI."""
    from journeys._world import journey_world

    manager = journey_world(root)
    world = manager.__enter__()

    created = world.run(
        "plan",
        "new",
        "--title",
        TITLE,
        "--why",
        WHY,
        "--topic",
        PLAN_ID,
        "--success",
        "I can explain what functools.wraps preserves, without looking it up",
        "--success",
        "I can write a decorator that takes an argument",
        "--constraint",
        "30 minutes a day, most days",
        "--milestone",
        "Read and explain a decorator someone else wrote (concepts: closures)",
        "--milestone",
        "Write a timing decorator from scratch (concepts: functools.wraps)",
        "--milestone",
        "Write a decorator that takes arguments (concepts: decorator factories)",
        "--resource",
        "https://docs.python.org/3/library/functools.html",
        "--activate",
    )
    if created.exit_code:
        raise SystemExit(f"could not create the demo plan:\n{created.output}")

    done = world.run("plan", "milestone", PLAN_ID, "0", "--done")
    if done.exit_code:
        raise SystemExit(f"could not complete a milestone:\n{done.output}")

    # Real progress rows, so Today shows a real recommendation instead of three
    # empty states. Recorded through the CLI, so the numbers in the picture are
    # computed by the product rather than typed into a fixture.
    for concept, confidence in (
        ("closures", "confident"),
        ("functools.wraps", "learning"),
        ("decorator factories", "struggling"),
    ):
        recorded = world.run("progress", concept, "--topic", PLAN_ID, "--confidence", confidence)
        if recorded.exit_code:
            raise SystemExit(f"could not record progress:\n{recorded.output}")

    enabled = world.run("brain", "enable", "obsidian", "--vault", str(world.vault))
    if enabled.exit_code:
        raise SystemExit(f"could not enable Obsidian:\n{enabled.output}")

    published = world.run("brain", "publish")
    if published.exit_code:
        raise SystemExit(f"publish failed:\n{published.output}")

    # The learner's own file, written by hand as a learner would.
    notes = world.vault / f"Study/Plans/{PLAN_ID}.notes.md"
    notes.write_text(
        "# My notes\n\n"
        f"{LEARNER_NOTE}\n\n"
        "Ask the mentor why a decorator that takes arguments needs three levels.\n",
        encoding="utf-8",
    )
    return manager, world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Directory for the PNGs.")
    parser.add_argument(
        "--keep", action="store_true", help="Keep the rendered HTML for inspection."
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit 0 even when some shots were skipped. Off by default.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="studyloop-vault-shots-"))
    manager, world = _build_published_vault(root)
    written: list[str] = []
    skipped: list[str] = []
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            for shot in SHOTS:
                source = world.vault / shot.source
                try:
                    text = source.read_text(encoding="utf-8")
                except OSError:
                    print(f"skip {shot.filename}: {shot.source} was never written")
                    skipped.append(shot.filename)
                    continue
                if shot.expect not in text:
                    print(
                        f"skip {shot.filename}: {shot.expect!r} is not in "
                        f"{shot.source} — refusing to publish a picture of an "
                        "empty note"
                    )
                    skipped.append(shot.filename)
                    continue

                html_path = root / f"{shot.filename}.html"
                html_path.write_text(_render(shot, text), encoding="utf-8")
                page.goto(html_path.as_uri(), wait_until="load")
                page.wait_for_timeout(250)
                page.screenshot(path=str(out / shot.filename), full_page=True)
                written.append(shot.filename)
                print(f"wrote {out / shot.filename}")
            browser.close()
    finally:
        manager.__exit__(None, None, None)
        if args.keep:
            print(f"rendered HTML kept at {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    print(f"\n{len(written)}/{len(SHOTS)} screenshots written to {out}")
    if skipped:
        print("skipped: " + ", ".join(skipped))
    if skipped and not args.allow_partial:
        # `return 0 if written else 1` reported success when two of three shots were
        # missing, so a docs build could quietly publish an incomplete set. A
        # validation council caught it. Partial is now a decision, not a default.
        print(
            "\nincomplete: pass --allow-partial to accept a partial set, or fix the "
            "reason a shot had nothing to photograph",
            file=sys.stderr,
        )
        return 1
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
