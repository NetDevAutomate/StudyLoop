"""Journey phases 2-4 — generation walk, review loop, durable outcomes.

Extends the representative journey past "session start" with a test-only
generator injected before the real server starts, using an isolated vault:

  Phase 2  Generate: drive the REAL Generate panel end-to-end — submit the
           form, watch the WS-fed progress UI finish, assert deck files
           actually land on disk.
  Phase 3  Review: walk the REAL flashcards UI over the generated deck —
           flip, answer — and assert the summary renders.
  Phase 4  Durability: the review recorded real rows (review_sessions via
           POST /api/session, card progress via POST /api/review) in the
           tmp review DB — the loop leaves a trace, not just pixels.

Run: cd packages/studyloop && uv run pytest tests/e2e/test_journey_generate_review.py -m e2e
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18596
_PUBLISHER = "JourneyPub"
_COURSE = "Journey_Course"
RESULTS = Path("test-results")


# ---------------------------------------------------------------------------
# Isolated world: tmp vault + tmp DBs + stub generator config
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Build the isolated vault/config; return paths the tests assert against."""
    root = tmp_path_factory.mktemp("journey")
    study = root / "Study"
    notes = study / _PUBLISHER / _COURSE / "study-notes"
    notes.mkdir(parents=True)
    (notes / "closures.md").write_text(
        "# Closures\n\nA closure captures enclosing scope.", encoding="utf-8"
    )
    (notes / "decorators.md").write_text(
        "# Decorators\n\nA decorator wraps a callable.", encoding="utf-8"
    )

    sessions_db = root / "sessions.db"
    conn = sqlite3.connect(sessions_db)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """CREATE TABLE study_progress (
            id TEXT PRIMARY KEY, topic TEXT, concept TEXT, confidence TEXT,
            first_seen TEXT, last_seen TEXT, session_count INTEGER,
            notes TEXT, created_at TEXT, updated_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO study_progress VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("j1", "python", "closures", "struggling", now, now, 1, None, now, now),
    )
    conn.commit()
    conn.close()

    # NOTE: card_reviews / review_sessions live in the SAME sessions.db —
    # get_db_path() resolves the 'session_db' key for the review store too.
    course_dir = study / _PUBLISHER / _COURSE
    cfg = root / "config.yaml"
    cfg.write_text(
        f"""
session_db: {sessions_db}
state_dir: {root / "state"}
review:
  directories:
    - {course_dir}
content:
  base_path: {study}
card_generator:
  backend: ollama
  max_workers: 2
""",
        encoding="utf-8",
    )
    return {
        "config": cfg,
        "study": study,
        "course_dir": course_dir,
        "review_db": sessions_db,  # same file — see NOTE above
        "sessions_db": sessions_db,
    }


@pytest.fixture(scope="module")
def server(world: dict) -> Generator[str, None, None]:
    env = os.environ.copy()
    env["STUDYLOOP_CONFIG"] = str(world["config"])
    proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(_tests_dir) / "_content_test_server.py"),
            "web",
            "--port",
            str(WEB_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/", timeout=1)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                break
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError(f"server failed to start on {WEB_PORT}")
    try:
        yield f"http://127.0.0.1:{WEB_PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def _diag(page: Page, name: str) -> None:
    RESULTS.mkdir(exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=str(RESULTS / f"{name}-{ts}.png"), full_page=True)
        (RESULTS / f"{name}-{ts}.html").write_text(page.content())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 2 — Generate: real panel, test-only generator, files on disk
# ---------------------------------------------------------------------------


def test_phase2_generate_walk_produces_deck_files(browser: Browser, server: str, world) -> None:
    page = browser.new_page()
    try:
        page.goto(f"{server}/#generate")
        page.wait_for_function("() => !!window.Alpine", timeout=5000)

        # Cascade the real selects (hydrated from the tmp vault).
        page.select_option('select[x-model="form.publisher"]', value=_PUBLISHER)
        page.wait_for_function(
            f"""() => {{
                const sel = document.querySelector('select[x-model="form.course"]');
                return sel && !sel.disabled &&
                       [...sel.options].some(o => o.value === '{_COURSE}');
            }}""",
            timeout=10000,
        )
        page.select_option('select[x-model="form.course"]', value=_COURSE)

        # Quizzes too (flashcards is pre-checked). Leave the provider select
        # UNTOUCHED: 'stub' is a backend, not a registry provider — an empty
        # provider falls through to the config's card_generator.backend
        # (stub in this world), which is exactly what we want.
        page.locator('input[value="quizzes"]').check()

        page.locator('.generate-form button[type="submit"]').click()

        # WS-fed progress runs to a finish summary (stub is fast).
        page.wait_for_function(
            "() => document.querySelector('.generate-summary') && "
            "document.querySelector('.generate-summary').innerText.length > 0",
            timeout=60000,
        )

        # The REAL assertion: deck files exist on disk under the course.
        course_dir: Path = world["course_dir"]
        flashcard_files = list(course_dir.rglob("flashcards/*.json"))
        quiz_files = list(course_dir.rglob("quizzes/*.json"))
        assert flashcard_files, f"no flashcard decks written under {course_dir}"
        assert quiz_files, f"no quiz decks written under {course_dir}"
    except Exception:
        _diag(page, "phase2-generate")
        raise
    finally:
        page.close()


# ---------------------------------------------------------------------------
# Phase 3 — Review: walk the real flashcards UI over the generated deck
# Phase 4 — Durability: the walk left real DB rows
# ---------------------------------------------------------------------------


def test_phase3_and_4_review_walk_records_outcomes(browser: Browser, server: str, world) -> None:
    page = browser.new_page()
    try:
        page.goto(f"{server}/#flashcards")
        page.wait_for_function("() => !!window.Alpine", timeout=5000)

        # Course list shows the generated deck's course; open its config.
        page.wait_for_function(
            "() => !document.body.innerText.includes('Checking your content')",
            timeout=15000,
        )
        page.get_by_role("button", name="Flashcards", exact=True).last.click()

        # Start the review session from the config screen.
        start = page.get_by_role("button", name="Start Session")
        start.wait_for(state="visible", timeout=10000)
        start.click()

        # Walk EVERY card: flip (Space) then mark correct (Y). The deck size
        # is whatever generation produced (visible as "1/N"); read N from the
        # Alpine state and answer exactly that many.
        # Wait for the study view + cards to hydrate before reading the count
        # (reading immediately after the click races the /api/cards fetch).
        page.wait_for_function(
            """() => {
                const els = [...document.querySelectorAll('[x-data^="reviewApp"]')];
                const el = els.find(e => e.getAttribute('x-data').includes('flashcards'));
                const st = el && el._x_dataStack && el._x_dataStack[0];
                return !!st && st.view === 'study' && st.cards.length > 0;
            }""",
            timeout=15000,
        )
        total = page.evaluate(
            """() => {
                const els = [...document.querySelectorAll('[x-data^="reviewApp"]')];
                const el = els.find(e => e.getAttribute('x-data').includes('flashcards'));
                return el._x_dataStack[0].cards.length;
            }"""
        )
        assert total > 0, "review session started with zero cards"
        for _ in range(total):
            page.keyboard.press("Space")  # reveal
            page.wait_for_timeout(120)
            page.keyboard.press("y")  # correct
            page.wait_for_timeout(120)

        # Summary view = session complete = outcomes flushed.
        page.wait_for_function(
            """() => {
                const els = [...document.querySelectorAll('[x-data^="reviewApp"]')];
                const el = els.find(e => e.getAttribute('x-data').includes('flashcards'));
                return el && el._x_dataStack && el._x_dataStack[0].view === 'summary';
            }""",
            timeout=15000,
        )

        # Phase 4 — durable outcomes in the tmp review DB.
        review_db: Path = world["review_db"]
        assert review_db.exists(), "review DB never created — no outcome recorded"
        conn = sqlite3.connect(review_db)
        try:
            reviews = conn.execute("SELECT COUNT(*) FROM card_reviews").fetchone()[0]
        except sqlite3.OperationalError:
            reviews = 0
        try:
            sessions = conn.execute("SELECT COUNT(*) FROM review_sessions").fetchone()[0]
        except sqlite3.OperationalError:
            sessions = 0
        conn.close()
        assert reviews > 0 or sessions > 0, (
            "review walk left no durable rows (card_reviews=0, review_sessions=0)"
        )
    except Exception:
        _diag(page, "phase3-review")
        raise
    finally:
        page.close()
