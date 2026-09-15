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
    #: Ranked session ids the arm returned -- parity between arms is list-level.
    ranked: tuple[str, ...] = ()

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
            "ranked": list(self.ranked),
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


def precision_values(
    per_item: Mapping[str, ItemScore], items: Sequence[Mapping[str, Any]], k: int
) -> dict[str, float]:
    """Per-item precision@k: gold sessions among the first ``k`` ranked, over ``k``.

    The denominator is ``k`` even when the arm returned fewer sessions -- an
    empty (or crashed) answer is precision ``0.0``, never undefined -- so a
    widen step that returns five sessions to find one gold is scored against
    the same denominator as an ``AND`` arm that returned one (§5
    pre-registration, guardrail 2). Gold ids are read from ``items`` because
    :class:`ItemScore` carries the ranked list but not the ruler's answer key.
    """
    gold = {str(item["id"]): set(item["gold_session_ids"]) for item in items}
    return {
        item_id: len(set(score.ranked[:k]) & gold.get(item_id, set())) / k
        for item_id, score in per_item.items()
    }


def macro_average_values(
    per_item: Mapping[str, ItemScore], values: Mapping[str, float]
) -> dict[str, Any]:
    """:func:`macro_average` over an arbitrary per-item value map (strata from ``per_item``)."""
    by_stratum: defaultdict[str, list[float]] = defaultdict(list)
    for item_id, score in per_item.items():
        by_stratum[score.stratum].append(values[item_id])
    if not by_stratum:
        return {"by_stratum": {}, "macro": 0.0}
    strata = {name: sum(vals) / len(vals) for name, vals in sorted(by_stratum.items())}
    return {"by_stratum": strata, "macro": sum(strata.values()) / len(strata)}


def precision_at_k(
    per_item: Mapping[str, ItemScore], items: Sequence[Mapping[str, Any]], k: int
) -> dict[str, Any]:
    """Macro precision@K over strata (a guardrail, reported beside recall)."""
    return macro_average_values(per_item, precision_values(per_item, items, k))


def _macro_diff_values(
    sample: Iterable[str],
    clusters: Mapping[str, list[str]],
    stratum_of: Mapping[str, str],
    a_values: Mapping[str, float],
    b_values: Mapping[str, float],
) -> float:
    """Macro (over strata present in the sample) paired difference ``a - b``."""
    by_stratum: defaultdict[str, list[float]] = defaultdict(list)
    for cluster in sample:
        for item_id in clusters[cluster]:
            by_stratum[stratum_of[item_id]].append(
                a_values[item_id] - b_values[item_id]
            )
    if not by_stratum:
        return 0.0
    return sum(sum(v) / len(v) for v in by_stratum.values()) / len(by_stratum)


def paired_cluster_bootstrap(
    a_values: Mapping[str, float],
    b_values: Mapping[str, float],
    items: Sequence[Mapping[str, Any]],
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    """Paired cluster bootstrap of a macro-averaged per-item value difference ``a - b``.

    The one resampling scheme every paired interval in the harness uses: gold
    clusters (not items) are drawn with replacement, ``resamples`` times, from
    ``random.Random(seed)``, and the percentile CI95 of the macro difference
    is reported. :func:`cluster_bootstrap` is this over hits; precision and
    MRR intervals pass their own per-item values. ``lower_above_zero`` is the
    §5 adopt clause 1 (D-12) -- weaker than :data:`.MIN_LIFT`, and named so
    the two are never confused.
    """
    clusters = _clusters_of(items)
    names = sorted(clusters)
    stratum_of = {str(item["id"]): str(item["stratum"]) for item in items}
    rng = random.Random(seed)  # nosec B311 - statistical bootstrap, not cryptography
    point = _macro_diff_values(names, clusters, stratum_of, a_values, b_values)
    draws = sorted(
        _macro_diff_values(
            rng.choices(names, k=len(names)), clusters, stratum_of, a_values, b_values
        )
        for _ in range(resamples)
    )
    lower = draws[int(0.025 * resamples)] if names else 0.0
    upper = draws[max(int(0.975 * resamples) - 1, 0)] if names else 0.0
    return {
        "point": point,
        "ci95": [lower, upper],
        "resamples": resamples,
        "seed": seed,
        "clusters": len(names),
        "lower_above_zero": lower > 0.0,
    }


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
    :func:`paired_cluster_bootstrap` over the per-item hits, with the same
    draws in the same order (pinned against a committed receipt by
    ``tests/test_eval_metrics.py``).
    """
    stats = paired_cluster_bootstrap(
        {item_id: float(score.hit) for item_id, score in a_per_item.items()},
        {item_id: float(score.hit) for item_id, score in b_per_item.items()},
        items,
        resamples=resamples,
        seed=seed,
    )
    return {
        "point": stats["point"],
        "ci95": stats["ci95"],
        "resamples": resamples,
        "seed": seed,
        "clusters": stats["clusters"],
        "established": stats["ci95"][0] >= MIN_LIFT,
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
    upper = draws[max(int(0.975 * resamples) - 1, 0)] if names else 0.0
    return {
        "stratum": stratum or "macro",
        "point": point,
        "ci95_lower": lower,
        "ci95_upper": upper,
        # Kept for older readers: the negated lower bound, NOT the upper
        # endpoint of the delta (Stage 4 council, kimi 1 / astra 5).
        "regression_upper95": -lower,
        "upper_at_least_zero": upper >= 0.0,
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
    "macro_average_values",
    "mrr_at_k",
    "non_inferiority",
    "paired_cluster_bootstrap",
    "precision_at_k",
    "precision_values",
    "recall_at_k",
]
