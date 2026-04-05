"""Tests for vendored static assets — offline PWA support."""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "studyctl" / "web" / "static"
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

    def test_vendor_js_files_not_empty(self):
        for f in (VENDOR_DIR / "js").iterdir():
            assert f.stat().st_size > 1000, f"{f.name} seems too small"


class TestNoCdnReferences:
    def test_session_html_no_external_scripts(self):
        content = (STATIC_DIR / "session.html").read_text()
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


class TestServiceWorkerCache:
    def test_sw_caches_vendor_assets(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "/vendor/js/htmx-2.0.4.min.js" in content
        assert "/vendor/js/alpine-3.14.8.min.js" in content
        assert "/vendor/css/opendyslexic-400.css" in content

    def test_sw_caches_inter_font(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "/vendor/css/inter.css" in content
        assert "/vendor/css/files/inter-latin.woff2" in content

    def test_sw_cache_version_bumped(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "studyctl-v6" in content
