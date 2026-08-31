"""Representative user-journey E2E for the three topic exercise formats.

Drives the REAL Alpine/HTMX UI served by ``studyloop web``: no mocked API, no
fictional selectors.

The journey mirrors what a learner actually does:

  Phase 1  A plan exists; its Exercises section is present and honest when empty
  Phase 2  Generate exercises for the plan's next milestone
  Phase 3  All three format tabs are present and switchable
  Phase 4  Blank slate: requirements only, empty editor, no supplied code
  Phase 5  Submit a weak blank-slate attempt → scored, and improvements come
           back as QUESTIONS, never as the answer
  Phase 6  Completion: the same editor pre-seeded with partial code
  Phase 7  Submitting the scaffold unchanged scores 0 — supplied code earns
           nothing (the invariant the shared pipeline exists to enforce)
  Phase 8  Finishing the completion scores full, with criteria marked `given`
  Phase 9  Multiple choice: answer wrong → mentored from the misconception,
           without the correct option being named
  Phase 10 Answer right → full score
  Phase 11 The answer key never reaches the browser (network-level assertion)

Run:
    cd packages/studyloop
    uv run pytest tests/e2e/test_journey_exercises.py -m e2e

QUARANTINED FOR 0.1.0 — the panel this journey drives does not exist.

Exercises ship in 0.1.0 as an API and a CLI surface only; no web panel and no
LLM generation. Every one of the five testids this file drives
(``exercise-refresh``, ``exercises-section``, ``exercise-generate``,
``exercise-format``, ``exercise-submit``) has zero occurrences in
web/static, and the string "exercise" appears nowhere in the SPA's HTML or JS.
All 11 phases were red for that one reason: 3 failed and 8 errored at fixture
setup.

Phase 11 is quarantined with the rest, which the remediation brief did not
anticipate, for two verified reasons:

  1. It cannot be kept live. It is not an API test — its ``authored_set``
     fixture creates the set through the real API and then OPENS IT IN THE UI
     (line ~356, ``page.locator('[data-testid="exercise-refresh"]').click()``),
     so it errors at setup like the panel phases. Its assertion reads
     ``page._seen_bodies``, i.e. traffic the panel generated; with no panel
     there is no traffic and ``assert bodies`` fails.

  2. Nothing is lost. The answer-key guarantee is covered at the API boundary,
     more strongly than here, by test_web_exercises.py:
     ``test_attempt_payload_withholds_the_answer`` and
     ``test_whole_response_body_is_free_of_the_answer_key``, which asserts
     ``'"correct"' not in text`` across the WHOLE response body, plus the
     author-side counterparts proving ``include_reference=true`` still works.
     Those are deterministic and need no browser. This phase only inspected
     whatever the panel happened to request.

Un-quarantine when the exercises panel is built: delete the pytestmark and
re-run. Do not "fix" these tests against a panel that is absent — that is how
a green suite starts certifying a surface nobody shipped.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import launch_env, shutdown  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skip(
        reason=(
            "quarantined panel journey — the exercises web panel is not part of "
            "0.1.0. All five testids this file drives have zero occurrences in "
            "web/static, so every phase errors at setup. Answer-key privacy is "
            "covered at the API boundary by test_web_exercises.py "
            "(test_whole_response_body_is_free_of_the_answer_key). Un-quarantine "
            "when the panel exists; see the module docstring for the full reason."
        )
    ),
]

WEB_PORT = 18613

PLAN_TITLE = "Master Python Closures"
PLAN_ID = "master-python-closures"

REFERENCE = """def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment"""

#: The distinctive reference-solution line that must never reach the learner.
HIDDEN_LINE = "nonlocal count"
#: The correct multiple-choice option text — must never appear in mentoring.
CORRECT_CHOICE = "A cell object referenced by the function"


def _diag(page: Page | None, name: str) -> None:
    """Best-effort failure artefacts (screenshot + HTML)."""
    if page is None:
        return
    RESULTS.mkdir(exist_ok=True)
    stamp = int(time.time())
    try:
        page.screenshot(path=str(RESULTS / f"{name}-{stamp}.png"), full_page=True)
        (RESULTS / f"{name}-{stamp}.html").write_text(page.content())
    except Exception:
        pass


def _post(base: str, path: str, payload: dict) -> dict:
    """POST JSON to the running server (fixture setup only, never assertions)."""
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


@pytest.fixture(scope="module")
def state_dirs():
    """Isolated root for the whole journey so it touches nothing real."""
    root = Path(tempfile.mkdtemp(prefix="studyloop-e2e-exercises-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def running_server(state_dirs: Path):
    """Real subprocess server, fully isolated via the shared e2e env helper.

    ``launch_env`` is used rather than ``start_web_server`` directly because it
    also redirects ``session_db`` and ``STUDYLOOP_SESSION_DIR``. Creating a plan
    writes an index row to the sessions DB, so without that redirect this
    journey would mutate the learner's real database — and contend on it with
    every other e2e module.

    The exercises directory needs no separate redirect: it defaults to
    ``<plans_dir>/exercises``, and ``launch_env`` already isolates the plans dir.
    """
    env = launch_env(state_dirs, WEB_PORT)
    base = env.base_url
    # A plan is the container for exercises, so seed one through the real API.
    _post(
        base,
        "/api/plans",
        {
            "title": PLAN_TITLE,
            "answers": {
                "why": "Ship a decorator-based retry layer in the team's ETL package.",
                "success": ["Write a parametrised decorator from memory"],
                "topics": ["python"],
                "milestones": ["Closures (concepts: closures, cell variables)"],
            },
        },
    )
    try:
        yield base
    finally:
        shutdown(env)


@pytest.fixture(scope="module")
def page(browser, running_server: str):
    """One page for the whole journey — state carries across phases."""
    context = browser.new_context()
    page = context.new_page()
    # Record every /api/exercises response so Phase 11 can prove, at the
    # network boundary, that the answer key never reached the browser.
    page._seen_bodies = []  # type: ignore[attr-defined]

    def _capture(response) -> None:
        if "/api/exercises" not in response.url:
            return
        with contextlib.suppress(Exception):
            page._seen_bodies.append((response.url, response.text()))  # type: ignore[attr-defined]

    page.on("response", _capture)
    page.goto(f"{running_server}/")
    page.wait_for_load_state("domcontentloaded")
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
    page.wait_for_timeout(600)
    try:
        yield page
    finally:
        context.close()


def _submit_and_wait(page: Page) -> None:
    """Click submit and wait for the review block to carry a score."""
    page.locator('[data-testid="exercise-submit"]').click()
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="exercise-score"]');
            return el && el.offsetParent !== null && /\\d+\\/100/.test(el.textContent);
        }""",
        timeout=15000,
    )


def _score(page: Page) -> int:
    text = page.locator('[data-testid="exercise-score"]').inner_text()
    return int(text.split("/")[0].strip())


def _mentoring(page: Page) -> list[str]:
    return [
        item.strip()
        for item in page.locator('[data-testid="exercise-mentoring"] li').all_inner_texts()
    ]


def _criteria(page: Page) -> dict[str, str]:
    """Map criterion title → status, read from the rendered review list."""
    return page.evaluate(
        """() => {
            const root = document.querySelector('[data-testid="exercise-criteria"]');
            if (!root) return {};
            const out = {};
            for (const li of root.querySelectorAll('li')) {
                const title = li.querySelector('span');
                const status = li.querySelector('small');
                if (title && status) out[title.textContent.trim()] = status.textContent.trim();
            }
            return out;
        }"""
    )


def _set_editor(page: Page, value: str) -> None:
    field = page.locator('[data-testid="exercise-editor"]')
    field.wait_for(state="visible", timeout=8000)
    field.fill(value)
    field.dispatch_event("input")


def test_phase1_plan_view_has_an_exercises_section(page: Page) -> None:
    """Phase 1 — the Exercises section renders inside the plan, empty and honest."""
    try:
        page.locator('[data-testid="plan-detail"]').wait_for(state="visible", timeout=15000)
        assert PLAN_TITLE in page.locator('[data-testid="plan-detail-title"]').inner_text()

        panel = page.locator('[data-testid="exercises-panel"]')
        panel.wait_for(state="visible", timeout=10000)
        assert "Exercises" in panel.inner_text()

        # The bare `header` element selector in the app chrome sets display:flex,
        # which stacked the heading and its description side by side — the
        # heading read as the first word of the paragraph. Assert on geometry so
        # the reset cannot be dropped silently.
        layout = page.evaluate(
            """() => {
                const head = document.querySelector('.exercises-header');
                if (!head) return null;
                const h = head.querySelector('h4');
                const p = head.querySelector('p');
                if (!h || !p) return null;
                const hb = h.getBoundingClientRect();
                const pb = p.getBoundingClientRect();
                return {display: getComputedStyle(head).display,
                        headingBottom: hb.bottom, paraTop: pb.top};
            }"""
        )
        assert layout is not None, "exercises header missing"
        assert layout["display"] != "flex", "header is still a flex row"
        assert layout["paraTop"] >= layout["headingBottom"] - 1, (
            f"description is not below the heading: {layout}"
        )

        # Empty state must say so rather than render a silent blank list.
        page.locator('[data-testid="exercises-empty"]').wait_for(state="visible", timeout=10000)
    except Exception:
        _diag(page, "exercises-phase1")
        raise


def test_phase2_generate_exercises_for_the_next_milestone(page: Page) -> None:
    """Phase 2 — one click turns the plan's next milestone into an exercise set."""
    try:
        page.locator('[data-testid="exercise-generate"]').click()
        page.locator('[data-testid="exercise-detail"]').wait_for(state="visible", timeout=15000)

        items = page.locator('[data-testid="exercise-set-list"] .exercise-set-item')
        assert items.count() >= 1, "no exercise set appeared after generating"
        assert "Closures" in items.first.inner_text()

        # The drafted set is honestly reported as not fully authored: the
        # generator invents no rubric checks and no quiz answers.
        blockers = page.locator('[data-testid="exercise-blockers"]')
        blockers.wait_for(state="visible", timeout=8000)
        text = blockers.inner_text().lower()
        assert "check" in text or "multiple-choice" in text, text
    except Exception:
        _diag(page, "exercises-phase2")
        raise


def test_phase3_all_three_formats_are_offered(page: Page) -> None:
    """Phase 3 — the three shapes are three tabs over one attempt surface."""
    try:
        tabs = page.locator('[data-testid="exercise-tabs"]')
        tabs.wait_for(state="visible", timeout=8000)
        for kind in ("blank_slate", "completion", "multiple_choice"):
            tab = page.locator(f'[data-testid="exercise-tab-{kind}"]')
            assert tab.count() == 1, f"missing tab for {kind}"
            assert tab.is_visible(), f"tab for {kind} not visible"

        # Switching format must not navigate away or re-mount the panel.
        page.locator('[data-testid="exercise-tab-completion"]').click()
        page.wait_for_timeout(250)
        assert page.locator('[data-testid="exercise-detail"]').is_visible()
        page.locator('[data-testid="exercise-tab-blank_slate"]').click()
        page.wait_for_timeout(250)
        assert (
            page.locator('[data-testid="exercise-tab-blank_slate"]').get_attribute("aria-selected")
            == "true"
        )
    except Exception:
        _diag(page, "exercises-phase3")
        raise


@pytest.fixture(scope="module")
def authored_set(running_server: str, page: Page):
    """A fully-authored set, created through the real API, then opened in the UI.

    The drafted set from Phase 2 deliberately has no rubric checks (nothing is
    invented), so scoring behaviour needs a set an author completed.
    """
    created = _post(
        running_server,
        "/api/exercises",
        {
            "topic": "closure state",
            "plan_id": PLAN_ID,
            "concepts": ["closures"],
            "requirements": [
                "make_counter() returns a callable",
                "Each returned callable counts its own calls independently",
            ],
            "rubric": [
                {
                    "title": "Defines the factory function",
                    "weight": 1,
                    "check": r"def\s+make_counter",
                    "ask": "What has to exist before anything can be returned",
                },
                {
                    "title": "Keeps state in the enclosing scope",
                    "weight": 3,
                    "check": r"nonlocal\s+\w+",
                    "ask": "Where does the count have to live to survive between calls",
                },
            ],
            "reference_solution": REFERENCE,
            "questions": [
                {
                    "prompt": "What keeps a closure's variable alive?",
                    "choices": [
                        {
                            "text": "The global namespace",
                            "why": "globals are shared, so two counters would collide",
                        },
                        {"text": CORRECT_CHOICE, "correct": True},
                        {"text": "Nothing, it is copied by value", "why": "values are rebound"},
                    ],
                }
            ],
        },
    )
    set_id = created["set"]["set_id"]
    page.locator('[data-testid="exercise-refresh"]').click()
    page.wait_for_function(
        """(id) => !!document.querySelector('[data-testid="exercise-set-' + id + '"]')""",
        arg=set_id,
        timeout=15000,
    )
    page.locator(f'[data-testid="exercise-set-{set_id}"]').click()
    page.wait_for_timeout(600)
    return set_id


def test_phase4_blank_slate_supplies_requirements_but_no_code(
    page: Page, authored_set: str
) -> None:
    """Phase 4 — blank slate means requirements only: the learner writes it all."""
    try:
        page.locator('[data-testid="exercise-tab-blank_slate"]').click()
        page.wait_for_timeout(300)

        requirements = page.locator('[data-testid="exercise-requirements"] li')
        assert requirements.count() == 2, requirements.all_inner_texts()

        # The editor starts empty, and the scaffold label says why.
        assert page.locator('[data-testid="exercise-editor"]').input_value() == ""
        scaffold = page.locator('[data-testid="exercise-scaffold"]').inner_text().lower()
        assert "no starting code" in scaffold, scaffold

        # The rubric is visible as a brief — titles and weights, no answer key.
        rubric = page.locator('[data-testid="exercise-rubric"]').inner_text()
        assert "Keeps state in the enclosing scope" in rubric
        assert "nonlocal" not in rubric, "rubric check pattern leaked into the UI"
    except Exception:
        _diag(page, "exercises-phase4")
        raise


def test_phase5_weak_attempt_is_scored_and_mentored_with_questions(
    page: Page, authored_set: str
) -> None:
    """Phase 5 — the review scores the attempt, then asks rather than tells."""
    try:
        page.locator('[data-testid="exercise-tab-blank_slate"]').click()
        page.wait_for_timeout(250)
        _set_editor(page, "def make_counter():\n    pass\n")
        _submit_and_wait(page)

        # 1 of 4 rubric weight.
        assert _score(page) == 25, page.locator('[data-testid="exercise-score"]').inner_text()
        assert "struggling" in page.locator('[data-testid="exercise-band"]').inner_text().lower()

        statuses = _criteria(page)
        assert statuses.get("Defines the factory function") == "met", statuses
        assert statuses.get("Keeps state in the enclosing scope") == "unmet", statuses

        mentoring = _mentoring(page)
        assert mentoring, "a failing attempt produced no mentoring"
        assert all(item.endswith("?") for item in mentoring), mentoring

        # The Socratic guarantee, asserted on the rendered page: the reference
        # solution is never handed over as the improvement.
        body = page.locator('[data-testid="exercise-review"]').inner_text()
        assert HIDDEN_LINE not in body, "reference solution leaked into the review UI"
        assert "count += 1" not in body
    except Exception:
        _diag(page, "exercises-phase5")
        raise


def test_phase6_completion_seeds_the_editor_with_partial_code(
    page: Page, authored_set: str
) -> None:
    """Phase 6 — same surface, now pre-filled: the scaffold is the parameter."""
    try:
        page.locator('[data-testid="exercise-tab-completion"]').click()
        page.wait_for_timeout(400)

        starter = page.locator('[data-testid="exercise-editor"]').input_value()
        assert starter.strip(), "completion editor was not seeded with starter code"
        assert "TODO" in starter, starter
        assert "def make_counter" in starter, starter
        # The hidden work must stay hidden, or there is nothing to complete.
        assert HIDDEN_LINE not in starter, "completion scaffold gave away the answer"

        scaffold = page.locator('[data-testid="exercise-scaffold"]').inner_text().lower()
        assert "supplied" in scaffold, scaffold

        # Requirements are identical to the blank slate — one authored task.
        assert page.locator('[data-testid="exercise-requirements"] li').count() == 2
    except Exception:
        _diag(page, "exercises-phase6")
        raise


def test_phase7_submitting_the_scaffold_unchanged_earns_nothing(
    page: Page, authored_set: str
) -> None:
    """Phase 7 — supplied code is never credited. The core scoring invariant."""
    try:
        page.locator('[data-testid="exercise-tab-completion"]').click()
        page.wait_for_timeout(400)
        # Deliberately submit the starter code exactly as handed over.
        _submit_and_wait(page)

        assert _score(page) == 0, page.locator('[data-testid="exercise-score"]').inner_text()

        given = page.locator('[data-testid="exercise-given"]')
        given.wait_for(state="visible", timeout=8000)
        assert "excluded from your score" in given.inner_text()

        statuses = _criteria(page)
        assert statuses.get("Defines the factory function") == "given", statuses

        warnings = page.locator('[data-testid="exercise-warnings"]').inner_text().lower()
        assert "starter code" in warnings, warnings

        mentoring = _mentoring(page)
        assert any("not do yet" in item for item in mentoring), mentoring
    except Exception:
        _diag(page, "exercises-phase7")
        raise


def test_phase8_finishing_the_completion_scores_on_the_learners_work(
    page: Page, authored_set: str
) -> None:
    """Phase 8 — a finished completion scores full, crediting only the delta."""
    try:
        page.locator('[data-testid="exercise-tab-completion"]').click()
        page.wait_for_timeout(400)
        _set_editor(page, REFERENCE)
        _submit_and_wait(page)

        assert _score(page) == 100, page.locator('[data-testid="exercise-score"]').inner_text()
        assert "strong" in page.locator('[data-testid="exercise-band"]').inner_text().lower()
        assert "completion" in page.locator('[data-testid="exercise-review-kind"]').inner_text()

        # The supplied signature is still `given`, not `met` — the score is 100
        # because everything assessable passed, not because credit was inherited.
        statuses = _criteria(page)
        assert statuses.get("Defines the factory function") == "given", statuses
        assert statuses.get("Keeps state in the enclosing scope") == "met", statuses
    except Exception:
        _diag(page, "exercises-phase8")
        raise


def test_phase9_wrong_multiple_choice_is_mentored_from_the_misconception(
    page: Page, authored_set: str
) -> None:
    """Phase 9 — a wrong answer earns a question about the reasoning, not the key."""
    try:
        page.locator('[data-testid="exercise-tab-multiple_choice"]').click()
        page.wait_for_timeout(400)

        question = page.locator('[data-testid="exercise-question-0"]')
        question.wait_for(state="visible", timeout=8000)
        assert "What keeps a closure's variable alive?" in question.inner_text()
        assert question.locator("label").count() == 3

        # Each input must be self-describing, not just visually adjacent to its
        # text: a screen reader reading the control alone still hears the option.
        labels = page.evaluate(
            """() => [...document.querySelectorAll(
                '[data-testid^="exercise-choice-0-"]'
            )].map(el => el.getAttribute('aria-label'))"""
        )
        assert len(labels) == 3, labels
        assert all(item and item.strip() for item in labels), labels
        assert any("global namespace" in item for item in labels), labels

        # Pick the global-namespace distractor.
        page.locator('[data-testid="exercise-choice-0-0"]').click()
        page.wait_for_timeout(250)
        _submit_and_wait(page)

        assert _score(page) == 0, page.locator('[data-testid="exercise-score"]').inner_text()

        mentoring = _mentoring(page)
        assert mentoring, "a wrong answer produced no mentoring"
        blob = " ".join(mentoring)
        assert "globals are shared" in blob, blob
        assert blob.strip().endswith("?")
        # The right answer must not be announced.
        assert CORRECT_CHOICE not in blob, "the correct option was handed over"
        review_text = page.locator('[data-testid="exercise-review"]').inner_text()
        assert CORRECT_CHOICE not in review_text, review_text
    except Exception:
        _diag(page, "exercises-phase9")
        raise


def test_phase10_correct_multiple_choice_scores_full(page: Page, authored_set: str) -> None:
    """Phase 10 — the right answer scores 100 and still pushes understanding."""
    try:
        page.locator('[data-testid="exercise-tab-multiple_choice"]').click()
        page.wait_for_timeout(400)
        # Clear the previous pick, then choose the cell-object option.
        page.locator('[data-testid="exercise-choice-0-1"]').click()
        page.wait_for_timeout(250)
        _submit_and_wait(page)

        assert _score(page) == 100, page.locator('[data-testid="exercise-score"]').inner_text()
        assert "strong" in page.locator('[data-testid="exercise-band"]').inner_text().lower()
        mentoring = _mentoring(page)
        assert mentoring and mentoring[0].endswith("?"), mentoring
    except Exception:
        _diag(page, "exercises-phase10")
        raise


def test_phase11_answer_key_never_crossed_the_network(page: Page, authored_set: str) -> None:
    """Phase 11 — the strongest form of the guarantee, at the network boundary.

    Asserting on the DOM proves the answer was not *displayed*. Asserting on
    every ``/api/exercises`` response body proves it was never *sent*, so it
    could not be recovered from devtools, a cached response, or a future UI
    change that renders more of the payload.
    """
    try:
        bodies = page._seen_bodies  # type: ignore[attr-defined]
        assert bodies, "no /api/exercises responses were captured"

        offenders = [
            url
            for url, body in bodies
            if "include_reference" not in url
            and (HIDDEN_LINE in body or f'"{CORRECT_CHOICE}", "correct"' in body)
        ]
        assert not offenders, f"answer key crossed the network: {offenders}"

        # And the correct-flag field itself is absent from attempt payloads.
        for url, body in bodies:
            if url.endswith("/api/exercises") or "include_reference" in url:
                continue
            if '"choices"' in body:
                assert '"correct":' not in body, f"correct flag shipped in {url}"
    except Exception:
        _diag(page, "exercises-phase11")
        raise
