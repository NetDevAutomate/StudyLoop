"""Bounded, configured agent interface to canonical context.

All source/model strings are untrusted data. Only stored receipts establish native
origin. Configuration, not tool arguments, selects work/personal scope. This module
owns response budgets and the distinction between a recorded check and semantic
validation of a software change.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config_loader import get_db_path, load_config
from .provenance import ExecutionState, Scope
from .scope import ScopeError, active_policy, visibility_sql
from .response import read_boundary
from .store import Access, Citation, ContextStore, _hash, _json

VERSION = "session-context/v1"
MAX_BODY_CHARS = 1_000_000
MAX_CANDIDATES = 100


def text(value: Any, name: str, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(
            f"{name} must be nonempty text of at most {maximum} characters"
        )
    return value


def integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def timestamp(value: str | None, name: str, *, default_now: bool = False) -> str | None:
    if value is None:
        return datetime.now(UTC).isoformat() if default_now else None
    text(value, name, 64)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp with a timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def size(value: Any) -> int:
    return len(_json(value).encode())


@contextmanager
def open_context(
    db: Path | None = None, *, write: bool = False, project: str | None = None
):
    """Open one policy-checked snapshot, never silently migrate an agent request."""
    path = (db or get_db_path(load_config())).expanduser().resolve()
    from .managed_history import require_query_target

    require_query_target(path)
    conn = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with nullcontext() if write else read_boundary():
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            context = AgentContext(conn, project=project)
            yield context
            if write:
                # Check the resolved boundary too: default/env scope changes do
                # not alter the durable project-classification digest.
                latest = active_policy()
                if latest != context.policy or latest.request_scope() != context.scope:
                    raise ScopeError(
                        "Context scope configuration changed during the request"
                    )
                conn.commit()
    finally:
        conn.rollback()
        conn.close()


class AgentContext:
    def __init__(self, conn: sqlite3.Connection, *, project: str | None = None):
        self.conn = conn
        self.policy = active_policy()
        self.scope = self.policy.request_scope()
        # This verifies the applied policy digest and pins the request snapshot.
        visibility_sql(conn, "e.session_id", policy=self.policy, scope=self.scope)
        allowed = {p.id for p in self.policy.projects if p.scope == self.scope}
        if project is not None:
            text(project, "project", 128)
            if project not in allowed:
                raise ScopeError(
                    "Project is unavailable under the configured request scope"
                )
            allowed = {project}
        self.project = project
        self.access = Access(
            scope=self.scope,
            projects=frozenset(allowed),
            include_unassigned=self.scope == Scope.UNCLASSIFIED and project is None,
        )
        self.store = ContextStore(conn)

    def _source(self, identity: str) -> dict | None:
        """Bound body allocation before reading it; verify the full captured binding."""
        text(identity, "evidence_id", 128)
        scope, params = self.store._where(self.access)
        row = self.conn.execute(
            "SELECT length(e.body) FROM context_evidence e "
            "LEFT JOIN context_session_projects sp ON sp.session_id=e.session_id "
            "LEFT JOIN context_projects p ON p.id=sp.project_id "
            "WHERE e.id=? AND " + scope,
            (identity, *params),
        ).fetchone()
        if row is None:
            return None
        if row[0] > MAX_BODY_CHARS:
            raise ValueError("Source exceeds the bounded reader's body limit")
        return self.store.source(identity, self.access)

    @staticmethod
    def _view(source: dict, start: int, length: int, reason: dict) -> dict:
        body = source["body"]
        end = min(start + length, len(body))
        result = {
            k: source[k]
            for k in (
                "id",
                "source_key",
                "session_id",
                "harness",
                "native_kind",
                "native_locator",
                "parser_version",
                "machine_id",
                "recorded_at",
                "first_captured_at",
                "body_sha256",
                "origin",
                "call_id",
                "target",
                "revision",
                "exit_code",
                "project_id",
                "scope",
                "provenance",
            )
        }
        result.update(
            citation={
                "evidence_id": source["id"],
                "start": start,
                "end": end,
                "quote": body[start:end],
                "body_sha256": source["body_sha256"],
                "offset_unit": "Unicode code points",
            },
            excerpt_truncated=start != 0 or end < len(body),
            why_selected=reason,
            content_authority="untrusted_source_data",
        )
        return result

    def source(
        self,
        identity: str,
        *,
        start: int = 0,
        length: int = 2000,
        budget_bytes: int = 32768,
    ) -> dict:
        integer(start, "start", 0, MAX_BODY_CHARS)
        integer(length, "length", 1, 8000)
        integer(budget_bytes, "budget_bytes", 4096, 131072)
        source = self._source(identity)
        if source is None:
            return {"contract_version": VERSION, "status": "unavailable"}
        if start > len(source["body"]):
            raise ValueError("Start offset is beyond this source version")
        result = {
            "contract_version": VERSION,
            "status": "available",
            "scope": self.scope.value,
            "source": self._view(
                source, start, length, {"method": "explicit_source_id"}
            ),
        }
        if size(result) > budget_bytes:
            raise ValueError(
                "Source metadata/excerpt exceeds the response budget; reduce length"
            )
        return result

    def propose(
        self,
        *,
        statement: str,
        state: str,
        target: str | None,
        citations: list[dict],
        producer: str,
    ) -> dict:
        text(statement, "statement", 4000)
        if target is not None:
            text(target, "target", 4096)
        bound = self._bind_citations(citations)
        identity = self.store.propose(
            statement=statement,
            state=ExecutionState(state),
            target=target,
            generator=producer,
            citations=bound,
            access=self.access,
        )
        return {
            "contract_version": VERSION,
            "assertion_id": identity,
            "semantic_status": "unverified_interpretation",
        }

    def _bind_citations(self, citations: list[dict]) -> list[Citation]:
        if not isinstance(citations, list) or not 1 <= len(citations) <= 8:
            raise ValueError("Between 1 and 8 exact citations are required")
        bound = []
        for value in citations:
            if not isinstance(value, dict) or set(value) != {
                "evidence_id",
                "start",
                "end",
                "quote",
            }:
                raise ValueError("Citation accepts only evidence_id,start,end,quote")
            text(value["quote"], "quote", 2000)
            citation = Citation(**value)
            source = self._source(citation.evidence_id)
            if (
                source is None
                or source["body"][citation.start : citation.end] != citation.quote
            ):
                raise ValueError(
                    "Citation unavailable or not bound to the exact stored version"
                )
            bound.append(citation)
        return bound

    def relate(self, from_id: str, to_id: str, relation: str, *, producer: str) -> dict:
        for identity in (from_id, to_id):
            if self._assertion(identity) is None:
                raise ValueError(
                    "Relationship endpoint unavailable under the configured scope"
                )
        identity = self.store.relate(from_id, to_id, relation, producer, self.access)
        return {
            "contract_version": VERSION,
            "relation_id": identity,
            "semantic_status": "unverified_relationship",
        }

    def review(self, *, producer: str, **document) -> dict:
        from .reviews import ReviewStore

        allowed = {
            "target_kind",
            "target_id",
            "verdict",
            "rationale",
            "citations",
            "limitations",
            "supersedes",
            "request_id",
        }
        required = {"target_kind", "target_id", "verdict", "rationale", "citations"}
        if not required <= document.keys() or not document.keys() <= allowed:
            raise ValueError(
                "Review accepts target_kind,target_id,verdict,rationale,citations,"
                "limitations,supersedes,request_id only"
            )
        identity = ReviewStore(self).append(producer=producer, **document)
        return {
            "contract_version": VERSION,
            "review_id": identity,
            "authority": "attributed_model_assessment",
            "independence": "not_established",
            "validation_of_change": "not_established",
        }

    def review_history(
        self,
        target_kind: str,
        target_id: str,
        *,
        limit: int = 8,
        as_of: str | None = None,
        budget_bytes: int = 32768,
    ) -> dict:
        from .reviews import ReviewStore

        integer(budget_bytes, "budget_bytes", 4096, 131072)
        cutoff = timestamp(as_of, "as_of", default_now=True)
        reviewer = ReviewStore(self)
        target = reviewer.target(target_kind, target_id, as_of=cutoff)
        if target is None:
            return {"contract_version": VERSION, "status": "unavailable"}
        report = reviewer.list(
            target_kind, target_id, as_of=cutoff, limit=limit, history=True
        )
        result = {
            "contract_version": VERSION,
            "scope": self.scope.value,
            "as_of": cutoff,
            "target_kind": target_kind,
            "target_id": target_id,
            "target": target[0],
            "reviews": [],
            "sources": [],
            "status": report["status"],
            "incomplete": report["incomplete"],
            "independence": "not_established",
            "validation_of_change": "not_established",
        }
        seen = set()

        def include(ids):
            for eid in sorted(ids):
                if eid not in seen:
                    source = self._source(eid)
                    if source is None:
                        return False
                    result["sources"].append(
                        self._view(source, 0, 1200, {"method": "review_dependency"})
                    )
                    seen.add(eid)
            return size(result) + 512 <= budget_bytes

        if not include(target[1]):
            raise ValueError("Review target and sources exceed the requested budget")
        for review in report["reviews"]:
            before, old_seen = len(result["sources"]), seen.copy()
            result["reviews"].append(review)
            if not include(review["evidence_ids"]):
                result["reviews"].pop()
                del result["sources"][before:]
                seen = old_seen
                result["incomplete"] = True
                result["status"] = "incomplete_reviews"
        result["response_bytes"] = 0
        for _ in range(4):
            result["response_bytes"] = size(result)
        if size(result) > budget_bytes:
            raise ValueError("Review response exceeds the requested budget")
        return result

    def _assertion(self, identity: str, *, as_of: str | None = None) -> dict | None:
        text(identity, "assertion_id", 128)
        # Inspect lengths, not protected prose, before delegating full exact checks.
        row = self.conn.execute(
            "SELECT length(a.statement),count(c.evidence_id),max(length(c.quote)),"
            "max(length(e.body)) FROM context_assertions a "
            "JOIN context_citations c ON c.assertion_id=a.id "
            "JOIN context_evidence e ON e.id=c.evidence_id WHERE a.id=? "
            "AND (? IS NULL OR a.created_at<=?) GROUP BY a.id",
            (identity, as_of, as_of),
        ).fetchone()
        if row is None:
            return None
        if row[0] > 4000 or row[1] > 8 or row[2] > 2000 or row[3] > MAX_BODY_CHARS:
            return None
        return self.store.assertion(identity, self.access)

    def _health(self) -> dict:
        """Only aggregate visible sources; global operator counters are not agent context."""
        scope, params = self.store._where(self.access)
        row = self.conn.execute(
            "SELECT count(*),max(e.recorded_at),max(e.first_captured_at) FROM context_evidence e "
            "LEFT JOIN context_session_projects sp ON sp.session_id=e.session_id "
            "LEFT JOIN context_projects p ON p.id=sp.project_id WHERE " + scope,
            params,
        ).fetchone()
        return {
            "visible_records": row[0],
            "latest_visible_source_at": row[1],
            "latest_visible_capture_at": row[2],
            "hook_liveness": "not_established",
            "archive_completeness": "not_established",
            "operator_diagnostics": "session-context health",
        }

    def search(
        self,
        query: str,
        *,
        max_sources: int = 12,
        budget_bytes: int = 32768,
        as_of: str | None = None,
        extra_ids: list[str] | None = None,
        extra_reason: str = "requested_check_metadata",
    ) -> dict:
        from .collection import collect
        from .selection import select

        text(query, "query")
        integer(max_sources, "max_sources", 1, 40)
        integer(budget_bytes, "budget_bytes", 4096, 131072)
        cutoff = timestamp(as_of, "as_of", default_now=True)
        assert cutoff is not None
        if extra_reason not in {"requested_check_metadata", "requested_assertion"}:
            raise ValueError("Unknown internal source selection reason")
        pool = collect(
            self, query, cutoff, extra_ids=extra_ids, extra_reason=extra_reason
        )
        return select(pool, max_sources, budget_bytes, policy="anchor_then_relations")

    def assess(
        self,
        query: str,
        assertion_ids: list[str],
        *,
        budget_bytes: int = 32768,
        as_of: str | None = None,
    ) -> dict:
        """Render attributed interpretation support and unresolved conflicts, not truth."""
        integer(budget_bytes, "budget_bytes", 16384, 131072)
        if not isinstance(assertion_ids, list) or not 1 <= len(assertion_ids) <= 8:
            raise ValueError("Supply between 1 and 8 assertion IDs")
        for identity in assertion_ids:
            text(identity, "assertion_id", 128)
        assertion_ids = list(dict.fromkeys(assertion_ids))
        cutoff = timestamp(as_of, "as_of", default_now=True)
        source_ids = []
        for identity in assertion_ids:
            assertion = self._assertion(identity, as_of=cutoff)
            if assertion is not None:
                source_ids.extend(c["evidence_id"] for c in assertion["citations"])
        pack = self.search(
            query,
            max_sources=40,
            budget_bytes=budget_bytes - 6000,
            as_of=cutoff,
            extra_ids=list(dict.fromkeys(source_ids)),
            extra_reason="requested_assertion",
        )
        candidates = {a["id"]: a for a in pack["assertions"]}
        claims = []
        for identity in assertion_ids:
            assertion = candidates.get(identity)
            claims.append(
                {
                    "assertion_id": identity,
                    "review_status": assertion.get("review_status", "unreviewed")
                    if assertion
                    else "unavailable_or_not_returned",
                    "review_ids": assertion.get("review_ids", []) if assertion else [],
                    "related_proposals": [
                        edge["id"]
                        for edge in pack["relationships"]
                        if edge["relation"] != "supports"
                        and identity in (edge["from_assertion"], edge["to_assertion"])
                    ],
                }
            )
        states = {claim["review_status"] for claim in claims}
        state = (
            "incomplete_evidence"
            if pack["coverage"]["limits_reached"]
            or states.intersection(
                {"incomplete_reviews", "unavailable_or_not_returned"}
            )
            else "disputed_reviews"
            if "disputed" in states
            else "proposed_conflict_requires_interpretation"
            if any(c["related_proposals"] for c in claims)
            else "unsupported_by_available_reviews"
            if "assessed_unsupported" in states
            else "attributed_support_available"
            if states == {"assessed_supported"}
            else "review_needed"
        )
        pack["assessment"] = {
            "kind": "attributed_interpretation_assessment",
            "status": state,
            "claims": claims,
            "semantic_validation": "not_established",
            "reviewer_independence": "not_established",
            "validation_of_change": "not_established",
            "explanation": {
                "incomplete_evidence": "Required context or reviews are missing or bounded. Do not infer complete support.",
                "disputed_reviews": "Available current assessments disagree; vote count and recency do not choose a winner.",
                "proposed_conflict_requires_interpretation": "A proposed contrary/correction relation remains inspectable alongside its reviews.",
                "unsupported_by_available_reviews": "At least one requested interpretation is unsupported by its available current assessments.",
                "attributed_support_available": "Available current assessments support these interpretations. Present this as attributed inference, not verified fact.",
                "review_needed": "At least one interpretation is unreviewed or uncertain. Inspect its citations and missing evidence.",
            }[state],
            "execution_checks": "Use memory_decide with explicit command, project, immutable revision and time requirements.",
            "evaluated_snapshot_id": pack["snapshot_id"],
        }
        pack["assessment_id"] = _hash(_json(pack["assessment"]))
        for _ in range(4):
            pack["response_bytes"] = size(pack)
        if size(pack) > budget_bytes:
            raise ValueError("Assessment exceeds the requested budget")
        return pack

    def decide(
        self,
        query: str,
        requirements: list[dict],
        *,
        budget_bytes: int = 32768,
        as_of: str | None = None,
    ) -> dict:
        """Assess explicitly requested execution checks, never approve a software change.

        Requirements describe the caller's question, not trusted source metadata.
        No model-supplied origin/revision/validation result is accepted as evidence.
        The response is rendered in code from the same scoped evidence snapshot.
        """
        integer(budget_bytes, "budget_bytes", 16384, 131072)
        cutoff = timestamp(as_of, "as_of", default_now=True)
        assert cutoff is not None
        if not isinstance(requirements, list) or not 1 <= len(requirements) <= 8:
            raise ValueError("Supply between 1 and 8 execution requirements")
        normalized = []
        names = set()
        for requirement in requirements:
            required = {
                "name",
                "project_id",
                "target",
                "revision",
                "expected_exit_code",
            }
            if (
                not isinstance(requirement, dict)
                or not required <= set(requirement)
                or (set(requirement) - required - {"not_before"})
            ):
                raise ValueError(
                    "Requirement fields: name,project_id,target,revision,expected_exit_code,optional not_before"
                )
            name = text(requirement["name"], "requirement name", 128)
            if name in names:
                raise ValueError("Requirement names must be unique")
            names.add(name)
            project = text(requirement["project_id"], "project_id", 128)
            if project not in (self.access.projects or frozenset()):
                raise ScopeError(
                    "Requirement project unavailable under the configured scope"
                )
            target = text(requirement["target"], "target", 4096)
            revision = text(requirement["revision"], "revision", 64)
            if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
                raise ValueError(
                    "Revision must be a full immutable commit hash; branch names are not identities"
                )
            code = integer(
                requirement["expected_exit_code"], "expected_exit_code", -65536, 65536
            )
            not_before = timestamp(requirement.get("not_before"), "not_before")
            if not_before and not_before > cutoff:
                raise ValueError("not_before must not be later than as_of")
            normalized.append(
                dict(
                    name=name,
                    project_id=project,
                    target=target,
                    revision=revision.lower(),
                    expected_exit_code=code,
                    not_before=not_before,
                )
            )
        reserve = size(normalized) + 6000
        if budget_bytes - reserve < 4096:
            raise ValueError("Requirements exceed this decision budget")
        scope, params = self.store._where(self.access)
        extra = []
        scan_capped = False
        for requirement in normalized:
            rows = self.conn.execute(
                "SELECT e.id FROM context_evidence e "
                "JOIN context_session_projects sp ON sp.session_id=e.session_id "
                "JOIN context_projects p ON p.id=sp.project_id WHERE "
                + scope
                + " AND p.id=? AND e.target=? AND (e.recorded_at IS NULL OR e.recorded_at<=?) "
                "ORDER BY e.recorded_at DESC,e.id LIMIT ?",
                (
                    *params,
                    requirement["project_id"],
                    requirement["target"],
                    cutoff,
                    MAX_CANDIDATES + 1,
                ),
            ).fetchall()
            scan_capped |= len(rows) > MAX_CANDIDATES
            extra.extend(row[0] for row in rows[:MAX_CANDIDATES])
        pack = self.search(
            query,
            max_sources=40,
            budget_bytes=budget_bytes - reserve,
            as_of=cutoff,
            extra_ids=list(dict.fromkeys(extra)),
        )
        checks = []
        for requirement in normalized:
            outcomes: dict[str, list[str]] = {
                "matched": [],
                "different_exit": [],
                "unknown": [],
                "inapplicable": [],
            }
            for source in pack["sources"]:
                if (
                    source["project_id"] != requirement["project_id"]
                    or source["target"] != requirement["target"]
                ):
                    continue
                revision = source["revision"]
                recorded = source["recorded_at"]
                if (
                    source["origin"] != "process_exit"
                    or revision is None
                    or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision)
                    or (requirement["not_before"] and recorded is None)
                ):
                    kind = "unknown"
                elif revision.lower() != requirement["revision"] or (
                    requirement["not_before"] and recorded < requirement["not_before"]
                ):
                    kind = "inapplicable"
                elif source["exit_code"] == requirement["expected_exit_code"]:
                    kind = "matched"
                else:
                    kind = "different_exit"
                outcomes[kind].append(source["id"])
            status = (
                "conflicting_records"
                if outcomes["matched"] and outcomes["different_exit"]
                else "recorded_match"
                if outcomes["matched"]
                else "recorded_mismatch"
                if outcomes["different_exit"]
                else "insufficient_metadata"
            )
            checks.append(
                {"requirement": requirement, "status": status, "source_ids": outcomes}
            )
        incomplete = bool(pack["coverage"]["limits_reached"]) or scan_capped
        conflicts = any(check["status"] == "conflicting_records" for check in checks)
        matched = all(check["status"] == "recorded_match" for check in checks)
        sufficiency = (
            "conflicting_records"
            if conflicts
            else (
                "incomplete_evidence"
                if incomplete
                else "recorded_checks_satisfied"
                if matched
                else "checks_not_established"
            )
        )
        pack["decision"] = {
            "kind": "execution_contract_assessment",
            "sufficiency": sufficiency,
            "checks": checks,
            "metadata_scan_capped": scan_capped,
            "explanation": {
                "conflicting_records": "Applicable archive records disagree. Recency does not choose a winner.",
                "incomplete_evidence": "Evidence was omitted by a bound. This response cannot establish all requested checks.",
                "recorded_checks_satisfied": "Captured records match the requested command, project, revision, time constraints and exit codes.",
                "checks_not_established": "The captured records do not establish every requested execution check.",
            }[sufficiency],
            "validation_of_change": "not_established",
            "limitation": "A matching execution record does not establish test adequacy, semantic correctness or permission to ship.",
            "next_check": "Inspect cited checks, resolve contrary records and capture missing applicable validation.",
            "evaluated_snapshot_id": pack["snapshot_id"],
        }
        pack["decision_id"] = _hash(_json(pack["decision"]))
        for _ in range(4):
            pack["response_bytes"] = size(pack)
        if size(pack) > budget_bytes:
            raise ValueError(
                "Decision exceeds the requested budget; narrow the requirements"
            )
        return pack
