"""Validation tier on public data: both rulers compute real numbers on the toy corpus.

These tests are the CI stand-in for the receipts written against the
learner's private database. They pin today's behaviour of the shipped tool
-- the planted crash class reproduces, keyword questions are found,
paraphrase questions are not -- and the harness mechanics: receipt
determinism, frozen-arm parity, census twins and the winnable ceiling.
Stage 2 flips the crash expectations; Stage 4 is expected to move the P
stratum. Each flip is a deliberate edit here, never a silent drift.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.eval import K
from agent_session_tools.eval.arms import build_arm
from agent_session_tools.eval.census import collect_questions, run_census
from agent_session_tools.eval.gold import load_gold, score_arm
from agent_session_tools.eval.metrics import cluster_bootstrap
from agent_session_tools.eval.receipt import build_receipt, stable_view
from agent_session_tools.eval.toy_corpus import BOILERPLATE, ToyCorpus, build_toy_corpus


@pytest.fixture(autouse=True)
def unclassified_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(json.dumps({"memory": {"default_scope": "unclassified"}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))


@pytest.fixture
def toy(tmp_path: Path) -> ToyCorpus:
    return build_toy_corpus(tmp_path / "toy")


def test_builder_is_deterministic(tmp_path: Path) -> None:
    a = build_toy_corpus(tmp_path / "a")
    b = build_toy_corpus(tmp_path / "b")
    assert a.gold_path.read_bytes() == b.gold_path.read_bytes()
    rows_a = sqlite3.connect(a.db_path).execute(
        "SELECT id, content FROM messages ORDER BY id"
    )
    rows_b = sqlite3.connect(b.db_path).execute(
        "SELECT id, content FROM messages ORDER BY id"
    )
    assert rows_a.fetchall() == rows_b.fetchall()


def test_gold_shape_matches_the_real_ruler(toy: ToyCorpus) -> None:
    gold = load_gold(toy.gold_path)
    strata = {item["stratum"] for item in gold.items}
    assert strata == {"K", "P", "R"}
    assert len(gold.items) == 12 * 3 + len(toy.crash_ids)
    assert all(len(item["gold_session_ids"]) == 1 for item in gold.items)


_TRIGGERS = (" and ", " or ", " not ")


def _has_trigger(question: str) -> bool:
    padded = f" {question.lower()} "
    return any(word in padded for word in _TRIGGERS)


def test_todays_tool_crashes_only_on_questions_carrying_a_conjunction(
    toy: ToyCorpus,
) -> None:
    """Every crash is the one raw-pass-through defect: the words and/or/not.

    The planted C-* questions crash, and so do six ordinary questions that
    happen to contain "and" or "or" -- which is the point. Stage 2 flips this:
    the same questions must then return rows, not raise.
    """
    gold = load_gold(toy.gold_path)
    result = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
    questions = {item["id"]: item["question"] for item in gold.items}
    crashed = {item_id for item_id, row in result.per_item.items() if row.error_kind}
    assert set(toy.crash_ids) <= crashed
    assert all(_has_trigger(questions[item_id]) for item_id in crashed), crashed
    assert set(result.errors_by_kind) == {"backtick", "question-mark", "comma"}
    assert result.crashes == 9


def test_todays_lexical_shape_keyword_found_paraphrase_missed(toy: ToyCorpus) -> None:
    """Pins today's numbers exactly so the next stages move them on purpose.

    K is dragged down only by the crash class (every non-crashing keyword
    question is found); P is the paraphrase gap a lexical arm cannot close
    (the five P hits share a stemmed token with their session); R names a
    detail from the answer and is mostly found. Stage 2 should lift K to 15/15
    without touching P; Stage 4 is expected to move P.
    """
    gold = load_gold(toy.gold_path)
    result = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
    by = result.recall["by_stratum"]
    assert by["K"] == pytest.approx(8 / 15)
    assert by["P"] == pytest.approx(5 / 12)
    assert by["R"] == pytest.approx(10 / 12)
    non_crashing_k_misses = [
        item_id
        for item_id, row in result.per_item.items()
        if row.stratum == "K" and not row.hit and not row.error_kind
    ]
    assert non_crashing_k_misses == []


def test_frozen_replica_matches_the_live_tool_item_for_item(toy: ToyCorpus) -> None:
    gold = load_gold(toy.gold_path)
    mcp = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
    frozen = score_arm(build_arm("frozen", toy.db_path, 10), gold.items, K)
    assert {i: (r.rank, r.hit, r.error_kind) for i, r in mcp.per_item.items()} == {
        i: (r.rank, r.hit, r.error_kind) for i, r in frozen.per_item.items()
    }
    stats = cluster_bootstrap(mcp.per_item, frozen.per_item, gold.items)
    assert stats["point"] == 0.0 and stats["ci95"] == [0.0, 0.0]


def test_receipt_metrics_digest_is_stable_across_runs(toy: ToyCorpus) -> None:
    gold = load_gold(toy.gold_path)
    digests = []
    for _ in range(2):
        result = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
        receipt = build_receipt(
            db_path=toy.db_path,
            gold=gold,
            results={"mcp": result},
            comparisons={},
            git_commit="x",
        )
        digests.append(receipt["metrics_sha256"])
        assert "latency_ms" not in json.dumps(stable_view(receipt))
    assert digests[0] == digests[1]


def test_census_sees_the_planted_twins_and_the_unwinnable_boilerplate(
    toy: ToyCorpus,
) -> None:
    conn = sqlite3.connect(f"file:{toy.db_path}?mode=ro", uri=True)
    try:
        questions = collect_questions(conn, k=K)
        boiler = [q for q in questions if q.text.strip() == BOILERPLATE]
        assert len(boiler) == len(toy.boilerplate_sessions)
        assert all(q.twins == len(toy.boilerplate_sessions) - 1 for q in boiler)
        assert all(q.unwinnable(K) for q in boiler)
        twins = [
            q for q in questions if q.session_id in toy.twin_sessions and q.twins == 1
        ]
        assert {q.session_id for q in twins} == set(toy.twin_sessions)
        assert not any(q.unwinnable(K) for q in twins)

        result = run_census(conn, build_arm("mcp", toy.db_path, 4 * K), questions, k=K)
    finally:
        conn.close()
    assert result.n_unwinnable == len(toy.boilerplate_sessions)
    assert result.ceiling == pytest.approx(1 - result.n_unwinnable / result.n_eligible)
    assert 0.0 <= result.hit_rate_of_ceiling <= 1.0
    assert result.hits_unwinnable <= result.n_unwinnable
    assert result.miss_vocab + result.miss_ranking + result.hits == result.n_eligible
