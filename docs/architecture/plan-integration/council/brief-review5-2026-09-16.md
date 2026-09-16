# Council brief — review 5 (docs/spec seats): Phase 6 (#15) of the plan-integration programme

**Date:** 2026-09-16 · **Branch:** `fix/plan-integration-bugs`, reviewed tree `fd10789e` (Phase 5 accepted at `1e1a5680`;
reviews 1–4 all `GATE: ACCEPT`, arbitrations under `docs/architecture/plan-integration/council/`). **You are one
independent seat**; no other seat's answer is visible. You have no tools — this brief is the complete evidence base.
This is the **docs/spec review** the plan reserved for #15 ("Docs/spec review at #15: `openai.gpt-6-astra`, `grok-4.6`,
`kimi-k2-thinking`"). Code was reviewed in rounds 1–4; do not re-review it. Your job: are the public claims true and
bounded, are the specs and docs synchronized, is the close-out honest, and is anything the archive will make stale.

After your review the change `plan-application-seam` is archived with `openspec archive` (the CLI merges the six delta
specs below into the normative specs), the verification receipt is re-run on the final tree, and the owner posts the
close-out in the morning. Nothing has been posted to GitHub; nothing here is pushed.

## 0. What you are reviewing against (binding)

### D-15 and D-16 (arbitration-plan-round1-2026-09-15.md, verbatim)

> **D-15 — Definition of done is a receipt, not a feeling.** Adopt GPT's proposal of a verification script, placed at
> `scripts/verify/plan_integration.py` (repo convention: `scripts/<area>/`), that runs the named suites, lint, typecheck
> and the `rg` invariants, records exit codes and node counts, and writes
> `docs/architecture/plan-integration/receipts/verify-<sha>.json`. Missing checks are recorded as failures, never as
> "not applicable".
>
> **D-16 — Learner benefit is a separate, later measurement; release language is bounded.** Ranking tests prove ranking
> compliance, not learning. Adopt GPT's phrasing for the docs: "plan-aware guidance with tested ranking rules", never
> "better learning". Adopt Grok's cheap pre-ship check: a five-scenario human rubric on frozen fixtures … scored "would I
> do the primary?", committed as a receipt. Post-ship accept/skip logging tagged `plan_backed|not` is a follow-on ticket,
> not part of #10's DoD.

### Issue #15 (verbatim)

Acceptance criteria:
- Study Plans, Now, Today, Web, MCP, and installer language describe the implemented automatic boundaries accurately.
- Active-learning, MCP, Web UI, agent-adapter, and CLI capability specs are synchronized.
- CLI, Web, MCP, and architect journeys document both supported behavior and remaining live-session-binding exclusions.
- Every acceptance area in parent issue #7 maps to completed child tickets and verification evidence.

Definition of Done:
- The full unit suite passes.
- Representative Web and MCP integration journeys pass independently and in the combined run.
- The combined integration run has no nested-event-loop ordering regression.
- All public documentation, installer output, and capability matrices agree.
- Repository status is clean and no temporary artifacts remain.
- Parent issue #7 has no unverified in-scope requirement.

### Issue #7 "Out of Scope" (verbatim) — what the docs must call deliberately not automatic

- Persisting a plan identifier on live study-session state.
- Automatically selecting a plan when a normal study session starts.
- Automatically running start, midpoint, or end checkpoints from session events.
- Automatically completing milestones from study-session evidence.
- Hard-blocking off-plan study or turning plan focus into an exclusion filter.
- Enforcing exactly one active plan.
- Changing the one-active-session invariant or introducing a second session authority.
- Building a second planning-specific PTY, ACP, WebSocket, or terminal implementation.
- Wholesale merge or resurrection of the archived browser-architect branch.
- Two-way editing from second-brain projections.
- Provider/model selection changes unrelated to the existing agent adapter and launch interfaces.
- Scheduling autonomous recurring planning sessions.
- Replacing the current Markdown source of truth with SQLite.

Issue #7, Further Notes: "The current plan-aware product boundary is documented accurately in the Study Plans guide; stale
installer language claiming that an active plan already changes Now must be corrected."

### Review-4 owner item on the Kiro/Claude architect headers (verbatim excerpt)

> **The decision the owner must make (T6.1):** keep the two harness-launched architects deliberately CLI-limited (then
> the pin stays and the install doc's disclosure is the contract), or grant them the plan tools … Granting authoring,
> lifecycle and a destructive tool to a harness-launched agent changes its permission model, which is why this is a
> human decision and not an arbiter's correction.

Phase 6 did **not** take that decision (it is the owner's); the install doc now states the boundary as a deliberate
permission boundary with the decision recorded as an open item in the close-out draft.

### Facts verified on `fd10789e` you may rely on

- Production FastMCP registry: exactly **32** unique tool names: `create_study_plan, delete_study_plan, end_session, evaluate_study_plan, generate_flashcards, generate_quiz, get_active_topics, get_chapter_text, get_concept_context, get_due_cards, get_lesson_tree, get_next_action, get_planning_interview, get_study_backlog, get_study_context, get_study_history, get_study_plan, get_topic_suggestions, list_courses, list_session_options, list_study_plans, log_review_outcome, log_struggle, log_topic, read_lesson, record_plan_learning, record_study_progress, record_topic_progress, search_lessons, set_study_plan_milestone, set_study_plan_status, update_study_plan`.
- The ten plan-named tools among them are exactly `studyloop.mcp.inventory.PLAN_TOOL_NAMES` (nine) + `record_plan_learning`.
- `tests/test_docs_plan_integration_contract.py`: 20 passed. Full studyloop suite at `3159efe0` (the first verify run): exit 0;
  agent-session-tools 2146 passed. `just lint`, `just typecheck` (pyright 0 errors), `openspec validate --specs --all`
  (25 passed), `mkdocs build --strict` clean at every commit below.
- The main specs have **no** requirement whose name collides with any delta requirement (checked by name); the merge is
  purely additive. Main specs mention study plans nowhere before the promotion.
- `studyloop install agents` printed only "Updated agent definitions." + per-tool counts before Phase 6.
- The `.html`/`.visual-check.*` Archify sidecars are gitignored; only the `.architecture.json` spec is tracked.

## 1. Phase-6 commits (oldest first)

```
87afdcd4 test(docs): RED — the plan integration's public claims are pinned to code (#15, T6.1)
bdc559d5 docs(plans): the public claims match the shipped boundary — pinned to code (#15, T6.1) — GREEN
b02bd63a test(verify): RED — the plan-integration verification script's registry and receipt (#15, T6.2, D-15)
1129b83e feat(verify): scripts/verify/plan_integration.py — the receipt is the definition of done (#15, T6.2, D-15) — GREEN
f51d5118 test(journey): the combined Web + MCP plan journey in one process (#15, T6.3)
a69867bf test(uat): the three study-plan doors as strict sign-off cells with an evidence bundle (#15, T6.3)
3159efe0 docs(uat): redacted summary of the plan-journeys sign-off run at a69867bf (#15, T6.3)
e605a835 fix(verify): parse pytest's bare -q summary line, not only the barred one (#15, T6.2)
dcfd44e4 docs(archify): plan-integration diagram shows the final structure — now consumer, nine MCP tools, planning purpose (#15, T6.4)
fd10789e docs(closeout): draft the #7–#15 close-out — every criterion mapped to a node id, receipt or commit; unmet ones marked (#15, T6.5)
```
## 2. Public docs after Phase 6

### `docs/study-plans.md` — full text

```markdown
# Study Plans

A study plan gives a larger learning goal enough shape to guide a session without
turning planning into another project. It records why the goal matters, what
success would look like, and a small set of milestones you can actually check.

Plans are optional. Study Session, review, and Today all work without one.

## Create a plan in the Web UI

1. Run `studyloop web` and open **Study Plans** in the sidebar.
2. Select **New plan**.
3. Start with the large prompt: describe where you are now, where you want to get
   to, what you have tried, and what tends to block you.
4. Fill in or edit **Title**, **Why**, **Success looks like**, **Topics**, and
   **Milestones**.
5. Create the plan, read it back, and change anything that does not sound like
   your own goal.

!!! important "The form is manual; the interview is the other door"
    The free-text brain dump is saved as context, but the Web UI does not
    ask an agent to decompose it into the structured fields. For an agent-led
    interview instead, choose **Plan with architect** beside **New plan** —
    see [Build a plan with the study-plan-architect](#build-a-plan-with-the-study-plan-architect).

## Keep the plan small enough to use

A useful plan can answer three questions:

- **Why:** what becomes possible if I learn this?
- **Success:** what could I do or explain that would demonstrate it?
- **Next milestone:** what is the next observable piece of progress?

Three to five milestones are usually easier to return to than a complete
curriculum. Add a constraint or an out-of-scope item when it protects the plan
from expanding.

Example:

```text
Title: Understand Python decorators
Why: Read and change the decorators used in our data pipelines
Success looks like:
- Explain the wrapper relationship without notes
- Write and test one timing decorator
Topics:
- python
Milestones:
- Trace a decorated function call (concepts: wrapper, closure)
- Write @timed with functools.wraps (concepts: decorator, wraps)
- Test metadata and return values (concepts: testing, function metadata)
```

The `(concepts: ...)` suffix is optional, but useful: it connects a milestone to
the confidence evidence StudyLoop records for those concepts.

## Use checkpoints instead of guilt

Open a plan and use the **Checkpoint** controls at three natural moments:

- **Start:** is this still the right work, and what is the smallest next step?
- **Mid:** has the session drifted, or has the plan itself proved wrong?
- **End:** what moved, what evidence exists, and what should be left ready?

A checkpoint can describe a plan as `on-track`, `at-risk`, `stalled`, or
`complete`. These labels describe the plan and its evidence, not the learner.
Previewing a checkpoint does not save it; choose **Record checkpoint** when the
result is worth preserving.

Milestone checkboxes update the Markdown plan itself. Activation is refused when
the plan has no mission, success criteria, or milestones, because an empty active
plan would create noise rather than direction.

## Activation

Creating, importing, replacing, or revising a plan through supported Web
operations checks the resulting document before saving it as active. CLI
activation commands also refuse plans missing a mission *why*, success
criteria, or milestones. Refused activation writes nothing. More than one plan
may be active.

## Build a plan with the study-plan-architect

Instead of filling in the form yourself, be interviewed. The
`study-plan-architect` persona runs the mission-first interview described
above, then evaluates the plan against real study evidence at the start,
middle, and end of every session run against it. It ships to every harness —
see [Connect your AI coding tool](agent-install.md) for the native start
command on your harness. The launcher-driven form works everywhere:

```bash
studyloop plan architect
# or, choosing a harness explicitly:
studyloop study --mode plan-architect --agent claude
```

In the Web UI, **Plan with architect** on the **Study Plans** view (beside
**New plan**, with an optional subject) starts the same interview as a
*planning* session in the Study Session console, using the agent and transport
the start picker has selected. The console is labelled as a planning session,
and the label survives a page reload. The click creates nothing: the plan
appears in the list when the interview creates it. If a session is already
running, the console offers to reattach to it or end it first, exactly as a
normal start does.

Whichever door starts it, the architect works from a planning brief — the
interview questions, an evidence seed from your study history, and the plans
that already exist — and creates, revises, activates, and evaluates plans
through the same plan tools an MCP-connected agent uses (see
[Study-plan tools over MCP](agent-install.md#study-plan-tools-over-mcp)),
falling back to `studyloop plan …` at a shell when its harness has no
`studyloop` server. Activation is readiness-gated on every one of those
paths, and deleting a plan needs your explicit confirmation. The
`record_plan_learning` tool the second-brain wind-down calls before any
projection (see [second-brain.md](second-brain.md)) is part of the same set.

## Use plans from the terminal

```bash
# See what exists
studyloop plan list
studyloop plan show PLAN_ID

# Create a small plan
studyloop plan new \
  --title "Understand Python decorators" \
  --why "Read and change our pipeline decorators" \
  --success "Explain the wrapper relationship" \
  --topic python \
  --milestone "Trace a decorated call (concepts: wrapper, closure)"

# Check and update it
studyloop plan evaluate PLAN_ID --phase start
studyloop plan milestone PLAN_ID 0 --done
studyloop plan status PLAN_ID active
```

Run `studyloop plan interview` to print the questions an agent-led planning
conversation should work through. It does not itself start an agent.

## Plan-aware now

An active plan changes what StudyLoop recommends. `studyloop now`, the Web
**Today** card, the daily `recap`, and the MCP `get_next_action` tool all read
one recommendation result, and that result considers every active plan: the
action that advances a plan's next milestone is named with the plan and the
milestone it serves, a plan with no other evidence still gets its next
milestone suggested, and a plan whose energy floor is above your current
energy has that milestone deferred with a reason rather than dropped. This is
plan-aware guidance with tested ranking rules — a bias, not a filter: an
overdue review or a fresh struggle on an unrelated topic can still outrank new
milestone work, and with no active plan the recommendation is exactly what it
was before plans existed. The ranking rules are tested; whether the primary is
the action *you* would take is a separate judgement, recorded per scenario in
the project's rubric receipt rather than claimed here.

## Deliberately not automatic

A plan biases guidance and gives agents a full set of lifecycle tools. It does
**not** run the session. By design, StudyLoop does not:

- **bind a live study session to a plan** — starting a study session never
  selects a plan and never stores a plan id on the session; the planning
  session the architect runs in is labelled `planning`, and that label is all
  it persists.
- **run checkpoints from session events** — start, mid, and end evaluations
  happen when you (or the architect) ask for them; a preview writes nothing,
  and only an explicit record is kept.
- **complete milestones from study evidence** — a milestone is checked off by
  you or by the architect, never inferred from a session.
- **enforce one active plan** — every active plan is considered,
  deterministically; none is a hidden singleton.
- **turn a plan into a filter** — off-plan study is never blocked, and urgent
  reviews or struggles can outrank plan work.
- **structure the manual form's brain dump** — the free text is saved as
  context; the architect interview is the door for an agent-led decomposition.

These boundaries are stated here so that a plan never appears more connected
than it is. See the [roadmap](roadmap.md) for the intended continuity work.

## Where plans live

Plans are Markdown files stored in StudyLoop's local state directory. Find the
exact folder with:

```bash
studyloop plan path
```

The plan document is the **single source of truth**. If you publish a plan into a
second brain (see [Second Brain](second-brain.md)), what appears there is a
projection: regenerated from this document and never read back into it.

Because the document is the source of truth, it remains readable and editable
without the Web UI. Checkpoint history is also indexed in the session database.

## When planning becomes avoidance

Stop editing the plan and choose a five-minute action if you notice yourself:

- refining milestone wording without trying one;
- adding resources faster than you use them;
- inventing target dates without a real deadline;
- treating a missing plan field as a reason not to study.

The plan exists to make the next session easier to start. A rough plan that gets
used is doing its job.
```
### `docs/agent-install.md` — diff vs `1e1a5680` (the 'Study-plan tools over MCP' section is otherwise unchanged from review 4; its table is reproduced below the diff)

```diff
diff --git a/docs/agent-install.md b/docs/agent-install.md
index 1169e7c5..f659f353 100644
--- a/docs/agent-install.md
+++ b/docs/agent-install.md
@@ -223,5 +223,9 @@ harness-launched architect definitions for Kiro CLI
 not attach it, so an architect started from those two harnesses takes the CLI
-fallback the persona describes; wiring them is tracked as Phase 6, T6.1 of the
-plan-integration change. A Web-launched architect (`purpose=planning`) carries
-the same persona and uses whichever servers its agent process is connected to.
+fallback the persona describes. That is a deliberate permission boundary, not
+an omission: granting a harness-launched agent authoring, lifecycle and a
+destructive tool changes its permission model, and the decision to do so is
+the maintainer's, recorded as an open item in the plan-integration close-out;
+the two definitions stay CLI-limited until it is taken. A Web-launched
+architect (`purpose=planning`) carries the same persona and uses whichever
+servers its agent process is connected to.
```
### `docs/agent-install.md` — the 'Study-plan tools over MCP' section as it reads now

```markdown
## Study-plan tools over MCP

The `studyloop` MCP server (the `studyloop-mcp` command; per-harness
registration is in `agents/mcp/README.md`) exposes the learner's study plans
to any connected agent. Every tool
goes through the same plan application layer the CLI and Web UI use, so the
readiness gate, the lifecycle statuses and the "the Markdown document is the
source of truth" rule are identical on every surface. An agent that cannot
reach the MCP server can do most of this work with `studyloop plan …` at a
shell; two operations have no CLI command — revising an existing plan's
mission, topics or milestones, and deleting a plan — and need the Web UI or an
MCP-connected session. Whether the tools are reachable depends on the agent
process having the `studyloop` server registered, not on the persona: today the
harness-launched architect definitions for Kiro CLI
(`agents/kiro/study-plan-architect.json`, no `mcpServers`) and Claude Code
(`agents/claude/study-plan-architect.md`, `tools: Read, Write, Grep, Bash`) do
not attach it, so an architect started from those two harnesses takes the CLI
fallback the persona describes. That is a deliberate permission boundary, not
an omission: granting a harness-launched agent authoring, lifecycle and a
destructive tool changes its permission model, and the decision to do so is
the maintainer's, recorded as an open item in the plan-integration close-out;
the two definitions stay CLI-limited until it is taken. A Web-launched
architect (`purpose=planning`) carries the same persona and uses whichever
servers its agent process is connected to.

| Tool | Purpose |
|---|---|
| `list_study_plans(status=None)` | List plan summaries, active first; filter to one lifecycle status. |
| `get_study_plan(plan_id, include_markdown=False, include_history=False, history_limit=20)` | Read one plan in full — mission, milestones, records, readiness — optionally with its Markdown and the checkpoint log (1–200 rows). |
| `get_planning_interview()` | The interview questions, an evidence seed from the study databases, and the plans that already exist — call before interviewing. |
| `create_study_plan(title, answers, plan_id=None, status="draft")` | Draft a new plan from interview answers; never replaces an existing plan (a taken id is a conflict). |
| `update_study_plan(plan_id, …)` | Revise fields, topics, milestones and status together, judged as one document and saved once. |
| `set_study_plan_status(plan_id, status)` | Move a plan between `draft`, `active`, `paused`, `complete`, `abandoned`; activation is readiness-gated. |
| `set_study_plan_milestone(plan_id, index, done)` | Mark one milestone complete (`done=true`) or reopen it (`false`) — set, not toggle, so a retry is safe. |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | Evaluate the plan at a `start`/`mid`/`end` checkpoint against real study evidence. The default is a preview that writes nothing; `record=true` appends the checkpoint to the log and the document and reports each write (`db_write`, `document_write`, `recording_complete`). |
| `delete_study_plan(plan_id, confirmed=False)` | Delete the plan document — irreversible, so it is refused unless `confirmed=true`. The plan's checkpoint history is kept. |
| `record_plan_learning(plan_id, title, body="", status="active")` | Append a learning record to the plan — the wind-down's first write. |

A refused call is a tool error whose message starts with a machine-readable
kind — `not_found:`, `invalid_id:`, `conflict:`, `invalid:`,
`invalid_milestone:`, `not_ready:`, or `plan_error:` for a refusal the
mapping has not met — followed by the plan layer's own message. A `not_ready:` refusal names every blocker, so the agent can ask the
learner for what is missing instead of reporting that something is wrong; on
a plan that is already active it adds "pause it or repair the blockers before
writing". A recorded evaluation whose database or document write failed is
not an error: the response says which write failed (`recording_complete:
false` with the reason in `warnings`) and still carries the evaluation.
```
### Other public pages — diff vs `1e1a5680`

```diff
diff --git a/README.md b/README.md
index 6e122dca..b770aa34 100644
--- a/README.md
+++ b/README.md
@@ -109,4 +109,5 @@ clear:
   system voices when available;
-- study plans can be created in the Web UI or CLI, but the current Web UI form is
-  manual—an agent-led planning interview is not integrated there yet;
+- study plans can be created in the Web UI form, the CLI, or through the agent-led
+  architect interview (Web UI, CLI, or MCP); an active plan biases the next-action
+  recommendation but is never bound to a live study session;
 - practice-task generation and verification are currently CLI workflows.
diff --git a/docs/acceptance-testing.md b/docs/acceptance-testing.md
index 73341c30..ebe6fde3 100644
--- a/docs/acceptance-testing.md
+++ b/docs/acceptance-testing.md
@@ -488,2 +488,3 @@ on the `testacc` recipe above.
 | `tests/acceptance/uat/test_journey_smoke.py` | A CI-safe mechanics smoke test: the hermetic server (E-B2) + a scripted turn sequence + the bundle writer, composed end to end, with the mentor played by the repo's existing ACP stub (`tests/_stub_acp_agent.py`) — no real harness binary, no LLM, no network. |
+| `tests/acceptance/uat/test_plan_journeys.py` | The three study-plan doors as required sign-off cells under the strict runner, against one hermetic world shared by every process: `architect_launch` (the real Plans view's **Plan with architect** in a real browser → one planning-purpose start → the labelled console, the label surviving a reload, the brief's structure in the persona the stub agent received, no plan created), `mcp_lifecycle` (the real `studyloop-mcp` server over stdio, the nine tools listed, create → activate → record a checkpoint → set a milestone → history, then the same plan read back through the web server) and `now_with_active_plan` (the Today card's "Advances plan" line and `/api/now`'s `plan_refs` naming the plan). Writes the full bundle to the durable root plus a redacted summary; grades no rubric (a stub agent holds no conversation) and says so in its arbitration note. |

@@ -552,3 +553,7 @@ round can land test-first. Named here, not silently absent:
   pieces above compose; it is not a sign-off run, grades no rubric, and
-  uses a scripted stub mentor rather than a real coding harness.
+  uses a scripted stub mentor rather than a real coding harness. The
+  study-plan journeys in `test_plan_journeys.py` are a real strict
+  sign-off over three cells, but with the same stub agent: they prove the
+  product surfaces (browser, stdio MCP, the now engine) and the shared
+  store, not an architect's interview.
 - **Council grading** (each seat receiving a bundle summary + rubric and
diff --git a/docs/cli-reference.md b/docs/cli-reference.md
index 55fdf2bf..a0494ba9 100644
--- a/docs/cli-reference.md
+++ b/docs/cli-reference.md
@@ -259,2 +259,4 @@ Default ranking is due review first, then struggling or low teach-back score, th

+With an active study plan the same engine is plan-aware (see [Study Plans](study-plans.md#plan-aware-now)): plan-related work gets a bounded bias within its urgency class, an eligible next milestone is suggested when no gathered candidate represents it, and a milestone above your current energy is deferred with a reason. The panel names the plan and milestone an action advances; `--json` gains `active_plans`, `energy_deferred`, `completion_actions` and per-action `plan_refs` only when a plan is active, so the no-plan output is unchanged.
+
 `studyloop chat-note` turns one markdown/text note into a compact Socratic context pack. V1 prints or speaks the mentor prompt; it does not run a separate chat backend.
diff --git a/docs/index.md b/docs/index.md
index f917cfcc..8db3f344 100644
--- a/docs/index.md
+++ b/docs/index.md
@@ -57,4 +57,6 @@ the local server, and cloud-backed agents still need their provider.
   service worker.
-- Create study plans through the current Web UI form or CLI. An agent-led
-  planning interview is not integrated into the Web UI yet.
+- Create study plans through the Web UI form, the CLI, or the agent-led
+  architect interview (**Plan with architect** in the Web UI, `studyloop plan
+  architect` at a shell, or the plan tools over MCP). A live study session is
+  not bound to a plan.
 - Use the CLI for practice-task generation and verification.
diff --git a/docs/roadmap.md b/docs/roadmap.md
index b742690f..6db9f4db 100644
--- a/docs/roadmap.md
+++ b/docs/roadmap.md
@@ -41,5 +41,8 @@ The next product improvements are:
 - a simpler installation and upgrade path than a source checkout;
-- a guided planning conversation that turns a learner's own words into a useful
-  plan without silently inventing goals or evidence;
-- stronger continuity between active plans, Today, review, and the next session;
+- continuity from an active plan into the *next session*: the plan already
+  biases `studyloop now` and Today with tested ranking rules and the architect
+  interview runs from the CLI, the Web UI and over MCP, but a live study
+  session is still not bound to a plan and checkpoints and milestones are
+  never inferred from session events (see the Study Plans guide, "Deliberately
+  not automatic");
 - clearer in-product explanations when an agent, voice backend, or optional
diff --git a/docs/web-ui-guide.md b/docs/web-ui-guide.md
index b90327d2..1fce8ea2 100644
--- a/docs/web-ui-guide.md
+++ b/docs/web-ui-guide.md
@@ -64,3 +64,8 @@ one or move to Study Session directly.

-Active study plans do not yet influence this recommendation.
+An active study plan biases this recommendation — plan-aware guidance with
+tested ranking rules, not a filter: the card names the plan and milestone an
+action advances, a milestone above your current energy is shown as deferred
+with a reason, and an overdue review or fresh struggle can still outrank new
+milestone work. With no active plan the card is unchanged. See
+[Study Plans](study-plans.md#plan-aware-now).

@@ -82,6 +87,8 @@ The Study Plans view lists plan status and milestone progress, opens the Markdow
 plan as a readable document, and lets you preview or record checkpoints. **New
-plan** begins with a free-text description, followed by manual structured fields.
-
-The current Web UI does not send that brain dump to an agent for decomposition.
-See [Study Plans](study-plans.md) for the full, current workflow.
+plan** begins with a free-text description, followed by manual structured fields;
+the form does not send that brain dump to an agent for decomposition.
+**Plan with architect**, beside it, starts the study-plan-architect interview
+as a *planning* session in the Study Session console (labelled as such, and
+the label survives a reload); the click itself creates no plan. See
+[Study Plans](study-plans.md) for the full, current workflow.
```
### `agents/mcp/README.md` — diff vs `1e1a5680`

```diff
diff --git a/agents/mcp/README.md b/agents/mcp/README.md
index 0678a233..ba5bdd7f 100644
--- a/agents/mcp/README.md
+++ b/agents/mcp/README.md
@@ -153,3 +153,9 @@ Requires a Google Cloud project with Calendar API enabled. See [setup guide](htt

-The `studyloop-mcp` server exposes 10 MCP tools for courses, backlog, and progress tracking. It's registered as a Python entry point and runs via stdio.
+The `studyloop-mcp` server exposes 32 MCP tools: courses and review cards, the study backlog and
+progress signals, lesson browsing, the live session, the `now` recommendation, and the learner's
+study plans (nine lifecycle tools plus `record_plan_learning`, every one through the same plan
+application layer the CLI and Web UI use — see `docs/agent-install.md`, "Study-plan tools over
+MCP", for the refusal kinds and the readiness gate). It's registered as a Python entry point and runs
+via stdio. The table below is pinned to the production registry by
+`tests/test_docs_plan_integration_contract.py`.

@@ -183,2 +189,4 @@ server NAME is `studyloop`; `studyloop-mcp` is the console-script COMMAND, never
 | `record_study_progress` | Record a card review result |
+| `get_due_cards` | Cards due for spaced-repetition review, one course or all |
+| `log_review_outcome` | Record the outcome of reviewing one card (with response time) |
 | `get_study_backlog` | List pending backlog topics |
@@ -187,6 +195,22 @@ server NAME is `studyloop`; `studyloop-mcp` is the console-script COMMAND, never
 | `record_topic_progress` | Update priority or resolve a backlog topic |
-| `get_concept_context` | Concept dependency edges for a topic, with per-edge provenance and `coverage` — the prerequisite structure a mentor sequences from |
-| `get_next_action` | The same "what now?" recommendation the web `/api/now` endpoint gives |
 | `get_active_topics` | The AuDHD three-topic active set vs the remaining backlog |
 | `log_topic` | Record a learning / struggling / insight signal mid-session |
+| `log_struggle` | Record a topic the learner struggled with, for later study |
+| `get_concept_context` | Concept dependency edges for a topic, with per-edge provenance and `coverage` — the prerequisite structure a mentor sequences from |
+| `get_next_action` | The same "what now?" recommendation the web `/api/now` endpoint gives — plan-aware when a plan is active |
+| `get_lesson_tree` | Browse the course-material tree: providers → courses → lessons |
+| `read_lesson` | The raw Markdown of one lesson |
+| `search_lessons` | Full-text search over lesson bodies |
+| `list_session_options` | The selectable study targets the web start picker offers |
+| `end_session` | End the currently-active study session (idempotent) |
+| `list_study_plans` | Study-plan summaries, active first; filter to one status |
+| `get_study_plan` | One plan in full — mission, milestones, records, readiness; optional Markdown and checkpoint history |
+| `get_planning_interview` | The interview questions, an evidence seed and the existing plans — the architect's brief |
+| `create_study_plan` | Draft a plan from interview answers; a taken id is a conflict, never a replacement |
+| `update_study_plan` | Revise fields, topics, milestones and status as one document, saved once |
+| `set_study_plan_status` | Move a plan between `draft`, `active`, `paused`, `complete`, `abandoned`; activation is readiness-gated |
+| `set_study_plan_milestone` | Set one milestone done or not done — set, not toggle, so a retry is safe |
+| `evaluate_study_plan` | A `start`/`mid`/`end` checkpoint against real evidence; preview by default, `record=true` reports each write |
+| `delete_study_plan` | Delete the plan document — refused unless `confirmed=true`; checkpoint history is kept |
+| `record_plan_learning` | Append a learning record to a plan — the wind-down's first write |
```
## 3. The code the docs are pinned to

### `packages/studyloop/src/studyloop/mcp/inventory.py` (new)

```python
"""Names of the study-plan tools the ``studyloop`` MCP server registers.

One tuple, importable without the ``mcp`` SDK (the ``studyloop[mcp]`` extra is
optional; the installer that prints these names runs without it), so the
public documentation, the installer's printed text and the persona can all be
pinned to the same list. ``tests/test_docs_plan_integration_contract.py``
grounds this tuple in the production ``FastMCP`` registry: it must name
exactly the registered tools whose name says *plan*, so a tool added to or
removed from ``studyloop.mcp.tools`` fails a test rather than leaving a stale
sentence in ``docs/agent-install.md``.
"""

from __future__ import annotations

from typing import Final

#: The nine plan lifecycle tools of design §4 (D-8, D-9), in lifecycle order:
#: discover → inspect → interview → create → revise → lifecycle → milestone →
#: evaluate → delete. Issues #11 (the first six) and #12 (the last three).
PLAN_TOOL_NAMES: Final[tuple[str, ...]] = (
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
    "set_study_plan_milestone",
    "evaluate_study_plan",
    "delete_study_plan",
)

#: The plan-write tool that pre-dates the nine: appends a learning record to a
#: plan — the wind-down's first write (ADR-0010). Documented beside the nine,
#: not counted among them.
LEARNING_RECORD_TOOL: Final = "record_plan_learning"

__all__ = ["LEARNING_RECORD_TOOL", "PLAN_TOOL_NAMES"]
```
### `packages/studyloop/src/studyloop/planning/boundaries.py` (new)

```python
"""What the plan integration deliberately does not automate.

Issue #7 drew this line on purpose ("Out of Scope"; the plan-application-seam
proposal's "Non-goals"): an active plan biases the ``now`` recommendation and
gives agents lifecycle tools, but it never runs the session. Each entry below
is the lead phrase of one bullet in ``docs/study-plans.md``'s "Deliberately
not automatic" list and one clause of the installer's boundary sentence;
``tests/test_docs_plan_integration_contract.py`` pins both to this tuple so
the public statement cannot claim more — or less — automation than the
product has without this constant moving with it.

The phrases are deliberately verbs: each names something StudyLoop does
**not** do, in the words the learner-facing doc uses.
"""

from __future__ import annotations

from typing import Final

#: Ordered as the doc lists them: the live-session boundary first (the one
#: issue #7 calls out as a separate future feature), then the three
#: session-driven automations, then the two things a plan must never become.
NOT_AUTOMATIC: Final[tuple[str, ...]] = (
    "bind a live study session to a plan",
    "run checkpoints from session events",
    "complete milestones from study evidence",
    "enforce one active plan",
    "turn a plan into a filter",
    "structure the manual form's brain dump",
)

__all__ = ["NOT_AUTOMATIC"]
```
### `packages/studyloop/src/studyloop/cli/_install.py` — diff vs `1e1a5680` (the installer's printed text)

```diff
diff --git a/packages/studyloop/src/studyloop/cli/_install.py b/packages/studyloop/src/studyloop/cli/_install.py
index 73e17e47..41c582d9 100644
--- a/packages/studyloop/src/studyloop/cli/_install.py
+++ b/packages/studyloop/src/studyloop/cli/_install.py
@@ -16,2 +16,4 @@ from studyloop.installers import (
 )
+from studyloop.mcp.inventory import PLAN_TOOL_NAMES
+from studyloop.planning.boundaries import NOT_AUTOMATIC

@@ -81 +83,28 @@ def install_agents(repo_root: Path | None, tools: tuple[str, ...], uninstall: bo
         console.print(f"  {line}")
+    if not uninstall:
+        for line in _plan_capability_lines():
+            console.print(line)
+
+
+def _plan_capability_lines() -> list[str]:
+    """What the installed definitions can do with study plans — and what stays manual.
+
+    Built from the two constants the public docs are pinned to
+    (``studyloop.mcp.inventory.PLAN_TOOL_NAMES``,
+    ``studyloop.planning.boundaries.NOT_AUTOMATIC``), so this text cannot claim
+    a tool the server lacks or an automation the product does not have. Which
+    harness definitions attach the ``studyloop`` server is a per-harness fact
+    the doc section named here states; the installer does not restate it.
+    """
+    tools = ", ".join(PLAN_TOOL_NAMES)
+    *first, last = NOT_AUTOMATIC[:-1]
+    boundary = ", ".join(first) + f", or {last}"
+    return [
+        "",
+        f"[bold]Study plans:[/bold] the [cyan]studyloop[/cyan] MCP server exposes "
+        f"{len(PLAN_TOOL_NAMES)} plan tools ({tools}) to any agent process it is registered "
+        "with; the Web UI's [bold]Plan with architect[/bold] starts a planning-purpose session.",
+        f"  An active plan gives plan-aware guidance with tested ranking rules; "
+        f"it does not {boundary}.",
+        '  See docs/agent-install.md, "Study-plan tools over MCP".',
+    ]
```
Rendered (CliRunner, `install agents --tool kiro`, installer mocked):

```
Updated agent definitions.
  shared: 1
  kiro: 3

Study plans: the studyloop MCP server exposes 9 plan tools (list_study_plans, get_study_plan, get_planning_interview,
create_study_plan, update_study_plan, set_study_plan_status, set_study_plan_milestone, evaluate_study_plan,
delete_study_plan) to any agent process it is registered with; the Web UI's Plan with architect starts a
planning-purpose session.
  An active plan gives plan-aware guidance with tested ranking rules; it does not bind a live study session to a plan,
run checkpoints from session events, complete milestones from study evidence, enforce one active plan, or turn a plan
into a filter.
  See docs/agent-install.md, "Study-plan tools over MCP".
```
### `packages/studyloop/tests/test_docs_plan_integration_contract.py` (new, full)

```python
"""Docs↔code contract for the plan integration's public claims (#15, T6.1).

Issue #15's first acceptance criterion is that "Study Plans, Now, Today, Web,
MCP, and installer language describe the implemented automatic boundaries
accurately". Prose cannot be proven accurate by reading it once — it drifts
the next time a tool is added or a boundary moves — so, like
``test_docs_harness_contract.py`` does for the six-harness scope, every claim
here is pinned to a code-side source of truth and compared as a SET or an
ordered tuple, never as a copied sentence:

* the nine plan tools + ``record_plan_learning`` — the constant
  :data:`studyloop.mcp.inventory.PLAN_TOOL_NAMES` (design §4, lifecycle order),
  itself grounded in the production ``FastMCP`` registry here so the constant
  can neither name a tool the server lacks nor omit one it has;
* the full ``studyloop-mcp`` inventory in ``agents/mcp/README.md`` — the
  registry, exactly (a stale "10 MCP tools" was found during T6.1);
* the learner-facing "Deliberately not automatic" list in
  ``docs/study-plans.md`` — :data:`studyloop.planning.boundaries.NOT_AUTOMATIC`,
  the one place issue #7's out-of-scope line is written down in code;
* the installer's printed text — the same two constants, so what
  ``studyloop install agents`` says matches what the docs say;
* the release language — D-16's bounded phrasing ("plan-aware guidance with
  tested ranking rules", never "better learning").
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from studyloop.mcp.inventory import LEARNING_RECORD_TOOL, PLAN_TOOL_NAMES
from studyloop.planning.boundaries import NOT_AUTOMATIC

REPO_ROOT = Path(__file__).resolve().parents[3]

_TABLE_TOOL_ROW = re.compile(r"^\|\s*`([a-z_]+)(?:\(|`)", re.MULTILINE)
_BULLET_LEAD = re.compile(r"^- \*\*(.+?)\*\*")


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body of the ``## <heading>`` section, up to the next ``## `` heading.

    Level-two headings only: a ``### `` inside the section belongs to it.
    """
    match = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"no '## {heading}' section found"
    return match.group(1)


def _prose(text: str) -> str:
    """Markdown soft-wraps lines, so a phrase can straddle a newline where a
    space belongs; collapse whitespace before any phrase-membership check."""
    return re.sub(r"\s+", " ", text)


def _table_tool_names(section: str) -> list[str]:
    """Tool names in a section's table, first column, in row order."""
    return _TABLE_TOOL_ROW.findall(section)


def _registry() -> set[str]:
    from studyloop.mcp.server import mcp

    return set(mcp._tool_manager._tools)


# ---------------------------------------------------------------------------
# The plan-tool constant is grounded in the production registry
# ---------------------------------------------------------------------------


def test_plan_tool_constant_is_exactly_the_registry_plan_tools() -> None:
    """The constant the docs and installer are pinned to must itself be true of
    the server: the nine design-§4 names plus ``record_plan_learning`` are
    exactly the registered tools whose name says ``plan`` — no invented tool,
    no unregistered tool, no registered plan tool the constant forgets."""
    registered = _registry()
    plan_named = {name for name in registered if "plan" in name}
    assert plan_named == set(PLAN_TOOL_NAMES) | {LEARNING_RECORD_TOOL}
    assert len(PLAN_TOOL_NAMES) == 9
    assert len(set(PLAN_TOOL_NAMES)) == len(PLAN_TOOL_NAMES), "duplicate names in the constant"
    assert LEARNING_RECORD_TOOL not in PLAN_TOOL_NAMES


# ---------------------------------------------------------------------------
# docs/agent-install.md
# ---------------------------------------------------------------------------


def test_agent_install_doc_table_is_the_nine_then_record_plan_learning() -> None:
    """The "Study-plan tools over MCP" table names every plan tool, in the
    constant's lifecycle order, with ``record_plan_learning`` last — and
    nothing else."""
    section = _section(_read("docs/agent-install.md"), "Study-plan tools over MCP")
    assert _table_tool_names(section) == [*PLAN_TOOL_NAMES, LEARNING_RECORD_TOOL]


def test_agent_install_doc_names_the_planning_purpose_and_no_stale_phase_reference() -> None:
    """The install doc names the Web door (``purpose=planning``) and states the
    Kiro/Claude harness boundary as an owner decision, not as "tracked as
    Phase 6, T6.1" — T6.1 is the phase that closes here."""
    text = _read("docs/agent-install.md")
    section = _prose(_section(text, "Study-plan tools over MCP"))
    assert "purpose=planning" in section
    assert "study-plan-architect.json" in section and "study-plan-architect.md" in section
    assert "T6.1" not in text, "the install doc still points at the phase that just closed"
    assert "Phase 6" not in text


# ---------------------------------------------------------------------------
# agents/mcp/README.md — the capability matrix per-harness registration points at
# ---------------------------------------------------------------------------


def test_mcp_readme_lists_the_whole_production_inventory() -> None:
    registered = _registry()
    section = _section(_read("agents/mcp/README.md"), "studyloop-mcp (Session DB Tools)")
    listed = _table_tool_names(section)
    assert len(listed) == len(set(listed)), f"duplicate rows: {listed}"
    assert set(listed) == registered, (
        f"README table vs registry — missing {sorted(registered - set(listed))}, "
        f"stale {sorted(set(listed) - registered)}"
    )


def test_mcp_readme_states_the_registry_count() -> None:
    section = _section(_read("agents/mcp/README.md"), "studyloop-mcp (Session DB Tools)")
    match = re.search(r"exposes (\d+) MCP tools", section)
    assert match, "the README no longer states how many tools the server exposes"
    assert int(match.group(1)) == len(_registry())


# ---------------------------------------------------------------------------
# docs/study-plans.md
# ---------------------------------------------------------------------------


def test_study_plans_doc_boundary_list_is_the_constant_in_order() -> None:
    """Each bullet of "Deliberately not automatic" opens with a bold lead
    phrase; the tuple of lead phrases IS ``NOT_AUTOMATIC``. A boundary cannot
    be dropped from the doc, added to it, or reworded without the constant
    moving with it."""
    section = _section(_read("docs/study-plans.md"), "Deliberately not automatic")
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    leads = []
    for bullet in bullets:
        lead = _BULLET_LEAD.match(bullet)
        assert lead, f"bullet without a bold lead phrase: {bullet!r}"
        leads.append(lead.group(1))
    assert tuple(leads) == NOT_AUTOMATIC


def test_not_automatic_constant_is_well_formed() -> None:
    assert len(NOT_AUTOMATIC) >= 4, "issue #7 names at least four automatic boundaries"
    assert len(set(NOT_AUTOMATIC)) == len(NOT_AUTOMATIC)
    for phrase in NOT_AUTOMATIC:
        assert phrase == phrase.strip() and phrase and phrase[0].islower(), phrase


def test_study_plans_doc_has_no_stale_gap_claims() -> None:
    """The pre-#15 "What a plan does not do yet" list said broader plan
    management "remains CLI-only" and cited ``mcp/tools.py:129``; both are
    false now and neither may come back."""
    text = _read("docs/study-plans.md")
    assert "What a plan does not do yet" not in text
    assert "CLI-only" not in text
    assert not re.search(r"mcp/tools\.py:\d+", text), "a line-number citation goes stale"


def test_study_plans_doc_uses_the_bounded_release_language() -> None:
    """D-16: ranking tests prove ranking compliance, not learning. The doc
    says "plan-aware guidance with tested ranking rules" and never promises
    "better learning"."""
    text = _prose(_read("docs/study-plans.md"))
    assert "plan-aware guidance with tested ranking rules" in text
    assert "better learning" not in text.lower()
    assert "learn faster" not in text.lower()


def test_study_plans_doc_plan_aware_now_section_names_every_consumer() -> None:
    """The four surfaces that consume the one recommendation result (#10)."""
    section = _prose(_section(_read("docs/study-plans.md"), "Plan-aware now"))
    for surface in ("studyloop now", "Today", "recap", "get_next_action"):
        assert surface in section, f"'Plan-aware now' does not name {surface!r}"


# ---------------------------------------------------------------------------
# The other public pages that described the pre-#7 gap
# ---------------------------------------------------------------------------

#: Public pages found during T6.1 still saying the gap #7 closed was open.
_PUBLIC_PLAN_PAGES = (
    "README.md",
    "docs/index.md",
    "docs/web-ui-guide.md",
    "docs/study-plans.md",
    "docs/cli-reference.md",
    "docs/roadmap.md",
)

#: Each pattern is a claim that was true before the change and is false now.
_STALE_GAP_CLAIMS = (
    r"planning interview is not integrated",
    r"do not yet influence",
    r"does not (?:yet )?(?:bias|influence|change) .{0,40}(?:now|Today|recommendation)",
    r"remains CLI-only",
    r"not available yet",
)


@pytest.mark.parametrize("rel_path", _PUBLIC_PLAN_PAGES)
def test_public_pages_no_longer_describe_the_closed_gap(rel_path: str) -> None:
    text = _prose(_read(rel_path))
    offenders = [
        pattern for pattern in _STALE_GAP_CLAIMS if re.search(pattern, text, re.IGNORECASE)
    ]
    assert not offenders, f"{rel_path} still carries a pre-#7 gap claim: {offenders}"


def test_web_ui_guide_today_and_plans_sections_state_the_shipped_behaviour() -> None:
    guide = _read("docs/web-ui-guide.md")
    today = _prose(_section(guide, "Today"))
    assert "plan-aware guidance with tested ranking rules" in today
    plans = _prose(_section(guide, "Study Plans"))
    assert "Plan with architect" in plans
    assert "creates no plan" in plans


# ---------------------------------------------------------------------------
# The installer's printed text
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _invoke_install_agents(runner: CliRunner, tmp_path: Path, *extra: str) -> str:
    from studyloop.cli import cli

    with (
        patch("studyloop.cli._install.require_repo_root", return_value=tmp_path),
        patch(
            "studyloop.cli._install.install_agent_definitions",
            return_value={"shared": 1, "kiro": 1},
        ),
    ):
        result = runner.invoke(
            cli, ["install", "agents", "--repo-root", str(tmp_path), "--tool", "kiro", *extra]
        )
    assert result.exit_code == 0, result.output
    return result.output


def test_installer_output_names_the_nine_tools_and_the_planning_purpose(
    runner: CliRunner, tmp_path: Path
) -> None:
    output = _invoke_install_agents(runner, tmp_path)
    for name in PLAN_TOOL_NAMES:
        assert name in output, f"installer output does not name {name}"
    assert "planning" in output
    assert "docs/agent-install.md" in output


def test_installer_output_states_the_boundary_with_the_constant(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The installer's boundary sentence is built from ``NOT_AUTOMATIC``, so
    it cannot claim more automation than the docs do (issue #7, Further
    Notes: stale installer language claiming an active plan already changes
    Now had to be corrected — the fix is to derive it)."""
    output = _invoke_install_agents(runner, tmp_path)
    for phrase in NOT_AUTOMATIC[:4]:
        assert phrase in output, f"installer output does not state the boundary {phrase!r}"


def test_uninstall_output_makes_no_capability_claims(runner: CliRunner, tmp_path: Path) -> None:
    output = _invoke_install_agents(runner, tmp_path, "--uninstall")
    assert "Removed agent definitions" in output
    for name in PLAN_TOOL_NAMES:
        assert name not in output
```
### `packages/studyloop/tests/test_plan_architect_persona.py` — the one changed pin (diff)

```diff
diff --git a/packages/studyloop/tests/test_plan_architect_persona.py b/packages/studyloop/tests/test_plan_architect_persona.py
index 4d08c233..34e086dc 100644
--- a/packages/studyloop/tests/test_plan_architect_persona.py
+++ b/packages/studyloop/tests/test_plan_architect_persona.py
@@ -392,2 +392,6 @@ def test_install_docs_disclose_architect_fallback_limits() -> None:
     assert "kiro" in lowered and "claude" in lowered, "the harness boundary is not disclosed"
-    assert "t6.1" in lowered, "the owner item is not named"
+    # Review 4 pinned the owner item as "T6.1"; T6.1 closed the phase without
+    # taking the permission decision, so the doc now names where it is recorded
+    # instead of the phase that has passed (test_docs_plan_integration_contract
+    # forbids the stale phase reference).
+    assert "open item" in lowered and "close-out" in lowered, "the owner item is not named"
```
## 4. The six delta specs `openspec archive` will merge into the normative specs (ADDED requirements only; full text)

### `openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md` → `openspec/specs/active-learning-decisions/spec.md`

Existing requirements in the main spec (names only): `The decision engine produces a ranked plan from multiple candidate sources`; `Energy and modality reshape candidate scoring`; `The CLI exposes the plan with energy, time, modality, interleave, speak, and json flags`; `chat-note builds a Socratic context pack scoped to allowed study roots`; `practice verify records attempts and updates study progress`; `recap today synthesises a four-field daily summary with optional voice and audio export`; `mastery graph renders concept dependencies as Mermaid or JSON`; `weak-links surfaces struggling prerequisites that block downstream concepts`; `Voice output is optional and never blocks the learning workflow`

```markdown
## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
The study-plan domain SHALL expose one application seam,
`studyloop.planning.PlanApplication`, and it SHALL be the only writer any
adapter (Web routes, CLI commands, MCP tools) uses for study plans. `apply`
SHALL evaluate readiness whenever the *resulting* document would be `active` —
create with `status="active"` (`CreatePlan`), import of a document whose
frontmatter says `active` (`ImportDocument`), replacement of an existing
document with one whose frontmatter says `active` (`ReplaceDocument`), and a
lifecycle transition to `active` (`TransitionLifecycle`) — and SHALL raise
`PlanNotReady` carrying a `ReadinessView` **before any canonical write** when
the plan has no mission `why`, no success criteria, or no milestones. Readiness
SHALL be computed by exactly one function (`authoring.readiness`), reached only
through the seam; no adapter SHALL carry a readiness check of its own.

The seam's read side (`browse`, `inspect`, `prepare_planning`) SHALL return
frozen, tuple-only views whose `to_json_dict()` returns a fresh container on
every call and serialises `PlanSummary` and `ReadinessView` to exactly the
`StudyPlan.summary()` and `authoring.readiness()` key sets. Domain failures
SHALL be exceptions with no CLI, HTTP or MCP vocabulary: `PlanNotFound`,
`InvalidPlanId`, `PlanConflict`, `InvalidField`, `PlanNotReady`,
`InvalidMilestone`.

#### Scenario: Create with status active on an unready plan
- **WHEN** `apply(CreatePlan(title="Vague", answers={}, status="active"))` is
  called
- **THEN** `PlanNotReady` is raised, its `readiness.ready` is `false` with a
  non-empty `blockers` tuple, and no document exists afterwards

#### Scenario: Whole-document replacement whose frontmatter says active
- **WHEN** `apply(ReplaceDocument(plan_id, markdown))` is called with a
  document whose frontmatter says `active` and which has no milestones
- **THEN** `PlanNotReady` is raised and the stored document is byte-identical
  to what it was before the call

#### Scenario: Status transition to active on an unready plan
- **WHEN** `apply(TransitionLifecycle(plan_id, "active"))` is called for a
  draft whose readiness reports blockers
- **THEN** `PlanNotReady` is raised and `inspect(plan_id).summary.status` is
  still `draft`

#### Scenario: Every door raises the same refusal
- **WHEN** the same unready document is refused via `CreatePlan`,
  `TransitionLifecycle`, `ReplaceDocument` and `ImportDocument`
- **THEN** the four `ReadinessView` payloads are equal apart from `plan_id`,
  and `str(exc)` is `plan is not ready to activate` for each

#### Scenario: Replacement keeps identity
- **WHEN** `apply(ReplaceDocument(plan_id, markdown))` is called with a
  document whose frontmatter names a different `id` and `created`
- **THEN** the persisted plan keeps the original `plan_id` and `created`, the
  content edits are applied, and no second document appears

#### Scenario: Several ready plans may be active
- **WHEN** two ready plans are created with `status="active"` and a third
  ready plan is transitioned to `active`
- **THEN** all three succeed and `browse(status="active")` returns all three

#### Scenario: Duplicate id without overwrite
- **WHEN** `apply(CreatePlan(..., plan_id="demo"))` is called and `demo`
  already exists with `overwrite=False`
- **THEN** `PlanConflict` is raised and the existing plan is unchanged; with
  `overwrite=True` the plan is replaced

#### Scenario: Browse order is the store's and is deterministic
- **WHEN** `browse()` is called over active and draft plans
- **THEN** active plans come first, then ascending `updated`, ties broken by
  plan id, and repeated calls return equal tuples

### Requirement: Partial checkpoint recording is reported, never silent
`evaluate_and_record` SHALL treat a `False` return from
`index.record_checkpoint` exactly as it treats a raised failure: by appending
`checkpoint not saved to the database` to the evaluation's `warnings`. The
index's swallow-and-return-`False` remains its best-effort policy; the caller
SHALL honour the answer. A successful database write SHALL add no warning.

#### Scenario: Database write reports failure by returning False
- **WHEN** `record_checkpoint` returns `False` during `evaluate_and_record`
- **THEN** the returned evaluation's `warnings` contains an entry mentioning
  `database`, and the evaluation is still returned with a valid verdict

#### Scenario: Database write succeeds
- **WHEN** `record_checkpoint` returns `True`
- **THEN** no warning mentioning `database` is present


### Requirement: Milestone set is idempotent and refuses indices the plan lacks
`apply(SetMilestone(plan_id, index, done))` SHALL set — not toggle — one
milestone's `done` state on a loaded candidate, judge the resulting document
with the same readiness gate every write uses when the plan is active, and
save once when the state changed. Applying the same intent twice SHALL leave
the same document *byte for byte*: a retry that asks for the state the
milestone already has writes nothing and leaves `updated` untouched (the
gate still runs first).
`index` is a 0-based position: an index past the end **or negative** SHALL
raise `InvalidMilestone` before any write. A plan that does not exist SHALL
raise `PlanNotFound` before the index is judged.

#### Scenario: Set is idempotent
- **WHEN** `SetMilestone(plan_id, 0, done=True)` is applied twice
- **THEN** the first application saves exactly once and the second saves
  nothing (document bytes and `updated` unchanged), the milestone is done
  after both, and `SetMilestone(plan_id, 0, done=False)` undoes it

#### Scenario: Negative index
- **WHEN** `SetMilestone(plan_id, -1, done=True)` is applied
- **THEN** `InvalidMilestone` is raised and the document is byte-identical

#### Scenario: Ticking a milestone on an unready active document
- **WHEN** `SetMilestone` is applied to a hand-edited active plan that has no
  mission
- **THEN** `PlanNotReady` is raised — the resulting document would be
  active-but-unready — and nothing is written

### Requirement: Deletion is confirmed and retains the checkpoint log
`apply(DeletePlan(plan_id, confirmed))` SHALL raise `InvalidField` unless
`confirmed` is `True` (after `PlanNotFound` for an unknown id), remove the
canonical document and its derived index row, retain every row of the durable
checkpoint log for that id, and return a frozen `DeleteResult(plan_id)` whose
`to_json_dict()` is `{"deleted": true, "plan_id": "<id>"}` — `apply` returns a
`DeleteResult` for this intent and a `PlanDetail` for every other, because a
detail cannot describe a plan that no longer exists.

#### Scenario: Unconfirmed delete
- **WHEN** `DeletePlan(plan_id)` is applied with `confirmed` left `False`
- **THEN** `InvalidField` is raised and the document is unchanged

#### Scenario: Confirmed delete keeps history
- **WHEN** a plan with one recorded checkpoint is deleted with `confirmed=True`
- **THEN** a `DeleteResult` is returned, `inspect(plan_id)` raises
  `PlanNotFound`, the derived index no longer lists the plan, and
  `checkpoint_history(plan_id)` still returns the row

### Requirement: Assessment reports each recording sink independently
`assess(AssessPlan(plan_id, phase, study_id, record, append_to_plan))` SHALL
return a frozen `AssessmentResult` carrying a `PlanEvaluationView` (whose
`to_json_dict()` equals `PlanEvaluation.to_dict()` key for key and whose
`markdown` is the rendered checkpoint block), `db_write` and `document_write`
each in `not_requested | saved | failed`, and the evaluation's `warnings`.
`record=False` SHALL call `evaluate_plan` and write to neither sink;
`record=True` SHALL call the Phase-0 `evaluate_and_record` — the seam adds no
second checkpoint writer — and read its two recording warnings back into the
sink fields. A failed sink SHALL be a reported outcome on the result, never an
exception (no `PartialRecording`), because the evaluation succeeded.
`recording_complete` is `True` when no requested sink failed — vacuously true
for a preview. The plan SHALL be found before the phase is judged (`PlanNotFound`
before `InvalidField`). Because appending the checkpoint re-saves the plan
document, `record=True, append_to_plan=True` on an *active* plan SHALL run the
same readiness gate every other write runs — before either sink is touched —
and raise `PlanNotReady` (with `already_active=True`) for an active-but-unready
document; a preview or a database-only recording persists no document and is
not gated.

#### Scenario: Preview writes neither sink
- **WHEN** `assess(AssessPlan(id, "mid", record=False))` is called
- **THEN** both sink fields are `not_requested`, no checkpoint row exists in
  the log or the document, and `recording_complete` is `True`

#### Scenario: Both sinks saved
- **WHEN** `assess(AssessPlan(id, "end", study_id="s1"))` is called and both
  writes succeed
- **THEN** both sink fields are `saved`, `recording_complete` is `True`, and
  the row is present in the log (with `study_id == "s1"`) and in the document

#### Scenario: Database failure reported, document still written
- **WHEN** the log write returns `False` or raises
- **THEN** `db_write == "failed"`, `document_write == "saved"`,
  `recording_complete` is `False`, `warnings` contains `checkpoint not saved
  to the database`, and the evaluation carries a valid verdict

#### Scenario: Recording onto an unready active document is refused first
- **WHEN** `assess(AssessPlan(id, "start"))` is called for a hand-edited active
  plan with no mission
- **THEN** `PlanNotReady` is raised before the checkpoint log is written, the
  document is byte-identical, and the same call with `record=False` or
  `append_to_plan=False` succeeds

#### Scenario: Document failure reported independently
- **WHEN** the document save raises
- **THEN** `document_write == "failed"`, `db_write == "saved"`, the log holds
  the row, and the document is unchanged

### Requirement: Active-plan guidance is a deterministic read
`get_active_guidance(*, today=None)` SHALL return a frozen `ActiveGuidance`
holding one `ActivePlanGuidance` per plan whose status is `active`, ordered by
`plan_id`, with: the `PlanSummary`; the plan's `ReadinessView` (`readiness`) —
the same view every write is judged by, so an active-but-unready document (a
hand edit or pre-gate import with no mission) is still listed but its entry
says that every `SetMilestone`, `RevisePlan` or recorded assessment on it will
be `PlanNotReady` until it is paused or repaired, with no second `inspect` per
plan; `next_milestone` (the first unchecked
milestone, or `None`); `match_keys`, a sorted, de-duplicated `tuple` of
`normalise_match_key`
over the topics and every milestone's concepts (casefold, punctuation replaced
by spaces, whitespace collapsed — matching is equality on the key, never a
substring test; a tuple, not a `frozenset`, because D-3 binds every view to
tuples and a consumer that wants a set builds one); `target_urgency` in `overdue` (days until target `< 0`),
`soon` (`0..7`), `later` (`> 7`) or `undated`; `energy_floor`; a
`completion_action` string only when the plan has milestones and every one is
done; and per-plan `warnings` for defects worked around (no milestones, a
target date that is not a date). Every document SHALL be enumerated by its
storage id and loaded through the identity-pinning seam path, so an entry's
id is the file's, never an untrusted frontmatter `id`; documents that cannot
be read or parsed SHALL be named in the collection's `warnings`, in id order.
Non-active plans are skipped. `today`
pins the urgency computation and the nested summary's `days_until_target` —
one effective date for the whole payload — for frozen-clock callers and
defaults to the UTC
date.

This view is the one plan-static read the `now` decision engine consumes
(issue #10, next requirement).

#### Scenario: One entry per active plan, ordered, others skipped
- **WHEN** plans `zeta` (active), `alpha` (active), `mid` (active) and one
  plan in each of `draft`, `paused`, `complete`, `abandoned` exist
- **THEN** `get_active_guidance().plans` has three entries in the order
  `alpha`, `mid`, `zeta`, and repeated calls return equal views

#### Scenario: Match keys and next milestone
- **WHEN** an active plan has topics `["SQL", "Data-Engineering"]` and
  milestones with concepts `["Window-Function"]` (done) and `["RANK vs
  DENSE_RANK", "dense rank"]`, `["window frame"]`
- **THEN** `match_keys == ("data engineering", "dense rank", "rank vs dense
  rank", "sql", "window frame", "window function")` — sorted, de-duplicated —
  and `next_milestone` is index `1`

#### Scenario: Urgency buckets
- **WHEN** the target date is 30 or 1 day(s) ago, today, 1, 7, 8 or 90 days
  ahead, or unset
- **THEN** `target_urgency` is `overdue`, `overdue`, `soon`, `soon`, `soon`,
  `later`, `later`, `undated` respectively

#### Scenario: Every milestone done
- **WHEN** an active plan's milestones are all `done`
- **THEN** `next_milestone` is `None` and `completion_action` is a non-empty
  string naming the plan

#### Scenario: Malformed documents become warnings
- **WHEN** an active plan has no milestones and `target_date: someday`, and an
  unreadable file sits beside it
- **THEN** the guidance is returned; the plan's entry has `next_milestone ==
  None`, `completion_action == None`, `target_urgency == "undated"` and
  warnings naming the milestones and the date; the collection's `warnings`
  name the unreadable file

#### Scenario: Identity is the file, not the frontmatter
- **WHEN** `alpha.md` carries frontmatter `id: beta` beside a real `beta.md`,
  and two unreadable files sit beside a healthy plan
- **THEN** the entries are `alpha`, `beta` (and `healthy`) with unique ids and
  their own titles — never two `beta` entries; `readiness.plan_id` matches
  the entry id; the collection's `warnings` name exactly the unreadable files
  in id order and never the readable mismatched one; `inspect(<entry id>)`
  resolves to the same document

#### Scenario: An unready active plan is listed with its blockers
- **WHEN** an active document has topics and milestones but no mission `why`
  and no success criteria, beside a ready active plan
- **THEN** both appear in `.plans`; the husk's `readiness.ready` is `false`
  and its `readiness.blockers` name the missing why and success criteria; the
  ready plan's `readiness.ready` is `true`; `load_plan` ran once per document;
  and `to_json_dict()` carries the `readiness` block per entry

### Requirement: The now engine is plan-aware with tested ranking rules
`studyloop.learning.decision.build_now_plan` SHALL remain the only ranker of
study actions and SHALL consume active plans through exactly one call to
`PlanApplication().get_active_guidance(today=…)`, where `today` is the date
of the same instant `generated_at` records. It SHALL apply these rules, in
this order (design §3, D-5):

1. Candidates are collected as before; a failure to read plans at all SHALL
   degrade to a `warnings` entry, never a failed recommendation, and SHALL be
   logged with its traceback on `studyloop.learning.decision` so a
   programming error cannot hide behind the learner-facing warning.
2. The energy capability is `low|medium|high → 3|6|10`. For an active plan
   whose `energy_floor` exceeds it, the next milestone SHALL be listed in
   `energy_deferred` and SHALL NOT become a candidate; plan-related due recall
   and struggle repair stay eligible and plan-related.
3. A candidate is plan-related when `normalise_match_key` of its concept,
   topic or course **equals** one of the plan's `match_keys`; no substring
   test. It names the plan's next milestone (`milestone_index`) only when the
   key equals one of that milestone's concepts **and** the plan is eligible —
   ready and within the energy capability; a topic or finished-milestone
   match, or any match on an energy-deferred or active-but-unready plan,
   carries `milestone_index = None` (plan-related repair), so a payload never
   names a milestone it also reports as deferred or that the seam would
   refuse to tick.
4. Scoring is today's scoring plus one bounded bias for plan-related
   candidates: within one urgency class plan-related beats unrelated, and a
   globally more-urgent unrelated candidate still wins — a bias, not a filter.
5. When no collected candidate represents an eligible (ready, energy-permitted)
   plan's next milestone, one `conversation` candidate SHALL be synthesised
   for it (source `study_plan:<plan_id>:<index>`, concept = the milestone's
   first concept or its title, topic = the plan's first topic), scored below
   every due and repair class. A learner with an active plan and no evidence
   is therefore sent to the plan, and `starter` is `false`.
6. After de-duplication every matching `PlanRef(plan_id, milestone_index)`
   SHALL be attached to each ranked action, ordered by target urgency
   (`overdue`, `soon`, `later`, `undated`) → most recent `updated` → `plan_id`,
   keeping the most specific milestone per plan.
7. When primary + alternates hold no plan-backed action and an eligible one
   whose estimate fits the requested time exists further down, it SHALL
   replace the last alternate only; the primary is never re-ranked by plans.
8. A fully-checked active plan SHALL appear in `completion_actions` and SHALL
   be neither matched nor synthesised. An active-but-unready plan SHALL be
   listed and matched (bias and a `milestone_index = None` reference) but
   never synthesised and never named as a milestone, with a warning naming
   its blockers.

`NowPlan` gains `active_plans` (ordered as rule 6), `energy_deferred`,
`completion_actions` and `warnings`; `LearningRecommendation` gains
`plan_refs: tuple[PlanRef, ...] = ()`. `to_json_dict()` SHALL omit each of
these when empty, so a learner with no active plan receives the pre-#10
payload **byte for byte** — pinned by `tests/golden/now_plan_no_active.json`,
captured before any of this shipped. Renderers (`studyloop now`, `GET
/api/now`, the Today card, the daily recap in its JSON, spoken and Rich-panel
forms) SHALL show plan relevance, energy deferral and the engine's warnings
from these fields, SHALL escape learner-authored text before any markup
(Rich or HTML), and SHALL NOT re-rank. Ranking tests prove
ranking compliance, not learner benefit (D-16); a five-scenario human rubric
receipt accompanies the change.

#### Scenario: No active plan is byte-identical to the golden
- **WHEN** no active plan exists (an empty plans directory, or only a draft)
  and `build_now_plan()` runs with a frozen clock in an empty world
- **THEN** the serialised `to_json_dict()` equals
  `tests/golden/now_plan_no_active.json` byte for byte, and no
  `active_plans`, `energy_deferred`, `completion_actions`, `warnings` or
  `plan_refs` key is present

#### Scenario: Matching due concept outranks unrelated of the same urgency
- **WHEN** an active plan's milestone names `window function` and two due
  items are two points apart, `decorators` (unrelated) ahead
- **THEN** `window function` is primary with `plan_refs == (PlanRef(plan, 0),)`
  and `decorators` is the first alternate with no refs

#### Scenario: A more-urgent unrelated item still wins
- **WHEN** the only collected candidate is an unrelated due item and the
  plan's next milestone is unrepresented
- **THEN** the due item is primary and the synthesised milestone
  (`study_plan:<id>:0`) is an alternate with a lower score

#### Scenario: Energy below the floor defers the milestone, keeps repair
- **WHEN** energy is `low` (3/10), the plan's `energy_floor` is 5, its next
  milestone is `Frames` and a struggle repair on a finished milestone's
  concept is collected
- **THEN** the repair is primary with `PlanRef(plan, None)`,
  `energy_deferred` names `(plan, 1, 5, 3)`, and no `study_plan:` candidate
  exists; at `medium` energy nothing is deferred and the milestone is
  synthesised

#### Scenario: A deferred milestone is never named by a reference
- **WHEN** energy is `low`, the plan's `energy_floor` is 5 and the only
  collected candidate's concept equals the next milestone's concept
- **THEN** the candidate is primary with `PlanRef(plan, None)` while
  `energy_deferred` names that milestone; at `medium` energy the same
  candidate carries `PlanRef(plan, 0)` and nothing is deferred

#### Scenario: An unready active plan is matched but never named
- **WHEN** an active plan has no mission and no success criteria (unready)
  and a collected candidate equals its next milestone's concept
- **THEN** the candidate is primary with `PlanRef(plan, None)`, no
  `study_plan:` candidate exists, the plan's `active_plans` entry has
  `ready == False` and `eligible == False`, and one warning names the plan,
  its blockers and "pause or repair"

#### Scenario: No substring matching
- **WHEN** a milestone titled `Window functions deep dive` has no concepts
  and candidates `window functions deep dive tutorial`, `window` and
  `joins`/`SQL` are collected
- **THEN** only `joins` is plan-related (`PlanRef(plan, None)` via the topic
  `sql`, casefolded); the other two carry no refs

#### Scenario: Every matching plan is referenced, in order
- **WHEN** six active plans (overdue, soon, later, three undated with
  distinct and tied `updated`) all name the primary's concept
- **THEN** `plan_refs` lists all six ordered overdue → soon → later → undated
  by latest `updated` then `plan_id`, and `active_plans` is in the same order

#### Scenario: A plan-backed action is preserved when energy allows
- **WHEN** four unrelated due items outrank everything and the plan's
  `energy_floor` is 5
- **THEN** at `medium` energy the synthesised milestone replaces the second
  alternate (the primary and first alternate are unchanged); at `low` energy
  the alternates are the unrelated items and `energy_deferred` names the
  milestone

#### Scenario: Fully-checked plan emits a completion action
- **WHEN** an active plan's every milestone is done and an unrelated due item
  is collected
- **THEN** `completion_actions` names the plan, the due item is primary with
  no refs, no `study_plan:` candidate exists, and the plan's `active_plans`
  entry has `next_milestone_index == None`

#### Scenario: Renderers show, never re-rank
- **WHEN** `studyloop now --energy low`, `GET /api/now?energy=low` and the
  daily recap run against the energy-deferral fixture
- **THEN** each names the primary the engine chose, the plan it advances, and
  the deferred milestone; with no plan the CLI panel prints no plan lines,
  `GET /api/now` equals the golden, and the recap's `plan_context` is absent
  from its JSON, its spoken text and the `recap today` panel

#### Scenario: Learner-authored text is data to every renderer
- **WHEN** an active plan's title, topic or milestone text contains Rich
  markup, HTML or shell punctuation (`Plan [/bold]`, `<script>…`, `"; rm -rf ~`)
- **THEN** `build_now_plan` ranks and serialises it unchanged and writes
  nothing to the document; `studyloop now` exits 0 and shows the text
  literally; the Today card renders it through `x-text`

### Requirement: Adapters reach study plans only through the seam
No module under `studyloop/cli`, `studyloop/web/routes` or `studyloop/mcp`
SHALL import `studyloop.planning.store`, `.index`, `.authoring` or
`.evaluation` (directly, relatively, as a whole-package handle, by wildcard
`from studyloop.planning import *`, by a literal string naming a forbidden
module or the whole package, by name through `from studyloop.planning import …`
for the names those modules contribute, or transitively through one of the
four allowed seam modules — `from studyloop.planning.application import
store`). `tests/test_architecture_plan_seam.py` SHALL enforce this by
parsing every adapter module, SHALL reject each planted bypass in a temp copy
of an adapter, and SHALL check its explicit name list against what
`studyloop.planning` actually re-exports from the four modules.

#### Scenario: Planted bypass is rejected
- **WHEN** `from studyloop.planning.store import save_plan`, `from
  studyloop.planning import *`, `importlib.import_module("studyloop.planning")`
  or `from studyloop.planning.application import store` is appended to a copy
  of `web/routes/plans.py` and the checker runs on the copy
- **THEN** the checker reports a violation for each; on the real tree it
  reports none

### Requirement: The learning-record rule has one copy
Learning-record validation (non-empty title; no H1–H3 lines in the body) and
idempotent numbering SHALL live in one function,
`studyloop.planning.store.append_learning_record(plan, title, body=, status=)`,
applied to an in-memory plan. The store's `record_learning` SHALL wrap it
(load → append → save only when created, so a duplicate leaves the file's
bytes untouched) and the seam's `RevisePlan(learning_record=…)` SHALL call it
on the revision candidate, translating its `ValueError` to `InvalidField`.
A revision whose only content is a learning record that already exists SHALL
write nothing (no save, bytes and `updated` untouched — the guarantee the
store's `record_learning` always gave); a duplicate record beside another
field change SHALL still be one save, and an empty revision remains the
Phase-1 "touch".

#### Scenario: The seam follows the store's rule
- **WHEN** `store.append_learning_record` is replaced by a function that
  raises `ValueError("the store said no")` and `RevisePlan(learning_record=…)`
  is applied
- **THEN** `InvalidField` carrying that message is raised and no record is
  added
```
### `openspec/changes/plan-application-seam/specs/agent-adapters/spec.md` → `openspec/specs/agent-adapters/spec.md`

Existing requirements in the main spec (names only): `Every adapter satisfies a six-member runtime-checkable protocol`; `The registry auto-discovers built-in adapters from sibling modules`; `Custom adapters from config override built-in adapters of the same name`; `Agent detection respects STUDYLOOP_AGENT env var and configured priority order`; `Persona injection uses one of two strategies depending on agent capability`; `Local-LLM adapters reuse Claude Code as the frontend with env-var tier-pinning`; `The fake adapter is gated behind STUDYLOOP_TEST_AGENT and opts out of production registries`; `MCP config is written for agents that declare mcp_setup`; ``studyloop install agents` symlinks platform-specific definitions from the source checkout`

```markdown
## ADDED Requirements

### Requirement: Persona resolution by purpose
`studyloop.agent_launcher` SHALL expose one resolver,
`persona_mode_for(purpose: str) -> str`, mapping a session purpose to the
persona mode that serves it: `planning` → `plan-architect`, anything else →
`focus`. Every web start path (PTY and ACP alike) SHALL obtain its mode
through this resolver; no route SHALL name a persona mode as a literal
(`rg 'build_canonical_persona\("focus"' packages/studyloop/src/studyloop/web` → 0).
`build_canonical_persona(mode, topic, energy, *, previous_notes=None,
brief=None)` SHALL accept the planning brief through the `brief` keyword and
render it as its own `## Planning brief` section — introduced as data about
the learner, not instructions — placed with the other context sections ahead
of the persona body. The brief SHALL NOT be carried through `previous_notes`
(which renders `Resuming Previous Session`, the framing for a resumed study
session) and SHALL NOT be folded into `topic`. With `brief=None` the output
SHALL be byte-identical to the pre-`brief` output, so no existing session's
`persona_hash` changes.

#### Scenario: Resolver maps the two purposes
- **WHEN** `persona_mode_for("planning")` and `persona_mode_for("focus")` are called
- **THEN** they return `plan-architect` and `focus` respectively

#### Scenario: Brief renders as its own section
- **WHEN** `build_canonical_persona("plan-architect", "Study plan", 5, brief="- item")` is called
- **THEN** the result contains `## Planning brief`, contains `- item`, contains
  the plan-architect persona body, and does not contain `Resuming Previous Session`

#### Scenario: No brief, no section
- **WHEN** `build_canonical_persona("focus", "Python", 5)` is called
- **THEN** the result contains no `## Planning brief` section and is
  byte-identical to the output before the `brief` keyword existed

### Requirement: Architect persona prefers the MCP plan tools
The canonical study-plan-architect persona (`agents/shared/personas/plan-architect.md`,
the body every harness projection carries verbatim after its own header) SHALL
carry one tooling section that introduces the plan tools over MCP **before** the
CLI fallback. The MCP subsection SHALL name the nine plan lifecycle tools of
design §4 — `list_study_plans`, `get_study_plan`, `get_planning_interview`,
`create_study_plan`, `update_study_plan`, `set_study_plan_status`,
`set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` — in
lifecycle order (discover → interview → create as `draft` → revise → activate →
tick → evaluate → delete), and SHALL state the three guards the plan
application layer enforces: activation only once `readiness` reports ready
(never creating as `active` to skip the gate), `evaluate_study_plan` with
`record=False` as a preview that writes nothing versus `record=True` to
persist a checkpoint, and `delete_study_plan` only with `confirmed=True` after
the learner has explicitly confirmed. The CLI fallback subsection SHALL give
the `studyloop plan` command for every lifecycle step that has one
(`interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate`,
`record`) and SHALL say plainly which steps the CLI cannot perform (revising an
existing plan's fields; deletion) rather than inventing a command. A tool
missing from the connected server's inventory SHALL route to that step's CLI
fallback. The interview protocol (one question per turn) SHALL be unchanged,
and the `focus` persona SHALL be byte-identical before and after this change.

#### Scenario: Planning persona names the nine tools before the fallback
- **WHEN** `build_canonical_persona(persona_mode_for("planning"), "Study plan", 5, brief="- item")` is rendered
- **THEN** the result names all nine design-§4 tool names inside the MCP
  subsection, the MCP subsection precedes the `CLI fallback` subsection and
  closes before it, no `studyloop plan` recipe appears inside the MCP
  subsection, and the `CLI fallback` subsection names `studyloop plan
  interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate` and
  `record` and no `studyloop plan delete`

#### Scenario: Focus persona untouched
- **WHEN** `build_canonical_persona("focus", "Python", 5)` is rendered with the
  three session paths fixed
- **THEN** its SHA-256 digest equals the digest recorded at `205819c7`

#### Scenario: Projections and manifest regenerate byte-identically
- **WHEN** `agents/claude/study-plan-architect.md`, `agents/opencode/study-plan-architect.md`
  and `agents/kiro/study-plan-architect/persona.md` are read
- **THEN** each body after its harness header equals the canonical persona
  byte-for-byte, and `agents/manifest.json` carries the generator's own hash
  for every architect projection it tracks
```
### `openspec/changes/plan-application-seam/specs/cli-surface/spec.md` → `openspec/specs/cli-surface/spec.md`

Existing requirements in the main spec (names only): `Commands are lazy-loaded to keep startup cost constant`; `Every lazy_subcommands target must resolve to a valid Click command or group`; `The command namespace is partitioned into groups and leaf commands`; `Two workspace packages install distinct console_scripts entry points`; `Optional extras gate command bodies, not command registration`; `The CLI is invocable via console_scripts and python -m studyloop.cli`; `Shared output uses a Rich console singleton and click.echo for JSON`; `click.version_option exposes the package version`; `The brain group is lazily registered and every command has --json`

```markdown
## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
`studyloop plan status <id> active` SHALL apply a `TransitionLifecycle` intent
through `PlanApplication` rather than checking readiness itself, so the refusal
a learner sees in the terminal is produced from the same `ReadinessView` the
Web API turns into its `422` body. A refused activation SHALL exit `1`, print
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers and
then the nudges as `•` bullets, print no traceback, and leave the document on
disk byte-identical. `studyloop plan list` and `studyloop plan show` SHALL
read through the seam (`browse` / `inspect`) with their `--json` shapes
unchanged: `list --json` emits the `StudyPlan.summary()` key set per plan;
`show --json` emits `{"plan", "mission", "milestones": [{"title", "done",
"concepts"}], "readiness"}`.

#### Scenario: Status transition to active on an unready plan
- **WHEN** `studyloop plan status vague-plan active` is run for a draft with
  no mission, success criteria or milestones
- **THEN** the exit code is `1`, the output contains `Cannot activate` and the
  word `Mission`, contains no `Traceback`, and `studyloop plan show
  vague-plan --json` still reports `"status": "draft"`

#### Scenario: The CLI refusal and the Web refusal are the same refusal
- **WHEN** the same unready draft is refused via `studyloop plan status <id>
  active` and via `PATCH /api/plans/{id}` with `{"status": "active"}`
- **THEN** the CLI's `•` bullets, in order, equal the Web `detail.blockers`
  followed by `detail.nudges`, and neither surface has written to the document

#### Scenario: Create with --activate on an unready plan
- **WHEN** `studyloop plan new --title Empty --activate` is run
- **THEN** the exit code is `1` and the output contains `Cannot activate`;
  no active plan is created

#### Scenario: A ready plan activates
- **WHEN** `studyloop plan status <id> active` is run for a plan with a
  mission `why`, a success criterion and a milestone
- **THEN** the exit code is `0`, the output is `<id> → active`, and `plan
  show <id> --json` reports `"status": "active"`

#### Scenario: Unknown id on the seam-backed commands
- **WHEN** `studyloop plan show nope` or `studyloop plan status nope paused`
  is run
- **THEN** the exit code is `1`, the output contains `No study plan with id`
  and no `Traceback`


### Requirement: The CLI maps every seam refusal to one line and exit 1
Every `studyloop plan` command that reads or writes through `PlanApplication`
SHALL catch `PlanError` and map it in one place (`_fail_for`): `PlanNotFound`
→ `No study plan with id '<id>'. Try: studyloop plan list`; `PlanNotReady` →
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers
and nudges; `PlanConflict` → `A study plan with id '<id>' already exists.
Choose another id.`; `InvalidPlanId` → `Invalid plan id '<id>': <reason>`;
`InvalidField` → `Invalid value: <reason>`; `InvalidMilestone` → `No such
milestone on '<id>': <reason>`. When the refused `PlanNotReady` carries
`already_active` (the stored plan was active and incomplete before the write —
a `record`, `milestone` or `evaluate --record` on a hand-edited document), the
mapping SHALL add a line telling the learner to pause the plan
(`studyloop plan status <id> paused`) or repair the blockers, then retry.
Every mapping SHALL exit `1` and print no traceback. `studyloop plan list` SHALL route a `browse` refusal through the
same mapping.

#### Scenario: A refusal reaching plan list is a message, not a traceback
- **WHEN** `studyloop plan list --status draft` is run and the seam refuses the
  filter with `InvalidField`
- **THEN** the exit code is `1`, the output contains the seam's reason and no
  `Traceback`

#### Scenario: Each refusal has its own line
- **WHEN** `studyloop plan status <id> active` is refused with `PlanConflict`,
  `InvalidField`, `InvalidPlanId`, `InvalidMilestone` or `PlanNotReady`
- **THEN** the exit code is `1` in every case, the output contains the
  mapping's distinguishing text (`already exists`, `Invalid value:`, `Invalid
  plan id`, `No such milestone`, `Cannot activate '<id>'`), and no `Traceback`


### Requirement: Every plan command reads and writes through the seam
`studyloop plan new|interview|evaluate|milestone|record|reindex` SHALL
delegate to `PlanApplication` like `list|show|status` already do, and
`cli/_plan.py` SHALL import no storage, index, authoring or evaluation module
(the architecture guard `tests/test_architecture_plan_seam.py` fails
otherwise). `plan new` SHALL be one `CreatePlan` whose `status` is `"active"`
with `--activate` and `"draft"` without; the `--activate` refusal SHALL be the
seam's `PlanNotReady` reached through `_fail_for` — the command holds no
readiness decision of its own — and a refused create SHALL write nothing.
`plan new --json` SHALL keep `{"plan", "readiness", "path"}`. `plan interview`
SHALL be `prepare_planning` and SHALL keep emitting `{"questions", "seed"}`
(no `existing_plans` key is added here). `plan reindex` SHALL call
`PlanApplication.reindex()`. The other CLI readers of plans — `exercise
from-milestone` and `brain publish`'s plan selection — SHALL read through
`inspect` / `browse`.

#### Scenario: Create with --activate on a ready plan
- **WHEN** `studyloop plan new --title "Glue ETL" --why … --success …
  --milestone … --activate` is run
- **THEN** exactly one `CreatePlan(status="active")` is applied, the exit
  code is `0`, and the stored plan's status is `active`

#### Scenario: Create with --activate on an unready plan writes nothing
- **WHEN** `studyloop plan new --title Empty --activate` is run
- **THEN** the exit code is `1`, the output contains `Cannot activate 'empty'`
  and the blockers, and the plans directory holds no document

### Requirement: The CLI milestone command is an idempotent set
`studyloop plan milestone <id> <index> [--done|--undone]` SHALL apply one
`SetMilestone`. With a flag the state is set as asked, so running the same
command twice is safe; without a flag the current state is read through the
seam and its opposite is set. A negative index SHALL be refused exactly like
one past the end (`No milestone at index -1 …`, exit `1`, document unchanged).

#### Scenario: Set twice stays set, no flag toggles
- **WHEN** `plan milestone <id> 0 --done` is run twice and then `plan
  milestone <id> 0` once
- **THEN** the outputs report `1/2`, `1/2`, `0/2`, and the three applied
  intents were `SetMilestone(done=True)`, `SetMilestone(done=True)`,
  `SetMilestone(done=False)`

### Requirement: Recorded checkpoints report a complete, partial or absent recording
`studyloop plan evaluate <id> --record` SHALL call `assess(record=True)`,
print the evaluation Markdown, and then print `Checkpoint recorded.` only when
every requested sink was saved. When a sink failed the command SHALL exit `0`
— the evaluation succeeded — and name each sink: `Checkpoint partially
recorded — database: <state>, document: <state>` when at least one sink
saved, and `Checkpoint not recorded — database: failed, document: <state>`
when none did ("partially" is only honest when something landed). Without
`--record` the command is `assess(record=False)` and writes nothing; `--json`
keeps emitting the evaluation dict unchanged.

#### Scenario: Database sink fails
- **WHEN** the checkpoint log write returns `False` during `plan evaluate <id>
  --record`
- **THEN** the exit code is `0`, the output contains `partially recorded`,
  `database: failed` and `document: saved`, and the plan document carries
  the checkpoint

#### Scenario: Both sinks fail
- **WHEN** the checkpoint log write returns `False` and the document save
  raises during `plan evaluate <id> --record`
- **THEN** the exit code is `0`, the output contains `Checkpoint not recorded`,
  `database: failed` and `document: failed`, never `partially recorded`, and
  the plan document carries no checkpoint

### Requirement: Learning records are one revision through the seam
`studyloop plan record <id> --title T [--body B]` SHALL apply one
`RevisePlan(learning_record=LearningRecordSpec(...))` and no preliminary read.
`created` in the `--json` output SHALL be the mutation's own outcome —
`PlanDetail.learning_record_outcome.created`, the store's
`append_learning_record` verdict relayed by the seam — never inferred from an
`inspect` taken before the revision (a record another writer files in that
window must be reported `created: false`), and the command carries no copy of
the store's identity rule. A retry with the same title and body SHALL report
`created: false` with the original `number`. An empty title SHALL be the
seam's `Invalid value: …` refusal, exit `1`.

#### Scenario: Retry reports created false
- **WHEN** `plan record <id> --title Insight --body prose --json` is run twice
- **THEN** both exit `0`; the first reports `created: true, number: 1`; the
  second reports `created: false, number: 1`; the plan holds one record

#### Scenario: A record filed by another writer just before the mutation
- **WHEN** the same record is written through the store immediately before
  the command's `RevisePlan` runs
- **THEN** the command exits `0` with `created: false, number: 1`, made no
  `inspect` call, and the plan holds one record
```
### `openspec/changes/plan-application-seam/specs/live-session-orchestration/spec.md` → `openspec/specs/live-session-orchestration/spec.md`

Existing requirements in the main spec (names only): `studyloop study composes a tmux session with agent and sidebar panes`; `Only one tmux-based session may be active at a time`; `IPC files provide the inter-process communication surface`; `studyloop park persists tangential questions to both DB and IPC`; `Energy-adaptive break suggestions use bounded thresholds`; `Session end flushes summary to DB and clears IPC files`; `Orphan sessions are auto-cleaned before new session start`; `The sidebar polls IPC files every 2 seconds`; `Timer supports elapsed and pomodoro modes with sidebar key bindings`

```markdown
## ADDED Requirements

### Requirement: Session purpose
A web session start (`POST /api/session/start`) SHALL carry a *purpose* —
`focus` (the default) or `planning` — validated structurally by
`StartSessionRequest` (`purpose: Literal["focus", "planning"] = "focus"`), so
any other value is refused with `422` before the handler runs. A `focus` start
SHALL be indistinguishable from a start that names no purpose: the same
persona, the same `persona_hash`, the same session-state `mode`. A `planning`
start SHALL launch the study-plan architect: the persona is the
`plan-architect` mode carrying a `## Planning brief` section (the interview
questions, the learner's history evidence and the existing plans), and the
session's topic is the learner's subject when one was supplied, else the fixed
label `Study plan` — the same label `studyloop plan architect` pins. The start
SHALL NOT create a plan and SHALL NOT store a plan id anywhere; the architect
creates plans through the plan tools during the session. The only planning
fact the live-session state carries is `purpose`, written on every start
(never inherited through the state file's read-merge-write), and
`GET /api/session/state` SHALL expose it for the reconnect label, defaulting to
`focus` when the state predates the key or the overlay branch rebuilt the
payload. If the planning brief cannot be built, the start SHALL refuse with a
structured error (`error`, `purpose`, `repair`; HTTP 500) and leave the
single-session slot free — no reservation, no live slot, no study row. Both
transports (`pty` and `acp`) SHALL follow this requirement identically.

#### Scenario: Planning start launches the architect with a brief
- **WHEN** `POST /api/session/start` is called with `{"purpose": "planning", "topic": "", ...}`
- **THEN** the response is `201`, the persona the agent receives has
  `**Mode:** plan-architect`, contains the plan-architect persona body and a
  `## Planning brief` section naming the interview questions and every existing
  plan by id and title, contains no `Resuming Previous Session` section, and
  the session topic is `Study plan`

#### Scenario: Planning start keeps a supplied subject
- **WHEN** `POST /api/session/start` is called with `{"purpose": "planning", "topic": "Spark", ...}`
- **THEN** the persona and the session state both carry the topic `Spark`

#### Scenario: Default purpose is focus and unchanged
- **WHEN** `POST /api/session/start` is called with no `purpose`
- **THEN** the persona is byte-identical to `build_canonical_persona("focus", topic, energy)`,
  the `persona_hash` is unchanged from before the purpose existed, the state's
  `mode` is `focus` and its `purpose` is `focus`

#### Scenario: Unknown purpose is refused structurally
- **WHEN** `POST /api/session/start` is called with `{"purpose": "revision", ...}`
- **THEN** the response is `422` and no session slot is held

#### Scenario: Planning start creates no plan and stores no plan id
- **WHEN** one plan exists and `POST /api/session/start` is called with `purpose: planning`
- **THEN** the set of plan ids on disk is unchanged, the `201` body has no
  `plan_id`, and the session state has no `plan_id` key

#### Scenario: Purpose is persisted for the reconnect label
- **WHEN** a `planning` session has started
- **THEN** the session state's `purpose` is `planning` and
  `GET /api/session/state` reports `purpose == "planning"` alongside the live
  session's id and topic

#### Scenario: Brief failure releases the session claim
- **WHEN** `PlanApplication.prepare_planning` raises during a `planning` start
- **THEN** the response is `500` with an `error` naming the brief and
  `purpose == "planning"`, the session state file is empty, no in-process
  session is held, no study row was created, and a following `focus` start
  succeeds with `201`

#### Scenario: PTY and ACP resolve the mode through one resolver
- **WHEN** a `planning` start is made over `transport: pty` and, separately,
  over `transport: acp`
- **THEN** each start calls `agent_launcher.persona_mode_for` exactly once
  with `planning`, each persona has `**Mode:** plan-architect` and a
  `## Planning brief` section, and each state records its own `transport`
  with `purpose == "planning"`
```
### `openspec/changes/plan-application-seam/specs/mcp-server/spec.md` → `openspec/specs/mcp-server/spec.md`

Existing requirements in the main spec (names only): `studyloop-mcp registers a fixed set of study tools`; `Review-loop tools enable a complete quiz cycle without the browser`; `Course paths are validated against traversal`; `get_study_context aggregates review state for one course`; `Generation tools save agent-authored content, not pipeline output`; `Desktop MCP clients can serve due-card content for review`; `Desktop MCP clients have Course Explorer read parity`; `docs/mcp.md documents studyloop-mcp and desktop registration`

```markdown
## ADDED Requirements

### Requirement: record_plan_learning writes through the plan seam
The `record_plan_learning(plan_id, title, body="", status="active")` tool
SHALL apply one `RevisePlan(plan_id, learning_record=LearningRecordSpec(title,
body, status))` through `studyloop.planning.PlanApplication` and SHALL import
no storage module (`studyloop.planning.store` or the store's `record_learning`
/ error family) and make no preliminary read. Its response SHALL keep the
pre-seam keys `{"plan_id", "number", "title", "status", "created"}`; `created`
SHALL be the mutation's own outcome — `PlanDetail.learning_record_outcome`,
the store's `append_learning_record` verdict relayed by the seam — never
inferred from an `inspect` taken before the revision, so a retry with the same
title and body reports `created: false` with the original `number`, and so
does a record another writer filed just before the mutation ran. Every seam
refusal SHALL be a `ToolError` mapped by the same `_plan_tool_error` helper the
nine plan tools of design §4 use (Phase 4, #12 — before the fold the tool mapped
inline, without a kind prefix): `PlanNotReady` SHALL render as `not_ready:
plan is not ready to activate: <blocker>; <blocker>…` (with the already-active
"pause it or repair" suffix when the plan was active) so the agent can tell
the learner what to repair (design §2, "ToolError containing blockers");
`PlanNotFound`, `InvalidPlanId` and `InvalidField` (the store's title/heading
rule) SHALL render as `not_found: …`, `invalid_id: …` and `invalid: …`
followed by their message, with the domain error chained as `__cause__`. The
success shape is unchanged by the fold.

This was the **only** change to `mcp/tools.py` in Phase 2. The six read/write
plan tools of design §4 are registered in Phase 3 (#11, the requirement
below); the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
`delete_study_plan`) are registered in #12 (the last requirement in this
file). The stdio smoke test pins the exact production inventory (32 unique
names), the nine plan tools and the core names (D-9, council review 3 F13).

#### Scenario: One revision through the seam
- **WHEN** `record_plan_learning("decorators", "MCP insight", body="prose")`
  is called on a ready active plan
- **THEN** exactly one `RevisePlan` whose `learning_record` carries that title
  and body is applied, the response is `{"plan_id": "decorators", "number": 1,
  "title": "MCP insight", "status": "active", "created": true}`, and the plan
  document holds the record

#### Scenario: Retry is one seam call and reports created false
- **WHEN** the same call is repeated
- **THEN** one `RevisePlan` is applied, the response has `created: false` and
  `number: 1`, and the plan still holds one record

#### Scenario: A record filed by another writer just before the mutation
- **WHEN** the same record is written through the store immediately before
  the tool's `RevisePlan` runs
- **THEN** the response has `created: false` and `number: 1`, the tool made no
  `inspect` call, and the plan holds one record

#### Scenario: Not-ready refusal names the blockers
- **WHEN** the seam raises `PlanNotReady` for the revision (the plan is active
  but has no mission, success criteria or milestones)
- **THEN** a `ToolError` is raised whose message starts with `not_ready: plan
  is not ready to activate: `, contains each blocker string from the
  `ReadinessView` and the "already active … pause it or repair" hint, and
  chains the `PlanNotReady` as its cause

#### Scenario: Store rule and id refusals are tool errors
- **WHEN** the title is blank, or the body contains a `###` line, or the plan
  id is unknown or malformed
- **THEN** a `ToolError` is raised reading `invalid: …`, `not_found: …` or
  `invalid_id: …` followed by the seam's message, and no record is added


### Requirement: Study-plan discovery and authoring tools
`register_tools(mcp)` SHALL register six study-plan tools in the production
inventory, each a thin adapter that makes exactly one
`studyloop.planning.PlanApplication` call and imports no storage, index,
authoring or evaluation module (D-6):

| Tool | Seam call |
|---|---|
| `list_study_plans(status=None)` | `browse(status=)` → `{"plans": [PlanSummary.to_json_dict()…], "count": N}` |
| `get_study_plan(plan_id, include_markdown=False, include_history=False, history_limit=20)` | `inspect(...)` → `PlanDetail.to_json_dict()` (the `GET /api/plans/{id}` body) |
| `get_planning_interview()` | `prepare_planning()` → `PlanningBrief.to_json_dict()` (`questions`, `seed`, `existing_plans`) |
| `create_study_plan(title, answers, plan_id=None, status="draft")` | `apply(CreatePlan(...))` with `overwrite` always `False` → `PlanDetail.to_json_dict()` |
| `update_study_plan(plan_id, title=None, topics=None, target_date=None, energy_floor=None, review_cadence_days=None, notes=None, milestones=None, status=None)` | `apply(RevisePlan(...))` — one intent, judged as one document → `PlanDetail.to_json_dict()` |
| `set_study_plan_status(plan_id, status)` | `apply(TransitionLifecycle(...))` → `PlanDetail.to_json_dict()` |

Every response SHALL be the seam view's `to_json_dict()` built on that call —
fresh containers, never a cached or shared dict. The adapter SHALL carry no
plan policy: the readiness gate, the lifecycle status list, the id rules and
the conflict check are the seam's, and the adapter forwards its arguments
unchanged (an omitted `update_study_plan` field SHALL reach the seam as `None`,
"leave as is", never as `""` or `[]`).

The `create_study_plan` schema SHALL NOT expose `overwrite` (D-4); an agent
cannot replace an existing plan by picking its id, and a taken id is a
conflict. One argument is normalised rather than forwarded unchanged: an
empty `plan_id` string is treated as omitted, so the seam allocates the
unique title slug instead of refusing `""` as a malformed id (council review
3). `update_study_plan` SHALL NOT expose `learning_record`:
`record_plan_learning` remains the one record writer (D-9).

`get_study_plan` SHALL refuse a `history_limit` outside `1..200` — the range
the Web history route accepts — with `invalid: history_limit must be between 1
and 200, got <n>` **before** calling the seam, so a refused limit performs no
database query.

Every seam refusal SHALL be one `ToolError` whose message is
`<kind>: <the seam's message>`, where `kind` is machine-readable:
`PlanNotFound` → `not_found`, `InvalidPlanId` → `invalid_id`, `PlanConflict` →
`conflict`, `InvalidField` → `invalid`, `PlanNotReady` → `not_ready` (rendered
`not_ready: plan is not ready to activate: <blocker>; <blocker>…`, with the
suffix `— the plan is already active; pause it or repair the blockers before
writing` when the plan was already active), `InvalidMilestone` →
`invalid_milestone`, and `plan_error` for any `PlanError` subclass this mapping
has not met. The `ToolError` SHALL chain the domain error as its cause.

#### Scenario: Discover, inspect, create, revise, activate
- **WHEN** an agent calls `get_planning_interview()` (no plans exist), then
  `create_study_plan("Python Decorators", {"why": …, "success": […],
  "topics": ["python"]})`, then `list_study_plans()`, then
  `update_study_plan(<id>, topics=[…], milestones=[{"title": …, "concepts":
  […]}])`, then `set_study_plan_status(<id>, "active")`, then
  `get_study_plan(<id>, include_markdown=True)`
- **THEN** the interview lists the `why`, `success` and `milestones` keys with
  `existing_plans: []`; the create returns a `draft` plan whose id is the
  unique title slug and whose `readiness.ready` is `false` (no milestones yet);
  the list shows that one plan; the revision returns `readiness.ready: true`
  with the new topics and milestone concepts; the transition returns status
  `active`; the inspection returns the active plan with its Markdown document,
  and `list_study_plans(status="active")` counts it while
  `list_study_plans(status="draft")` does not

#### Scenario: Refused activation carries the blockers and writes nothing
- **WHEN** `set_study_plan_status("husk", "active")` — or
  `create_study_plan("Husk", {}, plan_id="husk", status="active")`, or an
  `update_study_plan` whose resulting document would be active — is called
  for a plan with no mission, success criteria or milestones
- **THEN** a `ToolError` is raised whose message starts with `not_ready: plan
  is not ready to activate: ` and contains every blocker string the plan's
  `readiness` reports, the existing document is byte-identical afterwards
  (still `draft`), and no document is created for the refused create

#### Scenario: No overwrite through the MCP door
- **WHEN** `create_study_plan` is called with a `plan_id` that already exists
- **THEN** a `ToolError` starting `conflict: ` is raised, the existing
  document is byte-identical afterwards, and the tool's input schema has no
  `overwrite` property to ask for otherwise

#### Scenario: Every refusal is one prefixed ToolError
- **WHEN** the seam raises `PlanNotFound`, `InvalidPlanId`, `PlanConflict`,
  `InvalidField`, `InvalidMilestone`, or an unmapped `PlanError` from
  `browse`, `inspect`, `prepare_planning` or `apply`
- **THEN** the tool raises exactly one `ToolError` reading `not_found: …`,
  `invalid_id: …`, `conflict: …`, `invalid: …`, `invalid_milestone: …` or
  `plan_error: …` respectively, followed by the seam's message, with the
  domain error chained as `__cause__`

#### Scenario: A retried status transition is not refused
- **WHEN** `set_study_plan_status("decorators", "paused")` is called twice
- **THEN** both calls apply the same `TransitionLifecycle`, both return the
  plan with status `paused`, and neither raises

#### Scenario: history_limit is bounded before any read
- **WHEN** `get_study_plan("decorators", include_history=True,
  history_limit=0)` (or `-1`, `201`, `10000`) is called
- **THEN** a `ToolError` reading `invalid: history_limit must be between 1 and
  200, got <n>` is raised and `PlanApplication.inspect` is never called; `1`
  and `200` are accepted and forwarded unchanged

#### Scenario: Responses are fresh containers
- **WHEN** a response from any of the six tools is mutated by the caller and
  the same call is repeated
- **THEN** the second response is equal to an untouched first response and is
  not the same object



### Requirement: Study-plan progression and deletion tools
`register_tools(mcp)` SHALL register three further study-plan tools in the
production inventory — completing the nine of design §4 — each a thin adapter
that makes exactly one `studyloop.planning.PlanApplication` call, imports no
storage, index, authoring or evaluation module (D-6), and maps every seam
refusal through the same `<kind>: <message>` `ToolError` mapping as the six
above (the domain error chained as `__cause__` — an in-process requirement on
the adapter, checked by the delegation tests; the stdio transport carries the
prefixed refusal text only, since JSON-RPC does not serialise an exception
chain):

| Tool | Seam call |
|---|---|
| `set_study_plan_milestone(plan_id, index, done)` | `apply(SetMilestone(plan_id, index, done))` → `PlanDetail.to_json_dict()` |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `assess(AssessPlan(plan_id, phase, study_id, record))` → `AssessmentResult.to_json_dict()` |
| `delete_study_plan(plan_id, confirmed=False)` | `apply(DeletePlan(plan_id, confirmed))` → `DeleteResult.to_json_dict()` (`{"deleted": true, "plan_id": "<id>"}`) |

`set_study_plan_milestone` SHALL take `done` as a required boolean with no
default and forward it as given — set, not toggle: the tool SHALL make no
preliminary read and compute no opposite, so a second identical call returns
the same plan, raises nothing and rewrites nothing. An index the plan does
not have (past the end or negative) is the seam's `InvalidMilestone`,
rendered `invalid_milestone: …`; a set on an active-but-unready document is
the seam's `PlanNotReady`, rendered `not_ready: … — the plan is already
active; pause it or repair the blockers before writing`, and nothing is
written in either case.

`evaluate_study_plan` SHALL call `assess`, never `apply` (`AssessPlan` is not
a `PlanIntent`), SHALL default `record` to `False`, and SHALL NOT expose
`append_to_plan` (the seam's default, `True`, applies when recording). The
response SHALL be the `AssessmentResult` view — `evaluation`, `markdown`,
`db_write`, `document_write`, `recording_complete`, `warnings` — with each
sink reported **as the seam reports it** (`not_requested`, `saved`, `failed`),
never flattened to a boolean and never an invented `saved`. A preview
(`record=False`) SHALL write to neither sink: the document is byte-identical
afterwards and the checkpoint log is unchanged. With `record=True` a failed
sink SHALL surface as `failed` with `recording_complete: false` and the seam's
warning string in `warnings` — a reported outcome, never an exception and
never a bare success. Recording on an active plan that is unready SHALL be
refused (`not_ready: …`) before either sink is touched; an unknown `phase`
is the seam's `invalid: phase must be one of …`, judged after the plan
exists (`not_found:` first).

`delete_study_plan` SHALL keep `confirmed` as an ordinary boolean defaulting
to `False` in its schema — not required, not constrained to a literal `true`
— and SHALL forward it unchanged: an unconfirmed call is the seam's
`InvalidField`, rendered `invalid: deleting '<id>' requires confirmed=True`,
and the plan still exists byte-identical afterwards. A confirmed delete
removes the document and its derived index row and SHALL leave the plan's
checkpoint history in the sessions database readable. A missing plan is
`not_found:` before the confirmation is judged.

The production inventory SHALL be exactly 32 unique tool names — 23 at
`0a20a796` plus the nine design-§4 plan tools, `record_plan_learning` being
one of the 23 — and the stdio smoke test SHALL assert that exact count, the
nine plan names, `record_plan_learning` and the core names over the real
transport.

#### Scenario: A retried milestone set is a no-op
- **WHEN** `set_study_plan_milestone(<id>, 0, true)` is called twice on a
  ready plan with two milestones, then `set_study_plan_milestone(<id>, 0,
  false)`
- **THEN** the first call returns the plan with `milestones[0].done: true` and
  `plan.milestone_done: 1`; the second returns an equal response, raises
  nothing and leaves the document byte-identical; the third reopens the
  milestone (`done: false`, `milestone_done: 0`)

#### Scenario: Milestone set on an active-but-unready document is refused
- **WHEN** `set_study_plan_milestone("husk", 0, true)` is called for an active
  document with a milestone but no mission or success criteria
- **THEN** a `ToolError` is raised starting `not_ready: plan is not ready to
  activate: `, naming every blocker and containing `already active` and
  `pause it or repair`, and the document is byte-identical afterwards; an
  index the plan does not have (`2`, `9`, `-1`) is `invalid_milestone: No
  milestone at index …` with nothing written

#### Scenario: Evaluate preview writes nothing
- **WHEN** `evaluate_study_plan(<id>, "mid")` is called (the default
  `record=False`) on an active plan
- **THEN** the response carries the evaluation (`phase: "mid"`, a verdict, a
  non-empty `markdown`) with `db_write` and `document_write` both
  `not_requested` and `recording_complete: true`; the plan document is
  byte-identical afterwards; `get_study_plan(<id>, include_history=True)`
  returns an empty `history` and an empty `checkpoints` table

#### Scenario: Evaluate record reports both sinks
- **WHEN** `evaluate_study_plan(<id>, "end", study_id="sess-9", record=True)`
  is called on an active plan
- **THEN** `db_write` and `document_write` are `saved`, `recording_complete`
  is `true`, the checkpoint log holds one `end` row attributed to `sess-9`
  (visible through `get_study_plan(include_history=True)`), and the
  document's `checkpoints` table holds one `end` row

#### Scenario: A failed sink is a warning, not a success and not an error
- **WHEN** the checkpoint log write fails during
  `evaluate_study_plan(<id>, "start", record=True)`
- **THEN** the tool returns (no `ToolError`) with `db_write: "failed"`,
  `document_write: "saved"`, `recording_complete: false` and `checkpoint not
  saved to the database` in `warnings`; the document holds the checkpoint and
  the log does not

#### Scenario: Recording on an active-but-unready plan is refused before either sink
- **WHEN** `evaluate_study_plan("husk", "start", record=True)` is called for
  an active document that is unready
- **THEN** a `ToolError` starting `not_ready: ` with the "pause it or repair"
  hint is raised, the document is byte-identical and the log unchanged; the
  same call with `record=False` succeeds with both sinks `not_requested`

#### Scenario: Delete requires confirmation
- **WHEN** `delete_study_plan(<id>)` or `delete_study_plan(<id>,
  confirmed=False)` is called
- **THEN** a `ToolError` reading `invalid: deleting '<id>' requires
  confirmed=True` is raised, the document exists byte-identical afterwards
  and `list_study_plans()` still counts it; the tool's schema has
  `confirmed` as a boolean defaulting to `false`

#### Scenario: Confirmed delete keeps the checkpoint history
- **WHEN** a checkpoint has been recorded for `<id>` and
  `delete_study_plan(<id>, confirmed=True)` is called
- **THEN** the response is `{"deleted": true, "plan_id": "<id>"}`, the
  document is gone, `list_study_plans()` is empty, `get_study_plan(<id>)` is
  `not_found: …`, and the checkpoint history for `<id>` still holds the
  recorded row; `delete_study_plan("ghost")` is `not_found:` whether or not
  confirmed, and a traversal id is `invalid_id:`

#### Scenario: Every refusal of the three is one prefixed ToolError
- **WHEN** the seam raises `PlanNotFound`, `InvalidPlanId`, `PlanConflict`,
  `InvalidField`, `InvalidMilestone`, or an unmapped `PlanError` from
  `apply` (milestone, delete) or `assess` (evaluate)
- **THEN** the tool raises exactly one `ToolError` reading `not_found: …`,
  `invalid_id: …`, `conflict: …`, `invalid: …`, `invalid_milestone: …` or
  `plan_error: …` followed by the seam's message, with the domain error
  chained as `__cause__`; responses of the three are fresh containers on
  every call

#### Scenario: The production inventory is exactly 32 with the nine plan tools
- **WHEN** a stdio client performs the handshake and `tools/list` against
  `python -m studyloop.mcp.server` (no `--dev`)
- **THEN** exactly 32 unique names are advertised, including
  `list_study_plans`, `get_study_plan`, `get_planning_interview`,
  `create_study_plan`, `update_study_plan`, `set_study_plan_status`,
  `set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan`,
  `record_plan_learning` and the core tools
```
### `openspec/changes/plan-application-seam/specs/web-ui/spec.md` → `openspec/specs/web-ui/spec.md`

Existing requirements in the main spec (names only): `The PWA owns all chat-surface rendering`; `Explorer content routes are read-only and traversal-guarded`; `Course Explorer tree is cached by a visible-source fingerprint`; `Explorer full-text search is a derived, rebuildable cache`; `Struggle marking writes lesson provenance for later scoped generation`; `Generation progress streams over a per-job WebSocket`; `Session picker vendors are content sources, not study topics`; `Ending a session is confirmed in-page, never via native dialogs`; `Review list mode-splits Flashcards and Quizzes from one shared component`; `Settings → LLM Providers only persists verified credentials`; `The app lands on the Today one-next-action view`; `Starting a 4th topic requires parking one first`; `Quick-park captures a tangent without leaving the current view`; `Course lists never flash a false empty state`; `Live agent consoles are addressed by origin, never broadcast`; `The Study Session picker has no session-type selector`

```markdown
## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
Every Web API write that can leave a study plan in the `active` state —
create-with-status, raw-Markdown import, whole-document replacement, status
transition, and in-place revision of fields or milestones (including a body
that combines a status change with field edits) — SHALL delegate to
`PlanApplication.apply` as a single intent and SHALL be refused by the seam's
single readiness gate when the *resulting* document — the document as it
would be saved, after every supplied field is applied — has no mission `why`,
no success criteria, or no milestones. The gate judges the resulting document
whether the request makes the plan active or the plan already is. The routes
in `web/routes/plans.py` SHALL hold no readiness check and perform no store
write of their own (`rg 'readiness\(|save_plan' web/routes/plans.py` → 0
hits). A refusal SHALL be `422` whose response body is
`{"detail": {"message": "plan is not ready to activate", "plan_id": "<id>",
"ready": false, "blockers": [...], "nudges": [...]}}` — `detail` is the same
object the `PATCH` status path has always returned, `plan_id` included — and
SHALL persist nothing: no document is created, replaced or re-saved before the
gate runs, and a compound request is one write or none.

#### Scenario: Create with status active on an unready plan
- **WHEN** `POST /api/plans` is called with `{"title": "Vague", "status": "active", "answers": {}}`
- **THEN** the response is `422` whose `detail.ready` is `false` and
  `detail.blockers` is non-empty, no document is written, and
  `GET /api/plans?status=active` reports `count == 0`

#### Scenario: Whole-document replacement whose frontmatter says active
- **WHEN** `PATCH /api/plans/{id}` is called with `{"markdown": ...}` where the
  document's frontmatter has `status: active` and the Milestones section is
  empty
- **THEN** the response is `422` with `detail.ready == false`, and the stored
  document is byte-identical to what it was before the request (status still
  `draft`, milestone count unchanged)

#### Scenario: Status transition to active on an unready plan
- **WHEN** `PATCH /api/plans/{id}` is called with `{"status": "active"}` on a
  plan whose readiness reports blockers
- **THEN** the response is `422` with `detail.ready == false`, and
  `GET /api/plans/{id}` still reports `status == "draft"`

#### Scenario: Raw-markdown import whose frontmatter says active
- **WHEN** `POST /api/plans` is called with `{"markdown": ...}` whose
  frontmatter has `status: active` and which has no milestones
- **THEN** the response is `422` with `detail.ready == false` and no document
  is written

#### Scenario: Compound PATCH is judged as one resulting document
- **WHEN** `PATCH /api/plans/{id}` is called on a ready draft with
  `{"status": "active", "milestones": []}`
- **THEN** the response is `422` with `detail.ready == false`, the stored
  document is byte-identical to what it was before the request, and
  `GET /api/plans/{id}` still reports `status == "draft"` with its original
  milestone count — the status change is not saved before the edit is judged

#### Scenario: Compound PATCH that supplies what was missing activates
- **WHEN** `PATCH /api/plans/{id}` is called on a draft whose only blocker is
  "no milestones" with `{"status": "active", "milestones": [{"title": "First",
  "concepts": ["a"]}]}`
- **THEN** the response is `200`, the plan's `status` is `active`,
  `readiness.ready` is `true`, and the document was written exactly once

#### Scenario: Field-only edit cannot make an active plan unready
- **WHEN** `PATCH /api/plans/{id}` is called on an already-active plan with
  `{"milestones": []}` (no `status` in the body)
- **THEN** the response is `422` with `detail.ready == false`, and the stored
  document is byte-identical to what it was before the request

#### Scenario: Every door returns the same refusal
- **WHEN** the same unready document is refused via create-with-status, status
  transition, document replacement and raw-markdown import
- **THEN** the four `422` bodies are equal apart from `detail.plan_id`, with
  the same blockers and nudges in the same order

#### Scenario: A ready plan still activates on every door
- **WHEN** a plan with a mission `why`, at least one success criterion and at
  least one milestone is created with `status: active`, or transitioned to
  `active`, or replaced by a document whose frontmatter says `active`, or
  imported as raw Markdown whose frontmatter says `active`
- **THEN** the response is `201` (create, import) or `200` (patch) and the
  plan's `status` is `active`; several plans MAY be active at once

### Requirement: Plan routes map seam errors to HTTP status codes in one place
`web/routes/plans.py` SHALL translate `PlanError` subclasses exactly once:
`PlanNotFound` → `404`, `InvalidPlanId` and `InvalidField` → `400`,
`PlanConflict` → `409`, `PlanNotReady` → `422` (body above),
`InvalidMilestone` → `404`. Field validation for the in-place PATCH (empty
title, non-list milestones, non-integer `energy_floor` /
`review_cadence_days`, unknown `status`) SHALL be the seam's `InvalidField`
with the messages the route used before it delegated. Response bodies for
list, detail, create, patch and interview SHALL be unchanged from the
pre-seam routes: summaries carry the `StudyPlan.summary()` key set and
readiness blocks carry the `authoring.readiness()` key set.

#### Scenario: Duplicate id without overwrite
- **WHEN** `POST /api/plans` names a `plan_id` that already exists and does
  not set `"overwrite": true`
- **THEN** the response is `409` and the existing plan is unchanged

#### Scenario: Conflict is judged before readiness
- **WHEN** `POST /api/plans` names a `plan_id` that already exists, does not
  set `"overwrite": true`, and would also have failed the readiness gate
  (`"status": "active"` with empty `answers`)
- **THEN** the response is `409`, not `422`, and the existing plan is
  byte-identical to what it was before the request — identity and conflict
  are settled before the incoming document is judged, on every create door

#### Scenario: Unknown plan on a write
- **WHEN** `PATCH /api/plans/{id}` is called for an id with no document
- **THEN** the response is `404` before any field of the body is validated

#### Scenario: A bad field beside a status change writes nothing
- **WHEN** `PATCH /api/plans/{id}` is called with `{"status": "active",
  "title": "   "}` on a ready draft
- **THEN** the response is `400` and `GET /api/plans/{id}` still reports
  `status == "draft"` — the transition is not committed before the field is
  refused


### Requirement: The milestone checkbox is one SetMilestone; the toggle request is not replay-safe
`POST /api/plans/{id}/milestones/{index}/toggle` SHALL read the milestone's
current state through the seam and apply one `SetMilestone(plan_id, index,
done=<opposite>)` intent — never a route-side write and never the full-list
`RevisePlan` substitute the review-1 corrections used in the interim. The
seam's `SetMilestone` is a *set*, not a toggle: applying the same intent twice
leaves the same document. The legacy no-body toggle *request* is
read-invert-write and therefore **not** retry-idempotent: replaying it flips
the box again, and two concurrent toggles can collapse into one update — the
contract this checkbox has always had, acceptable for a checkbox, and no claim
of replay safety SHALL be made for it (council review 2, F3). A caller that
needs replay safety SHALL state the desired state (`PATCH` with `milestones`,
or the CLI's `--done`/`--undone`). An
index the plan does not have — past the end **or negative** — SHALL be the
seam's `InvalidMilestone`, mapped to `404`, with the document byte-identical
afterwards. The response body SHALL keep its pre-seam keys: `{"updated": true,
"index": <i>, "done": <bool>, "plan": <summary>}`.

#### Scenario: Toggle flips and flips back
- **WHEN** the toggle is posted twice for milestone `0` of a two-milestone plan
- **THEN** the first response has `done == true` and `plan.milestone_done ==
  1`; the second has `done == false` and `plan.milestone_done == 0`; each
  request applied exactly one `SetMilestone` whose `done` was the opposite of
  the state it read — a replayed request is not a no-op

#### Scenario: Out-of-range and negative indices
- **WHEN** the toggle is posted for index `42` or `-1`
- **THEN** the response is `404` and `GET /api/plans/{id}/markdown` is
  unchanged

### Requirement: Delete is confirmed by the verb and retains checkpoint history
`DELETE /api/plans/{id}` SHALL apply `DeletePlan(plan_id, confirmed=True)` —
the HTTP verb is the confirmation this route contract has always had — and
return `200` with `{"deleted": true, "plan_id": "<id>"}`. The canonical
document and its derived index row are removed; the durable checkpoint log
(`study_plan_checkpoints`) is retained. An unknown id SHALL be `404` and a
malformed id `400`, both before anything is removed.

#### Scenario: Delete removes the document and keeps the log
- **WHEN** a plan with one recorded checkpoint is deleted
- **THEN** the response is `200` with `deleted == true`; `GET /api/plans/{id}`
  is `404`; a second `DELETE` is `404`; the checkpoint log for that id still
  holds the row; the derived index no longer lists the plan

### Requirement: Checkpoint recording reports each sink
`POST /api/plans/{id}/evaluate` SHALL call `PlanApplication.assess` with
`record=True` and return `201` with `recorded`, `db_write`, `document_write`,
`evaluation` and `markdown`. `db_write` and `document_write` are each
`"not_requested"`, `"saved"` or `"failed"`; `recorded` SHALL be `true` only
when no requested sink failed. A failed sink is a reported outcome, not an
error response: the evaluation succeeded and the client is entitled to it, so
the status stays `201`. `GET /api/plans/{id}/evaluate` SHALL be
`assess(record=False)` and write to neither sink. The route SHALL hold no
phase check of its own: an unknown phase on `POST` is the seam's
`InvalidField` → `400`, judged after the plan is found (`404` first).

#### Scenario: Both sinks saved
- **WHEN** `POST /api/plans/{id}/evaluate` is called with `{"phase": "start"}`
  and both writes succeed
- **THEN** the body has `recorded == true`, `db_write == "saved"`,
  `document_write == "saved"`

#### Scenario: Database write fails
- **WHEN** the checkpoint log write returns `False` or raises during
  `POST /api/plans/{id}/evaluate`
- **THEN** the response is still `201`; `recorded == false`, `db_write ==
  "failed"`, `document_write == "saved"`; `evaluation.warnings` contains
  `checkpoint not saved to the database`; and the plan document carries the
  checkpoint row

#### Scenario: Document sink not requested
- **WHEN** the body has `"append_to_plan": false`
- **THEN** `document_write == "not_requested"`, `recorded == true`, the
  document has no new checkpoint and the log has the row

#### Scenario: Both sinks fail
- **WHEN** both writes fail during `POST /api/plans/{id}/evaluate`
- **THEN** the response is still `201` with `recorded == false`, `db_write ==
  "failed"`, `document_write == "failed"`; the plans panel shows `Not recorded
  <phase> checkpoint — database: failed, document: failed`, never "Partially
  recorded" — "partially" is shown only when at least one sink saved

#### Scenario: Preview writes nothing
- **WHEN** `GET /api/plans/{id}/evaluate?phase=end` is called
- **THEN** neither the checkpoint log nor the document gains a row

#### Scenario: Recording onto an unready active document
- **WHEN** `POST /api/plans/{id}/evaluate` is called for a hand-edited active
  plan with no mission
- **THEN** the response is the seam's `422` readiness refusal, the document is
  byte-identical, the checkpoint log has no row, and `GET
  /api/plans/{id}/evaluate` (preview) is still `200`


### Requirement: Plan with architect journey
The Study Plans view SHALL offer a **Plan with architect** control beside
**New plan** (button name `Plan with architect`, `data-testid="plan-architect"`)
with an optional subject field (`data-testid="plan-architect-subject"`, labelled
for assistive technology) and a live status region
(`data-testid="plan-architect-status"`, `role="status"`, `aria-live="polite"`).
One activation SHALL cause exactly one `POST /api/session/start` carrying
`purpose: "planning"`, `topic: <the subject, trimmed, or "">` (never omitted;
the server resolves `""` to the fixed label `Study plan`), `origin: "study"`
and the start picker's own `energy`, `agent` and `transport`. The Plans view
SHALL NOT post, open a WebSocket, mount a terminal or listen for the console's
`study-session-start` event: it dispatches one `plan-architect-request` window
event and the Study Session view's session timer — the one owner of the start
POST, the 409 handling and the `study-session-start` event the live console
mounts on — starts the session and navigates the learner to the existing
console (`#study-session`), then reports the outcome back with exactly one
`plan-architect-result` event. A second activation while a launch is in flight
SHALL be a no-op. The Study Session view's `init()` SHALL register its window
listeners once even when called twice (Alpine auto-init plus `x-init`).

The live console SHALL carry a purpose label (`data-testid="console-purpose-label"`,
`role="status"`, `aria-live="polite"`) that is rendered only for a planning
session, read from `purpose` on the `201` body on a fresh start and from `GET
/api/session/state` on load-time adoption; a focus console SHALL render as
before. `GET /api/session/state` SHALL report `purpose` for every session it
describes — on the live-slot overlay and on the file-only path a CLI session
takes — with an explicit persisted `purpose` winning, a file whose persisted
`mode` is the planning persona's (`persona_mode_for("planning")`) reporting
`planning`, and anything else `focus`; the topic string SHALL never be
consulted. The launch SHALL create no plan and store no plan id (D-11). A
launch refused with the existing `409` conflict shape (`error`,
`study_session_id`, `topic`, `agent`, `detached`, `reattach_url`) SHALL land
the learner on the picker's recovery block with the reattach lever, not on a
second console. The manual **New plan** path SHALL be unchanged.

#### Scenario: One click, one POST, the existing console
- **WHEN** the learner types `SQL window functions` into the subject field and
  activates **Plan with architect**
- **THEN** exactly one `POST /api/session/start` is made with `purpose ==
  "planning"`, `topic == "SQL window functions"`, `origin == "study"`; the
  response is `201` with `purpose == "planning"` and a `ws_url`; the page
  navigates to `#study-session`; exactly one `study-session-start` event with
  `purpose == "planning"` is dispatched; exactly one WebSocket to the `ws_url`
  opens; exactly one console is visible and nothing is mounted in the Plans view

#### Scenario: No subject
- **WHEN** the subject field is empty and **Plan with architect** is activated
- **THEN** the request carries `topic == ""` and the `201` body's `topic` is
  `Study plan`

#### Scenario: Label survives a reload
- **WHEN** a planning session is live and the page is reloaded
- **THEN** the console re-adopts the session from `GET /api/session/state`,
  whose body has `purpose == "planning"`, and exactly one visible
  `console-purpose-label` reads as a planning session, before and after the
  reload

#### Scenario: CLI-started architect is labelled from its persisted mode
- **WHEN** the session state file was written by `studyloop plan architect`
  (`mode == "plan-architect"`, no `purpose` key) and `GET /api/session/state`
  is called
- **THEN** the body has `purpose == "planning"`; a file with `mode == "focus"`
  and `topic == "Study plan"` reports `focus`; a file carrying `purpose ==
  "focus"` beside `mode == "plan-architect"` reports `focus`

#### Scenario: The brief's structure, never its wording
- **WHEN** the fake PTY agent receives the persona of a Web-launched planning
  session
- **THEN** it contains, in order, `## Planning brief`, `### Interview`,
  `### Evidence from the learner's history`, `### Existing plans` and the
  architect body's `## Tooling` section, with `**Mode:** plan-architect` and no
  `Resuming Previous Session` section

#### Scenario: Nothing is created by the launch
- **WHEN** **Plan with architect** is activated
- **THEN** `GET /api/plans` is unchanged, the plans directory holds no new
  document, and the session state carries no `plan_id`

#### Scenario: Conflict is the existing shape with a reattach lever
- **WHEN** a session is live and `POST /api/session/start` is called again with
  `purpose: "planning"`
- **THEN** the response is `409` with `error`, `study_session_id`, `topic`,
  `agent`, `detached` and `reattach_url == <the live session's ws_url>`; and a
  Plans-view launch that meets that `409` shows the picker's `.picker-error`
  with the body's `error` and the `Reattach to this session` control, with no
  terminal mounted

#### Scenario: Manual New plan is unchanged
- **WHEN** the learner uses **New plan**, fills the form and creates the plan
- **THEN** the reader shows the plan, `GET /api/plans` counts one more, and no
  session was started
```
## 5. `tasks.md` — Phase 6 as ticked (and the T3.4 line)

```markdown
## Phase 6 — #15 reconcile and verify

- [x] **T6.1** (RED `87afdcd4` → GREEN `bdc559d5`; specs promoted at archive) `docs/study-plans.md`: "What a plan does
      not do yet" (still claiming broader plan management "remains CLI-only", citing `mcp/tools.py:129`) → **"Plan-aware
      now"** in D-16's bounded language and **"Deliberately not automatic"** — six bullets whose bold lead phrases ARE
      `studyloop.planning.boundaries.NOT_AUTOMATIC` (no live-session binding, no session-driven checkpoints or milestone
      completion, no single-active rule, never a filter, the brain dump stays manual); the architect section names the
      tools it works through and the CLI fallback. `docs/agent-install.md`: the Kiro/Claude harness boundary stated as the
      maintainer's permission decision (recorded in the close-out draft), no longer "tracked as Phase 6, T6.1".
      `agents/mcp/README.md`: "10 MCP tools" → the real 32, the table == the registry. `README.md`, `docs/index.md`,
      `docs/web-ui-guide.md`, `docs/cli-reference.md`, `docs/roadmap.md`: every "not integrated yet" / "do not yet
      influence" claim about the closed gap replaced. **Installer:** `studyloop install agents` prints the nine plan
      tools, the planning-purpose door and the boundary sentence, all derived from `studyloop.mcp.inventory.PLAN_TOOL_NAMES`
      (importable without the `mcp` extra) and `NOT_AUTOMATIC`; uninstall prints no capability claims. **Contract:**
      `tests/test_docs_plan_integration_contract.py` (20) grounds `PLAN_TOOL_NAMES` in the production FastMCP registry
      (exactly the plan-named tools), pins the install-doc table (nine then `record_plan_learning`, lifecycle order),
      the README table and count, the boundary bullets (== the constant, in order), the installer output, D-16's
      language and a stale-claim sweep over six public pages. **Specs (c):** the six delta specs are promoted into
      `openspec/specs/{active-learning-decisions,agent-adapters,cli-surface,live-session-orchestration,mcp-server,web-ui}`
      by `openspec archive plan-application-seam` (the CLI's own merge, no hand-merging); `.openspec.yaml` loses
      `deferred:`; `openspec validate --specs --all` 25 passed; `check-release-consistency.py --release --pre-tag`
      validates the new archive. **Not done here, by design (owner decision):** granting the Kiro/Claude
      harness-launched architects the `studyloop` server — review 4 ruled it a permission-model change for a human.
- [x] **T6.2** (RED `b02bd63a` → GREEN `1129b83e`; parser fix `e605a835`) `scripts/verify/plan_integration.py` per design
      §8: 28 required checks — ruff check/format, pyright, the Bug A doors (4 node ids) and Bug B (2), the guard, the
      golden's sha256 and byte-identity node, the real stdio inventory (`-m integration`) and its in-process twin (32
      unique names, the nine, `record_plan_learning`, `CORE_TOOLS`, names recorded), the seventeen plan suites, the docs
      contract, the ten protected files (`git diff --quiet` vs `3a4f6b01` / `0a20a796`), six `rg` invariants (three
      "used by" expecting exit 0, three "zero" expecting rg's exit 1), the combined journey alone and in the
      `-m integration` run with the stdio smoke, the #14 browser module under `-m e2e`, `node --test`, `openspec
      validate --specs --all`, `mkdocs --strict`, and both packages' full suites. A check that cannot start is a
      FAILURE (exit_code null + error), never N/A; an unexpected success fails too. Unit-tested with an injected runner
      (`tests/test_verify_plan_integration_script.py`, 21). First real run at `3159efe0`: **28/28 ok, exit 0** — but
      empty node counts for `-q` output (the parser required `====` bars), so that receipt was discarded, the parser
      fixed, and the receipt re-run on the final tree: `receipts/verify-<sha>.json` (committed beside this file).
- [x] **T6.3** (`f51d5118`; UAT `a69867bf`, redacted summary `3159efe0`) **Combined journey**
      `tests/test_plan_journey_combined.py` (3, `integration`): one isolated scope shared by both transports —
      `POST /api/session/start {purpose: planning, topic: ""}` through TestClient with the fake agent → 201,
      `purpose == planning`, one `## Planning brief`, no plan on disk; `get_planning_interview` and `create_study_plan`
      through the production FastMCP registry (`mcp.call_tool` on the suite's shared background loop), the interview's
      prompts verbatim in the Web brief, the draft visible through `GET /api/plans`, a preview `evaluate_study_plan`
      with both sinks `not_requested` and the document bytes unchanged, activation over MCP reflected by the Web detail
      route, reconnect keeping the label with no `plan_id`; the ACP transport carrying one brief; the refusal kinds
      surviving the combined process. Every test asserts none of the three nested-event-loop signatures appears in the
      log, the responses or the tool results. Passes alone (3) and with the stdio smoke's pytest-asyncio tests in both
      orders (5). **UAT tier:** `tests/acceptance/uat/test_plan_journeys.py` — three required cells under the strict
      runner against one hermetic world: `architect_launch` (real browser: Plan with architect → labelled console →
      label survives reload → brief structure in the persona the stub agent received → no plan created),
      `mcp_lifecycle` (the real `studyloop-mcp` server over stdio: nine listed, create → activate → evaluate
      `record=true` both sinks `saved` → milestone → history; the same plan read back through the web server),
      `now_with_active_plan` (the Today card's "Advances plan: SQL Windows · milestone 2 …" and `/api/now`'s
      `plan_refs`). Sign-off 3/3, full bundle at the tier's durable root
      (`~/.local/share/studyloop/uat/uat-plan-journeys-20260916-074306-a69867bf`, private, sha256 inventory, rubric
      v1 hash pinned), redacted summary committed as `receipts/uat-plan-journeys-a69867bf.redacted.json`. **What UAT
      proved:** the three doors through the real product surfaces over one shared store, with a fake agent. **What it did
      not:** no architect conversation — no rubric criterion graded, no council seat consulted; the summary says so.
- [x] **T6.4** (`dcfd44e4`) Archify spec updated for the final structure: the `architect session` node between the
      Web routes and the MCP plan tools (Web → `purpose=planning: prepare_planning → brief`; architect ⇢ MCP tools
      dashed "when the harness attaches the server"), the MCP node as nine + `record_plan_learning` (32-tool
      inventory), the now engine's `get_active_guidance(today=)` edge solid and emphasised (was dashed "not yet
      wired"), a fourth guided view "Planning purpose (#13, #14)", the rose card carrying the not-automatic boundary.
      **Receipt** (archify skill, `node ~/.kiro/skills/archify/bin/archify.mjs`): `validate --quality showcase` → ok,
      9/9 artifact checks, composition showcase 0 errors / 0 warnings; `deliver … plan-integration.html --quality
      showcase` → **ok: true**, specification sha256 `f0d461abb7101927024e2ef49bcd470ef06c89c694a4b0a1020d57614f3fef59`
      (9282 bytes), artifact sha256 `688953dee90010e16df42abf3b15481323d4f9c4a150386d60aa0fc4a0cfac7e` (725524
      bytes); `visual-check` → **status: pass**, containment ok at 1440×900, 1600×1000, 1920×1080, 2048×1320
      (scrollHeight == innerHeight at each), readability pass (6px floor), light + dark captures; `visualReview:
      pending` by contract — perceptual review by the implementing agent from the 1440×900 light capture: balanced,
      no edge through an unrelated node, labels clear (three converging edges on the seam's top placed with `labelAt`).
      The `.html` and `.visual-check.*` sidecars stay gitignored and regenerate from the spec.
- [x] **T6.5** (`fd10789e`) Close-out **draft**, not posted:
      `receipts/issue-closeout-draft-2026-09-16.md` — one section per issue #8–#15 and the parent #7, every acceptance
      criterion mapped to a test node id / receipt / commit / promoted spec with an honest status ("partly" for #13's
      MCP-with-CLI-fallback, "mostly" for #14's brief — a subject travels, the brain dump does not; "in-process only" for
      #12's partial-recording refusal over stdio; the D-16 verdict PENDING for #10), the five #7 requirements not fully
      verified named plainly, a proposed PR #20 description, and the thirteen owner decisions still open in one place.
- [ ] ⚖ **Council review 5** (docs seats `openai.gpt-6-astra`, `grok-4.6`, `kimi-k2-thinking`; brief
      `council/brief-review5-2026-09-16.md`, receipts `council/review5/`) on the reconciled docs, the promoted
      specs, the installer text, the verify registry, the UAT summary and the close-out draft; arbitration
      `council/review-5-arbitration-2026-09-16.md`. Then (owner, in the morning) close #7–#15 with the evidence comments
      the draft holds.
```
```markdown
- [x] **T3.4** (engineering deliverable landed `c27a34d5`; **the owner verdict is an owner action, not an agent task** —
      recorded as open item 2 of `receipts/issue-closeout-draft-2026-09-16.md`; ticked at archive so the change can close, with the
      `PENDING` column left honest in the receipt) Human rubric receipt (D-16): five frozen scenarios scored "would I do the primary?", committed
      as `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`. **Receipt landed, scoring
      outstanding** (re-opened by council review 3, F6: a scored rubric is the DoD; an unscored one is not
      "done"). **As landed:** the five scenarios were
      run unattended and the emitted primary + rule-cited rationale recorded per row; the owner-verdict column is
      **PENDING** — no human was present and none was faked. Owner action: replace `PENDING` with yes/no + one
      line per row; a `no` on rows 1–4 is a council finding, not an agent edit. Delta spec: the guidance requirement loses "(not yet
      consumed)" and a new requirement "The now engine is plan-aware with tested ranking rules" carries nine
      scenarios. `docs/study-plans.md`: the now/Today "does not do yet" bullet removed; the learner-facing paragraph
      on plan-aware guidance is T6.1's.
```
## 6. The verification script's registry (`scripts/verify/plan_integration.py --list`) and the first real run

```
ruff-check                                   expect exit 0  uv run --group dev ruff check .
ruff-format                                  expect exit 0  uv run --group dev ruff format --check .
pyright                                      expect exit 0  uv run --group dev pyright
bug-a-readiness-gated-doors                  expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan packages/studyloop/tests/test_web_plans.py::test_markdown_replacement_refuses_an_unready_active_document packages/studyloop/tests/test_plan_application.py::test_create_transition_replace_refusal_payload_is_identical packages/studyloop/tests/test_plan_surface_parity.py::test_activation_refusal_is_identical_via_cli_and_web
bug-b-partial-recording-reported             expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning packages/studyloop/tests/test_planning_evaluation.py::test_successful_checkpoint_db_write_adds_no_warning
architecture-guard                           expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_architecture_plan_seam.py
golden-no-active-sha                         expect exit 0  python:check_golden_sha
golden-no-active-byte-identity               expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_now_plan_guidance.py::test_no_active_plans_json_byte_identical_to_golden
stdio-inventory                              expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_mcp_stdio_smoke.py -m integration
inventory-in-process                         expect exit 0  python:check_inventory_in_process
plan-suites                                  expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_plan_application.py packages/studyloop/tests/test_plan_application_mutations.py packages/studyloop/tests/test_plan_guidance.py packages/studyloop/tests/test_plan_intent_snapshots.py packages/studyloop/tests/test_plan_surface_parity.py packages/studyloop/tests/test_plan_record.py packages/studyloop/tests/test_plan_recording_failures.py packages/studyloop/tests/test_web_plans.py packages/studyloop/tests/test_web_plans_seam.py packages/studyloop/tests/test_cli_plan.py packages/studyloop/tests/test_cli_plan_seam.py packages/studyloop/tests/test_mcp_plan_tools.py packages/studyloop/tests/test_mcp_plan_record_seam.py packages/studyloop/tests/test_mcp_next_action.py packages/studyloop/tests/test_now_plan_guidance.py packages/studyloop/tests/test_session_start_purpose.py packages/studyloop/tests/test_plan_architect_persona.py
docs-contract                                expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_docs_plan_integration_contract.py
protected-files-3a4f6b01                     expect exit 0  git diff --quiet 3a4f6b01 -- packages/studyloop/tests/test_web_plans.py packages/studyloop/tests/test_cli_plan.py packages/studyloop/tests/test_planning_evaluation.py
protected-files-0a20a796                     expect exit 0  git diff --quiet 0a20a796 -- packages/studyloop/tests/test_learning_decision.py packages/studyloop/tests/test_web_now.py packages/studyloop/tests/test_recap_mastery_voice.py packages/studyloop/tests/test_web_session_start_pty.py packages/studyloop/tests/test_web_session_start_acp.py packages/studyloop/tests/test_web_session_ws.py packages/studyloop/tests/test_agent_launcher.py
rg-plan-application-cli                      expect exit 0  rg -n PlanApplication packages/studyloop/src/studyloop/cli
rg-plan-application-web-routes               expect exit 0  rg -n PlanApplication packages/studyloop/src/studyloop/web/routes
rg-plan-application-mcp                      expect exit 0  rg -n PlanApplication packages/studyloop/src/studyloop/mcp
rg-no-adapter-storage-imports                expect exit 1  rg -n studyloop\.planning\.(store|index|authoring|evaluation)\b packages/studyloop/src/studyloop/cli packages/studyloop/src/studyloop/web/routes packages/studyloop/src/studyloop/mcp
rg-no-adapter-storage-imports-from-package   expect exit 1  rg -n from studyloop\.planning import .*\b(store|index|authoring|evaluation)\b packages/studyloop/src/studyloop/cli packages/studyloop/src/studyloop/web/routes packages/studyloop/src/studyloop/mcp
rg-no-focus-literal-under-session-routes     expect exit 1  rg -n build_canonical_persona\("focus" packages/studyloop/src/studyloop/web/routes/session
combined-journey                             expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_plan_journey_combined.py -m integration
integration-combined                         expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_mcp_stdio_smoke.py packages/studyloop/tests/test_plan_journey_combined.py -m integration
browser-journey-e2e                          expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests/test_web_plan_architect_journey.py -m e2e
js-unit                                      expect exit 0  node --test packages/studyloop/tests/js/chunk-text.test.js packages/studyloop/tests/js/generate-panel.test.js packages/studyloop/tests/js/plan-architect-launch.test.js packages/studyloop/tests/js/plans-panel.test.js packages/studyloop/tests/js/session-timer.test.js packages/studyloop/tests/js/settings-panel.test.js packages/studyloop/tests/js/text-entry.test.js packages/studyloop/tests/js/today-panel-plan.test.js packages/studyloop/tests/js/today-panel.test.js
openspec-validate                            expect exit 0  openspec validate --specs --all --no-interactive
mkdocs-strict                                expect exit 0  uv run --extra docs mkdocs build --strict -q
full-suite-studyloop                         expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/studyloop/tests
full-suite-agent-session-tools               expect exit 0  uv run --group dev pytest -q -p no:cacheprovider packages/agent-session-tools/tests
```
First real run at `3159efe0` (before the parser fix): 28/28 checks ok, exit 0, wall clock ~17 min (studyloop suite
376 s, agent-session-tools 534 s with 2146 passed); the studyloop suites' node counts came back empty because `-q`
prints the summary without `====` bars under that package's config — fixed in `e605a835` (3 RED cases), receipt
re-run on the final tree after this review. Design §8 asked for: full suite, ruff check, ruff format --check, pyright,
the Bug A/B node ids, the architecture guard, the no-active golden, the stdio inventory, the rg invariants (three);
review 4 added: the in-process inventory twin, the named plan suites, the ten protected files against two bases,
`record_plan_learning`'s `not_ready:` prefix (covered by the plan suites), `-m integration` stdio, `-m e2e` #14
browser module, JS, `openspec validate`, `mkdocs --strict`.

## 7. The journeys (T6.3)

### `packages/studyloop/tests/test_plan_journey_combined.py` — module docstring and test names

```python
"""The combined Web + MCP plan journey in ONE process (#15, T6.3).

Issue #15's definition of done asks for "representative Web and MCP integration
journeys" that pass "independently and in the combined run" with "no
nested-event-loop ordering regression". This module is that journey: a
planning-purpose Web session (the real ``/api/session/start`` route through
``TestClient``, the fake agent, the real ``PlanApplication`` seam) and the plan
tools dispatched through the same production ``FastMCP`` registry the stdio
server serves — in one pytest process, one isolated scope, with the two
transports' event loops living side by side:

* ``TestClient`` runs the ASGI app on anyio's blocking portal (a thread);
* ``FastMCP.call_tool`` is a coroutine, run here on ``_helpers.run_async``'s
  shared background loop — the same loop every sync fixture in this suite
  uses for ``active.release()``.

Neither may ever call ``asyncio.run`` on a thread that already has a running
loop: the journey asserts that no "event loop is already running" /
"cannot be called from a running event loop" text reaches the log, the
responses or the tool results. Run alone::

    uv run --group dev pytest packages/studyloop/tests/test_plan_journey_combined.py -m integration

and in the combined run, after the stdio smoke's pytest-asyncio tests have
left their loop state behind::

    uv run --group dev pytest packages/studyloop/tests/test_mcp_stdio_smoke.py \
        packages/studyloop/tests/test_plan_journey_combined.py -m integration

Marked ``integration`` like the stdio smoke, so the default run deselects it;
``scripts/verify/plan_integration.py`` runs both forms.
"""
```
```
229:    def test_planning_session_then_mcp_plan_lifecycle_in_one_process(
303:    def test_planning_session_on_the_acp_transport_carries_one_brief(
320:    def test_mcp_refusal_after_a_web_start_is_a_structured_tool_error(
```
### `packages/studyloop/tests/acceptance/uat/test_plan_journeys.py` (new, full)

```python
"""UAT plan journeys (#15, T6.3): the three plan doors, one sign-off, one bundle.

Three cells, each a required sign-off cell under the strict runner
(:mod:`acceptance.uat.strict_runner`, council D-13), run against ONE hermetic
world — one plans directory, one sessions database, one session directory —
shared by every process the journeys start:

``architect_launch``
    The real web UI in a real browser: the Plans view's **Plan with
    architect** button → one ``POST /api/session/start`` with
    ``purpose: "planning"`` → the existing Study Session console, labelled as
    a planning session; the label survives a reload; no plan document exists
    afterwards. The "agent" is the PTY stub every ``test_web_*`` module uses
    (``echo agent-stub-ready; exec cat``), which also copies the persona file
    it was handed into a directory this module owns, so the brief's
    STRUCTURE is evidence — never its wording (council D-16: no simulated
    mentor is graded; none is graded here).

``mcp_lifecycle``
    The real ``studyloop-mcp`` server as a subprocess over stdio, pointed at
    the SAME plans directory and database, driven with the official ``mcp``
    client: the nine plan tools listed, ``create_study_plan`` →
    ``set_study_plan_status active`` → ``evaluate_study_plan record=true``
    (both sinks ``saved``) → ``set_study_plan_milestone`` → the checkpoint
    visible through ``get_study_plan include_history=true``; then the SAME
    plan read back through the web server's ``GET /api/plans/<id>``.

``now_with_active_plan``
    The Today view in the browser, now that a ready active plan exists: the
    one next action carries "Advances plan: <title …>", and ``/api/now`` names
    the plan in the primary's ``plan_refs`` with ``active_plans`` listed —
    plan-aware guidance with tested ranking rules (D-16), observed through
    the product surface rather than the engine.

The last test applies the strict sign-off rule to the recorded outcomes
(zero cells or any skipped/failed required cell → FAIL) and writes the full
evidence bundle (:mod:`acceptance.uat.bundle`) to the durable root — private,
atomic, hash-pinned — plus a redacted summary through the pinned redaction
rules. What this run proves is the three journeys' mechanics through the real
surfaces with a fake agent; it grades no pedagogy (the rubric's criteria are
about a mentor's conversation, and there is no mentor here), so
``per_criterion_scores`` is empty and the arbitration note says so.

Gated behind ``STUDYLOOP_ACC=1`` and ``STUDYLOOP_UAT=1`` like every test in
this tree::

    just testuat "" scripted packages/studyloop/tests/acceptance/uat/test_plan_journeys.py
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
pytest.importorskip("mcp")

# tests/acceptance/uat/test_plan_journeys.py -> tests/
_tests_dir = Path(__file__).resolve().parents[2]
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from _helpers import run_async  # noqa: E402
from _playwright_helpers import (  # noqa: E402
    _isolated_child_env,
    auth_context_fixture_factory,
    effective_credentials,
    start_web_server,
)
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from acceptance.uat.bundle import (  # noqa: E402
    ManifestFields,
    RunCounts,
    resolve_durable_root,
    write_bundle,
)
from acceptance.uat.redaction import load_redaction_rules, redact_summary  # noqa: E402
from acceptance.uat.rubric import load_rubric  # noqa: E402
from acceptance.uat.strict_runner import CellOutcome, evaluate_signoff  # noqa: E402
from studyloop.mcp.inventory import PLAN_TOOL_NAMES  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from playwright.sync_api import BrowserContext, Page

pytestmark = [pytest.mark.acceptance, pytest.mark.uat, pytest.mark.timeout(240)]

#: Distinct from every other fixed port (tests/test_port_uniqueness.py).
WEB_PORT = 18627
BASE = f"http://127.0.0.1:{WEB_PORT}"

REQUIRED_CELLS = ("architect_launch", "mcp_lifecycle", "now_with_active_plan")

PLAN_ID = "sql-windows"
PLAN_TITLE = "SQL Windows"
ANSWERS: dict[str, object] = {
    "why": "Ship analytics queries without help",
    "success": ["Write a RANK() query unaided"],
    "topics": ["sql"],
    "milestones": [
        {"title": "OVER clause", "concepts": ["window function"]},
        {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
    ],
}

#: Persona section headings whose presence proves the brief's STRUCTURE.
BRIEF_STRUCTURE = (
    "## Planning brief",
    "### Interview",
    "### Evidence from the learner's history",
    "### Existing plans",
    "## Tooling",
)

#: Outcomes and evidence accumulate across the cells; the sign-off test reads them.
RESULTS: dict[str, CellOutcome] = {}
EVIDENCE: dict[str, bytes] = {}


# ---------------------------------------------------------------------------
# One world, one web server, one MCP environment
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> Generator[dict[str, Path], None, None]:
    root = Path(tempfile.mkdtemp(prefix="studyloop-uat-plan-journeys-"))
    dirs = {
        "root": root,
        "plans": root / "study-plans",
        "sessions": root / "session-dir",
        "personas": root / "personas-seen",
        "db": root / "sessions.db",
    }
    for key, path in dirs.items():
        if key != "db":
            path.mkdir(parents=True, exist_ok=True)
    yield dirs


def _shared_env(world: dict[str, Path]) -> dict[str, str]:
    """The keys BOTH children must agree on for the journeys to meet."""
    return {
        "STUDYLOOP_PLANS_DIR": str(world["plans"]),
        "STUDYLOOP_DB": str(world["db"]),
    }


@pytest.fixture(scope="module")
def web_server(world: dict[str, Path]):
    agent_cmd = (
        f'cp "{{persona_file}}" "{world["personas"]}/$(date +%s%N).md"; '
        "echo agent-stub-ready; exec cat"
    )
    proc = start_web_server(
        WEB_PORT,
        extra_env={
            **_shared_env(world),
            "STUDYLOOP_TEST_AGENT_CMD": agent_cmd,
            "STUDYLOOP_SESSION_DIR": str(world["sessions"]),
        },
    )
    try:
        yield proc
    finally:
        _end_session_over_http()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture(scope="module")
def mcp_env(world: dict[str, Path]) -> dict[str, str]:
    """A hermetic environment for the stdio server, sharing only the plans
    directory and the database with the web server."""
    return _isolated_child_env(_shared_env(world))


@pytest.fixture(scope="module")
def mcp_transcript(web_server, mcp_env: dict[str, str]) -> dict[str, Any]:
    """Run the MCP lifecycle once for the module, on the suite's background loop.

    A fixture rather than a step inside one test because pytest groups the
    browser-parametrised tests (``[chromium]``) together and would otherwise
    run the Today cell before the MCP cell had created the plan it reads. Any
    failure here surfaces as an ERROR on both dependent cells, which the
    strict runner then reports as "never ran" — a fail, never a pass.
    """
    _ = web_server
    return run_async(_mcp_lifecycle(mcp_env))


auth_context = auth_context_fixture_factory()


@pytest.fixture()
def page(web_server, auth_context: BrowserContext) -> Generator[Page, None, None]:
    _ = web_server
    page = auth_context.new_page()
    try:
        yield page
    finally:
        page.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http(path: str, method: str = "GET") -> Any:
    user, password = effective_credentials()
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    if password:
        import base64

        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def _end_session_over_http() -> None:
    with contextlib.suppress(Exception):
        _http("/api/session/end", method="POST")


@contextlib.contextmanager
def _cell(name: str) -> Iterator[None]:
    """Record the cell's outcome for the strict runner; a failure stays a failure."""
    try:
        yield
    except BaseException:
        RESULTS[name] = CellOutcome.FAILED
        raise
    RESULTS[name] = CellOutcome.PASSED


def _evidence(name: str, payload: Any) -> None:
    EVIDENCE[name] = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _goto_plans(page: Page) -> None:
    page.goto(f"{BASE}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
    page.wait_for_function(
        "() => window.Alpine.store('plans') && window.Alpine.store('plans').initDone === true",
        timeout=8000,
    )
    page.locator('[data-testid="plan-architect"]').wait_for(state="visible", timeout=8000)
    # The Plans-view door goes through the Study Session timer's one start path,
    # which refuses (with the picker's own hint) until the picker has resolved an
    # agent. Wait for that resolution as a learner would see the picker fill in;
    # a click before it is a structured refusal, not a launch.
    page.wait_for_function(
        """() => {
          const root = document.querySelector('[x-data="sessionTimer()"]');
          if (!root) return false;
          const d = window.Alpine.$data(root);
          return !!(d && d.agent);
        }""",
        timeout=15000,
    )


def _wait_for_console(page: Page) -> None:
    page.wait_for_function("() => window.location.hash === '#study-session'", timeout=10000)
    page.wait_for_function(
        """() => {
          const selector = '.agent-console[x-data="liveAgentConsole()"]';
          return [...document.querySelectorAll(selector)].some((el) => {
            const d = window.Alpine.$data(el);
            return d && d.terminalMode === 'xterm' && d.connected === true;
          });
        }""",
        timeout=20000,
    )


def _visible_purpose_labels(page: Page) -> list[str]:
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="console-purpose-label"]')]
             .filter((el) => el.offsetParent !== null
                             && window.getComputedStyle(el).display !== 'none')
             .map((el) => el.textContent.trim())"""
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_tests_dir.parents[1], capture_output=True, text=True, check=True
    ).stdout.strip()


def _structured(result) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    assert not result.isError, result
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# The cells
# ---------------------------------------------------------------------------


class TestPlanJourneys:
    def test_architect_launch(self, page: Page, world: dict[str, Path]) -> None:
        with _cell("architect_launch"):
            plans_before = sorted(p.name for p in world["plans"].glob("*.md"))
            _goto_plans(page)
            posts: list[dict[str, Any]] = []

            def _on_response(response) -> None:  # type: ignore[no-untyped-def]
                request = response.request
                if request.method == "POST" and request.url.endswith("/api/session/start"):
                    posts.append(
                        {"body": json.loads(request.post_data or "{}"), "status": response.status}
                    )

            page.on("response", _on_response)
            page.locator('[data-testid="plan-architect-subject"]').fill("SQL window functions")
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.endswith("/api/session/start"),
                timeout=20000,
            ):
                page.get_by_role("button", name="Plan with architect").click()
            _wait_for_console(page)
            page.wait_for_timeout(600)
            page.remove_listener("response", _on_response)

            assert len(posts) == 1, posts
            assert posts[0]["status"] == 201 and posts[0]["body"]["purpose"] == "planning"
            labels = _visible_purpose_labels(page)
            assert labels and all("planning" in label.lower() for label in labels), labels

            # Reload: the label is derived from persisted state, not the click.
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_function("() => !!window.Alpine", timeout=5000)
            state = _http("/api/session/state")
            assert state["purpose"] == "planning"
            assert state["topic"] == "SQL window functions"
            assert "plan_id" not in state

            # The persona the architect was handed has the brief's structure.
            seen = sorted(world["personas"].glob("*.md"))
            assert len(seen) == 1, seen
            persona = seen[0].read_text(encoding="utf-8")
            positions = [persona.find(heading) for heading in BRIEF_STRUCTURE]
            assert all(p >= 0 for p in positions), dict(
                zip(BRIEF_STRUCTURE, positions, strict=True)
            )
            assert positions == sorted(positions), "brief sections out of order"
            assert persona.count("## Planning brief") == 1

            # The click created nothing: the plan documents are what they were.
            plans_after = sorted(p.name for p in world["plans"].glob("*.md"))
            assert plans_after == plans_before, (plans_before, plans_after)
            assert sorted(row["plan_id"] for row in _http("/api/plans")["plans"]) == [
                Path(name).stem for name in plans_before
            ]

            EVIDENCE["architect_launch/screenshot.png"] = page.screenshot()
            _evidence(
                "architect_launch/evidence.json",
                {
                    "post": posts[0],
                    "purpose_labels": labels,
                    "session_state_after_reload": state,
                    "brief_structure_positions": dict(zip(BRIEF_STRUCTURE, positions, strict=True)),
                    "plans_before_click": plans_before,
                    "plans_after_click": plans_after,
                },
            )
            _end_session_over_http()

    def test_mcp_lifecycle(self, mcp_transcript: dict[str, Any], world: dict[str, Path]) -> None:
        with _cell("mcp_lifecycle"):
            transcript = mcp_transcript
            assert set(PLAN_TOOL_NAMES) <= set(transcript["tools_listed"])
            assert transcript["created"]["plan"]["status"] == "draft"
            assert transcript["created"]["readiness"]["ready"] is True
            assert transcript["activated"]["plan"]["status"] == "active"
            recorded = transcript["recorded"]
            assert recorded["db_write"] == "saved" and recorded["document_write"] == "saved"
            assert recorded["recording_complete"] is True
            assert transcript["milestone"]["milestones"][0]["done"] is True
            assert len(transcript["history"]["checkpoints"]) == 1

            # The same plan, through the web server: one store, one seam.
            detail = _http(f"/api/plans/{PLAN_ID}")
            assert detail["plan"]["status"] == "active"
            assert detail["plan"]["milestone_done"] == 1
            document = (world["plans"] / f"{PLAN_ID}.md").read_text(encoding="utf-8")
            assert "- [x] **OVER clause**" in document
            assert "- [ ] **RANK vs DENSE_RANK**" in document

            _evidence(
                "mcp_lifecycle/transcript.json",
                {**transcript, "web_detail": detail},
            )
            EVIDENCE["mcp_lifecycle/plan-document.md"] = document.encode("utf-8")

    def test_now_with_active_plan(self, page: Page, mcp_transcript: dict[str, Any]) -> None:
        assert mcp_transcript["activated"]["plan"]["status"] == "active"
        with _cell("now_with_active_plan"):
            page.goto(f"{BASE}/")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_function("() => !!window.Alpine", timeout=5000)
            page.evaluate("() => window.Alpine.store('nav').go('today')")
            card = page.locator(".today-card:not(.today-starter)")
            card.wait_for(state="visible", timeout=10000)
            plan_line = page.locator(".today-plan")
            plan_line.wait_for(state="visible", timeout=10000)
            label = plan_line.inner_text()
            assert PLAN_TITLE in label, label

            now = _http("/api/now")
            assert now["starter"] is False
            assert [p["plan_id"] for p in now["active_plans"]] == [PLAN_ID]
            refs = now["primary"]["plan_refs"]
            assert refs and refs[0]["plan_id"] == PLAN_ID, now["primary"]
            # Milestone 0 is done, so the plan's next milestone is index 1.
            assert refs[0]["milestone_index"] == 1
            assert now["primary"]["source"].startswith(f"study_plan:{PLAN_ID}:")

            EVIDENCE["now_with_active_plan/screenshot.png"] = page.screenshot()
            _evidence(
                "now_with_active_plan/evidence.json",
                {"today_card_plan_line": label, "now": now},
            )

    def test_signoff_and_evidence_bundle(self, world: dict[str, Path]) -> None:
        """Strict sign-off over the three cells, then the bundle and its redacted summary."""
        verdict = evaluate_signoff(required_cells=REQUIRED_CELLS, results=RESULTS)
        assert verdict.passed, verdict.reasons

        rubric = load_rubric()
        rules = load_redaction_rules()
        repo_sha = _git("rev-parse", "--short", "HEAD")
        dirty = bool(_git("status", "--porcelain"))
        run_at = datetime.now(UTC)
        run_id = f"uat-plan-journeys-{run_at:%Y%m%d-%H%M%S}-{repo_sha}"
        counts = RunCounts(
            passed=sum(1 for o in RESULTS.values() if o is CellOutcome.PASSED),
            skipped=sum(1 for o in RESULTS.values() if o is CellOutcome.SKIPPED),
            failed=sum(1 for o in RESULTS.values() if o is CellOutcome.FAILED),
        )
        fields = ManifestFields(
            run_id=run_id,
            date=run_at.isoformat(timespec="seconds"),
            repo_sha=repo_sha,
            dirty=dirty,
            harness="fake-agent",
            harness_version=None,
            actor_backend="scripted",
            actor_model=None,
            platform=sys.platform,
            rubric_version=str(rubric.version),
            rubric_hash=rubric.content_hash,
            counts=counts,
        )
        run_dir = resolve_durable_root(real_env=os.environ, run_id=run_id)
        files = dict(EVIDENCE)
        files["cells.json"] = (
            json.dumps({name: str(outcome) for name, outcome in RESULTS.items()}, indent=2) + "\n"
        ).encode("utf-8")
        manifest_path = write_bundle(run_dir, fields, files=files)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["counts"] == counts.as_dict()
        for name in files:
            assert name in manifest["file_inventory"]

        summary = redact_summary(
            {
                "run_id": run_id,
                "date": fields.date,
                "repo_sha": repo_sha,
                "harness": "fake-agent",
                "harness_version": None,
                "actor_backend": "scripted",
                "actor_model": None,
                "rubric_version": rubric.version,
                "rubric_hash": rubric.content_hash,
                "journeys": {name: str(outcome) for name, outcome in RESULTS.items()},
                "per_criterion_scores": {},
                "arbitration_note": (
                    "Mechanics sign-off only: the three plan journeys passed through the "
                    "real web UI, the real stdio MCP server and the real now engine with a "
                    "fake (stub) agent. No mentor conversation took place, so no rubric "
                    "criterion was graded and no council seat was consulted; the rubric "
                    "version and hash are recorded so a graded run can cite the same document."
                ),
                "private_bundle_digest": "sha256:"
                + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                # Deliberately outside the allowlist; must be dropped by the rules.
                "absolute_bundle_path": str(run_dir),
            },
            rules,
        )
        assert "absolute_bundle_path" not in summary
        (run_dir / "redacted-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nUAT plan-journeys bundle: {run_dir}")


async def _mcp_lifecycle(env: dict[str, str]) -> dict[str, Any]:
    """The MCP door, over the real stdio transport, in lifecycle order."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "studyloop.mcp.server"], env=env
    )
    transcript: dict[str, Any] = {}
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        transcript["server"] = init.serverInfo.name
        tools = await session.list_tools()
        transcript["tools_listed"] = sorted(t.name for t in tools.tools)
        transcript["created"] = _structured(
            await session.call_tool(
                "create_study_plan",
                {"title": PLAN_TITLE, "answers": ANSWERS, "plan_id": PLAN_ID},
            )
        )
        transcript["activated"] = _structured(
            await session.call_tool(
                "set_study_plan_status", {"plan_id": PLAN_ID, "status": "active"}
            )
        )
        transcript["recorded"] = _structured(
            await session.call_tool(
                "evaluate_study_plan", {"plan_id": PLAN_ID, "phase": "start", "record": True}
            )
        )
        transcript["milestone"] = _structured(
            await session.call_tool(
                "set_study_plan_milestone", {"plan_id": PLAN_ID, "index": 0, "done": True}
            )
        )
        transcript["history"] = _structured(
            await session.call_tool("get_study_plan", {"plan_id": PLAN_ID, "include_history": True})
        )
    return transcript
```
### `docs/architecture/plan-integration/receipts/uat-plan-journeys-a69867bf.redacted.json`

```json
{
  "actor_backend": "scripted",
  "actor_model": null,
  "arbitration_note": "Mechanics sign-off only: the three plan journeys passed through the real web UI, the real stdio MCP server and the real now engine with a fake (stub) agent. No mentor conversation took place, so no rubric criterion was graded and no council seat was consulted; the rubric version and hash are recorded so a graded run can cite the same document.",
  "date": "2026-09-16T07:43:06+00:00",
  "harness": "fake-agent",
  "harness_version": null,
  "journeys": {
    "architect_launch": "passed",
    "mcp_lifecycle": "passed",
    "now_with_active_plan": "passed"
  },
  "per_criterion_scores": {},
  "private_bundle_digest": "sha256:bdab3a536290c57a22eb95c00844ad64edc39eebf729dd5d34fea7905e9d0f48",  # pragma: allowlist secret (a content digest)
  "repo_sha": "a69867bf",
  "rubric_hash": "4dfdc757e4ee0e6011ea52a9662531eea64cc6ff941714c92f33d76c11223c34",  # pragma: allowlist secret (a content digest)
  "rubric_version": 1,
  "run_id": "uat-plan-journeys-20260916-074306-a69867bf"
}
```
## 8. The close-out draft (full) — `receipts/issue-closeout-draft-2026-09-16.md`

```markdown
# Plan integration (#7–#15) — issue close-out DRAFT · 2026-09-16

**Status: DRAFT, not posted.** Written unattended by the Phase-6 agent for the owner to post in the
morning. Nothing here has been sent to GitHub: no issue closed, no comment left, PR #20 untouched. Every
claim below names the test node id, receipt or commit that backs it, and every criterion that is *not*
met is marked so rather than rounded up. Branch `fix/plan-integration-bugs`, local only; the tip at the
time of writing is the commit that adds this file (the verification receipt for the final tree is
`receipts/verify-<sha>.json` beside it).

Legend for the evidence column: `T:` a pytest node id or module under `packages/studyloop/tests/`;
`R:` a receipt under `docs/architecture/plan-integration/`; `C:` a commit on the branch;
`S:` a normative spec under `openspec/specs/` (promoted from the change's deltas at archive time).

Receipts that back several issues at once:

- `R: receipts/verify-<sha>.json` — the D-15 verification receipt: 28 required checks, every exit
  status and pytest node count, written by `scripts/verify/plan_integration.py` (first real run at
  `3159efe0`: 28/28 ok, exit 0; re-run on the final tree, committed beside this draft).
- `R: receipts/uat-plan-journeys-a69867bf.redacted.json` — the UAT strict sign-off over the three plan
  doors (browser architect launch, real stdio MCP lifecycle, Today with an active plan), 3/3 required
  cells, fake agent; private bundle digest `sha256:bdab3a53…`.
- `R: council/review-{1,2,3,4}-arbitration-*.md` — four code-review gates, all `GATE: ACCEPT`, every
  🔴/🟡 reproduced before acceptance.

---

## #8 — Plan integration 1: Centralize reads and activation

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Plan summaries and details are returned as immutable, serialization-ready views | yes | `T: test_plan_application.py::test_views_are_immutable_and_json_fresh`; `PlanningBrief` deep-freeze (review-1 F2, `C: dc7de0be`) |
| CLI and Web list, inspect, and activation paths use PlanApplication | yes | `C: e16340ca` (web), `C: 1d071758` (cli); `T: test_architecture_plan_seam.py` (30) — 0 violations over 67 adapter modules; verify checks `rg-plan-application-{cli,web-routes,mcp}` |
| Create-and-activate, lifecycle activation, and imported active documents enforce identical readiness rules | yes | `T: test_plan_application.py::test_create_transition_replace_refusal_payload_is_identical`; `T: test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan`, `::test_markdown_replacement_refuses_an_unready_active_document` (the Bug A RED, `3a4f6b01`); `T: test_plan_surface_parity.py::test_activation_refusal_is_identical_via_cli_and_web`; review-1 F1 closed the compound-PATCH door (`C: 705ba58b`) |
| Markdown remains authoritative and index refresh remains best-effort and recoverable | yes | `T: test_plan_application.py` (store writes tmp + rename; `PlanApplication.reindex()`); `S: active-learning-decisions` "Activation is readiness-gated on every entry path" |
| Domain failures contain no CLI, HTTP, or MCP types | yes | `planning/errors.py`; `T: test_cli_plan_seam.py` (`_fail_for` maps six domain errors), `T: test_web_plans_seam.py` (status mapping in one place), `T: test_mcp_plan_tools.py` (`_plan_tool_error`) |

DoD: protected suites `test_web_plans.py`, `test_cli_plan.py`, `test_planning_evaluation.py` are
byte-identical to `3a4f6b01` (verify check `protected-files-3a4f6b01`); normative specs promoted at
archive; working tree clean at the tip.

## #9 — Plan integration 2: Centralize mutations and checkpoints

| Acceptance criterion | Met | Evidence |
|---|---|---|
| CLI and Web no longer mutate Study Plans directly through the persistence layer | yes | `T: test_architecture_plan_seam.py` (guard + 14 planted bypasses rejected; `C: 5693e35c`, review-2 G7 `C: 59ab1e23`); `rg 'readiness\(|save_plan' web/routes/plans.py` → 0 |
| Plan identifier and creation time survive revisions and validated document replacement | yes | `T: test_plan_application.py::test_replace_preserves_id_and_created`, `::test_revise_preserves_id_and_created_and_bumps_updated` |
| Milestone changes set an explicit done value and are idempotent under retries | yes | `T: test_plan_application_mutations.py::test_set_milestone_done_is_idempotent`, `::test_set_unknown_milestone_raises_invalid_milestone`; Web toggle → `SetMilestone` (`C: da0026f9`, review-2 G6) |
| Checkpoint results distinguish complete recording from partial Markdown or SQLite writes | yes | Bug B `C: c16ffa35` + `T: test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning`, `::test_successful_checkpoint_db_write_adds_no_warning`; `T: test_plan_application_mutations.py::test_assess_db_failure_reports_failed_sink_and_returns_evaluation`, `::test_assess_document_failure_reported_independently`; review-2 G8 both-sinks-failed (`C: def5c561`) |
| Deletion retains checkpoint history and returns an immutable result view | yes | `T: test_plan_application_mutations.py::test_delete_retains_checkpoint_history`, `::test_delete_returns_delete_result_and_document_gone`, `::test_delete_without_confirm_raises_invalid_field` |
| Transport adapters map shared domain failures without reimplementing lifecycle policy | yes | `T: test_cli_plan_seam.py` (20), `T: test_web_plans_seam.py` (11), `T: test_mcp_plan_record_seam.py` (7) |

DoD: `T: test_plan_recording_failures.py` (6) covers partial checkpoint failures on an isolated DB;
store/evaluation/CLI plan/Web plan suites green in `verify: plan-suites` and `full-suite-studyloop`.

## #10 — Plan integration 3: Make Now plan-aware end to end

| Acceptance criterion | Met | Evidence |
|---|---|---|
| No-active-plan recommendations remain backward-compatible | yes | `T: test_now_plan_guidance.py::test_no_active_plans_json_byte_identical_to_golden`; golden `tests/golden/now_plan_no_active.json` sha256 `ec451ce8…` unchanged (verify `golden-no-active-sha`) |
| Matching due work and synthesized next-milestone actions carry explicit plan and milestone references | yes | `::test_matching_due_concept_outranks_unrelated_same_urgency`, `::test_synthesizes_milestone_when_no_candidate_represents_it`; review-3 F1 refs on deferred/unready plans carry `None` (`C: 64dc09f7`) |
| Urgent reviews and fresh struggles can still outrank new milestone work | yes | `::test_unrelated_more_urgent_due_outranks_new_milestone`, `::test_weak_due_still_beats_overdue_synthesised_milestone` |
| Multiple active plans, exact normalized matching, completed plans, malformed plans, and low-energy deferral are deterministic | yes | `::test_one_action_keeps_every_matching_plan_ref_ordered`, `::test_milestone_without_concepts_does_not_substring_match`, `::test_fully_checked_active_plan_emits_completion_not_candidate`, `::test_energy_below_floor_defers_new_milestone_keeps_repair`, `::test_guidance_failure_warns_and_logs_without_failing_now`; `T: test_plan_guidance.py::test_malformed_plan_browse_matches_store_list` |
| At least one eligible plan-backed action remains among primary and alternates when constraints permit it | yes | `::test_preserves_one_plan_backed_action_when_energy_allows`, `::test_plan_backed_guarantee_respects_time_limit` |
| CLI, Web Today, recap, and MCP consume one additive recommendation contract | yes | `::test_api_now_carries_plan_guidance_end_to_end`, `::test_cli_now_renders_plan_relevance_and_energy_deferral`, `::test_recap_shows_plan_context_without_reranking`, `::test_cli_recap_rich_panel_shows_engine_plan_context`; `tests/js/today-panel-plan.test.js`; UAT cell `now_with_active_plan` (Today card "Advances plan: SQL Windows · milestone 2 …" through a real browser) |
| MCP get_next_action gains interleave parity with CLI and Web | yes | `T: test_mcp_next_action.py` (10; `C: c30330a0`) |

DoD: no surface reads plans independently (guard; `::test_guidance_read_once_with_no_checkpoint_history_calls`);
docs now describe the behaviour (`docs/study-plans.md` "Plan-aware now", `docs/web-ui-guide.md` Today,
`docs/cli-reference.md`; pinned by `T: test_docs_plan_integration_contract.py`, `C: bdc559d5`).
**Not met — owner action:** the D-16 five-scenario human rubric
(`R: receipts/now-rubric-2026-09-16.md`) has its "would I do the primary?" column **PENDING**; the
scenarios were run and recorded, the judgement was not faked. T3.4 in `tasks.md` is ticked for the
engineering deliverable with the verdict named as an owner action.

## #11 — Plan integration 4: Add MCP discovery and authoring

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Register the six tools | yes | `C: 5a03b094`; `T: test_mcp_stdio_smoke.py::test_full_handshake_list_tools_and_call` (real transport, exactly 32 names, the nine present) |
| Every tool delegates to PlanApplication and returns its immutable views | yes | `T: test_mcp_plan_tools.py` (121) with `forbid_store` under every delegation test |
| Readiness refusal and domain failures map to useful ToolError responses | yes | `T: test_mcp_plan_tools.py` (`not_ready:` with blockers + pause-or-repair hint; `conflict:`, `invalid:`, `not_found:`, `invalid_id:`, `invalid_milestone:`, `plan_error:`) ; `T: test_plan_journey_combined.py::TestCombinedJourney::test_mcp_refusal_after_a_web_start_is_a_structured_tool_error` |
| Structured revision is the normal agent mutation path; raw Markdown replacement is not required | yes | `update_study_plan` → `RevisePlan`; `overwrite` and raw Markdown not exposed (D-4, D-9 pins in `test_mcp_plan_tools.py`) |
| Tool schemas support deterministic discovery and do not expose storage paths or reindex administration | yes | schema pins in `test_mcp_plan_tools.py`; inventory is exactly the nine + `record_plan_learning` among 32 (`T: test_docs_plan_integration_contract.py::test_plan_tool_constant_is_exactly_the_registry_plan_tools`) |

DoD: the real stdio handshake lists the tools and *calls* them — `list_courses` in the smoke test, and the
plan tools themselves in the UAT `mcp_lifecycle` cell (create → activate → evaluate record → milestone →
history over real stdio). Docs: `docs/agent-install.md` "Study-plan tools over MCP" (discovery →
activation journey); `agents/mcp/README.md` now lists all 32.

## #12 — Plan integration 5: Add MCP progression and deletion

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Register `set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` | yes | `C: b1e11e78`; stdio smoke asserts exactly 32 with the nine |
| Milestone changes accept an explicit done value and remain idempotent under retries | yes | `test_mcp_plan_tools.py` retry-idempotent pins; UAT `mcp_lifecycle` sets milestone 0 done over stdio and the document reads `- [x] **OVER clause**` |
| Evaluation distinguishes preview from record and accepts an optional study identifier | yes | `test_mcp_plan_tools.py` preview writes nothing / record reports sinks; `T: test_plan_journey_combined.py` step 4 (preview: both sinks `not_requested`, document bytes unchanged); UAT `mcp_lifecycle` (record: both `saved`, `recording_complete`) |
| Partial checkpoint writes return explicit warnings and never claim complete recording | yes, in-process | `test_mcp_plan_tools.py` failed-sink responses (`recording_complete: false` + warning). **Not exercised over the real stdio transport** — a failing sink needs a monkeypatched writer, which the subprocess cannot receive; the wire shape is the same `to_json_dict()` the in-process test pins |
| Deletion requires explicit confirmation and retains checkpoint history | yes | `test_mcp_plan_tools.py`; `T: test_plan_journey_combined.py` (refused without `confirmed=True`, document present; confirmed delete → Web 404) |

DoD: `record_plan_learning` folded onto `_plan_tool_error` (`not_ready:` prefix — an intentional, reported
wording change); `docs/agent-install.md` examples use the retry-safe operations.

## #13 — Plan integration 6: Launch planning-purpose agent sessions

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Session launch accepts planning purpose while normal study remains the default | yes | `T: test_session_start_purpose.py` (25): `::test_default_purpose_is_focus_and_unchanged`, `::test_unknown_purpose_is_rejected_structurally`; `C: 4fc51250` |
| Planning purpose selects the architect persona, shared protocol, and evidence-grounded planning brief | yes | `::test_planning_purpose_selects_plan_architect_persona_with_brief_section`; brief budget (review-4 F1, `C: 8f9b6011`); `T: test_plan_journey_combined.py` (the MCP interview's prompts verbatim in the Web brief — one seed) |
| PTY and ACP launch paths use one purpose/persona resolver | yes | `::test_pty_and_acp_use_one_resolver`; verify `rg-no-focus-literal-under-session-routes` (0 hits) |
| Starting an architect conversation creates no plan and stores no live-session plan identifier | yes | `::test_planning_launch_creates_no_plan_and_no_plan_id`; `T: test_web_plan_architect_journey.py::test_starting_the_architect_creates_no_plan`; UAT `architect_launch` (plan documents unchanged by the click) |
| Existing one-session conflict, reconnect, error, and cleanup behavior is preserved | yes | `::test_purpose_persisted_for_reconnect_label`, `::test_brief_failure_releases_session_claim` (both transports); `T: test_web_plan_architect_journey.py::test_conflict_returns_structured_error_and_offers_reattach`; protected transport suites byte-identical to `0a20a796` (verify `protected-files-0a20a796`) |
| The architect can use MCP authoring tools with the CLI retained as a harness fallback | **partly** | Persona: `T: test_plan_architect_persona.py` (16) — the nine named, MCP before CLI, lifecycle guards stated (`C: 6ba76757`). **Boundary:** the harness-launched Kiro (`study-plan-architect.json`, no `mcpServers`) and Claude Code (`tools: Read, Write, Grep, Bash`) definitions do not attach the `studyloop` server, so an architect started from those two takes the CLI fallback; a Web-launched architect uses whatever its agent process has. Disclosed in `docs/agent-install.md`; the permission decision is the owner's (below) |

DoD: fake-agent tests, no paid calls (all of the above); reconnect state externally observable
(`GET /api/session/state.purpose`, also for a CLI-started architect via the persisted persona mode —
`::TestReconnectLabelFromPersistedMode`); `S: live-session-orchestration` "Session purpose",
`S: agent-adapters` "Persona resolution by purpose" / "Architect persona prefers the MCP plan tools".

## #14 — Plan integration 7: Add the Web architect journey

| Acceptance criterion | Met | Evidence |
|---|---|---|
| The Plans view exposes a clear Plan with architect action | yes | `T: test_web_plan_architect_journey.py::test_plan_with_architect_action_posts_purpose_planning_and_navigates_to_console` (Playwright, real server, fake agent; `C: 7ad39941`) |
| Successful launch navigates to the existing live console and labels planning purpose correctly | yes | `::test_console_is_labelled_planning_and_label_survives_reconnect`; UAT `architect_launch` label "Planning session — study-plan architect" |
| The architect receives interview questions, evidence seeds, existing-plan summaries, and optional brain dump | **mostly** | `::test_brief_structure_present_not_wording` (the three brief sections in the persona the fake agent received). **The optional brain dump is not carried:** the Plans-view door takes an optional *subject* (the topic), not the free-text brain dump; the brain dump stays with the manual form (documented under "Deliberately not automatic") |
| Refresh and reconnect preserve planning-purpose context | yes | `::test_console_is_labelled_planning_and_label_survives_reconnect`; UAT `architect_launch` reload |
| The manual create/edit/checkpoint interface remains fully functional | yes | `::test_manual_new_plan_form_still_works`; `T: test_web_plans.py` (27) unchanged |
| Exactly one addressed console and WebSocket handle the planning session | yes | `::test_one_console_one_websocket`; `tests/js/plan-architect-launch.test.js` (14: one POST, one `study-session-start`, `init()` twice still one listener — the double-listener bug found and fixed in `C: 7ad39941`) |

DoD: browser tests cover launch, fallback, conflict, reconnect and structured errors; **"cancellation" is
covered only as "a second click in flight is a no-op" (JS) and the existing end-session path — there is
no dedicated browser test that abandons the launch mid-flight.** Accessibility: `aria-busy`,
`aria-describedby`, `role="status" aria-live="polite"` status region, screen-reader label on the subject
input (`C: 7ad39941`; not audited with a screen reader). **The one-question-at-a-time protocol is not
proven by a live agent:** every journey uses the fake agent, so the protocol is asserted only as
persona text. `S: web-ui` "Plan with architect journey" (8 scenarios).

## #15 — Plan integration 8: Reconcile release contract and verify

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Study Plans, Now, Today, Web, MCP, and installer language describe the implemented automatic boundaries accurately | yes | `C: bdc559d5`: `docs/study-plans.md` ("Plan-aware now", "Deliberately not automatic" — bold lead phrases == `studyloop.planning.boundaries.NOT_AUTOMATIC`), `docs/agent-install.md`, `agents/mcp/README.md` (32 tools == registry), `README.md`, `docs/index.md`, `docs/web-ui-guide.md`, `docs/cli-reference.md`, `docs/roadmap.md`; the installer prints the nine tools and the boundary from the same constants; all pinned by `T: test_docs_plan_integration_contract.py` (20) |
| Active-learning, MCP, Web UI, agent-adapter, and CLI capability specs are synchronized | yes | promoted from the change's six delta specs by `openspec archive plan-application-seam`; `openspec validate --specs --all` (verify `openspec-validate`) |
| CLI, Web, MCP, and architect journeys document both supported behavior and remaining live-session-binding exclusions | yes | "Deliberately not automatic"; `docs/acceptance-testing.md` scope note; the Archify spec's rose card (`C: dcfd44e4`) |
| Every acceptance area in parent issue #7 maps to completed child tickets and verification evidence | yes, with the exceptions marked above | this document + `R: receipts/verify-<sha>.json` |

DoD: full unit suite (verify `full-suite-studyloop`, `full-suite-agent-session-tools`); Web and MCP
journeys independently (`combined-journey`, `browser-journey-e2e`) and combined (`integration-combined`:
stdio smoke + combined journey in one process, both orders) with no nested-event-loop regression
(`T: test_plan_journey_combined.py` asserts the absence of the three signatures); docs, installer output
and capability matrices agree (docs contract); repository status clean at the tip. **Not clean in one
respect the owner must decide:** the unrelated local branches `feat/clean-start` (tip == local tag
`archive/feat-clean-start-2026-09-15`, not on origin) and `feat/harness-tier-promotion` (worktree
`../studyloop-wt/harness-tier`, 10 unmerged commits, not on origin) were not deleted — `branch -D` is
ask-first under the git rules because it destroys work.

## #7 — parent: acceptance areas → children

| Area of #7 | Child | Verification |
|---|---|---|
| Shared plan application module, six operations, invariants | #8, #9 | `test_plan_application*.py`, `test_plan_guidance.py`, the guard, reviews 1–2 |
| Active-plan guidance and ranking, additive `NowPlan`, four consumers | #10 | `test_now_plan_guidance.py`, `test_mcp_next_action.py`, golden, review 3; UAT `now_with_active_plan` |
| MCP lifecycle parity (nine tools, confirmed delete, no raw Markdown for agents) | #11, #12 | `test_mcp_plan_tools.py`, stdio smoke, UAT `mcp_lifecycle`, review 4 |
| Web architect launch (purpose, one resolver, brief, no plan created, one console) | #13, #14 | `test_session_start_purpose.py`, `test_plan_architect_persona.py`, `test_web_plan_architect_journey.py`, JS, UAT `architect_launch`, reviews 3–4 |
| Reconcile docs, installer, specs; verification | #15 | docs contract, verify receipt, UAT redacted summary, this document |
| Out of scope stays out (no live-session binding, no auto checkpoints/milestones, no single-active rule, never a filter, Markdown stays authoritative) | all | `NOT_AUTOMATIC` ↔ docs; `test_planning_launch_creates_no_plan_and_no_plan_id`; `test_multiple_ready_active_plans_are_valid`; golden byte-identity |

**#7 requirements not fully verified, stated plainly:** (1) the architect's one-question-at-a-time
protocol under a live model — persona text only; (2) the D-16 human rubric verdict — PENDING;
(3) the Kiro/Claude harness-launched architects reach the plan tools only through the CLI fallback until
the owner grants them the server; (4) partial-recording refusals over the *real* stdio transport —
in-process only; (5) the Web door carries a subject, not the manual form's brain dump.

---

## Proposed PR #20 description (replaces the "[in progress]" body)

**Title:** Plan integration: PlanApplication seam, plan-aware now, nine MCP tools, Web architect (#7–#15)

Closes #7, #8, #9, #10, #11, #12, #13, #14, #15.

**What this branch is.** One `PlanApplication` seam replaces the per-door lifecycle policy that produced
Bug A (activation readiness bypassed on create-with-status and whole-document replacement) and Bug B
(a failed checkpoint DB write reported as complete). CLI, Web routes and MCP reach study plans only
through it (an AST guard enforces this, 30 tests incl. 14 planted bypasses). On that seam: the `now`
engine is plan-aware with tested ranking rules (a bias, never a filter; the no-plan output is
byte-identical to a committed golden); nine MCP plan tools plus `record_plan_learning` (32-tool inventory,
pinned over the real stdio transport); a `planning` session purpose with one persona resolver for PTY and
ACP and a budgeted planning brief; **Plan with architect** on the Plans view, into the existing console,
labelled and reload-safe, creating no plan. Public docs, installer output and the capability matrix are
pinned to code constants; the normative specs are promoted; `scripts/verify/plan_integration.py` writes
the receipt.

**Evidence.** `docs/architecture/plan-integration/receipts/verify-<sha>.json` (28 checks, exit 0);
`receipts/uat-plan-journeys-a69867bf.redacted.json` (3/3 strict UAT cells: browser architect launch,
real stdio MCP lifecycle, Today with an active plan — fake agent); four council code reviews, all
ACCEPT (`council/review-{1,2,3,4}-arbitration-*.md`); the docs review (`council/review-5-*`).
Full suite per the receipt; `-m integration` combined run green in both orders; `just lint`,
`just typecheck`, `openspec validate`, `mkdocs --strict` clean.

**Honest limits.** The architect's one-question-at-a-time protocol is asserted as persona text, never
under a live model; the D-16 rubric awaits the owner's five verdicts; Kiro/Claude harness-launched
architects take the CLI fallback until the owner grants them the plan tools (a permission decision);
the Web door takes a subject, not the manual form's brain dump. Live-session binding, session-driven
checkpoints and milestone completion, and a single-active-plan rule are out of scope by design and
documented as such.

**Merge.** Fast-forward onto `main`; then `openspec` archive is already in the tree; tag per the release
process (`just release-consistency-shipped` passes on the archived change).

---

## Owner decisions still open (in one place)

1. **Kiro/Claude architect headers (T6.1 boundary):** keep the two harness-launched architects
   CLI-limited (the install doc's disclosure is then the contract), or grant them the `studyloop` server
   and the plan tools — Kiro: `mcpServers` + the nine `mcp_studyloop_*` names and
   `record_plan_learning` in `allowedTools` (mirroring `study-mentor.json`), flipping
   `test_install_agent_contracts.py:701` deliberately; Claude: a least-privilege explicit MCP allow-list.
   Review 4 ruled this a permission-model decision for a human.
2. **Score the D-16 rubric** — `receipts/now-rubric-2026-09-16.md`, five yes/no verdicts with a line
   each and the tree sha; re-read row 3 against `64dc09f7`. A `no` on rows 1–4 is a council finding.
3. **Deviation 12** (review 2) — a legacy active-but-unready document must be paused or repaired before
   any write. Confirm or reverse (one policy change in `_assert_can_be_active`'s callers; the tests that
   would flip are named in review-2 F2/G1).
4. **Review-3 F2 design question** — should `now` grow explicit urgency classes (rank by class first,
   plan relevance second)? The council decided a bias with the constant pinned to today's bands;
   reversing is a ranker redesign for a future planning round.
5. **Parser bug** (deviation 13) — a milestone concept literally containing `)` (e.g. `RANK()`) does not
   round-trip through the concepts regex; tracked, not fixed; F4's fixture stepped around it.
6. **`_evidence_command` quoting** (review 3, item 5) — backslash-escapes `"` in a suggested shell
   command; consider `shlex`-safe rendering when the golden is next allowed to move.
7. **`feat/clean-start`** — 7 commits not on origin; its tip equals the local tag
   `archive/feat-clean-start-2026-09-15` (also not on origin). Push the tag and delete, or discard.
8. **`feat/harness-tier-promotion`** — 10 unmerged commits, not on origin, checked out in the worktree
   `../studyloop-wt/harness-tier`. Merge, push, or discard:
   `git worktree remove ../studyloop-wt/harness-tier && git branch -D feat/harness-tier-promotion`.
9. **`or_first_filtered`** (review 1, §5 stream) — a fresh registration with a new gold set, or close as
   "exploratory, not pursued".
10. **Repository ruleset for branch deletion** — the "Default" ruleset blocks deletion on all branches,
    so the remote `feat/knowledge-proof` (tip == tag `archive/feat-knowledge-proof-2026-09-15`, PR #19
    closed) cannot be deleted until the owner relaxes it (ADR-0011 §4).
11. **Token revocation** — named in the stage brief as an open owner item; its context is in the earlier
    stage reports, not in this repository's records. Listed so it is not lost, not described here.
12. **`agent-session-tools/tests/test_eval_arms.py::TestPlannerIsolation::test_planner_patch_restored_after_tool_error`**
    — order-dependent under the root config (passes alone and in the package-local run); owner of
    `agent-session-tools`.
13. **The GitHub writes this draft exists for:** close #8–#15 with evidence comments, then #7; replace
    PR #20's body; mark it ready for review.
```
## 9. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for Phase 6 as the close of the programme (archive + close-out),
   with the single sentence that decides it.
2. **Findings**, each with severity 🔴 (a public claim that is false, or a spec/doc contradiction), 🟡 must-fix-before-
   archive (a claim not bounded per D-16, a spec requirement with no doc sentence or a doc claim with no spec/test behind
   it, an installer line that overclaims, a close-out row marked "met" that the evidence does not support), 🔵 should-fix,
   💡 note. For each: file (and section/line), what is wrong, why it matters, the concrete fix, and — where a test can pin
   it — the assertion to add to `test_docs_plan_integration_contract.py`. Check specifically:
   - (a) **Truth of every public claim** in `docs/study-plans.md` ("Plan-aware now", "Deliberately not automatic", the
     architect section), `docs/agent-install.md` ("Study-plan tools over MCP"), `agents/mcp/README.md`, `README.md`,
     `docs/index.md`, `docs/web-ui-guide.md`, `docs/cli-reference.md`, `docs/roadmap.md` against the facts in §0 and
     the specs in §4. Name any sentence that promises more than the specs/tests establish (e.g. does "the architect
     works from a planning brief … whichever door starts it" hold for the CLI-started architect, whose persona is the
     same file but whose brief comes from the launcher — is a brief rendered on the CLI path at all? Not established by
     this brief: say so if you cannot tell).
   - (b) **D-16 language**: is "better learning" or an equivalent promise anywhere? Is "plan-aware guidance with tested
     ranking rules" used where the docs describe #10? Does the "Plan-aware now" paragraph's last sentence (the rubric
     verdict "recorded per scenario in the project's rubric receipt") overstate — the receipt's verdict column is
     PENDING.
   - (c) **Spec ↔ docs synchronization**: for each delta requirement in §4, is there a public-doc sentence a learner or
     agent would read that states the behaviour (or is it legitimately internal)? Conversely, is there any doc claim
     (docs, installer, README) that no spec requirement or test backs? Produce the gap list, not a summary.
   - (d) **The boundary constant**: are the six `NOT_AUTOMATIC` phrases a faithful, complete rendering of #7's out-of-scope
     list as it applies to a learner (which #7 items are missing and should they be there; is "structure the manual
     form's brain dump" a boundary of the same kind as the other five, or a different statement mixed in)?
   - (e) **Installer text**: is a capability paragraph after `studyloop install agents` the right place, is the boundary
     sentence honest for Kiro/Claude harness-launched architects (it says "to any agent process it is registered with"),
     and should `--uninstall` say anything?
   - (f) **`agents/mcp/README.md`**: the heading still reads "studyloop-mcp (Session DB Tools)" while the server now
     spans review, backlog, lessons, session, now and plans — rename, or leave for link stability?
   - (g) **The verify registry (§6)**: is every design-§8 / review-4 check present by name, is anything missing (e.g. the
     three projection equalities and the two manifest hashes — covered by `test_plan_architect_persona.py` inside
     `plan-suites`; is that acceptable or should they be their own check?), and is running the two full suites separately
     — rather than the single workspace-wide run — a weakening of "the full suite" (the workspace-wide run has one known
     order-dependent agent-session-tools test)?
   - (h) **The UAT summary (§7)**: does `harness: "fake-agent"` and `actor_backend: "scripted"` describe the run honestly
     within the template's field meanings; is an empty `per_criterion_scores` with the arbitration note an acceptable
     redacted summary to commit, or should a mechanics-only run be labelled differently so it can never be mistaken for
     a graded sign-off?
   - (i) **The close-out draft (§8)**: for each row marked "yes", is the cited evidence sufficient (name any row where a
     node id does not prove the criterion as worded); for each "partly/mostly/not met", is the wording honest and
     complete; is any #7 requirement missing from the "not fully verified" list; are the thirteen owner decisions the
     right set (anything to add or drop)?
   - (j) **Archive readiness**: with every task ticked (T3.4's verdict named an owner action), is ticking T3.4 an honest
     task state or a repeat of the review-3 F6 mistake? Propose the exact wording if not. Does anything in the docs point
     at the *change* path (`openspec/changes/plan-application-seam/…`) that the archive will move?
   - (k) **Stale references**: any "Phase 6", "T6.1", "not yet", "CLI-only", "does not do yet", line-number citation, or
     "tracked as" left in a public page or the installer text.
   - (l) Anything else a maintainer reading these docs in six months would be misled by.
3. **Spec ↔ docs gap table** — two columns: delta requirement → doc sentence (or "internal"/"MISSING"); doc claim →
   spec/test (or "UNBACKED").
4. **Owner items** you would add to the close-out's list, or remove from it, with one line of reason each.
