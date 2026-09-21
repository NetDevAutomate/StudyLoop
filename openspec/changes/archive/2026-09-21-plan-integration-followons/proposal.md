## Why

The plan-integration programme (#7–#15) shipped on `fix/plan-integration-bugs` and is archived at
`openspec/changes/archive/2026-09-16-plan-application-seam/` (five council gates, 29/29 verification). The
owner's morning walkthrough of 2026-09-16 (`docs/architecture/plan-integration/HANDOFF-2026-09-16.md` §2,
decisions D-A…D-J) scored the D-16 rubric (`receipts/now-rubric-2026-09-16.md`) and took the decisions the
close-out draft had left open. Four of them are code; they are what this change carries:

1. **D-A — the harness-launched architects fall back to the CLI with full shell permissions.** Kiro's
   `study-plan-architect.json` has no `mcpServers` and Claude's `tools:` is built-ins only, so an architect
   started from either harness cannot use the nine plan tools the persona prefers; it shells out instead.
   "None of the harnesses should fall back to the CLI with full permissions." Probing the installed Kiro CLI
   (`receipts/kiro-agent-tools-probe-2026-09-16.md`) also showed the reference file, `study-mentor.json`,
   grants its studyloop tools in a spelling the CLI does not honour and never makes them visible.
2. **D-B — #14's optional brain dump is unimplemented.** The Web "Plan with architect" door carries a subject,
   not the free-text brain dump the manual form has; the architect starts without the learner's own words.
   No browser test abandons a launch mid-flight.
3. **D-C — deviation 12 is kept, so a legacy active-but-unready document ("husk") refuses every write until
   paused or repaired — but nothing tells the learner they have one.** `plan list` shows a husk as a healthy
   active plan; `doctor` has no plan check; the only repair path is "pause it, then edit".
4. **D-G — the completion action is a fixed sentence.** Rule 9 emits "close the plan or extend it" for any
   fully-checked plan without looking at the evidence: due reviews, live struggles or milestones ticked
   without evidence on that plan's concepts make "close" the wrong proposal. The owner scored it *no as
   phrased*.

Item 5 (D-F, scenario 3 *no*: a struggle-repair task has no energy demand; recommending hands-on repair of
a live struggle on a low-energy day compounds it) changes ranking and is designed and reviewed under its
own round inside this change, with a new rubric row (3b) for the owner to score before it ships.

## What Changes

- **Agent adapters (D-A).** The Kiro and Claude `study-plan-architect` definitions attach the `studyloop`
  server and allow exactly the nine plan lifecycle tools plus `record_plan_learning` — nothing else from that
  server — in the spelling each harness honours (`@studyloop` visibility + `@studyloop/<tool>` trust for Kiro;
  `mcp__studyloop__<tool>` in Claude's `tools:` allow-list). The pinned "no `mcpServers`" assertion is flipped
  deliberately, citing D-A. `study-mentor.json` is corrected to the working spelling (pre-existing defect).
- **Web architect door (D-B).** `POST /api/session/start` accepts an optional, length-bounded `brain_dump`
  for a `planning` launch; it travels in the planning brief as its own contained section (data, not
  instructions; never the topic; never on session state). The Plans view gains the textarea. A browser test
  abandons a launch mid-flight. Persona-text compliance is stated as the accepted CI level for "one question
  at a time".
- **Husk discovery and repair (D-C).** `doctor` names each active-but-unready plan with its blockers;
  `plan list` marks them; `GET /api/plans` carries `ready` per plan; `plan repair <id>` launches the
  architect with the blockers in its brief and creates nothing. The refusal text points at both
  `plan status <id> paused` and `plan repair <id>`.
- **Evidence-based completion (D-G).** A fully-checked plan's completion action carries the end
  assessment (counts of due reviews, struggles and unverified milestones on the plan's concepts) and a
  proposed action, `extend` or `close`; status never changes automatically. `plan close <id>` launches the
  architect with the assessment in its brief. Rubric row 4b for the owner.
- **Energy demand and the body-doubling floor (D-F, item 5, own round).** Per-item energy demand for
  struggle repair; a `body_double` candidate synthesised when nothing plan-related fits the day; no-plan
  output byte-identical to the golden. Rubric row 3b.

## Impact

- Specs: `agent-adapters` (grant + boundary), `web-ui` (brain dump; husk marker), `live-session-orchestration`
  (brain dump never persisted), `cli-surface` (`plan repair`, `plan close`, list marker, refusal text),
  `health-and-diagnostics` (plan check), `active-learning-decisions` (completion payload; item 5 rules).
- Code: `agents/{kiro,claude}/study-plan-architect.*`, `agents/kiro/study-mentor.json`, `agents/manifest.json`,
  `web/routes/session/{_models,_start}.py`, `web/static/{index.html,js/components/plans-panel.js,
  js/components/session-timer.js}`, `cli/{_plan,_doctor,_study}.py`, `session/start.py`, `agent_launcher.py`,
  `planning/{application,views}.py`, `learning/decision.py`, `doctor/*`, `web/routes/plans.py`, docs.
- Tests: RED first in every task (`tasks.md`); the protected files and the `now` golden do not move.
- Not in scope: D-D (context-derived plan bias) and D-E (overdue nudge / retire) are written proposals under
  `docs/architecture/plan-integration/proposals/` and become issues at the push step; D-H, D-I, D-J are
  repository administration.
