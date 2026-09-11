"""The gold ruler: the committed DEV set's identity, and how an arm is scored.

The sha256 and the counts are asserted literally. If the gold file changes,
this test fails -- which is the point: a ruler change must be a deliberate,
visible act, not a silently rescored receipt.
"""

from __future__ import annotations

import json

import pytest

from agent_session_tools.eval import K
from agent_session_tools.eval.gold import (
    GOLD_DEV_ITEMS,
    KNOWN_UNWINNABLE,
    default_gold_path,
    load_gold,
    score_arm,
)
from agent_session_tools.eval.seam import ArmError, Hit, Query

GOLD_DEV_SHA256 = "5632cd2b02a77dbd95ded3fae3aa32fa1599cd43929f43e44aa132343c3c6098"


class TestLoadGold:
    def test_the_committed_dev_set_has_the_recorded_digest_and_counts(self):
        gold = load_gold(require_items=GOLD_DEV_ITEMS)
        assert gold.path == default_gold_path()
        assert gold.sha256 == GOLD_DEV_SHA256
        assert gold.n == 91
        assert gold.strata == {"K": 33, "P": 29, "R": 29}
        assert gold.clusters == 57
        assert (gold.version, gold.name) == ("v2", "DEV")

    def test_the_three_known_unwinnable_items_are_in_the_set(self):
        gold = load_gold()
        ids = {item["id"] for item in gold.items}
        assert KNOWN_UNWINNABLE == {"A1-13", "A1-70", "A1-71"}
        assert KNOWN_UNWINNABLE <= ids

    def test_describe_is_the_receipt_block(self):
        described = load_gold().describe()
        assert described["sha256"] == GOLD_DEV_SHA256
        assert described["n"] == 91
        assert described["strata"] == {"K": 33, "P": 29, "R": 29}
        assert described["known_unwinnable"] == ["A1-13", "A1-70", "A1-71"]

    def test_an_unexpected_item_count_fails_closed(self):
        with pytest.raises(ValueError, match="expected 90 items, found 91"):
            load_gold(require_items=90)

    def test_a_malformed_item_is_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"items": [{"id": "x", "question": "q"}]}))
        with pytest.raises(ValueError, match="missing"):
            load_gold(path)

    def test_an_empty_set_is_rejected(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"items": []}))
        with pytest.raises(ValueError, match="no items"):
            load_gold(path)


class _ScriptedArm:
    """An arm whose answers (and crashes) are dictated by the test."""

    name = "scripted"
    supports_exclusion = False

    def __init__(self, answers: dict[str, list[str] | ArmError]) -> None:
        self.answers = answers

    def search(self, query: Query, k: int) -> list[Hit]:
        answer = self.answers[query.text]
        if isinstance(answer, ArmError):
            raise answer
        return [
            Hit(session_id, (f"m-{session_id}",), None, "scripted")
            for session_id in answer
        ][:k]

    def describe(self) -> dict[str, object]:
        return {"arm": self.name, "rows": 10}


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
        "stratum": "K",
        "cluster": "c1",
        "gold_session_ids": ["s2"],
    },
    {
        "id": "i3",
        "question": "q3",
        "stratum": "P",
        "cluster": "c2",
        "gold_session_ids": ["s3"],
    },
    {
        "id": "i4",
        "question": "q4",
        "stratum": "R",
        "cluster": "c3",
        "gold_session_ids": ["s4"],
    },
]


class TestScoreArm:
    @pytest.fixture
    def result(self):
        arm = _ScriptedArm(
            {
                "q1": ["s1", "sx"],  # hit at rank 1
                "q2": ["sx", "sy", "s2"],  # hit at rank 3
                "q3": ["sx"],  # miss
                "q4": ArmError(
                    "backtick", 'fts5: syntax error near "`"'
                ),  # crash = miss
            }
        )
        return score_arm(arm, ITEMS, K)

    def test_per_item_records_rank_hit_and_the_crash_kind(self, result):
        assert result.per_item["i1"].rank == 1
        assert result.per_item["i2"].rr == pytest.approx(1 / 3)
        assert result.per_item["i3"].hit == 0
        crashed = result.per_item["i4"]
        assert (crashed.hit, crashed.error_kind) == (0, "backtick")
        assert crashed.error is not None and "syntax error" in crashed.error

    def test_a_crash_is_a_miss_in_the_denominator_not_a_skip(self, result):
        assert len(result.per_item) == len(ITEMS)
        assert result.crashes == 1
        assert result.errors_by_kind == {"backtick": 1}
        assert result.recall["by_stratum"]["R"] == 0.0

    def test_macro_recall_and_mrr_are_hand_computable(self, result):
        assert result.recall["by_stratum"] == pytest.approx(
            {"K": 1.0, "P": 0.0, "R": 0.0}
        )
        assert result.recall["macro"] == pytest.approx(1 / 3)
        assert result.mrr["by_stratum"]["K"] == pytest.approx((1.0 + 1 / 3) / 2)

    def test_latency_and_config_are_recorded(self, result):
        assert set(result.latency_ms) == {"p50", "p95"}
        assert result.latency_ms["p50"] >= 0.0
        assert result.config == {"arm": "scripted", "rows": 10}

    def test_the_metrics_block_is_keyed_by_k(self, result):
        metrics = result.metrics()
        assert metrics[f"recall@{K}"]["macro"] == pytest.approx(1 / 3)
        assert metrics["crashes"] == 1
        assert metrics["n"] == 4

    def test_an_arm_that_escapes_the_seam_is_still_classified(self):
        class Escaping(_ScriptedArm):
            def search(self, query: Query, k: int) -> list[Hit]:
                if query.text == "q1":
                    raise RuntimeError("no such column: bogus")
                return []

        result = score_arm(Escaping({}), ITEMS, K)
        assert result.per_item["i1"].error_kind == "no-such-column"
        assert result.crashes == 1

    def test_k_bounds_the_ranks_that_can_hit(self):
        arm = _ScriptedArm(
            {
                "q1": ["a", "b", "c", "d", "e", "s1"],
                "q2": [],
                "q3": [],
                "q4": [],
            }
        )
        assert score_arm(arm, ITEMS, 5).per_item["i1"].hit == 0
        assert score_arm(arm, ITEMS, 6).per_item["i1"].hit == 1
