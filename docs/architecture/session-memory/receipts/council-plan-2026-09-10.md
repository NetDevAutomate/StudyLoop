# Council record — plan "Complete all outstanding StudyLoop work + cleanup" (Stage 1)

**Date:** 2026-09-10 · **Base:** `main` @ `4e588739` · **Seats:** `openai.gpt-6-astra` (1,877 words,
60 s), `grok-4.6` (10,093 words, 459 s), `qwen3-coder` (430 words, 11 s), via the LiteLLM gateway.
Brief 15 KB (under the 30 KB Grok limit). Spend: `reviews/2026-09-10-outstanding-work/council/spend.json`.

**Verdicts:** three-for-three **APPROVE-WITH-CHANGES**. No REJECT. Every constraint the plan set
(no push to main, tag-before-delete, no session-row deletion, Stage 6 gated) was respected by all
seats. The findings are false-finish and data-loss risks, which is what this review is for.

Method: every BLOCKING/MAJOR finding was re-checked against the repo before acceptance. Two seat
claims were **refuted at source** and are recorded as such — the council's value here was
concentrated in the checks, not the assertions, as in prior councils.

## Findings and dispositions

| id (seat) | severity | disposition | evidence checked |
|---|---|---|---|
| F1 astra/grok, F2 qwen | BLOCKING | **ACCEPT** — Stage 4 keep-half must be built by cherry-pick of **named SHAs**, not `rebase -i`; abort if the keep tree contains any `ontology_`/v48/v49 DDL or ontology reader; re-pin B0 on post-scope `main` (or prove the harness bypasses visibility) before the `+0.14` gate. | `main..feat/sessionweaver-phase2-retrofit` = 31 commits; the 13/14 split is **not contiguous** (`348dd6dc` ontology at #3, `fb33e2ce` planner at #23); the drop-half symbol `check_ontology_freshness` is registered by a keep-candidate install commit (`48ce4393`) — so the split needs symbol-level care, confirming F1. |
| F2 astra, F1 qwen | BLOCKING | **ACCEPT** — Stage 6 `.bak` procedure expanded: no `lsof` on DB or the two pins; copy WAL/SHM or `VACUUM INTO`; `PRAGMA integrity_check`+`foreign_key_check`; restore rehearsal to 5,879; export the one `context_concepts` row before DROP; record `.tables`+`user_version` before/after. | live DB `user_version`=47 with v48/v49 objects present (out-of-band); `context_concepts`=1 non-derived row; two `~/.local/share` pins in `git worktree list`. |
| F3 astra/grok | BLOCKING | **ACCEPT with correction** — Stage 9 done-when rewritten (tags are not branches); tag every **current** tip incl. `feat/knowledge-proof`@`5b930dbd` **before** Stage 5 rewrites it; prune a pin only on empty `lsof`/`ps`. **Correction:** grok's "archive/socratic 380 commits" is the REMOTE tip; the **local** `archive/socratic-study-mentor-main` is **6** commits off main (`git rev-list --count` = 6). Both gh-pages tips ARE distinct (`0adb4d5e` not an ancestor of `4104a323`) — that half of F3 holds. | `git merge-base --is-ancestor 0adb4d5e 4104a323` → false; `git rev-list --count main..archive/socratic-study-mentor-main` → 6. |
| F4 astra/grok/qwen | **REFUTE the confound, ACCEPT the commit-target** | The seats said census v2 must run before the planner or be confounded. **Refuted:** `paraphrase_census.py:13` states it queries "the committed prose FTS + phrase-token OR planner" — the census already uses the shipped planner, so Stage 4 does not confound it. **Accepted:** commit `paraphrase-census-v2.json` + sidecar **on `main`**, not only the worktree branch, so Stage 9 cannot lose it. | census script docstring line 13; script imports (no separate planner import — it exercises the shipped path). |
| F5 grok/astra | MAJOR | **ACCEPT** — Stage 5 finish line broadened to `okf|ontology_` (case-insensitive) and scoped to `main` + the post-delete knowledge-proof tree; repo-wide zero not claimed until Stage 9 deletes the OKF-bearing branches. | inventory §5; OKF present on b2/b3/b4/PR#18 until Stage 9. |
| F6 astra/grok | MAJOR | **ACCEPT** — Stage 3 pins the pre-fix pytest fail/skip node-id set; done-when = target test green AND the rest ⊆ pinned set. Confirmed the test is a **real leak check**: its fake shell does `echo "env:$STUDYLOOP_WEB_PASSWORD"` and asserts the value is absent from argv. | `test_session_start.py:315-328`. |
| F7 astra/grok | MAJOR | **ACCEPT** — Stage 8 requires a requirement-id harvest table (every `openspec/specs/*/spec.md` id → ADR/test path or `dropped`) before deletion; `git grep -n openspec` outside the deleted trees empty or historical. | plan Stage 8; 59 tracked files. |
| F8 astra/grok | MINOR | **ACCEPT** — Stage 7 sandboxes the `~/.grok/hooks/` write, records the real local Grok session paths + parse results, migrates only a copy. | `GrokExporter` parses `chat_history.jsonl` (undocumented format, receipt §6). |
| F9 astra/grok/qwen | MINOR | **ACCEPT** — council cadence: full three-seat on Stages 3, 4, 6, 9, 10; single-seat + artefact on 2, 5, 7, 8, escalating to three-seat on any BLOCKING/MAJOR. Keeps spend under the $20 ceiling. | $20 cap; Grok cost scales with brief size (459 s here). |
| qwen "push archive/gh-pages" | MINOR | **FOLD into Stage 9** — the two distinct gh-pages tips are already covered by F3's tag-every-tip rule. | same as F3. |
| astra "scope discovery for all outstanding" | MAJOR | **ACCEPT** — Stage 10 must classify every open PR and tracked task as done/kept/deferred; only PR #18 has an explicit path today. | plan lists PR #18 only. |

## Amendments folded into the stage briefs (authoritative for execution)

- **Stage 2** — run in the `feat/knowledge-proof` worktree on `5b930dbd`; commit `paraphrase-census-v2.json`
  + sidecar **on `main`** (cherry-pick or write-through), not only the branch. Not confounded by the
  planner (already shipped in the census path). Single-seat review.
- **Stage 3** — FIRST, before other stages, as an isolated security fix on `main`. Read
  `test_session_start.py:315` + the launcher that builds the child argv; fix so the password reaches
  the child via environment only. Pin the pre-fix fail/skip node-id set; done-when = target green AND
  rest ⊆ pinned. Full council on the diff.
- **Stage 4** — publish the 14 keep / 13 drop SHAs in a receipt first (from inventory §4a, verified:
  split is non-contiguous). Build keep-half by `git cherry-pick` of named SHAs onto `main`; after each,
  `git grep -nE 'ontology_|okf|user_version|CREATE TABLE.*ontology'` must be empty; resolve the
  `check_ontology_freshness` registration (drop-half symbol referenced by keep-candidate `48ce4393`) —
  keep the MCP-server registration, drop the ontology-freshness check. Re-pin B0 on post-scope `main`
  before the `+0.14` gate, or cite a harness path that bypasses `_visibility_sql`. Full council.
- **Stage 5** — tag `feat/knowledge-proof`@`5b930dbd` and push the tag BEFORE editing the branch.
  Finish line: `git grep -ilE 'okf|ontology_'` on `main` + the post-delete knowledge-proof tree hits
  only receipts/CHANGELOG/superseded-ADR text. Single-seat.
- **Stage 6** — GATED. `.bak` procedure = quiesce (no `lsof` on DB/pins) → `VACUUM INTO` a single file
  (captures WAL) → `integrity_check` + `foreign_key_check` = ok → restore rehearsal `COUNT(*)`=5,879 →
  export the `context_concepts` row to the receipt → DROP only on Andy's explicit confirmation → record
  `.tables`+`user_version` before/after. Full council on the procedure before asking Andy.
- **Stage 7** — sandbox the hook write; record the real Grok session paths + parse results; migrate only
  a copy of `chat_history.jsonl`. Single-seat.
- **Stage 8** — requirement-id harvest table before deletion; single-seat on the table.
- **Stage 9** — tag EVERY current tip `archive/<name>-2026-09-10` (incl. both distinct gh-pages tips,
  local `dev`/`wip`/`rescue`/`codex` tips) and push tags before any delete; `lsof`/`ps` both pins,
  prune only if empty; done-when = `git worktree list` shows main (+ live pins), `git branch -a` shows
  main + origin/main, `git tag -l 'archive/*-2026-09-10'` covers every classified tip. Full council on
  the classification before deletion.
- **Stage 10** — report pytest fail/skip node-ids against the pinned baseline (the 29 env-dependent
  failures accounted for, not hidden by a green claim); post-DROP schema receipt (`user_version` +
  `.tables`); classify every open PR/task as done/kept/deferred; final full council; hand-off = push
  `main` (owner-only) + any pin left live.

## Corrections to the brief (recorded, as the ruler requires)

1. `archive/socratic-study-mentor-main` (local) is **6** commits off `main`, not 380; the 380 figure
   in the brief was the remote tip's count. The local tip is nearly current.
2. Census v2 is **not** confounded by the Stage 4 planner: the census already queries the shipped
   phrase-token OR planner (`paraphrase_census.py:13`), so Stage 2-before-Stage 4 is fine and the
   ordering concern reduces to committing v2 on `main`.

Both corrections were made by re-running the seats' own checks, not by trusting the seat text.
