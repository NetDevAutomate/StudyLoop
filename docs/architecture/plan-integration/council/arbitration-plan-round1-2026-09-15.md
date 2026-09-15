# Arbitration — plan-integration council, planning round 1

**Date:** 2026-09-15 · **Arbiter:** coordinating agent (Kiro CLI, Claude) · **Owner directive:** close the
two confirmed bugs and the outstanding #7–#15 work plus the surviving PR #19 result, TDD, per-task
definition of done, data-driven, council-reviewed at every stage.

**Brief:** `brief-plan-2026-09-15.md` (sha256 in `plan-round1/manifest.json`).
**Seats:** `openai.gpt-6-astra` (`plan-round1/seat-openai.gpt-6-astra.md`), `grok-4.6`
(`plan-round1-grok-rerun/seat-grok-4.6.md`), `kimi-k2-thinking` (`plan-round1/seat-kimi-k2-thinking.md`).

**Instrument fault, recorded:** Grok's first run (`plan-round1/seat-grok-4.6.INVALID-tool-loop.md`)
announced "I'll inspect the repo", had no tools, and degenerated into a 20,000-token repetition loop. Cause:
the default system prompt did not state that the seat has no tools. Fix: `scripts/council/system-seat.md`
(explicit no-tools contract) — now the default for every council run. The re-run is the seat weighed here.

## Facts established after the brief (the seats flagged these as unknown)

| Question | Answer (verified in tree) |
|---|---|
| Is CLI `plan status X active` readiness-gated? | **Yes** — `cli/_plan.py:336-341` checks `readiness()` and exits 1. Bug A is Web-only. |
| Does `energy_floor` exist on the plan? | **Yes** — `models.py:133` (default 3), parsed/rendered in `markdown.py:445,476`. |
| `build_now_plan` `interleave` default | `"off"`; `InterleaveMode = Literal["off", "adaptive"]` (`decision.py:14,540`). |
| What does `previous_notes` do in `build_canonical_persona`? | Renders a **"Resuming Previous Session"** section with "pick up where we left off" copy (`agent_launcher.py:288-297`). Wrong carrier for a planning brief. |
| Do existing Web tests use `overwrite`? | No. |
| Who consumes `build_now_plan`? | `cli/_now.py`, `web/routes/now.py`, `mcp/tools.py`, `learning/recap.py`, `second_brain/obsidian.py`. |
| Existing Now/decision suites | `test_learning_decision.py`, `test_web_now.py`, `test_recap_mastery_voice.py`. |
| Plan-related Archify spec | None exists. One will be authored when the seam lands (structure changes). |
| §5 inputs present? | `~/.config/studyloop/sessions.db` (912 MB) and `receipts/gold-v2-dev.json` (91 items). |

## Decisions

Numbered so later council rounds and commits can cite them (D-1 …).

**D-1 — Bug B is fixed first, alone, in `planning/evaluation.py`.** Unanimous. Honour `record_checkpoint`'s
boolean in `evaluate_and_record` by appending the existing warning string. Not a route bug; the committed RED
test already names the contract. Keep `index.record_checkpoint`'s swallow-and-return-False as the index's
best-effort policy (GPT, Grok). *Rejected:* Kimi's `record_checkpoint_checked` wrapper returning a
`DomainError` union — a second checkpoint writer for a one-line fix.

**D-2 — Bug A is closed by the seam, and #8 owns create-and-activate and document replacement.** GPT and
Grok both read the same contradiction: #8's own DoD ("identical readiness on create-and-activate / transition /
imported active doc") names exactly the two doors the RED tests pin, yet #9's taxonomy puts create/replace in
#9. Resolution: `CreatePlan`, `ReplaceDocument`, `TransitionLifecycle` ship in #8; `RevisePlan`,
`SetMilestone`, `DeletePlan`, `AssessPlan` in #9. The PATCH-status gate in `web/routes/plans.py` is *deleted*
when the route delegates — no third copy. *Rejected:* Kimi's Phase 0 helper (`check_activation_readiness`
called from each route) — that is three route-local gates with a shared function, which is the duplication
#7 exists to remove.

**D-3 — Seam shape: four new modules, closed intent union, exceptions for domain errors, result-with-warnings
for partial recording.** `planning/{errors,views,intents,application}.py`. Views are frozen dataclasses with
tuples, `to_json_dict()` returns fresh containers, and they serialise to the **existing** `summary()` /
`readiness()` key sets so `test_web_plans.py` stays behaviour-identical (Grok's point). Domain errors are
exceptions (`PlanNotFound`, `InvalidPlanId`, `PlanConflict`, `InvalidField`, `PlanNotReady(readiness)`,
`InvalidMilestone`); adapters map them once. **No `PartialRecording` exception** — raising would prevent
returning the evaluation; `AssessmentResult.warnings` carries per-sink outcomes (GPT, Grok). *Rejected:*
Kimi's `Union[View, DomainError]` return type — pushes error handling into every caller and defeats a single
adapter mapping.

**D-4 — `overwrite` stays on the `CreatePlan` intent for Web/CLI compatibility but is not exposed on the
`create_study_plan` MCP tool.** GPT's authority-model objection is right for agents; Grok's compatibility point
is right for the existing REST body. Both hold.

**D-5 — Additive `NowPlan` fields are emitted only when non-empty; `plan_refs` is a tuple.** GPT and Grok
independently caught that "additive keys" and "no active plans → byte-identical output" contradict unless
empty keys are omitted. Adopted. `LearningRecommendation.plan_refs: tuple[PlanRef, ...] = ()` because one
action can match several plans (spec: "retain every reference"). *Rejected:* Kimi's `plan_ref:
Optional[tuple[str, str]]` — loses references. A golden `tests/golden/now_plan_no_active.json` pins today's
output before #10 starts.

**D-6 — Architecture guard is AST-based, allow-listed, and tested against a planted violation.** `ast.parse`
every module under `studyloop/cli/`, `studyloop/web/routes/`, `studyloop/mcp/`; fail on any
`Import`/`ImportFrom` rooted at `studyloop.planning.{store,index,authoring,evaluation}`; allow only
`studyloop.planning.{application,views,errors,intents}`. Follow relative imports and aliases (GPT). The
test must fail on a planted `from studyloop.planning.store import save_plan` in a temp copy (Grok). No new
dependency. *Rejected:* Kimi's `inspect.getsource` substring match — defeated by an alias or a line break.

**D-7 — Parallelisation map and critical path.**
```
Phase 0  Bug B (evaluation.py)                                   ─┐ parallel, no shared files
§5       plan_prose_query stream (separate worktree off main)    ─┘
Phase 1  #8 seam + Bug A (CLI/Web list/inspect/activate/create/replace)
Phase 2  #9 remaining intents + assess + get_active_guidance + architecture guard
Phase 3  #10 Now guidance  ∥  #11 six MCP tools  ∥  #13a purpose+resolver plumbing
Phase 4  #12 three MCP tools + inventory  ∥  #13b architect uses MCP tools (after #11)
Phase 5  #14 Web architect journey
Phase 6  #15 reconcile + verify
```
Critical path: #8 → #9 → #11 → #13b → #14 → #15. Kimi's observation that the purpose/persona plumbing does not
depend on MCP tools is correct and is why #13 is split: **#13a** (`purpose` on `StartSessionRequest`, one
`persona_mode_for(purpose)` resolver used by PTY and ACP, brief delivery, no plan created) runs in Phase 3;
**#13b** (architect persona instructions prefer the #11 tools, CLI fallback) waits for #11. *Rejected:* Kimi's
"run all of #13 and #14 in Phase 1" — #14's acceptance ("architect can use MCP authoring tools") cannot be
verified before #11 exists.

**D-8 — `mcp/tools.py` has one writer at a time: #11 → #12 → #10's final `interleave` commit.** Grok and GPT
both name this file as the merge hotspot. `decision.py` is #10-only; `_start.py` is #13-only. Sub-agents work
in separate worktrees and commit only owned files.

**D-9 — Nine MCP tools stay nine.** Spec is explicit; each maps to one intent; separate tools give agents
better schemas and discoverability. *Rejected:* Kimi's merge into a seven-tool `mutate_study_plan` union.
`record_plan_learning` is kept (nothing retires it); inventory 26 → 35; the stdio smoke test is retargeted in
#12 when all nine exist, not in #11.

**D-10 — The planning brief is delivered as its own persona section, not via `previous_notes` and not by
overloading `topic`.** `previous_notes` renders "Resuming Previous Session … pick up where we left off" —
semantically wrong for a fresh planning interview. `build_canonical_persona` gains an explicit
`brief: str | None = None` keyword rendering a "Planning brief" section; `plan-architect.md` is the mode.
History-derived evidence in the brief is data, not instructions (GPT). *Rejected:* Grok's `previous_notes`
carrier (on the fact above).

**D-11 — Only `purpose` is persisted on live-session state; no plan id.** The spec is not contradictory
here: the architect *creates* a plan through tools; the session does not store its id, and no future session
auto-selects it. *Rejected:* Kimi's "sessions are implicitly bound; log the plan id for reconnect" — that is
the live-session binding #7 puts out of scope.

**D-12 — §5 is a separate branch off `main`, never on the plan-integration critical path, freshly
pre-registered.** All three seats agree on independence; GPT and Grok agree the historical +0.142/+0.168 is
prioritisation evidence, not confirmation. The candidate is **Grok's narrow form**: `plan_prose_query`'s
quoted-token OR replaces only the OR *widen* step inside the shipped AND-then-OR planner, after
`retrieval.py:plan_query` has classified the string as natural language; the explicit `fts:`/uppercase door
never reaches it. Arms are planner variants (GPT's five: shipped; filtered OR-first; unfiltered AND-first;
unfiltered phrase-token OR; shipped-AND + candidate-OR-fallback), orthogonal to the transport arms. Primary
metric recall@5 on the committed 91-item DEV gold; precision@5 and MRR reported as guardrails; paired
bootstrap CI. Adopt iff DEV recall@5 lift has CI95 lower bound > 0 **and** precision@5 drop ≤ 0.05 absolute
**and** explicit-door tests pass **and** `tests/golden/session_search_pre_planner.json` is unchanged (the
widen path gets its own golden if adopted). Thresholds are frozen in a pre-registration receipt *before*
any run. *Rejected:* Kimi's re-run of the SEALED set as a confirmation set — it was spent on 2026-09-15 and
its questions are private; and Kimi's invented `eval.arms --arm plan_prose` CLI — the real entrypoint is
`eval/__main__.py` with `gold`/`census` subcommands.

**D-13 — ADR-0011 is amended, not rewritten.** Dated "Disposition after semantic-layer completion" section:
the claim-centric store did not merge (supersedes lines 6–7); the semantic-layer programme sealed without it
(supersedes the "prerequisite" claim at 51–52); cite the branch's Stage F fused-arm −0.140; separate the
portable lexical hypothesis from the retired storage architecture; link the §5 adopt/reject receipt; PR #19
closed with tip tagged `archive/feat-knowledge-proof-2026-09-15`. Historical text preserved with explicit
supersession (GPT). No renumbering of a never-merged ADR (Grok).

**D-14 — No new ADR for the seam.** The load-bearing rules (activation gating on every path, independent
checkpoint sinks, no plan id on a live session) are spec text and land in `openspec/specs/{active-learning-
decisions,mcp-server,web-ui,cli-surface,agent-adapters,live-session-orchestration}/spec.md`. An ADR is
written only if `planning` purpose changes session identity — it must not.

**D-15 — Definition of done is a receipt, not a feeling.** Adopt GPT's proposal of a verification script,
placed at `scripts/verify/plan_integration.py` (repo convention: `scripts/<area>/`), that runs the named
suites, lint, typecheck and the `rg` invariants, records exit codes and node counts, and writes
`docs/architecture/plan-integration/receipts/verify-<sha>.json`. Missing checks are recorded as failures,
never as "not applicable".

**D-16 — Learner benefit is a separate, later measurement; release language is bounded.** Ranking tests
prove ranking compliance, not learning. Adopt GPT's phrasing for the docs: "plan-aware guidance with tested
ranking rules", never "better learning". Adopt Grok's cheap pre-ship check: a five-scenario human rubric on
frozen fixtures (matching due; urgent-unrelated wins; energy-deferred; fully-checked; no-plan identical)
scored "would I do the primary?", committed as a receipt. Post-ship accept/skip logging tagged
`plan_backed|not` is a follow-on ticket, not part of #10's DoD.

**D-17 — Scope valve, not a cut.** If the critical path slips, #14 (browser journey) may move behind #15
(Grok) because the CLI already launches the architect (`776a9dc0`). #8/#9 are never cut: the two bugs exist
*because* policy lived in one route door.

## What each seat contributed that the others did not

- **GPT Astra:** the additive-vs-byte-identical contradiction; `plan_refs` as a collection; the `overwrite`
  authority gap; the sink-outcome matrix (`not_requested|saved|failed`); five pre-registered planner arms;
  the verification-script DoD; the bounded release language.
- **Grok 4.6:** the #8/#9 contradiction with the fix; delete the route gate rather than add a third; the narrow
  "OR-widen only" candidate for §5; the planted-violation requirement for the architecture test; the
  `mcp/tools.py` serialisation order; "do not renumber a never-merged ADR".
- **Kimi K2:** the #13 split (purpose plumbing does not need MCP tools); the reminder that the golden brief
  JSON must be shared between the MCP interview tool and the Web console so they cannot drift.

## Council rounds still to run

1. **Code review** after Phase 0 + Phase 1 land (diff + test output): seats `openai.gpt-6-astra`,
   `grok-4.6`, `qwen3-coder` (best-for-purpose: code).
2. **§5 receipt review** when the pre-registration and the measurement receipt exist: same three seats plus
   `deepseek-r1` for the statistics.
3. **Docs/spec review** at #15: `openai.gpt-6-astra`, `grok-4.6`, `kimi-k2-thinking`.
