"""Shared utility functions for agent-session-tools."""

import hashlib
from pathlib import Path


def stable_id(prefix: str, key: str) -> str:
    """Generate stable, deterministic ID from prefix and key.

    Uses SHA256 instead of Python's hash() which changes per process.
    """
    normalized = str(Path(key).resolve()).lower()
    hash_bytes = hashlib.sha256(normalized.encode()).hexdigest()[:12]
    return f"{prefix}_{hash_bytes}"


def content_hash(content: str) -> str:
    """Generate hash of content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def file_fingerprint(file_path: Path) -> str:
    """Generate fingerprint from file metadata for change detection."""
    stat = file_path.stat()
    return f"{stat.st_mtime}:{stat.st_size}"
