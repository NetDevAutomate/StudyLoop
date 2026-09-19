# Arbitration — council review 7 (item 5 of the plan-integration follow-on programme: D-F)

**Date:** 2026-09-19 · **Arbiter:** coordinating agent (owner present; the owner chose the seats' key and asked
for the run) · **Reviewed tree:** `feat/energy-demand-body-double` @ `6d5a2d0e` (four commits on `main`
`4f8e3e0f`; range `4f8e3e0f..6d5a2d0e`, 15 files, +1,042/−25). Seats ran against
`brief-review7-2026-09-19.md` (`review7/manifest.json`, run 12:10:45Z; astra and qwen `finish_reason=stop`,
**grok `length`** — its 16,000-token cap cut its answer inside §3 Refutations, so its verdict, findings and the
first refutation are complete and its §4 Gate is absent; not re-run, since every grok finding is 🔵/💡 and its
verdict is ACCEPT). **Corrections landed at:** `d1935256` (F1), `c1d7f2f2` (F5), `3347567e` (F7), `f814dc36`
(grok's label), `7194b66d` (F4 pins + a collector crash they surfaced), `02e282e6` (F2 claim), `bdf4d6c6`
(F3/F6 wording). Two corrections the agent found on its own re-read *before* the brief was frozen are part of
the reviewed tree (`8e9cbdf5` ready plans only; `6d5a2d0e` wording) and are listed in the brief §1.

**Brief size, recorded:** 117.6 KB, 1,734 lines (~31k prompt tokens per seat): D-F and rubric row 3 verbatim,
design §5 with its amendments and GREEN decisions, every diff in the range in full, row 3b as written, the
control receipt, reference facts, ten numbered check questions — including the scope of the plan-independent
deferral asked outright as (a).

## Seats and verdicts

| Seat | Verdict | 🔴 | 🟡 | 🔵/💡 |
| --- | --- | --- | --- | --- |
| `openai.gpt-6-astra` | ACCEPT-WITH-CORRECTIONS | F1 shell quoting; F2 ordering claim | F3 compatibility promise; F4 unpinned boundaries; F5 contradictory copy | F6 match semantics; F7 Web door context |
| `qwen3-coder` | ACCEPT-WITH-CORRECTIONS | scope (gate deferral on a plan); ordering claim | medium/high partition; docs; gentle-recall fallback; Web door; substring tests; row 3b ask | `evidence_command` reuse |
| `grok-4.6` | ACCEPT | — | — | 14-day boundary + unparseable path untested; decision 5 untested; two-plan case untested; Web pre-fill; "Your plans" label; medium=high behaviourally; `evidence_command` fine |

### Method

Each 🔴/🟡 was reproduced before acceptance — F1 with a real `/bin/sh` and a stub `studyloop` (the title's
`$(touch pwned)` ran), F2 through the engine at two modalities (42 vs 118 / 58 / 34; 60 vs 100 / 76 / 34), F5 by
reading row 3b's own rendered lines — then fixed one commit each with a RED test named by the seat where one was
named, and stash-proved where a fix could be reverted alone (F1: 3 of 7 titles fail without it).

### Findings and dispositions

| # | Finding (seat) | Disposition | Commit / test |
| --- | --- | --- | --- |
| F1 | The offered command replaced `"` with `\"` — presentation, not quoting; a plan title with `$(…)` executed when pasted (astra 🔴). | **Accepted, reproduced.** One `_shell_word` helper: plain text keeps the golden's double-quoted form, shell-special text is `shlex.quote`d; both command builders use it (`_evidence_command` had the same shape for every concept and topic). | `d1935256`; `test_body_double_command_preserves_title_as_one_literal_shell_argument` (7 titles through `/bin/sh`; stash-proved 3/7 red without the fix) |
| F2 | "Base below `MILESTONE_BASE_SCORE` so every real candidate outranks it" is false after adjustments: at low energy the proposal (42) outranks a hands-on task that energy penalises (34) (astra 🔴, qwen 🔴; grok 💡 "acceptable, do not lower the base"). | **Claim corrected, behaviour kept.** Reproduced exactly as computed. Every due and conversation candidate still outranks it at every modality; only a hands-on task the low-energy rule already penalises sits beneath — the energy rule doing what the finding asked ("instead of the least-bad task"), not a filter: nothing is removed from the ranking. Astra's proposed post-scoring floor would put a penalised hands-on task above the proposal at low energy, i.e. re-recommend the class of work the finding objected to. The *claim* was the defect: corrected in the constant's comment, the docstring, the spec delta's rule-5 clause and design §5 decision 4; the judgement is the owner's — row 3b reading (e). | `02e282e6`; `test_body_double_ordering_after_adjustments_follows_the_energy_rule` (recall and conversation modality) |
| F3 | "No plan and nothing deferred → byte-identical" still false: every struggle candidate gains `metadata.energy_demand` at every energy; older struggles and weak teach-backs defer too (astra 🟡). | **Accepted.** The contract now names exactly the two plan-independent changes, in the spec delta, both docs and design decision 1. | `bdf4d6c6` (docs) + `02e282e6` (spec paragraph, same file as F2's edit); `test_no_plan_eligible_repair_exposes_demand_without_deferral` (in `7194b66d`) |
| F4 | Five unpinned invariants: the 14-day boundary and unparseable dates; confidence/teach-back precedence; the capability matrix; decision 5 (deferred sole representative → eligible milestone conversation); two ready plans (astra 🟡; grok 🔵 on three of them). | **Accepted, all five written.** The boundary pin surfaced a **pre-existing collector crash**: `_struggle_candidates` sorted by `row["last_seen"]`, so a legacy `study_progress` row with a NULL `last_seen` raised and lost every struggle candidate; it now sorts as the oldest and derives as live. | `7194b66d`; `test_energy_demand_recency_boundaries_and_unknown_dates`, `test_energy_demand_confidence_and_teachback_precedence`, `test_repair_demand_capability_matrix`, `test_deferred_repair_allows_only_eligible_milestone_conversation`, `test_body_double_two_ready_plans_has_deterministic_context` |
| F5 | The milestone-deferral sentence ended "plan-related review and repair stay available" one line above the line deferring the repair (astra 🟡). | **Accepted.** Engine reason and CLI line now promise only due recall and gentle review; pinned as whole sentences. | `c1d7f2f2`; `test_cli_milestone_deferral_does_not_promise_live_repair` |
| F6 | Rule 7 can attach a husk reference to the proposal through its topic, so "names ready plans only" is true of the proposal's text, not of every rendered reference (astra 🔵). | **Accepted as a spec sentence**, no code change: the two-stage behaviour is now described in the rule-5 clause; `test_body_double_is_never_synthesised_for_an_unready_plan` already permits the husk ref and pins the proposal's text. | `02e282e6` |
| F7 | The Web door navigated only; the Body Double picker opened blank while the CLI door carried the plan title (astra 🔵, grok 🔵, qwen 🟡). | **Accepted, built** — the same event-not-storage handoff `today-resume` uses: `startAction` dispatches `body-double-request` {activity, energy}; `bodyDoubleSession.init` adopts it. Nothing starts on its own. | `3347567e`; JS `starting a body-double primary hands its plan to the Body Double view…`, `bodyDoubleActivity…` |
| G1 | `hasPlanContext` is true for a no-plan deferred repair and the block is headed "Your plans" (grok 🔵). | **Accepted.** `planNotesLabel()`: "Your plans" once any note involves a plan, else "Set aside today". | `f814dc36`; JS `planNotesLabel…` |
| Q1 | Gate the deferral on an active plan (qwen 🔴). | **Rejected** — see below. | design §5 decision 1; row 3b reading (d) |
| Q2 | Collapse the medium/high partition (qwen 🟡). | **Rejected** — see below. | design §5 decision 7; spec sentence |
| Q3 | Synthesise a same-concept gentle recall as the no-plan floor (qwen 🟡; grok 🔵 "follow-on"). | **Not taken; recorded as a follow-on** and put to the owner. | design §5 decision 8; row 3b reading (d) |
| Q4 | Row 3b should ask the owner about the no-plan consequence (qwen 🟡; grok's tail). | **Accepted.** Readings (d) and (e) added, printed from the real engine on `bdf4d6c6`. | `receipts/now-rubric-2026-09-16.md` |

### Rejected, with reasons

- **Q1 — gate repair deferral on an active plan (qwen 🔴).** Two seats and the owner's own words go the other
  way: the finding is "hands-on repair of a *live* struggle on a low-energy day compounds the struggle (RSD)" —
  a fact about the learner's day, not about plans — and D-F's item (1) says "at low energy a live struggle
  defers like new work" with no plan condition. Gating it would leave the original "no" standing for every
  learner without a plan. Astra: "reintroducing an unsafe recommendation merely because the learner lacks a plan
  would contradict the rationale for D-F". Grok: the same, and "listed, not recommended, is the honest state".
  Kept, with the compatibility contract re-worded to the truth (F3) and the no-plan floor put to the owner as
  row 3b reading (d) — the one person who can say whether the starter is the floor they want.
- **Q2 — collapse `medium` into `high` (qwen 🟡).** True that nothing in `ENERGY_CAPABILITY` sits between 3 and 6,
  so the two classes never differ in eligibility today. Astra and grok both keep the class as explanatory state
  — the payload says *why* a repair asks for 4/10 rather than 6/10, and the next energy scale change would
  otherwise need the derivation rebuilt. Kept; the spec now says both classes need at least medium energy today.
- **Astra's F2 fix (a post-scoring floor for `body_double`).** Rejected in favour of correcting the claim: the
  floor would rank a hands-on task the low-energy rule penalises above the proposal, which is the shape of
  recommendation the finding objected to. The behaviour is pinned exactly as it is and goes to the owner.
- **Q3 — a same-concept gentle recall as the no-plan floor.** Astra: "do not synthesise recall on the deferred
  struggle merely to maintain topical relevance; that would invent an unvalidated lower-demand action." Grok:
  a follow-on, not a merge gate. Recorded as decision 8 and asked in row 3b (d).

### Refutations, weighed

- Astra 1 ("42 < any real candidate" false) — **true**; F2. Astra 2–3 (byte-for-byte still false; "live struggle"
  too narrow) — **true**; F3. Astra 4 ("each GREEN decision is a test" not established: decisions 5 and the
  two-plan case untested) — **true**; F4 now pins both. Astra 5 ("the Today card starts it" — navigation only) —
  **true at the reviewed tree**; F7 built the handoff. Astra 6 ("zero regressions" is about failing ids at GREEN,
  not the reviewed tree) — **accepted as stated**; a full suite runs on the final tree below. Astra 7
  ("`learning` means recovered" is the chosen proxy, not established) — **accepted**; row 3b reading (c) asks
  the owner exactly that. Grok's one refutation (the same F2 claim) — **true**. Qwen: none.

### Verification after fixes (tree `bdf4d6c6` + the rubric edit)

- `test_now_plan_guidance.py` **71 passed** (47 at the reviewed tree, +24 test cases from F1–F5 including
  parametrisations), golden byte-identical; with `test_learning_decision.py` and the docs contract **96 passed**;
  JS **147/147** (+3); `openspec validate` valid;
  `mkdocs --strict` exit 0; ruff / ruff format / pyright clean on every touched file. Full suite and matched
  control on the final tree: see the receipt named in `tasks.md` T5.4 once it lands (running at arbitration time).

### Process findings

- The brief's check question (a) put the arbiter's own hardest decision to the seats directly and got a 2–1
  split with reasons on both sides — more useful than a unanimous nod. Keep doing that.
- Grok's 16k cap cut its Gate section. Its findings were complete and all 🔵/💡, so no re-run; a future brief
  of this size should either raise `--max-tokens` for that seat or ask for the Gate before the Refutations.
- One commit carried two logical changes: `3347567e` (F7) also contains the `planNotesLabel()` function that
  `f814dc36` (G1) relies on, because both edits were in `today-panel.js` when F7 was staged. Recorded rather than
  rewritten; both are unpushed and tested.
- F4's boundary pin finding a real, pre-existing crash (`None` `last_seen`) is the argument for writing boundary
  tests even when the design says the boundary is "obvious".

## Gate decision

**GATE: ACCEPT** — for the tree at `bdf4d6c6` (with the rubric-row edit), not the reviewed tree. Every 🔴 and 🟡
is either landed with a discriminating test (F1, F3, F4, F5, F7, G1, Q4) or rejected here with the reason and
the owner's question that replaces it (Q1, Q2, Q3, astra's F2 remedy). Item 5 is ready to merge once CI is green
on the branch; the change is **not** archived until the owner scores row 3b.

## Still open for the owner

1. **Rubric row 3b, five readings** — (a) sit with the plan rather than repair a live struggle; (b) the proposal
   beneath an unrelated due recall; (c) the gentle teach-back on a `learning` concept; **(d) the no-plan floor**
   (starter + deferred line, where the hands-on repair used to be); **(e) the proposal above an unrelated
   hands-on drill at low energy**. (d) and (e) are the two places the seats split; only the owner closes them.
2. Whether a same-concept gentle recall should be synthesised for a no-plan learner (decision 8) — after (d).
