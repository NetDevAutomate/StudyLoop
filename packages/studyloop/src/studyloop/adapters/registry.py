"""Adapter registry for the five admitted pre-release harnesses.

Built-in adapters live as sibling modules (e.g. ``claude.py``) and
expose a module-level ``ADAPTER`` attribute of type ``AgentAdapter``.
Custom adapters are loaded via ``studyloop.adapters._custom.load_custom_adapters()``,
which is generated from config at runtime and may not exist.

The registry is a module-level cache built on first access and explicitly
cleared by ``reset_registry()`` for test isolation.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil

from studyloop.adapters._protocol import AgentAdapter
from studyloop.harnesses import RELEASE_HARNESSES

log = logging.getLogger(__name__)

# Module-level cache — None means "not yet built"
_registry: dict[str, AgentAdapter] | None = None


def _discover_builtins() -> dict[str, AgentAdapter]:
    """Load only adapters admitted by the pre-release harness contract."""
    adapters: dict[str, AgentAdapter] = {}
    for name in RELEASE_HARNESSES:
        full_name = f"studyloop.adapters.{name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:
            log.warning("Failed to import adapter module %s: %s", full_name, exc)
            continue

        if not hasattr(module, "ADAPTER"):
            log.warning("Adapter module %s has no ADAPTER attribute — skipped", full_name)
            continue
        adapter = module.ADAPTER
        if not isinstance(adapter, AgentAdapter):
            log.warning(
                "ADAPTER in %s is not an AgentAdapter instance (%s) — skipped",
                full_name,
                type(adapter).__name__,
            )
            continue

        adapters[adapter.name] = adapter

    return adapters


def _load_custom_agents() -> dict[str, AgentAdapter]:
    """Load custom adapters from ``studyloop.adapters._custom``, if it exists.

    Returns an empty dict on any import or runtime error — the custom loader
    module is optional and may not be present.
    """
    try:
        from studyloop.adapters._custom import load_custom_adapters  # type: ignore[import]

        return load_custom_adapters()
    except Exception:
        return {}


def _build_registry() -> dict[str, AgentAdapter]:
    """Build the registry from admitted built-ins plus explicit extensions.

    Custom adapters may add locally maintained harnesses, but cannot override
    the semantics of an admitted release harness.
    """
    combined: dict[str, AgentAdapter] = {}
    combined.update(_discover_builtins())
    combined.update(
        (name, adapter) for name, adapter in _load_custom_agents().items() if name not in combined
    )
    return combined


def get_all_adapters() -> dict[str, AgentAdapter]:
    """Return the cached adapter registry, building it on the first call."""
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_adapter(name: str) -> AgentAdapter:
    """Return the adapter registered under *name*.

    Raises ``KeyError`` if no adapter with that name is registered.
    """
    adapters = get_all_adapters()
    if name not in adapters:
        raise KeyError(f"No adapter registered for agent {name!r}")
    return adapters[name]


def detect_agents() -> list[str]:
    """Return installed agent names in priority order.

    Priority:
    1. ``STUDYLOOP_AGENT`` env var (if set *and* binary is on PATH)
    2. ``agents.priority`` list from config (each checked with ``shutil.which``)
    3. Registry insertion order as the final fallback

    Only agents whose binary is resolvable via ``shutil.which`` are included.
    """
    from studyloop.settings import load_settings

    adapters = get_all_adapters()

    env_override = os.environ.get("STUDYLOOP_AGENT", "").strip()
    if env_override:
        adapter = adapters.get(env_override)
        if adapter is not None and shutil.which(adapter.binary):
            return [env_override]
        # Env var set but binary not available → return nothing rather than
        # falling through to a different agent (explicit intent should be honoured)
        return []

    # Build the ordered candidate list: config priority first, then remaining
    # registry entries for any adapters not mentioned in config.
    try:
        settings = load_settings()
        priority_names: list[str] = settings.agents.priority
    except Exception:
        priority_names = []

    seen: set[str] = set()
    ordered: list[str] = []
    for name in priority_names:
        if name in adapters and name not in seen:
            ordered.append(name)
            seen.add(name)
    # Append any registry entries not covered by config priority
    for name in adapters:
        if name not in seen:
            ordered.append(name)

    return [name for name in ordered if shutil.which(adapters[name].binary)]


def get_default_agent() -> str | None:
    """Return the first available agent, or ``None`` if none are installed."""
    available = detect_agents()
    return available[0] if available else None


def reset_registry() -> None:
    """Clear the module-level registry cache.

    Intended for test isolation — forces the next ``get_all_adapters()`` call
    to rebuild from scratch.
    """
    global _registry
    _registry = None
