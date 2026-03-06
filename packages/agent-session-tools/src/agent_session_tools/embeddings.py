"""Semantic embeddings for session search using sentence-transformers.

This module provides local embedding generation for semantic search capabilities.
Uses the all-MiniLM-L6-v2 model which is:
- Small (23MB)
- Fast (~50ms per query)
- Good quality for semantic similarity tasks
- Runs locally (no API costs, works offline)

The module handles graceful degradation when sentence-transformers is not installed,
allowing the rest of the application to function with FTS5-only search.
"""

import logging
import sqlite3
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# Supported embedding models with their configurations
# Ordered by recommendation priority for conceptual/tutoring content
SUPPORTED_MODELS = {
    # Recommended for conceptual content + tutoring
    "nomic-embed-text-v1.5": {
        "dimensions": 768,
        "size_mb": 550,
        "max_tokens": 8192,
        "description": "Best for conceptual understanding, excellent for tutoring/learning content",
        "hf_name": "nomic-ai/nomic-embed-text-v1.5",
    },
    # Good balance of quality and size
    "all-mpnet-base-v2": {
        "dimensions": 768,
        "size_mb": 420,
        "max_tokens": 512,
        "description": "Good general-purpose model with strong semantic understanding",
        "hf_name": "sentence-transformers/all-mpnet-base-v2",
    },
    # BGE models - state of the art for retrieval
    "bge-base-en-v1.5": {
        "dimensions": 768,
        "size_mb": 440,
        "max_tokens": 512,
        "description": "State-of-art retrieval model, excellent for search",
        "hf_name": "BAAI/bge-base-en-v1.5",
    },
    # Fast and small - good for initial testing
    "all-MiniLM-L6-v2": {
        "dimensions": 384,
        "size_mb": 23,
        "max_tokens": 256,
        "description": "Fast and small, good for testing but weaker semantics",
        "hf_name": "sentence-transformers/all-MiniLM-L6-v2",
    },
    # Code-specific model (for future two-model approach)
    "codebert-base": {
        "dimensions": 768,
        "size_mb": 500,
        "max_tokens": 512,
        "description": "Specialized for code content - use if >50% code blocks",
        "hf_name": "microsoft/codebert-base",
    },
}

# Default model - can be overridden via config.yaml or EMBEDDING_MODEL env var
# See config_loader.get_embedding_model() for the configured value
# Note: nomic-embed-text-v1.5 has compatibility issues with sentence-transformers 5.x
# Using all-mpnet-base-v2 as reliable default with strong semantic understanding
DEFAULT_MODEL = "all-mpnet-base-v2"

# Lazy-loaded model instances (supports multiple models)
_models: dict = {}
_current_model_name: str | None = None


def get_configured_model() -> str:
    """Get the embedding model from configuration.

    Checks (in order):
    1. EMBEDDING_MODEL environment variable
    2. semantic_search.model in config.yaml
    3. DEFAULT_MODEL constant

    Returns:
        Model name to use for embeddings
    """
    import os

    # Check environment variable first
    if (v := os.getenv("EMBEDDING_MODEL")):
        return v

    # Try to load from config (may fail if config not available)
    try:
        from .config_loader import get_embedding_model

        return get_embedding_model()
    except Exception:
        return DEFAULT_MODEL


# Noise filtering patterns (skip low-information content)
# Based on multi-model review: reduces false positives in search
NOISE_PATTERNS = {
    # Short acknowledgments
    "ok",
    "okay",
    "thanks",
    "thank you",
    "got it",
    "understood",
    "yes",
    "no",
    "sure",
    "right",
    "correct",
    "done",
    "great",
    # Common filler
    "let me",
    "i'll",
    "i will",
    "here's",
    "here is",
}
MIN_MEANINGFUL_LENGTH = 50  # Characters (about 12-15 words)
MIN_CODE_LENGTH = 20  # Shorter threshold for code content

# Check if sentence-transformers is available
try:
    import numpy as np  # pyright: ignore[reportMissingImports]
    from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]

    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    if TYPE_CHECKING:
        import numpy as np  # pyright: ignore[reportMissingImports]
        from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]


def is_available() -> bool:
    """Check if embedding functionality is available."""
    return EMBEDDINGS_AVAILABLE


def get_model_config(model_name: str) -> dict:
    """Get configuration for a supported model.

    Args:
        model_name: Short name or full HuggingFace name of the model

    Returns:
        Model configuration dict

    Raises:
        ValueError: If model is not supported
    """
    # Check if it's a short name
    if model_name in SUPPORTED_MODELS:
        return SUPPORTED_MODELS[model_name]

    # Check if it's a full HuggingFace name
    for _short_name, config in SUPPORTED_MODELS.items():
        if config["hf_name"] == model_name:
            return config

    # Unknown model - return generic config
    logger.warning(f"Model '{model_name}' not in supported list, using generic config")
    return {
        "dimensions": 768,  # Assume 768 as common default
        "size_mb": 0,
        "max_tokens": 512,
        "description": "Custom model",
        "hf_name": model_name,
    }


def list_supported_models() -> list[dict]:
    """List all supported embedding models with their configurations.

    Returns:
        List of model info dicts with name, dimensions, size, and description
    """
    return [
        {
            "name": name,
            "dimensions": config["dimensions"],
            "size_mb": config["size_mb"],
            "description": config["description"],
            "recommended": name == DEFAULT_MODEL,
        }
        for name, config in SUPPORTED_MODELS.items()
    ]


def get_model(model_name: str | None = None) -> "SentenceTransformer":
    """Get or lazily load the embedding model.

    Supports multiple models simultaneously - each is cached separately.

    Args:
        model_name: Name of the model to use. If None, uses DEFAULT_MODEL.
                    Can be either a short name (e.g., "nomic-embed-text-v1.5")
                    or a full HuggingFace name.

    Returns:
        Loaded SentenceTransformer model

    Raises:
        ImportError: If sentence-transformers is not installed
    """
    global _models, _current_model_name

    if not EMBEDDINGS_AVAILABLE:
        raise ImportError(
            "sentence-transformers is required for semantic search. "
            "Install with: uv add sentence-transformers numpy"
        )

    # Use default if not specified
    if model_name is None:
        model_name = DEFAULT_MODEL

    # Get the HuggingFace name for loading
    config = get_model_config(model_name)
    hf_name = config["hf_name"]

    # Check cache
    if model_name not in _models:
        logger.info(
            f"Loading embedding model: {model_name} ({config['dimensions']}d, {config['size_mb']}MB)"
        )
        logger.info(f"  Description: {config['description']}")

        # Special handling for nomic model which requires trust_remote_code
        trust_remote = "nomic" in hf_name.lower()

        _models[model_name] = SentenceTransformer(
            hf_name,
            trust_remote_code=trust_remote,
        )
        _current_model_name = model_name

        actual_dim = _models[model_name].get_sentence_embedding_dimension()
        if actual_dim != config["dimensions"]:
            logger.warning(
                f"  Actual dimensions ({actual_dim}) differ from expected ({config['dimensions']})"
            )

        logger.info(f"  Model loaded successfully (dim={actual_dim})")

    return _models[model_name]


def generate_embedding(text: str, model_name: str | None = None) -> bytes:
    """Generate embedding for text as bytes.

    Args:
        text: Text to embed (will be truncated based on model's max_tokens)
        model_name: Name of the model to use. If None, uses DEFAULT_MODEL.

    Returns:
        Embedding as bytes (float32 array serialized)

    Raises:
        ImportError: If sentence-transformers is not installed
    """
    if not EMBEDDINGS_AVAILABLE:
        raise ImportError(
            "sentence-transformers is required for semantic search. "
            "Install with: uv add sentence-transformers numpy"
        )

    if model_name is None:
        model_name = DEFAULT_MODEL

    model = get_model(model_name)
    config = get_model_config(model_name)

    # Truncate based on model's max tokens (~4 chars/token estimate)
    max_chars = config["max_tokens"] * 4
    if len(text) > max_chars:
        text = text[:max_chars]
        logger.debug(f"Truncated text to {max_chars} chars for model {model_name}")

    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.astype(np.float32).tobytes()


def get_embedding_dimensions(model_name: str | None = None) -> int:
    """Get the embedding dimensions for a model.

    Args:
        model_name: Name of the model. If None, uses DEFAULT_MODEL.

    Returns:
        Number of dimensions in the embedding vector
    """
    if model_name is None:
        model_name = DEFAULT_MODEL
    return get_model_config(model_name)["dimensions"]


def embedding_from_bytes(embedding_bytes: bytes) -> "np.ndarray":
    """Convert embedding bytes back to numpy array.

    Args:
        embedding_bytes: Serialized embedding from generate_embedding()

    Returns:
        Numpy array of float32 values
    """
    if not EMBEDDINGS_AVAILABLE:
        raise ImportError("numpy is required to decode embeddings")
    return np.frombuffer(embedding_bytes, dtype=np.float32)


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embeddings.

    Args:
        a: First embedding as bytes
        b: Second embedding as bytes

    Returns:
        Cosine similarity score between -1 and 1 (higher is more similar)
    """
    if not EMBEDDINGS_AVAILABLE:
        raise ImportError("numpy is required for similarity computation")

    vec_a = np.frombuffer(a, dtype=np.float32)
    vec_b = np.frombuffer(b, dtype=np.float32)

    dot_product = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))


def is_meaningful_content(content: str) -> bool:
    """Check if content is meaningful enough to embed.

    Filters out low-information messages that would pollute search results.
    Based on multi-model review recommendations.

    Args:
        content: Message content to check

    Returns:
        True if content should be embedded, False if it's noise
    """
    if not content:
        return False

    # Strip and normalize
    normalized = content.strip().lower()

    # Check for pure noise patterns
    if normalized in NOISE_PATTERNS:
        return False

    # Check if starts with common noise (but might have more content)
    first_words = " ".join(normalized.split()[:3])
    if first_words in NOISE_PATTERNS and len(normalized) < 100:
        return False

    # Code content has different threshold
    has_code = "```" in content or "def " in content or "class " in content
    min_length = MIN_CODE_LENGTH if has_code else MIN_MEANINGFUL_LENGTH

    if len(content) < min_length:
        return False

    # Check information density (avoid messages that are mostly whitespace/punctuation)
    alpha_ratio = sum(1 for c in content if c.isalnum()) / len(content)
    return alpha_ratio >= 0.3


def embed_message(
    conn: sqlite3.Connection,
    message_id: str,
    content: str,
    model_name: str = DEFAULT_MODEL,
    skip_existing: bool = True,
) -> bool:
    """Generate and store embedding for a single message.

    Args:
        conn: Database connection
        message_id: ID of the message to embed
        content: Message content to embed
        model_name: Embedding model to use
        skip_existing: If True, skip messages that already have embeddings

    Returns:
        True if embedding was created, False if skipped or failed
    """
    if not EMBEDDINGS_AVAILABLE:
        return False

    # Skip noise and low-information content
    if not is_meaningful_content(content):
        return False

    # Check if already embedded
    if skip_existing:
        existing = conn.execute(
            "SELECT 1 FROM message_embeddings WHERE message_id = ?", (message_id,)
        ).fetchone()
        if existing:
            return False

    try:
        embedding = generate_embedding(content, model_name)
        conn.execute(
            """
            INSERT OR REPLACE INTO message_embeddings (message_id, embedding, model)
            VALUES (?, ?, ?)
            """,
            (message_id, embedding, model_name),
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to embed message {message_id}: {e}")
        return False


def embed_session_messages(
    conn: sqlite3.Connection,
    session_id: str,
    model_name: str = DEFAULT_MODEL,
    min_content_length: int = 20,
) -> int:
    """Generate embeddings for all messages in a session.

    Args:
        conn: Database connection
        session_id: ID of the session to embed
        model_name: Embedding model to use
        min_content_length: Minimum content length to consider (final filter is is_meaningful_content)

    Returns:
        Number of messages embedded
    """
    if not EMBEDDINGS_AVAILABLE:
        logger.warning("Embeddings not available - sentence-transformers not installed")
        return 0

    # Get messages without embeddings (pre-filter by length, final filter by is_meaningful_content)
    messages = conn.execute(
        """
        SELECT m.id, m.content
        FROM messages m
        LEFT JOIN message_embeddings e ON m.id = e.message_id
        WHERE m.session_id = ?
          AND e.message_id IS NULL
          AND m.content IS NOT NULL
          AND LENGTH(m.content) >= ?
          AND m.role IN ('user', 'assistant')
        """,
        (session_id, min_content_length),
    ).fetchall()

    count = 0
    for msg_id, content in messages:
        # is_meaningful_content does the real filtering
        if embed_message(conn, msg_id, content, model_name, skip_existing=False):
            count += 1

    if count > 0:
        conn.commit()
        logger.info(f"Embedded {count} messages for session {session_id[:20]}...")

    return count


def embed_session(
    conn: sqlite3.Connection,
    session_id: str,
    model_name: str = DEFAULT_MODEL,
) -> bool:
    """Generate session-level embedding from aggregated message content.

    Creates a single embedding representing the entire session by combining
    key content from assistant and user messages.

    Args:
        conn: Database connection
        session_id: ID of the session to embed
        model_name: Embedding model to use

    Returns:
        True if embedding was created successfully
    """
    if not EMBEDDINGS_AVAILABLE:
        return False

    # Get key content from session (focus on user questions and assistant answers)
    messages = conn.execute(
        """
        SELECT role, content FROM messages
        WHERE session_id = ?
          AND role IN ('user', 'assistant')
          AND content IS NOT NULL
        ORDER BY seq, timestamp
        LIMIT 50
        """,
        (session_id,),
    ).fetchall()

    if not messages:
        return False

    # Combine content with role markers (truncate each message)
    parts = []
    for role, content in messages:
        truncated = content[:1000] if content else ""
        parts.append(f"{role}: {truncated}")

    combined = "\n".join(parts)

    try:
        embedding = generate_embedding(combined, model_name)
        conn.execute(
            """
            INSERT OR REPLACE INTO session_embeddings (session_id, embedding, model)
            VALUES (?, ?, ?)
            """,
            (session_id, embedding, model_name),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"Failed to embed session {session_id}: {e}")
        return False


def backfill_embeddings(
    conn: sqlite3.Connection,
    model_name: str = DEFAULT_MODEL,
    batch_size: int = 100,
    session_limit: int | None = None,
) -> dict:
    """Backfill embeddings for existing messages and sessions.

    Args:
        conn: Database connection
        model_name: Embedding model to use
        batch_size: Number of messages to process per batch
        session_limit: Maximum number of sessions to process (None for all)

    Returns:
        Dict with counts: {'messages': N, 'sessions': N, 'errors': N}
    """
    if not EMBEDDINGS_AVAILABLE:
        return {"messages": 0, "sessions": 0, "errors": 0, "available": False}

    stats = {"messages": 0, "sessions": 0, "errors": 0, "available": True}

    # Get sessions without embeddings
    query = """
        SELECT s.id FROM sessions s
        LEFT JOIN session_embeddings e ON s.id = e.session_id
        WHERE e.session_id IS NULL
        ORDER BY s.updated_at DESC
    """
    if session_limit:
        query += f" LIMIT {session_limit}"

    sessions = conn.execute(query).fetchall()
    logger.info(f"Backfilling embeddings for {len(sessions)} sessions")

    for (session_id,) in sessions:
        try:
            # Embed messages first
            msg_count = embed_session_messages(conn, session_id, model_name)
            stats["messages"] += msg_count

            # Then create session-level embedding
            if embed_session(conn, session_id, model_name):
                stats["sessions"] += 1
        except Exception as e:
            logger.error(f"Error backfilling session {session_id}: {e}")
            stats["errors"] += 1

    return stats
