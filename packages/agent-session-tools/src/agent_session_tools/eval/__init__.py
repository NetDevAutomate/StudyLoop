"""Retrieval evaluation harness: the instrument the retrieval layer is measured with.

Three tiers share one seam (:mod:`.seam`):

* **unit** -- metric arithmetic, bootstrap determinism, ceiling logic, receipt
  schema; hermetic, no model, no live database;
* **integration** -- arms driven end-to-end against a temporary database
  (the MCP arm through FastMCP ``call_tool``, the CLI arm as a subprocess);
* **validation** -- the two rulers scored against a real database and written
  as committed receipts: the gold DEV set (:mod:`.gold`) and the paraphrase
  census over the learner's own turns (:mod:`.census`).

The ruler constants below are frozen (plan council 2026-09-11, receipt
``semantic-layer/plan-council-2026-09-11.md``). Changing them is a ruler
change and is never automatic.
"""

from __future__ import annotations

#: Rank cut-off for every recall / hit metric.
K = 5
#: Paired cluster bootstrap: resamples and seed (validation-ruler.md v2).
RESAMPLES = 10_000
SEED = 20260910
#: A lift is "established" only when the CI95 lower bound clears this.
MIN_LIFT = 0.05
#: Non-inferiority margin for the census paired delta (plan council F7).
NON_INFERIORITY_MARGIN = -0.01
#: Receipt schema identifier written by :mod:`.receipt`.
RECEIPT_SCHEMA = "studyloop.retrieval-eval/v1"

__all__ = [
    "K",
    "MIN_LIFT",
    "NON_INFERIORITY_MARGIN",
    "RECEIPT_SCHEMA",
    "RESAMPLES",
    "SEED",
]
