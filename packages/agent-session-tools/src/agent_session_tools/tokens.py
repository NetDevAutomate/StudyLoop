#!/usr/bin/env python3
"""Token counting utilities with optional tiktoken support.

Falls back to character-based estimation when tiktoken is not installed.
"""

from typing import Protocol

# Try to import tiktoken, fall back gracefully
try:
    import tiktoken  # pyright: ignore[reportMissingImports]

    TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None  # type: ignore[assignment]
    TIKTOKEN_AVAILABLE = False


class TokenCounter(Protocol):
    """Protocol for token counting implementations."""

    def count(self, text: str) -> int:
        """Count tokens in text."""
        ...

    def truncate_to_fit(self, text: str, max_tokens: int, strategy: str = "end") -> str:
        """Truncate text to fit within max_tokens."""
        ...


class TiktokenCounter:
    """Accurate token counting using tiktoken (cl100k_base encoding)."""

    def __init__(self, model: str = "cl100k_base"):
        """Initialize with encoding.

        Args:
            model: Encoding name or model name. Claude uses cl100k_base.
        """
        if not TIKTOKEN_AVAILABLE or tiktoken is None:
            raise ImportError(
                "tiktoken is required. Install with: uv pip install tiktoken"
            )
        self.encoder = tiktoken.get_encoding(model)

    def count(self, text: str) -> int:
        """Count tokens in text."""
        if not text:
            return 0
        return len(self.encoder.encode(text))

    def truncate_to_fit(self, text: str, max_tokens: int, strategy: str = "end") -> str:
        """Truncate text to fit within max_tokens.

        Args:
            text: Text to truncate
            max_tokens: Maximum tokens allowed
            strategy: How to truncate - "end" (keep start), "start" (keep end),
                     "middle" (keep start and end, remove middle)

        Returns:
            Truncated text
        """
        if not text:
            return text

        tokens = self.encoder.encode(text)
        if len(tokens) <= max_tokens:
            return text

        if strategy == "end":
            # Keep the beginning
            truncated = tokens[:max_tokens]
        elif strategy == "start":
            # Keep the end
            truncated = tokens[-max_tokens:]
        elif strategy == "middle":
            # Keep beginning and end, remove middle
            half = max_tokens // 2
            truncated = tokens[:half] + tokens[-(max_tokens - half) :]
        else:
            truncated = tokens[:max_tokens]

        return self.encoder.decode(truncated)


class EstimateCounter:
    """Fallback token counter using character-based estimation.

    Uses ratio of ~4 characters per token (reasonable for English text).
    """

    CHARS_PER_TOKEN = 4

    def count(self, text: str) -> int:
        """Estimate tokens from character count."""
        if not text:
            return 0
        return len(text) // self.CHARS_PER_TOKEN

    def truncate_to_fit(self, text: str, max_tokens: int, strategy: str = "end") -> str:
        """Truncate text to fit within estimated max_tokens."""
        if not text:
            return text

        max_chars = max_tokens * self.CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text

        if strategy == "end":
            return text[:max_chars]
        elif strategy == "start":
            return text[-max_chars:]
        elif strategy == "middle":
            half = max_chars // 2
            return text[:half] + "\n...[truncated]...\n" + text[-(max_chars - half) :]
        else:
            return text[:max_chars]


def get_counter(prefer_accurate: bool = True) -> TokenCounter:
    """Get the best available token counter.

    Args:
        prefer_accurate: If True, use tiktoken if available. If False, always use estimation.

    Returns:
        TokenCounter implementation
    """
    if prefer_accurate and TIKTOKEN_AVAILABLE:
        return TiktokenCounter()
    return EstimateCounter()


def count_tokens(text: str, accurate: bool = True) -> int:
    """Convenience function to count tokens.

    Args:
        text: Text to count
        accurate: Use tiktoken if available

    Returns:
        Token count
    """
    counter = get_counter(prefer_accurate=accurate)
    return counter.count(text)


def truncate_to_tokens(
    text: str, max_tokens: int, strategy: str = "end", accurate: bool = True
) -> str:
    """Convenience function to truncate text to token limit.

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens
        strategy: "end", "start", or "middle"
        accurate: Use tiktoken if available

    Returns:
        Truncated text
    """
    counter = get_counter(prefer_accurate=accurate)
    return counter.truncate_to_fit(text, max_tokens, strategy)
