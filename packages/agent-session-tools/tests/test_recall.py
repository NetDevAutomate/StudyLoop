"""Contract and public-boundary tests for concept-first memory recall."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

import pytest
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "data" / "recall-contract.json"
)
_NOW = "2026-09-08T12:00:00+00:00"


class ProductionStore(Protocol):
    conn: sqlite3.Connection
    db_path: Path
    config_path: Path


def _service(store: ProductionStore):
    from agent_session_tools.context.concepts import ConceptService

    return ConceptService(store.db_path, now=lambda: _NOW)


def _capture(
    store: ProductionStore,
    body: str,
    *,
    session_id: str = "fixture-session-1",
    key: str | None = None,
) -> str:
    from agent_session_tools.context.provenance import Origin
    from agent_session_tools.context.store import ContextStore, NativeSource

    native_key = key or hashlib.sha256(body.encode()).hexdigest()[:16]
    return ContextStore(store.conn).capture(
        NativeSource(
            session_id=session_id,
            native_key=native_key,
            harness="fixture",
            native_kind="message:user",
            native_locator=f"fixture://{session_id}/{native_key}",
            parser_version="recall-test-v1",
            machine_id="fixture-machine",
            body=body,
            origin=Origin.CONVERSATION,
            recorded_at=_NOW,
        )
    )


def _concept(
    quote: str,
    *,
    title: str,
    description: str,
) -> dict[str, Any]:
    return {
        "type": "Finding",
        "title": title,
        "description": description,
        "tags": ["recall", "studyloop"],
        "confidence": 0.9,
        "quotes": [{"quote": quote}],
    }


def _document(*concepts: dict[str, Any]) -> dict[str, Any]:
    return {"concepts": list(concepts)}


def _message(
    store: ProductionStore,
    *,
    message_id: str,
    session_id: str,
    content: str,
    timestamp: str = _NOW,
) -> None:
    store.conn.execute(
        "INSERT INTO messages(id,session_id,role,content,timestamp) VALUES (?,?,?,?,?)",
        (message_id, session_id, "user", content, timestamp),
    )
    store.conn.commit()


def _tool_names() -> set[str]:
    from agent_session_tools.mcp_server import mcp

    return {tool.name for tool in asyncio.run(mcp._list_tools())}


def _mcp_text(result: Any) -> str:
    return "".join(block.text for block in result.content if block.type == "text")


def test_frozen_recall_contract_matches_sessionweaver_v0_2_0() -> None:
    assert (
        hashlib.sha256(_CONTRACT_PATH.read_bytes()).hexdigest()
        == (
            "504c2d403ebf77e26639e86795b9397b77c0c1346e6092401ea7919b20d2b8d1"  # pragma: allowlist secret
        )
    )


def test_server_exposes_memory_recall() -> None:
    assert "memory_recall" in _tool_names()


def test_recall_is_concept_first_contract_valid_and_deduplicates_source_session(
    production_store: ProductionStore,
) -> None:
    from agent_session_tools.recall import recall

    service = _service(production_store)
    quote = "contract recall evidence"
    _capture(production_store, quote, key="contract-recall-evidence")
    concept_id = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                quote,
                title="Contract recall concept",
                description="contractrecallterm statement",
            )
        ),
        actor="model",
    ).concept_ids[0]
    _message(
        production_store,
        message_id="contract-source-message",
        session_id="fixture-session-1",
        content="contractrecallterm source session",
    )
    _message(
        production_store,
        message_id="contract-other-message",
        session_id="fixture-session-2",
        content="contractrecallterm independent session",
    )

    report = recall(production_store.db_path, "contractrecallterm")
    payload = report.to_dict()

    Draft202012Validator(
        json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    ).validate(payload)
    assert [hit.concept_id for hit in report.concepts] == [concept_id]
    assert [hit.session_id for hit in report.sessions] == ["fixture-session-2"]
    assert list(payload) == ["concepts", "sessions", "plan", "k", "project"]


def test_recall_excludes_tombstoned_sessions_and_retired_concepts(
    production_store: ProductionStore,
) -> None:
    from agent_session_tools.recall import recall

    service = _service(production_store)
    retired_quote = "retired recall evidence"
    _capture(
        production_store,
        retired_quote,
        session_id="fixture-session-2",
        key="retired-recall-evidence",
    )
    retired_id = service.winddown(
        "fixture-session-2",
        _document(
            _concept(
                retired_quote,
                title="Retired recall concept",
                description="hiddenrecallterm retired statement",
            )
        ),
        actor="model",
    ).concept_ids[0]
    service.transition(retired_id, "retired", actor="owner", reason="obsolete")

    tombstone_quote = "tombstone recall evidence"
    _capture(production_store, tombstone_quote, key="tombstone-recall-evidence")
    service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                tombstone_quote,
                title="Tombstoned recall concept",
                description="hiddenrecallterm tombstoned statement",
            )
        ),
        actor="model",
    )
    _message(
        production_store,
        message_id="tombstoned-recall-message",
        session_id="fixture-session-1",
        content="hiddenrecallterm raw message",
    )
    production_store.conn.execute(
        "INSERT INTO context_tombstones VALUES (?,?,?)",
        ("fixture-session-1", "recall-deletion", _NOW),
    )
    production_store.conn.commit()

    report = recall(production_store.db_path, "hiddenrecallterm")

    assert report.concepts == ()
    assert report.sessions == ()


def test_recall_session_fallback_preserves_and_then_or_order_and_preview(
    production_store: ProductionStore,
) -> None:
    from agent_session_tools.recall import recall

    _message(
        production_store,
        message_id="fallback-both",
        session_id="fixture-session-1",
        content="fallbackalpha fallbackbravo " + "X" * 400,
        timestamp="2026-09-08T12:01:00+00:00",
    )
    _message(
        production_store,
        message_id="fallback-only",
        session_id="fixture-session-2",
        content="fallbackalpha only",
        timestamp="2026-09-08T12:02:00+00:00",
    )

    report = recall(production_store.db_path, "fallbackalpha fallbackbravo", k=2)

    assert [hit.session_id for hit in report.sessions] == [
        "fixture-session-1",
        "fixture-session-2",
    ]
    assert report.plan.fallback_used is True
    assert len(report.sessions[0].preview) == 300


def test_recall_executes_no_embedding_or_ontology_statement(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_session_tools.recall import recall

    executed: list[str] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(executed.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)

    recall(production_store.db_path, "reach context evidence")

    assert executed
    forbidden = ("message_embeddings", "semantic_search", "ontology_")
    assert all(
        not any(term in statement.lower() for term in forbidden)
        for statement in executed
    )


def test_recall_module_has_no_semantic_or_ontology_import() -> None:
    import agent_session_tools.recall as recall_module

    tree = ast.parse(Path(recall_module.__file__).read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert all("semantic_search" not in name for name in imported)
    assert all("ontology" not in name for name in imported)


@pytest.mark.asyncio
async def test_memory_recall_mcp_success_matches_library_contract(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_session_tools.mcp_server import _create_server

    monkeypatch.setattr(
        "agent_session_tools.mcp_server._get_db_path",
        lambda: production_store.db_path,
    )
    server = _create_server()
    async with create_connected_server_and_client_session(
        server._mcp_server, raise_exceptions=False
    ) as session:
        result = await session.call_tool(
            "memory_recall", {"question": "reach context evidence", "k": 2}
        )

    assert not result.isError
    payload = json.loads(_mcp_text(result))
    Draft202012Validator(
        json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    ).validate(payload)
    assert payload["k"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("k", "is_error"),
    [(1, False), (50, False), (0, True), (51, True), (True, True)],
)
async def test_memory_recall_mcp_enforces_k_bounds(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    k: Any,
    is_error: bool,
) -> None:
    from agent_session_tools.mcp_server import _create_server

    monkeypatch.setattr(
        "agent_session_tools.mcp_server._get_db_path",
        lambda: production_store.db_path,
    )
    server = _create_server()
    async with create_connected_server_and_client_session(
        server._mcp_server, raise_exceptions=False
    ) as session:
        result = await session.call_tool(
            "memory_recall", {"question": "context evidence", "k": k}
        )

    assert result.isError is is_error


@pytest.mark.asyncio
async def test_memory_recall_mcp_rejects_oversize_question(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_session_tools.mcp_server import _create_server

    monkeypatch.setattr(
        "agent_session_tools.mcp_server._get_db_path",
        lambda: production_store.db_path,
    )
    server = _create_server()
    async with create_connected_server_and_client_session(
        server._mcp_server, raise_exceptions=False
    ) as session:
        result = await session.call_tool("memory_recall", {"question": "x" * 4001})

    assert result.isError
    assert "at most 4000" in _mcp_text(result)


@pytest.mark.asyncio
async def test_memory_recall_mcp_scope_failure_uses_b1_diagnostic(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_session_tools.mcp_server import _create_server

    config = tmp_path / "unclassified-missing.yaml"
    config.write_text("memory: {}\n", encoding="utf-8")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setattr(
        "agent_session_tools.mcp_server._get_db_path",
        lambda: production_store.db_path,
    )
    server = _create_server()
    async with create_connected_server_and_client_session(
        server._mcp_server, raise_exceptions=False
    ) as session:
        result = await session.call_tool(
            "memory_recall", {"question": "context evidence"}
        )

    assert result.isError
    text = _mcp_text(result)
    payload = json.loads(text[text.index("{") :])
    assert payload["code"] == "scope_unconfigured"
    assert payload["remediation"]
