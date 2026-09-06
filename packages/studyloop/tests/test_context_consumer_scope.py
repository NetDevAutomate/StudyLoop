"""StudyLoop consumes only explicitly scoped history before model exposure."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import cast

import pytest
from click.testing import CliRunner

from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.migrations import migrate
from studyloop.cli import _extract, cli
from studyloop.history import search, sessions, streaks


@pytest.fixture
def consumer_db(tmp_path, monkeypatch):
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    now = datetime.now(UTC)
    for index, (sid, root, word) in enumerate(
        [("personal", "/consumer/personal", "python"), ("work", "/consumer/work", "redshift")]
    ):
        timestamp = (now - timedelta(minutes=2 - index)).isoformat()
        conn.execute(
            "INSERT INTO sessions(id,source,project_path,created_at,updated_at) VALUES (?,?,?,?,?)",
            (sid, "kiro_cli", root, timestamp, timestamp),
        )
        for seq, role in enumerate(["user", "assistant"]):
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content,seq,timestamp) "
                "VALUES (?,?,?,?,?,?)",
                (sid + str(seq), sid, role, f"{word} question? {sid.upper()}_ONLY", seq, timestamp),
            )
    conn.execute(
        "INSERT INTO study_progress(id,topic,concept,confidence,first_seen,last_seen) "
        "VALUES (?,?,?,?,?,?)",
        ("merged", "sql", "UNSCOPED_MERGED_CONTENT", "learning", now.isoformat(), now.isoformat()),
    )
    conn.execute(
        "INSERT INTO study_progress(id,topic,concept,confidence,first_seen,last_seen) "
        "VALUES (?,?,?,?,?,?)",
        ("win", "python", "UNSCOPED_WIN", "confident", now.isoformat(), now.isoformat()),
    )
    conn.execute(
        "INSERT INTO study_sessions(id,topic,started_at,duration_minutes) VALUES (?,?,?,?)",
        ("learning-session", "UNSCOPED_STUDY_SESSION", now.isoformat(), 20),
    )
    conn.commit()
    config = tmp_path / "memory.yaml"
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/consumer/personal"]},
                "work": {"scope": "work", "roots": ["/consumer/work"]},
            },
        }
    }
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_DB", str(db))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
    conn.close()
    return db, config, settings


def test_history_resume_and_streaks_exclude_newer_work_source(consumer_db):
    found = search.topic_frequency(["python", "redshift"])
    assert {row["session_id"] for row in found} == {"personal"}
    struggles = search.struggle_topics(min_sessions=1)
    assert "redshift" not in json.dumps(struggles)
    assert "python" in json.dumps(struggles)
    summary = sessions.get_last_session_summary()
    assert summary is not None
    assert summary["session_id"] == "personal"
    assert "PERSONAL_ONLY" in summary["last_message_preview"]
    assert "WORK_ONLY" not in json.dumps(summary)
    assert "UNSCOPED_MERGED_CONTENT" not in json.dumps(summary)
    assert summary["concepts_scope_status"] == "withheld_missing_scope_lineage"
    assert streaks.get_study_streaks()["sessions_this_week"] == 1


def test_extractor_selection_and_body_reads_filter_before_provider(consumer_db):
    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    received = []

    def provider(messages, session_id):
        received.append((session_id, messages))
        return []

    try:
        assert _extract._most_recent_session(conn, "kiro_cli") == "personal"
        assert _extract._sessions_for_source(conn, "kiro_cli", None) == ["personal"]
        assert _extract._fetch_messages(conn, "work") == []
        assert _extract._session_source(conn, "work") is None
        with pytest.raises(ScopeError, match="unavailable"):
            _extract._process_one(conn, "work", provider, dry_run=True)
        assert received == []
        _extract._process_one(conn, "personal", provider, dry_run=True)
        assert len(received) == 1 and received[0][0] == "personal"
        assert "WORK_ONLY" not in json.dumps(received)
    finally:
        conn.close()


def test_mismatched_progress_input_is_refused_before_provider(consumer_db):
    from studyloop.extractors.pipeline import extract_and_write

    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    called = []
    try:
        before = conn.execute("SELECT * FROM study_progress ORDER BY id").fetchall()
        with pytest.raises(ValueError, match="does not match"):
            extract_and_write(
                "personal", [], lambda *args: called.append(args) or [], connection=conn
            )
        assert called == []
        assert conn.execute("SELECT * FROM study_progress ORDER BY id").fetchall() == before
    finally:
        conn.close()


@pytest.mark.parametrize("mutation", ["edit", "reclassify", "forget"])
def test_extractor_releases_snapshot_and_rechecks_access(consumer_db, mutation):
    from agent_session_tools.context.observations import ObservationStore
    from agent_session_tools.context.provenance import Scope
    from agent_session_tools.context.store import Access, ContextStore
    from studyloop.extractors import ExtractorResult
    from studyloop.extractors.pipeline import extract_and_write

    db, config, settings = consumer_db
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    messages = _extract._fetch_messages(conn, "personal")
    conn.rollback()

    def provider(received, session_id):
        assert not conn.in_transaction
        assert received == messages and session_id == "personal"
        with sqlite3.connect(db, timeout=0.2) as other:
            other.execute("PRAGMA foreign_keys=ON")
            other.execute("BEGIN IMMEDIATE")
            if mutation == "edit":
                other.execute(
                    "UPDATE messages SET content='CHANGED_AFTER_CALL' WHERE session_id='personal'"
                )
            elif mutation == "forget":
                other.execute(
                    "INSERT INTO context_tombstones(session_id,deletion_id,deleted_at) "
                    "VALUES ('personal','fixture-deletion','2026-09-06')"
                )
            else:
                settings["memory"]["projects"]["personal"]["scope"] = "work"
                config.write_text(json.dumps(settings))
                apply_policy(other, ScopePolicy.from_config(settings), actor="test", dry_run=False)
        return [ExtractorResult("python", "generators", "learning", "MODEL_ASSESSMENT")]

    try:
        before = conn.execute("SELECT * FROM study_progress ORDER BY id").fetchall()
        if mutation == "edit":
            assert extract_and_write("personal", messages, provider, connection=conn) == 1
            report = ObservationStore(conn).list("studyloop.progress")[0]
            assert report["semantic_status"] == "unverified_interpretation"
            from agent_session_tools.context.store import _hash, _json

            assert report["payload"]["input_trace"]["fingerprint"] == _hash(_json(messages))
            assert report["source_relationship"] == "captured_input"
            sources = [
                ContextStore(conn).source(ref["id"], Access(scope=Scope.PERSONAL))
                for ref in report["sources"]
            ]
            assert all(source is not None for source in sources)
            assert {source["body"] for source in sources if source is not None} == {
                m["content"] for m in messages
            }
            assert all(source["origin"] == "unknown" for source in sources if source is not None)
            assert "CHANGED_AFTER_CALL" not in json.dumps(sources)
        else:
            with pytest.raises(ScopeError):
                extract_and_write("personal", messages, provider, connection=conn)
            assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 0
        assert conn.execute("SELECT * FROM study_progress ORDER BY id").fetchall() == before
    finally:
        conn.close()


def test_extractor_preserves_borrowed_transaction_and_rolls_back_failed_batch(consumer_db):
    from studyloop.extractors import ExtractorResult
    from studyloop.extractors.pipeline import extract_and_write

    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        messages = _extract._fetch_messages(conn, "personal")
        conn.rollback()
        conn.execute("UPDATE sessions SET updated_at='caller-owned' WHERE id='personal'")
        called = []
        with pytest.raises(ValueError, match="caller transaction"):
            extract_and_write(
                "personal", messages, lambda *args: called.append(args) or [], connection=conn
            )
        assert not called and conn.in_transaction
        assert (
            conn.execute("SELECT updated_at FROM sessions WHERE id='personal'").fetchone()[0]
            == "caller-owned"
        )
        conn.rollback()

        def invalid_batch(*args):
            # First report is valid; the second fails its write-time text check.
            return [
                ExtractorResult("python", "one", "learning"),
                ExtractorResult("python", "two", "learning", notes=cast("str", 42)),
            ]

        with pytest.raises(ValueError, match="text fields"):
            extract_and_write("personal", messages, invalid_batch, connection=conn)
        assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 0
        assert not conn.in_transaction
    finally:
        conn.close()


def test_input_order_changes_binding_but_identical_replays_deduplicate(consumer_db):
    from agent_session_tools.context.observations import ObservationStore
    from studyloop.extractors import ExtractorResult
    from studyloop.extractors.pipeline import extract_and_write

    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    def provider(*args):
        return [ExtractorResult("python", "generators", "learning")]

    try:
        original = _extract._fetch_messages(conn, "personal")
        conn.rollback()
        for _ in range(2):
            extract_and_write("personal", original, provider, connection=conn)
        assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 1
        conn.execute("UPDATE messages SET seq=1-seq WHERE session_id='personal'")
        conn.commit()
        reordered = _extract._fetch_messages(conn, "personal")
        assert reordered == list(reversed(original))
        conn.rollback()
        extract_and_write("personal", reordered, provider, connection=conn)
        reports = ObservationStore(conn).list("studyloop.progress")
        assert len(reports) == 2
        assert len({r["payload"]["input_trace"]["fingerprint"] for r in reports}) == 2
        assert {s["id"] for s in reports[0]["sources"]} == {s["id"] for s in reports[1]["sources"]}
    finally:
        conn.close()


def test_borrowed_progress_writer_leaves_commit_to_caller(consumer_db):
    from studyloop.history.progress import _record_progress_on_connection

    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _record_progress_on_connection(conn, "python", "generators", "learning")
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0
    finally:
        conn.close()


def test_same_concept_scopes_conflicts_reclassification_and_source_removal(
    consumer_db, monkeypatch
):
    from agent_session_tools.context.legacy_sources import capture_session_input
    from agent_session_tools.context.store import ContextStore
    from studyloop.history import observations

    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        personal = observations.record(
            conn,
            "python",
            "generators",
            "learning",
            "PERSONAL_NOTE",
            source_session_id="personal",
            created_by="extractor",
        )
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
        observations.record(
            conn,
            "python",
            "generators",
            "confident",
            "WORK_NOTE",
            source_session_id="work",
            created_by="extractor",
        )
        work_refs = capture_session_input(conn, "work").evidence_ids
        conn.commit()
        assert "PERSONAL_NOTE" not in json.dumps(observations.rows(conn))
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
        own = observations.rows(conn)
        assert len(own) == 1 and own[0]["observation_ids"] == [personal]
        assert "WORK_NOTE" not in json.dumps(own)
        assert own[0]["session_count"] == 1
        conn.rollback()
        ContextStore(conn).assign_session("work", "personal")
        both = observations.rows(conn)
        assert both[0]["confidence_status"] == "conflicting_reports"
        assert both[0]["reported_confidences"] == ["learning", "confident"]
        assert both[0]["session_count"] == 2
        conn.execute("DELETE FROM context_evidence WHERE id=?", (work_refs[0],))
        remaining = observations.rows(conn)
        assert remaining[0]["session_count"] == 1
        assert remaining[0]["confidence_status"] == "unverified_interpretation"
        assert "WORK_NOTE" not in json.dumps(remaining)
    finally:
        conn.close()


def test_manual_revision_does_not_copy_unbound_notes_and_retirement_blocks_legacy_fallback(
    consumer_db, monkeypatch
):
    from agent_session_tools.context.observations import ObservationStore
    from studyloop.history import observations

    db, config, _ = consumer_db
    # Explicit legacy inspection with no assigned projects is required to expose
    # a fallback. This fixture contains a same-subject old aggregate as a trap.
    settings = {"memory": {"default_scope": "unclassified", "projects": {}}}
    config.write_text(json.dumps(settings))
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("DELETE FROM context_session_projects")
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
    try:
        first = observations.record(
            conn, "sql", "UNSCOPED_MERGED_CONTENT", "learning", "ORIGINAL_NOTE"
        )
        second = observations.record(conn, "sql", "UNSCOPED_MERGED_CONTENT", "confident")
        current = next(r for r in observations.rows(conn) if r["topic"] == "sql")
        assert current["notes"] is None and current["observation_ids"] == [second]
        original = ObservationStore(conn).get(first)
        assert original is not None and original["payload"]["notes"] == "ORIGINAL_NOTE"
        assert ObservationStore(conn).forget(second)
        assert not any(r["topic"] == "sql" for r in observations.rows(conn))
        assert ObservationStore(conn).forget(first)
        assert not any(r["topic"] == "sql" for r in observations.rows(conn))
    finally:
        conn.close()


def test_eval_withholds_excluded_labels_and_uses_read_only_database(consumer_db, monkeypatch):
    from studyloop.extractors import eval_runner

    db, _, _ = consumer_db
    golden = [{"session_id": sid, "is_negative": False} for sid in ["personal", "work"]]
    monkeypatch.setattr(
        eval_runner,
        "_load",
        lambda path: (
            golden if path == eval_runner._GOLDEN_PATH else {"train": ["personal", "work"]}
        ),
    )
    received = []

    def provider(messages, session_id, **kwargs):
        received.append((session_id, messages))
        return []

    monkeypatch.setattr(eval_runner, "extract_struggles", provider)
    _, _, scores = eval_runner.run_eval("train", db_path=db, model="fixture")
    assert [sid for sid, _ in received] == ["personal"]
    assert scores[1].error == "Session unavailable in the configured scope"
    assert "WORK_ONLY" not in json.dumps(received)
    missing = db.parent / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        eval_runner.run_eval("train", db_path=missing, model="fixture")
    assert not missing.exists()


def test_resume_cli_explains_withholding_and_policy_error(consumer_db):
    _, config, settings = consumer_db
    runner = CliRunner()
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 0, repr(result.exception)
    assert "work/personal scope is known" in result.output
    assert "WORK_ONLY" not in result.output
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    config.write_text(json.dumps(settings))
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 1
    assert "session-context policy apply" in result.output
    assert "PERSONAL_ONLY" not in result.output


def test_studyloop_mcp_history_withholds_unowned_learning_fields(consumer_db):
    from studyloop.history import get_wins
    from studyloop.mcp.server import mcp

    tool = mcp._tool_manager._tools["get_study_history"].fn
    result = tool(topic="python")
    assert result["last_studied"] is not None
    assert result["session_stats"] == []
    assert result["wins"] == []
    assert result["learning_scope_status"] == "withheld_missing_scope_lineage"
    assert "UNSCOPED" not in json.dumps(result)
    assert sessions.get_study_session_stats() == []
    assert get_wins() == []


def test_memory_config_is_recognised_by_studyloop(consumer_db):
    from studyloop.settings import unknown_top_level_keys

    assert "memory" not in unknown_top_level_keys()


def test_owned_sessions_scores_and_bridges_keep_useful_history_in_each_scope(
    consumer_db, monkeypatch
):
    from studyloop.history import bridges, observations, teachback

    db, _, _ = consumer_db
    personal = sessions.start_study_session("python", "high", session_id="personal")
    assert personal is not None
    assert sessions.end_study_session(personal, "PERSONAL_SESSION", win_count=1, struggle_count=0)
    assert sessions.update_persona_hash(personal, "personal-persona")
    assert teachback.record_teachback(
        "generators",
        "python",
        (2, 2, 2, 2, 2),
        "micro",
        notes="PERSONAL_SCORE",
        session_id="personal",
    )
    assert bridges.record_bridge("packets", "network", "generators", "python", "PERSONAL_BRIDGE")
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    work = sessions.start_study_session("python", "low", session_id="work")
    assert work is not None
    assert sessions.end_study_session(work, "WORK_SESSION", win_count=0, struggle_count=1)
    assert sessions.update_persona_hash(work, "work-persona")
    for _ in range(25):
        assert teachback.record_teachback(
            "generators",
            "python",
            (4, 4, 4, 4, 4),
            "full",
            notes="WORK_SCORE",
            session_id="work",
        )
    assert bridges.record_bridge("packets", "network", "generators", "python", "WORK_BRIDGE")
    work_bridge = bridges.get_bridges()[0]["id"]
    assert sessions.get_session_notes(personal) is None
    assert sessions.end_study_session(personal, "WRONG_SCOPE") is False
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    assert sessions.get_session_notes(work) is None
    assert sessions.update_persona_hash(work, "WRONG_SCOPE") is False
    assert bridges.update_bridge_usage(work_bridge, True) is False
    assert sessions.get_session_notes(personal) == "PERSONAL_SESSION"
    stats = sessions.get_study_session_stats()
    assert sum(r["sessions"] for r in stats) == 1
    assert len(sessions.get_energy_session_data()) == 1
    latest = sessions.get_last_study_session()
    assert latest is not None and latest["energy_level"] == "high"
    assert sessions.get_persona_effectiveness()[0]["persona_hash"] == "personal-persona"
    scores = teachback.get_teachback_history("generators")
    assert len(scores) == 1 and scores[0]["notes"] == "PERSONAL_SCORE"
    assert [r["structural_mapping"] for r in bridges.get_bridges()] == ["PERSONAL_BRIDGE"]
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        projected = observations.rows(conn)
        assert projected[0]["last_teachback_score"] == 10
        assert "WORK_SCORE" not in json.dumps(projected)
        # The legacy aggregate remains untouched by the new teachback writer.
        assert not conn.execute(
            "SELECT 1 FROM study_progress WHERE concept='generators'"
        ).fetchone()
    from studyloop.mcp.server import mcp

    answer = mcp._tool_manager._tools["get_study_history"].fn(topic="python")
    assert answer["learning_scope_status"] == "scoped_learning_records"
    assert answer["session_stats"][0]["sessions"] == 1
    assert answer["teachback_scores"][0]["notes"] == "PERSONAL_SCORE"
    assert "WORK_" not in json.dumps(answer)


def test_score_only_history_has_accurate_scope_status_and_time_window(consumer_db):
    from studyloop.history import teachback
    from studyloop.mcp.server import mcp

    db, _, _ = consumer_db
    assert teachback.record_teachback(
        "generators", "python", (2, 2, 2, 2, 2), "micro", notes="RECENT_SCORE"
    )
    tool = mcp._tool_manager._tools["get_study_history"].fn
    result = tool(topic="python", days=30)
    assert result["session_stats"] == []
    assert result["teachback_scores"][0]["notes"] == "RECENT_SCORE"
    assert result["learning_scope_status"] == "scoped_learning_records"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE teach_back_scores SET created_at=datetime('now','-40 days')")
    assert tool(topic="python", days=30)["teachback_scores"] == []
    assert len(tool(topic="python", days=60)["teachback_scores"]) == 1


def test_linked_learning_records_follow_source_reclassification_and_tombstone(consumer_db):
    from studyloop.history import teachback

    db, _, _ = consumer_db
    identity = sessions.start_study_session("python", "high", session_id="personal")
    assert identity
    sessions.end_study_session(identity, "SOURCE_LINKED_NOTE")
    assert teachback.record_teachback(
        "generators", "python", (3, 3, 3, 3, 3), "micro", session_id="personal"
    )
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "UPDATE context_session_projects SET project_id='work' WHERE session_id='personal'"
        )
    assert sessions.get_session_notes(identity) is None
    assert teachback.get_teachback_history("generators") == []
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO context_tombstones(session_id,deletion_id,deleted_at) "
            "VALUES ('personal','forget-fixture','2026-09-06')"
        )
        assert not conn.execute("SELECT 1 FROM study_sessions WHERE id=?", (identity,)).fetchone()
        assert conn.execute("SELECT count(*) FROM teach_back_scores").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_teachback_failure_rolls_back_score_ownership_and_progress(consumer_db, monkeypatch):
    from studyloop.history import observations, teachback

    db, _, _ = consumer_db

    def fail(*args, **kwargs):
        raise RuntimeError("injected progress failure")

    monkeypatch.setattr(observations, "record", fail)
    with pytest.raises(RuntimeError, match="injected"):
        teachback.record_teachback("generators", "python", (3, 3, 3, 3, 3), "micro")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM teach_back_scores").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM context_record_owners").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0


def test_source_linked_teachback_without_capture_refuses_without_partial_state(consumer_db):
    from studyloop.history import teachback

    db, _, _ = consumer_db
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM messages WHERE session_id='personal'")
    with pytest.raises(ScopeError, match="nonempty captured input"):
        teachback.record_teachback(
            "generators", "python", (3, 3, 3, 3, 3), "micro", session_id="personal"
        )
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM teach_back_scores").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM context_record_owners").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0


def test_notes_parking_and_board_metadata_are_scoped_before_limits_and_bulk_writes(
    consumer_db, monkeypatch
):
    from studyloop import notes, parking

    db, _, _ = consumer_db
    monkeypatch.setattr(notes, "get_db_path", lambda: db)
    monkeypatch.setattr(parking, "get_db_path", lambda: db)
    study = sessions.start_study_session("python", "high", session_id="personal")
    personal_note = notes.add_note("PERSONAL_NOTE", body="PERSONAL_BODY", study_session_id=study)
    personal_park = parking.park_topic("Shared wording", session_id="personal")
    assert personal_note and personal_park
    assert parking.park_topic("Shared wording", session_id="personal") == personal_park
    assert parking.add_board_column("Private") is not None
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    work_ids = [notes.add_note(f"WORK_NOTE_{n}", body="WORK_BODY") for n in range(25)]
    work_park = parking.park_topic("Shared wording", session_id="work")
    assert work_park and work_park != personal_park
    for _ in range(3):
        parking.park_topic("Shared wording", session_id="work")
    work_column = parking.add_board_column("Private")
    assert work_column is not None and work_column["key"] == "private"
    assert parking.add_board_column("WORK_COLUMN") is not None
    assert notes.get_note(personal_note) is None
    assert notes.update_note(personal_note, body="WRONG") is None
    assert not parking.update_topic_priority(personal_park, 5)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    assert [row["title"] for row in notes.list_notes(limit=1)] == ["PERSONAL_NOTE"]
    assert notes.count_notes() == 1
    assert "WORK_" not in notes.notes_markdown()
    assert parking.get_topic_frequencies() == {"Shared wording": 2}
    assert parking.get_board()["total"] == 1
    assert "WORK_COLUMN" not in json.dumps(parking.get_board_columns())
    assert not parking.move_parked_topic(work_park, "next")
    assert not parking.rename_board_column("work-column", "LEAK")
    assert notes.clear_all_notes(hard=True) == 1
    assert parking.clear_all_parked_topics(hard=True) == 1
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    assert notes.count_notes() == len(work_ids)
    assert parking.get_topic_frequencies() == {"Shared wording": 4}
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_notes_require_both_native_and_study_parent_scope_and_purge_dependencies(
    consumer_db, monkeypatch
):
    from studyloop import notes, parking

    db, _, _ = consumer_db
    monkeypatch.setattr(notes, "get_db_path", lambda: db)
    monkeypatch.setattr(parking, "get_db_path", lambda: db)
    study = sessions.start_study_session("python", "high", session_id="personal")
    # An application placeholder may be owned before native capture; native IDs are never invented.
    placeholder_note = notes.add_note("APP_ONLY", study_session_id="application-before-capture")
    assert placeholder_note
    with pytest.raises(ScopeError, match="unavailable"):
        notes.add_note("MUST_NOT_EXIST", session_id="unknown-native")
    with sqlite3.connect(db) as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE id='unknown-native'").fetchone()
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) "
            "VALUES ('other-personal','fixture','/consumer/personal')"
        )
        conn.execute(
            "INSERT INTO context_session_projects(session_id,project_id) "
            "SELECT 'other-personal',project_id FROM context_session_projects "
            "WHERE session_id='personal'"
        )
    identity = notes.add_note(
        "TWO_DEPENDENCIES", session_id="other-personal", study_session_id=study
    )
    assert identity and notes.get_note(identity)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE context_session_projects SET project_id='work' WHERE session_id='personal'"
        )
    assert notes.get_note(identity) is None
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO context_tombstones VALUES ('personal','forget-parent','2026-09-06')"
        )
        assert not conn.execute("SELECT 1 FROM study_notes WHERE id=?", (identity,)).fetchone()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert notes.get_note(placeholder_note)


def test_web_reports_scope_setup_errors_without_returning_excluded_content(
    consumer_db, monkeypatch
):
    from fastapi.testclient import TestClient

    from studyloop import notes, parking
    from studyloop.web.app import create_app

    db, config, settings = consumer_db
    monkeypatch.setattr(notes, "get_db_path", lambda: db)
    monkeypatch.setattr(parking, "get_db_path", lambda: db)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    work_study = sessions.start_study_session("WORK_TOPIC", "high", session_id="work")
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    client = TestClient(create_app(study_dirs=[]))
    response = client.post(
        "/api/notes", json={"title": "must fail", "study_session_id": work_study}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "context_scope_unavailable"
    assert "WORK_TOPIC" not in response.text
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    config.write_text(json.dumps(settings))
    response = client.get("/api/notes")
    assert response.status_code == 409 and "policy apply" in response.text


def test_practice_attempt_and_derived_progress_are_atomic_scoped_and_deletable(
    consumer_db, tmp_path, monkeypatch
):
    import shlex
    import sys
    from pathlib import Path

    from studyloop.history import observations
    from studyloop.learning import practice

    db, _, _ = consumer_db
    command = shlex.join([sys.executable, "-c", "print('synthetic check')"])
    deck = tmp_path / "practice.json"
    deck.write_text(
        json.dumps(
            {
                "title": "Python Practice",
                "tasks": [
                    {
                        "taskType": "build",
                        "prompt": "Synthetic check",
                        "setup": "",
                        "successCriteria": ["process exits"],
                        "hint": "",
                        "expectedLearningOutcome": "generators",
                        "verification": {
                            "kind": "command",
                            "command": command,
                            "successCriteria": ["process exits"],
                        },
                    }
                ],
            }
        )
    )
    result = practice.verify_practice_task(
        deck,
        task_index=1,
        workdir=tmp_path,
        run_command=True,
        confirmed_command=command,
        notes="PERSONAL_PRACTICE",
    )
    assert result.passed and result.progress_recorded
    attempts = practice.list_practice_attempts()
    assert len(attempts) == 1
    assert attempts[0]["validation_of_learning"] == "not_established"
    with pytest.raises(ScopeError, match="outside"):
        practice.verify_practice_task(
            deck,
            task_index=1,
            workdir=Path("/consumer/work"),
            run_command=True,
            confirmed_command=command,
        )
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    assert practice.list_practice_attempts() == []
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert observations.rows(conn)
        conn.rollback()
        conn.execute("DELETE FROM practice_attempts")
        conn.commit()
        assert not observations.rows(conn)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    def fail(*args, **kwargs):
        raise RuntimeError("injected progress failure")

    monkeypatch.setattr(practice.observations, "record", fail)
    with pytest.raises(RuntimeError, match="injected"):
        practice.verify_practice_task(
            deck, task_index=1, workdir=tmp_path, run_command=True, confirmed_command=command
        )
    assert practice.list_practice_attempts() == []


def test_practice_project_reclassification_and_policy_change_during_execution(
    consumer_db, tmp_path, monkeypatch
):
    import subprocess
    from types import SimpleNamespace

    from studyloop.history import observations
    from studyloop.learning import practice

    db, config, settings = consumer_db
    settings["memory"]["projects"]["personal"]["roots"].append(str(tmp_path))
    config.write_text(json.dumps(settings))
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
    deck = SimpleNamespace(
        title="Python Practice",
        tasks=[SimpleNamespace(prompt="Synthetic check", expected_learning_outcome="generators")],
    )
    monkeypatch.setattr(practice, "load_practice_deck", lambda _: deck)
    monkeypatch.setattr(practice, "_verification_kind", lambda _: "command")
    monkeypatch.setattr(practice, "_verification_command", lambda _: "synthetic")
    for name in ("_expected_artifacts", "_verification_rubric", "_verification_evidence_prompts"):
        monkeypatch.setattr(practice, name, lambda _: [])
    monkeypatch.setattr(practice, "_verification_setup_command", lambda _: "")
    monkeypatch.setattr(practice, "_verification_timeout", lambda *_: 10)
    monkeypatch.setattr(
        practice.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "ok", "")
    )

    def verify():
        return practice.verify_practice_task(
            tmp_path / "deck.json",
            task_index=1,
            workdir=tmp_path,
            run_command=True,
            confirmed_command="synthetic",
        )

    assert verify().progress_recorded
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        owners = conn.execute(
            "SELECT project_id FROM context_record_owners WHERE table_name='practice_attempts'"
        ).fetchall()
        assert owners == [("personal",)]
        assert observations.rows(conn)
        conn.rollback()
        settings["memory"]["projects"]["personal"]["scope"] = "work"
        config.write_text(json.dumps(settings))
        apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
        assert not observations.rows(conn)
    assert practice.list_practice_attempts() == []

    settings["memory"]["projects"]["personal"]["scope"] = "personal"
    config.write_text(json.dumps(settings))
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
        before = conn.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0]

    def change_policy(*args, **kwargs):
        settings["memory"]["projects"]["personal"]["scope"] = "work"
        config.write_text(json.dumps(settings))
        return subprocess.CompletedProcess(args, 0, "ran before policy changed", "")

    monkeypatch.setattr(practice.subprocess, "run", change_policy)
    with pytest.raises(ScopeError):
        verify()
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert conn.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0] == before


def test_studyloop_stdio_history_keeps_scope_across_requests(consumer_db):
    import asyncio
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, config, settings = consumer_db

    async def journey():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "studyloop.mcp.server"],
            env=dict(os.environ),
        )
        async with (
            stdio_client(params) as (reader, writer),
            ClientSession(reader, writer) as client,
        ):
            await client.initialize()
            response = await client.call_tool("get_study_history", {"topic": "python"})
            assert not response.isError
            text = "".join(block.text for block in response.content if block.type == "text")
            assert "withheld_missing_scope_lineage" in text
            assert "UNSCOPED" not in text and "WORK_ONLY" not in text
            settings["memory"]["projects"]["personal"]["scope"] = "work"
            config.write_text(json.dumps(settings))
            response = await client.call_tool("get_study_history", {"topic": "python"})
            assert response.isError
            text = "".join(block.text for block in response.content if block.type == "text")
            assert "policy apply" in text
            assert "PERSONAL_ONLY" not in text and "WORK_ONLY" not in text

    asyncio.run(journey())


@pytest.mark.parametrize("read", [sessions.get_last_session_summary, streaks.get_study_streaks])
def test_missing_policy_is_not_presented_as_no_history(consumer_db, read):
    _, config, _ = consumer_db
    config.write_text("memory: {}\n")
    with pytest.raises(ScopeError, match="No context scope"):
        read()
