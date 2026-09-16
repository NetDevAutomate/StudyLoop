## Verdict

ACCEPT-WITH-CORRECTIONS — archive and close-out may proceed only after the rubric-receipt sentence, the unestablished “whichever door… planning brief” claim, the architect’s “session run against it” wording, and the ticked-but-unscored T3.4 checkbox are corrected.

## Findings

### F1 🟡 `docs/study-plans.md` § “Plan-aware now” — rubric verdict claimed as recorded

The closing sentence says the “would I do the primary?” judgement is “recorded per scenario in the project’s rubric receipt”. T3.4 and the close-out both state that receipt’s owner-verdict column is **PENDING**; only the unattended primary + rationale were written. D-16’s bound is that ranking tests prove ranking, not that a human already scored the fixtures. A six-month reader will treat the receipt as scored.

**Fix:** replace the clause with one that names the receipt and the pending verdict, e.g. “a separate judgement; the five frozen scenarios and the engine’s primaries live in `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`, whose owner-verdict column is still pending.”

**Pin** in `test_docs_plan_integration_contract.py` (`test_study_plans_doc_uses_the_bounded_release_language`):

```python
assert "recorded per scenario in the project's rubric receipt" not in text
assert "pending" in _prose(_section(_read("docs/study-plans.md"), "Plan-aware now")).lower()
```

### F2 🟡 `docs/study-plans.md` § “Build a plan with the study-plan-architect” — brief claimed on every door

“Whichever door starts it, the architect works from a planning brief — the interview questions, an evidence seed… and the plans that already exist” is specified only for `POST /api/session/start` with `purpose: "planning"` (`live-session-orchestration` / `agent-adapters`: `build_canonical_persona(..., brief=)`). `studyloop plan interview` is specified to emit `{questions, seed}` with **no** `existing_plans`. Whether `studyloop plan architect` / `studyloop study --mode plan-architect` passes `brief=` is **not established by the brief**; `brief=None` yields no `## Planning brief` section. The Web door is the only door the specs bind to a brief.

**Fix:** qualify: “A Web-launched planning session (`purpose=planning`) injects that brief into the persona. `studyloop plan interview` prints the questions and seed. A CLI-started architect uses the same persona file; whether its process also receives the brief is the launcher’s job, not this page’s claim.” If the CLI path does inject it, add a delta scenario and cite the node; do not leave the universal sentence standing on Web-only evidence.

**Pin:**

```python
section = _prose(_section(_read("docs/study-plans.md"), "Build a plan with the study-plan-architect"))
assert "whichever door" not in section.lower()
assert "purpose=planning" in section or "Web-launched" in section
```

### F3 🟡 `docs/study-plans.md` § “Build a plan with the study-plan-architect” — session-binding flavour

“then evaluates the plan against real study evidence at the start, middle, and end of every session run against it” reads as product behaviour. No session is “run against” a plan (`NOT_AUTOMATIC[0]`, #7 items 1–3, `test_planning_launch_creates_no_plan_and_no_plan_id`). Checkpoints fire only when the learner or the agent calls `evaluate` / Record checkpoint. The next section contradicts this sentence.

**Fix:** “The persona instructs the architect to call `evaluate_study_plan` (preview, then record) at start, mid, and end when you ask it to; StudyLoop never fires those checkpoints from session events.”

**Pin:** `assert "session run against" not in _read("docs/study-plans.md")`.

### F4 🟡 `openspec/changes/plan-application-seam/tasks.md` T3.4 — F6 repeated

T3.4’s text is “five frozen scenarios **scored** ‘would I do the primary?’”. It is `[x]` with the verdict named an owner action. Review-3 F6 already rejected an unscored rubric as DoD. The close-out’s PENDING column is honest; the checkbox is not.

**Fix** (exact):

```markdown
- [x] **T3.4a** (engineering, `c27a34d5`) five frozen scenarios run unattended; primary + rule-cited rationale committed as `receipts/now-rubric-2026-09-16.md`.
- [ ] **T3.4b** (owner, blocks calling #10’s D-16 DoD done) replace each `PENDING` with yes/no + one line; tree sha; re-read row 3 against `64dc09f7`. A `no` on rows 1–4 is a council finding.
```

Leave T6.1’s “specs promoted at archive” similarly unticked until `openspec archive` has actually run, or split the archive step out.

### F5 🟡 Public inventory sweep does not include `docs/mcp.md`

Existing `mcp-server` requirement: “`docs/mcp.md` documents studyloop-mcp and desktop registration”. That file is absent from Phase 6 diffs, from `_PUBLIC_PLAN_PAGES`, and from the stale-claim sweep. Whether it still says “10 MCP tools” or omits plans is **not established by the brief**. Archive will not rewrite it.

**Fix:** open `docs/mcp.md`; either add it to `_PUBLIC_PLAN_PAGES` and pin its count/table the same way as `agents/mcp/README.md`, or delete/redirect it and drop the existing spec sentence. Do not archive with an unexamined public inventory page.

**Pin:** extend `_PUBLIC_PLAN_PAGES` (or a sibling list) with `docs/mcp.md` and reuse `test_mcp_readme_states_the_registry_count` / `test_mcp_readme_lists_the_whole_production_inventory` against it, or assert the file does not exist.

### F6 🔵 `studyloop.planning.boundaries.NOT_AUTOMATIC` mixes kinds; installer silently drops the sixth

The first five leads faithfully render the learner-facing #7 non-automations (items 1–2 folded into “bind a live study session to a plan”). “structure the manual form’s brain dump” is a door-design fact (#14 “mostly”), not an automation the product refuses. `_plan_capability_lines` does `NOT_AUTOMATIC[:-1]`, so the installer never prints it; `test_installer_output_states_the_boundary_with_the_constant` only asserts `NOT_AUTOMATIC[:4]` and therefore does not pin “turn a plan into a filter” either (it appears only as `last`).

#7 items a learner might still miss from this list, all documented elsewhere or engineering-only: one-active-session invariant (pre-existing), two-way second-brain edit and Markdown-vs-SQLite (“Where plans live”), no autonomous recurring planning sessions (unmentioned), no second PTY / no browser-architect resurrection / no unrelated provider changes (not learner “automatic” claims).

**Fix:** keep the sixth bullet in `docs/study-plans.md`; stop feeding it through the installer slice. Change the installer test to `for phrase in NOT_AUTOMATIC[:5]`. Optional sixth #7 sentence under “Deliberately not automatic”: StudyLoop does not schedule recurring planning sessions.

### F7 🔵 Installer capability block after `studyloop install agents`

Right place (this is the command #7’s further notes named). The sentence “exposes 9 plan tools … to any agent process it is registered with” is literally true and does not say the just-installed Kiro/Claude architect attached the server. It is the moment an operator is most likely to assume they did. `--uninstall` correctly prints no capability lines.

**Fix:** one clause on the first capability line: “whether a given harness definition registers that server is per-harness — see docs/agent-install.md.” Do not list `record_plan_learning` in the nine; the inventory comment and the doc table already separate it.

**Pin:** `assert "per-harness" in output or "registered with" in output` already holds; add `assert LEARNING_RECORD_TOOL not in output` next to the existing nine-name loop if you want the omission locked.

### F8 🔵 `agents/mcp/README.md` heading “studyloop-mcp (Session DB Tools)”

The intro and table now cover review, backlog, lessons, session, now, and plans (32, pinned). The heading is leftover taxonomy. `test_mcp_readme_lists_the_whole_production_inventory` keys on that exact heading, so a rename is a one-line test change. Leave it if an external anchor depends on it; otherwise rename to `studyloop-mcp (learner tools)` so a maintainer does not skip the section looking for “session DB”.

### F9 💡 Verify registry (§6)

All design-§8 and review-4 checks are present as 28 named rows. Projection-body equalities and manifest hashes correctly live inside `plan-suites` via `test_plan_architect_persona.py`; they do not need their own receipt row. Running `full-suite-studyloop` and `full-suite-agent-session-tools` separately is not a weakening of “the full suite”: it is the stronger form, given owner item 12’s order-dependent `test_planner_patch_restored_after_tool_error` under the workspace-wide run. UAT and the rubric are correctly *not* in this script (separate receipts; D-15 never asked the script to grade a mentor).

### F10 💡 UAT redacted summary

`harness: "fake-agent"` and `actor_backend: "scripted"` match the PTY stub (`echo agent-stub-ready; exec cat`) and `docs/acceptance-testing.md`. Empty `per_criterion_scores` plus the arbitration note is an acceptable committed summary: the note states no mentor, no criterion, no council seat. A skimmer who reads only `journeys: 3/3 passed` could still mistake it for a graded sign-off.

**Optional:** if the redaction allowlist permits, add `"graded": false` (or `"signoff_kind": "mechanics"`). Do not invent a field the template will drop.

### F11 💡 Close-out rows vs evidence

Every “yes” row cites a node, commit, or receipt that actually speaks to the criterion as worded, with these bounds already marked and kept:

- #12 partial recording: “yes, in-process” is correct; stdio cannot receive the monkeypatch.
- #13 MCP-with-fallback: “partly” is correct (Kiro/Claude CLI-limited).
- #14 brief: “mostly” is correct (subject travels; brain dump does not).
- #10 D-16: “Not met — owner action” is correct.
- #15 “specs synchronized”: prospective on `openspec archive`; acceptable in a morning-after draft, not as a present-tense fact on `fd10789e`.
- #15 “boundaries accurate”: true after F1–F3, not before.

The five “#7 not fully verified” items are the right set for *product* gaps. Add the CLI-brief unknown (F2) if the owner does not inject or disprove it. #14 DoD asides (no mid-flight cancel browser test; no screen-reader audit; protocol as persona text only) are already in the #14 section and do not need to be duplicated into the #7 list.

Checkpoint labels `on-track` / `at-risk` / `stalled` / `complete` in `docs/study-plans.md` § “Use checkpoints” have no delta requirement and are **not established by the brief**. Leave or cite the evaluation type; do not treat them as pinned.

No public page in the provided diffs still contains “Phase 6”, “T6.1”, “CLI-only”, “What a plan does not do yet”, a `mcp/tools.py:N` citation, or “tracked as”. Nothing in the learner docs points at `openspec/changes/plan-application-seam/`. `mkdocs --strict` being clean is the link check for `second-brain.md` and the agent-install anchor.

### F12 💡 Other six-month traps

- Installer “9 plan tools” vs README “32” vs “nine + `record_plan_learning`” is consistent only if the reader knows the counting rule; the inventory module comment is the source of truth.
- `docs/study-plans.md` “It ships to every harness” is true of *definitions*; tool reach is per-harness. The caveat lives only in `docs/agent-install.md`.
- Archify `visualReview: pending` is the skill’s contract, not an unfinished product claim.
- The verify receipt is specified to be re-run on the post-review tip; `fd10789e` cannot contain `verify-fd10789e.json` written by itself. Commit the receipt in the follow-up commit after archive, not “beside” the draft in the same tree.

## Spec ↔ docs gap table

| Delta requirement / doc claim | Counterpart |
|---|---|
| active-learning: Activation is readiness-gated on every entry path | `docs/study-plans.md` § Activation; `docs/agent-install.md` readiness-gated activation |
| active-learning: Partial checkpoint recording is reported, never silent | `docs/agent-install.md` last paragraph of “Study-plan tools over MCP” (failed sink is not an error). study-plans silent — acceptable (agent-facing) |
| active-learning: Milestone set is idempotent… | `docs/agent-install.md` `set_study_plan_milestone` row (“set, not toggle”). study-plans checkboxes — no idempotency sentence (internal OK) |
| active-learning: Deletion is confirmed and retains the checkpoint log | study-plans “deleting a plan needs your explicit confirmation”; agent-install `delete_study_plan` row (history kept) |
| active-learning: Assessment reports each recording sink independently | agent-install `evaluate_study_plan` row + failed-write paragraph |
| active-learning: Active-plan guidance is a deterministic read | internal (engine). Public effect: § “Plan-aware now” |
| active-learning: The now engine is plan-aware with tested ranking rules | study-plans § “Plan-aware now”; `docs/web-ui-guide.md` Today; `docs/cli-reference.md` now paragraph; README / index / roadmap |
| active-learning: Adapters reach study plans only through the seam | internal (`test_architecture_plan_seam.py`) |
| active-learning: The learning-record rule has one copy | internal. Public: `record_plan_learning` row + study-plans wind-down sentence |
| agent-adapters: Persona resolution by purpose | study-plans planning-session label; agent-install `purpose=planning` |
| agent-adapters: Architect persona prefers the MCP plan tools | study-plans fallback sentence; agent-install full section + table |
| cli-surface: Activation is readiness-gated… | study-plans § Activation + CLI examples |
| cli-surface: The CLI maps every seam refusal to one line and exit 1 | internal CLI UX |
| cli-surface: Every plan command reads and writes through the seam | internal |
| cli-surface: The CLI milestone command is an idempotent set | study-plans shows `plan milestone … --done`; no-flag toggle is internal |
| cli-surface: Recorded checkpoints report complete / partial / absent | MCP side in agent-install; **CLI `plan evaluate --record` wording not in `docs/cli-reference.md`** — internal OK |
| cli-surface: Learning records are one revision through the seam | internal (`plan record` not in the study-plans terminal block) |
| live-session-orchestration: Session purpose | study-plans architect section (label, reload, creates nothing); web-ui-guide Study Plans |
| mcp-server: record_plan_learning writes through the plan seam | agent-install last table row; study-plans wind-down sentence |
| mcp-server: Study-plan discovery and authoring tools | agent-install table (six) + README table |
| mcp-server: Study-plan progression and deletion tools | agent-install table (three) + README table |
| web-ui: Activation is readiness-gated on every entry path | study-plans § Activation |
| web-ui: Plan routes map seam errors… | internal HTTP |
| web-ui: Milestone checkbox is one SetMilestone; toggle not replay-safe | correctly **not** claimed in public docs |
| web-ui: Delete is confirmed by the verb… | internal HTTP; confirmation stated in study-plans |
| web-ui: Checkpoint recording reports each sink | study-plans preview vs Record; partial-sink UI copy not public — internal OK |
| web-ui: Plan with architect journey | study-plans + web-ui-guide (subject, creates no plan, label survives reload) |
| CLI `studyloop plan architect` / `studyloop study --mode plan-architect` | **no delta requirement** (reconnect-from-`mode` is specified; the CLI entrypoint is not). Tests exist around purpose/mode, not established as a specified CLI contract |
| “Whichever door starts it, the architect works from a planning brief…” | **UNBACKED** for the CLI door (F2) |
| “evaluates … at the start, middle, and end of every session run against it” | **UNBACKED** as product behaviour; persona text only (F3) |
| Checkpoint labels `on-track` / `at-risk` / `stalled` / `complete` | **not established by the brief** — no delta names these verdicts |
| Rubric judgement “recorded per scenario in the project’s rubric receipt” | **UNBACKED** — receipt exists, verdicts PENDING (F1) |
| Installer: 9 tools + planning-purpose + five-phrase boundary + D-16 phrase | Backed by `PLAN_TOOL_NAMES`, `NOT_AUTOMATIC[:5]`, `test_docs_plan_integration_contract.py` |
| `docs/mcp.md` inventory language | **not established** — file not in the Phase 6 sweep (F5) |

## Owner items

**Add**

- Inject or disprove a `## Planning brief` on `studyloop plan architect` / `studyloop study --mode plan-architect`, then match F2’s sentence to the result. The public page currently asserts a brief the specs only bind on the Web start path.
- Confirm `docs/mcp.md` against the 32-name registry before archive (F5). Named by the existing mcp-server spec; invisible to the contract test.
- Split / untick T3.4 until the five rubric verdicts are written (F4). Same defect review-3 F6 already called.

**Keep as-is (do not remove)**

- Kiro/Claude permission decision (item 1) — still the T6.1 human gate; Phase 6 correctly refused to take it.
- Score the D-16 rubric (item 2) — this is T3.4b, not an agent task.
- Deviation 12, review-3 F2, parser `)`, `_evidence_command` quoting — real leftover design debts; not close-out theatre.
- Local branches, ruleset, token-revocation placeholder, order-dependent `agent-session-tools` test, GitHub writes (items 7–13) — housekeeping, but this draft is the one place they are listed. Do not drop them into the void.

**Do not add**

- A second live-session authority, auto checkpoints, auto milestone completion, single-active-plan, or session-plan binding — those stay #7 out of scope; the docs already say so once F3 is fixed.
