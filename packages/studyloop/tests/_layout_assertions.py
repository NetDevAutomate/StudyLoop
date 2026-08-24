"""Reusable Playwright geometry assertions for layout-regression tests.

WHY THIS EXISTS
---------------
DOM-presence assertions (``is_visible()``, ``text_content()``) are blind to
visual layout. Two ``display:block`` elements forced into a flex row both
report ``is_visible() == True`` and the right text *while visually
overlapping*. A whole sweep of "passing" functional tests missed a header
where the title overlapped its description, and a layout shell that clipped
the bottom of a form — because nothing asserted geometry.

These helpers assert against ``getBoundingClientRect()`` (the real painted
box) so that overlap, clipping, off-viewport, wrapping, and zero-size bugs
are caught automatically. Each assertion is named for the bug class it
catches and documents the real bug that motivated it.

USAGE
-----
All helpers take a Playwright ``Page`` plus CSS selector(s). They raise
``AssertionError`` with the offending bounding boxes on failure. Selectors
must resolve to a *visible* element unless noted; use the page's own
wait/navigation helpers to reach the right view state first.

    from _layout_assertions import (
        assert_stacked_no_overlap, assert_within_viewport,
        assert_hidden_when_class_present, assert_nonzero_size,
        assert_centered_in, assert_single_line,
    )

    assert_stacked_no_overlap(page, ".panel header h2", ".panel header p")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


# JS helper injected into every evaluate(): returns the first *visible* match
# for a selector. Critical because StudyLoop views are kept in the DOM and
# toggled via x-show (display:none); a bare document.querySelector would
# return a hidden instance of a shared class (.nav-bar, .nav-spacer, .shortcuts
# all appear in multiple view subtrees). "Visible" = laid out: offsetParent is
# non-null (or it's an SVG node with a real rect). The spacer case is special:
# an empty flex spacer has 0 height but a real width and IS visible, so we
# treat "laid out and has non-zero width OR height" as visible.
# Body of a JS helper that returns the first *visible* element matching a
# selector. Embedded as a nested function inside each evaluate() arrow body
# (Playwright requires the whole expression to be ONE function, so this is
# spliced in — not prepended as a separate declaration). Critical because
# StudyLoop views are kept in the DOM and toggled via x-show (display:none);
# a bare document.querySelector would return a hidden instance of a shared
# class (.nav-bar, .nav-spacer, .shortcuts all appear in multiple view
# subtrees). "Visible" = laid out: offsetParent non-null, or a real rect
# (an empty flex spacer has 0 height but real width and IS visible).
_VIS_FN = """
        function __vis(sel) {
            for (const el of document.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect();
                if (el.offsetParent !== null || r.width > 0 || r.height > 0) return el;
            }
            return null;
        }
"""


def _rect(page: Page, selector: str) -> dict | None:
    """Return the bounding rect of the first *visible* match, or None.

    Picks the first laid-out match (not merely the first in DOM order) so
    shared classes across x-show-toggled views don't resolve to a hidden
    instance. Returns None when no visible match exists.
    """
    return page.evaluate(
        """(sel) => {"""
        + _VIS_FN
        + """
            const el = __vis(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                    width: r.width, height: r.height};
        }""",
        selector,
    )


def assert_stacked_no_overlap(page: Page, upper: str, lower: str) -> None:
    """Assert ``upper`` sits entirely above ``lower`` with matching left edge.

    Catches the header collision class: the global ``header { display:flex }``
    rule cascaded into a nested ``<header class="body-double-header">``,
    laying its <h2> beside its <p> so they overlapped. A stacked content
    header must have the title's bottom <= the description's top, and both
    left-aligned (a flex *row* would put them at different lefts).
    """
    a = _rect(page, upper)
    b = _rect(page, lower)
    assert a is not None, f"upper element not laid out: {upper!r}"
    assert b is not None, f"lower element not laid out: {lower!r}"
    assert b["top"] >= a["bottom"] - 1, (
        f"{upper!r} and {lower!r} overlap vertically: "
        f"upper.bottom={a['bottom']:.1f}, lower.top={b['top']:.1f}"
    )
    assert abs(a["left"] - b["left"]) < 2, (
        f"{upper!r} and {lower!r} are not left-aligned (row layout?): "
        f"upper.left={a['left']:.1f}, lower.left={b['left']:.1f}"
    )


def assert_within_viewport(page: Page, selector: str, *, bottom: bool = True) -> None:
    """Assert the element's box lies within the viewport (not clipped/offscreen).

    Catches the silent-clipping class: ``body { min-height:100dvh }`` let
    ``.app-layout`` grow past the fold and its ``overflow:hidden`` hid the
    bottom of the Study Session picker (Start button edge + validation hint)
    with no scroll affordance. With ``bottom=True`` (default) the element's
    bottom must be <= viewport height; right edge must be <= viewport width.
    """
    r = _rect(page, selector)
    assert r is not None, f"element not laid out: {selector!r}"
    vp = page.viewport_size
    assert vp is not None, "viewport_size unavailable"
    if bottom:
        assert r["bottom"] <= vp["height"] + 1, (
            f"{selector!r} clipped below the fold: bottom={r['bottom']:.1f} "
            f"> viewport height {vp['height']}"
        )
    assert r["right"] <= vp["width"] + 1, (
        f"{selector!r} clipped past the right edge: right={r['right']:.1f} "
        f"> viewport width {vp['width']}"
    )
    assert r["left"] >= -1, f"{selector!r} offscreen left: left={r['left']:.1f}"


def assert_scroll_reachable(page: Page, selector: str, container: str) -> None:
    """Assert ``selector`` is reachable by scrolling ``container`` to the bottom.

    Complements assert_within_viewport for the legitimately-tall case: if a
    panel is taller than the viewport, its bottom content must live inside a
    scrollable container (``overflow-y:auto`` with scrollHeight > clientHeight)
    so the user can scroll to it — not be clipped by an ``overflow:hidden``
    ancestor. Motivated by the Study Session picker clipping bug.
    """
    reachable = page.evaluate(
        """([sel, contSel]) => {"""
        + _VIS_FN
        + """
            const el = __vis(sel);
            const cont = __vis(contSel);
            if (!el || !cont) return null;
            cont.scrollTop = cont.scrollHeight;
            const er = el.getBoundingClientRect();
            const cr = cont.getBoundingClientRect();
            return er.bottom <= cr.bottom + 1 && er.top >= cr.top - 1;
        }""",
        [selector, container],
    )
    assert reachable is not None, f"element or container not found: {selector!r} / {container!r}"
    assert reachable, (
        f"{selector!r} is not reachable by scrolling {container!r} — it is "
        f"clipped rather than scrollable"
    )


def assert_hidden_when_class_present(page: Page, selector: str) -> None:
    """Assert an element matching ``selector`` computes to ``display:none``.

    Catches the unbacked-toggle-class class: Alpine added class ``hidden`` to
    the Body Double voice-select when voice was off, but no
    ``.voice-select.hidden { display:none }`` rule existed, so the dropdown
    stayed visible permanently. Pass a selector that includes the toggle
    class, e.g. ``.voice-select.hidden``.
    """
    # Note: here we DO want the literal matched element (with its toggle class),
    # not the first visible one — the whole point is that it should be hidden.
    display = page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return '__absent__';
            return getComputedStyle(el).display;
        }""",
        selector,
    )
    assert display != "__absent__", (
        f"no element matches {selector!r} — cannot verify it is hidden "
        f"(is the toggle class applied in this state?)"
    )
    assert display == "none", (
        f"{selector!r} should be display:none when its hidden class is "
        f"present, but computed display={display!r}"
    )


def assert_nonzero_size(page: Page, selector: str) -> None:
    """Assert every match has width > 0 and height > 0 (unless display:none).

    Catches the zero-size-element class: a zero-width spacer <span> in the
    Quizzes config nav-bar broke the space-between balance, shifting the
    title ~18px off-centre. A structural element that occupies a layout slot
    must have real size.
    """
    bad = page.evaluate(
        """(sel) => {
            return [...document.querySelectorAll(sel)]
                .filter(el => getComputedStyle(el).display !== 'none')
                .map(el => { const r = el.getBoundingClientRect();
                    return {w: r.width, h: r.height}; })
                .filter(d => d.w <= 0 || d.h <= 0);
        }""",
        selector,
    )
    assert not bad, (
        f"{selector!r} has {len(bad)} zero-size element(s) that still occupy a layout slot: {bad!r}"
    )


def assert_centered_in(page: Page, child: str, container: str, *, tolerance_px: float = 4) -> None:
    """Assert ``child``'s horizontal midpoint is within tolerance of ``container``'s.

    Catches the off-centre class: the Quizzes config nav title was ~18px
    right of the nav-bar midpoint because the third flex slot was a
    zero-width spacer. tolerance_px absorbs sub-pixel rounding without
    masking a real offset.
    """
    geom = page.evaluate(
        """([childSel, contSel]) => {"""
        + _VIS_FN
        + """
            const c = __vis(childSel);
            const k = __vis(contSel);
            if (!c || !k) return null;
            const cr = c.getBoundingClientRect();
            const kr = k.getBoundingClientRect();
            return {childMid: (cr.left + cr.right) / 2,
                    contMid: (kr.left + kr.right) / 2};
        }""",
        [child, container],
    )
    assert geom is not None, f"element not found: {child!r} or {container!r}"
    offset = abs(geom["childMid"] - geom["contMid"])
    assert offset <= tolerance_px, (
        f"{child!r} is off-centre within {container!r} by {offset:.1f}px "
        f"(tolerance {tolerance_px}px)"
    )


def assert_single_line(page: Page, container: str, child_selector: str) -> None:
    """Assert all matched children share one top (have not wrapped to 2+ lines).

    Catches the unwanted-wrap class: the Flashcards keyboard-hints bar
    wrapped 'Esc Home' onto a second line at 768px. All hint spans in the
    row should share a single ``getBoundingClientRect().top``.
    """
    tops = page.evaluate(
        """([contSel, childSel]) => {"""
        + _VIS_FN
        + """
            const cont = __vis(contSel);
            if (!cont) return null;
            const kids = [...cont.querySelectorAll(childSel)]
                .filter(el => el.offsetParent !== null);
            return [...new Set(kids.map(el =>
                Math.round(el.getBoundingClientRect().top)))];
        }""",
        [container, child_selector],
    )
    assert tops is not None, f"container not found: {container!r}"
    assert len(tops) <= 1, (
        f"children {child_selector!r} in {container!r} wrapped to "
        f"{len(tops)} lines (distinct tops: {tops})"
    )
