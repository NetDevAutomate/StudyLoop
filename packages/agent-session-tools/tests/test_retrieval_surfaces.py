"""Per-surface hybrid default resolution + encoder pre-warm (lane A1, council D-1/D-2/D-3).

Council D-1 (blocking): ``load_config()`` deep-merges user YAML over
``DEFAULT_CONFIG``, so with a boolean schema default an absent key and an
explicit ``false`` were indistinguishable -- the surface default could never
engage. ``semantic_search.hybrid`` is a tri-state sentinel now: ``None``
("unset") lets the surface decide, ``True``/``False`` always wins regardless
of surface. Every truth-table test here drives the real ``load_config()``
with a written YAML fixture (never a pre-built dict), per council TEST SHAPE
ruling A20.

None of these tests import ``sqlite_vec`` or a real encoder: the degradation
tests use a real ``message_embeddings`` row and let the real
``_extension_available()`` run (this environment has no sqlite-vec, so that
IS the "no sidecar" reason), and the encoder-construction-failure test
monkeypatches ``query_encoders.get_query_encoder`` itself -- A2's factory
seam -- rather than a real backend.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from importlib.resources import files
from pathlib import Path

import pytest

from agent_session_tools import (
    config_loader,
    embedding_store,
    query_encoders,
    retrieval,
)
from agent_session_tools.migrations import migrate


def _write_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    config_path = tmp_path / "config.yaml"
    # Hermetic by default: the warm consults the configured database for its
    # model pin, and a fixture that names no database would otherwise read the
    # developer's real ~/.config/studyloop/sessions.db.
    if "database:" not in body:
        body = f"database:\n  path: {tmp_path / 'absent.db'}\n" + body
    config_path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.delenv(retrieval.MODE_ENV, raising=False)


def _semantic_config_from_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    """Drive ``get_semantic_config`` through a real ``load_config()`` YAML fixture."""
    _write_config(tmp_path, monkeypatch, body)
    config = config_loader.load_config()
    real_get_semantic_config = config_loader.get_semantic_config
    monkeypatch.setattr(
        config_loader,
        "get_semantic_config",
        lambda cfg=None: real_get_semantic_config(cfg or config),
    )


class TestSurfaceRegistry:
    def test_every_surface_has_a_default(self):
        assert set(retrieval.SURFACE_DEFAULTS) == set(retrieval.SURFACES)

    def test_every_default_is_a_known_mode(self):
        assert all(
            mode in retrieval.MODES for mode in retrieval.SURFACE_DEFAULTS.values()
        )

    def test_unknown_surface_fails_loudly(self):
        with pytest.raises(ValueError, match="unknown retrieval surface"):
            retrieval.resolve_mode(surface="vibes")


class TestTheFlip:
    """THE FLIP (council REC-2): the final, single, clearly-labelled commit.

    Pinned here rather than in ``TestSurfaceRegistry`` above so dropping just
    that one commit (and this test with it) leaves every earlier commit's
    suite green on its own -- these are the only assertions in the whole
    lane that depend on which mode is the current default.
    """

    def test_cli_stays_lexical(self) -> None:
        assert (
            retrieval.SURFACE_DEFAULTS[retrieval.SURFACE_CLI] == retrieval.MODE_LEXICAL
        )

    def test_mcp_and_web_default_to_hybrid(self) -> None:
        assert (
            retrieval.SURFACE_DEFAULTS[retrieval.SURFACE_MCP] == retrieval.MODE_HYBRID
        )
        assert (
            retrieval.SURFACE_DEFAULTS[retrieval.SURFACE_WEB] == retrieval.MODE_HYBRID
        )


class TestTriStateTruthTable:
    """Council D-1's truth table: arg > env > explicit file > surface default."""

    @pytest.mark.parametrize("surface", retrieval.SURFACES)
    def test_absent_key_yields_the_surface_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path, monkeypatch, "semantic_search:\n  model: stub-model\n"
        )
        config = config_loader.load_config()
        assert config["semantic_search"]["hybrid"] is None, (
            "an absent key must stay the sentinel, not a boolean default"
        )
        assert (
            retrieval.resolve_mode(surface=surface)
            == retrieval.SURFACE_DEFAULTS[surface]
        )

    @pytest.mark.parametrize("surface", retrieval.SURFACES)
    def test_explicit_file_true_forces_hybrid_on_every_surface(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path, monkeypatch, "semantic_search:\n  hybrid: true\n"
        )
        assert retrieval.resolve_mode(surface=surface) == retrieval.MODE_HYBRID

    @pytest.mark.parametrize("surface", retrieval.SURFACES)
    def test_explicit_file_false_forces_lexical_on_every_surface(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path, monkeypatch, "semantic_search:\n  hybrid: false\n"
        )
        assert retrieval.resolve_mode(surface=surface) == retrieval.MODE_LEXICAL

    def test_env_beats_an_explicit_file_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path, monkeypatch, "semantic_search:\n  hybrid: true\n"
        )
        monkeypatch.setenv(retrieval.MODE_ENV, "lexical")
        assert (
            retrieval.resolve_mode(surface=retrieval.SURFACE_MCP)
            == retrieval.MODE_LEXICAL
        )

    def test_argument_beats_env_and_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path, monkeypatch, "semantic_search:\n  hybrid: false\n"
        )
        monkeypatch.setenv(retrieval.MODE_ENV, "lexical")
        assert (
            retrieval.resolve_mode("hybrid", surface=retrieval.SURFACE_CLI)
            == retrieval.MODE_HYBRID
        )

    def test_config_unreadable_falls_back_to_lexical_not_a_surface_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The lexical arm always works -- a broken config must never be read
        as "surface says hybrid"."""
        monkeypatch.delenv(retrieval.MODE_ENV, raising=False)
        monkeypatch.setattr(
            config_loader,
            "get_semantic_config",
            lambda: (_ for _ in ()).throw(RuntimeError("config boom")),
        )
        assert (
            retrieval.resolve_mode(surface=retrieval.SURFACE_MCP)
            == retrieval.MODE_LEXICAL
        )


def _get_tools():
    """Import tool functions from the MCP server (matches test_mcp_server.py)."""
    from importlib import import_module

    from agent_session_tools.mcp_server import mcp

    run_async = import_module(
        f"{__package__}._helpers" if __package__ else "_helpers"
    ).run_async

    tools = run_async(mcp._list_tools())
    return {tool.name: tool.fn for tool in tools}  # type: ignore[attr-defined]


class TestCallSitesPassTheirSurface:
    def test_mcp_session_search_passes_the_mcp_surface(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("fastmcp")
        db_path = tmp_path / "sessions.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            files("agent_session_tools").joinpath("schema.sql").read_text()
        )
        migrate(conn)
        conn.commit()
        conn.close()

        monkeypatch.setattr(
            "agent_session_tools.mcp_server._get_db_path", lambda: db_path
        )

        seen: dict[str, object] = {}
        real_search = retrieval.search

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return real_search(*args, **kwargs)

        monkeypatch.setattr(retrieval, "search", spy)

        tools = _get_tools()
        tools["session_search"](query="nothing")

        assert seen.get("surface") == retrieval.SURFACE_MCP


class TestDegradationThroughTheFactory:
    """Item (b): a hybrid-default surface degrades gracefully, never crashes."""

    def _conn_with_a_vector(self, tmp_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(tmp_path / "sessions.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            files("agent_session_tools").joinpath("schema.sql").read_text()
        )
        migrate(conn)
        conn.execute(
            "INSERT INTO sessions(id, source, updated_at) VALUES ('s-a', 'kiro_cli', '2026-09-01')"
        )
        conn.execute(
            "INSERT INTO messages(id, session_id, role, content, timestamp, seq) "
            "VALUES ('m-a', 's-a', 'assistant', "
            "'a decision about database indexing was made in this message', "
            "'2026-09-01T10:00:00', 1)"
        )
        conn.execute(
            "INSERT INTO message_embeddings(message_id, chunk_ix, model, dim, "
            "content_sha256, truncated, embedding) VALUES "
            "('m-a', 0, 'scripted-model', 4, ?, 0, ?)",
            ("ab" * 32, b"\x00" * 16),
        )
        conn.commit()
        return conn

    def test_no_sidecar_extension_degrades_to_lexical_and_names_the_reason(
        self, tmp_path: Path
    ) -> None:
        """No monkeypatching: this dev environment genuinely has no sqlite-vec,
        so the real ``_extension_available()`` reports it -- exactly the "no
        sidecar" degradation path a learner without the extra hits."""
        conn = self._conn_with_a_vector(tmp_path)
        result = retrieval.search(conn, "database indexing", mode="hybrid")
        assert result.status.mode == "lexical"
        assert result.status.note
        assert "hybrid requested but lexical only" in result.status.note

    def test_encoder_construction_failure_via_the_factory_degrades_to_lexical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = self._conn_with_a_vector(tmp_path)
        monkeypatch.setattr(embedding_store, "_extension_available", lambda: (True, ""))
        monkeypatch.setattr(
            config_loader, "get_semantic_config", lambda: {"query_encoder": "onnx"}
        )

        def _boom(*_args, **_kwargs):
            raise RuntimeError("factory boom")

        monkeypatch.setattr(query_encoders, "get_query_encoder", _boom)

        result = retrieval.search(conn, "database indexing", mode="hybrid")
        assert result.status.mode == "lexical"
        assert "hybrid requested but lexical only" in (result.status.note or "")
        assert "factory boom" in (result.status.note or "")
        assert result.hits, "the lexical arm must still return its own hits"

    def test_the_process_never_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = self._conn_with_a_vector(tmp_path)
        monkeypatch.setattr(embedding_store, "_extension_available", lambda: (True, ""))
        monkeypatch.setattr(
            config_loader, "get_semantic_config", lambda: {"query_encoder": "onnx"}
        )
        monkeypatch.setattr(
            query_encoders,
            "get_query_encoder",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        # Must not raise -- a search never fails because the semantic layer isn't there.
        retrieval.search(conn, "database indexing", mode="hybrid")


class TestEncoderWarmStatus:
    """Item (c): a background warm reports cold/warming/warm/failed/disabled."""

    @pytest.fixture(autouse=True)
    def _clean_state(self):
        query_encoders.reset_cache()
        retrieval.reset_warm_status()
        yield
        query_encoders.reset_cache()
        retrieval.reset_warm_status()

    def test_initial_state_is_cold(self) -> None:
        assert retrieval.encoder_warm_status().state == retrieval.WarmState.COLD

    def test_disabled_when_the_surface_never_resolves_to_hybrid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path, monkeypatch, "semantic_search:\n  hybrid: false\n"
        )
        thread = retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP)
        assert thread is None
        status = retrieval.encoder_warm_status()
        assert status.state == retrieval.WarmState.DISABLED

    def test_cold_to_warming_to_warm_transitions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path,
            monkeypatch,
            "semantic_search:\n  hybrid: true\n  model: warm-model\n",
        )

        class SlowEncoder:
            name = "warm-model"
            dim = 4
            max_tokens = 64

            def __init__(self, model, *, local_files_only=False):
                time.sleep(0.05)

            def count_tokens(self, text):
                return len(text.split())

            def encode(self, texts):
                return [b"\x00" * 16 for _ in texts]

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", SlowEncoder)

        assert retrieval.encoder_warm_status().state == retrieval.WarmState.COLD
        thread = retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP)
        assert thread is not None
        # The warm must report "warming" before it can possibly be done.
        deadline = time.monotonic() + 2
        seen_warming = False
        while time.monotonic() < deadline:
            if retrieval.encoder_warm_status().state == retrieval.WarmState.WARMING:
                seen_warming = True
                break
        assert seen_warming, "never observed the warming state"
        thread.join(timeout=5)
        status = retrieval.encoder_warm_status()
        assert status.state == retrieval.WarmState.WARM
        assert status.model == "warm-model"
        assert status.elapsed is not None and status.elapsed >= 0

    def test_a_failing_construction_reports_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path,
            monkeypatch,
            "semantic_search:\n  hybrid: true\n  model: boom-model\n",
        )

        class Boom:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("kaboom")

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", Boom)
        thread = retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP)
        assert thread is not None
        thread.join(timeout=5)
        status = retrieval.encoder_warm_status()
        assert status.state == retrieval.WarmState.FAILED
        assert "kaboom" in status.detail

    def test_server_boot_never_blocks_on_the_warm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path,
            monkeypatch,
            "semantic_search:\n  hybrid: true\n  model: slow-model\n",
        )

        class SlowEncoder:
            name = "slow-model"
            dim = 4
            max_tokens = 64

            def __init__(self, model, *, local_files_only=False):
                time.sleep(0.3)

            def count_tokens(self, text):
                return len(text.split())

            def encode(self, texts):
                return [b"\x00" * 16 for _ in texts]

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", SlowEncoder)
        start = time.monotonic()
        thread = retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP)
        elapsed = time.monotonic() - start
        assert elapsed < 0.2, (
            "warm_query_encoder must return immediately, not block on the load"
        )
        assert thread is not None
        thread.join(timeout=5)

    def test_a_concurrent_search_does_not_double_construct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _semantic_config_from_yaml(
            tmp_path,
            monkeypatch,
            "semantic_search:\n  hybrid: true\n  model: racey-model\n",
        )
        constructed: list[object] = []

        class SlowEncoder:
            name = "racey-model"
            dim = 4
            max_tokens = 64

            def __init__(self, model, *, local_files_only=False):
                time.sleep(0.1)
                constructed.append(self)

            def count_tokens(self, text):
                return len(text.split())

            def encode(self, texts):
                return [b"\x00" * 16 for _ in texts]

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", SlowEncoder)

        warm_thread = retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP)
        assert warm_thread is not None

        errors: list[BaseException] = []

        def concurrent_search():
            try:
                retrieval._encoder("racey-model")
            except BaseException as exc:  # pragma: no cover - failure path only
                errors.append(exc)

        searcher = threading.Thread(target=concurrent_search)
        searcher.start()
        warm_thread.join(timeout=5)
        searcher.join(timeout=5)

        assert not errors
        assert len(constructed) == 1, (
            "construction ran more than once under a racing search"
        )

    def test_the_warm_never_goes_online(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A background warm bypasses ``retrieval._encoder()`` entirely, so it
        needs its own offline guarantee -- mirrors
        ``TestOfflineLoading`` in test_retrieval_hybrid.py."""
        _semantic_config_from_yaml(
            tmp_path,
            monkeypatch,
            "semantic_search:\n  hybrid: true\n  model: offline-model\n",
        )
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        seen: dict[str, object] = {}

        class Fake:
            def __init__(self, model, *, local_files_only=False):
                seen["model"], seen["local_files_only"] = model, local_files_only

            def count_tokens(self, text):
                return len(text.split())

            def encode(self, texts):
                return [b"\x00" * 16 for _ in texts]

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", Fake)

        thread = retrieval.warm_query_encoder(
            surface=retrieval.SURFACE_MCP, blocking=True
        )
        assert thread is None  # blocking=True never returns a thread
        assert seen == {"model": "offline-model", "local_files_only": True}
        assert os.environ.get("HF_HUB_OFFLINE") == "1"


class TestRetrievalStatusSchemaContract:
    """D-18: pin the field-level shape so B-lane acceptance validators can cite it."""

    def test_the_field_set_is_exactly_the_documented_seven(self) -> None:
        import dataclasses

        names = {field.name for field in dataclasses.fields(retrieval.RetrievalStatus)}
        assert names == {
            "mode",
            "plan",
            "terms",
            "queries",
            "widened",
            "note",
            "semantic",
        }


class TestWarmModelResolution:
    """The warm must heat the encoder searches will use.

    ``_semantic_ranking`` reads its model pin from ``message_embeddings`` in
    the database; a warm that reads only ``semantic_search.model`` heats an
    encoder no search encodes with whenever the config model differs from the
    corpus pin (the schema default does). Resolution: explicit argument, then
    the database pin, then the configured model.
    """

    @pytest.fixture(autouse=True)
    def _clean_state(self):
        query_encoders.reset_cache()
        retrieval.reset_warm_status()
        yield
        query_encoders.reset_cache()
        retrieval.reset_warm_status()

    def _db(self, tmp_path: Path, pin: str | None) -> Path:
        db_path = tmp_path / "sessions.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            files("agent_session_tools").joinpath("schema.sql").read_text()
        )
        migrate(conn)
        if pin is not None:
            conn.execute(
                "INSERT INTO sessions(id, source, updated_at) "
                "VALUES ('s-a', 'kiro_cli', '2026-09-01')"
            )
            conn.execute(
                "INSERT INTO messages(id, session_id, role, content, timestamp, seq) "
                "VALUES ('m-a', 's-a', 'assistant', 'pinned corpus text', "
                "'2026-09-01T10:00:00', 1)"
            )
            conn.execute(
                "INSERT INTO message_embeddings(message_id, chunk_ix, model, dim, "
                "content_sha256, truncated, embedding) VALUES ('m-a', 0, ?, 4, ?, 0, ?)",
                (pin, "ab" * 32, b"\x00" * 16),
            )
        conn.commit()
        conn.close()
        return db_path

    def _warmed_model(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        pin: str | None,
        explicit: str | None = None,
    ) -> tuple[str | None, list[str]]:
        db_path = self._db(tmp_path, pin)
        _semantic_config_from_yaml(
            tmp_path,
            monkeypatch,
            f"database:\n  path: {db_path}\n"
            "semantic_search:\n  hybrid: true\n  model: config-model\n",
        )
        constructed: list[str] = []

        def fake_get_query_encoder(model, **kwargs):
            constructed.append(model)

            class Fake:
                name = model
                dim = 4
                max_tokens = 64

                def count_tokens(self, text):
                    return len(text.split())

                def encode(self, texts):
                    return [b"\x00" * 16 for _ in texts]

            return Fake()

        monkeypatch.setattr(query_encoders, "get_query_encoder", fake_get_query_encoder)
        retrieval.warm_query_encoder(
            surface=retrieval.SURFACE_MCP, model=explicit, blocking=True
        )
        return retrieval.encoder_warm_status().model, constructed

    def test_the_database_pin_beats_the_configured_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warmed, constructed = self._warmed_model(
            tmp_path, monkeypatch, pin="pinned-model"
        )
        assert retrieval.encoder_warm_status().state == retrieval.WarmState.WARM
        assert warmed == "pinned-model"
        assert constructed == ["pinned-model"]

    def test_the_configured_model_is_the_fallback_without_a_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warmed, constructed = self._warmed_model(tmp_path, monkeypatch, pin=None)
        assert warmed == "config-model"
        assert constructed == ["config-model"]

    def test_an_explicit_model_argument_beats_both(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warmed, constructed = self._warmed_model(
            tmp_path, monkeypatch, pin="pinned-model", explicit="explicit-model"
        )
        assert warmed == "explicit-model"
        assert constructed == ["explicit-model"]
