"""The `session-export` auto-embed hook: bounded, optional, and never fatal.

Design D-7. ``session-export`` is what a SessionEnd hook runs, so this step has
three hard properties, and each one is a test below:

1. It asks ``availability()`` first and **never downloads a model** — when the
   model or the ``sqlite-vec`` extension is not already local it prints one line
   naming ``session-maint embed`` and the export still exits 0.
2. It passes ``semantic_search.auto_embed_budget_seconds`` to ``embed()``, so a
   session close can never block on inference for an unbounded time.
3. Nothing it does can fail an export that already committed.

``embedding_store`` is stubbed throughout (Lane B owns the real one), which is
also the point: the hook must reach it through a lazy
``importlib.import_module`` so a ``session-export`` with no semantic extra
installed never pays for sentence-transformers at import time.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
from dataclasses import dataclass

import pytest

from agent_session_tools import export_sessions


@dataclass(frozen=True)
class FakeAvailability:
    ready: bool
    model_ok: bool = True
    extension_ok: bool = True
    reason: str = ""


@dataclass(frozen=True)
class FakeEmbedStats:
    model: str = "all-MiniLM-L6-v2"
    dim: int = 384
    embedded_messages: int = 12
    chunks_written: int = 15
    skipped_changed: int = 1
    remaining: int = 40
    seconds: float = 3.25


class FakeStore:
    """Stands in for ``agent_session_tools.embedding_store``."""

    def __init__(
        self,
        *,
        available: FakeAvailability | None = None,
        availability_raises: BaseException | None = None,
        embed_raises: BaseException | None = None,
        stats: FakeEmbedStats | None = None,
    ) -> None:
        self._available = available or FakeAvailability(ready=True)
        self._availability_raises = availability_raises
        self._embed_raises = embed_raises
        self._stats = stats or FakeEmbedStats()
        self.availability_calls = 0
        self.embed_calls: list[dict[str, object]] = []

    def availability(self, model: str | None = None) -> FakeAvailability:
        self.availability_calls += 1
        if self._availability_raises is not None:
            raise self._availability_raises
        return self._available

    def embed(self, conn: sqlite3.Connection, **kwargs: object) -> FakeEmbedStats:
        self.embed_calls.append({"conn": conn, **kwargs})
        if self._embed_raises is not None:
            raise self._embed_raises
        return self._stats


@pytest.fixture
def install_store(monkeypatch: pytest.MonkeyPatch):
    """Serve a stub for the hook's lazy ``import_module`` call."""

    def _install(store: FakeStore | None) -> FakeStore | None:
        real = importlib.import_module

        def fake_import(name: str, package: str | None = None):
            if name == "agent_session_tools.embedding_store":
                if store is None:
                    raise ImportError(
                        "No module named 'agent_session_tools.embedding_store'"
                    )
                return store
            return real(name, package)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        return store

    return _install


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def _semantic_config(tmp_path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    config = tmp_path / "auto-embed-config.yaml"
    config.write_text(
        "memory:\n  default_scope: unclassified\nsemantic_search:\n" + body
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))


@pytest.fixture(autouse=True)
def auto_embed_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt this module back in to the hook the suite's isolated config disables.

    The package conftest sets ``auto_embed: false`` so that no other test runs
    the real model (its comment says why). These tests are the ones that must
    see the hook fire, so they turn it back on and stub ``embedding_store``. No
    budget key is written, so the 20s D-7 default is what reaches ``embed()``.
    """
    _semantic_config(tmp_path, monkeypatch, "  auto_embed: true\n")


class TestReady:
    def test_embed_runs_with_the_configured_budget_and_prints_one_line(
        self,
        conn: sqlite3.Connection,
        install_store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = install_store(FakeStore())

        export_sessions._maybe_auto_embed(conn)

        assert store.availability_calls == 1, (
            "availability must be asked before embedding"
        )
        assert len(store.embed_calls) == 1
        call = store.embed_calls[0]
        assert call["conn"] is conn
        assert call["budget_seconds"] == 20, "the D-7 default budget must reach embed()"

        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1, f"the hook must print exactly one line, got {out}"
        assert "12" in out[0] and "40" in out[0] and "3.2" in out[0], out[0]

    def test_the_model_load_runs_offline_once_the_cache_check_passed(
        self,
        conn: sqlite3.Connection,
        install_store,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A SessionEnd hook must not issue network HEAD requests for a cached model."""
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        seen: dict[str, str | None] = {}
        store = install_store(FakeStore())
        original_embed = store.embed

        def embed(conn_arg, **kwargs):
            seen["offline"] = os.environ.get("HF_HUB_OFFLINE")
            return original_embed(conn_arg, **kwargs)

        monkeypatch.setattr(store, "embed", embed)
        export_sessions._maybe_auto_embed(conn)
        assert seen == {"offline": "1"}

    def test_the_budget_comes_from_config(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        conn: sqlite3.Connection,
        install_store,
    ) -> None:
        _semantic_config(tmp_path, monkeypatch, "  auto_embed_budget_seconds: 5\n")
        store = install_store(FakeStore())

        export_sessions._maybe_auto_embed(conn)

        assert store.embed_calls[0]["budget_seconds"] == 5

    def test_auto_embed_false_skips_the_hook_entirely(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        conn: sqlite3.Connection,
        install_store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _semantic_config(tmp_path, monkeypatch, "  auto_embed: false\n")
        store = install_store(FakeStore())

        export_sessions._maybe_auto_embed(conn)

        assert store.availability_calls == 0 and not store.embed_calls
        assert capsys.readouterr().out == ""


class TestNotReady:
    def test_prints_the_install_pointer_and_does_not_embed(
        self,
        conn: sqlite3.Connection,
        install_store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = install_store(
            FakeStore(
                available=FakeAvailability(
                    ready=False,
                    model_ok=False,
                    reason="model all-MiniLM-L6-v2 is not downloaded",
                )
            )
        )

        export_sessions._maybe_auto_embed(conn)

        assert not store.embed_calls, "a SessionEnd hook must never download a model"
        out = capsys.readouterr().out.strip()
        assert out == (
            "semantic index not built: model all-MiniLM-L6-v2 is not downloaded; "
            "run session-maint embed"
        ), out


class TestNeverFatal:
    @pytest.mark.parametrize(
        "store",
        [
            FakeStore(embed_raises=RuntimeError("model died mid-batch")),
            FakeStore(embed_raises=sqlite3.OperationalError("database is locked")),
            FakeStore(availability_raises=RuntimeError("torch import blew up")),
        ],
        ids=["embed-raises", "db-locked", "availability-raises"],
    )
    def test_one_warning_line_instead_of_a_failed_export(
        self,
        conn: sqlite3.Connection,
        install_store,
        capsys: pytest.CaptureFixture[str],
        store: FakeStore,
    ) -> None:
        install_store(store)

        export_sessions._maybe_auto_embed(conn)  # must not raise

        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1 and out[0].startswith("warning:"), out

    def test_a_missing_embedding_store_is_a_warning_not_a_crash(
        self,
        conn: sqlite3.Connection,
        install_store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        install_store(None)

        export_sessions._maybe_auto_embed(conn)

        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1 and out[0].startswith("warning:"), out


class TestWiring:
    def test_embedding_store_is_not_imported_at_module_scope(self) -> None:
        """A top-level import would pull sentence-transformers into every export."""
        assert not hasattr(export_sessions, "embedding_store"), (
            "embedding_store must be imported lazily inside _maybe_auto_embed"
        )

    def test_export_run_calls_the_hook_while_the_connection_is_open(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The hook must land after the commit and before the connection closes."""
        seen: list[sqlite3.Connection] = []

        def record(conn: sqlite3.Connection) -> None:
            # A closed connection raises ProgrammingError here; a usable one
            # answers. This is the assertion that pins the call site.
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
            seen.append(conn)

        monkeypatch.setattr(export_sessions, "_maybe_auto_embed", record)
        export_sessions._run_export(tmp_path / "sessions.db", set(), True)

        assert len(seen) == 1, "the auto-embed hook did not run for a successful export"


class TestRealPath:
    """The production caller really hands embed() a connection with no open transaction."""

    def test_the_export_connection_reaches_embed_without_an_ambient_transaction(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import struct
        from importlib.resources import files

        from agent_session_tools import embedding_store
        from agent_session_tools.migrations import migrate

        class Encoder:
            name, dim, max_tokens = "fake-model", 4, 64

            def count_tokens(self, text: str) -> int:
                return len(text.split())

            def encode(self, texts):  # noqa: ANN001
                return [struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in texts]

        db = tmp_path / "sessions.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            files("agent_session_tools").joinpath("schema.sql").read_text()
        )
        migrate(conn)
        conn.execute("INSERT INTO sessions(id, source) VALUES ('s', 'kiro_cli')")
        conn.execute(
            "INSERT INTO messages(id, session_id, role, content) VALUES ('m', 's', 'user', ?)",
            ("a learner question long enough to be embedded by the export hook path",),
        )
        conn.commit()  # what export_run has just done when the hook is called

        seen: dict[str, bool] = {}
        real_embed = embedding_store.embed

        def spy(conn_arg, **kwargs):
            seen["in_transaction_at_entry"] = conn_arg.in_transaction
            return real_embed(conn_arg, encoder=Encoder(), **kwargs)

        monkeypatch.setattr(embedding_store, "embed", spy)
        monkeypatch.setattr(
            embedding_store,
            "availability",
            lambda model=None: embedding_store.Availability(True, True, True, "ready"),
        )
        monkeypatch.setattr(
            embedding_store, "_resolve_pin", lambda model, encoder: ("fake-model", 4)
        )

        export_sessions._maybe_auto_embed(conn)

        assert seen == {"in_transaction_at_entry": False}
        assert (
            conn.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0] == 1
        )
        assert "embedded 1 messages" in capsys.readouterr().out
