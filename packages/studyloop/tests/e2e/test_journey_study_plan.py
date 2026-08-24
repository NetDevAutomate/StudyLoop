"""Representative user-journey E2E for Study Plans — drives the REAL web UI.

Every assertion runs against the actual Alpine/HTMX UI served by
``studyloop web``; there are no fictional selectors and no mocked API.

The journey mirrors what a learner actually does:

  Phase 1  Left pane exposes a Study Plan section (empty state honest)
  Phase 2  Seed a digest-approved plan through the real compatibility API
  Phase 3  The plan appears in the left-pane list, with progress
  Phase 4  The plan document renders as *structured* Markdown — real
           headings, task lists, and a table in the DOM, not a code dump
  Phase 5  Evaluate at all three checkpoints (start / mid / end)
  Phase 6  Record a checkpoint and see it land in the rendered document
  Phase 7  Milestone progress is read-only and evidence-driven
  Phase 8  A ready plan can be activated from the reader
  Phase 9  An incomplete plan is refused activation, with reasons

Run:
    cd packages/studyloop
    uv run pytest tests/e2e/test_journey_study_plan.py -m e2e
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

WEB_PORT = 18616  # unique; 18611 is reserved for the developer's live server

PLAN_TITLE = "Ship a Glue ETL Job"
PLAN_WHY = "Own the nightly customer-events pipeline without pairing."
INCOMPLETE_TITLE = "Vague Someday Plan"


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
    """Own every filesystem and environment input used by this journey."""
    root = tmp_path_factory.mktemp("study-plan-world")
    return build_test_world(root, WEB_PORT, fake_agent=True)


@pytest.fixture(scope="module")
def running_server(test_world: E2ETestWorld):
    """Real subprocess server bound to the journey's hermetic world."""
    server = start_server(test_world)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def page(browser, running_server: RunningServer):
    """One page for the whole journey — state carries across phases."""
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{running_server.base_url}/#study-plans")
    page.wait_for_load_state("domcontentloaded")
    # Navigate via the real nav store (page.goto('#x') alone is ignored).
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
    page.wait_for_timeout(400)
    try:
        yield page
    finally:
        context.close()


def _create_approved_plan(page: Page, payload: dict[str, object]) -> str:
    """Create and approve the exact proposal through the browser-authority API."""
    plan_id = page.evaluate(
        """async (payload) => {
            const csrf = document.cookie
                .split(';')
                .map(item => item.trim().split('='))
                .find(parts => parts[0] === 'studyloop_csrf')?.slice(1).join('=') || '';
            const headers = {
                'Content-Type': 'application/json',
                'X-CSRF-Token': decodeURIComponent(csrf),
            };
            const previewResponse = await fetch('/api/plans', {
                method: 'POST', headers, body: JSON.stringify(payload),
            });
            const preview = await previewResponse.json();
            if (previewResponse.status !== 202) {
                throw new Error(
                    `proposal failed (${previewResponse.status}): ${JSON.stringify(preview)}`
                );
            }
            const proposal = preview.proposal;
            const decisionResponse = await fetch('/api/plans', {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    proposal_id: proposal.proposal_id,
                    proposal_digest: proposal.proposal_digest,
                    decision: 'approve',
                }),
            });
            const decision = await decisionResponse.json();
            if (decisionResponse.status !== 201) {
                throw new Error(
                    `approval failed (${decisionResponse.status}): ${JSON.stringify(decision)}`
                );
            }
            return decision.plan.plan_id;
        }""",
        payload,
    )
    assert isinstance(plan_id, str) and plan_id
    return plan_id


def _load_and_select_plan(page: Page, plan_id: str) -> None:
    page.evaluate(
        """async (planId) => {
            const store = window.Alpine.store('plans');
            await store.load();
            await store.select(planId);
        }""",
        plan_id,
    )


def test_phase1_left_pane_has_study_plan_section(page: Page) -> None:
    """Phase 1 — the left pane carries a Study Plan section with a plan list."""
    try:
        nav = page.locator('[data-testid="nav-study-plans"]')
        nav.wait_for(state="visible", timeout=8000)
        assert "Study Plans" in nav.inner_text()

        # The section lives in the sidebar (left pane), not the content column.
        in_sidebar = page.evaluate(
            """() => {
                const el = document.querySelector('[data-testid="sidebar-plans"]');
                return !!(el && el.closest('nav.sidebar'));
            }"""
        )
        assert in_sidebar, "plan list is not inside the left-pane sidebar"

        section = page.locator('[data-testid="sidebar-plans"]')
        section.wait_for(state="visible", timeout=8000)
        # The label is uppercased by CSS text-transform, so compare case-insensitively.
        assert "existing plans" in section.inner_text().lower()

        # Empty state must be honest rather than a silent blank list.
        page.locator('[data-testid="sidebar-plans-empty"]').wait_for(state="visible", timeout=8000)
    except Exception:
        _diag(page, "plan-phase1")
        raise


def test_phase2_seed_digest_approved_plan_for_the_reader(page: Page) -> None:
    """Phase 2 — a real proposal decision creates the reader's canonical plan."""
    try:
        plan_id = _create_approved_plan(
            page,
            {
                "title": PLAN_TITLE,
                "status": "draft",
                "answers": {
                    "why": PLAN_WHY,
                    "success": [
                        "Deploy a Glue job unaided",
                        "Explain the job bookmark to a colleague",
                    ],
                    "topics": ["data-engineering", "python"],
                    "out_of_scope": ["EMR tuning"],
                    "milestones": [
                        {
                            "title": "Understand Glue job anatomy",
                            "concepts": ["glue job", "job bookmark"],
                        },
                        {"title": "Write the transform", "concepts": ["dynamicframe"]},
                        {
                            "title": "Schedule and monitor it",
                            "concepts": ["cloudwatch"],
                        },
                    ],
                },
            },
        )
        assert plan_id == "ship-a-glue-etl-job"
        _load_and_select_plan(page, plan_id)
        page.locator('[data-testid="plan-detail"]').wait_for(state="visible", timeout=12000)

        title = page.locator('[data-testid="plan-detail-title"]').inner_text()
        assert PLAN_TITLE in title, f"detail did not open the new plan: {title!r}"
    except Exception:
        _diag(page, "plan-phase2")
        raise


def test_phase3_plan_appears_in_left_pane_list(page: Page) -> None:
    """Phase 3 — the new plan is listed in the left pane with its progress."""
    try:
        item = page.locator('.sidebar-plan-item[data-plan-id="ship-a-glue-etl-job"]')
        item.wait_for(state="visible", timeout=8000)
        text = item.inner_text()
        assert PLAN_TITLE in text
        assert "0/3" in text, f"expected 0/3 milestones in the sidebar, got {text!r}"

        # Clicking the sidebar entry must drive the reader (shared store wiring).
        item.click()
        page.wait_for_timeout(400)
        assert PLAN_TITLE in page.locator('[data-testid="plan-detail-title"]').inner_text()
    except Exception:
        _diag(page, "plan-phase3")
        raise


def test_phase4_markdown_renders_as_structured_html(page: Page) -> None:
    """Phase 4 — the plan renders as structured Markdown, not raw text.

    Asserts on the *rendered DOM* rather than the response body: headings,
    a GitHub task list, and the checkpoint table must all become real
    elements, which is what "properly render in the web UI" means.
    """
    try:
        doc = page.locator('[data-testid="plan-markdown"]')
        doc.wait_for(state="visible", timeout=8000)
        doc.locator("svg").wait_for(state="visible", timeout=10_000)

        structure = page.evaluate(
            """() => {
                const el = document.querySelector('[data-testid="plan-markdown"]');
                if (!el) return null;
                return {
                    h1: [...el.querySelectorAll('h1')].map(n => n.textContent.trim()),
                    h2: [...el.querySelectorAll('h2')].map(n => n.textContent.trim()),
                    h3: [...el.querySelectorAll('h3')].map(n => n.textContent.trim()),
                    listItems: el.querySelectorAll('li').length,
                    tables: el.querySelectorAll('table').length,
                    tableHeaders: [...el.querySelectorAll('th')].map(n => n.textContent.trim()),
                    strong: el.querySelectorAll('strong').length,
                    diagrams: el.querySelectorAll('svg').length,
                    links: [...el.querySelectorAll('a')].map(n => n.getAttribute('href')),
                    rawFrontmatterLeaked: el.textContent.includes('review_cadence_days:'),
                    text: el.textContent,
                };
            }"""
        )
        assert structure is not None, "plan document element missing"

        assert PLAN_TITLE in " ".join(structure["h1"]), f"no h1 title: {structure['h1']}"

        sections = " ".join(structure["h2"]).lower()
        for expected in ("mission", "milestones", "resources", "checkpoints"):
            assert expected in sections, f"missing '## {expected}' heading: {structure['h2']}"

        subs = " ".join(structure["h3"]).lower()
        for expected in ("why", "success looks like", "out of scope"):
            assert expected in subs, f"missing '### {expected}': {structure['h3']}"

        assert structure["listItems"] >= 5, f"too few <li>: {structure['listItems']}"
        assert structure["tables"] >= 1, "checkpoint table did not render as <table>"
        headers = " ".join(structure["tableHeaders"]).lower()
        assert "verdict" in headers, f"checkpoint table headers wrong: {structure['tableHeaders']}"

        # Schema-v2 milestone concepts live in table cells, while the learning
        # map's Mermaid fence must render as SVG rather than remain a code dump.
        for concept in ("glue job", "dynamicframe", "cloudwatch"):
            assert concept in structure["text"], f"missing milestone concept: {concept}"
        assert structure["diagrams"] >= 1, "learning-map Mermaid did not render as SVG"
        assert PLAN_WHY in structure["text"], "mission 'why' missing from rendered document"

        # Frontmatter is metadata, not content: it must not leak into the page.
        assert not structure["rawFrontmatterLeaked"], "YAML frontmatter leaked into the render"
    except Exception:
        _diag(page, "plan-phase4")
        raise


def test_phase5_evaluates_at_all_three_checkpoints(page: Page) -> None:
    """Phase 5 — start, mid, and end checkpoints each produce a verdict."""
    try:
        for phase in ("start", "mid", "end"):
            page.locator(f'[data-testid="plan-eval-{phase}"]').click()
            block = page.locator('[data-testid="plan-evaluation"]')
            block.wait_for(state="visible", timeout=10000)
            page.wait_for_function(
                """(p) => {
                    const el = document.querySelector('[data-testid="plan-eval-phase"]');
                    return el && el.textContent.includes(p);
                }""",
                arg=phase,
                timeout=10000,
            )

            # The verdict pill is uppercased by CSS text-transform.
            verdict = page.locator('[data-testid="plan-verdict"]').inner_text().strip().lower()
            assert verdict in {"on-track", "at-risk", "stalled", "complete"}, verdict

            headline = page.locator('[data-testid="plan-headline"]').inner_text().strip()
            assert headline, f"{phase} checkpoint produced no headline"

            recs = page.locator('[data-testid="plan-recommendations"] li')
            assert recs.count() >= 1, f"{phase} checkpoint gave no recommendations"
    except Exception:
        _diag(page, "plan-phase5")
        raise


def test_phase6_record_checkpoint_lands_in_document(page: Page) -> None:
    """Phase 6 — recording a checkpoint appends it to the rendered document."""
    try:
        page.locator('[data-testid="plan-eval-start"]').click()
        page.locator('[data-testid="plan-evaluation"]').wait_for(state="visible", timeout=10000)

        page.locator('[data-testid="plan-record-checkpoint"]').click()
        page.wait_for_function(
            """() => {
                const el = document.querySelector('[data-testid="plan-record-status"]');
                return el && el.textContent.trim().length > 0;
            }""",
            timeout=12000,
        )
        status = page.locator('[data-testid="plan-record-status"]').inner_text()
        assert "recorded" in status.lower(), status

        # The checkpoint table in the rendered document must now have a data row.
        rows = page.evaluate(
            """() => {
                    const el = document.querySelector('[data-testid="plan-markdown"]');
                    if (!el) return [];
                    const table = [...el.querySelectorAll('table')].find(table =>
                        [...table.querySelectorAll('th')]
                            .some(th => th.textContent.trim() === 'Phase')
                    );
                if (!table) return [];
                return [...table.querySelectorAll('tbody tr')].map(
                    tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim())
                );
            }"""
        )
        assert rows, "no checkpoint rows rendered in the document table"
        phases = {cells[1] for cells in rows if len(cells) > 1}
        assert "start" in phases, f"recorded start checkpoint not in table: {rows}"
    except Exception:
        _diag(page, "plan-phase6")
        raise


def test_phase7_milestone_progress_is_evidence_driven(page: Page) -> None:
    """Phase 7 — collected notes and manual clicks cannot claim completion."""
    try:
        before = page.locator('[data-testid="plan-detail-progress"]').inner_text()
        assert "0/3" in before, before

        evidence_note = page.locator('[data-testid="plan-progress-evidence-note"]')
        evidence_note.wait_for(state="visible", timeout=8000)
        note_text = evidence_note.inner_text().lower()
        assert "verified studyloop" in note_text, note_text
        assert "notes" in note_text and "never" in note_text, note_text

        milestone = page.locator('[data-testid="plan-milestone-0"]')
        assert milestone.is_disabled(), "milestone completion is still a manual control"
        assert not milestone.is_checked(), "unverified milestone appears complete"

        # A reload must reconstruct the same evidence-backed state.
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
        page.locator('[data-testid="sidebar-plans"]').wait_for(state="visible", timeout=8000)
        reloaded_item = page.locator('.sidebar-plan-item[data-plan-id="ship-a-glue-etl-job"]')
        reloaded_item.wait_for(state="visible", timeout=8000)
        reloaded_item.click()
        page.locator('[data-testid="plan-detail"]').wait_for(state="visible", timeout=8000)

        reloaded_progress = page.locator('[data-testid="plan-detail-progress"]').inner_text()
        assert "0/3" in reloaded_progress, reloaded_progress
        checked = page.locator('[data-testid="plan-milestone-0"]').is_checked()
        assert not checked, "unverified completion appeared after browser reload"
    except Exception:
        _diag(page, "plan-phase7")
        raise


def test_phase8_ready_plan_can_be_activated_from_the_reader(page: Page) -> None:
    """Phase 8 — the browser supplies learner authority for a valid transition."""
    try:
        page.locator('[data-testid="plan-activate"]').click()
        page.wait_for_function(
            """() => {
                const el = document.querySelector('[data-testid="plan-detail-status"]');
                return el && el.textContent.trim().toLowerCase() === 'active';
            }""",
            timeout=10_000,
        )
        error = page.locator('[data-testid="plan-error"]')
        assert not (error.count() and error.is_visible()), error.inner_text()
    except Exception:
        _diag(page, "plan-phase8")
        raise


def test_phase9_incomplete_plan_is_refused_activation(page: Page) -> None:
    """Phase 9 — a plan with no success criteria or milestones cannot activate."""
    try:
        plan_id = _create_approved_plan(
            page,
            {
                "title": INCOMPLETE_TITLE,
                "answers": {"why": "Explore this safely before committing to a direction."},
            },
        )
        _load_and_select_plan(page, plan_id)
        page.locator('[data-testid="plan-detail"]').wait_for(state="visible", timeout=12000)

        assert INCOMPLETE_TITLE in page.locator('[data-testid="plan-detail-title"]').inner_text()

        blockers = page.locator('[data-testid="plan-blockers"]')
        blockers.wait_for(state="visible", timeout=8000)
        blocker_text = blockers.inner_text().lower()
        assert "success" in blocker_text, blocker_text
        assert "milestone" in blocker_text, blocker_text

        page.locator('[data-testid="plan-activate"]').click()
        page.wait_for_function(
            """() => {
                const el = document.querySelector('[data-testid="plan-error"]');
                return el && el.offsetParent !== null && el.textContent.trim().length > 0;
            }""",
            timeout=10000,
        )
        error = page.locator('[data-testid="plan-error"]').inner_text().lower()
        assert "cannot activate" in error, error

        # Status must be unchanged — the refusal has to actually refuse.
        # Status pill is uppercased by CSS text-transform.
        status = page.locator('[data-testid="plan-detail-status"]').inner_text().strip().lower()
        assert status == "draft", f"plan activated despite blockers: {status!r}"
    except Exception:
        _diag(page, "plan-phase9")
        raise
