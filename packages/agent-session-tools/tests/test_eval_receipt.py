"""The receipt: a fingerprint that notices a changed corpus, a digest that ignores the clock."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.eval import RECEIPT_SCHEMA
from agent_session_tools.eval.gold import GoldSet, score_arm
from agent_session_tools.eval.metrics import cluster_bootstrap
from agent_session_tools.eval.receipt import (
    build_receipt,
    db_fingerprint,
    metrics_sha256,
    stable_view,
    write_receipt,
)
from agent_session_tools.eval.seam import Hit, Query

ITEMS = [
    {
        "id": "i1",
        "question": "q1",
        "stratum": "K",
        "cluster": "c1",
        "gold_session_ids": ["s1"],
    },
    {
        "id": "i2",
        "question": "q2",
        "stratum": "P",
        "cluster": "c2",
        "gold_session_ids": ["s2"],
    },
    {
        "id": "i3",
        "question": "q3",
        "stratum": "R",
        "cluster": "c3",
        "gold_session_ids": ["s3"],
    },
]


class _StubArm:
    def __init__(self, name: str, answers: dict[str, list[str]]) -> None:
        self.name = name
        self.supports_exclusion = False
        self.answers = answers

    def search(self, query: Query, k: int) -> list[Hit]:
        return [
            Hit(sid, (f"m-{sid}",), None, self.name) for sid in self.answers[query.text]
        ][:k]

    def describe(self) -> dict[str, object]:
        return {"arm": self.name, "rows": 10}


@pytest.fixture
def fingerprint_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fp.db"
    conn = sqlite3.connect(db_path)
    schema = Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    conn.executescript(schema.read_text())
    from agent_session_tools.migrations import migrate

    migrate(conn)
    for index, session_id in enumerate(("s1", "s2"), start=1):
        conn.execute(
            "INSERT INTO sessions (id, source, project_path, git_branch, "
            "created_at, updated_at, session_type) VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                "claude_code",
                f"/projects/{session_id}",
                "main",
                f"2026-01-0{index}T10:00:00",
                f"2026-01-0{index}T12:00:00",
                "work",
            ),
        )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES ('m-1','s1','user','a planted retrieval note','2026-01-01T10:00:00',1)"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def unclassified_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(json.dumps({"memory": {"default_scope": "unclassified"}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))


@pytest.fixture
def gold_set(tmp_path: Path) -> GoldSet:
    return GoldSet(
        path=tmp_path / "gold.json",
        sha256="deadbeef",
        version="v2",
        name="DEV",
        items=tuple(ITEMS),
    )


@pytest.fixture
def receipt(fingerprint_db: Path, gold_set: GoldSet) -> dict:
    a = score_arm(_StubArm("mcp", {"q1": ["s1"], "q2": ["sx"], "q3": ["s3"]}), ITEMS)
    b = score_arm(_StubArm("frozen", {"q1": ["s1"], "q2": ["sx"], "q3": ["sx"]}), ITEMS)
    return build_receipt(
        db_path=fingerprint_db,
        gold=gold_set,
        results={"mcp": a, "frozen": b},
        comparisons={
            "mcp_vs_frozen": cluster_bootstrap(
                a.per_item, b.per_item, ITEMS, resamples=100
            )
        },
        git_commit="3826a9b4",
    )


class TestSchema:
    def test_the_receipt_carries_the_frozen_schema_and_every_block(self, receipt):
        assert receipt["schema"] == RECEIPT_SCHEMA
        assert set(receipt) >= {
            "schema",
            "created_utc",
            "git_commit",
            "db",
            "gold",
            "arms",
            "comparisons",
            "metrics_sha256",
        }
        assert set(receipt["db"]) == {"path", "size_bytes", "fingerprint"}
        assert receipt["db"]["size_bytes"] > 0
        assert receipt["gold"]["sha256"] == "deadbeef"
        assert receipt["gold"]["n"] == 3

    def test_each_arm_block_has_config_metrics_errors_and_latency(self, receipt):
        for name in ("mcp", "frozen"):
            arm = receipt["arms"][name]
            assert set(arm) >= {"config", "metrics", "errors_by_kind", "latency_ms"}
            assert arm["config"]["arm"] == name
            assert set(arm["latency_ms"]) == {"p50", "p95"}
        assert receipt["arms"]["mcp"]["metrics"]["recall@5"]["macro"] == pytest.approx(
            2 / 3
        )
        assert receipt["arms"]["frozen"]["metrics"]["recall@5"][
            "macro"
        ] == pytest.approx(1 / 3)

    def test_the_comparison_is_the_bootstrap_block(self, receipt):
        comparison = receipt["comparisons"]["mcp_vs_frozen"]
        assert comparison["point"] == pytest.approx(1 / 3)
        assert set(comparison) >= {
            "point",
            "ci95",
            "resamples",
            "seed",
            "clusters",
            "established",
        }

    def test_it_is_written_as_canonical_json(self, receipt, tmp_path):
        out = write_receipt(tmp_path / "nested" / "receipt.json", receipt)
        text = out.read_text()
        assert text.endswith("\n")
        assert '\n  "arms"' in text  # two-space indent, keys sorted (arms first)
        assert json.loads(text) == receipt


class TestStableView:
    def test_it_drops_the_clock_and_every_timing(self, receipt):
        stable = stable_view(receipt)
        assert "created_utc" not in stable
        assert "metrics_sha256" not in stable
        for name in ("mcp", "frozen"):
            assert "latency_ms" not in stable["arms"][name]
            assert all(
                "latency_ms" not in item
                for item in stable["arms"][name]["per_item"].values()
            )
        assert stable["arms"]["mcp"]["metrics"] == receipt["arms"]["mcp"]["metrics"]

    def test_it_does_not_mutate_the_receipt(self, receipt):
        stable_view(receipt)
        assert "created_utc" in receipt
        assert "latency_ms" in receipt["arms"]["mcp"]

    def test_the_digest_ignores_timings_and_the_clock(self, receipt):
        original = receipt["metrics_sha256"]
        assert original == metrics_sha256(receipt)
        slower = json.loads(json.dumps(receipt))
        slower["created_utc"] = "2030-01-01T00:00:00+00:00"
        slower["arms"]["mcp"]["latency_ms"] = {"p50": 999.0, "p95": 4242.0}
        for item in slower["arms"]["mcp"]["per_item"].values():
            item["latency_ms"] = 123.456
        assert metrics_sha256(slower) == original

    def test_the_digest_moves_when_a_result_moves(self, receipt):
        changed = json.loads(json.dumps(receipt))
        changed["arms"]["mcp"]["per_item"]["i2"]["hit"] = 1
        assert metrics_sha256(changed) != receipt["metrics_sha256"]


class TestFingerprint:
    def test_it_is_stable_across_calls(self, fingerprint_db):
        assert db_fingerprint(fingerprint_db) == db_fingerprint(fingerprint_db)

    def test_it_moves_when_the_corpus_moves(self, fingerprint_db):
        before = db_fingerprint(fingerprint_db)
        conn = sqlite3.connect(fingerprint_db)
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
            "VALUES ('m-2','s2','user','one more turn','2026-01-02T10:00:00',1)"
        )
        conn.commit()
        conn.close()
        assert db_fingerprint(fingerprint_db) != before

    def test_a_supplied_fingerprint_is_not_recomputed(self, fingerprint_db, gold_set):
        result = score_arm(_StubArm("mcp", {"q1": ["s1"], "q2": [], "q3": []}), ITEMS)
        receipt = build_receipt(
            db_path=fingerprint_db,
            gold=gold_set,
            results={"mcp": result},
            fingerprint="supplied",
        )
        assert receipt["db"]["fingerprint"] == "supplied"
