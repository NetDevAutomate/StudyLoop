"""Tests for recap, mastery graph, and voice doctor checks."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING

from studyloop.doctor import voice
from studyloop.learning import mastery, recap
from studyloop.learning import voice as learning_voice

if TYPE_CHECKING:
    from pathlib import Path


def test_empty_day_returns_gentle_no_data_recap(monkeypatch) -> None:
    monkeypatch.setattr("studyloop.history.get_wins", lambda days: [])
    monkeypatch.setattr("studyloop.history.progress.get_struggling_topics", lambda days: [])
    monkeypatch.setattr("studyloop.history.spaced_repetition_due", lambda topics: [])

    plan = SimpleNamespace(
        starter=True,
        primary=SimpleNamespace(
            concept="one tiny recall loop",
            evidence_command="studyloop now",
        ),
    )

    monkeypatch.setattr("studyloop.learning.decision.build_now_plan", lambda: plan)

    result = recap.build_daily_recap()

    assert result.has_data is False
    assert "checking in" in result.win


def test_mermaid_output_validates_structurally(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE concept_dependencies (
            id TEXT PRIMARY KEY,
            topic TEXT,
            source_concept TEXT,
            target_concept TEXT,
            relation_type TEXT,
            evidence TEXT,
            source_type TEXT,
            confidence REAL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO concept_dependencies
        VALUES ('1', 'python', 'decorators', 'closures', 'prerequisite', 'test', 'explicit', 0.9)
        """
    )
    conn.execute(
        """
        INSERT INTO concept_dependencies
        VALUES ('2', 'python', '`typing.protocol`', 'duck typing [shape]',
                'prerequisite', 'test', 'explicit', 0.8)
        """
    )
    conn.commit()
    conn.close()

    def connect():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(mastery._connection, "_connect", connect)
    monkeypatch.setattr(mastery, "seed_inferred_dependencies", lambda topic: 0)

    output = mastery.mastery_graph_mermaid("python")

    assert output.startswith("flowchart LR")
    assert '-->|"prerequisite"|' in output
    assert "`typing.protocol`" not in output
    assert "duck typing (shape)" in output


def test_list_dependencies_skips_markdown_seed_when_edges_exist(
    monkeypatch, tmp_path: Path
) -> None:
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE concept_dependencies (
            id TEXT PRIMARY KEY,
            topic TEXT,
            source_concept TEXT,
            target_concept TEXT,
            relation_type TEXT,
            evidence TEXT,
            source_type TEXT,
            confidence REAL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO concept_dependencies
        VALUES ('1', 'python', 'decorators', 'closures', 'prerequisite', 'test', 'explicit', 0.9)
        """
    )
    conn.commit()
    conn.close()

    def connect():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    seed_calls = 0

    def seed(topic: str) -> int:
        nonlocal seed_calls
        seed_calls += 1
        return 0

    monkeypatch.setattr(mastery._connection, "_connect", connect)
    monkeypatch.setattr(mastery, "seed_inferred_dependencies", seed)

    edges = mastery.list_dependencies("python")

    assert [edge.source_concept for edge in edges] == ["decorators"]
    assert seed_calls == 0


def test_weak_links_return_struggling_blockers_first(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE concept_dependencies (
            id TEXT PRIMARY KEY,
            topic TEXT,
            source_concept TEXT,
            target_concept TEXT,
            relation_type TEXT,
            evidence TEXT,
            source_type TEXT,
            confidence REAL
        );
        CREATE TABLE study_progress (
            concept TEXT,
            topic TEXT,
            confidence TEXT,
            last_teachback_score INTEGER,
            last_seen TEXT
        );
        INSERT INTO concept_dependencies
        VALUES ('1', 'python', 'decorators', 'closures', 'prerequisite', 'test', 'explicit', 0.9);
        INSERT INTO concept_dependencies
        VALUES ('2', 'python', 'generators', 'iterators', 'prerequisite', 'test', 'explicit', 0.9);
        INSERT INTO study_progress VALUES ('decorators', 'python', 'struggling', 8, '2026-01-01');
        INSERT INTO study_progress VALUES ('generators', 'python', 'learning', 13, '2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    def connect():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(mastery._connection, "_connect", connect)
    monkeypatch.setattr(mastery, "seed_inferred_dependencies", lambda topic: 0)

    links = mastery.weak_links_for_topic("python")

    assert links[0]["concept"] == "decorators"
    assert links[0]["dependency"] == "closures"


def test_voice_doctor_checks_openvox_only_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(voice, "load_raw_config", lambda: {"tts": {"backend": "kokoro"}})
    monkeypatch.setattr(voice.shutil, "which", lambda name: None)

    results = voice.check_voice_readiness()

    openvox = next(item for item in results if item.name == "openvox_api")
    assert openvox.status == "info"
    assert "skipped" in openvox.message


def test_voice_doctor_reports_openvox_reachability(monkeypatch) -> None:
    monkeypatch.setattr(
        voice,
        "load_raw_config",
        lambda: {
            "tts": {
                "backend": "openvox",
                "openvox_base_url": "http://127.0.0.1:8000/v1",
            }
        },
    )
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/afplay")
    monkeypatch.setattr(voice, "_openvox_reachable", lambda base_url: True)

    results = voice.check_voice_readiness()

    assert next(item for item in results if item.name == "openvox_api").status == "pass"


def test_recap_audio_file_export_writes_openvox_bytes(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b"RIFFfake-wave"

    monkeypatch.setattr(
        learning_voice,
        "load_raw_config",
        lambda: {"tts": {"backend": "openvox", "openvox_response_format": "wav"}},
    )
    monkeypatch.setattr(
        learning_voice.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )

    output = tmp_path / "recap.wav"

    assert learning_voice.synthesize_text_to_file("Win: decorators.", output) is True
    assert output.read_bytes() == b"RIFFfake-wave"
