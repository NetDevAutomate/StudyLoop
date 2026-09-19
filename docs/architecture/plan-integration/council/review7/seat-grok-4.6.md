# Council review 7 — item 5 (D-F)

## 1. Verdict

**ACCEPT.** Both halves of the owner's row-3 "no" are implemented, tested against the live struggle collector, documented, and process-clean (RED→GREEN, no new writer, golden byte-identical, matched full-suite delta = the new tests).

## 2. Findings

### Council question (design §5 decision 1) — plan-independent deferral is the right scope

The finding is RSD, not plans: recommending hands-on repair of a *live* struggle on a low-energy day compounds the struggle whether or not a plan names it. Gating `_defer_repairs` on `plans.matchable` would leave the original "no" unfixed for every no-plan learner. The body-double half correctly requires a ready active plan ("sit with the plan"); the repair half must not.

D-5's rewording to "no plan **and nothing deferred**" is the honest contract. The golden world defers nothing and is unchanged. A no-plan learner whose live struggle is deferred gets `energy_deferred_repairs` plus the starter — listed, not recommended — which is what "defer like new work" means. Do not reverse this.

A same-concept gentle recall as a no-plan floor is a follow-on, not a correction (see 🔵 below).

### (a) Scope — no defect

`DeferredRepair.plan_id` / `plan_title` are `None` when unmatched; `_defer_repairs` calls `plans.first_match` only to *name* the entry. `test_body_double_never_appears_without_an_active_plan` pins the no-plan path. Spec delta, `docs/study-plans.md`, `docs/cli-reference.md`, and design §5 all say the same words. Consistent.

### (b) Demand derivation

`_energy_demand` matches amendment 1: `learning`→`low`; non-`struggling` kept only for weak teach-back→`medium`; `struggling` with `seen is None or seen <= 14`→`high`; older `struggling`→`medium`. Unparseable `last_seen` is the cautious side the finding asked for.

`assessment_recorded_at` (`last_seen = max(recorded_at of current reports)`) is the right recency basis: live-ness is "when they last *reported* struggling," not last session contact. A 3-day `struggling` with a decent teach-back is still a live struggle (RSD); a 20-day `struggling` is not. Age dominates teach-back for the `struggling` class — correct.

A `struggling`+weak-teach-back row does **not** deserve `high` regardless of age. Live-ness is the RSD trigger; a stale struggle with a weak score is the medium class the design named.

💡 **`medium` (4) and `high` (6) are behaviourally identical at all three `ENERGY_CAPABILITY` values.** `low` (3) defers both; `medium` (6) and `high` (10) carry both. Nothing in the energy scale sits between 3 and 6, so `required_capability` 4 vs 6 never changes ranking. The class is still worth carrying: renderers and `DeferredRepair.reason` distinguish "a live struggle" / "an older struggle" / "a weak teach-back," which is the information the learner needs. Do not collapse the classes. Do not pretend 4/10 is a real gate — if a fourth energy level is ever added, the 4 becomes load-bearing. No JSON change required; a comment on `ENERGY_DEMAND_CAPABILITY` would be enough.

🔵 **`LIVE_STRUGGLE_DAYS` boundary and the unparseable path are untested.** `test_live_struggle_repair_defers_at_low_energy_like_new_work` uses 3 and 20 days only.

- Fix: plant `days_ago=14` (high) and `days_ago=15` (medium); plant one `struggling` row with `last_seen="not-a-date"` and one with `last_seen` missing; assert `energy_demand`.
- RED: `test_live_struggle_window_is_fourteen_days_inclusive` and `test_unparseable_last_seen_on_struggling_is_live`.

14 days is a reasonable live window; the owner can override when scoring 3b. Inclusive `<=` matches the spec's "within 14 days."

### (c) Deferral mechanics — correct

`_defer_repairs` keys on `metadata["energy_demand"]` ∈ `ENERGY_DEMAND_CAPABILITY`, so due recall is untouched even with `confidence == "struggling"` — pinned by the second half of `test_recovered_repair_stays_eligible_at_low_energy`.

Same concept due *and* struggling: rank the due row, defer the repair. Right. They are different actions (recall vs hands-on). Suppressing the deferred line when the concept is already primary would hide that the *repair* is what was refused. The CLI printing the concept twice is honest, not a bug.

A deferred repair does not represent a milestone (`_defer_repairs` runs before `plans.milestone_candidates`). Right. The synthesised milestone is `action_type="conversation"` — talk about it, the cheap form — and only when the milestone is itself within the floor. That is not a side door for work the energy cannot carry. Hands-on repair stays deferred.

🔵 **Decision 5 is untested.** No test plants a live struggle on an *eligible* next-milestone concept (floor ≤ 3) and asserts a `study_plan:` conversation is synthesised after the repair is stripped.

- Fix: plan with `energy_floor=3`, next milestone concept `window frame`, plant `_struggle("window frame", days_ago=3)`, `energy="low"`. Assert the struggle is in `energy_deferred_repairs`, primary (or an alternate) is `source.startswith("study_plan:")` / `action_type=="conversation"`, and no ranked hands-on on that concept.
- RED: `test_deferred_repair_does_not_represent_an_eligible_milestone`.

Code order in `build_now_plan` is already correct; this is a pin, not a behaviour change.

### (d) Body double as candidate

Base 30 + 12 bias = 42 < `MILESTONE_BASE_SCORE` 48 at *base*. After the low-energy hands-on penalty a practice candidate scores 48 − 14 = 34 < 42, so the proposal outranks it.

💡 **The inversion is acceptable — do not lower `BODY_DOUBLE_BASE_SCORE`.** The finding is "do not recommend hard work at low energy." A conversation that advertises no new material and no repair *should* beat a penalised hands-on practice. The invariant "any real candidate outranks it" is true at base and after every adjustment except the deliberate low-energy hands-on/visual penalty. Document that exception on `BODY_DOUBLE_BASE_SCORE`; do not "fix" it. A due, a continuity (58), a transfer (52), a modality-matched practice (48+18), or a plan-related practice (48+12−14=46) still win.

`concept = "Sit with <title>"` as a `_candidate_keys` member is harmless: it will not equal a milestone concept, and the topic (plan's first topic) is the intended match. `plan_refs` are set explicitly, so a second ready plan is referenced even when its topic differs.

🔵 **Two ready plans are untested, and the CLI door names only the first title.** `_body_double_candidate` sets `concept="Sit with your plans"`, `titles=" and ".join(...)`, `evidence_command` from `named[0]` only. Starting one session is right; naming only the first in the command is the compromise. Pin it.

- RED: `test_body_double_with_two_ready_plans_names_both_and_opens_the_first` — two ready plans, nothing plan-related fits; assert concept, reason contains both titles, command uses the first, `plan_refs` has both `(id, None)`.

`estimated_minutes` 25 (conversation default) is fine.

### (e) Rule 8 — not a filter in disguise

`test_preserves_one_plan_backed_action_when_energy_allows` now expects `["due 0", "due 1", "Sit with Sql Windows"]` at low energy. Rule 8 has always replaced the *last* alternate with a plan-backed action; the primary is untouched. Previously nothing eligible existed below the floor, so three unrelated dues filled the slots. Now the eligible plan-backed action is the body double — it advertises no work the energy cannot carry, which is the property the docstring protects. `due 2` lost the slot the same way a synthesised milestone takes it at medium. Right.

### (f) Honest starter — defensible for this item

`_starter_candidate(..., after_deferral=True)` changes only the reason. The action stays "one tiny recall loop" on the first configured topic. For a no-plan learner with only live struggles that is a weaker offer than a `recall` on the deferred concept, but the finding said *defer* the live repair, not convert it into a gentle review. The starter is the existing empty-set floor; lying that "no learning evidence found yet" was the thing that had to change. `test_body_double_never_appears_without_an_active_plan` pins `"defer" in reason` (loose — see (i)).

🔵 A same-concept gentle recall as a no-plan floor is a follow-on, not a merge gate. If taken: synthesise `action_type="recall"` on the deferred concept at starter-level score when `deferred_repairs` is non-empty and `not plans.matchable`. RED: `test_no_plan_live_struggle_offers_gentle_recall_not_the_generic_starter`.

### (g) Renderers

CLI `_render_plan`: door label swaps on `primary.source == "body_double"`; one escaped line per `energy_deferred_repairs`; plan-less repairs omit the title prefix. Recap `_plan_context`: one sentence per repair; reachable at low energy only (default recap energy is medium, as the hard rules say); pinned through `_plan_context` directly. Today: `deferredRepairNotes`, `viewForAction` → `body-double`, markup `x-show` includes the new length. All match amendment 2/3.

🔵 **Web door does not pre-fill the plan title.** `startAction` only `nav.go('body-double')`; the Body Double view opens its own picker. CLI carries `studyloop study "<title>" --mode co-study`. The recommendation named a plan; the Web door drops it. Not wrong — the learner can pick — but a worse door than the CLI on the same payload.

- Fix: pass the first `plan_refs[].plan_id` (or primary concept title) into the Body Double view's picker as the initial selection.
- RED: extend `test('a body-double primary starts in the Body Double view…')` to assert the payload the view receives, once the view accepts an initial plan.

Not 🟡: the brief marks this out of range; the session door (not `GET /api/body-double/focus`) is the correct target.

🔵 **`hasPlanContext` is true for a no-plan deferred repair, and the notes block is labelled "Your plans".** `today-panel.js` `hasPlanContext` ORs `deferredRepairNotes().length > 0`; `index.html` wraps that block in `<p class="today-parked-label">Your plans</p>`. A no-plan learner sees a "Your plans" heading containing only "Repairing “decorators”…". The JS test (`deferredRepairNotes: a repair unrelated to any plan… counts as plan context alone`) pins the current lie.

- Fix: retitle the block when `active_plans` is empty ("Deferred for energy", or keep the lines and drop the heading); `hasPlanContext` can stay true so the notes still show.
- RED: update that JS test to assert the visible heading is not "Your plans" when `active_plans` is absent.

💡 `evidence_command` as the door field is acceptable. Every renderer already reads it; a new field would be a fourth JSON key for one candidate type. The CLI relabels; the command string itself is a session start, so a consumer that executes it does the right thing. MCP `get_next_action` returning `to_json_dict()` unchanged is safe: the new key is omitted when empty; `source="body_double"` plus `--mode co-study` is self-describing. Disclose `energy_deferred_repairs` and `source=body_double` in the tool docstring / persona on the next MCP pass — not a merge gate (`PRODUCTION_TOOL_COUNT` correctly unchanged).

### (h) Spec delta — matches the code

MODIFIED requirement restates the ranker with item 5 inlined. Rule 2's demand classes, the additive `energy_deferred_repairs` key, plan-independent deferral, the body-double clause after milestone synthesis, rule 7's slot becoming the body double below the floor, and the qualified byte-for-byte sentence all match `build_now_plan` / `_defer_repairs` / `_body_double_candidate`.

Ready-only synthesis is implied by spec rule 8 ("never synthesised") plus the body double being a synthesis; `test_body_double_is_never_synthesised_for_an_unready_plan` pins it. No dedicated spec scenario for "unready husk alone → no body double" — add one if the delta is edited again; not blocking.

Scenario "A deferred repair does not represent a milestone" is stated in rule 5's prose and untested (see (c)). Scenario "Renderers show, never re-rank" claims `GET /api/now?energy=low` and the recap's spoken/Rich forms; the new pin is CLI + `_plan_context` + Today markup. Pre-existing renderer tests plus `to_json_dict` omit-empty cover the rest. Not a contract break.

### (i) Tests

Six REDs drive the real `_struggle_candidates` over `_plant_struggles` / `_struggle` rows — the right seam, since demand is derived in the collector. The unready correction (`8e9cbdf5`) is test+fix in one commit; acceptable as a pre-review re-read.

Gaps already named: 14-day boundary, unparseable `last_seen`, two ready plans, decision 5. Medium-vs-high indistinguishability is implicitly true (both defer at low, both vanish at medium) and does not need its own test.

Loose substring: `assert "defer" in low.primary.reason.lower()` in `test_body_double_never_appears_without_an_active_plan` would survive a wording change that dropped the honest sentence. Pin the designed clause.

- Fix: `assert low.primary.reason.startswith("Today's energy deferred the repair work")`.
- Same test, tighter assertion — not a new name.

Other reason checks (`"Frames" in … and "window function" in …`, `"3/10" in … and "6/10" in …`) are specific enough.

### (j) Rubric row 3b

The three readings are the right questions for the finding's two halves, printed from the real engine over `_plant_struggles`:

- (a) live struggle → body-double primary — "would you sit with the plan rather than repair the live struggle today?"
- (b) + unrelated due → due primary, proposal beneath — "is the proposal right to sit beneath the unrelated due recall?"
- (c) `learning` → gentle teach-back — "is the recovered teach-back one you would do at low energy?"

They cover (1) demand (live defers, recovered stays) and (2) the floor (synthesise when nothing fits; proposal, not filter). Scores in the receipt (42 = 30+12; 100 = 70+12+18; 118 due) match §6.

Ask the owner one extra thing when scoring, not as a fourth reading in the table: **"A learner with no plan and only a live struggle at low energy now gets the starter plus a deferred-repair note, not the hands-on repair. Is that the no-plan floor you want?"** That is design §5 decision 1, and only the owner can close it. Do not hold the merge on the answer — the finding's text does not gate repair on a plan.

Omitted and not needed in 3b: older-struggle (medium) class; same-concept due+repair double print; the 14-day window. Those are engine pins, not human-judgement questions.

## 3. Refutations

- **"any real candidate outranks it"** (design §5, `BODY_DOUBLE_BASE_SCORE` comment, spec rule 5) is false after the low
