"""The gold ruler: load gold v2 DEV and score one arm against every item.

The gold set is a committed JSON receipt (91 items, each with a stratum in
K/P/R and a cluster) and its sha256 is recorded on every receipt, so a
result can never be quoted against a set nobody can reproduce.

Three items are *known unwinnable* by any lexical arm (:data:`KNOWN_UNWINNABLE`).
They stay in the denominator: the ceiling is a property of the ruler, not an
excuse to shrink it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import K
from .metrics import (
    ItemScore,
    crash_count,
    errors_by_kind,
    hit_and_rank,
    latency_percentiles,
    mrr_at_k,
    recall_at_k,
)
from .seam import ArmError, Query, classify_failure

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .seam import Retriever

#: Committed gold DEV set, relative to the repository root.
GOLD_DEV_RELATIVE = Path("docs/architecture/session-memory/receipts/gold-v2-dev.json")
#: Item count of the committed DEV set (a loaded set that differs is a ruler change).
GOLD_DEV_ITEMS = 91
#: Items no lexical arm can win (paraphrase-only evidence); kept in the denominator.
KNOWN_UNWINNABLE = frozenset({"A1-13", "A1-70", "A1-71"})

_REQUIRED_ITEM_KEYS = ("id", "question", "stratum", "cluster", "gold_session_ids")


def default_gold_path() -> Path:
    """The in-repo DEV gold path, resolved from this module's location."""
    return Path(__file__).resolve().parents[5] / GOLD_DEV_RELATIVE


@dataclass(frozen=True, slots=True)
class GoldSet:
    """A loaded gold set plus the identity a receipt has to record."""

    path: Path
    sha256: str
    version: str
    name: str
    items: tuple[dict[str, Any], ...]

    @property
    def n(self) -> int:
        return len(self.items)

    @property
    def strata(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item["stratum"]] = counts.get(item["stratum"], 0) + 1
        return dict(sorted(counts.items()))

    @property
    def clusters(self) -> int:
        return len({item["cluster"] for item in self.items})

    def describe(self) -> dict[str, Any]:
        """The ``gold`` block of a receipt."""
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "n": self.n,
            "strata": self.strata,
            "clusters": self.clusters,
            "version": self.version,
            "set": self.name,
            "known_unwinnable": sorted(KNOWN_UNWINNABLE),
        }


def load_gold(path: Path | None = None, *, require_items: int | None = None) -> GoldSet:
    """Load and structurally validate a gold set, recording its sha256.

    ``require_items`` fails closed on an unexpected count -- pass
    :data:`GOLD_DEV_ITEMS` when the caller means the committed DEV set.
    """
    gold_path = (path or default_gold_path()).expanduser()
    raw = gold_path.read_bytes()
    payload = json.loads(raw)
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{gold_path}: no items")
    for item in items:
        missing = [key for key in _REQUIRED_ITEM_KEYS if key not in item]
        if missing:
            raise ValueError(
                f"{gold_path}: item {item.get('id', '?')} missing {missing}"
            )
    if require_items is not None and len(items) != require_items:
        raise ValueError(
            f"{gold_path}: expected {require_items} items, found {len(items)}"
        )
    return GoldSet(
        path=gold_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        version=str(payload.get("gold_version", "")),
        name=str(payload.get("set", "")),
        items=tuple(items),
    )


@dataclass(frozen=True, slots=True)
class ArmResult:
    """One arm scored over one gold set."""

    name: str
    per_item: dict[str, ItemScore]
    recall: dict[str, Any]
    mrr: dict[str, Any]
    errors_by_kind: dict[str, int]
    crashes: int
    latency_ms: dict[str, float]
    config: dict[str, Any]
    k: int

    def metrics(self) -> dict[str, Any]:
        """The receipt's per-arm metric block (no timings -- those are separate)."""
        return {
            f"recall@{self.k}": self.recall,
            f"mrr@{self.k}": self.mrr,
            "crashes": self.crashes,
            "n": len(self.per_item),
        }


def score_arm(arm: Retriever, items: Sequence[dict[str, Any]], k: int = K) -> ArmResult:
    """Ask ``arm`` every gold question and score the ranked sessions it returns.

    A raised :class:`~.seam.ArmError` is recorded with its ``kind`` and scored
    as a miss; any other exception is classified the same way rather than
    escaping and losing the run.
    """
    per_item: dict[str, ItemScore] = {}
    latencies: list[float] = []
    for item in items:
        query = Query(text=item["question"])
        started = time.perf_counter()
        error_kind: str | None = None
        error: str | None = None
        try:
            hits = arm.search(query, k)
            ranked = [hit.session_id for hit in hits]
        except ArmError as exc:
            ranked = []
            error_kind, error = exc.kind, str(exc)
        except (
            Exception
        ) as exc:  # an arm that escapes the seam is still a measured miss
            ranked = []
            error_kind, error = classify_failure(exc), f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        hit, rr, rank = hit_and_rank(ranked, item["gold_session_ids"], k)
        per_item[str(item["id"])] = ItemScore(
            stratum=str(item["stratum"]),
            cluster=str(item["cluster"]),
            hit=hit,
            rr=rr,
            rank=rank,
            error_kind=error_kind,
            error=error,
            latency_ms=latency_ms,
        )
    return ArmResult(
        name=arm.name,
        per_item=per_item,
        recall=recall_at_k(per_item),
        mrr=mrr_at_k(per_item),
        errors_by_kind=errors_by_kind(per_item),
        crashes=crash_count(per_item),
        latency_ms=latency_percentiles(latencies),
        config=dict(arm.describe()),
        k=k,
    )


__all__ = [
    "GOLD_DEV_ITEMS",
    "GOLD_DEV_RELATIVE",
    "KNOWN_UNWINNABLE",
    "ArmResult",
    "GoldSet",
    "default_gold_path",
    "load_gold",
    "score_arm",
]
