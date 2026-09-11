"""`doctor`'s embeddings_alignment check, and the repair `doctor --fix` runs.

The check exists because migration 48's triggers are a *mechanism*: they delete a
message's vectors when its text changes or the row goes away. A mechanism that is
never counted is a mechanism nobody knows failed, so the doctor proves the
invariant with the five counts from ``embedding_alignment`` instead of trusting
it — and the severities have to differ, because only one of the five (the
``missing`` backlog) needs the embedding model to shrink. That one must stay
manual; the other four are plain SQL and `--fix` must actually run them, which is
exactly the dishonesty ``test_doctor_fts_repair.py`` was written for.

Deliberately model-free and extension-free: every state is planted with SQL and
the semantic-extra probe is monkeypatched, so the matrix is identical on a
machine with sentence-transformers installed and one without.
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# A model that IS in SUPPORTED_MODELS, so the check resolves a real dimension and
# `dim` participates in the mismatch count (the `None` path is covered too).
MODEL = "all-MiniLM-L6-v2"
DIM = 384
VEC = b"\x00\x00\x80\x3f" * 4  # opaque bytes; nothing here reads a vector

LONG = "a learner question that is comfortably longer than fifty characters here"


def _build_sessions_db(path: Path) -> None:
    """A real sessions DB: agent_session_tools schema.sql + every migration."""
    from agent_session_tools.migrations import migrate

    conn = sqlite3.connect(path)
    try:
        conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
        migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _connect(path: Path, *, foreign_keys: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    """Two eligible messages (m1, m2) plus one ineligible tool_result (m3)."""
    conn.execute("INSERT INTO sessions(id, source) VALUES ('s1', 'kiro_cli')")
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES "
        "('m1','s1','user',?), ('m2','s1','assistant',?), ('m3','s1','tool_result',?)",
        (LONG, LONG, LONG),
    )


def _seed_hidden(conn: sqlite3.Connection) -> None:
    """A session under a retired source label — eligible-at-embed-time, hidden now."""
    conn.execute("INSERT INTO sessions(id, source) VALUES ('hidden', 'aider')")
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES ('h1','hidden','user',?)",
        (LONG,),
    )


def _vector(
    conn: sqlite3.Connection,
    message_id: str,
    chunk_ix: int = 0,
    *,
    model: str = MODEL,
    dim: int = DIM,
    sha: str | None = None,
) -> None:
    from agent_session_tools import embedding_alignment as align

    if sha is None:
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
        sha = align.content_sha256(row[0] if row else "")
    conn.execute(
        "INSERT INTO message_embeddings"
        "(message_id, chunk_ix, model, dim, content_sha256, embedding) VALUES (?,?,?,?,?,?)",
        (message_id, chunk_ix, model, dim, sha, VEC),
    )


@pytest.fixture
def sessions_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A migrated sessions DB that every doctor path resolves to."""
    db = tmp_path / "sessions.db"
    _build_sessions_db(db)
    # _get_sessions_db_path() -> studyloop.settings.get_db_path(), which honours
    # STUDYLOOP_DB. Same mechanism test_doctor_fts_repair.py uses.
    monkeypatch.setenv("STUDYLOOP_DB", str(db))
    monkeypatch.setenv("EMBEDDING_MODEL", MODEL)
    return db


@pytest.fixture
def semantic_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the extra as present, so the matrix does not depend on this machine."""
    import studyloop.doctor.database as database

    monkeypatch.setattr(database, "_missing_semantic_modules", lambda: ())


def _result(db: Path):
    """Run the check the way check_sessions_db does and return its single row."""
    from studyloop.doctor.database import _check_embeddings_alignment

    conn = _connect(db)
    try:
        results = _check_embeddings_alignment(conn, db)
    finally:
        conn.close()
    assert len(results) == 1, f"expected exactly one row, got {results}"
    return results[0]


class TestSeverityMatrix:
    def test_pass_when_every_eligible_message_has_a_current_vector(
        self, sessions_db: Path, semantic_installed: None
    ) -> None:
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
            _vector(conn, "m1")
            _vector(conn, "m2")
        conn.close()

        result = _result(sessions_db)
        assert result.status == "pass", result.message
        assert result.name == "embeddings_alignment"
        assert result.category == "database"
        assert result.fix_auto is False
        assert "message_embeddings" in result.message, "the real table must be named"

    def test_warn_when_only_the_backlog_is_non_zero(
        self, sessions_db: Path, semantic_installed: None
    ) -> None:
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
        conn.close()

        result = _result(sessions_db)
        assert result.status == "warn", result.message
        assert result.fix_hint == "session-maint embed"
        assert result.fix_auto is False, (
            "shrinking the backlog needs the model; doctor --fix must not claim it can"
        )
        assert "2 of 2" in result.message, result.message

    @pytest.mark.parametrize(
        ("state", "plant"),
        [
            ("stale", lambda conn: _vector(conn, "m1", sha="0" * 64)),
            ("orphaned", lambda conn: _vector(conn, "ghost", sha="0" * 64)),
            ("model_mismatch", lambda conn: _vector(conn, "m1", model="other-model")),
            ("model_mismatch", lambda conn: _vector(conn, "m1", dim=DIM + 1)),
        ],
    )
    def test_fail_for_each_misaligned_state(
        self,
        sessions_db: Path,
        semantic_installed: None,
        state: str,
        plant,
    ) -> None:
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
            _vector(conn, "m2")
            plant(conn)
        conn.close()

        result = _result(sessions_db)
        assert result.status == "fail", result.message
        assert state in result.message, result.message
        assert result.fix_hint == "session-maint embed-check --fix"
        assert result.fix_auto is True

    def test_fail_for_a_hidden_source_whose_vectors_survived_retirement(
        self, sessions_db: Path, semantic_installed: None
    ) -> None:
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
            _seed_hidden(conn)
            _vector(conn, "m1")
            _vector(conn, "m2")
            _vector(conn, "h1")
        conn.close()

        result = _result(sessions_db)
        assert result.status == "fail", result.message
        assert "hidden 1" in result.message, result.message
        assert result.fix_auto is True

    def test_fail_wins_over_the_backlog_warning(
        self, sessions_db: Path, semantic_installed: None
    ) -> None:
        """A misaligned vector is a live wrong answer; a backlog is only absence."""
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
            _vector(conn, "m1", sha="0" * 64)  # stale, and m2 still missing
        conn.close()

        result = _result(sessions_db)
        assert result.status == "fail", result.message

    def test_info_when_the_semantic_extra_is_absent_and_nothing_is_embedded(
        self, sessions_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import studyloop.doctor.database as database

        monkeypatch.setattr(
            database, "_missing_semantic_modules", lambda: ("sentence_transformers",)
        )
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
        conn.close()

        result = _result(sessions_db)
        assert result.status == "info", result.message
        assert result.fix_auto is False
        assert "sentence_transformers" in result.message
        assert "agent-session-tools[semantic]" in result.fix_hint
        # info must not move the exit code: a missing optional extra is not a fault.
        from studyloop.cli._doctor import _compute_exit_code

        assert _compute_exit_code([result]) == 0

    def test_missing_extra_does_not_hide_misalignment_once_vectors_exist(
        self, sessions_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rows > 0 means the invariant is live, whatever is installed today."""
        import studyloop.doctor.database as database

        monkeypatch.setattr(database, "_missing_semantic_modules", lambda: ("sqlite_vec",))
        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
            _vector(conn, "m1", sha="0" * 64)
        conn.close()

        assert _result(sessions_db).status == "fail"

    def test_no_message_embeddings_table_is_not_a_finding(self, tmp_path: Path) -> None:
        """A database below migration 48 has nothing to align — same as _check_fts_drift."""
        from studyloop.doctor.database import _check_embeddings_alignment

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(db)
        with conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT)")
            conn.execute(
                "CREATE TABLE messages (id TEXT PRIMARY KEY, session_id TEXT, "
                "role TEXT, content TEXT)"
            )
        try:
            assert _check_embeddings_alignment(conn, db) == []
        finally:
            conn.close()


class TestConfiguredModel:
    def test_a_registry_model_resolves_its_dimension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyloop.doctor.database import _configured_embedding_model

        monkeypatch.setenv("EMBEDDING_MODEL", MODEL)
        assert _configured_embedding_model() == (MODEL, DIM)

    def test_an_unknown_model_resolves_no_dimension_rather_than_guessing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyloop.doctor.database import _configured_embedding_model

        monkeypatch.setenv("EMBEDDING_MODEL", "hand-set-model")
        assert _configured_embedding_model() == ("hand-set-model", None)


class TestCheckIsWiredIntoCheckSessionsDb:
    def test_check_sessions_db_reports_embeddings_alignment(
        self, sessions_db: Path, semantic_installed: None
    ) -> None:
        from studyloop.doctor.database import check_sessions_db

        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
            _vector(conn, "m1")
            _vector(conn, "m2")
        conn.close()

        names = [r.name for r in check_sessions_db()]
        assert "embeddings_alignment" in names, names


class _FakeStore:
    """Stands in for Lane B's embedding_store, which doctor --fix imports lazily."""

    def __init__(self, *, reconcile_raises: BaseException | None = None) -> None:
        self.calls: list[sqlite3.Connection] = []
        self._raises = reconcile_raises

    def reconcile(self, conn: sqlite3.Connection) -> tuple[int, int]:
        self.calls.append(conn)
        if self._raises is not None:
            raise self._raises
        return (7, 2)


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch):
    """Install a fake ``agent_session_tools.embedding_store`` for the lazy import."""
    import importlib

    def _install(store: _FakeStore) -> _FakeStore:
        real = importlib.import_module

        def fake_import(name: str, package: str | None = None):
            if name == "agent_session_tools.embedding_store":
                return store
            return real(name, package)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        return store

    return _install


class TestDoctorFixRepairsAlignment:
    @staticmethod
    def _misaligned(db: Path) -> None:
        conn = _connect(db)
        with conn:
            _seed(conn)
            _seed_hidden(conn)
            _vector(conn, "m1")  # aligned — must survive
            _vector(conn, "m2", sha="0" * 64)  # stale
            _vector(conn, "h1")  # hidden
            _vector(conn, "ghost", sha="0" * 64)  # orphaned
            _vector(conn, "m1", chunk_ix=1, model="other-model")  # model mismatch
        conn.close()

    @staticmethod
    def _rows(db: Path) -> list[tuple[str, int]]:
        conn = sqlite3.connect(db)
        try:
            return [
                (r[0], r[1])
                for r in conn.execute(
                    "SELECT message_id, chunk_ix FROM message_embeddings ORDER BY 1,2"
                )
            ]
        finally:
            conn.close()

    def test_apply_fixes_sweeps_every_misaligned_vector_and_keeps_the_aligned_one(
        self, sessions_db: Path, semantic_installed: None, fake_store
    ) -> None:
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.database import check_sessions_db

        self._misaligned(sessions_db)
        assert len(self._rows(sessions_db)) == 5, "fixture did not plant the states"
        store = fake_store(_FakeStore())

        results = check_sessions_db()
        assert any(r.name == "embeddings_alignment" and r.status == "fail" for r in results), [
            r.name for r in results
        ]

        actions = _apply_fixes(results)

        assert self._rows(sessions_db) == [("m1", 0)], (
            "sweep must delete exactly the misaligned vectors and nothing else"
        )
        assert store.calls, "the sidecar index was never reconciled"
        action = next(a for a in actions if "embeddings alignment" in a)
        assert "swept 4" in action, action
        assert "+7/-2" in action, action

        # And the re-run is clean: only the backlog is left.
        after = [r for r in check_sessions_db() if r.name == "embeddings_alignment"]
        assert after[0].status == "warn", after[0].message

    def test_sweep_still_repairs_when_the_sidecar_extension_is_absent(
        self, sessions_db: Path, semantic_installed: None, fake_store
    ) -> None:
        """D-8: no sqlite-vec means no derived index — not a failed fix."""
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.database import check_sessions_db

        self._misaligned(sessions_db)
        fake_store(_FakeStore(reconcile_raises=ImportError("no module named sqlite_vec")))

        actions = _apply_fixes(check_sessions_db())

        assert self._rows(sessions_db) == [("m1", 0)]
        action = next(a for a in actions if "embeddings alignment" in a)
        assert "not rebuilt" in action, action

    def test_a_backlog_alone_is_never_auto_fixed(
        self, sessions_db: Path, semantic_installed: None, fake_store
    ) -> None:
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.database import check_sessions_db

        conn = _connect(sessions_db)
        with conn:
            _seed(conn)
        conn.close()
        store = fake_store(_FakeStore())

        actions = _apply_fixes(check_sessions_db())

        assert not any("embeddings alignment" in a for a in actions), actions
        assert not store.calls, "nothing to reconcile when nothing was misaligned"
