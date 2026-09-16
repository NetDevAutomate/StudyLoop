## 1. Verdict

**REJECT** — Phase 6 cannot honestly close the programme while the mandatory D-16 human verdict remains PENDING, acknowledged in-scope gaps remain unresolved, and the draft presents future archive and final-verification actions as completed evidence.

## 2. Findings

### F1 — 🔴 Ticking T3.4 repeats the explicitly rejected definition-of-done substitution

**Files:** `openspec/changes/plan-application-seam/tasks.md`, T3.4; `docs/architecture/plan-integration/receipts/issue-closeout-draft-2026-09-16.md`, #10 and proposed PR description.

The task says both “ticked at archive so the change can close” and “a scored rubric is the DoD; an unscored one is not ‘done’.” Naming the scorer as the owner does not satisfy D-16 or review-3 F6.

Replace T3.4 with:

> - [ ] **T3.4 — D-16 human rubric acceptance pending.** Engineering fixture outputs and rule-cited rationales landed at `c27a34d5`; this does not complete the task. The owner must enter five yes/no verdicts, one explanation per scenario, and the evaluated tree SHA in `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`. A “no” on rows 1–4 returns to council arbitration. Do not mark complete or close #10, #15, or #7 before the verdicts and any resulting findings are resolved.

**Done:** five scored rows, no PENDING verdict, identified evaluated tree, required arbitration resolved.

Do not add a permanent public-doc test requiring a dated task checkbox. This belongs in an archive/close-out readiness check.

### F2 — 🔴 The Study Plans guide promises automatic architect evaluations and universal tooling that its own exclusions contradict

**File:** `docs/study-plans.md`, “Build a plan with the study-plan-architect.”

Two sentences need correction:

> “then evaluates the plan … at the start, middle, and end of every session run against it”

This implies guaranteed session-linked evaluation despite the explicit exclusion of session binding and session-event checkpoints.

> “Whichever door starts it, the architect works from a planning brief … and creates, revises, activates, and evaluates plans through the same plan tools … falling back to `studyloop plan …`”

A rendered planning brief on the **CLI launch path is not established by the brief**. The supplied specifications establish that behavior for Web starts. The universal revision claim also conflicts with the disclosed Kiro/Claude CLI fallback, which cannot revise existing fields or delete plans.

Use:

> The architect persona describes a mission-first interview and explicit start, mid, and end checkpoints. StudyLoop does not schedule these checkpoints from session events or bind the conversation to a plan.

> A Web-launched architect receives a planning brief containing interview questions, study-history evidence, and existing-plan summaries. An MCP-connected architect can obtain that context with `get_planning_interview`. Available plan operations depend on the connected tools; the CLI fallback cannot revise an existing plan’s fields or delete a plan. See the harness-specific limits in the installation guide.

A stronger CLI-brief claim requires a named launcher-path test and specification; neither is supplied.

**Contract pin:** add `test_architect_docs_bound_checkpoints_and_fallback` asserting that the section excludes event-driven evaluation, names the two unsupported fallback operations, and contains no “every session run against it” or “Whichever door” guarantee.

### F3 — 🔴 The public rubric sentence reports a judgement that has not happened

**File:** `docs/study-plans.md`, “Plan-aware now,” final sentence.

> “whether the primary is the action *you* would take is a separate judgement, recorded per scenario in the project's rubric receipt”

The outputs and rationales are recorded; the human judgements are PENDING.

Replace with:

> Ranking tests establish compliance with the ranking rules, not learner benefit. Human acceptance of the suggested primary action is a separate five-scenario check; its verdicts are currently pending.

After scoring, change only the status sentence and link to the actual receipt.

**Contract pin:** extend `test_study_plans_doc_uses_the_bounded_release_language` with a receipt-status consistency assertion: while the human-verdict cells are PENDING, the public paragraph must say they are pending.

No “better learning,” “learn faster,” or equivalent outcome guarantee appears in the supplied public text. The preferred phrase is correctly used for #10 in the guide, Web guide, and installer. The problem is the claimed completion of the separate judgement, not the ranking language itself.

### F4 — 🔴 MCP mission-revision claims exceed the specified tool schema

**Files:** `docs/agent-install.md`, “Study-plan tools over MCP”; delta `mcp-server/spec.md`, “Study-plan discovery and authoring tools.”

The installation guide identifies “revising an existing plan’s **mission**, topics or milestones” as an operation available through Web or MCP. The specified `update_study_plan(...)` signature exposes title, topics, dates, energy, cadence, notes, milestones and status—but no mission fields.

Mission revision through this MCP tool is **not established by the brief**.

**Fix:** either document the supported field list without promising MCP mission revision, or synchronize the specification and public schema evidence if the accepted implementation actually supports it. This review does not authorize a new tool capability.

**Contract pin:** add `test_documented_mcp_revision_fields_exist_in_schema`, comparing any publicly enumerated revision fields against the production tool input schema. Do not use tool-name presence as evidence of field-level capabilities.

### F5 — 🟡 “Plan-aware now” needs eligibility and compatibility qualifications

**Files:** `docs/study-plans.md`, “Plan-aware now”; `docs/cli-reference.md`, Now paragraph.

The guide says:

> “a plan with no other evidence still gets its next milestone suggested”

The specification requires a **ready, energy-permitted** plan with an unchecked next milestone. An active-but-unready document is matched for repair, not synthesized; a fully checked plan produces a completion action.

The guide also says that with no active plan the recommendation is “exactly what it was before plans existed.” The supplied golden proves the frozen empty/draft fixture. The specification separately requires warnings on failed plan reads, so an unconditional no-plan byte-identity promise must not swallow that exception.

The CLI sentence says JSON “gains” several fields when active. The specification says each empty field is omitted; activation does not cause every listed key to appear.

**Fix:**

- Say “a ready plan with an energy-eligible next milestone.”
- Explain active-but-unready repair warnings and fully checked completion actions.
- Say normal no-active-plan output remains unchanged, while plan-read failures can add warnings.
- Say the JSON adds **non-empty** plan-context fields and action references.

**Contract pins:** add `test_now_docs_state_eligibility_and_optional_json_fields`, checking these qualifications. Keep `test_no_active_plans_json_byte_identical_to_golden` as the behavioral evidence, not a universal proof about every failure state.

### F6 — 🟡 The installer undercounts the category it names, although its registration condition is honest

**Files:** `packages/studyloop/src/studyloop/cli/_install.py`, `_plan_capability_lines`; `agents/mcp/README.md`.

“Exposes 9 plan tools” is ambiguous against the verified **ten plan-named tools**. Other documentation correctly distinguishes nine lifecycle tools plus `record_plan_learning`.

Use:

> The `studyloop` MCP server exposes nine plan lifecycle tools (…) plus `record_plan_learning`, available to agent processes with the server registered and the tools permitted.

A short capability paragraph after installation is appropriate. “To any agent process it is registered with” already avoids claiming that `install agents --tool kiro` attaches the server; an explicit permission qualifier makes the boundary clearer. The detailed Kiro/Claude explanation can remain in the linked guide.

`--uninstall` should make no capability claim; its existing test is appropriate.

**Contract pins:**

- Extend `test_installer_output_names_the_nine_tools_and_the_planning_purpose` to require “lifecycle” and `record_plan_learning`.
- Extend `test_installer_output_states_the_boundary_with_the_constant` to cover every intended installer boundary, including “turn a plan into a filter”; it currently checks only the first four.
- Preserve `test_uninstall_output_makes_no_capability_claims`.

### F7 — 🟡 The boundary tuple is a useful summary, not a complete or behavior-grounded specification

**Files:** `docs/study-plans.md`, “Deliberately not automatic” and “Where plans live”; `packages/studyloop/src/studyloop/planning/boundaries.py`.

The first five phrases faithfully summarize the central learner-facing restrictions. Selecting and persisting a plan at normal session start are both explained under live-session binding.

Coverage of the remaining #7 exclusions is:

| #7 exclusion | Coverage and disposition |
|---|---|
| One-active-session invariant; no second authority | The architect conflict paragraph supports this; explicitly state that planning uses the same single-session slot. |
| No second planning transport or terminal | The existing-console paragraph supports this; keep it outside an automation-only list. |
| No browser-architect branch resurrection | Internal project scope; no learner-facing bullet needed. |
| No two-way second-brain editing | Explicitly covered by “never read back into it.” |
| No unrelated provider/model selection changes | The selected agent/transport language is compatible; internal scope, not a required negative product claim. |
| No autonomous recurring planning | **Missing from the supplied guide.** Add a direct sentence that planning sessions start only on request and are not scheduled autonomously. |
| Markdown not replaced by SQLite | Explicitly covered by “single source of truth”; checkpoint indexing is distinguished. |

“Structure the manual form’s brain dump” is a **current input-path limitation**, not the same kind of session-automation exclusion. It may remain nearby, but label it as such. It also does not explain away #14’s separate unimplemented **brain-dump handoff** requirement.

The tuple/prose equality test proves consistency between two representations, not that production behavior enforces the exclusions. The module’s “cannot claim more—or less—automation” explanation overstates what that pin establishes.

**Fix:** distinguish automation boundaries, input limitations, and internal scope. Add the autonomous-scheduling sentence and adjust the tuple/test together if it becomes a bullet.

**Contract pin:** require the recurrence exclusion and the single-session statement; retain behavioral evidence such as `test_planning_launch_creates_no_plan_and_no_plan_id` separately.

### F8 — 🔴 Two additive specifications disagree about reconnect-purpose inference

**Files:**

- `openspec/changes/plan-application-seam/specs/live-session-orchestration/spec.md`, “Session purpose.”
- `openspec/changes/plan-application-seam/specs/web-ui/spec.md`, “Plan with architect journey.”

The former says `/api/session/state` defaults to `focus` when state predates the purpose key or an overlay rebuilt the payload. The latter requires a state file with `mode == "plan-architect"` and no purpose key to report `planning`.

**Fix the orchestration requirement to match the explicit Web scenario:**

> `GET /api/session/state` SHALL preserve an explicit persisted purpose; otherwise it SHALL infer `planning` from the persisted planning persona mode and default to `focus` for other states. The same precedence applies to file-only and live-slot overlay responses; topic text SHALL never determine purpose.

**Done:** both normative requirements state identical precedence, and `test_web_plan_architect_journey.py::TestReconnectLabelFromPersistedMode` remains the cited behavioral evidence.

Additional specification cleanup before promotion:

- In `agent-adapters/spec.md`, qualify “A tool missing … SHALL route to that step’s CLI fallback”: field revision and deletion have **no** such fallback.
- In `active-learning-decisions/spec.md`, qualify the guidance statement that every recorded assessment on an unready active plan is refused: database-only recording is expressly permitted by “Assessment reports each recording sink independently.”
- In `cli-surface/spec.md`, rename “one line and exit 1” to “one shared mapping and exit 1”; its readiness mapping explicitly prints multiple lines.
- Reconcile the CLI milestone message description with the shared `InvalidMilestone` mapping rather than specifying two apparently different leading messages.

These are contract corrections, not a reopening of implementation review.

### F9 — 🟡 Several learner-visible behaviors lack a public sentence in the supplied evidence

**Files:** public plan/CLI guides; corresponding CLI and Web delta requirements.

The gap table below identifies all delta requirements. The material public gaps are:

- Partial recording on **CLI and Web**: success HTTP/exit status does not mean both sinks saved; “not recorded” differs from “partially recorded.”
- CLI milestone behavior: `--done`/`--undone` are retry-safe; omitting the flag toggles.
- Web checkbox requests: replaying the legacy toggle is not retry-safe.
- Active-but-unready hand-edited plans: preview remains available; document-writing operations require pause or repair.
- Deletion confirmation semantics: the MCP flag is required, while the Web API treats the DELETE verb itself as confirmation.

The existing general statement “deleting a plan needs your explicit confirmation” is safe as an architect instruction, but must not be presented as a universal separate-confirmation mechanism for every API. The Web specification explicitly accepts the DELETE request as confirmation.

**Fix:** add short “Recording outcomes” and “Retries and deletion” notes to `docs/study-plans.md`, with detailed CLI behavior in `docs/cli-reference.md`.

**Contract pins:** add `test_plan_docs_distinguish_partial_recording_and_retry_semantics`, including the contrast between Web toggle replay and explicit desired-state operations.

Because only a diff of the CLI reference is supplied, whether some of these explanations already exist elsewhere in that file is **not established by the brief**. Cite the existing sentence instead if it does.

### F10 — 🟡 The verification registry covers the requested checks, but not the draft’s enlarged claims

**Files:** `scripts/verify/plan_integration.py` registry; close-out draft, #15 and proposed PR evidence.

All design-§8 and review-4 checks enumerated in §6 are present: lint/format/typecheck, Bug A/B, guard, golden digest and identity, both inventories, plan suites, docs contract, protected files, invariants, integration/browser/JS checks, specification validation, documentation build, and both package suites.

The projection equalities and manifest hashes may legitimately remain inside `plan-suites` through `test_plan_architect_persona.py`; separate top-level checks are unnecessary if the receipt identifies the selected tests and counts.

Three limits must be corrected:

1. **Combined ordering:** the registry runs stdio smoke before the combined journey, not the reverse. The brief reports earlier passes in both orders, but the final receipt cannot be described as verifying both orders unless a reverse-order check is added.
2. **“Full suite”:** two package-scoped runs are not a workspace-wide run. The known root-config order failure is explicitly listed as owner item 12. Claim “both package suites pass independently” until the required full-suite interpretation is resolved; do not quietly weaken it.
3. **Final receipt:** the only real run supplied had unusable node counts and was discarded. A complete D-15 receipt on the post-archive tree is still pending.

**Done:** commit an actual receipt with the tested SHA, all required exits, usable pytest counts, inventory and golden evidence, and no missing required checks. If additional checks are added, update “28 checks” everywhere.

Also provide separate evidence for `check-release-consistency.py --release --pre-tag` and `just release-consistency-shipped` before claiming they passed; neither is in the listed registry.

### F11 — 🟡 UAT is honestly mechanics-only, but one specific evidence claim is overstated

**Files:** `docs/acceptance-testing.md`; UAT redacted receipt; close-out #14; `tasks.md`, T6.3.

`harness: "fake-agent"`, `actor_backend: "scripted"`, null model fields, empty `per_criterion_scores`, and the explicit arbitration note accurately describe the run. The template’s broader field definitions are **not established by the brief**, but no supplied evidence conflicts with those values.

Committing that redacted summary is acceptable. It must consistently be called **mechanics sign-off**, not an architect-interview or D-16 human acceptance sign-off. Adding an allowlisted `signoff_scope: "mechanics"` would make machine consumers less likely to confuse it with grading.

The cited UAT `test_architect_launch` checks visible labels **before** reload and checks `/api/session/state` **after** reload. It does not assert a visible planning label after reload. Therefore “UAT proves the label survives reload” exceeds that cell’s assertions. The separate `test_console_is_labelled_planning_and_label_survives_reconnect` is the correct supplied citation for the UI claim.

**Fix:** narrow the UAT receipt/documentation attribution to persisted purpose after reload, or add a post-reload visible-label assertion and issue a new receipt. Do not retroactively strengthen the old receipt.

### F12 — 🔴 The proposed close-out admits incomplete acceptance while still scheduling unconditional closure

**File:** `docs/architecture/plan-integration/receipts/issue-closeout-draft-2026-09-16.md`.

“Closes #7 … #15” is not made honest by a later “Honest limits” paragraph. In particular:

- #10 has an unmet binding D-16 check.
- #13 remains “partly” pending a human permission-boundary decision.
- #14 omits an explicitly named acceptance input: optional brain dump.
- #15 requires completed children and no unverified in-scope parent requirement.

The claim “yes, with the exceptions marked above” does not satisfy #15’s completed-child criterion.

**Fix:** replace unconditional closing keywords with “Related: #7–#15” in the draft until each affected issue is either satisfied or explicitly re-scoped by the owner. A re-scope must record the changed acceptance wording and residual ticket; documentation alone is not acceptance amendment.

The other row-level corrections are:

| Close-out row | Correction needed |
|---|---|
| #8 Markdown authority and best-effort recoverable index | A module citation plus activation requirement does not identify a recovery test. Supply the actual test for index failure/reindex recovery; its identity is not established by the brief. |
| #9 milestone changes “idempotent under retries” | Qualify this as explicit-state seam/CLI/MCP operations, excluding the Web toggle request and no-flag CLI toggle. |
| #14 manual create/edit/checkpoint interface | Cited browser evidence establishes manual creation; unchanged API tests support the routes. Manual edit/checkpoint UI coverage is not established by the supplied citations. Narrow the evidence statement or identify those browser tests. |
| #15 public claims agree | Not yet, for F2–F7. |
| #15 specs synchronized | Pending archive and F8 corrections, not “yes” based on a future promotion. |
| #15 completed-child mapping | “Mapped; acceptance incomplete,” not “yes.” |

The remaining “yes” rows have relevant supplied test/module evidence at the level appropriate to this docs review; that does not constitute independent execution of those tests.

The qualified rows also need precision:

- #12 correctly says failed-sink behavior is tested in-process only, but calling it a “partial-recording **refusal**” is wrong: it is a successful evaluation with incomplete recording.
- A subprocess’s inability to receive an in-process monkeypatch is a test-method limitation, not proof that failure-path wire testing is impossible.
- #13’s permission decision remains unresolved; describing the temporary restriction as deliberate must not imply that the owner chose the permanent outcome.
- #14’s “mostly” is candid, but missing input behavior is **unimplemented**, not merely unverified.
- “Cancellation” is not tested by ignoring a second click. Add the dedicated cancellation gap to the parent list.
- Persona-text verification is legitimate evidence of the specified one-question protocol instruction, but not of live-model compliance.

### F13 — 🟡 Clean status, temporary-artifact removal, and branch cleanup are different claims

**Files:** close-out draft, #8/#15 and owner items 7–8; `tasks.md`, T6.4.

The brief does not establish final clean status or removal of temporary artifacts. Gitignored Archify sidecars cannot establish either fact: intentional generated deliverables may be retained, while scratch artifacts still need disposition.

The supplied UAT `world` fixture creates a temporary directory without a shown cleanup step. This is evidence that “no temporary artifacts remain” needs an explicit cleanup receipt—not a request to reopen the fixture’s implementation review.

Unrelated branches and worktrees do not themselves make this working tree dirty. Deleting them is not a prerequisite for #15 repository cleanliness.

**Fix:**

- Record final tracked/untracked working-tree status.
- Record scratch-directory cleanup separately from intentional durable evidence and regenerable artifacts.
- Move unrelated branch/worktree decisions out of the #15 cleanliness discussion.
- Do not delete unrelated work merely to make the close-out look complete.

### F14 — 🟡 Archive prose is prematurely past tense and contains references that will age poorly

**Files:** `tasks.md`, T6.1/T6.2; close-out draft; six delta specs.

The reviewed tree precedes archive and final verification, but the task and close-out text already say specs “are promoted,” the final receipt is “committed beside this draft,” and release checks pass. Those statements need **PENDING** status until actual artifacts exist.

Replace every `verify-<sha>.json` placeholder in the posted close-out with an actual path and clearly distinguish the verified source commit from any later receipt-only commit.

No supplied public page contains a literal `openspec/changes/plan-application-seam/...` link that archive will break. Other repository references are **not established by the brief**. The six source paths in the brief are archival inputs, not proof of public broken links.

Before promotion, remove or replace normative-spec chronology such as:

- “issue #10, next requirement”
- “Phase-0”
- “This was the only change … in Phase 2”
- “the last requirement in this file”
- unqualified “design §…” references

Keep historical provenance in the archived design/receipt; use requirement names or stable links for normative dependencies. Immutable baseline SHAs and named golden fixtures remain useful evidence and need not be removed merely because they are historical.

**Stale-reference audit:** the supplied public text no longer contains the old “not integrated yet,” “do not yet influence,” `mcp/tools.py:129`, or “tracked as Phase 6, T6.1” claims. The current “CLI-limited” disclosure is accurate, not stale. The install guide’s unlinked “open item in the … close-out” should become a stable link, updated when the owner decides.

### F15 — 🔵 The MCP heading and historical counts need clearer maintenance contracts

**File:** `agents/mcp/README.md`, “studyloop-mcp (Session DB Tools).”

The heading is now misleadingly narrow. Rename it to **“studyloop-mcp (Study tools)”** and retain an explicit legacy anchor for link stability. Update the two `_section(...)` users in `test_docs_plan_integration_contract.py`.

The verified 32-tool table is correct. Keep its registry equality and count tests. The installer should distinguish nine lifecycle tools from ten plan-named tools as described in F6.

Also correct stale scenario-count prose: T3.4 says the Now requirement carries nine scenarios, and the close-out says the Web journey carries eight; the supplied delta texts contain more. Remove incidental counts unless generated or deliberately tested.

## 3. Spec ↔ docs gap table

“**MISSING**” below means no adequate public sentence is supplied in this brief, not a claim about unseen portions of repository files.

| Delta requirement → public sentence, or doc claim → backing | Correspondence / gap |
|---|---|
| **Active-learning: Activation is readiness-gated on every entry path** | `docs/study-plans.md`, “Activation”: resulting active documents are checked and refused activation writes nothing. Frozen views, exception types, identity preservation and adapter architecture are **internal**. |
| **Active-learning: Partial checkpoint recording is reported, never silent** | Install guide describes failed recording sinks and warnings. **MISSING** general Web/CLI explanation that successful evaluation can accompany failed recording. |
| **Active-learning: Milestone set is idempotent and refuses indices the plan lacks** | Install guide: “set, not toggle, so a retry is safe.” Index errors are listed as `invalid_milestone:`. Active-but-unready behavior needs the F9 public explanation. |
| **Active-learning: Deletion is confirmed and retains the checkpoint log** | Install table: confirmation flag required; checkpoint history kept. Frozen result and derived-index removal are **internal**. |
| **Active-learning: Assessment reports each recording sink independently** | Install table and following paragraph describe preview, sink fields and `recording_complete: false`. **MISSING** the corresponding CLI/Web outcomes and database-only exception explanation where exposed. |
| **Active-learning: Active-plan guidance is a deterministic read** | Guide: every active plan is considered deterministically. Match-key implementation, view ordering, identity pinning and one effective date are **internal**. **MISSING** unready-plan and fully checked-plan user outcomes. |
| **Active-learning: The now engine is plan-aware with tested ranking rules** | Guide’s “Plan-aware now,” CLI reference, Web Today section. Eligibility, optional fields, warning exceptions and pending rubric need F3/F5 corrections. |
| **Active-learning: Adapters reach study plans only through the seam** | Install guide: every tool uses the same application layer as CLI/Web. AST/import enforcement is **internal**. |
| **Active-learning: The learning-record rule has one copy** | **Internal** implementation requirement. Public install table identifies the record operation; validation/idempotent retry details would be useful but are not necessary to explain code ownership. |
| **Agent-adapters: Persona resolution by purpose** | Guide: Web architect starts a planning session using the selected agent/transport. Resolver mapping, brief placement and byte-identical focus rendering are **internal**. |
| **Agent-adapters: Architect persona prefers the MCP plan tools** | Guide and install section describe MCP tools and CLI fallback. Public universal-capability wording and specification fallback exception need F2/F8 corrections. |
| **CLI: Activation is readiness-gated on every entry path** | Guide “Activation” and terminal status example. Exact JSON compatibility is an adapter contract; refusal explanations should be linked from the CLI reference. |
| **CLI: The CLI maps every seam refusal to one line and exit 1** | **MISSING** supplied public CLI refusal/exit-status explanation. `_fail_for` ownership is **internal**; requirement title needs correction. |
| **CLI: Every plan command reads and writes through the seam** | Install guide’s shared-layer statement. Command delegation, preserved key sets and reindex implementation are **internal**. |
| **CLI: The CLI milestone command is an idempotent set** | Terminal example shows `--done`, but **MISSING** no-flag toggle and explicit-flag retry distinction. |
| **CLI: Recorded checkpoints report a complete, partial or absent recording** | **MISSING** public CLI success/partial/absent-recording explanation, including exit 0 on successful evaluation despite failed sinks. |
| **CLI: Learning records are one revision through the seam** | One-revision architecture is **internal**. The supplied public text does not document `created: false` retry output; add it if advertising record-command retry semantics. |
| **Live-session: Session purpose** | Guide describes planning label, reload, no creation, shared session conflict and selected transports. Specification reconnect-default conflict needs F8 correction. |
| **MCP: record_plan_learning writes through the plan seam** | Install table calls it the wind-down’s first write; shared seam and prefixed errors are explained. Mutation-outcome propagation is **internal**. |
| **MCP: Study-plan discovery and authoring tools** | Install table documents six tools, conflict behavior, limits and refusal kinds. Mission revision is **UNBACKED** by the specified update schema. |
| **MCP: Study-plan progression and deletion tools** | Install table documents explicit milestone state, preview/record, confirmation and retained history. README documents the complete 32-tool inventory. |
| **Web: Activation is readiness-gated on every entry path** | Guide “Activation” states the relevant operations, resulting-document validation and write-nothing refusal. HTTP shape and single-intent delegation are **internal/API** details. |
| **Web: Plan routes map seam errors to HTTP status codes in one place** | Centralized mapping is **internal**. Shared readiness behavior is public; no requirement to teach learners every HTTP status. |
| **Web: The milestone checkbox is one SetMilestone; the toggle request is not replay-safe** | Guide says checkboxes update Markdown. **MISSING** retry distinction for API callers; do not imply Web-toggle replay safety in the close-out. |
| **Web: Delete is confirmed by the verb and retains checkpoint history** | History retention appears in the MCP table. **MISSING** Web API confirmation distinction; universal “explicit confirmation” wording needs qualification. |
| **Web: Checkpoint recording reports each sink** | Guide describes preview and explicit recording. **MISSING** partial/absent-recording UI outcomes and successful HTTP response despite sink failure. |
| **Web: Plan with architect journey** | Guide and Web UI guide describe control, optional subject, existing console, label/reload, conflict and no plan creation. Detailed events/ARIA selectors are **internal**. |
| **Doc claim: all launch doors receive a rendered planning brief** | **UNBACKED** for CLI/harness-native launches by supplied specs/tests; Web path is backed. |
| **Doc claim: architect evaluates at every session’s start/mid/end** | Contradicts manual/session-event boundary; persona instructions do not prove guaranteed execution. |
| **Doc claim: MCP can revise existing mission** | **UNBACKED** by supplied `update_study_plan` schema. |
| **Doc claim: human primary-action judgement is recorded per scenario** | Contradicted by T3.4 and #10: verdicts PENDING. |
| **Doc claim: no-active-plan output unchanged** | Backed for normal frozen empty/draft case by `test_no_active_plans_json_byte_identical_to_golden`; qualify warning/failure cases. |
| **Doc claim: active plan always gets a next milestone without other evidence** | Backed only for ready, energy-eligible, unfinished plans by synthesis rules and tests. |
| **Doc claim: manual brain dump is saved, not decomposed** | Explicitly stated in the guide/Web guide; Web requirement preserves the manual path. This does not establish delivery of that text to the architect. |
| **Doc claim: Markdown is authoritative; projections are one-way** | Bound by #7 exclusions and guide “Where plans live”; architecture/index behavior remains compatible. |
| **Doc claim: 32 registered tools** | Backed by verified production registry, README table equality and stdio inventory. |
| **Installer claim: nine “plan tools”** | Nine **lifecycle** tools are backed; total plan-named tools are ten. Qualify the category. |
| **Doc claim: label survives reload** | Backed by named dedicated browser test; UAT cell itself establishes persisted purpose after reload, not a post-reload visible-label assertion. |
| **Doc claim: architect interview available over MCP** | Backed as tools plus persona used by a connected agent—not as a separate MCP launch endpoint or verified live-model interview. |
| **Close-out claim: all specifications promoted; final receipt committed** | Future actions on the reviewed tree; **UNBACKED** until archive and receipt exist. |
| **Close-out claim: combined final verification covers both orders** | Listed registry covers one order; earlier both-order evidence is reported separately. |
| **Close-out claim: all children complete; parent has no unverified in-scope requirement** | Contradicted by its own pending/partial/missing entries. |

## 4. Owner items

- **Add — Resolve closure eligibility for #7/#10/#13/#14/#15:** satisfy each remaining criterion or explicitly amend its scope before enabling automatic issue closure.
- **Retain and strengthen item 2 — D-16 verdicts:** scoring is a blocking acceptance action, not post-close administrative work.
- **Retain item 1 — Kiro/Claude permissions:** record an explicit keep-limited or grant-tools decision; this seat does not choose a permission model.
- **Add — Optional brain-dump handoff:** implement it or formally remove it from #14 acceptance with a residual ticket; a subject field is not equivalent.
- **Add — Cancellation evidence:** resolve the missing browser abandonment/cancellation coverage instead of treating a repeated-click no-op as cancellation.
- **Add — Workspace test scope:** resolve item 12’s order-dependent failure or formally identify an accepted package-scoped verification boundary; keep the failure visible.
- **Add — Archive/final-receipt approval:** require actual promoted specs, resolved receipt path, release-consistency results and cleanup evidence before posting completion claims.
- **Add — Live-model protocol evidence disposition:** state whether persona-text compliance satisfies acceptance or whether a live-agent run is required; the mechanics UAT cannot decide this.
- **Clarify item 3 — Legacy unready-plan policy:** identify whether it is an unresolved acceptance decision or an accepted policy with a possible future reconsideration.
- **Clarify item 4 — Urgency-class redesign:** label it a future design option, not an open Phase-6 acceptance decision, because the brief says council already accepted the bounded-bias rule.
- **Move items 5–6 to linked follow-on tickets:** parser round-trip and suggested-command quoting are known defects, not reasons to reinterpret this docs review as code re-review.
- **Move items 7–10 out of #15 cleanliness:** unrelated branches, exploratory work and deletion rules are repository administration, not evidence that this working tree is dirty.
- **Route item 11 privately to the responsible owner:** retain visibility without inventing token context or publishing sensitive details not established by the brief.
- **Rewrite item 13 — GitHub writes:** authorize evidence comments now only as status reports; close issues and mark the PR ready only after the blocking decisions and receipts are complete.
