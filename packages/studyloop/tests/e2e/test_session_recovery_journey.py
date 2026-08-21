"""End-to-end recovery journey — getting UNSTUCK from a live session.

Two reported dead ends, both reproduced here against the REAL server:

  Bug A  "A session for X is already active. Reattach to it, or end it first."
         …with no way to do either. The 409 body has carried
         ``detached``/``reattach_url`` since the WS grace window landed, and
         ``GET /api/session/state`` now carries them too — nothing consumed
         either. Worse, a session started from **Body Double** put the Study
         Session view into a closed loop: the "Live session" banner routed
         there, the Study view refused to adopt a foreign-origin session, so
         it rendered the picker, and every Start 409'd.

  Bug B  the park-first modal listed the three live topics and offered exactly
         one verb — park. A topic you no longer care about could not be
         removed, so the modal was a wall rather than a fork.

Every phase runs against its OWN config, session DB and IPC directory. That is
not hygiene theatre: the park-first modal reads the real parking lot, and the
developer's has ~37 pending rows — an unisolated run would open the modal and
silently never issue the request under test.

Selectors remain surface-scoped where the two pickers share a control name;
stable ``data-testid`` hooks are used for the critical Study Session actions.
The Body Double view is declared BEFORE Study Session in index.html, so an
unscoped class selector can otherwise resolve to the hidden Body Double
surface.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_session_recovery_journey.py -m e2e
"""

from __future__ import annotations

import contextlib
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import start_web_server  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

RESULTS = Path("test-results")

CONFIGURED_TOPICS = ("Python Decorators", "SQL Window Functions", "BGP Route Reflectors")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """A server on its own config + DB + IPC dir, with the harness agent.

    The config carries three ``topics:`` so the picker's configured-topic list
    is populated — that list is the one the user said they felt trapped by, and
    the escape-hatch assertions below need it to be non-empty.
    """
    root = tmp_path_factory.mktemp("session-recovery")
    session_dir = root / "session-ipc"
    session_dir.mkdir(parents=True, exist_ok=True)
    config = root / "config.yaml"
    topics_yaml = "".join(
        f"  - name: {name}\n    slug: {name.lower().replace(' ', '-')}\n"
        f"    obsidian_path: Vendor/Course\n"
        for name in CONFIGURED_TOPICS
    )
    config.write_text(
        f"topics:\n{topics_yaml}session_db: {root / 'sessions.db'}\n",
        encoding="utf-8",
    )

    port = _free_port()
    proc = start_web_server(
        port,
        extra_env={
            "STUDYLOOP_CONFIG": str(config),
            "STUDYLOOP_SESSION_DIR": str(session_dir),
            "STUDYLOOP_PLANS_DIR": str(root / "study-plans"),
            "STUDYLOOP_TEST_AGENT": "1",
        },
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url
    finally:
        with contextlib.suppress(Exception):
            _post(base_url, "/api/session/end", {})
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Server-side helpers (out-of-band, so the browser's own calls stay meaningful)
# ---------------------------------------------------------------------------


def _post(base_url: str, path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read().decode()
            return res.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return exc.code, (json.loads(raw) if raw else {})


def _get(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=30) as res:
        return json.loads(res.read().decode())


def _start_session(base_url: str, topic: str, origin: str) -> str:
    status, body = _post(
        base_url,
        "/api/session/start",
        {"topic": topic, "energy": 5, "agent": "fake", "transport": "pty", "origin": origin},
    )
    assert status == 201, f"could not start a {origin} session: {status} {body}"
    return body["study_session_id"]


@pytest.fixture()
def clean_session(env: str):
    """No live session, and an empty parking lot, before and after each test."""
    _post(env, "/api/session/end", {})
    _post(env, "/api/parking/clear", {"all": True, "hard": True})
    yield env
    _post(env, "/api/session/end", {})
    _post(env, "/api/parking/clear", {"all": True, "hard": True})


@pytest.fixture()
def page(clean_session: str, browser):
    context = browser.new_context(viewport={"width": 1500, "height": 1000})
    pg = context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    pg._studyloop_errors = errors
    yield pg
    context.close()


def _diag(page: Page, label: str) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        page.screenshot(path=str(RESULTS / f"session-recovery-{label}.png"), full_page=True)
    with contextlib.suppress(Exception):
        (RESULTS / f"session-recovery-{label}.html").write_text(page.content(), encoding="utf-8")


def _goto(page: Page, base_url: str, view: str) -> None:
    if not page.url.startswith(base_url):
        page.goto(f"{base_url}/#{view}")
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')", timeout=15_000)
    page.evaluate("(v) => window.Alpine.store('nav').go(v)", view)
    page.wait_for_timeout(300)


def _study_data(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[x-data="sessionTimer()"]');
          const d = window.Alpine.$data(root);
          return {
            sessionActive: d.sessionActive,
            startError: d.startError,
            conflict: d.conflictSession ? JSON.parse(JSON.stringify(d.conflictSession)) : null,
          };
        }"""
    )


# ---------------------------------------------------------------------------
# Bug A — the picker must offer a way out, not just a complaint
# ---------------------------------------------------------------------------


class TestStudyPickerRecovery:
    def test_picker_offers_recovery_while_a_body_double_session_is_live(
        self, clean_session: str, page: Page
    ) -> None:
        """The closed loop, end to end.

        A Body Double session is live. The Study view will not adopt it (the
        origin guard exists so two consoles never attach to one PTY), so it
        renders the picker — the exact state in which Start can only ever 409.
        The picker must SAY so up front and offer both levers.
        """
        _start_session(clean_session, "Body double focus", origin="body-double")
        _goto(page, clean_session, "study-session")

        picker = page.locator(".study-start-picker")
        picker.wait_for(state="visible", timeout=10_000)

        error = page.locator(".study-start-picker .picker-error")
        try:
            error.wait_for(state="visible", timeout=10_000)
        except Exception:  # pragma: no cover - diagnostics only
            _diag(page, "no-proactive-conflict")
            raise
        text = error.text_content() or ""
        assert "Body Double" in text, (
            "the picker must name the surface that owns the live session, got: " + text
        )

        # Both levers, with accessible names (no repeat of the unlabelled ■).
        open_btn = page.locator(".study-start-picker #study-conflict-open")
        end_btn = page.locator(".study-start-picker #study-conflict-end")
        open_btn.wait_for(state="visible", timeout=5_000)
        end_btn.wait_for(state="visible", timeout=5_000)
        assert (open_btn.text_content() or "").strip(), "the open-surface button needs a label"
        assert (end_btn.text_content() or "").strip(), "the end button needs a label"

        # Reattach must NOT be offered here: adopting a foreign-origin session
        # in this view is what the origin guard exists to prevent.
        assert not page.locator(".study-start-picker #study-conflict-reattach").is_visible()

        page.locator("#study-conflict-open").click()
        page.wait_for_timeout(300)
        assert page.evaluate("() => window.Alpine.store('nav').current") == "body-double"

    def test_live_session_banner_routes_to_the_owning_surface(
        self, clean_session: str, page: Page
    ) -> None:
        """The banner must not send the learner to a view that will 409 them."""
        _start_session(clean_session, "Body double focus", origin="body-double")
        _goto(page, clean_session, "flashcards")

        banner = page.locator(".session-indicator")
        banner.wait_for(state="visible", timeout=10_000)
        banner.click()
        page.wait_for_timeout(400)

        current = page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "body-double", (
            "a body-double session's banner must open Body Double, not the "
            f"Study picker that cannot adopt it (landed on {current!r})"
        )

    def test_end_from_the_picker_releases_the_slot(self, clean_session: str, page: Page) -> None:
        """End must be reachable in the ONE state that needs it — no session
        of our own, someone else's session blocking Start."""
        _start_session(clean_session, "Body double focus", origin="body-double")
        _goto(page, clean_session, "study-session")

        page.locator(".study-start-picker #study-conflict-end").wait_for(
            state="visible", timeout=10_000
        )
        page.locator("#study-conflict-end").click()

        dialog = page.locator("#end-confirm .end-confirm-dialog")
        dialog.wait_for(state="visible", timeout=5_000)
        page.locator("[data-testid='study-end-confirm-yes']").click()

        page.wait_for_function(
            """async () => {
              const res = await fetch('/api/session/state');
              const s = await res.json();
              return !s.study_session_id;
            }""",
            timeout=10_000,
        )
        page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              return !d.conflictSession && !d.startError;
            }""",
            timeout=5_000,
        )

    def test_409_from_a_second_tab_offers_reattach_that_adopts_the_session(
        self, clean_session: str, page: Page, browser
    ) -> None:
        """Two tabs, one session — the plain 409 path.

        Tab B was sitting on the picker before tab A started a session, so its
        Start really does 409. Reattach must adopt the LIVE session (the server
        holds it through the detach grace window) rather than leaving the tab
        staring at an error.
        """
        _goto(page, clean_session, "study-session")
        page.locator(".study-start-picker").wait_for(state="visible", timeout=10_000)

        session_id = _start_session(clean_session, "Study focus", origin="study")

        page.evaluate(
            """() => {
              window._reattachDetail = null;
              window.addEventListener('study-session-start', (e) => {
                if (e.detail && e.detail.reattached) window._reattachDetail = e.detail;
              });
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'Something else entirely';
              d.selectedTopic = '';
              d.agent = 'fake';
            }"""
        )
        page.locator("[data-testid='study-start-session']").click()

        error = page.locator(".study-start-picker .picker-error")
        try:
            error.wait_for(state="visible", timeout=10_000)
        except Exception:  # pragma: no cover - diagnostics only
            _diag(page, "no-409-error")
            raise
        assert "already active" in (error.text_content() or "")

        reattach = page.locator(".study-start-picker #study-conflict-reattach")
        reattach.wait_for(state="visible", timeout=5_000)
        page.locator("#study-conflict-reattach").click()

        page.wait_for_function("() => window._reattachDetail !== null", timeout=10_000)
        detail = page.evaluate("() => window._reattachDetail")
        assert detail["studySessionId"] == session_id
        assert detail["reattached"] is True
        assert session_id in detail["wsUrl"]

        state = _study_data(page)
        assert state["sessionActive"] is True
        assert state["conflict"] is None
        assert state["startError"] == ""

    def test_body_double_picker_offers_the_same_recovery(
        self, clean_session: str, page: Page
    ) -> None:
        """The Body Double twin had the identical defect; it gets the identical
        fix — including routing back to the surface that owns the session."""
        _start_session(clean_session, "Study focus", origin="study")
        _goto(page, clean_session, "body-double")

        error = page.locator(".bd-start-picker .picker-error")
        error.wait_for(state="visible", timeout=10_000)
        assert "Study Session" in (error.text_content() or "")

        open_btn = page.locator(".bd-start-picker #bd-conflict-open")
        end_btn = page.locator(".bd-start-picker #bd-conflict-end")
        open_btn.wait_for(state="visible", timeout=5_000)
        end_btn.wait_for(state="visible", timeout=5_000)

        page.locator("#bd-conflict-open").click()
        page.wait_for_timeout(400)
        assert page.evaluate("() => window.Alpine.store('nav').current") == "study-session"

    def test_body_double_picker_can_end_a_foreign_session(
        self, clean_session: str, page: Page
    ) -> None:
        """The Body Double recovery block can release a Study session it does not own."""
        _start_session(clean_session, "Study focus", origin="study")
        _goto(page, clean_session, "body-double")

        page.locator("#bd-start-error").wait_for(state="visible", timeout=10_000)
        page.locator("#bd-conflict-end").wait_for(state="visible", timeout=5_000)
        page.locator("#bd-conflict-end").click()

        page.wait_for_function(
            """async () => {
              const res = await fetch('/api/session/state');
              const state = await res.json();
              return !state.study_session_id;
            }""",
            timeout=10_000,
        )

    def test_body_double_picker_can_reattach_its_own_session(
        self, clean_session: str, page: Page
    ) -> None:
        """The own-origin recovery path adopts the existing Body Double session."""
        session_id = _start_session(clean_session, "Body double focus", origin="body-double")
        _goto(page, clean_session, "body-double")

        page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="bodyDoubleSession()"]');
              const data = window.Alpine.$data(root);
              data.sessionActive = false;
              data.conflictSession = null;
              data.startError = '';
              data.activity = 'Another focus';
              data.agent = 'fake';
            }"""
        )
        page.locator("#bd-start-session").click()
        page.locator("#bd-start-error").wait_for(state="visible", timeout=10_000)
        page.locator("#bd-conflict-reattach").wait_for(state="visible", timeout=5_000)
        page.locator("#bd-conflict-reattach").click()

        page.wait_for_function(
            """(expected) => {
              const root = document.querySelector('[x-data="bodyDoubleSession()"]');
              const data = window.Alpine.$data(root);
              return data.sessionActive === true
                && data.studySessionId === expected
                && !data.conflictSession;
            }""",
            arg=session_id,
            timeout=10_000,
        )


# ---------------------------------------------------------------------------
# Bug B — the park-first modal must be a fork, not a wall
# ---------------------------------------------------------------------------


class TestParkFirstModalDelete:
    def _seed_three(self, base_url: str) -> list[str]:
        questions = ["Topic Alpha", "Topic Bravo", "Topic Charlie"]
        for q in questions:
            status, _ = _post(base_url, "/api/backlog/park", {"question": q})
            assert status == 200, q
        return questions

    def _open_modal(self, page: Page, base_url: str) -> None:
        _goto(page, base_url, "study-session")
        page.locator(".study-start-picker").wait_for(state="visible", timeout=10_000)
        page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'A brand new fourth topic';
              d.selectedTopic = '';
              d.agent = 'fake';
            }"""
        )
        page.locator("[data-testid='study-start-session']").click()
        page.locator(".park-first-overlay").wait_for(state="visible", timeout=10_000)

    def test_modal_can_delete_a_listed_topic_and_undo_it(
        self, clean_session: str, page: Page
    ) -> None:
        self._seed_three(clean_session)
        self._open_modal(page, clean_session)

        assert page.locator(".park-first-item").count() == 3

        delete_buttons = page.locator(".park-first-item .park-first-delete")
        assert delete_buttons.count() == 3, "every listed topic needs a delete action"
        label = delete_buttons.first.get_attribute("aria-label") or ""
        assert label.strip(), "the delete button needs an accessible name"

        delete_buttons.first.click()

        page.wait_for_function(
            "() => document.querySelectorAll('.park-first-item').length === 2",
            timeout=10_000,
        )
        after = _get(clean_session, "/api/backlog")
        assert after["active_count"] == 2, after

        # Soft, therefore undoable — the Parking Lot panel's contract.
        undo = page.locator(".park-first-undo-btn")
        undo.wait_for(state="visible", timeout=5_000)
        undo.click()
        page.wait_for_function(
            "() => document.querySelectorAll('.park-first-item').length === 3",
            timeout=10_000,
        )
        restored = _get(clean_session, "/api/backlog")
        assert restored["active_count"] == 3, restored

    def test_deleting_frees_a_slot_so_the_session_can_start(
        self, clean_session: str, page: Page
    ) -> None:
        """A wall becomes a fork: after deleting, the modal offers the start
        the learner came for."""
        self._seed_three(clean_session)
        self._open_modal(page, clean_session)

        page.locator(".park-first-item .park-first-delete").first.click()
        page.wait_for_function(
            "() => document.querySelectorAll('.park-first-item').length === 2",
            timeout=10_000,
        )

        proceed = page.locator(".park-first-proceed")
        proceed.wait_for(state="visible", timeout=5_000)
        proceed.click()

        page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              return window.Alpine.$data(root).sessionActive === true;
            }""",
            timeout=20_000,
        )


# ---------------------------------------------------------------------------
# Bug B, second half — the configured-topic list is not a cage
# ---------------------------------------------------------------------------


class TestConfiguredTopicEscapeHatch:
    def test_picker_names_the_config_source_and_advertises_free_text(
        self, clean_session: str, page: Page
    ) -> None:
        """The dropdown is capped at three by config, and there is no route to
        edit it. The picker must at least say where the list comes from and
        that typing anything is allowed."""
        _goto(page, clean_session, "study-session")
        page.locator(".study-start-picker").wait_for(state="visible", timeout=10_000)

        page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              return (d.studyOptions.topics || []).length === 3;
            }""",
            timeout=10_000,
        )

        hint = page.locator("#topic-source-hint")
        hint.wait_for(state="visible", timeout=5_000)
        text = (hint.text_content() or "").lower()
        assert "config.yaml" in text, text
        assert "type" in text, text

    def test_a_topic_outside_the_config_list_can_be_started(
        self, clean_session: str, page: Page
    ) -> None:
        """The escape hatch has to actually work, not merely be described."""
        _goto(page, clean_session, "study-session")
        page.locator(".study-start-picker").wait_for(state="visible", timeout=10_000)

        page.locator("#topic-input").fill("Kafka consumer groups")
        page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              window.Alpine.$data(root).agent = 'fake';
            }"""
        )
        page.wait_for_function(
            "() => !document.querySelector('[data-testid=study-start-session]').disabled",
            timeout=5_000,
        )
        page.locator("[data-testid='study-start-session']").click()

        page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              return window.Alpine.$data(root).sessionActive === true;
            }""",
            timeout=20_000,
        )
        state = _get(clean_session, "/api/session/state")
        assert state["topic"] == "Kafka consumer groups", state
