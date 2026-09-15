"""Metric arithmetic, hand-computed: macro is not micro, and the bootstrap is fixed.

Every number in this file is computed by hand in the test body, so a change in
:mod:`agent_session_tools.eval.metrics` cannot quietly redefine the ruler.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_session_tools.eval import MIN_LIFT, NON_INFERIORITY_MARGIN, RESAMPLES, SEED
from agent_session_tools.eval.metrics import (
    ItemScore,
    cluster_bootstrap,
    crash_count,
    errors_by_kind,
    hit_and_rank,
    latency_percentiles,
    macro_average,
    mrr_at_k,
    non_inferiority,
    paired_cluster_bootstrap,
    precision_at_k,
    precision_values,
    recall_at_k,
)


def _six_items() -> dict[str, ItemScore]:
    """Six scored items across three strata: K 2/2, P 0/1, R 1/3.

    micro recall = 3/6 = 0.5, macro = (1.0 + 0.0 + 1/3)/3 -- deliberately
    different, because the ruler is macro over strata.
    """
    return {
        "k1": ItemScore("K", "c1", 1, 1.0, 1),
        "k2": ItemScore("K", "c1", 1, 0.5, 2),
        "p1": ItemScore("P", "c2", 0, 0.0, None),
        "r1": ItemScore("R", "c3", 1, 0.2, 5),
        "r2": ItemScore("R", "c3", 0, 0.0, None),
        "r3": ItemScore("R", "c4", 0, 0.0, None),
    }


class TestPerItem:
    def test_hit_is_the_first_gold_session_within_k(self):
        assert hit_and_rank(["a", "b", "c"], {"c"}, 5) == (1, 1 / 3, 3)

    def test_a_gold_session_past_k_is_a_miss(self):
        ranked = ["a", "b", "c", "d", "e", "gold"]
        assert hit_and_rank(ranked, {"gold"}, 5) == (0, 0.0, None)

    def test_first_of_several_gold_sessions_sets_the_rank(self):
        assert hit_and_rank(["x", "g2", "g1"], {"g1", "g2"}, 5) == (1, 0.5, 2)

    def test_no_results_is_a_miss(self):
        assert hit_and_rank([], {"g"}, 5) == (0, 0.0, None)


class TestAggregates:
    def test_macro_recall_is_not_micro_recall(self):
        per_item = _six_items()
        micro = sum(s.hit for s in per_item.values()) / len(per_item)
        recall = recall_at_k(per_item)
        assert recall["by_stratum"] == pytest.approx({"K": 1.0, "P": 0.0, "R": 1 / 3})
        assert recall["macro"] == pytest.approx((1.0 + 0.0 + 1 / 3) / 3)
        assert micro == pytest.approx(0.5)
        assert recall["macro"] != pytest.approx(micro)

    def test_macro_mrr_averages_strata_of_reciprocal_ranks(self):
        mrr = mrr_at_k(_six_items())
        assert mrr["by_stratum"] == pytest.approx({"K": 0.75, "P": 0.0, "R": 0.2 / 3})
        assert mrr["macro"] == pytest.approx((0.75 + 0.0 + 0.2 / 3) / 3)

    def test_empty_input_is_zero_not_a_crash(self):
        assert macro_average({}, "hit") == {"by_stratum": {}, "macro": 0.0}

    def test_crashes_are_counted_by_kind_and_still_scored_as_misses(self):
        per_item = _six_items()
        per_item["x1"] = ItemScore("K", "c9", 0, 0.0, None, error_kind="backtick")
        per_item["x2"] = ItemScore("P", "c9", 0, 0.0, None, error_kind="backtick")
        per_item["x3"] = ItemScore("R", "c9", 0, 0.0, None, error_kind="question-mark")
        assert errors_by_kind(per_item) == {"backtick": 2, "question-mark": 1}
        assert crash_count(per_item) == 3
        # The crashed items are in the denominator: K drops from 1.0 to 2/3.
        assert recall_at_k(per_item)["by_stratum"]["K"] == pytest.approx(2 / 3)

    def test_latency_percentiles_use_the_ported_index_arithmetic(self):
        values = [float(n) for n in range(1, 101)]
        assert latency_percentiles(values) == {"p50": 51.0, "p95": 95.0}

    def test_latency_percentiles_of_nothing_are_zero(self):
        assert latency_percentiles([]) == {"p50": 0.0, "p95": 0.0}


def _paired(diffs: list[int], strata: list[str]) -> tuple[dict, dict, list[dict]]:
    """Build (a, b, items) where item i has hit difference ``diffs[i]``."""
    a: dict[str, ItemScore] = {}
    b: dict[str, ItemScore] = {}
    items: list[dict] = []
    for index, (diff, stratum) in enumerate(zip(diffs, strata, strict=True)):
        item_id = f"q{index}"
        a[item_id] = ItemScore(stratum, f"c{index}", diff, float(diff))
        b[item_id] = ItemScore(stratum, f"c{index}", 0, 0.0)
        items.append({"id": item_id, "cluster": f"c{index}", "stratum": stratum})
    return a, b, items


def _mixed_clusters() -> tuple[dict, dict, list[dict]]:
    """45 clusters of 1-3 items over three strata, with mixed per-item wins."""
    a: dict[str, ItemScore] = {}
    b: dict[str, ItemScore] = {}
    items: list[dict] = []
    index = 0
    for cluster in range(15):
        for stratum in ("K", "P", "R"):
            for position in range(1 + cluster % 3):
                item_id = f"q{index}"
                index += 1
                diff = 1 if (cluster + position) % 3 == 0 else 0
                a[item_id] = ItemScore(stratum, f"c{cluster}", diff, float(diff))
                b[item_id] = ItemScore(stratum, f"c{cluster}", 0, 0.0)
                items.append(
                    {"id": item_id, "cluster": f"c{cluster}", "stratum": stratum}
                )
    return a, b, items


class TestClusterBootstrap:
    def test_defaults_are_the_frozen_constants(self):
        a, b, items = _paired([1, 0], ["K", "K"])
        result = cluster_bootstrap(a, b, items, resamples=10)
        assert (RESAMPLES, SEED, MIN_LIFT) == (10_000, 20260910, 0.05)
        assert result["seed"] == SEED

    def test_the_same_seed_gives_an_identical_interval(self):
        diffs = [1, 0] * 12
        a, b, items = _paired(diffs, ["K"] * 24)
        first = cluster_bootstrap(a, b, items, resamples=1000, seed=SEED)
        second = cluster_bootstrap(a, b, items, resamples=1000, seed=SEED)
        assert first == second

    def test_the_seed_moves_the_interval_but_never_the_point(self):
        """Seed sensitivity, asserted over a sweep rather than one neighbour.

        The statistic is discrete (0/1 hits over 45 clusters), so two
        particular seeds can legitimately land on the same percentile. What
        must hold is that the interval depends on the seed *at all* while the
        point estimate -- which is not resampled -- does not.
        """
        a, b, items = _mixed_clusters()
        runs = {
            seed: cluster_bootstrap(a, b, items, resamples=1000, seed=seed)
            for seed in (SEED, SEED + 1, SEED + 2, SEED + 3, SEED + 4)
        }
        assert len({tuple(run["ci95"]) for run in runs.values()}) > 1
        assert len({run["point"] for run in runs.values()}) == 1

    def test_no_difference_is_not_an_established_lift(self):
        a, b, items = _paired([0, 0, 0, 0], ["K", "K", "P", "R"])
        result = cluster_bootstrap(a, b, items, resamples=200)
        assert result["point"] == 0.0
        assert result["ci95"] == [0.0, 0.0]
        assert result["established"] is False

    def test_a_uniform_win_is_established(self):
        a, b, items = _paired([1] * 6, ["K", "K", "P", "P", "R", "R"])
        result = cluster_bootstrap(a, b, items, resamples=200)
        assert result["point"] == 1.0
        assert result["established"] is True
        assert result["clusters"] == 6

    @pytest.mark.parametrize(
        ("cluster_size", "established"),
        # Every cluster contributes exactly one improved item, so every resample
        # yields the same macro delta: 1/20 = 0.05 (exactly the MIN_LIFT
        # boundary, which is inclusive) and 1/21 = 0.0476 (just under it).
        [(20, True), (21, False)],
    )
    def test_the_established_boundary_is_inclusive(self, cluster_size, established):
        a: dict[str, ItemScore] = {}
        b: dict[str, ItemScore] = {}
        items: list[dict] = []
        for cluster in range(20):
            for position in range(cluster_size):
                item_id = f"c{cluster}-{position}"
                hit = 1 if position == 0 else 0
                a[item_id] = ItemScore("K", f"c{cluster}", hit, float(hit))
                b[item_id] = ItemScore("K", f"c{cluster}", 0, 0.0)
                items.append({"id": item_id, "cluster": f"c{cluster}", "stratum": "K"})
        result = cluster_bootstrap(a, b, items, resamples=200)
        assert result["ci95"][0] == pytest.approx(1 / cluster_size)
        assert result["established"] is established


class TestNonInferiority:
    def test_the_frozen_margin_is_a_negative_floor_on_the_delta(self):
        assert NON_INFERIORITY_MARGIN == -0.01

    def test_an_identical_arm_is_non_inferior(self):
        a, b, items = _paired([0, 0, 0, 0], ["K", "K", "P", "R"])
        result = non_inferiority(a, b, items, resamples=200)
        assert result["ci95_lower"] == 0.0
        assert result["regression_upper95"] == 0.0
        assert result["non_inferior"] is True

    def test_a_uniform_regression_is_not_non_inferior(self):
        a, b, items = _paired([1] * 6, ["K", "K", "P", "P", "R", "R"])
        # b - a is a uniform regression of 1.0 in every stratum.
        result = non_inferiority(b, a, items, resamples=200)
        assert result["point"] == -1.0
        assert result["non_inferior"] is False
        assert result["margin"] == NON_INFERIORITY_MARGIN

    def test_one_stratum_can_be_scored_alone(self):
        a, b, items = _paired([1, 1, 0, 0], ["K", "K", "P", "P"])
        result = non_inferiority(a, b, items, stratum="P", resamples=100)
        assert result["stratum"] == "P"
        assert result["clusters"] == 2
        assert result["point"] == 0.0


# --------------------------------------------------------------------------- §5 additions
# precision@K (guardrail) and the value-based paired bootstrap the recall
# bootstrap now delegates to. The delegation is pinned against a COMMITTED
# receipt: the interval recorded at Stage 2 must be reproduced bit for bit from
# that receipt's own per-item rows, or the ruler has moved.

_STAGE2_RECEIPT = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/session-memory/receipts/semantic-layer/stage2-gold-v2.json"
)
_GOLD_DEV = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/session-memory/receipts/gold-v2-dev.json"
)


def _ranked_items() -> tuple[dict[str, ItemScore], list[dict]]:
    """Four items with ranked lists; gold ids chosen so precision is hand-computable."""
    per_item = {
        "k1": ItemScore("K", "c1", 1, 1.0, 1, ranked=("g1", "x", "y", "z", "w")),
        "k2": ItemScore("K", "c1", 1, 0.5, 2, ranked=("x", "g2a", "g2b")),
        "p1": ItemScore("P", "c2", 0, 0.0, None, ranked=("x", "y")),
        "r1": ItemScore(
            "R", "c3", 0, 0.0, None, ranked=()
        ),  # a crash or an empty answer
    }
    items = [
        {"id": "k1", "cluster": "c1", "stratum": "K", "gold_session_ids": ["g1"]},
        {
            "id": "k2",
            "cluster": "c1",
            "stratum": "K",
            "gold_session_ids": ["g2a", "g2b"],
        },
        {"id": "p1", "cluster": "c2", "stratum": "P", "gold_session_ids": ["g3"]},
        {"id": "r1", "cluster": "c3", "stratum": "R", "gold_session_ids": ["g4"]},
    ]
    return per_item, items


class TestPrecisionAtK:
    def test_per_item_precision_divides_by_k_not_by_what_came_back(self):
        per_item, items = _ranked_items()
        assert precision_values(per_item, items, 5) == {
            "k1": 1 / 5,
            "k2": 2 / 5,  # both gold sessions inside the first five
            "p1": 0.0,
            "r1": 0.0,  # nothing returned is precision 0, never undefined
        }

    def test_only_the_first_k_ranks_count(self):
        per_item, items = _ranked_items()
        assert precision_values(per_item, items, 1) == {
            "k1": 1.0,
            "k2": 0.0,
            "p1": 0.0,
            "r1": 0.0,
        }

    def test_macro_precision_averages_strata_not_items(self):
        per_item, items = _ranked_items()
        result = precision_at_k(per_item, items, 5)
        assert result["by_stratum"] == pytest.approx({"K": 0.3, "P": 0.0, "R": 0.0})
        assert result["macro"] == pytest.approx(0.1)

    def test_empty_input_is_zero_not_a_crash(self):
        assert precision_at_k({}, [], 5) == {"by_stratum": {}, "macro": 0.0}


class TestPairedClusterBootstrap:
    def test_it_is_the_recall_bootstrap_when_fed_hits(self):
        a, b, items = _mixed_clusters()
        hits_a = {i: float(s.hit) for i, s in a.items()}
        hits_b = {i: float(s.hit) for i, s in b.items()}
        values = paired_cluster_bootstrap(hits_a, hits_b, items, resamples=500)
        recall = cluster_bootstrap(a, b, items, resamples=500)
        assert values["point"] == recall["point"]
        assert values["ci95"] == recall["ci95"]
        assert values["clusters"] == recall["clusters"] == 15

    def test_lower_above_zero_is_strict_and_distinct_from_established(self):
        a, b, items = _paired([1, 0, 0, 0], ["K", "P", "R", "R"])
        values = paired_cluster_bootstrap(
            {i: float(s.hit) for i, s in a.items()},
            {i: float(s.hit) for i, s in b.items()},
            items,
            resamples=200,
        )
        # Resampling four one-item clusters can leave K out entirely: the
        # lower bound is exactly zero, which is NOT strictly above zero.
        assert values["ci95"][0] == 0.0
        assert values["lower_above_zero"] is False
        assert "established" not in values

    def test_no_clusters_is_zero_not_a_crash(self):
        values = paired_cluster_bootstrap({}, {}, [], resamples=10)
        assert values["point"] == 0.0
        assert values["ci95"] == [0.0, 0.0]
        assert values["clusters"] == 0

    @pytest.mark.skipif(
        not (_STAGE2_RECEIPT.exists() and _GOLD_DEV.exists()),
        reason="committed receipts not present in this checkout",
    )
    def test_it_reproduces_the_committed_stage2_intervals_bit_for_bit(self):
        """The bootstrap arithmetic is pinned to a receipt in the repository.

        Stage 2's ``mcp_vs_frozen`` interval (paired +0.052, CI95 [+0.011,
        +0.100]) is recomputed here from that receipt's own per-item rows with
        the frozen seed and resample count. Any drift in the draw order, the
        percentile arithmetic or the macro-over-strata fold shows up as an
        unequal float.
        """
        receipt = json.loads(_STAGE2_RECEIPT.read_text())
        gold = json.loads(_GOLD_DEV.read_text())["items"]

        def scores(arm: str) -> dict[str, ItemScore]:
            return {
                item_id: ItemScore(
                    row["stratum"], row["cluster"], row["hit"], row["rr"]
                )
                for item_id, row in receipt["arms"][arm]["per_item"].items()
            }

        for pair in ("mcp_vs_frozen", "frozen_vs_mcp"):
            a, b = pair.split("_vs_")
            fresh = cluster_bootstrap(scores(a), scores(b), gold)
            recorded = receipt["comparisons"][pair]
            assert fresh["point"] == recorded["point"], pair
            assert fresh["ci95"] == recorded["ci95"], pair
            assert fresh["established"] == recorded["established"], pair
