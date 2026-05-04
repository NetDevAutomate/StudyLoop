"""Tests for agent_session_tools.embeddings — semantic embedding utilities.

Strategy:
- sentence-transformers and numpy are optional runtime deps. All tests that
  exercise embedding generation patch the module-level EMBEDDINGS_AVAILABLE
  flag and inject a mock SentenceTransformer so no GPU/model download occurs.
- Tests for pure-Python logic (noise filtering, model config, list helpers)
  need no mocks — they are fast and dependency-free.
- DB-touching tests use an in-memory SQLite database with the base schema and
  all migrations applied (so message_embeddings / session_embeddings tables
  are present). We do NOT use the conftest `migrated_db` fixture here because
  those fixtures yield (conn, db_path) tuples and these tests only need conn.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# numpy is optional — import conditionally so that pure-Python tests
# (noise filtering, model config, etc.) still run when numpy is absent.
# Tests that actually need numpy are decorated with @requires_numpy.
try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    _NUMPY_AVAILABLE = False

requires_numpy = pytest.mark.skipif(
    not _NUMPY_AVAILABLE, reason="numpy not installed (install [semantic] extra)"
)

import agent_session_tools.embeddings as emb  # noqa: E402
from agent_session_tools.migrations import migrate  # noqa: E402


# ---------------------------------------------------------------------------
# Internal test helpers
# ---------------------------------------------------------------------------


def _make_embedding(dims: int = 384):  # -> np.ndarray when numpy is present
    """Return a deterministic unit-norm float32 vector."""
    assert _NUMPY_AVAILABLE, "numpy required"
    vec = np.ones(dims, dtype=np.float32)
    return vec / np.linalg.norm(vec)


def _embedding_bytes(dims: int = 384) -> bytes:
    return _make_embedding(dims).tobytes()


def _db_with_schema() -> sqlite3.Connection:
    """In-memory DB with base schema + all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema_path = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    )
    with open(schema_path) as f:
        conn.executescript(f.read())
    migrate(conn)
    return conn


def _insert_session(conn: sqlite3.Connection, session_id: str = "sess-001") -> None:
    conn.execute(
        "INSERT INTO sessions (id, source, project_path, created_at, updated_at) "
        "VALUES (?, 'claude_code', '/project', '2024-01-01T00:00:00', '2024-01-01T01:00:00')",
        (session_id,),
    )
    conn.commit()


def _insert_message(
    conn: sqlite3.Connection,
    msg_id: str,
    session_id: str = "sess-001",
    role: str = "user",
    content: str = "This is a meaningful message that is long enough to embed.",
) -> None:
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, '2024-01-01T00:00:00')",
        (msg_id, session_id, role, content),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixture: mock SentenceTransformer
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_model():
    """Patch the module so EMBEDDINGS_AVAILABLE=True with a mock ST model.

    The mock model's encode() returns a MagicMock whose .astype() returns a
    real numpy array so generate_embedding() can call .tobytes() on it.
    Automatically skipped when numpy is not installed.
    """
    if not _NUMPY_AVAILABLE:
        pytest.skip("numpy not installed (install [semantic] extra)")

    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 384
    mock_array = MagicMock()
    mock_array.astype.return_value = _make_embedding(384)
    model.encode.return_value = mock_array

    with (
        patch.object(emb, "EMBEDDINGS_AVAILABLE", True),
        patch.object(emb, "_models", {}),
        patch.object(emb, "np", np),
    ):
        yield model


# ===========================================================================
# 1. Module-level availability flag
# ===========================================================================


def test_is_available_returns_true_when_flag_set():
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", True):
        assert emb.is_available() is True


def test_is_available_returns_false_when_flag_clear():
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        assert emb.is_available() is False


# ===========================================================================
# 2. get_configured_model — env var, config, and DEFAULT_MODEL fallback
# ===========================================================================


def test_get_configured_model_env_var_takes_precedence(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "bge-base-en-v1.5")
    assert emb.get_configured_model() == "bge-base-en-v1.5"


def test_get_configured_model_returns_non_empty_string(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    # config.yaml may not be present in CI — assert type only
    result = emb.get_configured_model()
    assert isinstance(result, str)
    assert len(result) > 0


def test_default_model_constant_is_in_supported_models():
    assert emb.DEFAULT_MODEL in emb.SUPPORTED_MODELS


# ===========================================================================
# 3. SUPPORTED_MODELS and get_model_config
# ===========================================================================


def test_supported_models_contains_exactly_expected_keys():
    expected = {
        "nomic-embed-text-v1.5",
        "all-mpnet-base-v2",
        "bge-base-en-v1.5",
        "all-MiniLM-L6-v2",
        "codebert-base",
    }
    assert expected == set(emb.SUPPORTED_MODELS.keys())


def test_get_model_config_by_short_name():
    config = emb.get_model_config("all-MiniLM-L6-v2")
    assert config["dimensions"] == 384
    assert config["max_tokens"] == 256
    assert "hf_name" in config


def test_get_model_config_by_hf_name_resolves_correctly():
    config = emb.get_model_config("sentence-transformers/all-MiniLM-L6-v2")
    assert config["dimensions"] == 384


def test_get_model_config_nomic_model():
    config = emb.get_model_config("nomic-embed-text-v1.5")
    assert config["dimensions"] == 768
    assert "nomic" in config["hf_name"].lower()


def test_get_model_config_unknown_model_returns_generic_config():
    config = emb.get_model_config("some-unknown-model-xyz")
    assert config["dimensions"] == 768
    assert config["description"] == "Custom model"
    assert config["hf_name"] == "some-unknown-model-xyz"


@pytest.mark.parametrize("name", list(emb.SUPPORTED_MODELS.keys()))
def test_get_model_config_every_model_has_required_keys(name):
    required = {"dimensions", "size_mb", "max_tokens", "description", "hf_name"}
    config = emb.get_model_config(name)
    assert required.issubset(config.keys())


# ===========================================================================
# 4. list_supported_models
# ===========================================================================


def test_list_supported_models_returns_all_models():
    models = emb.list_supported_models()
    assert len(models) == len(emb.SUPPORTED_MODELS)


def test_list_supported_models_entries_have_required_fields():
    required = {"name", "dimensions", "size_mb", "description", "recommended"}
    for m in emb.list_supported_models():
        assert required.issubset(m.keys())


def test_list_supported_models_exactly_one_recommended():
    models = emb.list_supported_models()
    recommended = [m for m in models if m["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["name"] == emb.DEFAULT_MODEL


# ===========================================================================
# 5. get_embedding_dimensions
# ===========================================================================


@pytest.mark.parametrize(
    "model_name, expected_dims",
    [
        ("all-MiniLM-L6-v2", 384),
        ("all-mpnet-base-v2", 768),
        ("nomic-embed-text-v1.5", 768),
        ("bge-base-en-v1.5", 768),
        ("codebert-base", 768),
        (None, 768),  # None -> DEFAULT_MODEL = all-mpnet-base-v2 = 768d
    ],
)
def test_get_embedding_dimensions(model_name, expected_dims):
    assert emb.get_embedding_dimensions(model_name) == expected_dims


# ===========================================================================
# 6. get_model — lazy loading, caching, trust_remote_code flag
# ===========================================================================


def test_get_model_raises_import_error_when_unavailable():
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        with pytest.raises(ImportError, match="sentence-transformers"):
            emb.get_model()


@requires_numpy
def test_get_model_caches_loaded_model(mock_model):
    with patch.object(emb, "SentenceTransformer", return_value=mock_model):
        emb._models.clear()
        m1 = emb.get_model("all-MiniLM-L6-v2")
        m2 = emb.get_model("all-MiniLM-L6-v2")
    assert m1 is m2


@requires_numpy
def test_get_model_none_defaults_to_default_model(mock_model):
    with patch.object(emb, "SentenceTransformer", return_value=mock_model):
        emb._models.clear()
        emb.get_model(None)
    assert emb.DEFAULT_MODEL in emb._models


@requires_numpy
def test_get_model_nomic_passes_trust_remote_code_true(mock_model):
    """nomic models require trust_remote_code=True at load time."""
    captured: dict = {}

    def capture_st(hf_name, trust_remote_code=False):
        captured["trust_remote_code"] = trust_remote_code
        return mock_model

    with patch.object(emb, "SentenceTransformer", side_effect=capture_st):
        emb._models.clear()
        emb.get_model("nomic-embed-text-v1.5")

    assert captured["trust_remote_code"] is True


@requires_numpy
def test_get_model_non_nomic_passes_trust_remote_code_false(mock_model):
    captured: dict = {}

    def capture_st(hf_name, trust_remote_code=False):
        captured["trust_remote_code"] = trust_remote_code
        return mock_model

    with patch.object(emb, "SentenceTransformer", side_effect=capture_st):
        emb._models.clear()
        emb.get_model("all-MiniLM-L6-v2")

    assert captured["trust_remote_code"] is False


@requires_numpy
def test_get_model_dimension_mismatch_logs_warning(mock_model, caplog):
    """Actual dim != config dim must warn, not raise."""
    mock_model.get_sentence_embedding_dimension.return_value = (
        999  # intentional mismatch
    )

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
        caplog.at_level(logging.WARNING),
    ):
        emb.get_model("all-MiniLM-L6-v2")

    assert any("differ" in r.message.lower() for r in caplog.records)


# ===========================================================================
# 7. generate_embedding
# ===========================================================================


def test_generate_embedding_raises_import_error_when_unavailable():
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        with pytest.raises(ImportError, match="sentence-transformers"):
            emb.generate_embedding("hello")


@requires_numpy
def test_generate_embedding_returns_bytes(mock_model):
    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        result = emb.generate_embedding("This is a test sentence.")
    assert isinstance(result, bytes)


@requires_numpy
def test_generate_embedding_truncates_text_exceeding_max_tokens(mock_model):
    config = emb.get_model_config("all-MiniLM-L6-v2")
    max_chars = config["max_tokens"] * 4
    long_text = "x" * (max_chars + 500)

    captured: dict = {}

    def capture_encode(text, convert_to_numpy=True):
        captured["text"] = text
        arr = MagicMock()
        arr.astype.return_value = _make_embedding(384)
        return arr

    mock_model.encode.side_effect = capture_encode

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        emb.generate_embedding(long_text, "all-MiniLM-L6-v2")

    assert len(captured["text"]) == max_chars


@requires_numpy
def test_generate_embedding_short_text_passed_unchanged(mock_model):
    short_text = "Hello world"
    captured: dict = {}

    def capture_encode(text, convert_to_numpy=True):
        captured["text"] = text
        arr = MagicMock()
        arr.astype.return_value = _make_embedding(384)
        return arr

    mock_model.encode.side_effect = capture_encode

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        emb.generate_embedding(short_text, "all-MiniLM-L6-v2")

    assert captured["text"] == short_text


@requires_numpy
def test_generate_embedding_populates_model_cache(mock_model):
    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        emb.generate_embedding("test text", "all-MiniLM-L6-v2")
        # The cache assertion MUST happen inside the patch context -- the
        # patched ``emb._models`` dict is restored to the original on exit,
        # so ``emb._models`` outside the ``with`` has never seen the write.
        assert "all-MiniLM-L6-v2" in emb._models


# ===========================================================================
# 8. embedding_from_bytes — round-trip fidelity
# ===========================================================================


def test_embedding_from_bytes_raises_import_error_when_unavailable():
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        with pytest.raises(ImportError, match="numpy"):
            emb.embedding_from_bytes(b"\x00" * 16)


@requires_numpy
def test_embedding_from_bytes_round_trip_preserves_values():
    original = _make_embedding(384)
    recovered = emb.embedding_from_bytes(original.tobytes())
    np.testing.assert_array_almost_equal(original, recovered)


@requires_numpy
def test_embedding_from_bytes_preserves_float32_dtype():
    vec = np.ones(8, dtype=np.float32)
    recovered = emb.embedding_from_bytes(vec.tobytes())
    assert recovered.dtype == np.float32


@requires_numpy
def test_embedding_from_bytes_correct_array_length():
    dims = 128
    vec = np.zeros(dims, dtype=np.float32)
    recovered = emb.embedding_from_bytes(vec.tobytes())
    assert len(recovered) == dims


# ===========================================================================
# 9. cosine_similarity
# ===========================================================================


def test_cosine_similarity_raises_import_error_when_unavailable():
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        with pytest.raises(ImportError, match="numpy"):
            emb.cosine_similarity(b"\x00" * 4, b"\x00" * 4)


@requires_numpy
def test_cosine_similarity_identical_vectors_returns_one():
    b = _make_embedding(384).tobytes()
    score = emb.cosine_similarity(b, b)
    assert abs(score - 1.0) < 1e-5


@requires_numpy
def test_cosine_similarity_orthogonal_vectors_returns_zero():
    a = np.zeros(4, dtype=np.float32)
    b = np.zeros(4, dtype=np.float32)
    a[0] = 1.0
    b[1] = 1.0
    score = emb.cosine_similarity(a.tobytes(), b.tobytes())
    assert abs(score) < 1e-5


@requires_numpy
def test_cosine_similarity_zero_vector_returns_zero():
    zero = np.zeros(384, dtype=np.float32).tobytes()
    other = _make_embedding(384).tobytes()
    assert emb.cosine_similarity(zero, other) == 0.0


@requires_numpy
def test_cosine_similarity_result_within_minus_one_to_one():
    a = _embedding_bytes(384)
    b = _embedding_bytes(384)
    score = emb.cosine_similarity(a, b)
    # Floating-point cosine similarity can land at 1.0 + eps (or -1.0 - eps)
    # for near-identical vectors; allow a tiny tolerance on both ends.
    assert -1.0 - 1e-6 <= score <= 1.0 + 1e-6


@requires_numpy
def test_cosine_similarity_antiparallel_vectors_returns_minus_one():
    vec = _make_embedding(16)
    neg = (-vec).tobytes()
    score = emb.cosine_similarity(vec.tobytes(), neg)
    assert abs(score - (-1.0)) < 1e-5


# ===========================================================================
# 10. is_meaningful_content — noise filtering
# ===========================================================================


@pytest.mark.parametrize(
    "noise",
    [
        "",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "got it",
        "yes",
        "no",
        "sure",
        "right",
        "correct",
        "done",
        "great",
        "let me",
        "i'll",
        "i will",
        "here's",
        "here is",
    ],
)
def test_is_meaningful_content_rejects_noise_patterns(noise):
    assert emb.is_meaningful_content(noise) is False


def test_is_meaningful_content_rejects_empty_string():
    assert emb.is_meaningful_content("") is False


def test_is_meaningful_content_rejects_short_plain_text():
    # Under MIN_MEANINGFUL_LENGTH (50 chars) with no code markers
    assert emb.is_meaningful_content("too short") is False


def test_is_meaningful_content_accepts_long_plain_text():
    long_text = (
        "This is a detailed explanation of how Python generators work "
        "and why they save memory compared to regular lists in iteration."
    )
    assert emb.is_meaningful_content(long_text) is True


def test_is_meaningful_content_code_backtick_block_accepted():
    code = "```python\nprint('hello world')\n```"
    assert emb.is_meaningful_content(code) is True


def test_is_meaningful_content_code_def_keyword_accepted():
    # "def " triggers code mode; MIN_CODE_LENGTH=20 chars
    code = "def foo(x): return x * 2"
    assert len(code) >= emb.MIN_CODE_LENGTH
    assert emb.is_meaningful_content(code) is True


def test_is_meaningful_content_code_class_keyword_accepted():
    code = "class MyService:\n    pass"
    assert emb.is_meaningful_content(code) is True


def test_is_meaningful_content_rejects_very_short_code():
    # Below MIN_CODE_LENGTH even with "def "
    assert emb.is_meaningful_content("def f()") is False


def test_is_meaningful_content_rejects_low_alpha_ratio():
    # Mostly punctuation/spaces — alpha_ratio < 0.3
    junk = ". . . . . . . . . . . . . . . . . . . . . . . . "
    assert emb.is_meaningful_content(junk) is False


def test_is_meaningful_content_noise_prefix_short_content_rejected():
    # "let me" at start + full content under 100 chars -> rejected
    short = "let me check this quickly"
    assert len(short) < 100
    assert emb.is_meaningful_content(short) is False


def test_is_meaningful_content_noise_prefix_long_content_evaluated_normally():
    # Content > 100 chars bypasses the first_words short-circuit
    long_noise_start = "let me " + "explain something in great detail " * 5
    assert len(long_noise_start) > 100
    result = emb.is_meaningful_content(long_noise_start)
    assert isinstance(result, bool)  # reaches length/alpha checks, no crash


# ===========================================================================
# 11. embed_message — single-message DB write
# ===========================================================================


@pytest.fixture()
def embed_db():
    """In-memory fully-migrated DB with one session pre-inserted."""
    conn = _db_with_schema()
    _insert_session(conn, "sess-001")
    yield conn
    conn.close()


def test_embed_message_returns_false_when_unavailable(embed_db):
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        assert emb.embed_message(embed_db, "msg-001", "some content") is False


def test_embed_message_returns_false_for_noise_content(embed_db):
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", True):
        assert emb.embed_message(embed_db, "msg-001", "ok") is False


@requires_numpy
def test_embed_message_skips_if_row_already_in_message_embeddings(embed_db, mock_model):
    _insert_message(embed_db, "msg-001")
    embed_db.execute(
        "INSERT INTO message_embeddings (message_id, embedding, model) VALUES (?, ?, ?)",
        ("msg-001", _embedding_bytes(384), "all-MiniLM-L6-v2"),
    )
    embed_db.commit()

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        result = emb.embed_message(
            embed_db,
            "msg-001",
            "This is a meaningful message that is long enough to embed.",
            skip_existing=True,
        )
    assert result is False


@requires_numpy
def test_embed_message_creates_row_in_message_embeddings(embed_db, mock_model):
    _insert_message(embed_db, "msg-001")
    content = (
        "This is a detailed message about Python generators and memory efficiency."
    )

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        result = emb.embed_message(embed_db, "msg-001", content, skip_existing=False)

    assert result is True
    row = embed_db.execute(
        "SELECT embedding, model FROM message_embeddings WHERE message_id = ?",
        ("msg-001",),
    ).fetchone()
    assert row is not None
    assert row[1] == emb.DEFAULT_MODEL


def test_embed_message_exception_during_generate_returns_false(embed_db):
    _insert_message(embed_db, "msg-001")
    content = (
        "This is a meaningful long message that exceeds the threshold for embedding."
    )

    with (
        patch.object(emb, "EMBEDDINGS_AVAILABLE", True),
        patch.object(emb, "generate_embedding", side_effect=RuntimeError("exploded")),
    ):
        result = emb.embed_message(embed_db, "msg-001", content, skip_existing=False)

    assert result is False


# ===========================================================================
# 12. embed_session_messages — batch embedding for a session
# ===========================================================================


def test_embed_session_messages_returns_zero_when_unavailable(embed_db):
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        assert emb.embed_session_messages(embed_db, "sess-001") == 0


@requires_numpy
def test_embed_session_messages_embeds_qualifying_user_and_assistant_messages(
    embed_db, mock_model
):
    long = "This is a very detailed message about Python closures and scope management."
    _insert_message(embed_db, "msg-001", content=long)
    _insert_message(embed_db, "msg-002", role="assistant", content=long)

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        count = emb.embed_session_messages(embed_db, "sess-001")

    assert count == 2


@requires_numpy
def test_embed_session_messages_skips_short_content(embed_db, mock_model):
    # "hi" is well below min_content_length=20
    _insert_message(embed_db, "msg-short", content="hi")

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        count = emb.embed_session_messages(embed_db, "sess-001")

    assert count == 0


@requires_numpy
def test_embed_session_messages_skips_tool_role_messages(embed_db, mock_model):
    """The SQL WHERE clause limits to role IN ('user', 'assistant')."""
    long = "Tool output: processed 42 items successfully with detailed output text."
    _insert_message(embed_db, "msg-tool", role="tool_use", content=long)

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        count = emb.embed_session_messages(embed_db, "sess-001")

    assert count == 0


@requires_numpy
def test_embed_session_messages_commits_on_success(embed_db, mock_model):
    long = (
        "This detailed message explains Python decorators and how they work at runtime."
    )
    _insert_message(embed_db, "msg-001", content=long)

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        emb.embed_session_messages(embed_db, "sess-001")

    row = embed_db.execute(
        "SELECT message_id FROM message_embeddings WHERE message_id = 'msg-001'"
    ).fetchone()
    assert row is not None


# ===========================================================================
# 13. embed_session — session-level aggregate embedding
# ===========================================================================


def test_embed_session_returns_false_when_unavailable(embed_db):
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
        assert emb.embed_session(embed_db, "sess-001") is False


def test_embed_session_returns_false_when_no_messages_exist(embed_db):
    with patch.object(emb, "EMBEDDINGS_AVAILABLE", True):
        assert emb.embed_session(embed_db, "sess-001") is False


@requires_numpy
def test_embed_session_creates_row_in_session_embeddings(embed_db, mock_model):
    _insert_message(embed_db, "msg-001", content="Tell me about Python decorators.")
    _insert_message(
        embed_db,
        "msg-002",
        role="assistant",
        content="Decorators are functions that wrap other functions to extend behaviour.",
    )

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        result = emb.embed_session(embed_db, "sess-001")

    assert result is True
    row = embed_db.execute(
        "SELECT session_id, model FROM session_embeddings WHERE session_id = ?",
        ("sess-001",),
    ).fetchone()
    assert row is not None
    assert row[0] == "sess-001"


def test_embed_session_exception_returns_false(embed_db):
    _insert_message(embed_db, "msg-001", content="Meaningful content for session test.")

    with (
        patch.object(emb, "EMBEDDINGS_AVAILABLE", True),
        patch.object(emb, "generate_embedding", side_effect=RuntimeError("boom")),
    ):
        result = emb.embed_session(embed_db, "sess-001")

    assert result is False


@requires_numpy
def test_embed_session_upserts_on_repeated_call(embed_db, mock_model):
    """INSERT OR REPLACE means a second call must succeed, not raise."""
    _insert_message(embed_db, "msg-001", content="Meaningful question about Python.")

    with (
        patch.object(emb, "SentenceTransformer", return_value=mock_model),
        patch.object(emb, "_models", {}),
    ):
        first = emb.embed_session(embed_db, "sess-001")
        second = emb.embed_session(embed_db, "sess-001")

    assert first is True
    assert second is True


# ===========================================================================
# 14. backfill_embeddings — top-level orchestration
# ===========================================================================


def test_backfill_embeddings_returns_unavailable_dict_when_no_st():
    conn = _db_with_schema()
    try:
        with patch.object(emb, "EMBEDDINGS_AVAILABLE", False):
            result = emb.backfill_embeddings(conn)
        assert result == {"messages": 0, "sessions": 0, "errors": 0, "available": False}
    finally:
        conn.close()


@requires_numpy
def test_backfill_embeddings_empty_db_returns_zero_counts(mock_model):
    conn = _db_with_schema()
    try:
        with (
            patch.object(emb, "SentenceTransformer", return_value=mock_model),
            patch.object(emb, "_models", {}),
        ):
            result = emb.backfill_embeddings(conn)
        assert result == {"messages": 0, "sessions": 0, "errors": 0, "available": True}
    finally:
        conn.close()


@requires_numpy
def test_backfill_embeddings_processes_sessions_with_messages(mock_model):
    conn = _db_with_schema()
    try:
        _insert_session(conn, "sess-A")
        _insert_session(conn, "sess-B")
        long = (
            "This detailed message explains important Python concepts about closures."
        )
        _insert_message(conn, "msg-A", "sess-A", content=long)
        _insert_message(conn, "msg-B", "sess-B", content=long)

        with (
            patch.object(emb, "SentenceTransformer", return_value=mock_model),
            patch.object(emb, "_models", {}),
        ):
            result = emb.backfill_embeddings(conn)

        assert result["sessions"] == 2
        assert result["messages"] == 2
        assert result["errors"] == 0
    finally:
        conn.close()


@requires_numpy
def test_backfill_embeddings_respects_session_limit(mock_model):
    conn = _db_with_schema()
    try:
        long = "Detailed message about Python that is informative and well-structured."
        for i in range(5):
            sid = f"sess-{i:03d}"
            _insert_session(conn, sid)
            _insert_message(conn, f"msg-{i}", sid, content=long)

        with (
            patch.object(emb, "SentenceTransformer", return_value=mock_model),
            patch.object(emb, "_models", {}),
        ):
            result = emb.backfill_embeddings(conn, session_limit=2)

        assert result["sessions"] == 2
    finally:
        conn.close()


@requires_numpy
def test_backfill_embeddings_skips_sessions_already_in_session_embeddings(mock_model):
    conn = _db_with_schema()
    try:
        _insert_session(conn, "sess-done")
        long = (
            "This is a meaningful informative message about Python testing frameworks."
        )
        _insert_message(conn, "msg-done", "sess-done", content=long)

        conn.execute(
            "INSERT INTO session_embeddings (session_id, embedding, model) VALUES (?, ?, ?)",
            ("sess-done", _embedding_bytes(384), emb.DEFAULT_MODEL),
        )
        conn.commit()

        with (
            patch.object(emb, "SentenceTransformer", return_value=mock_model),
            patch.object(emb, "_models", {}),
        ):
            result = emb.backfill_embeddings(conn)

        assert result["sessions"] == 0
    finally:
        conn.close()


@requires_numpy
def test_backfill_embeddings_increments_error_count_on_exception(mock_model):
    conn = _db_with_schema()
    try:
        _insert_session(conn, "sess-err")
        long = "A meaningful long message that should trigger an embedding attempt."
        _insert_message(conn, "msg-err", "sess-err", content=long)

        with (
            patch.object(emb, "SentenceTransformer", return_value=mock_model),
            patch.object(emb, "_models", {}),
            patch.object(
                emb, "embed_session_messages", side_effect=RuntimeError("db bang")
            ),
        ):
            result = emb.backfill_embeddings(conn)

        assert result["errors"] == 1
    finally:
        conn.close()
