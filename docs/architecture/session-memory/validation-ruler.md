# Validation ruler v2 — knowledge-layer proof programme

**Pre-registered:** 2026-09-10T00:05Z, revised from v1 after a three-reviewer, two-family
council (receipt: `receipts/council-ruler-review.md`). Frozen by the commit that adds this
file; no threshold may change afterwards. Programme root `main @ ec5fb93d`; build base
`feat/sessionweaver-phase2-retrofit @ 031dbab9`
([PR #18](https://github.com/NetDevAutomate/StudyLoop/pull/18)).

## The question, and what "proven" is allowed to mean

Do the knowledge layers — concept sidecar (`memory_winddown` / `memory_recall`), tier-1
ontology, embeddings — measurably improve what an agent can recall and decide, over the
raw-text FTS5 path that ships today, at an operational cost an agent session can bear?

**Claim matrix.** Each gate licenses exactly one sentence and no other:

| Gate | If it passes, the record may say… | It never establishes |
|---|---|---|
| G1 | "Concept-fused retrieval recalls gold sessions better than the shipped path by ≥ 0.05, on a sealed set" | decision correctness, agent outcome |
| G2 | "Wind-down produces citation-bound concepts whose quotes entail the proposition (audited)" | that the concepts are useful |
| G3a | "The tier-1 graph rebuilds deterministically from source at bounded cost" | that the graph is worth having |
| G3b | "Ontology arms do / do not lift fused recall, and do / do not answer typed queries" | anything about agent outcome |
| G4 | "Embeddings lift paraphrase recall without keyword regression, within budget" | — |
| G6 | "`memory_search` returns current, quote-supported decisions and surfaces conflicts, with ≥ 0.95 precision" | that agents *use* them well |
| G5 | "In a blinded 40-pair pilot, transcripts with the knowledge layers were judged better by Δ" | user outcome; it is a pilot |

"The knowledge layers improve agent decisions" may be written only if G1, G2, G6, the
operational budgets and G5 all pass — and then only with the word *pilot* attached.
"Not established" is an acceptable, recorded outcome. The bar is never lowered to fit.

## Gold set v2 — two sets, one yardstick

- **Size and balance.** n ≥ 150 admitted questions, strata balanced within ±5 %:
  ≥ 50 keyword (K), ≥ 50 paraphrase (P), ≥ 50 relational (R).
- **Clustering unit.** Each question names its **cluster** = the source session (or fact
  cluster when one fact spans sessions). At most two questions per cluster; all
  inference resamples clusters, not questions.
- **Content.** Each item carries: question, stratum, cluster id, gold session id(s), an
  **atomic expected answer**, and ≥ 1 **accepted evidence span** (message id + code-point
  offsets). A hit is a gold session in the top 5; span presence is recorded for audit.
- **Authoring.** A council of ≥ 2 model families, given only session transcripts (never
  retrieval code, the concept store, or this ruler's thresholds), with an explicitly
  adversarial brief: write questions a keyword index should *miss* for P and that need
  two sessions for R. Sessions sampled uniformly from those with ≥ 10 messages; ≥ 50 % of
  clusters drawn from sessions **outside** the 348 PoC wind-down set.
- **Admission.** A second family, shown the answering session and the proposed span,
  must agree the answer is correct and the span supports it. Candidates generated /
  rejected / admitted are counted, with rejection reasons, in the gold receipt.
- **Split.** Admitted items are randomly split 50 / 50 by cluster into **DEV** (builder-
  visible, path given to builder agents, ≤ 4 looks per gate) and **SEALED** (stored
  outside the repository at a path never passed to any builder agent; only its SHA-256 is
  committed; **exactly one scoring run per gate**, performed by the orchestrator after the
  builder declares the candidate final). A gate passes on SEALED or not at all.
- **Corpus digest.** `sha256` over canonical JSON of every gold cluster's session ids,
  message ids, message bodies, `user_version`, `messages_fts` tokenizer, and the
  retrieval configuration in force. Recorded in the gold receipt and every result receipt;
  a mismatch voids the receipt.

## Statistics (fixed for every recall gate)

- Metric: recall@5 per question. MRR@5 reported, never gated.
- **Inference:** cluster bootstrap, 10,000 resamples, of the paired per-question hit
  difference (candidate − comparator); 95 % percentile interval. Wilson intervals on
  single-arm recall are reported as descriptive only.
- **Established lift** = the paired **lower** 95 % bound ≥ **+0.05** recall@5.
- **Non-inferiority** (per stratum, where required) = one-sided 95 % upper bound on
  (comparator − candidate) ≤ 0.05.
- **Aggregate** = macro-average over K / P / R, never the pooled micro-average.
- **Factorial control.** `B0` = the shipped FTS5 path pinned at `031dbab9` (planner and
  tokenizer frozen). `B1` = the same path at the candidate commit. Candidate = `B1 +
  feature`. `B1` must be non-inferior to `B0` on the aggregate; lift is measured against
  `B1`. A regression in `B1` is a finding in its own right and blocks the gate.
- **Fusion contract.** The fused arm's algorithm, per-source candidate budget, dedup rule
  and tie-break are versioned in `receipts/fusion-spec-v<N>.md` before the first DEV
  look; every arm returns exactly five results within the same byte budget.

## Gates

| Gate | Stage | Pass condition (all clauses) | On failure at cap |
|---|---|---|---|
| **G1 Recall** | 3 | On SEALED: fused (B1 + **bound** concepts only; legacy-unbound roots excluded from the candidate arm) macro recall@5 ≥ 0.64; established lift vs B1 ≥ +0.05; K and R non-inferior; P point ≥ 0.20 with P lower bound ≥ B1's P point | record "not established"; Stage 5 still runs |
| **G2 Binding** | 3 | Wind-down re-run (writer model pre-registered below) over the 348 PoC sessions: ≥ 90 % of sessions with ≥ 10 messages yield ≥ 1 `bound = 1` concept; unbound writes = 0; **blinded semantic audit** of a random 100 bound concepts by a second family: ≥ 95 % proposition-entailed-by-quote, full failure taxonomy reported; mutation tests prove rejection of altered body, stale offsets, wrong evidence id, mis-aligned code-point span | record; investigate the writer, never relax the trigger |
| **G3a Ontology build** | 4 | Live-DB rebuild writes `ontology_build_state`; identical `logical_hash` across two full rebuilds **and** a controlled source mutation changes it; fixture graph matches expected entities and edges; violations 0; cold ≤ 5 s (the code's existing `_MAX_COLD_REBUILD_SECONDS`, not a new claim); the 13,384 / 28,698 anomaly resolved by a per-class source-to-row reconciliation receipt | blocks G3b |
| **G3b Ontology value** | 4 | Pre-registered comparator: `H` = the Stage 3 fused arm as frozen at G1 (named by commit). Two separate receipts: (i) `OH − H` on SEALED with the established-lift rule; (ii) a **typed-query benchmark** of 30 council-authored questions only a graph can answer (harness of session, parent of subagent, artifacts touched in ≥ 3 sessions of a project) scored for exact-answer accuracy, provenance and p95 latency. **Stage 6 rule:** build ontology *recall* surfaces only if (i) passes; build ontology *typed-query* surfaces only if (ii) accuracy ≥ 0.90 | skip the corresponding Stage 6 items; record both receipts |
| **G4 Embeddings** | 5 | On SEALED vs the frozen non-embedding fused arm: established lift on P ≥ +0.10 with P point ≥ 0.35; K and R non-inferior; concept index build ≤ 60 s; operational budgets met | record; ship with embeddings disabled |
| **G6 Decision retrieval** | 3 | Held-out decision set (council-authored, ≥ 60 items: current / superseded-by-`corrects` / disputed-by-`contradicts` / no-coverage, ≥ 15 each): `memory_search` top result precision ≥ 0.95 for current items with the supporting quote returned; conflict surfaced (`related_proposals` or `conflict_review`) on ≥ 0.95 of disputed items; abstention or `coverage.limits_reached` on ≥ 0.95 of no-coverage items | record; this blocks the composite claim |
| **G5 Pilot** | 7 | 40 paired openers on real parked / struggled topics, counterbalanced order, fresh context each; both arms identical model, prompt, tool-call, token and time budgets and **both** keep raw FTS — only the knowledge-layer retrieval differs; tool names and metadata stripped before rating; two-family blind rating on a 5-point rubric (grounded in a prior decision · correct prerequisite ordering · no invented history · substantive first question); Krippendorff α ≥ 0.70 required; Wilcoxon signed-rank on the paired score with pre-registered MID = 0.5 | record "not established" |

**Operational budgets** (every enabled arm, measured on the frozen corpus, same machine,
recorded per gate): p50 / p95 end-to-end query latency with p95 ≤ 500 ms and ≤ 2 × B1;
returned payload ≤ the tool's `budget_bytes` default (32 KiB) with no truncated citation;
index storage reported; no paid external API call in the serving path.

**Cheaper honest proxy before G5 (Stage 7 first step):** a single-turn
decision-reconstruction benchmark on 40 held-out items — identical context and token
budget, the agent must name the current decision, its bound quote, its uncertainty, one
prerequisite and one first question; scored for exactness. It screens candidates; it
does not license any outcome claim.

## Build gates (every stage)

GitHub CI every job `success` on the pushed branch (the local sandbox cannot run Chrome or
`ps`; CI is the oracle). `ruff check` + `format --check` clean; `pyright` 0/0/0; archify
`validate --quality showcase` 0 errors / 0 warnings for every touched diagram with a
`deliver` receipt; `mkdocs build --strict` exit 0; contract and parity tests green;
`README.md`, `GLOSSARY.md`, archify spec and CHANGELOG updated in the same PR as the code.

## Stop rules

1. Per gate: ≤ 4 DEV looks; exactly 1 SEALED look.
2. "Improvement" = the DEV paired lower bound rose. Two consecutive DEV looks without
   improvement → stop the stage, write the receipt, move on.
3. Programme caps: **7 elapsed days**; ≤ 400 sub-agent runs for Stage 3 wind-down
   authoring (writer model `claude-sonnet-5`), ≤ 60 council runs overall; **$0 external
   API spend** — any paid endpoint requires approval. Reaching a cap → stop and ask.
4. Never automatic: merge to `main`; force / destructive git; touching
   `.worktrees/b5-real-corpus`; deleting live data; changing this file.
5. Environmental exclusions only when the identical test is green in CI on the same
   commit. Transient CI failure excluded only with a root cause and a green re-run of the
   same commit. CI red for infrastructure reasons > 24 h → stop and report.

## Receipts and authority

Every receipt (`receipts/*.json`) carries: the ruler commit, the candidate commit, gold
SHA-256 (DEV or SEALED), corpus digest, fusion-spec version, and the SHA-256 of the
previous receipt in the chain. A gate **passes** only when (a) the receipt meets every
pre-registered clause mechanically **and** (b) a two-family council review of the receipt
finds no blocking objection to its validity. The orchestrator may override a council
objection only by citing artifact evidence that refutes it, recorded in the receipt.
Council findings are otherwise leads: nothing is acted on until verified against the
artifact.
