"""Standalone memory policy administration; no StudyLoop runtime dependency."""

from __future__ import annotations

import getpass
import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from ..config_loader import get_db_path, load_config
from ..migrations import migrate
from .scope import ScopeError, ScopePolicy, apply_policy

app = typer.Typer(help="Configure and inspect source-grounded session memory.")
policy_app = typer.Typer(help="Preview or apply explicitly configured project scopes.")
app.add_typer(policy_app, name="policy")


DatabaseOption = Annotated[
    Path | None, typer.Option("--db", "-d", help="Database path; defaults to config")
]
ActorOption = Annotated[
    str | None, typer.Option(help="Audit identity; defaults to current OS user")
]


@policy_app.command("plan")
def policy_plan(db: DatabaseOption = None, actor: ActorOption = None) -> None:
    """Preview classifications without changing the source database."""
    _policy_command(db, actor, persist=False)


@policy_app.command("apply")
def policy_apply(db: DatabaseOption = None, actor: ActorOption = None) -> None:
    """Apply the configured project scopes and record their audit trail.

    Use policy plan first to inspect the changes. This command explicitly persists
    the classification and any required additive database migration.
    """
    _policy_command(db, actor, persist=True)


def _policy_command(db: Path | None, actor: str | None, *, persist: bool) -> None:
    config = load_config()
    policy = ScopePolicy.from_config(config)
    path = (db or get_db_path(config)).expanduser().resolve()
    if not path.is_file():
        raise typer.BadParameter(
            "Database does not exist; capture or repair sessions first"
        )
    if persist:
        conn = sqlite3.connect(path)
    else:
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn = sqlite3.connect(":memory:")
        try:
            source.backup(conn)
        finally:
            source.close()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        migrate(conn)
        result = apply_policy(
            conn, policy, actor=actor or getpass.getuser(), dry_run=not persist
        )
        typer.echo(json.dumps(result, indent=2))
    except (ScopeError, RuntimeError, sqlite3.Error) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        conn.close()


def main() -> int:
    try:
        app()
    except ScopeError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
