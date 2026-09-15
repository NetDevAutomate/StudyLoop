# Stage 5 lane A2 — ONNX query encoder: artefact pin + parity pre-registration

Written before any parity number was computed. Council amendments this lane implements: goes
first in the A-chain and owns the construction seam (D-2); fp32 first, int8 only as a follow-up
if fp32 misses the 0.5 s load target (D-5); the artefact is pinned before coding (D-6).

**Correction (fix round 1):** the paragraph above originally claimed this receipt was written at
the lane base commit (`18540267`), before `agent_session_tools.onnx_encoder` existed. Git does
not support that: the pin (`embeddings.ONNX_ARTIFACTS`) and the implementation that reads it
(`onnx_encoder.py`) landed together in `e86c3f02`, and this receipt is the commit after it
(`d82618a3`). What D-6 actually gets from this lane is: the pin and the implementation in one
commit (so no implementation-without-a-pin window ever existed on this branch), this receipt
recorded immediately after, and the pinned values independently re-verified against upstream
before this fix round closed (every field in the table below re-checked against
`BAAI/bge-small-en-v1.5`'s own file listing and matched). Treat that re-verification as the
substitute evidence for "pinned before coding" rather than the commit-ordering claim.

## D-6 — the pinned artefact (recorded alongside `agent_session_tools.onnx_encoder`, in the same
commit; independently re-verified in the fix round below)

Checked 2026-09-15 against `BAAI/bge-small-en-v1.5`'s own file listing
(`https://huggingface.co/api/models/BAAI/bge-small-en-v1.5?blobs=true`), the same upstream commit
the torch corpus encoder already reads:

| field | value |
|---|---|
| `hf_name` | `BAAI/bge-small-en-v1.5` |
| `revision` (repo commit) | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| onnx graph | `onnx/model.onnx`, sha256 `828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35`, 133,093,490 bytes (fp32, per the repo's `onnx/` — no separate int8 file at this revision) |
| tokenizer | `tokenizer.json`, sha256 `d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66` (same file the torch/sentence-transformers path loads at this revision — same tokenizer, stated) |
| `tokenizer_config.json` | sha256 `9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3` |
| pooling | CLS token (`1_Pooling/config.json`: `pooling_mode_cls_token: true`) then L2-normalise (`2_Normalize` in `modules.json`) — **not** mean pooling |

Recorded in code at `agent_session_tools.embeddings.ONNX_ARTIFACTS["bge-small-en-v1.5"]`.

## The construction seam (D-2)

`agent_session_tools.query_encoders.get_query_encoder(model, *, backend=None, revision=None,
local_files_only=True, warmup=False, on_phase=None)` is now the one call site every query-side
caller (`retrieval._encoder`, and any future caller) goes through:

* backend selection: argument → `STUDYLOOP_QUERY_ENCODER` → `semantic_search.query_encoder` in
  config → `"torch"`; unknown value raises `ValueError` (`resolve_backend`)
* cache key `(model, backend, revision)`, not model alone (E-A1)
* single-flight construction: one lock per key, tested with 8 threads racing a slow fake encoder
  (`test_single_flight_constructs_once_under_concurrency`)
* a `LoadPhase` enum (`runtime_import | weights | warmup | ready | failed | disabled`) and
  `PhaseEvent`/`PhaseListener` for lane A4, emitted in order with monotonic timestamps, zero cost
  with `on_phase=None`

`OnnxEncoder` (`agent_session_tools.onnx_encoder`) implements the same `Encoder` Protocol the
torch path does (`isinstance(OnnxEncoder(...), Encoder)`), loads the pinned artefact with
`local_files_only` passed through unchanged (never a download during a search), and CLS-pools +
L2-normalises to match the torch pipeline's own pooling config for this model.

## Pre-registered parity acceptance numbers (owner-signed pre-registration O-3; coordinator
synthesis) — stated before any run

| gate | floor |
|---|---|
| top-1 agreement (torch vs onnx ranking) | 100%, modulo documented score ties |
| ordered top-5 agreement | ≥ 95% |
| per-query cosine (diagnostic) | ≥ 0.999 |
| encoder load time, cold and warm | target < 0.5 s (fp32); int8 only pursued if this misses |

Every divergence, when the real run happens, is listed — not summarised away.

## A real, one-shot demonstration run (this lane, scratch cache, not a receipt-grade measurement)

To check the mechanics against the real artefact rather than only fakes, the pinned files were
fetched once into a scratch `HF_HOME` (`/tmp`, outside every repo and config path this lane is
allowed to touch; not committed, deleted after this run) and hashed — both matched the pin
exactly:

```
828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35  onnx/model.onnx
d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66  tokenizer.json
```

Then, offline (`HF_HUB_OFFLINE=1`, `local_files_only=True` throughout), on the 3-sentence fixture
`test_query_encoders.py::TestOnnxTorchParityAcceptance` also uses:

| text | cosine(torch, onnx) |
|---|---|
| "use a window function with PARTITION BY..." | 1.000000 |
| "the deployment pipeline failed because the docker..." | 1.000000 |
| "ranking rows per group is exactly what window..." | 1.000000 |

Load time (single warm-process run, not the Stage 1 cold-process protocol — **not** a substitute
for a receipt-grade cold/warm measurement): onnx encoder construction 0.094 s, a second
construction (warm HF cache) 0.074 s — both already under the 0.5 s target (D-5), so int8 is not
motivated by this sample. `onnx.encode()` on the 3-text batch took 0.004 s against torch's 0.091 s
for the same batch, in the same warm process. This one run is evidence the pipeline is wired
correctly end-to-end; it is not the statistically repeated, cold-process, gold-DEV receipt the
gates above call for — that stays deferred, below.

**Correction (fix round 1) — top-1/top-5 were not actually computed here originally.** The
paragraph that used to sit here said "top-1/top-5 trivially agree at cosine 1.0" — that is an
inference from the per-text cosine number, not a measurement of the ranking gate this lane
pre-registered. `test_query_encoders.py::TestOnnxTorchParityAcceptance` now also encodes a query
("how do I rank rows within each group using a window function") with both arms and ranks the
3-text fixture by cosine to it under each arm independently. Re-running the same scratch-cache
demonstration with that query added:

```
torch ranking: ['use a window function with PARTITION BY...',
                'ranking rows per group is exactly what window...',
                'the deployment pipeline failed because the docker...']
onnx  ranking: ['use a window function with PARTITION BY...',
                'ranking rows per group is exactly what window...',
                'the deployment pipeline failed because the docker...']
```

The two ranked lists are identical (top-1 agreement 100%, and the full 3-item order matches, so
the ordered-top-5 gate is vacuously met on a 3-item fixture) — a real measurement now, not an
inference from the cosine table, though still on the same 3-sentence sample and not the
gold-DEV set.

## What is measured now vs. deferred

**Measured (this lane, network-free unit/mechanics tier — council TEST SHAPE, no model
downloads, no network):**

* Protocol conformance, factory truth table, offline-rule (artefact absent → explanatory
  `RuntimeError`, no socket connection — asserted by patching `socket.socket.connect` to raise),
  hybrid-search degrade-to-lexical with the reason in `retrieval_status.note`, phase-hook
  ordering/monotonicity, and no-import-time-cost (`torch`/`onnxruntime`/`sentence_transformers`
  absent from `sys.modules` after importing `retrieval` and `config_loader`) — all green, see
  `tests/test_query_encoders.py`.
* The parity **machinery** (cosine + ranking-agreement checks) against synthetic vectors
  (`TestParitySmokeMachinery`) — proves the comparison is correct, not that the real model agrees
  with itself.

**Deferred to the coordinator (needs the real artefact fetched by an explicit install/doctor/
backfill action, and — for the gold-DEV run — the owner's Stage 4 clone; council D-5/REC-2, D-26
"do not fabricate pre-change live failures"):**

* A statistically-repeated, cold-process, full-gold-DEV torch-vs-onnx cosine and top-1/top-5
  agreement run (not the single warm-process 3-sentence sample above). The exact test that runs
  the fixture-scale version for real already exists, is committed, and is verified working (see
  the demonstration run above): `tests/test_query_encoders.py::TestOnnxTorchParityAcceptance`
  (marked `integration`). In this lane's default worktree state (no artefact cached) it skips
  with the reason "pinned onnx artefact ... is not in the local Hugging Face cache" — the
  demonstrated skip path; with the artefact cached (as the scratch run above did) it passes for
  real. `uv run --group dev pytest -m integration
  packages/agent-session-tools/tests/test_query_encoders.py -k Parity` after a
  `session-maint`-style warm of the onnx backend will run it.
* Real gold-DEV parity via the existing eval harness (`arms cli-hybrid`, torch vs onnx query
  encoders) — needs the Stage 4 clone, which this lane's worktree does not have.
* Real cold/warm load-time measurement — needs the artefact fetched; the phase-hook events this
  lane adds (`RUNTIME_IMPORT` → `WEIGHTS` → `READY`, with monotonic timestamps) are exactly what
  that measurement would time.

* fp32 vs the 0.5 s target, and therefore whether int8 is in scope at all (D-5) — depends on the
  above.

**Brief deliverable 4 (the in-lane fixture fallback) is PARTIAL, not fully met — say so plainly.**
The brief's fallback for "no Stage 4 clone" is a *committed*, deterministic, few-hundred-chunk
fixture corpus, embedded with the torch encoder in-lane, with both arms compared on it. What
exists instead is the 3-sentence inline fixture in `TestOnnxTorchParityAcceptance` (cosine *and*,
as of this fix round, ranking agreement — see the correction above) plus the synthetic-vector
ranking machinery in `TestParitySmokeMachinery`. That is real evidence at unit scale, but it is
not the few-hundred-chunk corpus deliverable 4 asks for, and it is gated on the artefact being
cached (it skips by default in a clean worktree). A merge on this lane's evidence alone is
relying on: (a) the unit/mechanics tier being green, (b) the one demonstration run above (3
sentences, single process, artefact fetched to a scratch cache and deleted, not receipt-grade),
and (c) the gold-DEV run staying explicitly deferred to the coordinator with the owner's Stage 4
clone. It is not relying on a committed corpus-scale parity comparison, because none exists yet.

## Corpus side (council QA2.2)

Unchanged: `embedding_store._load_encoder` and corpus embeddings stay torch-only. This lane never
touches the write/embed path — only `retrieval._encoder`, the QUERY-side read path.
