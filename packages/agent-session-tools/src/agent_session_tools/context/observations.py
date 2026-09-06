"""Source-linked interpretations and explicitly owned reports, independent of StudyLoop.

Source ownership is resolved on every read. A source link proves which captured
input contributed, not that the interpretation is correct. Supersession is an
explicit recorded update, never an inference from timestamp ordering.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from .provenance import Scope
from .scope import ScopeError, ScopePolicy, _audit, active_policy, visibility_sql
from .store import Access, ContextStore, _hash, _json, _now, _text


class ObservationStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.sources = ContextStore(conn)
        if conn.execute("PRAGMA user_version").fetchone()[0] < 33:
            raise RuntimeError(
                "Observation schema missing; migrate this database first"
            )

    def _session_owners_available(self) -> bool:
        return bool(
            self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='context_observation_session_owners'"
            ).fetchone()
        )

    def _session_owner(self, identity: str) -> str | None:
        if not self._session_owners_available():
            return None
        row = self.conn.execute(
            "SELECT session_id FROM context_observation_session_owners WHERE observation_id=?",
            (identity,),
        ).fetchone()
        return row[0] if row else None

    def _visible(
        self, policy: ScopePolicy, scope: Scope, *, _include_withdrawn=False
    ) -> tuple[str, list[Any]]:
        from .withdrawal_gate import predicate
        from .scope import _visibility_sql

        source_clause, source_values = _visibility_sql(
            self.conn,
            "e.session_id",
            policy=policy,
            scope=scope,
            withdrawals=not _include_withdrawn,
        )
        source_clause = (
            "("
            + source_clause
            + " AND "
            + ("1" if _include_withdrawn else predicate(self.conn, "evidence", "e.id"))
            + ")"
        )
        project_ids = [p.id for p in policy.projects if p.scope == scope]
        project_clause = "0"
        project_values: list[Any] = []
        if project_ids:
            project_clause = (
                "p.scope=? AND p.id IN (" + ",".join("?" for _ in project_ids) + ")"
            )
            project_values = [scope.value, *project_ids]
        session_clause = "0"
        session_values: list[Any] = []
        if self._session_owners_available():
            native, session_values = _visibility_sql(
                self.conn,
                "native_owner.session_id",
                policy=policy,
                scope=scope,
                withdrawals=not _include_withdrawn,
            )
            session_clause = (
                "EXISTS (SELECT 1 FROM context_observation_session_owners native_owner "
                "JOIN sessions native ON native.id=native_owner.session_id "
                "WHERE native_owner.observation_id=o.id AND " + native + ")"
            )
        clause = f"""NOT EXISTS (SELECT 1 FROM context_observation_tombstones t
          WHERE t.observation_id=o.id) AND (
          (EXISTS (SELECT 1 FROM context_observation_sources r WHERE r.observation_id=o.id)
           AND NOT EXISTS (SELECT 1 FROM context_observation_sources r
             LEFT JOIN context_evidence e ON e.id=r.evidence_id
             WHERE r.observation_id=o.id AND (e.id IS NULL OR NOT {source_clause})))
          OR (NOT EXISTS (SELECT 1 FROM context_observation_sources r WHERE r.observation_id=o.id)
            AND EXISTS (SELECT 1 FROM context_observation_owners ow
              LEFT JOIN context_projects p ON p.id=ow.project_id
              WHERE ow.observation_id=o.id AND (ow.fixed_scope=? OR ({project_clause}))))
          OR {session_clause}
        )"""
        from .records import observation_clause

        records_clause, records_values = observation_clause(
            self.conn,
            policy,
            scope=scope,
            _include_withdrawn=_include_withdrawn,
        )
        return "(" + clause + ") AND " + records_clause + " AND " + (
            "1" if _include_withdrawn else predicate(self.conn, "observation", "o.id")
        ), [
            *source_values,
            scope.value,
            *project_values,
            *session_values,
            *records_values,
        ]

    def _refs(self, identity: str) -> tuple[list[str], list[str]]:
        sources = [
            r[0]
            for r in self.conn.execute(
                "SELECT evidence_id FROM context_observation_sources WHERE observation_id=? ORDER BY evidence_id",
                (identity,),
            )
        ]
        previous = [
            r[0]
            for r in self.conn.execute(
                "SELECT previous_id FROM context_observation_supersedes WHERE observation_id=? ORDER BY previous_id",
                (identity,),
            )
        ]
        return sources, previous

    def _checked(
        self,
        row: dict[str, Any],
        policy: ScopePolicy,
        scope: Scope,
        *,
        visible_snapshot: tuple[str, list[Any]] | None = None,
    ) -> dict[str, Any]:
        refs, previous = self._refs(row["id"])
        binding = {
            k: row[k]
            for k in (
                "kind",
                "subject",
                "payload",
                "producer",
                "authority",
                "recorded_at",
            )
        }
        binding.update(sources=refs, supersedes=previous)
        if (
            _hash(_json(binding)) != row["binding_sha256"]
            or _hash(_json([row["kind"], row["subject"]])) != row["subject_sha256"]
        ):
            raise ValueError("Stored observation binding failed")
        access = Access(scope=scope)
        sources = []
        for identity in refs:
            source = self.sources.source(identity, access)
            if source is None:
                raise ScopeError("Observation source unavailable in current scope")
            sources.append(
                {
                    "id": identity,
                    "session_id": source["session_id"],
                    "body_sha256": source["body_sha256"],
                    "origin": source["origin"],
                    "native_locator": source["native_locator"],
                    "recorded_at": source["recorded_at"],
                }
            )
        owner = self.conn.execute(
            "SELECT project_id,fixed_scope FROM context_observation_owners WHERE observation_id=?",
            (row["id"],),
        ).fetchone()
        visible, values = visible_snapshot or self._visible(policy, scope)
        visible_previous = [
            identity
            for identity in previous
            if self.conn.execute(
                "SELECT 1 FROM context_observations o WHERE o.id=? AND " + visible,
                [identity, *values],
            ).fetchone()
        ]
        record_dependencies = []
        if self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='context_record_observations'"
        ).fetchone():
            record_dependencies = [
                {"owner_id": r[0], "table": r[1], "record_id": r[2]}
                for r in self.conn.execute(
                    "SELECT dep.id,dep.table_name,dep.row_id FROM context_record_observations link "
                    "JOIN context_record_owners dep ON dep.id=link.record_id "
                    "WHERE link.observation_id=? ORDER BY dep.id",
                    (row["id"],),
                )
            ]
        session_owner = self._session_owner(row["id"])
        return {
            **row,
            "payload": json.loads(row["payload"]),
            "sources": sources,
            "source_relationship": "about_session"
            if session_owner
            else "captured_input"
            if refs
            else "none",
            "supersedes": visible_previous,
            "history_incomplete": len(visible_previous) != len(previous),
            "owner": {"session_id": session_owner}
            if session_owner
            else {"project_id": owner[0], "fixed_scope": owner[1]}
            if owner
            else None,
            "scope": scope.value,
            "semantic_status": "unverified_interpretation"
            if row["authority"] == "model_interpretation"
            else "reported_assessment",
            "why_available": "owning session is visible"
            if session_owner
            else "all contributing sources are visible"
            if refs
            else "explicit owner scope",
            **(
                {"record_dependencies": record_dependencies}
                if record_dependencies
                else {}
            ),
        }

    def get(self, identity: str) -> dict[str, Any] | None:
        policy = active_policy()
        scope = policy.request_scope()
        clause, values = self._visible(policy, scope)
        rows = self.sources._rows(
            "SELECT o.* FROM context_observations o WHERE o.id=? AND " + clause,
            [identity, *values],
        )
        return self._checked(rows[0], policy, scope) if rows else None

    def list(
        self, kind: str, *, subject: str | None = None, current: bool = True
    ) -> list[dict[str, Any]]:
        policy = active_policy()
        scope = policy.request_scope()
        clause, values = self._visible(policy, scope)
        predicates = ["o.kind=?", clause]
        params = [kind, *values]
        if subject is not None:
            predicates.append("o.subject=?")
            params.append(subject)
        if current:
            # Content-free retirement survives a hidden or forgotten successor.
            predicates.append(
                "NOT EXISTS (SELECT 1 FROM context_observation_supersedes v WHERE v.previous_id=o.id)"
            )
        rows = self.sources._rows(
            "SELECT o.* FROM context_observations o WHERE "
            + " AND ".join(predicates)
            + " ORDER BY o.recorded_at,o.id",
            params,
        )
        return [self._checked(row, policy, scope) for row in rows]

    def append(
        self,
        *,
        kind: str,
        subject: str,
        payload: dict[str, Any],
        producer: str,
        authority: str,
        evidence_ids: Sequence[str] = (),
        supersedes: Sequence[str] = (),
        request_key: str | None = None,
        owner_path: Path | None = None,
        owner_session_id: str | None = None,
    ) -> str:
        """Trusted adapter operation; scope is never supplied by model payload.

        Without source dependencies, the current configured project or explicit
        request scope owns the report. With dependencies, every source must be
        visible before the observation body can be stored.
        """
        for value, name in (
            (kind, "kind"),
            (subject, "subject"),
            (producer, "producer"),
        ):
            _text(value, name)
        if authority not in ("reported", "model_interpretation"):
            raise ValueError("Invalid observation authority")
        if not isinstance(payload, dict):
            raise ValueError("Observation payload must be an object")
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if len(encoded.encode()) > 256_000:
            raise ValueError("Observation payload exceeds 256000 bytes")
        if kind in (
            "session.annotation.note",
            "session.annotation.tags",
            "session.annotation.learning",
        ):
            if owner_session_id != subject or authority != "reported":
                raise ValueError(
                    "Session annotations require their named session owner and reported authority"
                )
            if kind.endswith(".note") and (
                not isinstance(payload.get("notes"), str)
                or set(payload) - {"notes", "legacy_updated_at"}
            ):
                raise ValueError("Session note requires notes text")
            if kind.endswith(".tags") and (
                set(payload) != {"tags"}
                or not isinstance(payload["tags"], list)
                or any(not isinstance(t, str) or not t for t in payload["tags"])
            ):
                raise ValueError("Session tags require a list of nonempty text tags")
        refs, previous = sorted(set(evidence_ids)), sorted(set(supersedes))
        if owner_session_id is not None:
            _text(owner_session_id, "owner_session_id")
            if refs or owner_path:
                raise ValueError(
                    "Session ownership cannot also claim captured inputs or a path owner"
                )
            if not self._session_owners_available():
                raise RuntimeError(
                    "Session observation ownership needs database migration"
                )
        if authority == "model_interpretation" and not refs:
            raise ValueError(
                "Model interpretations require captured source dependencies"
            )
        with self.sources._atomic():
            policy = active_policy()
            scope = policy.request_scope()
            visible, values = visibility_sql(
                self.conn, "e.session_id", policy=policy, scope=scope
            )
            from .withdrawal_gate import predicate

            visible += " AND " + predicate(self.conn, "evidence", "e.id")
            if owner_session_id is not None:
                owner_visible, owner_values = visibility_sql(
                    self.conn, "s.id", policy=policy, scope=scope
                )
                if not self.conn.execute(
                    "SELECT 1 FROM sessions s WHERE s.id=? AND " + owner_visible,
                    [owner_session_id, *owner_values],
                ).fetchone():
                    raise ScopeError("Annotation session unavailable in current scope")
            for identity in refs:
                if not self.conn.execute(
                    "SELECT 1 FROM context_evidence e WHERE e.id=? AND " + visible,
                    [identity, *values],
                ).fetchone():
                    raise ScopeError("Observation source unavailable in current scope")
                self.sources.source(
                    identity, Access(scope=scope)
                )  # verify immutable binding
            for identity in previous:
                prior = self.get(identity)
                if (
                    prior is None
                    or prior["kind"] != kind
                    or prior["subject"] != subject
                    or (
                        (
                            owner_session_id is not None
                            or (prior["owner"] or {}).get("session_id") is not None
                        )
                        and (prior["owner"] or {}).get("session_id") != owner_session_id
                    )
                ):
                    raise ScopeError(
                        "Revision target unavailable or belongs to another subject"
                    )
            project = policy.project_for_path(owner_path or Path.cwd())
            if owner_path and project and project.scope != scope:
                raise ScopeError(
                    "Observation working directory is outside the requested scope"
                )
            if project is not None and project.scope != scope:
                project = None  # The explicit process scope outranks CWD defaults.
            owner = (
                None
                if refs
                else [project.id if project else None, None if project else scope.value]
            )
            if owner_session_id is not None:
                owner = ["session", owner_session_id]
            stable = {
                "kind": kind,
                "subject": subject,
                "payload": encoded,
                "producer": producer,
                "authority": authority,
                "sources": refs,
                "supersedes": previous,
                "initial_owner": owner,
                "request_key": request_key or uuid4().hex,
            }
            identity = _hash(_json(stable))
            if self.conn.execute(
                "SELECT 1 FROM context_observation_tombstones WHERE observation_id=?",
                (identity,),
            ).fetchone():
                raise ValueError("Observation was forgotten")
            if self.conn.execute(
                "SELECT 1 FROM context_observations WHERE id=?", (identity,)
            ).fetchone():
                if self.get(identity) is None:
                    raise ScopeError(
                        "Existing observation unavailable in current scope"
                    )
                return identity
            stamp = _now()
            binding = {
                k: stable[k]
                for k in (
                    "kind",
                    "subject",
                    "payload",
                    "producer",
                    "authority",
                    "sources",
                    "supersedes",
                )
            }
            binding["recorded_at"] = stamp
            self.conn.execute(
                "INSERT INTO context_observations VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    kind,
                    subject,
                    encoded,
                    producer,
                    authority,
                    stamp,
                    _hash(_json(binding)),
                    _hash(_json([kind, subject])),
                ),
            )
            self.conn.executemany(
                "INSERT INTO context_observation_sources VALUES (?,?)",
                [(identity, ref) for ref in refs],
            )
            self.conn.executemany(
                "INSERT INTO context_observation_supersedes VALUES (?,?)",
                [(identity, prior) for prior in previous],
            )
            if owner_session_id is not None:
                self.conn.execute(
                    "INSERT INTO context_observation_session_owners VALUES (?,?)",
                    (identity, owner_session_id),
                )
            elif owner is not None:
                self.conn.execute(
                    "INSERT INTO context_observation_owners VALUES (?,?,?)",
                    [identity, *owner],
                )
                _audit(
                    self.conn,
                    action="observation_owner",
                    subject=identity,
                    before=None,
                    after=owner,
                    actor=producer,
                    digest=policy.digest,
                )
            return identity

    def assign(
        self,
        identity: str,
        *,
        actor: str,
        project_id: str | None = None,
        scope: Scope | None = None,
    ) -> None:
        """Trusted local administration; source-linked records follow their sources."""
        _text(actor, "actor")
        if (project_id is None) == (scope is None):
            raise ValueError("Choose exactly one explicit project or scope")
        with self.sources._atomic():
            if self.get(identity) is None:
                raise ScopeError("Observation unavailable in current scope")
            if self._refs(identity)[0]:
                raise ValueError(
                    "Source-linked ownership must follow the source assignment"
                )
            if self._session_owner(identity):
                raise ValueError(
                    "Session-owned observations follow their session assignment"
                )
            policy = active_policy()
            if project_id is not None and project_id not in {
                p.id for p in policy.projects
            }:
                raise ScopeError("Destination project is not configured")
            if scope is not None and not isinstance(scope, Scope):
                raise ValueError("Invalid explicit scope")
            old = self.conn.execute(
                "SELECT project_id,fixed_scope FROM context_observation_owners WHERE observation_id=?",
                (identity,),
            ).fetchone()
            after = [project_id, scope.value if scope else None]
            self.conn.execute(
                "UPDATE context_observation_owners SET project_id=?,fixed_scope=? WHERE observation_id=?",
                [*after, identity],
            )
            _audit(
                self.conn,
                action="observation_owner",
                subject=identity,
                before=list(old),
                after=after,
                actor=actor,
                digest=policy.digest,
            )

    def forget(self, identity: str) -> bool:
        """Purge one observation locally; source/sync/backup lifecycle is separate."""
        with self.sources._atomic():
            if self.get(identity) is None:
                return False
            self.conn.execute(
                "DELETE FROM context_observations WHERE id=?", (identity,)
            )
            return True
