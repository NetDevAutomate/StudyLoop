# Arbitration — council review 1 (Phase 0 + Phase 1 code) and the §5 receipt review

**Date:** 2026-09-15 · **Arbiter:** coordinating agent · **Reviewed trees:** `fix/plan-integration-bugs` @
`ac121874` (code) and `feat/lexical-or-fallback` @ `4e4a8ae6` (receipts). **Fixes landed at:** `f827f69c`
(seam) and `c082b45a` (lexical). Briefs: `brief-review1-2026-09-15.md`, `brief-review-lexical-2026-09-15.md`.

## Code review 1 — seats and verdicts

| Seat | Verdict | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | **REJECT** — mixed PATCH bypasses the resulting-document gate | `review1/seat-openai.gpt-6-astra.md` |
| `qwen3-coder` | ACCEPT (but its own 🔴 is the same atomicity defect) | `review1/seat-qwen3-coder.md` |
| `grok-4.6` | ACCEPT-WITH-CORRECTIONS | `review1-grok-rerun/seat-grok-4.6.md` |

**Instrument fault, recorded:** Grok's first attempt (`review1/manifest.run1.json`) returned empty content
with `finish_reason=length` at 16k tokens — the whole budget went to hidden reasoning on a 90 KB brief. The
re-run at 40k tokens succeeded (21.5k output). Lesson for the runner: large code briefs need ≥ 32k for
reasoning-heavy seats; recorded here rather than silently dropping the seat the owner mandated.

### Findings and dispositions

GPT Astra's REJECT was **verified by hand before acceptance** (probe against `ac121874`):
`PATCH {"status":"active","milestones":[]}` on a ready draft → `200`, stored `active`, `milestone_total 0`,
`ready false`. That is a fourth door; a field-only `{"milestones":[]}` on an already-active plan was a
fifth (pre-existing). Both seats that looked at `patch_plan` found it; Grok called the route comment "false".

| # | Finding | Sev | Disposition | Landed |
|---|---|---|---|---|
| F1 | Compound PATCH = seam transition + second unguarded save; readiness judged on the pre-edit document (mirror: adding the missing milestones in the same request was wrongly refused) | 🔴 | **Accept.** `RevisePlan` brought forward from Phase 2 with `status`; one load → all edits on a candidate → gate on the *resulting* document → one save. `TransitionLifecycle` delegates to `_revise` so there is one gate path. Route builds one intent; `_field_updates` and the route-side `save_plan` deleted; milestone toggle rides `RevisePlan` until `SetMilestone` (Phase 2). | `705ba58b` |
| F1b | Field-only destructive edit on an active plan → active-but-unready | 🔴 | **Accept** (same fix). | `705ba58b` |
| F4 | Conflict precedence: duplicate id + unready active body → 422; spec scenario says 409 unconditionally | 🟡 | **Accept.** `_persist_new`: validate id → probe existence → `PlanConflict` → gate → create; store's race check kept. | `5326b663` |
| F3 | `inspect` calls `store.load_plan_text` outside translation; CLI `plan list` unwrapped; `_fail_for` mapped only `PlanNotFound` (qwen) | 🟡 | **Accept.** `_load_text` translation; `_fail_for` maps all six errors; `list` and `status` routed through it. | `b761141b` |
| F2 | `PlanningBrief` deep-frozen only via `build()`; `_freeze` returned unsupported leaves unchanged | 🟡 | **Accept.** `__post_init__` freezes; `_freeze` recurses and raises `TypeError` on non-JSON leaves. | `dc7de0be` |
| F5 | Import identity precedence implicit; title-slug fallback not implemented (Grok's first 🟡) | 🟡 | **Accept.** explicit id > frontmatter id > `unique_plan_id(title)`; `_load` pins the model to the storage id so no write path files a second document. | `f812500b` |
| F6 | Bug B regression coverage and DB isolation not visible | 🟡 | **Accept.** `tests/test_plan_recording_failures.py` (6 tests, isolated DB); mutation check confirmed 3/6 fail when the boolean is discarded. | `182c82f9` |
| — | Spec: "resulting document" not honoured; 422 shown as detail not body; doc paragraph overbroad | 🟡 | **Accept.** Scenarios for compound PATCH, field-only edit, ready import, precedence; response as `{"detail": {...}}`; GPT's bounded Activation wording. | `37da80e5`, `f827f69c` |
| — | Grok: CLI `plan new --activate` still drafts, gates and writes itself | 🟡 | **Accept, deferred to Phase 2 T2.2** where `new|interview|evaluate|milestone|record` migrate. Not a bypass (same predicate), a second policy site. | tasks.md |
| — | qwen: `ReplaceDocument` id mismatch not explicit | 🟡 | **Reject as stated** — `_replace` pins `plan_id`/`created` from the loaded plan and F5's test `test_replace_keeps_requested_storage_identity_when_frontmatter_disagrees` now pins the behaviour. | — |
| — | GPT: `CreatePlan.answers` caller-mutable | 💡 | Noted; Phase 2 hazard table. | — |

**Deviations 1–6 from Agent A:** 1, 2, 3, 4, 6 accepted by all seats (with F5 tests for 1). Deviation 5
(validate-then-transition-then-edit) **reversed** — it was the F1 mechanism.

**Process finding (RED-commit pyright directive):** GPT recommends line-level suppressions scoped to the
RED commit and removed in GREEN, with the merge criterion being a recorded *pytest* failure, not a type-check
failure; qwen recommends exempting `tests/` from the hook. **Adopted GPT's**: keep tests under pyright; a RED
commit may carry `# pyright: ignore[reportMissingImports]` on the specific import lines; GREEN removes them;
no RED suppressions in a merge candidate. Recorded as a convention for tasks.md.

### Verification after fixes (`f827f69c`)

- Probe: F1 → 422, F1 mirror → 200, F1b → 422, F4 → 409.
- `rg 'readiness\(|save_plan' web/routes/plans.py` → 0 hits. `git diff 3a4f6b01` on the three protected
  test files → 0 lines.
- `pytest -k "plan or planning"` → 399 passed. Full suite → 4629 passed, 4 skipped. `just lint`, `just
  typecheck` → 0.

## §5 receipt review — seats and verdicts

| Seat | Verdict on `adopt: false` | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | Correct; withhold completion sign-off until wording + instrument protections fixed | `review-lexical/seat-openai.gpt-6-astra.md` |
| `grok-4.6` | Correct; the run had power to see the claimed +0.14 transfer and did not | `review-lexical/seat-grok-4.6.md` |
| `deepseek-r1` | Correct; power ≈ Δ0.15 at 80% on this design | `review-lexical/seat-deepseek-r1.md` |

Unanimous that the frozen rule was read correctly and the rejection stands. The substantive agreement
worth recording: the historical +0.142/+0.168 was measured against the pre-Stage-2 planner (shipped then
0.1066, crashing on 42/91); `main`'s shipped planner now scores 0.1700 with 0 crashes, and the narrow widen
candidate 0.1599. The lift the archived branch reported was largely the crash fix, which `main` already has.

| # | Finding | Sev | Disposition | Landed |
|---|---|---|---|---|
| L1 | `judge()` omits the registration's prose "crashes appeared → reject"; no registered-pair check; no finite/ordered-CI validation (GPT, Grok) | 🟡 | **Accept.** Eligibility pre-check (crashes on either arm; registered pair) named ahead of the four frozen clauses, which are unchanged; malformed input raises. Frozen verdict re-derived **byte-identical** (sha256 `604a42b5…`) and pinned by a test. | `39d7564c` |
| L2 | Instrument bindings untested (candidate preserves AND terms; empty content never searches; explicit door bypassed by every variant; patch restored after error; precision denominator; crash → zero precision/MRR) | 🟡 | **Accept.** 9 tests added, all green on first run — no defect found. One finding recorded: FTS5 *rejecting* an explicit string re-plans through the planner in force (same under every arm; not a defect). | `b3777d71` |
| L3 | Receipt accounting: "four hits changed" is three + one rank; latency conclusion outside the registered analysis; two runs conflated; precision guardrail vacuous on a 0.0363 baseline | 🟡 | **Accept**, edits to the `.md` only; frozen `.json` and pre-registration untouched (diff 0). | `63267154` |
| L4 | ADR states PR closed / tag exists before execution; over-broad "prerequisite" and "the store was a cost" claims | 🟡 | **Accept.** Decision separated from execution ("Execution pending; recorded when command output establishes it"); claims bounded to the tested arm and this programme. | `c082b45a` |
| — | GPT §4: a new registration for `or_first_filtered` (+0.0575 DEV, CI crossing zero) would need ≈190 informative clusters for +0.05 at 80% power; do not relabel DEV as confirmation | 💡 | **Accept the reading; no new registration now.** Recorded as a parked hypothesis in the receipt. | — |
| — | GPT: `derived_from.digest_notation` "byte-for-byte" → "unchanged" | 🔵 | **Deferred** — changing derived output would break byte-identity of the frozen receipt's re-derivation. Fix in the next receipt format, not this one. | — |

### Verification after fixes (`c082b45a`)

- Pre-registration and measurement JSON: `git diff d696bc8a` → 0 lines. Golden sha unchanged. `retrieval.py`
  unchanged vs `main`. `adopt: false` in the receipt. Lexical/planner/arms/metrics suites → 139 passed; whole
  package → 2146 passed.

## Gate decision

**Phase 0 + Phase 1 (with review-1 corrections) is ACCEPTED as the base for Phase 2.** The §5 stream is
**COMPLETE as measured** — reject, receipts committed, ADR amended — pending only the owner-executed PR #19
close and archive tag, which the ADR now says are pending.

## Still open for the owner

1. Merge order: `feat/lexical-or-fallback` (touches only `agent-session-tools` + ADR) can merge to `main`
   independently; `fix/plan-integration-bugs` continues into Phase 2.
2. Execute the PR #19 close + `archive/feat-knowledge-proof-2026-09-15` tag; then update the ADR's
   "Execution pending" lines with the command output.
3. Decide whether the parked `or_first_filtered` hypothesis gets a fresh registration with a new gold set,
   or is closed as "exploratory, not pursued".
