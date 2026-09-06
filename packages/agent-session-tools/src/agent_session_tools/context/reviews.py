"""Attributed assessments of exact interpretations; never semantic certification."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from .observations import ObservationStore
from .store import _hash, _json

if TYPE_CHECKING:
    from .public import AgentContext

VERDICTS = {"supported", "unsupported", "uncertain"}
KIND = "context.interpretation_review"


class ReviewStore:
    def __init__(self, context: AgentContext):
        self.context = context
        self.conn = context.conn
        self.observations = ObservationStore(self.conn)
        if self.conn.execute("PRAGMA user_version").fetchone()[0] < 35:
            raise RuntimeError("Review schema missing; migrate this database first")

    def target(self, kind: str, identity: str, *, as_of: str | None = None):
        from .public import text

        text(identity, "target_id", 128)
        if kind == "assertion":
            assertion = self.context._assertion(identity, as_of=as_of)
            if assertion is None:
                return None
            assertion["citations"].sort(
                key=lambda c: (c["evidence_id"], c["start_offset"], c["end_offset"])
            )
            sources = {c["evidence_id"] for c in assertion["citations"]}
            if as_of:
                for eid in sources:
                    source = self.context._source(eid)
                    if source is None or (
                        source["recorded_at"] and source["recorded_at"] > as_of
                    ):
                        return None
            return assertion, sources
        if kind != "relation":
            raise ValueError("Review target_kind must be assertion or relation")
        row = self.conn.execute(
            "SELECT * FROM context_relations WHERE id=?", (identity,)
        ).fetchone()
        if row is None:
            return None
        edge = dict(row)
        if as_of and edge["created_at"] > as_of:
            return None
        left = self.target("assertion", edge["from_assertion"], as_of=as_of)
        right = self.target("assertion", edge["to_assertion"], as_of=as_of)
        if left is None or right is None:
            return None
        return {"relation": edge, "from": left[0], "to": right[0]}, left[1] | right[1]

    def append(
        self,
        *,
        target_kind: str,
        target_id: str,
        verdict: str,
        rationale: str,
        citations: list[dict],
        producer: str,
        limitations: list[str] | None = None,
        supersedes: list[str] | None = None,
        request_id: str | None = None,
    ) -> str:
        from .public import text

        text(producer, "producer", 128)
        text(rationale, "rationale", 2000)
        text(verdict, "verdict", 32)
        if verdict not in VERDICTS:
            raise ValueError(
                "Review verdict must be supported, unsupported or uncertain"
            )
        limitations = [] if limitations is None else limitations
        supersedes = [] if supersedes is None else supersedes
        if not isinstance(limitations, list) or len(limitations) > 8:
            raise ValueError("Supply at most 8 review limitations")
        for value in limitations:
            text(value, "limitation", 500)
        if not isinstance(supersedes, list) or len(supersedes) > 8:
            raise ValueError("Supply at most 8 previous review IDs")
        for value in supersedes:
            text(value, "previous_review_id", 128)
        if request_id is not None:
            text(request_id, "request_id", 128)
        with self.context.store._atomic():
            target = self.target(target_kind, target_id)
            if target is None:
                raise ValueError("Review target is unavailable")
            bound = self.context._bind_citations(citations)
            for identity in supersedes:
                prior = self.get(identity)
                if prior is None or (prior["target_kind"], prior["target_id"]) != (
                    target_kind,
                    target_id,
                ):
                    raise ValueError(
                        "Previous review is unavailable or reviews another target"
                    )
                if prior["producer"] != producer:
                    raise ValueError(
                        "A reviewer cannot supersede another producer's assessment"
                    )
            digest = _hash(_json(target[0]))
            payload = {
                "target_kind": target_kind,
                "target_id": target_id,
                "target_sha256": digest,
                "verdict": verdict,
                "rationale": rationale,
                "limitations": limitations,
                "citations": [asdict(c) for c in bound],
            }
            identity = self.observations.append(
                kind=KIND,
                subject=f"{target_kind}:{target_id}",
                payload=payload,
                producer=producer,
                authority="model_interpretation",
                evidence_ids=sorted(target[1] | {c.evidence_id for c in bound}),
                supersedes=supersedes,
                request_key=request_id,
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO context_review_targets VALUES (?,?,?,?)",
                (
                    identity,
                    target_id if target_kind == "assertion" else None,
                    target_id if target_kind == "relation" else None,
                    digest,
                ),
            )
        return identity

    def _visible(self, as_of=None):
        scope, params = self.context.store._where(self.context.access)
        return (
            "EXISTS (SELECT 1 FROM context_observation_sources d WHERE d.observation_id=o.id) "
            "AND NOT EXISTS (SELECT 1 FROM context_observation_sources d "
            "LEFT JOIN context_evidence e ON e.id=d.evidence_id "
            "LEFT JOIN context_session_projects sp ON sp.session_id=e.session_id "
            "LEFT JOIN context_projects p ON p.id=sp.project_id WHERE d.observation_id=o.id "
            "AND (e.id IS NULL OR COALESCE((" + scope + "),0)=0 "
            "OR (? IS NOT NULL AND e.recorded_at>?)))",
            [*params, as_of, as_of],
        )

    def get(self, identity: str, *, as_of: str | None = None) -> dict | None:
        from .public import MAX_BODY_CHARS, text

        text(identity, "review_id", 128)
        clause, params = self._visible(as_of)
        row = self.conn.execute(
            "SELECT t.*,length(o.payload) AS payload_length FROM context_review_targets t "
            "JOIN context_observations o ON o.id=t.observation_id "
            "WHERE o.id=? AND o.kind=? AND (? IS NULL OR o.recorded_at<=?) AND "
            + clause,
            (identity, KIND, as_of, as_of, *params),
        ).fetchone()
        if row is None:
            return None
        if row["payload_length"] > 24000:
            raise ValueError("Review payload exceeds bounded reader size")
        deps = [
            r[0]
            for r in self.conn.execute(
                "SELECT evidence_id FROM context_observation_sources WHERE observation_id=?",
                (identity,),
            )
        ]
        for eid in deps:
            # Scope/project and size before observation text is loaded.
            size_row = self.conn.execute(
                "SELECT length(body),recorded_at FROM context_evidence WHERE id=?",
                (eid,),
            ).fetchone()
            if size_row is None or size_row[0] > MAX_BODY_CHARS:
                raise ValueError("Review source exceeds bounded reader size")
            if as_of and size_row[1] and size_row[1] > as_of:
                return None
            if self.context._source(eid) is None:
                return None
        observation = self.observations.get(identity)
        if observation is None:
            return None
        payload = observation["payload"]
        kind = "assertion" if row["assertion_id"] is not None else "relation"
        target_id = row["assertion_id"] or row["relation_id"]
        target = self.target(kind, target_id, as_of=as_of)
        if target is None:
            return None
        if (
            _hash(_json(target[0])) != row["target_sha256"]
            or payload["target_sha256"] != row["target_sha256"]
            or (payload["target_kind"], payload["target_id"]) != (kind, target_id)
            or payload["verdict"] not in VERDICTS
        ):
            raise ValueError("Review target binding failed")
        self.context._bind_citations(payload["citations"])
        current = (
            self.conn.execute(
                "SELECT 1 FROM context_observation_supersedes WHERE previous_id=? LIMIT 1",
                (identity,),
            ).fetchone()
            is None
        )
        return {
            "id": identity,
            **payload,
            "producer": observation["producer"],
            "recorded_at": observation["recorded_at"],
            "current": current,
            "supersedes": observation["supersedes"],
            "history_incomplete": observation["history_incomplete"],
            "evidence_ids": sorted(deps),
            "authority": "attributed_model_assessment",
            "reviewer_independence": "not_established",
            "validation_of_change": "not_established",
        }

    def list(
        self,
        target_kind: str,
        target_id: str,
        *,
        as_of: str | None = None,
        limit: int = 8,
        history: bool = False,
    ) -> dict:
        from .public import integer

        integer(limit, "review_limit", 1, 16)
        if self.target(target_kind, target_id, as_of=as_of) is None:
            return {"status": "unavailable", "reviews": [], "incomplete": False}
        column = "assertion_id" if target_kind == "assertion" else "relation_id"
        clause, params = self._visible(as_of)
        current = (
            ""
            if history
            else (
                " AND NOT EXISTS (SELECT 1 FROM context_observation_supersedes s WHERE s.previous_id=o.id)"
            )
        )
        rows = self.conn.execute(
            "SELECT o.id FROM context_review_targets t JOIN context_observations o ON o.id=t.observation_id "
            "WHERE t."
            + column
            + "=? AND o.kind=? AND (? IS NULL OR o.recorded_at<=?) AND "
            + clause
            + current
            + " ORDER BY o.recorded_at,o.id LIMIT ?",
            (target_id, KIND, as_of, as_of, *params, limit + 1),
        ).fetchall()
        reviews = []
        incomplete = len(rows) > limit
        for row in rows[:limit]:
            try:
                review = self.get(row[0], as_of=as_of)
            except ValueError:
                review = None
                incomplete = True
            if review is not None:
                reviews.append(review)
        verdicts = {r["verdict"] for r in reviews if r["current"]}
        state = (
            "incomplete_reviews"
            if incomplete
            else "disputed"
            if {"supported", "unsupported"} <= verdicts
            else "uncertain"
            if "uncertain" in verdicts
            else "assessed_supported"
            if verdicts == {"supported"}
            else "assessed_unsupported"
            if verdicts == {"unsupported"}
            else "unreviewed"
        )
        return {
            "status": state,
            "reviews": reviews,
            "incomplete": incomplete,
            "authority": "attributed_model_assessments",
            "independence": "not_established",
        }
