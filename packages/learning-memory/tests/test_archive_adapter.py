"""The archive adapter against a synthetic archive database.

Synthetic rather than the live file, because a test that needs 5,879 real sessions
is a test nobody runs. The three sessions here are the three shapes that carry
behaviour: an ``agent-*`` child naming its parent, a prose-less session that must be
refused, and a session with adjacent exporter duplicates.

The one thing that IS asserted against reality is that the adapter's connection
cannot write.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from learning_memory import NoEvidenceError, Store
from learning_memory.adapters.archive import ArchiveAdapter, open_readonly

if TYPE_CHECKING:
    from pathlib import Path

    from learning_memory import ParsedSession

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

PARENT = "56866d9d-6ce0-44d2-b453-f461d5b933bf"
CHILD = "agent-a6b222bb0e631d27c"
PROSELESS = "tool-only-session"
DUPES = "dupe-session"


def _archive(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(ARCHIVE_DDL)
    conn.executemany(
        "INSERT INTO sessions(id, source, project_path, git_branch, created_at, updated_at,"
        " metadata, content_hash, session_type) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            # created_at deliberately puts the CHILD first, so ordering has to be
            # topological rather than chronological for parent_id to be filled.
            (
                CHILD,
                "claude_code",
                "/repo",
                "main",
                "2026-09-01T10:00:00+00:00",
                "2026-09-01T10:05:00+00:00",
                json.dumps({"source_session_id": PARENT}),
                None,
                "work",
            ),
            (
                PARENT,
                "claude_code",
                "/repo",
                "main",
                "2026-09-01T11:00:00+00:00",
                "2026-09-01T11:30:00+00:00",
                json.dumps({"other": 1}),
                None,
                "work",
            ),
            (
                PROSELESS,
                "kiro_cli",
                "/repo",
                None,
                "2026-09-02T09:00:00+00:00",
                "2026-09-02T09:01:00+00:00",
                None,
                None,
                "work",
            ),
            (
                DUPES,
                # Was "repoprompt" before the 2026-09-10 adapter-scope ruling: a
                # retired label, which the adapter's default allow-list now hides,
                # so these duplicate-collapse and self-lineage assertions would have
                # been testing an excluded row. Scope behaviour lives in
                # test_archive_scope.py; this file is about parsing.
                "codex",
                None,
                None,
                "2026-09-03T09:00:00+00:00",
                "2026-09-03T09:01:00+00:00",
                json.dumps({"source_session_id": DUPES}),
                None,
                "work",
            ),
        ],
    )
    rows = [
        # PARENT: a full little exchange, with seq deliberately NULL/duplicated to
        # prove ordering uses `id` (the live archive has 678 NULL and 924 dupes).
        (PARENT, "system", "You are Claude Code...", None, None, 5),
        (PARENT, "user", "why did the gate fail?", None, "2026-09-01T11:00:01+00:00", None),
        (PARENT, "assistant", "[tool:Bash]", "claude-4", "2026-09-01T11:00:02+00:00", 5),
        (
            PARENT,
            "assistant",
            "recall was low, 0.107 macro",
            "claude-4",
            "2026-09-01T11:00:03+00:00",
            5,
        ),
        (PARENT, "user", "<system-reminder>be careful</system-reminder>", None, None, None),
        (PARENT, "user", "and the tokenizer?", None, "2026-09-01T11:00:05+00:00", None),
        (PARENT, "assistant", "measured in Stage F", "claude-4", "2026-09-01T11:00:06+00:00", None),
        # CHILD: a sub-agent transcript.
        (CHILD, "user", "sub-agent brief: read the specs", None, "2026-09-01T10:00:01+00:00", 0),
        (CHILD, "assistant", "[tool:Read]", "claude-4", "2026-09-01T10:00:02+00:00", 1),
        (CHILD, "assistant", "the specs say X", "claude-4", "2026-09-01T10:00:03+00:00", 2),
        # PROSELESS: tool traffic only -> nothing citable.
        (PROSELESS, "assistant", "[tool:Bash]", None, None, 0),
        (PROSELESS, "toolResult", "exit 0", None, None, 1),
        (PROSELESS, "error", "[API Error: nope]", None, None, 2),
        # DUPES: three adjacent identical assistant rows, then a non-adjacent repeat.
        (DUPES, "user", "explain the plan?", None, "2026-09-03T09:00:01+00:00", 0),
        (DUPES, "assistant", "the same answer", "gpt", "2026-09-03T09:00:02+00:00", 1),
        (DUPES, "assistant", "the same answer", "gpt", "2026-09-03T09:00:03+00:00", 2),
        (DUPES, "assistant", "the same answer", "gpt", "2026-09-03T09:00:04+00:00", 3),
        (DUPES, "user", "again please?", None, "2026-09-03T09:00:05+00:00", 4),
        (DUPES, "assistant", "the same answer", "gpt", "2026-09-03T09:00:06+00:00", 5),
    ]
    conn.executemany(
        "INSERT INTO messages(session_id, role, content, model, timestamp, seq)"
        " VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def adapter(tmp_path: Path) -> ArchiveAdapter:
    path = tmp_path / "sessions.db"
    _archive(path)
    return ArchiveAdapter.open(path)


def _parsed(adapter: ArchiveAdapter, session_id: str) -> ParsedSession:
    return adapter.parse_id(session_id)


# ------------------------------------------------------------------ read-only


def test_the_adapters_connection_refuses_a_write(adapter: ArchiveAdapter) -> None:
    """The archive is the only surviving copy of 5,261 sessions. mode=ro, enforced."""
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        adapter._conn.execute("DELETE FROM messages")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        adapter._conn.execute("UPDATE sessions SET source = 'x'")


def test_open_readonly_refuses_a_write(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    _archive(path)
    conn = open_readonly(path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO sessions(id) VALUES ('x')")
    finally:
        conn.close()


# -------------------------------------------------------------------- discover


def test_discover_is_deterministic_and_covers_every_session(adapter: ArchiveAdapter) -> None:
    first = [ref.locator for ref in adapter.discover()]
    second = [ref.locator for ref in adapter.discover()]
    assert first == second
    assert first == [CHILD, PARENT, PROSELESS, DUPES], "ordered by (created_at, id)"
    assert all(ref.harness == "archive" for ref in adapter.discover())


def test_discover_supplies_a_source_digest_despite_null_content_hash(
    adapter: ArchiveAdapter,
) -> None:
    """`sessions.content_hash` is NULL for all 5,879 live rows, so it is computed."""
    refs = {ref.locator: ref for ref in adapter.discover()}
    assert all(ref.source_sha256 and len(ref.source_sha256) == 64 for ref in refs.values())
    assert len({ref.source_sha256 for ref in refs.values()}) == 4, "distinct per session"
    again = {ref.locator: ref.source_sha256 for ref in adapter.discover()}
    assert again[PARENT] == refs[PARENT].source_sha256, "stable across calls"


def test_session_ids_puts_parents_before_children(adapter: ArchiveAdapter) -> None:
    order = adapter.session_ids()
    assert order.index(PARENT) < order.index(CHILD)
    assert sorted(order) == sorted([CHILD, PARENT, PROSELESS, DUPES])


# ----------------------------------------------------------------------- parse


def test_parse_keeps_the_archive_id_and_harness(adapter: ArchiveAdapter) -> None:
    parsed = _parsed(adapter, PARENT)
    assert parsed.session.id == PARENT, "ADR §6: session ids are unchanged"
    assert parsed.session.harness == "claude_code", "harness is the archive `source`"
    assert parsed.session.project == "/repo"
    assert parsed.session.branch == "main"
    assert parsed.session.started_at == "2026-09-01T11:00:00+00:00"
    assert parsed.session.ended_at == "2026-09-01T11:30:00+00:00"
    assert parsed.adapter_version == "archive-v1"
    assert parsed.classifier_version == "archive-classifier-v1"
    assert parsed.native_source is None, "the harnesses rotated the originals away"


def test_parse_classifies_and_numbers_turns(adapter: ArchiveAdapter) -> None:
    parsed = _parsed(adapter, PARENT)
    shape = [(event.turn_id, event.seq, event.kind, event.tool_name) for event in parsed.events]
    assert shape == [
        (0, 0, "system", None),  # preamble, before any user turn
        (1, 1, "user", None),
        (1, 2, "tool_call", "Bash"),
        (1, 3, "assistant_prose", None),
        (1, 4, "system", None),  # <system-reminder> is not a learner turn
        (2, 5, "user", None),
        (2, 6, "assistant_prose", None),
    ]
    assert [event.actor for event in parsed.events][1] == "learner"
    assert [event.actor for event in parsed.events][2] == "claude-4", "model wins as actor"


def test_parse_orders_by_id_not_by_seq(adapter: ArchiveAdapter) -> None:
    """The synthetic rows carry NULL and duplicate seq values on purpose."""
    parsed = _parsed(adapter, PARENT)
    assert [event.seq for event in parsed.events] == [0, 1, 2, 3, 4, 5, 6]
    texts = [event.text for event in parsed.events]
    assert texts[1] == "why did the gate fail?"
    assert texts[-1] == "measured in Stage F"


def test_parse_collapses_adjacent_duplicates_only(adapter: ArchiveAdapter) -> None:
    parsed = _parsed(adapter, DUPES)
    assert parsed.exporter_dupes_collapsed == 2
    prose = [event.text for event in parsed.events if event.kind == "assistant_prose"]
    assert prose == ["the same answer", "the same answer"], "the non-adjacent repeat survives"
    assert [event.seq for event in parsed.events] == [0, 1, 4, 5], "survivors keep their positions"


def test_parse_reports_lineage_for_an_agent_child(adapter: ArchiveAdapter) -> None:
    child = _parsed(adapter, CHILD)
    assert child.lineage == [PARENT]
    assert child.session.parent_id == PARENT

    parent = _parsed(adapter, PARENT)
    assert parent.lineage == []
    assert parent.session.parent_id is None


def test_a_self_referencing_source_session_id_is_not_lineage(adapter: ArchiveAdapter) -> None:
    """126 live rows name themselves; an edge to yourself is not provenance."""
    parsed = _parsed(adapter, DUPES)
    assert parsed.lineage == []
    assert parsed.session.parent_id is None
    assert adapter.self_referencing_lineage() == [DUPES]


def test_unrecoverable_lineage_names_the_agents_with_no_parent(adapter: ArchiveAdapter) -> None:
    _archive_only_child = adapter.unrecoverable_lineage()
    assert _archive_only_child == [], "the one agent-* session here does name a parent"


def test_parse_of_an_unknown_session_raises(adapter: ArchiveAdapter) -> None:
    with pytest.raises(KeyError):
        adapter.parse_id("no-such-session")


# ------------------------------------------------------------ end-to-end ingest


def test_ingest_of_the_synthetic_archive(adapter: ArchiveAdapter, tmp_path: Path) -> None:
    """The adapter's output is what the store accepts, including the refusal."""
    store = Store.connect(tmp_path / "lm.db")
    store.install()
    try:
        rejected: list[str] = []
        for session_id in adapter.session_ids():
            try:
                store.ingest(adapter.parse_id(session_id))
            except NoEvidenceError:
                rejected.append(session_id)

        assert rejected == [PROSELESS], "tool-only traffic has nothing citable"
        counts = store.row_counts()
        assert counts["sessions"] == 3
        assert counts["lineage"] == 1, "the child's edge landed"
        assert store.pending_lineage() == []

        # The citation surface is prose only, one row per distinct prose text.
        visible = store.visible_evidence(PARENT)
        assert [row["body"] for row in visible] == [
            "why did the gate fail?",
            "recall was low, 0.107 macro",
            "and the tokenizer?",
            "measured in Stage F",
        ]
        # Tool text is stored but never citable and never searchable.
        assert store.search_prose("[tool:Bash]") == []
        assert [hit["session_id"] for hit in store.search_prose("tokenizer")] == [PARENT]

        parent_row = store.connection.execute(
            "SELECT parent_id, adapter_version, classifier_version, exporter_dupes_collapsed"
            " FROM sessions WHERE id = ?",
            (CHILD,),
        ).fetchone()
        assert parent_row["parent_id"] == PARENT
        assert parent_row["adapter_version"] == "archive-v1"
        assert parent_row["classifier_version"] == "archive-classifier-v1"

        dupe_row = store.connection.execute(
            "SELECT exporter_dupes_collapsed FROM sessions WHERE id = ?", (DUPES,)
        ).fetchone()
        assert dupe_row["exporter_dupes_collapsed"] == 2
    finally:
        store.close()


def test_reingesting_the_whole_archive_is_a_no_op(adapter: ArchiveAdapter, tmp_path: Path) -> None:
    """The sweep runs repeatedly over overlapping windows; it must add nothing."""
    store = Store.connect(tmp_path / "lm.db")
    store.install()

    def sweep() -> None:
        for session_id in adapter.session_ids():
            try:
                store.ingest(adapter.parse_id(session_id))
            except NoEvidenceError:
                continue

    try:
        sweep()
        snapshot = store.row_counts()
        sweep()
        sweep()
        assert store.row_counts() == snapshot
    finally:
        store.close()
