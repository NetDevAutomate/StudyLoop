# Arbitration — council review 3 (Phase 3 code: #10 plan-aware `now` ∥ #11 six MCP tools ∥ #13a `planning` purpose)

**Date:** 2026-09-16 · **Arbiter:** coordinating agent (unattended) · **Reviewed tree:** `fix/plan-integration-bugs`
@ `575e26ff` — the merge of `feat/p3-now`, `feat/p3-mcp`, `feat/p3-purpose` onto the accepted Phase-2 base
`0a20a796`. Seats ran against `brief-review3-2026-09-16.md` (sha256 `6726455f…`, committed `03ffd5d1`;
`review3/manifest.json`). **Fixes landed at:** `05d5d73d..c27a34d5` (findings), then the D-8 last-writer commit
`4f7a5e60`/`c30330a0` and its follow-through `65bde13c`. Phase 2 was accepted in
`review-2-arbitration-2026-09-16.md`.

**Brief size, recorded:** 206 KB against a ~120 KB target. The JS noise was trimmed first as instructed (the JS
test source is listed by name only; spec diffs carry one line of context); the Python diffs and the three new
test modules' full source were kept whole by instruction. All three seats consumed it in one run (prompt
52–56k tokens, `finish_reason=stop`), so the size cost nothing this round.

## Seats and verdicts

| Seat | Verdict | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | **ACCEPT-WITH-CORRECTIONS** (per stream: #10, #11, #13a each with corrections) — two 🔴 (F1 refs bypass the energy/readiness gates; F2 a constant bias is not urgency-class ordering), six 🟡 (F3 rule evidence, F4 hostile content, F5 `CreatePlan.answers`, F6 rubric unscored, F7 vacuous rollback test, F8 recap panel), four 🔵 | `review3/seat-openai.gpt-6-astra.md` (6.6k tokens) |
| `grok-4.6` | **ACCEPT-WITH-CORRECTIONS** — no 🔴; three 🟡 (unready-plan test, hostile-content fixtures, rubric unscored); seven 🔵; #11 ACCEPT, #13a ACCEPT | `review3/seat-grok-4.6.md` (21.5k tokens) |
| `qwen3-coder` | ACCEPT — four 🔴, two 🟡, four 🔵 (see rejections: most rest on misreadings) | `review3/seat-qwen3-coder.md` (2.5k tokens) |

No instrument fault: every seat finished in one run; no re-run manifest exists.

### Method

Every 🔴/🟡 was **reproduced before acceptance** — a probe script on `575e26ff`, then a RED test seen failing and
committed before the fix — or rejected with the reason below. Two seats naming one defect are one finding
group; one RED commit + one GREEN commit per group. Protected files stayed byte-identical (verified below), the
golden's sha256 did not move, and the architecture guard passed after every commit.

### Findings and dispositions

| # | Finding (seat) | Sev | Reproduction on `575e26ff` | Disposition | Landed |
|---|---|---|---|---|---|
| F1 | A collected candidate matching the **next milestone's concept** of an energy-deferred or active-but-unready plan gets `PlanRef(id, <index>)`: the ranker names a milestone it also reports as deferred, or one the seam will refuse to tick (review-2 G1's "must not") (GPT 🔴; Grok 🟡 "unready plan untested") | 🔴 | Probe: husk (`status=active`, no mission) + due `window frame` → `PlanRef('husk', 0)`; floor 5 at `low` → `PlanRef('sql-windows', 0)` beside `energy_deferred=[…milestone 0…]` | **Accept, narrowed.** `attach_refs` names the index only for a plan in the `synthesise` set (ready **and** within capability); otherwise the match is plan-related repair (`None`). Bias and reference stay — rule 3 keeps repair eligible; G1 keeps the husk listed. GPT's wider fix (apply eligibility to *collected* work before ranking) is **rejected**: it would suppress pre-plan candidates on the plans' account, which "existing collection unchanged" and "bias, not filter" forbid; GPT itself ruled that a deferred plan's `None` ref satisfies rule 8. `_guarantee_plan_backed`'s false docstring claim corrected. Spec rules 3 and 8 reworded; two scenarios. | RED `05d5d73d` (2 failed), GREEN `64dc09f7` |
| F2 | `PLAN_RELATED_BIAS = 12` cannot implement "within an urgency class plan-related beats unrelated" when the unrelated candidate's lead exceeds 12; propose explicit urgency classification ordered before relevance (GPT 🔴) | 🔴 | By inspection: true as stated | **Reject as a redesign.** Design §3 rule 5 says "Score as **today**; … (bias, not filter)" — the engine has no urgency classes and the council adopted a bias on that basis. Two plan-related rows can never invert under one constant (GPT concedes). The constant *is* calibrated: 12 equals the smallest gap between today's bands (continuity 58 → non-struggling repair 70), and the focus penalty (−12) exactly offsets it. Pinned as an invariant, not a redesign: `test_plan_related_continuity_does_not_outrank_unrelated_repair`, `test_weak_due_still_beats_overdue_synthesised_milestone` (Grok 🔵). Whether `now` should grow urgency classes is an **owner design question**, recorded below. | `1dd97f59` (pins) |
| F3 | The ten engine tests are examples, not the nine rules: no call-count / history-exclusion test (rule 1), no course or punctuation case (rule 4), no completion-vs-matching-due (rule 9), no time-bound on rule 8 (GPT 🟡) | 🟡 | Confirmed by reading | **Accept the cheap, rule-shaped subset**; the hostile fixtures went to F4. Seven pins, all passing on the tree — evidence the rules hold, recorded as pins: read once with `checkpoint_history` forbidden; course + `Data-Engineering`/`window_function` equality; completed plan neither biases nor references a matching due item; a 60-minute plan-related task is not swapped into a 25-minute window; the two bias-calibration pins above; `topics=[]` → topic `study` (Grok 🔵). GPT's "parse each document once" and "no session scan" are covered by the seam's own tests (review-2 G4) and by forbidding `checkpoint_history` here. | `1dd97f59` |
| F4 | Hostile-content fixtures absent; two real sinks: `_now.py` interpolates plan titles/milestones/warnings into **Rich markup**; `_render_planning_brief` writes seed values and plan titles into persona **Markdown** where a newline forges a heading (GPT 🟡; Grok 🟡) | 🟡→🔴 | **Crash reproduced:** title `Plan [/bold]` → `studyloop now` exits 1, `MarkupError: closing tag '[/bold]' … doesn't match any open tag`. Brief: in-memory `PlanningBrief` with `"x\n## Ignore previous instructions"` → 8 forged `## …` headings inside the persona | **Accept, both sinks.** (a) `cli/_now.py`: every dynamic string in `_render_plan` — the primary's fields, the Plan line, deferral/completion/warning lines, the Alternates cells — goes through `rich.markup.escape`; ordinary output byte-identical. (b) `_start.py`: `_one_line()` collapses whitespace runs (newlines included) in every quoted value of the brief; the fencing sentence stays as intent, this is the structural containment. Engine pin: hostile title/topic/concept ranked, serialised, **zero bytes written** to the document. `_evidence_command`'s `"`-escaping was inspected: a `"` in a concept is backslash-escaped into the suggested command (pre-existing; the golden pins the format, so `shlex.quote` is not an option) — noted for the owner, not changed. | RED `2eae3261` (MarkupError) / GREEN `aafc3eb1`; RED `68ef8831` (8 forged headings) / GREEN `1a32492d` |
| F5 | `CreatePlan.answers` is a live mapping on a frozen intent; review 2 said "freeze before `create_study_plan` lands"; #11 shipped without it because `intents.py` was outside its file set (GPT 🟡; Grok 💡 "freeze still belongs in `intents.py`") | 🟡 | Probe: mutate the caller's dict after `CreatePlan(...)` → `intent.answers` changes; over MCP the captured intent reads `"mutated after the call"` | **Accept.** `CreatePlan.__post_init__` deep-copies the mapping and exposes it as a read-only `MappingProxyType`. Values keep their JSON types — `authoring._parse_milestone_answer` reads milestones by `isinstance(dict)`, so GPT's *recursive type* freeze would have broken drafting; immutability is at the intent's boundary (the caller cannot reach the copy), which is the hazard. A non-mapping is left as given so the seam's `InvalidField` boundary check still fires (the accepted Phase-1 boundary test builds that intent at import time). New module `tests/test_plan_intent_snapshots.py` (6). `RevisePlan.milestones`/`topics` share the shape but were not named by review 2 and their tests compare against lists; deferred to #12 with the same recipe. | RED `0adc65e3` (4 failed / 2 passed), GREEN `3880e302` |
| F6 | The D-16 rubric receipt is honest (`PENDING`, nothing faked) but T3.4 is ticked as done; "scored" is the DoD (GPT 🟡; Grok 🟡) | 🟡 | By reading | **Accept as a task-state correction.** T3.4 re-opened (`[ ]`, "receipt landed, scoring outstanding") with the owner action written in. Not a code change; no test can replace the judgment. The `docs/study-plans.md` bullet deletion stands (GPT and Grok agree: the bias shipped; PENDING is about human acceptance, not existence). | `c27a34d5` |
| F7 | `test_brief_failure_releases_session_claim` asserts `start.call_count == abort.call_count` — true at (0, 0) and (5, 5); PTY only (GPT 🟡; Grok 🔵) | 🟡 | By reading | **Accept.** Parametrised over `pty`/`acp`; `assert_not_called()` on both history writers; exact 500 body keys; empty state file; no live slot; no persona shipped; the following focus start succeeds. New `test_focus_start_overwrites_stale_planning_purpose`. **No production change was needed** — both transports already behaved; the strengthened tests prove it. | `ecbeba41` |
| F8 | The spec names the daily recap among the renderers; `--json` and the spoken form carry `plan_context`, the Rich panel in `cli/_recap.py` does not (outside #10's file set, reported not closed) (GPT 🟡) | 🟡 | RED: no `Plan:` line in the panel | **Accept.** One `Plan:` line when `plan_context` is non-empty, escaped (F4's rule), read through `getattr` because `test_voice_backends.py`'s recap double predates the field. Rendering only. | RED `7302b883`, GREEN `e3859443` |
| F9 | `_load_guidance`'s bare `except Exception → None` swallows `ImportError`/`TypeError` behind the learner-facing warning (GPT 🔵; Grok 🔵) | 🔵 | RED: 0 log records | **Accept.** `logger.warning(..., exc_info=True)` before degrading; the bare except stays — the resilience is the contract (spec rule 1), the observability was the gap. | RED `1dd97f59`, GREEN `5ba6be0d` |
| F10 | Today card drops `warnings`: an unready plan's blockers are on the CLI and in the JSON, invisible on Today; `hasPlanContext` "unused" (Grok 🔵; GPT/qwen "remove it") | 🔵 | By reading | **Accept the warnings; keep `hasPlanContext`.** `warningNotes()` renders `plan.warnings` verbatim through `x-text` in the notes block; `hasPlanContext` counts them. It was called unused because the JS test source was not in the brief — three `node:test` cases assert it. | RED `ac34c63e` (2 fail), GREEN `014d69e3` (115 pass) |
| F11 | `list_study_plans` docstring "then by last update" reads newest-first; `browse` is active first then `updated` **ascending** (GPT 🔵; Grok 🔵) | 🔵 | Verified: `store.list_plans` sorts `(status != "active", updated)`; the store's own comment said "most recently updated" | **Accept as a wording fix** in the tool docstring and the store comment. Whether oldest-first is the *right* browse order is Phase-0 behaviour, protected by `test_web_plans.py`, and not this review's to change. | `c27a34d5` |
| F12 | `plan_id or None` in `create_study_plan` turns an explicit `""` into "omitted", against the spec's "forwards arguments unchanged" (GPT §3) | 🔵 | By reading | **Accept as a documented normalisation**, not a behaviour change: an empty id meaning "allocate the slug" is the friendlier door for an agent. Spec sentence added. | `c27a34d5` |
| F13 | Inventory arithmetic: design §4 / D-9 "26 → 35" and T4.1 "lists 35"; the registry had **23** at `0a20a796`, 29 now, **32** with #12 (GPT, Grok, qwen — unanimous) | 🔵 | `len(mcp._tool_manager._tools) == 29`; 23 at the base | **Accept.** design §4 and T4.1 corrected to 32 with the GPT/Grok assertion shape: exact unique count **and** the nine plan names plus `CORE_TOOLS`; fold `record_plan_learning`'s inline mapping into `_plan_tool_error` in the same #12 commit after pinning its wording; extend `forbid_store` with the authoring/evaluation entry points first. The arbitration-round-1 text is history and is not edited. | `c27a34d5` |
| — | Deliberate edits to Phase-3 tests: `test_brief_failure_releases_session_claim` strengthened (F7); `test_mcp_session_parity.py::test_delegates_to_build_now_plan` now expects `interleave="off"` (it pinned the pre-T3.5 call — the absence of the feature, not a contract) | — | Full-suite `-x` stopped on it after `c30330a0` | Recorded here as review 1 requires. | `ecbeba41`, `65bde13c` |

### Rejected, with reasons

- **GPT F2** urgency-class ranker — rejected above as a redesign of what design §3 decided; pinned as a calibration
  invariant; owner question recorded.
- **qwen 🔴 (a)** "rank inversion within a class": adding one constant to both plan-related rows preserves their
  order; the example inverts nothing. **(f)** "incorrect upgrade rule": `refs.get(id) is None` upgrades repair → milestone
  and never downgrades — deterministic and, per GPT and Grok, correct. **(v)** and **Grok 🔵** 500 → 409/424/503: the
  structured 500 stays (GPT: an unexpected server-side preparation failure; no transient classification justifies
  503; 409 would collide with the session-conflict door). **(q)** `update_study_plan(status=)` vs `set_study_plan_status`:
  both docstrings already distinguish repair-and-activate-as-one-document from a pure transition (GPT, Grok accept
  deviation b). **🟡 (h)** Python < 3.7 dict order: the project requires ≥ 3.12. **🟡 (t)** expand `forbid_store` by
  `hasattr` iteration: vague; the concrete extension (authoring/evaluation entry points) is #12's, written into T4.1.
  **§3** "agent-install.md discrepancy": a misreading — the doc says the three Phase-4 tools are not yet available, which
  is true.
- **GPT F10** parse `updated` into instants: the store writes one `utc_now_iso()` format; a hand-edited offset would
  mis-sort a tie-break only. Noted, not changed. **GPT F10** speech does not announce deferrals: the spoken form names
  the plan the primary advances; deferrals are on the panel and in JSON — documented here as the narrower contract.
  **GPT F12** topic-omission contract: `topic` stays required; #14 sends `topic: ""` for a planning launch — written
  into the hazards below.

### Verification after fixes (`65bde13c`)

- Full suite: `uv run --group dev pytest packages/studyloop/tests -q -p no:cacheprovider -x` → **4890 passed, 4 skipped**, exit 0 (5m48s)
  (785 deselected by the project's default markers — integration/e2e/live/acceptance/uat). Baseline at `575e26ff`
  was the three streams' own gates (4826 passed at #11's tip).
- `test_now_plan_guidance.py` 31 passed (was 19); `test_session_start_purpose.py` 16 (was 12); new
  `test_plan_intent_snapshots.py` 6; new `test_mcp_next_action.py` 10; `test_mcp_plan_tools.py` 58 unchanged;
  guard `test_architecture_plan_seam.py` 30 passed; `test_mcp_stdio_smoke.py -m integration` 2 passed (inventory 29).
- JS: `node --test packages/studyloop/tests/js/*.test.js` → **115 pass, 0 fail** (was 113).
- `just lint` → ruff clean, 1027 files formatted; `just typecheck` → pyright 0 errors; `openspec validate
  plan-application-seam` → valid; `openspec validate --specs --all` → 25 passed; `mkdocs build --strict` exit 0.
- Protected files: `git diff 3a4f6b01 -- test_web_plans.py test_cli_plan.py test_planning_evaluation.py` → **0
  lines**; `git diff 0a20a796 -- test_learning_decision.py test_web_now.py test_recap_mastery_voice.py
  test_web_session_start_pty.py test_web_session_start_acp.py test_web_session_ws.py test_agent_launcher.py` → **0
  lines**. Golden `now_plan_no_active.json` sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`
  unchanged. `rg` invariants: 0 adapter imports of `planning.store|index|authoring|evaluation`; 0
  `build_canonical_persona("focus"` literals under `web/`.
- The workspace-wide order-dependent failure #11 reported (`agent-session-tools/tests/test_eval_arms.py::
  TestPlannerIsolation::test_planner_patch_restored_after_tool_error`) passes alone (1 passed); it is outside this
  programme's packages and unchanged by Phase 3 — assigned to the owner of `agent-session-tools`, not fixed here.
- Pre-commit on every commit: ruff, ruff-format, detect-secrets, bandit, trufflehog, pyright — passed; two commits
  were re-staged and re-created after a hook rewrote a file (no `--amend`); no secret detector fired.

### The D-8 last-writer commit (T3.5) — landed

`get_next_action(energy="medium", time_minutes=25, modality="recall", interleave="off")` in `mcp/tools.py`:
`interleave` is a plain string validated against `get_args(InterleaveMode)` with the existing `ToolError` wording
(`Invalid interleave 'x': choose one of ('off', 'adaptive')`), then `cast` and forwarded to `build_now_plan`;
`@consistent_read` stays; the validation pattern is reused verbatim, not factored (all three seats). Only that one
function moved; the inventory is still 29. Tests in the new `tests/test_mcp_next_action.py` (the seats asked that
`test_mcp_plan_tools.py` be left to #12): schema gains `interleave` default `"off"`; `"adaptive"` is forwarded once
and the response carries `INTERLEAVE_RATIOS[energy]` at medium/high; `ADAPTIVE`/`random`/`""`/`on` are refused
naming both choices with zero engine calls; the default and explicit `"off"` calls equal the no-plan golden byte for
byte; the energy/modality refusals keep their wording. RED `4f7a5e60` (9 failed / 1 passed) → GREEN `c30330a0`;
follow-through `65bde13c` (the parity test above). **D-8 order note:** the design serialised #11 → #12 → this
commit; #12 has not started and `tools.py` was otherwise quiet, so the arbiter landed it now as the brief
directed — #12 rebases onto it and must not touch `get_next_action`.

### Phase 4/5 hazards (endorsed from the seats, with the arbiter's additions)

**#12 — three tools.** `set_study_plan_milestone` reuses `_plan_tool_error` unchanged (`InvalidMilestone` and the
`already_active` hint are mapped) and must come back `not_ready: … already active … pause or repair` on a husk with
nothing written — the twin of F1's engine test. `evaluate_study_plan(record=False)` calls `assess`, never
`apply(AssessPlan)` (it is not in `PlanIntent`), and returns the view's JSON **with** `db_write`/`document_write` as the
seam reports them (`not_requested` for a preview — do not flatten to booleans, do not invent `saved`); `record=True`
on an unready active document is refused before either sink (review-2 F2). `delete_study_plan(confirmed=False)`
keeps the boolean default in the schema and lets the seam's `InvalidField` refuse an unconfirmed call — GPT: do not
require the parameter or constrain it to literal `true`. Extend `forbid_store` with the authoring/evaluation entry
points before `evaluate_study_plan` lands; real-seam tests compare document bytes and checkpoint rows. Fold
`record_plan_learning`'s inline mapping into `_plan_tool_error` in the same commit, after pinning its prefixes,
blockers and chained cause. **Inventory:** assert exactly **32** unique names and the nine design-§4 names plus
`CORE_TOOLS` (T4.1 now says so). Apply F5's snapshot recipe to `RevisePlan.milestones`/`topics` if #12 touches
`intents.py`.

**#13b / #14 — what the purpose plumbing gives and lacks.** Present: `purpose` on the `201` body and the session
state, `GET /api/session/state` echoing it, one resolver, the brief as its own persona section, ACP `persona_text`
inline. Absent: the nine tool names in the persona (T4.2 — edit `agents/shared/personas/plan-architect.md`, do not
overload `_render_planning_brief`); a "Plan with architect" control; a console label that reads `purpose`; the CLI
`studyloop plan architect` writes no `purpose`, so a CLI-started architect reconnects labelled `focus` under
`setdefault` — decide whether the CLI writer persists `purpose=planning` (never infer it from the topic `"Study
plan"`). `topic` stays required: #14 sends `topic: ""` for a planning launch. Hazard: a large seed plus many plans
makes ACP `persona_text` a first-prompt token bomb — cap or summarise `### Evidence` in #13b without changing
`_resolve_persona`'s shape; add a test that the brief is sent once before the user's first prompt. The parser bug
(`RANK()` concepts) is still open in the parser's files; F4's fixture avoided `)` deliberately.

### Does the rubric show a ranking a learner would accept?

Rows 1–4 are rankings the arbiter would accept as this morning's `studyloop now` (Grok concurs; GPT withholds the
learner verdict as a human's): row 1 the near-tie goes to the plan (bias); row 2 an overdue review at 118 beats new
milestone work at 60 (bias, not filter — exactly D-16's language); row 3 the cheap plan-related repair stays and the
deferred milestone is named; row 4 the finished plan is a completion note, not a task. Row 5 is byte-identical.
**But the receipt is not scored**, and after F1 row 3's family changes in one detail — a match on the *next*
milestone's concept below the floor now carries `None`, not the index — so the owner should re-read row 3 against
`64dc09f7` before writing `yes`. The D-16 check is met when five verdicts, a reviewer and a tree sha are in the
receipt; a `no` on rows 1–4 is a council finding, not an agent edit.

### Process finding

All three seats name the same call that needed a human: the numbers that *are* rule 5 (`PLAN_RELATED_BIAS = 12`,
`MILESTONE_BASE_SCORE = 48`) were chosen by an unattended agent, the D-16 receipt was then honestly left `PENDING`,
and the feature was documented as done anyway (T3.4 ticked, the docs bullet removed). The arbiter upholds the
constants (they are calibrated to today's bands and now pinned), upholds the docs bullet (the bias exists), and
re-opens T3.4: "implemented and mechanically exercised" is not "human check completed". Second, smaller: a
review-2 hazard with a named owner ("freeze `CreatePlan.answers` before `create_study_plan` lands") fell between
three disjoint file sets — the parallel-worktree discipline that made Phase 3 mergeable without conflicts also let
a cross-cutting prerequisite go unowned. Convention going forward: a hazard addressed to a phase is assigned to
one stream's file set in `tasks.md` before the streams start.

## Gate decision

**Phase 3 (#10, #11, #13a) with the review-3 corrections F1, F3–F13 and the T3.5 interleave commit is ACCEPTED as
the base for Phase 4.** #12 may register the three remaining tools against the seam with the hazards above (32,
not 35; `assess` not `apply`; `confirmed=False` default; fold `record_plan_learning`; extend `forbid_store`); #13b
may edit the architect persona to name the nine tools; #14 follows #13b.

## Still open for the owner

1. **Score the D-16 rubric** (`receipts/now-rubric-2026-09-16.md`): five `yes`/`no` verdicts with a line each, the
   reviewer and the tree sha; re-read row 3 against `64dc09f7`. T3.4 stays open until then.
2. **Design question from F2:** should `now` grow explicit urgency classes (rank by class first, plan relevance
   second)? The council decided a bias; the constant is pinned to today's bands. Reversing is a ranker redesign,
   not a fix — a decision for a future planning round, not an arbitration.
3. **Deviation 12** (review 2) remains an owner decision: legacy active-but-unready documents must be paused or
   repaired before any write; the `now` ranker now never names their milestones (F1).
4. **Parser bug** (`RANK()` concepts) — still tracked, not fixed; F4's fixture stepped around it on purpose.
5. **`_evidence_command`** backslash-escapes `"` inside a suggested shell command (pre-existing; the golden pins
   the format). A plan concept containing shell metacharacters produces a suggestion the learner should read
   before pasting. Consider `shlex`-safe rendering when the golden is next allowed to move.
6. **Unrelated local branches, again not touched** (review 2 item 3 stands): `feat/clean-start` (7 commits ahead of
   `main`, not on origin) and `feat/harness-tier-promotion` (checked out clean in the worktree
   `../studyloop-wt/harness-tier`, not on origin). Both carry unmerged commits that exist nowhere else; deleting
   either destroys work. The Phase-3 branches `feat/p3-now`, `feat/p3-mcp`, `feat/p3-purpose` were already merged
   and deleted; no Phase-3 worktree remains.
7. `agent-session-tools/tests/test_eval_arms.py::TestPlannerIsolation::test_planner_patch_restored_after_tool_error`
   is order-dependent under the root config (passes alone); owner of `agent-session-tools`.

GATE: ACCEPT
