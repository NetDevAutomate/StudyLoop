"""Hybrid retrieval (Stage 4): the semantic arm fused into the lexical service.

The encoder here is scripted: named texts get named vectors, everything else
gets a hash vector, so "the paraphrase is near the answer" is something a
test states literally rather than hopes a real model produces.
"""

from __future__ import annotations

import sqlite3
import struct
from importlib.resources import files
from pathlib import Path

import pytest

from agent_session_tools import embedding_store as store
from agent_session_tools import retrieval
from agent_session_tools.migrations import migrate

pytest.importorskip("sqlite_vec")

DIM = 4
LONG_TAIL = " -- padded so the message is long enough to be eligible for embedding"

AXES = {
    "north": (1.0, 0.0, 0.0, 0.0),
    "east": (0.0, 1.0, 0.0, 0.0),
    "south": (0.0, 0.0, 1.0, 0.0),
    "west": (0.0, 0.0, 0.0, 1.0),
}


class ScriptedEncoder:
    """``scripts`` maps a text to an axis name; unscripted text hashes to a vector."""

    name = "scripted-model"
    dim = DIM
    max_tokens = 64

    def __init__(self, scripts: dict[str, str]) -> None:
        self.scripts = scripts

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode(self, texts):  # noqa: ANN001 - Protocol shape
        out: list[bytes] = []
        for text in texts:
            axis = self.scripts.get(text)
            if axis is not None:
                out.append(struct.pack(f"<{DIM}f", *AXES[axis]))
                continue
            seed = sum((i + 1) * ord(c) for i, c in enumerate(text)) or 1
            raw = [((seed >> (3 * k)) % 97) + 1 for k in range(DIM)]
            norm = sum(v * v for v in raw) ** 0.5
            out.append(struct.pack(f"<{DIM}f", *[v / norm for v in raw]))
        return out


ANSWER = (
    "use a window function with PARTITION BY to rank rows inside each group" + LONG_TAIL
)
DECOY = (
    "the deployment pipeline failed because the docker image tag was wrong" + LONG_TAIL
)
HIDDEN = "ranking rows per group is exactly what window functions are for" + LONG_TAIL
PARAPHRASE = "numbering a customer's records separately within the result set"


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "sessions.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    conn.execute(
        "INSERT INTO sessions(id, source, updated_at) VALUES ('s-a', 'kiro_cli', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO sessions(id, source, updated_at) VALUES ('s-b', 'codex', '2026-09-02')"
    )
    conn.execute(
        "INSERT INTO sessions(id, source, updated_at) VALUES ('s-h', 'legacy_tool', '2026-09-03')"
    )
    rows = [
        ("answer", "s-a", "assistant", ANSWER, "2026-09-01T10:00:00"),
        ("decoy", "s-b", "assistant", DECOY, "2026-09-02T10:00:00"),
        ("hidden", "s-h", "assistant", HIDDEN, "2026-09-03T10:00:00"),
    ]
    conn.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, seq) VALUES (?,?,?,?,?,1)",
        rows,
    )
    conn.commit()
    return conn


def _embedded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """A database whose vectors put the paraphrase on the answer's axis and nothing else's."""
    conn = _db(tmp_path)
    encoder = ScriptedEncoder(
        {
            ANSWER: "north",
            HIDDEN: "north",  # a retired-source session that is semantically perfect
            DECOY: "east",
            retrieval.QUERY_PREFIXES.get("scripted-model", "") + PARAPHRASE: "north",
        }
    )
    stats = store.embed(conn, encoder=encoder)
    assert stats.embedded_messages == 2, "the hidden session is never embedded"
    store.reconcile(conn)
    monkeypatch.setitem(retrieval._ENCODERS, "scripted-model", encoder)
    monkeypatch.setattr(
        store,
        "availability",
        lambda model=None: store.Availability(True, True, True, "ready"),
    )
    return conn


class TestModeResolution:
    def test_argument_beats_environment_beats_config(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv(retrieval.MODE_ENV, raising=False)
        monkeypatch.setattr(
            "agent_session_tools.config_loader.get_semantic_config",
            lambda: {"hybrid": False},
        )
        assert retrieval.resolve_mode() == "lexical"
        monkeypatch.setattr(
            "agent_session_tools.config_loader.get_semantic_config",
            lambda: {"hybrid": True},
        )
        assert retrieval.resolve_mode() == "hybrid"
        monkeypatch.setenv(retrieval.MODE_ENV, "lexical")
        assert retrieval.resolve_mode() == "lexical"
        assert retrieval.resolve_mode("hybrid") == "hybrid"

    def test_unknown_mode_is_a_caller_error(self):
        with pytest.raises(ValueError, match="unknown retrieval mode"):
            retrieval.resolve_mode("vibes")


class TestDegradation:
    def test_hybrid_without_vectors_is_lexical_and_says_so(self, tmp_path: Path):
        conn = _db(tmp_path)
        result = retrieval.search(conn, "docker image tag", mode="hybrid")
        assert result.status.mode == "lexical"
        assert result.status.semantic is None
        assert "hybrid requested but lexical only: no vectors" in (
            result.status.note or ""
        )
        assert [h.message_id for h in result.hits] == ["decoy"]

    def test_lexical_mode_never_touches_the_semantic_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        conn = _embedded(tmp_path, monkeypatch)
        monkeypatch.setattr(
            retrieval,
            "_semantic_ranking",
            lambda *a, **k: pytest.fail("semantic arm ran"),
        )
        result = retrieval.search(conn, PARAPHRASE, mode="lexical")
        assert result.status.mode == "lexical" and result.status.note is None

    def test_explicit_syntax_stays_lexical_in_hybrid_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        conn = _embedded(tmp_path, monkeypatch)
        result = retrieval.search(conn, "fts:docker OR window", mode="hybrid")
        assert result.status.mode == "lexical" and result.status.plan == "explicit"
        assert "explicit FTS5 syntax is searched lexically" in (
            result.status.note or ""
        )
        assert {h.message_id for h in result.hits} == {"decoy", "answer"}


class TestHybrid:
    def test_a_paraphrase_with_no_shared_word_is_found_by_the_semantic_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        conn = _embedded(tmp_path, monkeypatch)
        lexical = retrieval.search(conn, PARAPHRASE, mode="lexical")
        assert lexical.hits == (), "lexically the paraphrase finds nothing"
        hybrid = retrieval.search(conn, PARAPHRASE, mode="hybrid")
        assert hybrid.status.mode == "hybrid"
        assert [h.message_id for h in hybrid.hits][0] == "answer"
        assert "hidden" not in {h.message_id for h in hybrid.hits}
        assert hybrid.status.semantic is not None
        assert hybrid.status.semantic["model"] == "scripted-model"
        assert hybrid.status.semantic["semantic_only_in_result"] >= 1
        assert hybrid.status.plan in ("and", "or")  # the lexical plan is still reported

    def test_hidden_sessions_are_never_returned_even_when_semantically_perfect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        conn = _embedded(tmp_path, monkeypatch)
        # Force a vector for the hidden message into the table and the sidecar as if
        # it had been admitted once, then retired: the filters must still drop it.
        row = conn.execute(
            "SELECT embedding, content_sha256, model, dim FROM message_embeddings "
            "WHERE message_id='answer'"
        ).fetchone()
        conn.execute(
            "INSERT INTO message_embeddings(message_id, chunk_ix, model, dim, content_sha256, "
            "truncated, embedding, created_at) VALUES ('hidden', 0, ?, ?, ?, 0, ?, '2026-09-03')",
            (row["model"], row["dim"], store.content_sha256(HIDDEN), row["embedding"]),
        )
        conn.commit()
        store.reconcile(conn)
        assert store.knn(conn, row["embedding"], 5)[0][0] in {"answer", "hidden"}
        hybrid = retrieval.search(conn, PARAPHRASE, mode="hybrid")
        assert "hidden" not in {h.message_id for h in hybrid.hits}
        assert "s-h" not in {h.session_id for h in hybrid.hits}

    def test_exclusions_and_filters_bind_the_semantic_arm_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        conn = _embedded(tmp_path, monkeypatch)
        excluded = retrieval.search(
            conn, PARAPHRASE, mode="hybrid", exclude_message_ids=("answer",)
        )
        assert "answer" not in {h.message_id for h in excluded.hits}
        other_source = retrieval.search(conn, PARAPHRASE, mode="hybrid", source="codex")
        assert {h.session_id for h in other_source.hits} <= {"s-b"}

    def test_semantic_status_counts_are_consistent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        conn = _embedded(tmp_path, monkeypatch)
        hybrid = retrieval.search(conn, PARAPHRASE, mode="hybrid", limit=1)
        assert len(hybrid.hits) == 1
        info = hybrid.status.semantic
        assert info is not None
        assert info["after_filters"] <= info["candidates"] <= retrieval.FUSION_DEPTH
        assert info["model"] == "scripted-model"


class TestFusion:
    def _hit(
        self, message_id: str, timestamp: str = "2026-01-01T00:00:00"
    ) -> retrieval.RetrievalHit:
        return retrieval.RetrievalHit(
            message_id=message_id,
            session_id=f"s-{message_id}",
            source="kiro_cli",
            project_path=None,
            updated_at=None,
            role="user",
            timestamp=timestamp,
            preview="",
            rank=0.0,
        )

    def test_rrf_scores_and_tie_breaks_as_pre_registered(self):
        lexical = [self._hit("both"), self._hit("lex-only")]
        semantic_ids = ["sem-only", "both"]
        rows = {m: self._hit(m) for m in semantic_ids}
        fused, semantic_only = retrieval._fuse(lexical, semantic_ids, rows, limit=10)
        ids = [h.message_id for h in fused]
        assert ids[0] == "both", "present in both arms wins"
        # lex-only: rank 2 lexical -> 1/62; sem-only: rank 1 semantic -> 1/61 -> sem-only first
        assert ids[1:] == ["sem-only", "lex-only"]
        assert semantic_only == 1
        assert fused[0].rank == pytest.approx(-(1 / 61 + 1 / 62))

    def test_a_candidate_dropped_by_the_filters_is_not_scored(self):
        lexical = [self._hit("a")]
        fused, semantic_only = retrieval._fuse(
            lexical, ["dropped", "a"], {"a": lexical[0]}, limit=10
        )
        assert [h.message_id for h in fused] == ["a"] and semantic_only == 0

    def test_an_exact_tie_goes_to_the_lexical_arm(self):
        """Lexical rank 1 and semantic rank 1 score the same; lexical presence breaks it."""
        old, new = (
            self._hit("old", "2026-01-01T00:00:00"),
            self._hit("new", "2026-06-01T00:00:00"),
        )
        fused, _ = retrieval._fuse([old], ["new"], {"new": new}, limit=10)
        assert [h.message_id for h in fused] == ["old", "new"]
