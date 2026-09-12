# Stage 4 record — hybrid retrieval, measured (2026-09-11 → 12)

Pre-registration: `stage4-preregistration-2026-09-11.md` (commit `64651373`, written before any
hybrid number existed). Code under test: `d2263ac5` (hybrid mode), `08de69bf` (efficiency, same
answers; bake-off receipts), `73c50ace`. Every number below is in a committed receipt named in
its row. Three seats review this record after it is committed; their addendum follows it.

## What shipped

`retrieval.search(..., mode=)` — `"lexical"` (unchanged) or `"hybrid"`: the lexical plan exactly
as before to a depth of 50, then the semantic arm (`embedding_store.candidates()`, 100 chunk rows,
collapsed to messages by best distance, hydrated through the **same filter clauses** the lexical
arm uses), fused by Reciprocal Rank Fusion with `k = 60`, no weights, not tuned. Mode resolves
argument → `STUDYLOOP_RETRIEVAL_MODE` → `semantic_search.hybrid` → lexical. Explicit FTS5 stays
lexical. When the arm cannot run (no vectors, no extension, no model, dimension mismatch) the
result is the lexical one and `retrieval_status.note` says why. `retrieval_status.mode` is
`"hybrid"` only when both arms ran; `retrieval_status.semantic` names the model and how many of the
returned hits only the semantic arm found. The harness pins modes through the environment (arms
`mcp`/`cli` lexical, `hybrid`/`cli-hybrid`), and every gold comparison now carries the K-stratum
paired CI. Tests: `tests/test_retrieval_hybrid.py` (12; a paraphrase sharing no word with its
answer is found only by hybrid; a retired-source session with a perfect vector is never returned;
exclusions and source filters bind the semantic arm; fusion order and tie-breaks; every
degradation reason).

## DEV bake-off (selection only — pre-registered rule; `stage4-bakeoff-<model>-gold-quiet.json`)

Each model backfilled into its own `VACUUM INTO` clone of the live database by the Stage 3 job
(`session-maint embed`, no cap); lexical and hybrid through the real `session_search` on the same
clone. Lexical is identical on all three (0.1585 · K 0.303 · P 0.034 · R 0.138 · MRR 0.1305 · 0
crashes — the Stage 2 number, reproduced).

| model | chunks | backfill | hybrid macro R@5 | K | P | R | MRR@5 | Δ macro vs lexical (CI95) | K stratum CI95 lower |
|---|---|---|---|---|---|---|---|---|---|
| **bge-small-en-v1.5** (384-d, 512 tok) | 106,613 | 690 s | **0.2793** | 0.424 | 0.069 | 0.345 | 0.1801 | **+0.1209 [+0.061, +0.190]** | +0.030 |
| all-MiniLM-L6-v2 (384-d, 256 tok) | 174,371 | 477 s (Stage 3) | 0.2564 | 0.424 | 0.034 | 0.310 | 0.1674 | +0.0979 [+0.039, +0.165] | +0.030 |
| all-mpnet-base-v2 (768-d) | 106,613 | ~27 min | 0.2476 | 0.364 | 0.034 | 0.345 | 0.1571 | +0.0892 [+0.023, +0.164] | −0.061 |

**Chosen: bge-small-en-v1.5** — highest point estimate, also the fastest. The two receipts per
model (`-gold.json` under concurrent GPU load, `-gold-quiet.json`) carry the same
`metrics_sha256`: the efficiency commit changed no answer. mpnet caveat: the registry said 512
tokens where the model truncates at 384, so its 385–512-token chunk tails were cut; its number is a
lower bound and the registry entry is corrected (`08de69bf`). H1 was **wrong about where the lift
is**: P (paraphrase) moved from 1/29 to 2/29 for bge and not at all for the others; the lift is in
K (10 → 14 of 33) and R (4 → 10 of 29). On DEV the semantic arm alone (MiniLM) had a P gold
session somewhere in its top-50 messages for 7/29 questions and in its top-5 sessions for 2; the
lexical arm 2 and 1.

## Gates (bge, on its clone, fingerprint `b3721924ce…`, 5,880 sessions / 4,601 visible)

| gate | pre-registered | measured | result |
|---|---|---|---|
| G0 crashes | 0 on `mcp` | 0 on every arm, every run | ✅ |
| G0 cli ≡ mcp | identical ranked ids on the 91, both modes | `stage4-bakeoff-bge-gold-all-arms.json`: `cli_vs_mcp` and `cli-hybrid_vs_hybrid` point 0, CI [0, 0] | ✅ |
| G0 golden file | `tests/golden/session_search_pre_planner.json` unchanged | unchanged (suite) | ✅ |
| G0 fingerprint | paired receipts share a DB | gold and census pairs each on one file | ✅ |
| G2 K non-inferior | K-stratum CI95 upper ≥ 0 | K point **+0.121**, CI95 lower **+0.030** (`hybrid_vs_mcp_K`) | ✅ |
| G3 census | paired hit@5 CI95 lower ≥ −0.01, cluster = session | 5,435 questions, 848 sessions: lexical **0.6155** (3,345) → hybrid **0.6968** (3,787); Δ **+0.0813, CI95 [+0.063, +0.103]**; untied 5,038: +0.0877 [+0.068, +0.111]; transitions both 3,256 · hybrid-only **531** · lexical-only **89** · neither 1,559 (`stage4-census-bge-paired.json`) | ✅ |
| G4 latency | gold DEV through `mcp`, warm, **p95 ≤ 146 ms** | quiet machine (1-min load ≈ 5 on 16 cores), three back-to-back receipts `stage4-latency-bge-run{1,2,3}.json`: hybrid p50 77 / 78 / 77, **p95 150 / 153 / 151 ms**; lexical p95 92 / 88 / 91 (Stage 1: 96). Paired interleaved (273 pairs): median overhead **55 ms**, p95 62 ms | ❌ by 4–7 ms |
| G4 secondary | chunk cap 32 on the chosen model, same gates | 93,570 rows (87.8 %), 303 messages capped; recall **identical** (0.2793, same strata, same CIs); p95 **148 / 148 / 143** (`stage4-secondary-bge-cap32-run{1,2,3}.json`) | ❌ median 148; not met with confidence |
| G5 hidden never returned | zero across every arm and run | 1,279 hidden sessions in the clone; **0** in 5,873 ranked ids across the bge gold receipts; **0** in 2,944 ids from 300 census questions through `hybrid` at k=20; unit test through `candidates()` | ✅ |
| G1 established lift | SEALED, once, by the owner: CI95 lower ≥ +0.05 | **not yet run** — owner-held set. DEV (reported, not the gate): +0.121 [+0.061, +0.190] | ⏳ |

Where the hybrid call's time goes (quiet, bge, 91 queries): encode 12 ms · KNN k=100 over 106k
rows 33 ms · canonical batch 3 ms · hydrate 1 ms · lexical 8–22 ms · fusion < 1 ms → p50 77 ms.
The p95 is set by four or five OR-widened lexical queries that take 90–140 ms on their own, plus
the ~55 ms the semantic arm adds to every call. The brute-force `vec0` scan is the cost that
scales with the corpus; a chunk cap buys 12 % of it.

## Decision — by the pre-registered rule

G4 failed (150–153 ms against 146; the secondary 143–148). The rule says: any gate fails → the
hybrid mode ships **off by default** and the layer is called **"lexical, semantic deferred"**.
That is what this record does: `semantic_search.hybrid` defaults to `false`;
`STUDYLOOP_RETRIEVAL_MODE=hybrid` or `hybrid: true` turns it on for an embedded database. The
recall gates that were measurable here (G2, G3, G5, G0) all passed, and G3 passed by a wide margin
on 5,435 real learner turns. The margin on G4 is 3 % of the gate, on the 87th-slowest of 91 queries;
whether that is a reason to keep a working semantic arm off is the owner's decision, made against
a re-pre-registered gate if at all — not a number this stage moves after seeing it.

## What the census actually shows

The 257 questions with **zero** vocabulary overlap with their own session (the "vocabulary gap"
class) were recovered by the hybrid arm in **2** cases (255 remain). The +442 net hits are almost
all **ranking** recoveries (1,833 → 1,393 ranking misses): the right session shared words with the
question but bm25 ranked it below five others, and the semantic arm lifted it. By source: codex
0.477 → 0.606, kiro_cli 0.519 → 0.625, claude_code 0.806 → 0.840, grok 0.588 → 0.608. Consistent
with the P stratum on gold: on this corpus a question that shares no word with any message in its
session is rarely close to one in embedding space either — the gap is usually a new topic, not a
paraphrase. Semantic retrieval here is a **re-ranker of lexical near-misses** more than a bridge
across vocabularies. R1 ("query without exact phrasing") is met in that sense and not in the other.

## Reported, not gated

- **CLI cold start**: `cli-hybrid` p50 **3.1 s** per invocation with bge (4.2 s with MiniLM; the
  model load dominates) against 142–176 ms lexical (`stage4-bakeoff-bge-gold-all-arms.json`,
  `stage4-bakeoff-minilm-gold.json`); ranked ids identical to the MCP arm item by item in both modes. The MCP process loads once. Before hybrid could be the
  default for the CLI too, the CLI needs a resident encoder or a smaller runtime — a Stage 5 item.
- The census on the clone: lexical 0.6155 vs Stage 2's 0.6154 on the live file (one more eligible
  question, 5,435).
- The alignment report and sidecar contracts held through the bake-off: each clone ended
  `missing 0 / orphaned 0 / stale 0`, sidecar rows = table rows (bge 106,613; sidecar 180.4 MB).
- Under concurrent GPU load the same code measured p50 390 / p95 520 ms (MiniLM,
  `stage4-bakeoff-minilm-gold.json`): the latency numbers depend on the machine's state, the
  recall numbers do not (same `metrics_sha256`).

## What the owner does for G1

The SEALED set is owner-held. On this machine, with the bge clone still present:

```bash
cd packages/agent-session-tools && HF_HUB_OFFLINE=1 uv run --group dev python -m agent_session_tools.eval gold \
  --db <bge clone>/sessions.db --arms mcp,hybrid \
  --gold ~/.local/share/studyloop/knowledge-proof/sealed/<gold file> \
  --out ../../docs/architecture/session-memory/receipts/semantic-layer/stage4-sealed-bge-gold.json
```

The clone lives in the session scratch directory and is reclaimed with the session; to regenerate:
`VACUUM INTO` a clone of the live database, `migrate`, `session-maint embed --db <clone> --model
bge-small-en-v1.5` (about 12 minutes). `hybrid_vs_mcp.ci95[0] >= 0.05` in the receipt is G1.

## Council addendum — three seats, 2026-09-12 00:5x

Brief 38.4 KB (`reviews/2026-09-10-outstanding-work/stage14-hybrid/`). Verdicts: **astra
ACCEPT-WITH-CORRECTIONS** (10 MAJOR, 1 MINOR) · **kimi-k2-thinking ACCEPT-WITH-CORRECTIONS** (3
MINOR) · **qwen3-coder ACCEPT-WITH-CORRECTIONS** (1 "BLOCKING" that confirms the G4 failure was
handled correctly, 2 MAJOR wording, 3 MINOR). Every MAJOR verified at source. The original
sections above are unchanged; this addendum corrects them.

| seat / id | finding | disposition |
|---|---|---|
| astra 2 | **the fusion departed from the pre-registration**: the semantic list was cut to 50 and ranked *before* the shared filters, so an excluded candidate still held its rank (in the census the question's own message is usually semantic rank 1 — every semantic score was 1/(k+r+1)); `max(limit, 50)` could feed more than 50 lexical rows | **CONFIRMED by reading, fixed in `73ee7221`**: survivors are ranked densely after the filters; both lists are cut to exactly 50. Tests `test_survivors_are_ranked_densely_after_the_filters`, `test_both_lists_are_cut_to_the_fusion_depth`. **Everything on bge was re-measured as v2** (below). Gold is unaffected (no exclusions on gold: identical numbers); the census moved by +0.0006 |
| astra 3 | `os.environ.setdefault("HF_HUB_OFFLINE", "1")` does not stop a download when the environment says `0` | **CONFIRMED, fixed**: the search path loads with `local_files_only=True` (`embeddings.get_model`, `SentenceTransformerEncoder`); test with `HF_HUB_OFFLINE=0` set |
| astra 5 · kimi 1 | G2 as written uses the delta CI's **upper** endpoint; the receipt boolean tests the lower with margin 0; `regression_upper95` is the negated lower bound, not the upper | **CONFIRMED, fixed**: `non_inferiority` now reports `ci95_upper` and `upper_at_least_zero`; the old field is kept and labelled. v2 bge K stratum: point +0.121, CI95 **[+0.030, +0.242]**, upper ≥ 0 ✅ (also the stricter lower-bound test). mpnet under the written rule: upper +0.182 ≥ 0 → passes G2; under the receipt boolean it did not — selection unaffected. The owner checks **G1 and G2** on SEALED |
| astra 6 | census pairing unasserted; gold bootstrap correctness unverified from the brief | **ACCEPTED**: `assert_paired` checks identical id sets, sessions, tied flags and twin counts; an independent re-implementation of the gold cluster bootstrap from the receipt's per-item hits reproduces the CI **exactly** ([+0.0605, +0.1895], `stage4-p-stratum-diagnostic-bge.json`) |
| astra 4 | hidden-session evidence covered 300 of 5,435 census questions | **ACCEPTED, closed by measurement**: the paired census now checks every returned session of both arms — v2: **0** hidden in 23,341 (lexical) and **0** in 25,683 (hybrid) returned session ids over all 5,435 questions; 1,279 hidden sessions in the clone; gold receipts 0 in 5,873 |
| astra 7 · qwen 3, 6 | "440 ranking recoveries" is a net figure; provenance unproven | **ACCEPTED, replaced by the cross-tab** (v2): of the lexical arm's **1,833 ranking misses the hybrid hits 537** (29.3 %); of its **257 vocabulary-gap misses, 2** (0.8 %); of its **3,345 hits, 94 are lost** (2.8 %). Net +445. Wording: *primarily re-ranking of lexical near-misses, with minimal vocabulary bridging*. Whether a recovered session entered through a semantic-only message is not attributed |
| astra 8 · kimi 2 · qwen 2 | P: "1 → 2" is net; H1 "wrong" overstated; "gap is usually a new topic" is causal without annotation | **ACCEPTED**: paired P transitions (bge, gold): both 1, hybrid-only **1**, lexical-only 0, neither 27; K: +4 / −0; R: +6 / −0 (`stage4-p-stratum-diagnostic-bge.json`). H1 said the lift would *concentrate* in P; it did not (P +1 of 29, K +4 of 33, R +6 of 29). bge semantic-arm coverage: P gold session in its top-50 messages 6/29, in its first five sessions 2/29 (lexical 2 and 1) — fusion is not suppressing P coverage the arm has. "New topic, not paraphrase" is downgraded to a **hypothesis that needs annotation** |
| astra 9 | mpnet "lower bound" unjustified | **ACCEPTED**: mpnet is a **confounded arm** (512-token chunks against a 384-token model); a corrected bake-off was not run and would be recorded separately |
| astra 10 | provenance: quiet receipts name `d2263ac5` while the efficiency change is `08de69bf`; `metrics_sha256` differs between receipts | **EXPLAINED**: the quiet receipts were generated with the efficiency change applied in the working tree and HEAD still `d2263ac5`; `metrics_sha256` covers the stable view *including the database path*, which changed with the scratch directory — identity of answers is shown by ranked-id comparison, which the v2 all-arms receipt makes item by item (`cli` ≡ `mcp`, `cli-hybrid` ≡ `hybrid`). For SEALED the selected clone is preserved (see below) |
| astra 1 · qwen 4 · kimi 4 | the pre-registration named no repetition or aggregation; "median 148, not met with confidence" is post-hoc language; the margin is 2.7–4.8 %, not 3 %; the secondary's census was not re-run | **ACCEPTED**: results are reported as they are. v2 primary p95 **157 / 153 / 150 ms** (three runs, quiet machine) — all above 146. Secondary (cap 32) **148.7 / 145.5 / 142.6** — one run above the gate, two below; recall identical to the primary. The secondary's G3 was **not** re-measured. The decision (off by default) rests on the primary, which fails in every run. Any future gate names warm-up, load, repetitions, estimator and aggregation *before* it is measured |
| astra 11 · qwen 5 | "87th-slowest" reverses the order; parity should cite the ranked-id field; "520 ms" source | **ACCEPTED**: p95 here is the 87th value ascending, i.e. the **fifth-slowest** of 91; parity is the `per_item.ranked` identity, item by item, in `stage4-v2-bge-gold-all-arms.json`; 520 ms is `stage4-bakeoff-minilm-gold.json` (first MiniLM run, under load) |
| kimi 3 | miss-class definitions absent from the receipt | **ACCEPTED**: `miss_class_definitions` in the paired receipt |

### v2 numbers (code `73ee7221`, bge clone, quiet machine, load ≈ 6 on 16 cores)

| ruler | lexical | hybrid v2 | paired | receipt |
|---|---|---|---|---|
| gold DEV macro R@5 | 0.1585 | **0.2793** (K 0.424 · P 0.069 · R 0.345 · MRR 0.1801) | +0.1209 **[+0.0605, +0.1895]**; K [+0.030, +0.242] | `stage4-v2-bge-gold-all-arms.json` |
| gold DEV, CLI arms | 0.1585 (p50 142 ms) | 0.2793 (p50 **3.17 s**) | ranked ids identical item by item, both modes | same |
| census hit@5 (5,435) | 0.6155 (3,345) | **0.6973** (3,790) | **+0.0819 [+0.0634, +0.1037]**; untied 5,038 questions in receipt | `stage4-census-bge-v2-paired.json` |
| census transitions | | | both 3,251 · hybrid-only **539** · lexical-only **94** · neither 1,551 | same |
| hidden returned | 0 / 23,341 | 0 / 25,683 | | same |
| latency p95 (3 runs) | 89 / 90 / 92 | **157 / 153 / 150** | gate 146 ❌ | `stage4-v2-latency-bge-run{1,2,3}.json` |
| secondary cap 32 p95 | | **148.7 / 145.5 / 142.6** (recall identical) | mixed: 1 above, 2 below | `stage4-v2-secondary-bge-cap32-run{1,2,3}.json` |

The decision stands: **hybrid off by default; "lexical, semantic deferred"**; G1 and G2 on SEALED by
the owner. The v1 receipts (`stage4-census-bge-*.json`, `stage4-latency-bge-run*.json`,
`stage4-secondary-bge-cap32-run*.json`, `stage4-bakeoff-bge-gold-all-arms.json`) are the
pre-correction measurement and stay committed as such.

### For the owner, before SEALED

1. Preserve the selected clone: `bakeoff-bge/sessions.db` + `sessions.vec.db` (1.28 GB + 180 MB) —
   it lives in the session scratch directory and is reclaimed with the session. Copy it to a path
   you own, or regenerate (VACUUM INTO a clone of the live database → `migrate` →
   `session-maint embed --db <clone> --model bge-small-en-v1.5`, ~12 min) and compare its
   `session-maint embed-check` counts (all zero) before the run.
2. Run the command in "What the owner does for G1" against that clone at code `73ee7221` or later;
   read `hybrid_vs_mcp.ci95[0] >= 0.05` (G1) **and** `hybrid_vs_mcp_K.upper_at_least_zero` (G2).
3. Decide whether 150–157 ms against 146 keeps a semantic arm that passed every recall gate off by
   default. If not, that is a **new pre-registration** (gate, warm-up, load, repetitions,
   estimator, aggregation named first), not an edit to this one.
