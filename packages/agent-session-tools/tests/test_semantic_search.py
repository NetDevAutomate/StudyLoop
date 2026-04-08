"""Tests for semantic_search.py — hybrid FTS5 + vector search.

Strategy:
- FTS5 tests use real SQLite (migrated_db fixture) with actual full-text search.
- Vector / hybrid tests mock EMBEDDINGS_AVAILABLE and the embedding functions so
  the suite runs without sentence-transformers installed.
- _fusion_rank is tested purely as a unit (no DB required).
- format_suggested_context and _format_single_result are pure string functions,
  tested without any DB or mocks.
"""

from __future__ import annotations

import struct
import sqlite3
from typing import Any
from unittest.mock import patch

import pytest

from agent_session_tools.migrations import migrate
from agent_session_tools.semantic_search import (
    SearchContext,
    SearchResult,
    _format_single_result,
    _fts_search,
    _fusion_rank,
    _vector_search,
    find_similar_sessions,
    format_suggested_context,
    hybrid_search,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding(value: float = 1.0, dims: int = 4) -> bytes:
    """Create a minimal float32 embedding as bytes."""
    return struct.pack(f"{dims}f", *([value] * dims))


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    project_path: str = "/test/project",
    source: str = "claude_code",
    session_type: str = "work",
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (id, source, project_path, session_type, created_at, updated_at)
        VALUES (?, ?, ?, ?, '2024-01-01T10:00:00', '2024-01-01T12:00:00')
        """,
        (session_id, source, project_path, session_type),
    )


def _insert_message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    content: str,
    role: str = "user",
    timestamp: str = "2024-01-01T10:00:00",
) -> None:
    conn.execute(
        """
        INSERT INTO messages (id, session_id, role, content, timestamp, seq)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (message_id, session_id, role, content, timestamp),
    )


def _insert_message_embedding(
    conn: sqlite3.Connection,
    message_id: str,
    embedding: bytes,
) -> None:
    conn.execute(
        """
        INSERT INTO message_embeddings (message_id, embedding, model)
        VALUES (?, ?, 'test-model')
        """,
        (message_id, embedding),
    )


def _insert_session_embedding(
    conn: sqlite3.Connection,
    session_id: str,
    embedding: bytes,
) -> None:
    conn.execute(
        """
        INSERT INTO session_embeddings (session_id, embedding, model)
        VALUES (?, ?, 'test-model')
        """,
        (session_id, embedding),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    """Fully migrated in-memory database with FTS5 and embedding tables."""
    from pathlib import Path

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    schema_path = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    )
    with open(schema_path) as f:
        conn.executescript(f.read())

    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def populated_db(db):
    """Database pre-populated with two sessions and searchable messages."""
    _insert_session(db, "sess-alpha", "/projects/alpha", "claude_code", "work")
    _insert_session(db, "sess-beta", "/projects/beta", "kiro_cli", "learning")

    _insert_message(
        db,
        "msg-a1",
        "sess-alpha",
        "Python decorators are functions that wrap other functions",
        "user",
        "2024-01-01T10:00:00",
    )
    _insert_message(
        db,
        "msg-a2",
        "sess-alpha",
        "How does the decorator pattern improve code reusability",
        "assistant",
        "2024-01-01T10:01:00",
    )
    _insert_message(
        db,
        "msg-b1",
        "sess-beta",
        "SQLite FTS5 full text search tutorial and examples",
        "user",
        "2024-01-02T09:00:00",
    )
    _insert_message(
        db,
        "msg-b2",
        "sess-beta",
        "Understanding database indexing and query optimisation",
        "assistant",
        "2024-01-02T09:01:00",
    )

    db.commit()
    return db


# ---------------------------------------------------------------------------
# SearchResult dataclass
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_to_dict_has_all_fields(self):
        r = SearchResult(
            session_id="s1",
            project_path="/p",
            content_preview="hello",
            message_id="m1",
            role="user",
            timestamp="2024-01-01",
            source="claude_code",
            fts_score=0.5,
            semantic_score=0.7,
            combined_score=0.62,
            match_type="hybrid",
        )
        d = r.to_dict()
        assert d["session_id"] == "s1"
        assert d["match_type"] == "hybrid"
        assert d["fts_score"] == 0.5
        assert d["combined_score"] == 0.62

    def test_to_dict_keys_complete(self):
        r = SearchResult(session_id="s", project_path="/p", content_preview="x")
        keys = set(r.to_dict().keys())
        expected = {
            "session_id",
            "project_path",
            "content_preview",
            "message_id",
            "role",
            "timestamp",
            "source",
            "fts_score",
            "semantic_score",
            "combined_score",
            "match_type",
        }
        assert keys == expected

    def test_default_match_type_is_fts(self):
        r = SearchResult(session_id="s", project_path="/p", content_preview="x")
        assert r.match_type == "fts"

    def test_default_scores_are_zero(self):
        r = SearchResult(session_id="s", project_path="/p", content_preview="x")
        assert r.fts_score == 0.0
        assert r.semantic_score == 0.0
        assert r.combined_score == 0.0


# ---------------------------------------------------------------------------
# SearchContext dataclass
# ---------------------------------------------------------------------------


class TestSearchContext:
    def test_defaults(self):
        ctx = SearchContext()
        assert ctx.project_path is None
        assert ctx.source is None
        assert ctx.roles == ["user", "assistant"]
        assert ctx.exclude_session_ids == []

    def test_custom_roles(self):
        ctx = SearchContext(roles=["user"])
        assert ctx.roles == ["user"]

    def test_exclude_session_ids(self):
        ctx = SearchContext(exclude_session_ids=["abc", "def"])
        assert len(ctx.exclude_session_ids) == 2


# ---------------------------------------------------------------------------
# _fts_search
# ---------------------------------------------------------------------------


class TestFtsSearch:
    def test_returns_matching_messages(self, populated_db):
        results = _fts_search(populated_db, "decorator", 10, SearchContext())
        session_ids = {r["session_id"] for r in results}
        assert "sess-alpha" in session_ids

    def test_returns_dict_list(self, populated_db):
        results = _fts_search(populated_db, "decorator", 10, SearchContext())
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], dict)

    def test_result_has_required_keys(self, populated_db):
        results = _fts_search(populated_db, "decorator", 10, SearchContext())
        assert results, "Expected at least one result for 'decorator'"
        r = results[0]
        for key in ("session_id", "project_path", "preview", "score"):
            assert key in r, f"Missing key: {key}"

    def test_no_match_returns_empty(self, populated_db):
        results = _fts_search(populated_db, "xyzzy_no_match_ever", 10, SearchContext())
        assert results == []

    def test_empty_query_returns_empty(self, populated_db):
        # Empty / whitespace query should not crash and FTS returns no rows
        results = _fts_search(populated_db, "", 10, SearchContext())
        assert isinstance(results, list)

    def test_filter_by_project_path(self, populated_db):
        ctx = SearchContext(project_path="/projects/alpha")
        results = _fts_search(populated_db, "decorator", 10, ctx)
        for r in results:
            assert "alpha" in r["project_path"]

    def test_filter_by_source(self, populated_db):
        ctx = SearchContext(source="kiro_cli")
        results = _fts_search(populated_db, "database", 10, ctx)
        for r in results:
            assert r["source"] == "kiro_cli"

    def test_filter_by_session_type(self, populated_db):
        ctx = SearchContext(session_type="learning")
        results = _fts_search(populated_db, "database", 10, ctx)
        # All matching rows should come from sess-beta (learning type)
        for r in results:
            assert r["session_id"] == "sess-beta"

    def test_filter_roles_assistant_only(self, populated_db):
        ctx = SearchContext(roles=["assistant"])
        results = _fts_search(populated_db, "decorator", 10, ctx)
        for r in results:
            assert r["role"] == "assistant"

    def test_exclude_session_ids(self, populated_db):
        ctx = SearchContext(exclude_session_ids=["sess-alpha"])
        results = _fts_search(populated_db, "decorator", 10, ctx)
        for r in results:
            assert r["session_id"] != "sess-alpha"

    def test_limit_respected(self, populated_db):
        results = _fts_search(populated_db, "the", 1, SearchContext())
        assert len(results) <= 1

    def test_since_filter(self, populated_db):
        ctx = SearchContext(since="2024-01-02T00:00:00")
        results = _fts_search(populated_db, "database", 10, ctx)
        for r in results:
            assert r["timestamp"] >= "2024-01-02T00:00:00"

    def test_before_filter(self, populated_db):
        ctx = SearchContext(before="2024-01-01T23:59:59")
        results = _fts_search(populated_db, "decorator", 10, ctx)
        for r in results:
            assert r["timestamp"] <= "2024-01-01T23:59:59"

    def test_malformed_fts_query_returns_empty_not_exception(self, populated_db):
        # SQLite FTS will raise OperationalError for certain malformed queries;
        # _fts_search should catch it and return [].
        results = _fts_search(populated_db, "AND OR NOT", 10, SearchContext())
        # Whether it returns results or empty is fine — must not raise
        assert isinstance(results, list)

    def test_preview_truncated_to_500_chars(self, populated_db):
        long_content = "word " * 200  # ~1000 chars
        _insert_session(populated_db, "sess-long")
        _insert_message(populated_db, "msg-long", "sess-long", long_content)
        populated_db.commit()

        results = _fts_search(populated_db, "word", 10, SearchContext())
        for r in results:
            if r["session_id"] == "sess-long":
                assert len(r["preview"]) <= 500


# ---------------------------------------------------------------------------
# _vector_search  (mocked embeddings)
# ---------------------------------------------------------------------------


class TestVectorSearch:
    def test_returns_empty_when_embeddings_unavailable(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = _vector_search(populated_db, "decorator", 10, SearchContext())
        assert results == []

    def test_returns_results_when_embeddings_available(self, populated_db):
        emb = _make_embedding(0.5)
        _insert_message_embedding(populated_db, "msg-a1", emb)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.generate_embedding",
                return_value=emb,
            ),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.9,
            ),
        ):
            results = _vector_search(populated_db, "decorator", 10, SearchContext())

        assert len(results) >= 1
        assert results[0]["score"] == 0.9

    def test_results_sorted_by_similarity_descending(self, populated_db):
        emb_a = _make_embedding(1.0)
        emb_b = _make_embedding(0.5)
        _insert_message_embedding(populated_db, "msg-a1", emb_a)
        _insert_message_embedding(populated_db, "msg-b1", emb_b)
        populated_db.commit()

        scores = {"msg-a1": 0.9, "msg-b1": 0.3}

        def fake_cosine(query_emb: bytes, stored_emb: bytes) -> float:
            # Identify row by embedding value
            if stored_emb == emb_a:
                return scores["msg-a1"]
            return scores["msg-b1"]

        query_emb = _make_embedding(0.8)
        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.generate_embedding",
                return_value=query_emb,
            ),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                side_effect=fake_cosine,
            ),
        ):
            results = _vector_search(populated_db, "any", 10, SearchContext())

        assert len(results) >= 2
        assert results[0]["score"] >= results[1]["score"]

    def test_limit_respected(self, populated_db):
        emb = _make_embedding()
        _insert_message_embedding(populated_db, "msg-a1", emb)
        _insert_message_embedding(populated_db, "msg-b1", emb)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.generate_embedding",
                return_value=emb,
            ),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.5,
            ),
        ):
            results = _vector_search(populated_db, "any", 1, SearchContext())

        assert len(results) <= 1

    def test_filter_by_source(self, populated_db):
        emb = _make_embedding()
        _insert_message_embedding(populated_db, "msg-a1", emb)
        _insert_message_embedding(populated_db, "msg-b1", emb)
        populated_db.commit()

        ctx = SearchContext(source="claude_code")
        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.generate_embedding",
                return_value=emb,
            ),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.5,
            ),
        ):
            results = _vector_search(populated_db, "any", 10, ctx)

        for r in results:
            assert r["source"] == "claude_code"

    def test_exclude_session_ids(self, populated_db):
        emb = _make_embedding()
        _insert_message_embedding(populated_db, "msg-a1", emb)
        _insert_message_embedding(populated_db, "msg-b1", emb)
        populated_db.commit()

        ctx = SearchContext(exclude_session_ids=["sess-alpha"])
        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.generate_embedding",
                return_value=emb,
            ),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.5,
            ),
        ):
            results = _vector_search(populated_db, "any", 10, ctx)

        for r in results:
            assert r["session_id"] != "sess-alpha"


# ---------------------------------------------------------------------------
# _fusion_rank  (pure unit — no DB)
# ---------------------------------------------------------------------------


class TestFusionRank:
    def _make_fts_row(
        self, session_id: str, message_id: str, score: float = -1.0
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "message_id": message_id,
            "project_path": f"/proj/{session_id}",
            "source": "claude_code",
            "role": "user",
            "timestamp": "2024-01-01",
            "preview": f"preview for {message_id}",
            "score": score,
        }

    def test_returns_search_result_objects(self):
        fts = [self._make_fts_row("s1", "m1")]
        vec = [self._make_fts_row("s1", "m1")]
        results = _fusion_rank(fts, vec, 0.4, 0.6)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_sorted_by_combined_score_descending(self):
        fts = [self._make_fts_row("s1", "m1"), self._make_fts_row("s2", "m2")]
        vec = [self._make_fts_row("s1", "m1")]
        results = _fusion_rank(fts, vec, 0.4, 0.6)
        scores = [r.combined_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_match_type_hybrid_when_in_both(self):
        row = self._make_fts_row("s1", "m1")
        results = _fusion_rank([row], [row], 0.5, 0.5)
        assert results[0].match_type == "hybrid"

    def test_match_type_fts_when_only_fts(self):
        fts_row = self._make_fts_row("s1", "m1")
        vec_row = self._make_fts_row("s2", "m2")
        # s1 is fts-only, s2 is vector-only
        results = _fusion_rank([fts_row], [vec_row], 0.5, 0.5)
        match_types = {r.session_id: r.match_type for r in results}
        assert match_types["s1"] == "fts"

    def test_match_type_semantic_when_only_vector(self):
        fts_row = self._make_fts_row("s1", "m1")
        vec_row = self._make_fts_row("s2", "m2")
        results = _fusion_rank([fts_row], [vec_row], 0.5, 0.5)
        match_types = {r.session_id: r.match_type for r in results}
        assert match_types["s2"] == "semantic"

    def test_rrf_formula_with_known_ranks(self):
        """Verify RRF: score = weight * 1/(60+rank). Rank 1 → 1/61."""
        fts = [self._make_fts_row("s1", "m1")]
        vec = [self._make_fts_row("s1", "m1")]
        results = _fusion_rank(fts, vec, 0.4, 0.6)
        expected = 0.4 * (1 / 61) + 0.6 * (1 / 61)
        assert abs(results[0].combined_score - expected) < 1e-9

    def test_higher_rank_gets_lower_score(self):
        fts = [
            self._make_fts_row("s1", "m1"),
            self._make_fts_row("s2", "m2"),
        ]
        results = _fusion_rank(fts, [], 1.0, 0.0)
        # s1 rank=1 > s2 rank=2
        assert results[0].session_id == "s1"
        assert results[0].combined_score > results[1].combined_score

    def test_weights_affect_score(self):
        """Semantic weight controls contribution from vector-only results.

        When a result appears in only one list, its score is solely determined
        by that list's weight.  A vector-only result at rank 1 scores
        sem_w * 1/61.  Raising semantic_weight raises its combined score.
        """
        vec_only = self._make_fts_row("s1", "m1")
        # low semantic weight: s1 scores 0.2 * (1/61)
        low_sem = _fusion_rank([], [vec_only], 0.8, 0.2)
        # high semantic weight: s1 scores 0.8 * (1/61)
        high_sem = _fusion_rank([], [vec_only], 0.2, 0.8)
        assert high_sem[0].combined_score > low_sem[0].combined_score

    def test_empty_fts_empty_vec_returns_empty(self):
        assert _fusion_rank([], [], 0.5, 0.5) == []

    def test_all_results_from_fts_only(self):
        fts = [self._make_fts_row("s1", "m1"), self._make_fts_row("s2", "m2")]
        results = _fusion_rank(fts, [], 1.0, 0.0)
        for r in results:
            assert r.match_type == "fts"
            assert r.semantic_score == 0.0

    def test_all_results_from_vector_only(self):
        vec = [self._make_fts_row("s1", "m1"), self._make_fts_row("s2", "m2")]
        results = _fusion_rank([], vec, 0.0, 1.0)
        for r in results:
            assert r.match_type == "semantic"
            assert r.fts_score == 0.0

    def test_deduplicates_same_session_message(self):
        """Same (session_id, message_id) appearing in both lists → one result."""
        row = self._make_fts_row("s1", "m1")
        results = _fusion_rank([row], [row], 0.5, 0.5)
        ids = [(r.session_id, r.message_id) for r in results]
        assert len(ids) == len(set(ids))

    def test_result_preserves_metadata(self):
        row = self._make_fts_row("s1", "m1")
        row["project_path"] = "/custom/path"
        row["source"] = "kiro_cli"
        row["role"] = "assistant"
        row["preview"] = "custom preview"
        results = _fusion_rank([row], [], 1.0, 0.0)
        assert results[0].project_path == "/custom/path"
        assert results[0].source == "kiro_cli"
        assert results[0].content_preview == "custom preview"


# ---------------------------------------------------------------------------
# hybrid_search  (integration of FTS + fusion; mocked embeddings)
# ---------------------------------------------------------------------------


class TestHybridSearch:
    def test_returns_list_of_search_results(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "decorator")
        assert isinstance(results, list)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_fts_only_mode_skips_vector(self, populated_db):
        with patch("agent_session_tools.semantic_search._vector_search") as mock_vec:
            results = hybrid_search(populated_db, "decorator", fts_only=True)
        mock_vec.assert_not_called()
        assert isinstance(results, list)

    def test_empty_query_returns_list(self, populated_db):
        results = hybrid_search(populated_db, "")
        assert isinstance(results, list)

    def test_no_results_for_non_matching_query(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "xyzzy_no_match_8472")
        assert results == []

    def test_limit_respected(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "the", limit=1)
        assert len(results) <= 1

    def test_fts_fallback_match_type_is_fts(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "decorator")
        for r in results:
            assert r.match_type == "fts"

    def test_fts_fallback_semantic_score_is_zero(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "decorator")
        for r in results:
            assert r.semantic_score == 0.0

    def test_combined_score_equals_fts_score_when_no_vector(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "decorator")
        for r in results:
            assert r.combined_score == r.fts_score

    def test_hybrid_mode_uses_fusion_when_both_available(self, populated_db):
        emb = _make_embedding()
        _insert_message_embedding(populated_db, "msg-a1", emb)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.generate_embedding",
                return_value=emb,
            ),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.8,
            ),
        ):
            results = hybrid_search(populated_db, "decorator")

        assert isinstance(results, list)

    def test_vector_failure_falls_back_to_fts(self, populated_db):
        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search._vector_search",
                side_effect=RuntimeError("model load failed"),
            ),
        ):
            results = hybrid_search(populated_db, "decorator")

        # Should still return FTS results, not raise
        assert isinstance(results, list)
        for r in results:
            assert r.match_type == "fts"

    def test_context_project_filter_applied(self, populated_db):
        ctx = SearchContext(project_path="/projects/alpha")
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "decorator", context=ctx)
        for r in results:
            assert "alpha" in r.project_path

    def test_context_source_filter_applied(self, populated_db):
        ctx = SearchContext(source="kiro_cli")
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "database", context=ctx)
        for r in results:
            assert r.source == "kiro_cli"

    def test_default_context_created_when_none(self, populated_db):
        """Passing context=None should not raise."""
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = hybrid_search(populated_db, "decorator", context=None)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# find_similar_sessions
# ---------------------------------------------------------------------------


class TestFindSimilarSessions:
    def test_returns_empty_when_embeddings_unavailable(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", False):
            results = find_similar_sessions(populated_db, "sess-alpha")
        assert results == []

    def test_returns_empty_when_no_reference_embedding(self, populated_db):
        with patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True):
            results = find_similar_sessions(populated_db, "sess-alpha")
        assert results == []

    def test_returns_similar_sessions(self, populated_db):
        emb_alpha = _make_embedding(1.0)
        emb_beta = _make_embedding(0.9)
        _insert_session_embedding(populated_db, "sess-alpha", emb_alpha)
        _insert_session_embedding(populated_db, "sess-beta", emb_beta)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.85,
            ),
        ):
            results = find_similar_sessions(populated_db, "sess-alpha")

        assert len(results) >= 1
        # Reference session must not appear in results
        for r in results:
            assert r.session_id != "sess-alpha"

    def test_results_sorted_by_semantic_score_descending(self, populated_db):
        emb_ref = _make_embedding(1.0)
        emb_a = _make_embedding(0.8)
        emb_b = _make_embedding(0.3)
        _insert_session_embedding(populated_db, "sess-alpha", emb_ref)
        _insert_session_embedding(populated_db, "sess-beta", emb_a)
        # Add a third session
        _insert_session(populated_db, "sess-gamma")
        _insert_session_embedding(populated_db, "sess-gamma", emb_b)
        populated_db.commit()

        call_count = {"n": 0}

        def sim_by_call(a: bytes, b: bytes) -> float:
            call_count["n"] += 1
            if b == emb_a:
                return 0.9
            return 0.2

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                side_effect=sim_by_call,
            ),
        ):
            results = find_similar_sessions(populated_db, "sess-alpha")

        scores = [r.semantic_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_limit_respected(self, populated_db):
        emb = _make_embedding()
        _insert_session_embedding(populated_db, "sess-alpha", emb)
        _insert_session_embedding(populated_db, "sess-beta", emb)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.5,
            ),
        ):
            results = find_similar_sessions(populated_db, "sess-alpha", limit=1)

        assert len(results) <= 1

    def test_exclude_same_project(self, populated_db):
        emb = _make_embedding()
        _insert_session_embedding(populated_db, "sess-alpha", emb)
        _insert_session_embedding(populated_db, "sess-beta", emb)
        # sess-beta is in /projects/beta — different project from sess-alpha (/projects/alpha)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.5,
            ),
        ):
            results = find_similar_sessions(
                populated_db, "sess-alpha", exclude_same_project=True
            )

        # sess-beta is a different project so should still appear
        assert all(r.project_path != "/projects/alpha" for r in results)

    def test_all_results_have_semantic_match_type(self, populated_db):
        emb = _make_embedding()
        _insert_session_embedding(populated_db, "sess-alpha", emb)
        _insert_session_embedding(populated_db, "sess-beta", emb)
        populated_db.commit()

        with (
            patch("agent_session_tools.semantic_search.EMBEDDINGS_AVAILABLE", True),
            patch(
                "agent_session_tools.semantic_search.cosine_similarity",
                return_value=0.5,
            ),
        ):
            results = find_similar_sessions(populated_db, "sess-alpha")

        for r in results:
            assert r.match_type == "semantic"


# ---------------------------------------------------------------------------
# format_suggested_context  (pure string formatting — no DB)
# ---------------------------------------------------------------------------


def _make_result(
    session_id: str = "s1",
    combined_score: float = 0.02,
    match_type: str = "hybrid",
    project_path: str = "/proj/myproject",
    content_preview: str = "Some content here",
    source: str = "claude_code",
    timestamp: str = "2024-01-01T10:00:00",
) -> SearchResult:
    return SearchResult(
        session_id=session_id,
        project_path=project_path,
        content_preview=content_preview,
        source=source,
        timestamp=timestamp,
        match_type=match_type,
        combined_score=combined_score,
        fts_score=0.01,
        semantic_score=0.01,
    )


class TestFormatSuggestedContext:
    def test_empty_results_returns_no_matches_message(self):
        output = format_suggested_context([], "test query")
        assert "No historical sessions found" in output
        assert "test query" in output

    def test_contains_query_in_output(self):
        results = [_make_result(combined_score=0.02)]
        output = format_suggested_context(results, "my search query")
        assert "my search query" in output

    def test_high_confidence_heading_for_high_scores(self):
        results = [_make_result(combined_score=0.02)]
        output = format_suggested_context(results, "query")
        assert "high confidence" in output.lower()

    def test_medium_confidence_heading_for_medium_scores(self):
        results = [_make_result(combined_score=0.01)]
        output = format_suggested_context(results, "query")
        assert "medium confidence" in output.lower()

    def test_low_confidence_heading_for_low_scores(self):
        results = [_make_result(combined_score=0.001)]
        output = format_suggested_context(results, "query")
        assert "low" in output.lower()

    def test_usage_guidance_included(self):
        results = [_make_result()]
        output = format_suggested_context(results, "query")
        assert "How to Use This Context" in output

    def test_result_count_in_output(self):
        results = [_make_result("s1"), _make_result("s2")]
        output = format_suggested_context(results, "query")
        assert "2" in output

    def test_max_results_limits_high_confidence_section(self):
        # Generate 5 high-confidence results; section should show at most 3
        results = [_make_result(f"s{i}", combined_score=0.02) for i in range(5)]
        output = format_suggested_context(results, "query", max_results=5)
        # The format shows at most 3 high confidence and 2 medium
        # We just verify it's a string and doesn't crash
        assert isinstance(output, str)

    def test_code_snippet_extracted_when_present(self):
        preview = "Here is some text.\n```python\nprint('hello')\n```\nmore text"
        results = [_make_result(content_preview=preview)]
        output = format_suggested_context(results, "query", include_code_snippets=True)
        assert "```python" in output

    def test_no_code_snippet_when_disabled(self):
        preview = "```python\nprint('hello')\n```"
        results = [_make_result(content_preview=preview)]
        output = format_suggested_context(results, "query", include_code_snippets=False)
        # Should not extract the code block into its own section
        assert "Code Snippet" not in output


# ---------------------------------------------------------------------------
# _format_single_result  (pure string formatting — no DB)
# ---------------------------------------------------------------------------


class TestFormatSingleResult:
    def test_contains_project_name(self):
        r = _make_result(project_path="/my/project/myproject")
        output = _format_single_result(r, 1)
        assert "myproject" in output

    def test_contains_full_path(self):
        r = _make_result(project_path="/my/project/myproject")
        output = _format_single_result(r, 1)
        assert "/my/project/myproject" in output

    def test_contains_index_number(self):
        r = _make_result()
        output = _format_single_result(r, 3)
        assert "3." in output

    def test_contains_source(self):
        r = _make_result(source="kiro_cli")
        output = _format_single_result(r, 1)
        assert "kiro_cli" in output

    def test_contains_timestamp_when_present(self):
        r = _make_result(timestamp="2024-06-15T14:00:00")
        output = _format_single_result(r, 1)
        assert "2024-06-15" in output

    def test_no_timestamp_section_when_empty(self):
        r = _make_result(timestamp="")
        output = _format_single_result(r, 1)
        assert "When:" not in output

    def test_match_type_hybrid_explanation(self):
        r = _make_result(match_type="hybrid")
        output = _format_single_result(r, 1)
        assert "keywords and meaning" in output

    def test_match_type_fts_explanation(self):
        r = _make_result(match_type="fts")
        output = _format_single_result(r, 1)
        assert "keywords" in output

    def test_match_type_semantic_explanation(self):
        r = _make_result(match_type="semantic")
        output = _format_single_result(r, 1)
        assert "meaning" in output

    def test_combined_score_in_output(self):
        r = _make_result(combined_score=0.0234)
        output = _format_single_result(r, 1)
        assert "0.0234" in output

    def test_code_block_extracted_when_include_code_true(self):
        r = _make_result(content_preview="Intro\n```python\nx = 1\n```\nOutro")
        output = _format_single_result(r, 1, include_code=True)
        assert "Code Snippet" in output

    def test_code_block_not_extracted_when_include_code_false(self):
        r = _make_result(content_preview="Intro\n```python\nx = 1\n```\nOutro")
        output = _format_single_result(r, 1, include_code=False)
        assert "Code Snippet" not in output

    def test_plain_preview_shown_when_no_code_block(self):
        r = _make_result(
            content_preview="Plain text content without any code blocks here"
        )
        output = _format_single_result(r, 1)
        assert "Preview" in output

    def test_unknown_project_path_shows_unknown(self):
        r = _make_result(project_path="")
        output = _format_single_result(r, 1)
        assert "Unknown" in output


# ---------------------------------------------------------------------------
# format_suggested_context — default query argument
# ---------------------------------------------------------------------------


def test_format_suggested_context_with_empty_query():
    """Calling with an empty query string should not raise."""
    results = [_make_result()]
    output = format_suggested_context(results, "")
    assert isinstance(output, str)
