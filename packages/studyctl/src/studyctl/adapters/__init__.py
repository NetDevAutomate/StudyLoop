"""Agent adapter package — modular agent detection and launch.

Usage:
    from studyctl.adapters import detect_agents, get_adapter

    agents = detect_agents()
    adapter = get_adapter('claude')
    persona = adapter.setup(content, session_dir)
    cmd = adapter.launch_cmd(persona, resume=False)
"""

from studyctl.adapters._protocol import AdapterProtocol, AgentAdapter
from studyctl.adapters.registry import (
    detect_agents,
    get_adapter,
    get_all_adapters,
    get_default_agent,
    reset_registry,
)

__all__ = [
    "AdapterProtocol",
    "AgentAdapter",
    "detect_agents",
    "get_adapter",
    "get_all_adapters",
    "get_default_agent",
    "reset_registry",
]
