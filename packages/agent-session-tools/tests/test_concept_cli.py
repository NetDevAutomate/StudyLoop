"""session-context wind-down/concept CLI verbs and the memory_winddown MCP tool.

tasks.md 3.2: malformed input fails loudly with field-level errors; valid
input survives a lossless round trip; ``context_assertions.proposed_state``
stays execution state.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agent_session_tools.context.cli import app
from agent_session_tools.context.concepts import ConceptService, _ConceptRepository
from agent_session_tools.context.store import ContextStore, NativeSource
from agent_session_tools.context.provenance import Origin

runner = CliRunner()

_NOW = "2026-09-08T12:00:00+00:00"
_QUOTE = "Wind-down CLI exact evidence quote."


@pytest.fixture
def store(production_store):
    """production_store with one extra quotable evidence body."""
    conn = production_store.conn
    store = ContextStore(conn)
    store.capture(
        NativeSource(
            session_id="fixture-session-1",
            native_key="cli-quote",
            harness="codex",
            native_kind="message",
            native_locator="fixture://codex/fixture-session-1#cli-quote",
            parser_version="fixture",
            machine_id="fixture-machine",
            body=_QUOTE,
            origin=Origin.CONVERSATION,
        )
    )
    conn.commit()
    return production_store


def _document(**overrides) -> dict:
    concept = {
        "type": "Decision",
        "title": "CLI wind-down concept",
        "description": "The CLI wind-down concept statement.",
        "tags": ["cli", "winddown"],
        "confidence": 0.9,
        "quotes": [{"quote": _QUOTE}],
        **overrides,
    }
    return {"concepts": [concept]}


def _write_doc(tmp_path, payload) -> str:
    path = tmp_path / "winddown.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestWinddown:
    def test_valid_input_round_trips_losslessly(self, store, tmp_path):
        result = runner.invoke(
            app,
            [
                "winddown",
                "--session",
                "fixture-session-1",
                "--from",
                _write_doc(tmp_path, _document()),
                "--db",
                str(store.db_path),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["command"] == "winddown"
        assert payload["writes"] == 1
        assert payload["errors"] == []
        [concept_id] = payload["concept_ids"]

        row = store.conn.execute(
            "SELECT kind,title,statement,canonical_tags,confidence,binding_state "
            "FROM context_concepts WHERE id=?",
            (concept_id,),
        ).fetchone()
        assert tuple(row) == (
            "Decision",
            "CLI wind-down concept",
            "The CLI wind-down concept statement.",
            '["cli","winddown"]',
            0.9,
            "bound",
        )
        # Errata #3: the backing assertion keeps execution state, never a
        # concept vocabulary.
        assert store.conn.execute(
            "SELECT proposed_state FROM context_assertions WHERE id=?",
            (concept_id,),
        ).fetchone() == ("unknown",)

    def test_stdin_input_is_accepted(self, store):
        result = runner.invoke(
            app,
            [
                "winddown",
                "--session",
                "fixture-session-1",
                "--stdin",
                "--db",
                str(store.db_path),
            ],
            input=json.dumps(_document()),
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["writes"] == 1

    def test_malformed_document_fails_loudly_with_field_level_errors(
        self, store, tmp_path
    ):
        bad = _document(type="Nonsense", confidence=0.1)
        result = runner.invoke(
            app,
            [
                "winddown",
                "--session",
                "fixture-session-1",
                "--from",
                _write_doc(tmp_path, bad),
                "--db",
                str(store.db_path),
            ],
        )
        assert result.exit_code == 2
        payload = json.loads(result.stderr)
        paths = {error["path"] for error in payload["errors"]}
        assert "/concepts/0/type" in paths
        assert "/concepts/0/confidence" in paths
        assert payload["writes"] == 0
        # No partial writes.
        assert store.conn.execute(
            "SELECT COUNT(*) FROM context_concepts"
        ).fetchone() == (0,)

    def test_invalid_json_fails_loudly(self, store, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "winddown",
                "--session",
                "fixture-session-1",
                "--from",
                str(path),
                "--db",
                str(store.db_path),
            ],
        )
        assert result.exit_code == 2
        payload = json.loads(result.stderr)
        assert payload["errors"][0]["code"] == "invalid_json"

    def test_symlink_input_is_refused(self, store, tmp_path):
        target = tmp_path / "target.json"
        target.write_text(json.dumps(_document()), encoding="utf-8")
        link = tmp_path / "link.json"
        link.symlink_to(target)
        result = runner.invoke(
            app,
            [
                "winddown",
                "--session",
                "fixture-session-1",
                "--from",
                str(link),
                "--db",
                str(store.db_path),
            ],
        )
        assert result.exit_code == 2
        assert json.loads(result.stderr)["errors"][0]["code"] == "unsafe_input"


def _created_concept(store, tmp_path) -> str:
    service = ConceptService(store.db_path, now=lambda: _NOW, prepare_schema=False)
    created = service.winddown("fixture-session-1", _document(), actor="fixture-author")
    assert created.errors == ()
    return created.concept_ids[0]


class TestLifecycleVerbs:
    def test_accept_then_retire(self, store, tmp_path):
        concept_id = _created_concept(store, tmp_path)
        accepted = runner.invoke(
            app,
            [
                "concept",
                "accept",
                concept_id,
                "--reason",
                "operator accepted",
                "--db",
                str(store.db_path),
            ],
        )
        assert accepted.exit_code == 0, accepted.output
        payload = json.loads(accepted.stdout)
        assert payload["standing"] == "accepted"
        assert payload["writes"] == 1

        retired = runner.invoke(
            app,
            [
                "concept",
                "retire",
                concept_id,
                "--reason",
                "operator retired",
                "--db",
                str(store.db_path),
            ],
        )
        assert retired.exit_code == 0, retired.output
        assert json.loads(retired.stdout)["standing"] == "retired"

    def test_retired_is_terminal_with_a_field_level_error(self, store, tmp_path):
        concept_id = _created_concept(store, tmp_path)
        for _ in range(1):
            runner.invoke(
                app,
                [
                    "concept",
                    "retire",
                    concept_id,
                    "--reason",
                    "first retire",
                    "--db",
                    str(store.db_path),
                ],
            )
        again = runner.invoke(
            app,
            [
                "concept",
                "accept",
                concept_id,
                "--reason",
                "too late",
                "--db",
                str(store.db_path),
            ],
        )
        assert again.exit_code == 2
        payload = json.loads(again.stderr)
        assert payload["errors"][0]["code"] == "retired_terminal"
        assert payload["errors"][0]["path"] == "/standing"


class TestBind:
    def test_bind_legacy_root_with_exact_quotes(self, store, tmp_path):
        conn = store.conn
        repository = _ConceptRepository(conn, now=lambda: _NOW)
        conn.execute("BEGIN")
        legacy_id = repository.seed_legacy(
            original_bytes=b"legacy fixture bytes",
            kind="Decision",
            title="CLI wind-down concept",
            statement="The CLI wind-down concept statement.",
            tags=("cli", "winddown"),
            confidence=0.9,
            source_session_id="fixture-session-1",
            source_uri="sessionweaver://session/fixture-session-1",
            producer="legacy-writer",
        )
        conn.commit()

        document = tmp_path / "bind.json"
        document.write_text(json.dumps({"quotes": [{"quote": _QUOTE}]}))
        result = runner.invoke(
            app,
            [
                "concept",
                "bind",
                legacy_id,
                "--from",
                str(document),
                "--reason",
                "operator bind",
                "--db",
                str(store.db_path),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["legacy_concept_id"] == legacy_id
        assert payload["writes"] == 4
        assert payload["concept_id"]


class TestImportOkf:
    def _okf_tree(self, tmp_path):
        root = tmp_path / "okf"
        root.mkdir()
        (root / "one.md").write_text(
            "---\n"
            "type: Finding\n"
            "title: Legacy OKF record\n"
            "description: Legacy OKF description.\n"
            "tags: [legacy, okf]\n"
            "sources:\n"
            "  - resource: sessionweaver://session/fixture-session-1\n"
            "    role: transcript\n"
            "verified:\n"
            "  status: machine-confirmed\n"
            "  by: legacy-writer\n"
            "confidence: 0.8\n"
            "actor: legacy-writer\n"
            "---\n"
            "Legacy OKF body statement.\n",
            encoding="utf-8",
        )
        return root

    def test_dry_run_then_write_with_report(self, store, tmp_path):
        root = self._okf_tree(tmp_path)
        dry = runner.invoke(
            app,
            [
                "concept",
                "import-okf",
                str(root),
                "--dry-run",
                "--db",
                str(store.db_path),
            ],
        )
        assert dry.exit_code == 0, dry.output
        assert json.loads(dry.stdout)["writes"] == 0

        report_path = tmp_path / "report.json"
        write = runner.invoke(
            app,
            [
                "concept",
                "import-okf",
                str(root),
                "--report",
                str(report_path),
                "--db",
                str(store.db_path),
            ],
        )
        assert write.exit_code == 0, write.output
        payload = json.loads(write.stdout)
        assert payload["scanned"] == 1
        assert payload["imported"] == 1
        assert json.loads(report_path.read_text()) == payload

    def test_symlinked_directory_is_refused(self, store, tmp_path):
        root = self._okf_tree(tmp_path)
        link = tmp_path / "okf-link"
        link.symlink_to(root)
        result = runner.invoke(
            app,
            ["concept", "import-okf", str(link), "--db", str(store.db_path)],
        )
        assert result.exit_code == 2
        assert json.loads(result.stderr)["errors"][0]["code"] == "unsafe_directory"


class TestProject:
    def test_projection_writes_disposable_markdown(self, store, tmp_path):
        concept_id = _created_concept(store, tmp_path)
        out = tmp_path / "projection"
        result = runner.invoke(
            app,
            [
                "concept",
                "project",
                "--out",
                str(out),
                "--json",
                "--db",
                str(store.db_path),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["created"] == 1
        [markdown] = [p for p in out.glob("*.md")]
        content = markdown.read_text(encoding="utf-8")
        assert concept_id in content
        assert "The CLI wind-down concept statement." in content


class TestMemoryWinddownTool:
    def _tool(self):
        pytest.importorskip("fastmcp")
        from importlib import import_module

        from agent_session_tools.mcp_server import mcp

        run_async = import_module(
            f"{__package__}._helpers" if __package__ else "_helpers"
        ).run_async
        tools = run_async(mcp._list_tools())
        return {tool.name: tool.fn for tool in tools}["memory_winddown"]  # type: ignore[attr-defined]

    def test_valid_document_writes_and_reports(self, store):
        tool = self._tool()
        result = tool(session_id="fixture-session-1", document=_document())
        assert result["writes"] == 1
        assert result["concept_ids"]
        assert result["errors"] == []

    def test_malformed_document_fails_loudly_without_partial_writes(self, store):
        tool = self._tool()
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError) as excinfo:
            tool(
                session_id="fixture-session-1",
                document=_document(type="Nonsense", confidence=2.0),
            )
        payload = json.loads(str(excinfo.value))
        paths = {error["path"] for error in payload["errors"]}
        assert "/concepts/0/type" in paths
        assert "/concepts/0/confidence" in paths
        assert store.conn.execute(
            "SELECT COUNT(*) FROM context_concepts"
        ).fetchone() == (0,)
