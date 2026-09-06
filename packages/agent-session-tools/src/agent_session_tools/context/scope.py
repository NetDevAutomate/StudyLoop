"""Explicit local scope configuration, audited application and reusable SQL guards.

Queries never infer scope from a harness or query text. Configuration and an
explicit process scope override are local-owner inputs, not MCP tool parameters.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config_loader import load_config
from .provenance import Scope, ScopeAssignment
from .store import ContextStore


class ScopeError(ValueError):
    """Missing, invalid or unapplied explicit scope configuration."""


@dataclass(frozen=True)
class ProjectPolicy:
    id: str
    scope: Scope
    roots: tuple[Path, ...]


@dataclass(frozen=True)
class ScopePolicy:
    projects: tuple[ProjectPolicy, ...]
    default_scope: Scope | None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ScopePolicy:
        memory = config.get("memory", {})
        if not isinstance(memory, dict):
            raise ScopeError("memory must be a mapping")
        raw_scope = memory.get("default_scope")
        try:
            default = Scope(raw_scope) if raw_scope is not None else None
        except (TypeError, ValueError) as exc:
            raise ScopeError(
                "memory.default_scope must be personal, work, unclassified or null"
            ) from exc
        raw_projects = memory.get("projects", {})
        if not isinstance(raw_projects, dict):
            raise ScopeError("memory.projects must be a mapping of project IDs")
        projects = []
        owners: dict[Path, str] = {}
        if any(not isinstance(identity, str) for identity in raw_projects):
            raise ScopeError("Project IDs must be strings")
        for identity, raw in sorted(raw_projects.items()):
            if not isinstance(identity, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identity
            ):
                raise ScopeError(
                    "Project IDs must be stable names using letters, digits, dot, dash or underscore"
                )
            if not isinstance(raw, dict) or "scope" not in raw:
                raise ScopeError(f"Project {identity} requires an explicit scope")
            try:
                scope = Scope(raw["scope"])
            except (ValueError, TypeError) as exc:
                raise ScopeError(f"Invalid scope for project {identity}") from exc
            roots = raw.get("roots", [])
            if not isinstance(roots, list) or any(
                not isinstance(root, str) or not root.strip() for root in roots
            ):
                raise ScopeError(
                    f"Project {identity} roots must be a list of absolute paths"
                )
            paths = []
            for root in roots:
                path = Path(os.path.expandvars(root)).expanduser()
                if not path.is_absolute():
                    raise ScopeError(f"Project {identity} root must be absolute")
                path = path.resolve()
                if path in owners and owners[path] != identity:
                    raise ScopeError("The same root cannot belong to two projects")
                owners[path] = identity
                paths.append(path)
            projects.append(ProjectPolicy(identity, scope, tuple(sorted(set(paths)))))
        return cls(tuple(projects), default)

    @property
    def digest(self) -> str:
        # Current request/default scope does not reclassify stored sources. Only
        # project definitions belong in the durable classification fingerprint.
        payload = {
            p.id: {"scope": p.scope.value, "roots": [str(root) for root in p.roots]}
            for p in self.projects
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def project_for_path(self, value: str | Path | None) -> ProjectPolicy | None:
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            return None
        path = path.resolve()
        matches = [
            (len(root.parts), p)
            for p in self.projects
            for root in p.roots
            if path == root or root in path.parents
        ]
        return max(matches, key=lambda item: item[0])[1] if matches else None

    def request_scope(
        self, *, cwd: Path | None = None, override: str | None = None
    ) -> Scope:
        from .response import observe_scope

        explicit = (
            override if override is not None else os.getenv("SESSION_CONTEXT_SCOPE")
        )
        if explicit is not None:
            try:
                resolved = Scope(explicit)
            except ValueError as exc:
                raise ScopeError(
                    "SESSION_CONTEXT_SCOPE must be personal, work or unclassified"
                ) from exc
            return observe_scope(self, resolved)
        project = self.project_for_path(cwd or Path.cwd())
        if project:
            return observe_scope(self, project.scope)
        if self.default_scope is not None:
            return observe_scope(self, self.default_scope)
        raise ScopeError(
            "No context scope configured. Set memory.default_scope or a project root in "
            "config.yaml, then use session-context policy apply. Scope is never inferred from a harness."
        )


def active_policy() -> ScopePolicy:
    # Do not reuse query_db's lazy cache: scope revocation/configuration changes
    # must take effect on the next request in a long-running MCP process.
    from .response import observe_policy

    policy = ScopePolicy.from_config(load_config())
    observe_policy(policy)
    return policy


def _table(conn: sqlite3.Connection, name: str, schema: str) -> bool:
    return (
        conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _visibility_sql(
    conn: sqlite3.Connection,
    session_column: str = "s.id",
    *,
    schema: str = "main",
    policy: ScopePolicy | None = None,
    scope: Scope | None = None,
    withdrawals: bool = True,
) -> tuple[str, list[Any]]:
    """Predicate for a session ID expression; filter before selecting any body.

    The schema/column are internal SQL identifiers, never user-supplied query text.
    Legacy databases are inspectable in explicit unclassified scope only when no
    project definitions are configured. Otherwise apply the policy first. A stored
    fingerprint attests applied project definitions, not every session assignment.
    The caller must close or end the transaction after the request; the guard pins
    a read snapshot through the subsequent source query.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*", schema) or not re.fullmatch(
        r"[A-Za-z_]\w*\.[A-Za-z_]\w*", session_column
    ):
        raise ValueError("Invalid internal scope SQL identifier")
    policy = policy or active_policy()
    scope = scope or policy.request_scope()
    # Keep the policy head, assignments and subsequent body query in the same
    # snapshot even for callers that did not explicitly start a read transaction.
    if not conn.in_transaction:
        conn.execute("BEGIN")
    has_state = _table(conn, "context_policy_state", schema)
    if has_state:
        row = conn.execute(
            f"SELECT digest FROM {schema}.context_policy_state WHERE id=1"
        ).fetchone()
        if row is None or row[0] != policy.digest:
            raise ScopeError(
                "Project scope configuration has changed; run session-context policy apply before querying this database"
            )
    elif policy.projects:
        raise ScopeError(
            "Project scope policy is not applied; run session-context policy apply"
        )
    has_assignments = _table(conn, "context_session_projects", schema)
    params: list[Any] = []
    if not has_assignments:
        if scope != Scope.UNCLASSIFIED:
            raise ScopeError(
                "This database needs migration and scope classification; run session-context policy apply"
            )
        predicate = "1"
    else:
        ids = [project.id for project in policy.projects if project.scope == scope]
        assigned = "0"
        if ids:
            assigned = f"""{session_column} IN (
                SELECT sp.session_id FROM {schema}.context_session_projects sp
                JOIN {schema}.context_projects p ON p.id=sp.project_id
                WHERE p.scope=? AND p.id IN ({",".join("?" for _ in ids)}))"""
            params = [scope.value, *ids]
        if scope == Scope.UNCLASSIFIED:
            unassigned = f"""NOT EXISTS (SELECT 1 FROM {schema}.context_session_projects sp
                WHERE sp.session_id={session_column})"""
            predicate = f"({unassigned} OR {assigned})"
        else:
            predicate = assigned
    if _table(conn, "context_tombstones", schema):
        predicate += f""" AND NOT EXISTS (SELECT 1 FROM {schema}.context_tombstones tomb
            WHERE tomb.session_id={session_column})"""
    from .response import observe_database, observe_scope
    from .withdrawal_gate import predicate as withdrawal_predicate

    if withdrawals:
        predicate += " AND " + withdrawal_predicate(
            conn, "session", session_column, schema=schema
        )

    observe_scope(policy, scope)
    observe_database(conn, schema)
    return "(" + predicate + ")", params


def visibility_sql(
    conn: sqlite3.Connection,
    session_column: str = "s.id",
    *,
    schema: str = "main",
    policy: ScopePolicy | None = None,
    scope: Scope | None = None,
) -> tuple[str, list[Any]]:
    """Filter current scope, permanent retirement and withdrawal before body reads."""
    return _visibility_sql(
        conn, session_column, schema=schema, policy=policy, scope=scope
    )


def retirement_selection_sql(
    conn: sqlite3.Connection, *, policy: ScopePolicy, scope: Scope
) -> tuple[str, list[Any]]:
    """Internal ID/count-only selection for explicit forget, including quarantine.

    A withheld source must remain forgettable within the configured scope. This
    predicate never authorizes returning its body or restoring its permission.
    """
    return _visibility_sql(conn, "s.id", policy=policy, scope=scope, withdrawals=False)


def _audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    subject: str,
    before: Any,
    after: Any,
    actor: str,
    digest: str,
) -> None:
    conn.execute(
        "INSERT INTO context_scope_audit VALUES (?,?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            action,
            subject,
            json.dumps(before, sort_keys=True),
            json.dumps(after, sort_keys=True),
            actor,
            digest,
            datetime.now(UTC).isoformat(),
        ),
    )


def apply_policy(
    conn: sqlite3.Connection, policy: ScopePolicy, *, actor: str, dry_run: bool = True
) -> dict[str, Any]:
    """Preview or atomically apply explicit project roots and scope classification.

    Non-root assignments (explicit/remote) are preserved when no local root matches.
    Removed projects are retained unclassified, with assignments preserved, so a
    stale inbound row cannot revive its earlier personal/work classification.
    """
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("A policy change requires an actor")
    if not _table(conn, "context_policy_state", "main"):
        raise ScopeError("Migrate the database before applying a scope policy")
    store = ContextStore(conn)
    with store._atomic():
        existing = {
            r[0]: {"scope": r[1], "policy_id": r[2]}
            for r in conn.execute("SELECT id,scope,policy_id FROM context_projects")
        }
        changes = []
        configured = {p.id: p for p in policy.projects}
        for identity in sorted(set(existing) | set(configured)):
            project = configured.get(identity)
            after = {
                "scope": project.scope.value if project else Scope.UNCLASSIFIED.value,
                "policy_id": policy.digest,
            }
            if existing.get(identity) != after:
                changes.append(
                    {
                        "kind": "project",
                        "id": identity,
                        "before": existing.get(identity),
                        "after": after,
                    }
                )
        assignments = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                "SELECT session_id,project_id,assignment_kind FROM context_session_projects"
            )
        }
        for sid, path in conn.execute("SELECT id,project_path FROM sessions"):
            project = policy.project_for_path(path)
            old = assignments.get(sid)
            if old and old[1] == "explicit":
                # A deliberate per-session assignment outranks a root default.
                after = old
            else:
                after = (
                    (project.id, "root_policy")
                    if project
                    else (None if old and old[1] == "root_policy" else old)
                )
            if old != after:
                changes.append(
                    {"kind": "session", "id": sid, "before": old, "after": after}
                )
        report = {
            "dry_run": dry_run,
            "policy_digest": policy.digest,
            "changes": changes,
        }
        if dry_run:
            return report
        for change in changes:
            if change["kind"] == "project":
                store.configure_project(
                    ScopeAssignment(
                        scope=Scope(change["after"]["scope"]),
                        project_id=change["id"],
                        policy_id=policy.digest,
                    )
                )
            elif change["after"] is None:
                conn.execute(
                    "DELETE FROM context_session_projects WHERE session_id=?",
                    (change["id"],),
                )
            else:
                project_id, kind = change["after"]
                conn.execute(
                    """INSERT INTO context_session_projects(session_id,project_id,assignment_kind)
                    VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                    project_id=excluded.project_id,assignment_kind=excluded.assignment_kind""",
                    (change["id"], project_id, kind),
                )
            _audit(
                conn,
                action=change["kind"],
                subject=change["id"],
                before=change["before"],
                after=change["after"],
                actor=actor,
                digest=policy.digest,
            )
        conn.execute(
            "UPDATE context_policy_state SET digest=?,applied_at=? WHERE id=1",
            (policy.digest, datetime.now(UTC).isoformat()),
        )
        return report
