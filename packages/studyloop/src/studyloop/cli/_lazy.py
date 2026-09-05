"""LazyGroup — defers command module imports until invoked.

Keeps CLI startup fast even with many command modules. Essential once
content commands (Phase 1) bring heavy deps like pymupdf.
"""

from __future__ import annotations

import importlib

import click


class LazyGroup(click.Group):
    """Click group that lazy-loads subcommands from dotted import paths.

    ``dev_subcommands`` are omitted from help and command resolution unless
    the root command was invoked with ``--dev``. Hiding at the group boundary
    matters: an experimental command should not look supported and then fail
    after import — it should not be part of the production CLI surface at all.
    """

    def __init__(
        self,
        *args,
        lazy_subcommands: dict[str, str] | None = None,
        dev_subcommands: set[str] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._lazy_subcommands = lazy_subcommands or {}
        self._dev_subcommands = dev_subcommands or set()

    @staticmethod
    def _dev_enabled(ctx: click.Context) -> bool:
        return bool(ctx.params.get("dev", False))

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(
            name
            for name in self._lazy_subcommands
            if name not in self._dev_subcommands or self._dev_enabled(ctx)
        )
        return base + lazy

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.BaseCommand | None:  # type: ignore[override]
        if cmd_name in self._dev_subcommands and not self._dev_enabled(ctx):
            return None
        if cmd_name in self._lazy_subcommands:
            return self._resolve(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _resolve(self, cmd_name: str) -> click.BaseCommand:  # type: ignore[return-value]
        import_path = self._lazy_subcommands[cmd_name]
        modname, attr_name = import_path.rsplit(":", 1)
        mod = importlib.import_module(modname)
        return getattr(mod, attr_name)
