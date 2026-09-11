"""Metric arithmetic for the retrieval rulers: hits, macro averages, bootstrap.

Ported faithfully from ``scripts/knowledge_proof/score.py`` on
``feat/knowledge-proof`` -- the same per-item hit/reciprocal-rank definition,
the same macro-over-strata aggregation, the same paired cluster bootstrap
(clusters resampled with replacement, percentile CI95, fixed seed) and the
same "established lift" rule. The constants live in :mod:`.` and are frozen.

Everything here is pure: no database, no filesystem, no clock. An arm's
crash is *not* hidden by this module -- the ruler records it as a miss with
its :class:`~.seam.ArmError` ``kind`` and the miss lands in the denominator.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from . import MIN_LIFT, NON_INFERIORITY_MARGIN, RESAMPLES, SEED

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

#: Which per-item field an aggregate reads.
Field = Literal["hit", "rr"]


@dataclass(frozen=True, slots=True)
class ItemScore:
    """One gold item scored against one arm.

    ``error_kind`` is set when the arm raised: the item still counts, with
    ``hit = 0``. A crash is a miss, never a skip.
    """

    stratum: str
    cluster: str
    hit: int
    rr: float
    rank: int | None = None
    error_kind: str | None = None
    error: str | None = None
    latency_ms: float = 0.0

    def value(self, field: Field) -> float:
        return float(self.hit) if field == "hit" else self.rr

    def to_dict(self) -> dict[str, Any]:
        return {
            "stratum": self.stratum,
            "cluster": self.cluster,
            "hit": self.hit,
            "rr": self.rr,
            "rank": self.rank,
            "error_kind": self.error_kind,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


def hit_and_rank(
    ranked_session_ids: Sequence[str], gold_session_ids: Iterable[str], k: int
) -> tuple[int, float, int | None]:
    """Score one item: ``(hit, reciprocal_rank, rank)`` within the first ``k``.

    ``hit`` is 1 when any gold session is in the first ``k`` ranks; ``rr`` is
    ``1/rank`` of the first gold session, else 0.0.
    """
    gold = set(gold_session_ids)
    for rank, session_id in enumerate(ranked_session_ids[:k], start=1):
        if session_id in gold:
            return 1, 1.0 / rank, rank
    return 0, 0.0, None


def macro_average(per_item: Mapping[str, ItemScore], field: Field) -> dict[str, Any]:
    """Average within each stratum, then average the strata (macro, not micro)."""
    by_stratum: defaultdict[str, list[float]] = defaultdict(list)
    for score in per_item.values():
        by_stratum[score.stratum].append(score.value(field))
    if not by_stratum:
        return {"by_stratum": {}, "macro": 0.0}
    strata = {name: sum(vals) / len(vals) for name, vals in sorted(by_stratum.items())}
    return {"by_stratum": strata, "macro": sum(strata.values()) / len(strata)}


def recall_at_k(per_item: Mapping[str, ItemScore]) -> dict[str, Any]:
    """Macro recall@K over strata."""
    return macro_average(per_item, "hit")


def mrr_at_k(per_item: Mapping[str, ItemScore]) -> dict[str, Any]:
    """Macro MRR@K over strata (reported, never gated)."""
    return macro_average(per_item, "rr")


def errors_by_kind(per_item: Mapping[str, ItemScore]) -> dict[str, int]:
    """Count crashes by :class:`~.seam.ArmError` kind."""
    counts: defaultdict[str, int] = defaultdict(int)
    for score in per_item.values():
        if score.error_kind is not None:
            counts[score.error_kind] += 1
    return dict(sorted(counts.items()))


def crash_count(per_item: Mapping[str, ItemScore]) -> int:
    """How many items the arm answered by raising."""
    return sum(1 for score in per_item.values() if score.error_kind is not None)


def latency_percentiles(latencies_ms: Iterable[float]) -> dict[str, float]:
    """``p50``/``p95`` with the ported index arithmetic (empty -> zeros)."""
    ordered = sorted(latencies_ms)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0}
    return {
        "p50": ordered[len(ordered) // 2],
        "p95": ordered[max(int(len(ordered) * 0.95) - 1, 0)],
    }


def _clusters_of(
    items: Sequence[Mapping[str, Any]], *, stratum: str | None = None
) -> dict[str, list[str]]:
    clusters: defaultdict[str, list[str]] = defaultdict(list)
    for item in items:
        if stratum is not None and item["stratum"] != stratum:
            continue
        clusters[str(item["cluster"])].append(str(item["id"]))
    return dict(clusters)


def _macro_diff(
    sample: Iterable[str],
    clusters: Mapping[str, list[str]],
    a_per_item: Mapping[str, ItemScore],
    b_per_item: Mapping[str, ItemScore],
) -> float:
    """Macro (over strata present in the sample) paired hit difference a - b."""
    by_stratum: defaultdict[str, list[float]] = defaultdict(list)
    for cluster in sample:
        for item_id in clusters[cluster]:
            a = a_per_item[item_id]
            by_stratum[a.stratum].append(float(a.hit - b_per_item[item_id].hit))
    if not by_stratum:
        return 0.0
    return sum(sum(v) / len(v) for v in by_stratum.values()) / len(by_stratum)


def cluster_bootstrap(
    a_per_item: Mapping[str, ItemScore],
    b_per_item: Mapping[str, ItemScore],
    items: Sequence[Mapping[str, Any]],
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    """Paired cluster bootstrap of the macro recall@K difference ``a - b``.

    Gold clusters (not items) are the resampling unit, because items inside a
    cluster share a session and are not independent. Percentile CI95; a lift
    is *established* only when the lower bound clears :data:`.MIN_LIFT`.
    """
    clusters = _clusters_of(items)
    names = sorted(clusters)
    rng = random.Random(seed)  # nosec B311 - statistical bootstrap, not cryptography
    point = _macro_diff(names, clusters, a_per_item, b_per_item)
    draws = sorted(
        _macro_diff(rng.choices(names, k=len(names)), clusters, a_per_item, b_per_item)
        for _ in range(resamples)
    )
    lower = draws[int(0.025 * resamples)]
    upper = draws[max(int(0.975 * resamples) - 1, 0)]
    return {
        "point": point,
        "ci95": [lower, upper],
        "resamples": resamples,
        "seed": seed,
        "clusters": len(names),
        "established": lower >= MIN_LIFT,
    }


def non_inferiority(
    a_per_item: Mapping[str, ItemScore],
    b_per_item: Mapping[str, ItemScore],
    items: Sequence[Mapping[str, Any]],
    margin: float = NON_INFERIORITY_MARGIN,
    stratum: str | None = None,
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    """Is ``a`` non-inferior to ``b`` -- the CI95 lower bound of ``a - b`` clears ``margin``?

    Same paired cluster bootstrap as :func:`cluster_bootstrap`, optionally
    restricted to one stratum. The frozen margin is
    :data:`.NON_INFERIORITY_MARGIN` (a negative floor on the delta), so the
    equivalent one-sided reading is reported too: a regression whose upper
    bound stays under ``-margin`` passes.
    """
    clusters = _clusters_of(items, stratum=stratum)
    names = sorted(clusters)
    rng = random.Random(seed)  # nosec B311 - statistical bootstrap, not cryptography
    point = _macro_diff(names, clusters, a_per_item, b_per_item)
    draws = sorted(
        _macro_diff(rng.choices(names, k=len(names)), clusters, a_per_item, b_per_item)
        for _ in range(resamples)
    )
    lower = draws[int(0.025 * resamples)] if names else 0.0
    return {
        "stratum": stratum or "macro",
        "point": point,
        "ci95_lower": lower,
        "regression_upper95": -lower,
        "margin": margin,
        "resamples": resamples,
        "seed": seed,
        "clusters": len(names),
        "non_inferior": lower >= margin,
    }


__all__ = [
    "Field",
    "ItemScore",
    "cluster_bootstrap",
    "crash_count",
    "errors_by_kind",
    "hit_and_rank",
    "latency_percentiles",
    "macro_average",
    "mrr_at_k",
    "non_inferiority",
    "recall_at_k",
]
