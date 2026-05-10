"""LazyGroup — defers command module imports until invoked.

Keeps CLI startup fast even with many command modules. Essential once
content commands (Phase 1) bring heavy deps like pymupdf.
"""

from __future__ import annotations

import importlib

import click


class LazyGroup(click.Group):
    """Click group that lazy-loads subcommands from dotted import paths."""

    def __init__(self, *args, lazy_subcommands: dict[str, str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._lazy_subcommands = lazy_subcommands or {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(self._lazy_subcommands.keys())
        return base + lazy

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.BaseCommand | None:  # type: ignore[override]
        if cmd_name in self._lazy_subcommands:
            return self._resolve(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _resolve(self, cmd_name: str) -> click.BaseCommand:  # type: ignore[return-value]
        import_path = self._lazy_subcommands[cmd_name]
        modname, attr_name = import_path.rsplit(":", 1)
        mod = importlib.import_module(modname)
        return getattr(mod, attr_name)
