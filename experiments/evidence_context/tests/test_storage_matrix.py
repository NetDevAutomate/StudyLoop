"""Small cycle, multi-edge and missing-root correctness checks for storage clients."""

import pytest

from experiments.evidence_context.storage_matrix.benchmark import (
    build_graph,
    build_sql,
    graph_query,
    hybrid_query,
    sql_query,
)
from experiments.evidence_context.storage_matrix.query_diagnostic import indexed_query


def test_full_and_projection_graph_preserve_rows_on_cycles(tmp_path):
    pytest.importorskip("ladybug")
    records = [
        {"id": key, "project": "p", "at": "2026", "text": "body " + key}
        for key in ("a", "b", "c", "isolated")
    ]
    edges = [
        ("a", "b", "sequence"),
        ("a", "b", "file"),
        ("b", "a", "sequence"),
        ("b", "c", "sequence"),
    ]
    sql, _ = build_sql(tmp_path / "content.sqlite", records, edges)
    db, graph, _ = build_graph(tmp_path / "full.lbdb", records, edges)
    pdb, projection, _ = build_graph(tmp_path / "projection.lbdb", records, edges, True)
    try:
        assert [r[0] for r in sql_query(sql, "a", 2)] == ["a", "b", "c"]
        for root in ("a", "b", "isolated", "missing"):
            for depth in (0, 1, 2):
                expected = sql_query(sql, root, depth)
                assert graph_query(graph, root, depth) == expected
                assert hybrid_query(projection, sql, root, depth) == expected
                assert indexed_query(sql, root, depth) == expected
    finally:
        graph.close()
        db.close()
        projection.close()
        pdb.close()
        sql.close()
