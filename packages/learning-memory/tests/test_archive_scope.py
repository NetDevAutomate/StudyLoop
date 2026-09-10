"""The archive adapter's source allow-list.

Andy's ruling of 2026-09-10 (``docs/architecture/session-memory/receipts/
adapter-scope-2026-09-10.md`` §4.4, §5 "Stage 4"): the supported session sources are
exactly the six harnesses plus first-party ``study_mentor``. The live ``sessions.db``
also holds 1,279 sessions under seven retired labels, and it is the only surviving copy
of ~89 % of that history — so they are **hidden, never deleted**.

Two things therefore have to hold at once, and both are asserted here: nothing scoped
out is *enumerated* (no sweep ingests it, census v2 reads the six-source corpus), and
everything scoped out is still *readable by id* (hiding, not deleting). The fixture has
one session per source so the two retired ones are countable.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from learning_memory import ingest_archive
from learning_memory.adapters.archive import SUPPORTED_SOURCES, ArchiveAdapter

if TYPE_CHECKING:
    from pathlib import Path

ARCHIVE_DDL = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, source TEXT, project_path TEXT, git_branch TEXT,
    created_at TEXT, updated_at TEXT, metadata TEXT, content_hash TEXT,
    import_fingerprint TEXT, session_type TEXT
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY, session_id TEXT, parent_id TEXT, role TEXT, content TEXT,
    model TEXT, timestamp TEXT, metadata TEXT, content_hash TEXT, seq INTEGER
);
"""

KIRO = "kiro-session"
GROK = "grok-session"
MENTOR = "mentor-session"
AIDER = "aider-session"
KILOCODE = "kilocode-session"
# An in-scope sub-agent whose parent is the out-of-scope aider session: the edge the
# allow-list must report rather than store.
ORPHAN_CHILD = "agent-child-of-aider"

SUPPORTED_IDS = [KIRO, GROK, MENTOR, ORPHAN_CHILD]
RETIRED_IDS = [AIDER, KILOCODE]

_ROWS = [
    (KIRO, "kiro_cli", None),
    (GROK, "grok", None),
    (MENTOR, "study_mentor", None),
    (AIDER, "aider", None),
    (KILOCODE, "kilocode_cli", None),
    (ORPHAN_CHILD, "kiro_cli", AIDER),
]


def _archive(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(ARCHIVE_DDL)
    conn.executemany(
        "INSERT INTO sessions(id, source, project_path, git_branch, created_at, updated_at,"
        " metadata, content_hash, session_type) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                session_id,
                source,
                "/repo",
                "main",
                f"2026-09-0{index + 1}T10:00:00+00:00",
                f"2026-09-0{index + 1}T10:05:00+00:00",
                json.dumps({"source_session_id": parent}) if parent else None,
                None,
                "work",
            )
            for index, (session_id, source, parent) in enumerate(_ROWS)
        ],
    )
    conn.executemany(
        "INSERT INTO messages(session_id, role, content, model, timestamp, seq)"
        " VALUES (?,?,?,?,?,?)",
        [
            # One learner turn and one prose reply each, so every session is citable
            # and the store accepts it — the refusal path is tested elsewhere.
            row
            for session_id, _source, _parent in _ROWS
            for row in (
                (session_id, "user", f"what did {session_id} decide?", None, None, 0),
                (session_id, "assistant", f"{session_id} decided X", "model-1", None, 1),
            )
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "sessions.db"
    _archive(path)
    return path


@pytest.fixture
def scoped(db: Path) -> ArchiveAdapter:
    """The default adapter: the allow-list is the default, not an opt-in."""
    return ArchiveAdapter.open(db)


@pytest.fixture
def unscoped(db: Path) -> ArchiveAdapter:
    return ArchiveAdapter.open(db, sources=None)


# ---------------------------------------------------------------- the allow-list


def test_the_allow_list_is_the_seven_supported_sources() -> None:
    """Locked as a literal: this worktree has no agent_session_tools.sources to import."""
    expected = {"claude_code", "codex", "grok", "kiro_cli", "opencode", "pi", "study_mentor"}
    assert set(SUPPORTED_SOURCES) == expected
    for retired in ("repoprompt", "aider", "kilocode_cli", "litellm-proxy", "gemini_cli"):
        assert retired not in SUPPORTED_SOURCES
    for retired in ("bedrock_proxy", "omp"):
        assert retired not in SUPPORTED_SOURCES


def test_the_default_is_scoped_not_opt_in(scoped: ArchiveAdapter) -> None:
    assert scoped.sources == SUPPORTED_SOURCES


# ------------------------------------------------------------------- enumeration


def test_discover_excludes_the_retired_sources(scoped: ArchiveAdapter) -> None:
    found = [ref.locator for ref in scoped.discover()]
    assert sorted(found) == sorted(SUPPORTED_IDS)
    assert AIDER not in found
    assert KILOCODE not in found
    assert all(ref.source_sha256 and len(ref.source_sha256) == 64 for ref in scoped.discover())


def test_session_ids_excludes_the_retired_sources(scoped: ArchiveAdapter) -> None:
    assert sorted(scoped.session_ids()) == sorted(SUPPORTED_IDS)


def test_sources_none_includes_everything(unscoped: ArchiveAdapter) -> None:
    """The escape hatch behind --include-retired-sources restores the v1 corpus."""
    assert sorted(ref.locator for ref in unscoped.discover()) == sorted(SUPPORTED_IDS + RETIRED_IDS)
    assert sorted(unscoped.session_ids()) == sorted(SUPPORTED_IDS + RETIRED_IDS)


def test_hidden_source_counts_names_what_was_excluded(scoped: ArchiveAdapter) -> None:
    assert scoped.hidden_source_counts() == {"aider": 1, "kilocode_cli": 1}


def test_hidden_source_counts_is_empty_when_unscoped(unscoped: ArchiveAdapter) -> None:
    assert unscoped.hidden_source_counts() == {}


def test_source_counts_stays_a_census_of_the_whole_file(scoped: ArchiveAdapter) -> None:
    """Hiding, not deleting: the receipt must still be able to say what is in the file."""
    assert scoped.source_counts() == {
        "kiro_cli": 2,
        "aider": 1,
        "grok": 1,
        "kilocode_cli": 1,
        "study_mentor": 1,
    }


# ------------------------------------------------------ explicit access by id


def test_a_retired_session_is_still_parseable_by_id(scoped: ArchiveAdapter) -> None:
    """Hidden from enumeration, readable by id — that is the whole difference."""
    parsed = scoped.parse_id(AIDER)
    assert parsed.session.id == AIDER
    assert parsed.session.harness == "aider"
    assert [event.text for event in parsed.events if event.kind == "user"] == [
        f"what did {AIDER} decide?"
    ]
    assert scoped.parse_id(KILOCODE).session.harness == "kilocode_cli"
    assert scoped.session_metadata(AIDER) == {}


def test_the_scoped_connection_still_refuses_a_write(scoped: ArchiveAdapter) -> None:
    """The allow-list is a WHERE clause; every statement stays a SELECT on mode=ro."""
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        scoped._conn.execute("DELETE FROM sessions WHERE source = 'aider'")


# ------------------------------------------------------------------------ lineage


def test_a_parent_outside_the_allow_list_is_reported_not_linked(
    scoped: ArchiveAdapter,
) -> None:
    assert scoped.lineage_map() == {}, "the aider parent would not be ingested"
    assert scoped.out_of_scope_lineage() == {ORPHAN_CHILD: AIDER}
    parsed = scoped.parse_id(ORPHAN_CHILD)
    assert parsed.session.parent_id is None
    assert parsed.lineage == []


def test_unscoped_lineage_links_the_retired_parent(unscoped: ArchiveAdapter) -> None:
    assert unscoped.lineage_map() == {ORPHAN_CHILD: AIDER}
    assert unscoped.out_of_scope_lineage() == {}
    assert unscoped.parse_id(ORPHAN_CHILD).session.parent_id == AIDER
    assert unscoped.session_ids().index(AIDER) < unscoped.session_ids().index(ORPHAN_CHILD)


def test_lineage_reports_only_in_scope_children(scoped: ArchiveAdapter) -> None:
    assert scoped.unrecoverable_lineage() == [], "the one agent-* row does name a parent"
    assert scoped.self_referencing_lineage() == []


# ----------------------------------------------------------------- ingest receipt


@pytest.fixture
def _stub_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """The corpus digest is the ruler's pinned function over the real gold.

    Stubbed here because this test's input is a 6-session synthetic archive, not the
    corpus the gold was authored against — running the real function would assert
    nothing about scope and would load ``scripts/knowledge_proof/score.py``.
    """
    monkeypatch.setattr(ingest_archive, "_load_corpus_digest", lambda *_args: {"value": None})


def _run(db: Path, tmp_path: Path, name: str, *extra: str) -> dict[str, object]:
    receipt = tmp_path / f"{name}.json"
    exit_code = ingest_archive.main(
        [
            "--db",
            str(db),
            "--store",
            str(tmp_path / f"{name}.lm.db"),
            "--receipt",
            str(receipt),
            *extra,
        ]
    )
    assert exit_code == 0
    return json.loads(receipt.read_text(encoding="utf-8"))


@pytest.mark.usefixtures("_stub_digest")
def test_the_run_receipt_records_the_scope_and_the_hidden_count(db: Path, tmp_path: Path) -> None:
    """Census v2's provenance has to show which corpus was read."""
    receipt = _run(db, tmp_path, "scoped")
    expected_scope = sorted(SUPPORTED_SOURCES)

    assert receipt["sources_scope"] == expected_scope
    scope = receipt["scope"]
    assert isinstance(scope, dict)
    assert scope["sources"] == expected_scope
    assert scope["include_retired_sources"] is False
    assert scope["hidden_sessions"] == 2
    assert scope["hidden_by_source"] == {"aider": 1, "kilocode_cli": 1}
    assert "adapter-scope-2026-09-10.md" in str(scope["ruling"])

    sessions = receipt["sessions"]
    assert isinstance(sessions, dict)
    assert sessions["ingested"] == len(SUPPORTED_IDS)
    assert sessions["rejected"] == 0
    per_source = receipt["per_source_sessions"]
    assert isinstance(per_source, dict)
    assert set(per_source) == {"kiro_cli", "grok", "study_mentor"}

    # Unfiltered census of the file survives alongside the scope: hidden, not deleted.
    assert receipt["archive_per_source_sessions"] == {
        "kiro_cli": 2,
        "aider": 1,
        "grok": 1,
        "kilocode_cli": 1,
        "study_mentor": 1,
    }
    lineage = receipt["lineage"]
    assert isinstance(lineage, dict)
    assert lineage["edges"] == 0
    assert lineage["out_of_scope_parent_count"] == 1
    assert lineage["out_of_scope_parent_sample"] == {ORPHAN_CHILD: AIDER}


@pytest.mark.usefixtures("_stub_digest")
def test_include_retired_sources_ingests_everything_and_says_so(db: Path, tmp_path: Path) -> None:
    receipt = _run(db, tmp_path, "unscoped", "--include-retired-sources")

    assert receipt["sources_scope"] == "all"
    scope = receipt["scope"]
    assert isinstance(scope, dict)
    assert scope["include_retired_sources"] is True
    assert scope["hidden_sessions"] == 0
    assert scope["hidden_by_source"] == {}

    sessions = receipt["sessions"]
    assert isinstance(sessions, dict)
    assert sessions["ingested"] == len(SUPPORTED_IDS) + len(RETIRED_IDS)
    per_source = receipt["per_source_sessions"]
    assert isinstance(per_source, dict)
    assert set(per_source) == {"kiro_cli", "grok", "study_mentor", "aider", "kilocode_cli"}
    lineage = receipt["lineage"]
    assert isinstance(lineage, dict)
    assert lineage["edges"] == 1, "the aider parent is ingested, so the edge is real"
    assert lineage["out_of_scope_parent_count"] == 0
