# Handover — plan-integration follow-ons, mid-programme (start here in a fresh session)

**Written:** 2026-09-16, evening, by the coordinating agent (Kiro CLI) after items 1 and 2 landed; the
session stopped on model availability, not on a blocker.
**For:** the next coordinating agent in `/Users/ataylor/code/personal/tools/studyloop`.
**Owner:** Andy Taylor (`NetDevAutomate`). Steering applies: TDD, council review (GPT Astra + Grok 4.6 + one
best-for-purpose seat), data-driven, one recommended approach, brutal honesty, AuDHD-friendly (one thing at a
time). **Read this file first, then the parent** `HANDOFF-2026-09-16.md` (the owner's decisions D-A…D-J and
the working rules — still binding, not repeated here).

## 0. First five minutes — verify, don't trust

```bash
cd /Users/ataylor/code/personal/tools/studyloop
git status --porcelain | grep -v playwright            # expect empty
git branch --show-current                               # fix/plan-integration-bugs
git worktree list                                       # exactly one (this checkout)
git log --oneline -1                                    # 9a132aea at handover time
git rev-list --count main..HEAD                         # 163 at handover time
git rev-list --count origin/fix/plan-integration-bugs..HEAD   # 144 unpushed
git rev-list --count origin/main..main                  # 2 unpushed
openspec validate plan-integration-followons            # "is valid"
uv run python scripts/check-release-consistency.py --skip-wheel --release --pre-tag   # passes
curl -s -m 5 http://127.0.0.1:4000/health/liveliness    # LiteLLM: "I'm alive!" (needed for the council)
```

**Do not push and do not write to GitHub until item 7** (owner present; parent handover §3 item 7).

## 1. What landed this session (all local commits on `fix/plan-integration-bugs`, all verified)

| Commit | What | Verified by |
|---|---|---|
| `0a88d07f` | **Closed archived T3.4b.** The owner scored the D-16 rubric this morning; the archived change still carried the task open, so `openspec validate --archived` failed it and `just release-consistency-shipped` failed. `docs/study-plans.md` "Plan-aware now" now states the outcome (accepted rows *and* the two `no` findings); the contract pin keys on the receipt header "owner verdicts RECORDED" (the old `"PENDING" in receipt` guard was fooled by the word in the receipt's prose). | docs contract 25 passed; `release-consistency-shipped` passes |
| `222db4a3` | **Opened `openspec/changes/plan-integration-followons/`** (proposal, design §1–§6, tasks T1–T7, `.openspec.yaml` with `deferred: >-`), plus the **Kiro tools probe receipt** (below). `git add -f` is needed under `openspec/`. | `openspec validate` valid |
| `b620a7c8` | Item 1 RED (5 tests). | 5 failed / 30 passed on the previous tree |
| `f5c2057d` | **Pre-existing defect fixed:** `agents/kiro/study-mentor.json` — `@studyloop` added to `tools`; twelve `mcp_<server>_<tool>` grants → `@<server>/<tool>`. Manifest hash + `.secrets.baseline` refreshed (detect-secrets 1.5.0). | see probe receipt |
| `8a80c7d5` | **Item 1 GREEN (D-A):** Kiro architect `tools: [@builtin, @studyloop, @session-db]`, `mcpServers` studyloop + session-db, `allowedTools` exactly `@studyloop/<nine>` + `@studyloop/record_plan_learning`; Claude architect frontmatter `tools:` + `mcp__studyloop__<ten>`. The `"mcpServers" not in definition` pin flipped deliberately (docstring cites D-A). | targeted run 297 passed |
| `fb48a8ba` | Item 1 docs: `docs/agent-install.md` boundary paragraph → the granted state (pins updated in `test_plan_architect_persona.py`); `agents/mcp/README.md` `~/.grok/config.toml` → `$GROK_HOME/config.toml` (the `user-settings.json` sentence the parent handover questioned was **correct**). | full suite **5079 passed / 4 skipped, exit 0**; `just lint`; `just typecheck` 0 errors; `mkdocs --strict` |
| `71a74894` | Item 2 RED: `TestBrainDump` (8 failed / 2 guards), JS (4 failed / 13), browser `test_brain_dump_reaches_the_architect_persona` (RED) and `test_abandoning_a_launch_mid_flight_leaves_no_session_and_no_plan` (passes on the existing End path — cancellation is now covered). | as stated |
| `9a132aea` | **Item 2 GREEN (D-B):** `StartSessionRequest.brain_dump` (`BRAIN_DUMP_MAX_CHARS = 4000`, structural 422); renderer `_render_planning_brief(brief, *, brain_dump=None)` appends `### Learner's brain dump` only when present — blockquote per line, leading block markers backslash-escaped (F4 containment), paragraphs kept, clipped with a marker; never topic, never state, once in the persona; focus start ignores it. UI textarea `data-testid="plan-architect-braindump"`; `plansStore.architectBrainDump` → request detail `brainDump` → `sessionTimer` posts `brain_dump` only when non-blank and only for planning. Docs (`docs/study-plans.md`), web-ui + live-session-orchestration deltas (MODIFIED requirements), close-out draft #14 rows flipped to met with D-B stated. | `test_session_start_purpose.py` 35 passed; JS 133/133 clean exit; browser journey **10 passed** (`-m e2e`); full suite **5089 passed / 4 skipped, exit 0** (413 s) |

**Key evidence file:** `receipts/kiro-agent-tools-probe-2026-09-16.md`. On kiro-cli 2.21.4, `tools: ["@builtin"]`
hides every MCP tool even with the server in `mcpServers`; `allowedTools` honours `@server/tool` and **not**
`mcp_server_tool` (probe B: an `mcp_` entry stayed "not trusted" beside an `@` entry "trusted"). The parent
handover's `mcp_studyloop_*` spelling came from a file that was itself inert — this is the one place the
implementation departs from the handover's wording, on evidence, with D-A's intent preserved. Re-run the two
probes after any Kiro upgrade.

## 2. Tasks state (`openspec/changes/plan-integration-followons/tasks.md`)

- T1.0–T1.3 ticked with receipts. **T2.1/T2.2 are done but not yet ticked in `tasks.md`** — tick them first
  (RED `71a74894`, GREEN `9a132aea`, receipts in the table above), in the same commit as item 3's RED or on
  their own.
- Council review 6 (T6.1–T6.3) has **not** run: it reviews items 1–4 as one batch after item 4.

## 3. Next: item 3 — husk discovery + `plan repair <id>` (D-C). Design settled, RED not yet written

Design is in `openspec/changes/plan-integration-followons/design.md` §3. Decisions taken while mapping (keep them
unless the code contradicts):

- **Discovery source:** `PlanApplication.get_active_guidance()` already yields `(plan, readiness)` per active plan;
  add a read-only `PlanApplication.husks() -> tuple[PlanDetail, ...]` over it (active and `not readiness.ready`),
  order as `browse`. No new store call, no new writer.
- **`PlanSummary` gains `ready: bool`** (computed in `from_plan`) → 18 keys. This is a contract change on
  `plan list --json` and `GET /api/plans`; the only pin is
  `test_plan_application.py::test_summary_and_readiness_views_match_the_legacy_dicts_exactly`
  (`PlanSummary.from_plan(plan).to_json_dict() == plan.summary()`), so **`StudyPlan.summary()` in
  `planning/models.py` L200–221 must gain `"ready"` too** (via `authoring.readiness(plan)["ready"]`), and the
  cli-surface + web-ui deltas must say the key set grew. Protected `test_web_plans.py` / `test_cli_plan.py` assert
  keys present, not the exact set — verify with `-k "web_plans or cli_plan"` before committing.
- **Doctor:** `check_study_plans()` registered under category `config` in `cli/_doctor.py::_get_registry()`
  (no new category; the health spec enumerates categories verbatim). One `warn` row per husk (id, title,
  blockers; `fix_hint` = `studyloop plan repair <id>  (or: studyloop plan status <id> paused)`; `fix_auto=False`);
  zero husks → one `pass` row; no plans → `info`. Unit-test it like `TestUnknownConfigKeysCheck`
  (`tests/test_cli_doctor.py` L129–164) with `monkeypatch.setenv(store.PLANS_DIR_ENV, …)`.
- **`plan list`:** `!` after the status for a husk in the Rich table; `--husks` filter; `--json` rows carry `ready`.
- **`plan repair <id>`** in `cli/_plan.py`: `_inspect(id)`; ready → exit 0 "Nothing to repair on '<id>'"; unknown
  id → `_fail_for` (exit 1); husk → launch through the one chain. **Threading the brief without a user-facing
  option:** click's `ctx.invoke(study, …, brief=text)` passes extra kwargs straight to the callback, so add
  `brief: str | None = None` as a plain keyword on `study()` (not a click option), then
  `_handle_start(…, brief=brief)` → `start_session(…, brief=brief)` → `build_canonical_persona(mode, topic,
  energy, previous_notes=…, brief=brief, brief_intro=…)` (`session/start.py` L439 currently omits `brief=`).
- **`build_canonical_persona` gains `brief_intro: str | None = None`** (`agent_launcher.py` L325–336): `None` keeps
  today's "This is a PLANNING session: interview the learner and build a study plan…" sentence byte-for-byte
  (the Web door's `persona_hash` must not move — `test_focus_persona_unchanged`, `test_planning_brief_travels_once`);
  repair passes "This is a PLAN REPAIR session: the plan below is active but incomplete — ask the learner only for
  what is missing, then repair it…". Item 4 reuses the same keyword for its closing review.
- **Brief shape for repair:** first section `### Repair: what this plan is missing` listing exactly
  `readiness.blockers` as `- ` lines, then the plan summary (title, status, topics, milestones done/total) and the
  honest provenance line: `created < 2026-09-15` → "predates the readiness gate"; otherwise "active and
  incomplete; the seam cannot tell how it got that way" (never claim a hand edit). Topic for the launch = the plan
  title. `RevisePlan` has no mission fields, so a mission blocker is repaired by the learner in the Markdown or via
  `ReplaceDocument`/Web `PATCH markdown`; milestones/topics via `update_study_plan` — the persona's new
  "Repairing a plan" subsection must say so.
- **Refusal text** `_refuse_activation(already_active=True)` (`cli/_plan.py` L134–136) names both
  `studyloop plan status <id> paused` **and** `studyloop plan repair <id>`; `test_evaluate_record_on_unready_active_plan_is_refused_with_a_repair_hint`
  (`test_cli_plan_seam.py` L279) keeps passing and a new test asserts the repair command is named.
- **Web:** `GET /api/plans` rows carry `ready`; sidebar marker inside `.sidebar-plan-meta` (`index.html` ~L359–364).
- **Persona:** body edits change every projection — regenerate `agents/manifest.json`
  (`uv run python scripts/update-agent-manifest.py`, then revert `updated` on entries whose hash did not move) and
  refresh `.secrets.baseline` with `uvx detect-secrets==1.5.0 scan --baseline .secrets.baseline --exclude-files
  '<the hook's exclude regex from .pre-commit-config.yaml L45–49>'` — **never** scan a single path (it rewrote the
  whole baseline once this session; restored from a copy).

RED test names for item 3 are in `tasks.md` T3.1; the husk fixture literal to reuse is in
`test_cli_plan_seam.py` L286–290 (`husk.md`, frontmatter `status: active`, no mission). The launch-capture pattern
is `test_cli_plan.py::test_architect_delegates_to_study_with_plan_architect_mode` (L216–257): patch
`studyloop.session.start.start_session` and read `**kwargs` — `brief` arrives there.

## 4. Then: item 4 (D-G), council review 6, item 5, item 6, item 7

- **Item 4** design §4: `CompletionAction` gains `due_reviews`, `struggles`, `unverified_milestones`, `proposal`
  (`extend|close`), `evidence`; `_PlanContext.build` (`learning/decision.py` L751–830) obtains the counts via
  `PlanApplication().assess(AssessPlan(plan_id, phase="end", record=False))` (preview; no write); failure → old
  sentence + `warnings`. `plan close <id>` mirrors `plan repair` with `### Closing review`. Golden
  `tests/golden/now_plan_no_active.json` sha `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`
  must not move. Rubric row **4b** appended to `receipts/now-rubric-2026-09-16.md` (never overwrite row 4).
  Full code map for item 4 was gathered this session — key lines: `CompletionAction` L122–131, rule-9 block
  L779–789, `to_json_dict` L176–198, completion sentence composed in `planning/views.py` L793–797,
  `evaluate_plan` end-phase data sources `planning/evaluation.py` L168–242/L367–440, renderers `cli/_now.py`
  L72–73, `learning/recap.py` L68–69, `today-panel.js` L165–168.
- **Council review 6** (T6.1–T6.3): brief shape `council/brief-review4-2026-09-16.md`; command in the parent
  handover §3; seats `openai.gpt-6-astra`, `grok-4.6`, `qwen3-coder`; `--max-tokens 40000 --timeout 1700`;
  reproduce every 🔴/🟡 before accepting; arbitration ends `GATE: ACCEPT|FAIL`; then
  `scripts/verify/plan_integration.py --out receipts/verify-<sha>.json` (29 + new checks, never skip).
- **Item 5** (D-F) has its design page (§5) — own RED, own review 7, rubric row **3b** for the owner.
- **Item 6** proposals (D-D, D-E) under `docs/architecture/plan-integration/proposals/`.
- **Item 7** only with the owner present; then the owner revokes both tokens (D-J).

## 5. Things learned the hard way this session (don't repeat)

- **Probe the harness before pinning a test.** The handover's grant spelling was inherited from a broken file;
  two `/tools` runs against throw-away agents settled it in minutes and produced a receipt the council can read.
- **A pin keyed on a word can be fooled by prose.** `"PENDING" in receipt` kept passing after the rubric was
  scored because the receipt's explanatory text still contains the word. Key pins on a deliberate header phrase.
- **`node --test` "Promise resolution is still pending"** = a test created a second `sessionTimer()` on the same
  fake window (two listeners, two POSTs) and left it running; one timer per test, or split the test.
- **Pyright reports a missing keyword on the argument line**, so a RED-phase `# pyright: ignore[reportCallIssue]`
  must sit on the `kwarg=…` line, not the call line. Remove in GREEN.
- **The e2e "abandon" is the End control, not navigate-away:** a closed socket detaches with a grace period by
  design (`web/routes/session/_grace.py`), so the honest cancellation test ends the session right after the 201.
- Pre-commit rewrites (ruff-format) → re-stage and make a **new** commit; never `--amend`.
- Sub-agents: one `context-gatherer` per item worked; one of four returned FAILED with no output and was simply
  re-dispatched narrower (ask for < 25k chars). Their reports are saved under
  `~/.kiro/sessions/ac9c3fb76917e9ea/sess_03dceb2b-9fca-4c99-a823-097f2d33376b/tool-outputs/` (items 1–3:
  `orchestrate_subagent-269c353d.txt`; item 4: `orchestrate_subagent-723864a8.txt`) — reuse before re-gathering.

## 6. Open observations not in the execution order

- `packages/studyloop/` holds ten stray files literally named `<MagicMock id='…'>` (untracked scratch from some
  earlier run) — a housekeeping delete, not this programme's.
- `agents/kiro/study-mentor.json`'s **behaviour changes** for the production mentor after `f5c2057d`: its six
  studyloop tools become visible and trusted as the file always intended. Tell the owner; it is what the file said.
- Whether the Web-launched architect's agent process (Kiro via ACP/PTY) sees the studyloop server depends on that
  process's own agent config — the install doc now says so plainly.
