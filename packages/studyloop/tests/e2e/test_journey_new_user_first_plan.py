"""Cold-start E2E: a brand-new learner builds their first study plan.

This is deliberately NOT another coverage pass over the plan panel — the phase
journey in ``test_journey_study_plan.py`` already does that with tidy fixture
data. This file exists because the panel's first real user will be someone who
has never seen it, working from a genuine situation, and that path has different
failure modes:

  * the empty state is the FIRST thing they see, so it has to invite an action
    rather than look broken;
  * their own words are long, messy and full of characters a naive template
    breaks on — course names with pipes and slashes, a course that has not been
    released yet, apostrophes;
  * they do not know the decomposition yet, which is the whole reason the
    brain-dump box leads the form;
  * nothing in the database has seeded anything, so every "seeded from history"
    path must degrade gracefully rather than error.

The learner modelled here is real: general programming understanding with a
little hands-on practice, now following the ArjanCodes course path, with several
non-course topics running alongside. Their course list intentionally includes an
unreleased course, because "I plan to take this when it exists" is a normal thing
to put in a plan and must not be silently dropped or treated as available.

Run:
    cd packages/studyloop
    uv run pytest tests/e2e/test_journey_new_user_first_plan.py -m e2e
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402
from e2e._env import TestWorld as E2ETestWorld  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18624  # unique; 18611 is the developer's live server, 18616 the plan journey
LEGACY_WIZARD_REASON = (
    "The structured wizard was replaced by the conversational Architect; "
    "create, approve, reload, and revise are covered by test_agentic_planning_browser.py"
)

# ---------------------------------------------------------------------------
# The learner's own words. Kept verbatim rather than sanitised, because the
# awkward characters are the point: `1/3`, `|`, and an apostrophe all pass
# through a Markdown document, a SQLite row and a mermaid label on the way to
# the screen, and any one of them could break a naive template.
# ---------------------------------------------------------------------------

BRAIN_DUMP = (
    "I understand programming concepts in general and I've done a little "
    "hands-on work, but I've never been taught software design properly. "
    "I'm working through the ArjanCodes path: Next-Level Python first, then "
    "Software Design Mastery 1/3 | CORE DESIGNER, then 2/3 | SYSTEM DESIGNER, "
    "and 3/3 | MASTER DESIGNER once it's released. After those I want The "
    "Software Designer Mindset and Pythonic Patterns. I also own Domain "
    "Modeling Fundamentals and Design Wins and haven't decided where they fit. "
    "Alongside the courses I need agentic workflows with orchestration, "
    "knowledge graphs, ontology services, and Python testing/TDD — those aren't "
    "courses, they're things I'll be expected to build. I don't know how to "
    "break this into steps yet, which is why I'm writing it here instead of "
    "filling in a form."
)

PLAN_TITLE = "From writing Python to designing software"
PLAN_WHY = (
    "I want to stop assembling scripts and start designing systems on purpose, "
    "so I can be trusted with a service end to end."
)
PLAN_TOPICS = (
    "Next-Level Python, software design principles, domain modelling, "
    "Pythonic patterns, agentic workflows with orchestration, knowledge graphs, "
    "ontology services, Python testing and TDD"
)
PLAN_SUCCESS = (
    "I can justify a design decision out loud without hedging; "
    "I can write a test before the code it covers and not delete it later"
)
# Milestone concepts are the REAL section names from the learner's course vault
# (~/Obsidian/Personal/Study/ArjanCodes), not invented stand-ins. That matters:
# these are the strings `studyloop content ingest` derives concepts from, so a
# plan written against them lines up with the mastery graph and the review deck
# instead of creating a second, parallel vocabulary that never joins up.
#
# The unreleased course is included on purpose — see the module docstring.
PLAN_MILESTONES = (
    "Next-Level Python (type-annotations, iterators, generators, context-managers)\n"
    "Next-Level Python (next-level-functions, next-level-classes, concurrent-programming)\n"
    "Software Design Mastery 1/3 | CORE DESIGNER (core-level-1, core-level-2, core-level-3)\n"
    "Software Design Mastery 2/3 | SYSTEM DESIGNER (system-level-1, system-level-2)\n"
    "Software Design Mastery 3/3 | MASTER DESIGNER — not yet released\n"
    "Domain Modeling Fundamentals (domain-modeling, domain-implementation)\n"
    "The Software Designer Mindset (tradeoffs, refactoring, design-wins)\n"
    "Pythonic Patterns (strategy, observer, composition over inheritance)\n"
    "Python testing and TDD (red-green-refactor, test doubles, fixtures)\n"
    "Agentic workflows with orchestration (tool use, state, retries)\n"
    "Knowledge graphs and ontology services (triples, inference, domain vocabulary)"
)


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


@pytest.fixture(scope="module")
def test_world(tmp_path_factory: pytest.TempPathFactory) -> E2ETestWorld:
    """A genuinely empty world — no seeded plans, no session history.

    The point of this journey is the cold start, so nothing may be pre-created.
    """
    root = tmp_path_factory.mktemp("new-user-world")
    return build_test_world(root, WEB_PORT, fake_agent=True)


@pytest.fixture(scope="module")
def running_server(test_world: E2ETestWorld):
    server = start_server(test_world)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def page(browser, running_server: RunningServer):
    """One page across the journey — a real user does not reload between steps."""
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{running_server.base_url}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=15_000)
    # Hash navigation alone does not move this SPA; the nav store does.
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
    page.wait_for_timeout(500)
    try:
        yield page
    finally:
        context.close()


def _fill(page: Page, testid: str, value: str) -> None:
    """Fill an Alpine-bound field and let x-model flush."""
    field = page.locator(f'[data-testid="{testid}"]')
    field.wait_for(state="visible", timeout=8000)
    field.fill(value)
    field.dispatch_event("input")


# ---------------------------------------------------------------------------


def test_phase1_first_screen_invites_an_action(page: Page) -> None:
    """Phase 1 — with nothing saved, the panel must not look broken.

    An empty list and an empty content column are indistinguishable from a
    failed load. The first screen a new user sees has to name the next action.
    """
    try:
        empty = page.locator('[data-testid="sidebar-plans-empty"]')
        empty.wait_for(state="visible", timeout=10_000)
        text = empty.inner_text().lower()

        # It must point at the control that starts the work, by name.
        assert "new plan" in text, f"empty state does not name the New plan action: {text!r}"

        # And that control must actually be there and usable, not merely mentioned.
        new_btn = page.locator('[data-testid="plan-new"]')
        new_btn.wait_for(state="visible", timeout=8000)
        assert new_btn.is_enabled(), "New plan button is present but disabled on a cold start"

        # No plan detail should be showing — there is no plan to show.
        assert (
            page.locator('[data-testid="plan-detail"]').count() == 0
            or not page.locator('[data-testid="plan-detail"]').is_visible()
        ), "a plan detail pane is visible before any plan exists"
    except Exception:
        _diag(page, "newuser-phase1-fail")
        raise


def test_phase2_braindump_leads_the_architect_capture(page: Page) -> None:
    """Phase 2 — the free-text box is reachable before optional context.

    A learner who knew the decomposition would not need the tool. The brain-dump
    field exists so they can describe the situation in their own words. It must
    be the primary visible input, while optional notes remain secondary.
    """
    try:
        page.locator('[data-testid="plan-new"]').click()
        capture = page.locator('[data-testid="architect-capture"]')
        capture.wait_for(state="visible", timeout=8000)

        dump = page.locator('[data-testid="architect-brain-dump"]')
        dump.wait_for(state="visible", timeout=8000)

        ordered_first = page.evaluate(
            """() => {
                const dump = document.querySelector('[data-testid="architect-brain-dump"]');
                const context = document.querySelector('[data-testid="architect-context-text"]');
                if (!dump || !context) return false;
                // Node.DOCUMENT_POSITION_FOLLOWING === 4
                return !!(dump.compareDocumentPosition(context) & 4);
            }"""
        )
        assert ordered_first, "brain-dump field does not precede optional study context"
        dump.fill(BRAIN_DUMP)
        assert dump.input_value() == BRAIN_DUMP
    except Exception:
        _diag(page, "newuser-phase2-fail")
        raise


@pytest.mark.skip(reason=LEGACY_WIZARD_REASON)
def test_phase3_the_learners_own_words_survive_the_round_trip(page: Page) -> None:
    """Phase 3 — create the plan from realistic, awkward input.

    `1/3`, `|` and an apostrophe all traverse a Markdown document, a SQLite row
    and the rendered DOM. Any of them could be swallowed by a naive template, and
    a course name silently mangled is worse than a visible error because the
    learner will not notice until they cannot find it again.
    """
    try:
        _fill(page, "plan-field-braindump", BRAIN_DUMP)
        _fill(page, "plan-field-title", PLAN_TITLE)
        _fill(page, "plan-field-why", PLAN_WHY)
        _fill(page, "plan-field-topics", PLAN_TOPICS)
        _fill(page, "plan-field-success", PLAN_SUCCESS)
        _fill(page, "plan-field-milestones", PLAN_MILESTONES)

        page.locator('[data-testid="plan-create-submit"]').click()

        detail = page.locator('[data-testid="plan-detail"]')
        detail.wait_for(state="visible", timeout=15_000)

        title = page.locator('[data-testid="plan-detail-title"]').inner_text()
        assert PLAN_TITLE in title, f"plan title not shown after create: {title!r}"

        # No error banner: a create that half-worked must not look successful.
        err = page.locator('[data-testid="plan-error"]')
        if err.count() and err.is_visible():
            raise AssertionError(f"plan created with an error banner showing: {err.inner_text()!r}")

        body = page.locator('[data-testid="plan-markdown"]').inner_text()
        for fragment in (
            "Next-Level Python",
            "CORE DESIGNER",
            "SYSTEM DESIGNER",
            "MASTER DESIGNER",
            "Pythonic Patterns",
            "ontology services",
        ):
            assert fragment in body, f"{fragment!r} missing from the rendered plan document"

        # The pipe and the fraction are the characters most likely to be eaten.
        assert "1/3" in body or "1 / 3" in body, "course numbering was lost in the round trip"

        # Real course section names must survive verbatim. These are the strings
        # the content pipeline derives concepts from, so a hyphenated identifier
        # mangled here (or "helpfully" title-cased) silently decouples the plan
        # from the mastery graph that is supposed to track it.
        for section in ("type-annotations", "context-managers", "core-level-1", "domain-modeling"):
            assert section in body, (
                f"course section name {section!r} did not survive the round trip"
            )
    except Exception:
        _diag(page, "newuser-phase3-fail")
        raise


@pytest.mark.skip(reason=LEGACY_WIZARD_REASON)
def test_phase4_plan_appears_in_the_sidebar_with_progress(page: Page) -> None:
    """Phase 4 — the plan joins the left-pane list and the empty state retires.

    A plan that exists but is not listed cannot be returned to, which for this
    feature is the same as not existing.
    """
    try:
        page.locator('[data-testid="sidebar-plans"]').wait_for(state="visible", timeout=8000)
        listed = page.locator('[data-testid="sidebar-plans"]').inner_text()
        assert PLAN_TITLE in listed, f"new plan absent from the sidebar list: {listed!r}"

        empty = page.locator('[data-testid="sidebar-plans-empty"]')
        assert not (empty.count() and empty.is_visible()), (
            "empty state is still showing although a plan now exists"
        )

        progress = page.locator('[data-testid="plan-detail-progress"]')
        progress.wait_for(state="visible", timeout=8000)
        # Nine milestones, none done: progress must read as zero-of-nine, not blank.
        assert any(ch.isdigit() for ch in progress.inner_text()), (
            f"progress indicator carries no numbers: {progress.inner_text()!r}"
        )
    except Exception:
        _diag(page, "newuser-phase4-fail")
        raise


@pytest.mark.skip(reason=LEGACY_WIZARD_REASON)
def test_phase5_a_reload_still_finds_the_plan(page: Page) -> None:
    """Phase 5 — the plan survives a browser reload.

    This is the defect class a phase journey misses: the suite navigates with
    `go()` after acting, so a store that only populates on user action still
    passes. A real learner closes the tab and comes back, and an empty sidebar
    then reads as lost work.
    """
    try:
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.Alpine", timeout=15_000)
        page.evaluate("() => window.Alpine.store('nav').go('study-plans')")

        page.wait_for_function(
            """(t) => {
                const el = document.querySelector('[data-testid="sidebar-plans"]');
                return !!(el && el.innerText.includes(t));
            }""",
            arg=PLAN_TITLE,
            timeout=15_000,
        )
    except Exception:
        _diag(page, "newuser-phase5-fail")
        raise


@pytest.mark.skip(reason=LEGACY_WIZARD_REASON)
def test_phase6_evaluation_is_honest_with_no_history(page: Page) -> None:
    """Phase 6 — evaluating a brand-new plan must not invent progress.

    `seed_from_history` reads the sessions DB, and on a cold start there is
    nothing there. The evaluation has to say so rather than fabricate a verdict
    or fail with a stack trace — an encouraging but baseless verdict is the worst
    outcome, because it teaches the learner to distrust the feature.
    """
    try:
        page.locator('[data-testid="sidebar-plans"]').get_by_text(PLAN_TITLE).first.click()
        page.locator('[data-testid="plan-detail"]').wait_for(state="visible", timeout=10_000)

        start = page.locator('[data-testid="plan-eval-start"]')
        start.wait_for(state="visible", timeout=8000)
        start.click()

        page.locator('[data-testid="plan-evaluation"]').wait_for(state="visible", timeout=15_000)
        verdict = page.locator('[data-testid="plan-verdict"]').inner_text().strip()
        assert verdict, "evaluation rendered with an empty verdict"

        err = page.locator('[data-testid="plan-error"]')
        assert not (err.count() and err.is_visible()), (
            f"evaluation errored on a cold start: {err.inner_text() if err.count() else ''!r}"
        )
    except Exception:
        _diag(page, "newuser-phase6-fail")
        raise
