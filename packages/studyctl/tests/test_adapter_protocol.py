"""Tests for the adapter Protocol and AgentAdapter dataclass."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestAgentAdapterDataclass:
    def test_create_minimal_adapter(self):
        from studyctl.adapters._protocol import AgentAdapter

        def setup(content: str, session_dir: Path) -> Path:
            return session_dir / "persona.md"

        def launch(persona_path: Path, resume: bool) -> str:
            return f"agent --prompt {persona_path}"

        adapter = AgentAdapter(
            name="test-agent",
            binary="test-agent",
            setup=setup,
            launch_cmd=launch,
        )
        assert adapter.name == "test-agent"
        assert adapter.binary == "test-agent"
        assert adapter.teardown is None
        assert adapter.mcp_setup is None

    def test_adapter_is_frozen(self):
        from studyctl.adapters._protocol import AgentAdapter

        adapter = AgentAdapter(
            name="x",
            binary="x",
            setup=lambda c, d: d / "p.md",
            launch_cmd=lambda p, r: "x",
        )
        with pytest.raises(AttributeError):
            adapter.name = "changed"  # type: ignore[misc]

    def test_adapter_with_all_fields(self):
        from studyctl.adapters._protocol import AgentAdapter

        adapter = AgentAdapter(
            name="full",
            binary="full-agent",
            setup=lambda c, d: d / "p.md",
            launch_cmd=lambda p, r: "full",
            teardown=lambda d: None,
            mcp_setup=lambda d: None,
        )
        assert adapter.teardown is not None
        assert adapter.mcp_setup is not None

    def test_adapter_has_protocol_attributes(self):
        """AgentAdapter has all attributes defined by AdapterProtocol.

        Note: runtime_checkable isinstance doesn't work with dataclass Callable
        fields (they're data attributes, not methods). We verify structurally.
        """
        from studyctl.adapters._protocol import AgentAdapter

        adapter = AgentAdapter(
            name="test",
            binary="test",
            setup=lambda c, d: d / "p.md",
            launch_cmd=lambda p, r: "test",
        )
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "binary")
        assert hasattr(adapter, "setup")
        assert hasattr(adapter, "launch_cmd")
        assert hasattr(adapter, "teardown")
        assert hasattr(adapter, "mcp_setup")
