# Stage 1 freeze — what may not move while the retrieval layer is tuned

Frozen 2026-09-11 at `main` `f3599df7`, before any product change (plan council 2026-09-11,
astra Q10). Changing any line below is a ruler change: it is never automatic and is recorded as a
new freeze, not an edit to this one.

## Question sets

| set | file | identity | n |
|---|---|---|---|
| Gold DEV | `receipts/gold-v2-dev.json` | sha256 `5632cd2b02a77dbd…` | 91 items · 57 clusters · K 33 / P 29 / R 29 |
| Gold SEALED | owner-held (`~/.local/share/studyloop/knowledge-proof/sealed/`, mode 0400) | sha in `gold-v2-receipt-r2.json` (branch) | 84 · scored **once**, at Stage 4, by the owner |
| Census population | derived, not stored: `messages.role='user'` in visible non-`agent-*` sessions, ≤ 200 words, ≥ 3 content tokens | DB fingerprint `05e354d34748…` | 5,434 eligible · 397 tied (identical text in > 5 sessions) · untied share 0.9269 |
| Toy corpus | `agent_session_tools/eval/toy_corpus.py` (public) | deterministic build | 39 gold items · 12 sessions |

## Scope and exclusions

- Visibility = `context.scope.visibility_sql(conn, "s.id")` — admitted sources are `SUPPORTED_SOURCES`
  (the six harnesses + `study_mentor`); 1,279 retired-source sessions are hidden and must never be
  returned or embedded.
- Gold items `A1-13`, `A1-70`, `A1-71` have no visible gold session; they stay in the denominator.
- Census self-exclusion: the question's own message id and byte-identical re-asks in the same
  session (whitespace-normalised). *Tied* iff `twins + 1 > 5` — a handicap, not an impossibility; tied hits are reported, never credited.

## Metrics and inference

- Primary: **macro recall@5 over K/P/R** (never micro). Reported: MRR@5, crashes by kind, latency p50/p95.
- Paired **cluster** bootstrap, cluster = gold `cluster` (= source session), **10,000** resamples, seed
  **20260910**, percentile CI95. **Established lift** = CI95 lower bound ≥ **+0.05**.
- Census gate: paired delta of hit@5 with cluster = session, **non-inferiority margin −0.01**.
  `hit_rate_untied` credits only hits on untied questions. The census runs only through arms that exclude the question's own message at query time (`supports_exclusion`).
- Receipts: `studyloop.retrieval-eval/v1`; `metrics_sha256` over the stable view (no timings);
  timings are reported, never compared.

## Arms and their commits

| arm | what | pinned |
|---|---|---|
| `mcp` | the real `session_search` through FastMCP `call_tool` — **gates acceptance** | code under test |
| `cli` | `session-query search … --output-format json` as a subprocess | code under test |
| `frozen` | replica of `main` @ `9a48a6ad`'s planner + SQL | frozen copy in `eval/arms.py`; a test pins it equal to the live planner *today* |

## Baselines (the anchors every later receipt pairs against)

| ruler | arm | number | receipt |
|---|---|---|---|
| gold DEV | mcp | macro recall@5 **0.1066** · MRR 0.0837 · crashes **42/91** · p50 18 ms | `stage1-baseline-gold.json` (`metrics_sha256 36c4b59f…`) |
| gold DEV | cli | **0.0000** · crashes 42/91 · 0 rows on the other 49 | same |
| gold DEV | frozen | 0.1066 · identical ranked ids to mcp on all 91 items | same |
| census | frozen (SQL-level self-exclusion) | hit@5 **0.1305** · on the 3,085 questions that ran **0.230** · hit-untied 0.1408 · vocab-gap 198 · crash 2,349 (**43.2%**) · ranking 2,178 (untied 1,955) · tied hits 0 | `stage1-baseline-census-frozen.json` |
| census | ~~mcp~~ **WITHDRAWN** | 0.5256 — the shipped tool returns no message ids, so the question's own message could not be excluded and the number credits a question for finding itself; kept as evidence, never compared | `stage1-baseline-census-mcp.json` |
| cost | — | corpus 51,729 embeddable messages; overflow 21.8 / 15.7 / 18.1 % (MiniLM / bge-small / mpnet); KNN 4.6 ms @384-d, 8.5 ms @768-d | `stage1-model-measurements.json` |

## Guardrails (fail the run, never a footnote)

1. crashes > 0 on the gold set through the `mcp` arm (from Stage 2 on).
2. `cli` and `mcp` disagree on ranked session ids for any gold question (from Stage 2 on).
3. any hidden session returned by any arm.
4. the explicit-syntax golden file `tests/golden/session_search_pre_planner.json` changes.
5. K-stratum paired delta CI95 upper bound < 0 against the frozen arm (an exact-match regression).
6. any receipt whose DB fingerprint differs from its comparison partner's.
