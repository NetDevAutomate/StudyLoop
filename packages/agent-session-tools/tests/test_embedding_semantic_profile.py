"""Semantic profile: the real model and the real ``vec0`` index on the toy corpus.

The unit tier (``test_embedding_store.py``) proves the mechanics against a fake
encoder. This file proves the substrate works with the thing it was built for:
``all-MiniLM-L6-v2`` writing real 384-dimensional vectors into
``message_embeddings``, reconciled into a sidecar ``vec0`` table, queried by
KNN. It runs in the ``semantic`` CI profile only (``just test-semantic``), and
skips rather than fails when the optional dependencies are absent.

The toy corpus is the same public stand-in the Stage 2 rulers use, so nothing
here touches the learner's private database.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("sentence_transformers", reason="install the [semantic] extra")
pytest.importorskip("sqlite_vec", reason="install the [semantic] extra")

from agent_session_tools import embedding_alignment as align  # noqa: E402
from agent_session_tools import embedding_store as store  # noqa: E402
from agent_session_tools.eval.toy_corpus import build_toy_corpus  # noqa: E402

MODEL = "all-MiniLM-L6-v2"
DIM = 384

#: A session whose source is retired AFTER it was embedded (D-6). Its learner
#: turn paraphrases toy-01 closely, so KNN will rank it near that session's
#: vectors -- which is the point: it must be found and never returned.
RETIRED_SESSION = "retired-01"
RETIRED_MESSAGE = "retired-01-m1"
RETIRED_TEXT = "Why does the tmux server drop its socket once the laptop has been asleep for a while?"


@pytest.fixture(scope="module")
def encoder() -> store.Encoder:
    """The real model, loaded once for the module (``get_model`` caches it anyway)."""
    return store.SentenceTransformerEncoder(MODEL)


@pytest.fixture
def corpus(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, Path]]:
    """The toy corpus plus one extra session that will be retired mid-test."""
    toy = build_toy_corpus(tmp_path / "toy")
    conn = sqlite3.connect(toy.db_path)
    conn.execute(
        "INSERT INTO sessions(id, source, project_path, created_at, updated_at, session_type) "
        "VALUES (?,?,?,?,?,?)",
        (
            RETIRED_SESSION,
            "kiro_cli",  # admitted at embed time; retired below
            "/projects/retired-01",
            "2026-02-01T09:00:00",
            "2026-02-01T09:30:00",
            "work",
        ),
    )
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content, timestamp, seq) VALUES (?,?,?,?,?,?)",
        (
            RETIRED_MESSAGE,
            RETIRED_SESSION,
            "user",
            RETIRED_TEXT,
            "2026-02-01T09:01:00",
            1,
        ),
    )
    conn.commit()
    yield conn, toy.db_path
    conn.close()


def _visible_ids(conn: sqlite3.Connection, message_ids: list[str]) -> set[str]:
    """The subset of ``message_ids`` a product read is allowed to return (D-6).

    This is the join Stage 4's fusion does inside ``retrieval.search``: the raw
    KNN candidates, filtered by the *same* predicate the lexical arm uses.
    """
    if not message_ids:
        return set()
    predicate, params = align.eligible_predicate()
    placeholders = ",".join("?" for _ in message_ids)
    rows = conn.execute(
        f"SELECT m.id FROM messages m JOIN sessions s ON s.id = m.session_id "
        f"WHERE {predicate} AND m.id IN ({placeholders})",
        [*params, *message_ids],
    ).fetchall()
    return {row[0] for row in rows}


def test_the_real_model_embeds_the_toy_corpus_into_an_aligned_reconciled_index(
    corpus: tuple[sqlite3.Connection, Path],
    encoder: store.Encoder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn, db_path = corpus

    stats = store.embed(conn, encoder=encoder, batch_size=32)

    # --- the record ---------------------------------------------------------
    assert stats.model == MODEL and stats.dim == DIM
    assert (
        stats.embedded_messages > 0 and stats.chunks_written >= stats.embedded_messages
    )
    assert stats.skipped_changed == 0 and stats.remaining == 0
    report = align.alignment_report(conn, model=MODEL, dim=DIM)
    assert report.complete, report.to_dict()
    assert report.rows == stats.chunks_written
    lengths = {
        length
        for (length,) in conn.execute(
            "SELECT DISTINCT length(embedding) FROM message_embeddings"
        )
    }
    assert lengths == {DIM * 4}, "float32 little-endian, one vector per chunk"

    # --- the derived index --------------------------------------------------
    inserted, deleted = store.reconcile(conn)
    assert (inserted, deleted) == (stats.chunks_written, 0)
    assert store.sidecar_path(db_path).exists()
    vec_rows = conn.execute("SELECT COUNT(*) FROM vec.message_vec").fetchone()[0]
    assert vec_rows == report.rows
    assert store.reconcile(conn) == (0, 0), "a second pass has nothing to do"

    # --- KNN finds a chunk's own vector first -------------------------------
    own_key, own_vector = conn.execute(
        "SELECT message_id, embedding FROM message_embeddings "
        "WHERE message_id LIKE 'toy-01%' ORDER BY chunk_ix LIMIT 1"
    ).fetchone()
    hits = store.knn(conn, own_vector, 5)
    assert hits[0][0] == own_key
    assert hits[0][2] == pytest.approx(0.0, abs=1e-4)
    assert len(hits) == 5
    distances = [distance for *_rest, distance in hits]
    assert distances == sorted(distances), "vec0 returns candidates nearest first"

    # Report the measured cost of the whole corpus for the stage receipt.
    with capsys.disabled():
        print(
            f"\n[receipt] {MODEL}: {stats.embedded_messages} messages / "
            f"{stats.chunks_written} chunks in {stats.seconds:.2f}s "
            f"({stats.truncated_chunks} hard-windowed), sidecar "
            f"{store.sidecar_path(db_path).stat().st_size / 1024:.0f} KiB"
        )


def test_a_source_retired_after_embedding_is_found_by_knn_and_never_returned(
    corpus: tuple[sqlite3.Connection, Path],
    encoder: store.Encoder,
) -> None:
    """D-6: the index holds raw candidates; the read predicate is what filters."""
    conn, _ = corpus
    store.embed(conn, encoder=encoder, batch_size=32)
    assert align.alignment_report(conn, model=MODEL, dim=DIM).complete

    # The source is retired now, after the vectors were written.
    conn.execute("UPDATE sessions SET source='aider' WHERE id=?", (RETIRED_SESSION,))
    conn.commit()
    hidden_report = align.alignment_report(conn, model=MODEL, dim=DIM)
    assert hidden_report.hidden >= 1 and not hidden_report.aligned

    store.reconcile(conn)
    retired_vector = conn.execute(
        "SELECT embedding FROM message_embeddings WHERE message_id=?",
        (RETIRED_MESSAGE,),
    ).fetchone()[0]

    candidates = store.knn(conn, retired_vector, 10)
    candidate_ids = [message_id for message_id, _ix, _d in candidates]
    assert candidate_ids[0] == RETIRED_MESSAGE, (
        "the raw index does hold the hidden vector"
    )

    visible = _visible_ids(conn, candidate_ids)
    assert RETIRED_MESSAGE not in visible, "the read predicate drops the retired source"
    assert visible, "the visible neighbours still come through"
    assert "toy-01-m1" in candidate_ids, (
        "the paraphrase ranks near the session it paraphrases"
    )

    # The sweep is the repair: the hidden rows go, and the index follows.
    swept = align.sweep(conn, model=MODEL, dim=DIM)
    conn.commit()
    assert swept.hidden >= 1
    _inserted, deleted = store.reconcile(conn)
    assert deleted >= 1
    assert align.alignment_report(conn, model=MODEL, dim=DIM).aligned
    assert not conn.execute(
        "SELECT 1 FROM vec.message_vec WHERE chunk_key LIKE ?",
        (f"{RETIRED_MESSAGE}#%",),
    ).fetchone()
