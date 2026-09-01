"""Render validation — html / terminal / markdown / mermaid actually paint.

WHY THIS FILE EXISTS
--------------------
DOM presence is not rendering. ``is_visible()`` returns True for an element
whose renderer threw, whose SVG never got generated, or whose canvas is zero-sized.
Each test here asserts *painted output*:

- **html**     — the SPA boots with zero JS errors and its chrome lays out
                 without overlap or clipping (geometry, via _layout_assertions)
- **markdown** — a real lesson's markdown becomes real block elements
                 (h1/h2/p/ul/li/code) through marked → DOMPurify → hljs
- **mermaid**  — a ```mermaid fence and the mastery graph both become an
                 ``<svg>`` with non-zero size and rendered node text
- **terminal** — xterm.js paints agent bytes: the terminal reports sized rows
                 and a canvas/viewport with real geometry (never 0 by 0)

The gate in ``tests/test_e2e_coverage_gate.py`` names these four functions, so
deleting or renaming one fails the default test run.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_render_validation.py -m e2e
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _layout_assertions import (  # noqa: E402
    assert_nonzero_size,
    assert_stacked_no_overlap,
    assert_within_viewport,
)
from e2e._env import (  # noqa: E402
    STUDY_TOPIC,
    ConsoleWatch,
    diag,
    goto_view,
    launch_env,
    shutdown,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

PORT = 18601


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """Server bound to an isolated vault (never the user's real vault)."""
    root = tmp_path_factory.mktemp("render-validation")
    e = launch_env(root, PORT)
    try:
        yield e
    finally:
        shutdown(e)


@pytest.fixture
def page(browser: Browser, env):
    """A page with console-error capture wired in from the first byte."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg._watch = ConsoleWatch(pg)  # type: ignore[attr-defined]
    try:
        yield pg
    finally:
        ctx.close()


def _watch(page: Page) -> ConsoleWatch:
    return page._watch  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# html
# ---------------------------------------------------------------------------


def test_spa_html_renders_without_console_errors(page: Page, env) -> None:
    """The SPA boots clean and its chrome lays out without overlap/clipping.

    Four failure classes in one test because they share a page load:
    (1) a JS exception during boot, (2) a module the SPA imports that is not
    actually served, (3) markup that parses but paints on top of itself,
    (4) markup that paints off-screen. All four have shipped before.
    """
    js_responses: list[tuple[str, int]] = []

    def _capture_js(response) -> None:
        if "/js/" in response.url:
            js_responses.append((response.url, response.status))

    page.on("response", _capture_js)

    try:
        page.goto(f"{env.base_url}/")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.Alpine", timeout=15000)

        # 1. Structural: exactly one document shell, and no XML parser error
        #    nodes (which is how a malformed inline SVG surfaces).
        assert page.locator("html").count() == 1
        assert page.locator("body").count() == 1
        assert page.locator("parsererror").count() == 0

        # 2. The vendored render libraries the other three classes depend on
        #    are actually loaded — a 404'd vendor file otherwise shows up as a
        #    confusing render failure three tests later.
        libs = page.evaluate(
            "() => ({marked: !!window.marked, mermaid: !!window.mermaid, "
            "hljs: !!window.hljs, purify: !!window.DOMPurify})"
        )
        assert all(libs.values()), f"vendored render libs missing: {libs}"

        # 3. The SPA's OWN module graph resolved. js/main.js imports
        #    js/lib/chunk-text.js and js/lib/timer-thresholds.js; a bare
        #    `lib/` rule in .gitignore kept both out of every commit, so a
        #    fresh clone served 404s and Alpine never finished booting. That
        #    surfaced downstream as a strict-mode locator violation and a
        #    select_option timeout in a different file — symptoms nowhere near
        #    the cause. Assert the status codes directly.
        failed_js = [(url, status) for url, status in js_responses if status >= 400]
        assert js_responses, "the SPA requested no /js/* modules at all"
        assert not failed_js, f"SPA JavaScript module requests failed: {failed_js}"

        # 4. Geometry: the sidebar chrome and a content header paint sanely.
        assert_nonzero_size(page, ".sidebar-btn")
        nav_sel = "nav.sidebar" if page.locator("nav.sidebar").count() else "nav"
        assert_within_viewport(page, nav_sel)

        goto_view(page, "body-double")
        assert_stacked_no_overlap(page, ".body-double-header h2", ".body-double-header p")

        _watch(page).assert_clean("booting the SPA and opening Body Double")
    except Exception:
        diag(page, "render-html", _watch(page))
        raise


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------


def _open_lesson_reader(page: Page, env) -> None:
    """Drive the Course Explorer the way a user does: open → course → lesson."""
    page.goto(f"{env.base_url}/")
    page.wait_for_function("() => !!window.Alpine", timeout=15000)
    page.locator(".explorer-sidebar-btn").click()
    card = page.locator(".explorer-course-card").first
    card.wait_for(state="visible", timeout=20000)
    card.click()
    lesson = page.locator(".explorer-lesson-item").first
    lesson.wait_for(state="visible", timeout=20000)
    lesson.click()
    page.locator(".explorer-reader-prose").wait_for(state="visible", timeout=20000)


def test_lesson_markdown_renders_to_block_elements(page: Page, env) -> None:
    """Lesson markdown becomes real HTML blocks, not escaped text.

    Asserts the *converted* structure (headings, paragraph, list items, inline
    and fenced code) rather than substring presence, because a broken
    marked/DOMPurify chain still leaves the raw markdown text on the page — a
    substring assertion would pass while the user sees ``## Why they matter``.
    """
    try:
        _open_lesson_reader(page, env)
        prose = page.locator(".explorer-reader-prose")

        counts = page.evaluate(
            """() => {
                const el = document.querySelector('.explorer-reader-prose');
                const n = (s) => el.querySelectorAll(s).length;
                return {h1: n('h1'), h2: n('h2'), p: n('p'), li: n('li'),
                        code: n('code'), pre: n('pre'),
                        raw: el.innerText.includes('## Why they matter')};
            }"""
        )
        assert counts["h2"] >= 2, f"headings not converted to <h2>: {counts}"
        assert counts["p"] >= 1, f"no paragraph elements rendered: {counts}"
        assert counts["li"] >= 3, f"bullet list not converted to <li>: {counts}"
        assert counts["pre"] >= 1 and counts["code"] >= 1, (
            f"fenced code block not rendered as <pre><code>: {counts}"
        )
        assert not counts["raw"], (
            "raw markdown ('## Why they matter') is visible — the marked → "
            "DOMPurify chain did not run"
        )

        # Painted, not merely present: the prose box has real height.
        assert_nonzero_size(page, ".explorer-reader-prose")
        box = prose.bounding_box()
        assert box and box["height"] > 100, f"prose box too small to be rendered: {box}"

        # Syntax highlighting ran on the python fence (hljs adds spans).
        hl = page.evaluate(
            "() => document.querySelectorAll('.explorer-reader-prose pre code span').length"
        )
        assert hl > 0, "highlight.js produced no token spans in the code fence"

        _watch(page).assert_clean("rendering lesson markdown")
    except Exception:
        diag(page, "render-markdown", _watch(page))
        raise


# ---------------------------------------------------------------------------
# mermaid
# ---------------------------------------------------------------------------


def test_mermaid_fence_renders_to_svg(page: Page, env) -> None:
    """A ```mermaid fence in a lesson becomes a real, sized <svg>.

    Covers the two-pass pipeline: ``renderMarkdown()`` swaps the fence for a
    ``.mermaid-diagram[data-src]`` placeholder, then ``renderMermaidIn()``
    replaces it with SVG. The fallback path writes the diagram source into
    ``.mermaid-fallback`` — asserting *no* fallback is what distinguishes
    "rendered" from "gave up and showed the source".
    """
    try:
        _open_lesson_reader(page, env)

        page.wait_for_function(
            "() => document.querySelector('.explorer-reader-prose svg') !== null",
            timeout=25000,
        )
        info = page.evaluate(
            """() => {
                const root = document.querySelector('.explorer-reader-prose');
                const svg = root.querySelector('svg');
                const r = svg.getBoundingClientRect();
                // Node geometry is the aspect-ratio-independent proof: a
                // flowchart LR renders as one short wide row, so asserting a
                // minimum SVG *height* would flake. What must be true is that
                // real node shapes were laid out with real size.
                const nodeSel = '.node rect, .node polygon, .node circle, .node path, g.node';
                const shapes = [...svg.querySelectorAll(nodeSel)]
                    .map(el => el.getBoundingClientRect())
                    .filter(b => b.width > 4 && b.height > 4);
                return {
                    w: r.width, h: r.height,
                    paintedShapes: shapes.length,
                    text: svg.textContent || '',
                    fallback: root.querySelectorAll('.mermaid-fallback').length,
                    unrendered: root.querySelectorAll('.mermaid-diagram[data-src]').length,
                };
            }"""
        )
        assert info["fallback"] == 0, "mermaid fell back to raw source (render threw)"
        assert info["unrendered"] == 0, "a .mermaid-diagram placeholder was never replaced"
        assert info["w"] > 50 and info["h"] > 8, f"mermaid svg has no real size: {info}"
        assert info["paintedShapes"] >= 2, (
            f"mermaid produced an <svg> with no laid-out node shapes — the diagram is empty: {info}"
        )
        assert "wrapper" in info["text"], (
            f"mermaid svg does not contain the diagram's node labels: {info['text'][-200:]!r}"
        )
        _watch(page).assert_clean("rendering a mermaid fence")
    except Exception:
        diag(page, "render-mermaid-lesson", _watch(page))
        raise


def test_mastery_graph_renders_mermaid_svg(page: Page, env) -> None:
    """The Mastery view's graph card paints a mermaid <svg>.

    The graph's *data* comes from learning evidence in the user's DB, which a
    hermetic test must not depend on or write to — so the two mastery API
    responses are stubbed with a faithful payload while the client-side
    mermaid pipeline under test runs for real. The server-side generator is
    covered separately by ``test_mastery_api_emits_mermaid_source``.
    """
    try:
        page.route(
            "**/api/mastery/graph*",
            lambda route: route.fulfill(
                json={
                    "topic": STUDY_TOPIC,
                    "nodes": ["closures", "decorators", "functools.wraps"],
                    "edges": [
                        {
                            "topic": STUDY_TOPIC,
                            "source_concept": "closures",
                            "target_concept": "decorators",
                            "relation_type": "prerequisite",
                            "evidence": "lesson 01",
                            "source_type": "markdown",
                            "confidence": 0.9,
                        },
                        {
                            "topic": STUDY_TOPIC,
                            "source_concept": "decorators",
                            "target_concept": "functools.wraps",
                            "relation_type": "refines",
                            "evidence": "lesson 01",
                            "source_type": "markdown",
                            "confidence": 0.8,
                        },
                    ],
                    "edge_count_total": 2,
                    "limited": False,
                }
            ),
        )
        page.route(
            "**/api/mastery/weak-links*",
            lambda route: route.fulfill(
                json={
                    "topic": STUDY_TOPIC,
                    "weak_links": [
                        {
                            "source_concept": "closures",
                            "target_concept": "decorators",
                            "relation_type": "prerequisite",
                            "confidence": 0.4,
                        }
                    ],
                    "weak_link_count_total": 1,
                    "limited": False,
                }
            ),
        )
        page.goto(f"{env.base_url}/")
        goto_view(page, "mastery")

        page.wait_for_function(
            "() => document.querySelector('.mastery-graph-canvas svg') !== null",
            timeout=25000,
        )
        info = page.evaluate(
            """() => {
                const el = document.querySelector('.mastery-graph-canvas');
                const svg = el.querySelector('svg');
                const r = svg.getBoundingClientRect();
                const nodeSel = '.node rect, .node polygon, .node circle, .node path, g.node';
                const shapes = [...svg.querySelectorAll(nodeSel)]
                    .map(n => n.getBoundingClientRect())
                    .filter(b => b.width > 4 && b.height > 4);
                return {w: r.width, h: r.height, paintedShapes: shapes.length,
                        text: svg.textContent || ''};
            }"""
        )
        assert info["w"] > 50 and info["h"] > 8, f"mastery svg not sized: {info}"
        assert info["paintedShapes"] >= 2, (
            f"mastery graph svg has no laid-out concept nodes: {info}"
        )
        assert "decorators" in info["text"], (
            f"mastery svg missing concept labels: {info['text'][:200]!r}"
        )
        # The summary counters must agree with the graph the user is looking at.
        summary = page.locator(".mastery-summary").inner_text()
        assert "3" in summary and "2" in summary, f"mastery counters wrong: {summary!r}"
        _watch(page).assert_clean("rendering the mastery graph")
    except Exception:
        diag(page, "render-mermaid-mastery", _watch(page))
        raise


def test_mastery_api_emits_mermaid_source(env) -> None:
    """Server side of the mermaid contract: ``format=mermaid`` returns a graph.

    Complements the browser test above — together they prove the whole path
    (server emits valid mermaid, browser renders mermaid to SVG).
    """
    import requests

    resp = requests.get(
        f"{env.base_url}/api/mastery/graph",
        params={"topic": STUDY_TOPIC, "format": "mermaid", "limit": 20},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert body.lstrip().startswith("flowchart"), f"not mermaid source: {body[:120]!r}"


# ---------------------------------------------------------------------------
# terminal
# ---------------------------------------------------------------------------

FAKE_PORT = 18602


@pytest.fixture(scope="module")
def fake_env(tmp_path_factory):
    """Server with a source-test child behind the real Codex adapter."""
    root = tmp_path_factory.mktemp("render-terminal")
    e = launch_env(root, FAKE_PORT, fake_agent=True)
    try:
        yield e
    finally:
        try:
            import requests

            requests.post(f"{e.base_url}/api/session/end", timeout=10)
        except Exception:  # pragma: no cover
            pass
        shutdown(e)


def test_terminal_paints_agent_bytes(browser: Browser, fake_env) -> None:
    """xterm.js paints real agent output into a sized terminal.

    Asserts the render, not just the connection: xterm's WebGL/canvas renderer
    keeps glyphs out of the DOM, so this reads xterm's own buffer (the source
    of what is painted) *and* the canvas geometry. An unsized canvas with a
    populated buffer is the "terminal is blank" bug; a sized canvas with an
    empty buffer is the "connected but no bytes" bug. Both are caught.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    try:
        page.route(
            "**/api/backlog",
            lambda route: route.fulfill(
                json={
                    "active": [],
                    "parking_lot": [],
                    "active_count": 0,
                    "parking_lot_count": 0,
                    "max_active": 3,
                }
            ),
        )
        page.goto(f"{fake_env.base_url}/#study-session")
        page.wait_for_function("() => !!window.Alpine", timeout=15000)
        page.locator("#topic-input").fill(STUDY_TOPIC)
        page.wait_for_function(
            """() => {
                const s = document.querySelector('#agent-select');
                return s && [...s.options].some(o => o.value === 'codex');
            }""",
            timeout=40000,
        )
        page.select_option("#agent-select", value="codex")
        page.wait_for_function(
            "() => !document.querySelector('.study-start-picker .start-session-btn').disabled",
            timeout=10000,
        )
        page.locator(".study-start-picker .start-session-btn").click()

        # Connected: the WS handshake completed and the header reflects it.
        page.wait_for_function("() => document.body.innerText.includes('Connected')", timeout=30000)

        # Painted: xterm's own buffer holds the agent's banner bytes.
        # The Terminal instance lives on the `liveAgentConsole()` Alpine
        # component as `_term` (no global), so reach it through Alpine.$data
        # on the mount element rather than adding a test-only product hook.
        page.wait_for_function(
            """() => {
                const mount = document.querySelector('.xterm-mount');
                if (!mount || !window.Alpine || !window.Alpine.$data) return false;
                const data = window.Alpine.$data(mount);
                const t = data && data._term;
                if (!t || !t.buffer) return false;
                const b = t.buffer.active;
                let s = '';
                for (let i = 0; i < b.length; i++) {
                    const line = b.getLine(i);
                    if (line) s += line.translateToString(true) + '\\n';
                }
                return s.includes('FAKE-AGENT READY');
            }""",
            timeout=30000,
        )

        # Sized: the xterm viewport/canvas has real geometry (never zero).
        geom = page.evaluate(
            """() => {
                const el = document.querySelector('.xterm-screen')
                       || document.querySelector('.xterm canvas')
                       || document.querySelector('.xterm');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {w: r.width, h: r.height};
            }"""
        )
        assert geom, "no xterm element in the DOM after connecting"
        assert geom["w"] > 100 and geom["h"] > 50, f"terminal not sized: {geom}"
        watch.assert_clean("rendering the live terminal")
    except Exception:
        diag(page, "render-terminal", watch)
        raise
    finally:
        try:
            import requests

            requests.post(f"{fake_env.base_url}/api/session/end", timeout=10)
        except Exception:  # pragma: no cover
            pass
        ctx.close()
