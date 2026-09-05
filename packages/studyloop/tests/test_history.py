"""Tests for history module bug fixes."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _make_db(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with the current progress provenance columns."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE study_progress (
            id TEXT PRIMARY KEY,
            topic TEXT,
            concept TEXT,
            confidence TEXT,
            first_seen TEXT,
            last_seen TEXT,
            session_count INTEGER,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            source_course TEXT,
            source_section TEXT,
            source_publisher TEXT,
            source_session_id TEXT,
            created_by TEXT DEFAULT 'agent'
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _make_teachback_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE teach_back_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT NOT NULL,
            topic TEXT NOT NULL,
            session_id TEXT,
            score_accuracy INTEGER,
            score_own_words INTEGER,
            score_structure INTEGER,
            score_depth INTEGER,
            score_transfer INTEGER,
            total_score INTEGER GENERATED ALWAYS AS (
                COALESCE(score_accuracy, 0) + COALESCE(score_own_words, 0)
                + COALESCE(score_structure, 0) + COALESCE(score_depth, 0)
                + COALESCE(score_transfer, 0)
            ) STORED,
            review_type TEXT NOT NULL,
            question_angle TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE study_progress (
            id TEXT PRIMARY KEY,
            topic TEXT,
            concept TEXT,
            confidence TEXT,
            first_seen TEXT,
            last_seen TEXT,
            session_count INTEGER,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            last_teachback_score INTEGER,
            angles_used TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestRecordProgressCaseNormalisation:
    """Bug 1: record_progress() should normalise case for UUID generation."""

    def test_same_id_for_different_cases(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        hist.record_progress("Python", "Decorators", "learning")
        hist.record_progress("python", "decorators", "confident")

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM study_progress").fetchall()
        conn.close()

        assert len(rows) == 1, "Different cases should map to the same row"
        # Should have been updated (session_count incremented)
        assert rows[0][6] == 2  # session_count column

    def test_strips_whitespace(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        hist.record_progress("Python ", " Decorators", "learning")
        hist.record_progress("python", "decorators", "confident")

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM study_progress").fetchall()
        conn.close()

        assert len(rows) == 1


class TestSpacedRepetitionDue:
    def test_uses_study_progress_evidence_not_message_mentions(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)
        last_seen = (datetime.now(UTC) - timedelta(days=15)).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO study_progress
                (id, topic, concept, confidence, first_seen, last_seen, session_count, notes)
            VALUES ('p1', 'python', 'decorators', 'learning', ?, ?, 2, NULL)
            """,
            (last_seen, last_seen),
        )
        conn.commit()
        conn.close()

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn
        import studyloop.history.search as search_mod

        def fail_topic_frequency(*args, **kwargs):
            raise AssertionError("keyword search used")

        monkeypatch.setattr(_conn, "_connect", mock_connect)
        monkeypatch.setattr(search_mod, "topic_frequency", fail_topic_frequency)

        due = hist.spaced_repetition_due({"python": ["python"], "sql": ["sql"]})

        assert due[0]["topic"] == "python"
        assert due[0]["concept"] == "decorators"
        assert due[0]["evidence"] == "study_progress"
        assert due[0]["review_type"] == "Apply to new problem"
        assert due[-1]["topic"] == "sql"
        assert due[-1]["review_type"] == "New topic -- start fresh"

    def test_struggling_concepts_are_due_immediately(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)
        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO study_progress
                (id, topic, concept, confidence, first_seen, last_seen, session_count, notes)
            VALUES ('p1', 'spark', 'partition skew', 'struggling', ?, ?, 1, NULL)
            """,
            (now, now),
        )
        conn.commit()
        conn.close()

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        due = hist.spaced_repetition_due({"spark": ["spark"]})

        assert len(due) == 1
        assert due[0]["concept"] == "partition skew"
        assert due[0]["review_type"] == "Guided repair + tiny practice"

    def test_recent_progress_is_not_reported_as_new_topic(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)
        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO study_progress
                (id, topic, concept, confidence, first_seen, last_seen, session_count, notes)
            VALUES ('p1', 'python', 'decorators', 'learning', ?, ?, 1, NULL)
            """,
            (now, now),
        )
        conn.commit()
        conn.close()

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        due = hist.spaced_repetition_due({"python": ["python"], "sql": ["sql"]})

        assert [item["topic"] for item in due] == ["sql"]
        assert due[0]["review_type"] == "New topic -- start fresh"


class TestTeachbackProgressEvidence:
    def test_record_teachback_creates_progress_evidence(self, tmp_path, monkeypatch):
        db_path = _make_teachback_db(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        ok = hist.record_teachback(
            concept="Decorators",
            topic="Python",
            scores=(4, 4, 4, 4, 4),
            review_type="full",
            angle="bloom_apply",
            notes="Clear transfer.",
        )

        assert ok is True
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        score = conn.execute("SELECT concept, topic, total_score FROM teach_back_scores").fetchone()
        progress = conn.execute(
            """
            SELECT topic, concept, confidence, last_teachback_score, angles_used, notes
            FROM study_progress
            """
        ).fetchone()
        conn.close()

        assert dict(score) == {"concept": "Decorators", "topic": "Python", "total_score": 20}
        assert progress["topic"] == "python"
        assert progress["concept"] == "decorators"
        assert progress["confidence"] == "mastered"
        assert progress["last_teachback_score"] == 20
        assert json.loads(progress["angles_used"]) == ["bloom_apply"]
        assert progress["notes"] == "Clear transfer."


def _make_teachback_db_with_check_constraints(tmp_path: Path) -> Path:
    """Same shape as `_make_teachback_db`, but with the real schema's CHECK
    constraints on `teach_back_scores.score_*` (migrations.py migrate_v10) --
    needed to actually trigger sqlite3.IntegrityError for the R-21 test below.
    """
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE teach_back_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT NOT NULL,
            topic TEXT NOT NULL,
            session_id TEXT,
            score_accuracy INTEGER CHECK(score_accuracy BETWEEN 1 AND 4),
            score_own_words INTEGER CHECK(score_own_words BETWEEN 1 AND 4),
            score_structure INTEGER CHECK(score_structure BETWEEN 1 AND 4),
            score_depth INTEGER CHECK(score_depth BETWEEN 1 AND 4),
            score_transfer INTEGER CHECK(score_transfer BETWEEN 1 AND 4),
            total_score INTEGER GENERATED ALWAYS AS (
                COALESCE(score_accuracy, 0) + COALESCE(score_own_words, 0)
                + COALESCE(score_structure, 0) + COALESCE(score_depth, 0)
                + COALESCE(score_transfer, 0)
            ) STORED,
            review_type TEXT NOT NULL,
            question_angle TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE study_progress (
            id TEXT PRIMARY KEY,
            topic TEXT,
            concept TEXT,
            confidence TEXT,
            first_seen TEXT,
            last_seen TEXT,
            session_count INTEGER,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            last_teachback_score INTEGER,
            angles_used TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestRecordTeachbackSerialisationAndErrors:
    """R-21: explicit serialisation invariant, and CHECK violations must not
    raise through the public function unhandled."""

    def test_uses_db_immediate_for_explicit_serialisation(self, tmp_path, monkeypatch):
        """Documents the invariant: the read-decide-write span runs inside
        `db.immediate()`, not bare on the connection's default isolation
        level. Not a reordering test -- R-21 was corrected to "not a lost-
        update race" -- this asserts the serialisation is explicit rather
        than an accident of statement order.
        """
        db_path = _make_teachback_db(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn
        import studyloop.history.teachback as teachback_mod

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        calls: list[sqlite3.Connection] = []
        real_immediate = teachback_mod.immediate

        def spying_immediate(conn):
            calls.append(conn)
            return real_immediate(conn)

        monkeypatch.setattr(teachback_mod, "immediate", spying_immediate)

        ok = hist.record_teachback(
            concept="Decorators",
            topic="Python",
            scores=(3, 3, 3, 3, 3),
            review_type="micro",
        )

        assert ok is True
        assert len(calls) == 1

    def test_check_violation_does_not_raise_through_public_function(self, tmp_path, monkeypatch):
        """A CHECK-constraint violation (score outside BETWEEN 1 AND 4) used
        to raise sqlite3.IntegrityError straight through record_teachback,
        because `except sqlite3.OperationalError` does not catch it.
        """
        db_path = _make_teachback_db_with_check_constraints(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        # score_accuracy=5 violates CHECK(score_accuracy BETWEEN 1 AND 4).
        ok = hist.record_teachback(
            concept="Decorators",
            topic="Python",
            scores=(5, 3, 3, 3, 3),
            review_type="micro",
        )

        assert ok is False

        # And the transaction rolled back cleanly -- no partial row survives.
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM teach_back_scores").fetchone()[0]
        conn.close()
        assert count == 0

    def test_locked_db_raises_and_logs_not_silently_returned_as_false(
        self, tmp_path, monkeypatch, caplog
    ):
        """R-21b (M3 council, arbitration A10): `except sqlite3.DatabaseError`
        is IntegrityError's *and* OperationalError's shared parent -- so the
        broad catch that let a CHECK violation return False also silently
        swallowed a genuine lock/timeout OperationalError into the exact
        same "return False" as an expected rejection, indistinguishable from
        one another to every caller. Reproduced with a real connection whose
        `execute` only raises on the specific statement `record_teachback`
        actually issues (not every statement -- unlike a CHECK violation,
        which SQLite itself raises, "database is locked" has to be injected
        here since there is no real lock contention in a single-process
        test), so `BEGIN IMMEDIATE`/`ROLLBACK`/`isolation_level` all still
        behave like the real connection they wrap.
        """
        db_path = _make_teachback_db(tmp_path)

        class _LockOnInsertConn:
            def __init__(self, real_conn: sqlite3.Connection) -> None:
                self._real = real_conn

            def execute(self, sql, *args, **kwargs):
                if "INSERT INTO teach_back_scores" in sql:
                    raise sqlite3.OperationalError("database is locked")
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return _LockOnInsertConn(conn)

        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.history.teachback"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            hist.record_teachback(
                concept="Decorators",
                topic="Python",
                scores=(3, 3, 3, 3, 3),
                review_type="micro",
            )

        assert any("record_teachback" in r.message for r in caplog.records)


class TestProgressIdFor:
    """R-21: `progress_id_for` must be separator-safe and backward-compatible
    with the plain-join formula for the (overwhelmingly common) case where
    neither field contains ':' or '\\'.
    """

    def test_no_collision_across_separator_position(self):
        from studyloop.history._connection import progress_id_for

        # The bug this closes: a plain f"{topic}:{concept}" join makes both
        # pairs below join to the identical string "a:b:c".
        a = progress_id_for("a:b", "c")
        b = progress_id_for("a", "b:c")
        assert a != b

    def test_backward_compatible_with_old_formula_when_no_separator_present(self):
        """The overwhelmingly common case -- no ':' or '\\' in either field --
        must keep producing the exact id the old `f"{topic}:{concept}"` join
        did, so existing study_progress rows are not orphaned by this fix.
        """
        import uuid

        from studyloop.history._connection import progress_id_for

        old_style = str(uuid.uuid5(uuid.NAMESPACE_DNS, "python:decorators"))
        assert progress_id_for("python", "decorators") == old_style

    def test_deterministic(self):
        from studyloop.history._connection import progress_id_for

        assert progress_id_for("python", "decorators") == progress_id_for("python", "decorators")

    def test_teachback_and_progress_derive_the_same_id(self):
        """history/teachback.py and history/progress.py both upsert
        study_progress for a (topic, concept) pair -- they must agree on the
        id or one write silently orphans the other's row.
        """
        import studyloop.history.progress as progress_mod
        import studyloop.history.teachback as teachback_mod

        assert progress_mod._connection.progress_id_for(
            "python", "decorators"
        ) == teachback_mod._connection.progress_id_for("python", "decorators")


class TestGetStudyTerms:
    """Bug 2: _get_study_terms() should derive terms from config."""

    def test_returns_config_terms(self, monkeypatch):
        @dataclass
        class FakeTopic:
            name: str
            tags: list[str] = field(default_factory=list)

        fake_topics = [
            FakeTopic(name="Kafka", tags=["streaming", "events"]),
            FakeTopic(name="Flink", tags=["streaming", "realtime"]),
        ]

        import studyloop.history.search as search_mod

        monkeypatch.setattr(
            search_mod,
            "_get_study_terms",
            lambda: sorted(
                {t.name.lower() for t in fake_topics}
                | {tag.lower() for t in fake_topics for tag in t.tags}
            ),
        )

        terms = search_mod._get_study_terms()
        assert "kafka" in terms
        assert "streaming" in terms
        assert "flink" in terms
        assert "realtime" in terms

    def test_returns_fallback_when_no_config(self, monkeypatch):
        import studyloop.history.search as search_mod

        # Test fallback by making get_topics return falsy
        monkeypatch.setattr("studyloop.topics.get_topics", lambda: None)
        terms = search_mod._get_study_terms()
        # When get_topics returns falsy, should fall back to defaults
        assert "spark" in terms
        assert "python" in terms

    def test_fallback_on_import_error(self, monkeypatch):
        import studyloop.history.search as search_mod
        import studyloop.topics

        monkeypatch.setattr(
            studyloop.topics,
            "get_topics",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        terms = search_mod._get_study_terms()
        assert "spark" in terms  # fallback list


class TestNoModuleLevelLoadSettings:
    """Bug 3: _DB_CANDIDATES should no longer exist as a module attribute."""

    def test_no_db_candidates_attribute(self):
        import studyloop.history as hist

        assert not hasattr(hist, "_DB_CANDIDATES"), (
            "_DB_CANDIDATES should not exist — load_settings() must not be called at import time"
        )

    def test_get_db_path_uses_settings(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        db_path.touch()

        @dataclass
        class FakeSettings:
            session_db: object = field(default_factory=lambda: db_path)

        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "load_settings", lambda: FakeSettings())

        result = _conn._get_db_path()
        assert result == db_path


def _make_migrated_db(tmp_path):
    """Create a temp DB with full schema + all migrations applied."""
    schema_path = (
        Path(__file__).parent.parent.parent
        / "agent-session-tools"
        / "src"
        / "agent_session_tools"
        / "schema.sql"
    )
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text())
    conn.commit()

    ast_migrations = __import__("pytest").importorskip("agent_session_tools.migrations")

    ast_migrations.migrate(conn)
    conn.close()
    return db_path


def _mock_connect_for(db_path, monkeypatch):
    """Patch history._connection._connect to use a specific DB path."""
    import studyloop.history._connection as _conn

    def mock_connect():
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(_conn, "_connect", mock_connect)


class TestMigrateBridgesToGraph:
    """Task 3: knowledge_bridges → concept graph migration."""

    def test_migrates_bridges_to_concepts_and_relations(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)

        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 structural_mapping, quality, created_by)
            VALUES ('ECMP routing', 'networking', 'Spark partitioning', 'spark',
                    'both distribute across paths', 'effective', 'agent')
            """
        )
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 structural_mapping, quality, created_by)
            VALUES ('VLAN', 'networking', 'data lake zones', 'aws',
                    'logical isolation', 'validated', 'user')
            """
        )
        conn.commit()
        conn.close()

        import studyloop.history as hist

        _mock_connect_for(db_path, monkeypatch)

        count = hist.migrate_bridges_to_graph()
        assert count == 2

        conn = sqlite3.connect(db_path)
        concepts = conn.execute("SELECT name, domain FROM concepts").fetchall()
        concept_set = {(r[0], r[1]) for r in concepts}
        assert ("ecmp routing", "networking") in concept_set
        assert ("spark partitioning", "spark") in concept_set
        assert ("vlan", "networking") in concept_set
        assert ("data lake zones", "aws") in concept_set

        relations = conn.execute(
            "SELECT relation_type, confidence FROM concept_relations"
        ).fetchall()
        assert len(relations) == 2
        assert all(r[0] == "analogy_to" for r in relations)
        # effective → 1.0, validated → 0.7
        confidences = sorted(r[1] for r in relations)
        assert confidences == [0.7, 1.0]
        conn.close()

    def test_returns_zero_when_no_bridges(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        import studyloop.history as hist

        assert hist.migrate_bridges_to_graph() == 0

    def test_idempotent_on_rerun(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)

        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 quality, created_by)
            VALUES ('NAT', 'networking', 'data transformation', 'data_eng',
                    'proposed', 'agent')
            """
        )
        conn.commit()
        conn.close()

        import studyloop.history as hist

        _mock_connect_for(db_path, monkeypatch)

        hist.migrate_bridges_to_graph()
        hist.migrate_bridges_to_graph()  # second run — should not duplicate

        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM concept_relations").fetchone()[0] == 1
        conn.close()

    def test_proposed_quality_maps_to_low_confidence(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)

        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 quality, created_by)
            VALUES ('firewall rules', 'networking', 'data access policies', 'data_eng',
                    'proposed', 'agent')
            """
        )
        conn.commit()
        conn.close()

        import studyloop.history as hist

        _mock_connect_for(db_path, monkeypatch)
        hist.migrate_bridges_to_graph()

        conn = sqlite3.connect(db_path)
        confidence = conn.execute("SELECT confidence FROM concept_relations").fetchone()[0]
        assert confidence == 0.3  # proposed → 0.3
        conn.close()

    def test_concept_names_are_lowercased(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)

        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 quality, created_by)
            VALUES ('BGP Route Propagation', 'networking',
                    'Event Streaming', 'kafka', 'effective', 'agent')
            """
        )
        conn.commit()
        conn.close()

        import studyloop.history as hist

        _mock_connect_for(db_path, monkeypatch)
        hist.migrate_bridges_to_graph()

        conn = sqlite3.connect(db_path)
        names = [r[0] for r in conn.execute("SELECT name FROM concepts").fetchall()]
        assert "bgp route propagation" in names
        assert "event streaming" in names
        conn.close()


class TestSeedConceptsFromConfig:
    """Task 4: seed concepts from config topics + tags."""

    def test_seeds_concepts_from_topics(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        @dataclass
        class FakeTopic:
            name: str
            tags: list[str] = field(default_factory=list)

        fake_topics = [
            FakeTopic(name="python", tags=["decorators", "generators"]),
            FakeTopic(name="sql", tags=["joins", "CTEs"]),
        ]

        import studyloop.history as hist

        monkeypatch.setattr("studyloop.topics.get_topics", lambda: fake_topics)

        count = hist.seed_concepts_from_config()
        assert count == 4

        conn = sqlite3.connect(db_path)
        concepts = {
            (r[0], r[1]) for r in conn.execute("SELECT name, domain FROM concepts").fetchall()
        }
        assert ("decorators", "python") in concepts
        assert ("generators", "python") in concepts
        assert ("joins", "sql") in concepts
        assert ("ctes", "sql") in concepts  # lowercased
        conn.close()

    def test_idempotent_on_rerun(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        @dataclass
        class FakeTopic:
            name: str
            tags: list[str] = field(default_factory=list)

        monkeypatch.setattr(
            "studyloop.topics.get_topics",
            lambda: [FakeTopic(name="python", tags=["decorators"])],
        )

        import studyloop.history as hist

        hist.seed_concepts_from_config()
        hist.seed_concepts_from_config()  # second run

        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
        conn.close()

    def test_returns_zero_when_no_topics(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        monkeypatch.setattr("studyloop.topics.get_topics", lambda: [])

        import studyloop.history as hist

        assert hist.seed_concepts_from_config() == 0

    def test_deterministic_uuid_generation(self, tmp_path, monkeypatch):
        """Same domain:name should always produce the same concept ID."""
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        import uuid

        import studyloop.history as hist

        @dataclass
        class FakeTopic:
            name: str
            tags: list[str] = field(default_factory=list)

        monkeypatch.setattr(
            "studyloop.topics.get_topics",
            lambda: [FakeTopic(name="python", tags=["decorators"])],
        )
        hist.seed_concepts_from_config()

        conn = sqlite3.connect(db_path)
        stored_id = conn.execute("SELECT id FROM concepts").fetchone()[0]
        expected_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "python:decorators"))
        assert stored_id == expected_id
        conn.close()


class TestListConcepts:
    """list_concepts() returns stored concepts for display."""

    def test_returns_empty_for_empty_db(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        import studyloop.history as hist

        result = hist.list_concepts()
        assert result == []

    def test_returns_concepts_ordered_by_domain_and_name(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO concepts (id, name, domain, description) "
            "VALUES ('1', 'generators', 'python', 'lazy iterators')"
        )
        conn.execute(
            "INSERT INTO concepts (id, name, domain, description) "
            "VALUES ('2', 'decorators', 'python', 'function wrappers')"
        )
        conn.execute(
            "INSERT INTO concepts (id, name, domain, description) "
            "VALUES ('3', 'joins', 'sql', NULL)"
        )
        conn.commit()
        conn.close()

        import studyloop.history as hist

        result = hist.list_concepts()
        assert len(result) == 3
        # Ordered by domain then name: python/decorators, python/generators, sql/joins
        assert result[0].id == "2"
        assert result[0].name == "decorators"
        assert result[0].domain == "python"
        assert result[0].description == "function wrappers"
        assert result[1].name == "generators"
        assert result[2].name == "joins"
        assert result[2].description is None  # NULL preserved (no COALESCE)

    def test_filters_by_domain(self, tmp_path, monkeypatch):
        """Passing domain= returns only concepts in that domain, ordered by name."""
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO concepts (id, name, domain) VALUES ('1', 'generators', 'python')")
        conn.execute("INSERT INTO concepts (id, name, domain) VALUES ('2', 'decorators', 'python')")
        conn.execute("INSERT INTO concepts (id, name, domain) VALUES ('3', 'joins', 'sql')")
        conn.commit()
        conn.close()

        import studyloop.history as hist

        result = hist.list_concepts(domain="python")
        assert len(result) == 2
        assert result[0].name == "decorators"
        assert result[1].name == "generators"
        # sql concept should be excluded
        assert all(c.domain == "python" for c in result)

    def test_domain_filter_no_matches(self, tmp_path, monkeypatch):
        """Domain filter with no matching concepts returns empty list."""
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO concepts (id, name, domain) VALUES ('1', 'joins', 'sql')")
        conn.commit()
        conn.close()

        import studyloop.history as hist

        result = hist.list_concepts(domain="python")
        assert result == []

    def test_returns_concept_summary_namedtuple(self, tmp_path, monkeypatch):
        """Results are ConceptSummary NamedTuples with id, name, domain, description."""
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO concepts (id, name, domain, description) "
            "VALUES ('abc-123', 'decorators', 'python', 'function wrappers')"
        )
        conn.commit()
        conn.close()

        import studyloop.history as hist

        result = hist.list_concepts()
        assert len(result) == 1
        concept = result[0]
        assert isinstance(concept, hist.ConceptSummary)
        assert concept.id == "abc-123"
        assert concept.name == "decorators"
        assert concept.domain == "python"
        assert concept.description == "function wrappers"

    def test_returns_no_db(self, monkeypatch):
        """Returns empty list when no DB connection available."""
        import studyloop.history as hist
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", lambda: None)
        assert hist.list_concepts() == []


def _make_messages_db(tmp_path: Path) -> Path:
    """The REAL export schema — messages + messages_fts + sync triggers.

    Built from agent-session-tools' schema.sql rather than a hand-rolled
    subset, because the R-92 bug only exists in the real shape: both
    ``messages`` and ``messages_fts`` carry a ``content`` column, so an
    unqualified ``content MATCH ?`` in their join is "ambiguous column
    name: content".
    """
    schema = (
        Path(__file__).resolve().parents[2]
        / "agent-session-tools"
        / "src"
        / "agent_session_tools"
        / "schema.sql"
    ).read_text()
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.execute("INSERT INTO sessions (id, source) VALUES ('s1', 'kiro_cli')")
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp) "
        "VALUES ('m1', 's1', 'user', 'I keep mixing up sql window functions', ?)",
        ((datetime.now(UTC) - timedelta(days=1)).isoformat(),),
    )
    conn.commit()
    conn.close()
    return db_path


class TestTopicFrequencyR92:
    """R-92: the FTS join must qualify ``messages_fts.content``.

    ``get_study_history`` (the MCP tool) goes through ``topic_frequency``;
    before the fix every call raised ``sqlite3.OperationalError: ambiguous
    column name: content``, which R-22b then (correctly) re-raised rather
    than masking as "topic never mentioned".
    """

    def _mock(self, db_path: Path, monkeypatch) -> None:
        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", mock_connect)

    def test_matches_against_the_real_join_without_ambiguity(self, tmp_path, monkeypatch):
        self._mock(_make_messages_db(tmp_path), monkeypatch)

        import studyloop.history as hist

        rows = hist.topic_frequency(["sql"], days=30)

        assert len(rows) == 1
        assert rows[0]["session_id"] == "s1"
        assert "sql" in rows[0]["snippet"].lower()

    def test_multiple_keywords_or_together(self, tmp_path, monkeypatch):
        """Every placeholder in the OR chain must be qualified, not just one."""
        self._mock(_make_messages_db(tmp_path), monkeypatch)

        import studyloop.history as hist

        rows = hist.topic_frequency(["spark", "window functions"], days=30)

        assert len(rows) == 1, "second keyword in the OR chain did not match"

    def test_phrase_keywords_do_not_match_scattered_terms(self, tmp_path, monkeypatch):
        """Keywords with spaces are FTS5 phrases, not AND'd loose terms."""
        db_path = _make_messages_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) "
            "VALUES ('m2', 's1', 'user', "
            "'the functions of a window manager', ?)",
            ((datetime.now(UTC) - timedelta(days=1)).isoformat(),),
        )
        conn.commit()
        conn.close()
        self._mock(db_path, monkeypatch)

        import studyloop.history as hist

        rows = hist.topic_frequency(["window functions"], days=30)

        assert [r["session_id"] for r in rows] == ["s1"]
        assert "window" in rows[0]["snippet"].lower()
        # m2 has both words but not the phrase; matching it would mean the
        # keyword was parsed as two loose terms.
        assert len(rows) == 1

    def test_no_keywords_returns_empty_without_touching_the_db(self, monkeypatch):
        import studyloop.history as hist
        import studyloop.history._connection as _conn

        def explode():  # pragma: no cover - reaching this IS the failure
            raise AssertionError("an empty keyword list must not open the DB")

        monkeypatch.setattr(_conn, "_connect", explode)
        assert hist.topic_frequency([], days=30) == []
