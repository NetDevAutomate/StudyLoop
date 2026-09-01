"""Playwright e2e tests for ``studyloop web --dev`` (libghostty / ghostty-web).

Exercises a representative user workflow against a live server started with
``--dev``, which swaps xterm.js for ghostty-web 0.4.0 (Ghostty's VT100 parser
compiled to WASM). xterm.js remains the default path and is regression-guarded
by :class:`TestDefaultModeUnchanged`.

Requirement coverage
--------------------
1. :class:`TestResizePreservesPromptText`
   Resizing the browser resizes the terminal without losing prompt text.
2. :class:`TestThemePropagation`
   A palette change reaches the terminal *and* the surrounding web panes.
3. :class:`TestFontPropagation`
   A font change reaches the terminal *and* the web frames.
4. :class:`TestRefreshMaintainsSession`
   A browser refresh keeps the session alive.
5. :class:`TestGlyphAndEmojiSupport`
   Wide CJK, emoji, combining marks and box drawing round-trip correctly.

Why assertions go through ``window.__studyloopGhostty``
-------------------------------------------------------
ghostty-web renders to a **canvas**, so there is no DOM text to scrape (unlike
xterm.js's DOM renderer or wterm). Terminal content is therefore asserted two
ways, and both are used deliberately:

* ``readBuffer()`` — reads the real VT buffer through the xterm-compatible
  ``buffer.active.getLine(...).translateToString()`` API. This proves the
  *emulator* holds the right cells.
* canvas pixel sampling — proves the *renderer* actually repainted, which is
  what catches "theme value updated but nothing redrew" bugs.

Plan/analysis: docs/explorations/ghostty-web-evaluation.md
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.e2e]

# WASM decode + first paint is the slow step; everything else is fast.
WASM_TIMEOUT_MS = 30_000
MOUNT_TIMEOUT_MS = 20_000


# ---------------------------------------------------------------------------
# Server fixtures
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Bind port 0 to get a kernel-assigned free port.

    Avoids the hardcoded-port collisions that make parallel e2e runs flaky.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


_IPC_FILENAMES = ("session-state.json", "session-topics.md", "session-parking.md")


def _clear_ipc(session_dir: Path) -> None:
    """Clear only the transient IPC files owned by this test world."""
    for name in _IPC_FILENAMES:
        (session_dir / name).unlink(missing_ok=True)


@pytest.fixture(scope="module")
def dev_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[RunningServer, None, None]:
    """One hermetic ``--dev`` server shared by the module."""
    root = tmp_path_factory.mktemp("ghostty-dev-world")
    world = build_test_world(root, _free_port())
    server = start_server(world, extra_args=["--dev"])
    try:
        yield server
    finally:
        _clear_ipc(world.session_dir)
        server.stop()


@pytest.fixture()
def dev_page(dev_server: RunningServer, browser):
    """Fresh page + context per test, wide enough for a realistic terminal."""
    _clear_ipc(dev_server.world.session_dir)
    ctx_args: dict = {"viewport": {"width": 1400, "height": 900}}
    context = browser.new_context(**ctx_args)
    page = context.new_page()
    page._studyloop_session_dir = dev_server.world.session_dir  # type: ignore[attr-defined]
    page.goto(f"{dev_server.base_url}/#study-session")
    page.wait_for_load_state("domcontentloaded")
    try:
        yield page
    finally:
        context.close()
        _clear_ipc(dev_server.world.session_dir)


@pytest.fixture()
def default_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[RunningServer, None, None]:
    """Default xterm server for the renderer regression guard."""
    root = tmp_path_factory.mktemp("ghostty-default-world")
    world = build_test_world(root, _free_port())
    server = start_server(world)
    try:
        yield server
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Browser-side helpers
# ---------------------------------------------------------------------------

# Mounts the PTY terminal by flipping the Alpine session state and firing the
# same event the real start-session flow fires. No PTY child is spawned; the
# WebSocket 403s harmlessly, which is fine — these tests assert rendering,
# resize, theme and font behaviour, not PTY plumbing.
_MOUNT_TERMINAL_JS = """
() => {
  const root = document.querySelector('[x-data="sessionTimer()"]');
  if (root && window.Alpine) {
    const data = window.Alpine.$data(root);
    data.sessionActive = true;
    data.topic = 'ghostty-e2e';
  }
  window.dispatchEvent(new CustomEvent('study-session-start', {
    detail: {
      topic: 'ghostty-e2e', energy: 5, sessionType: 'study',
      targetKind: 'topic', agent: 'claude', resolvedAgent: 'claude',
      studySessionId: 'ghostty-e2e-1', transport: 'pty',
      wsUrl: '/api/session/ws?study_session_id=ghostty-e2e-1',
    }
  }));
}
"""

# Canvas measurements, sampled from the rendered bitmap.
#
# "Ink" is measured *relative to the modal pixel colour* (the terminal
# background), not against black. An earlier version compared against black
# and reported inkFraction == 1.0 for a blank terminal, because the default
# background #1a1b26 is not black — so every pixel counted as ink and the
# metric could never detect anything.
#
# Returns:
#   bgHex      most common pixel colour == the painted background
#   inkRatio   fraction of pixels differing noticeably from that background
#   checksum   position-weighted checksum, to detect *any* repaint
_CANVAS_STATS_JS = """
() => {
  const canvas = document.querySelector('.xterm-mount canvas');
  if (!canvas) return null;
  const ctx = canvas.getContext('2d');
  const w = Math.min(canvas.width, 600);
  const h = Math.min(canvas.height, 300);
  const data = ctx.getImageData(0, 0, w, h).data;

  const counts = new Map();
  let checksum = 0;
  for (let i = 0; i < data.length; i += 4) {
    const key = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
    counts.set(key, (counts.get(key) || 0) + 1);
    checksum = (checksum + key * ((i % 97) + 1)) % 2147483647;
  }

  let bgKey = 0, bgCount = -1;
  for (const [key, count] of counts) {
    if (count > bgCount) { bgCount = count; bgKey = key; }
  }
  const bgR = (bgKey >> 16) & 255, bgG = (bgKey >> 8) & 255, bgB = bgKey & 255;

  let ink = 0;
  const total = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    const d = Math.abs(data[i] - bgR)
            + Math.abs(data[i + 1] - bgG)
            + Math.abs(data[i + 2] - bgB);
    if (d > 24) ink += 1;
  }

  const hex = (n) => n.toString(16).padStart(2, '0');
  return {
    checksum,
    bgHex: '#' + hex(bgR) + hex(bgG) + hex(bgB),
    inkRatio: ink / total,
    distinctColours: counts.size,
    width: canvas.width,
    height: canvas.height,
  };
}
"""


def _wait_for_engine(page) -> None:
    """Wait until the ghostty adapter is installed and WASM has initialised."""
    page.wait_for_function(
        "() => typeof window.GhosttyWeb !== 'undefined'"
        " && typeof window.__studyloopGhostty !== 'undefined'",
        timeout=WASM_TIMEOUT_MS,
    )
    page.wait_for_function(
        "() => window.__studyloopGhostty.ready === true",
        timeout=WASM_TIMEOUT_MS,
    )
    error = page.evaluate("() => window.__studyloopGhostty.error")
    assert error is None, f"ghostty WASM init failed: {error}"


def _mount_terminal(page) -> None:
    """Mount the terminal and wait until the real ghostty Terminal exists."""
    _wait_for_engine(page)
    page.evaluate(_MOUNT_TERMINAL_JS)
    page.wait_for_selector(".xterm-mount", state="visible", timeout=MOUNT_TIMEOUT_MS)
    page.wait_for_function(
        "() => document.querySelector('.xterm-mount.ghostty-active') !== null",
        timeout=MOUNT_TIMEOUT_MS,
    )
    # The adapter registers itself only once the real Terminal is constructed.
    page.wait_for_function(
        "() => { const g = window.__studyloopGhostty;"
        " return g.adapter && g.adapter._term && g.adapter._term.renderer; }",
        timeout=MOUNT_TIMEOUT_MS,
    )
    page.wait_for_selector(".xterm-mount canvas", timeout=MOUNT_TIMEOUT_MS)


def _write(page, text: str) -> None:
    """Write to the terminal as if the PTY had emitted it."""
    page.evaluate(
        "(t) => window.__studyloopGhostty.adapter.write(t)",
        text,
    )


def _buffer_text(page) -> str:
    """Whole visible buffer via the xterm-compatible API (lossy for marks)."""
    lines = page.evaluate("() => window.__studyloopGhostty.readBuffer()")
    assert lines is not None, "terminal buffer unavailable"
    return "\n".join(lines)


def _grapheme_text(page) -> str:
    """Whole visible buffer with full grapheme clusters preserved.

    Reads through libghostty's ``getGraphemeString()``. Required for combining
    marks and ZWJ sequences, which the xterm-compatible ``translateToString()``
    shim collapses to one codepoint per cell.
    """
    lines = page.evaluate("() => window.__studyloopGhostty.readBufferGraphemes()")
    assert lines is not None, "grapheme buffer unavailable"
    return "\n".join(lines)


def _dims(page) -> tuple[int, int]:
    return tuple(  # type: ignore[return-value]
        page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " return [a._term.cols, a._term.rows]; }"
        )
    )


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------


class TestGhosttyEngineLoads:
    """--dev wires libghostty in without breaking the page."""

    def test_dev_meta_tag_is_ghostty(self, dev_page) -> None:
        content = dev_page.eval_on_selector(
            'meta[name="studyloop-dev-mode"]',
            "(el) => el.getAttribute('content')",
        )
        assert content == "ghostty"

    def test_ghostty_bundle_and_wasm_initialise(self, dev_page) -> None:
        """The UMD bundle loads and the inlined WASM decodes successfully.

        The WASM is a base64 data URL inside the bundle, so this also proves
        the offline/no-second-fetch property holds.
        """
        _wait_for_engine(dev_page)
        exports = dev_page.evaluate("() => Object.keys(window.GhosttyWeb)")
        assert "Terminal" in exports
        assert "FitAddon" in exports
        assert "init" in exports
        assert dev_page.evaluate("() => window.__studyloopGhostty.version") == "0.4.0"

    def test_terminal_global_is_ghostty_adapter(self, dev_page) -> None:
        """window.Terminal is the adapter, so liveAgentConsole() needs no edits."""
        _wait_for_engine(dev_page)
        assert dev_page.evaluate("() => window.Terminal.name") == "GhosttyAdapter"
        # xterm's WebGL/clipboard addons have no ghostty counterpart and must
        # not be loaded (their `if (window.X)` guards have to be falsy).
        assert dev_page.evaluate("() => window.WebglAddon") is None
        assert dev_page.evaluate("() => window.ClipboardAddon") is None

    def test_terminal_mounts_and_paints(self, dev_page) -> None:
        """A canvas is created and the startup banner reaches the VT buffer."""
        _mount_terminal(dev_page)
        cols, rows = _dims(dev_page)
        assert cols > 0 and rows > 0, f"bad dimensions: {cols}x{rows}"
        # liveAgentConsole writes this synchronously, before WASM was ready —
        # proving the adapter's replay queue works.
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || [])"
            ".join('\\n').includes('Connecting to agent')",
            timeout=MOUNT_TIMEOUT_MS,
        )

    def test_no_page_errors_during_startup(self, dev_server: RunningServer, browser) -> None:
        """No uncaught JS errors are introduced by the ghostty swap."""
        ctx_args: dict = {"viewport": {"width": 1400, "height": 900}}
        context = browser.new_context(**ctx_args)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        try:
            page.goto(f"{dev_server.base_url}/#study-session")
            page.wait_for_load_state("domcontentloaded")
            _mount_terminal(page)
            # Pre-existing app-level error, present in default mode too, so it
            # is not attributable to the ghostty swap.
            fatal = [e for e in errors if "reading 'type'" not in e]
            assert not fatal, f"unexpected JS errors: {fatal}"
        finally:
            context.close()


# ---------------------------------------------------------------------------
# 1. Resize
# ---------------------------------------------------------------------------


class TestResizePreservesPromptText:
    """Resizing the browser resizes the terminal without losing prompt text."""

    def test_resize_changes_dimensions_and_keeps_prompt(self, dev_page) -> None:
        _mount_terminal(dev_page)

        prompt = "study@loop:~$ echo resize-probe"
        _write(dev_page, f"\r\n{prompt}\r\n")
        dev_page.wait_for_function(
            "(p) => (window.__studyloopGhostty.readBuffer() || []).join('\\n').includes(p)",
            arg=prompt,
            timeout=10_000,
        )

        wide_cols, wide_rows = _dims(dev_page)

        # Shrink: FitAddon's ResizeObserver should recompute cols/rows.
        dev_page.set_viewport_size({"width": 820, "height": 560})
        dev_page.wait_for_function(
            "([c, r]) => { const t = window.__studyloopGhostty.adapter._term;"
            " return t.cols !== c || t.rows !== r; }",
            arg=[wide_cols, wide_rows],
            timeout=15_000,
        )
        narrow_cols, narrow_rows = _dims(dev_page)
        assert (narrow_cols, narrow_rows) != (wide_cols, wide_rows), (
            "terminal did not resize with the viewport"
        )
        assert narrow_cols < wide_cols, (
            f"expected fewer columns after shrink: {wide_cols} -> {narrow_cols}"
        )
        # The prompt must survive the reflow — this is the regression the
        # requirement names explicitly.
        assert prompt in _buffer_text(dev_page), "prompt text lost after shrinking the viewport"

        # Grow back: dimensions recover and the text is still there.
        dev_page.set_viewport_size({"width": 1400, "height": 900})
        dev_page.wait_for_function(
            "([c, r]) => { const t = window.__studyloopGhostty.adapter._term;"
            " return t.cols !== c || t.rows !== r; }",
            arg=[narrow_cols, narrow_rows],
            timeout=15_000,
        )
        grown_cols, _ = _dims(dev_page)
        assert grown_cols > narrow_cols, (
            f"expected more columns after growing: {narrow_cols} -> {grown_cols}"
        )
        assert prompt in _buffer_text(dev_page), "prompt text lost after growing the viewport"

    def test_resize_notifies_pty_with_new_dimensions(self, dev_page) -> None:
        """onResize fires so a real PTY would receive TIOCSWINSZ."""
        _mount_terminal(dev_page)
        dev_page.evaluate(
            """() => {
              window.__resizeEvents = [];
              window.__studyloopGhostty.adapter.onResize((d) => {
                window.__resizeEvents.push(d);
              });
            }"""
        )
        dev_page.set_viewport_size({"width": 900, "height": 620})
        dev_page.wait_for_function("() => (window.__resizeEvents || []).length > 0", timeout=15_000)
        events = dev_page.evaluate("() => window.__resizeEvents")
        assert events and events[-1]["cols"] > 0 and events[-1]["rows"] > 0


# ---------------------------------------------------------------------------
# 2. Theme
# ---------------------------------------------------------------------------


class TestThemePropagation:
    """A palette change reaches the terminal AND the surrounding web panes.

    This is the behaviour the xterm.js path gets wrong twice over: it snapshots
    the theme once at construction, and it reads the CSS variables off
    ``document.documentElement`` where the palette overrides never land (they
    are applied to ``body[data-palette]``).
    """

    # Dracula's --bg, straight from style.css.
    DRACULA_BG = "#282a36"
    TOKYO_BG = "#1a1b26"

    def test_palette_change_updates_terminal_theme(self, dev_page) -> None:
        _mount_terminal(dev_page)
        _write(dev_page, "\r\ntheme probe \x1b[32mgreen\x1b[0m \x1b[31mred\x1b[0m\r\n")

        before = dev_page.evaluate("() => window.__studyloopGhostty.appliedTheme.background")
        assert before.lower() == self.TOKYO_BG, f"unexpected default bg: {before}"

        dev_page.evaluate("() => window.Alpine.store('settings').setPalette('dracula')")
        dev_page.wait_for_function(
            "(bg) => window.__studyloopGhostty.appliedTheme.background.toLowerCase() === bg",
            arg=self.DRACULA_BG,
            timeout=10_000,
        )

        theme = dev_page.evaluate("() => window.__studyloopGhostty.appliedTheme")
        assert theme["background"].lower() == self.DRACULA_BG
        # Dracula's accent/foreground differ from tokyo-night too, so a full
        # palette really was rebuilt rather than just the background.
        assert theme["foreground"].lower() == "#f8f8f2"
        assert theme["cursor"].lower() == "#bd93f9"

    def test_palette_change_repaints_the_canvas(self, dev_page) -> None:
        """The renderer actually redraws — not just the tracked theme value.

        Asserts on the *painted* background colour, which is the strongest
        available signal: ghostty-web renders each frame with dirty tracking
        and only paints a background for cells that carry a non-default one,
        so a palette swap leaves the canvas untouched unless the adapter
        explicitly re-fills it and forces a full repaint.
        """
        _mount_terminal(dev_page)
        _write(dev_page, "\r\n" + ("repaint-probe " * 6) + "\r\n")
        dev_page.wait_for_timeout(500)

        before = dev_page.evaluate(_CANVAS_STATS_JS)
        assert before is not None, "no canvas found"
        assert before["bgHex"].lower() == self.TOKYO_BG, (
            f"expected tokyo-night background on canvas, got {before['bgHex']}"
        )
        assert before["inkRatio"] > 0, f"canvas has no text drawn at all: {before}"

        dev_page.evaluate("() => window.Alpine.store('settings').setPalette('dracula')")
        dev_page.wait_for_function(
            "(bg) => window.__studyloopGhostty.appliedTheme.background.toLowerCase() === bg",
            arg=self.DRACULA_BG,
            timeout=10_000,
        )
        # Poll the bitmap: the repaint lands on an animation frame.
        dev_page.wait_for_function(
            """(bg) => {
              const c = document.querySelector('.xterm-mount canvas');
              if (!c) return false;
              const d = c.getContext('2d').getImageData(0, 0, 40, 20).data;
              const counts = new Map();
              for (let i = 0; i < d.length; i += 4) {
                const k = (d[i] << 16) | (d[i+1] << 8) | d[i+2];
                counts.set(k, (counts.get(k) || 0) + 1);
              }
              let best = 0, bestC = -1;
              for (const [k, n] of counts) { if (n > bestC) { bestC = n; best = k; } }
              const hex = (n) => n.toString(16).padStart(2, '0');
              const got = '#' + hex((best >> 16) & 255)
                        + hex((best >> 8) & 255) + hex(best & 255);
              return got === bg;
            }""",
            arg=self.DRACULA_BG,
            timeout=10_000,
        )

        after = dev_page.evaluate(_CANVAS_STATS_JS)
        assert after["bgHex"].lower() == self.DRACULA_BG, (
            f"canvas background did not repaint: {after['bgHex']}"
        )
        assert after["checksum"] != before["checksum"], (
            "canvas pixels unchanged after palette switch"
        )
        # Text is still drawn after the repaint — the re-fill did not wipe it.
        assert after["inkRatio"] > 0, f"repaint wiped the terminal text: {after}"

    def test_palette_change_also_restyles_web_panes(self, dev_page) -> None:
        """Same switch restyles the surrounding UI, so the two stay in step."""
        _mount_terminal(dev_page)

        pane_before = dev_page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        var_before = dev_page.evaluate(
            "() => getComputedStyle(document.body).getPropertyValue('--bg').trim()"
        )

        dev_page.evaluate("() => window.Alpine.store('settings').setPalette('dracula')")
        dev_page.wait_for_function(
            "(bg) => getComputedStyle(document.body)"
            ".getPropertyValue('--bg').trim().toLowerCase() === bg",
            arg=self.DRACULA_BG,
            timeout=10_000,
        )

        pane_after = dev_page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        var_after = dev_page.evaluate(
            "() => getComputedStyle(document.body).getPropertyValue('--bg').trim()"
        )
        assert var_after.lower() == self.DRACULA_BG
        assert var_before.lower() != var_after.lower()
        assert pane_before != pane_after, "web pane background did not change"

        # And the terminal converges on the same value — one source of truth.
        # Waited for rather than read instantly: the CSS variable updates
        # synchronously with the attribute, while the adapter propagates on the
        # next animation frame. The contract is that they agree, not that they
        # change in the same tick.
        dev_page.wait_for_function(
            """() => {
              const pane = getComputedStyle(document.body)
                .getPropertyValue('--bg').trim().toLowerCase();
              const term = window.__studyloopGhostty.appliedTheme;
              return !!term && term.background.toLowerCase() === pane;
            }""",
            timeout=10_000,
        )
        term_bg = dev_page.evaluate("() => window.__studyloopGhostty.appliedTheme.background")
        assert term_bg.lower() == var_after.lower(), (
            f"terminal bg {term_bg} disagrees with pane var {var_after}"
        )

    @pytest.mark.parametrize(
        ("palette", "expected_bg"),
        [
            ("nord", "#2e3440"),
            ("gruvbox-dark", "#282828"),
            ("catppuccin-latte", "#eff1f5"),
        ],
    )
    def test_multiple_palettes_propagate(self, dev_page, palette, expected_bg) -> None:
        """Propagation is generic, not special-cased for one palette.

        catppuccin-latte is a light palette, so this also covers the
        dark -> light transition.
        """
        _mount_terminal(dev_page)
        dev_page.evaluate("(p) => window.Alpine.store('settings').setPalette(p)", palette)
        dev_page.wait_for_function(
            "(bg) => window.__studyloopGhostty.appliedTheme.background.toLowerCase() === bg",
            arg=expected_bg,
            timeout=10_000,
        )
        assert (
            dev_page.evaluate("() => window.__studyloopGhostty.appliedTheme.background").lower()
            == expected_bg
        )


# ---------------------------------------------------------------------------
# 3. Font
# ---------------------------------------------------------------------------


class TestFontPropagation:
    """A font change reaches the terminal AND the web frames."""

    def test_font_picker_updates_terminal_and_prose(self, dev_page) -> None:
        _mount_terminal(dev_page)

        font_before = dev_page.evaluate("() => window.__studyloopGhostty.appliedFont")
        prose_before = dev_page.evaluate(
            "() => getComputedStyle(document.body).getPropertyValue('--font').trim()"
        )

        dev_page.evaluate("() => window.Alpine.store('settings').setFont('atkinson')")
        dev_page.wait_for_function(
            "() => window.__studyloopGhostty.appliedFont.fontFamily.includes('Atkinson')",
            timeout=10_000,
        )

        font_after = dev_page.evaluate("() => window.__studyloopGhostty.appliedFont")
        prose_after = dev_page.evaluate(
            "() => getComputedStyle(document.body).getPropertyValue('--font').trim()"
        )

        # Terminal side.
        assert "Atkinson" in font_after["fontFamily"]
        assert font_after["fontFamily"] != font_before["fontFamily"]
        assert font_after["fontSize"] != font_before["fontSize"], (
            "expected the legibility font to bump terminal font size"
        )
        # Web-frame side.
        assert "Atkinson" in prose_after
        assert prose_before != prose_after, "prose font variable did not change"

    def test_font_change_is_applied_to_the_live_renderer(self, dev_page) -> None:
        """The change reaches ghostty's renderer, not just the adapter's record.

        A larger font means wider cells, so FitAddon must land on fewer
        columns — measurable proof the renderer re-measured.
        """
        _mount_terminal(dev_page)
        cols_before, _ = _dims(dev_page)
        size_before = dev_page.evaluate(
            "() => window.__studyloopGhostty.adapter._term.options.fontSize"
        )

        dev_page.evaluate("() => window.Alpine.store('settings').setFont('atkinson')")
        dev_page.wait_for_function(
            "(s) => window.__studyloopGhostty.adapter._term.options.fontSize !== s",
            arg=size_before,
            timeout=10_000,
        )

        opts = dev_page.evaluate(
            "() => { const o = window.__studyloopGhostty.adapter._term.options;"
            " return { fontFamily: o.fontFamily, fontSize: o.fontSize }; }"
        )
        assert "Atkinson" in opts["fontFamily"]
        assert opts["fontSize"] > size_before

        dev_page.wait_for_function(
            "(c) => window.__studyloopGhostty.adapter._term.cols < c",
            arg=cols_before,
            timeout=15_000,
        )
        cols_after, _ = _dims(dev_page)
        assert cols_after < cols_before, (
            f"larger font should reduce columns: {cols_before} -> {cols_after}"
        )

    def test_dyslexic_toggle_reaches_the_terminal(self, dev_page) -> None:
        """OpenDyslexic applies to the terminal too, not only to prose.

        The accessibility toggle would otherwise stop at the terminal edge —
        exactly the kind of half-applied setting this work is meant to fix.
        """
        _mount_terminal(dev_page)
        dev_page.evaluate("() => window.Alpine.store('settings').setFont('opendyslexic')")
        dev_page.wait_for_function(
            "() => window.__studyloopGhostty.appliedFont.fontFamily.includes('OpenDyslexic')",
            timeout=10_000,
        )
        assert dev_page.evaluate("() => document.body.getAttribute('data-font') === 'opendyslexic'")
        font = dev_page.evaluate("() => window.__studyloopGhostty.appliedFont")
        assert "OpenDyslexic" in font["fontFamily"]


# ---------------------------------------------------------------------------
# 4. Refresh
# ---------------------------------------------------------------------------


class TestRefreshMaintainsSession:
    """A browser refresh keeps the session — state, engine and theme.

    SCOPE: these tests write session state to disk with **no live WebSocket
    attached**, so they validate state restore, dev-engine re-initialisation
    and palette persistence across a reload. They do NOT prove that a *live*
    PTY session survives a refresh — it does not.

    ``test_ghostty_live_session_journey.py::TestLiveRefresh`` covers that case
    against a real agent and records the reason: a refresh closes the session
    WebSocket, and ``web/routes/session/_ws.py`` releases the session in a
    ``finally`` block, killing the agent. That is a pre-existing,
    engine-independent defect (reproduced on the default xterm.js path) and is
    tracked there as a strict xfail.
    """

    @staticmethod
    def _write_active_session_state(session_dir: Path) -> dict:
        """Persist an active session to the IPC file the server reads.

        ``tmux_session`` is deliberately omitted: the server's zombie check
        clears any state whose tmux session is dead, which would erase this
        fixture before the page could read it.

        The session directory is supplied by the running test world, rather
        than resolved from the parent process's environment.
        """
        session_dir.mkdir(parents=True, exist_ok=True)
        state_file = session_dir / "session-state.json"
        state = {
            "study_session_id": "ghostty-refresh-1",
            "topic": "Ghostty Refresh Topic",
            "energy": 7,
            "mode": "study",
            "start_time": "2026-08-03T10:00:00",
            "started_at": "2026-08-03T10:00:00",
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return state

    @staticmethod
    def _await_server_sees_session(page, session_id: str) -> None:
        """Block until the server reports the session.

        Establishes the precondition explicitly instead of assuming the write
        is visible: without this the test asserts on a race and fails with an
        opaque KeyError when it loses.
        """
        page.wait_for_function(
            """async (id) => {
              const res = await fetch('/api/session/state', { cache: 'no-store' });
              if (!res.ok) return false;
              const state = await res.json();
              return state.study_session_id === id;
            }""",
            arg=session_id,
            timeout=15_000,
        )

    def test_session_state_survives_reload(self, dev_page) -> None:
        state = self._write_active_session_state(dev_page._studyloop_session_dir)
        self._await_server_sees_session(dev_page, state["study_session_id"])

        dev_page.reload()
        dev_page.wait_for_load_state("domcontentloaded")

        # Server still reports the session after the refresh.
        served = dev_page.evaluate(
            "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
        )
        assert served.get("study_session_id") == state["study_session_id"], (
            f"session lost across reload; server returned {served!r}"
        )

        # Client restored it into the dashboard.
        dev_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              if (!root || !window.Alpine) return false;
              const d = window.Alpine.$data(root);
              return d.sessionActive === true;
            }""",
            timeout=15_000,
        )
        restored = dev_page.evaluate(
            """() => {
              const d = window.Alpine.$data(
                document.querySelector('[x-data="sessionTimer()"]'));
              return { active: d.sessionActive, topic: d.topic };
            }"""
        )
        assert restored["active"] is True
        assert restored["topic"] == state["topic"]

    def test_engine_and_terminal_recover_after_reload(self, dev_page) -> None:
        """The dev engine survives a refresh and can serve a terminal again."""
        _mount_terminal(dev_page)
        _write(dev_page, "\r\nbefore-reload-marker\r\n")
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || [])"
            ".join('\\n').includes('before-reload-marker')",
            timeout=10_000,
        )
        state = self._write_active_session_state(dev_page._studyloop_session_dir)
        self._await_server_sees_session(dev_page, state["study_session_id"])

        dev_page.reload()
        dev_page.wait_for_load_state("domcontentloaded")

        # Engine re-initialises (fresh WASM instance) and re-mounts cleanly.
        _mount_terminal(dev_page)
        assert dev_page.evaluate("() => window.Terminal.name") == "GhosttyAdapter"
        cols, rows = _dims(dev_page)
        assert cols > 0 and rows > 0

        _write(dev_page, "\r\nafter-reload-marker\r\n")
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || [])"
            ".join('\\n').includes('after-reload-marker')",
            timeout=10_000,
        )

    def test_theme_choice_survives_reload(self, dev_page) -> None:
        """A palette picked before the refresh is re-applied to the terminal.

        Covers the ordering hazard: on reload the palette is restored from
        localStorage during Alpine init, which may land before or after the
        WASM finishes loading. The terminal must end up correct either way.
        """
        _mount_terminal(dev_page)
        dev_page.evaluate("() => window.Alpine.store('settings').setPalette('nord')")
        dev_page.wait_for_function(
            "() => window.__studyloopGhostty.appliedTheme.background.toLowerCase() === '#2e3440'",
            timeout=10_000,
        )
        state = self._write_active_session_state(dev_page._studyloop_session_dir)
        self._await_server_sees_session(dev_page, state["study_session_id"])

        dev_page.reload()
        dev_page.wait_for_load_state("domcontentloaded")
        _mount_terminal(dev_page)

        assert dev_page.evaluate("() => document.body.dataset.palette") == "nord"
        dev_page.wait_for_function(
            "() => window.__studyloopGhostty.appliedTheme.background.toLowerCase() === '#2e3440'",
            timeout=10_000,
        )


# ---------------------------------------------------------------------------
# 5. Glyphs and emoji
# ---------------------------------------------------------------------------


class TestGlyphAndEmojiSupport:
    """Emoji, wide CJK, box drawing, accents and grapheme clusters.

    Two views of terminal content are asserted deliberately:

    * ``readBuffer()`` — the xterm-compatible ``translateToString()`` path,
      which returns one codepoint per cell and so loses combining marks.
    * ``readBufferGraphemes()`` — libghostty's ``getGraphemeString()``, which
      preserves whole clusters. This is the accurate view, and the reason
      libghostty is preferable to xterm.js for complex scripts.

    The lossiness of the first is pinned by
    :meth:`test_translate_to_string_is_lossy_for_combining_marks` so that an
    upstream fix is noticed rather than silently assumed.
    """

    def test_emoji_round_trip_through_the_buffer(self, dev_page) -> None:
        _mount_terminal(dev_page)
        emoji = "🎯 🧠 ✅ 🚀 🔥"
        _write(dev_page, f"\r\n{emoji}\r\n")
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || []).join('\\n').includes('🎯')",
            timeout=10_000,
        )
        text = _buffer_text(dev_page)
        for glyph in ("🎯", "🧠", "✅", "🚀", "🔥"):
            assert glyph in text, f"emoji {glyph} missing from terminal buffer"

    def test_cjk_box_drawing_and_precomposed_accents(self, dev_page) -> None:
        """The scripts and glyph sets a study terminal actually renders.

        Covers double-width CJK/Hangul, box drawing (TUI frames), Powerline
        private-use glyphs (agent prompts) and precomposed Latin accents.
        """
        _mount_terminal(dev_page)
        samples = {
            "cjk": "日本語のテキスト",
            "hangul": "한국어",
            "accents": "éàüñǎ",
            "box": "┌─┬─┐│├─┼─┤└─┴─┘",
            "blocks": "░▒▓█▁▂▃▄▅▆▇",
            "powerline": "\ue0b0\ue0b2",
            "marks": "✔✘→←↑↓",
        }
        for label, sample in samples.items():
            _write(dev_page, f"\r\n{label}:{sample}\r\n")

        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || []).join('\\n').includes('marks:')",
            timeout=10_000,
        )
        text = _buffer_text(dev_page)
        for label, sample in samples.items():
            assert sample in text, f"{label} sample {sample!r} did not survive the terminal buffer"

    def test_wide_glyphs_occupy_two_cells(self, dev_page) -> None:
        """CJK width handling is correct, not merely byte-preserving.

        A double-width run must consume twice as many columns as an ASCII run
        of the same character count — the property naive emulators get wrong,
        and the one that misaligns every TUI drawn beside CJK text.
        """
        _mount_terminal(dev_page)
        result = dev_page.evaluate(
            """async () => {
              const a = window.__studyloopGhostty.adapter;
              const term = a._term;
              term.clear();
              a.write('\\r\\n');
              a.write('日本語');          // 3 chars, expect 6 columns
              await new Promise((r) => setTimeout(r, 300));
              const wideCursor = term.wasmTerm.getCursor().x;
              term.clear();
              a.write('\\r\\n');
              a.write('abc');             // 3 chars, expect 3 columns
              await new Promise((r) => setTimeout(r, 300));
              const asciiCursor = term.wasmTerm.getCursor().x;
              return { wideCursor, asciiCursor };
            }"""
        )
        assert result["asciiCursor"] == 3, (
            f"ASCII cursor should advance 3 columns, got {result['asciiCursor']}"
        )
        assert result["wideCursor"] == 6, (
            "double-width CJK should advance 6 columns, got "
            f"{result['wideCursor']} — width handling is wrong"
        )

    def test_glyphs_are_actually_drawn(self, dev_page) -> None:
        """Emoji and CJK reach the canvas, not just the buffer.

        Guards against a renderer that silently drops glyphs it cannot shape:
        the buffer would still report them while the user saw blanks.
        """
        _mount_terminal(dev_page)
        dev_page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " a._term.clear(); a.write('\\r\\n'); }"
        )
        dev_page.wait_for_timeout(500)
        blank = dev_page.evaluate(_CANVAS_STATS_JS)

        _write(dev_page, "🎯🧠✅🚀🔥 日本語 ┌─┬─┐\r\n")
        dev_page.wait_for_timeout(700)
        drawn = dev_page.evaluate(_CANVAS_STATS_JS)

        assert drawn["inkRatio"] > blank["inkRatio"], (
            "canvas ink did not increase after writing glyphs — nothing rendered "
            f"(blank={blank['inkRatio']:.5f}, drawn={drawn['inkRatio']:.5f})"
        )
        # Emoji are colour glyphs, so a successful draw introduces colours the
        # near-monochrome blank canvas did not have.
        assert drawn["distinctColours"] > blank["distinctColours"], (
            "no new colours after drawing emoji — colour glyphs not rendered "
            f"(blank={blank['distinctColours']}, drawn={drawn['distinctColours']})"
        )

    # ------------------------------------------------------------------
    # Grapheme clusters — the headline reason to prefer libghostty.
    # ------------------------------------------------------------------

    def test_combining_marks_survive_as_grapheme_clusters(self, dev_page) -> None:
        """Devanagari conjuncts and stacked combining marks are preserved.

        libghostty stores a full grapheme cluster per cell, so 'स्'
        (U+0938 + virama U+094D) and 'ते' (U+0924 + vowel sign U+0947) stay
        intact — the case xterm.js is documented to get wrong.

        Asserted through the grapheme API rather than translateToString(),
        which is a lossy xterm-compat shim (see
        test_translate_to_string_is_lossy_for_combining_marks).
        """
        _mount_terminal(dev_page)
        dev_page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " a._term.clear(); a.write('\\r\\n'); }"
        )
        _write(dev_page, "नमस्ते")
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBufferGraphemes() || []).join('').includes('न')",
            timeout=10_000,
        )
        text = _grapheme_text(dev_page)
        assert "नमस्ते" in text, f"Devanagari grapheme clusters not preserved; buffer held {text!r}"

    def test_stacked_combining_accent_is_preserved(self, dev_page) -> None:
        """A base char plus a combining diaeresis stays one cluster."""
        _mount_terminal(dev_page)
        dev_page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " a._term.clear(); a.write('\\r\\n'); }"
        )
        _write(dev_page, "ǎ\u0308")
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBufferGraphemes() || [])"
            ".join('').includes('\u01ce')",
            timeout=10_000,
        )
        assert "ǎ\u0308" in _grapheme_text(dev_page), (
            "combining diaeresis U+0308 lost from its base character"
        )

    def test_zwj_emoji_sequence_occupies_one_cell(self, dev_page) -> None:
        """A ZWJ family emoji stays a single grapheme, not three emoji."""
        _mount_terminal(dev_page)
        family = "👨\u200d👩\u200d👧"
        dev_page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " a._term.clear(); a.write('\\r\\n'); }"
        )
        _write(dev_page, family)
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBufferGraphemes() || []).join('').includes('👨')",
            timeout=10_000,
        )
        assert family in _grapheme_text(dev_page), (
            "ZWJ family emoji was split into separate codepoints"
        )
        # And it is stored in ONE cell, proving cluster handling rather than
        # accidental adjacency.
        cell = dev_page.evaluate(
            """() => {
              const t = window.__studyloopGhostty.adapter._term;
              const row = t.wasmTerm.getCursor().y;
              return t.wasmTerm.getGraphemeString(row, 0);
            }"""
        )
        assert cell == family, f"expected the whole cluster in cell 0, got {cell!r}"

    def test_translate_to_string_is_lossy_for_combining_marks(self, dev_page) -> None:
        """Pin the xterm-compat shim's known lossiness.

        ghostty-web's ``translateToString()`` / ``getCell().getChars()`` return
        one codepoint per cell, so combining marks are dropped even though the
        VT layer stored them (proved by the grapheme tests above). Any StudyLoop
        feature that scrapes terminal text must use the grapheme API instead.
        Pinned as a test so an upstream fix is noticed rather than assumed.
        """
        _mount_terminal(dev_page)
        dev_page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " a._term.clear(); a.write('\\r\\n'); }"
        )
        _write(dev_page, "नमस्ते")
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || []).join('').includes('न')",
            timeout=10_000,
        )
        lossy = _buffer_text(dev_page)
        accurate = _grapheme_text(dev_page)
        assert "नमस्ते" in accurate, "grapheme API should be accurate"
        assert "नमस्ते" not in lossy, (
            "translateToString() now preserves combining marks — upstream "
            "improved; drop this test and simplify readBuffer()"
        )
        assert "नमसत" in lossy, f"expected base-consonant-only fallback, got {lossy!r}"


class TestKeyboardInput:
    """Keystrokes reach the PTY — the path synthetic writes cannot exercise.

    Regression guard for an inverted-contract bug that shipped briefly and is
    invisible to any test that drives the terminal with ``adapter.write()``:

    * xterm.js ``attachCustomKeyEventHandler``: return **false** to stop the
      key reaching the terminal; true means "handle normally".
    * ghostty-web: return **true** to consume the key.

    ``liveAgentConsole()`` returns true for every non-Ctrl-\\ key, so passing
    its handler through unwrapped swallowed **all** input. The terminal still
    rendered agent output perfectly, so it looked healthy while being unusable.
    """

    def test_typing_emits_data(self, dev_page) -> None:
        _mount_terminal(dev_page)
        dev_page.evaluate(
            """() => {
              window.__emitted = [];
              window.__studyloopGhostty.adapter.onData((d) => window.__emitted.push(d));
            }"""
        )
        dev_page.click(".xterm-mount")
        dev_page.keyboard.type("abc")
        dev_page.keyboard.press("Enter")
        dev_page.wait_for_function("() => (window.__emitted || []).length >= 4", timeout=10_000)
        emitted = dev_page.evaluate("() => window.__emitted")
        assert emitted[:3] == ["a", "b", "c"], f"unexpected key data: {emitted!r}"
        assert "\r" in emitted, f"Enter did not produce CR: {emitted!r}"

    def test_printable_keys_reach_the_terminal_buffer(self, dev_page) -> None:
        """Typed characters are echoed into the emulator by the local echo path.

        Uses the terminal's own echo of injected input so no PTY is needed:
        ``input()`` is the API xterm exposes for programmatic user input.
        """
        _mount_terminal(dev_page)
        dev_page.evaluate(
            "() => { const a = window.__studyloopGhostty.adapter;"
            " a._term.clear(); a.write('\\r\\n'); }"
        )
        # Echo what the key path produces, mirroring a PTY in cooked mode.
        dev_page.evaluate(
            """() => {
              const a = window.__studyloopGhostty.adapter;
              a.onData((d) => a.write(d));
            }"""
        )
        dev_page.click(".xterm-mount")
        dev_page.keyboard.type("keypath")
        # MOUNT_TIMEOUT_MS, not the 10s used by its two sibling keystroke tests.
        # Those wait on a JS array that onData appends to synchronously; this one
        # waits on readBuffer(), so its chain also includes the wasm renderer --
        # the subsystem this file already calibrates at 20s to mount and 30s to
        # load. A 10s ceiling on the longer chain was inconsistent with that, and
        # this was the only failure in 500 unscaled e2e tests.
        #
        # A fixed number, checkable against the constant above, and it does not
        # move with the size of the run. Nor can it now hide a server error: the
        # per-test server-log detector fails a test on an unhandled exception
        # independently of any timeout, which is why that landed first.
        dev_page.wait_for_function(
            "() => (window.__studyloopGhostty.readBuffer() || []).join('\\n').includes('keypath')",
            timeout=MOUNT_TIMEOUT_MS,
        )
        assert "keypath" in _buffer_text(dev_page)

    def test_handler_returning_false_consumes_the_key(self, dev_page) -> None:
        """xterm semantics preserved: false means the app consumed the key.

        Ctrl-\\ (focus escape) relies on this, so the inversion must not be a
        blanket "always pass through".
        """
        _mount_terminal(dev_page)
        dev_page.evaluate(
            """() => {
              window.__emitted = [];
              window.__seen = [];
              const a = window.__studyloopGhostty.adapter;
              a.onData((d) => window.__emitted.push(d));
              a.attachCustomKeyEventHandler((ev) => {
                window.__seen.push(ev.key);
                return ev.key !== 'x';   // consume 'x', pass everything else
              });
            }"""
        )
        dev_page.click(".xterm-mount")
        dev_page.keyboard.type("axb")
        dev_page.wait_for_function("() => (window.__emitted || []).length >= 2", timeout=10_000)
        dev_page.wait_for_timeout(300)
        emitted = dev_page.evaluate("() => window.__emitted")
        seen = dev_page.evaluate("() => window.__seen")
        assert "x" in seen, f"handler was not consulted for 'x': {seen!r}"
        assert "a" in emitted and "b" in emitted, f"pass-through keys were lost: {emitted!r}"
        assert "x" not in emitted, f"'x' should have been consumed by the handler: {emitted!r}"


# ---------------------------------------------------------------------------
# Regression guard: default path untouched
# ---------------------------------------------------------------------------


class TestDefaultModeUnchanged:
    """Without --dev, xterm.js is still the renderer — the whole point of the gate."""

    def test_default_mode_loads_xterm_not_ghostty(
        self, browser, default_server: RunningServer
    ) -> None:
        ctx_args: dict = {"viewport": {"width": 1200, "height": 800}}
        context = browser.new_context(**ctx_args)
        page = context.new_page()
        try:
            page.goto(f"{default_server.base_url}/")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_function(
                "() => typeof window.Terminal === 'function'"
                " && typeof window.FitAddon === 'object'",
                timeout=10_000,
            )
            assert page.evaluate("() => window.Terminal.name") != "GhosttyAdapter"
            assert page.evaluate("() => typeof window.GhosttyWeb === 'undefined'")
            assert page.evaluate("() => typeof window.__studyloopGhostty === 'undefined'")
            assert page.query_selector('meta[name="studyloop-dev-mode"]') is None
        finally:
            context.close()
