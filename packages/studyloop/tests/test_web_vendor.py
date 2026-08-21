"""Tests for vendored static assets — local-first, no-CDN serving.

Also: regression tests for the session-options cache poisoning fix
(docs/issues/0005-vendor-picker-lists-repo-directories.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"
VENDOR_DIR = STATIC_DIR / "vendor"


# ---------------------------------------------------------------------------
# Regression tests for issue 0005: session-options cache poisoning
# ---------------------------------------------------------------------------


class TestSessionOptionsCachePoisoningRegression:
    """Protect against stale/poisoned session-options-index.json.

    Issue 0005: a cache file built under a different root set (e.g.
    by a test with cwd-relative study roots) validates as fresh when
    the real roots don't exist, because the fingerprint didn't include
    the root list itself.
    """

    def test_stale_index_from_different_root_set_is_rejected(self, tmp_path: Path) -> None:
        """A cached index built under root set B must NOT validate
        when the current root set is A (even if both are absent).

        This models the exact bug: fingerprints matched because both had
        empty records (no roots exist), so the root list itself wasn't
        compared. After the fix, the fingerprint includes the root list
        and a version bump invalidates all old caches.
        """
        from studyloop.web.routes.session import _options

        # Seed a poisoned index file at a known state_dir
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        index_path = state_dir / "session-options-index.json"

        # Build a poisoned payload — the vendors reference repo dirs
        poisoned_targets = {
            "session_types": [],
            "topics": [{"label": "Python", "value": "python", "kind": "topic", "path": "/fake"}],
            "vendors": [
                {"label": "agents", "value": "agents", "kind": "vendor", "path": "/tmp/agents"},
                {"label": "docs", "value": "docs", "kind": "vendor", "path": "/tmp/docs"},
            ],
            "courses": [],
            "lessons": [],
        }

        # Current root set A — different from the root set used when cache was built
        current_roots_a = [Path("/nonexistent/vault-a/Study")]

        state = SimpleNamespace()

        with (
            patch.object(_options, "_study_roots", return_value=current_roots_a),
            patch.object(_options, "_courses_roots", return_value=[]),
            patch(
                "studyloop.web.routes.session._options._target_index_path",
                return_value=index_path,
            ),
            patch("studyloop.settings.get_config_path", side_effect=OSError("no config")),
        ):
            # Build the LIVE fingerprint (which now includes roots)
            live_fp = _options._target_fingerprint()

            # Write a poisoned index whose fingerprint matches on everything
            # EXCEPT the roots (simulating the pre-fix bug where roots were
            # NOT included, so the fingerprints were identical)
            poisoned_fingerprint = dict(live_fp)
            # Tamper: change roots to simulate it was built under root set B
            poisoned_fingerprint["roots"] = ["/nonexistent/vault-b/Study"]

            index_path.write_text(
                json.dumps(
                    {
                        "version": _options._SESSION_OPTION_INDEX_VERSION,
                        "built_at": 1000000.0,
                        "fingerprint": poisoned_fingerprint,
                        "targets": poisoned_targets,
                    }
                )
            )

            result = _options._get_indexed_target_options(state, force=False)

        # The poisoned vendors must NOT be returned — should get a fresh
        # (empty) scan instead
        vendor_values = [v["value"] for v in result.get("vendors", [])]
        assert "agents" not in vendor_values
        assert "docs" not in vendor_values

    def test_index_with_relative_paths_is_rejected_on_read(self, tmp_path: Path) -> None:
        """_read_target_index must reject a payload containing relative paths."""
        from studyloop.web.routes.session import _options

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        index_path = state_dir / "session-options-index.json"

        # A payload where vendor paths are relative (the bug signature)
        poisoned_targets = {
            "session_types": [],
            "topics": [],
            "vendors": [
                {
                    "label": "pycache",
                    "value": "__pycache__",
                    "kind": "vendor",
                    "path": "__pycache__",
                },
                {"label": "agents", "value": "agents", "kind": "vendor", "path": "agents"},
            ],
            "courses": [],
            "lessons": [],
        }

        # Use a fingerprint that would match (same version, same shape)
        matching_fingerprint = {
            "version": _options._SESSION_OPTION_INDEX_VERSION,
            "config": [],
            "roots": [],
            "record_count": 0,
            "records": [],
        }

        index_path.write_text(
            json.dumps(
                {
                    "version": _options._SESSION_OPTION_INDEX_VERSION,
                    "built_at": 1000000.0,
                    "fingerprint": matching_fingerprint,
                    "targets": poisoned_targets,
                }
            )
        )

        with patch(
            "studyloop.web.routes.session._options._target_index_path",
            return_value=index_path,
        ):
            result = _options._read_target_index(matching_fingerprint)

        # Must be rejected — None means "cache miss, do a fresh scan"
        assert result is None

    def test_write_refuses_relative_paths(self, tmp_path: Path) -> None:
        """_write_target_index must refuse to persist relative paths."""
        from studyloop.web.routes.session import _options

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        index_path = state_dir / "session-options-index.json"

        targets_with_relative = {
            "session_types": [],
            "topics": [],
            "vendors": [
                {"label": "bad", "value": "bad", "kind": "vendor", "path": "relative/path"},
            ],
            "courses": [],
            "lessons": [],
        }

        fingerprint = {"version": 2, "config": [], "roots": [], "record_count": 0, "records": []}

        with patch(
            "studyloop.web.routes.session._options._target_index_path",
            return_value=index_path,
        ):
            _options._write_target_index(fingerprint, targets_with_relative)

        # File must NOT have been written
        assert not index_path.exists()

    def test_target_index_path_never_resolves_to_real_state_dir(self, tmp_path: Path) -> None:
        """During tests, _target_index_path must NOT resolve under the
        real ~/.local/share/studyloop — the autouse fixture must redirect it."""
        from studyloop.web.routes.session._options import _target_index_path

        path = _target_index_path()
        real_state = Path.home() / ".local" / "share" / "studyloop"
        if path is not None:
            assert not str(path).startswith(str(real_state)), (
                f"_target_index_path() resolved to {path} which is under "
                f"the real state dir {real_state} — test isolation is broken"
            )


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


class TestGhosttyWebVendorFilesExist:
    """Vendor file assertions for ghostty-web 0.4.0 (T3 — ghostty-web renderer)."""

    def test_ghostty_web_umd_exists(self):
        assert (VENDOR_DIR / "js" / "ghostty-web-0.4.0.umd.js").exists()

    def test_ghostty_web_wasm_exists(self):
        assert (VENDOR_DIR / "js" / "ghostty-vt-0.4.0.wasm").exists()

    def test_ghostty_web_bootstrap_exists(self):
        assert (VENDOR_DIR / "js" / "ghostty-web-bootstrap-0.4.0.js").exists()

    def test_ghostty_web_wasm_size(self):
        """WASM binary should be between 300 KB and 600 KB (sanity check)."""
        wasm = VENDOR_DIR / "js" / "ghostty-vt-0.4.0.wasm"
        size = wasm.stat().st_size
        assert 300_000 < size < 600_000, f"WASM size {size} outside expected range"


class TestDevRendererInjection:
    """Verify that create_app injects correct scripts based on dev_renderer."""

    def _get_index_html(self, dev_mode: bool, dev_renderer: str | None = None) -> str:
        from fastapi.testclient import TestClient

        from studyloop.web.app import create_app

        app = create_app(dev_mode=dev_mode, dev_renderer=dev_renderer)
        client = TestClient(app)
        resp = client.get("/")
        return resp.text

    def test_ghostty_renderer_injects_ghostty_scripts(self):
        html = self._get_index_html(dev_mode=True, dev_renderer="ghostty")
        assert 'content="ghostty-web"' in html
        assert "ghostty-web-0.4.0.umd.js" in html
        assert "ghostty-web-bootstrap-0.4.0.js" in html
        # Must NOT have wterm scripts
        assert "wterm-0.3.0.js" not in html
        assert "wterm-adapter" not in html

    def test_wterm_renderer_injects_wterm_scripts(self):
        html = self._get_index_html(dev_mode=True, dev_renderer="wterm")
        assert 'content="wterm"' in html
        assert "wterm-0.3.0.js" in html
        assert "wterm-adapter-0.3.0.js" in html
        # Must NOT have ghostty scripts
        assert "ghostty-web-0.4.0.umd.js" not in html
        assert "ghostty-web-bootstrap" not in html

    def test_no_dev_mode_injects_nothing(self):
        html = self._get_index_html(dev_mode=False)
        assert "studyloop-dev-mode" not in html
        assert "ghostty-web" not in html
        assert "wterm-0.3.0.js" not in html
