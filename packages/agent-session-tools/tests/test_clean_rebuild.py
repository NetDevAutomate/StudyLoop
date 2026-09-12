"""Tests for agent_session_tools.clean_rebuild — the filtered clean-start copy.

One discriminating test per classification decision. A fixture database is
built with init_db (the same migration the destination uses) and then given
the shapes the live database had on 2026-09-12: a junk-only session, a
legacy-source session with a human turn, a supported-harness session with a
human turn, a NULL-session learner record, and a table the migration does
not create.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent_session_tools import clean_rebuild as cr
from agent_session_tools.clean_rebuild import (
    UnclassifiedTableError,
    archive_source,
    classify_schema,
    rebuild_clean,
)
from agent_session_tools.export_sessions import init_db

HUMAN = "Can you explain how Spark decides the number of partitions for a join?"
PROSE = "Spark sizes shuffle partitions from spark.sql.shuffle.partitions; AQE can coalesce them."


def _fixture(path: Path) -> None:
    init_db(str(path)).close()
    c = sqlite3.connect(path)
    with c:
        # kept: supported harness + a human turn
        c.execute("INSERT INTO sessions (id, source) VALUES ('keep', 'kiro_cli')")
        c.executemany(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, 'keep', ?, ?)",
            [
                ("k1", "user", HUMAN),
                ("k2", "assistant", PROSE),
                ("k3", "assistant", "[tool:Bash]"),  # dropped row inside a kept session
                ("k4", "user", "ok"),  # ack, dropped
            ],
        )
        # dropped: supported harness but no human turn (sub-agent transcript)
        c.execute("INSERT INTO sessions (id, source) VALUES ('noh', 'claude_code')")
        c.executemany(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, 'noh', ?, ?)",
            [("n1", "assistant", PROSE), ("n2", "assistant", "[tool:Read]")],
        )
        # dropped: human turn but legacy source
        c.execute("INSERT INTO sessions (id, source) VALUES ('legacy', 'aider')")
        c.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES ('l1', 'legacy', 'user', ?)",
            (HUMAN,),
        )
        # follow-message rows: one on a kept message, one on a dropped message
        c.execute(
            "INSERT INTO file_references (message_id, session_id, file_path, tool_name) VALUES ('k1', 'keep', '/a.py', 'Read')"
        )
        c.execute(
            "INSERT INTO file_references (message_id, session_id, file_path, tool_name) VALUES ('k3', 'keep', '/b.py', 'Read')"
        )
        # follow-session rows
        c.execute("INSERT INTO session_tags (session_id, tag) VALUES ('keep', 'spark')")
        c.execute("INSERT INTO session_tags (session_id, tag) VALUES ('noh', 'agent')")
        # NULL-session learner record must survive; a record pointing at a
        # dropped session must survive with its pointer nulled
        c.execute(
            "INSERT INTO study_sessions (id, session_id, started_at) VALUES ('ss-null', NULL, '2026-09-12T00:00:00Z')"
        )
        c.execute(
            "INSERT INTO parked_topics (question, session_id, source) VALUES ('what is AQE?', 'noh', 'struggled')"
        )
        # a table the migration does not create, written by another package
        c.execute("CREATE TABLE study_plans (id TEXT PRIMARY KEY, title TEXT)")
        c.execute("INSERT INTO study_plans VALUES ('p1', 'Spark in 4 weeks')")
    c.close()


@pytest.fixture
def src(tmp_path: Path) -> Path:
    p = tmp_path / "live.db"
    _fixture(p)
    return p


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


# ── exhaustiveness ────────────────────────────────────────────────────────────


def test_classify_schema_covers_fixture(src: Path) -> None:
    conn = sqlite3.connect("file::memory:", uri=True)
    conn.execute("ATTACH DATABASE ? AS src", (src.resolve().as_uri() + "?mode=ro",))
    classified = classify_schema(conn, "src")
    assert classified["sessions"] == "filtered"
    assert classified["messages_fts"] == "rebuilt"
    assert classified["messages_fts_data"] == "fts_shadow"
    assert classified["study_plans"] == "verbatim"


def test_unknown_table_raises_with_its_name(src: Path) -> None:
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE totally_new_thing (x)")
    c.execute(
        "CREATE TABLE plain_table_data (x)"
    )  # ends in _data but is NOT an fts shadow
    c.close()
    conn = sqlite3.connect("file::memory:", uri=True)
    conn.execute("ATTACH DATABASE ? AS src", (src.resolve().as_uri() + "?mode=ro",))
    with pytest.raises(UnclassifiedTableError) as exc:
        classify_schema(conn, "src")
    assert "totally_new_thing" in str(exc.value)
    assert "plain_table_data" in str(exc.value)


def test_classification_sets_are_disjoint() -> None:
    sets = [
        cr.FILTERED,
        cr.FOLLOW_MESSAGE,
        cr.FOLLOW_SESSION,
        cr.EVIDENCE,
        cr.NULL_SESSION_IF_DROPPED,
        cr.VERBATIM,
        cr.INSTANCE_SINGLETONS,
        cr.REBUILT,
    ]
    seen: set[str] = set()
    for s in sets:
        assert not (s & seen), s & seen
        seen |= s


# ── dry run ───────────────────────────────────────────────────────────────────


def test_dry_run_reports_keep_set_and_writes_nothing(src: Path, tmp_path: Path) -> None:
    before = src.read_bytes()
    stats = rebuild_clean(src, None, dry_run=True)
    assert stats.dry_run
    assert stats.sessions_kept == 1 and stats.sessions_total == 3
    assert stats.messages_kept == 2 and stats.messages_total == 7
    assert src.read_bytes() == before
    assert not list(tmp_path.glob("*.clean.db"))


# ── real run: the keep rules ──────────────────────────────────────────────────


@pytest.fixture
def built(src: Path, tmp_path: Path) -> tuple[Path, cr.RebuildStats]:
    dest = tmp_path / "clean.db"
    stats = rebuild_clean(src, dest, dry_run=False)
    return dest, stats


def test_source_is_untouched(src: Path, tmp_path: Path) -> None:
    before = src.read_bytes()
    rebuild_clean(src, tmp_path / "c.db", dry_run=False)
    assert src.read_bytes() == before


def test_keeps_only_real_conversations(built: tuple[Path, cr.RebuildStats]) -> None:
    dest, stats = built
    c = _ro(dest)
    assert {r[0] for r in c.execute("SELECT id FROM sessions")} == {"keep"}
    assert {r[0] for r in c.execute("SELECT id FROM messages")} == {"k1", "k2"}
    assert stats.fk_violations == 0 and stats.fts_rows == 2


def test_follow_message_and_follow_session(built: tuple[Path, cr.RebuildStats]) -> None:
    dest, _ = built
    c = _ro(dest)
    assert [r[0] for r in c.execute("SELECT message_id FROM file_references")] == ["k1"]
    assert [r[0] for r in c.execute("SELECT session_id FROM session_tags")] == ["keep"]


def test_null_session_learner_record_survives(
    built: tuple[Path, cr.RebuildStats],
) -> None:
    dest, _ = built
    c = _ro(dest)
    assert (
        c.execute("SELECT COUNT(*) FROM study_sessions WHERE id='ss-null'").fetchone()[
            0
        ]
        == 1
    )


def test_parked_topic_survives_with_dropped_session_nulled(
    built: tuple[Path, cr.RebuildStats],
) -> None:
    dest, _ = built
    c = _ro(dest)
    rows = c.execute("SELECT question, session_id FROM parked_topics").fetchall()
    assert rows == [("what is AQE?", None)]


def test_table_absent_from_migration_is_carried_with_rows(
    built: tuple[Path, cr.RebuildStats],
) -> None:
    dest, stats = built
    assert "study_plans" in stats.tables_carried
    c = _ro(dest)
    assert c.execute("SELECT title FROM study_plans").fetchone() == (
        "Spark in 4 weeks",
    )


def test_rebuilt_tables_start_empty(built: tuple[Path, cr.RebuildStats]) -> None:
    dest, stats = built
    c = _ro(dest)
    assert c.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0] == 0
    assert "message_embeddings" in stats.tables_rebuilt


def test_fts_index_matches_kept_messages(built: tuple[Path, cr.RebuildStats]) -> None:
    dest, _ = built
    c = _ro(dest)
    hits = c.execute(
        "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'partitions'"
    ).fetchall()
    assert (
        len(hits) == 2
    )  # k1 and k2 both mention partitions; k3/n1 must not be indexed
    stale = c.execute(
        "SELECT COUNT(*) FROM messages_fts WHERE rowid NOT IN (SELECT rowid FROM messages)"
    ).fetchone()[0]
    assert stale == 0


def test_refuses_to_overwrite_or_self_target(src: Path, tmp_path: Path) -> None:
    dest = tmp_path / "exists.db"
    dest.write_bytes(b"")
    with pytest.raises(FileExistsError):
        rebuild_clean(src, dest, dry_run=False)
    with pytest.raises(ValueError):
        rebuild_clean(src, src, dry_run=False)


# ── archive ───────────────────────────────────────────────────────────────────


def test_archive_moves_never_deletes(src: Path, tmp_path: Path) -> None:
    payload = src.read_bytes()
    (src.parent / (src.name + "-wal")).write_bytes(b"wal")
    target = archive_source(src, tmp_path / "archive", review_after="2026-12-12")
    assert not src.exists()
    assert target.read_bytes() == payload
    assert (tmp_path / "archive" / (target.name + "-wal")).exists()
    readme = (tmp_path / "archive" / "README.md").read_text()
    assert "2026-12-12" in readme and target.name in readme


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_cli_dry_run_by_default_writes_nothing(src: Path, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from agent_session_tools.maintenance import app

    before = src.read_bytes()
    r = CliRunner().invoke(
        app, ["clean-start", "--db", str(src), "--dest", str(tmp_path / "new.db")]
    )
    assert r.exit_code == 0, r.output
    assert "DRY RUN" in r.output and "keep 1 of 3" in r.output
    assert not (tmp_path / "new.db").exists()
    assert src.read_bytes() == before


def test_cli_yes_requires_dest(src: Path) -> None:
    from typer.testing import CliRunner

    from agent_session_tools.maintenance import app

    r = CliRunner().invoke(app, ["clean-start", "--db", str(src), "--yes"])
    assert r.exit_code == 2 and "--dest" in r.output


def test_cli_full_run_with_archive_deletes_nothing(src: Path, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from agent_session_tools.maintenance import app

    payload = src.read_bytes()
    dest = tmp_path / "new" / "sessions.db"
    archive = tmp_path / "archive"
    r = CliRunner().invoke(
        app,
        [
            "clean-start",
            "--db",
            str(src),
            "--dest",
            str(dest),
            "--yes",
            "--archive-to",
            str(archive),
        ],
    )
    assert r.exit_code == 0, r.output
    assert dest.exists() and "fk_check : 0" in r.output
    assert not src.exists(), "source must be MOVED to the archive"
    archived = [p for p in archive.iterdir() if p.suffix == ".db"]
    assert len(archived) == 1 and archived[0].read_bytes() == payload
    assert (archive / "README.md").exists()
