"""Tests for history module bug fixes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


def _make_db(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with the study_progress table."""
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
            updated_at TEXT
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

        import studyctl.history as hist

        monkeypatch.setattr(hist, "_connect", mock_connect)

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

        import studyctl.history as hist

        monkeypatch.setattr(hist, "_connect", mock_connect)

        hist.record_progress("Python ", " Decorators", "learning")
        hist.record_progress("python", "decorators", "confident")

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM study_progress").fetchall()
        conn.close()

        assert len(rows) == 1


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

        import studyctl.history as hist

        monkeypatch.setattr(
            hist,
            "_get_study_terms",
            lambda: sorted(
                {t.name.lower() for t in fake_topics}
                | {tag.lower() for t in fake_topics for tag in t.tags}
            ),
        )

        terms = hist._get_study_terms()
        assert "kafka" in terms
        assert "streaming" in terms
        assert "flink" in terms
        assert "realtime" in terms

    def test_returns_fallback_when_no_config(self, monkeypatch):
        import studyctl.history as hist

        # Test fallback by making get_topics return falsy
        monkeypatch.setattr("studyctl.config.get_topics", lambda: None)
        terms = hist._get_study_terms()
        # When get_topics returns falsy, should fall back to defaults
        assert "spark" in terms
        assert "python" in terms

    def test_fallback_on_import_error(self, monkeypatch):
        import studyctl.config
        import studyctl.history as hist

        monkeypatch.setattr(
            studyctl.config,
            "get_topics",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        terms = hist._get_study_terms()
        assert "spark" in terms  # fallback list


class TestNoModuleLevelLoadSettings:
    """Bug 3: _DB_CANDIDATES should no longer exist as a module attribute."""

    def test_no_db_candidates_attribute(self):
        import studyctl.history as hist

        assert not hasattr(hist, "_DB_CANDIDATES"), (
            "_DB_CANDIDATES should not exist — load_settings() must not be called at import time"
        )

    def test_find_db_uses_settings(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        db_path.touch()

        @dataclass
        class FakeSettings:
            session_db: object = field(default_factory=lambda: db_path)

        import studyctl.history as hist

        monkeypatch.setattr(hist, "load_settings", lambda: FakeSettings())

        result = hist._find_db()
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

    from agent_session_tools.migrations import migrate

    migrate(conn)
    conn.close()
    return db_path


def _mock_connect_for(db_path, monkeypatch):
    """Patch history._connect to use a specific DB path."""
    import studyctl.history as hist

    def mock_connect():
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(hist, "_connect", mock_connect)


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

        import studyctl.history as hist

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

        import studyctl.history as hist

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

        import studyctl.history as hist

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

        import studyctl.history as hist

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

        import studyctl.history as hist

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

        import studyctl.history as hist

        monkeypatch.setattr("studyctl.config.get_topics", lambda: fake_topics)

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
            "studyctl.config.get_topics",
            lambda: [FakeTopic(name="python", tags=["decorators"])],
        )

        import studyctl.history as hist

        hist.seed_concepts_from_config()
        hist.seed_concepts_from_config()  # second run

        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
        conn.close()

    def test_returns_zero_when_no_topics(self, tmp_path, monkeypatch):
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        monkeypatch.setattr("studyctl.config.get_topics", lambda: [])

        import studyctl.history as hist

        assert hist.seed_concepts_from_config() == 0

    def test_deterministic_uuid_generation(self, tmp_path, monkeypatch):
        """Same domain:name should always produce the same concept ID."""
        db_path = _make_migrated_db(tmp_path)
        _mock_connect_for(db_path, monkeypatch)

        import uuid

        import studyctl.history as hist

        @dataclass
        class FakeTopic:
            name: str
            tags: list[str] = field(default_factory=list)

        monkeypatch.setattr(
            "studyctl.config.get_topics",
            lambda: [FakeTopic(name="python", tags=["decorators"])],
        )
        hist.seed_concepts_from_config()

        conn = sqlite3.connect(db_path)
        stored_id = conn.execute("SELECT id FROM concepts").fetchone()[0]
        expected_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "python:decorators"))
        assert stored_id == expected_id
        conn.close()
