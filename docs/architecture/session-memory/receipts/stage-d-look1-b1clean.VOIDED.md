# stage-d-look1-b1clean.json — VOIDED

Voided by the receipt council (seat gpt-5.6-terra, run `4ed818c7`) for provenance: the Stage 2
gold receipt's hashes are non-reproducible (ruler-amendment-002, F3/F4). The seat re-derived the
receipt's statistics exactly; they were superseded by `stage-d-look2-planner-control.json`, which
reproduces B0/B1/B1_clean identically and adds the `B1_planner` control.

The receipt file itself is **byte-identical to its commit `ca55c653`** (sha256
`ec9d6576028140fa…`). It was briefly edited in place to carry this notice (commit `f5c1597d`),
which the second council seat (deepseek-3.2, run `74685923`) correctly flagged as breaking the
chain's intent; the edit was reverted and the notice moved here. Rule from here on: **a receipt is
never mutated after commit — annotations live in a sidecar.**

Counts as DEV look 1 of ≤ 4 for the G1 family.
