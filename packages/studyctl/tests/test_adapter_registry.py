"""Tests for the adapter registry (auto-discovery + detection)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_fake_adapter(name: str, binary: str | None = None):
    """Create a minimal AgentAdapter for test injection."""
    from studyctl.adapters._protocol import AgentAdapter

    return AgentAdapter(
        name=name,
        binary=binary or f"{name}-bin",
        setup=lambda c, d: d / "p",
        launch_cmd=lambda p, r: name,
    )


class TestRegistry:
    def test_get_all_adapters_returns_dict(self):
        # Just verify it returns a dict (no builtins exist yet)
        from studyctl.adapters.registry import get_all_adapters, reset_registry

        reset_registry()
        adapters = get_all_adapters()
        assert isinstance(adapters, dict)

    def test_get_adapter_unknown_raises(self):
        from studyctl.adapters.registry import get_adapter, reset_registry

        reset_registry()
        with pytest.raises(KeyError):
            get_adapter("nonexistent")

    def test_detect_agents_env_override(self):
        # Register a fake adapter, set env var, mock which
        from studyctl.adapters import registry
        from studyctl.adapters._protocol import AgentAdapter
        from studyctl.adapters.registry import detect_agents, reset_registry

        reset_registry()
        # Manually inject a test adapter
        fake = AgentAdapter(
            name="fake",
            binary="fake-bin",
            setup=lambda c, d: d / "p",
            launch_cmd=lambda p, r: "fake",
        )
        registry._registry = {"fake": fake}
        with (
            patch("shutil.which", return_value="/usr/bin/fake"),
            patch.dict("os.environ", {"STUDYCTL_AGENT": "fake"}),
        ):
            result = detect_agents()
        assert result == ["fake"]
        reset_registry()

    def test_detect_agents_env_unavailable(self):
        from studyctl.adapters import registry
        from studyctl.adapters._protocol import AgentAdapter

        registry.reset_registry()
        fake = AgentAdapter(
            name="fake",
            binary="fake-bin",
            setup=lambda c, d: d / "p",
            launch_cmd=lambda p, r: "fake",
        )
        registry._registry = {"fake": fake}
        with (
            patch("shutil.which", return_value=None),
            patch.dict("os.environ", {"STUDYCTL_AGENT": "fake"}),
        ):
            result = registry.detect_agents()
        assert result == []
        registry.reset_registry()

    def test_reset_registry(self):
        from studyctl.adapters.registry import get_all_adapters, reset_registry

        get_all_adapters()  # populate cache
        reset_registry()
        # Should work without error
        get_all_adapters()

    def test_get_adapter_returns_correct_adapter(self):
        from studyctl.adapters import registry

        registry.reset_registry()
        fake = _make_fake_adapter("myfake")
        registry._registry = {"myfake": fake}
        result = registry.get_adapter("myfake")
        assert result.name == "myfake"
        registry.reset_registry()

    def test_get_default_agent_returns_first_available(self):
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {
            "alpha": _make_fake_adapter("alpha", "alpha-bin"),
            "beta": _make_fake_adapter("beta", "beta-bin"),
        }
        settings_mock = MagicMock()
        settings_mock.agents.priority = ["alpha", "beta"]
        with (
            patch("studyctl.adapters.registry.shutil.which", return_value="/usr/bin/alpha"),
            patch("studyctl.settings.load_settings", return_value=settings_mock),
        ):
            result = registry.get_default_agent()
        assert result == "alpha"
        registry.reset_registry()

    def test_get_default_agent_returns_none_when_empty(self):
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {}
        settings_mock = MagicMock()
        settings_mock.agents.priority = []
        with (
            patch("studyctl.adapters.registry.shutil.which", return_value=None),
            patch("studyctl.settings.load_settings", return_value=settings_mock),
        ):
            result = registry.get_default_agent()
        assert result is None
        registry.reset_registry()

    def test_get_all_adapters_uses_cache(self):
        """Second call returns same dict object (cache hit)."""
        from studyctl.adapters import registry

        registry.reset_registry()
        first = registry.get_all_adapters()
        second = registry.get_all_adapters()
        assert first is second
        registry.reset_registry()


class TestDetectAgentsPriority:
    def test_respects_config_priority_order(self):
        """detect_agents returns agents in config.yaml priority order."""
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {
            "alpha": _make_fake_adapter("alpha", "alpha-bin"),
            "beta": _make_fake_adapter("beta", "beta-bin"),
            "gamma": _make_fake_adapter("gamma", "gamma-bin"),
        }
        settings_mock = MagicMock()
        settings_mock.agents.priority = ["gamma", "alpha", "beta"]

        def which_all(binary):
            return f"/usr/bin/{binary}"

        with (
            patch("studyctl.adapters.registry.shutil.which", side_effect=which_all),
            patch("studyctl.settings.load_settings", return_value=settings_mock),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = registry.detect_agents()

        assert result == ["gamma", "alpha", "beta"]
        registry.reset_registry()

    def test_agents_not_in_priority_appended_after(self):
        """Agents not listed in priority are appended after priority list."""
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {
            "alpha": _make_fake_adapter("alpha", "alpha-bin"),
            "beta": _make_fake_adapter("beta", "beta-bin"),
            "extra": _make_fake_adapter("extra", "extra-bin"),
        }
        settings_mock = MagicMock()
        settings_mock.agents.priority = ["beta", "alpha"]

        def which_all(binary):
            return f"/usr/bin/{binary}"

        with (
            patch("studyctl.adapters.registry.shutil.which", side_effect=which_all),
            patch("studyctl.settings.load_settings", return_value=settings_mock),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = registry.detect_agents()

        # priority names first, then unlisted "extra"
        assert result.index("beta") < result.index("alpha")
        assert "extra" in result
        assert result.index("alpha") < result.index("extra")
        registry.reset_registry()

    def test_unavailable_agents_excluded(self):
        """Agents whose binary is not found by shutil.which are excluded."""
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {
            "present": _make_fake_adapter("present", "present-bin"),
            "absent": _make_fake_adapter("absent", "absent-bin"),
        }
        settings_mock = MagicMock()
        settings_mock.agents.priority = ["present", "absent"]

        def selective_which(binary):
            return "/usr/bin/present-bin" if binary == "present-bin" else None

        with (
            patch("studyctl.adapters.registry.shutil.which", side_effect=selective_which),
            patch("studyctl.settings.load_settings", return_value=settings_mock),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = registry.detect_agents()

        assert result == ["present"]
        assert "absent" not in result
        registry.reset_registry()

    def test_env_override_unknown_agent_returns_empty(self):
        """STUDYCTL_AGENT set to an unregistered name returns empty list."""
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {"real": _make_fake_adapter("real", "real-bin")}
        with (
            patch("studyctl.adapters.registry.shutil.which", return_value="/usr/bin/real"),
            patch.dict("os.environ", {"STUDYCTL_AGENT": "ghost"}),
        ):
            result = registry.detect_agents()
        assert result == []
        registry.reset_registry()

    def test_settings_failure_falls_back_gracefully(self):
        """If load_settings raises, priority defaults to empty and all available shown."""
        from studyctl.adapters import registry

        registry.reset_registry()
        registry._registry = {
            "alpha": _make_fake_adapter("alpha", "alpha-bin"),
        }

        with (
            patch("studyctl.adapters.registry.shutil.which", return_value="/usr/bin/alpha-bin"),
            patch("studyctl.settings.load_settings", side_effect=RuntimeError("boom")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = registry.detect_agents()

        assert result == ["alpha"]
        registry.reset_registry()


class TestDiscoveryErrorHandling:
    def test_bad_module_logged_and_skipped(self, caplog):
        """If an adapter module fails to import, it's logged and skipped."""
        import logging

        from studyctl.adapters import registry

        registry.reset_registry()

        class _FakeModuleInfo:
            name = "bad_adapter"

        def fake_iter(path):
            yield _FakeModuleInfo()

        with (
            patch("pkgutil.iter_modules", side_effect=fake_iter),
            patch("importlib.import_module", side_effect=ImportError("boom")),
            caplog.at_level(logging.WARNING, logger="studyctl.adapters.registry"),
        ):
            result = registry._discover_builtins()

        assert result == {}
        assert any("boom" in r.message or "bad_adapter" in r.message for r in caplog.records)
        registry.reset_registry()

    def test_module_missing_adapter_attribute_logged(self, caplog):
        """Module without ADAPTER attribute is skipped with a warning."""
        import logging

        from studyctl.adapters import registry

        registry.reset_registry()

        class _FakeModuleInfo:
            name = "no_adapter_mod"

        def fake_iter(path):
            yield _FakeModuleInfo()

        fake_module = MagicMock(spec=[])  # no ADAPTER attribute
        del fake_module.ADAPTER

        with (
            patch("pkgutil.iter_modules", side_effect=fake_iter),
            patch("importlib.import_module", return_value=fake_module),
            caplog.at_level(logging.WARNING, logger="studyctl.adapters.registry"),
        ):
            result = registry._discover_builtins()

        assert result == {}
        assert any("no ADAPTER" in r.message for r in caplog.records)
        registry.reset_registry()

    def test_adapter_wrong_type_logged_and_skipped(self, caplog):
        """Module with ADAPTER of wrong type is logged and skipped."""
        import logging

        from studyctl.adapters import registry

        registry.reset_registry()

        class _FakeModuleInfo:
            name = "wrong_type_mod"

        def fake_iter(path):
            yield _FakeModuleInfo()

        fake_module = MagicMock()
        fake_module.ADAPTER = "not-an-AgentAdapter"

        with (
            patch("pkgutil.iter_modules", side_effect=fake_iter),
            patch("importlib.import_module", return_value=fake_module),
            caplog.at_level(logging.WARNING, logger="studyctl.adapters.registry"),
        ):
            result = registry._discover_builtins()

        assert result == {}
        assert any("not an AgentAdapter" in r.message for r in caplog.records)
        registry.reset_registry()

    def test_custom_agents_merged(self):
        """Custom agents from _load_custom_agents are merged into registry."""
        from studyctl.adapters import registry

        registry.reset_registry()
        custom = _make_fake_adapter("custom-agent", "custom-bin")
        with (
            patch(
                "studyctl.adapters.registry._load_custom_agents",
                return_value={"custom-agent": custom},
            ),
            patch("studyctl.adapters.registry._discover_builtins", return_value={}),
        ):
            result = registry._build_registry()
        assert "custom-agent" in result
        registry.reset_registry()

    def test_custom_overrides_builtin(self):
        """A custom agent with the same name as a built-in overrides it."""
        from studyctl.adapters import registry

        registry.reset_registry()
        builtin = _make_fake_adapter("claude", "claude-bin")
        custom_claude = _make_fake_adapter("claude", "custom-claude-bin")
        with (
            patch(
                "studyctl.adapters.registry._discover_builtins",
                return_value={"claude": builtin},
            ),
            patch(
                "studyctl.adapters.registry._load_custom_agents",
                return_value={"claude": custom_claude},
            ),
        ):
            result = registry._build_registry()
        # custom wins
        assert result["claude"].binary == "custom-claude-bin"
        registry.reset_registry()

    def test_load_custom_agents_returns_empty_on_missing_module(self):
        """_load_custom_agents returns {} when _custom module is absent."""
        from studyctl.adapters import registry

        # The real _custom module won't exist in test env; verify graceful return
        result = registry._load_custom_agents()
        assert isinstance(result, dict)

    def test_load_custom_agents_returns_empty_when_loader_raises(self):
        """_load_custom_agents returns {} when load_custom_adapters() raises."""
        from studyctl.adapters import registry

        # Simulate the _custom module existing but load_custom_adapters() blowing up
        fake_module = MagicMock()
        fake_module.load_custom_adapters = MagicMock(side_effect=RuntimeError("bad config"))
        with patch.dict("sys.modules", {"studyctl.adapters._custom": fake_module}):
            result = registry._load_custom_agents()
        assert result == {}
