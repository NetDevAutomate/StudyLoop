"""Verify every LazyGroup entry resolves to an importable module.

This test catches broken lazy subcommand registrations (typos, missing modules,
wrong attribute names) before users encounter them at runtime.
"""

from __future__ import annotations

import importlib

from studyctl.cli import cli


class TestLazySubcommands:
    def test_all_lazy_subcommands_importable(self) -> None:
        """Every LazyGroup entry must resolve to an importable module."""
        for name, import_path in cli._lazy_subcommands.items():
            module_path, _ = import_path.rsplit(":", 1)
            mod = importlib.import_module(module_path)
            assert mod is not None, f"Failed to import {module_path} for command '{name}'"

    def test_all_lazy_subcommands_have_attribute(self) -> None:
        """Every LazyGroup entry must resolve to a real attribute on the module."""
        for name, import_path in cli._lazy_subcommands.items():
            module_path, attr_name = import_path.rsplit(":", 1)
            mod = importlib.import_module(module_path)
            assert hasattr(mod, attr_name), (
                f"Module '{module_path}' has no attribute '{attr_name}' for command '{name}'"
            )

    def test_lazy_subcommands_dict_is_non_empty(self) -> None:
        """Sanity check: the lazy subcommands dict must not be empty."""
        assert len(cli._lazy_subcommands) > 0

    def test_lazy_subcommands_include_core_commands(self) -> None:
        """Core commands must be present in the lazy subcommands dict."""
        expected = {"review", "study", "doctor", "update", "backup", "bridge"}
        registered = set(cli._lazy_subcommands.keys())
        missing = expected - registered
        assert not missing, f"Core commands missing from lazy registry: {missing}"
