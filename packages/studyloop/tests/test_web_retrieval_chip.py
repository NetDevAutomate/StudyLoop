"""The web status chip for the encoder warm (lane A4 deliverable 4, council D-8).

The chip renders lane A1's warm status -- ``cold|warming|warm|failed|disabled``
plus model and elapsed -- following the ``GET /api/tts/health`` precedent
(E-A8): a small JSON surface the browser polls, not a push channel, and
explicitly NOT a spinner pretending to know a percentage.

Every assertion here is a SET derived from the code (the dataclass's fields,
the enum's members) compared against what a parser extracts from the payload or
the static asset -- never copied prose (council TEST SHAPE ruling A20). A new
``WarmState`` member therefore fails this file until the chip handles it.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from agent_session_tools import embedding_store, load_indicator, query_encoders, retrieval
from studyloop.web.app import create_app

STATIC = Path(__file__).parent.parent / "src" / "studyloop" / "web" / "static"
CHIP_JS = STATIC / "js" / "retrieval-chip.js"
INDEX_HTML = STATIC / "index.html"


@pytest.fixture(autouse=True)
def _cold_warm_status():
    retrieval.reset_warm_status()
    yield
    retrieval.reset_warm_status()


class TestTheHealthEndpoint:
    def test_the_payload_is_exactly_the_warm_status_contract(self) -> None:
        client = TestClient(create_app(study_dirs=[]))
        response = client.get("/api/retrieval/health")
        assert response.status_code == 200
        expected = {field.name for field in dataclasses.fields(retrieval.EncoderWarmStatus)}
        assert set(response.json()) == expected

    def test_a_cold_process_reports_cold(self) -> None:
        client = TestClient(create_app(study_dirs=[]))
        payload = client.get("/api/retrieval/health").json()
        assert payload["state"] == retrieval.WarmState.COLD.value
        assert payload["model"] is None
        assert payload["elapsed"] is None

    def test_a_failed_warm_is_reported_honestly(self) -> None:
        retrieval._set_warm_status(
            retrieval.EncoderWarmStatus(
                state=retrieval.WarmState.FAILED,
                model="bge-small-en-v1.5",
                elapsed=1.25,
                detail="RuntimeError: no artefact",
            )
        )
        client = TestClient(create_app(study_dirs=[]))
        payload = client.get("/api/retrieval/health").json()
        assert payload["state"] == "failed"
        assert payload["detail"] == "RuntimeError: no artefact"
        assert payload["elapsed"] == pytest.approx(1.25)

    def test_the_endpoint_never_loads_an_encoder(self, monkeypatch) -> None:
        """Reading a status must not become a reason to construct anything.

        Patches the CONSTRUCTION SEAM (``query_encoders.get_query_encoder``
        and ``embedding_store.SentenceTransformerEncoder``), not the one
        convenience wrapper (``retrieval.warm_query_encoder``) the route never
        called in the first place -- the route only calls
        ``retrieval.encoder_warm_status()``, so patching the wrapper alone
        passed even before the route existed and would keep passing for any
        future edit that constructed an encoder through a different call site
        (minor finding, fix round 1)."""

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the status endpoint constructed an encoder")

        monkeypatch.setattr(query_encoders, "get_query_encoder", _explode)
        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", _explode)
        client = TestClient(create_app(study_dirs=[]))
        assert client.get("/api/retrieval/health").status_code == 200


class TestTheChipAsset:
    def test_the_chip_handles_every_warm_state(self) -> None:
        source = CHIP_JS.read_text(encoding="utf-8")
        handled = set(re.findall(r"'([a-z]+)':", source))
        assert {state.value for state in retrieval.WarmState} <= handled

    def test_the_chip_polls_the_health_endpoint(self) -> None:
        assert "/api/retrieval/health" in CHIP_JS.read_text(encoding="utf-8")

    def test_the_chip_shows_no_percentage(self) -> None:
        """E-A9: no progress bar, and therefore no percent anywhere near it."""
        assert "%" not in CHIP_JS.read_text(encoding="utf-8")

    def test_the_page_loads_the_chip_and_renders_it(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "/js/retrieval-chip.js" in html
        assert 'id="encoder-warm-chip"' in html

    def test_the_chip_relies_on_alpines_own_auto_init(self) -> None:
        """``Alpine.store(name, value)`` already calls ``value.init()`` on
        registration (verified against the vendored bundle: Alpine 3.14.8's
        registration path calls a store's own ``init()`` unconditionally). An
        explicit second call here doubles every immediate fetch and the
        1500 ms poller for the lifetime of the page. The sibling asset
        (nav-and-panel-stores.js) relies on the auto-init and never
        self-calls; this file must not deviate (minor finding, fix round 1)."""
        source = CHIP_JS.read_text(encoding="utf-8")
        assert not re.search(r"Alpine\.store\([^)]*\)\.init\(\)", source)


class TestStateDirAgreement:
    def test_both_packages_default_to_the_same_state_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``agent_session_tools`` cannot import ``studyloop.settings`` (the
        dependency runs the other way), so it resolves the state dir itself. If
        the two ever diverge, the persisted load durations move somewhere the
        rest of the product does not look."""
        from studyloop import settings

        monkeypatch.delenv(load_indicator.STATE_DIR_ENV, raising=False)
        assert load_indicator.state_dir() == settings.DEFAULT_STATE_DIR

    def test_both_packages_honour_the_same_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyloop import settings

        monkeypatch.setenv(load_indicator.STATE_DIR_ENV, str(tmp_path / "elsewhere"))
        assert load_indicator.state_dir() == settings._default_state_dir()

    def test_a_configured_state_dir_wins_over_both_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``settings.get_state_dir()`` goes through ``load_settings().state_dir``,
        and a raw ``state_dir:`` key in config.yaml overrides that field's
        env-aware default (settings.py's ``_SCALAR_FIELDS``). Before the fix,
        ``load_indicator.state_dir()`` never consulted config.yaml at all, so a
        learner who set ``state_dir:`` had durations persisted somewhere the
        rest of the product never looked (major finding, fix round 1) --
        exactly the two resolvers this class's other tests deliberately do
        NOT exercise, because they agree trivially."""
        from studyloop import settings

        configured = tmp_path / "custom-state"
        config_path = tmp_path / "config.yaml"
        config_path.write_text(f"state_dir: {configured}\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
        # An env override must NOT win over an explicit config-file key --
        # that is settings.py's own precedence, and the two packages must
        # agree on it too.
        monkeypatch.setenv(load_indicator.STATE_DIR_ENV, str(tmp_path / "elsewhere"))
        assert settings.get_state_dir() == configured
        assert load_indicator.state_dir() == settings.get_state_dir()
