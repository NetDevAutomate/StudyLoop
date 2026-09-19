# Council review 7 — item 5 (D-F): per-item energy demand for repair, and the body-doubling floor

**Date:** 2026-09-19 · **Branch:** `feat/energy-demand-body-double`, reviewed tree `6d5a2d0e` (four commits on
`main` `4f8e3e0f`; `main` carries items 1–4 and the follow-on chores, CI fully green on `a03fc9bd` and
`4f8e3e0f`). **Reviewed range:** `4f8e3e0f..6d5a2d0e` — 4 commits, 15 files, +1,042/−25. **You are one
independent seat**; no other seat's answer is visible. You have no tools — this brief is the complete evidence
base. One implementing agent worked between owner checkpoints; your findings gate the merge of item 5 to `main`
and the owner's scoring of rubric row 3b (T5.5), after which the change is archived.

Item 5 answers the owner's one **"no"** on the D-16 rubric walkthrough (row 3, 2026-09-16): at low energy the
engine recommended hands-on repair of a *live* struggle because a struggle-repair candidate carried no energy
demand of its own — rule 3 only gated new milestone work. This review is about one ranker change and its
renderers; nothing else moved in the range.

## 0. What you are reviewing against (binding)

### Owner decision (HANDOFF-2026-09-16.md §2, verbatim)

> | D-F | Scenario 3 (**no**): a struggle-repair task has no energy demand; hands-on repair of a live struggle on a
> low-energy day compounds the struggle (RSD). Derive per-item energy demand from struggle recency / teach-back;
> when nothing plan-related fits the day's capability, synthesise a **body-doubling / open-session** candidate
> (feature exists: ADR-0001/0003, `web/routes/body_double.py`) naming the deferred items. |

### Rubric row 3 (`receipts/now-rubric-2026-09-16.md`, the finding, verbatim)

> | 3 | Energy-deferred | Plan `sql-windows` with `energy_floor: 5`; milestone 0 `Window basics` **done** (concepts
> `[window function]`), milestone 1 `Frames` (concepts `[window frame]`). One struggle-repair item `window
> function`/sql, `hands-on`, base 82. **Energy `low`** (capability 3/10). | **`window function`** (hands-on, score
> 80, `plan_refs=[(sql-windows, None)]`); no alternates; `energy_deferred=[(sql-windows, milestone 1, floor 5,
> capability 3)]`; JSON gains `energy_deferred`. | Rule 3: capability 3 < floor 5, so the *new* milestone (Frames)
> is deferred and named, not synthesised; the plan-related repair on a finished milestone's concept stays
> eligible and keeps its ref (`None`: plan-related repair, not the next milestone). Score = 82 + 12 bias − 14
> (hands-on at low energy). | **no** — owner, 2026-09-16: a struggle-repair task has no energy demand of its own;
> recommending hands-on repair of a *live* struggle on a low-energy day risks compounding the struggle and
> damaging confidence (RSD). Finding for council: (1) derive a per-item energy demand for repair from struggle
> recency/teach-back — at low energy a live struggle defers like new work, a recovered one stays eligible as
> gentle review; (2) when nothing plan-related fits the day's capability, synthesise a body-doubling /
> open-session candidate (feature exists: ADR-0001/0003, `web/routes/body_double.py`) naming the deferred items,
> instead of the least-bad task. |

### Owner's standing rule (2026-09-18, design preamble)

Nothing in the planning/architect flow may be kiro-cli specific; every process and steering surface applies
across all supported harnesses. (Item 5 touches no harness-specific surface; the co-study door is the CLI's
`studyloop study … --mode co-study` and the Web's Body Double view, both harness-neutral.)

### Design §5 — verbatim as it stands at the reviewed tree (`openspec/changes/plan-integration-followons/design.md`)

#### (design.md §5) Item 5 — per-item energy demand and the body-doubling floor (D-F) — designed here, reviewed separately

*(One page, written before item 5's RED; see tasks T5.\*.)*

- **Energy demand per candidate.** `_struggle_candidates` derives `energy_demand ∈ {low, medium, high}` from
  struggle state: `confidence == "struggling"` (a live struggle, ≤ 14 days) → `high`; `struggling` older than
  14 days or a weak teach-back → `medium`; recovered / gentle review → `low`. Demand maps to a required
  capability (`high` → 6, `medium` → 4, `low` → 0) compared with `ENERGY_CAPABILITY[energy]`.
- **Rule 3 extended.** Below capability, *repair* above demand is deferred exactly like new milestone work and
  listed in `energy_deferred` with a reason naming the struggle; recovered repair stays eligible as gentle
  review. Due recall (`source=study_progress` due rows) is unaffected.
- **Body-doubling floor.** When the eligible plan-related set is empty **and** at least one active plan exists,
  synthesise one candidate: `source="body_double"`, `action_type="conversation"`, low base score (below any
  real candidate), reason naming the deferred items, `plan_refs` for each named plan with `milestone_index
  None`, and an `evidence_command` that opens the existing body-double session route (`studyloop study
  --mode co-study` / `web/routes/body_double.py`). A proposal, not a filter: real candidates still rank above
  it.
- **No-plan output byte-identical to the golden**; `INTERLEAVE_RATIOS["low"]` unchanged (the design does not
  call for it).
- **Rubric row 3b** (owner scores): scenario 3's fixture at low energy now yields the deferred repair named in
  `energy_deferred` and a body-double primary (or the due recall if one exists).

**T5.1 review against the code (2026-09-18, tree `7208eb67`) — three amendments, each from reading
`learning/decision.py`, not the text above:**

1. **Demand classes are the struggle collector's classes.** `_struggle_candidates` emits a row only when
   `confidence in ("struggling", "learning")` or `last_teachback_score < 14`; "recovered / gentle review" is not a
   row it produces. So: `struggling` with `last_seen` ≤ 14 days → `high`; `struggling` older than 14 days, or any
   row whose only signal is a weak teach-back → `medium`; `learning` → `low`. Demand is derived once, in the
   collector, and carried in the candidate's `metadata` beside `confidence` so the scorer and the renderers read
   one value. Required capability `high → 6`, `medium → 4`, `low → 0` stands (the `low` class is what "repair is
   cheaper than encoding" was always about).
2. **`energy_deferred` is milestone-shaped and cannot carry a repair as it is.** `DeferredMilestone` has a
   mandatory `milestone_index`, and all three renderers (`cli/_now.py`, `learning/recap.py`,
   `today-panel.js::deferredNotes`) print `milestone {index + 1} "{title}" needs energy {floor}/10`. A deferred
   repair gets its own frozen `DeferredRepair` (`plan_id`/`plan_title` when plan-related, else `None`, `concept`,
   `topic`, `confidence`, `energy_demand`, `required_capability`, `energy_capability`, `reason` naming the
   struggle), carried in a **new additive key `energy_deferred_repairs`** — not folded into `energy_deferred`,
   whose consumers would print "milestone None". Same "readable off the top" rule as the closing review's
   evidence lines: each renderer gains one line per deferred repair.
3. **The body-double door is a session start, not `web/routes/body_double.py`.** That route is the read-only focus
   reader (`GET /api/body-double/focus`). The session door is `studyloop study "<topic>" --mode co-study` on the
   CLI and a session start from the Body Double view (origin `body-double`) on the Web. `_evidence_command` has
   no branch for a `conversation` candidate and would fall through to `studyloop progress … -c learning`, which is
   a write, not a door — so the body-double candidate carries `evidence_command = 'studyloop study "<plan title>"
   --mode co-study'` set explicitly, and `_evidence_command` is not asked to guess. `source="body_double"`,
   `action_type="conversation"`, base score below `MILESTONE_BASE_SCORE` (48) so any real candidate outranks it.

Rule 3's *deferral* of repair is the change; rule 3's *eligibility* of plan-related due recall is untouched. The
no-plan golden stays byte-identical because a body-double candidate requires an active plan and the golden world
has none; `INTERLEAVE_RATIOS["low"]` unchanged.

**Decisions taken at GREEN (2026-09-19), each a test in `test_now_plan_guidance.py`:**

1. **The deferral is plan-independent.** A live struggle is a live struggle whether or not a plan names it
   (amendment 2's `plan_id … else None` already said so); the finding was about the learner's day, not the
   plan. The body double, by contrast, *requires* a matchable active plan — it is "sit with the plan".
   Consequence, stated rather than hidden: D-5's "a learner with no active plan receives the pre-#10 payload
   byte for byte" now holds for a no-plan learner **with nothing deferred**; a no-plan learner whose live
   struggle is deferred at low energy gets `energy_deferred_repairs` (and the starter if nothing else was
   collected) where they used to get the hands-on repair. The golden world defers nothing and is unchanged.
   The spec delta and both docs say so in those words. **A council question (review 7):** is that the right
   scope for D-F, or should the repair half be gated on an active plan?
6. **The body double names ready plans only.** An active-but-unready plan is matched but never synthesised
   (spec rule 8), and the body double is a synthesis; with only a husk active and nothing plan-related fitting,
   nothing is proposed to sit with — the warning beside it already says "pause or repair"
   (`test_body_double_is_never_synthesised_for_an_unready_plan`).
2. **Rule 8's guaranteed slot below the floor is the body-double proposal.** It carries `plan_refs`, so where
   four unrelated due items outrank everything at low energy the second alternate is now the proposal, not a
   third unrelated item. It advertises no work the energy cannot carry — the property rule 8's docstring
   protects — and the primary is untouched. `test_preserves_one_plan_backed_action_when_energy_allows` says so.
3. **The starter tells the truth after a deferral.** With no plan and every real candidate deferred, the starter
   stands in; its reason now says the energy deferred the repair work rather than "no learning evidence found
   yet", which would be false. The golden world defers nothing, so its sentence is unchanged.
4. **Body-double shape.** Base `BODY_DOUBLE_BASE_SCORE = 30` (+12 bias = 42 < practice 48, milestone 48);
   concept `Sit with <title>` (one plan) / `Sit with your plans`; `plan_refs` for every matchable plan; reason
   naming each deferred milestone and repair; command `studyloop study "<first title>" --mode co-study`. The
   Today card starts it in the Body Double view (`viewForAction`); the CLI labels the command "Sit with the plan".
5. **A deferred repair does not "represent" a milestone** (rule 6 runs after the deferral), so an eligible
   milestone whose only collected representative was a deferred live struggle is synthesised as a conversation —
   the learner can still talk about it.

Known edge, not solved here: a `struggling` row whose `last_seen` cannot be parsed is read as live (`high`) —
the cautious side; `_days_since` returns `None` and the demand falls to `high`.

### Hard rules for this batch (verified on `6d5a2d0e` before this brief was written)

- TDD: the RED commit `ef319a7b` (six Python tests, five JS tests, each red for its missing name: 6 failed / 40
  passed; JS 5 failed / 139 passed) precedes GREEN `326abcf9`; the two corrections `8e9cbdf5` (test + fix in one
  commit) and `6d5a2d0e` (wording only) follow.
- The seam adds **no new writer**: item 5 is a ranker change; `build_now_plan` still reads plans through exactly
  one `PlanApplication().get_active_guidance()` call plus the item-4 preview read for fully-checked plans; the
  struggle collector reads `history.observations.rows` as before and writes nothing.
- Golden `tests/golden/now_plan_no_active.json` sha256
  `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0` **unchanged** (measured);
  `test_no_active_plans_json_byte_identical_to_golden` green. Architecture guard `test_architecture_plan_seam.py`
  **30 passed**. MCP production inventory unchanged (`PRODUCTION_TOOL_COUNT = 32`).
- `test_now_plan_guidance.py` **47 passed** (six REDs flipped, one existing pin updated —
  `test_preserves_one_plan_backed_action_when_energy_allows`, see design §5 decision 2 — and one correction
  test added); plan suites (`test_now_plan_guidance`, `test_learning_decision`, `test_cli_plan_seam`,
  `test_plan_application`, `test_docs_plan_integration_contract`) **189 passed**; JS **144 passed** (+5); e2e
  browser journeys `test_journey_study_plan.py` + `test_plans_api.py` **20 passed**; `mkdocs build --strict` exit
  0; `openspec validate plan-integration-followons` valid; ruff check / ruff format --check / pyright clean.
- Full suite at GREEN `326abcf9`, matched control on a clean `main` `4f8e3e0f` worktree, both importing from
  their own tree: item5 30 failed / **5126 passed** / 14 errors; control 30 failed / 5120 passed / 14 errors;
  **item5 − control = ∅, control − item5 = ∅**; the 44 shared ids are byte-identical to the committed
  sandbox-environmental set (`receipts/full-suite-control-item4-2026-09-18.md`). Receipt:
  `receipts/full-suite-control-item5-2026-09-19.md` (§5 below). The two corrections after GREEN were verified
  with the plan suites, not a second full run.
- CI has **not** seen this branch; it is pushed after this review, as with items 3/3b/4.
- The recap (`build_daily_recap`) calls `build_now_plan()` at its default `medium` energy (6/10), which carries
  every demand class; a deferred repair can therefore reach the recap's sentence builder `_plan_context(plan)`
  only for a low-energy plan handed to it — the renderer exists and is pinned through `_plan_context` directly.

## 1. Commits in the range (oldest first)

| Commit | RED/GREEN/other | Files |
| --- | --- | --- |
| `ef319a7b` | **RED** — six Python tests + five JS tests | `tests/test_now_plan_guidance.py`, `tests/js/today-panel-plan.test.js` |
| `326abcf9` | **GREEN** — engine, three renderers, spec delta (MODIFIED requirement), docs, rubric row 3b, task ticks, control receipt | 14 files |
| `8e9cbdf5` | correction (agent's own re-read, before this brief): the body double names **ready** plans only; test + fix | `learning/decision.py`, `tests/test_now_plan_guidance.py` |
| `6d5a2d0e` | wording: the no-plan payload is byte-identical only when nothing is deferred | spec delta, `docs/cli-reference.md`, `docs/study-plans.md`, `design.md` |

## 2. The agent's own implementation report (verbatim from `tasks.md`, T5.1–T5.5)

#### (tasks.md) Item 5 — energy demand + body-doubling floor (D-F) · own round

- [x] **T5.1** Design §5 reviewed against the code (`_struggle_candidates`, `_score_candidates`, rule 3) — amend if
      the code contradicts it. (2026-09-18: three amendments recorded under §5 — the demand classes are the struggle
      collector's own (`struggling` fresh/old, weak teach-back, `learning`; no "recovered" row exists); a deferred
      repair needs its own `DeferredRepair` in a new additive `energy_deferred_repairs` key because `DeferredMilestone`
      and its three renderers are milestone-shaped; the body-double door is `studyloop study … --mode co-study` /
      the Body Double view's session start, not the read-only `body_double.py` focus route, so the candidate sets
      its `evidence_command` explicitly. T5.2's RED names hold; a sixth test pins the new key's rendering.)
- [x] **T5.2** RED `tests/test_now_plan_guidance.py`: `test_live_struggle_repair_defers_at_low_energy_like_new_work`,
      `test_recovered_repair_stays_eligible_at_low_energy`, `test_body_double_candidate_is_synthesised_when_nothing_plan_related_fits`,
      `test_body_double_is_a_proposal_not_a_filter`, `test_body_double_never_appears_without_an_active_plan`,
      golden byte-identity still green. (2026-09-19, `ef319a7b` on `feat/energy-demand-body-double`: the five plus
      the sixth, `test_cli_now_and_recap_render_deferred_repairs_and_the_body_double_door`, and five JS pins in
      `tests/js/today-panel-plan.test.js` (`deferredRepairNotes`, `viewForAction`, markup). The struggle collector
      runs for real over patched `observations.rows`, since demand is derived in the collector. 6 red / 40 green,
      JS 5 red / 139 green, each for its missing name.)
- [x] **T5.3** GREEN: `energy_demand`, rule 3 extension, `body_double` synthesis, CLI/Today "sit with the plan" line.
      (2026-09-19: `DeferredRepair` + `energy_deferred_repairs`, `ENERGY_DEMAND_CAPABILITY`/`LIVE_STRUGGLE_DAYS`,
      `_energy_demand` in the collector, `_defer_repairs` before rule 6, `_body_double_candidate` after it,
      honest starter after a deferral; CLI `now` + recap + Today card lines; MODIFIED requirement in the
      `active-learning-decisions` delta; docs `study-plans.md` "Plan-aware now" + `cli-reference.md`; design §5
      "Decisions taken at GREEN" 1-5. Module 46/46, JS 144/144, e2e plan journeys 20/20, docs contract 39/39,
      `mkdocs --strict` exit 0, `openspec validate` valid; full suite vs a clean `main` control — see the GREEN
      commit's receipt.)
- [ ] ⚖ **T5.4** Council review 7 (`review7`, same seats or `kimi-k2-thinking` third); arbitration; corrections.
- [ ] **T5.5** Rubric row **3b** for the owner (`PENDING`); the change is archived only after the owner scores 3b
      (4b was scored **yes / yes** on 2026-09-18, so 3b is the one row still outstanding). (2026-09-19: row 3b
      written into `receipts/now-rubric-2026-09-16.md` with three readings printed from the real engine — (a) live
      struggle → body-double primary, (b) plus an unrelated due recall → due recall primary, proposal beneath,
      (c) recovered `learning` → gentle teach-back primary — verdict `PENDING`.)

## 3. The diffs — `4f8e3e0f..6d5a2d0e`, every file, in full

```diff
diff --git a/docs/architecture/plan-integration/receipts/full-suite-control-item5-2026-09-19.md b/docs/architecture/plan-integration/receipts/full-suite-control-item5-2026-09-19.md
new file mode 100644
index 00000000..0f415e32
--- /dev/null
+++ b/docs/architecture/plan-integration/receipts/full-suite-control-item5-2026-09-19.md
@@ -0,0 +1,36 @@
+# Full-suite matched control — item 5 (D-F) — 2026-09-19
+
+Two full `packages/studyloop/tests` runs in parallel, same machine, same
+sandbox, `-q -p no:cacheprovider -rfE`:
+
+| Tree | Worktree | Result |
+| --- | --- | --- |
+| **item 5** (`feat/energy-demand-body-double`, RED `ef319a7b` + GREEN working tree) | `studyloop-wt/item5` | 30 failed, **5126 passed**, 4 skipped, 804 deselected, 14 errors (10:17) |
+| **control** (`main` `4f8e3e0f`, detached) | `studyloop-wt/ctrl-item5` | 30 failed, 5120 passed, 4 skipped, 804 deselected, 14 errors (10:24) |
+
+Both worktrees were `uv sync --all-packages --group dev` and each proved to
+import `studyloop` from its own tree before the run.
+
+## Sorted failing-id sets
+
+- item5 ∖ control = **∅** — zero regressions.
+- control ∖ item5 = **∅** — nothing item 5 fixed by accident, and the six
+  new tests account for the passed-count difference (+6).
+- item5 ∖ committed environmental set (`full-suite-control-item4-2026-09-18.md`,
+  44 ids + item 4's seven then-REDs) = **∅**. The seven ids on the other side of
+  that comparison are item 4's REDs, green since `82293293`.
+
+The 44 shared ids are the sandbox-environmental set the item-4 receipt lists
+by name (journeys world guards, acceptance isolation, second-brain CLI/doctor,
+harness-matrix live mechanics, obsidian vault isolation, fresh-install scope);
+unchanged here, byte for byte.
+
+## Scoped gates on the same tree
+
+- `test_now_plan_guidance.py` 46/46 (six REDs flipped; golden `now_plan_no_active.json` byte-identical);
+  `test_learning_decision.py` 5/5 (one stub updated to the starter's new keyword).
+- JS `node --test packages/studyloop/tests/js/*.test.js` 144/144 (+5).
+- e2e `test_journey_study_plan.py` + `test_plans_api.py` 20/20 (browser).
+- `test_docs_plan_integration_contract.py` + `test_ci_workflow_contract.py` 39/39.
+- `mkdocs build --strict` exit 0; `openspec validate plan-integration-followons` valid.
+- ruff check / ruff format --check / pyright: clean on every touched file.
diff --git a/docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md b/docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md
index ff46f1f4..759ce0e9 100644
--- a/docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md
+++ b/docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md
@@ -1,6 +1,6 @@
 # Plan-aware `now` — five-scenario human rubric (D-16) · 2026-09-16

-**Status: owner verdicts RECORDED 2026-09-16 (interactive walkthrough with the coordinator).** Scenarios 1, 2 and the primary of 4: yes. Scenario 3: **no** (finding). Scenario 4 completion action: **no as phrased** (finding). Scenario 5: verified. **Row 4b added and scored 2026-09-18** (item 4 / D-G, tree `feat/plan-close`; outputs emitted from the tree committed as `82293293`): scenario 4 re-run with the end assessment planted, both proposals recorded as emitted; owner verdict **yes** on both readings — (a) *extend* with named evidence is a proposal the owner would walk, (b) a clean review's *close* is one the owner would agree to. This closes row 4's "no as phrased" finding; row 4 is kept as the record of the original finding. This receipt was produced unattended
+**Status: owner verdicts RECORDED 2026-09-16 (interactive walkthrough with the coordinator).** Scenarios 1, 2 and the primary of 4: yes. Scenario 3: **no** (finding). Scenario 4 completion action: **no as phrased** (finding). Scenario 5: verified. **Row 3b added 2026-09-19** (item 5 / D-F, tree `feat/energy-demand-body-double`; outputs emitted from the tree the GREEN commit records): scenario 3 re-run with the struggle collector live, three readings printed, verdict `PENDING` for the owner. **Row 4b added and scored 2026-09-18** (item 4 / D-G, tree `feat/plan-close`; outputs emitted from the tree committed as `82293293`): scenario 4 re-run with the end assessment planted, both proposals recorded as emitted; owner verdict **yes** on both readings — (a) *extend* with named evidence is a proposal the owner would walk, (b) a clean review's *close* is one the owner would agree to. This closes row 4's "no as phrased" finding; row 4 is kept as the record of the original finding. This receipt was produced unattended
 overnight. Every scenario below was *run* on frozen fixtures and the primary
 and its rationale are recorded exactly as the engine emitted them; the
 "would I do the primary?" column is a human judgement that only the owner can
@@ -30,6 +30,7 @@ learning").
 | 1 | Matching due | Active plan `sql-windows` ("SQL Windows", topics `[sql]`, next milestone 0 concepts `[window function]`). Due items: `decorators`/python base 102, `window function`/sql base 100. | **`window function`** (sql, recall, score 130, `plan_refs=[(sql-windows, 0)]`); alternate `decorators` (120, no refs). | Rule 5: both are due items two points apart — one urgency class — so the plan-related one takes the +12 bias and wins; the unrelated due item is *kept* as an alternate (bias, not filter). Rule 7 names the milestone the action advances. | **yes** — owner, 2026-09-16: "window function is the logical step before decorating it" (a prerequisite-order argument; see F2 follow-on). |
 | 2 | Urgent-unrelated wins | Same plan. One due item: `decorators`/python, base 100 (an overdue spaced-repetition review). Nothing represents milestone 0. | **`decorators`** (118, no refs); alternate `window function` (60, `source=study_plan:sql-windows:0`, `plan_refs=[(sql-windows, 0)]`, reason "Next milestone 1/1 of plan 'SQL Windows': Window basics"). | Rule 5: the unrelated candidate is in a more urgent class (due review) and wins outright — the bias cannot lift new-milestone work over it. Rule 6: the plan's next milestone was unrepresented, so it was synthesised at base 48 + bias 12 = 60 and appears as the plan-backed alternate (rule 8 satisfied without any swap). | **yes** — owner, 2026-09-16: clear the overdue review first. Note for follow-on: an overdue item *unrelated* to the plan must not sit as an alternate indefinitely — propose it explicitly (age-aware nudge) or let the learner retire it. |
 | 3 | Energy-deferred | Plan `sql-windows` with `energy_floor: 5`; milestone 0 `Window basics` **done** (concepts `[window function]`), milestone 1 `Frames` (concepts `[window frame]`). One struggle-repair item `window function`/sql, `hands-on`, base 82. **Energy `low`** (capability 3/10). | **`window function`** (hands-on, score 80, `plan_refs=[(sql-windows, None)]`); no alternates; `energy_deferred=[(sql-windows, milestone 1, floor 5, capability 3)]`; JSON gains `energy_deferred`. | Rule 3: capability 3 < floor 5, so the *new* milestone (Frames) is deferred and named, not synthesised; the plan-related repair on a finished milestone's concept stays eligible and keeps its ref (`None`: plan-related repair, not the next milestone). Score = 82 + 12 bias − 14 (hands-on at low energy). | **no** — owner, 2026-09-16: a struggle-repair task has no energy demand of its own; recommending hands-on repair of a *live* struggle on a low-energy day risks compounding the struggle and damaging confidence (RSD). Finding for council: (1) derive a per-item energy demand for repair from struggle recency/teach-back — at low energy a live struggle defers like new work, a recovered one stays eligible as gentle review; (2) when nothing plan-related fits the day's capability, synthesise a body-doubling / open-session candidate (feature exists: ADR-0001/0003, `web/routes/body_double.py`) naming the deferred items, instead of the least-bad task. |
+| 3b | Energy-deferred — **re-run after D-F (item 5, 2026-09-19)** | Row 3's fixture (`sql-windows`, `energy_floor: 5`, milestone 0 `Window basics` done `[window function]`, milestone 1 `Frames` `[window frame]`; **energy `low`**, capability 3/10), with the struggle collector running for real over three readings: **(a)** `window function` recorded `struggling` 3 days ago (a live struggle); **(b)** the same plus an unrelated due recall `decorators`/python base 100; **(c)** `window function` recorded `learning` (recovered). | **(a)** primary **`Sit with SQL Windows`** (conversation, `source=body_double`, score 42, `plan_refs=[(sql-windows, None)]`, command `studyloop study "SQL Windows" --mode co-study`), reason *"Nothing plan-related fits low energy today — deferred: milestone 2 “Frames” of SQL Windows; repair of “window function”. Sit with SQL Windows instead: a body-double session, no new material, no repair."*; no alternates; `energy_deferred=[(sql-windows, 1, 5, 3)]`; **`energy_deferred_repairs=[(sql-windows, window function, struggling, high, 6, 3)]`** with reason *"low energy carries 3/10; repairing 'window function' (a live struggle) asks for at least 6/10 — deferred like new work; due recall and gentle review stay available"*. **(b)** primary **`decorators`** (118, no refs); the body-double proposal is the only alternate (42). **(c)** primary **`window function`** (teachback, 100, `plan_refs=[(sql-windows, None)]`, `energy_demand=low`); nothing deferred but the milestone. | Rule 3 extended (design §5): repair carries a demand derived in the struggle collector — live `struggling` → high (6/10), older `struggling` or a weak teach-back → medium (4/10), `learning` → low (0/10) — and below the capability is deferred like new work into its own key, never ranked; due recall is never deferred. When nothing plan-related fits and an active plan exists, one body-double candidate is synthesised (base 30 + 12 bias = 42 < any real candidate — a proposal, not a filter) carrying the co-study session door. | **PENDING** — owner: (a) would you sit with the plan rather than repair the live struggle today? (b) is the body-double proposal right to sit beneath the unrelated due recall? (c) is the gentle teach-back on a recovered concept one you would do at low energy? |
 | 4 | Fully-checked | Plan `done-plan` ("Done Plan"), milestones A and B both done. One due item `decorators`/python base 100. | **`decorators`** (118, no refs); `completion_actions=[(done-plan, "Every milestone of 'Done Plan' is checked off — close the plan or extend it with a follow-on mission.")]`; no `study_plan:` candidate anywhere; JSON gains `active_plans` + `completion_actions`. | Rule 9: a fully-checked plan is reported as a completion action and is neither matched (no bias, no refs) nor synthesised. | **primary yes / completion action no as phrased** — owner, 2026-09-16: the completion action must be contextual and consensual. Run the end assessment (`assess(phase="end")`: due reviews, struggles, unverified milestones on the plan's concepts). If outstanding work touches the plan's concepts (or their prerequisites — F2 concept edges), propose *extend* and name the evidence; if clean, propose *close* and ask the learner to agree ("anything you are not comfortable with?"). Status never changes automatically (#7). Natural vehicle: architect with `purpose=planning` and the assessment in the brief (`plan close <id>`, sibling of `plan repair <id>`). Finding for council. |
 | 4b | Fully-checked — **re-run after D-G (item 4, 2026-09-18)** | Row 4's fixture (`done-plan`, milestones A `[alpha]` and B `[beta]` both done; one due item `decorators`/python base 100), plus the end assessment's readers planted: **(a)** one due review on plan concept `alpha` (`overdue`) with session mentions backing both concepts; **(b)** no due rows, same mentions. | Primary unchanged in both: **`decorators`** (118, no refs); no `study_plan:` candidate. **(a)** `completion_actions=[(done-plan, due 1 / struggles 0 / unverified 0, proposal **extend**, evidence `["Due review: alpha — overdue"]`)]`, sentence: "Every milestone of 'Done Plan' is checked off, and the closing review proposes extending the plan — 1 due review, 0 struggles and 0 unverified milestones on its concepts. Walk the evidence with the architect: studyloop plan close done-plan." **(b)** counts 0/0/0, proposal **close**, evidence `[]`, sentence: "Every milestone of 'Done Plan' is checked off and the closing review is clean — it proposes closing the plan. Close it with the architect when you agree: studyloop plan close done-plan." No warnings; JSON gains the five keys only inside the entry. | Rule 9 as before for the ranking. The completion action is now the end assessment read as a preview (`assess(phase="end", record=False)`, one call, no write, no status change): `extend` iff any of the three counts on the plan's own concepts is above zero, else `close`; due counts only rows naming a concept (the scheduler's "new topic" row is excluded — owner decision 2026-09-17). `plan close done-plan` launches the architect with the same review as the brief's first section; status moves only when the learner agrees. | **yes / yes** — owner, 2026-09-18, answering the two questions as posed: (a) **yes**, a proposal the owner would walk; (b) **yes**, a close the owner would agree to. No further line given. Closes row 4's "no as phrased" finding; status still moves only when the learner agrees in the architect conversation. |
 | 5 | No-plan identical | No plan documents at all; no collector candidates. | **`one tiny recall loop`** (python, recall, 28, `source=starter`) — the starter. | D-5: `serialise(plan) == golden` → **byte-identical** (`True` in the run); the JSON key list is exactly the golden's — no additive key is present. | **verified** — owner walkthrough 2026-09-16: nothing to judge; the byte-identical golden is the acceptance. |
@@ -47,7 +48,12 @@ The five rows correspond to
 `test_fully_checked_active_plan_emits_completion_not_candidate` and
 `test_no_active_plans_json_byte_identical_to_golden`; the primaries above are
 what those tests assert, printed from a throwaway driver over the same
-fixtures. Row 4b corresponds to
+fixtures. Row 3b corresponds to
+`test_body_double_candidate_is_synthesised_when_nothing_plan_related_fits`
+(reading a), `test_body_double_is_a_proposal_not_a_filter` (reading b) and
+`test_recovered_repair_stays_eligible_at_low_energy` (reading c), printed on
+2026-09-19 from a throwaway driver over the module's `_plant_struggles`
+fixture with the struggle collector running for real. Row 4b corresponds to
 `test_completion_action_carries_the_end_assessment_and_proposes_extend_when_concepts_are_due`
 (reading a) and `test_completion_action_proposes_close_when_the_assessment_is_clean`
 (reading b), printed the same way on 2026-09-18 with the end assessment's
diff --git a/docs/cli-reference.md b/docs/cli-reference.md
index 90078af6..c633011d 100644
--- a/docs/cli-reference.md
+++ b/docs/cli-reference.md
@@ -259,7 +259,7 @@ studyloop now --speak

 Default ranking is due review first, then struggling or low teach-back score, then active-course continuity, then modality match. Low energy suppresses hard context switching.

-With an active study plan the same engine is plan-aware (see [Study Plans](study-plans.md#plan-aware-now)): plan-related work gets a bounded bias within its urgency class, a ready plan's next milestone is suggested when it is within your energy and no gathered candidate represents it, and a milestone above your current energy is deferred with a reason. The panel names the plan and milestone an action advances; `--json` adds `active_plans`, `energy_deferred`, `completion_actions`, `warnings` and per-action `plan_refs` only when each is non-empty, so the no-plan output is unchanged and a plan that cannot be read shows up as a warning rather than a failure.
+With an active study plan the same engine is plan-aware (see [Study Plans](study-plans.md#plan-aware-now)): plan-related work gets a bounded bias within its urgency class, a ready plan's next milestone is suggested when it is within your energy and no gathered candidate represents it, and a milestone above your current energy is deferred with a reason. Repair of a live struggle is deferred the same way at low energy (an older struggle or weak teach-back needs medium; a concept still being learned is never deferred, nor is a due review), and when nothing plan-related fits the day the panel proposes sitting with the plan — its command is the co-study door, `studyloop study "<plan>" --mode co-study`, labelled "Sit with the plan" rather than "Record evidence". The panel names the plan and milestone an action advances and prints one "Deferred for energy" line per deferred milestone and per deferred repair; `--json` adds `active_plans`, `energy_deferred`, `energy_deferred_repairs`, `completion_actions`, `warnings` and per-action `plan_refs` only when each is non-empty, so with no plan and nothing deferred the output is unchanged (the deferral of a live struggle at low energy is the one thing that happens without a plan), and a plan that cannot be read shows up as a warning rather than a failure.

 `studyloop chat-note` turns one markdown/text note into a compact Socratic context pack. V1 prints or speaks the mentor prompt; it does not run a separate chat backend.

diff --git a/docs/study-plans.md b/docs/study-plans.md
index 2c072c76..12f69e7a 100644
--- a/docs/study-plans.md
+++ b/docs/study-plans.md
@@ -219,7 +219,16 @@ action that advances a plan's next milestone is named with the plan and the
 milestone it serves; a **ready** plan whose next milestone is within your
 current energy gets that milestone suggested even when no other evidence
 points at it; and a plan whose energy floor is above your current energy has
-that milestone deferred with a reason rather than dropped. An active plan that
+that milestone deferred with a reason rather than dropped. Repair has an
+energy demand of its own: on a low-energy day a **live** struggle (recorded
+as struggling within the last two weeks) is deferred like new work — listed,
+not recommended — an older struggle or a weak teach-back needs medium energy,
+and a concept you are still learning is the gentle review that stays
+available at any energy; due reviews are never deferred. When nothing
+plan-related fits the day's energy, the recommendation is to **sit with the
+plan** — a body-double session, no new material, no repair — with the
+deferred items named; a real, unrelated action still outranks that proposal
+when one exists. An active plan that
 is **not ready** — a hand edit removed its mission or its milestones — is
 listed with a warning naming what to repair; it still biases related work,
 but no milestone is suggested for it until it is paused or repaired. A plan
@@ -243,7 +252,9 @@ action keeps its plain sentence and a warning says why — a failure is never
 shown as a clean slate. This is plan-aware guidance with tested ranking rules — a bias, not
 a filter: an overdue review or a fresh struggle on an unrelated topic can
 still outrank new milestone work. With no active plan the recommendation is
-unchanged; a plan that cannot be read adds a warning and nothing else. The
+unchanged — except that a live struggle is deferred at low energy whether or
+not a plan names it; a plan that cannot be read adds a warning and nothing
+else. The
 ranking rules are tested; whether the primary is the action *you* would take
 is a separate judgement. Five frozen scenarios and the engine's primaries are
 in the project's rubric receipt
diff --git a/openspec/changes/plan-integration-followons/design.md b/openspec/changes/plan-integration-followons/design.md
index c847d696..a72d5067 100644
--- a/openspec/changes/plan-integration-followons/design.md
+++ b/openspec/changes/plan-integration-followons/design.md
@@ -268,6 +268,39 @@ Rule 3's *deferral* of repair is the change; rule 3's *eligibility* of plan-rela
 no-plan golden stays byte-identical because a body-double candidate requires an active plan and the golden world
 has none; `INTERLEAVE_RATIOS["low"]` unchanged.

+**Decisions taken at GREEN (2026-09-19), each a test in `test_now_plan_guidance.py`:**
+
+1. **The deferral is plan-independent.** A live struggle is a live struggle whether or not a plan names it
+   (amendment 2's `plan_id … else None` already said so); the finding was about the learner's day, not the
+   plan. The body double, by contrast, *requires* a matchable active plan — it is "sit with the plan".
+   Consequence, stated rather than hidden: D-5's "a learner with no active plan receives the pre-#10 payload
+   byte for byte" now holds for a no-plan learner **with nothing deferred**; a no-plan learner whose live
+   struggle is deferred at low energy gets `energy_deferred_repairs` (and the starter if nothing else was
+   collected) where they used to get the hands-on repair. The golden world defers nothing and is unchanged.
+   The spec delta and both docs say so in those words. **A council question (review 7):** is that the right
+   scope for D-F, or should the repair half be gated on an active plan?
+6. **The body double names ready plans only.** An active-but-unready plan is matched but never synthesised
+   (spec rule 8), and the body double is a synthesis; with only a husk active and nothing plan-related fitting,
+   nothing is proposed to sit with — the warning beside it already says "pause or repair"
+   (`test_body_double_is_never_synthesised_for_an_unready_plan`).
+2. **Rule 8's guaranteed slot below the floor is the body-double proposal.** It carries `plan_refs`, so where
+   four unrelated due items outrank everything at low energy the second alternate is now the proposal, not a
+   third unrelated item. It advertises no work the energy cannot carry — the property rule 8's docstring
+   protects — and the primary is untouched. `test_preserves_one_plan_backed_action_when_energy_allows` says so.
+3. **The starter tells the truth after a deferral.** With no plan and every real candidate deferred, the starter
+   stands in; its reason now says the energy deferred the repair work rather than "no learning evidence found
+   yet", which would be false. The golden world defers nothing, so its sentence is unchanged.
+4. **Body-double shape.** Base `BODY_DOUBLE_BASE_SCORE = 30` (+12 bias = 42 < practice 48, milestone 48);
+   concept `Sit with <title>` (one plan) / `Sit with your plans`; `plan_refs` for every matchable plan; reason
+   naming each deferred milestone and repair; command `studyloop study "<first title>" --mode co-study`. The
+   Today card starts it in the Body Double view (`viewForAction`); the CLI labels the command "Sit with the plan".
+5. **A deferred repair does not "represent" a milestone** (rule 6 runs after the deferral), so an eligible
+   milestone whose only collected representative was a deferred live struggle is synthesised as a conversation —
+   the learner can still talk about it.
+
+Known edge, not solved here: a `struggling` row whose `last_seen` cannot be parsed is read as live (`high`) —
+the cautious side; `_days_since` returns `None` and the demand falls to `high`.
+
 ## 6. Verification

 `scripts/verify/plan_integration.py` gains registered checks for: the two architect grants (the ten names in
diff --git a/openspec/changes/plan-integration-followons/specs/active-learning-decisions/spec.md b/openspec/changes/plan-integration-followons/specs/active-learning-decisions/spec.md
index 2705937c..d5ffedad 100644
--- a/openspec/changes/plan-integration-followons/specs/active-learning-decisions/spec.md
+++ b/openspec/changes/plan-integration-followons/specs/active-learning-decisions/spec.md
@@ -96,3 +96,236 @@ print each evidence line beneath it, and none SHALL re-rank.
   `plan close <id>` still launches the architect, its brief's fourth line is
   `Proposal: unassessed — the review is partial`, the gap is among the first
   section's lines, and its status line does not say the review proposes
+
+## MODIFIED Requirements
+
+### Requirement: The now engine is plan-aware with tested ranking rules
+`studyloop.learning.decision.build_now_plan` SHALL remain the only ranker of
+study actions and SHALL consume active plans through exactly one call to
+`PlanApplication().get_active_guidance(today=…)`, where `today` is the date
+of the same instant `generated_at` records. It SHALL apply these rules, in
+this order (the plan-application-seam design, §3; decision D-5 of its
+council plan; item 5 / D-F of the follow-ons for rule 2's repair half and
+the body-doubling floor):
+
+1. Candidates are collected as before; a failure to read plans at all SHALL
+   degrade to a `warnings` entry, never a failed recommendation, and SHALL be
+   logged with its traceback on `studyloop.learning.decision` so a
+   programming error cannot hide behind the learner-facing warning.
+2. The energy capability is `low|medium|high → 3|6|10`. For an active plan
+   whose `energy_floor` exceeds it, the next milestone SHALL be listed in
+   `energy_deferred` and SHALL NOT become a candidate. Plan-related due recall
+   stays eligible and plan-related whatever its recorded confidence. A
+   struggle **repair** carries an energy demand of its own, derived once in
+   the struggle collector from its own row classes and carried in the
+   candidate's `metadata["energy_demand"]`: `struggling` seen within 14 days →
+   `high` (asks for 6/10); `struggling` older than that, or a row whose only
+   signal is a weak teach-back → `medium` (4/10); `learning` → `low` (0/10).
+   A repair whose demand exceeds the capability SHALL be deferred exactly
+   like new milestone work — listed in `energy_deferred_repairs` as a
+   `DeferredRepair` (`plan_id`/`plan_title` when plan-related, else `None`,
+   `concept`, `topic`, `confidence`, `energy_demand`, `required_capability`,
+   `energy_capability`, `reason` naming the struggle) and never ranked; the
+   deferral does not depend on a plan existing. A `low`-demand repair is
+   always carried. `energy_deferred` stays milestone-shaped; a repair is never
+   folded into it.
+3. A candidate is plan-related when `normalise_match_key` of its concept,
+   topic or course **equals** one of the plan's `match_keys`; no substring
+   test. It names the plan's next milestone (`milestone_index`) only when the
+   key equals one of that milestone's concepts **and** the plan is eligible —
+   ready and within the energy capability; a topic or finished-milestone
+   match, or any match on an energy-deferred or active-but-unready plan,
+   carries `milestone_index = None` (plan-related repair), so a payload never
+   names a milestone it also reports as deferred or that the seam would
+   refuse to tick.
+4. Scoring is today's scoring plus one bounded bias for plan-related
+   candidates: within one urgency class plan-related beats unrelated, and a
+   globally more-urgent unrelated candidate still wins — a bias, not a filter.
+5. When no collected candidate represents an eligible (ready, energy-permitted)
+   plan's next milestone, one `conversation` candidate SHALL be synthesised
+   for it (source `study_plan:<plan_id>:<index>`, concept = the milestone's
+   first concept or its title, topic = the plan's first topic), scored below
+   every due and repair class. A learner with an active plan and no evidence
+   is therefore sent to the plan, and `starter` is `false`. A deferred repair
+   (rule 2) does not "represent" a milestone. When, after rules 2 and 5, **no
+   candidate is plan-related** and at least one matchable active plan exists,
+   one **body-double** candidate SHALL be synthesised instead of leaving the
+   plan to the least-bad task: `source = "body_double"`, `action_type =
+   "conversation"`, base score below the synthesised-milestone base so every
+   real candidate outranks it (a proposal, never a filter), `plan_refs`
+   `(plan_id, None)` for every matchable plan, a reason naming the deferred
+   milestones and repairs it stands in for, and `evidence_command` the
+   co-study session door — `studyloop study "<plan title>" --mode co-study` —
+   set explicitly, never a progress write. No active plan (a draft is not
+   one) → no body-double candidate; when every real candidate was deferred
+   and no plan exists, the starter stands in and its reason says the energy
+   deferred the repair work, not that no evidence exists.
+6. After de-duplication every matching `PlanRef(plan_id, milestone_index)`
+   SHALL be attached to each ranked action, ordered by target urgency
+   (`overdue`, `soon`, `later`, `undated`) → most recent `updated` → `plan_id`,
+   keeping the most specific milestone per plan.
+7. When primary + alternates hold no plan-backed action and an eligible one
+   whose estimate fits the requested time exists further down, it SHALL
+   replace the last alternate only; the primary is never re-ranked by plans.
+   Below a plan's floor that plan-backed action is the body-double proposal
+   (it advertises no work the energy cannot carry), never the deferred
+   milestone.
+8. A fully-checked active plan SHALL appear in `completion_actions` and SHALL
+   be neither matched nor synthesised. An active-but-unready plan SHALL be
+   listed and matched (bias and a `milestone_index = None` reference) but
+   never synthesised and never named as a milestone, with a warning naming
+   its blockers.
+
+`NowPlan` gains `active_plans` (ordered as rule 6), `energy_deferred`,
+`energy_deferred_repairs`, `completion_actions` and `warnings`;
+`LearningRecommendation` gains `plan_refs: tuple[PlanRef, ...] = ()`.
+`to_json_dict()` SHALL omit each of these when empty, so a learner with no
+active plan **and nothing deferred** receives the pre-#10 payload **byte for
+byte** — pinned by `tests/golden/now_plan_no_active.json`, captured before any
+of this shipped. The one plan-independent change is rule 2's repair half: a
+learner with no plan whose live struggle is deferred at low energy receives
+`energy_deferred_repairs` (and the starter, if nothing else was collected)
+where they used to receive the hands-on repair itself.
+Renderers (`studyloop now`, `GET /api/now`, the Today card, the daily recap in
+its JSON, spoken and Rich-panel forms) SHALL show plan relevance, energy
+deferral — one line per deferred milestone **and** one per deferred repair —
+and the engine's warnings from these fields, SHALL label a body-double
+primary's command as the session door it is ("Sit with the plan", and the
+Today card starts it in the Body Double view) rather than as evidence to
+record, SHALL escape learner-authored text before any markup (Rich or HTML),
+and SHALL NOT re-rank. Ranking tests prove ranking compliance, not learner
+benefit (D-16); a five-scenario human rubric receipt accompanies the change,
+with row 3b re-run after this requirement's repair half.
+
+#### Scenario: No active plan is byte-identical to the golden
+- **WHEN** no active plan exists (an empty plans directory, or only a draft)
+  and `build_now_plan()` runs with a frozen clock in an empty world
+- **THEN** the serialised `to_json_dict()` equals
+  `tests/golden/now_plan_no_active.json` byte for byte, and no
+  `active_plans`, `energy_deferred`, `energy_deferred_repairs`,
+  `completion_actions`, `warnings` or `plan_refs` key is present
+
+#### Scenario: Matching due concept outranks unrelated of the same urgency
+- **WHEN** an active plan's milestone names `window function` and two due
+  items are two points apart, `decorators` (unrelated) ahead
+- **THEN** `window function` is primary with `plan_refs == (PlanRef(plan, 0),)`
+  and `decorators` is the first alternate with no refs
+
+#### Scenario: A more-urgent unrelated item still wins
+- **WHEN** the only collected candidate is an unrelated due item and the
+  plan's next milestone is unrepresented
+- **THEN** the due item is primary and the synthesised milestone
+  (`study_plan:<id>:0`) is an alternate with a lower score
+
+#### Scenario: Energy below the floor defers the milestone, keeps repair
+- **WHEN** energy is `low` (3/10), the plan's `energy_floor` is 5, its next
+  milestone is `Frames` and a `learning` row on a finished milestone's
+  concept is collected by the struggle collector (gentle repair)
+- **THEN** that repair is primary (`teachback`, `energy_demand == "low"`) with
+  `PlanRef(plan, None)`, `energy_deferred` names `(plan, 1, 5, 3)`,
+  `energy_deferred_repairs` is empty, and no `study_plan:` or `body_double`
+  candidate exists; at `medium` energy nothing is deferred and the milestone
+  is synthesised
+
+#### Scenario: A live struggle's repair defers at low energy like new work
+- **WHEN** energy is `low` and the struggle collector holds a `struggling` row
+  seen 3 days ago on a plan concept, a `struggling` row seen 20 days ago on
+  another, a `struggling` row seen 1 day ago unrelated to any plan, and a
+  `confident` row kept only for a teach-back score of 9
+- **THEN** none of the four is ranked; `energy_deferred_repairs` names all
+  four — the live plan-related one `("high", 6, 3)` with the plan's id and
+  title, the 20-day one `medium` (4), the weak-teach-back one `medium`, the
+  unrelated one with `plan_id` and `plan_title` `None` — `energy_deferred`
+  still names the milestone alone, and at `medium` energy the key is absent
+  and the live repair is ranked again
+
+#### Scenario: Due recall is never deferred
+- **WHEN** energy is `low`, a due row on a plan concept is collected with
+  `confidence == "struggling"` and a live struggle repair is also collected
+- **THEN** the due row is primary with `PlanRef(plan, None)`, the repair is
+  in `energy_deferred_repairs`, and no `body_double` candidate exists
+
+#### Scenario: Nothing plan-related fits, so the engine proposes sitting with the plan
+- **WHEN** energy is `low`, the plan's `energy_floor` is 5 (milestone
+  deferred) and its only repair is a live struggle (deferred)
+- **THEN** the primary is `source == "body_double"`, `action_type ==
+  "conversation"`, `plan_refs == (PlanRef(plan, None),)`, `evidence_command ==
+  'studyloop study "<plan title>" --mode co-study'`, its reason names the
+  deferred milestone and the deferred repair, `starter` is `false`, and the
+  JSON keys are the golden's then `active_plans`, `energy_deferred`,
+  `energy_deferred_repairs`
+
+#### Scenario: The body-double candidate is a proposal, not a filter
+- **WHEN** the same world also collects an unrelated due item
+- **THEN** the due item is primary with no refs and the body-double
+  candidate is the only alternate, with a lower score
+
+#### Scenario: No active plan, no body double
+- **WHEN** no plan document exists (or only a draft) and a live unrelated
+  struggle is collected at `low` energy
+- **THEN** no `body_double` candidate exists, `energy_deferred_repairs` names
+  the struggle with `plan_id None`, `starter` is `true` and the starter's
+  reason says the energy deferred the repair work
+
+#### Scenario: A deferred milestone is never named by a reference
+- **WHEN** energy is `low`, the plan's `energy_floor` is 5 and the only
+  collected candidate's concept equals the next milestone's concept
+- **THEN** the candidate is primary with `PlanRef(plan, None)` while
+  `energy_deferred` names that milestone; at `medium` energy the same
+  candidate carries `PlanRef(plan, 0)` and nothing is deferred
+
+#### Scenario: An unready active plan is matched but never named
+- **WHEN** an active plan has no mission and no success criteria (unready)
+  and a collected candidate equals its next milestone's concept
+- **THEN** the candidate is primary with `PlanRef(plan, None)`, no
+  `study_plan:` candidate exists, the plan's `active_plans` entry has
+  `ready == False` and `eligible == False`, and one warning names the plan,
+  its blockers and "pause or repair"
+
+#### Scenario: No substring matching
+- **WHEN** a milestone titled `Window functions deep dive` has no concepts
+  and candidates `window functions deep dive tutorial`, `window` and
+  `joins`/`SQL` are collected
+- **THEN** only `joins` is plan-related (`PlanRef(plan, None)` via the topic
+  `sql`, casefolded); the other two carry no refs
+
+#### Scenario: Every matching plan is referenced, in order
+- **WHEN** six active plans (overdue, soon, later, three undated with
+  distinct and tied `updated`) all name the primary's concept
+- **THEN** `plan_refs` lists all six ordered overdue → soon → later → undated
+  by latest `updated` then `plan_id`, and `active_plans` is in the same order
+
+#### Scenario: A plan-backed action is preserved when energy allows
+- **WHEN** four unrelated due items outrank everything and the plan's
+  `energy_floor` is 5
+- **THEN** at `medium` energy the synthesised milestone replaces the second
+  alternate (the primary and first alternate are unchanged); at `low` energy
+  the primary and first alternate are the two best unrelated items, the
+  second alternate is the body-double proposal with `PlanRef(plan, None)`,
+  no `study_plan:` candidate exists and `energy_deferred` names the milestone
+
+#### Scenario: Fully-checked plan emits a completion action
+- **WHEN** an active plan's every milestone is done and an unrelated due item
+  is collected
+- **THEN** `completion_actions` names the plan, the due item is primary with
+  no refs, no `study_plan:` candidate exists, and the plan's `active_plans`
+  entry has `next_milestone_index == None`
+
+#### Scenario: Renderers show, never re-rank
+- **WHEN** `studyloop now --energy low`, `GET /api/now?energy=low` and the
+  daily recap run against the energy-deferral fixture, and against the
+  live-struggle fixture
+- **THEN** each names the primary the engine chose, the plan it advances, the
+  deferred milestone and — for the live-struggle fixture — one line per
+  deferred repair with its demand and the day's capability; a body-double
+  primary is labelled "Sit with the plan" with its `--mode co-study` door
+  and never "Record evidence"; with no plan the CLI panel prints no plan
+  lines, `GET /api/now` equals the golden, and the recap's `plan_context` is
+  absent from its JSON, its spoken text and the `recap today` panel
+
+#### Scenario: Learner-authored text is data to every renderer
+- **WHEN** an active plan's title, topic or milestone text contains Rich
+  markup, HTML or shell punctuation (`Plan [/bold]`, `<script>…`, `"; rm -rf ~`)
+- **THEN** `build_now_plan` ranks and serialises it unchanged and writes
+  nothing to the document; `studyloop now` exits 0 and shows the text
+  literally; the Today card renders it through `x-text`
diff --git a/openspec/changes/plan-integration-followons/tasks.md b/openspec/changes/plan-integration-followons/tasks.md
index 8f3b6d44..da05fd77 100644
--- a/openspec/changes/plan-integration-followons/tasks.md
+++ b/openspec/changes/plan-integration-followons/tasks.md
@@ -199,14 +199,28 @@ writer, through the existing gate, closes that. Kept out of item 3 so item 3's f
       and its three renderers are milestone-shaped; the body-double door is `studyloop study … --mode co-study` /
       the Body Double view's session start, not the read-only `body_double.py` focus route, so the candidate sets
       its `evidence_command` explicitly. T5.2's RED names hold; a sixth test pins the new key's rendering.)
-- [ ] **T5.2** RED `tests/test_now_plan_guidance.py`: `test_live_struggle_repair_defers_at_low_energy_like_new_work`,
+- [x] **T5.2** RED `tests/test_now_plan_guidance.py`: `test_live_struggle_repair_defers_at_low_energy_like_new_work`,
       `test_recovered_repair_stays_eligible_at_low_energy`, `test_body_double_candidate_is_synthesised_when_nothing_plan_related_fits`,
       `test_body_double_is_a_proposal_not_a_filter`, `test_body_double_never_appears_without_an_active_plan`,
-      golden byte-identity still green.
-- [ ] **T5.3** GREEN: `energy_demand`, rule 3 extension, `body_double` synthesis, CLI/Today "sit with the plan" line.
+      golden byte-identity still green. (2026-09-19, `ef319a7b` on `feat/energy-demand-body-double`: the five plus
+      the sixth, `test_cli_now_and_recap_render_deferred_repairs_and_the_body_double_door`, and five JS pins in
+      `tests/js/today-panel-plan.test.js` (`deferredRepairNotes`, `viewForAction`, markup). The struggle collector
+      runs for real over patched `observations.rows`, since demand is derived in the collector. 6 red / 40 green,
+      JS 5 red / 139 green, each for its missing name.)
+- [x] **T5.3** GREEN: `energy_demand`, rule 3 extension, `body_double` synthesis, CLI/Today "sit with the plan" line.
+      (2026-09-19: `DeferredRepair` + `energy_deferred_repairs`, `ENERGY_DEMAND_CAPABILITY`/`LIVE_STRUGGLE_DAYS`,
+      `_energy_demand` in the collector, `_defer_repairs` before rule 6, `_body_double_candidate` after it,
+      honest starter after a deferral; CLI `now` + recap + Today card lines; MODIFIED requirement in the
+      `active-learning-decisions` delta; docs `study-plans.md` "Plan-aware now" + `cli-reference.md`; design §5
+      "Decisions taken at GREEN" 1-5. Module 46/46, JS 144/144, e2e plan journeys 20/20, docs contract 39/39,
+      `mkdocs --strict` exit 0, `openspec validate` valid; full suite vs a clean `main` control — see the GREEN
+      commit's receipt.)
 - [ ] ⚖ **T5.4** Council review 7 (`review7`, same seats or `kimi-k2-thinking` third); arbitration; corrections.
 - [ ] **T5.5** Rubric row **3b** for the owner (`PENDING`); the change is archived only after the owner scores 3b
-      (4b was scored **yes / yes** on 2026-09-18, so 3b is the one row still outstanding).
+      (4b was scored **yes / yes** on 2026-09-18, so 3b is the one row still outstanding). (2026-09-19: row 3b
+      written into `receipts/now-rubric-2026-09-16.md` with three readings printed from the real engine — (a) live
+      struggle → body-double primary, (b) plus an unrelated due recall → due recall primary, proposal beneath,
+      (c) recovered `learning` → gentle teach-back primary — verdict `PENDING`.)

 ## Item 6 — proposals (no code)

diff --git a/packages/studyloop/src/studyloop/cli/_now.py b/packages/studyloop/src/studyloop/cli/_now.py
index 1d917906..48cf89e6 100644
--- a/packages/studyloop/src/studyloop/cli/_now.py
+++ b/packages/studyloop/src/studyloop/cli/_now.py
@@ -46,6 +46,9 @@ def _render_plan(plan) -> None:
     primary = plan.primary
     plans = _active_plans(plan)
     plan_line = _plan_line(primary, plans)
+    # A body-double primary (design §5) carries the co-study session door, not a
+    # progress write: label it as the door it is.
+    door = "Sit with the plan" if primary.source == "body_double" else "Record evidence"
     body = (
         f"[bold]{escape(primary.concept)}[/bold]\n"
         f"Topic: [cyan]{escape(primary.topic)}[/cyan]\n"
@@ -54,7 +57,7 @@ def _render_plan(plan) -> None:
         f"Why: {escape(primary.reason)}\n"
         f"Source: [dim]{escape(primary.source)}[/dim]\n"
         + (f"Plan: [magenta]{escape(plan_line)}[/magenta]\n" if plan_line else "")
-        + f"\n[bold]Record evidence:[/bold]\n{escape(primary.evidence_command)}"
+        + f"\n[bold]{door}:[/bold]\n{escape(primary.evidence_command)}"
     )
     console.print(Panel(body, title="Study Now", border_style="cyan"))

@@ -69,6 +72,16 @@ def _render_plan(plan) -> None:
             f"energy {deferred.energy_floor}/10; {plan.energy} energy carries "
             f"{deferred.energy_capability}/10. Plan-related review and repair stay available."
         )
+    # One line per deferred repair (design §5, amendment 2): its own key, its
+    # own sentence — a repair has no milestone number to print.
+    for repair in getattr(plan, "energy_deferred_repairs", ()):
+        where = f"{escape(repair.plan_title)} — " if repair.plan_title else ""
+        console.print(
+            f"[yellow]Deferred for energy:[/yellow] {where}repairing "
+            f"“{escape(repair.concept)}” ({escape(repair.confidence)}) asks for "
+            f"{repair.required_capability}/10; {plan.energy} energy carries "
+            f"{repair.energy_capability}/10. Due recall and gentle review stay available."
+        )
     for completion in getattr(plan, "completion_actions", ()):
         # "Closing review", not "Plan complete": the status is still active until
         # the learner agrees with the architect (council review 6, F6).
diff --git a/packages/studyloop/src/studyloop/learning/decision.py b/packages/studyloop/src/studyloop/learning/decision.py
index 37132cbd..2f0960e3 100644
--- a/packages/studyloop/src/studyloop/learning/decision.py
+++ b/packages/studyloop/src/studyloop/learning/decision.py
@@ -53,10 +53,31 @@ INTERLEAVE_RATIOS: dict[EnergyLevel, dict[str, int]] = {

 #: Design §3 rule 3 — what each self-reported energy level can carry, on the
 #: 1-10 scale a plan's ``energy_floor`` uses. Below a plan's floor, *new*
-#: milestone work is deferred; plan-related due recall and struggle repair
-#: stay eligible, because repair is cheaper than encoding.
+#: milestone work is deferred; plan-related due recall stays eligible, and so
+#: does struggle repair whose own demand (below) the energy can carry.
 ENERGY_CAPABILITY: dict[EnergyLevel, int] = {"low": 3, "medium": 6, "high": 10}

+EnergyDemand = Literal["low", "medium", "high"]
+
+#: Design §5 (item 5, D-F) — the capability a struggle repair asks for, by the
+#: demand class the struggle collector derives from its own row classes: a
+#: ``struggling`` row seen within ``LIVE_STRUGGLE_DAYS`` is ``high`` (a live
+#: struggle; hands-on repair on a low-energy day risks compounding it — rubric
+#: row 3, the owner's one "no"); ``struggling`` older than that, or a row whose
+#: only signal is a weak teach-back, is ``medium``; ``learning`` is ``low`` —
+#: the gentle review "repair is cheaper than encoding" was always about.
+#: Compared with ``ENERGY_CAPABILITY``: ``low`` (3) carries only low demand,
+#: ``medium`` (6) carries every class.
+ENERGY_DEMAND_CAPABILITY: dict[EnergyDemand, int] = {"high": 6, "medium": 4, "low": 0}
+LIVE_STRUGGLE_DAYS = 14
+
+#: Base score of the synthesised body-double candidate (design §5): below
+#: ``MILESTONE_BASE_SCORE`` so every real candidate — due, repair, practice,
+#: continuity, a synthesised milestone — outranks it. A proposal, never a
+#: filter; the plan bias then lifts it over nothing but the starter.
+BODY_DOUBLE_BASE_SCORE = 30
+BODY_DOUBLE_SOURCE = "body_double"
+
 #: Rule 5 — the bias a plan-related candidate receives. Large enough to decide
 #: a near-tie inside one urgency class (two due items a few days apart), small
 #: enough that a clearly more-urgent unrelated candidate (a struggling repair,
@@ -129,6 +150,32 @@ class DeferredMilestone:
         return asdict(self)


+@dataclass(frozen=True)
+class DeferredRepair:
+    """A struggle repair the current energy cannot carry (rule 3 extended, design §5).
+
+    Its own type, not a :class:`DeferredMilestone`: that one has a mandatory
+    ``milestone_index`` and its three renderers print ``milestone N`` — a repair
+    folded into it would read "milestone None" (T5.1 amendment 2). ``plan_id``
+    and ``plan_title`` are set when the struggle's concept, topic or course
+    matches an active plan, else ``None``: the deferral does not depend on a
+    plan — a live struggle is a live struggle whether or not a plan names it.
+    """
+
+    plan_id: str | None
+    plan_title: str | None
+    concept: str
+    topic: str
+    confidence: str
+    energy_demand: EnergyDemand
+    required_capability: int
+    energy_capability: int
+    reason: str
+
+    def to_json_dict(self) -> dict:
+        return asdict(self)
+
+
 @dataclass(frozen=True)
 class CompletionAction:
     """What to do about an active plan whose every milestone is checked (rule 9).
@@ -203,6 +250,7 @@ class NowPlan:
     starter: bool = False
     active_plans: tuple[ActivePlanSummary, ...] = ()
     energy_deferred: tuple[DeferredMilestone, ...] = ()
+    energy_deferred_repairs: tuple[DeferredRepair, ...] = ()
     completion_actions: tuple[CompletionAction, ...] = ()
     warnings: tuple[str, ...] = ()

@@ -224,6 +272,10 @@ class NowPlan:
             data["active_plans"] = [item.to_json_dict() for item in self.active_plans]
         if self.energy_deferred:
             data["energy_deferred"] = [item.to_json_dict() for item in self.energy_deferred]
+        if self.energy_deferred_repairs:
+            data["energy_deferred_repairs"] = [
+                item.to_json_dict() for item in self.energy_deferred_repairs
+            ]
         if self.completion_actions:
             data["completion_actions"] = [item.to_json_dict() for item in self.completion_actions]
         if self.warnings:
@@ -385,6 +437,7 @@ def _struggle_candidates(time_minutes: int) -> list[_Candidate]:
         conn.close()

     candidates: list[_Candidate] = []
+    today = datetime.now(UTC).date()
     for row in rows:
         row_keys = set(row.keys())
         concept = str(row["concept"])
@@ -420,12 +473,45 @@ def _struggle_candidates(time_minutes: int) -> list[_Candidate]:
                     "confidence": confidence,
                     "last_teachback_score": teachback_score,
                     "session_count": row["session_count"],
+                    # Design §5: derived once, here, from the collector's own
+                    # classes; the deferral and every renderer read this value.
+                    "energy_demand": _energy_demand(
+                        confidence, row.get("last_seen") if "last_seen" in row_keys else None, today
+                    ),
                 },
             )
         )
     return candidates


+def _energy_demand(confidence: str | None, last_seen: object, today: date) -> EnergyDemand:
+    """The capability class a repair asks for (design §5, T5.1 amendment 1).
+
+    ``struggling`` seen within :data:`LIVE_STRUGGLE_DAYS` is a live struggle —
+    ``high``; a ``struggling`` row older than that, or one the collector kept
+    only for its weak teach-back, is ``medium``; ``learning`` is ``low``. An
+    unreadable ``last_seen`` on a ``struggling`` row is read as live: the
+    cautious side is the one the finding asks for.
+    """
+    if confidence == "learning":
+        return "low"
+    if confidence != "struggling":
+        return "medium"
+    seen = _days_since(last_seen, today)
+    if seen is None or seen <= LIVE_STRUGGLE_DAYS:
+        return "high"
+    return "medium"
+
+
+def _days_since(stamp: object, today: date) -> int | None:
+    if not isinstance(stamp, str) or not stamp:
+        return None
+    try:
+        return (today - datetime.fromisoformat(stamp).date()).days
+    except ValueError:
+        return None
+
+
 def _due_card_candidates(time_minutes: int) -> list[_Candidate]:
     try:
         from studyloop.services.review import list_course_summaries
@@ -566,7 +652,7 @@ def _transfer_candidates(time_minutes: int) -> list[_Candidate]:
     return candidates


-def _starter_candidate(time_minutes: int) -> _Candidate:
+def _starter_candidate(time_minutes: int, *, after_deferral: bool = False) -> _Candidate:
     try:
         from studyloop.topics import get_topics

@@ -579,11 +665,20 @@ def _starter_candidate(time_minutes: int) -> _Candidate:
     else:
         topic = "python"
         display = "Python"
+    # "No learning evidence" would be false when evidence exists and today's
+    # energy deferred all of it (design §5); say what happened instead. The
+    # golden world has nothing to defer, so its sentence is unchanged.
+    reason = (
+        "Today's energy deferred the repair work it cannot carry; "
+        "start with one small retrieval signal instead"
+        if after_deferral
+        else "No learning evidence found yet; start by creating one small retrieval signal"
+    )
     return _Candidate(
         concept="one tiny recall loop",
         topic=topic,
         course=topic,
-        reason="No learning evidence found yet; start by creating one small retrieval signal",
+        reason=reason,
         action_type="recall",
         estimated_minutes=_estimate_minutes("recall", time_minutes, 10),
         source="starter",
@@ -967,6 +1062,18 @@ class _PlanContext:
             synthesised.append(_milestone_candidate(plan, milestone, time_minutes))
         return synthesised

+    def first_match(self, candidate: _Candidate) -> ActivePlanGuidance | None:
+        """The first matchable plan (plan order) this candidate's keys equal, if any."""
+        keys = _candidate_keys(candidate)
+        for plan in self.matchable:
+            if keys & frozenset(plan.match_keys):
+                return plan
+        return None
+
+    def is_plan_related(self, candidate: _Candidate) -> bool:
+        """Rule 5's test, before scoring: a ref already attached, or a key match."""
+        return bool(candidate.plan_refs) or self.first_match(candidate) is not None
+
     def attach_refs(self, candidate: _Candidate) -> _Candidate:
         """Rule 7: every matching plan, most specific milestone per plan, in plan order.

@@ -1048,6 +1155,110 @@ def _milestone_candidate(
     )


+def _defer_repairs(
+    candidates: list[_Candidate], *, energy: EnergyLevel, plans: _PlanContext
+) -> tuple[list[_Candidate], tuple[DeferredRepair, ...]]:
+    """Rule 3 extended (design §5): repair above its own energy demand is deferred like new work.
+
+    Only a candidate carrying ``energy_demand`` — the struggle collector's — is
+    judged. Due recall is never deferred whatever its confidence says, and a
+    ``learning`` repair (``low`` demand) is always carried. Plan-independent:
+    the entry names the plan when one matches, else ``None``.
+    """
+    capability = ENERGY_CAPABILITY[energy]
+    kept: list[_Candidate] = []
+    deferred: list[DeferredRepair] = []
+    for candidate in candidates:
+        demand = candidate.metadata.get("energy_demand")
+        if demand not in ENERGY_DEMAND_CAPABILITY:
+            kept.append(candidate)
+            continue
+        required = ENERGY_DEMAND_CAPABILITY[demand]
+        if capability >= required:
+            kept.append(candidate)
+            continue
+        plan = plans.first_match(candidate)
+        confidence = str(candidate.metadata.get("confidence") or "struggling")
+        if demand == "high":
+            what = "a live struggle"
+        elif confidence == "struggling":
+            what = "an older struggle"
+        else:
+            what = "a weak teach-back"
+        deferred.append(
+            DeferredRepair(
+                plan_id=plan.plan.plan_id if plan is not None else None,
+                plan_title=plan.plan.title if plan is not None else None,
+                concept=candidate.concept,
+                topic=candidate.topic,
+                confidence=confidence,
+                energy_demand=demand,
+                required_capability=required,
+                energy_capability=capability,
+                reason=(
+                    f"{energy} energy carries {capability}/10; repairing "
+                    f"{candidate.concept!r} ({what}) asks for at least {required}/10 — "
+                    "deferred like new work; due recall and gentle review stay available"
+                ),
+            )
+        )
+    return kept, tuple(deferred)
+
+
+def _body_double_candidate(
+    plans: _PlanContext,
+    candidates: list[_Candidate],
+    deferred_repairs: tuple[DeferredRepair, ...],
+    *,
+    energy: EnergyLevel,
+    time_minutes: int,
+) -> _Candidate | None:
+    """Design §5's floor: nothing plan-related fits and an active plan exists → sit with it.
+
+    One ``source="body_double"`` conversation candidate, base below every real
+    candidate's (a proposal, not a filter), ``plan_refs`` ``(plan, None)`` for
+    every matchable plan, reason naming what it stands in for, and the co-study
+    session door as its command (T5.1 amendment 3): ``_evidence_command`` has
+    no branch for it and would answer with a progress *write*, not a door.
+    """
+    if not plans.matchable or any(plans.is_plan_related(c) for c in candidates):
+        return None
+    # An active-but-unready plan is matched but never synthesised (spec rule 8);
+    # the body double is a synthesis, so only ready plans are sat with. The
+    # warning beside it already says "pause or repair".
+    named = [plan.plan for plan in plans.matchable if plan.readiness.ready]
+    if not named:
+        return None
+    first = named[0]
+    titles = " and ".join(plan.title for plan in named)
+    items = [
+        f"milestone {d.milestone_index + 1} “{d.title}” of {d.plan_title}" for d in plans.deferred
+    ] + [f"repair of “{d.concept}”" for d in deferred_repairs]
+    deferred_note = f" — deferred: {'; '.join(items)}" if items else ""
+    topic = first.topics[0] if first.topics else "study"
+    safe_title = first.title.replace('"', '\\"')
+    return _Candidate(
+        concept=f"Sit with {first.title}" if len(named) == 1 else "Sit with your plans",
+        topic=topic,
+        course=None,
+        reason=(
+            f"Nothing plan-related fits {energy} energy today{deferred_note}. "
+            f"Sit with {titles} instead: a body-double session, no new material, no repair."
+        ),
+        action_type="conversation",
+        estimated_minutes=_estimate_minutes("conversation", time_minutes, 25),
+        source=BODY_DOUBLE_SOURCE,
+        evidence_command=f'studyloop study "{safe_title}" --mode co-study',
+        score=BODY_DOUBLE_BASE_SCORE,
+        metadata={
+            "plan_id": first.plan_id,
+            "deferred_milestones": len(plans.deferred),
+            "deferred_repairs": len(deferred_repairs),
+        },
+        plan_refs=tuple(PlanRef(plan.plan_id, None) for plan in named),
+    )
+
+
 def _guarantee_plan_backed(ranked: list[_Candidate], time_minutes: int) -> list[_Candidate]:
     """Rule 8: ≥ 1 plan-backed action among primary + alternates when time permits.

@@ -1084,11 +1295,14 @@ def build_now_plan(

     Order of operations is design §3's: guidance is read once (1), candidates
     are collected as before (2), the energy capability decides which next
-    milestones are eligible (3), matching is key equality (4), scoring is
-    today's plus the plan bias (5), an unrepresented eligible milestone is
-    synthesised (6), then de-duplication and reference attachment (7), the
-    plan-backed guarantee (8), with fully-checked plans reported as
-    completion actions rather than candidates (9).
+    milestones are eligible and — since design §5 — which struggle repairs
+    are carried, the rest deferred beside them (3), matching is key equality
+    (4), scoring is today's plus the plan bias (5), an unrepresented eligible
+    milestone is synthesised (6) — and when nothing plan-related fits an
+    active plan, one body-double proposal is (§5) — then de-duplication and
+    reference attachment (7), the plan-backed guarantee (8), with
+    fully-checked plans reported as completion actions rather than
+    candidates (9).
     """
     time_minutes = max(5, min(int(time_minutes), 180))
     now = datetime.now(UTC)
@@ -1103,11 +1317,19 @@ def build_now_plan(
     ]
     if interleave == "adaptive" and energy != "low":
         candidates.extend(_transfer_candidates(time_minutes))
+    # Rule 3 extended: before rule 6 reads what is "represented", so a deferred
+    # repair does not stand in for the milestone it can no longer carry.
+    candidates, deferred_repairs = _defer_repairs(candidates, energy=energy, plans=plans)
     candidates.extend(plans.milestone_candidates(candidates, time_minutes))
+    body_double = _body_double_candidate(
+        plans, candidates, deferred_repairs, energy=energy, time_minutes=time_minutes
+    )
+    if body_double is not None:
+        candidates.append(body_double)

     starter = False
     if not candidates:
-        candidates = [_starter_candidate(time_minutes)]
+        candidates = [_starter_candidate(time_minutes, after_deferral=bool(deferred_repairs))]
         starter = True

     ranked = _dedupe(
@@ -1137,6 +1359,7 @@ def build_now_plan(
         interleave_ratio=INTERLEAVE_RATIOS[energy] if interleave == "adaptive" else {},
         active_plans=plans.summaries,
         energy_deferred=plans.deferred,
+        energy_deferred_repairs=deferred_repairs,
         completion_actions=plans.completions,
         warnings=plans.warnings,
     )
diff --git a/packages/studyloop/src/studyloop/learning/recap.py b/packages/studyloop/src/studyloop/learning/recap.py
index b9f995fd..58618fd2 100644
--- a/packages/studyloop/src/studyloop/learning/recap.py
+++ b/packages/studyloop/src/studyloop/learning/recap.py
@@ -65,6 +65,13 @@ def _plan_context(plan) -> str:
             f"{deferred.title}, waits for more energy: it needs {deferred.energy_floor} of 10 "
             f"and today's energy carries {deferred.energy_capability}."
         )
+    for repair in getattr(plan, "energy_deferred_repairs", ()):
+        where = f" of {repair.plan_title}" if repair.plan_title else ""
+        sentences.append(
+            f"Repairing {repair.concept}{where} waits for more energy: it asks for "
+            f"{repair.required_capability} of 10 and today's energy carries "
+            f"{repair.energy_capability}."
+        )
     for completion in getattr(plan, "completion_actions", ()):
         sentences.append(completion.action)
     return " ".join(sentences)
diff --git a/packages/studyloop/src/studyloop/web/static/index.html b/packages/studyloop/src/studyloop/web/static/index.html
index c23e0982..e7885fea 100644
--- a/packages/studyloop/src/studyloop/web/static/index.html
+++ b/packages/studyloop/src/studyloop/web/static/index.html
@@ -1104,12 +1104,17 @@
                cannot carry, and plans whose every milestone is checked.
                Not a `.today-card` on purpose: the browser smoke test addresses
                the single action card by that class. -->
-          <div x-show="!loading && plan && (deferredNotes().length > 0 || completionNotes().length > 0 || warningNotes().length > 0)"
+          <div x-show="!loading && plan && (deferredNotes().length > 0 || deferredRepairNotes().length > 0 || completionNotes().length > 0 || warningNotes().length > 0)"
                class="today-plan-notes">
             <p class="today-parked-label">Your plans</p>
             <template x-for="(note, i) in deferredNotes()" :key="'d' + i">
               <p class="today-meta">Deferred for energy: <span x-text="note"></span></p>
             </template>
+            <!-- Struggle repair today's energy cannot carry (design §5): its own
+                 key and line — a repair has no milestone number to print. -->
+            <template x-for="(note, i) in deferredRepairNotes()" :key="'r' + i">
+              <p class="today-meta">Deferred for energy: <span x-text="note"></span></p>
+            </template>
             <!-- One block per finished plan (council review 6, F6): the closing
                  review's sentence with ITS OWN evidence lines beneath it, keyed by
                  plan id, so two finished plans never share one flat list. The label
diff --git a/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js b/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
index ceca6023..0e87dd53 100644
--- a/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
+++ b/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
@@ -114,7 +114,15 @@ export function todayPanel() {
     },

     startAction(rec) {
-      Alpine.store('nav').go(this._viewFor(rec.action_type));
+      Alpine.store('nav').go(this.viewForAction(rec));
+    },
+
+    /* The view an action starts in. A body-double proposal (design §5) is a
+       session in the Body Double view, whatever its action_type says; every
+       other action keeps the action_type mapping above. */
+    viewForAction(rec) {
+      if (rec && rec.source === 'body_double') return 'body-double';
+      return this._viewFor(rec && rec.action_type);
     },

     /* ---- Plan relevance (issue #10) — rendering of what /api/now ranked. ----
@@ -162,6 +170,21 @@ export function todayPanel() {
       );
     },

+    /* One line per struggle repair today's energy cannot carry (design §5,
+       amendment 2): its own key, its own sentence — a repair has no milestone
+       number. A repair unrelated to any plan names none. */
+    deferredRepairNotes() {
+      const repairs = (this.plan && this.plan.energy_deferred_repairs) || [];
+      const energy = (this.plan && this.plan.energy) || 'current';
+      return repairs.map((r) => {
+        const head = r.plan_title
+          ? `${r.plan_title} \u2014 repairing`
+          : 'Repairing';
+        return `${head} \u201c${r.concept}\u201d (${r.confidence}) waits for more energy `
+          + `(asks for ${r.required_capability}/10, ${energy} energy carries ${r.energy_capability}/10)`;
+      });
+    },
+
     /* One block per finished plan (council review 6, F6): the closing review's
        sentence and ITS evidence lines, keyed by plan_id, in the engine's order.
        With two finished plans a flat list of lines lost the plan each belonged
@@ -199,6 +222,7 @@ export function todayPanel() {
       return (
         this.planLabel(this.plan && this.plan.primary) !== ''
         || this.deferredNotes().length > 0
+        || this.deferredRepairNotes().length > 0
         || this.completionNotes().length > 0
         || this.warningNotes().length > 0
       );
diff --git a/packages/studyloop/tests/js/today-panel-plan.test.js b/packages/studyloop/tests/js/today-panel-plan.test.js
index 6de30487..004c2069 100644
--- a/packages/studyloop/tests/js/today-panel-plan.test.js
+++ b/packages/studyloop/tests/js/today-panel-plan.test.js
@@ -268,3 +268,100 @@ test('warningNotes: absent key renders no warning text', () => {
   assert.deepEqual(panel.warningNotes(), []);
   assert.equal(panel.hasPlanContext, false);
 });
+
+/* Item 5 (D-F): a repair the day's energy cannot carry, in its own additive key
+   (design §5 amendment 2 — `energy_deferred` is milestone-shaped), and the
+   body-double proposal the engine synthesises when nothing plan-related fits. */
+const DEFERRED_REPAIR_PAYLOAD = {
+  ...PLAN_PAYLOAD,
+  primary: {
+    concept: 'Sit with SQL Windows',
+    action_type: 'conversation',
+    estimated_minutes: 25,
+    reason: 'Nothing plan-related fits low energy today',
+    source: 'body_double',
+    evidence_command: 'studyloop study "SQL Windows" --mode co-study',
+    plan_refs: [{ plan_id: 'sql-windows', milestone_index: null }],
+  },
+  energy_deferred_repairs: [
+    {
+      plan_id: 'sql-windows',
+      plan_title: 'SQL Windows',
+      concept: 'window function',
+      topic: 'sql',
+      confidence: 'struggling',
+      energy_demand: 'high',
+      required_capability: 6,
+      energy_capability: 3,
+      reason: 'low energy carries 3/10; repairing a live struggle asks for at least 6/10',
+    },
+  ],
+};
+
+test('deferredRepairNotes: one readable line per energy-deferred repair', () => {
+  const panel = todayPanel();
+  panel.plan = DEFERRED_REPAIR_PAYLOAD;
+
+  assert.deepEqual(panel.deferredRepairNotes(), [
+    'SQL Windows \u2014 repairing \u201cwindow function\u201d (struggling) waits for more energy '
+    + '(asks for 6/10, low energy carries 3/10)',
+  ]);
+});
+
+test('deferredRepairNotes: a repair unrelated to any plan names no plan, and counts as plan context alone', () => {
+  const panel = todayPanel();
+  panel.plan = {
+    ...NO_PLAN_PAYLOAD,
+    energy: 'low',
+    energy_deferred_repairs: [
+      {
+        plan_id: null,
+        plan_title: null,
+        concept: 'decorators',
+        topic: 'python',
+        confidence: 'struggling',
+        energy_demand: 'high',
+        required_capability: 6,
+        energy_capability: 3,
+        reason: 'low energy carries 3/10',
+      },
+    ],
+  };
+
+  assert.deepEqual(panel.deferredRepairNotes(), [
+    'Repairing \u201cdecorators\u201d (struggling) waits for more energy '
+    + '(asks for 6/10, low energy carries 3/10)',
+  ]);
+  assert.equal(panel.hasPlanContext, true);
+});
+
+test('deferredRepairNotes: absent key renders nothing, before and after assignment', () => {
+  const panel = todayPanel();
+
+  assert.deepEqual(panel.deferredRepairNotes(), []);
+
+  panel.plan = PLAN_PAYLOAD;
+
+  assert.deepEqual(panel.deferredRepairNotes(), []);
+});
+
+test('a body-double primary starts in the Body Double view; every other action keeps its view', () => {
+  const panel = todayPanel();
+
+  assert.equal(panel.viewForAction(DEFERRED_REPAIR_PAYLOAD.primary), 'body-double');
+  assert.equal(panel.viewForAction(PLAN_PAYLOAD.primary), 'study-session');
+  assert.equal(panel.viewForAction(NO_PLAN_PAYLOAD.primary), 'flashcards');
+});
+
+test('the Today card markup renders the deferred repairs beside the deferred milestones', () => {
+  const html = fs.readFileSync(
+    new URL('../../src/studyloop/web/static/index.html', import.meta.url), 'utf8',
+  );
+  const start = html.indexOf('class="today-plan-notes"');
+  const end = html.indexOf('</div>', html.indexOf('warningNotes()', start));
+  const block = html.slice(start, end);
+  assert.match(block, /x-for="\(note, i\) in deferredRepairNotes\(\)" :key="'r' \+ i"/);
+  assert.match(block, /Deferred for energy: <span x-text="note">/);
+  const show = html.slice(html.lastIndexOf('x-show=', start), start);
+  assert.match(show, /deferredRepairNotes\(\)\.length > 0/, 'the notes block shows for a deferred repair alone');
+});
diff --git a/packages/studyloop/tests/test_learning_decision.py b/packages/studyloop/tests/test_learning_decision.py
index 347aa4ca..807a5743 100644
--- a/packages/studyloop/tests/test_learning_decision.py
+++ b/packages/studyloop/tests/test_learning_decision.py
@@ -48,7 +48,7 @@ def test_no_data_returns_starter_recommendation(monkeypatch) -> None:
     monkeypatch.setattr(
         decision,
         "_starter_candidate",
-        lambda time_minutes: _candidate("starter", score=10),
+        lambda time_minutes, after_deferral=False: _candidate("starter", score=10),
     )

     plan = build_now_plan()
diff --git a/packages/studyloop/tests/test_now_plan_guidance.py b/packages/studyloop/tests/test_now_plan_guidance.py
index 2bd3d24d..4027f3d0 100644
--- a/packages/studyloop/tests/test_now_plan_guidance.py
+++ b/packages/studyloop/tests/test_now_plan_guidance.py
@@ -335,7 +335,13 @@ def test_synthesizes_milestone_when_no_candidate_represents_it(monkeypatch) -> N


 def test_preserves_one_plan_backed_action_when_energy_allows(monkeypatch) -> None:
-    """Rule 8: ≥ 1 eligible plan-backed action in primary + alternates when energy permits."""
+    """Rule 8: ≥ 1 eligible plan-backed action in primary + alternates when energy permits.
+
+    Below the floor the milestone is deferred, never synthesised; since design §5
+    the plan-backed slot rule 8 keeps is then the body-double proposal — sitting
+    with the plan asks for no energy the day cannot carry — and the primary and
+    first alternate stay the real, higher-ranked candidates.
+    """
     _plan(
         "sql-windows", energy_floor=5, milestones=[Milestone("Frames", concepts=["window frame"])]
     )
@@ -350,7 +356,10 @@ def test_preserves_one_plan_backed_action_when_energy_allows(monkeypatch) -> Non

     low = build_now_plan(energy="low")

-    assert [rec.concept for rec in _all(low)] == ["due 0", "due 1", "due 2"]
+    assert [rec.concept for rec in _all(low)] == ["due 0", "due 1", "Sit with Sql Windows"]
+    assert low.alternates[1].source == "body_double"
+    assert low.alternates[1].plan_refs == (PlanRef("sql-windows", None),)
+    assert not any(rec.source.startswith("study_plan:") for rec in _all(low))
     assert [d.milestone_index for d in low.energy_deferred] == [0]


@@ -1153,3 +1162,309 @@ def test_completion_evidence_cap_keeps_the_counts_and_names_the_overflow(monkeyp
     assert action.evidence[-1].startswith("… and ")
     assert action.evidence[-1].endswith(" more")
     assert f"{action.due_reviews} due reviews" in action.action
+
+
+# ---------------------------------------------------------------------------
+# T5.2 — item 5 (D-F): per-item energy demand for repair, and the body-doubling
+# floor. Design §5 with its three T5.1 amendments. The struggle collector runs
+# for real here — demand is derived in the collector, so injecting candidates
+# through ``_due_progress_candidates`` would bypass the very thing under test.
+# ---------------------------------------------------------------------------
+
+
+def _struggle(
+    concept: str,
+    *,
+    topic: str = "sql",
+    confidence: str = "struggling",
+    days_ago: int = 3,
+    teachback: int | None = None,
+) -> dict:
+    """One row as ``history.observations.rows`` projects it.
+
+    ``last_seen`` is relative to the frozen clock.
+    """
+    from datetime import timedelta
+
+    seen = (FROZEN_NOW - timedelta(days=days_ago)).isoformat()
+    return {
+        "id": f"{topic}/{concept}",
+        "topic": topic,
+        "concept": concept,
+        "confidence": confidence,
+        "first_seen": seen,
+        "last_seen": seen,
+        "session_count": 1,
+        "notes": None,
+        "last_teachback_score": teachback,
+    }
+
+
+def _plant_struggles(
+    monkeypatch: pytest.MonkeyPatch, *rows: dict, due: tuple[_Candidate, ...] = ()
+) -> None:
+    """Silence every collector except the struggle collector, which reads ``rows``."""
+    from studyloop.history import observations
+
+    real_collector = decision._struggle_candidates
+    _patch_collectors(monkeypatch, *due)
+    monkeypatch.setattr(decision, "_struggle_candidates", real_collector)
+    monkeypatch.setattr(observations, "rows", lambda conn: [dict(row) for row in rows])
+
+
+def _row3_plan() -> None:
+    """Rubric row 3's plan: floor 5, milestone 0 done, milestone 1 ``Frames`` open."""
+    _plan(
+        "sql-windows",
+        title="SQL Windows",
+        energy_floor=5,
+        milestones=[
+            Milestone(title="Window basics", done=True, concepts=["window function"]),
+            Milestone(title="Frames", concepts=["window frame"]),
+        ],
+    )
+
+
+def test_live_struggle_repair_defers_at_low_energy_like_new_work(monkeypatch) -> None:
+    """Rule 3 extended (design §5, amendment 1 + 2): repair carries a demand of its own.
+
+    ``struggling`` seen within 14 days is ``high`` (asks for 6/10); ``struggling``
+    older than that, or a row whose only signal is a weak teach-back, is
+    ``medium`` (4/10). Below the capability the repair is deferred like new
+    milestone work — listed, not ranked — in its own additive key, plan-related
+    or not; the milestone deferral beside it is untouched.
+    """
+    _row3_plan()
+    _plant_struggles(
+        monkeypatch,
+        _struggle("window function", days_ago=3),  # live, plan-related → high
+        _struggle("window frame", days_ago=20),  # old, plan-related → medium
+        _struggle("decorators", topic="python", days_ago=1),  # live, unrelated → high
+        _struggle("closures", topic="python", confidence="confident", days_ago=2, teachback=9),
+    )
+
+    low = build_now_plan(energy="low")
+
+    deferred = {item.concept: item for item in low.energy_deferred_repairs}
+    assert set(deferred) == {"window function", "window frame", "decorators", "closures"}
+    assert not any(rec.concept in deferred for rec in _all(low)), "deferred repair is not ranked"
+
+    live = deferred["window function"]
+    assert isinstance(live, decision.DeferredRepair)
+    assert (live.plan_id, live.plan_title, live.topic, live.confidence) == (
+        "sql-windows",
+        "SQL Windows",
+        "sql",
+        "struggling",
+    )
+    assert (live.energy_demand, live.required_capability, live.energy_capability) == ("high", 6, 3)
+    assert "3/10" in live.reason and "6/10" in live.reason
+    assert (
+        deferred["window frame"].energy_demand,
+        deferred["window frame"].required_capability,
+    ) == (
+        "medium",
+        4,
+    )
+    assert deferred["closures"].energy_demand == "medium", (
+        "a weak teach-back alone is medium demand"
+    )
+    assert (deferred["decorators"].plan_id, deferred["decorators"].plan_title) == (None, None)
+    assert deferred["decorators"].energy_demand == "high"
+    # The milestone deferral is what it was (rule 3's original half).
+    assert [(d.plan_id, d.milestone_index) for d in low.energy_deferred] == [("sql-windows", 1)]
+
+    payload = low.to_json_dict()
+    assert [entry["concept"] for entry in payload["energy_deferred_repairs"]] == [
+        item.concept for item in low.energy_deferred_repairs
+    ]
+    assert payload["energy_deferred_repairs"][0]["energy_demand"] in {"high", "medium"}
+
+    # Medium energy (6/10) carries every demand class: nothing deferred, key absent.
+    medium = build_now_plan(energy="medium")
+
+    assert medium.energy_deferred_repairs == ()
+    assert "energy_deferred_repairs" not in medium.to_json_dict()
+    assert any(rec.concept == "window function" for rec in _all(medium))
+
+
+def test_recovered_repair_stays_eligible_at_low_energy(monkeypatch) -> None:
+    """A ``learning`` row is ``low`` demand — the gentle review "repair is cheaper than
+    encoding" was always about — and stays eligible below the plan's floor with its
+    plan-related ref. Due recall is unaffected whatever its confidence says."""
+    _row3_plan()
+    _plant_struggles(monkeypatch, _struggle("window function", confidence="learning", days_ago=2))
+
+    low = build_now_plan(energy="low")
+
+    assert low.primary.concept == "window function"
+    assert low.primary.action_type == "teachback"
+    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
+    assert low.primary.metadata["energy_demand"] == "low"
+    assert low.energy_deferred_repairs == ()
+    assert not any(rec.source == "body_double" for rec in _all(low))
+    assert [d.milestone_index for d in low.energy_deferred] == [1]
+
+    # A due row on a plan concept, even one recorded as struggling, is recall,
+    # not repair: it is never deferred and nothing is synthesised beside it.
+    import dataclasses
+
+    due = dataclasses.replace(
+        _candidate("window frame", topic="sql", score=100),
+        metadata={"confidence": "struggling", "days_ago": 6},
+    )
+    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3), due=(due,))
+
+    low = build_now_plan(energy="low")
+
+    assert low.primary.concept == "window frame"
+    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
+    assert [d.concept for d in low.energy_deferred_repairs] == ["window function"]
+    assert not any(rec.source == "body_double" for rec in _all(low))
+
+
+def test_body_double_candidate_is_synthesised_when_nothing_plan_related_fits(monkeypatch) -> None:
+    """Rubric row 3b's world: the plan's milestone is deferred and its only repair is a
+    live struggle, so nothing plan-related fits low energy. The engine proposes sitting
+    with the plan — a body-double session — naming what it stands in for, through the
+    session door (amendment 3), never the least-bad task."""
+    _row3_plan()
+    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
+
+    low = build_now_plan(energy="low")
+
+    primary = low.primary
+    assert primary.source == "body_double"
+    assert primary.action_type == "conversation"
+    assert primary.plan_refs == (PlanRef("sql-windows", None),)
+    assert primary.evidence_command == 'studyloop study "SQL Windows" --mode co-study'
+    assert "Frames" in primary.reason and "window function" in primary.reason
+    assert low.starter is False
+    assert low.alternates == []
+    assert [d.concept for d in low.energy_deferred_repairs] == ["window function"]
+    assert [d.milestone_index for d in low.energy_deferred] == [1]
+    assert decision.BODY_DOUBLE_BASE_SCORE < decision.MILESTONE_BASE_SCORE
+
+    golden_keys = list(json.loads(GOLDEN.read_text(encoding="utf-8")))
+    payload = low.to_json_dict()
+    assert list(payload) == [
+        *golden_keys,
+        "active_plans",
+        "energy_deferred",
+        "energy_deferred_repairs",
+    ]
+    assert payload["primary"]["source"] == "body_double"
+
+
+def test_body_double_is_a_proposal_not_a_filter(monkeypatch) -> None:
+    """An unrelated real candidate still wins; the body-double proposal sits beneath it
+    as an alternate, base score below any real candidate's."""
+    _row3_plan()
+    _plant_struggles(
+        monkeypatch,
+        _struggle("window function", days_ago=3),
+        due=(_candidate("decorators", topic="python", score=100),),
+    )
+
+    low = build_now_plan(energy="low")
+
+    assert low.primary.concept == "decorators"
+    assert low.primary.plan_refs == ()
+    assert [rec.source for rec in low.alternates] == ["body_double"]
+    assert low.alternates[0].score < low.primary.score
+    assert "Frames" in low.alternates[0].reason
+
+
+def test_body_double_is_never_synthesised_for_an_unready_plan(monkeypatch) -> None:
+    """An active-but-unready plan is matched but never synthesised (spec rule 8), and the
+    body double is a synthesis: with only a husk active and nothing plan-related fitting,
+    the engine proposes nothing to sit with — the warning already says repair it."""
+    husk = StudyPlan(
+        plan_id="husk",
+        title="Husk",
+        status="active",
+        created="2026-08-01T00:00:00+00:00",
+        updated="2026-09-01T00:00:00+00:00",
+        topics=["sql"],
+        milestones=[Milestone(title="Frames", concepts=["window frame"])],
+    )
+    store.create_plan(husk)  # no mission, no success criteria: unready
+    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
+
+    low = build_now_plan(energy="low")
+
+    assert not any(rec.source == "body_double" for rec in _all(low))
+    assert [d.concept for d in low.energy_deferred_repairs] == ["window function"]
+    assert low.starter is True
+    assert any("husk" in w for w in low.warnings)
+
+    # A ready plan beside the husk: the proposal names the ready one only; rule 7
+    # may still attach a `(husk, None)` ref because the topics match.
+    _row3_plan()
+
+    low = build_now_plan(energy="low")
+
+    assert low.primary.source == "body_double"
+    assert low.primary.concept == "Sit with SQL Windows"
+    assert PlanRef("sql-windows", None) in low.primary.plan_refs
+    assert low.primary.evidence_command == 'studyloop study "SQL Windows" --mode co-study'
+    assert "Husk" not in low.primary.reason
+
+
+def test_body_double_never_appears_without_an_active_plan(monkeypatch) -> None:
+    """No active plan, no plan to sit with: the deferral still happens (plan-independent,
+    ``plan_id`` ``None``), the golden world stays untouched, and a non-active plan is
+    not an active plan."""
+    _plant_struggles(monkeypatch, _struggle("decorators", topic="python", days_ago=1))
+
+    low = build_now_plan(energy="low")
+
+    assert not any(rec.source == "body_double" for rec in _all(low))
+    assert [(d.concept, d.plan_id, d.plan_title) for d in low.energy_deferred_repairs] == [
+        ("decorators", None, None)
+    ]
+    # Every real candidate was deferred: the starter stands in, and says why.
+    assert low.starter is True
+    assert "defer" in low.primary.reason.lower()
+
+    _plan("draft-plan", status="draft")
+
+    low = build_now_plan(energy="low")
+
+    assert not any(rec.source == "body_double" for rec in _all(low))
+    assert "active_plans" not in low.to_json_dict()
+
+
+def test_cli_now_and_recap_render_deferred_repairs_and_the_body_double_door(
+    monkeypatch,
+) -> None:
+    """Amendment 2's "readable off the top" rule: each renderer gains one line per
+    deferred repair, and a body-double primary shows its door, not "record evidence"."""
+    from click.testing import CliRunner
+
+    from studyloop.cli import cli
+    from studyloop.learning import recap
+
+    _row3_plan()
+    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
+
+    rich = CliRunner().invoke(cli, ["now", "--energy", "low"])
+    as_json = CliRunner().invoke(cli, ["now", "--energy", "low", "--json"])
+
+    assert rich.exit_code == 0, rich.output
+    flat = " ".join(rich.output.split())
+    assert "Deferred for energy" in flat and "Frames" in flat  # the milestone line stays
+    assert "window function" in flat and "6/10" in flat  # …and the repair has its own line
+    assert "Sit with the plan" in flat
+    assert "--mode co-study" in flat
+    assert "Record evidence" not in flat
+    assert as_json.exit_code == 0, as_json.output
+    payload = json.loads(as_json.output)
+    assert payload["primary"]["source"] == "body_double"
+    assert payload["energy_deferred_repairs"][0]["concept"] == "window function"
+    assert payload["energy_deferred_repairs"][0]["required_capability"] == 6
+
+    context = recap._plan_context(build_now_plan(energy="low"))
+
+    assert "Frames" in context
+    assert "window function" in context and "6 of 10" in context
```

## 4. Rubric row 3b as written (verbatim from `receipts/now-rubric-2026-09-16.md`)

| 3b | Energy-deferred — **re-run after D-F (item 5, 2026-09-19)** | Row 3's fixture (`sql-windows`, `energy_floor: 5`, milestone 0 `Window basics` done `[window function]`, milestone 1 `Frames` `[window frame]`; **energy `low`**, capability 3/10), with the struggle collector running for real over three readings: **(a)** `window function` recorded `struggling` 3 days ago (a live struggle); **(b)** the same plus an unrelated due recall `decorators`/python base 100; **(c)** `window function` recorded `learning` (recovered). | **(a)** primary **`Sit with SQL Windows`** (conversation, `source=body_double`, score 42, `plan_refs=[(sql-windows, None)]`, command `studyloop study "SQL Windows" --mode co-study`), reason *"Nothing plan-related fits low energy today — deferred: milestone 2 “Frames” of SQL Windows; repair of “window function”. Sit with SQL Windows instead: a body-double session, no new material, no repair."*; no alternates; `energy_deferred=[(sql-windows, 1, 5, 3)]`; **`energy_deferred_repairs=[(sql-windows, window function, struggling, high, 6, 3)]`** with reason *"low energy carries 3/10; repairing 'window function' (a live struggle) asks for at least 6/10 — deferred like new work; due recall and gentle review stay available"*. **(b)** primary **`decorators`** (118, no refs); the body-double proposal is the only alternate (42). **(c)** primary **`window function`** (teachback, 100, `plan_refs=[(sql-windows, None)]`, `energy_demand=low`); nothing deferred but the milestone. | Rule 3 extended (design §5): repair carries a demand derived in the struggle collector — live `struggling` → high (6/10), older `struggling` or a weak teach-back → medium (4/10), `learning` → low (0/10) — and below the capability is deferred like new work into its own key, never ranked; due recall is never deferred. When nothing plan-related fits and an active plan exists, one body-double candidate is synthesised (base 30 + 12 bias = 42 < any real candidate — a proposal, not a filter) carrying the co-study session door. | **PENDING** — owner: (a) would you sit with the plan rather than repair the live struggle today? (b) is the body-double proposal right to sit beneath the unrelated due recall? (c) is the gentle teach-back on a recovered concept one you would do at low energy? |

## 5. The control receipt (verbatim)

# Full-suite matched control — item 5 (D-F) — 2026-09-19

Two full `packages/studyloop/tests` runs in parallel, same machine, same
sandbox, `-q -p no:cacheprovider -rfE`:

| Tree | Worktree | Result |
| --- | --- | --- |
| **item 5** (`feat/energy-demand-body-double`, RED `ef319a7b` + GREEN working tree) | `studyloop-wt/item5` | 30 failed, **5126 passed**, 4 skipped, 804 deselected, 14 errors (10:17) |
| **control** (`main` `4f8e3e0f`, detached) | `studyloop-wt/ctrl-item5` | 30 failed, 5120 passed, 4 skipped, 804 deselected, 14 errors (10:24) |

Both worktrees were `uv sync --all-packages --group dev` and each proved to
import `studyloop` from its own tree before the run.

#### (receipt) Sorted failing-id sets

- item5 ∖ control = **∅** — zero regressions.
- control ∖ item5 = **∅** — nothing item 5 fixed by accident, and the six
  new tests account for the passed-count difference (+6).
- item5 ∖ committed environmental set (`full-suite-control-item4-2026-09-18.md`,
  44 ids + item 4's seven then-REDs) = **∅**. The seven ids on the other side of
  that comparison are item 4's REDs, green since `82293293`.

The 44 shared ids are the sandbox-environmental set the item-4 receipt lists
by name (journeys world guards, acceptance isolation, second-brain CLI/doctor,
harness-matrix live mechanics, obsidian vault isolation, fresh-install scope);
unchanged here, byte for byte.

#### (receipt) Scoped gates on the same tree

- `test_now_plan_guidance.py` 46/46 (six REDs flipped; golden `now_plan_no_active.json` byte-identical);
  `test_learning_decision.py` 5/5 (one stub updated to the starter's new keyword).
- JS `node --test packages/studyloop/tests/js/*.test.js` 144/144 (+5).
- e2e `test_journey_study_plan.py` + `test_plans_api.py` 20/20 (browser).
- `test_docs_plan_integration_contract.py` + `test_ci_workflow_contract.py` 39/39.
- `mkdocs build --strict` exit 0; `openspec validate plan-integration-followons` valid.
- ruff check / ruff format --check / pyright: clean on every touched file.

## 6. Reference facts you may rely on (verified on `6d5a2d0e`)

- `ENERGY_CAPABILITY = {"low": 3, "medium": 6, "high": 10}` (unchanged). New: `ENERGY_DEMAND_CAPABILITY =
  {"high": 6, "medium": 4, "low": 0}`, `LIVE_STRUGGLE_DAYS = 14`, `BODY_DOUBLE_BASE_SCORE = 30`,
  `BODY_DOUBLE_SOURCE = "body_double"`. `MILESTONE_BASE_SCORE = 48`, `PLAN_RELATED_BIAS = 12` (unchanged).
- Collector base scores (unchanged): due progress `100 + min(days_ago, 30)` (+35 struggling, +15 learning, +25
  weak teach-back); struggle repair 82 (`struggling`, hands-on) or 70 (else, teachback) `+ max(0, 14 − score) × 3`;
  due cards `96 + min(due_count, 20)`; continuity 58; transfer 52; practice 48; starter 10.
- Scoring adjustments (unchanged): low energy −14 for hands-on/visual, −28 for a topic switch from the last
  session; modality match +18 (`recall` matches `recall`/`teachback`; `conversation` matches
  `conversation`/`teachback`); plan bias +12 when `plan_refs` or a key match. So in row 3b reading (a) the body
  double scores 30 + 12 = 42; in (c) the `learning` teachback scores 70 + 12 + 18 = 100.
- `history.observations.rows(conn)` projects one row per subject with `confidence` (the most conservative
  current report), `last_seen = max(recorded_at of current reports)` (`time_basis: assessment_recorded_at`),
  `last_teachback_score` (only when exactly one current report), `session_count`. Legacy databases fall back to
  `SELECT * FROM study_progress`, whose `last_seen` is the column of that name.
- `_struggle_candidates` keeps a row when `confidence in ("struggling", "learning")` or `last_teachback_score <
  14`; at most 12 rows, sorted `struggling` first then by teach-back then by `last_seen` desc.
- `_dedupe` runs after scoring; the deferral runs before rule 6 and before scoring, so a due row and a struggle
  row on the same concept are two candidates at deferral time — the struggle one may be deferred while the due
  one is ranked (the CLI then prints the concept twice: as the primary and in a "Deferred for energy" line).
- `_PlanContext.matchable` = every active plan except fully-checked ones, **including active-but-unready**
  plans; `synthesise` = ready plans with a next milestone within capability. `attach_refs` (rule 7) references
  every matchable plan whose keys equal the candidate's — a body double whose topic equals a husk's topic is
  referenced to the husk too (`(husk, None)`), though it never names the husk (correction `8e9cbdf5`).
- The Today card's `startAction` navigates only (`Alpine.store('nav').go(view)`); the Body Double view opens
  with its own picker. The body-double proposal's plan title is **not** pre-filled into that picker on the Web
  door; the CLI door carries it (`studyloop study "<title>" --mode co-study`). Not done in this range.
- `evidence_command` is the JSON key every renderer reads for the primary's command; for the body double it
  carries a session door, not an evidence write. The CLI labels it "Sit with the plan"; the key name is unchanged.
- `metadata["energy_demand"]` is now present on every struggle-collector candidate's JSON at every energy
  (additive field inside `metadata`); the golden world has no struggle candidates.

## 7. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for item 5 as the tree to merge to `main` and the tree
   the owner scores row 3b against — with the single sentence that decides it.
2. **Findings**, each with severity 🔴 defect (wrong behaviour or a bug), 🟡 must-fix-before-merge (design/contract
   violation, missing test, unsafe pattern), 🔵 should-fix, 💡 note. For each: file:line or function, what is wrong,
   why it matters, the concrete fix, and the RED test that would pin it (name it). Check specifically:
   - (a) **Scope of the deferral.** Design §5 decision 1 makes repair deferral plan-independent: a learner with
     **no plan** and a live struggle at low energy now gets the starter plus `energy_deferred_repairs` where they
     got the hands-on repair. D-5's "no active plan → pre-#10 payload byte for byte" was re-worded to "…and
     nothing deferred". Is this D-F's intent (the finding is about RSD, not plans) or scope creep into the
     no-plan learner's experience? If creep: is gating the repair half on an active plan the fix, or a different
     no-plan floor (what would a no-plan learner with only live struggles be offered)?
   - (b) **Demand derivation.** `_energy_demand`: `learning → low`; any non-`struggling` row the collector kept
     (weak teach-back on `confident`/`mastered`) → `medium`; `struggling` ≤ 14 days → `high`, else `medium`; an
     unparseable/missing `last_seen` on `struggling` → `high`. Is 14 days the right live window, and is
     `assessment_recorded_at` (when the struggle was *recorded*) the right recency basis versus when it was last
     *seen* in a session? Does a `struggling` row with a weak teach-back deserve `high` regardless of age? Is
     `medium` (4/10) for a weak teach-back alone right when nothing in `ENERGY_CAPABILITY` sits between 3 and
     6 — i.e. `medium` and `high` demand are behaviourally identical at the three energy levels; is the class
     worth carrying, and if so should the JSON say so?
   - (c) **Deferral mechanics.** `_defer_repairs` keys on `metadata["energy_demand"]` presence; due recall is
     never deferred even when `confidence == "struggling"` (pinned). Same concept due *and* struggling: the due
     row is ranked and the repair is deferred — right, or should the deferred line be suppressed when the same
     concept is the primary? A deferred repair no longer "represents" a milestone (rule 6 then synthesises the
     milestone conversation) — right, or does that re-introduce work the energy cannot carry through a side door?
   - (d) **Body double as candidate.** Base 30 (+12 = 42): below practice 48 and milestone 48 at base, but a
     hands-on practice task at low energy scores 48 − 14 = 34 < 42, so the proposal outranks it. Design says
     "any real candidate outranks it" at base; is the post-adjustment inversion acceptable (low energy penalises
     hands-on deliberately) or a 🟡? `concept = "Sit with <title>"` is used as a match key (`_candidate_keys`):
     any collision risk? `plan_refs` for every ready matchable plan, but the CLI door names only the **first**
     plan's title — right for two plans? `estimated_minutes` default 25.
   - (e) **Rule 8 interaction** (decision 2, the one existing pin changed): with four unrelated due items at low
     energy the second alternate is now the body-double proposal instead of a third unrelated due item. Right
     ("advertises no work the energy cannot carry") or a filter in disguise (a real candidate lost its slot)?
   - (f) **Honest starter** (decision 3): after a deferral the starter's reason changes; the starter's *action*
     ("one tiny recall loop" on the first configured topic) is unchanged — is that a defensible offer for a
     no-plan learner with only live struggles, or should the deferred repair's own gentle form (a `recall` on the
     same concept) be synthesised instead?
   - (g) **Renderers.** CLI: "Deferred for energy: … repairing “x” (confidence) asks for N/10; low energy carries
     3/10" and "Sit with the plan:" replacing "Record evidence:" for a body-double primary. Recap: a sentence per
     deferred repair, reachable only through `_plan_context` (see hard rules). Today card:
     `deferredRepairNotes()`, `viewForAction` → `body-double`; the plan title is **not** pre-filled into the Body
     Double picker — 🟡 or 🔵? Is the JSON key `evidence_command` acceptable for a door, or should the body
     double carry a distinct field? MCP `get_next_action` returns `to_json_dict()` unchanged — is the new key
     disclosed where an agent reads (tool docstring, persona)?
   - (h) **Spec delta.** A MODIFIED requirement restating "The now engine is plan-aware with tested ranking
     rules" with item 5 inline. Does every sentence match the code as diffed (rule 2's demand classes, the
     body-double clause after rule 5, rule 7's slot, the qualified byte-for-byte sentence)? Any scenario that
     the tests do not actually pin?
   - (i) **Tests.** Six new Python tests drive the real struggle collector over patched `observations.rows`
     (rows built by `_struggle`). Do they pin the boundary (14 days exactly), the unparseable `last_seen` path,
     the two-plan body double, the medium-vs-high indistinguishability? Is anything asserted only via a
     substring that a wording change would silently pass?
   - (j) **Rubric row 3b as written** (§4): are the three readings the right questions to put to the owner, and
     do they cover the finding's two halves? Anything the owner should be asked that the row omits?
3. **Refutations:** any claim in §0–§6 you believe is false or not established by the brief — say which and why.
4. **Gate:** the shortest list of corrections that would turn your verdict into ACCEPT, each with its RED test
   name; or "none".
