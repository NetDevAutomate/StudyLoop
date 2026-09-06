"""Actual CLI/MCP rich context: scope, exact support, bounds and sufficiency."""

import asyncio
import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from agent_session_tools.context.cli import app
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.public import MAX_BODY_CHARS, open_context, size
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource

REVISION = "a" * 40
TARGET = '["uv","run","pytest"]'
STAMP = "2026-09-01T12:00:00+00:00"
CUTOFF = "2026-09-06T12:00:00Z"


@pytest.fixture
def fixture(migrated_db, tmp_path, monkeypatch):
    conn, path = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setattr("agent_session_tools.context.store._now", lambda: STAMP)
    settings = {
        "database": {"path": str(path)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/fixture/personal"]},
                "work": {"scope": "work", "roots": ["/fixture/work"]},
            },
        },
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setattr("agent_session_tools.mcp_server._get_db_path", lambda: path)
    for sid, project in [
        ("p1", "personal"),
        ("p2", "personal"),
        ("w1", "work"),
        ("u1", "unknown"),
    ]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "codex", "/fixture/" + project),
        )
    conn.commit()
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    store = ContextStore(conn)
    template = NativeSource(
        session_id="p1",
        native_key="prose",
        harness="claude_code",
        native_kind="message:assistant",
        native_locator="fixture.jsonl#line/1",
        parser_version="fixture",
        machine_id="fixture-machine",
        body="🐍 cache: choose SQLite for atomic writes.",
        origin=Origin.CONVERSATION,
        recorded_at=STAMP,
    )
    sources = {
        "report": template,
        "contrary": replace(
            template,
            session_id="p2",
            native_key="contrary",
            harness="kiro_cli",
            body="Consider a graph store for multi-hop traversal.",
        ),
        "work": replace(
            template,
            session_id="w1",
            native_key="work",
            body="cache WORK_SECRET",
            native_locator="WORK_PATH",
        ),
        "unknown": replace(
            template, session_id="u1", native_key="unknown", body="cache UNKNOWN_SECRET"
        ),
        "pass": replace(
            template,
            native_key="execution",
            origin=Origin.PROCESS_EXIT,
            body="2 passed",
            harness="codex",
            target=TARGET,
            revision=REVISION,
            exit_code=0,
        ),
    }
    ids = {name: store.capture(source) for name, source in sources.items()}
    return dict(
        conn=conn,
        path=path,
        config=config,
        settings=settings,
        store=store,
        sources=sources,
        ids=ids,
    )


def registered_tools():
    from agent_session_tools.mcp_server import mcp

    return {tool.name: getattr(tool, "fn") for tool in asyncio.run(mcp._list_tools())}


def requirement(**changes):
    return {
        "name": "unit tests",
        "project_id": "personal",
        "target": TARGET,
        "revision": REVISION,
        "expected_exit_code": 0,
        **changes,
    }


def assert_private_absent(result):
    value = json.dumps(result)
    assert (
        "WORK_SECRET" not in value
        and "UNKNOWN_SECRET" not in value
        and "WORK_PATH" not in value
    )


def proposal(context, identity, body, statement):
    return context.propose(
        statement=statement,
        state="completed",
        target="cache",
        citations=[
            {"evidence_id": identity, "start": 0, "end": len(body), "quote": body}
        ],
        producer="test-agent",
    )["assertion_id"]


def test_actual_cli_and_mcp_search_return_exact_scoped_context(fixture):
    mcp = registered_tools()
    result = mcp["memory_search"]("cache", as_of=CUTOFF)
    assert [s["id"] for s in result["sources"]] == [fixture["ids"]["report"]]
    source = result["sources"][0]
    assert source["provenance"]["basis"] == "reported"
    assert source["citation"]["quote"] == fixture["sources"]["report"].body
    assert source["why_selected"]["method"] == "lexical_match"
    assert result["response_bytes"] == size(result)
    assert_private_absent(result)
    cli = CliRunner().invoke(
        app, ["search", "cache", "--db", str(fixture["path"]), "--as-of", CUTOFF]
    )
    assert cli.exit_code == 0, cli.exception
    assert json.loads(cli.output) == result
    hidden = mcp["memory_source"](fixture["ids"]["work"])
    assert hidden["status"] == "unavailable"
    assert_private_absent(hidden)
    with pytest.raises(ScopeError):
        mcp["memory_search"]("cache", project="work")


def test_exact_unicode_offsets_and_old_versions_remain_citable(fixture):
    original = fixture["sources"]["report"]
    fixture["store"].capture(replace(original, body="new content"))
    with open_context(fixture["path"]) as context:
        result = context.source(fixture["ids"]["report"], start=2, length=5)
    assert result["source"]["citation"]["quote"] == "cache"
    assert result["source"]["citation"]["start"] == 2
    assert result["source"]["excerpt_truncated"]


def test_relationship_expands_nonlexical_contrary_evidence_with_all_sources(fixture):
    with open_context(fixture["path"], write=True) as context:
        first = proposal(
            context,
            fixture["ids"]["report"],
            fixture["sources"]["report"].body,
            "Use SQLite",
        )
        second = proposal(
            context,
            fixture["ids"]["contrary"],
            fixture["sources"]["contrary"].body,
            "Use a graph",
        )
        context.relate(second, first, "contradicts", producer="test-agent")
    with open_context(fixture["path"]) as context:
        result = context.search("cache", as_of=CUTOFF)
    assert {s["id"] for s in result["sources"]} == {
        fixture["ids"]["report"],
        fixture["ids"]["contrary"],
    }
    assert {a["statement"] for a in result["assertions"]} == {
        "Use SQLite",
        "Use a graph",
    }
    assert result["relationships"][0]["semantic_status"] == "unverified_relationship"
    assert result["coverage"]["limits_reached"] == []


def test_relationship_to_reclassified_source_is_withheld_entirely(fixture):
    with open_context(fixture["path"], write=True) as context:
        first = proposal(
            context,
            fixture["ids"]["report"],
            fixture["sources"]["report"].body,
            "Visible",
        )
        second = proposal(
            context,
            fixture["ids"]["contrary"],
            fixture["sources"]["contrary"].body,
            "REVOKED_SECRET",
        )
        context.relate(second, first, "corrects", producer="test-agent")
    fixture["conn"].execute(
        "UPDATE context_session_projects SET project_id='work',assignment_kind='explicit' WHERE session_id='p2'"
    )
    fixture["conn"].commit()
    with open_context(fixture["path"]) as context:
        result = context.search("cache", as_of=CUTOFF)
    assert "REVOKED_SECRET" not in json.dumps(result)
    assert result["relationships"] == []


def test_proposal_cannot_write_native_authority_or_false_citation(fixture, tmp_path):
    mcp = registered_tools()
    cite = {
        "evidence_id": fixture["ids"]["report"],
        "start": 0,
        "end": 4,
        "quote": "FAKE",
    }
    with pytest.raises(ValueError, match="bound"):
        mcp["memory_propose"]("claim", "completed", [cite])
    document = tmp_path / "proposal.json"
    body = fixture["sources"]["report"].body
    cite.update(end=len(body), quote=body)
    document.write_text(
        json.dumps(
            {
                "statement": "claim",
                "state": "completed",
                "target": None,
                "citations": [cite],
                "origin": "process_exit",
            }
        )
    )
    result = CliRunner().invoke(
        app, ["propose", str(document), "--db", str(fixture["path"])]
    )
    assert isinstance(result.exception, ValueError)
    assert (
        fixture["conn"].execute("SELECT count(*) FROM context_assertions").fetchone()[0]
        == 0
    )

    result = mcp["memory_propose"]("claim", "completed", [cite])
    assert result["semantic_status"] == "unverified_interpretation"
    row = fixture["conn"].execute("SELECT generator FROM context_assertions").fetchone()
    assert row[0] == "agent:session-db-mcp"
    assert (
        mcp["memory_source"](fixture["ids"]["report"])["source"]["origin"]
        == "conversation_message"
    )


def proposed_pair(fixture):
    with open_context(fixture["path"], write=True) as context:
        first = proposal(
            context,
            fixture["ids"]["report"],
            fixture["sources"]["report"].body,
            "Original report",
        )
        second = proposal(
            context,
            fixture["ids"]["contrary"],
            fixture["sources"]["contrary"].body,
            "Contrary report",
        )
        context.relate(second, first, "contradicts", producer="fixture")
    return first, second


@pytest.mark.parametrize("budget", [8192, 16384])
def test_complete_contrary_group_displaces_lower_ranked_lexical_matches(
    fixture, budget
):
    proposed_pair(fixture)
    for i in range(8):
        fixture["store"].capture(
            replace(
                fixture["sources"]["report"],
                native_key=f"filler-{i}",
                body="cache " + "details " * 150,
            )
        )
    with open_context(fixture["path"]) as context:
        result = context.search("cache", max_sources=2, budget_bytes=budget)
    assert {s["id"] for s in result["sources"]} == {
        fixture["ids"]["report"],
        fixture["ids"]["contrary"],
    }
    assert len(result["relationships"]) == 1
    assert result["conflict_review"]["returned_proposed_relations"] == 1
    assert result["conflict_review"]["semantic_conflict_absence_established"] is False
    assert result["context_status"] == "incomplete_context"
    assert size(result) <= budget


def test_group_that_cannot_fit_is_reported_without_a_dangling_relationship(fixture):
    source = replace(
        fixture["sources"]["contrary"], native_key="extra", body="Another source"
    )
    extra = fixture["store"].capture(source)
    with open_context(fixture["path"], write=True) as context:
        first = proposal(
            context,
            fixture["ids"]["report"],
            fixture["sources"]["report"].body,
            "Original",
        )
        second = context.propose(
            statement="Needs two sources",
            state="unknown",
            target=None,
            producer="fixture",
            citations=[
                {"evidence_id": eid, "start": 0, "end": len(body), "quote": body}
                for eid, body in [
                    (extra, source.body),
                    (fixture["ids"]["contrary"], fixture["sources"]["contrary"].body),
                ]
            ],
        )["assertion_id"]
        context.relate(second, first, "corrects", producer="fixture")
    with open_context(fixture["path"]) as context:
        result = context.search("cache", max_sources=2)
    assert result["relationships"] == []
    assert result["conflict_review"]["status"] == "known_relations_omitted"
    assert result["conflict_review"]["omitted_proposed_relations"] == 1
    ids = {s["id"] for s in result["sources"]}
    for assertion in result["assertions"]:
        assert {c["evidence_id"] for c in assertion["citations"]} <= ids


def test_hidden_relationships_do_not_consume_discovery_capacity_or_leak_counts(fixture):
    first, second = proposed_pair(fixture)
    with open_context(fixture["path"], write=True) as context:
        for i in range(35):
            context.relate(second, first, "contradicts", producer=f"hidden-{i}")
        visible = proposal(
            context,
            fixture["ids"]["pass"],
            fixture["sources"]["pass"].body,
            "Visible contrary proposal",
        )
        context.relate(visible, first, "contradicts", producer="visible")
    fixture["conn"].execute(
        "UPDATE context_session_projects SET project_id='work',assignment_kind='explicit' "
        "WHERE session_id='p2'"
    )
    fixture["conn"].commit()
    with open_context(fixture["path"]) as context:
        result = context.search("cache", max_sources=2)
    assert result["conflict_review"]["known_proposed_relations"] == 1
    assert result["conflict_review"]["returned_proposed_relations"] == 1
    assert result["coverage"]["limits_reached"] == []
    assert "Contrary report" not in json.dumps(result)
    assert "hidden-" not in json.dumps(result)


def test_discovery_cap_never_implies_that_all_proposed_conflicts_were_examined(fixture):
    first, second = proposed_pair(fixture)
    with open_context(fixture["path"], write=True) as context:
        for i in range(30):
            second = proposal(
                context,
                fixture["ids"]["contrary"],
                fixture["sources"]["contrary"].body,
                f"Alternative claim {i}",
            )
            context.relate(second, first, "contradicts", producer=f"proposal-{i}")
    with open_context(fixture["path"]) as context:
        result = context.search("cache", max_sources=40, budget_bytes=131072)
    assert result["context_status"] == "incomplete_context"
    assert "relationship_discovery" in result["coverage"]["limits_reached"]
    assert result["conflict_review"]["known_proposed_relations"] == 24
    assert result["conflict_review"]["semantic_conflict_absence_established"] is False


def test_duplicate_relation_producers_do_not_increase_selection_priority(fixture):
    first, second = proposed_pair(fixture)
    with open_context(fixture["path"], write=True) as context:
        for i in range(35):
            context.relate(second, first, "contradicts", producer=f"repeated-{i}")
    with open_context(fixture["path"]) as context:
        result = context.search("cache")
    assert result["conflict_review"]["known_proposed_relations"] == 1
    assert len(result["relationships"]) == 1
    assert result["coverage"]["limits_reached"] == []


def test_contrary_group_can_be_discovered_below_the_initial_output_limit(fixture):
    leading = fixture["store"].capture(
        replace(fixture["sources"]["report"], native_key="leading", body="cache")
    )
    proposed_pair(fixture)
    for i in range(6):
        fixture["store"].capture(
            replace(
                fixture["sources"]["report"],
                native_key=f"filler-{i}",
                body="cache " + "detail " * 80,
            )
        )
    with open_context(fixture["path"]) as context:
        result = context.search("cache", max_sources=3)
    assert {s["id"] for s in result["sources"]} == {
        leading,
        fixture["ids"]["report"],
        fixture["ids"]["contrary"],
    }
    assert len(result["relationships"]) == 1


@pytest.mark.parametrize("budget", [4096, 8192, 16384])
def test_entire_response_is_bounded_and_omission_is_visible(fixture, budget):
    for index in range(20):
        fixture["store"].capture(
            replace(
                fixture["sources"]["report"],
                native_key=str(index),
                body="cache " + "🐍" * 2000,
            )
        )
    with open_context(fixture["path"]) as context:
        result = context.search(
            "cache", budget_bytes=budget, max_sources=20, as_of=CUTOFF
        )
    assert size(result) <= budget
    assert result["response_bytes"] == size(result)
    assert result["coverage"]["limits_reached"]
    assert_private_absent(result)


def test_oversized_body_is_not_loaded_or_misrepresented_as_complete(fixture):
    identity = fixture["store"].capture(
        replace(
            fixture["sources"]["report"],
            native_key="oversize",
            body="oversize " + "x" * MAX_BODY_CHARS,
        )
    )
    with open_context(fixture["path"]) as context:
        result = context.search("oversize", as_of=CUTOFF)
        with pytest.raises(ValueError, match="body limit"):
            context.source(identity)
    assert result["sources"] == []
    assert "source_binding_or_size" in result["coverage"]["limits_reached"]


def test_matching_execution_contract_is_not_semantic_validation(fixture):
    result = registered_tools()["memory_decide"](
        "unrelated wording", [requirement()], as_of=CUTOFF
    )
    decision = result["decision"]
    assert decision["sufficiency"] == "recorded_checks_satisfied"
    assert decision["validation_of_change"] == "not_established"
    assert decision["checks"][0]["source_ids"]["matched"] == [fixture["ids"]["pass"]]
    assert result["sources"][0]["why_selected"]["method"] == "requested_check_metadata"


@pytest.mark.parametrize(
    "change",
    [
        {"revision": None},
        {"recorded_at": None},
        {"origin": Origin.TOOL_RESULT, "exit_code": None},
    ],
)
def test_missing_metadata_stays_unknown_and_blocks_needed_check(fixture, change):
    fixture["conn"].execute(
        "DELETE FROM context_evidence WHERE id=?", (fixture["ids"]["pass"],)
    )
    fixture["conn"].commit()
    fixture["store"].capture(replace(fixture["sources"]["pass"], **change))
    result = registered_tools()["memory_decide"](
        "cache", [requirement(not_before=STAMP)], as_of=CUTOFF
    )
    assert result["decision"]["sufficiency"] == "checks_not_established"
    assert len(result["decision"]["checks"][0]["source_ids"]["unknown"]) == 1


def test_same_revision_conflict_is_not_resolved_by_recency(fixture):
    failed = fixture["store"].capture(
        replace(
            fixture["sources"]["pass"],
            native_key="failed",
            exit_code=1,
            recorded_at="2026-09-02T00:00:00Z",
        )
    )
    result = registered_tools()["memory_decide"]("cache", [requirement()], as_of=CUTOFF)
    assert result["decision"]["sufficiency"] == "conflicting_records"
    assert result["decision"]["checks"][0]["source_ids"]["different_exit"] == [failed]
    assert {s["id"] for s in result["sources"]} >= {failed, fixture["ids"]["pass"]}


def test_changed_revision_and_time_have_explicit_applicability(fixture):
    old = fixture["store"].capture(
        replace(
            fixture["sources"]["pass"], native_key="old", revision="b" * 40, exit_code=1
        )
    )
    result = registered_tools()["memory_decide"]("cache", [requirement()], as_of=CUTOFF)
    assert result["decision"]["sufficiency"] == "recorded_checks_satisfied"
    assert result["decision"]["checks"][0]["source_ids"]["inapplicable"] == [old]
    result = registered_tools()["memory_decide"](
        "cache", [requirement(not_before="2026-09-03T00:00:00Z")], as_of=CUTOFF
    )
    assert result["decision"]["sufficiency"] == "checks_not_established"


@pytest.mark.parametrize("revision", ["main", "latest", "a123456", "", "a" * 41])
def test_mutable_or_ambiguous_requested_revisions_are_rejected(fixture, revision):
    with pytest.raises(ValueError):
        registered_tools()["memory_decide"]("cache", [requirement(revision=revision)])


def test_omitted_check_records_prevent_sufficiency(fixture):
    for index in range(45):
        fixture["store"].capture(
            replace(fixture["sources"]["pass"], native_key=f"check-{index}")
        )
    result = registered_tools()["memory_decide"]("cache", [requirement()], as_of=CUTOFF)
    assert result["decision"]["sufficiency"] == "incomplete_evidence"
    assert result["coverage"]["limits_reached"]


def test_tombstone_and_asof_do_not_resurrect_or_expose_future_sources(fixture):
    future = fixture["store"].capture(
        replace(
            fixture["sources"]["report"],
            native_key="future",
            body="cache FUTURE_SECRET",
            recorded_at="2027-01-01T00:00:00Z",
        )
    )
    fixture["conn"].execute(
        "INSERT INTO context_tombstones VALUES ('p1','gone','2026-09-03T00:00:00Z')"
    )
    fixture["conn"].commit()
    result = registered_tools()["memory_search"]("cache", as_of="2026-09-02T00:00:00Z")
    assert result["sources"] == []
    assert future not in json.dumps(result)
    assert (
        registered_tools()["memory_source"](fixture["ids"]["report"])["status"]
        == "unavailable"
    )


def test_removed_project_is_not_returned_through_unclassified_scope(
    fixture, monkeypatch
):
    fixture["conn"].execute(
        "UPDATE context_session_projects SET assignment_kind='explicit' WHERE session_id='p1'"
    )
    fixture["conn"].commit()
    del fixture["settings"]["memory"]["projects"]["personal"]
    fixture["config"].write_text(json.dumps(fixture["settings"]))
    apply_policy(
        fixture["conn"],
        ScopePolicy.from_config(fixture["settings"]),
        actor="test",
        dry_run=False,
    )
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "unclassified")
    result = registered_tools()["memory_search"]("cache", as_of=CUTOFF)
    assert {s["id"] for s in result["sources"]} == {fixture["ids"]["unknown"]}


def test_request_observes_unapplied_config_change(fixture):
    fixture["settings"]["memory"]["projects"]["personal"]["scope"] = "work"
    fixture["config"].write_text(json.dumps(fixture["settings"]))
    with pytest.raises(ScopeError, match="changed"):
        registered_tools()["memory_search"]("cache")


def test_tokenizer_match_centres_the_excerpt_on_actual_unicode_text(fixture):
    source = replace(
        fixture["sources"]["report"],
        native_key="accent",
        body=("unrelated introduction " * 200) + "café latency result",
    )
    identity = fixture["store"].capture(source)
    with open_context(fixture["path"]) as context:
        result = context.search("cafe", as_of=CUTOFF)
    row = next(s for s in result["sources"] if s["id"] == identity)
    quote = row["citation"]
    assert "café" in quote["quote"]
    assert quote["start"] > 0
    assert source.body[quote["start"] : quote["end"]] == quote["quote"]


def test_asof_withholds_later_interpretations_of_older_sources(fixture, monkeypatch):
    monkeypatch.setattr(
        "agent_session_tools.context.store._now", lambda: "2027-01-01T00:00:00+00:00"
    )
    with open_context(fixture["path"], write=True) as context:
        proposal(
            context,
            fixture["ids"]["report"],
            fixture["sources"]["report"].body,
            "FUTURE_INTERPRETATION",
        )
    with open_context(fixture["path"]) as context:
        result = context.search("cache", as_of=CUTOFF)
    assert len(result["sources"]) == 1
    assert result["assertions"] == []
    assert "FUTURE_INTERPRETATION" not in json.dumps(result)


def test_policy_drift_during_proposal_rolls_back_the_write(fixture):
    with pytest.raises(ScopeError, match="changed"):
        with open_context(fixture["path"], write=True) as context:
            proposal(
                context,
                fixture["ids"]["report"],
                fixture["sources"]["report"].body,
                "NOT_COMMITTED",
            )
            fixture["settings"]["memory"]["projects"]["personal"]["scope"] = "work"
            fixture["config"].write_text(json.dumps(fixture["settings"]))
    assert (
        fixture["conn"].execute("SELECT count(*) FROM context_assertions").fetchone()[0]
        == 0
    )
