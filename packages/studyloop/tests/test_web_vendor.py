"""Tests for vendored static assets — local-first, no-CDN serving."""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"
VENDOR_DIR = STATIC_DIR / "vendor"


class TestVendorFilesExist:
    def test_htmx_exists(self):
        assert (VENDOR_DIR / "js" / "htmx-2.0.4.min.js").exists()

    def test_htmx_sse_exists(self):
        assert (VENDOR_DIR / "js" / "htmx-ext-sse-2.2.2.js").exists()

    def test_alpine_exists(self):
        assert (VENDOR_DIR / "js" / "alpine-3.14.8.min.js").exists()

    def test_opendyslexic_css_exists(self):
        assert (VENDOR_DIR / "css" / "opendyslexic-400.css").exists()

    def test_opendyslexic_woff2_exists(self):
        assert (VENDOR_DIR / "css" / "files" / "opendyslexic-latin-400-normal.woff2").exists()

    def test_inter_css_exists(self):
        assert (VENDOR_DIR / "css" / "inter.css").exists()

    def test_inter_woff2_latin_exists(self):
        assert (VENDOR_DIR / "css" / "files" / "inter-latin.woff2").exists()

    def test_inter_woff2_latin_ext_exists(self):
        assert (VENDOR_DIR / "css" / "files" / "inter-latin-ext.woff2").exists()

    def test_lexend_css_and_woff2_exist(self):
        assert (VENDOR_DIR / "css" / "lexend.css").exists()
        assert (VENDOR_DIR / "css" / "files" / "lexend-latin-400.woff2").exists()
        assert (VENDOR_DIR / "css" / "files" / "lexend-latin-700.woff2").exists()

    def test_atkinson_css_and_woff2_exist(self):
        assert (VENDOR_DIR / "css" / "atkinson-hyperlegible.css").exists()
        assert (VENDOR_DIR / "css" / "files" / "atkinson-hyperlegible-latin-400.woff2").exists()
        assert (VENDOR_DIR / "css" / "files" / "atkinson-hyperlegible-latin-700.woff2").exists()

    def test_vendor_js_files_not_empty(self):
        for f in (VENDOR_DIR / "js").iterdir():
            assert f.stat().st_size > 1000, f"{f.name} seems too small"


class TestNoCdnReferences:
    def test_index_html_no_external_scripts(self):
        content = (STATIC_DIR / "index.html").read_text()
        assert "unpkg.com" not in content
        assert "cdn.jsdelivr.net" not in content
        # Verify local paths are used
        assert "/vendor/js/htmx-2.0.4.min.js" in content
        assert "/vendor/js/alpine-3.14.8.min.js" in content

    def test_style_css_no_opendyslexic_cdn(self):
        content = (STATIC_DIR / "style.css").read_text()
        assert "cdn.jsdelivr.net/npm/@fontsource/opendyslexic" not in content
        assert "/vendor/css/opendyslexic-400.css" in content

    def test_style_css_no_google_fonts_cdn(self):
        content = (STATIC_DIR / "style.css").read_text()
        assert "fonts.googleapis.com" not in content
        assert "/vendor/css/inter.css" in content

    def test_style_css_imports_picker_fonts_locally(self):
        content = (STATIC_DIR / "style.css").read_text()
        assert "/vendor/css/lexend.css" in content
        assert "/vendor/css/atkinson-hyperlegible.css" in content

    def test_vendored_font_css_is_offline(self):
        for name in ("lexend.css", "atkinson-hyperlegible.css"):
            content = (VENDOR_DIR / "css" / name).read_text()
            assert "https://" not in content
            assert "./files/" in content


class TestNoServiceWorker:
    def test_sw_js_stays_deleted(self):
        """PWA offline was removed (audit 2026-07-11 §0.1): sw.js was never
        registered and must not silently return without that decision being
        revisited."""
        assert not (STATIC_DIR / "sw.js").exists()
