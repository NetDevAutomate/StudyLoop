"""Tests for mastery graph web routes."""

from __future__ import annotations

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app  # noqa: E402


def test_api_mastery_graph_returns_json_contract(monkeypatch) -> None:
    seen: dict[str, int | None] = {}

    def fake_graph(topic: str, *, max_edges: int | None = None) -> dict:
        seen["max_edges"] = max_edges
        return {
            "topic": topic,
            "nodes": ["decorators"],
            "edges": [],
            "edge_count_total": 0,
            "limited": False,
        }

    monkeypatch.setattr(
        "studyloop.web.routes.mastery.mastery_graph_json",
        fake_graph,
    )
    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/mastery/graph?topic=python&limit=25")

    assert resp.status_code == 200
    assert resp.json()["topic"] == "python"
    assert resp.json()["nodes"] == ["decorators"]
    assert seen["max_edges"] == 25


def test_api_mastery_graph_returns_mermaid(monkeypatch) -> None:
    seen: dict[str, int | None] = {}

    def fake_mermaid(topic: str, *, max_edges: int | None = None) -> str:
        seen["max_edges"] = max_edges
        return f"flowchart LR\n  {topic}[{topic}]"

    monkeypatch.setattr(
        "studyloop.web.routes.mastery.mastery_graph_mermaid",
        fake_mermaid,
    )
    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/mastery/graph?topic=python&format=mermaid&limit=30")

    assert resp.status_code == 200
    assert resp.text.startswith("flowchart LR")
    assert "text/plain" in resp.headers["content-type"]
    assert seen["max_edges"] == 30


def test_api_mastery_weak_links_returns_items(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.web.routes.mastery.weak_links_for_topic",
        lambda topic: [{"topic": topic, "concept": "decorators", "dependency": "closures"}],
    )
    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/mastery/weak-links?topic=python")

    assert resp.status_code == 200
    assert resp.json()["weak_links"][0]["concept"] == "decorators"
    assert resp.json()["weak_link_count_total"] == 1
