#!/usr/bin/env python3
"""Capture a browser session for the ``live_xtiles`` Playwright checks. Run once.

xTiles signs you in through a browser, and there is no API key to paste. So the
live checks cannot log in for themselves: this script opens a real window, waits
for you to sign in by hand, and saves the resulting session so the tests can reuse
it.

    env -u VIRTUAL_ENV uv run python scripts/xtiles-live-auth.py

The saved file is a **credential**. It is written outside the repository, to
``~/.cache/studyloop-live/`` by default, with owner-only permissions, and a guard
test refuses any path inside the working tree. Delete it when you are done:

    rm ~/.cache/studyloop-live/xtiles-auth.json

That does not sign you out of xTiles — it only discards this copy. Ending the
connection itself means removing the ``xtiles`` MCP server from your assistant's
own configuration, which is the same place the sign-in lives.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

DEFAULT_STATE = Path.home() / ".cache" / "studyloop-live" / "xtiles-auth.json"
XTILES_URL = "https://xtiles.app/"

#: What we wait for. Not a fixed selector: the point is "you are signed in", and
#: the reliable signal for that is the URL no longer being the marketing or login
#: page. A selector would pin this script to one version of someone else's UI.
SIGNED_IN_HINTS = ("/my/", "/workspace", "/planner", "/doc/")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help=f"Where to write the session. Default: {DEFAULT_STATE}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for you to finish signing in. Default: 300.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    state: Path = args.state.expanduser().resolve()

    repo_root = Path(__file__).resolve().parents[1]
    if repo_root in state.parents or state == repo_root:
        print(
            f"refusing to write a session credential inside the repository: {state}",
            file=sys.stderr,
        )
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright is not installed in this environment; run this with `uv run --group dev`",
            file=sys.stderr,
        )
        return 1

    state.parent.mkdir(parents=True, exist_ok=True)

    print(f"Opening {XTILES_URL} in a real browser window.")
    print("Sign in to xTiles, then leave the window on any signed-in page.")
    print(f"Waiting up to {args.timeout}s. Close nothing — this script closes it.\n")

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(XTILES_URL, wait_until="domcontentloaded")

        deadline = args.timeout * 1000
        waited = 0
        step = 2000
        while waited < deadline:
            page.wait_for_timeout(step)
            waited += step
            if any(hint in page.url for hint in SIGNED_IN_HINTS):
                break
        else:
            print(
                f"still on {page.url} after {args.timeout}s — no session saved.\n"
                "Rerun and sign in, or pass --timeout to allow longer.",
                file=sys.stderr,
            )
            browser.close()
            return 1

        # Give the app a moment to finish writing whatever it stores on sign-in,
        # so the captured state is one a reload would actually accept.
        page.wait_for_timeout(2500)
        context.storage_state(path=str(state))
        browser.close()

    os.chmod(state, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Saved a signed-in session to {state} (owner-only).")
    print("\nNow run the live checks:\n")
    print(
        "  STUDYLOOP_LIVE_XTILES=1 \\\n"
        '  STUDYLOOP_LIVE_XTILES_URL="<the URL your assistant returned>" \\\n'
        '  STUDYLOOP_LIVE_XTILES_PROBE="StudyLoop round-trip probe" \\\n'
        "  env -u VIRTUAL_ENV uv run --group dev pytest -m live_xtiles -v"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
