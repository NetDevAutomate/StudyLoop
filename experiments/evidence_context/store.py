"""Offline evidence-context experiment. Never opens a production database to write.

Only keyword retrieval and explicitly reviewed relationships are implemented.
Byte budgets describe canonical UTF-8 JSON, not model tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _time(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include an explicit timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class EvidenceRecord:
    message_id: str
    session_id: str
    harness: str
    project: str
    scope: str
    content: str
    timestamp: str | None
    source_locator: str
    role: str = "assistant"
    lineage_id: str | None = None
    seq: int | None = None
    available_at: str | None = None


@dataclass(frozen=True)
class Citation:
    version_id: str
    content_hash: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Relationship:
    source_id: str
    target_id: str
    kind: str
    supporting_citations: tuple[Citation, ...]
    asserted_at: str | None
    origin: str = "unknown"
    review_state: str = "unreviewed"
    extractor_version: str = "unspecified"
    reviewer: str | None = None
    available_at: str | None = None


@dataclass(frozen=True)
class EvidenceItem:
    version_id: str
    message_id: str
    session_id: str
    harness: str
    project: str
    scope: str
    timestamp: str | None
    available_at: str | None
    source_locator: str
    role: str
    lineage_id: str | None
    content_hash: str
    citation: Citation
    retrieval_reasons: tuple[str, ...]
    verification_status: str = "unverified_report"

    @property
    def content(self) -> str:
        """The returned exact excerpt, never an inferred summary."""
        return self.citation.text


@dataclass(frozen=True)
class EvidencePack:
    status: str
    evidence: tuple[EvidenceItem, ...] = ()
    relationships: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    exclusions: dict[str, int] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def byte_size(self) -> int:
        return len(self.to_json().encode("utf-8"))


class EvidenceStore:
    """Append-only experimental store: source versions and citations are immutable."""

    VERSION_SIBLING_LIMIT = 64

    KINDS = frozenset(
        {"mentioned_with", "supports", "contradicts", "corrects", "supersedes", "depends_on"}
    )

    def __init__(self, path: Path, conn: sqlite3.Connection):
        self.path = path
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def create(cls, path: str | Path) -> EvidenceStore:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        store = cls(path, sqlite3.connect(path))
        store.conn.executescript("""
        CREATE TABLE experiment_meta(name TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO experiment_meta VALUES('format','evidence-context-v1');
        CREATE TABLE evidence(
          version_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
          message_id TEXT NOT NULL, session_id TEXT NOT NULL, harness TEXT NOT NULL,
          project TEXT NOT NULL, scope TEXT NOT NULL, content TEXT NOT NULL,
          timestamp TEXT, source_locator TEXT NOT NULL, role TEXT NOT NULL,
          lineage_id TEXT, seq INTEGER, available_at TEXT
        );
        CREATE VIRTUAL TABLE evidence_fts USING fts5(version_id UNINDEXED,content);
        CREATE TABLE relationships(
          relationship_id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL REFERENCES evidence(version_id),
          target_id TEXT NOT NULL REFERENCES evidence(version_id),
          kind TEXT NOT NULL, asserted_at TEXT, available_at TEXT,
          origin TEXT NOT NULL, review_state TEXT NOT NULL,
          extractor_version TEXT NOT NULL, reviewer TEXT, citations_json TEXT NOT NULL
        );
        CREATE INDEX evidence_scope ON evidence(project,scope,timestamp,available_at);
        CREATE INDEX relationship_source ON relationships(source_id);
        CREATE INDEX relationship_target ON relationships(target_id);
        """)
        return store

    @classmethod
    def open(cls, path: str | Path) -> EvidenceStore:
        path = Path(path).resolve()
        # mode=rw avoids accidentally creating a file at a wrong source path.
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
        try:
            row = conn.execute("SELECT value FROM experiment_meta WHERE name='format'").fetchone()
            if row is None or row[0] != "evidence-context-v1":
                raise ValueError("Not an evidence-context experiment database")
        except Exception:
            conn.close()
            raise
        return cls(path, conn)

    def close(self) -> None:
        self.conn.close()

    def add_evidence(self, record: EvidenceRecord) -> str:
        data = asdict(record)
        for key in (
            "message_id",
            "session_id",
            "harness",
            "project",
            "scope",
            "content",
            "source_locator",
            "role",
        ):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError(f"Explicit nonempty {key} required")
        if record.seq is not None and (not isinstance(record.seq, int) or record.seq < 0):
            raise ValueError("seq must be a nonnegative integer or unknown")
        data["timestamp"] = _time(record.timestamp)
        data["available_at"] = _time(record.available_at)
        content_hash = _hash(record.content)
        version_id = _hash(canonical_json(data))
        data.update(version_id=version_id, content_hash=content_hash)
        with self.conn:
            if not self.conn.execute(
                "SELECT 1 FROM evidence WHERE version_id=?", (version_id,)
            ).fetchone():
                columns = list(data)
                self.conn.execute(
                    f"INSERT INTO evidence({','.join(columns)}) "
                    f"VALUES({','.join('?' for _ in columns)})",
                    [data[key] for key in columns],
                )
                self.conn.execute(
                    "INSERT INTO evidence_fts VALUES(?,?)", (version_id, record.content)
                )
        return version_id

    def _row(self, version_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM evidence WHERE version_id=?", (version_id,)
        ).fetchone()
        if row is None:
            raise KeyError(version_id)
        return row

    def cite(self, version_id: str, start: int = 0, end: int | None = None) -> Citation:
        row = self._row(version_id)
        if _hash(row["content"]) != row["content_hash"]:
            raise ValueError("Stored evidence content hash mismatch")
        end = len(row["content"]) if end is None else end
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end > len(row["content"])
            or start >= end
        ):
            raise ValueError("Citation must name a nonempty exact character span")
        return Citation(version_id, row["content_hash"], start, end, row["content"][start:end])

    def resolve_citation(self, citation: Citation) -> str:
        resolved = self.cite(citation.version_id, citation.start, citation.end)
        if resolved != citation:
            raise ValueError("Citation hash, span, or text does not match frozen evidence")
        return resolved.text

    def add_relationship(self, relationship: Relationship) -> str:
        if relationship.kind not in self.KINDS:
            raise ValueError("Unsupported relationship kind; verification is not inferred")
        if not relationship.supporting_citations:
            raise ValueError("Relationships require supporting source spans")
        if relationship.origin not in {"asserted", "inferred", "unknown"}:
            raise ValueError("Unknown relationship origin")
        if relationship.review_state not in {"reviewed", "unreviewed", "rejected"}:
            raise ValueError("Unknown review state")
        if relationship.review_state == "reviewed" and not relationship.reviewer:
            raise ValueError("Reviewed relationships require an explicit reviewer")
        for reference in relationship.supporting_citations:
            self.resolve_citation(reference)
        self._row(relationship.source_id)
        self._row(relationship.target_id)
        data = asdict(relationship)
        data["asserted_at"] = _time(relationship.asserted_at)
        data["available_at"] = _time(relationship.available_at)
        relationship_id = _hash(canonical_json(data))
        data["citations_json"] = canonical_json(data.pop("supporting_citations"))
        data["relationship_id"] = relationship_id
        with self.conn:
            columns = list(data)
            self.conn.execute(
                f"INSERT OR IGNORE INTO relationships({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                [data[key] for key in columns],
            )
        return relationship_id

    @staticmethod
    def _eligible(row: sqlite3.Row, project: str, scope: str, cutoff: str | None) -> bool:
        if row["project"] != project or row["scope"] != scope:
            return False
        return cutoff is None or (
            row["timestamp"] is not None
            and row["available_at"] is not None
            and row["timestamp"] <= cutoff
            and row["available_at"] <= cutoff
        )

    def _item(
        self, row: sqlite3.Row, reasons: tuple[str, ...], terms: list[str], excerpt_chars: int
    ) -> EvidenceItem:
        content = row["content"]
        lower = content.lower()
        positions = [lower.find(term.lower()) for term in terms if term.lower() in lower]
        start = max(0, min(positions, default=0) - 160)
        if len(content) <= excerpt_chars:
            start = 0
        end = min(len(content), start + excerpt_chars)
        return EvidenceItem(
            **{
                key: row[key]
                for key in (
                    "version_id",
                    "message_id",
                    "session_id",
                    "harness",
                    "project",
                    "scope",
                    "timestamp",
                    "available_at",
                    "source_locator",
                    "role",
                    "lineage_id",
                    "content_hash",
                )
            },
            citation=self.cite(row["version_id"], start, end),
            retrieval_reasons=reasons,
        )

    def retrieve(
        self,
        query: str,
        *,
        project: str,
        scope: str,
        as_of: str | None = None,
        max_bytes: int = 8000,
        limit: int = 8,
        use_relationships: bool = False,
        max_hops: int = 1,
        neighbor_turns: int = 1,
        excerpt_chars: int = 1200,
    ) -> EvidencePack:
        """Build one evidence pack from one consistent SQLite read snapshot."""
        owns_transaction = not self.conn.in_transaction
        if owns_transaction:
            self.conn.execute("BEGIN")
        try:
            return self._retrieve(
                query,
                project=project,
                scope=scope,
                as_of=as_of,
                max_bytes=max_bytes,
                limit=limit,
                use_relationships=use_relationships,
                max_hops=max_hops,
                neighbor_turns=neighbor_turns,
                excerpt_chars=excerpt_chars,
            )
        finally:
            if owns_transaction:
                self.conn.rollback()

    def _retrieve(
        self,
        query: str,
        *,
        project: str,
        scope: str,
        as_of: str | None = None,
        max_bytes: int = 8000,
        limit: int = 8,
        use_relationships: bool = False,
        max_hops: int = 1,
        neighbor_turns: int = 1,
        excerpt_chars: int = 1200,
    ) -> EvidencePack:
        if not project or not scope:
            raise ValueError("Explicit project and scope required")
        if (
            not 1 <= limit <= 100
            or not 0 <= max_hops <= 3
            or not 0 <= neighbor_turns <= 3
            or not 1 <= excerpt_chars <= 10000
        ):
            raise ValueError("Retrieval bounds exceeded")
        cutoff = _time(as_of)
        terms = re.findall(r"\w+", query, flags=re.UNICODE)[:32]
        manifest = {
            "arm": "C" if use_relationships else "A",
            "semantic_retrieval": "not_run",
            "budget_unit": "utf8_bytes",
            "citation_span_unit": "unicode_codepoints",
            "as_of": cutoff,
            "relationship_origin": "reviewed_assertions_only",
        }
        selected: dict[str, EvidenceItem] = {}
        selected_edges: dict[str, dict[str, Any]] = {}
        warnings: set[str] = set()
        exclusions = {
            "budget": 0,
            "scope_or_time": 0,
            "unreviewed_relationship": 0,
            "duplicate_lineage": 0,
        }

        def pack() -> EvidencePack:
            return EvidencePack(
                "ok" if selected else "no_evidence",
                tuple(selected.values()),
                tuple(selected_edges.values()),
                tuple(sorted(warnings)),
                dict(exclusions),
                manifest,
            )

        if pack().byte_size > max_bytes:
            raise ValueError("Byte budget cannot hold an empty evidence pack")

        def attempt(
            rows: list[sqlite3.Row], reason: str, edge: dict[str, Any] | None = None
        ) -> bool:
            if not all(self._eligible(row, project, scope, cutoff) for row in rows):
                return False
            before = dict(selected)
            edge_before = dict(selected_edges)
            warnings_before = set(warnings)
            for row in rows:
                if row["version_id"] in selected:
                    continue
                if not self._eligible(row, project, scope, cutoff):
                    return False
                duplicate = next(
                    (
                        item
                        for item in selected.values()
                        if row["lineage_id"]
                        and item.lineage_id == row["lineage_id"]
                        and item.content_hash == row["content_hash"]
                    ),
                    None,
                )
                if duplicate:
                    if edge is not None:
                        selected.clear()
                        selected.update(before)
                        return False
                    exclusions["duplicate_lineage"] += 1
                    continue
                selected[row["version_id"]] = self._item(row, (reason,), terms, excerpt_chars)
                if row["timestamp"] is None or row["available_at"] is None:
                    warnings.add("unknown_time_or_availability")
                if any(
                    item.version_id != row["version_id"]
                    and item.harness == row["harness"]
                    and item.session_id == row["session_id"]
                    and item.message_id == row["message_id"]
                    and item.content_hash != row["content_hash"]
                    for item in selected.values()
                ):
                    warnings.add("conflicting_source_versions")
            if edge:
                selected_edges[edge["relationship_id"]] = edge
                if edge["kind"] in {"contradicts", "corrects", "supersedes"}:
                    warnings.add("conflicting_or_revised_evidence")
            if len(selected) > limit or pack().byte_size > max_bytes - 192:
                selected.clear()
                selected.update(before)
                selected_edges.clear()
                selected_edges.update(edge_before)
                warnings.clear()
                warnings.update(warnings_before)
                exclusions["budget"] += 1
                warnings.add("context_incomplete")
                if edge and edge["kind"] in {"contradicts", "corrects", "supersedes"}:
                    warnings.add("counterevidence_omitted_due_to_budget")
                return False
            return True

        candidates = []
        if terms:
            fts = " OR ".join('"' + term + '"' for term in terms)
            sql = (
                "SELECT e.* FROM evidence_fts JOIN evidence e USING(version_id) "
                "WHERE evidence_fts MATCH ? AND e.project=? AND e.scope=?"
            )
            params: list[Any] = [fts, project, scope]
            if cutoff:
                sql += (
                    " AND e.timestamp IS NOT NULL AND e.available_at IS NOT NULL "
                    "AND e.timestamp<=? AND e.available_at<=?"
                )
                params.extend([cutoff, cutoff])
            sql += " ORDER BY bm25(evidence_fts),e.timestamp,e.version_id LIMIT ?"
            params.append(min(256, max(32, limit * 8)))
            candidates = list(self.conn.execute(sql, params))
        # Seeds use the same ranking in both arms. Relationship expansion is
        # interleaved per seed so a complete small chain can compete for budget.
        for seed in candidates:
            if not attempt([seed], "fts"):
                continue
            variant_sql = (
                "SELECT * FROM evidence WHERE harness=? AND session_id=? AND message_id=? "
                "AND project=? AND scope=?"
            )
            variant_params: list[Any] = [
                seed["harness"],
                seed["session_id"],
                seed["message_id"],
                project,
                scope,
            ]
            if cutoff:
                variant_sql += (
                    " AND timestamp IS NOT NULL AND available_at IS NOT NULL "
                    "AND timestamp<=? AND available_at<=?"
                )
                variant_params.extend([cutoff, cutoff])
            variant_sql += " ORDER BY version_id LIMIT ?"
            variant_params.append(self.VERSION_SIBLING_LIMIT + 1)
            variants = list(self.conn.execute(variant_sql, variant_params))
            if len(variants) > self.VERSION_SIBLING_LIMIT:
                warnings.update({"context_incomplete", "source_versions_omitted_due_to_limit"})
            for variant in variants[: self.VERSION_SIBLING_LIMIT]:
                attempt([variant], "source_variant")
            if use_relationships:
                frontier = [seed["version_id"]]
                visited: set[str] = set()
                for _ in range(max_hops):
                    following = []
                    for version_id in frontier:
                        if version_id in visited:
                            continue
                        visited.add(version_id)
                        edges = self.conn.execute(
                            "SELECT * FROM relationships WHERE source_id=? OR target_id=? "
                            "ORDER BY CASE kind WHEN 'contradicts' THEN 0 "
                            "WHEN 'corrects' THEN 1 ELSE 2 END,relationship_id LIMIT 64",
                            (version_id, version_id),
                        )
                        for relation in edges:
                            references = [
                                Citation(**value)
                                for value in json.loads(relation["citations_json"])
                            ]
                            rows = [
                                self._row(value)
                                for value in dict.fromkeys(
                                    [
                                        relation["source_id"],
                                        relation["target_id"],
                                        *(ref.version_id for ref in references),
                                    ]
                                )
                            ]
                            # Hidden scopes and future evidence do not contribute
                            # counts or labels to the returned diagnostics.
                            if not all(self._eligible(row, project, scope, cutoff) for row in rows):
                                continue
                            if cutoff and (
                                relation["asserted_at"] is None
                                or relation["available_at"] is None
                                or relation["asserted_at"] > cutoff
                                or relation["available_at"] > cutoff
                            ):
                                continue
                            if (
                                relation["review_state"] != "reviewed"
                                or relation["origin"] != "asserted"
                                or not relation["reviewer"]
                            ):
                                exclusions["unreviewed_relationship"] += 1
                                continue
                            for reference in references:
                                self.resolve_citation(reference)
                            edge = {
                                key: relation[key]
                                for key in (
                                    "relationship_id",
                                    "source_id",
                                    "target_id",
                                    "kind",
                                    "asserted_at",
                                    "available_at",
                                    "origin",
                                    "review_state",
                                    "extractor_version",
                                    "reviewer",
                                )
                            }
                            edge["supporting_citations"] = [asdict(ref) for ref in references]
                            if attempt(rows, "relationship", edge):
                                following.extend([relation["source_id"], relation["target_id"]])
                    frontier = following
            if neighbor_turns and seed["seq"] is not None:
                neighbors = self.conn.execute(
                    "SELECT * FROM evidence WHERE harness=? AND session_id=? "
                    "AND seq BETWEEN ? AND ? ORDER BY seq,version_id LIMIT 32",
                    (
                        seed["harness"],
                        seed["session_id"],
                        seed["seq"] - neighbor_turns,
                        seed["seq"] + neighbor_turns,
                    ),
                )
                for neighbor in neighbors:
                    if self._eligible(neighbor, project, scope, cutoff):
                        attempt([neighbor], "adjacent_turn")
        result = pack()
        if result.byte_size > max_bytes:
            raise ValueError("Byte budget too small for retrieval diagnostics")
        return result
