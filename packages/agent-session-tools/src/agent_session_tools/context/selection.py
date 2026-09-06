"""Pack already authorized evidence groups; selection never verifies their meaning."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .store import _hash, _json

MAX_ASSERTIONS = 24
MAX_RELATIONS = 24
POLICIES = ("lexical_first", "reserve_20", "anchor_then_relations")


def size(value) -> int:
    return len(_json(value).encode())


@dataclass
class EvidencePool:
    """Internal collector result. Every item and dependency is scoped and time-filtered."""

    base: dict
    sources: dict[str, dict]
    lexical_ids: list[str]
    check_ids: list[str]
    assertions: dict[str, dict]
    relations: list[dict]
    limits: set[str]
    reviews: dict[str, dict] = field(default_factory=dict)


def select(
    pool: EvidencePool, max_sources: int, budget_bytes: int, *, policy: str
) -> dict:
    if policy not in POLICIES:
        raise ValueError("Unknown internal evidence selection policy")
    result = deepcopy(pool.base)
    result.update(
        sources=[], assertions=[], relationships=[], reviews=[], selection_policy=policy
    )
    result["context_status"] = "incomplete_context"
    result["conflict_review"] = {
        "status": "coverage_limited",
        "known_proposed_relations": 0,
        "returned_proposed_relations": 0,
        "omitted_proposed_relations": 0,
        "semantic_conflict_absence_established": False,
    }
    selected = {
        "sources": set(),
        "assertions": set(),
        "relationships": set(),
        "reviews": set(),
    }
    bounds = {
        "sources": max_sources,
        "assertions": MAX_ASSERTIONS,
        "relationships": MAX_RELATIONS,
        "reviews": 16,
    }

    def bundle(source_ids=(), assertion_ids=(), edges=()):
        # All dependencies are inserted together or none of this group is inserted.
        aids = list(dict.fromkeys(assertion_ids))
        review_ids = list(
            dict.fromkeys(
                [
                    *(
                        rid
                        for aid in aids
                        for rid in pool.assertions[aid].get("review_ids", [])
                    ),
                    *(rid for edge in edges for rid in edge.get("review_ids", [])),
                ]
            )
        )
        ids = list(
            dict.fromkeys(
                [
                    *source_ids,
                    *(
                        eid
                        for rid in review_ids
                        for eid in pool.reviews[rid]["evidence_ids"]
                    ),
                    *(
                        c["evidence_id"]
                        for aid in aids
                        for c in pool.assertions[aid]["citations"]
                    ),
                ]
            )
        )
        return {
            "sources": [pool.sources[eid] for eid in ids],
            "assertions": [pool.assertions[aid] for aid in aids],
            "relationships": list(edges),
            "reviews": [pool.reviews[rid] for rid in review_ids],
        }

    lexical = [bundle([eid]) for eid in pool.lexical_ids]
    checks = [bundle([eid]) for eid in pool.check_ids]
    relations = [
        bundle(
            assertion_ids=[edge["from_assertion"], edge["to_assertion"]], edges=[edge]
        )
        for edge in pool.relations
    ]
    contrary = [g for g in relations if g["relationships"][0]["relation"] != "supports"]
    supporting = [
        g for g in relations if g["relationships"][0]["relation"] == "supports"
    ]
    assertions = [bundle(assertion_ids=[aid]) for aid in pool.assertions]

    def attempt(
        group, *, source_limit=max_sources, byte_limit=budget_bytes, persist=True
    ):
        added = {
            key: [item for item in group[key] if item["id"] not in selected[key]]
            for key in selected
        }
        reasons = {
            key
            for key in selected
            if len(selected[key]) + len(added[key])
            > (source_limit if key == "sources" else bounds[key])
        }
        if reasons:
            return reasons
        for key in selected:
            result[key].extend(added[key])
        # Reserve final coverage, status, identity and byte-count fields.
        fits = size(result) + 1024 <= byte_limit
        if not fits or not persist:
            for key in selected:
                if added[key]:
                    del result[key][-len(added[key]) :]
        else:
            for key in selected:
                selected[key].update(item["id"] for item in added[key])
        return set() if fits else {"response_bytes"}

    # Caller-specified execution metadata gets first consideration in every policy.
    for group in checks:
        attempt(group)
    if policy == "lexical_first":
        for group in lexical + contrary + supporting + assertions:
            attempt(group)
    elif policy == "reserve_20":
        for group in lexical:
            attempt(
                group,
                source_limit=max(1, int(max_sources * 0.8)),
                byte_limit=int(budget_bytes * 0.8),
            )
        for group in contrary + lexical + supporting + assertions:
            attempt(group)
    else:
        for group in lexical[:1] + contrary + lexical[1:] + supporting + assertions:
            attempt(group)

    limits = set(pool.limits)
    # Temporary reservation failures do not become permanent omission warnings.
    for group in checks + lexical + contrary + supporting + assertions:
        if any(
            item["id"] not in selected[key] for key in selected for item in group[key]
        ):
            limits.update(attempt(group, persist=False))
    known = len(contrary)
    returned = sum(edge["relation"] != "supports" for edge in result["relationships"])
    omitted = known - returned
    if omitted:
        limits.add("contrary_relations")
    result["coverage"]["limits_reached"] = sorted(limits)
    result["conflict_review"].update(
        status=(
            "known_relations_omitted"
            if omitted
            else "coverage_limited"
            if limits
            else "proposed_relations_require_review"
            if returned
            else "no_proposed_relation_found"
        ),
        known_proposed_relations=known,
        returned_proposed_relations=returned,
        omitted_proposed_relations=omitted,
    )
    result["context_status"] = (
        "incomplete_context"
        if limits
        else "proposed_conflicts_require_review"
        if returned
        else "retrieved_context_requires_interpretation"
    )
    result["snapshot_id"] = _hash(_json(result))
    result["response_bytes"] = 0
    for _ in range(4):
        result["response_bytes"] = size(result)
    if size(result) > budget_bytes:
        raise ValueError("Response metadata exceeds the requested budget")
    return result
