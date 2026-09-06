"""Disposable lifecycle lab; trusted replicas, fixed scope, no production transport.

Tombstones form a grow-only set. Version parents express causality; timestamps
only filter visibility. Derived objects declare every source they depend on.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import TYPE_CHECKING, Any

from .store import _time, canonical_json

if TYPE_CHECKING:
    from pathlib import Path


class Replica:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def create(cls, path: Path) -> Replica:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        replica = cls(path)
        replica.conn.executescript("""
        CREATE TABLE sources(id TEXT PRIMARY KEY, scope TEXT NOT NULL);
        CREATE TABLE tombstones(source TEXT PRIMARY KEY REFERENCES sources(id));
        CREATE TABLE versions(id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES sources(id),
            parent TEXT REFERENCES versions(id) DEFERRABLE INITIALLY DEFERRED,
            body TEXT NOT NULL, available TEXT NOT NULL, reason TEXT NOT NULL);
        CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, body);
        CREATE TABLE artifacts(id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE dependencies(artifact TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
            source TEXT REFERENCES sources(id), PRIMARY KEY(artifact, source));
        """)
        return replica

    def close(self) -> None:
        self.conn.close()

    def _source(self, source: str, scope: str) -> None:
        if not source or scope not in {"personal", "work", "unclassified"}:
            raise ValueError("Explicit stable source identity and scope required")
        previous = self.conn.execute("SELECT scope FROM sources WHERE id=?", (source,)).fetchone()
        if previous and previous[0] != scope:
            raise ValueError("Scope reclassification is not implemented")
        self.conn.execute("INSERT OR IGNORE INTO sources VALUES (?,?)", (source, scope))

    def forgotten(self, source: str) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM tombstones WHERE source=?", (source,)).fetchone()
            is not None
        )

    def _invalidate(self, source: str) -> None:
        self.conn.execute(
            "DELETE FROM artifacts WHERE id IN (SELECT artifact FROM dependencies WHERE source=?)",
            (source,),
        )

    def add(
        self,
        source: str,
        scope: str,
        body: str,
        available: str,
        parent: str | None = None,
        reason: str = "",
    ) -> str | None:
        """Return None for stale re-import of a forgotten identity."""
        with self.conn:
            return self._add(source, scope, body, available, parent, reason)

    def _add(
        self, source: str, scope: str, body: str, available: str, parent: str | None, reason: str
    ) -> str | None:
        self._source(source, scope)
        if self.forgotten(source):
            return None
        available = _time(available)  # type: ignore[assignment]
        if not available or not body:
            raise ValueError("Body and explicit availability required")
        if parent:
            row = self.conn.execute(
                "SELECT source,available FROM versions WHERE id=?", (parent,)
            ).fetchone()
            if not row or row[0] != source or available < row[1] or not reason:
                raise ValueError(
                    "Correction needs an existing same-source parent, reason "
                    "and nondecreasing availability"
                )
        values = {
            "source": source,
            "parent": parent,
            "body": body,
            "available": available,
            "reason": reason,
        }
        identity = hashlib.sha256(canonical_json(values).encode()).hexdigest()
        if not self.conn.execute("SELECT 1 FROM versions WHERE id=?", (identity,)).fetchone():
            self._invalidate(source)
            self.conn.execute(
                "INSERT INTO versions VALUES (?,?,?,?,?,?)",
                (identity, source, parent, body, available, reason),
            )
            self.conn.execute("INSERT INTO search VALUES (?,?)", (identity, body))
        return identity

    def forget(self, source: str, scope: str) -> None:
        with self.conn:
            self._forget(source, scope)

    def _forget(self, source: str, scope: str) -> None:
        self._source(source, scope)
        self.conn.execute("INSERT OR IGNORE INTO tombstones VALUES (?)", (source,))
        self._invalidate(source)
        self.conn.execute(
            "DELETE FROM search WHERE id IN (SELECT id FROM versions WHERE source=?)", (source,)
        )
        self.conn.execute("DELETE FROM versions WHERE source=?", (source,))

    def heads(self, source: str, as_of: str | None = None) -> list[dict[str, Any]]:
        cutoff = _time(as_of)
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM versions WHERE source=? ORDER BY id", (source,)
            )
        ]
        visible = [r for r in rows if cutoff is None or r["available"] <= cutoff]
        parents = {r["parent"] for r in visible}
        return [r for r in visible if r["id"] not in parents]

    def lookup(self, version: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM versions WHERE id=?", (version,)).fetchone()
        return dict(row) if row else None

    def search(self, term: str) -> list[str]:
        # This lab searches all remaining versions. heads() is current selection.
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT id FROM search WHERE search MATCH ? ORDER BY id",
                ('"' + term.replace('"', '""') + '"',),
            )
        ]

    def derive(self, identity: str, kind: str, body: str, sources: list[str]) -> None:
        if not sources:
            raise ValueError("Derived content must declare source dependencies")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            for source in sources:
                if self.forgotten(source) or not self.heads(source):
                    raise ValueError("Cannot derive from missing or forgotten source")
            self.conn.execute("INSERT INTO artifacts VALUES (?,?,?)", (identity, kind, body))
            self.conn.executemany(
                "INSERT INTO dependencies VALUES (?,?)", [(identity, s) for s in set(sources)]
            )

    def rebuild(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM search")
            self.conn.execute("INSERT INTO search SELECT id,body FROM versions")

    def export(self, scopes: set[str]) -> str:
        """Filter before serialization; no excluded body enters the transfer."""
        with self.conn:
            self.conn.execute("BEGIN")
            sources = [
                dict(r)
                for r in self.conn.execute("SELECT * FROM sources ORDER BY id")
                if r["scope"] in scopes
            ]
            allowed = {s["id"] for s in sources}
            deleted = [
                r[0]
                for r in self.conn.execute("SELECT source FROM tombstones ORDER BY source")
                if r[0] in allowed
            ]
            versions = [
                dict(r)
                for r in self.conn.execute("SELECT * FROM versions ORDER BY id")
                if r["source"] in allowed
            ]
        return canonical_json(
            {"format": 1, "sources": sources, "deleted": deleted, "versions": versions}
        )

    def receive(self, payload: str, scopes: set[str]) -> None:
        """Atomic application of a trusted lab snapshot; parent-order independent."""
        data = json.loads(payload)
        if data["format"] != 1:
            raise ValueError("Unsupported transfer format")
        source_scopes = {s["id"]: s["scope"] for s in data["sources"]}
        if any(scope not in scopes for scope in source_scopes.values()):
            raise ValueError("Transfer outside receiver scope policy")
        with self.conn:
            for source, scope in source_scopes.items():
                self._source(source, scope)
            for source in data["deleted"]:
                self._forget(source, source_scopes[source])
            pending = list(data["versions"])
            while pending:
                next_round = []
                for row in pending:
                    source = row["source"]
                    scope = source_scopes[source]
                    if self.forgotten(source):
                        continue
                    parent = row["parent"]
                    if parent and not self.lookup(parent):
                        next_round.append(row)
                        continue
                    identity = self._add(
                        source, scope, row["body"], row["available"], parent, row["reason"]
                    )
                    if identity != row["id"]:
                        raise ValueError("Corrupt version identity")
                if next_round and len(next_round) == len(pending):
                    raise ValueError("Missing or cyclic version parents")
                pending = next_round
