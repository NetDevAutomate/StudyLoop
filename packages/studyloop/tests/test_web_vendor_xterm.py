"""Smoke tests for the vendored xterm.js assets (§1.6).

Asserts that xterm.js + fit/webgl addons + xterm.css exist on disk and
are referenced from ``web/static/index.html``. Catches the regression
where one of the vendor files is deleted or the index tag is dropped
during a refactor — cheap to assert, would otherwise only surface as
a blank terminal pane in the browser.

This test does NOT exercise the terminal itself (that's §1.7 with the
Alpine component). It's a pure file-existence + reference check.

Plan: private-docs/2026-05-09-refactor-agent-session-transport-plan.md §1.6
"""

from __future__ import annotations

from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"

VENDOR_JS = STATIC_DIR / "vendor" / "js"
VENDOR_CSS = STATIC_DIR / "vendor" / "css"
INDEX_HTML = STATIC_DIR / "index.html"

# Keep these in sync with the versions pinned in index.html. Bumping a
# vendored file is a two-line change: drop the new asset, update the
# version here.
EXPECTED_JS = {
    "xterm-6.0.0.js",
    "xterm-addon-fit-0.11.0.js",
    "xterm-addon-webgl-0.19.0.js",
    "xterm-addon-clipboard-0.2.0.js",
}
EXPECTED_CSS = {"xterm-6.0.0.css"}

# Chat rendering libs (§U1 — ACP Chat UI plan)
EXPECTED_CHAT_JS = {
    "marked-12.0.0.min.js",
    "highlight-11.9.0.min.js",
    "purify-3.1.0.min.js",
}
EXPECTED_CHAT_CSS = {"highlight-tokyo-night-dark.css"}


class TestVendorFilesExist:
    @pytest.mark.parametrize("filename", sorted(EXPECTED_JS))
    def test_js_file_exists(self, filename: str) -> None:
        path = VENDOR_JS / filename
        assert path.exists(), f"Missing vendored JS asset: {path}"
        # UMD bundles should be non-trivial in size. If one shrinks to
        # zero bytes it's usually a broken download that slipped through.
        assert path.stat().st_size > 1000, f"Suspiciously small asset: {path}"

    @pytest.mark.parametrize("filename", sorted(EXPECTED_CSS))
    def test_css_file_exists(self, filename: str) -> None:
        path = VENDOR_CSS / filename
        assert path.exists(), f"Missing vendored CSS asset: {path}"
        assert path.stat().st_size > 500, f"Suspiciously small asset: {path}"


class TestIndexReferencesVendor:
    def test_index_references_all_vendor_assets(self) -> None:
        """Every expected vendor filename must appear verbatim in index.html."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        for name in EXPECTED_JS | EXPECTED_CSS:
            assert name in html, f"index.html does not reference {name}"

    def test_index_has_xterm_css_link_tag(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "/vendor/css/xterm-6.0.0.css" in html
        assert "<link" in html.split("/vendor/css/xterm-6.0.0.css")[0].splitlines()[-1]

    def test_xterm_umd_bundles_load_in_correct_order(self) -> None:
        """Every addon must load AFTER xterm.js — addons reference the xterm
        UMD globals. A transposed order would leave FitAddon/WebglAddon/
        ClipboardAddon unable to find the Terminal class."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        xterm_pos = html.index("xterm-6.0.0.js")
        for addon in (
            "xterm-addon-fit-0.11.0.js",
            "xterm-addon-webgl-0.19.0.js",
            "xterm-addon-clipboard-0.2.0.js",
        ):
            assert xterm_pos < html.index(addon), f"{addon} must load after xterm.js"


class TestChatVendorFilesExist:
    """Smoke tests for the vendored chat rendering assets (§U1).

    Parallel to TestVendorFilesExist above — same shape, different files.
    Asserts marked, highlight.js, DOMPurify, and the highlight theme CSS
    exist on disk and are non-trivially sized.
    """

    @pytest.mark.parametrize("filename", sorted(EXPECTED_CHAT_JS))
    def test_chat_js_file_exists(self, filename: str) -> None:
        path = VENDOR_JS / filename
        assert path.exists(), f"Missing vendored chat JS asset: {path}"
        assert path.stat().st_size > 1000, f"Suspiciously small asset: {path}"

    @pytest.mark.parametrize("filename", sorted(EXPECTED_CHAT_CSS))
    def test_chat_css_file_exists(self, filename: str) -> None:
        path = VENDOR_CSS / filename
        assert path.exists(), f"Missing vendored chat CSS asset: {path}"
        assert path.stat().st_size > 200, f"Suspiciously small asset: {path}"


class TestIndexReferencesChatVendor:
    """index.html must reference every chat vendor asset verbatim."""

    def test_index_references_all_chat_vendor_assets(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        for name in EXPECTED_CHAT_JS | EXPECTED_CHAT_CSS:
            assert name in html, f"index.html does not reference {name}"

    def test_index_has_highlight_theme_css_link_tag(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "/vendor/css/highlight-tokyo-night-dark.css" in html
        assert (
            "<link" in html.split("/vendor/css/highlight-tokyo-night-dark.css")[0].splitlines()[-1]
        )

    def test_chat_libs_load_in_correct_order(self) -> None:
        """DOMPurify must appear before marked and hljs — it is a sanitiser
        that marked/hljs may invoke. marked must appear before hljs so that
        an integration combining both renders markdown first, then highlights."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        purify_pos = html.index("purify-3.1.0.min.js")
        marked_pos = html.index("marked-12.0.0.min.js")
        hljs_pos = html.index("highlight-11.9.0.min.js")
        assert purify_pos < marked_pos, "DOMPurify must load before marked"
        assert marked_pos < hljs_pos, "marked must load before highlight.js"
