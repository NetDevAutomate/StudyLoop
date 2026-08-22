"""Tests for mastery graph colour categories, legend data and mermaid styling.

The node signal is `study_progress.confidence`, so these tests build both
`concept_dependencies` and `study_progress`, plus one case with no
`study_progress` table at all — the shape unit tests of the graph already use,
and the shape a fresh install has before any teach-back is recorded.
"""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

import pytest

from studyloop.learning import mastery

if TYPE_CHECKING:
    from pathlib import Path

_DEPENDENCIES_DDL = """
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

_PROGRESS_DDL = """
CREATE TABLE study_progress (
    id TEXT,
    topic TEXT,
    concept TEXT,
    confidence TEXT,
    last_teachback_score INTEGER,
    last_seen TEXT
)
"""

_EDGES = [
    ("1", "python", "decorators", "closures", "heading_path", "n.md", "heading", 0.45),
    ("2", "python", "closures", "scope", "backlink", "n.md", "backlink", 0.5),
    ("3", "python", "scope", "namespaces", "tagged_with", "n.md", "tag", 0.35),
    ("4", "python", "namespaces", "imports", "prerequisite", "n.md", "explicit", 0.8),
    ("5", "python", "imports", "packaging", "heading_path", "n.md", "heading", 0.45),
]

_PROGRESS = [
    ("p1", "python", "decorators", "struggling", 6, "2026-08-01"),
    ("p2", "python", "closures", "learning", 12, "2026-08-02"),
    ("p3", "python", "scope", "confident", 16, "2026-08-03"),
    ("p4", "python", "namespaces", "mastered", 19, "2026-08-04"),
    # confidence missing, score present — exercises the score fallback.
    ("p5", "python", "imports", None, 7, "2026-08-05"),
    # "packaging" is deliberately absent: no evidence at all.
]


def _build(tmp_path: Path, monkeypatch, *, with_progress: bool = True) -> None:
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(_DEPENDENCIES_DDL)
    conn.executemany("INSERT INTO concept_dependencies VALUES (?,?,?,?,?,?,?,?)", _EDGES)
    if with_progress:
        conn.execute(_PROGRESS_DDL)
        conn.executemany("INSERT INTO study_progress VALUES (?,?,?,?,?,?)", _PROGRESS)
    conn.commit()
    conn.close()

    def connect():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(mastery._connection, "_connect", connect)
    monkeypatch.setattr(mastery, "seed_inferred_dependencies", lambda topic: 0)


def test_node_categories_come_from_study_progress_confidence(tmp_path, monkeypatch) -> None:
    _build(tmp_path, monkeypatch)

    categories = mastery.mastery_graph_json("python")["node_categories"]

    assert categories["decorators"] == "struggling"
    assert categories["closures"] == "learning"
    assert categories["scope"] == "confident"
    assert categories["namespaces"] == "mastered"


def test_node_without_progress_row_is_untracked(tmp_path, monkeypatch) -> None:
    _build(tmp_path, monkeypatch)

    categories = mastery.mastery_graph_json("python")["node_categories"]

    assert categories["packaging"] == "untracked"


def test_score_only_row_falls_back_to_teachback_thresholds(tmp_path, monkeypatch) -> None:
    """A row with no `confidence` is placed by score, never left untracked."""
    _build(tmp_path, monkeypatch)

    categories = mastery.mastery_graph_json("python")["node_categories"]

    assert categories["imports"] == "struggling"


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0, "struggling"), (8, "struggling"), (9, "learning"), (13, "learning"), (14, "confident")],
)
def test_score_thresholds_match_teachback_writer(score: int, expected: str) -> None:
    """The score bands must agree with the function that writes `confidence`."""
    from studyloop.history.teachback import _confidence_from_teachback

    assert mastery._category_for_progress({"last_teachback_score": score}) == expected
    # The writer agrees below the mastery band, which needs a `review_type`
    # that `study_progress` does not carry.
    if score < 18:
        assert _confidence_from_teachback(score, "micro") == expected


def test_missing_study_progress_table_is_tolerated(tmp_path, monkeypatch) -> None:
    """A DB with no `study_progress` table must still produce a graph."""
    _build(tmp_path, monkeypatch, with_progress=False)

    graph = mastery.mastery_graph_json("python")

    assert set(graph["node_categories"].values()) == {"untracked"}


def test_mermaid_emits_classdef_for_every_category(tmp_path, monkeypatch) -> None:
    _build(tmp_path, monkeypatch)

    output = mastery.mastery_graph_mermaid("python")

    assert output.startswith("flowchart LR")
    for category in mastery._NODE_CATEGORIES:
        assert f"classDef {category['class_name']} " in output
        assert f"fill:{category['colour']}" in output


def test_mermaid_assigns_nodes_to_their_category_class(tmp_path, monkeypatch) -> None:
    _build(tmp_path, monkeypatch)

    output = mastery.mastery_graph_mermaid("python")

    assert "class decorators,imports slStruggling;" in output
    assert "class packaging slUntracked;" in output


def test_untracked_class_is_dashed_as_a_non_colour_signal(tmp_path, monkeypatch) -> None:
    """Colour is not the only channel: "no evidence" also reads as dashed."""
    _build(tmp_path, monkeypatch)

    output = mastery.mastery_graph_mermaid("python")

    assert "stroke-dasharray:4 3" in output


def test_linkstyle_indices_are_exhaustive_and_in_bounds(tmp_path, monkeypatch) -> None:
    """Mermaid raises on an out-of-bounds linkStyle index, so every emitted
    index must address a real edge and every edge must be styled exactly once.
    """
    _build(tmp_path, monkeypatch)

    output = mastery.mastery_graph_mermaid("python")
    edge_count = len(mastery.mastery_graph_json("python")["edges"])
    styled: list[int] = []
    for match in re.finditer(r"^\s*linkStyle ([\d,]+) ", output, re.MULTILINE):
        styled.extend(int(part) for part in match.group(1).split(","))

    assert sorted(styled) == list(range(edge_count))


def test_unstyled_relation_types_fall_into_the_other_bucket() -> None:
    """`tagged_with`, `bridge` and concept_relations types are not lost."""
    assert mastery._relation_key("heading_path") == "heading_path"
    assert mastery._relation_key("backlink") == "backlink"
    assert mastery._relation_key("tagged_with") == "other"
    assert mastery._relation_key("prerequisite") == "other"


def test_edge_relations_each_get_a_distinct_linkstyle_colour(tmp_path, monkeypatch) -> None:
    _build(tmp_path, monkeypatch)

    output = mastery.mastery_graph_mermaid("python")

    for relation in mastery._EDGE_RELATIONS:
        assert f"stroke:{relation['colour']}" in output


def test_legend_is_data_and_covers_every_styled_category() -> None:
    legend = mastery.mastery_legend()

    node_keys = [item["key"] for item in legend if item["kind"] == "node"]
    edge_keys = [item["key"] for item in legend if item["kind"] == "edge"]
    assert node_keys == [category["key"] for category in mastery._NODE_CATEGORIES]
    assert edge_keys == [relation["key"] for relation in mastery._EDGE_RELATIONS]
    for item in legend:
        assert item["label"]
        assert item["meaning"]
        assert re.fullmatch(r"#[0-9a-f]{6}", item["colour"]), item


def test_legend_colours_match_the_graph_exactly(tmp_path, monkeypatch) -> None:
    """The legend cannot drift: every colour it advertises is in the mermaid."""
    _build(tmp_path, monkeypatch)

    output = mastery.mastery_graph_mermaid("python")

    for item in mastery.mastery_legend():
        assert item["colour"] in output, item


def test_existing_graph_json_fields_are_unchanged(tmp_path, monkeypatch) -> None:
    """The new fields are ADDITIVE — the panel and its tests read the old ones."""
    _build(tmp_path, monkeypatch)

    graph = mastery.mastery_graph_json("python")

    assert set(graph) >= {"topic", "nodes", "edges", "edge_count_total", "limited"}
    assert graph["topic"] == "python"
    assert all(isinstance(node, str) for node in graph["nodes"])
    assert graph["edge_count_total"] == len(_EDGES)


# ---------------------------------------------------------------------------
# API surface — the field the Mastery panel's legend reads
# ---------------------------------------------------------------------------


def _client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from studyloop.web.app import create_app

    return TestClient(create_app(study_dirs=[]))


def test_api_graph_response_carries_the_legend(monkeypatch) -> None:
    """`legend` is present even when the generator returns a legacy payload.

    The route uses `setdefault`, so a substituted generator — which is how the
    existing route tests drive this endpoint — still yields a renderable legend
    rather than an empty panel.
    """
    monkeypatch.setattr(
        "studyloop.web.routes.mastery.mastery_graph_json",
        lambda topic, *, max_edges=None: {
            "topic": topic,
            "nodes": ["decorators"],
            "edges": [],
            "edge_count_total": 0,
            "limited": False,
        },
    )

    resp = _client().get("/api/mastery/graph?topic=python")

    assert resp.status_code == 200
    body = resp.json()
    # Additive: every pre-existing field still reads exactly as before.
    assert body["topic"] == "python"
    assert body["nodes"] == ["decorators"]
    assert body["edges"] == []
    assert body["edge_count_total"] == 0
    assert body["limited"] is False
    # New.
    assert [item["kind"] for item in body["legend"]].count("node") == len(mastery._NODE_CATEGORIES)
    assert [item["kind"] for item in body["legend"]].count("edge") == len(mastery._EDGE_RELATIONS)
    assert "node_categories" in body


def test_api_legend_entries_have_the_fields_a_legend_row_needs() -> None:
    resp = _client().get("/api/mastery/graph?topic=python")

    assert resp.status_code == 200
    legend = resp.json()["legend"]
    assert legend, "legend must never be empty — the panel iterates it"
    for item in legend:
        assert {"kind", "key", "label", "colour", "meaning"} <= set(item), item
