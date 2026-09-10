# Council record — Stage 2 (paraphrase census v2 on the six-source corpus)

**Date:** 2026-09-10 · **Cadence:** single seat (`openai.gpt-6-astra`, 1,128 words, 58.6 s, 8,908
tokens) per the plan council's Stage 2 ruling (`council-plan-2026-09-10.md`, F9); escalation to three
seats was reserved for a BLOCKING finding — none was raised. Brief 15 KB; raw review and spend under
the git-ignored `reviews/2026-09-10-outstanding-work/stage2-census/`.

**Verdict:** **ACCEPT-WITH-CORRECTIONS.** Two MAJOR findings, four MINOR. The seat's central point
was about evidence class, not arithmetic: every number in `paraphrase-census-v2.md` re-derives from
the two JSON receipts (Q1: "all numeric cells follow"), but the sidecar's *interpretation* — same
question set, 23 recoveries, zero regressions, corpus unchanged — was inferred from aggregates that
cannot distinguish net from gross. Both stores still existed, so the answer was to **measure**
(`paraphrase-census-pair.json`, `paraphrase-census-duplicates-v2.json`, commit `dacbe46e`) rather
than to soften the wording.

## Dispositions

| id | severity | finding | disposition | measurement |
|---|---|---|---|---|
| F1 | MAJOR | "23 recoveries, zero regressions" is a **net** figure; membership identity and gross transitions UNVERIFIED | **ACCEPT — sidecar corrected by measurement.** Membership IS identical (3,299 questions keyed by `session|sha256(text)|occurrence`, 0 only-in-v1, 0 only-in-v2). But gross transitions are **32 miss→hit and 9 hit→miss**, net +23. Codex's "unchanged" row (515 → 515) hid a 4-in/4-out swap; kiro_cli's +22 was 27 in / 5 out. Composition **+3.09 pt** (v1 rate on the v2 cohort 60.38 % vs 57.29 % overall), retrieval **+0.70 pt** (61.08 − 60.38) — the seat's own hypothetical (60.382 %, +3.096 / +0.697) was exactly right. | `paraphrase-census-pair.json` → `summary.membership`, `summary.transitions_by_harness`, `summary.hit_rate` |
| F1 (mechanism) | — | "retired sessions displaced those questions" needs paired top-5s; corpus changes can shift bm25 without a retired session in the top-5 | **ACCEPT — partly displacement, partly IDF shift.** Of the 32 recoveries, **23** had ≥ 1 retired-label session in v1's top-5 (displacement); **9** had none (bm25/IDF shift from a 1,258-session-smaller index). All **9 regressions** had 0 retired sessions in their v1 top-5 — pure IDF shift. The "23" in the sidecar was coincidentally the displacement count, not the recovery count. | `summary.miss_to_hit_with_retired_session_in_v1_top5` = 23, `…_without…` = 9, `changed_questions[]` |
| F2 | MAJOR | equal archive counts prove count stability, not session identity or content; "same 20 rejects" UNVERIFIED | **ACCEPT — measured, one real change found.** Session id sets identical (4,580 = 4,580). Per-session sha256 over ordered prose `(kind, text)`: **4,579 identical, 1 mismatch** — `codex_rollout-2026-08-20T19-26-40-…` is a still-live Codex rollout re-exported at 13:02Z today (live `updated_at` 2026-09-10T13:02:59Z), 140 → 144 prose events, **16 → 16 learner turns** (no census question added or changed; none of the 41 transitions is from it). v2's 20 rejects **⊆** v1's 41 (the other 21 are retired-label sessions). | `summary.content_stability`, `digest_mismatches`, `summary.rejected_sessions` |
| F3 | MINOR | "1,279 fewer sessions competing" is the archive count; the index shrank by 5,838 − 4,580 = **1,258** | **ACCEPT.** 21 retired-label sessions were already rejected as nothing-citable in v1, so they never entered the v1 index. Correct sentence: *scoping hides 1,279 archive sessions; the FTS index lost 1,258 ingested sessions.* | `ingest-archive-v1.json` ingested 5,838; `ingest-archive-v2.json` ingested 4,580 |
| F4 | MINOR | "`aider` transcripts carry almost no learner prose" is UNVERIFIED (203 ranking misses, 0 vocabulary misses says nothing about prose volume) | **ACCEPT — my explanation was wrong; the real mechanism is worse and more interesting.** The 422 `aider` sessions hold 442 learner turns with **6 distinct texts**: "Tell me about Python decorators" × 203, "Hello" × 103, "Goodbye" × 103, "Q2 follow-up" × 16. They are synthetic fixtures. v1's 204 aider questions were 203 byte-identical prompts each competing against 202 identical siblings — self-retrieval-without-self is *structurally* impossible there. The 0.5 % was a duplication artefact, never a retrieval or adapter finding. | v1 store: `SELECT count(*), count(DISTINCT text) … harness='aider' AND kind='user'` → 442 / 6 |
| F4 (generalised) | — | — | The same structure exists in-scope. Among the 3,299 six-source questions, **475 (14.4 %)** have an identical sibling in ≥ 1 other session and **221 (6.7 %)** in ≥ 5 other sessions (kiro_cli 90, claude_code **78 of 205**, codex 53). The top offender is a kiro-cli compaction prompt in 49 sessions. These are counted as `ranking` misses by the census but no ranker can win them; the honest ranking-miss share is therefore **≤ 33.2 % and ≥ 26.5 %** (1,096 − 221 = 875 of 3,299). | `paraphrase-census-duplicates-v2.json` |
| F5 | MINOR | 21 under-threshold questions unallocated; session counts (14/3/6) conflated with question counts | **ACCEPT.** Residual: **opencode 16** questions (7 hit, 7 ranking, 2 vocab), **pi 5** (3 hit, 1 ranking, 1 vocab), **study_mentor 0** eligible questions (its `mentor-*` sessions have no eligible learner turns). 16 + 5 = 21. Residual hit rate 10/21 = 47.6 %. | `paraphrase-census-pair.json` → `transitions_by_harness.opencode`, `.pi`; `summary.questions_per_harness_v2` |
| F6 | MINOR | "hidden from every read path" conflicts with the ingest receipt's policy "hidden, never deleted; readable by id" | **ACCEPT — wording.** Retired-label sessions are hidden from search, list, discovery and ingest; they remain readable by explicit id (`parse_id` is unfiltered by design, `adapter-scope-2026-09-10.md`). | `ingest-archive-v2.json` → `scope.policy` |
| Q4 | — | "a census after Stage 4 would measure the same planner over the same store" over-claims | **ACCEPT — narrowed.** The evidenced statement is: *Stage 4's later landing does not explain the measured v1→v2 difference* (both receipts' `planner` fields name `learning_memory.store.plan_prose_query (phrase-token OR)`; the census imports it from the branch at `5b930dbd`). Equivalence of any *future* run requires pinning code and store, as every other receipt in this programme does. | both receipts' `planner` field |

## Sentences in `paraphrase-census-v2.md` superseded by this record

The sidecar is a committed receipt and is not edited. The following statements in it are
superseded, with the corrected reading:

1. *"23 ranking misses gone, 0 new misses anywhere"* → **32 recoveries, 9 regressions, net +23**; 23 of
   the recoveries are displacement, 9 recoveries and all 9 regressions are IDF shift.
2. *"with 1,279 fewer sessions competing"* → **1,258 fewer ingested sessions in the index** (1,279 hidden
   in the archive, 21 of which were never citable).
3. *"a label whose transcripts carry almost no learner prose"* (aider) → **a synthetic fixture label: 442
   learner turns, 6 distinct texts, 203 copies of one prompt**; structurally unretrievable, not a prose
   or retrieval finding.
4. *"no session arrived between v1 and v2"* → **no session arrived; one live Codex session gained 4
   assistant-prose events** (learner turns unchanged, no census question affected).
5. *"Ranking remains the dominant miss class (33.2 %)"* → **ranking is 26.5 %–33.2 %**; at least 221 of the
   1,096 "ranking" misses (6.7 % of all questions) are identical-text duplicates that no ranker can win.
   Ranking is still the largest *addressable* class (875 questions vs 188 vocabulary-gap), and the 70 %
   target is still not met (61.1 %), so the ranking pass remains the next lever — but its ceiling on this
   corpus is 100 % − 6.7 % ≈ 93 %, not 100 %, and a de-duplication or query-side "is this a boilerplate
   turn" filter is a cheaper first cut than a better ranker.
6. *"hidden from every read path"* → **hidden from search, list, discovery and ingest; readable by
   explicit id.**

Unchanged and confirmed by the paired measurement: identical question membership (3,299); identical
per-harness `n` and vocabulary-gap counts; the headline 57.29 % → 61.08 %; the composition-dominates
reading (+3.09 pt of the +3.79 pt).

## Stage 2 finish line

- `paraphrase-census-v2.json` + sidecar committed: `feat/knowledge-proof` `71b19025`, `main` `80e36f1b`
  (+ v1 receipts carried to `main` in `d1e7a123` so the sidecar's target exists there).
- Paired + duplicates censuses and their receipts: `feat/knowledge-proof` `dacbe46e`; receipts carried
  to `main` with this record.
- Headline deltas restated with their decomposition above. Council: ACCEPT-WITH-CORRECTIONS, all six
  corrections measured and recorded here; no escalation required.

## What this changes downstream

- **Stage 4's `+0.14` gate** is unaffected by this stage (that gate is on the DEV gold set with the
  knowledge-proof harness, not on the census), but the plan council's F1 stands: B0 must be re-pinned
  on the scoped corpus before the gate is read.
- **Ranking pass (later plan, not this one):** its brief must exclude the 221 duplicate-text questions
  from the target denominator or state the 93 % ceiling, and should measure the paired transitions,
  not the aggregate — the 4-in/4-out swap hidden inside codex's flat 0.654 is exactly the kind of
  change an aggregate finish line would miss.
- **`study_mentor`** contributes 0 eligible learner turns on this corpus; it is in scope as a source
  but cannot be measured by this census.
