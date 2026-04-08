"""Agent adapter Protocol and dataclass.

The AdapterProtocol defines the contract that every agent adapter
must satisfy. AgentAdapter is the concrete frozen dataclass that
implements it using callables for each behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@runtime_checkable
class AdapterProtocol(Protocol):
    """Contract for agent adapters.

    Any object with these attributes and methods can act as an adapter.
    The AgentAdapter dataclass satisfies this Protocol, but custom
    implementations can use any class as long as it provides these fields.
    """

    name: str
    binary: str

    def setup(self, canonical_content: str, session_dir: Path) -> Path: ...
    def launch_cmd(self, persona_path: Path, resume: bool) -> str: ...
    def teardown(self, session_dir: Path) -> None: ...
    def mcp_setup(self, session_dir: Path) -> None: ...


@dataclass(frozen=True)
class AgentAdapter:
    """Configuration and behaviour for one AI coding agent.

    Each field is either static data or a callable that handles
    the agent-specific mechanism for persona injection and launch.
    """

    name: str
    binary: str
    setup: Callable[[str, Path], Path]
    """(canonical_content, session_dir) -> persona_path"""
    launch_cmd: Callable[[Path, bool], str]
    """(persona_path, resume) -> shell command string"""
    teardown: Callable[[Path], None] | None = None
    """Optional cleanup for agents that write global state."""
    mcp_setup: Callable[[Path], None] | None = None
    """Optional MCP config writer for the session directory."""
