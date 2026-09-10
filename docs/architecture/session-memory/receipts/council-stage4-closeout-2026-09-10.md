# Stage 4 close-out — sidecar to `council-stage4-2026-09-10.md`

**Date:** 2026-09-10 22:57–23:00 BST.

## The BLOCKING item is resolved by the owner

Council record F1 (astra, BLOCKING) held that landing the keep-half is a *non-inferior integration*, not
an established retrieval win (CI95 lower +0.043 < the ruler's +0.05), and that only the ruler's owner
can grant that exception. Andy's directive at 22:57, verbatim:

> "As OKF is no longer a part of the solution, OKF should be fully removed - leaving no remittance as
> part of the merge."

Read as: **proceed with the merge**, with the hard condition that the merged tree carries **no OKF
remnant**. The ruler exception is therefore recorded as **owner-granted by merge directive**, with the
lift claim stated as it is (+0.107, CI95 [+0.043, +0.182], non-inferior on every stratum, **not**
established under the ruler). No retrieval win is claimed.

## What landed

- `main` fast-forwarded `9235ab79` → **`48900c3d`** (13 commits: 11 cherry-picks, the Stage 4 receipt,
  the council record). Tree byte-identical to the tested integration tree
  (`git rev-parse HEAD^{tree}` = `integrate/pr18-keep-half^{tree}`).
- [PR #18](https://github.com/NetDevAutomate/StudyLoop/pull/18) **CLOSED** 21:59:14Z with the corrected
  reason (keep-half landed by named cherry-pick; OKF half dropped by owner ruling; attribution
  correction; 42-question FTS crash left open; branch tip to be tagged before deletion).

## The zero-remnant condition, proven over the whole tree

`git grep -ilE 'okf|ontolog|concept_sidecar|memory_winddown|check_ontology'` over the **entire** tree
(not only `packages/`), excluding the receipts directory (which documents the removal) and the two
pre-existing benign hits (minified vendor identifier `oKf`; "ontology services" as a learner topic in an
e2e fixture):

| tree | matching files |
|---|---|
| `main` before merge (`9235ab79`) | 6 |
| `integrate/pr18-keep-half` (`48900c3d`) | 6 — **identical set** |
| `main` after merge (`48900c3d`) | 6 — identical set |

**The merge introduced no OKF/ontology mention anywhere.** The six pre-existing files —
`.gitignore`, `docs/architecture/session-memory/GLOSSARY.md`, `…/README.md`,
`…/verified-architecture.architecture.json`, `docs/session-memory.md`, `scripts/plan_agent_harness.py`
— are `main`'s own residue and are exactly **Stage 5's scope**, to be removed next under the same
directive. `packages/` is clean; `migrations.py` `VERSION = 47`.

## grok-4.6 — second non-delivery

Stage 4 review: `finish_reason: length` at 12,000 completion tokens after 363 s; the text is an
investigation narrative ("I'll locate the receipt, ADR, inventory…") with **no VERDICT line and no
findings table**. Same failure mode as its Stage 1 review (10,093 words, most of it narration) and its
Stage 3 attempt 1 (20 min, nothing). Two of three stages without a usable verdict. Disposition: the seat
is **replaced for the remaining stages** by `deepseek-r1`-class alternatives being excluded (recorded
unsound answers), so the third seat becomes **`kimi-k2-thinking`** (gateway-listed, different family from
GPT and Qwen). Astra and qwen have delivered on every stage.

## Carried to the hand-off list (Stage 10)

1. `main`'s shipped `session_search` crashes on 42/91 natural-language DEV questions (FTS5 syntax:
   backtick ×31, `?` ×8, `,` ×1, bare digits ×2). Not fixed by the keep-half. Highest-value next change.
2. The real +0.142 lever is `learning_memory.store.plan_prose_query` on `feat/knowledge-proof` —
   semantic-layer work, not this plan.
3. `test_fresh_install_scope.py::…virgin_home` fails under a mise-shimmed tmux with a virgin HOME
   (environment class); make the scope test hermetic about tmux.
4. `env=None` when `--lan` has no password inherits the parent's `STUDYLOOP_WEB_PASSWORD` if set (Stage 3
   astra Q3) — a contract question, not a leak.
5. Gold DEV items `A1-13`, `A1-70`, `A1-71` are unwinnable after scoping; a v3 gold set is the evaluation
   owner's call before any future look.
