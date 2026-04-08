"""Shared helpers for local LLM adapters (Ollama and LM Studio).

Both adapters use Claude Code as the frontend but point it at a local
LLM backend via environment variables. These helpers are extracted here
to avoid duplication between ollama.py and lmstudio.py.
"""

from __future__ import annotations


def _get_local_llm_config(provider: str) -> tuple[str, str]:
    """Return (base_url, model) for a local LLM provider from config.

    Falls back to sensible defaults if config isn't available.
    """
    defaults = {
        "ollama": ("http://localhost:4000", "qwen3-coder"),  # LiteLLM proxy
        "lmstudio": ("http://localhost:1234", "qwen3-coder"),
    }
    try:
        from studyctl.settings import load_settings

        cfg = getattr(load_settings().agents, provider, None)
        if cfg and cfg.model:
            return cfg.base_url or defaults[provider][0], cfg.model
    except Exception:
        pass
    return defaults[provider]


def _local_llm_env_prefix(base_url: str, auth_token: str, model: str) -> str:
    """Build shell env var exports for a local LLM provider.

    Tier-pins all Claude Code model tiers to the same model, since
    local LLMs only serve one model at a time. Without this, Claude
    tries to use different models for sub-agents and fast tasks.
    """
    return (
        f"export ANTHROPIC_BASE_URL={base_url} "
        f"ANTHROPIC_AUTH_TOKEN={auth_token} "
        f"ANTHROPIC_MODEL={model} "
        f"ANTHROPIC_SMALL_FAST_MODEL={model} "
        f"ANTHROPIC_DEFAULT_HAIKU_MODEL={model} "
        f"ANTHROPIC_DEFAULT_SONNET_MODEL={model} "
        f"ANTHROPIC_DEFAULT_OPUS_MODEL={model}; "
    )
