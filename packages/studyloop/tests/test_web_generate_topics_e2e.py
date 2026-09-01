"""Playwright e2e tests for the Generate panel struggling-topics dropdown (P3).

Two test classes:

* ``TestStrugglingTopicsDropdownShape`` — route-stub, real server.
  Intercepts ``/api/history/struggling-topics`` with a synthetic 2-topic
  payload; asserts the ``select[x-model="form.topic_slug"]`` options
  populate correctly via Alpine.

* ``TestStrugglingTopicsEndToEnd`` — real server, seeded tmp DB.
  Seeds a tmp sessions.db via direct sqlite3 INSERT (same 10-column
  schema as ``test_web_history_struggling.py``), boots the server against
  that DB via ``session_db: <path>`` in a tmp config, and asserts the
  dropdown is populated from the real route.

Port: 18581 (unique; siblings use 18580).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from playwright.sync_api import Browser, Page, Route


pytestmark = [pytest.mark.e2e]

WEB_PORT = 18587  # uniqueness enforced by tests/test_port_uniqueness.py

_PUBLISHER = "DataCamp"
_COURSE = "Intro_To_Pandas"

# Synthetic route-stub payload — matches the REAL response shape:
# list[{"topic", "concept_count", "session_count", "last_seen"}]
_STUB_PAYLOAD = [
    {
        "topic": "python",
        "concept_count": 2,
        "session_count": 4,
        "last_seen": "2026-05-30T00:00:00",
    },
    {
        "topic": "sql-joins",
        "concept_count": 1,
        "session_count": 2,
        "last_seen": "2026-05-29T00:00:00",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Minimal 3-level study tree: publisher / course / lesson files."""
    study = tmp_path / "Study"
    notes = study / _PUBLISHER / _COURSE / "study-notes"
    notes.mkdir(parents=True)
    (notes / "advanced-pandas.md").write_text(
        "# Pandas\n\nGroupby and pivot tables.", encoding="utf-8"
    )
    (notes / "joins.md").write_text("# Joins\n\nINNER, LEFT, RIGHT.", encoding="utf-8")
    return study


@pytest.fixture
def sessions_db(tmp_path: Path) -> Path:
    """Tmp sessions.db seeded with 2 struggling study_progress rows.

    Uses direct sqlite3 INSERT — no record_progress import, no LLM budget.
    Mirrors the 10-column schema from test_web_history_struggling.py exactly:
    (id, topic, concept, confidence, first_seen, last_seen,
     session_count, notes, created_at, updated_at)
    """
    db = tmp_path / "sessions.db"
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE study_progress (
            id          TEXT PRIMARY KEY,
            topic       TEXT,
            concept     TEXT,
            confidence  TEXT,
            first_seen  TEXT,
            last_seen   TEXT,
            session_count INTEGER,
            notes       TEXT,
            created_at  TEXT,
            updated_at  TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO study_progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("id1", "python", "abc-vs-protocol", "struggling", now, now, 3, None, now, now),
            ("id2", "sql-joins", "outer-join", "struggling", now, now, 2, None, now, now),
        ],
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def stub_config(tmp_path: Path, vault: Path, sessions_db: Path) -> Path:
    """Tmp YAML config with vault paths and session_db wired to
    our seeded tmp DB so the running server never touches the real DB.

    ``session_db`` is the YAML key; ``_connection._connect()`` resolves it
    via ``load_settings().session_db`` which reads ``STUDYLOOP_CONFIG``.
    """
    cfg = tmp_path / "studyloop-test.yaml"
    course_dir = vault / _PUBLISHER / _COURSE
    cfg.write_text(
        f"""
session_db: {sessions_db}
review:
  directories:
    - {course_dir}
content:
  base_path: {vault}
card_generator:
  backend: ollama
  max_workers: 2
""",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def server(stub_config: Path) -> Generator[subprocess.Popen, None, None]:
    """Bring up ``studyloop web`` with the tmp config; tear down at end.

    Mirrors the pattern in test_web_content_gen_e2e.py exactly.
    """
    env = os.environ.copy()
    env["STUDYLOOP_CONFIG"] = str(stub_config)
    cmd = [
        sys.executable,
        "-m",
        "studyloop.cli",
        "web",
        "--port",
        str(WEB_PORT),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
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
        msg = f"Web server failed to start on port {WEB_PORT}"
        raise RuntimeError(msg)
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture
def page(server: subprocess.Popen, browser: Browser) -> Generator[Page, None, None]:
    context = browser.new_context()
    p = context.new_page()
    try:
        yield p
    finally:
        p.close()
        context.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_struggling_topics_js() -> str:
    """Return an inline JS expression (not a function) evaluating to the
    strugglingTopics array on the generatePanel Alpine component.

    Used inside wait_for_function bodies where the outer ``() => ...``
    already provides the arrow-function wrapper.
    """
    return (
        "window.Alpine.$data("
        "document.querySelector('[x-data=\"generatePanel()\"]')"
        ").strugglingTopics"
    )


_ALPINE_DATA_EXPR = _get_struggling_topics_js()


def _goto_generate(page: Page) -> None:
    """Navigate to the Generate panel and wait for Alpine to be ready."""
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#generate")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_function("() => window.Alpine.store('nav').current === 'generate'", timeout=3000)


def _wait_publishers_loaded(page: Page) -> None:
    """Block until the Publisher dropdown has options from /api/content/publishers."""
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('select[x-model="form.publisher"]');
            return sel && sel.querySelectorAll('option').length > 1;
        }""",
        timeout=5000,
    )


def _select_publisher_course(page: Page) -> None:
    """Drive the publisher → course cascade to trigger onCourseChange().

    onCourseChange() is what fires the /api/history/struggling-topics fetch.
    """
    _wait_publishers_loaded(page)
    page.select_option('select[x-model="form.publisher"]', value=_PUBLISHER)
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('select[x-model="form.course"]');
            return sel && !sel.disabled && sel.querySelectorAll('option').length > 1;
        }""",
        timeout=5000,
    )
    page.select_option('select[x-model="form.course"]', value=_COURSE)


# ---------------------------------------------------------------------------
# Class 1: Route-stub — intercept the API, assert dropdown shape
# ---------------------------------------------------------------------------


class TestStrugglingTopicsDropdownShape:
    """Intercept /api/history/struggling-topics with a synthetic 2-topic
    payload and assert Alpine populates the topic select correctly.

    The fetch fires automatically in onCourseChange() when the course is
    selected — NOT on radio click — so we drive publisher/course first.
    """

    def test_stub_topics_populate_select_options(self, page: Page) -> None:
        """Route-stubbed payload → 2 options appear in the topic <select>."""

        def _handle(route: Route) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_STUB_PAYLOAD),
            )

        page.route("**/api/history/struggling-topics**", _handle)

        _goto_generate(page)
        _select_publisher_course(page)

        # Wait for Alpine to process the (intercepted) fetch response.
        page.wait_for_function(
            f"() => {_ALPINE_DATA_EXPR}.length > 0",
            timeout=5000,
        )

        # The topic <select> must have option elements for each stub topic
        # (plus the default "all struggling topics" placeholder).
        option_values = page.evaluate(
            """() => {
                const sel = document.querySelector('select[x-model="form.topic_slug"]');
                if (!sel) return [];
                return [...sel.querySelectorAll('option')]
                    .map(o => o.value)
                    .filter(Boolean);
            }"""
        )
        assert set(option_values) == {
            "python",
            "sql-joins",
        }, f"unexpected option values: {option_values!r}"

    def test_stub_returns_exactly_two_options(self, page: Page) -> None:
        """Exactly 2 non-placeholder options are rendered (one per stub topic)."""

        def _handle(route: Route) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_STUB_PAYLOAD),
            )

        page.route("**/api/history/struggling-topics**", _handle)

        _goto_generate(page)
        _select_publisher_course(page)

        page.wait_for_function(
            f"() => {_ALPINE_DATA_EXPR}.length >= 2",
            timeout=5000,
        )

        count = page.evaluate(
            """() => {
                const sel = document.querySelector('select[x-model="form.topic_slug"]');
                if (!sel) return 0;
                return [...sel.querySelectorAll('option')]
                    .filter(o => o.value !== '').length;
            }"""
        )
        assert count == 2, f"expected 2 non-placeholder options, got {count}"

    def test_topic_radio_reveals_topic_select(self, page: Page) -> None:
        """Clicking the 'topic_struggles' radio makes the topic <select> visible."""

        def _handle(route: Route) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_STUB_PAYLOAD),
            )

        page.route("**/api/history/struggling-topics**", _handle)

        _goto_generate(page)
        _select_publisher_course(page)

        page.wait_for_function(
            f"() => {_ALPINE_DATA_EXPR}.length > 0",
            timeout=5000,
        )

        # Switch scope to topic_struggles — this row is x-show'd into view.
        page.click('.generate-form input[type=radio][value="topic_struggles"]')

        # The label row containing the topic select must now be visible.
        topic_label = page.locator('.generate-form label:has(select[x-model="form.topic_slug"])')
        topic_label.wait_for(state="visible", timeout=5000)
        assert topic_label.is_visible(), (
            "topic select label row is not visible after clicking topic_struggles radio"
        )


# ---------------------------------------------------------------------------
# Class 2: End-to-end — real server, seeded tmp DB
# ---------------------------------------------------------------------------


class TestStrugglingTopicsEndToEnd:
    """Real server, seeded tmp DB — asserts the full route→UI chain.

    The server's session_db is wired to our tmp DB via ``session_db: <path>``
    in the stub config YAML, which the subprocess inherits via STUDYLOOP_CONFIG.
    """

    def test_real_route_returns_seeded_topics(self, page: Page) -> None:
        """GET /api/history/struggling-topics returns HTTP 200 with 2 entries."""
        with page.expect_response("**/api/history/struggling-topics**") as resp_info:
            _goto_generate(page)
            _select_publisher_course(page)

        resp = resp_info.value
        assert resp.status == 200, f"expected 200, got {resp.status}"
        data = resp.json()
        assert isinstance(data, list), f"expected list, got {type(data)}"
        topics = {entry["topic"] for entry in data}
        assert "python" in topics, f"'python' missing from topics: {topics!r}"
        assert "sql-joins" in topics, f"'sql-joins' missing from topics: {topics!r}"

    def test_real_route_response_has_correct_shape(self, page: Page) -> None:
        """Each item in the response has the expected keys."""
        with page.expect_response("**/api/history/struggling-topics**") as resp_info:
            _goto_generate(page)
            _select_publisher_course(page)

        data = resp_info.value.json()
        assert len(data) >= 2, f"expected at least 2 entries, got {len(data)}"
        for item in data:
            for key in ("topic", "concept_count", "session_count", "last_seen"):
                assert key in item, f"key {key!r} missing from response item: {item!r}"

    def test_seeded_topics_appear_in_alpine_state(self, page: Page) -> None:
        """After course selection Alpine strugglingTopics contains both seeded topics."""
        _goto_generate(page)
        _select_publisher_course(page)

        # Wait for the fetch to resolve and Alpine to update.
        page.wait_for_function(
            f"() => {_ALPINE_DATA_EXPR}.length >= 2",
            timeout=5000,
        )

        alpine_topics = page.evaluate(f"() => {_ALPINE_DATA_EXPR}.map(t => t.topic)")
        assert "python" in alpine_topics, (
            f"'python' missing from Alpine strugglingTopics: {alpine_topics!r}"
        )
        assert "sql-joins" in alpine_topics, (
            f"'sql-joins' missing from Alpine strugglingTopics: {alpine_topics!r}"
        )

    def test_seeded_topics_appear_as_select_options(self, page: Page) -> None:
        """Both seeded topics appear as <option> values in the topic select."""
        _goto_generate(page)
        _select_publisher_course(page)

        page.wait_for_function(
            f"() => {_ALPINE_DATA_EXPR}.length >= 2",
            timeout=5000,
        )

        option_values = page.evaluate(
            """() => {
                const sel = document.querySelector('select[x-model="form.topic_slug"]');
                if (!sel) return [];
                return [...sel.querySelectorAll('option')]
                    .map(o => o.value)
                    .filter(Boolean);
            }"""
        )
        assert "python" in option_values, f"'python' not in select options: {option_values!r}"
        assert "sql-joins" in option_values, f"'sql-joins' not in select options: {option_values!r}"
