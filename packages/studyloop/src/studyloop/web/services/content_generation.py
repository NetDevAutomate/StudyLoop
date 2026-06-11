"""Business helpers for content-generation routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderAvailabilityInput:
    """Inputs needed to decide if a generation provider is currently usable."""

    slug: str
    auth_env: str
    env_value: str
    stored_secret: str | None
    bedrock_credentials: bool
    ollama_reachable: bool


def provider_is_available(data: ProviderAvailabilityInput) -> bool:
    """Return whether the provider has the credential/runtime signal it needs."""
    if data.slug == "bedrock":
        return bool(data.stored_secret or data.bedrock_credentials)
    if data.slug == "ollama":
        return data.ollama_reachable
    return bool((data.stored_secret or "").strip() or data.env_value.strip())


def queue_terminal_frame(
    queue: list[dict[str, Any]], frame: dict[str, Any], *, max_size: int
) -> None:
    """Append a frame to a bounded in-memory queue, dropping the oldest item."""
    if len(queue) >= max_size:
        del queue[0]
    queue.append(frame)
