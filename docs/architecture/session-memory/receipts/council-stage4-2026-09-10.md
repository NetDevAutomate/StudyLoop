# Council record — Stage 4 (PR #18 keep-half; merge decision)

**Date:** 2026-09-10 · **Under review:** `integrate/pr18-keep-half` @ `efd4f3e8` (11 cherry-picked
commits + receipt) against `main` @ `9235ab79` · **Receipt:** `stage4-pr18-keep-half-2026-09-10.md`,
`stage4-keep-half-dev-rescore.json` · **Cadence:** full three seats. Returned: `openai.gpt-6-astra`
**MERGE-WITH-CONDITIONS** (1 BLOCKING, 3 MAJOR, 2 MINOR; 61 s), `qwen3-coder` **MERGE** (2 MAJOR; 9 s).
`grok-4.6` still generating at the time of writing (budget reduced to 12k tokens after two stalls);
arbitrated in the next record if it lands.

## The attribution correction — confirmed by both seats

Both seats independently read ADR-0011:311 and `proof_arms.py::B1_planner` and confirmed: **the +0.142
belongs to replacing the shipped planner with `learning_memory.store.plan_prose_query`, not to
`fb33e2ce`**. F-B0-1 is a *measured defect* in the shipped AND-first path. The inventory conflated the
deficient planner with its experimental replacement, and the plan council (all three seats, this morning)
passed that through. Astra's wording refinement is accepted: "+0.14 was **not achieved, and is not
supported by the cited attribution**" rather than "never achievable".

## Dispositions

| seat / id | severity | finding | disposition | evidence |
|---|---|---|---|---|
| astra F2 | MAJOR | B0 fidelity UNVERIFIED — aggregate equality is not path equivalence; run all 91 through the **native** `session_search` on pinned `main` | **CLOSED by measurement.** `main`'s real `session_search`, called through FastMCP's own `call_tool` (no harness, no adapter): errors on **42/91**, the **same 42 question ids** as the harness B0 arm; the other **49 return zero rows**; B0 and B1 error on identical ids. B0 = 0.000 is the shipped path, not an artefact. | this record; command in the transcript: `PYTHONPATH=<pin>/src … server.call_tool("session_search", …)` |
| astra F3 | MAJOR | error taxonomy sums to 40, not 42 | **CLOSED — receipt truncated to top 3.** Full: backtick 31, `?` 8, `,` 1, `no such column: 9` 1, `no such column: budget` 1 = **42**. Paired identity of failing ids confirmed above. | per-question records in `stage4-keep-half-dev-rescore.json` |
| astra F4 | MAJOR | "gate-green" overstates; check ordinary configured HOME | **CLOSED — mechanism narrowed.** Under the ordinary HOME the mise shim runs (`tmux 3.7b`); only the test's synthetic virgin HOME breaks it. A real mise-managed user is unaffected. Wording corrected to "adjusted-baseline gate with one diagnosed environment red". The test-hermeticity improvement is a hand-off item. | transcript |
| astra F5 | MINOR | literal grep is not clean; record baseline exceptions | **ACCEPT** — the receipt already lists the two pre-existing benign hits by file and matching substring; "clean" means "no newly introduced residue". | receipt §OKF residue proof |
| astra F6 | MINOR | preservation of Stage 8 harvest inputs (dropped `tasks.md`) UNVERIFIED | **ACCEPT** — `031dbab9` stays reachable via the PR branch until Stage 9 tags it `archive/…`; the dropped `tasks.md` is at `031dbab9:openspec/changes/sessionweaver-phase2-retrofit/tasks.md` and is added to Stage 8's harvest input list. | Stage 8 brief amended |
| qwen F1/F2 | MAJOR | attribution wrong; lift not established | **ACCEPT** — same as above. qwen's Q2 ("the correct gate is non-inferiority + positive lift") *redefines the ruler after seeing the result*, which astra explicitly warns against; the ruler's conjunction stands as written. |
| qwen Q3 | — | "confirm `git show 9235ab79:…mcp_server.py` uses `escape_fts_query`" | Done (the native replay above executes exactly that code). |
| **astra F1** | **BLOCKING** | The ruler requires non-inferiority **and** established lift (CI lower ≥ +0.05). Lower bound is **+0.043**, shortfall **0.0074**. Landing this is a *non-inferior integration landing*, not an established retrieval win, and needs an **explicit authorized exception**; "the authority permitted to approve that exception is UNVERIFIED". | **OPEN — owner decision.** The ruler is Andy's (`validation-ruler.md`); neither the coordinator nor the council can waive it. Put to Andy with the three options below. | `stage4-keep-half-dev-rescore.json` → `comparisons.B1_vs_B0.lift.ci95[0]` = 0.0426 |

## What is settled

- Keep-half is OKF-clean (no new residue; `VERSION = 47`), cherry-picked by name with every conflict
  resolution documented, and reproduces PR #18's shipped retrieval path to 17 digits.
- Static gates green; full suite +1 red vs pin, diagnosed and environment-class.
- `main`'s shipped `session_search` **cannot answer any of the 91 DEV questions** today (42 crash, 49
  empty). The keep-half answers 49 of them and hits gold on ~11 % macro; it does **not** fix the 42
  crashes. Both facts go to the hand-off list regardless of the merge decision.
- The plan's "+0.14" gate was mis-specified from a misread of the ADR; the real +0.142 lever is on
  `feat/knowledge-proof` and belongs to the semantic-layer work.

## The one open question (for Andy)

Under the ruler as written, this keep-half is **non-inferior everywhere but not an established lift**
(+0.107, CI95 [+0.043, +0.182]; bar +0.05). Options:

1. **Land it as a non-inferior integration** (recorded exception: the purpose of Stage 4 is to land PR
   #18's non-OKF half so the PR can close, not to claim a retrieval win). Merge `integrate/pr18-keep-half`
   into `main`, close PR #18 with the corrected reason.
2. **Do not land it**; close PR #18 as superseded, keep `main`'s (currently zero-scoring, 42-crash)
   search, and take the whole retrieval question into the semantic-layer plan.
3. **Land it and fix the crash half first**: add an FTS-syntax sanitiser to `_session_search_queries`
   on the integration branch (backtick, `?`, `,`, bare digits), re-score, then merge. Adds a code
   change Stage 4 did not plan for; likely lifts B1 above the +0.05 bar since 42 more questions get
   answered, but that is a prediction, not a measurement.

Recommendation: **option 1**. It is strictly better than `main` on every stratum, carries no OKF, and the
ruler's lift bar was written for *knowledge-layer* claims, not for landing plumbing. Option 3 is the
right *next* piece of work and is cleaner as its own council-reviewed change on `main` after the merge.
