# Arbitration — council review 2 (Phase 2 code: #9 mutations, assess, guidance, guard)

**Date:** 2026-09-16 · **Arbiter:** coordinating agent (unattended) · **Reviewed tree:** `fix/plan-integration-bugs`
@ `b42d3b36` (Phase 2, commits `a4862301..b42d3b36`); seats ran against the brief
`brief-review2-2026-09-16.md` (sha256 `de05925a…`, `review2/manifest.json`). **Fixes landed at:** `18fb4f0f..71d24023`
(F1, F2 — before this arbitration was written) and `b671f69e..b65c6718` (G1–G9, this arbitration). Phase 0 + 1
were accepted in `review-1-arbitration-2026-09-15.md`.

## Seats and verdicts

| Seat | Verdict | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | **ACCEPT-WITH-CORRECTIONS** — four 🔴 (no-op writes, checkpoint readiness bypass, toggle retry claim, two-read `created`), four 🟡, two 🔵 | `review2/seat-openai.gpt-6-astra.md` |
| `grok-4.6` | **ACCEPT-WITH-CORRECTIONS** — one 🟡 (guidance must expose readiness), four 🔵, three 💡 | `review2/seat-grok-4.6.md` |
| `qwen3-coder` | ACCEPT — one 🟡 (skip the gate for readiness-neutral writes on a legacy husk) | `review2/seat-qwen3-coder.md` |

All three seats completed in one run (`finish_reason=stop`; GPT 5.5k, Grok 18.3k, qwen 1.3k output tokens) — no
instrument fault this round. Grok's 40k budget from the review-1 lesson held.

### Method

Every 🔴/🟡 was **reproduced by hand before acceptance** (probe or a RED test seen failing on the tree), or rejected
with a reason. Each accepted finding group is one RED commit (seen failing, count recorded in the message) followed
by one GREEN commit. Two seats naming the same defect are one group. Protected files stayed byte-identical (below).

### Findings and dispositions

| # | Finding (seat) | Sev | Reproduction | Disposition | Landed |
|---|---|---|---|---|---|
| F1 | Duplicate `SetMilestone` / duplicate-only learning-record `RevisePlan` still call `save_plan`, bumping `updated` and re-rendering — CLI "already recorded (no change)" false, `browse()` reorders on retry (GPT) | 🔴 | RED tests advancing `utc_now_iso` past the timestamp's resolution: 4 failed on `d755237b` | **Accept.** Gate first, then save only on an actual change; `_revise` uses the store's `created`; duplicate-beside-a-field-change still one save; empty revision still the Phase-1 touch. Phase-1 assertion `len(saves) == 2` → `1` (it encoded the defect). Spec: "each application saves exactly once" → "byte for byte". | RED `18fb4f0f`, GREEN `979956d4` |
| F2 | `assess(record=True, append_to_plan=True)` re-saves an active-but-unready husk via `evaluate_and_record`, which `SetMilestone`/`RevisePlan` refuse (GPT) | 🔴 | RED: `PlanNotReady` expected before the DB sink; seen failing on `979956d4` | **Accept.** One gate before either sink when the document will be re-saved; preview and DB-only not gated. `PlanNotReady.already_active`; CLI refusal adds "pause it (`studyloop plan status <id> paused`) or repair the blockers" (GPT's legacy-document ruling). Web 422 / CLI exit 1 with nothing in either sink pinned. Grok's 🔵 sibling test `test_revise_learning_record_on_unready_active_is_refused` landed here on a real document. | RED `1381da2e`, GREEN `71d24023` |
| G1 | `ActivePlanGuidance` drops readiness — deviation 12 made active-but-unready a live, unwritable state the ranker would promote blind; #10 cannot see it without a second `inspect` per plan (Grok 🟡 headline; GPT "guidance consistency") | 🟡 | Probe on `71d24023`: husk (topics + milestones, no mission) emitted with `warnings == ()`, no readiness; `SetMilestone` on it `PlanNotReady(already_active=True)` | **Accept — Phase 3 prerequisite.** `ActivePlanGuidance.readiness: ReadinessView` (own field, not folded into `warnings`: a blocker is policy, not a worked-around defect); JSON gains `"readiness"`; the husk stays listed — the ranker decides. One `load_plan` per document pinned. Spec requirement + scenario. | RED `b671f69e`, GREEN `3b23111a` |
| G2 | Two clocks: `target_urgency` from `today`, nested `PlanSummary.days_until_target` from the wall clock (GPT F6 🟡; Grok 🔵) | 🟡 | Probe: pinned `today` → `soon` beside `days_until_target == -400` | **Accept; deviation 3's split clock reversed.** `PlanSummary.from_plan(plan, *, today=None)`; guidance resolves one effective date per call and passes it down. The vacuous `+60 → later` test replaced by `+3 → soon, days == 3`; new test at −1/0/7/8 from a date far from the wall clock. | RED `5eef77a0`, GREEN `9a066ac0` |
| G3 | `match_keys: frozenset` violates D-3 "frozen dataclasses with tuples"; the delta cannot override the decision (GPT F7) | 🟡 | By inspection against `arbitration-plan-round1` D-3 | **Accept.** `tuple[str, ...]`, sorted, de-duplicated; JSON array unchanged. Three Phase-2 assertions in `test_plan_guidance.py` changed `frozenset` → tuple (recorded: they encoded the deviation). Grok's (f) accepted the frozenset without checking D-3; the decision wins. `normalise_match_key` docstring → future tense (GPT §3). Spec updated. | RED `cdc4ab39`, GREEN `534e9595` |
| G4 | Guidance consumed `store.list_plans()` (frontmatter ids) and compared with `list_plan_ids()` (filenames): `alpha.md` saying `id: beta` → entry `beta`, false "alpha could not be parsed", duplicate ids (GPT F5) | 🟡 | Probe on `71d24023`: ids `['beta', 'beta']`, warning names `alpha`; `inspect('alpha')` → `alpha` | **Accept.** Enumerate `list_plan_ids()` once, load each through `_load` (review-1 F5's identity pin); unreadable → one warning, logged; one deterministic order, no cross-scan comparison (also removes the transient false warning under a concurrent edit). Spec scenario. | RED `68be59aa`, GREEN `2707d05f` |
| G5 | `created` inferred from an `inspect` before the mutation — a same-spec writer in the window makes a no-op report `created: true`; `PlanDetail.learning_record_matching` is a second identity copy (GPT F4 🔴; Grok 🔵) | 🔴 | RED with the writer modelled at the seam boundary (`store.record_learning` just before the real `apply`): CLI and MCP both reported `created: true` | **Accept; deviation 5 reversed as the outcome mechanism.** `LearningRecordOutcome(record, created)` on `PlanDetail.learning_record_outcome` (operation-local; `None` otherwise; absent from `to_json_dict` — D-3). `_revise` relays the store's `(record, created)`. CLI/MCP make no preliminary read; response keys unchanged. `learning_record_matching` deleted. Not a transaction: concurrent filesystem writes remain non-atomic (GPT's bound). cli-surface and mcp-server deltas re-specified (they prescribed the racy matching). | RED `6bd2654c`, GREEN `e62487b3` |
| G6 | Route/test/spec claim "a retried request cannot flip a box twice"; the test's second assertion is `done is False` (GPT F3) | 🔴 | By reading: read-invert-write | **Accept as a documentation/spec correction; behaviour unchanged** (legacy toggle contract stays; Grok (i): acceptable for a checkbox). Claim withdrawn from route, module docstring, test docstring and web-ui delta; test renamed `test_legacy_toggle_repeated_requests_flip_twice` and pins the flip-back. Replay safety = desired-state request (`PATCH milestones`, CLI `--done/--undone`); no idempotency-key protocol added. | `de745650` |
| G7 | Guard misses `from studyloop.planning import *`, `importlib.import_module("studyloop.planning")`, and transitive `from studyloop.planning.application import store` (GPT F8) | 🟡 | Probe on `71d24023`: all five planted forms **MISSED** (incl. `from ...planning import *`, `from studyloop.planning.views import readiness`) | **Accept.** Wildcard from the package (absolute/relative); string equal to the whole package; any `FORBIDDEN_PACKAGE_NAMES` name imported from one of the four allowed seam modules. 6 planted cases added (30 tests). Non-literal dynamic imports / attribute access stay out of scope (tripwire, not sandbox). Spec updated. | RED `181ef517`, GREEN `59ab1e23` |
| G8 | Failure matrix untested; both sinks failed rendered as "partially recorded" in CLI and plans panel (GPT F9; and the "correct 'partial' when no sink saved" half of GPT's deviation-7 ruling) | 🔵 | RED: CLI printed `Checkpoint partially recorded — database: failed, document: failed`; JS `partially recorded start checkpoint — …` | **Accept (cheap; Bug B's shape one layer up).** `AssessmentResult.any_sink_saved` (not in JSON); CLI `Checkpoint not recorded — …`, exit 0; JS `Not recorded <phase> checkpoint — …`. Matrix pinned: raising DB still attempts the document; both failed; DB failed with document not requested; preview saved nowhere but complete. No second writer. Specs (cli-surface, web-ui). | RED `2877ed77`, GREEN `def5c561` |
| G9 | `_freeze_rows` stores whatever `isoformat()` returns; nested-row detach and MCP DB isolation untested (GPT F10); pin the delete load→unlink race (GPT) | 🔵 | RED: an `isoformat()` returning a list was stored as-is | **Accept.** Leaf coerced to `str`; `test_evaluation_view_detaches_nested_rows_and_warnings`, `test_lenient_row_leaf_is_immutable_and_json_serializable`, `test_delete_vanished_after_load_raises_not_found`; MCP file gains the `STUDYLOOP_DB` fixture (`6bd2654c`; the suite-wide conftest temp DB uses `setdefault`, so a per-test fixture is the only guarantee against an exported developer path). | RED `a2923315`, GREEN `b65c6718` |
| — | Deviation 12: skip the readiness gate for writes that "cannot change readiness" (`SetMilestone`, learning-record-only `RevisePlan`) on a legacy active-but-unready document (qwen 🟡; also qwen's process finding) | 🟡 | n/a — a policy proposal | **Reject.** Two of three seats rule the other way and the arbiter agrees: D-2 is the *resulting document*, not the field list; a skip-list is a second policy site (which fields affect readiness?) — the thing the seam exists to destroy (Grok); "do not carve out `SetMilestone` or learning-record-only revision" (GPT). The recovery path is real and now tested and worded: pause (`TransitionLifecycle(status="paused")` skips the gate by construction) or repair, then retry — landed with F2 (`71d24023`). Owner-visible consequence recorded below. | — |
| — | Sink status parsed from two warning strings (Grok 🔵) | 🔵 | n/a | **Accept as-is.** The fields cannot disagree with the warnings they derive from; `test_planning_evaluation.py` is frozen so `evaluate_and_record` cannot grow structured outcomes this phase. When that file is unfrozen: return sink enums from the writer, delete the scrape. | — |
| — | No seam test for learning-record-only `RevisePlan` on an unready active document (Grok 🔵) | 🔵 | — | **Accepted, landed** with F2 as `test_revise_learning_record_on_unready_active_is_refused` (real document, zero saves). | `1381da2e` |
| — | `CreatePlan.answers` / `RevisePlan.milestones` live mappings (Grok 💡, GPT inherited hazard) | 💡 | — | **Noted, deferred to #11**: freeze before `create_study_plan` lands or any intent is queued/replayed. Not a demonstrated bypass in the synchronous calls. | Phase 3 hazards |
| — | `PlanApplication` uninjectable (Grok 💡, GPT) | 💡 | — | **Accept as-is**; do not invent a DI seam in #10. Reconsider a small factory only when ranker tests need it. | — |
| — | Parser: milestone concepts regex stops at the first `)` (deviation 13; Grok 💡, GPT) | 💡 | — | **Deferred as a tracked parser bug**, not dismissed: a round-trip regression is due before claiming matching fidelity for parenthesised concepts. Do not "fix" matching to paper over it. | tasks.md |

**Deviations 1–13:** 1, 2, 4, 6, 7 (exit 0), 8, 9, 10 (with G9's hardening), 11, 13 (as a tracked bug) accepted by all
seats and here. **3** accepted for `today=`, its split clock **reversed** (G2). **5 reversed** as the adapter outcome
mechanism (G5). **12 accepted — keep the gate** (qwen's carve-out rejected), with the fixture correction retained and
real legacy-document refusal tests on the seam, Web and CLI.

**Owner-visible consequence (deviation 12, for the record):** a legacy, hand-edited or xTiles-imported active plan
with no mission cannot `plan record` / `plan milestone` / `record_plan_learning` / record a checkpoint into the
document until it is paused or repaired. The CLI now says exactly that and names the command; the guidance read now
shows the blockers on the entry so #10 will not recommend a milestone the seam will refuse to tick. All three seats
flag that this was the one judgment call that needed a human before the CLI/MCP started refusing; it is recorded here
for the owner to confirm or reverse — reversing it is one policy change in `_assert_can_be_active`'s callers, not a
redesign.

### The `ActivePlanGuidance` shape #10 consumes

```
ActiveGuidance(plans: tuple[ActivePlanGuidance, ...], warnings: tuple[str, ...])   # ordered by storage id
ActivePlanGuidance(
    plan: PlanSummary,                    # days_until_target on the SAME effective date as target_urgency
    readiness: ReadinessView,             # ready / blockers / nudges — an unready active plan is listed, not writable
    next_milestone: MilestoneView | None, # first unchecked; None when none or all done
    match_keys: tuple[str, ...],          # sorted, de-duplicated normalise_match_key() over topics + all concepts
    target_urgency: "overdue" | "soon" | "later" | "undated",
    energy_floor: int,                    # raw document value (clamped on write only)
    completion_action: str | None,        # English with the title in it — data, not a prompt
    warnings: tuple[str, ...],            # worked-around document defects
)
```

Rules for #10 from the seats, endorsed: import `normalise_match_key`, equality on the key only; honour collection
`warnings` and per-plan `readiness.ready`; sort every tie explicitly; one parse per document, zero checkpoint-history
calls, no session scan; hostile-content fixtures for titles/topics/milestone text with no lifecycle write.

### Verification after fixes (`b65c6718`)

- Full suite: `uv run --group dev pytest packages/studyloop/tests -q -p no:cacheprovider -x` → **4769 passed, 4
  skipped**, exit 0 (5m35s; 785 deselected by the project's default markers — integration/e2e/live/acceptance/uat).
  Baseline at `b42d3b36` was 4730 passed.
- Plan-filtered (`-k "plan or planning or mcp"`) → 683 passed at `e62487b3`; guard `test_architecture_plan_seam.py`
  → 30 passed (20 planted bypasses rejected, 8 allowed forms clean, 0 violations over the adapters).
- Integration-marked test touching plans (`test_second_brain_template_packaging.py`) + journeys → 37 passed. The
  acceptance/UAT lanes contain no plan journey and need harness binaries; not run.
- JS: `node --test packages/studyloop/tests/js/*.test.js` → **107 pass, 0 fail** (was 106).
- `just lint` → ruff clean, 1022 files formatted; `just typecheck` → pyright 0 errors; `openspec validate
  plan-application-seam` → valid; `openspec validate --specs --all` → 25 passed.
- Protected files: `git diff 3a4f6b01 -- tests/test_web_plans.py tests/test_cli_plan.py
  tests/test_planning_evaluation.py` → **0 lines**; changed `assert` lines in `test_plan_record.py` /
  `test_planning_store.py` → 0. `rg` invariant over the three adapter packages → 0 hits.
- Pre-commit on every commit: ruff, ruff-format, detect-secrets, bandit, trufflehog, pyright — all passed; no secret
  detector fired. Two commits were re-staged and re-created after ruff-format rewrote a test file (no `--amend`).

### Deliberate edits to accepted Phase-1/2 tests (recorded, as review-1 required)

- `test_revise_learning_record_appends_once_and_is_idempotent`: `len(saves) == 2` → `1` (F1; the assertion encoded
  the defect).
- `test_plan_guidance.py`: three `frozenset({...})` assertions → sorted tuples (G3; the assertions encoded deviation
  from D-3); `test_active_guidance_defaults_to_the_real_today` strengthened from `+60 → later` to `+3 → soon` with
  `days_until_target == 3` (G2; the old form was vacuous).
- `test_plan_detail_finds_the_learning_record_a_spec_would_match` replaced by
  `test_record_created_reflects_append_outcome_not_prior_inspection` (G5; it pinned the deleted helper).
- `test_toggle_is_a_set_milestone_behind_the_route` renamed `test_legacy_toggle_repeated_requests_flip_twice` with
  the flip-back pinned explicitly (G6).

### Process finding

The three seats agree on the one item that needed a human: deviation 12. The agent applied the decided invariant
consistently rather than carving an exception, and this arbitration upholds that — but it is a product call about
what a learner can do tomorrow with an imported husk, so it is surfaced above as an owner decision, with the recovery
path tested and worded. Second, smaller: two Phase-2 tests (F1's `len(saves) == 2`, G3's `frozenset`) pinned a
deviation rather than the decision; the RED-commit discipline caught both only because the seats read the tests
against the decisions, not against the code. Convention going forward: a test that pins a deviation must cite the
deviation number in its docstring, so a reviewer can tell "pinned on purpose" from "pinned by accident".

## Gate decision

**Phase 2 (with review-2 corrections F1–F2 and G1–G9) is ACCEPTED as the base for Phase 3.** #10 may consume
`get_active_guidance()` in the shape above; #11 may register the six MCP tools against the seam with the hazards
recorded in the seats' §4 (freeze `CreatePlan.answers` first; `AssessPlan` goes to `assess()`; `DeletePlan` needs an
explicit confirmation flag; copy `record_plan_learning`'s `PlanNotReady` → `ToolError` mapping).

## Still open for the owner

1. Confirm or reverse the deviation-12 ruling (legacy active-but-unready documents must be paused or repaired before
   any write). Reversal is one policy change; the tests that would flip are named in F2/G1.
2. Parser bug (deviation 13): schedule the round-trip regression for parenthesised concepts before #10 claims
   matching fidelity.
3. Unrelated local branches found during clean-up and **not touched** (both carry unmerged commits that exist nowhere
   else): `feat/clean-start` (7 commits ahead of `main`, not on origin) and `feat/harness-tier-promotion` (10 commits,
   not on origin, checked out clean in the worktree `../studyloop-wt/harness-tier`). Deleting either would destroy
   work; decide whether to merge, push, or discard them.

GATE: ACCEPT
