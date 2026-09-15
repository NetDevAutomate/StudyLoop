# Stage 5 pre-registration — resident-state gates for the default flip (signed 2026-09-15)

Successor to `stage4-preregistration-2026-09-11.md`, written per the Stage 4 rule: reversing
hybrid-off-by-default is "a new pre-registration … not an edit to this one"
(`stage4-record-2026-09-12.md`). Drafted by the coordinator from the 2026-09-15 design council's
envelopes (`reviews/2026-09-15-acceptance-harness/council/ARBITRATION.md`, O-1…O-4); options
selected by the owner in-session on 2026-09-15, BEFORE any gated number was measured. The
unchosen options are kept below as record.

## What this pre-registration governs

1. **Gate L** — the resident-state latency gate that, if passed, permits the A1 flip commit
   (hybrid default ON for the `mcp` and `web` surfaces; `cli` unchanged).
2. **Gate P** — the torch↔ONNX query-encoder parity gate that, together with the load gate,
   permits the A2 flip (`semantic_search.query_encoder: onnx` as the CLI default). The lane-level
   fixture gates are pre-registered separately in
   `stage5-onnx-parity-lane-a2-preregistration.md`; this file governs the gold-DEV run.
3. **Trigger D** — the pre-named condition under which a resident-daemon lane (A3) would be
   opened at all.

Historical numbers (Stage 4's 150–157 ms, the 2.87 s load) are context, not measurements under
this registration.

## Gate L — resident-state latency (OWNER PICK: **L-astra**)

- Surface: the real MCP `session_search` path in a long-lived process (and the web retrieval
  call site if its plumbing differs), on the owner's machine, network off, load recorded.
- Corpus: the bge clone regenerated per the Stage 4 record (2026-09-15 clone:
  `~/.local/share/studyloop/eval-clones/bakeoff-bge-20260915/`, 41,239 vectors / 32,173 eligible
  messages, embed-check all zeros); fingerprint recorded in the receipt.
- Warm-up: encoder loaded to `ready` + one discarded query; warm-up duration reported, excluded.
- Query set: the committed Stage 4 gold DEV queries.
- Design (L-astra): 30 independent process starts × 100 measured requests per cell; concurrency
  1 and 4; idle plus one named repeatable background workload; uncertainty clustered by start
  (bootstrap); one-sided 95% upper confidence bound on p95.
- **Gate**: UB95(p95 wall) ≤ 200 ms AND paired hybrid−lexical p95 overhead ≤ 100 ms, per
  surface/cell; separately, startup-race first-query p95 ≤ 3.5 s including degraded/error
  outcomes. No pooling away a failing cell; every cell reported.
- Outcome rule: pass → the held flip commit lands with the receipt; fail → the default stays
  off, the receipt is committed as-is, and any retry is a NEW pre-registration.
- Unchosen options (record): L-grok — ≥30 reps in one resident process, three back-to-back
  runs; every run p95 ≤ 220 ms OR paired overhead p95 ≤ 80 ms.

## Gate P — query-encoder parity on gold DEV (OWNER PICK: **P-coordinator**)

- Arms: torch `SentenceTransformerEncoder` vs fp32 `OnnxEncoder` (int8 only if fp32 cold load
  > 0.5 s; a separate signing).
- Corpus: the Stage 4 gold DEV queries on the same clone as Gate L.
- **Gate**: top-1 ranked-id agreement 100% modulo documented score ties; ordered top-5
  agreement on ≥ 95% of queries; per-query cosine ≥ 0.999 as a diagnostic (never a substitute
  for the retrieval comparison); every divergence listed in the receipt.
- Load gate: fp32 ONNX cold load < 0.5 s on the owner's machine; per-query encode ≤ 50 ms.
- Unchosen options (record): P-astra — 100% top-1, ≥95% exact ordered top-5, fixed tie policy,
  no recall-gate reduction, cosine ≥ 0.9999; P-kimi — exact ordered top-5, zero top-3 swaps
  (rejected as float-noise-fragile by two seats).

## Trigger D — daemon lane (OWNER PICK: **D-astra**)

A3 is opened only if, after A2's receipts: fresh-process CLI hybrid p95 > 750 ms with a warm
artefact cache, AND profiling attributes the excess to process-local initialisation rather than
KNN/corpus access (a daemon is no remedy for the latter). Unchosen (record): D-grok — p50 ≥
500 ms cold-process warm-cache, or encode ≥ 50 ms, or parity failure.

## Also signed

- **O-2**: the owner accepts that G1/G2 on the SEALED set are unrun; the flipped default is
  documented "provisional pending SEALED"; the SEALED run remains owed and its outcome can
  re-open this registration.
- **O-5**: the UAT tier's additional opt-in is `STUDYLOOP_UAT=1`.
- **O-6**: three independent clean-environment runs per preview harness for a production
  declaration.
- **O-7**: `testacc` defaults to all six harnesses with named skips.

Signed: owner selections recorded in-session 2026-09-15 (see
`reviews/2026-09-15-acceptance-harness/council/ARBITRATION.md`, "Owner decisions"); committed at
the sha this file lands in.
