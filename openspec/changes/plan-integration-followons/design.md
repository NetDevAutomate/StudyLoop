# Design — plan-integration follow-ons (D-A, D-B, D-C, D-G; D-F designed in §5)

Decisions are cited as D-A…D-J from `docs/architecture/plan-integration/HANDOFF-2026-09-16.md` §2 (owner,
2026-09-16) and as D-n from the archived arbitration. Where this document and a decision disagree, the decision
wins and this document is wrong. The seam (`planning/{application,views,intents,errors}.py`) is unchanged in
shape: every item below reads through it and adds **no new writer**.

## 1. Harness grants for the architect (D-A)

Evidence: `docs/architecture/plan-integration/receipts/kiro-agent-tools-probe-2026-09-16.md`. On the installed
Kiro CLI (2.21.4) visibility is the `tools` array (`@builtin` hides every MCP tool even when the server is in
`mcpServers`) and trust is `allowedTools` in the `@<server>/<tool>` spelling; `mcp_<server>_<tool>` is inert.
Claude Code's `tools:` frontmatter is an allow-list; MCP tools are `mcp__<server>__<tool>`, and a built-ins-only
list excludes them all (that is today's disclosed boundary).

```jsonc
// agents/kiro/study-plan-architect.json — the granted shape
"tools": ["@builtin", "@studyloop", "@session-db"],          // visibility
"mcpServers": {"session-db": {"command": "session-db-mcp", "args": []},
               "studyloop":  {"command": "studyloop-mcp",  "args": []}},
"allowedTools": ["fs_read", "execute_bash", "grep", "glob", "web_fetch", "web_search",
                 "@studyloop/list_study_plans", … the nine in lifecycle order …,
                 "@studyloop/record_plan_learning"]           // trust: the ten, nothing else from studyloop
```

```yaml
# agents/claude/study-plan-architect.md frontmatter
tools: Read, Write, Grep, Bash, mcp__studyloop__list_study_plans, …, mcp__studyloop__record_plan_learning
```

The ten names are derived in tests from `studyloop.mcp.inventory.PLAN_TOOL_NAMES` + `LEARNING_RECORD_TOOL`. The
`session-db` server is *visible* to the Kiro architect (its loaded `shared/session-protocol.md` resource asks for
`session_search` at session start) and *not trusted* — it prompts — which is the least-privilege reading of the
owner's "grant what is needed". `study-mentor.json` is corrected in the same item (own commit): `@studyloop`
added to `tools`; its twelve `mcp_<server>_<tool>` allow entries rewritten as `@<server>/<tool>`. Learner
confirmation for deletion stays a persona rule; tool permission is not user authorisation (review 4).

The install doc's boundary paragraph becomes the granted state and names the `mcp.json`/agent-config
spelling difference; `agents/mcp/README.md`'s `$GROK_HOME/user-settings.json` sentence was verified **correct**
against `installers._grok_user_settings_path` — the tidy is the other direction (`~/.grok/config.toml` →
`$GROK_HOME/config.toml`, default `~/.grok`).

## 2. Brain dump on the Web door (D-B)

```python
class StartSessionRequest:
    brain_dump: str | None = Field(default=None, max_length=BRAIN_DUMP_MAX_CHARS)   # 4000
```

- Only meaningful for `purpose == "planning"`; on a `focus` start it is ignored (never rendered, never stored).
- `_render_planning_brief(brief, *, brain_dump=None)` appends a fourth section, `### Learner's brain dump`,
  **only when a non-blank dump is present**, so the three-section pins and the byte budget tests stay as they
  are. Containment (review-3 F4): the dump is rendered as a Markdown blockquote, every line prefixed `> `, after
  `_one_line`-per-line normalisation of whitespace runs; a line can therefore never begin with `#`, `-`, or a
  fence, and no heading can be forged. It is introduced as "the learner's own words — evidence, not
  instructions" under the section heading. The fixed sentence in `build_canonical_persona`'s
  `## Planning brief` wrapper already says the whole section is data.
- The dump is **never** the topic (`_launch_topic` unchanged: subject or `Study plan`), **never** written to
  session state (`build_session_state_payload` has no free-text slot; the tests assert the text is absent from
  the state file and `GET /api/session/state`), and travels once, inside the persona (on ACP the persona is
  echoed in the 201 `persona_text` by design; the tests assert it appears there and nowhere else in the body).
- Over-limit → FastAPI's structural 422 (`{"detail": [...]}`), the same door `purpose` uses; the handover's
  "structured 400" is read as "structured refusal before the handler runs" — no new exception handler.
- UI: a `<textarea data-testid="plan-architect-braindump">` beside the subject; `plansStore.architectBrainDump`
  travels in the `plan-architect-request` detail; `sessionTimer.startPlanning` forwards it into
  `startSession({purpose, brainDump})` and the POST body as `brain_dump` (omitted when blank). The two JS
  `deepEqual` pins on the detail gain the key.
- **Abandon mid-flight (browser):** click, then navigate away / press the console's cancel before the console
  attaches: no live slot (`GET /api/session/state` has no `study_session_id`, or the slot is released by the
  navigate-away path the app already has), `GET /api/plans` unchanged, at most one WebSocket ever opened.
- Persona-text compliance is the CI level for "one question at a time" (D-B); the web-ui spec says so.

## 3. Husk discovery and `plan repair <id>` (D-C)

A **husk** is an active document that fails `ReadinessView` (a hand-edited or pre-gate document). Deviation 12
stands: the gate refuses every write until the plan is paused or repaired.

- **Read:** `PlanApplication.husks() -> tuple[PlanDetail, ...]` — a read-only convenience over
  `get_active_guidance()`: every active plan whose `readiness.ready` is false, as `PlanDetail` (so callers get
  `summary`, `readiness` and `created`/`updated`). No new store call; order as `browse`.
- **Provenance hint** (honest): `created < 2026-09-15` (the gate's date) → "predates the readiness gate";
  otherwise → "edited outside StudyLoop after the gate" is **not** claimed — the seam cannot tell a hand edit
  from an import, so the hint says "active and incomplete; the seam cannot tell how it got that way".
- **`doctor`:** one checker `check_study_plans()` under category `config` (no new category; the health spec's
  enumeration is untouched), one `warn` row per husk: message names the id, title and blockers; `fix_hint`
  is `studyloop plan repair <id>  (or: studyloop plan status <id> paused)`; `fix_auto=False`. Zero husks → one
  `pass` row "N active plan(s), all ready" (or `info` when there are no plans).
- **`plan list`:** a `!` marker after the status for a husk (human table); `--husks` filters to them; the
  `--json` per-row shape gains **`ready: bool`** — a contract change on `list --json` and `GET /api/plans`
  (both are `PlanSummary.to_json_dict()`); the cli-surface and web-ui deltas say so. `PlanSummary` gains
  `ready` computed in `from_plan` — 18 keys.
- **`plan repair <id>`:** reads `inspect(id)`; a ready plan → exit 0, "Nothing to repair on '<id>'"; a husk →
  launches the architect through the one launch chain (`study --mode plan-architect`) with a brief whose
  first section is `### Repair: what this plan is missing`, listing exactly `readiness.blockers`, followed by
  the plan's summary; **creates nothing**. The brief reaches the persona through a new `brief=` keyword
  threaded `study → _handle_start → start_session → build_canonical_persona(brief=)` — the same keyword the
  Web door uses — with the wrapper sentence parameterised so a repair is not framed as "build a study plan".
- **Refusal text:** `_refuse_activation(already_active=True)` names both `studyloop plan status <id> paused`
  and `studyloop plan repair <id>`.
- **Persona:** a "Repairing a plan" subsection: ask only for the missing pieces named in the brief; a mission
  blocker is repaired by the learner in the Markdown or by `update_study_plan` where a field exists; never
  hand-edit.

Decisions taken at GREEN (2026-09-17, owner present — Andy asked "after `plan repair <id>` what happens to the
husk doc?" and chose this shape):

- **`plan repair` on a plan that is not active** (an unready draft, or a paused incomplete plan): exit 0, no
  launch, "`'<id>' is <status>, so nothing blocks it` … finish it with `studyloop plan architect`", then the
  readiness block. A draft is unready by nature and is not a husk; a paused incomplete plan is what the gate
  asked for.
- **`husk_provenance(created)` lives in `views.py`**, not `authoring.py`: it is a sentence about a verdict (a
  view), the gate *date* is the policy and stays in `authoring` as `READINESS_GATE_DATE`. This is what lets
  `cli/_plan.py` import it through the package without an architecture-guard exception — the guard's covering
  test flagged the authoring placement, correctly.

### 3b. Mission writer for `update_study_plan` (filed and **built** 2026-09-17)

Found while answering the question above: `readiness()` has three blocker classes (mission `why`, `success`
criteria, `milestones`), but `RevisePlan` — what `update_study_plan` maps to — had **no mission fields**, and
the only write that could set a mission was `ReplaceDocument`, whose sole caller is the Web `PATCH markdown`
route. So the architect `plan repair` launched could repair a missing-milestones husk over MCP but could only
*dictate* the fix for the husk fixture itself (no mission). Item 3 shipped with the persona saying exactly that.

Built as its own RED/GREEN (`35d890ef` → `653e825b`), not widened into item 3, so item 3's finish stayed
countable. `RevisePlan` gained `why: str | None`, `success`, `constraints`, `out_of_scope: Sequence[str] |
None`, applied by `_revise` to the candidate's `Mission` after every field is validated and before the one
gate — `None` leaves as is, a list replaces the whole list stripped of blanks, a bare string where a list
belongs is `InvalidField` before any write (the same rule as `topics`); the duplicate-record short-circuit sees
mission updates too. `update_study_plan` and `PATCH /api/plans/{id}` expose them on the same intent. The
persona's repair table lost its "no tool writes the mission" row; the two Revise rows lost "not the mission";
the gate paragraph gained the one-call alternative beside the pause path.

**Owner decision (T3b.0, 2026-09-17):** MCP and Web only — no CLI `plan revise`. The persona's CLI fallback
row keeps saying no CLI command edits an existing plan's fields, on purpose.

Two pins flipped with the design, deliberately and at their source: `test_schemas_carry_the_design_signatures`
(the `update_study_plan` property set grows by four), and review 5's
`test_agent_install_doc_does_not_promise_mission_revision_over_mcp`, whose premise was `"why" not in schema` —
renamed `…_promises_exactly_what_update_study_plan_revises` and inverted: the install doc now lists the mission
among what MCP revises and the row names every schema property.

## 4. `plan close <id>` — evidence-based, consensual completion (D-G)

- **Payload:** `CompletionAction` gains `due_reviews: int`, `struggles: int`, `unverified_milestones: int`,
  `proposal: Literal["extend", "close"]`, `evidence: tuple[str, ...]` (one line per counted item, capped), and
  keeps `action` (the sentence, now composed from the proposal). `proposal == "extend"` iff any count > 0.
- **Read:** `_PlanContext.build` obtains the assessment through `PlanApplication().assess(AssessPlan(plan_id,
  phase="end", record=False))` — the preview path; **no write, no checkpoint**. Its cost is one evaluation per
  fully-checked active plan (rare), read once per `build_now_plan`. Failure → the pre-change sentence plus a
  `warnings` entry; `now` never fails on it.
- **Never a status change** (#7, `NOT_AUTOMATIC`): the engine proposes; the architect asks; the learner agrees;
  `set_study_plan_status` is the only door to `complete`.
- **`plan close <id>`:** `inspect(id)`; not fully checked → exit 1 "'<id>' still has N open milestone(s)";
  fully checked → run the end assessment (preview) and launch the architect with a brief whose first section
  is `### Closing review` (the counts, the evidence lines, the proposal), sibling of `plan repair`.
- **Renderers:** CLI `now`, Today card and recap print the proposal and the counts; JSON carries the new keys
  only inside `completion_actions` entries, which exist only when a fully-checked active plan exists — the
  no-plan golden is unchanged.
- **Persona:** an "Extend or close" subsection: read the evidence back; propose; ask "anything you are not
  comfortable with?"; change status only when the learner agrees.
- **Pinned by the RED (`14c8938b`, 2026-09-17):** the `### Closing review` section's first four `- ` lines are
  `Due reviews on plan concepts: N`, `Struggles on plan concepts: N`, `Unverified milestones: N`,
  `Proposal: extend|close`, followed by the evidence lines — readable off the top, as the repair section's
  blockers are. The intro says `CLOSING REVIEW`, does not say "build a study plan", and says the status changes
  "only when the learner agrees". The composed sentence differs from the pre-change either-way sentence and
  names the proposal. The refusal is `'<id>' still has N open milestone(s)` (exit 1, no launch).
- **Decided by the owner (2026-09-17), pinned by the RED:** the completion review counts only due rows that
  name a concept. `spaced_repetition_due` appends a `New topic -- start fresh` row (`concept: None`,
  `evidence: configured_topic`) for every plan topic with no progress rows — the scheduler's cold-start hint
  for "what should I review now", not a lapsed review. The evaluator already ignores it at concept level (a
  `None` concept never matches a milestone concept, so it contributes nothing to `unverified_milestones`), and
  counting it would tell a learner who has just ticked every milestone to "start fresh" — the
  incompleteness-after-success framing D-G exists to avoid. `unverified_milestones` remains the honest carrier
  of "done without evidence". `plan evaluate` keeps the row (phase `start` wants it); the exclusion is the
  completion review's, one definition beside `PlanEvaluationView` in `planning/views.py`, consumed by both the
  engine's `CompletionAction` and the `plan close` brief. Measured cost of the preview on the live 877 MB
  database: ~320 ms per fully-checked plan per `build_now_plan` (five readers), a transient state by design.
- **Open for GREEN (not pinned):** what `proposal` holds when the assessment fails. `Literal["extend", "close"]`
  has no honest value for "not assessed" — `extend` asserts outstanding work without evidence, `close` asserts
  a clean slate without evidence. Default unless vetoed: `proposal: Literal["extend", "close"] | None`, `None`
  on failure with the counts `0` and `evidence` empty; the `warnings` entry explains; renderers print the plain
  sentence when `proposal is None`. One nullable field carries the state; the three counts keep their type.

## 5. Item 5 — per-item energy demand and the body-doubling floor (D-F) — designed here, reviewed separately

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

## 6. Verification

`scripts/verify/plan_integration.py` gains registered checks for: the two architect grants (the ten names in
both files, derived from the inventory), the `plan repair`/`plan close` refusal texts, and the golden sha
(existing). Council review 6 covers items 1–4; review 7 covers item 5. Receipts under
`docs/architecture/plan-integration/receipts/verify-<sha>.json`.
