"""Falsify ownership, provenance, correction and decision-role claims on real paths."""

import json
from dataclasses import replace

import pytest

from agent_session_tools.context import records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from studyloop.history import bridges, concepts, graph
from studyloop.learning import mastery


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    roots = {name: tmp_path / name for name in ("personal", "second", "work")}
    for root in roots.values():
        root.mkdir()
    db = tmp_path / "sessions.db"
    settings = {
        "database": {"path": str(db)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                name: {"scope": "work" if name == "work" else "personal", "roots": [str(root)]}
                for name, root in roots.items()
            },
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
    monkeypatch.setenv("STUDYLOOP_DB", str(db))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    monkeypatch.chdir(roots["personal"])
    conn = records.connect(db)
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    yield conn, path, settings, roots
    conn.close()


def edge(**changes):
    return replace(
        mastery.ConceptDependency(
            topic="python",
            source_concept="closures",
            target_concept="decorators",
            relation_type="prerequisite",
            evidence="Reported teaching order",
            source_type="explicit",
            confidence=0.8,
        ),
        **changes,
    )


def test_scopes_keep_same_labels_with_distinct_provenance(graph_db, monkeypatch):
    _, _, _, roots = graph_db
    personal = concepts.record_concept("closures", "python", "PERSONAL")
    mastery.upsert_dependency(edge(evidence="PERSONAL"))
    monkeypatch.chdir(roots["work"])
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    work = concepts.record_concept("closures", "python", "WORK_EXCLUDED")
    mastery.upsert_dependency(edge(evidence="WORK_EXCLUDED", confidence=1.0))
    assert personal != work
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    assert [c.description for c in concepts.list_concepts()] == ["PERSONAL"]
    found = mastery.list_dependencies("python")
    assert len(found) == 1 and found[0].evidence == "PERSONAL"
    assert found[0].provenance["semantic_validation"] == "not_established"


def test_update_changes_only_current_project_not_independent_same_scope(graph_db, monkeypatch):
    _, _, _, roots = graph_db
    mastery.upsert_dependency(edge(evidence="first project"))
    monkeypatch.chdir(roots["second"])
    mastery.upsert_dependency(edge(evidence="second project"))
    mastery.upsert_dependency(edge(evidence="second corrected", confidence=0.2))
    found = mastery.list_dependencies("python")
    assert {r.evidence for r in found} == {"first project", "second corrected"}
    assert sorted(r.confidence for r in found) == [0.2, 0.8]
    # An update to one relationship must not retire another in the same topic.
    mastery.upsert_dependency(edge(source_concept="iterators", target_concept="generators"))
    assert len(mastery.list_dependencies("python")) == 3


def test_bridge_correction_and_forget_recompute_without_orphan_edges(graph_db):
    conn, _, _, _ = graph_db
    for description in ("FIRST", "INDEPENDENT"):
        assert bridges.record_bridge(
            "routing", "networking", "closures", "python", description, quality="validated"
        )
    assert bridges.migrate_bridges_to_graph() == 2
    first = mastery.list_dependencies("python")
    assert len(first) == 2
    ids = [r.provenance["record_id"] for r in first]
    conn.execute(
        "UPDATE knowledge_bridges SET structural_mapping='CORRECTED',quality='proposed' WHERE id=?",
        (ids[0],),
    )
    conn.commit()
    corrected = mastery.list_dependencies("python")
    assert corrected[0].provenance["snapshot_sha256"] != first[0].provenance["snapshot_sha256"]
    assert corrected[0].provenance["structural_mapping"] == "CORRECTED"
    conn.execute("DELETE FROM knowledge_bridges WHERE id=?", (ids[0],))
    conn.commit()
    left = mastery.list_dependencies("python")
    assert len(left) == 1 and left[0].provenance["record_id"] == ids[1]
    assert all(
        c.provenance and c.provenance["record_id"] == ids[1] for c in concepts.list_concepts()
    )
    assert conn.execute("SELECT count(*) FROM concept_relations").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_native_parent_forgetting_removes_projected_relationship(graph_db):
    conn, _, _, roots = graph_db
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES ('native','fixture',?)",
        (str(roots["personal"]),),
    )
    conn.commit()
    from agent_session_tools.context.scope import active_policy

    apply_policy(conn, active_policy(), actor="test", dry_run=False)
    conn.execute("BEGIN IMMEDIATE")
    cursor = conn.execute(
        "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) "
        "VALUES ('routing','networking','closures','python')"
    )
    records.bind(conn, "knowledge_bridges", cursor.lastrowid, session_id="native")
    conn.commit()
    assert len(mastery.list_dependencies("python")) == 1
    conn.execute("INSERT INTO context_tombstones VALUES ('native','forget','2026-09-06')")
    conn.commit()
    assert mastery.list_dependencies("python") == []
    assert concepts.list_concepts() == []


def test_project_reclassification_withholds_labels_and_edges(graph_db):
    conn, path, settings, _ = graph_db
    concepts.record_concept("closures", "python", "PRIVATE")
    mastery.upsert_dependency(edge())
    bridges.record_bridge("routing", "networking", "closures", "python", "PRIVATE")
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    path.write_text(json.dumps(settings))
    with pytest.raises(ScopeError):
        concepts.list_concepts()
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    assert concepts.list_concepts() == []
    assert mastery.list_dependencies("python") == []


def test_forgotten_report_does_not_fall_back_to_global_legacy(graph_db):
    conn, _, _, _ = graph_db
    mastery.upsert_dependency(edge())
    identity = mastery.list_dependencies("python")[0].provenance["observation_id"]
    conn.execute(
        "INSERT INTO concept_dependencies(id,topic,source_concept,target_concept,relation_type) "
        "VALUES ('old','python','closures','decorators','prerequisite')"
    )
    conn.commit()
    assert ObservationStore(conn).forget(identity)
    assert mastery.list_dependencies("python") == []


def test_config_and_markdown_do_not_read_before_ownership(graph_db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source read before ownership")

    monkeypatch.setattr("studyloop.topics.get_topics", forbidden)
    monkeypatch.setattr(mastery, "_markdown_roots", forbidden)
    with pytest.raises(ScopeError, match="file ownership"):
        concepts.seed_concepts_from_config()
    assert mastery.seed_inferred_dependencies("python") == 0
    assert mastery._seed_from_markdown("python") == 0
    with pytest.raises(ScopeError, match="source projection"):
        mastery.upsert_dependency(edge(source_type="heading"))


def test_analogy_is_context_not_a_prerequisite(graph_db, monkeypatch):
    bridges.record_bridge(
        "closures", "python", "decorators", "python", "An analogy", quality="validated"
    )
    monkeypatch.setattr(
        mastery, "_progress_by_concept", lambda topic: {"closures": {"confidence": "struggling"}}
    )
    found = mastery.list_dependencies("python")
    assert found[0].provenance["quality_report"] == "validated"
    assert found[0].provenance["semantic_validation"] == "not_established"
    assert mastery.weak_links_for_topic("python") == []
    mastery.upsert_dependency(edge())
    links = mastery.weak_links_for_topic("python")
    assert len(links) == 1
    assert links[0]["relationship_status"] == "reported_dependency_not_validated_prerequisite"


@pytest.mark.parametrize("weight", [-1, 2, float("inf"), float("nan")])
def test_invalid_report_weight_is_not_persisted(graph_db, weight):
    with pytest.raises(ValueError):
        mastery.upsert_dependency(edge(confidence=weight))
    assert mastery.list_dependencies("python") == []


def test_identical_manual_report_is_idempotent(graph_db):
    conn, _, _, _ = graph_db
    mastery.upsert_dependency(edge())
    mastery.upsert_dependency(edge())
    assert len(graph.reports(conn, graph.DEPENDENCY)) == 1


def test_bounded_context_keeps_complete_contributions_and_reports_omission(graph_db):
    bridges.record_bridge("closures", "python", "decorators", "python", "界" * 20000)
    result = mastery.agent_concept_context("python", max_bytes=4096)
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 4096
    assert result["edges"] == [] and result["nodes"] == []
    assert result["edge_count_total"] == 1 and result["coverage"] == "partial"
    assert result["semantic_arbitration"] == "not_performed"


def test_unclassified_retirement_suppresses_legacy_fallback(graph_db, monkeypatch):
    conn, _, _, _ = graph_db
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "unclassified")
    mastery.upsert_dependency(edge())
    concept_id = concepts.record_concept("closures", "python")
    assert concept_id is not None
    observation_id = mastery.list_dependencies("python")[0].provenance["observation_id"]
    conn.execute("INSERT INTO concepts(id,name,domain) VALUES ('legacy','closures','python')")
    conn.execute(
        "INSERT INTO concept_dependencies(id,topic,source_concept,target_concept,relation_type) "
        "VALUES ('legacy','python','closures','decorators','prerequisite')"
    )
    conn.commit()
    assert len(concepts.list_concepts()) == 1
    assert len(mastery.list_dependencies("python")) == 1
    store = ObservationStore(conn)
    assert store.forget(observation_id) and store.forget(concept_id)
    assert concepts.list_concepts() == [] and mastery.list_dependencies("python") == []


def test_recommendation_retains_relationship_binding(graph_db, monkeypatch):
    from studyloop.learning import decision

    mastery.upsert_dependency(edge())
    monkeypatch.setattr(
        mastery, "_progress_by_concept", lambda topic: {"closures": {"confidence": "struggling"}}
    )
    monkeypatch.setattr(decision, "TOPIC_KEYWORDS", {"python": []})
    candidate = decision._transfer_candidates(20)[0].recommendation().to_json_dict()
    expected = mastery.list_dependencies("python")[0].provenance
    assert candidate["metadata"]["relationship_observation_id"] == expected["observation_id"]
    assert candidate["metadata"]["relationship_binding_sha256"] == expected["binding_sha256"]
    assert candidate["metadata"]["semantic_validation"] == "not_established"


@pytest.mark.parametrize(
    "relation", ["requires", "depends_on", "heading_path", "backlink", "tagged_with"]
)
def test_ambiguous_direction_cannot_become_prerequisite(graph_db, monkeypatch, relation):
    mastery.upsert_dependency(edge(relation_type=relation))
    monkeypatch.setattr(
        mastery, "_progress_by_concept", lambda topic: {"closures": {"confidence": "struggling"}}
    )
    assert len(mastery.list_dependencies("python")) == 1
    assert mastery.weak_links_for_topic("python") == []


def test_forget_after_reclassification_does_not_return_when_scope_restored(graph_db, monkeypatch):
    conn, path, settings, _ = graph_db
    mastery.upsert_dependency(edge())
    identity = mastery.list_dependencies("python")[0].provenance["observation_id"]
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    path.write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    assert ObservationStore(conn).forget(identity)
    settings["memory"]["projects"]["personal"]["scope"] = "personal"
    path.write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="test", dry_run=False)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    assert mastery.list_dependencies("python") == []


def test_graph_legend_does_not_turn_reported_mastery_into_validation(graph_db):
    meaning = next(row["meaning"] for row in mastery.mastery_legend() if row["key"] == "mastered")
    assert "Reported" in meaning and "does not prove" in meaning
    assert (
        mastery.mastery_graph_json("python")["learning_assessment_status"]
        == "reported_categories_not_independent_validation"
    )
