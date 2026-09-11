"""Unit tier for ``embedding_store``: a fake encoder, real SQLite, no model.

The encoder is the seam the design put there on purpose, so every decision this
file pins -- D-3 chunking, D-4 the hash checked inside the write transaction,
D-5 the model pin -- is checked with deterministic vectors and a token count
you can do in your head (whitespace words). Only the sidecar tests need the
real ``sqlite-vec`` extension, and they skip without it.

The semantic-profile file (``test_embedding_semantic_profile.py``) is the same
substrate driven by the real model; this one is what CI runs on every commit.
"""

from __future__ import annotations

import sqlite3
import struct
from importlib.resources import files
from pathlib import Path

import pytest

from agent_session_tools import embedding_alignment as align
from agent_session_tools import embedding_store as store
from agent_session_tools.migrations import migrate

DIM = 4
LONG = "a learner question long enough to be eligible, fifty characters or more here"


class FakeEncoder:
    """Deterministic stand-in for a sentence-transformers model.

    Tokens are whitespace-separated words, so ``max_tokens=8`` means "eight
    words" and a chunk boundary is something the test can state literally. The
    default cap is comfortably above ``LONG`` so the storage tests are
    single-chunk by construction; the chunking tests pass a small cap on
    purpose. The vector is a hash of the text, normalised, so identical text
    always encodes identically and different text almost never collides.
    """

    def __init__(
        self, *, name: str = "fake-model", dim: int = DIM, max_tokens: int = 32
    ) -> None:
        self.name = name
        self.dim = dim
        self.max_tokens = max_tokens
        self.calls: list[list[str]] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode(self, texts):  # noqa: ANN001 - Protocol shape, checked by the store
        self.calls.append(list(texts))
        out: list[bytes] = []
        for text in texts:
            seed = sum((i + 1) * ord(c) for i, c in enumerate(text)) or 1
            raw = [((seed >> (3 * k)) % 97) + 1 for k in range(self.dim)]
            norm = sum(v * v for v in raw) ** 0.5
            out.append(struct.pack(f"<{self.dim}f", *[v / norm for v in raw]))
        return out


def _db(tmp_path: Path, name: str = "sessions.db") -> tuple[sqlite3.Connection, Path]:
    db_path = tmp_path / name
    conn = sqlite3.connect(db_path)
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    return conn, db_path


def _seed(
    conn: sqlite3.Connection, messages: dict[str, str], *, source: str = "kiro_cli"
) -> None:
    session_id = f"s-{source}"
    conn.execute(
        "INSERT OR IGNORE INTO sessions(id, source) VALUES (?, ?)", (session_id, source)
    )
    for seq, (message_id, content) in enumerate(messages.items(), start=1):
        conn.execute(
            "INSERT INTO messages(id, session_id, role, content, seq) VALUES (?,?,?,?,?)",
            (message_id, session_id, "user", content, seq),
        )
    conn.commit()


def _rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT message_id, chunk_ix, model, dim, content_sha256, truncated, embedding "
        "FROM message_embeddings ORDER BY message_id, chunk_ix"
    ).fetchall()


# ---------------------------------------------------------------------------
# D-3 chunking
# ---------------------------------------------------------------------------


def test_short_text_is_one_untruncated_chunk():
    encoder = FakeEncoder(max_tokens=8)
    assert store.chunk_text("four words go here", encoder) == [
        ("four words go here", False)
    ]


def test_empty_text_produces_no_chunks():
    assert store.chunk_text("", FakeEncoder()) == []


def test_chunks_break_on_paragraph_boundaries_before_sentences():
    encoder = FakeEncoder(max_tokens=6)
    text = "one two three four.\n\nfive six seven eight."
    chunks = store.chunk_text(text, encoder)
    assert [chunk for chunk, _ in chunks] == [
        "one two three four.\n\n",
        "five six seven eight.",
    ]
    assert not any(truncated for _, truncated in chunks)


def test_a_long_paragraph_falls_back_to_sentence_boundaries():
    encoder = FakeEncoder(max_tokens=5)
    text = "alpha beta gamma delta. epsilon zeta eta theta. iota kappa."
    chunks = store.chunk_text(text, encoder)
    assert [chunk for chunk, _ in chunks] == [
        "alpha beta gamma delta. ",
        "epsilon zeta eta theta. ",
        "iota kappa.",
    ]
    assert not any(truncated for _, truncated in chunks)


def test_a_sentence_over_the_cap_becomes_hard_windows_marked_truncated():
    encoder = FakeEncoder(max_tokens=4)
    text = "one two three four five six seven eight nine"
    chunks = store.chunk_text(text, encoder)
    assert len(chunks) > 1
    assert all(truncated for _, truncated in chunks), "every hard window is marked"
    assert all(encoder.count_tokens(chunk) <= 4 for chunk, _ in chunks)


@pytest.mark.parametrize(
    "text",
    [
        "one two three four five six seven eight nine ten eleven twelve",
        "para one has words here.\n\npara two also has several words here.\n\nshort.",
        "no-whitespace-at-all-" * 40,
        "  leading space and a trailing newline and enough words to split\n",
    ],
)
def test_chunking_never_drops_content(text: str):
    """The invariant behind "no truncation": the chunks rebuild the text exactly."""
    encoder = FakeEncoder(max_tokens=5)
    chunks = store.chunk_text(text, encoder)
    assert "".join(chunk for chunk, _ in chunks) == text
    assert all(encoder.count_tokens(chunk) <= 5 for chunk, _ in chunks)


def test_a_cap_that_cannot_hold_a_character_is_refused_rather_than_looped():
    class Impossible(FakeEncoder):
        def count_tokens(self, text: str) -> int:
            return 99 if text else 0

    with pytest.raises(ValueError, match="cannot hold even one character"):
        store.chunk_text("anything at all", Impossible(max_tokens=1))


# ---------------------------------------------------------------------------
# D-4 the embed job
# ---------------------------------------------------------------------------


def test_embed_writes_rows_with_the_message_hash_model_and_dim(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    encoder = FakeEncoder()

    stats = store.embed(conn, encoder=encoder)

    assert (stats.embedded_messages, stats.chunks_written, stats.remaining) == (1, 1, 0)
    assert (stats.model, stats.dim) == ("fake-model", DIM)
    (row,) = _rows(conn)
    message_id, chunk_ix, model, dim, sha, truncated, embedding = row
    assert (message_id, chunk_ix, model, dim, truncated) == (
        "m1",
        0,
        "fake-model",
        DIM,
        0,
    )
    assert sha == align.content_sha256(LONG)
    assert len(embedding) == DIM * 4
    assert align.alignment_report(conn, model="fake-model", dim=DIM).complete


def test_chunk_ix_is_a_dense_sequence_and_every_chunk_carries_the_message_hash(
    tmp_path: Path,
):
    conn, _ = _db(tmp_path)
    content = "alpha beta gamma delta. epsilon zeta eta theta. iota kappa lambda mu nu."
    _seed(conn, {"m1": content})

    stats = store.embed(conn, encoder=FakeEncoder(max_tokens=5))

    rows = _rows(conn)
    assert stats.chunks_written == len(rows) > 1
    assert [r[1] for r in rows] == list(range(len(rows)))
    assert {r[4] for r in rows} == {align.content_sha256(content)}
    assert align.alignment_report(conn, model="fake-model", dim=DIM).stale == 0


def test_truncated_chunks_are_recorded_as_such_in_the_row(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(
        conn, {"m1": "one two three four five six seven eight nine ten eleven twelve"}
    )

    stats = store.embed(conn, encoder=FakeEncoder(max_tokens=4))

    truncated_flags = [r[5] for r in _rows(conn)]
    assert set(truncated_flags) == {1}
    assert stats.truncated_chunks == len(truncated_flags)


def test_content_that_changes_between_encode_and_write_is_skipped_not_stored(
    tmp_path: Path,
):
    """D-4: the hash is the proof. No row ever describes text the message no longer has."""
    conn, db_path = _db(tmp_path)
    _seed(conn, {"m1": LONG, "m2": LONG + " second message"})
    rewritten = "rewritten by the exporter, still long enough to stay eligible here"
    fired = {"n": 0}

    def rewrite_m1_once() -> None:
        # A second connection is the real shape of the race: the exporter's
        # upsert commits while the embed job holds no lock (encoding).
        fired["n"] += 1
        if fired["n"] > 1:
            return
        other = sqlite3.connect(db_path)
        try:
            other.execute(
                "UPDATE messages SET content = ? WHERE id = 'm1'", (rewritten,)
            )
            other.commit()
        finally:
            other.close()

    stats = store.embed(conn, encoder=FakeEncoder(), _after_encode=rewrite_m1_once)

    assert stats.skipped_changed == 1, "the encoded m1 was refused at the write"
    stored = {row[0]: row[4] for row in _rows(conn)}
    assert stored["m1"] == align.content_sha256(rewritten), (
        "m1 was re-embedded against the text it now has, never the text that was encoded"
    )
    assert stored["m2"] == align.content_sha256(LONG + " second message")
    report = align.alignment_report(conn, model="fake-model", dim=DIM)
    assert report.stale == 0 and report.complete


def test_a_batch_in_which_everything_changed_stops_instead_of_spinning(tmp_path: Path):
    conn, db_path = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    seen = {"n": 0}

    def rewrite_every_time() -> None:
        seen["n"] += 1
        other = sqlite3.connect(db_path)
        try:
            other.execute(
                "UPDATE messages SET content = ? WHERE id = 'm1'",
                (
                    f"rewritten {seen['n']} times and still long enough to be eligible here",
                ),
            )
            other.commit()
        finally:
            other.close()

    stats = store.embed(conn, encoder=FakeEncoder(), _after_encode=rewrite_every_time)

    assert seen["n"] == 1, "one batch, then it gives up rather than looping"
    assert (stats.embedded_messages, stats.skipped_changed, stats.remaining) == (
        0,
        1,
        1,
    )


def test_budget_stops_between_batches_and_reports_the_remainder(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {f"m{n}": f"{LONG} number {n}" for n in range(1, 6)})

    class SlowEncoder(FakeEncoder):
        """Each batch costs more than the whole budget, so exactly one runs."""

        def __init__(self, clock: list[float]) -> None:
            super().__init__()
            self._clock = clock

        def encode(self, texts):  # noqa: ANN001
            self._clock[0] += 10.0
            return super().encode(texts)

    clock = [0.0]
    monkey = pytest.MonkeyPatch()
    monkey.setattr(store.time, "monotonic", lambda: clock[0])
    try:
        stats = store.embed(
            conn, encoder=SlowEncoder(clock), budget_seconds=1.0, batch_size=2
        )
    finally:
        monkey.undo()

    assert stats.embedded_messages == 2, "one batch of two, then the budget stops it"
    assert stats.remaining == 3 > 0
    assert align.alignment_report(conn, model="fake-model", dim=DIM).aligned


def test_hidden_sources_are_never_embedded(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    _seed(conn, {"h1": LONG + " retired"}, source="aider")

    store.embed(conn, encoder=FakeEncoder())

    assert [r[0] for r in _rows(conn)] == ["m1"]
    assert align.alignment_report(conn, model="fake-model", dim=DIM).hidden == 0


def test_embed_is_idempotent(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    first = store.embed(conn, encoder=FakeEncoder())
    second = store.embed(conn, encoder=FakeEncoder())
    assert first.embedded_messages == 1
    assert (second.embedded_messages, second.chunks_written, second.remaining) == (
        0,
        0,
        0,
    )
    assert len(_rows(conn)) == 1


# ---------------------------------------------------------------------------
# D-5 the model pin
# ---------------------------------------------------------------------------


def test_embed_refuses_while_another_models_vectors_exist(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG, "m2": LONG + " two"})
    store.embed(conn, encoder=FakeEncoder(name="old-model"))

    with pytest.raises(ValueError, match="--replace-model"):
        store.embed(conn, encoder=FakeEncoder(name="new-model"))

    assert {r[2] for r in _rows(conn)} == {"old-model"}


def test_replace_model_sweeps_the_mismatch_then_embeds(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG, "m2": LONG + " two"})
    store.embed(conn, encoder=FakeEncoder(name="old-model"))

    stats = store.embed(conn, encoder=FakeEncoder(name="new-model"), replace_model=True)

    assert stats.swept == 2
    assert stats.embedded_messages == 2
    assert {r[2] for r in _rows(conn)} == {"new-model"}
    assert align.alignment_report(conn, model="new-model", dim=DIM).complete


def test_a_model_argument_that_contradicts_the_encoder_is_refused(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    with pytest.raises(ValueError, match="does not match the injected encoder"):
        store.embed(conn, model="some-other-model", encoder=FakeEncoder())


# ---------------------------------------------------------------------------
# D-2 the sidecar
# ---------------------------------------------------------------------------


def test_sidecar_sits_beside_the_database_and_never_inside_it():
    assert store.sidecar_path(Path("/tmp/x/sessions.db")) == Path(
        "/tmp/x/sessions.vec.db"
    )
    assert store.sidecar_path("/tmp/x/hot.sqlite3") == Path("/tmp/x/hot.vec.db")


def test_chunk_key_round_trips_even_when_the_id_contains_the_separator():
    assert store.chunk_key("m#1", 7) == "m#1#7"
    assert store.split_chunk_key("m#1#7") == ("m#1", 7)


def test_availability_never_downloads_and_names_the_missing_half(monkeypatch):
    """The export path (D-7) calls this on every session end; it must be cheap."""
    import builtins

    real_import = builtins.__import__

    def no_sqlite_vec(name, *args, **kwargs):
        if name == "sqlite_vec":
            raise ImportError("no sqlite_vec")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sqlite_vec)
    result = store.availability("all-MiniLM-L6-v2")
    assert not result.ready and not result.extension_ok
    assert store.INSTALL_HINT in result.reason


class TestSidecarIndex:
    """Everything that needs the real ``vec0`` virtual table."""

    @pytest.fixture(autouse=True)
    def _require_extension(self):
        pytest.importorskip("sqlite_vec")

    def test_reconcile_inserts_what_is_missing_and_deletes_what_is_extra(
        self, tmp_path: Path
    ):
        conn, db_path = _db(tmp_path)
        _seed(conn, {"m1": LONG, "m2": LONG + " two"})
        store.embed(conn, encoder=FakeEncoder())

        inserted, deleted = store.reconcile(conn)
        assert (inserted, deleted) == (2, 0)
        assert store.sidecar_path(db_path).exists(), "the index is a file beside the DB"

        assert store.reconcile(conn) == (0, 0), "idempotent"

        # A vector deleted from the record must leave the index; an orphan key
        # planted in the index must leave it too.
        conn.execute("DELETE FROM message_embeddings WHERE message_id='m2'")
        conn.commit()
        conn.execute(
            "INSERT INTO vec.message_vec(chunk_key, embedding) VALUES (?,?)",
            ("ghost#0", struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)),
        )
        conn.commit()
        assert store.reconcile(conn) == (0, 2)
        assert conn.execute("SELECT chunk_key FROM vec.message_vec").fetchall() == [
            ("m1#0",)
        ]

    def test_sessions_db_holds_no_virtual_table_so_plain_maintenance_still_works(
        self, tmp_path: Path
    ):
        conn, db_path = _db(tmp_path)
        _seed(conn, {"m1": LONG})
        store.embed(conn, encoder=FakeEncoder())
        store.reconcile(conn)

        plain = sqlite3.connect(db_path)
        try:
            names = {r[0] for r in plain.execute("SELECT name FROM sqlite_master")}
            assert not any(name.startswith("message_vec") for name in names)
            assert plain.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            plain.execute("VACUUM INTO ?", (str(tmp_path / "clone.db"),))
        finally:
            plain.close()

    def test_knn_returns_the_chunk_itself_at_distance_zero(self, tmp_path: Path):
        conn, _ = _db(tmp_path)
        _seed(
            conn,
            {"m1": LONG, "m2": "an entirely different message, also long enough here"},
        )
        store.embed(conn, encoder=FakeEncoder())
        store.reconcile(conn)

        own = conn.execute(
            "SELECT embedding FROM message_embeddings WHERE message_id='m1' AND chunk_ix=0"
        ).fetchone()[0]
        hits = store.knn(conn, own, 2)

        assert hits[0][0] == "m1" and hits[0][1] == 0
        assert hits[0][2] == pytest.approx(0.0, abs=1e-5)
        assert len(hits) == 2 and hits[1][2] > hits[0][2]

    def test_knn_without_an_index_says_how_to_build_one(self, tmp_path: Path):
        conn, _ = _db(tmp_path)
        _seed(conn, {"m1": LONG})
        with pytest.raises(RuntimeError, match="no vector index"):
            store.knn(conn, struct.pack("<4f", 1.0, 0.0, 0.0, 0.0), 1)

    def test_reconcile_refuses_a_table_holding_two_dimensions(self, tmp_path: Path):
        conn, _ = _db(tmp_path)
        _seed(conn, {"m1": LONG})
        store.embed(conn, encoder=FakeEncoder())
        conn.execute(
            "INSERT INTO message_embeddings"
            "(message_id, chunk_ix, model, dim, content_sha256, embedding) VALUES (?,?,?,?,?,?)",
            (
                "m1",
                1,
                "other",
                8,
                align.content_sha256(LONG),
                struct.pack("<8f", *([0.5] * 8)),
            ),
        )
        conn.commit()
        with pytest.raises(ValueError, match="more than one dimension"):
            store.reconcile(conn)

    def test_ensure_index_rebuilds_a_sidecar_built_for_another_dimension(
        self, tmp_path: Path
    ):
        conn, _ = _db(tmp_path)
        _seed(conn, {"m1": LONG})
        store.ensure_index(conn, model="fake-model", dim=8)
        conn.execute(
            "INSERT INTO vec.message_vec(chunk_key, embedding) VALUES (?,?)",
            ("stale#0", struct.pack("<8f", *([0.5] * 8))),
        )
        conn.commit()

        store.ensure_index(conn, model="fake-model", dim=DIM)

        sql = conn.execute(
            "SELECT sql FROM vec.sqlite_master WHERE name='message_vec'"
        ).fetchone()[0]
        assert "float[4]" in sql
        assert conn.execute("SELECT COUNT(*) FROM vec.message_vec").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Stage 3 council corrections
# ---------------------------------------------------------------------------


def test_embed_refuses_an_ambient_transaction(tmp_path: Path):
    """astra 4: encoding must hold no lock and every batch must own its BEGIN IMMEDIATE."""
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    conn.execute("BEGIN")
    with pytest.raises(ValueError, match="no open transaction"):
        store.embed(conn, encoder=FakeEncoder())
    conn.rollback()
    assert _rows(conn) == []


def test_a_source_retired_between_encode_and_write_is_not_embedded(tmp_path: Path):
    """astra 2: the write re-checks the whole eligibility predicate, not only the hash."""
    conn, db_path = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    fired = {"n": 0}

    def retire_the_source_once() -> None:
        fired["n"] += 1
        if fired["n"] > 1:
            return
        other = sqlite3.connect(db_path)
        try:
            other.execute(
                "UPDATE sessions SET source = 'aider' WHERE id = 's-kiro_cli'"
            )
            other.commit()
        finally:
            other.close()

    stats = store.embed(
        conn, encoder=FakeEncoder(), _after_encode=retire_the_source_once
    )
    assert stats.embedded_messages == 0 and stats.skipped_changed == 1
    assert _rows(conn) == []
    report = align.alignment_report(conn, model="fake-model", dim=DIM)
    assert report.hidden == 0 and report.eligible == 0


def test_embed_sweeps_orphaned_stale_and_hidden_rows_without_being_asked(
    tmp_path: Path,
):
    """astra 2 (second half): a run that ends with missing == 0 also ends aligned."""
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    _seed(conn, {"h1": LONG + " in a retired source"}, source="aider")
    conn.execute("PRAGMA foreign_keys=OFF")
    for message_id, sha in (
        ("ghost", align.content_sha256("")),  # orphaned
        ("m1", "0" * 64),  # stale
        ("h1", align.content_sha256(LONG + " in a retired source")),  # hidden
    ):
        conn.execute(
            "INSERT INTO message_embeddings"
            "(message_id, chunk_ix, model, dim, content_sha256, embedding) VALUES (?,?,?,?,?,?)",
            (message_id, 0, "fake-model", DIM, sha, b"\x00" * (DIM * 4)),
        )
    conn.commit()
    assert not align.alignment_report(conn, model="fake-model", dim=DIM).aligned

    stats = store.embed(conn, encoder=FakeEncoder())

    assert stats.swept == 3
    report = align.alignment_report(conn, model="fake-model", dim=DIM)
    assert report.complete, report.to_dict()
    assert {row[0] for row in _rows(conn)} == {"m1"}


def test_embed_still_refuses_another_models_rows_unless_told_to_replace(tmp_path: Path):
    conn, _ = _db(tmp_path)
    _seed(conn, {"m1": LONG})
    conn.execute(
        "INSERT INTO message_embeddings"
        "(message_id, chunk_ix, model, dim, content_sha256, embedding) VALUES (?,?,?,?,?,?)",
        ("m1", 0, "other-model", DIM, align.content_sha256(LONG), b"\x00" * (DIM * 4)),
    )
    conn.commit()
    with pytest.raises(ValueError, match="replace-model"):
        store.embed(conn, encoder=FakeEncoder())
    assert [row[2] for row in _rows(conn)] == ["other-model"], "refusal deleted nothing"


class TestCandidates:
    """D-6 as a query: nothing stale and nothing hidden survives the join."""

    @pytest.fixture(autouse=True)
    def _need_extension(self):
        pytest.importorskip("sqlite_vec")

    def test_stale_hidden_and_deleted_neighbours_are_filtered_out(self, tmp_path: Path):
        conn, _ = _db(tmp_path)
        encoder = FakeEncoder()
        _seed(
            conn,
            {"keep": LONG, "scrubbed": LONG + " scrub me", "gone": LONG + " delete me"},
        )
        _seed(conn, {"retired": LONG + " retired later"}, source="codex")
        store.embed(conn, encoder=encoder)
        store.reconcile(conn)
        assert conn.execute("SELECT COUNT(*) FROM vec.message_vec").fetchone()[0] == 4

        # The sidecar goes stale on purpose: three writes, no reconcile after them.
        conn.execute(
            "UPDATE messages SET content = ? WHERE id = 'scrubbed'",
            ("[REDACTED] " + LONG,),
        )
        conn.execute("DELETE FROM messages WHERE id = 'gone'")
        conn.execute("UPDATE sessions SET source = 'aider' WHERE id = 's-codex'")
        conn.commit()

        probe = encoder.encode([LONG])[0]
        raw = {message_id for message_id, _, _ in store.knn(conn, probe, 10)}
        assert raw == {"keep", "scrubbed", "gone", "retired"}, (
            "the raw index still names all four"
        )
        filtered = store.candidates(conn, probe, 10)
        assert [(m, s) for m, s, _, _ in filtered] == [("keep", "s-kiro_cli")]
        # And the doctor sees the retired-source row as hidden until the next sweep.
        assert align.alignment_report(conn, model="fake-model", dim=DIM).hidden == 1
