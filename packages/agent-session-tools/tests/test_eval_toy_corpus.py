"""Validation tier on public data: both rulers compute real numbers on the toy corpus.

These tests are the CI stand-in for the receipts written against the
learner's private database. They pin the live tool's behaviour next to the frozen Stage 1 control
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

from agent_session_tools.eval import K, MIN_LIFT
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


def test_the_crash_class_is_gone_and_the_frozen_control_still_shows_it(
    toy: ToyCorpus,
) -> None:
    """Stage 2 flipped this pin on purpose: the live tool crashes on nothing.

    Stage 1 pinned nine crashes -- the three planted C-* questions and six
    ordinary ones -- every one carrying a lowercase and/or/not that the
    shipped code took for an FTS5 operator. The frozen replica keeps that
    behaviour as the control, so the defect stays visible next to its fix.
    """
    gold = load_gold(toy.gold_path)
    questions = {item["id"]: item["question"] for item in gold.items}
    live = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
    assert live.crashes == 0 and not live.errors_by_kind
    assert all(
        live.per_item[item_id].hit and live.per_item[item_id].rank == 1
        for item_id in toy.crash_ids
    )
    frozen = score_arm(build_arm("frozen", toy.db_path, 10), gold.items, K)
    crashed = {i for i, row in frozen.per_item.items() if row.error_kind}
    assert set(toy.crash_ids) <= crashed
    assert all(_has_trigger(questions[i]) for i in crashed), crashed
    assert set(frozen.errors_by_kind) == {"backtick", "question-mark", "comma"}
    assert frozen.crashes == 9


def test_stage2_lexical_shape_keyword_complete_paraphrase_untouched(
    toy: ToyCorpus,
) -> None:
    """Pins Stage 2's numbers exactly so Stage 4 moves them on purpose.

    K is complete: every keyword question is found once nothing crashes. P is
    unchanged at 5/12 -- the paraphrase gap a lexical arm cannot close and the
    number the semantic arm must move. R is complete for the same reason as K
    (its two Stage 1 misses were crashes).
    """
    gold = load_gold(toy.gold_path)
    result = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
    by = result.recall["by_stratum"]
    assert by["K"] == pytest.approx(15 / 15)
    assert by["P"] == pytest.approx(5 / 12)
    assert by["R"] == pytest.approx(12 / 12)


def test_frozen_control_differs_from_the_live_tool_exactly_where_it_crashed(
    toy: ToyCorpus,
) -> None:
    """The only items that moved are the nine the control crashes on, each now
    a rank-1 hit, so the paired bootstrap reports an established lift -- the
    toy set's version of the Stage 2 gate."""
    gold = load_gold(toy.gold_path)
    live = score_arm(build_arm("mcp", toy.db_path, 10), gold.items, K)
    frozen = score_arm(build_arm("frozen", toy.db_path, 10), gold.items, K)

    def shape(row):
        return (row.rank, row.hit, row.error_kind)

    moved = {
        i for i in live.per_item if shape(live.per_item[i]) != shape(frozen.per_item[i])
    }
    assert moved == {i for i, row in frozen.per_item.items() if row.error_kind}
    assert all(live.per_item[i].hit and live.per_item[i].rank == 1 for i in moved)
    stats = cluster_bootstrap(live.per_item, frozen.per_item, gold.items)
    assert stats["point"] == pytest.approx(19 / 90, abs=1e-6)
    assert stats["ci95"][0] >= MIN_LIFT


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
        assert all(q.tied(K) for q in boiler)
        twins = [
            q for q in questions if q.session_id in toy.twin_sessions and q.twins == 1
        ]
        assert {q.session_id for q in twins} == set(toy.twin_sessions)
        assert not any(q.tied(K) for q in twins)

        # Both arms exclude the question itself at query time -- the frozen
        # replica at SQL level, the live tool through exclude_message_ids -- so
        # the census can gate the real tool. Every control crash is a live hit.
        live = run_census(conn, build_arm("mcp", toy.db_path, K), questions, k=K)
        result = run_census(conn, build_arm("frozen", toy.db_path, K), questions, k=K)
    finally:
        conn.close()
    assert live.n_eligible == result.n_eligible
    assert (live.miss_crash, result.miss_crash) == (0, 4)
    assert live.hits == result.hits + result.miss_crash
    assert (live.miss_vocab, live.miss_ranking) == (
        result.miss_vocab,
        result.miss_ranking,
    )
    assert result.n_tied == len(toy.boilerplate_sessions)
    assert result.untied_share == pytest.approx(1 - result.n_tied / result.n_eligible)
    assert 0.0 <= result.hit_rate_untied <= 1.0
    assert result.hits_tied <= result.n_tied
    assert (
        result.miss_vocab + result.miss_crash + result.miss_ranking + result.hits
        == result.n_eligible
    )
