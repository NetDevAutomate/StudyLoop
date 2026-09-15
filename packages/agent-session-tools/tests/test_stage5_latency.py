"""Gate L's measurement arithmetic: the bootstrap bound, the verdicts, the schema.

Every number here is hand-computed in the test body or derived from a fixture
recorded in the file, so a change in
:mod:`agent_session_tools.eval.stage5_latency` cannot quietly redefine the
gate. Nothing in this file loads a model, opens a socket, touches the real
clone or starts a process: the parent aggregation is exercised against a
recorded fixture of child reports, which is exactly the seam the runner is
built around.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_session_tools.eval.metrics import latency_percentiles
from agent_session_tools.eval.stage5_latency import (
    BOOTSTRAP_RESAMPLES,
    CHILD_SCHEMA,
    DEFAULT_CELLS,
    DEFAULT_REQUESTS,
    DEFAULT_SEED,
    DEFAULT_STARTS,
    GATE_FIRST_QUERY_P95_MS,
    GATE_OVERHEAD_P95_MS,
    GATE_P95_MS,
    SCHEMA,
    WORKLOAD_NAME,
    Cell,
    ChildReport,
    FirstQuery,
    Timing,
    WarmReport,
    aggregate_cell,
    bootstrap_p95_upper_bound,
    build_stage5_receipt,
    cell_verdict,
    leg_schedule,
    overall_verdict,
    p95,
    parse_cells,
    preflight_reasons,
    workload_plan,
)


class TestFrozenConstants:
    def test_the_defaults_are_the_pre_registered_design(self):
        assert (DEFAULT_STARTS, DEFAULT_REQUESTS) == (30, 100)
        assert [cell.name for cell in DEFAULT_CELLS] == [
            "c1-idle",
            "c1-load",
            "c4-idle",
            "c4-load",
        ]
        assert (GATE_P95_MS, GATE_OVERHEAD_P95_MS, GATE_FIRST_QUERY_P95_MS) == (
            200.0,
            100.0,
            3500.0,
        )
        assert BOOTSTRAP_RESAMPLES == 2000

    def test_the_background_workload_is_named_and_repeatable(self):
        assert WORKLOAD_NAME == "spin-half-cores"
        plan = workload_plan(cores=16)
        assert plan["name"] == WORKLOAD_NAME
        assert plan["processes"] == 8
        assert plan["cores"] == 16
        # A one-core machine still gets one spinner, never zero.
        assert workload_plan(cores=1)["processes"] == 1

    def test_cells_round_trip_through_their_flag_spelling(self):
        assert parse_cells("1:idle,4:load") == (
            Cell(concurrency=1, workload="idle"),
            Cell(concurrency=4, workload="load"),
        )
        assert parse_cells("1:idle")[0].name == "c1-idle"
        with pytest.raises(ValueError, match="unknown workload"):
            parse_cells("1:thermal")
        with pytest.raises(ValueError, match="concurrency"):
            parse_cells("nine:idle")


class TestPreflight:
    """Refuse before the run, not after 120 starts of measuring lexical twice."""

    def test_a_ready_machine_has_nothing_to_report(self):
        assert (
            preflight_reasons(
                extension=(True, ""), model=(True, ""), pin_model="bge-small-en-v1.5"
            )
            == []
        )

    def test_a_missing_extension_is_named_with_its_install_hint(self):
        reasons = preflight_reasons(
            extension=(False, "sqlite-vec is not installed; install: ..."),
            model=(True, ""),
            pin_model="bge-small-en-v1.5",
        )
        assert reasons == ["sqlite-vec is not installed; install: ..."]

    def test_a_missing_model_is_named_too(self):
        reasons = preflight_reasons(
            extension=(True, ""),
            model=(False, "model bge-small-en-v1.5 is not in the HF cache"),
            pin_model="bge-small-en-v1.5",
        )
        assert reasons == ["model bge-small-en-v1.5 is not in the HF cache"]

    def test_both_are_reported_together_rather_than_one_at_a_time(self):
        reasons = preflight_reasons(
            extension=(False, "no vec"), model=(False, "no model"), pin_model="m"
        )
        assert reasons == ["no vec", "no model"]

    def test_a_probe_that_failed_without_a_reason_still_refuses(self):
        reasons = preflight_reasons(
            extension=(False, ""), model=(True, ""), pin_model="m"
        )
        assert reasons == ["the sqlite-vec extension is unavailable"]


class TestPercentile:
    def test_p95_is_the_repo_s_ported_index_arithmetic(self):
        values = [float(n) for n in range(1, 101)]
        assert p95(values) == 95.0
        assert p95(values) == latency_percentiles(values)["p95"]

    def test_p95_of_nothing_is_zero(self):
        assert p95([]) == 0.0


class TestBootstrapUpperBound:
    def test_two_single_value_starts_give_a_hand_computed_bound(self):
        """The whole bound, computed by hand, on the smallest interesting case.

        Two starts, one request each: ``a`` at 10 ms and ``b`` at 100 ms. A
        resample draws two starts with replacement and pools them, so the
        pooled p95 of two values is ``sorted[max(int(2*0.95)-1, 0)] ==
        sorted[0]`` -- the *smaller* value. That is 100 only when both draws
        are ``b`` (probability 1/4), so the 95th percentile of the 2000 draws
        is 100.0 while the point estimate stays 10.0.
        """
        result = bootstrap_p95_upper_bound(
            {"a": [10.0], "b": [100.0]}, resamples=2000, seed=DEFAULT_SEED
        )
        assert result["point_p95_ms"] == 10.0
        assert result["ub95_p95_ms"] == 100.0
        assert result["starts"] == 2
        assert result["n"] == 2
        assert result["resamples"] == 2000
        assert result["seed"] == DEFAULT_SEED
        assert result["one_sided"] == 0.95

    def test_identical_starts_leave_no_room_between_point_and_bound(self):
        values = [float(n) for n in range(1, 101)]
        by_start = {f"s{index}": list(values) for index in range(5)}
        result = bootstrap_p95_upper_bound(by_start, resamples=500, seed=DEFAULT_SEED)
        assert result["point_p95_ms"] == 95.0
        assert result["ub95_p95_ms"] == 95.0

    def test_the_bound_is_never_below_the_point(self):
        by_start = {
            "fast": [float(n) for n in range(1, 51)],
            "middling": [float(n) for n in range(20, 70)],
            "slow": [float(n) for n in range(90, 140)],
        }
        result = bootstrap_p95_upper_bound(by_start, resamples=500, seed=DEFAULT_SEED)
        assert result["ub95_p95_ms"] >= result["point_p95_ms"]

    def test_one_slow_start_raises_the_bound(self):
        base = {f"s{index}": [10.0] * 20 for index in range(10)}
        before = bootstrap_p95_upper_bound(base, resamples=500, seed=DEFAULT_SEED)
        base["s-slow"] = [900.0] * 20
        after = bootstrap_p95_upper_bound(base, resamples=500, seed=DEFAULT_SEED)
        assert after["ub95_p95_ms"] > before["ub95_p95_ms"]

    def test_the_same_seed_is_the_same_bound_and_the_point_ignores_the_seed(self):
        by_start = {f"s{i}": [float(i * 3 + n) for n in range(30)] for i in range(12)}
        first = bootstrap_p95_upper_bound(by_start, resamples=400, seed=DEFAULT_SEED)
        second = bootstrap_p95_upper_bound(by_start, resamples=400, seed=DEFAULT_SEED)
        assert first == second
        bounds = {
            bootstrap_p95_upper_bound(by_start, resamples=400, seed=seed)["ub95_p95_ms"]
            for seed in range(DEFAULT_SEED, DEFAULT_SEED + 6)
        }
        points = {
            bootstrap_p95_upper_bound(by_start, resamples=400, seed=seed)[
                "point_p95_ms"
            ]
            for seed in range(DEFAULT_SEED, DEFAULT_SEED + 6)
        }
        assert len(bounds) > 1
        assert len(points) == 1

    def test_no_starts_is_zeros_not_a_crash(self):
        result = bootstrap_p95_upper_bound({}, resamples=10, seed=1)
        assert result["point_p95_ms"] == 0.0
        assert result["ub95_p95_ms"] == 0.0
        assert result["starts"] == 0


class TestCellVerdict:
    @pytest.mark.parametrize(
        ("ub95", "overhead", "first_query", "expected"),
        [
            (150.0, 40.0, 1200.0, True),
            (200.0, 100.0, 3500.0, True),  # every bound is inclusive
            (200.1, 40.0, 1200.0, False),  # wall bound blown
            (150.0, 100.1, 1200.0, False),  # paired overhead blown
            (150.0, 40.0, 3500.1, False),  # startup race blown
            (900.0, 900.0, 9000.0, False),  # everything blown
        ],
    )
    def test_the_truth_table(self, ub95, overhead, first_query, expected):
        verdict = cell_verdict(
            ub95_p95_ms=ub95,
            overhead_p95_ms=overhead,
            first_query_p95_ms=first_query,
        )
        assert verdict["pass"] is expected
        assert set(verdict["checks"]) == {
            "ub95_p95_ms",
            "overhead_p95_ms",
            "first_query_p95_ms",
            "hybrid_answered",
        }
        assert verdict["checks"]["ub95_p95_ms"]["threshold_ms"] == GATE_P95_MS
        assert verdict["checks"]["overhead_p95_ms"]["threshold_ms"] == (
            GATE_OVERHEAD_P95_MS
        )
        assert verdict["checks"]["first_query_p95_ms"]["threshold_ms"] == (
            GATE_FIRST_QUERY_P95_MS
        )

    def test_a_named_failure_reason_says_which_check_failed(self):
        verdict = cell_verdict(
            ub95_p95_ms=250.0, overhead_p95_ms=40.0, first_query_p95_ms=100.0
        )
        assert verdict["failed_checks"] == ["ub95_p95_ms"]

    def test_a_cell_where_hybrid_never_ran_cannot_pass(self):
        """The trap this check exists for, met on the first smoke run.

        Without ``sqlite-vec`` installed the semantic arm cannot run, so every
        hybrid request degrades to lexical, the paired overhead collapses to a
        few milliseconds and the cell reports a comfortable PASS -- for a
        measurement in which the thing being gated never executed once. A gate
        that can be passed by not running the feature is not a gate.
        """
        verdict = cell_verdict(
            ub95_p95_ms=44.0,
            overhead_p95_ms=3.2,
            first_query_p95_ms=800.0,
            hybrid_answered=0,
        )
        assert verdict["pass"] is False
        assert verdict["failed_checks"] == ["hybrid_answered"]
        assert verdict["checks"]["hybrid_answered"]["value"] == 0

    def test_one_genuine_hybrid_answer_satisfies_the_guard(self):
        verdict = cell_verdict(
            ub95_p95_ms=44.0,
            overhead_p95_ms=3.2,
            first_query_p95_ms=800.0,
            hybrid_answered=1,
        )
        assert verdict["pass"] is True


class TestOverallVerdict:
    def test_all_passing_cells_pass(self):
        cells = {
            "c1-idle": {"verdict": {"pass": True, "failed_checks": []}},
            "c4-load": {"verdict": {"pass": True, "failed_checks": []}},
        }
        overall = overall_verdict(cells)
        assert overall["pass"] is True
        assert overall["failing_cells"] == []

    def test_one_failing_cell_fails_the_gate_and_is_never_pooled_away(self):
        cells = {
            "c1-idle": {"verdict": {"pass": True, "failed_checks": []}},
            "c1-load": {"verdict": {"pass": True, "failed_checks": []}},
            "c4-idle": {"verdict": {"pass": True, "failed_checks": []}},
            # Three cells comfortably inside the gate cannot buy the fourth.
            "c4-load": {"verdict": {"pass": False, "failed_checks": ["ub95_p95_ms"]}},
        }
        overall = overall_verdict(cells)
        assert overall["pass"] is False
        assert overall["failing_cells"] == ["c4-load"]
        assert overall["cells_reported"] == 4
        assert "no pooling" in overall["rule"]

    def test_no_cells_at_all_is_a_failure_not_a_pass(self):
        overall = overall_verdict({})
        assert overall["pass"] is False


class TestLegSchedule:
    def test_every_request_is_timed_in_both_legs(self):
        batches = leg_schedule(requests=10, concurrency=1)
        assert [len(batch.pair_indices) for batch in batches] == [1] * 10
        assert all(set(batch.legs) == {"hybrid", "lexical"} for batch in batches)
        pairs = [index for batch in batches for index in batch.pair_indices]
        assert pairs == list(range(10))

    def test_concurrency_four_batches_four_at_a_time_with_a_short_tail(self):
        batches = leg_schedule(requests=10, concurrency=4)
        assert [len(batch.pair_indices) for batch in batches] == [4, 4, 2]
        assert batches[0].pair_indices == (0, 1, 2, 3)
        assert batches[-1].pair_indices == (8, 9)

    def test_the_leg_order_alternates_so_neither_leg_is_always_first(self):
        batches = leg_schedule(requests=8, concurrency=1)
        assert [batch.legs[0] for batch in batches] == [
            "hybrid",
            "lexical",
        ] * 4

    def test_no_requests_is_no_batches(self):
        assert leg_schedule(requests=0, concurrency=4) == ()


def _timing(pair_index: int, leg: str, wall_ms: float, mode: str | None) -> Timing:
    return Timing(
        pair_index=pair_index,
        leg=leg,
        query_id=f"A1-{pair_index}",
        wall_ms=wall_ms,
        mode=mode,
        rows=10,
        error=None,
    )


def _report(
    start_index: int,
    *,
    concurrency: int = 1,
    workload: str = "idle",
    hybrid: list[float],
    lexical: list[float],
    first_query_ms: float = 1200.0,
    first_query_mode: str | None = "hybrid",
    first_query_status: str = "ok",
) -> ChildReport:
    timings: list[Timing] = []
    for pair_index, (hybrid_ms, lexical_ms) in enumerate(
        zip(hybrid, lexical, strict=True)
    ):
        timings.append(_timing(pair_index, "hybrid", hybrid_ms, "hybrid"))
        timings.append(_timing(pair_index, "lexical", lexical_ms, "lexical"))
    return ChildReport(
        schema=CHILD_SCHEMA,
        start_index=start_index,
        concurrency=concurrency,
        workload=workload,
        requests=len(hybrid),
        first_query=FirstQuery(
            wall_ms=first_query_ms - 40.0,
            since_spawn_ms=first_query_ms,
            mode=first_query_mode,
            status=first_query_status,
            error=None,
            rows=10,
            warm_state_at_issue="warming",
        ),
        warm=WarmReport(
            state="warm",
            model="bge-small-en-v1.5",
            load_elapsed_ms=900.0,
            wait_ms=910.0,
            discarded_query_ms=70.0,
            detail="",
        ),
        timings=tuple(timings),
        environment={"git_commit": "abc1234", "backend": "torch"},
        elapsed_ms=5000.0,
    )


@pytest.fixture
def recorded_children() -> list[ChildReport]:
    """Six recorded starts of five paired requests -- the parent's only input.

    Start ``5`` is deliberately the slow one: it is what makes the clustered
    bootstrap's upper bound sit above the pooled point estimate, which is the
    whole reason the pre-registration clusters by start.
    """
    reports = []
    for start_index in range(5):
        base = 40.0 + start_index
        reports.append(
            _report(
                start_index,
                hybrid=[base + n for n in range(5)],
                lexical=[base - 10.0 + n for n in range(5)],
                first_query_ms=1000.0 + 50.0 * start_index,
            )
        )
    reports.append(
        _report(
            5,
            hybrid=[300.0, 310.0, 320.0, 330.0, 340.0],
            lexical=[100.0, 101.0, 102.0, 103.0, 104.0],
            first_query_ms=3100.0,
            first_query_mode="lexical",  # degraded: the warm lost the race
        )
    )
    return reports


class TestChildSchema:
    def test_a_child_report_round_trips_through_its_json_shape(self, recorded_children):
        original = recorded_children[0]
        restored = ChildReport.from_dict(original.to_dict())
        assert restored == original
        assert original.to_dict()["schema"] == CHILD_SCHEMA
        assert set(original.to_dict()) == {
            "schema",
            "start_index",
            "concurrency",
            "workload",
            "requests",
            "first_query",
            "warm",
            "timings",
            "environment",
            "elapsed_ms",
        }

    def test_the_json_shape_is_plain_data(self, recorded_children):
        import json

        payload = recorded_children[0].to_dict()
        assert json.loads(json.dumps(payload)) == payload

    def test_a_report_from_another_schema_is_refused(self, recorded_children):
        payload = recorded_children[0].to_dict()
        payload["schema"] = "studyloop.stage5-latency-child/v0"
        with pytest.raises(ValueError, match="schema"):
            ChildReport.from_dict(payload)

    def test_a_missing_block_is_refused_rather_than_defaulted(self, recorded_children):
        payload = recorded_children[0].to_dict()
        del payload["first_query"]
        with pytest.raises(ValueError, match="first_query"):
            ChildReport.from_dict(payload)


class TestAggregateCell:
    def test_it_aggregates_recorded_children_without_starting_a_process(
        self, recorded_children
    ):
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"),
            recorded_children,
            resamples=500,
            seed=DEFAULT_SEED,
        )
        assert cell["cell"] == "c1-idle"
        assert cell["starts"] == 6
        assert cell["requests_per_start"] == [5] * 6
        # Pooled hybrid p95 over 30 values, by the repo's index arithmetic.
        pooled = sorted(
            timing.wall_ms
            for report in recorded_children
            for timing in report.timings
            if timing.leg == "hybrid"
        )
        assert cell["hybrid"]["point_p95_ms"] == pooled[int(30 * 0.95) - 1]
        assert cell["hybrid"]["ub95_p95_ms"] >= cell["hybrid"]["point_p95_ms"]
        assert cell["lexical"]["point_p95_ms"] > 0.0

    def test_the_overhead_is_paired_per_request_not_a_difference_of_p95s(self):
        """Two starts chosen so the paired answer and the naive one differ.

        Both starts answer hybrid in 100 ms. One is lexically fast (90 ms, so
        10 ms of overhead), the other lexically very fast (20 ms, so 80 ms of
        overhead). Pooled hybrid p95 is 100 and pooled lexical p95 is 90, so
        *differencing the two p95s* claims 10 ms of overhead -- while the p95 of
        the twenty paired differences is 80 ms. Only the paired figure is the
        one the pre-registration gates on.
        """
        reports = [
            _report(0, hybrid=[100.0] * 10, lexical=[90.0] * 10),
            _report(1, hybrid=[100.0] * 10, lexical=[20.0] * 10),
        ]
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"), reports, resamples=200, seed=1
        )
        assert cell["hybrid"]["point_p95_ms"] == 100.0
        assert cell["lexical"]["point_p95_ms"] == 90.0
        assert cell["overhead"]["point_p95_ms"] == 80.0
        naive = cell["hybrid"]["point_p95_ms"] - cell["lexical"]["point_p95_ms"]
        assert naive == 10.0
        assert cell["overhead"]["point_p95_ms"] != pytest.approx(naive)

    def test_the_overhead_matches_a_hand_paired_difference_on_the_fixture(
        self, recorded_children
    ):
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"),
            recorded_children,
            resamples=500,
            seed=DEFAULT_SEED,
        )
        differences = sorted(
            hybrid.wall_ms - lexical.wall_ms
            for report in recorded_children
            for hybrid in report.timings
            if hybrid.leg == "hybrid"
            for lexical in report.timings
            if lexical.leg == "lexical" and lexical.pair_index == hybrid.pair_index
        )
        assert cell["overhead"]["point_p95_ms"] == differences[int(30 * 0.95) - 1]

    def test_the_startup_race_is_one_value_per_start(self, recorded_children):
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"),
            recorded_children,
            resamples=500,
            seed=DEFAULT_SEED,
        )
        first = cell["first_query"]
        assert first["values_ms"] == [1000.0, 1050.0, 1100.0, 1150.0, 1200.0, 3100.0]
        assert first["p95_ms"] == p95(first["values_ms"])
        assert first["modes"] == {"hybrid": 5, "lexical": 1}
        assert first["degraded"] == 1
        assert first["errors"] == 0

    def test_a_degraded_measured_request_is_counted_never_dropped(self):
        reports = [
            _report(0, hybrid=[50.0, 50.0], lexical=[40.0, 40.0]),
        ]
        degraded = list(reports[0].timings)
        degraded[0] = Timing(
            pair_index=0,
            leg="hybrid",
            query_id="A1-0",
            wall_ms=50.0,
            mode="lexical",  # hybrid asked for, lexical answered
            rows=10,
            error=None,
        )
        degraded[2] = Timing(
            pair_index=1,
            leg="hybrid",
            query_id="A1-1",
            wall_ms=50.0,
            mode=None,
            rows=0,
            error="RuntimeError: boom",
        )
        reports[0] = ChildReport.from_dict(
            {
                **reports[0].to_dict(),
                "timings": [timing.to_dict() for timing in degraded],
            }
        )
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"), reports, resamples=50, seed=1
        )
        assert cell["degraded_to_lexical"] == 1
        assert cell["errors"]["hybrid"] == 1
        assert cell["hybrid"]["n"] == 2  # both still in the denominator
        # Neither request answered in hybrid, so the guard bites.
        assert cell["hybrid_answered"] == 0
        assert cell["verdict"]["pass"] is False
        assert "hybrid_answered" in cell["verdict"]["failed_checks"]

    def test_a_wholly_degraded_cell_names_the_reason_in_the_receipt(self):
        """The reason a request degraded is kept, not just the fact.

        A receipt saying "every request degraded" and nothing else sends the
        reader back to the machine; one saying ``sqlite-vec is not installed``
        is self-diagnosing. The note is recorded only for a request that
        degraded or raised, so the common case costs nothing.
        """
        reason = "hybrid requested but lexical only: sqlite-vec is not installed"
        timings = [
            Timing(
                pair_index=index,
                leg=leg,
                query_id=f"A1-{index}",
                wall_ms=40.0,
                mode="lexical",
                rows=10,
                error=None,
                note=reason if leg == "hybrid" else None,
            )
            for index in range(2)
            for leg in ("hybrid", "lexical")
        ]
        report = ChildReport.from_dict(
            {
                **_report(0, hybrid=[40.0, 40.0], lexical=[40.0, 40.0]).to_dict(),
                "timings": [timing.to_dict() for timing in timings],
            }
        )
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"), [report], resamples=50, seed=1
        )
        assert cell["degraded_reasons"] == {reason: 2}
        assert cell["hybrid_answered"] == 0
        assert cell["verdict"]["pass"] is False

    def test_the_cell_carries_its_own_verdict(self, recorded_children):
        cell = aggregate_cell(
            Cell(concurrency=1, workload="idle"),
            recorded_children,
            resamples=500,
            seed=DEFAULT_SEED,
        )
        assert set(cell["verdict"]) == {"pass", "checks", "failed_checks"}

    def test_a_cell_with_no_children_is_a_failing_cell_not_a_missing_one(self):
        cell = aggregate_cell(
            Cell(concurrency=4, workload="load"), [], resamples=50, seed=1
        )
        assert cell["starts"] == 0
        assert cell["verdict"]["pass"] is False
        assert "no starts" in cell["note"]


def _db_block() -> dict[str, Any]:
    return {
        "path": "/tmp/clone/sessions.db",
        "size_bytes": 891289600,
        "fingerprint": "deadbeef",
        "quick_fingerprint": "cafebabe",
        "visibility": {
            "admitted_sources": ["claude_code"],
            "visible_sessions": 10,
            "total_sessions": 12,
        },
        "embeddings": {"model": "bge-small-en-v1.5", "dim": 384, "vectors": 41239},
    }


class TestReceipt:
    @pytest.fixture
    def receipt(self, recorded_children) -> dict[str, Any]:
        cells = {
            "c1-idle": aggregate_cell(
                Cell(concurrency=1, workload="idle"),
                recorded_children,
                resamples=500,
                seed=DEFAULT_SEED,
            )
        }
        return build_stage5_receipt(
            cells=cells,
            db=_db_block(),
            gold={"path": "/repo/gold.json", "sha256": "abc", "n": 91},
            args={"starts": 6, "requests": 5, "seed": DEFAULT_SEED},
            workload=workload_plan(cores=16),
            git_commit="abc1234",
            environment={"platform": "darwin"},
        )

    def test_it_carries_the_frozen_schema_and_every_block(self, receipt):
        assert receipt["schema"] == SCHEMA
        assert set(receipt) >= {
            "schema",
            "created_utc",
            "git_commit",
            "pre_registration",
            "db",
            "gold",
            "args",
            "workload",
            "gates",
            "cells",
            "verdict",
            "environment",
            "metrics_sha256",
        }
        assert "stage5-preregistration-2026-09-15" in receipt["pre_registration"]

    def test_the_gate_thresholds_are_echoed_so_the_receipt_reads_alone(self, receipt):
        assert receipt["gates"] == {
            "ub95_p95_ms": GATE_P95_MS,
            "overhead_p95_ms": GATE_OVERHEAD_P95_MS,
            "first_query_p95_ms": GATE_FIRST_QUERY_P95_MS,
            "one_sided_confidence": 0.95,
            "clustered_by": "start",
        }

    def test_the_args_are_echoed(self, receipt):
        assert receipt["args"]["starts"] == 6
        assert receipt["args"]["seed"] == DEFAULT_SEED

    def test_the_digest_covers_the_measured_numbers_and_ignores_the_clock(
        self, receipt
    ):
        import copy
        import json

        from agent_session_tools.eval.receipt import metrics_sha256

        assert receipt["metrics_sha256"] == metrics_sha256(receipt)
        later = copy.deepcopy(receipt)
        later["created_utc"] = "2030-01-01T00:00:00+00:00"
        assert metrics_sha256(later) == receipt["metrics_sha256"]
        moved = json.loads(json.dumps(receipt))
        moved["cells"]["c1-idle"]["hybrid"]["point_p95_ms"] = 999.0
        assert metrics_sha256(moved) != receipt["metrics_sha256"]

    def test_the_overall_verdict_is_the_cells_and_never_a_pool(self, receipt):
        assert receipt["verdict"]["cells_reported"] == 1
        assert "no pooling" in receipt["verdict"]["rule"]


class TestMeasurementConfigMeasuresTheShippingSystem:
    def test_query_encoder_is_auto_not_a_hardcoded_backend(self, tmp_path):
        """The Gate L SUT is the system as it ships: query_encoder resolves
        per the schema default ('auto' since the A2 flip, Gate P PASS), not a
        backend pinned by the tool. The 2026-09-15 torch-pinned run is kept as
        the torch-path receipt; this pins the corrected SUT.
        """
        from agent_session_tools.eval.stage5_latency import measurement_config

        config = measurement_config(tmp_path / "sessions.db", "bge-small-en-v1.5")
        assert config["semantic_search"]["query_encoder"] == "auto"
