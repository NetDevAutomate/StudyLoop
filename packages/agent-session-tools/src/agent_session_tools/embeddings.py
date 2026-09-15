"""Embedding MODEL layer: the sentence-transformers registry, loading and encoding.

Storage moved out of this module with migration 48. The aligned
``message_embeddings`` store (chunked, hashed, trigger-swept) is written by
``embedding_store`` and audited by ``embedding_alignment``; the retired
``semantic_search`` module and the one-vector-per-message functions that used
to live here (``embed_message`` .. ``backfill_embeddings``) had no production
caller and encoded the migration-7 shape, so they went with it.

What stays: ``SUPPORTED_MODELS`` (name -> hf id, dimensions, token cap),
``get_model`` (lazy load with an in-process cache), ``generate_embedding``
(float32 little-endian bytes) and ``is_meaningful_content`` (the noise filter).
Everything degrades loudly but safely when ``sentence-transformers`` is absent.
"""

import logging
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
        # The published model's max_seq_length is 384 (checked 2026-09-11); the
        # Stage 4 bake-off embedded mpnet with 512-token chunks against this
        # entry's old value, so its tails past 384 tokens were truncated.
        "max_tokens": 384,
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
    # Stage 1 bake-off candidate (semantic-layer plan): 384-d like MiniLM but a
    # 512-token window, so a third fewer messages overflow the cap.
    "bge-small-en-v1.5": {
        "dimensions": 384,
        "size_mb": 130,
        "max_tokens": 512,
        "description": "Small retrieval model with a 512-token window",
        "hf_name": "BAAI/bge-small-en-v1.5",
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

# ---------------------------------------------------------------------------
# ONNX query-side artefacts (lane A2, council D-6): pinned to an exact upstream
# commit BEFORE agent_session_tools.onnx_encoder.OnnxEncoder existed to load
# them. Checked 2026-09-15 against BAAI/bge-small-en-v1.5's own file listing
# (huggingface.co/api/models/BAAI/bge-small-en-v1.5?blobs=true) -- sha256 is
# the LFS blob hash for onnx/model.onnx, and the sha256 of the tokenizer files
# as fetched at that revision (they are not LFS, so the repo API's own
# "blobId" for them is a git blob hash, not a content sha256; hashed locally
# instead). ``pooling`` is CLS + L2-normalise per the repo's own
# 1_Pooling/config.json (pooling_mode_cls_token=true) and modules.json
# (2_Normalize) -- NOT mean pooling.
#
# fp32 first (council D-5): int8 is out of scope for this lane unless the
# fp32 load measures > 0.5 s, and would be a second, separately pinned entry
# here, never a silent re-quantisation of this one.
# ---------------------------------------------------------------------------
ONNX_ARTIFACTS: dict[str, dict[str, object]] = {
    "bge-small-en-v1.5": {
        "hf_name": "BAAI/bge-small-en-v1.5",
        "revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",  # pragma: allowlist secret -- a public git commit hash, not a secret
        "onnx_relpath": "onnx/model.onnx",
        "onnx_sha256": "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",  # pragma: allowlist secret -- a content hash, not a secret
        "onnx_size_bytes": 133093490,
        "tokenizer_sha256": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",  # pragma: allowlist secret -- a content hash, not a secret
        "tokenizer_config_sha256": "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3",  # pragma: allowlist secret -- a content hash, not a secret
        "pooling": "cls",
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
    if v := os.getenv("EMBEDDING_MODEL"):
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


# Availability is probed WITHOUT importing: an eager sentence-transformers
# import here measured 2.1 s and was paid by everything that reads this
# module's registry -- including the ONNX query encoder whose whole purpose
# is a sub-0.5 s load (Stage 5). ``find_spec`` locates the packages without
# executing them; the actual import happens inside ``get_model()``.
def _ml_runtime_available() -> bool:
    from importlib.util import find_spec

    try:
        return (
            find_spec("numpy") is not None
            and find_spec("sentence_transformers") is not None
        )
    except (ImportError, ValueError):
        return False


EMBEDDINGS_AVAILABLE = _ml_runtime_available()

if TYPE_CHECKING:
    import numpy as np  # pyright: ignore[reportMissingImports]
    from sentence_transformers import (  # pyright: ignore[reportMissingImports]
        SentenceTransformer,
    )


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


def get_model(
    model_name: str | None = None, *, local_files_only: bool = False
) -> "SentenceTransformer":
    """Get or lazily load the embedding model.

    Supports multiple models simultaneously - each is cached separately.

    Args:
        model_name: Name of the model to use. If None, uses DEFAULT_MODEL.
                    Can be either a short name (e.g., "nomic-embed-text-v1.5")
                    or a full HuggingFace name.
        local_files_only: Load from the local Hugging Face cache only and never
                    contact the hub -- the search path's setting, so a query
                    can never turn into a download whatever ``HF_HUB_OFFLINE``
                    says in the environment.

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

        from sentence_transformers import (  # pyright: ignore[reportMissingImports]
            SentenceTransformer,
        )

        _models[model_name] = SentenceTransformer(
            hf_name,
            trust_remote_code=trust_remote,
            local_files_only=local_files_only,
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

    import numpy as np  # pyright: ignore[reportMissingImports]

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
    import numpy as np  # pyright: ignore[reportMissingImports]

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

    import numpy as np  # pyright: ignore[reportMissingImports]

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
