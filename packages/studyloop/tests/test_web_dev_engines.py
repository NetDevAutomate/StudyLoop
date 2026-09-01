"""Unit tests for the ``studyloop web --dev`` terminal engine registry.

These run in the default (non-e2e) suite: no browser, no server subprocess.
They pin the contract the vendored adapters depend on:

* the ``studyloop-dev-mode`` meta marker carries the engine name, which is what
  each adapter checks before patching ``window.Terminal``;
* engine scripts are injected **after** the xterm.js bundles and with
  ``defer``, so the adapter's assignment is the last writer;
* the default (non-dev) path serves ``index.html`` byte-for-byte untouched, so
  xterm.js remains the production renderer.

Related e2e coverage: ``tests/e2e/test_ghostty_dev_terminal.py``.
"""

from __future__ import annotations

import pytest

from studyloop.web.dev_engines import (
    DEFAULT_DEV_ENGINE,
    DEV_ENGINES,
    inject_dev_engine,
    resolve_dev_engine,
)

SAMPLE_HTML = (
    "<!doctype html>\n"
    "<html>\n<head>\n"
    '  <meta charset="utf-8">\n'
    '  <script defer src="/vendor/js/xterm-6.0.0.js"></script>\n'
    '  <script defer src="/vendor/js/xterm-addon-fit-0.11.0.js"></script>\n'
    "</head>\n<body></body>\n</html>\n"
)


class TestRegistry:
    def test_ghostty_is_the_default_engine(self) -> None:
        """--dev means libghostty, and it is the only registered engine."""
        assert DEFAULT_DEV_ENGINE == "ghostty"
        assert DEFAULT_DEV_ENGINE in DEV_ENGINES

    def test_every_registered_engine_has_assets(self) -> None:
        # Asserts the shape of the registry rather than its exact membership, so
        # adding an engine does not require editing this test - only removing the
        # asset contract would. wterm was removed in favour of a single engine.
        assert set(DEV_ENGINES) == {"ghostty"}
        for engine, assets in DEV_ENGINES.items():
            assert assets["js"], f"{engine} has no scripts"
            assert assets["css"], f"{engine} has no stylesheet"

    def test_engine_assets_exist_on_disk(self) -> None:
        """Every registered asset is actually vendored.

        Catches a rename or a missed vendor step before it becomes a 404 and a
        silently dormant adapter in the browser.
        """
        from studyloop.web.app import STATIC_DIR

        for engine, assets in DEV_ENGINES.items():
            for url in (*assets["js"], *assets["css"]):
                path = STATIC_DIR / url.lstrip("/")
                assert path.is_file(), f"{engine}: missing vendored asset {url}"
                assert path.stat().st_size > 0, f"{engine}: empty asset {url}"

    @pytest.mark.parametrize("raw", ["ghostty", "GHOSTTY", " Ghostty "])
    def test_resolve_accepts_case_and_whitespace(self, raw: str) -> None:
        assert resolve_dev_engine(raw) == raw.strip().lower()

    def test_resolve_none_returns_default(self) -> None:
        assert resolve_dev_engine(None) == DEFAULT_DEV_ENGINE

    def test_resolve_rejects_unknown_engine(self) -> None:
        with pytest.raises(ValueError, match="Unknown dev engine"):
            resolve_dev_engine("nope")


class TestInjection:
    def test_marker_carries_engine_name(self) -> None:
        # The marker must NAME the engine rather than being a bare boolean flag:
        # the browser-side bootstrap keys off the content value, so a generic
        # marker would patch window.Terminal for any dev engine.
        html = inject_dev_engine(SAMPLE_HTML, "ghostty")
        assert '<meta name="studyloop-dev-mode" content="ghostty">' in html

    def test_injects_all_engine_assets(self) -> None:
        html = inject_dev_engine(SAMPLE_HTML, "ghostty")
        for url in (
            "/vendor/dev/js/ghostty-web-0.4.0.js",
            "/vendor/dev/js/ghostty-adapter-0.4.0.js",
            "/vendor/dev/css/ghostty-0.4.0.css",
        ):
            assert url in html, f"{url} not injected"

    def test_adapter_script_runs_after_xterm(self) -> None:
        """Document order decides who owns window.Terminal.

        Both sets of scripts are ``defer``, and deferred scripts execute in
        document order, so the adapter must appear *after* the xterm bundles or
        xterm would overwrite the patch.
        """
        html = inject_dev_engine(SAMPLE_HTML, "ghostty")
        assert html.index("xterm-6.0.0.js") < html.index("ghostty-adapter-0.4.0.js")

    def test_engine_scripts_are_deferred(self) -> None:
        html = inject_dev_engine(SAMPLE_HTML, "ghostty")
        for url in DEV_ENGINES["ghostty"]["js"]:
            assert f'<script defer src="{url}"></script>' in html

    def test_injection_is_inside_head(self) -> None:
        html = inject_dev_engine(SAMPLE_HTML, "ghostty")
        head = html.index("<head>")
        head_end = html.index("</head>")
        assert head < html.index("studyloop-dev-mode") < head_end
        assert head < html.index("ghostty-adapter-0.4.0.js") < head_end

    def test_original_markup_is_preserved(self) -> None:
        """Injection adds, never rewrites."""
        html = inject_dev_engine(SAMPLE_HTML, "ghostty")
        for line in SAMPLE_HTML.splitlines():
            if line.strip():
                assert line.strip() in html

    def test_unknown_engine_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown dev engine"):
            inject_dev_engine(SAMPLE_HTML, "not-an-engine")


class TestCreateApp:
    """create_app's dev wiring, exercised through the ASGI app."""

    @staticmethod
    def _client(**kwargs):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from studyloop.web.app import create_app

        return TestClient(create_app(**kwargs))

    def test_default_mode_has_no_dev_markup(self) -> None:
        """The gate holds: no --dev means no ghostty anywhere in the page."""
        response = self._client().get("/")
        assert response.status_code == 200
        assert "studyloop-dev-mode" not in response.text
        assert "ghostty" not in response.text
        assert "wterm" not in response.text

    def test_default_mode_records_no_engine(self) -> None:
        pytest.importorskip("fastapi")
        from studyloop.web.app import create_app

        assert create_app().state.dev_engine is None

    def test_dev_mode_defaults_to_ghostty(self) -> None:
        response = self._client(dev_mode=True).get("/")
        assert response.status_code == 200
        assert '<meta name="studyloop-dev-mode" content="ghostty">' in response.text

    def test_dev_mode_honours_explicit_engine(self) -> None:
        # Naming the engine explicitly must behave the same as defaulting to it.
        # Worth keeping with one engine registered: it is the path a second engine
        # would arrive through, and it proves the plumbing is not hardcoded.
        response = self._client(dev_mode=True, dev_engine="ghostty").get("/")
        assert '<meta name="studyloop-dev-mode" content="ghostty">' in response.text

    def test_dev_mode_records_engine_on_state(self) -> None:
        pytest.importorskip("fastapi")
        from studyloop.web.app import create_app

        assert create_app(dev_mode=True).state.dev_engine == "ghostty"
        assert create_app(dev_mode=True, dev_engine="ghostty").state.dev_engine == "ghostty"

    def test_unknown_engine_fails_fast(self) -> None:
        """Bad --dev-engine errors at startup, not on first page load."""
        pytest.importorskip("fastapi")
        from studyloop.web.app import create_app

        with pytest.raises(ValueError, match="Unknown dev engine"):
            create_app(dev_mode=True, dev_engine="nope")

    def test_unknown_engine_ignored_without_dev_mode(self) -> None:
        """dev_engine is inert unless dev_mode is on."""
        pytest.importorskip("fastapi")
        from studyloop.web.app import create_app

        app = create_app(dev_engine="nope")
        assert app.state.dev_engine is None

    def test_dev_assets_are_served(self) -> None:
        client = self._client(dev_mode=True)
        for url in (
            *DEV_ENGINES["ghostty"]["js"],
            *DEV_ENGINES["ghostty"]["css"],
        ):
            response = client.get(url)
            assert response.status_code == 200, f"{url} -> {response.status_code}"
            assert response.content, f"{url} served empty"

    def test_dev_html_is_not_cached(self) -> None:
        """Stale dev HTML would silently pin an old adapter in the browser."""
        response = self._client(dev_mode=True).get("/")
        assert "no-cache" in response.headers.get("Cache-Control", "")


class TestTerminalEngineDescriptor:
    """``describe_terminal_engine`` — the honest answer to "what renders my terminal".

    The registry alone cannot answer that question: ``--dev`` swaps the *renderer*
    (``window.Terminal``) while the transport picker chooses how the agent
    *process* is driven. Two unrelated axes that the UI used to conflate, because
    the ``pty`` option's label hard-coded "xterm.js" whatever was actually loaded.
    """

    def test_default_mode_reports_xterm(self) -> None:
        from studyloop.web.dev_engines import describe_terminal_engine

        info = describe_terminal_engine(False, None)
        assert info["dev_mode"] is False
        assert info["engine"] is None
        assert info["renderer"] == "xterm.js"
        assert info["experimental"] is False
        assert info["caveats"] == []

    def test_dev_engine_is_named_and_flagged_experimental(self) -> None:
        from studyloop.web.dev_engines import describe_terminal_engine

        info = describe_terminal_engine(True, "ghostty")
        assert info["dev_mode"] is True
        assert info["engine"] == "ghostty"
        assert info["renderer"] == "libghostty"
        assert info["experimental"] is True

    def test_dev_engine_carries_the_documented_caveats(self) -> None:
        """A learner running an experimental renderer must be told what it drops.

        docs/web-ui-guide.md §"Known gaps (why this is still --dev)" is the
        source; nothing surfaced it before, so the browser silently behaved
        differently with no way to find out why.
        """
        from studyloop.web.dev_engines import describe_terminal_engine

        caveats = describe_terminal_engine(True, "ghostty")["caveats"]
        assert caveats, "an experimental engine with no stated caveats is a trap"
        joined = " ".join(caveats).lower()
        assert "clipboard" in joined
        assert "scrollback" in joined

    def test_engine_is_ignored_when_dev_mode_is_off(self) -> None:
        """``dev_engine`` is inert without ``--dev`` — matching create_app."""
        from studyloop.web.dev_engines import describe_terminal_engine

        assert describe_terminal_engine(False, "ghostty")["renderer"] == "xterm.js"

    def test_every_registered_engine_has_a_label_and_caveats(self) -> None:
        for engine, assets in DEV_ENGINES.items():
            assert assets.get("renderer"), f"{engine} has no renderer name"
            assert assets.get("caveats"), f"{engine} has no stated caveats"


class TestSessionOptionsExposesTheEngine:
    """``GET /api/session/options`` is the channel to the browser.

    Before this, ``app.state.dev_mode`` / ``app.state.dev_engine`` were written
    by ``create_app`` and read by nothing at all, and the only signal that
    reached the page was a ``<meta>`` marker consumed exclusively by the
    vendored adapters. The UI had no way to label itself honestly.
    """

    @staticmethod
    def _options(**kwargs) -> dict:
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from studyloop.web.app import create_app

        response = TestClient(create_app(**kwargs)).get("/api/session/options")
        assert response.status_code == 200, response.text
        return response.json()

    def test_default_mode_says_xterm(self) -> None:
        engine = self._options()["terminal_engine"]
        assert engine["dev_mode"] is False
        assert engine["renderer"] == "xterm.js"
        assert engine["experimental"] is False

    def test_dev_mode_says_libghostty(self) -> None:
        engine = self._options(dev_mode=True)["terminal_engine"]
        assert engine["dev_mode"] is True
        assert engine["engine"] == "ghostty"
        assert engine["renderer"] == "libghostty"
        assert engine["experimental"] is True
        assert engine["caveats"]

    def test_dev_mode_honours_the_selected_engine(self) -> None:
        # ghostty is the only registered engine since wterm was removed, so this
        # asserts the explicit-selection path still resolves rather than being
        # short-circuited by the default. It is the route a future second engine
        # would arrive through.
        engine = self._options(dev_mode=True, dev_engine="ghostty")["terminal_engine"]
        assert engine["engine"] == "ghostty"
        assert engine["renderer"] == "libghostty"

    def test_agents_no_longer_recommend_the_legacy_transport(self) -> None:
        """``recommended_transport: "ttyd"`` had zero consumers and pointed at
        the retired path. A field nobody reads cannot be trusted to be right."""
        for agent in self._options()["agents"]:
            assert "recommended_transport" not in agent, (
                "recommended_transport is back — it steers nothing and names the legacy path"
            )


class TestVendoredBundle:
    """Properties of the vendored ghostty-web bundle we rely on."""

    @staticmethod
    def _bundle_text() -> str:
        from studyloop.web.app import STATIC_DIR

        path = STATIC_DIR / "vendor/dev/js/ghostty-web-0.4.0.js"
        return path.read_text(encoding="utf-8", errors="replace")

    def test_bundle_is_umd_exposing_a_global(self) -> None:
        """A plain <script src> must define window.GhosttyWeb.

        ghostty-web's package entry point is ESM; StudyLoop vendors the UMD
        build precisely so no bundler or import map is needed.
        """
        text = self._bundle_text()
        assert "e.GhosttyWeb={}" in text
        assert "typeof exports" in text[:400]

    def test_wasm_is_inlined_so_no_second_fetch(self) -> None:
        """The WASM binary ships inside the bundle as a base64 data URL.

        This is why dev mode needs no ``.wasm`` route, no MIME-type config, and
        works offline.
        """
        assert "data:application/wasm;base64," in self._bundle_text()

    def test_adapter_declares_the_expected_engine_marker(self) -> None:
        """The adapter keys off the same marker value the server injects."""
        from studyloop.web.app import STATIC_DIR

        adapter = (STATIC_DIR / "vendor/dev/js/ghostty-adapter-0.4.0.js").read_text(
            encoding="utf-8"
        )
        assert "studyloop-dev-mode" in adapter
        assert "'ghostty'" in adapter

    def test_adapter_forwards_the_whole_selection_api(self) -> None:
        """The facade must forward every selection method, not just getSelection.

        ghostty-web's Terminal exposes five (selectAll, getSelection,
        hasSelection, clearSelection, selectLines), each delegating to its
        selectionManager. This adapter is the ONLY thing callers touch --
        liveAgentConsole() never holds the underlying Terminal -- so a method the
        facade omits is simply absent at runtime, however well the library
        implements it. That is not a cosmetic gap: ghostty-web paints to a
        canvas, so there is no DOM text and ``window.getSelection()`` cannot
        stand in.

        For most of this adapter's life only getSelection was forwarded, which
        made three browser tests fail in ways that read like a missing library
        feature (``selectAll is not a function``) or an unrelated race (a 15s
        readiness timeout, because that predicate called selectAll before
        deciding the terminal was ready). This asserts the parity directly so a
        future facade method cannot go missing quietly.
        """
        from studyloop.web.app import STATIC_DIR

        bundle_dir = STATIC_DIR / "vendor/dev/js"
        adapter = (bundle_dir / "ghostty-adapter-0.4.0.js").read_text(encoding="utf-8")
        bundle = (bundle_dir / "ghostty-web-0.4.0.js").read_text(encoding="utf-8")

        selection_api = (
            "selectAll",
            "getSelection",
            "hasSelection",
            "clearSelection",
            "selectLines",
        )
        for name in selection_api:
            assert f"{name}(" in bundle, (
                f"{name} is missing from ghostty-web itself -- this test's premise "
                "changed; re-check the bundle before relaxing the adapter."
            )
            assert f"    {name}(" in adapter, (
                f"the adapter facade does not forward {name}(). Callers only ever "
                "reach this facade, so the method is absent at runtime even though "
                "ghostty-web implements it."
            )

    def test_dev_css_declares_terminal_font_variables(self) -> None:
        """Font propagation depends on these custom properties existing."""
        from studyloop.web.app import STATIC_DIR

        css = (STATIC_DIR / "vendor/dev/css/ghostty-0.4.0.css").read_text(encoding="utf-8")
        assert "--term-font-family" in css
        assert "--term-font-size" in css
        # Re-pointed per reading-font choice and for OpenDyslexic.
        assert 'body[data-font="atkinson"]' in css
        assert "body.dyslexic" in css
