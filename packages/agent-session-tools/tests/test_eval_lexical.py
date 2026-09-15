"""§5 (D-12): the adopt/reject verdict is a function of the receipt, not of a reader.

Every clause is exercised in both directions on a synthetic receipt, the digest
prefixing is shown idempotent, and the ``lexical-verdict`` door of
``python -m agent_session_tools.eval`` is driven end to end on a temp receipt.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agent_session_tools.eval import __main__ as eval_main
from agent_session_tools.eval.lexical import (
    DEFAULT_CANDIDATE,
    DEFAULT_CONTROL,
    PRE_PLANNER_GOLDEN_RELATIVE,
    PRE_PLANNER_GOLDEN_SHA256,
    PRECISION_DROP_MAX,
    RULE,
    derive_receipt,
    explicit_door_holds,
    format_verdict,
    golden_sha256,
    judge,
    prefix_digests,
    repo_root,
)

_OR_FALLBACK_TESTS = Path(__file__).parent / "test_query_planner_or_fallback.py"
_PAIR = f"{DEFAULT_CANDIDATE}_vs_{DEFAULT_CONTROL}"

#: The preserved raw gold receipt of the 2026-09-15 DEV run (outside the
#: repository, as the pre-registration places it) and its registered digest.
_RAW_RECEIPT = Path(
    "~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/"
    "or-fallback-dev-2026-09-15.raw.json"
).expanduser()
_RAW_RECEIPT_SHA256 = "6b8c18095850e1cd253129af6d143a2be1b9407ce6938533117d4bd3e447b57d"  # pragma: allowlist secret
_COMMITTED_RECEIPT = (
    repo_root()
    / "docs/architecture/session-memory/receipts/lexical/or-fallback-dev-2026-09-15.json"
)


def _receipt(
    *,
    lower: float = 0.02,
    upper: float = 0.1,
    point: float = 0.06,
    control_precision: float = 0.05,
    candidate_precision: float = 0.04,
    candidate: str = DEFAULT_CANDIDATE,
    control: str = DEFAULT_CONTROL,
    candidate_crashes: int = 0,
    control_crashes: int = 0,
) -> dict[str, Any]:
    """A gold receipt with the two arms the verdict reads, and nothing it does not.

    ``*_crashes`` items are written the way :func:`eval.gold.score_arm` writes
    them -- an ``error_kind`` on the per-item row and the count in ``metrics``
    -- so the receipt stays internally consistent.
    """

    def arm(precision: float, crashes: int) -> dict[str, Any]:
        per_item: dict[str, Any] = {
            "q1": {"stratum": "K", "hit": 1, "ranked": ["s-1"], "error_kind": None}
        }
        for index in range(crashes):
            per_item[f"x{index}"] = {
                "stratum": "K",
                "hit": 0,
                "ranked": [],
                "error_kind": "backtick",
            }
        return {
            "config": {"git_commit": "a" * 40, "planner": "x"},
            "metrics": {
                "recall@5": {"macro": 0.2, "by_stratum": {"K": 0.2}},
                "precision@5": {"macro": precision, "by_stratum": {"K": precision}},
                "mrr@5": {"macro": 0.1, "by_stratum": {"K": 0.1}},
                "crashes": crashes,
                "n": len(per_item),
            },
            "per_item": per_item,
        }

    return {
        "schema": "studyloop.retrieval-eval/v1",
        "git_commit": "b" * 40,
        "db": {"path": "/x/sessions.db", "fingerprint": "c" * 64},
        "gold": {"sha256": "d" * 64, "n": 91},
        "arms": {
            control: arm(control_precision, control_crashes),
            candidate: arm(candidate_precision, candidate_crashes),
        },
        "comparisons": {
            f"{candidate}_vs_{control}": {
                "point": point,
                "ci95": [lower, upper],
                "resamples": 10_000,
                "seed": 20260910,
                "clusters": 57,
                "established": lower >= 0.05,
            }
        },
        "metrics_sha256": "e" * 64,
    }


class TestClauses:
    def test_all_four_holding_is_an_adopt(self):
        verdict = judge(_receipt())
        assert verdict["adopt"] is True
        assert verdict["decided_by"] == ["all four clauses hold"]
        assert verdict["rule"] == RULE
        assert all(clause["holds"] for clause in verdict["clauses"].values())

    def test_clause_1_needs_the_lower_bound_strictly_above_zero(self):
        touching = judge(_receipt(lower=0.0))
        assert touching["adopt"] is False
        assert touching["decided_by"] == ["1_recall_ci95_lower_above_zero"]
        assert touching["clauses"]["1_recall_ci95_lower_above_zero"]["ci95"] == [
            0.0,
            0.1,
        ]
        negative = judge(_receipt(lower=-0.03, point=0.01))
        assert negative["decided_by"] == ["1_recall_ci95_lower_above_zero"]

    def test_clause_1_reports_the_programmes_stronger_rule_beside_d12s(self):
        weak = judge(_receipt(lower=0.02))["clauses"]["1_recall_ci95_lower_above_zero"]
        assert weak["holds"] is True
        assert weak["established_lift_at_min_lift"] is False
        strong = judge(_receipt(lower=0.06))["clauses"][
            "1_recall_ci95_lower_above_zero"
        ]
        assert strong["established_lift_at_min_lift"] is True

    def test_clause_2_is_an_absolute_precision_drop_with_an_inclusive_bound(self):
        assert PRECISION_DROP_MAX == 0.05
        at_bound = judge(_receipt(control_precision=0.10, candidate_precision=0.05))
        assert at_bound["clauses"]["2_precision_drop_at_most_0.05"]["holds"] is True
        assert at_bound["adopt"] is True
        over = judge(_receipt(control_precision=0.10, candidate_precision=0.04))
        assert over["adopt"] is False
        assert over["decided_by"] == ["2_precision_drop_at_most_0.05"]
        assert over["clauses"]["2_precision_drop_at_most_0.05"][
            "drop"
        ] == pytest.approx(0.06)
        # A precision GAIN is a negative drop and always within bound.
        gain = judge(_receipt(control_precision=0.04, candidate_precision=0.10))
        assert gain["clauses"]["2_precision_drop_at_most_0.05"]["holds"] is True

    def test_clause_3_re_evaluates_the_explicit_door_on_the_live_planner(self):
        door = explicit_door_holds()
        assert door == {
            "fts_prefix_is_verbatim": True,
            "uppercase_operator_outside_quotes_is_verbatim": True,
            "quoted_operator_is_not_explicit": True,
        }
        assert (
            judge(_receipt())["clauses"]["3_explicit_door_tests_pass"]["holds"] is True
        )

    def test_clause_4_compares_the_golden_digest_under_the_given_root(self, tmp_path):
        moved = tmp_path / PRE_PLANNER_GOLDEN_RELATIVE
        moved.parent.mkdir(parents=True)
        moved.write_bytes(b"{}")
        verdict = judge(_receipt(), root=tmp_path)
        assert verdict["adopt"] is False
        assert verdict["decided_by"] == ["4_pre_planner_golden_unchanged"]
        clause = verdict["clauses"]["4_pre_planner_golden_unchanged"]
        assert clause["expected"] == f"sha256:{PRE_PLANNER_GOLDEN_SHA256}"
        assert clause["actual"] == f"sha256:{hashlib.sha256(b'{}').hexdigest()}"

    def test_clause_4_holds_on_this_checkout(self):
        assert golden_sha256() == PRE_PLANNER_GOLDEN_SHA256
        assert (repo_root() / PRE_PLANNER_GOLDEN_RELATIVE).is_file()

    def test_the_test_suites_pin_is_the_same_digest(self):
        """The S.1 test file carries the digest as a literal; the two may never drift."""
        assert PRE_PLANNER_GOLDEN_SHA256 in _OR_FALLBACK_TESTS.read_text()

    def test_every_failing_clause_is_named(self):
        verdict = judge(
            _receipt(lower=-0.1, control_precision=0.3, candidate_precision=0.1)
        )
        assert verdict["adopt"] is False
        assert verdict["decided_by"] == [
            "1_recall_ci95_lower_above_zero",
            "2_precision_drop_at_most_0.05",
        ]

    def test_a_missing_arm_is_an_error_not_a_reject(self):
        receipt = _receipt()
        del receipt["arms"][DEFAULT_CANDIDATE]
        with pytest.raises(KeyError, match="not in the receipt"):
            judge(receipt)


class TestEligibilityAndFailClosed:
    """The pre-registration's prose, encoded (council review, 2026-09-15).

    "Crashes appeared" and "a different arm won" are a reject *before* the
    four frozen clauses are read; they are named in ``decided_by`` and never
    renumber the clauses. A malformed receipt -- a non-finite number, a
    reversed interval, a crash count its own rows contradict -- is refused
    outright, the way a missing arm already is: an error, never a verdict.
    """

    def test_judge_zero_lower_bound_rejects(self):
        touching = judge(_receipt(lower=0.0))
        assert touching["adopt"] is False
        assert touching["decided_by"] == ["1_recall_ci95_lower_above_zero"]
        assert touching["clauses"]["1_recall_ci95_lower_above_zero"]["holds"] is False
        # The bound is strict, not fuzzy: the smallest positive lower bound adopts.
        assert judge(_receipt(lower=1e-12))["adopt"] is True

    def test_judge_precision_boundary_is_inclusive(self):
        at_bound = judge(_receipt(control_precision=0.10, candidate_precision=0.05))
        clause = at_bound["clauses"]["2_precision_drop_at_most_0.05"]
        assert clause["drop"] == PRECISION_DROP_MAX
        assert clause["holds"] is True
        assert at_bound["adopt"] is True
        just_over = judge(
            _receipt(control_precision=0.10, candidate_precision=0.05 - 1e-9)
        )
        assert just_over["adopt"] is False
        assert just_over["decided_by"] == ["2_precision_drop_at_most_0.05"]

    def test_judge_rejects_wrong_registered_pair(self):
        """The rule registers one pair; any other is compared but never adopted."""
        exploratory = "mcp:or_first_filtered"
        verdict = judge(
            _receipt(candidate=exploratory), candidate=exploratory, control="mcp"
        )
        # The generic comparison is still computed and readable ...
        assert all(clause["holds"] for clause in verdict["clauses"].values())
        assert verdict["candidate"] == exploratory
        # ... but the registered verdict is withheld, and says why.
        assert verdict["adopt"] is False
        assert len(verdict["decided_by"]) == 1
        assert verdict["decided_by"][0].startswith("eligibility:registered_pair")
        assert DEFAULT_CANDIDATE in verdict["decided_by"][0]
        # The registered pair read backwards is not the registered pair.
        swapped = judge(
            _receipt(candidate=DEFAULT_CONTROL, control=DEFAULT_CANDIDATE),
            candidate=DEFAULT_CONTROL,
            control=DEFAULT_CANDIDATE,
        )
        assert swapped["adopt"] is False
        assert swapped["decided_by"][0].startswith("eligibility:registered_pair")
        # The same numbers on the registered pair adopt.
        assert judge(_receipt())["adopt"] is True

    def test_judge_rejects_crashes_under_frozen_rule(self):
        """'Crashes appeared' is a reject even when all four clauses hold."""
        crashed = judge(_receipt(candidate_crashes=1))
        assert all(clause["holds"] for clause in crashed["clauses"].values())
        assert crashed["adopt"] is False
        assert crashed["decided_by"] == [
            f"eligibility:no_crashes ({DEFAULT_CANDIDATE} crashed on 1 item)"
        ]
        # A crashing control is no basis for an adopt either: its recall is
        # artificially low, which would flatter the candidate's delta.
        control_crashed = judge(_receipt(control_crashes=2))
        assert control_crashed["adopt"] is False
        assert control_crashed["decided_by"] == [
            f"eligibility:no_crashes ({DEFAULT_CONTROL} crashed on 2 items)"
        ]
        # Ineligibility is named ahead of any failed clause; the clauses keep
        # their names and numbers.
        both = judge(_receipt(lower=-0.01, candidate_crashes=1))
        assert both["decided_by"][0].startswith("eligibility:no_crashes")
        assert both["decided_by"][1] == "1_recall_ci95_lower_above_zero"
        assert list(both["clauses"]) == [
            "1_recall_ci95_lower_above_zero",
            "2_precision_drop_at_most_0.05",
            "3_explicit_door_tests_pass",
            "4_pre_planner_golden_unchanged",
        ]
        # An eligible receipt's verdict is exactly what it was.
        assert judge(_receipt())["decided_by"] == ["all four clauses hold"]
        # A crash count the per-item rows contradict is a malformed receipt.
        inconsistent = _receipt()
        inconsistent["arms"][DEFAULT_CANDIDATE]["metrics"]["crashes"] = 2
        with pytest.raises(ValueError, match="crashes"):
            judge(inconsistent)
        negative = _receipt()
        negative["arms"][DEFAULT_CONTROL]["metrics"]["crashes"] = -1
        with pytest.raises(ValueError, match="crashes"):
            judge(negative)

    @pytest.mark.parametrize(
        "ci95",
        [
            [float("inf"), float("inf")],  # +inf > 0 would otherwise "hold"
            [float("nan"), 0.1],
            [0.02, float("nan")],
            [0.1, 0.02],  # reversed
            [0.02],  # not an interval
            [0.02, 0.1, 0.2],
            ["0.02", "0.1"],  # strings that happen to parse are still not numbers
            None,
        ],
    )
    def test_judge_rejects_nonfinite_or_reversed_ci(self, ci95):
        broken = _receipt()
        broken["comparisons"][_PAIR]["ci95"] = ci95
        with pytest.raises(ValueError, match="ci95"):
            judge(broken)

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_judge_rejects_nonfinite_point_and_precision(self, value):
        broken_point = _receipt()
        broken_point["comparisons"][_PAIR]["point"] = value
        with pytest.raises(ValueError, match="point"):
            judge(broken_point)
        broken_precision = _receipt()
        broken_precision["arms"][DEFAULT_CANDIDATE]["metrics"]["precision@5"][
            "macro"
        ] = value
        with pytest.raises(ValueError, match="precision@5"):
            judge(broken_precision)

    def test_format_verdict_names_the_ineligibility(self):
        text = format_verdict(judge(_receipt(candidate_crashes=1)))
        assert text.splitlines()[-1] == "adopt: false"
        assert "decided_by: eligibility:no_crashes" in text
        # Every clause line still prints HOLDS: the reject came from eligibility.
        assert "FAILS" not in text


class TestFrozenReceiptReproduction:
    """The 2026-09-15 DEV verdict is a function of the raw receipt, re-derived here.

    The registered ``lexical-verdict`` command is re-run against the preserved
    raw receipt into a temporary path and compared byte for byte with the
    committed receipt: the eligibility checks added after the council review
    must leave an eligible receipt's verdict exactly as it was.
    """

    @pytest.mark.skipif(
        not (_RAW_RECEIPT.is_file() and _COMMITTED_RECEIPT.is_file()),
        reason="the preserved raw receipt lives outside the repository",
    )
    def test_lexical_verdict_reproduces_the_committed_receipt_byte_for_byte(
        self, tmp_path, capsys
    ):
        if hashlib.sha256(_RAW_RECEIPT.read_bytes()).hexdigest() != _RAW_RECEIPT_SHA256:
            pytest.skip(
                "the file at the preserved path is not the registered raw receipt"
            )
        out_path = tmp_path / "rederived.json"
        code = eval_main.main(
            [
                "lexical-verdict",
                "--receipt",
                str(_RAW_RECEIPT),
                "--candidate",
                DEFAULT_CANDIDATE,
                "--control",
                DEFAULT_CONTROL,
                "--out",
                str(out_path),
            ]
        )
        assert code == 0
        assert out_path.read_bytes() == _COMMITTED_RECEIPT.read_bytes()
        printed = capsys.readouterr().out
        assert "decided_by: 1_recall_ci95_lower_above_zero" in printed
        assert printed.splitlines()[-2] == "adopt: false"
        derived = json.loads(out_path.read_text())
        assert derived["verdict"]["clauses"]["1_recall_ci95_lower_above_zero"][
            "ci95"
        ] == [-0.049955791335101675, 0.027777777777777776]
        assert (
            derived["verdict"]["clauses"]["1_recall_ci95_lower_above_zero"]["point"]
            == -0.010101010101010102
        )


class TestDerivedReceipt:
    def test_digests_are_prefixed_recursively_and_idempotently(self):
        raw = _receipt()
        once = prefix_digests(raw)
        assert once["git_commit"] == "git:" + "b" * 40
        assert once["db"]["fingerprint"] == "sha256:" + "c" * 64
        assert once["gold"]["sha256"] == "sha256:" + "d" * 64
        assert once["metrics_sha256"] == "sha256:" + "e" * 64
        assert (
            once["arms"][DEFAULT_CONTROL]["config"]["git_commit"] == "git:" + "a" * 40
        )
        assert prefix_digests(once) == once
        # Nothing else moved.
        assert (
            once["arms"][DEFAULT_CONTROL]["per_item"]
            == raw["arms"][DEFAULT_CONTROL]["per_item"]
        )
        assert once["comparisons"] == raw["comparisons"]

    def test_the_raw_receipt_is_not_mutated(self):
        raw = _receipt()
        snapshot = copy.deepcopy(raw)
        derive_receipt(raw, b"raw-bytes", judge(raw), raw_path="/tmp/raw.json")
        assert raw == snapshot

    def test_derived_carries_provenance_and_the_verdict(self):
        raw = _receipt()
        verdict = judge(raw)
        derived = derive_receipt(raw, b"raw-bytes", verdict, raw_path="/tmp/raw.json")
        assert derived["verdict"] == verdict
        assert derived["derived_from"]["raw_receipt"] == "/tmp/raw.json"
        assert (
            derived["derived_from"]["raw_sha256"]
            == "sha256:" + hashlib.sha256(b"raw-bytes").hexdigest()
        )
        assert derived["metrics_sha256"] == "sha256:" + "e" * 64

    def test_no_bare_hex_string_survives_in_the_derived_json(self):
        """What the detect-secrets hook flags: a quoted string that is nothing but hex."""
        import re

        derived = derive_receipt(_receipt(), b"x", judge(_receipt()), raw_path="r")
        text = json.dumps(derived)
        bare = [s for s in re.findall(r'"([a-fA-F0-9]{12,})"', text)]
        assert bare == []

    def test_format_verdict_ends_with_the_adopt_line(self):
        text = format_verdict(judge(_receipt(lower=0.0)))
        assert text.splitlines()[-1] == "adopt: false"
        assert "1_recall_ci95_lower_above_zero: FAILS" in text
        assert "decided_by: 1_recall_ci95_lower_above_zero" in text


class TestCommandDoor:
    def test_lexical_verdict_writes_the_derived_receipt_and_prints_the_verdict(
        self, tmp_path, capsys
    ):
        raw_path = tmp_path / "raw.json"
        raw_path.write_text(json.dumps(_receipt(), sort_keys=True))
        out_path = tmp_path / "derived.json"
        code = eval_main.main(
            ["lexical-verdict", "--receipt", str(raw_path), "--out", str(out_path)]
        )
        assert code == 0
        printed = capsys.readouterr().out
        assert "adopt: true" in printed
        assert "decided_by: all four clauses hold" in printed
        derived = json.loads(out_path.read_text())
        assert derived["verdict"]["adopt"] is True
        assert derived["verdict"]["candidate"] == DEFAULT_CANDIDATE
        assert derived["gold"]["sha256"].startswith("sha256:")
        assert derived["derived_from"]["raw_sha256"] == (
            "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()
        )
