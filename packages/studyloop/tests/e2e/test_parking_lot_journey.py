"""End-to-end Parking Lot journey — drives the REAL StudyLoop web UI.

This is the authoritative gate for the parking-lot feature. It walks the whole
representative workflow a learner actually performs, against the real Alpine
panel and the real server (no stubbed selectors, no mocked fetches):

  Phase 1  Capture — park thoughts mid-flow via the quick-park 'p' shortcut
  Phase 2  Open the dedicated Parking Lot side panel; parked items are there
  Phase 3  Edit a card IN PLACE — retitle it and grow the terse capture into a
           real Markdown note containing a mermaid diagram
  Phase 4  Markdown renders FULLY (headings, table, task list, code, diagram)
           and the rendered output follows the ACTIVE THEME (asserted across a
           palette switch, including a light palette)
  Phase 5  Notes round-trip as clean Markdown (server normalisation visible in
           the textarea after save, and durable across a reload)
  Phase 6  Kanban — arrange cards into columns (keyboard move + a user-created
           column), and confirm the arrangement persists
  Phase 7  Clearing — clear ONE item, clear a USER-SELECTED SUBSET, clear ALL,
           and undo a clear

Each phase runs against a dedicated temp DB (STUDYLOOP_CONFIG points at a temp
config with its own session_db) so the suite never touches the developer's real
parked topics.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_parking_lot_journey.py -m e2e
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402
from e2e._env import TestWorld as E2ETestWorld  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18615  # unique; 18611 is reserved for the developer's live server

LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS study_sessions (id TEXT PRIMARY KEY, started_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, source TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS parked_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_session_id TEXT,
    session_id TEXT,
    topic_tag TEXT,
    question TEXT NOT NULL,
    context TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
    scheduled_for TEXT,
    resolved_at TEXT,
    parked_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT DEFAULT 'agent',
    source TEXT NOT NULL DEFAULT 'parked'
        CHECK(source IN ('parked', 'struggled', 'manual')),
    tech_area TEXT,
    priority INTEGER
);
"""

# The note a learner would actually write a week later: prose + structure +
# a diagram. Exercises the FULL Markdown surface, not a subset — every block
# type here is asserted in the render test, so "full Markdown" is a claim the
# suite can actually cash.
RICH_NOTE = """## Why this mattered

The nested-loop join blew up on the 4M-row fact table.

> The planner is only as good as its statistics.

### What I checked

| Step | Finding |
| --- | --- |
| `EXPLAIN` | planner chose nested loop |
| stats | `n_distinct` badly stale |

- [x] Reproduced on a copy
- [ ] Re-run ANALYZE and re-measure

1. Read the plan
2. Check the stats
   - `pg_stats.n_distinct`
   - last `ANALYZE` time

~~Blamed the index~~ — it was the stats all along. See
[the docs](https://example.com/analyze).

```sql
ANALYZE fact_orders;
```

```mermaid
graph TD
    A[Stale stats] --> B[Bad row estimate]
    B --> C[Nested loop chosen]
    C --> D[Query 40x slower]
```
"""


_CONSOLE: list[str] = []


@pytest.fixture(autouse=True)
def _capture_console(page: Page):
    """Record browser console + uncaught page errors for failure artefacts.

    Without this, a silent JS failure is invisible: the HTML artefact shows the
    *outcome* (an unrendered placeholder) but never the *cause*, so diagnosis
    degenerates into reading source and guessing. A listener has to be attached
    before the page runs, which is why this is a fixture rather than something
    ``_diag`` can do after the fact.
    """
    _CONSOLE.clear()
    # Unhandled promise REJECTIONS do not arrive on Playwright's pageerror
    # channel, and this app fires async work without awaiting it
    # (togglePreview() calls the async renderPreview() bare), so a throw inside
    # such a call is invisible on every channel unless we route it ourselves.
    # That invisibility is what made the mermaid failure look like "the code ran
    # and quietly did nothing" through three separate investigations.
    page.add_init_script(
        "window.addEventListener('unhandledrejection', (e) => {"
        "  const r = e.reason;"
        "  console.error('[unhandledrejection] ' + ((r && (r.stack || r.message)) || r));"
        "});"
    )
    page.on("console", lambda m: _CONSOLE.append(f"[{m.type}] {m.text}"))
    page.on("pageerror", lambda e: _CONSOLE.append(f"[pageerror] {e}"))
    # A failed script/resource load does NOT arrive on the console channel, so
    # without these a 404 on a vendored bundle looks exactly like "everything
    # loaded and the feature silently did nothing" — which is the single most
    # misleading state to debug from.
    page.on("requestfailed", lambda r: _CONSOLE.append(f"[requestfailed] {r.url} {r.failure}"))
    page.on(
        "response",
        lambda r: _CONSOLE.append(f"[http {r.status}] {r.url}") if r.status >= 400 else None,
    )
    return None


def _diag(page: Page | None, name: str) -> None:
    """Best-effort failure artefacts (screenshot + HTML + console)."""
    if page is None:
        return
    RESULTS.mkdir(exist_ok=True)
    ts = int(time.time())
    try:
        # Probe the LIVE page, not just its corpse. A DOM dump shows an
        # unrendered placeholder but cannot say whether the library that should
        # have rendered it is even present — the difference between "asset
        # missing" and "wrong root element passed".
        probe = page.evaluate(
            """() => {
                const previews = document.querySelectorAll('#parking-panel .parking-note-preview');
                const first = previews[0] || null;
                return {
                    mermaid_type: typeof window.mermaid,
                    has_render: !!(window.mermaid && window.mermaid.render),
                    previews: previews.length,
                    placeholders_page: document.querySelectorAll('.mermaid-diagram').length,
                    unrendered: document.querySelectorAll('.mermaid-diagram[data-src]').length,
                    placeholders_in_first: first
                        ? first.querySelectorAll('.mermaid-diagram').length : -1,
                    first_has_h2: first ? !!first.querySelector('h2') : False_,
                    activeEl: document.activeElement
                        ? (document.activeElement.tagName + '.'
                            + (document.activeElement.className || '')).slice(0, 50)
                        : 'none',
                    editingCards: document.querySelectorAll(
                        '#parking-panel .parking-card.editing'
                    ).length,
                    cardsInbox: document.querySelectorAll(
                        '#parking-panel .parking-column[data-column="inbox"] .parking-card'
                    ).length,
                    cardsNext: document.querySelectorAll(
                        '#parking-panel .parking-column[data-column="next"] .parking-card'
                    ).length,
                };
            }""".replace("False_", "false")
        )
        _CONSOLE.append(f"[probe] {probe}")
    except Exception as exc:  # pragma: no cover — diagnostics must never mask
        _CONSOLE.append(f"[probe failed] {exc}")
    try:
        page.screenshot(path=str(RESULTS / f"{name}-{ts}.png"), full_page=True)
        (RESULTS / f"{name}-{ts}.html").write_text(page.content())
    except Exception:
        pass
    try:
        # Always write, even when empty: "no console output" and "the listener
        # never attached" are different diagnoses and must not look identical.
        body = "\n".join(_CONSOLE) if _CONSOLE else "(listener attached, no console output)"
        (RESULTS / f"{name}-{ts}.console.log").write_text(body)
    except Exception:
        pass


@pytest.fixture(scope="module")
def test_world(tmp_path_factory: pytest.TempPathFactory) -> E2ETestWorld:
    """Build a hermetic world while preserving the legacy schema scenario."""
    root = tmp_path_factory.mktemp("parking-journey")
    world = build_test_world(root, WEB_PORT, fake_agent=True)
    with sqlite3.connect(world.session_db) as conn:
        conn.executescript(LEGACY_SCHEMA)
    return world


@pytest.fixture(scope="module")
def running_server(test_world: E2ETestWorld) -> Iterator[RunningServer]:
    """Run the Parking journey against its explicit hermetic world."""
    server = start_server(test_world)
    try:
        yield server
    finally:
        server.stop()


DEFAULT_COLUMNS = [
    ("inbox", "Inbox"),
    ("next", "Next Up"),
    ("exploring", "Exploring"),
    ("done", "Done"),
]


@pytest.fixture()
def clean_board(running_server: RunningServer) -> str:
    """Reset the board (items AND column shape) before each test.

    Columns are part of the board's state — tests that add "Blocked" or remove
    "Done" would otherwise leak their shape into later phases. Resetting both
    keeps each phase independently meaningful.
    """
    import requests

    base_url = running_server.base_url
    requests.post(
        f"{base_url}/api/parking/clear",
        json={"all": True, "hard": True},
        timeout=10,
    )

    existing = requests.get(f"{base_url}/api/parking/columns", timeout=10).json()["columns"]
    wanted = dict(DEFAULT_COLUMNS)
    # Drop user-added columns; restore any renamed default back to its name.
    for col in existing:
        if col["key"] not in wanted:
            requests.delete(f"{base_url}/api/parking/columns/{col['key']}", timeout=10)
    present = {
        c["key"]: c["name"]
        for c in requests.get(f"{base_url}/api/parking/columns", timeout=10).json()["columns"]
    }
    for key, name in DEFAULT_COLUMNS:
        if key not in present:
            created = requests.post(
                f"{base_url}/api/parking/columns", json={"name": name}, timeout=10
            ).json()["column"]
            # A recreated default may get a de-duplicated key; normalise below.
            present[created["key"]] = created["name"]
        elif present[key] != name:
            requests.patch(
                f"{base_url}/api/parking/columns/{key}",
                json={"name": name},
                timeout=10,
            )
    requests.post(
        f"{base_url}/api/parking/columns/reorder",
        json={"keys": [k for k, _ in DEFAULT_COLUMNS]},
        timeout=10,
    )
    return base_url


def _open_panel(page: Page) -> None:
    """Click the real sidebar button and wait for the board to hydrate."""
    page.wait_for_function("() => !!window.Alpine", timeout=10000)
    page.locator("#parking-lot-toggle").click()
    page.wait_for_selector("#parking-panel", state="visible", timeout=8000)
    page.wait_for_function(
        "() => document.querySelectorAll('#parking-panel .parking-column').length > 0",
        timeout=8000,
    )


def _seed(server: str, *questions: str) -> list[int]:
    """Create cards through the real API (stands in for agent-side parking)."""
    import requests

    ids = []
    for q in questions:
        resp = requests.post(f"{server}/api/parking/item", json={"question": q}, timeout=10)
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids


def _card(page: Page, question: str):
    return page.locator(
        ".parking-card",
        has=page.locator(f'.parking-card-title:text-is("{question}")'),
    )


# ---------------------------------------------------------------------------
# Phase 1 + 2 — capture mid-flow, then find it in the dedicated side panel
# ---------------------------------------------------------------------------


def test_quick_park_then_item_appears_in_parking_panel(page: Page, clean_board: str) -> None:
    """Phase 1+2: 'p' parks a tangent; the Parking Lot panel shows it."""
    try:
        page.goto(f"{clean_board}/#today")
        page.wait_for_function("() => !!window.Alpine", timeout=10000)

        # Quick-park via the real keyboard shortcut (flow protection path).
        page.keyboard.press("p")
        page.wait_for_selector(".quick-park-input", state="visible", timeout=5000)
        page.locator(".quick-park-input").fill("Why did that join get slow?")
        page.locator('.end-confirm-yes:has-text("Park it")').click()
        page.wait_for_selector(".quick-park-overlay", state="hidden", timeout=5000)

        _open_panel(page)
        title = page.locator(
            '#parking-panel .parking-card-title:has-text("Why did that join get slow?")'
        )
        title.wait_for(state="visible", timeout=8000)
        assert page.locator("#parking-total-count").inner_text().strip() == "1 item"
    except Exception:
        _diag(page, "parking-capture")
        raise


def test_panel_is_a_board_with_columns(page: Page, clean_board: str) -> None:
    """Phase 2: the panel is board-like — multiple named columns, not a list."""
    try:
        _seed(clean_board, "Board shape check")
        page.goto(f"{clean_board}/")
        _open_panel(page)
        columns = page.locator("#parking-panel .parking-column")
        assert columns.count() >= 4, f"expected a multi-column board, got {columns.count()}"
        names = [
            n.strip() for n in page.locator("#parking-panel .parking-column-name").all_inner_texts()
        ]
        assert "INBOX" in [n.upper() for n in names]
    except Exception:
        _diag(page, "parking-board-shape")
        raise


# ---------------------------------------------------------------------------
# Phase 3 + 4 + 5 — edit in place, full Markdown + diagram, theme, clean round-trip
# ---------------------------------------------------------------------------


def test_edit_in_place_with_markdown_and_diagram_rendering(page: Page, clean_board: str) -> None:
    """Phases 3-5: grow a terse capture into a rendered, themed Markdown note.

    Asserts the things that make the parking lot worth revisiting:
      * the card is editable in place (title + notes)
      * FULL Markdown renders — heading, GFM table, task list, highlighted code
      * the mermaid diagram renders to an actual <svg>
      * the note survives a reload as clean Markdown
    """
    try:
        _seed(clean_board, "terse capture")
        page.goto(f"{clean_board}/")
        _open_panel(page)

        # --- Phase 3: open the editor on the card, edit in place ---
        page.locator('#parking-panel .parking-card-title:has-text("terse capture")').click()
        page.wait_for_selector("#parking-note-input", state="visible", timeout=8000)

        page.locator("#parking-panel .parking-title-input").fill(
            "Why does the planner choose a nested loop here?"
        )
        page.locator("#parking-note-input").fill(RICH_NOTE)
        page.locator("#parking-panel .parking-area-input").fill("SQL")
        page.select_option("#parking-panel .parking-priority-input", "4")

        # --- Phase 4: full Markdown renders in the preview ---
        page.locator("#parking-preview-btn").click()
        preview = page.locator("#parking-panel .parking-note-preview")
        preview.wait_for(state="visible", timeout=8000)

        page.wait_for_function(
            """() => {
                const p = document.querySelector('#parking-panel .parking-note-preview');
                return !!p && !!p.querySelector('h2') && !!p.querySelector('table');
            }""",
            timeout=8000,
        )
        # Headings, GFM table, task list, fenced code — not a partial subset.
        assert preview.locator("h2").count() >= 1, "heading did not render"
        assert preview.locator("h3").count() >= 1, "sub-heading did not render"
        assert preview.locator("table").count() == 1, "GFM table did not render"
        assert preview.locator("table td").count() >= 4, "table cells missing"
        assert preview.locator('input[type="checkbox"]').count() >= 2, (
            "GFM task list did not render"
        )
        assert preview.locator("pre code").count() >= 1, "fenced code block did not render"
        # The rest of the block surface: blockquote, ordered + nested lists,
        # strikethrough, inline code, links. Asserted individually so a
        # regression in any single one is named, not hidden behind "it rendered".
        assert preview.locator("blockquote").count() >= 1, "blockquote did not render"
        assert preview.locator("ol").count() >= 1, "ordered list did not render"
        assert preview.locator("ol ul").count() >= 1, "nested list did not render"
        assert preview.locator("del").count() >= 1, "strikethrough did not render"
        assert preview.locator("code").count() >= 2, "inline code did not render"
        link = preview.locator('a[href="https://example.com/analyze"]')
        assert link.count() == 1, "link did not render"
        # Links are hardened by renderMarkdown() — new tab, no referrer leak.
        assert link.get_attribute("target") == "_blank"
        assert "noopener" in (link.get_attribute("rel") or "")
        # highlight.js ran over the SQL block.
        assert preview.locator("pre code.hljs, pre code span.hljs-keyword").count() >= 1, (
            "syntax highlighting did not run"
        )

        # Mermaid rendered to a real SVG (not left as a placeholder or fallback).
        page.wait_for_function(
            """() => {
                const p = document.querySelector('#parking-panel .parking-note-preview');
                return !!p && !!p.querySelector('.mermaid-diagram svg');
            }""",
            timeout=15000,
        )
        assert preview.locator(".mermaid-fallback").count() == 0, "mermaid fell back to <pre>"
        mermaid_config = page.evaluate("() => window.mermaid.mermaidAPI.getConfig()")
        assert mermaid_config["htmlLabels"] is False
        assert mermaid_config["flowchart"]["htmlLabels"] is False, (
            "Mermaid was not configured to emit sanitizer-safe SVG labels"
        )
        # text_content, not inner_text: an <svg> is not an HTMLElement.
        diagram_text = preview.locator(".mermaid-diagram svg").text_content()
        assert diagram_text is not None
        assert "Nested loop chosen" in diagram_text.replace("\n", " ")

        # --- Phase 5: save; the textarea adopts the server's clean Markdown ---
        page.locator("#parking-save-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#parking-save-btn').innerText.trim() === 'Saved'",
            timeout=10000,
        )
        RESULTS.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS / "parking-lot-note-rendered.png"))

        # Durable across a full reload — and still clean Markdown.
        page.reload()
        _open_panel(page)
        card_title = page.locator(
            '#parking-panel .parking-card-title:has-text("Why does the planner choose")'
        )
        card_title.wait_for(state="visible", timeout=8000)
        # The collapsed card advertises its diagram + metadata.
        card = page.locator("#parking-panel .parking-card").first
        assert "diagram" in card.inner_text()
        assert "SQL" in card.inner_text()

        card_title.click()
        page.wait_for_selector("#parking-note-input", state="visible", timeout=8000)
        stored = page.locator("#parking-note-input").input_value()
        assert "```mermaid" in stored, "diagram source lost on round-trip"
        assert "| Step | Finding |" in stored, "table lost on round-trip"
        assert "\r" not in stored, "CRLF leaked into stored Markdown"
        assert not any(
            line != line.rstrip() and not line.endswith("  ") for line in stored.split("\n")
        ), "trailing whitespace present in stored Markdown"
        assert stored.endswith("\n"), "stored Markdown missing single trailing newline"
        assert "\n\n\n" not in stored, "collapsed blank lines not applied"
    except Exception:
        _diag(page, "parking-edit-markdown")
        raise


def test_rendered_markdown_follows_the_active_theme(page: Page, clean_board: str) -> None:
    """Phase 4: rendered output respects the CURRENT theme, not a default.

    Two assertions that a hardcoded theme cannot satisfy:
      1. The preview surface's colours come from the active palette tokens.
      2. The mermaid SVG re-renders with the new palette's colours after a
         palette switch — including to a LIGHT palette (the case a hardcoded
         `theme: 'dark'` got visibly wrong).
    """
    try:
        _seed(clean_board, "theme check")
        page.goto(f"{clean_board}/")
        _open_panel(page)
        page.locator('#parking-panel .parking-card-title:has-text("theme check")').click()
        page.wait_for_selector("#parking-note-input", state="visible", timeout=8000)
        page.locator("#parking-note-input").fill(
            "# Themed\n\n```mermaid\ngraph TD\n    A[One] --> B[Two]\n```\n"
        )
        page.locator("#parking-preview-btn").click()
        page.wait_for_function(
            """() => !!document.querySelector(
                 '#parking-panel .parking-note-preview .mermaid-diagram svg')""",
            timeout=15000,
        )

        def probe() -> dict:
            return page.evaluate("""() => {
                const css = getComputedStyle(document.body);
                const prev = document.querySelector('#parking-panel .parking-note-preview');
                const svg = prev.querySelector('.mermaid-diagram svg');
                const node = svg.querySelector('.node > rect.label-container');
                return {
                  palette: document.body.getAttribute('data-palette') || 'tokyo-night',
                  tokenBg: css.getPropertyValue('--bg').trim(),
                  tokenText: css.getPropertyValue('--text').trim(),
                  previewBg: getComputedStyle(prev).backgroundColor,
                  previewColor: getComputedStyle(prev).color,
                  nodeFill: node ? getComputedStyle(node).fill : '',
                  svgHtml: svg.outerHTML.slice(0, 4000),
                };
            }""")

        def to_rgb(hex_or_rgb: str) -> str:
            s = hex_or_rgb.strip()
            if s.startswith("#") and len(s) == 7:
                return f"rgb({int(s[1:3], 16)}, {int(s[3:5], 16)}, {int(s[5:7], 16)})"
            return s

        # --- Default palette: preview surface uses the palette tokens ---
        dark = probe()
        assert dark["previewBg"] == to_rgb(dark["tokenBg"]), (
            f"preview background {dark['previewBg']} != palette --bg {dark['tokenBg']}"
        )
        assert dark["previewColor"] == to_rgb(dark["tokenText"]), (
            f"preview text {dark['previewColor']} != palette --text {dark['tokenText']}"
        )
        assert dark["nodeFill"], "mermaid node had no computed fill"

        # --- Switch to a LIGHT palette and re-render ---
        page.evaluate("() => window.Alpine.store('settings').setPalette('catppuccin-latte')")
        page.wait_for_function(
            "() => document.body.getAttribute('data-palette') === 'catppuccin-latte'",
            timeout=5000,
        )
        # The palette change fires studyloop:theme-change → mermaid re-init;
        # the component re-renders the open preview.
        page.wait_for_timeout(400)
        page.wait_for_function(
            """() => !!document.querySelector(
                 '#parking-panel .parking-note-preview .mermaid-diagram svg')""",
            timeout=15000,
        )
        light = probe()
        assert light["palette"] == "catppuccin-latte"
        assert light["previewBg"] == to_rgb(light["tokenBg"]), (
            "preview background did not follow the light palette"
        )
        assert light["previewBg"] != dark["previewBg"], "preview surface never changed"

        # The diagram itself must be re-coloured — the whole point. A hardcoded
        # mermaid theme leaves the SVG byte-identical across a palette switch.
        assert light["svgHtml"] != dark["svgHtml"], (
            "mermaid SVG identical after palette switch — diagram ignored the theme"
        )
        assert light["nodeFill"] != dark["nodeFill"], (
            f"mermaid node fill unchanged ({dark['nodeFill']}) — theme not applied"
        )
        # And the diagram's surface should now be light, matching the page.
        light_fill = light["nodeFill"]
        nums = [int(n) for n in light_fill.replace("rgb(", "").replace(")", "").split(",")[:3]]
        assert sum(nums) / 3 > 128, f"light palette produced a dark diagram node: {light_fill}"

        RESULTS.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS / "parking-lot-theme-light.png"))
    except Exception:
        _diag(page, "parking-theme")
        raise


# ---------------------------------------------------------------------------
# Phase 6 — Kanban arrangement
# ---------------------------------------------------------------------------


def test_kanban_move_and_user_created_column_persist(page: Page, clean_board: str) -> None:
    """Phase 6: arrange cards across columns — including one the user creates."""
    import requests

    try:
        _seed(clean_board, "Move me with the keyboard")
        page.goto(f"{clean_board}/")
        _open_panel(page)

        # --- User creates their own column (board shape is not fixed) ---
        page.locator("#parking-manage-columns").click()
        page.locator("#parking-new-column").fill("Blocked")
        page.locator("#parking-add-column").click()
        page.wait_for_function(
            """() => [...document.querySelectorAll('#parking-panel .parking-column')]
                     .some(c => c.dataset.column === 'blocked')""",
            timeout=8000,
        )

        # --- Keyboard move (the accessible equivalent of drag-and-drop) ---
        card = page.locator("#parking-panel .parking-card").first
        card.focus()
        card.press("ArrowRight")
        page.wait_for_function(
            """() => {
                const col = document.querySelector(
                  '#parking-panel .parking-column[data-column="next"]');
                return !!col && col.querySelectorAll('.parking-card').length === 1;
            }""",
            timeout=8000,
        )

        # --- Persisted server-side, not just optimistic UI ---
        board = requests.get(f"{clean_board}/api/parking/board", timeout=10).json()
        by_key = {c["key"]: c for c in board["columns"]}
        assert "blocked" in by_key, "user-created column not persisted"
        assert [i["question"] for i in by_key["next"]["items"]] == ["Move me with the keyboard"]
        assert by_key["inbox"]["items"] == []

        # --- Survives a reload (the arrangement is real state) ---
        page.reload()
        _open_panel(page)
        page.wait_for_function(
            """() => {
                const col = document.querySelector(
                  '#parking-panel .parking-column[data-column="next"]');
                return !!col && col.querySelectorAll('.parking-card').length === 1;
            }""",
            timeout=8000,
        )
        RESULTS.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS / "parking-lot-kanban.png"))
    except Exception:
        _diag(page, "parking-kanban")
        raise


def test_drag_and_drop_moves_a_card(page: Page, clean_board: str) -> None:
    """Phase 6b: pointer-drag a card to the adjacent column in a real browser.

    Uses explicit mouse steps rather than ``drag_to``: the board implements
    dragging with POINTER events (so it also works with a finger), and the
    intermediate move is what crosses the 6px drag threshold.

    Targets the ADJACENT column deliberately — that is the realistic gesture,
    and on a board wider than the panel a far column is scrolled out of view
    (the component auto-scrolls at the edge for those, but asserting a
    scroll-and-drag adds nothing to what this test is pinning: that a pointer
    drag re-columns a card and persists it).
    """
    import requests

    try:
        _seed(clean_board, "Drag me")
        page.goto(f"{clean_board}/")
        _open_panel(page)

        source = page.locator("#parking-panel .parking-card").first
        target = page.locator('#parking-panel .parking-column[data-column="next"]')
        src_box = source.bounding_box()
        tgt_box = target.bounding_box()
        assert src_box and tgt_box

        page.mouse.move(src_box["x"] + src_box["width"] / 2, src_box["y"] + src_box["height"] / 2)
        page.mouse.down()
        # Two moves: the first crosses the drag threshold, the second lands on
        # the target column so `dragOverColumn` is set before pointerup.
        page.mouse.move(
            src_box["x"] + src_box["width"] / 2 + 30,
            src_box["y"] + src_box["height"] / 2 + 10,
            steps=4,
        )
        page.mouse.move(tgt_box["x"] + tgt_box["width"] / 2, tgt_box["y"] + 40, steps=8)
        page.wait_for_function(
            """() => {
                const c = document.querySelector(
                  '#parking-panel .parking-column[data-column="next"]');
                return !!c && c.classList.contains('drag-over');
            }""",
            timeout=5000,
        )
        page.mouse.up()

        page.wait_for_function(
            """() => {
                const col = document.querySelector(
                  '#parking-panel .parking-column[data-column="next"]');
                return !!col && col.querySelectorAll('.parking-card').length === 1;
            }""",
            timeout=8000,
        )
        board = requests.get(f"{clean_board}/api/parking/board", timeout=10).json()
        by_key = {c["key"]: c for c in board["columns"]}
        assert [i["question"] for i in by_key["next"]["items"]] == ["Drag me"]
        assert by_key["inbox"]["items"] == []
    except Exception:
        _diag(page, "parking-dragdrop")
        raise


def test_column_can_be_renamed_and_removed_without_losing_cards(
    page: Page, clean_board: str
) -> None:
    """Phase 6c: the board is the user's — rename and remove columns safely."""
    import requests

    try:
        _seed(clean_board, "Keep me safe")
        page.goto(f"{clean_board}/")
        _open_panel(page)

        page.locator("#parking-manage-columns").click()
        rename_field = page.locator("#parking-panel .parking-column-rename").first
        rename_field.fill("Brain Dump")
        rename_field.press("Enter")
        page.wait_for_function(
            """() => [...document.querySelectorAll('#parking-panel .parking-column-name')]
                     .some(n => n.textContent.trim() === 'Brain Dump')""",
            timeout=8000,
        )

        # Remove the LAST column (empty) — the card in 'inbox' must be untouched.
        # Wait for the admin list to settle after the rename's re-render first,
        # so the Remove click can't land on a row that's being replaced.
        page.wait_for_function(
            """() => document.querySelectorAll(
                 '#parking-panel .parking-column-admin-row').length === 4""",
            timeout=8000,
        )
        rows = page.locator("#parking-panel .parking-column-admin-row")
        rows.last.locator('button:has-text("Remove")').click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-column').length === 3",
            timeout=8000,
        )

        board = requests.get(f"{clean_board}/api/parking/board", timeout=10).json()
        assert board["total"] == 1, "removing a column lost a card"
        names = {c["name"] for c in board["columns"]}
        assert "Brain Dump" in names
    except Exception:
        _diag(page, "parking-columns")
        raise


# ---------------------------------------------------------------------------
# Phase 7 — clearing controls
# ---------------------------------------------------------------------------


def test_clear_single_item(page: Page, clean_board: str) -> None:
    """Phase 7a: clear ONE parked item from its card."""
    try:
        _seed(clean_board, "Clear just me", "Leave me alone")
        page.goto(f"{clean_board}/")
        _open_panel(page)
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 2",
            timeout=8000,
        )

        _card(page, "Clear just me").locator(".parking-card-clear").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 1",
            timeout=8000,
        )
        remaining = page.locator("#parking-panel .parking-card-title").inner_text()
        assert remaining.strip() == "Leave me alone"
        assert page.locator("#parking-total-count").inner_text().strip() == "1 item"
    except Exception:
        _diag(page, "parking-clear-single")
        raise


def test_clear_user_selected_subset(page: Page, clean_board: str) -> None:
    """Phase 7b: the user ticks an ARBITRARY subset and clears exactly that.

    Selection is user-driven — this picks a non-contiguous subset (1st and 3rd
    of four) precisely to prove no fixed rule (oldest N, whole column) is being
    applied under the hood.
    """
    import requests

    try:
        _seed(clean_board, "Alpha", "Beta", "Gamma", "Delta")
        page.goto(f"{clean_board}/")
        _open_panel(page)
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 4",
            timeout=8000,
        )

        page.locator("#parking-select-mode").click()
        page.wait_for_selector("#parking-clear-selected", state="visible", timeout=5000)
        # Clear-selected must be inert until something is actually chosen.
        assert page.locator("#parking-clear-selected").is_disabled()

        _card(page, "Alpha").locator(".parking-card-check").check()
        _card(page, "Gamma").locator(".parking-card-check").check()
        page.wait_for_function(
            """() => document.querySelector('#parking-selected-count')
                     .innerText.trim().startsWith('2')""",
            timeout=5000,
        )
        assert not page.locator("#parking-clear-selected").is_disabled()

        page.locator("#parking-clear-selected").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 2",
            timeout=8000,
        )
        titles = {
            t.strip() for t in page.locator("#parking-panel .parking-card-title").all_inner_texts()
        }
        assert titles == {"Beta", "Delta"}

        board = requests.get(f"{clean_board}/api/parking/board", timeout=10).json()
        assert board["total"] == 2
    except Exception:
        _diag(page, "parking-clear-subset")
        raise


def test_clear_all_and_undo(page: Page, clean_board: str) -> None:
    """Phase 7c: clear ALL, then undo — a soft clear is recoverable."""
    import requests

    try:
        _seed(clean_board, "One", "Two", "Three")
        page.goto(f"{clean_board}/")
        _open_panel(page)
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 3",
            timeout=8000,
        )

        page.locator("#parking-clear-all").click()
        page.wait_for_selector("#parking-empty", state="visible", timeout=8000)
        assert requests.get(f"{clean_board}/api/parking/board", timeout=10).json()["total"] == 0
        # Clear-all disables itself once the board is empty.
        assert page.locator("#parking-clear-all").is_disabled()

        page.locator("#parking-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 3",
            timeout=8000,
        )
        titles = {
            t.strip() for t in page.locator("#parking-panel .parking-card-title").all_inner_texts()
        }
        assert titles == {"One", "Two", "Three"}
    except Exception:
        _diag(page, "parking-clear-all")
        raise


def test_clearing_a_card_with_notes_preserves_the_note_on_undo(
    page: Page, clean_board: str
) -> None:
    """Phase 7d: undo restores the NOTE too, not just the title.

    Otherwise "undo" would silently amputate the very context that made the
    parked thought worth keeping.
    """
    try:
        import requests

        resp = requests.post(
            f"{clean_board}/api/parking/item",
            json={"question": "With a note", "notes": RICH_NOTE},
            timeout=10,
        )
        assert resp.status_code == 201

        page.goto(f"{clean_board}/")
        _open_panel(page)
        _card(page, "With a note").locator(".parking-card-clear").click()
        page.wait_for_selector("#parking-empty", state="visible", timeout=8000)
        page.locator("#parking-undo-clear").click()
        page.wait_for_selector(
            '#parking-panel .parking-card-title:has-text("With a note")',
            state="visible",
            timeout=8000,
        )

        page.locator('#parking-panel .parking-card-title:has-text("With a note")').click()
        page.wait_for_selector("#parking-note-input", state="visible", timeout=8000)
        restored = page.locator("#parking-note-input").input_value()
        assert "```mermaid" in restored
        assert "Why this mattered" in restored
    except Exception:
        _diag(page, "parking-undo-notes")
        raise


# ---------------------------------------------------------------------------
# Whole-journey walk — one page, one continuous session
# ---------------------------------------------------------------------------


def test_full_representative_parking_workflow(page: Page, clean_board: str) -> None:
    """The complete loop in ONE browser session, as a learner would live it.

    Capture mid-flow → open the board → write up the note with a diagram →
    arrange it → capture two more → clear a chosen subset → clear the rest →
    undo. The per-phase tests above pin each behaviour; this proves they
    compose without stepping on each other.
    """
    import requests

    try:
        page.goto(f"{clean_board}/#today")
        page.wait_for_function("() => !!window.Alpine", timeout=10000)

        # 1. Park a tangent without leaving the current view.
        page.keyboard.press("p")
        page.wait_for_selector(".quick-park-input", state="visible", timeout=5000)
        page.locator(".quick-park-input").fill("Nested loop join blew up")
        page.locator('.end-confirm-yes:has-text("Park it")').click()
        page.wait_for_selector(".quick-park-overlay", state="hidden", timeout=5000)

        # 2. Open the dedicated panel.
        _open_panel(page)
        page.wait_for_selector(
            '#parking-panel .parking-card-title:has-text("Nested loop join blew up")',
            timeout=8000,
        )

        # 3. Write it up properly — the "make it make sense later" step.
        page.locator(
            '#parking-panel .parking-card-title:has-text("Nested loop join blew up")'
        ).click()
        page.wait_for_selector("#parking-note-input", state="visible", timeout=8000)
        page.locator("#parking-note-input").fill("## Context\n\nStale stats on fact_orders.\n")
        # Insert a diagram with the one-click button (not hand-typed).
        page.locator("#parking-insert-diagram").click()
        page.wait_for_function(
            """() => document.querySelector('#parking-note-input')
                     .value.includes('```mermaid')""",
            timeout=5000,
        )
        page.locator("#parking-save-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#parking-save-btn').innerText.trim() === 'Saved'",
            timeout=10000,
        )
        # The inserted diagram renders (split mode shows the preview).
        page.wait_for_function(
            """() => !!document.querySelector(
                 '#parking-panel .parking-note-preview .mermaid-diagram svg')""",
            timeout=15000,
        )

        # 4. Arrange it: promote out of the inbox, then collapse the editor.
        page.locator("#parking-panel .parking-card").first.press("Escape")
        card = page.locator("#parking-panel .parking-card").first
        card.focus()
        card.press("ArrowRight")
        page.wait_for_function(
            """() => {
                const c = document.querySelector(
                  '#parking-panel .parking-column[data-column="next"]');
                return !!c && c.querySelectorAll('.parking-card').length === 1;
            }""",
            timeout=8000,
        )

        # 5. Two more captures, then clear a user-chosen subset.
        _seed(clean_board, "Tangent A", "Tangent B")
        page.evaluate("() => window.dispatchEvent(new CustomEvent('parking:changed'))")
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 3",
            timeout=8000,
        )
        page.locator("#parking-select-mode").click()
        _card(page, "Tangent A").locator(".parking-card-check").check()
        page.locator("#parking-clear-selected").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 2",
            timeout=8000,
        )

        # 6. Clear everything, then undo — the written-up note comes back whole.
        page.locator("#parking-clear-all").click()
        page.wait_for_selector("#parking-empty", state="visible", timeout=8000)
        page.locator("#parking-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 2",
            timeout=8000,
        )

        board = requests.get(f"{clean_board}/api/parking/board", timeout=10).json()
        written_up = [
            i
            for c in board["columns"]
            for i in c["items"]
            if i["question"] == "Nested loop join blew up"
        ]
        assert len(written_up) == 1, "the written-up card did not survive the journey"
        assert written_up[0]["has_diagram"] is True
        assert "## Context" in written_up[0]["notes"]
        assert written_up[0]["board_column"] == "next", "arrangement lost"

        RESULTS.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS / "parking-lot-full-journey.png"))
    except Exception:
        _diag(page, "parking-full-journey")
        raise
