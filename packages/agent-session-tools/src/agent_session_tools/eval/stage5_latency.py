"""Gate L: the resident-state latency measurement runner (Stage 5, option L-astra).

Pre-registration:
``docs/architecture/session-memory/receipts/semantic-layer/stage5-preregistration-2026-09-15.md``.
This module implements that design and nothing else -- it decides whether the
hybrid default may be flipped ON for the ``mcp`` and ``web`` surfaces, so every
choice it makes is either quoted from the pre-registration or recorded in the
receipt it writes.

The design, in the pre-registration's own words: *30 independent process starts
x 100 measured requests per cell; concurrency 1 and 4; idle plus one named
repeatable background workload; uncertainty clustered by start (bootstrap);
one-sided 95% upper confidence bound on p95.* Gate: ``UB95(p95 wall) <= 200 ms``
AND paired hybrid-lexical ``p95`` overhead ``<= 100 ms``, per cell; separately
startup-race first-query ``p95 <= 3.5 s`` including degraded/error outcomes.
**No pooling away a failing cell** -- every cell is reported and any failing
cell fails the gate.

Two processes, one module
-------------------------
``child`` is one *start*: a fresh interpreter that races its own encoder warm
with a first query, then runs the measured requests and prints one JSON blob.
``run`` is the parent: it launches the starts, runs the named background
workload for the load cells, aggregates the children it collected and writes
one receipt.

That split is the whole point of the design. "30 independent process starts" can
only be measured by 30 real process starts -- a loop inside one interpreter
would share a warm encoder, a warm import graph and a warm page cache, and the
startup race would be unmeasurable after the first iteration.

Why the child is faithful to the mcp surface
--------------------------------------------
The child calls the shipped ``session_search`` tool through FastMCP
``call_tool`` (:mod:`.arms`' interface, one persistent event loop, as a server
has), against a database and a config the parent wrote, and lets
:func:`agent_session_tools.retrieval.resolve_mode` decide the mode from
``surface="mcp"``. The *hybrid* leg is produced by setting
``retrieval.SURFACE_DEFAULTS[SURFACE_MCP] = "hybrid"`` -- literally the one-dict
edit the held flip commit makes -- and the *lexical* leg by setting it back. So
the paired overhead this runner reports is exactly "the cost of the flip",
measured through the same resolution chain a real MCP server walks, not through
the ``STUDYLOOP_RETRIEVAL_MODE`` override (which short-circuits step 4 of
``resolve_mode`` and would prove nothing about the surface default).

For that to be true the measurement config must leave ``semantic_search.hybrid``
*unset*: an explicit ``true``/``false`` in config.yaml wins on every surface, so
a machine that pins it can never observe the flip. The parent therefore writes a
minimal config (recorded verbatim, with its sha256, in the receipt) rather than
reading the owner's.

Running it
----------
The environment needs the ``semantic`` extra, and a plain ``uv run --group dev``
re-syncs it away again -- without ``sqlite-vec`` the semantic arm cannot run,
every hybrid request degrades to lexical and the run measures two lexical
searches. :func:`preflight_reasons` refuses before the first start rather than
after the last, but the sync is the caller's to get right::

    uv sync --all-packages --group dev --extra semantic
    uv run --no-sync python -m agent_session_tools.eval stage5-latency \
        --db ~/.local/share/studyloop/eval-clones/bakeoff-bge-20260915/sessions.db \
        --out docs/.../stage5-gate-l-<date>.json

Add ``--smoke`` for the plumbing proof (2 starts x 5 requests x ``1:idle``),
whose receipt is never the gate's. The exit status is 0 for a passing gate, 1
for a failing one (the receipt is written either way -- the pre-registration's
outcome rule commits a failing receipt as-is), and 2 when the run could not
start.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import subprocess  # noqa: S404 - fixed argv built here, never a shell
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .gold import GOLD_DEV_ITEMS, load_gold
from .receipt import db_fingerprint, metrics_sha256, resolved_visibility, write_receipt

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

#: Wall-clock at the earliest moment this module can observe in a child.
_IMPORT_MONOTONIC = time.monotonic()

#: Receipt schema written by :func:`build_stage5_receipt`.
SCHEMA = "studyloop.stage5-latency/v1"
#: Schema of the JSON blob one child prints.
CHILD_SCHEMA = "studyloop.stage5-latency-child/v1"
#: The signed design this runner implements; quoted on every receipt.
PRE_REGISTRATION = (
    "docs/architecture/session-memory/receipts/semantic-layer/"
    "stage5-preregistration-2026-09-15.md"
)
#: Line prefix the child prints its JSON blob behind, so unrelated stdout
#: noise (a library banner, a load indicator) can never break the parent's
#: parse.
CHILD_SENTINEL = "STAGE5-CHILD-JSON "

# --- the pre-registered design, frozen ------------------------------------
#: "30 independent process starts x 100 measured requests per cell".
DEFAULT_STARTS = 30
DEFAULT_REQUESTS = 100
#: Cluster bootstrap by start: resamples and seed. B is smaller than the gold
#: ruler's 10,000 because the resampling unit is a *start* whose statistic
#: pools 100-200 timings, so each draw costs a sort of ~3,000 values.
BOOTSTRAP_RESAMPLES = 2000
DEFAULT_SEED = 20260915
#: One-sided upper confidence bound: "one-sided 95% upper confidence bound on p95".
ONE_SIDED = 0.95
#: The gate, per cell.
GATE_P95_MS = 200.0
GATE_OVERHEAD_P95_MS = 100.0
GATE_FIRST_QUERY_P95_MS = 3500.0
#: Rows the measured tool call asks for -- the shipped ``session_search`` default.
DEFAULT_ROWS = 10

LEG_HYBRID = "hybrid"
LEG_LEXICAL = "lexical"
LEGS = (LEG_HYBRID, LEG_LEXICAL)

WORKLOAD_IDLE = "idle"
WORKLOAD_LOAD = "load"
WORKLOADS = (WORKLOAD_IDLE, WORKLOAD_LOAD)

#: The pre-registration's "one named repeatable background workload". Named
#: here, implemented by :data:`SPIN_SOURCE`, and echoed into the receipt: K CPU
#: -bound python spinners where K is half the machine's cores.
WORKLOAD_NAME = "spin-half-cores"
#: A tight integer loop: no allocation, no I/O, no syscalls in the hot path, so
#: the load it applies is CPU contention and nothing else. Deadline-bounded so
#: a spinner orphaned by a killed parent cannot spin forever.
SPIN_SOURCE = (
    "import sys, time\n"
    "deadline = time.monotonic() + float(sys.argv[1])\n"
    "x = 1\n"
    "while time.monotonic() < deadline:\n"
    "    for _ in range(200000):\n"
    "        x = (x * 1103515245 + 12345) & 0x7FFFFFFF\n"
)
#: Safety net, not a schedule: the parent terminates its spinners after every
#: start, and this only bounds an orphan.
WORKLOAD_TTL_SECONDS = 600.0
#: Seconds the spinners are given to reach steady state before a child starts.
WORKLOAD_SETTLE_SECONDS = 0.25

#: Environment variables removed from a child's environment. Each of these
#: would silently take the measurement somewhere else:
#: ``STUDYLOOP_RETRIEVAL_MODE`` wins over the surface default (so the flip
#: would never be what was measured), ``DATABASE_PATH`` overrides
#: ``database.path`` in the config the parent wrote, ``STUDYLOOP_DB`` and
#: ``STUDYLOOP_QUERY_ENCODER`` likewise pre-empt the written config.
CHILD_ENV_STRIPPED = (
    "STUDYLOOP_RETRIEVAL_MODE",
    "STUDYLOOP_QUERY_ENCODER",
    "DATABASE_PATH",
    "STUDYLOOP_DB",
)


# ---------------------------------------------------------------- cells
@dataclass(frozen=True, slots=True)
class Cell:
    """One measured cell: a concurrency and a background-load condition."""

    concurrency: int
    workload: str

    @property
    def name(self) -> str:
        return f"c{self.concurrency}-{self.workload}"

    def describe(self) -> dict[str, Any]:
        return {
            "cell": self.name,
            "concurrency": self.concurrency,
            "workload": self.workload,
        }


#: "concurrency 1 and 4; idle plus one named repeatable background workload".
DEFAULT_CELLS = (
    Cell(1, WORKLOAD_IDLE),
    Cell(1, WORKLOAD_LOAD),
    Cell(4, WORKLOAD_IDLE),
    Cell(4, WORKLOAD_LOAD),
)


def parse_cells(spec: str) -> tuple[Cell, ...]:
    """Parse ``--cells 1:idle,4:load`` into cells, refusing anything unnamed."""
    cells: list[Cell] = []
    for chunk in (part.strip() for part in spec.split(",")):
        if not chunk:
            continue
        concurrency, _, workload = chunk.partition(":")
        try:
            width = int(concurrency)
        except ValueError:
            raise ValueError(
                f"cell {chunk!r}: concurrency must be an integer, not {concurrency!r}"
            ) from None
        if width < 1:
            raise ValueError(f"cell {chunk!r}: concurrency must be at least 1")
        if workload not in WORKLOADS:
            raise ValueError(
                f"cell {chunk!r}: unknown workload {workload!r}; "
                f"expected one of {WORKLOADS}"
            )
        cells.append(Cell(width, workload))
    if not cells:
        raise ValueError(f"no cells in {spec!r}")
    return tuple(cells)


def workload_plan(
    cores: int | None = None, ttl_seconds: float = WORKLOAD_TTL_SECONDS
) -> dict[str, Any]:
    """The named background workload, described well enough to reproduce it.

    ``spin-half-cores``: ``max(1, cores // 2)`` python subprocesses each running
    :data:`SPIN_SOURCE`. Half the cores on purpose -- a workload that saturates
    every core measures scheduler starvation rather than a busy machine, and the
    gate is about a machine the learner is also working on.
    """
    resolved = cores if cores is not None else (os.cpu_count() or 2)
    return {
        "name": WORKLOAD_NAME,
        "cores": resolved,
        "processes": max(1, resolved // 2),
        "spin": "python integer loop, no allocation and no I/O",
        "ttl_seconds": ttl_seconds,
        "settle_seconds": WORKLOAD_SETTLE_SECONDS,
        "relaunched": "once per start, terminated when that start exits",
    }


# ---------------------------------------------------------- the child's data
@dataclass(frozen=True, slots=True)
class Timing:
    """One measured request.

    ``note`` is ``retrieval_status.note`` and is kept only when the request
    degraded (``mode`` is not the leg that was asked for) or raised, because
    that note is the only thing that says *why* -- "every hybrid request
    answered lexically" without a reason sends the receipt's reader back to the
    machine. A request that did what was asked carries ``None``, so the common
    case costs nothing in the receipt.
    """

    pair_index: int
    leg: str
    query_id: str
    wall_ms: float
    mode: str | None
    rows: int
    error: str | None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_index": self.pair_index,
            "leg": self.leg,
            "query_id": self.query_id,
            "wall_ms": self.wall_ms,
            "mode": self.mode,
            "rows": self.rows,
            "error": self.error,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Timing:
        return cls(
            pair_index=int(payload["pair_index"]),
            leg=str(payload["leg"]),
            query_id=str(payload["query_id"]),
            wall_ms=float(payload["wall_ms"]),
            mode=None if payload.get("mode") is None else str(payload["mode"]),
            rows=int(payload["rows"]),
            error=None if payload.get("error") is None else str(payload["error"]),
            note=None if payload.get("note") is None else str(payload["note"]),
        )

    @property
    def degraded(self) -> bool:
        """Answered, but not in the mode the leg asked for."""
        return self.error is None and self.mode != self.leg


@dataclass(frozen=True, slots=True)
class FirstQuery:
    """The startup race: the first query, issued immediately at process start.

    ``since_spawn_ms`` is measured from the parent's pre-``Popen`` clock, so it
    includes interpreter startup and every import -- the conservative reading of
    "startup-race first-query", and the one the gate is applied to.
    ``wall_ms`` is the child's own view (from its first executed line) and is
    reported beside it. ``mode`` is ``retrieval_status.mode``, so a query that
    lost the race and was answered lexically is visible rather than averaged
    away; ``status`` is ``"error"`` for a degraded outcome that raised, and it
    still counts.
    """

    wall_ms: float
    since_spawn_ms: float | None
    mode: str | None
    status: str
    error: str | None
    rows: int
    warm_state_at_issue: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_ms": self.wall_ms,
            "since_spawn_ms": self.since_spawn_ms,
            "mode": self.mode,
            "status": self.status,
            "error": self.error,
            "rows": self.rows,
            "warm_state_at_issue": self.warm_state_at_issue,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FirstQuery:
        since = payload.get("since_spawn_ms")
        return cls(
            wall_ms=float(payload["wall_ms"]),
            since_spawn_ms=None if since is None else float(since),
            mode=None if payload.get("mode") is None else str(payload["mode"]),
            status=str(payload["status"]),
            error=None if payload.get("error") is None else str(payload["error"]),
            rows=int(payload["rows"]),
            warm_state_at_issue=str(payload["warm_state_at_issue"]),
        )

    @property
    def gated_ms(self) -> float:
        """What the startup-race gate reads: since-spawn when known."""
        return self.wall_ms if self.since_spawn_ms is None else self.since_spawn_ms


@dataclass(frozen=True, slots=True)
class WarmReport:
    """Warm-up, excluded from the measured requests and reported anyway.

    The pre-registration excludes "encoder loaded to ``ready`` + one discarded
    query" and requires the duration be reported. ``load_elapsed_ms`` is the
    background warm's own timing (from ``retrieval.encoder_warm_status()``),
    ``wait_ms`` is how long the child waited for it after the racing first
    query returned, and ``discarded_query_ms`` is the one thrown-away query.
    """

    state: str
    model: str | None
    load_elapsed_ms: float | None
    wait_ms: float
    discarded_query_ms: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "model": self.model,
            "load_elapsed_ms": self.load_elapsed_ms,
            "wait_ms": self.wait_ms,
            "discarded_query_ms": self.discarded_query_ms,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WarmReport:
        elapsed = payload.get("load_elapsed_ms")
        return cls(
            state=str(payload["state"]),
            model=None if payload.get("model") is None else str(payload["model"]),
            load_elapsed_ms=None if elapsed is None else float(elapsed),
            wait_ms=float(payload["wait_ms"]),
            discarded_query_ms=float(payload["discarded_query_ms"]),
            detail=str(payload.get("detail", "")),
        )

    @property
    def total_ms(self) -> float:
        """Everything the pre-registration excludes, added up."""
        load = self.load_elapsed_ms or 0.0
        return max(load, self.wait_ms) + self.discarded_query_ms


_CHILD_BLOCKS = (
    "start_index",
    "concurrency",
    "workload",
    "requests",
    "first_query",
    "warm",
    "timings",
    "environment",
    "elapsed_ms",
)


@dataclass(frozen=True, slots=True)
class ChildReport:
    """One start's measurements -- the parent's only input, and a receipt row."""

    schema: str
    start_index: int
    concurrency: int
    workload: str
    requests: int
    first_query: FirstQuery
    warm: WarmReport
    timings: tuple[Timing, ...]
    environment: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "start_index": self.start_index,
            "concurrency": self.concurrency,
            "workload": self.workload,
            "requests": self.requests,
            "first_query": self.first_query.to_dict(),
            "warm": self.warm.to_dict(),
            "timings": [timing.to_dict() for timing in self.timings],
            "environment": dict(self.environment),
            "elapsed_ms": self.elapsed_ms,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ChildReport:
        """Load a child blob, refusing anything this parent cannot read.

        Fails closed on purpose: a silently defaulted block would let a child
        that never ran its warm, or one from an older schema, be aggregated as
        if it had, and the receipt would look complete.
        """
        schema = str(payload.get("schema", ""))
        if schema != CHILD_SCHEMA:
            raise ValueError(
                f"child schema {schema!r} is not {CHILD_SCHEMA!r}; refusing to read it"
            )
        missing = [block for block in _CHILD_BLOCKS if block not in payload]
        if missing:
            raise ValueError(f"child blob is missing {', '.join(missing)}")
        return cls(
            schema=schema,
            start_index=int(payload["start_index"]),
            concurrency=int(payload["concurrency"]),
            workload=str(payload["workload"]),
            requests=int(payload["requests"]),
            first_query=FirstQuery.from_dict(payload["first_query"]),
            warm=WarmReport.from_dict(payload["warm"]),
            timings=tuple(Timing.from_dict(t) for t in payload["timings"]),
            environment=dict(payload["environment"]),
            elapsed_ms=float(payload["elapsed_ms"]),
        )

    def start_key(self) -> str:
        return f"start-{self.start_index:03d}"

    def leg_walls(self, leg: str) -> list[float]:
        return [t.wall_ms for t in self.timings if t.leg == leg]

    def paired_overhead(self) -> list[float]:
        """``hybrid - lexical`` per request, paired by position in the cycle."""
        hybrid = {t.pair_index: t.wall_ms for t in self.timings if t.leg == LEG_HYBRID}
        lexical = {
            t.pair_index: t.wall_ms for t in self.timings if t.leg == LEG_LEXICAL
        }
        return [
            hybrid[index] - lexical[index]
            for index in sorted(set(hybrid) & set(lexical))
        ]


# ------------------------------------------------------------- arithmetic
def p95(values: Sequence[float]) -> float:
    """p95 by the repo's ported index arithmetic (:func:`.metrics.latency_percentiles`).

    One definition of p95 across every StudyLoop retrieval receipt matters more
    than a textbook interpolation: two receipts that disagree about what p95
    means cannot be compared, and this gate is quoted against Stage 4's numbers.
    """
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(int(len(ordered) * 0.95) - 1, 0)]


def bootstrap_p95_upper_bound(
    by_start: Mapping[str, Sequence[float]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """One-sided 95% upper confidence bound on p95, clustered by start.

    The resampling unit is a **start**, not a request: requests inside one
    process share an encoder instance, a page cache and a scheduler placement,
    so they are not independent and a per-request bootstrap would report an
    interval far too narrow. Each draw resamples the starts with replacement,
    pools their timings and takes :func:`p95`; the bound is the 95th percentile
    of the draws, by the same index arithmetic.
    """
    names = sorted(by_start)
    pooled = [value for name in names for value in by_start[name]]
    point = p95(pooled)
    if not names:
        return {
            "point_p95_ms": 0.0,
            "ub95_p95_ms": 0.0,
            "point_p50_ms": 0.0,
            "starts": 0,
            "n": 0,
            "resamples": resamples,
            "seed": seed,
            "one_sided": ONE_SIDED,
        }
    rng = random.Random(seed)  # nosec B311 - statistical bootstrap, not cryptography
    draws: list[float] = []
    for _ in range(resamples):
        sample = rng.choices(names, k=len(names))
        draws.append(p95([value for name in sample for value in by_start[name]]))
    draws.sort()
    ordered_pooled = sorted(pooled)
    return {
        "point_p95_ms": point,
        "ub95_p95_ms": draws[max(int(resamples * ONE_SIDED) - 1, 0)],
        "point_p50_ms": ordered_pooled[len(ordered_pooled) // 2],
        "starts": len(names),
        "n": len(pooled),
        "resamples": resamples,
        "seed": seed,
        "one_sided": ONE_SIDED,
    }


def cell_verdict(
    *,
    ub95_p95_ms: float,
    overhead_p95_ms: float,
    first_query_p95_ms: float,
    hybrid_answered: int = 1,
) -> dict[str, Any]:
    """The pre-registered gate for one cell, check by check.

    Each threshold is inclusive (the pre-registration says ``<=``). The wall
    check reads the bootstrap's **upper bound**; the overhead and startup-race
    checks read the **point** p95 -- that is what the signed text says, and a
    runner that quietly gated the overhead on its own upper bound would be
    running a stricter, unsigned gate.

    ``hybrid_answered`` is a validity guard rather than a fourth threshold: it
    is how many measured requests on the hybrid leg were actually *answered* in
    hybrid mode. Zero means the semantic arm never ran (a missing ``sqlite-vec``
    does exactly this, and it was the first smoke run's result), in which case
    the wall and overhead numbers describe two lexical searches and a PASS would
    flip the default on evidence that hybrid was never measured.
    """
    checks: dict[str, dict[str, Any]] = {
        "ub95_p95_ms": {
            "value": ub95_p95_ms,
            "threshold_ms": GATE_P95_MS,
            "pass": ub95_p95_ms <= GATE_P95_MS,
            "reads": "one-sided 95% upper bound on p95 wall, clustered by start",
        },
        "overhead_p95_ms": {
            "value": overhead_p95_ms,
            "threshold_ms": GATE_OVERHEAD_P95_MS,
            "pass": overhead_p95_ms <= GATE_OVERHEAD_P95_MS,
            "reads": "p95 of the paired hybrid-lexical per-request difference",
        },
        "first_query_p95_ms": {
            "value": first_query_p95_ms,
            "threshold_ms": GATE_FIRST_QUERY_P95_MS,
            "pass": first_query_p95_ms <= GATE_FIRST_QUERY_P95_MS,
            "reads": "p95 of the startup-race first query across starts, "
            "degraded and error outcomes included",
        },
        "hybrid_answered": {
            "value": hybrid_answered,
            "required": ">= 1",
            "pass": hybrid_answered >= 1,
            "reads": "measured requests the hybrid leg actually answered in "
            "hybrid mode; zero means the semantic arm never ran and the cell "
            "measured lexical twice",
        },
    }
    failed = [name for name, check in checks.items() if not check["pass"]]
    return {"pass": not failed, "checks": checks, "failed_checks": failed}


def overall_verdict(cells: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The gate over every cell: any failing cell fails it.

    "No pooling away a failing cell" is the pre-registration's phrase and this
    function is where it is enforced -- there is deliberately no path here that
    combines cells into one number. A run with no cells at all fails too: an
    absent measurement is not a pass.
    """
    failing = sorted(
        name
        for name, cell in cells.items()
        if not bool(dict(cell.get("verdict", {})).get("pass"))
    )
    return {
        "pass": bool(cells) and not failing,
        "failing_cells": failing,
        "cells_reported": len(cells),
        "rule": (
            "no pooling: every cell is reported and any failing cell fails "
            "Gate L (stage5 pre-registration, Gate L / L-astra)"
        ),
    }


# ------------------------------------------------------- the leg schedule
@dataclass(frozen=True, slots=True)
class Batch:
    """One batch of requests, run once per leg at the cell's concurrency."""

    pair_indices: tuple[int, ...]
    legs: tuple[str, str]


def leg_schedule(*, requests: int, concurrency: int) -> tuple[Batch, ...]:
    """Batches of ``concurrency`` requests, each timed in both legs.

    Pairing is per request and adjacent in time: the same query is answered
    hybrid and lexical within one batch, on the same connection and under the
    same load, which is what makes the difference a *paired* overhead rather
    than a difference of two independently drifting p95s.

    The leg order alternates per batch so neither leg is systematically first
    (the second leg of a pair benefits from a warmer page cache for that
    query's rows, and always giving that advantage to lexical would flatter the
    overhead).
    """
    batches: list[Batch] = []
    for batch_index, start in enumerate(range(0, requests, concurrency)):
        indices = tuple(range(start, min(start + concurrency, requests)))
        legs = LEGS if batch_index % 2 == 0 else (LEG_LEXICAL, LEG_HYBRID)
        batches.append(Batch(indices, legs))
    return tuple(batches)


# --------------------------------------------------------- aggregation
def _by_start(
    reports: Sequence[ChildReport], values: Callable[[ChildReport], Sequence[float]]
) -> dict[str, list[float]]:
    return {report.start_key(): list(values(report)) for report in reports}


def aggregate_cell(
    cell: Cell,
    reports: Sequence[ChildReport],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Everything the receipt says about one cell, from the starts it collected.

    Pure: it takes recorded child reports and starts no process, so the whole
    aggregation is unit-testable against a fixture.
    """
    if not reports:
        return {
            **cell.describe(),
            "starts": 0,
            "requests_per_start": [],
            "hybrid": bootstrap_p95_upper_bound({}, resamples=resamples, seed=seed),
            "lexical": bootstrap_p95_upper_bound({}, resamples=resamples, seed=seed),
            "overhead": bootstrap_p95_upper_bound({}, resamples=resamples, seed=seed),
            "first_query": {
                "values_ms": [],
                "p95_ms": 0.0,
                "p50_ms": 0.0,
                "max_ms": 0.0,
                "modes": {},
                "degraded": 0,
                "errors": 0,
                "bootstrap": bootstrap_p95_upper_bound(
                    {}, resamples=resamples, seed=seed
                ),
            },
            "warm": {"total_p50_ms": 0.0, "total_p95_ms": 0.0, "states": {}},
            "errors": {LEG_HYBRID: 0, LEG_LEXICAL: 0},
            "degraded_to_lexical": 0,
            "degraded_reasons": {},
            "hybrid_answered": 0,
            "by_start": {},
            # A cell that produced no starts is a failing cell, not an absent
            # one: the gate is "every cell reported", and a missing cell must
            # not read as a pass.
            "note": "no starts were collected for this cell",
            "verdict": cell_verdict(
                ub95_p95_ms=float("inf"),
                overhead_p95_ms=float("inf"),
                first_query_p95_ms=float("inf"),
                hybrid_answered=0,
            ),
        }

    hybrid_by_start = _by_start(reports, lambda r: r.leg_walls(LEG_HYBRID))
    lexical_by_start = _by_start(reports, lambda r: r.leg_walls(LEG_LEXICAL))
    overhead_by_start = _by_start(reports, lambda r: r.paired_overhead())

    hybrid = bootstrap_p95_upper_bound(hybrid_by_start, resamples=resamples, seed=seed)
    lexical = bootstrap_p95_upper_bound(
        lexical_by_start, resamples=resamples, seed=seed
    )
    overhead = bootstrap_p95_upper_bound(
        overhead_by_start, resamples=resamples, seed=seed
    )

    first_values = [report.first_query.gated_ms for report in reports]
    modes: dict[str, int] = {}
    for report in reports:
        key = report.first_query.mode or "unknown"
        modes[key] = modes.get(key, 0) + 1
    warm_states: dict[str, int] = {}
    for report in reports:
        warm_states[report.warm.state] = warm_states.get(report.warm.state, 0) + 1
    warm_totals = [report.warm.total_ms for report in reports]

    errors = {
        leg: sum(1 for r in reports for t in r.timings if t.leg == leg and t.error)
        for leg in LEGS
    }
    hybrid_timings = [t for r in reports for t in r.timings if t.leg == LEG_HYBRID]
    degraded = sum(1 for t in hybrid_timings if t.degraded)
    hybrid_answered = sum(
        1 for t in hybrid_timings if t.error is None and t.mode == LEG_HYBRID
    )
    reasons: dict[str, int] = {}
    for timing in hybrid_timings:
        if timing.degraded and timing.note:
            reasons[timing.note] = reasons.get(timing.note, 0) + 1

    verdict = cell_verdict(
        ub95_p95_ms=hybrid["ub95_p95_ms"],
        overhead_p95_ms=overhead["point_p95_ms"],
        first_query_p95_ms=p95(first_values),
        hybrid_answered=hybrid_answered,
    )
    return {
        **cell.describe(),
        "starts": len(reports),
        "requests_per_start": [len(r.leg_walls(LEG_HYBRID)) for r in reports],
        "hybrid": hybrid,
        "lexical": lexical,
        "overhead": overhead,
        "first_query": {
            "values_ms": first_values,
            "p95_ms": p95(first_values),
            "p50_ms": sorted(first_values)[len(first_values) // 2],
            "max_ms": max(first_values),
            "modes": dict(sorted(modes.items())),
            "degraded": sum(
                1
                for r in reports
                if r.first_query.status == "ok" and r.first_query.mode != LEG_HYBRID
            ),
            "errors": sum(1 for r in reports if r.first_query.status != "ok"),
            # Reported, never gated: the pre-registration gates the startup
            # race on p95, not on a bound.
            "bootstrap": bootstrap_p95_upper_bound(
                {r.start_key(): [r.first_query.gated_ms] for r in reports},
                resamples=resamples,
                seed=seed,
            ),
        },
        "warm": {
            "total_p50_ms": sorted(warm_totals)[len(warm_totals) // 2],
            "total_p95_ms": p95(warm_totals),
            "load_p95_ms": p95([r.warm.load_elapsed_ms or 0.0 for r in reports]),
            "discarded_query_p95_ms": p95([r.warm.discarded_query_ms for r in reports]),
            "states": dict(sorted(warm_states.items())),
        },
        "errors": errors,
        "degraded_to_lexical": degraded,
        "degraded_reasons": dict(sorted(reasons.items())),
        "hybrid_answered": hybrid_answered,
        # Kept so the bound can be recomputed from the receipt alone, without
        # re-measuring -- the same reason the gold receipt keeps ``per_item``.
        "by_start": {
            name: {
                LEG_HYBRID: [round(v, 3) for v in hybrid_by_start[name]],
                LEG_LEXICAL: [round(v, 3) for v in lexical_by_start[name]],
                "overhead": [round(v, 3) for v in overhead_by_start[name]],
            }
            for name in sorted(hybrid_by_start)
        },
        "note": "",
        "verdict": verdict,
    }


def build_stage5_receipt(
    *,
    cells: Mapping[str, Mapping[str, Any]],
    db: Mapping[str, Any],
    gold: Mapping[str, Any],
    args: Mapping[str, Any],
    workload: Mapping[str, Any],
    git_commit: str = "",
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble Gate L's receipt.

    The digest deliberately covers the measured percentiles: for a latency
    receipt the timings *are* the result, so ``metrics_sha256`` answering "are
    these the same numbers?" is the useful question. Only the clock and
    ``elapsed_ms`` are stripped, by the shared
    :func:`.receipt.metrics_sha256`.
    """
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit,
        "pre_registration": PRE_REGISTRATION,
        "gate": "L (L-astra): resident-state latency for the mcp/web default flip",
        "db": dict(db),
        "gold": dict(gold),
        "args": dict(args),
        "workload": dict(workload),
        "gates": {
            "ub95_p95_ms": GATE_P95_MS,
            "overhead_p95_ms": GATE_OVERHEAD_P95_MS,
            "first_query_p95_ms": GATE_FIRST_QUERY_P95_MS,
            "one_sided_confidence": ONE_SIDED,
            "clustered_by": "start",
        },
        "cells": {name: dict(cell) for name, cell in cells.items()},
        "environment": dict(environment or {}),
        "verdict": overall_verdict(cells),
    }
    receipt["metrics_sha256"] = metrics_sha256(receipt)
    return receipt


# =========================================================== the child
def _git_head() -> str:
    from .arms import _git_head as head

    return head()


def db_quick_fingerprint(db_path: Path) -> dict[str, Any]:
    """A cheap identity for the corpus, computed once per child.

    :func:`.receipt.db_fingerprint` scans every session and message count --
    right for one receipt, wrong 120 times over on an 850 MB clone. This is the
    cheap agreement check instead: size, mtime and the embedding pin. The parent
    computes the real fingerprint once and asserts every child saw this same
    quick one.
    """
    import hashlib
    import sqlite3

    stat = db_path.stat()
    model, dim, vectors = "", 0, 0
    with suppress(sqlite3.Error):
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT model, dim, COUNT(*) FROM message_embeddings GROUP BY model, dim"
            ).fetchone()
            if row is not None:
                model, dim, vectors = str(row[0]), int(row[1]), int(row[2])
        finally:
            conn.close()
    digest = hashlib.sha256(
        f"{db_path}\x1f{stat.st_size}\x1f{stat.st_mtime_ns}\x1f{model}\x1f{dim}"
        f"\x1f{vectors}".encode()
    ).hexdigest()
    return {
        "path": str(db_path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "embeddings": {"model": model, "dim": dim, "vectors": vectors},
        "quick_fingerprint": digest,
    }


class _LoopRunner:
    """One event loop on one thread, for the whole child -- as a server has.

    ``arms.McpArm`` calls ``asyncio.run`` per query, which is right for a ruler
    that scores 91 questions and wrong for a latency measurement: it builds and
    tears down an event loop inside every timed request, and it can never have
    four tool calls genuinely in flight. Here the loop outlives the process's
    requests and the client threads submit onto it.
    """

    def __init__(self) -> None:
        import asyncio
        import threading

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="stage5-loop", daemon=True
        )
        self._thread.start()

    def call(self, coro: Any) -> Any:
        import asyncio

        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        with suppress(RuntimeError):
            self._loop.close()


class McpSurfaceCaller:
    """The shipped ``session_search`` tool, on the mcp surface, in this process.

    No ``STUDYLOOP_RETRIEVAL_MODE``, no patched ``_get_db_path``: the database
    comes from the config the parent wrote and the mode from
    ``resolve_mode(surface="mcp")``, so what is timed is the resolution chain a
    real MCP server walks.
    """

    def __init__(self, *, rows: int = DEFAULT_ROWS) -> None:
        from agent_session_tools import mcp_server

        self._server = mcp_server
        self.rows = rows
        self._loop = _LoopRunner()

    def call(self, pair_index: int, leg: str, query_id: str, text: str) -> Timing:
        from .arms import _split_payload

        arguments = {"query": text, "limit": self.rows}
        started = time.perf_counter()
        try:
            result = self._loop.call(
                self._server.mcp.call_tool("session_search", arguments)
            )
        except Exception as exc:
            return Timing(
                pair_index=pair_index,
                leg=leg,
                query_id=query_id,
                wall_ms=(time.perf_counter() - started) * 1000,
                mode=None,
                rows=0,
                error=f"{type(exc).__name__}: {exc}",
            )
        wall_ms = (time.perf_counter() - started) * 1000
        rows, status = _split_payload(getattr(result, "structured_content", None))
        mode = None if status is None else status.get("mode")
        return Timing(
            pair_index=pair_index,
            leg=leg,
            query_id=query_id,
            wall_ms=wall_ms,
            mode=mode,
            rows=len(rows),
            error=None,
            # Only when the answer was not the mode asked for: that note names
            # the reason (a missing sqlite-vec, a dim mismatch, an explicit FTS5
            # query), and it is the difference between a diagnosable receipt and
            # "everything degraded, good luck".
            note=(
                None
                if mode == leg or status is None
                else (status.get("note") or "no note")
            ),
        )

    def close(self) -> None:
        self._loop.close()


@contextmanager
def _flip(leg: str) -> Iterator[None]:
    """Hold ``SURFACE_DEFAULTS[mcp]`` at one leg's value.

    This IS the flip commit, applied in-process: that commit changes only this
    dict. Mutating a module global is safe here because the leg is switched
    between batches, never while a batch's threads are in flight.
    """
    from agent_session_tools import retrieval

    previous = retrieval.SURFACE_DEFAULTS[retrieval.SURFACE_MCP]
    retrieval.SURFACE_DEFAULTS[retrieval.SURFACE_MCP] = leg
    try:
        yield
    finally:
        retrieval.SURFACE_DEFAULTS[retrieval.SURFACE_MCP] = previous


def _run_batch(
    caller: McpSurfaceCaller,
    pool: ThreadPoolExecutor | None,
    indices: Sequence[int],
    leg: str,
    queries: Sequence[tuple[str, str]],
) -> list[Timing]:
    """One leg of one batch, at the cell's concurrency."""
    jobs = [(index, *queries[index % len(queries)]) for index in indices]
    if pool is None:
        return [caller.call(index, leg, qid, text) for index, qid, text in jobs]
    futures = [
        pool.submit(caller.call, index, leg, qid, text) for index, qid, text in jobs
    ]
    return [future.result() for future in futures]


@dataclass(frozen=True, slots=True)
class _Measured:
    """What one start's three phases produced, before the receipt fields."""

    first_query: FirstQuery
    warm: WarmReport
    timings: tuple[Timing, ...]
    measured_ms: float
    resolved_mode_hybrid_leg: str


def _measure_start(
    args: argparse.Namespace, queries: Sequence[tuple[str, str]]
) -> _Measured:
    """The three phases of one start, in the order the pre-registration names.

    (a) the startup race, (b) warm-up to ready plus one discarded query --
    excluded from the measured set and reported -- then (c) the measured
    requests, paired per query at the cell's concurrency.
    """
    from agent_session_tools import retrieval

    from .arms import _quiet_errors

    # The flip, held for the whole start: ``warm_query_encoder`` only warms a
    # surface whose resolved mode is hybrid, so this has to precede it.
    with _flip(LEG_HYBRID), _quiet_errors():
        resolved = retrieval.resolve_mode(surface=retrieval.SURFACE_MCP)
        warm_thread = retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP)
        caller = McpSurfaceCaller(rows=args.rows)
        try:
            # (a) the first query, issued immediately, with no wait for the
            # warm. A degraded answer is data, not an error.
            warm_at_issue = retrieval.encoder_warm_status().state.value
            first_timing = caller.call(-1, LEG_HYBRID, *queries[0])
            first_done = time.monotonic()
            first_query = FirstQuery(
                wall_ms=(first_done - _IMPORT_MONOTONIC) * 1000,
                since_spawn_ms=(
                    None
                    if args.spawn_monotonic is None
                    else (first_done - args.spawn_monotonic) * 1000
                ),
                mode=first_timing.mode,
                status="error" if first_timing.error else "ok",
                error=first_timing.error,
                rows=first_timing.rows,
                warm_state_at_issue=warm_at_issue,
            )

            # (b) warm-up to ready + one discarded query, both excluded.
            wait_started = time.monotonic()
            if warm_thread is not None:
                warm_thread.join(timeout=args.warm_timeout)
            wait_ms = (time.monotonic() - wait_started) * 1000
            status = retrieval.encoder_warm_status()
            discarded = caller.call(-2, LEG_HYBRID, *queries[0])
            warm = WarmReport(
                state=status.state.value,
                model=status.model,
                load_elapsed_ms=(
                    None if status.elapsed is None else status.elapsed * 1000
                ),
                wait_ms=wait_ms,
                discarded_query_ms=discarded.wall_ms,
                detail=status.detail,
            )

            # (c) the measured requests.
            measured_started = time.monotonic()
            timings: list[Timing] = []
            pool = (
                ThreadPoolExecutor(max_workers=args.concurrency)
                if args.concurrency > 1
                else None
            )
            try:
                for batch in leg_schedule(
                    requests=args.requests, concurrency=args.concurrency
                ):
                    for leg in batch.legs:
                        with _flip(leg):
                            timings.extend(
                                _run_batch(
                                    caller, pool, batch.pair_indices, leg, queries
                                )
                            )
            finally:
                if pool is not None:
                    pool.shutdown(wait=True)
            measured_ms = (time.monotonic() - measured_started) * 1000
        finally:
            caller.close()
    return _Measured(
        first_query=first_query,
        warm=warm,
        timings=tuple(timings),
        measured_ms=measured_ms,
        resolved_mode_hybrid_leg=resolved,
    )


def run_child(args: argparse.Namespace) -> int:
    """One independent start: race the warm, warm up, measure, print the blob."""
    from agent_session_tools import query_encoders

    load_before = os.getloadavg()
    gold = load_gold(Path(args.gold).expanduser() if args.gold else None)
    queries = [(str(item["id"]), str(item["question"])) for item in gold.items]

    measured = _measure_start(args, queries)

    report = ChildReport(
        schema=CHILD_SCHEMA,
        start_index=args.start_index,
        concurrency=args.concurrency,
        workload=args.workload,
        requests=args.requests,
        first_query=measured.first_query,
        warm=measured.warm,
        timings=measured.timings,
        environment={
            "db": db_quick_fingerprint(Path(args.db).expanduser()),
            "gold_sha256": gold.sha256,
            "gold_n": gold.n,
            "backend": query_encoders.resolve_backend(),
            "resolved_mode_hybrid_leg": measured.resolved_mode_hybrid_leg,
            "git_commit": _git_head(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "load_avg_before": list(load_before),
            "load_avg_after": list(os.getloadavg()),
            "measured_ms": measured.measured_ms,
            "config": os.environ.get("STUDYLOOP_CONFIG", ""),
            "config_sha256": args.config_sha,
        },
        elapsed_ms=(time.monotonic() - _IMPORT_MONOTONIC) * 1000,
    )
    print(CHILD_SENTINEL + json.dumps(report.to_dict()))
    return 0


# =========================================================== the parent
MEASUREMENT_CONFIG_NOTE = (
    "written by stage5_latency for Gate L: semantic_search.hybrid is "
    "deliberately ABSENT so retrieval.resolve_mode falls through to "
    "SURFACE_DEFAULTS and the surface flip is what gets measured"
)


def measurement_config(db_path: Path, model: str) -> dict[str, Any]:
    """The config every child reads -- minimal, and reproducible from the receipt.

    ``semantic_search.hybrid`` is absent, which is the only way the surface
    default can decide the mode (``resolve_mode`` step 3 short-circuits on an
    explicit ``true``/``false``, on every surface). ``model`` is the database's
    own embedding pin rather than the schema default, because
    ``warm_query_encoder`` warms the *configured* model while the search encodes
    with the *pinned* one -- a mismatch would warm an encoder no query uses and
    make every measured request pay a cold load.
    """
    return {
        "_note": MEASUREMENT_CONFIG_NOTE,
        "database": {"path": str(db_path)},
        "memory": {"default_scope": "unclassified", "projects": {}},
        "semantic_search": {"model": model, "query_encoder": "torch"},
    }


def preflight_reasons(
    *, extension: tuple[bool, str], model: tuple[bool, str], pin_model: str
) -> list[str]:
    """Why this machine cannot measure hybrid, if it cannot.

    Checked BEFORE the first start, because the failure mode is silent and
    expensive: without ``sqlite-vec`` the semantic arm cannot run, every hybrid
    request degrades to lexical, and 120 starts later the receipt reports a few
    milliseconds of "overhead" between two lexical searches. The
    :func:`cell_verdict` guard catches that afterwards; this catches it before
    two hours are spent.
    """
    reasons: list[str] = []
    extension_ok, extension_reason = extension
    if not extension_ok:
        reasons.append(extension_reason or "the sqlite-vec extension is unavailable")
    model_ok, model_reason = model
    if not model_ok:
        reasons.append(model_reason or f"the {pin_model} query encoder is unavailable")
    return reasons


def _preflight(pin_model: str) -> list[str]:
    """Probe this machine for the two things hybrid needs, offline and cheaply."""
    from agent_session_tools import embedding_store

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    return preflight_reasons(
        extension=embedding_store._extension_available(),
        model=embedding_store._model_available(pin_model),
        pin_model=pin_model,
    )


def _embedding_pin(db_path: Path) -> tuple[str, int, int]:
    import sqlite3

    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT model, dim, COUNT(*) FROM message_embeddings GROUP BY model, dim"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(
            f"{db_path} has no rows in message_embeddings; Gate L needs the "
            "bge clone from the Stage 4 record"
        )
    return str(row[0]), int(row[1]), int(row[2])


@contextmanager
def background_workload(
    workload: str, *, cores: int | None = None, ttl: float = WORKLOAD_TTL_SECONDS
) -> Iterator[dict[str, Any]]:
    """Run the named workload for one start, and always take it down again."""
    if workload == WORKLOAD_IDLE:
        yield {"name": WORKLOAD_IDLE, "processes": 0}
        return
    plan = workload_plan(cores=cores, ttl_seconds=ttl)
    spinners = [
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", SPIN_SOURCE, str(ttl)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(int(plan["processes"]))
    ]
    time.sleep(WORKLOAD_SETTLE_SECONDS)
    try:
        yield plan
    finally:
        for spinner in spinners:
            with suppress(OSError):
                spinner.terminate()
        for spinner in spinners:
            with suppress(OSError, subprocess.TimeoutExpired):
                spinner.wait(timeout=10)


def _child_environment(config_path: Path) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if key not in CHILD_ENV_STRIPPED
    }
    env["STUDYLOOP_CONFIG"] = str(config_path)
    # A measurement must never download a model, and tokenizer thread fan-out
    # inside a concurrency cell would measure someone else's parallelism.
    env["HF_HUB_OFFLINE"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    return env


def launch_start(
    *,
    cell: Cell,
    start_index: int,
    requests: int,
    rows: int,
    db_path: Path,
    config_path: Path,
    config_sha: str,
    gold_path: Path | None,
    timeout: float,
    warm_timeout: float,
) -> ChildReport:
    """One process start; its JSON blob, or a RuntimeError naming what it printed."""
    argv = [
        sys.executable,
        "-m",
        f"{__package__}.stage5_latency",
        "child",
        "--db",
        str(db_path),
        "--start-index",
        str(start_index),
        "--concurrency",
        str(cell.concurrency),
        "--workload",
        cell.workload,
        "--requests",
        str(requests),
        "--rows",
        str(rows),
        "--config-sha",
        config_sha,
        "--warm-timeout",
        str(warm_timeout),
    ]
    if gold_path is not None:
        argv += ["--gold", str(gold_path)]
    spawn = time.monotonic()
    argv += ["--spawn-monotonic", repr(spawn)]
    done = subprocess.run(  # noqa: S603 - fixed argv built here, no shell
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_child_environment(config_path),
    )
    for line in done.stdout.splitlines():
        if line.startswith(CHILD_SENTINEL):
            return ChildReport.from_dict(json.loads(line[len(CHILD_SENTINEL) :]))
    detail = (done.stderr or done.stdout).strip()[-2000:]
    raise RuntimeError(
        f"start {start_index} of cell {cell.name} printed no report "
        f"(exit {done.returncode}): {detail}"
    )


def run_parent(args: argparse.Namespace) -> int:
    """Launch every start of every cell, aggregate, write one receipt."""
    import hashlib
    import tempfile

    import yaml

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"no database at {db_path}", file=sys.stderr)
        return 2
    starts, requests, cells = args.starts, args.requests, args.cells
    if args.smoke:
        # The plumbing proof, not a measurement: two starts, five requests,
        # one cell. Its receipt is never the Gate L receipt.
        starts, requests, cells = 2, 5, (Cell(1, WORKLOAD_IDLE),)

    model, dim, vectors = _embedding_pin(db_path)
    blockers = _preflight(model)
    if blockers and not args.allow_degraded:
        print(
            "this machine cannot measure hybrid, so Gate L would time two "
            "lexical searches and call the difference an overhead:",
            file=sys.stderr,
        )
        for reason in blockers:
            print(f"  - {reason}", file=sys.stderr)
        print(
            "fix it, or pass --allow-degraded to record the degraded run "
            "anyway (it will FAIL the hybrid_answered check)",
            file=sys.stderr,
        )
        return 2
    gold = load_gold(
        Path(args.gold).expanduser() if args.gold else None,
        require_items=None if args.gold else GOLD_DEV_ITEMS,
    )
    config = measurement_config(db_path, model)
    config_text = yaml.safe_dump(config, sort_keys=True)
    config_sha = hashlib.sha256(config_text.encode()).hexdigest()

    aggregated: dict[str, Any] = {}
    failures: list[str] = []
    #: Every quick fingerprint a child saw, so a corpus that moved mid-run is
    #: detectable rather than averaged into the receipt.
    seen_quick: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="stage5-latency-") as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(config_text)
        for cell in cells:
            reports: list[ChildReport] = []
            for start_index in range(starts):
                with background_workload(cell.workload, cores=args.cores):
                    try:
                        report = launch_start(
                            cell=cell,
                            start_index=start_index,
                            requests=requests,
                            rows=args.rows,
                            db_path=db_path,
                            config_path=config_path,
                            config_sha=config_sha,
                            gold_path=(
                                Path(args.gold).expanduser() if args.gold else None
                            ),
                            timeout=args.child_timeout,
                            warm_timeout=args.warm_timeout,
                        )
                    except (
                        RuntimeError,
                        ValueError,
                        subprocess.SubprocessError,
                    ) as exc:
                        # A lost start is recorded, never retried silently: the
                        # design says 30 independent starts, and a receipt that
                        # quietly measured 29 is a different design.
                        failures.append(f"{cell.name} start {start_index}: {exc}")
                        print(f"  start {start_index} FAILED: {exc}", file=sys.stderr)
                        continue
                reports.append(report)
                child_db = report.environment.get("db")
                if isinstance(child_db, dict):
                    seen_quick.add(str(child_db.get("quick_fingerprint", "")))
                print(
                    f"  {cell.name} start {start_index}: "
                    f"hybrid p95 {p95(report.leg_walls(LEG_HYBRID)):.1f} ms  "
                    f"lexical p95 {p95(report.leg_walls(LEG_LEXICAL)):.1f} ms  "
                    f"first {report.first_query.gated_ms:.0f} ms "
                    f"({report.first_query.mode})  warm {report.warm.total_ms:.0f} ms",
                    file=sys.stderr,
                )
            aggregated[cell.name] = aggregate_cell(
                cell, reports, resamples=args.resamples, seed=args.seed
            )

    parent_quick = db_quick_fingerprint(db_path)["quick_fingerprint"]
    drifted = sorted(seen_quick - {parent_quick})

    receipt = build_stage5_receipt(
        cells=aggregated,
        db={
            "path": str(db_path),
            "size_bytes": db_path.stat().st_size,
            "fingerprint": db_fingerprint(db_path),
            "visibility": resolved_visibility(db_path),
            "embeddings": {"model": model, "dim": dim, "vectors": vectors},
            "quick_fingerprint": db_quick_fingerprint(db_path)["quick_fingerprint"],
        },
        gold={
            "path": str(gold.path),
            "sha256": gold.sha256,
            "n": gold.n,
            "set": gold.name,
            "version": gold.version,
        },
        args={
            "db": str(db_path),
            "starts": starts,
            "requests": requests,
            "cells": [cell.name for cell in cells],
            "rows": args.rows,
            "seed": args.seed,
            "resamples": args.resamples,
            "smoke": bool(args.smoke),
            "out": str(args.out),
        },
        workload=workload_plan(cores=args.cores),
        git_commit=_git_head(),
        environment={
            "surface": "mcp",
            "interface": "fastmcp call_tool(session_search), one loop per start",
            "flip_simulated_by": "retrieval.SURFACE_DEFAULTS[SURFACE_MCP]",
            "config": config,
            "config_sha256": config_sha,
            "stripped_env": list(CHILD_ENV_STRIPPED),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "lost_starts": failures,
            "child_quick_fingerprints": sorted(seen_quick),
            "corpus_drifted_mid_run": drifted,
            "preflight_blockers": blockers,
        },
    )
    out = write_receipt(args.out, receipt)

    for name, cell_result in receipt["cells"].items():
        verdict = "PASS" if cell_result["verdict"]["pass"] else "FAIL"
        print(
            f"{name:>9}  starts {cell_result['starts']:>2}  "
            f"hybrid p95 {cell_result['hybrid']['point_p95_ms']:7.1f} ms  "
            f"UB95 {cell_result['hybrid']['ub95_p95_ms']:7.1f} ms  "
            f"lexical p95 {cell_result['lexical']['point_p95_ms']:7.1f} ms  "
            f"overhead p95 {cell_result['overhead']['point_p95_ms']:7.1f} ms  "
            f"first-query p95 {cell_result['first_query']['p95_ms']:7.0f} ms  "
            f"hybrid-answered {cell_result['hybrid_answered']}  "
            f"degraded {cell_result['degraded_to_lexical']}  {verdict}"
            + (
                f"  failed={','.join(cell_result['verdict']['failed_checks'])}"
                if cell_result["verdict"]["failed_checks"]
                else ""
            )
        )
    if failures:
        print(f"lost starts: {len(failures)}")
    if drifted:
        print(f"WARNING corpus changed mid-run; child fingerprints {drifted}")
    for name, cell_result in receipt["cells"].items():
        for reason, count in cell_result["degraded_reasons"].items():
            print(f"{name} degraded x{count}: {reason}")
    print(f"metrics_sha256 {receipt['metrics_sha256']}")
    print(f"verdict {'PASS' if receipt['verdict']['pass'] else 'FAIL'}")
    print(f"receipt -> {out}")
    return 0 if receipt["verdict"]["pass"] else 1


# =========================================================== the CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"python -m {__package__}.stage5_latency",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    add_parent_arguments(sub.add_parser("run", help="the measurement (parent)"))

    child = sub.add_parser("child", help="one start (launched by the parent)")
    child.add_argument("--db", required=True)
    child.add_argument("--start-index", type=int, required=True)
    child.add_argument("--concurrency", type=int, required=True)
    child.add_argument("--workload", choices=WORKLOADS, required=True)
    child.add_argument("--requests", type=int, required=True)
    child.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    child.add_argument("--gold")
    child.add_argument("--config-sha", default="")
    child.add_argument("--spawn-monotonic", type=float)
    child.add_argument("--warm-timeout", type=float, default=300.0)
    return parser


def add_parent_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The parent's flags, shared with ``python -m agent_session_tools.eval``."""
    parser.add_argument(
        "--db",
        default="~/.local/share/studyloop/eval-clones/bakeoff-bge-20260915/sessions.db",
        help="the eval clone to measure against (read-only)",
    )
    parser.add_argument(
        "--starts",
        type=int,
        default=DEFAULT_STARTS,
        help=f"independent process starts per cell (pre-registered {DEFAULT_STARTS})",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=DEFAULT_REQUESTS,
        help=f"measured requests per start (pre-registered {DEFAULT_REQUESTS})",
    )
    parser.add_argument(
        "--cells",
        type=parse_cells,
        default=DEFAULT_CELLS,
        help="comma-separated concurrency:workload cells (default all four)",
    )
    parser.add_argument("--out", required=True, help="receipt path to write")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--resamples", type=int, default=BOOTSTRAP_RESAMPLES)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--gold", help="gold json (default: the in-repo DEV set)")
    parser.add_argument(
        "--cores", type=int, help="cores the workload sizes itself against"
    )
    parser.add_argument("--child-timeout", type=float, default=1800.0)
    parser.add_argument("--warm-timeout", type=float, default=300.0)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="plumbing proof: 2 starts x 5 requests x cell 1:idle, NOT a gate run",
    )
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        help="measure even when the semantic arm cannot run (the cells will FAIL)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "child":
        return run_child(args)
    if args.mode == "run":
        return run_parent(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "CHILD_SCHEMA",
    "DEFAULT_CELLS",
    "DEFAULT_REQUESTS",
    "DEFAULT_SEED",
    "DEFAULT_STARTS",
    "GATE_FIRST_QUERY_P95_MS",
    "GATE_OVERHEAD_P95_MS",
    "GATE_P95_MS",
    "PRE_REGISTRATION",
    "SCHEMA",
    "WORKLOAD_NAME",
    "Batch",
    "Cell",
    "ChildReport",
    "FirstQuery",
    "McpSurfaceCaller",
    "Timing",
    "WarmReport",
    "add_parent_arguments",
    "aggregate_cell",
    "background_workload",
    "bootstrap_p95_upper_bound",
    "build_stage5_receipt",
    "cell_verdict",
    "leg_schedule",
    "main",
    "overall_verdict",
    "p95",
    "parse_cells",
    "preflight_reasons",
    "run_parent",
    "workload_plan",
]
