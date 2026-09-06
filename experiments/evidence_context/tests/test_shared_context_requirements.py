"""B1/E1 regressions only; unimplemented lifecycle gates are in REQUIREMENTS.md."""

import pytest

from experiments.evidence_context.store import Relationship


def query(store, **changes):
    options = {
        "project": "synthetic-project",
        "scope": "personal",
        "max_bytes": 20000,
        "neighbor_turns": 0,
        "use_relationships": True,
    }
    options.update(changes)
    return store.retrieve("cachepolicy", **options)


def reviewed_link(store, source, target):
    return store.add_relationship(
        Relationship(
            source_id=source,
            target_id=target,
            kind="contradicts",
            supporting_citations=(store.cite(source), store.cite(target)),
            asserted_at="2026-01-02T00:00:00Z",
            available_at="2026-01-02T00:00:01Z",
            origin="asserted",
            review_state="reviewed",
            reviewer="synthetic-reviewer",
        )
    )


@pytest.mark.parametrize(
    "hidden", [{"scope": "work"}, {"scope": "unclassified"}, {"project": "other-project"}]
)
def test_b1_hidden_source_absent_from_whole_pack_and_explanation(store, record, hidden):
    seed = store.add_evidence(record())
    secret = store.add_evidence(
        record(
            message_id="restricted-message",
            content="cachepolicy PRIVATE_SENTINEL",
            source_locator="synthetic://restricted",
            **hidden,
        )
    )
    edge = reviewed_link(store, seed, secret)
    pack = query(store)
    assert {item.version_id for item in pack.evidence} == {seed}
    serialized = pack.to_json()
    for forbidden in (
        secret,
        edge,
        "PRIVATE_SENTINEL",
        "restricted-message",
        "synthetic://restricted",
    ):
        assert forbidden not in serialized


def test_e1_keyword_reason_is_grounded_in_exact_source_not_verification(store, record):
    version = store.add_evidence(record())
    (item,) = query(store, use_relationships=False).evidence
    assert item.version_id == version
    assert "fts" in item.retrieval_reasons
    assert store.resolve_citation(item.citation) == item.citation.text
    assert item.verification_status == "unverified_report"


def test_e1_relationship_reason_has_returned_edge_and_resolvable_support(store, record):
    seed = store.add_evidence(record())
    contrary = store.add_evidence(
        record(message_id="contrary", content="The earlier choice failed.")
    )
    edge_id = reviewed_link(store, seed, contrary)
    pack = query(store)
    items = {item.version_id: item for item in pack.evidence}
    assert "relationship" in items[contrary].retrieval_reasons
    (edge,) = pack.relationships
    assert edge["relationship_id"] == edge_id
    assert {edge["source_id"], edge["target_id"]} == {seed, contrary}
    assert edge["review_state"] == "reviewed"
    for citation in edge["supporting_citations"]:
        assert citation["text"] == store.cite(citation["version_id"]).text
    assert all(item.verification_status == "unverified_report" for item in items.values())
