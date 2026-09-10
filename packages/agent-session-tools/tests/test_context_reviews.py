"""Review meaning stays attributed; scope, lineage and exact bindings are enforced."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from importlib.resources import files

import pytest
from typer.testing import CliRunner

from agent_session_tools.context.cli import app
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.public import open_context, size
from agent_session_tools.context.reviews import ReviewStore
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource

STAMP = "2026-09-01T12:00:00+00:00"
CUTOFF = "2026-09-06T12:00:00+00:00"


@pytest.fixture
def history(migrated_db, tmp_path, monkeypatch):
    conn, path = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setattr("agent_session_tools.context.store._now", lambda: STAMP)
    monkeypatch.setattr("agent_session_tools.context.observations._now", lambda: STAMP)
    config = {
        "database": {"path": str(path)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "a": {"scope": "personal", "roots": ["/review/a"]},
                "b": {"scope": "personal", "roots": ["/review/b"]},
                "w": {"scope": "work", "roots": ["/review/w"]},
            },
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    monkeypatch.setattr("agent_session_tools.mcp_server._get_db_path", lambda: path)
    for sid in ("a", "b", "w"):
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "kiro_cli", "/review/" + sid),
        )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    store = ContextStore(conn)
    base = NativeSource(
        session_id="a",
        native_key="one",
        harness="codex",
        native_kind="message:assistant",
        native_locator="fixture.jsonl#line/1",
        parser_version="fixture",
        machine_id="fixture",
        origin=Origin.CONVERSATION,
        recorded_at=STAMP,
        body="We chose SQLite for atomic writes.",
    )
    records = {
        "original": base,
        "extra": replace(base, session_id="b", body="No graph benchmark was run."),
        "private": replace(base, session_id="w", body="PRIVATE_REVIEW_SOURCE"),
    }
    ids = {name: store.capture(record) for name, record in records.items()}

    def cite(name):
        body = records[name].body
        return {"evidence_id": ids[name], "start": 0, "end": len(body), "quote": body}

    with open_context(path, write=True) as context:
        assertion = context.propose(
            statement="SQLite was proven faster than every graph database.",
            state="completed",
            target=None,
            producer="fixture-author",
            citations=[cite("original")],
        )["assertion_id"]
    return dict(
        conn=conn,
        path=path,
        config=config,
        config_path=config_path,
        store=store,
        ids=ids,
        records=records,
        cite=cite,
        assertion=assertion,
    )


def review(
    history, *, producer="model-a", verdict="supported", source="original", **kwargs
):
    with open_context(history["path"], write=True) as context:
        return context.review(
            producer=producer,
            target_kind="assertion",
            target_id=history["assertion"],
            verdict=verdict,
            rationale="A reviewer's proposed interpretation.",
            citations=[history["cite"](source)],
            **kwargs,
        )["review_id"]


def test_favourable_review_is_not_native_validation_or_independent_approval(history):
    identity = review(history)
    with open_context(history["path"]) as context:
        result = context.assess("SQLite", [history["assertion"]], as_of=CUTOFF)
    assert result["assessment"]["status"] == "attributed_support_available"
    assert result["assessment"]["semantic_validation"] == "not_established"
    assert result["assessment"]["reviewer_independence"] == "not_established"
    assert result["assessment"]["validation_of_change"] == "not_established"
    assert result["reviews"][0]["id"] == identity
    assert result["sources"][0]["origin"] == "conversation_message"
    assert result["sources"][0]["provenance"]["execution_state"] == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [
        ("authority", "human_approved"),
        ("origin", "process_exit"),
        ("independent", True),
    ],
)
def test_review_cannot_supply_authority_fields(history, field, value):
    with pytest.raises(ValueError, match="accepts"):
        review(history, **{field: value})
    assert (
        history["conn"]
        .execute("SELECT count(*) FROM context_review_targets")
        .fetchone()[0]
        == 0
    )


def test_disagreement_is_not_resolved_by_more_votes_or_recency(history):
    for i in range(3):
        review(history, producer=f"supporter-{i}")
    review(history, producer="contrary", verdict="unsupported", source="extra")
    with open_context(history["path"]) as context:
        result = context.assess(
            "SQLite", [history["assertion"]], budget_bytes=65536, as_of=CUTOFF
        )
    assert result["assessment"]["status"] == "disputed_reviews"
    assert len(result["reviews"]) == 4
    assert {r["verdict"] for r in result["reviews"]} == {"supported", "unsupported"}


def test_review_revision_retains_history_and_only_revises_own_producer(history):
    original = review(history)
    with pytest.raises(ValueError, match="another producer"):
        review(history, producer="model-b", supersedes=[original])
    left = review(history, verdict="unsupported", source="extra", supersedes=[original])
    right = review(history, verdict="supported", supersedes=[original])
    with open_context(history["path"]) as context:
        store = ReviewStore(context)
        current = store.list("assertion", history["assertion"])
        past = context.review_history("assertion", history["assertion"])
    assert current["status"] == "disputed"
    assert {r["id"] for r in current["reviews"]} == {left, right}
    assert len(past["reviews"]) == 3
    assert next(r for r in past["reviews"] if r["id"] == original)["current"] is False


def test_forgotten_successor_cannot_reactivate_a_retired_supporting_review(history):
    original = review(history)
    successor = review(
        history, verdict="unsupported", source="extra", supersedes=[original]
    )
    observations = ObservationStore(history["conn"])
    assert observations.forget(successor)
    with open_context(history["path"]) as context:
        assert (
            ReviewStore(context).list("assertion", history["assertion"])["status"]
            == "unreviewed"
        )
        retired = ReviewStore(context).get(original)
        assert retired is not None and retired["current"] is False
        assert (
            context.assess("SQLite", [history["assertion"]])["assessment"]["status"]
            == "review_needed"
        )


def test_project_narrowing_withholds_review_before_prose_and_counts(history):
    review(history, source="extra", verdict="unsupported")
    with open_context(history["path"], project="a") as context:
        result = context.search("SQLite")
    assert result["reviews"] == []
    assert result["assertions"][0]["review_status"] == "unreviewed"
    assert "No graph benchmark" not in json.dumps(result)
    assert "A reviewer's" not in json.dumps(result)


def test_review_source_reclassification_revokes_entire_review_and_its_derived_status(
    history,
):
    review(history, source="extra")
    history["config"]["memory"]["projects"]["b"]["scope"] = "work"
    history["config_path"].write_text(json.dumps(history["config"]))
    apply_policy(
        history["conn"],
        ScopePolicy.from_config(history["config"]),
        actor="fixture",
        dry_run=False,
    )
    with open_context(history["path"]) as context:
        result = context.assess("SQLite", [history["assertion"]])
    assert result["assessment"]["status"] == "review_needed"
    assert result["reviews"] == []
    assert "No graph benchmark" not in json.dumps(result)


def test_review_rejects_hidden_source_or_inexact_quote_without_partial_write(history):
    with pytest.raises(ValueError, match="Citation unavailable"):
        review(history, source="private")
    citation = history["cite"]("original")
    citation["quote"] = "Benchmarks prove this is fastest"
    with open_context(history["path"], write=True) as context:
        with pytest.raises(ValueError, match="Citation unavailable"):
            context.review(
                producer="fixture",
                target_kind="assertion",
                target_id=history["assertion"],
                verdict="supported",
                rationale="bad",
                citations=[citation],
            )
    assert (
        history["conn"]
        .execute("SELECT count(*) FROM context_review_targets")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("delete_target", [True, False])
def test_target_or_source_purge_removes_review_payload_and_retains_retirement(
    history, delete_target
):
    identity = review(history, source="extra")
    if delete_target:
        history["conn"].execute(
            "DELETE FROM context_assertions WHERE id=?", (history["assertion"],)
        )
    else:
        history["conn"].execute(
            "DELETE FROM context_evidence WHERE id=?", (history["ids"]["extra"],)
        )
    history["conn"].commit()
    assert (
        not history["conn"]
        .execute("SELECT 1 FROM context_observations WHERE id=?", (identity,))
        .fetchone()
    )
    assert (
        not history["conn"]
        .execute(
            "SELECT 1 FROM context_review_targets WHERE observation_id=?", (identity,)
        )
        .fetchone()
    )
    assert (
        history["conn"]
        .execute(
            "SELECT 1 FROM context_observation_tombstones WHERE observation_id=?",
            (identity,),
        )
        .fetchone()
    )
    assert history["conn"].execute("PRAGMA foreign_key_check").fetchall() == []


def test_future_review_is_not_used_by_historical_assessment(history, monkeypatch):
    monkeypatch.setattr(
        "agent_session_tools.context.observations._now",
        lambda: "2027-01-01T00:00:00+00:00",
    )
    review(history)
    with open_context(history["path"]) as context:
        result = context.assess("SQLite", [history["assertion"]], as_of=CUTOFF)
    assert result["reviews"] == []
    assert result["assessment"]["status"] == "review_needed"


def test_review_cap_and_byte_omission_cannot_present_complete_support(history):
    for i in range(6):
        review(history, producer=f"model-{i}")
    with open_context(history["path"]) as context:
        result = context.assess("SQLite", [history["assertion"]], as_of=CUTOFF)
        small = context.review_history(
            "assertion", history["assertion"], budget_bytes=4096
        )
    assert result["assessment"]["status"] == "incomplete_evidence"
    assert "review_coverage" in result["coverage"]["limits_reached"]
    assert size(small) <= 4096 and small["incomplete"]
    assert small["status"] == "incomplete_reviews"


def test_cli_mcp_review_and_assessment_share_the_contract(history, tmp_path):
    from agent_session_tools.mcp_server import mcp

    tools = {t.name: getattr(t, "fn") for t in asyncio.run(mcp._list_tools())}
    result = tools["memory_review"](
        "assertion",
        history["assertion"],
        "unsupported",
        "Atomic writes do not establish comparative speed.",
        [history["cite"]("extra")],
    )
    assert result["authority"] == "attributed_model_assessment"
    expected = tools["memory_assess"]("SQLite", [history["assertion"]], as_of=CUTOFF)
    path = tmp_path / "assertions.json"
    path.write_text(json.dumps([history["assertion"]]))
    cli = CliRunner().invoke(
        app,
        [
            "assess",
            "SQLite",
            str(path),
            "--db",
            str(history["path"]),
            "--as-of",
            CUTOFF,
        ],
    )
    assert cli.exit_code == 0, cli.exception
    assert json.loads(cli.output) == expected
    assert expected["assessment"]["status"] == "unsupported_by_available_reviews"


def test_v35_upgrade_rolls_back_and_retries_without_losing_conversation(monkeypatch):
    import agent_session_tools.migrations as migrations

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 35)

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 34)
        migrations.migrate(conn)
    conn.execute("INSERT INTO sessions(id,source) VALUES ('kept','kiro_cli')")
    conn.commit()
    real = migrations.MIGRATIONS[35]

    def interrupted(db):
        from agent_session_tools.context.review_schema import STATEMENTS

        db.execute(STATEMENTS[0])
        raise RuntimeError("injected migration failure")

    with monkeypatch.context() as failure:
        failure.setitem(migrations.MIGRATIONS, 35, (real[0], interrupted))
        with pytest.raises(RuntimeError, match="injected"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 34
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_review_targets'"
    ).fetchone()
    migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 35
    assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "kept"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_relation_review_binds_both_endpoints_and_purges_with_either(history):
    with open_context(history["path"], write=True) as context:
        other = context.propose(
            statement="No comparative speed benchmark exists in this evidence.",
            state="unknown",
            target=None,
            producer="fixture-author",
            citations=[history["cite"]("extra")],
        )["assertion_id"]
        edge = context.relate(
            other, history["assertion"], "contradicts", producer="fixture"
        )["relation_id"]
        rid = context.review(
            target_kind="relation",
            target_id=edge,
            producer="model-a",
            verdict="uncertain",
            rationale="Absence of a benchmark challenges support; it does not prove falsity.",
            citations=[history["cite"]("extra")],
        )["review_id"]
    with open_context(history["path"]) as context:
        item = ReviewStore(context).get(rid)
        assert item is not None
        assert set(item["evidence_ids"]) == {
            history["ids"]["original"],
            history["ids"]["extra"],
        }
        result = context.search("SQLite", budget_bytes=65536)
        assert next(r for r in result["relationships"] if r["id"] == edge)[
            "review_ids"
        ] == [rid]
        assert {r["id"] for r in result["reviews"]} == {rid}
    conn = history["conn"]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE context_relations SET relation='supports' WHERE id=?", (edge,)
        )
    conn.rollback()
    # Even the endpoint not explicitly quoted by the reviewer remains a dependency.
    conn.execute("DELETE FROM context_assertions WHERE id=?", (history["assertion"],))
    conn.commit()
    assert not conn.execute(
        "SELECT 1 FROM context_observations WHERE id=?", (rid,)
    ).fetchone()
    assert conn.execute(
        "SELECT 1 FROM context_observation_tombstones WHERE observation_id=?", (rid,)
    ).fetchone()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_corrupt_review_target_binding_is_rejected_and_coverage_reports_gap(history):
    rid = review(history)
    conn = history["conn"]
    # Simulate corruption outside the supported writer, which rejects this UPDATE.
    conn.execute("DROP TRIGGER context_review_targets_immutable")
    conn.execute(
        "UPDATE context_review_targets SET target_sha256=? WHERE observation_id=?",
        ("0" * 64, rid),
    )
    conn.commit()
    with open_context(history["path"]) as context:
        with pytest.raises(ValueError, match="target binding"):
            ReviewStore(context).get(rid)
        report = context.assess("SQLite", [history["assertion"]], as_of=CUTOFF)
    assert report["assessment"]["status"] == "incomplete_evidence"
    assert report["reviews"] == []


def test_future_dependency_is_filtered_before_review_limit(history):
    future = history["store"].capture(
        replace(
            history["records"]["extra"],
            native_key="future",
            recorded_at="2027-01-01T00:00:00Z",
        )
    )
    body = history["records"]["extra"].body
    for i in range(6):
        with open_context(history["path"], write=True) as context:
            context.review(
                target_kind="assertion",
                target_id=history["assertion"],
                producer=f"future-{i}",
                verdict="supported",
                rationale="Future evidence must not consume the time window.",
                citations=[
                    {"evidence_id": future, "start": 0, "end": len(body), "quote": body}
                ],
            )
    current = review(history, verdict="unsupported", source="extra")
    with open_context(history["path"]) as context:
        result = ReviewStore(context).list(
            "assertion", history["assertion"], as_of=CUTOFF, limit=1
        )
    assert result["incomplete"] is False
    assert result["status"] == "assessed_unsupported"
    assert [r["id"] for r in result["reviews"]] == [current]


def test_review_request_replay_is_idempotent_but_cannot_restore_forgotten_content(
    history,
):
    first = review(history, request_id="one-stable-request")
    assert review(history, request_id="one-stable-request") == first
    assert ObservationStore(history["conn"]).forget(first)
    with pytest.raises(ValueError, match="forgotten"):
        review(history, request_id="one-stable-request")
    assert (
        history["conn"]
        .execute("SELECT count(*) FROM context_review_targets")
        .fetchone()[0]
        == 0
    )
