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
from .capture import capture_health
from .scope import ScopeError, ScopePolicy, apply_policy
from .public import open_context
from .store import _json

app = typer.Typer(help="Configure and inspect source-grounded session memory.")
policy_app = typer.Typer(help="Preview or apply explicitly configured project scopes.")
app.add_typer(policy_app, name="policy")


DatabaseOption = Annotated[
    Path | None, typer.Option("--db", "-d", help="Database path; defaults to config")
]
ActorOption = Annotated[
    str | None, typer.Option(help="Audit identity; defaults to current OS user")
]


@app.command("annotations")
def annotation_history(
    session_id: str,
    db: DatabaseOption = None,
    kind: str = "note",
    max_bytes: int = 32768,
) -> None:
    """Inspect reported annotations, corrections and conflicting current versions."""
    from .annotations import view

    with open_context(db) as context:
        result = view(context.conn, session_id, kind=kind, max_bytes=max_bytes)
    typer.echo(_json(result))


@app.command("health")
def health(db: DatabaseOption = None) -> None:
    """Read body-free operator capture diagnostics without migrating the database."""
    path = (db or get_db_path(load_config())).expanduser().resolve()
    if not path.is_file():
        raise typer.BadParameter("Database does not exist")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        typer.echo(json.dumps(capture_health(conn), indent=2))
    finally:
        conn.close()


@app.command("search")
def search(
    query: str,
    db: DatabaseOption = None,
    project: str | None = None,
    max_sources: int = 12,
    budget_bytes: int = 32768,
    as_of: str | None = None,
) -> None:
    """Retrieve bounded, scoped native context with exact citations and explanations."""
    with open_context(db, project=project) as context:
        typer.echo(
            _json(
                context.search(
                    query,
                    max_sources=max_sources,
                    budget_bytes=budget_bytes,
                    as_of=as_of,
                )
            )
        )


@app.command("source")
def source(
    evidence_id: str,
    db: DatabaseOption = None,
    project: str | None = None,
    start: int = 0,
    length: int = 2000,
    budget_bytes: int = 32768,
) -> None:
    """Read an exact excerpt of a visible immutable source version."""
    with open_context(db, project=project) as context:
        typer.echo(
            _json(
                context.source(
                    evidence_id, start=start, length=length, budget_bytes=budget_bytes
                )
            )
        )


def _input(path: Path):
    if path.stat().st_size > 65536:
        raise ValueError("Input document exceeds 64KiB")
    return json.loads(path.read_text())


@app.command("propose")
def propose(
    document: Path, db: DatabaseOption = None, project: str | None = None
) -> None:
    """Store an unverified interpretation backed by exact source citations.

    JSON document fields: statement,state,target,citations. Source provenance cannot
    be supplied or changed by a proposal. Citation fields: evidence_id,start,end,quote.
    """
    value = _input(document)
    if not isinstance(value, dict) or set(value) != {
        "statement",
        "state",
        "target",
        "citations",
    }:
        raise ValueError("Proposal accepts only statement,state,target,citations")
    with open_context(db, write=True, project=project) as context:
        result = context.propose(**value, producer="agent:session-context-cli")
    typer.echo(_json(result))


@app.command("relate")
def relate(
    from_id: str,
    to_id: str,
    relation: str,
    db: DatabaseOption = None,
    project: str | None = None,
) -> None:
    """Propose supports, contradicts or corrects; never silently adopt a correction."""
    with open_context(db, write=True, project=project) as context:
        result = context.relate(
            from_id, to_id, relation, producer="agent:session-context-cli"
        )
    typer.echo(_json(result))


@app.command("decide")
def decide(
    query: str,
    requirements: Path,
    db: DatabaseOption = None,
    project: str | None = None,
    budget_bytes: int = 32768,
    as_of: str | None = None,
) -> None:
    """Assess a JSON list of execution requirements against captured records.

    Each requirement needs name,project_id,target,revision,expected_exit_code and
    optional not_before. A matched execution contract does not validate a change.
    """
    value = _input(requirements)
    with open_context(db, project=project) as context:
        typer.echo(
            _json(context.decide(query, value, budget_bytes=budget_bytes, as_of=as_of))
        )


@app.command("review")
def review(
    document: Path, db: DatabaseOption = None, project: str | None = None
) -> None:
    """Record a source-bound assessment; this never supplies human or native authority."""
    value = _input(document)
    if not isinstance(value, dict) or "producer" in value:
        raise ValueError("Review must be an object without a producer override")
    with open_context(db, write=True, project=project) as context:
        result = context.review(producer="agent:session-context-cli", **value)
    typer.echo(_json(result))


@app.command("reviews")
def reviews(
    target_kind: str,
    target_id: str,
    db: DatabaseOption = None,
    project: str | None = None,
    limit: int = 8,
    budget_bytes: int = 32768,
    as_of: str | None = None,
) -> None:
    """Inspect bounded review history for an assertion or relationship."""
    with open_context(db, project=project) as context:
        typer.echo(
            _json(
                context.review_history(
                    target_kind,
                    target_id,
                    limit=limit,
                    budget_bytes=budget_bytes,
                    as_of=as_of,
                )
            )
        )


@app.command("assess")
def assess(
    query: str,
    assertions: Path,
    db: DatabaseOption = None,
    project: str | None = None,
    budget_bytes: int = 32768,
    as_of: str | None = None,
) -> None:
    """Assess a JSON list of assertion IDs using attributed reviews and contrary proposals."""
    value = _input(assertions)
    with open_context(db, project=project) as context:
        typer.echo(
            _json(context.assess(query, value, budget_bytes=budget_bytes, as_of=as_of))
        )


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
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
