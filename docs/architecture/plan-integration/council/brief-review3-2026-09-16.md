# Council brief — code review 3: Phase 3 (#10 ∥ #11 ∥ #13a) of the plan-integration programme

**Date:** 2026-09-16 · **Branch:** `fix/plan-integration-bugs`, reviewed tree `575e26ff` = the merge of three
parallel Phase-3 branches (`feat/p3-now`, `feat/p3-mcp`, `feat/p3-purpose`) onto the accepted Phase-2 base
`0a20a796` (review-2 corrections included; accepted in `review-2-arbitration-2026-09-16.md`, `GATE: ACCEPT`).
**You are one independent seat**; no other seat's answer is visible. You have no tools — this brief is the
complete evidence base. Three implementing agents ran unattended overnight in separate worktrees, each owning
disjoint files; your findings gate Phase 4 (#12 three more MCP tools + inventory pin; #13b architect persona
prefers the MCP tools) and Phase 5 (#14 Web architect journey).

## 0. What you are reviewing against (binding)

### Design §3 — plan-aware `now` (D-5). `decision.py` is the only ranker. Order inside `build_now_plan`:

1. `guidance = PlanApplication().get_active_guidance()` — one plan-static read; no session-history scan.
2. Existing candidate collection unchanged.
3. Energy capability `low|medium|high → 3|6|10`; below a plan's `energy_floor`, *new-milestone* work is deferred
   (listed in `energy_deferred`); plan-related due recall / struggle repair stays eligible.
4. Match: `casefold` + strip punctuation; **equality** on topic/course or on named milestone concepts. No substring.
5. Score as today; within an urgency class plan-related beats unrelated; a globally more-urgent unrelated
   candidate still wins (bias, not filter).
6. If no candidate represents an eligible next milestone, synthesise one.
7. `_dedupe`, then attach every matching `PlanRef`, ordered by target urgency → most recent update → plan id.
8. Guarantee ≥ 1 eligible plan-backed action in primary + alternates when time/energy permit.
9. Fully-checked active plan → `completion_actions`, never a study candidate.

```python
@dataclass(frozen=True) class PlanRef: plan_id: str; milestone_index: int | None = None
LearningRecommendation.plan_refs: tuple[PlanRef, ...] = ()
NowPlan.active_plans / energy_deferred / completion_actions / warnings: tuple[...] = ()
```
**Conditional emission (D-5):** `to_json_dict()` omits each additive key when empty and omits `plan_refs` when
empty, so a learner with no active plan gets the pre-#10 payload byte for byte. Golden
`tests/golden/now_plan_no_active.json` was captured **before** any #10 change (sha256
`ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`) and must not move.
**D-16:** ranking tests prove ranking compliance, not learning; release language is "plan-aware guidance with
tested ranking rules", never "better learning"; a five-scenario human rubric (matching due; urgent-unrelated
wins; energy-deferred; fully-checked; no-plan identical) scored "would I do the primary?" is committed as a
receipt; post-ship accept/skip logging is a follow-on, not #10's DoD.

### Design §4 — MCP tools (D-8, D-9)

| Tool | Seam call | Phase |
|---|---|---|
| `list_study_plans(status=None)` | `browse` | 3 (#11) |
| `get_study_plan(plan_id, include_markdown=False, include_history=False)` | `inspect` | 3 |
| `get_planning_interview()` | `prepare_planning` | 3 |
| `create_study_plan(title, answers, plan_id=None, status="draft")` | `apply(CreatePlan(overwrite=False))` | 3 |
| `update_study_plan(plan_id, **explicit fields)` | `apply(RevisePlan)` | 3 |
| `set_study_plan_status(plan_id, status)` | `apply(TransitionLifecycle)` | 3 |
| `set_study_plan_milestone(plan_id, index, done)` | `apply(SetMilestone)` | 4 (#12) |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `assess` | 4 |
| `delete_study_plan(plan_id, confirmed=False)` | `apply(DeletePlan)` | 4 |

**D-8:** `mcp/tools.py` has one writer at a time: #11 → #12 → **#10's final `interleave` commit** (T3.5:
`get_next_action(..., interleave="off")`). `decision.py` is #10-only; `_start.py` is #13-only. **D-9:** nine tools
stay nine; `record_plan_learning` is kept; the design text says "inventory 26 → 35; the stdio smoke test is
retargeted in #12 when all nine exist, not in #11". **Fact for you:** the production registry at `0a20a796` had
**23** tools (the design's "26" was wrong), it has **29** at `575e26ff`, and `tests/test_mcp_stdio_smoke.py`
pins `len(names) >= 21` plus a `CORE_TOOLS` name set, not an exact count. **D-4:** `overwrite` is never exposed
on `create_study_plan`.

### Design §5 — `planning` purpose (D-10, D-11)

```python
class StartSessionRequest: ...; purpose: Literal["focus", "planning"] = "focus"
def persona_mode_for(purpose: str) -> str: return "plan-architect" if purpose == "planning" else "focus"
def build_canonical_persona(mode, topic, energy, *, previous_notes=None, brief: str | None = None) -> str
```
`_start.py` (PTY **and** ACP) call `persona_mode_for(body.purpose)`; for `planning`, render
`PlanApplication().prepare_planning()` to Markdown and pass it as `brief=` — its own "Planning brief" persona
section, **not** `previous_notes` (which renders "Resuming Previous Session"), **not** folded into `topic`.
History-derived evidence in the brief is data, not instructions. **D-11:** only `purpose` is persisted on
live-session state; no plan id; no plan is created by the launch. Topic for an architect launch: the
user-supplied subject if present, else the fixed label `"Study plan"` (matches CLI `776a9dc0`). D-6 still holds:
routes may import only `studyloop.planning.{application,views,errors,intents}` (guard
`tests/test_architecture_plan_seam.py`, 30 tests).

### Review-2 arbitration — what it handed Phase 3

The `ActivePlanGuidance` shape #10 consumes (G1–G4 landed):
```
ActiveGuidance(plans: tuple[ActivePlanGuidance, ...], warnings: tuple[str, ...])   # ordered by storage id
ActivePlanGuidance(plan: PlanSummary (days_until_target on the SAME effective date as target_urgency),
    readiness: ReadinessView,             # an unready active plan is LISTED, not writable (deviation 12)
    next_milestone: MilestoneView | None, # first unchecked; None when none or all done
    match_keys: tuple[str, ...],          # sorted, de-duplicated normalise_match_key() over topics + ALL concepts
    target_urgency: "overdue" | "soon" | "later" | "undated", energy_floor: int (raw document value),
    completion_action: str | None,        # English with the title in it — data, not a prompt
    warnings: tuple[str, ...])
```
Rules for #10 the seats endorsed: import `normalise_match_key`, equality on the key only; honour collection
`warnings` and per-plan `readiness.ready`; sort every tie explicitly; one parse per document, zero
checkpoint-history calls, no session scan; hostile-content fixtures for titles/topics/milestone text with no
lifecycle write. Hazards recorded for #11: freeze `CreatePlan.answers` (live mapping) before `create_study_plan`
lands or any intent is queued/replayed; `AssessPlan` goes to `assess()`; `DeletePlan` needs an explicit
confirmation flag; copy `record_plan_learning`'s `PlanNotReady` → `ToolError` mapping. Open owner items: the
deviation-12 ruling (legacy active-but-unready documents must be paused or repaired before any write — the
`now` ranker must not recommend a milestone the seam will refuse to tick); the parser bug (milestone concepts
regex stops at the first `)`, so `RANK()` does not round-trip) — "do not fix matching to paper over it".

### Hard rules for this phase (verified on `575e26ff` before this brief was written)

- TDD: each stream's RED commit precedes its GREEN (§1). Protected files byte-identical: vs `3a4f6b01` —
  `test_web_plans.py`, `test_cli_plan.py`, `test_planning_evaluation.py`; vs `0a20a796` —
  `test_learning_decision.py`, `test_web_now.py`, `test_recap_mastery_voice.py`, `test_web_session_start_pty.py`,
  `test_web_session_start_acp.py`, `test_web_session_ws.py`, `test_agent_launcher.py` (all `git diff` → 0 lines).
- Golden sha256 unchanged (above). Guard 30 passed. Each stream's own gate is quoted in §2; the merged tree's
  full-suite run is the arbiter's job after your findings, not a claim in this brief.
- Ownership: #10 = `learning/decision.py`, `cli/_now.py`, `learning/recap.py`, Today card JS/HTML, tests, golden;
  #11 = `mcp/tools.py` (append only), `tests/test_mcp_plan_tools.py`, mcp-server spec; #13a =
  `web/routes/session/{_models,_start,_dashboard}.py`, `agent_launcher.py`, `tests/test_session_start_purpose.py`.

## 1. Commits on the three branches (oldest last), each RED before its GREEN

```text
575e26ff merge: Phase 3 — feat/p3-purpose into fix/plan-integration-bugs
86d39cbc merge: Phase 3 — feat/p3-mcp into fix/plan-integration-bugs
59de8452 merge: Phase 3 — feat/p3-now into fix/plan-integration-bugs
362edf57 docs(plan-integration): tick T3.6/T3.7 with commits, RED evidence and gates          (#11)
2685316c docs(spec): #10 plan-aware now — delta spec, D-16 rubric receipt, tasks T3.1–T3.4      (#10)
df33690b feat(now): renderers show plan relevance and energy deferral — GREEN                   (#10)
bd919d51 docs(mcp): list the study-plan tools an agent can call                                 (#11)
9717f0ae docs(spec): mcp-server delta — study-plan discovery and authoring tools                (#11)
d2013380 test(now): RED — renderers show plan relevance and energy deferral                     (#10)
b9e1e551 docs(spec): session purpose + persona resolution deltas; tick T3.8/T3.9                (#13a)
4fc51250 feat(session): start purpose, one persona resolver, planning brief (T3.9)              (#13a)
0f1b3d08 feat(now): plan-aware ranking per design §3 — T3.3 GREEN                               (#10)
5a03b094 feat(mcp): six study-plan tools as thin adapters over the seam (T3.7)                  (#11)
eb28a1fb test(mcp): bind the seam spies as methods so delegation asserts can run                (#11)
6e5af8c1 test(now): RED — T3.2 nine ranking rules of the plan-aware `now`                       (#10)
484db041 test(mcp): RED — six study-plan tools of design §4 (T3.6)                              (#11)
0c4d9160 test(session): RED — start purpose, one persona resolver, planning brief (T3.8)        (#13a)
848f413b test(now): T3.1 — golden of the no-active-plan `now` emit, captured pre-#10            (#10)
```

`git diff 0a20a796..575e26ff --stat`:

```text
 docs/agent-install.md                              |  29 +
 .../receipts/now-rubric-2026-09-16.md              |  57 ++
 docs/study-plans.md                                |   2 -
 .../specs/active-learning-decisions/spec.md        | 122 +++-
 .../specs/agent-adapters/spec.md                   |  32 +
 .../specs/live-session-orchestration/spec.md       |  72 +++
 .../plan-application-seam/specs/mcp-server/spec.md | 113 +++-
 openspec/changes/plan-application-seam/tasks.md    | 119 +++-
 packages/studyloop/src/studyloop/agent_launcher.py |  38 +-
 packages/studyloop/src/studyloop/cli/_now.py       |  52 +-
 .../studyloop/src/studyloop/learning/decision.py   | 462 ++++++++++++-
 packages/studyloop/src/studyloop/learning/recap.py |  50 +-
 packages/studyloop/src/studyloop/mcp/tools.py      | 270 ++++++++
 .../src/studyloop/web/routes/session/_dashboard.py |   7 +-
 .../src/studyloop/web/routes/session/_models.py    |  12 +
 .../src/studyloop/web/routes/session/_start.py     | 252 ++++++--
 .../studyloop/src/studyloop/web/static/index.html  |  22 +-
 .../web/static/js/components/today-panel.js        |  58 ++
 .../studyloop/tests/golden/now_plan_no_active.json |  24 +
 .../studyloop/tests/js/today-panel-plan.test.js    | 158 +++++
 packages/studyloop/tests/test_mcp_plan_tools.py    | 718 +++++++++++++++++++++
 packages/studyloop/tests/test_now_plan_guidance.py | 519 +++++++++++++++
 .../studyloop/tests/test_session_start_purpose.py  | 427 ++++++++++++
 23 files changed, 3515 insertions(+), 100 deletions(-)
```

## 2. The three agents' own implementation reports (verbatim from `tasks.md`, T3.1–T3.9)

### #10 — Now guidance (agent B)

- **T3.1** (`848f413b`) Capture golden `tests/golden/now_plan_no_active.json` on the pre-#10 tree with frozen clock and
  an isolated empty DB. Commit alone. **As landed:** captured from the unmodified engine at `0a20a796` (empty
  sessions DB, empty plans dir, empty content roots, no topics/focus, clock `2026-09-16T09:30:00+00:00`);
  sha256 `ec451ce8…503c0`; the byte-equality test in `tests/test_now_plan_guidance.py` passed on that tree before
  any #10 change.
- **T3.2** (`6e5af8c1`, seen 9 failed / 1 passed on `848f413b`: seven `ImportError: PlanRef`, one
  `AttributeError: completion_actions`, one JSON-key assertion; the golden test passed) RED
  `tests/test_now_plan_guidance.py` (ten engine tests, named in the file). Renderer RED `d2013380` (CLI panel, recap
  `plan_context`, Today-card helpers in `tests/js/today-panel-plan.test.js` 0/6; the two `/api/now` end-to-end
  tests passed already and are kept as the wire-contract proof).
- **T3.3** (engine `0f1b3d08`; renderers `df33690b`) **As landed:** `build_now_plan` reads guidance once through
  `PlanApplication().get_active_guidance(today=now.date())` (one clock with `generated_at`); `ENERGY_CAPABILITY`
  3|6|10; `PLAN_RELATED_BIAS = 12` inside today's scoring; synthesised milestone candidate (`conversation`, source
  `study_plan:<id>:<k>`, base 48 + overdue 6 / soon 3) so a plan with no evidence is the primary and `starter` is
  false; refs attached after `_dedupe` in urgency → `updated` desc → id order with the most specific milestone per
  plan; rule-8 swap of the last alternate only; fully-checked plans → `completion_actions`, neither matched nor
  synthesised; an unready active plan (review-2 G1) is matched but never synthesised, with a warning naming its
  blockers; unreadable plans → a warning, never a failure. `NowPlan.active_plans` is a compact `ActivePlanSummary`
  (not `PlanSummary`) so renderers get title, urgency, floor, eligibility and next-milestone index without the
  full summary. Renderers: CLI `Plan:` line + deferral/completion/warning lines + Plan column (only when plans
  exist); recap `plan_context` (omitted when empty; `cli/_recap.py`'s rich panel is outside #10's ownership and
  does not print it yet — `--json` and the spoken form do); Today card `planLabel` / `deferredNotes` /
  `completionNotes` with a notes block that is deliberately not a `.today-card` (the browser smoke test addresses
  the single action card by that class). `web/routes/now.py` needed no edit. Protected files `git diff 0a20a796 --
  test_learning_decision.py test_web_now.py test_recap_mastery_voice.py` → 0 lines.
- **T3.4** Human rubric receipt (D-16): five frozen scenarios scored "would I do the primary?", committed as
  `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`. **As landed:** the five scenarios were
  run unattended and the emitted primary + rule-cited rationale recorded per row; the owner-verdict column is
  **PENDING** — no human was present and none was faked. Delta spec: the guidance requirement loses "(not yet
  consumed)" and a new requirement "The now engine is plan-aware with tested ranking rules" carries nine
  scenarios. `docs/study-plans.md`: the now/Today "does not do yet" bullet removed.
- **T3.5** (last, after #11 and #12 have landed in `tools.py`) `get_next_action(..., interleave="off")` — **not yet
  done**; see deliverable 6.

### #11 — six MCP tools (agent C)

- **T3.6** (`484db041`, RED: 58 failed, every one `KeyError: Tool '<name>' not registered` against the 23-tool
  inventory at `0a20a796`; spy-binding harness fix `eb28a1fb`) RED `tests/test_mcp_plan_tools.py`: schema present
  for six with the design §4 signatures; each delegates to a monkeypatched `PlanApplication` with the store and
  index forbidden underneath (`forbid_store`); `PlanNotReady` → ToolError `not_ready: plan is not ready to
  activate: <blockers>` (plus "pause or repair" when already active); duplicate create → `conflict:`; every
  subclass → one prefixed ToolError with the domain error chained; `set_study_plan_status` retry idempotent;
  `overwrite` absent from `create_study_plan`'s schema and description (D-4); `learning_record` absent from
  `update_study_plan` (D-9); `get_study_plan(history_limit)` outside 1..200 → `invalid:` with no seam call; every
  response is the view's `to_json_dict()` in fresh containers; real-seam journeys on an isolated plans dir +
  `STUDYLOOP_DB`.
- **T3.7** (`5a03b094`) Six thin adapters appended after `log_struggle`, inside the production inventory: one seam
  call each, one mapping helper `_plan_tool_error` (`not_found` / `invalid_id` / `conflict` / `invalid` /
  `not_ready` / `invalid_milestone`, `plan_error` as the safety net); no plan policy in the adapter.
  `record_plan_learning` untouched (its inline mapping is a fold candidate for #12, the next `tools.py` writer).
  `test_mcp_stdio_smoke.py` **unchanged** and passing — it pins `>= 21` plus the core names, not an exact count,
  so the inventory moving 23 → 29 (the file said 26; the production registry at `0a20a796` had 23) needs no edit
  here; retarget in #12. **Deviations, each reported:** (a) `history_limit` is bounded in the adapter to the Web
  route's `Query(ge=1, le=200)` range — the seam does not bound it and `application.py` is not in #11's file set;
  a seam-level bound would be the single copy. (b) `update_study_plan` exposes `status` beside the field edits so
  repair-and-activate is one `RevisePlan` judged once (the F1 contract), while `set_study_plan_status` remains the
  dedicated transition tool; `learning_record` is deliberately not exposed. (c) The "freeze `CreatePlan.answers`"
  hazard lives in `intents.py`, outside #11's ownership; over MCP the `answers` object is decoded per call and
  retained by no one, so no snapshot is taken in the adapter. Delta spec: mcp-server requirement "Study-plan
  discovery and authoring tools" (seven scenarios); `docs/agent-install.md` gains "Study-plan tools over MCP".
  **Gates at `bd919d51`:** `-k "mcp or plan"` 756 passed; full `-x` 4826 passed / 4 skipped exit 0; `just lint`
  clean; `just typecheck` 0; guard 30 passed; `test_mcp_stdio_smoke.py -m integration` 2 passed; `openspec
  validate` valid; `mkdocs build --strict` clean; `git diff 0a20a796 -- mcp/tools.py` → 0 deleted lines.
  Workspace-wide `pytest -q` (both packages): 6941 passed, 16 skipped, **1 failed** —
  `agent-session-tools/tests/test_eval_arms.py::TestPlannerIsolation::test_planner_patch_restored_after_tool_error`,
  order-dependent under the root config (it calls `monkeypatch.undo()` mid-test, which also undoes the autouse
  `STUDYLOOP_CONFIG` fixtures); passes alone and in the package-local run; outside #11's ownership.

### #13a — purpose + resolver (agent D)

- **T3.8** (`0c4d9160`, 11 failed / 1 pin passed on `0a20a796`) RED `tests/test_session_start_purpose.py` (names in
  the file). Fake agent: StubTransport factories, binary preflight bypassed through the `STUDYLOOP_TEST_*_CMD`
  hatch accessor.
- **T3.9** (`4fc51250`) **As landed:** `StartSessionRequest.purpose: Literal["focus", "planning"] = "focus"` (the
  only model change; `topic` stays required — a blank topic on `planning` resolves to `"Study plan"`, the label
  `776a9dc0` pins); `agent_launcher.persona_mode_for(purpose: str) -> str` and `build_canonical_persona(mode,
  topic, energy, *, previous_notes=None, brief=None)`, byte-identical output when `brief` is `None`. `_start.py`:
  one `_resolve_persona(body, topic)` both transports call — resolver → optional brief → persona + hash — and the
  `PlanningBrief → Markdown` renderer lives in the route (routes may import `planning.application|views`, D-6
  guard 30 passed). The persona is now built **before** the DB record, so a brief failure returns a structured
  500 (`error`/`purpose`/`repair`) from inside the claim's `try` with nothing to roll back but the reservation.
  `purpose` is always written to the state payload (never inherited through the read-merge-write) and `GET
  /api/session/state` echoes it (`setdefault("purpose", "focus")`, the `origin` pattern); the `201` body gains
  `purpose`. Delta specs: `live-session-orchestration` ("Session purpose"), `agent-adapters` ("Persona
  resolution by purpose"). Gates: `-k "session or launcher or purpose or persona"` 651 passed; `just lint`
  clean; `just typecheck` 0 errors; `test_web_session_start_pty.py`, `test_web_session_start_acp.py`,
  `test_web_session_ws.py`, `test_agent_launcher.py` green and unchanged (91).


## 3. #10 — plan-aware `now` (engine, renderers, tests, golden, rubric)

### `packages/studyloop/src/studyloop/learning/decision.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/learning/decision.py b/packages/studyloop/src/studyloop/learning/decision.py
index 07ddbf93..b4323ca6 100644
--- a/packages/studyloop/src/studyloop/learning/decision.py
+++ b/packages/studyloop/src/studyloop/learning/decision.py
@@ -1,14 +1,31 @@
-"""Shared decision engine for "what should I study now?" recommendations."""
+"""Shared decision engine for "what should I study now?" recommendations.
+
+This module is the **only ranker**. Active study plans (design §3, D-5) enter
+it as one plan-static read — ``PlanApplication().get_active_guidance()`` — and
+leave as a *bias* on the existing scores, a synthesised candidate for an
+unrepresented next milestone, and references attached to the ranked actions.
+Renderers show that plan relevance; none of them re-rank.
+
+With no active plan the emitted JSON is byte for byte what it was before plans
+existed: every additive field is omitted when empty
+(``tests/golden/now_plan_no_active.json``).
+"""

 from __future__ import annotations

+import dataclasses
 import sqlite3
 from dataclasses import asdict, dataclass, field
 from datetime import UTC, datetime
-from typing import Literal
+from typing import TYPE_CHECKING, Literal

 from studyloop.cli._shared import TOPIC_KEYWORDS

+if TYPE_CHECKING:
+    from datetime import date
+
+    from studyloop.planning.views import ActiveGuidance, ActivePlanGuidance, MilestoneView
+
 EnergyLevel = Literal["low", "medium", "high"]
 Modality = Literal["recall", "conversation", "hands-on", "visual", "audio"]
 InterleaveMode = Literal["off", "adaptive"]
@@ -21,6 +38,95 @@ INTERLEAVE_RATIOS: dict[EnergyLevel, dict[str, int]] = {
     "high": {"current": 40, "weak_links": 30, "transfer": 30},
 }

+#: Design §3 rule 3 — what each self-reported energy level can carry, on the
+#: 1-10 scale a plan's ``energy_floor`` uses. Below a plan's floor, *new*
+#: milestone work is deferred; plan-related due recall and struggle repair
+#: stay eligible, because repair is cheaper than encoding.
+ENERGY_CAPABILITY: dict[EnergyLevel, int] = {"low": 3, "medium": 6, "high": 10}
+
+#: Rule 5 — the bias a plan-related candidate receives. Large enough to decide
+#: a near-tie inside one urgency class (two due items a few days apart), small
+#: enough that a clearly more-urgent unrelated candidate (a struggling repair,
+#: an overdue review) still wins: a bias, never a filter.
+PLAN_RELATED_BIAS = 12
+
+#: Base score of a synthesised next-milestone candidate (rule 6) — new
+#: learning, so below every due/repair class and beside practice (48); the
+#: bias above then lifts it over unrelated practice and continuity.
+MILESTONE_BASE_SCORE = 48
+_MILESTONE_URGENCY_BONUS: dict[str, int] = {"overdue": 6, "soon": 3}
+
+#: Sort rank of a plan's target urgency (rule 7).
+_URGENCY_RANK: dict[str, int] = {"overdue": 0, "soon": 1, "later": 2, "undated": 3}
+
+#: Source prefix of every synthesised milestone candidate: ``study_plan:<id>:<index>``.
+PLAN_SOURCE_PREFIX = "study_plan:"
+
+
+@dataclass(frozen=True)
+class PlanRef:
+    """One active plan an action advances; ``milestone_index`` when it names a milestone.
+
+    An action can match several plans, so a recommendation carries a tuple of
+    these (D-5: "retain every reference"). ``None`` means the action matched
+    the plan on a topic or a finished milestone's concept — plan-related
+    repair — rather than on the next milestone.
+    """
+
+    plan_id: str
+    milestone_index: int | None = None
+
+    def to_json_dict(self) -> dict:
+        return {"plan_id": self.plan_id, "milestone_index": self.milestone_index}
+
+
+@dataclass(frozen=True)
+class ActivePlanSummary:
+    """What a renderer needs to show one active plan beside the recommendation."""
+
+    plan_id: str
+    title: str
+    target_urgency: str
+    days_until_target: int | None
+    energy_floor: int
+    eligible: bool
+    next_milestone: str
+    next_milestone_index: int | None
+    milestone_done: int
+    milestone_total: int
+    ready: bool
+
+    def to_json_dict(self) -> dict:
+        return asdict(self)
+
+
+@dataclass(frozen=True)
+class DeferredMilestone:
+    """A next milestone the current energy cannot carry (rule 3)."""
+
+    plan_id: str
+    plan_title: str
+    milestone_index: int
+    title: str
+    energy_floor: int
+    energy_capability: int
+    reason: str
+
+    def to_json_dict(self) -> dict:
+        return asdict(self)
+
+
+@dataclass(frozen=True)
+class CompletionAction:
+    """What to do about an active plan whose every milestone is checked (rule 9)."""
+
+    plan_id: str
+    plan_title: str
+    action: str
+
+    def to_json_dict(self) -> dict:
+        return asdict(self)
+

 @dataclass(frozen=True)
 class LearningRecommendation:
@@ -36,9 +142,14 @@ class LearningRecommendation:
     score: float
     course: str | None = None
     metadata: dict[str, str | int | float | None] = field(default_factory=dict)
+    plan_refs: tuple[PlanRef, ...] = ()

     def to_json_dict(self) -> dict:
-        return asdict(self)
+        data = asdict(self)
+        refs = data.pop("plan_refs")
+        if refs:
+            data["plan_refs"] = list(refs)
+        return data


 @dataclass(frozen=True)
@@ -54,9 +165,13 @@ class NowPlan:
     alternates: list[LearningRecommendation]
     interleave_ratio: dict[str, int]
     starter: bool = False
+    active_plans: tuple[ActivePlanSummary, ...] = ()
+    energy_deferred: tuple[DeferredMilestone, ...] = ()
+    completion_actions: tuple[CompletionAction, ...] = ()
+    warnings: tuple[str, ...] = ()

     def to_json_dict(self) -> dict:
-        return {
+        data = {
             "energy": self.energy,
             "time_minutes": self.time_minutes,
             "modality": self.modality,
@@ -67,6 +182,17 @@ class NowPlan:
             "primary": self.primary.to_json_dict(),
             "alternates": [item.to_json_dict() for item in self.alternates],
         }
+        # Additive keys only when non-empty (D-5): a learner with no active
+        # plan gets the pre-plan payload, byte for byte.
+        if self.active_plans:
+            data["active_plans"] = [item.to_json_dict() for item in self.active_plans]
+        if self.energy_deferred:
+            data["energy_deferred"] = [item.to_json_dict() for item in self.energy_deferred]
+        if self.completion_actions:
+            data["completion_actions"] = [item.to_json_dict() for item in self.completion_actions]
+        if self.warnings:
+            data["warnings"] = list(self.warnings)
+        return data


 @dataclass(frozen=True)
@@ -81,6 +207,7 @@ class _Candidate:
     score: float
     course: str | None = None
     metadata: dict[str, str | int | float | None] = field(default_factory=dict)
+    plan_refs: tuple[PlanRef, ...] = ()

     def recommendation(self) -> LearningRecommendation:
         return LearningRecommendation(
@@ -94,6 +221,7 @@ class _Candidate:
             score=round(self.score, 2),
             course=self.course,
             metadata=self.metadata,
+            plan_refs=self.plan_refs,
         )


@@ -464,6 +592,7 @@ def _score_candidates(
     energy: EnergyLevel,
     modality: Modality,
     interleave: InterleaveMode,
+    plan_keys: frozenset[str] = frozenset(),
 ) -> list[_Candidate]:
     last_topic = _last_focus_topic(candidates)
     focus_topics = _focus_topics()
@@ -498,21 +627,12 @@ def _score_candidates(
                 score -= 25
             elif energy in {"medium", "high"} and candidate.action_type == "visual":
                 score += 8 if energy == "medium" else 16
+        # Design §3 rule 5: plan-related beats unrelated inside one urgency
+        # class; a globally more-urgent unrelated candidate still wins.
+        if candidate.plan_refs or (plan_keys and _candidate_keys(candidate) & plan_keys):
+            score += PLAN_RELATED_BIAS

-        scored.append(
-            _Candidate(
-                concept=candidate.concept,
-                topic=candidate.topic,
-                course=candidate.course,
-                reason=candidate.reason,
-                action_type=candidate.action_type,
-                estimated_minutes=candidate.estimated_minutes,
-                source=candidate.source,
-                evidence_command=candidate.evidence_command,
-                score=score,
-                metadata=candidate.metadata,
-            )
-        )
+        scored.append(dataclasses.replace(candidate, score=score))
     return scored


@@ -532,6 +652,287 @@ def _dedupe(candidates: list[_Candidate]) -> list[_Candidate]:
     return result


+# ---------------------------------------------------------------------------
+# Active study plans (design §3, D-5)
+# ---------------------------------------------------------------------------
+
+
+def _match_key(text: str) -> str:
+    """The seam's normalisation — casefold, punctuation to spaces — applied here too.
+
+    Imported lazily like every other collaborator in this module: the
+    planning package reaches back into ``studyloop.learning`` for its concept
+    filter, so a module-level import would be a cycle.
+    """
+    from studyloop.planning.views import normalise_match_key
+
+    return normalise_match_key(text)
+
+
+def _candidate_keys(candidate: _Candidate) -> frozenset[str]:
+    """The keys on which a candidate can equal a plan: its concept, topic and course."""
+    keys = {_match_key(candidate.concept), _match_key(candidate.topic)}
+    if candidate.course:
+        keys.add(_match_key(candidate.course))
+    keys.discard("")
+    return frozenset(keys)
+
+
+def _load_guidance(today: date) -> ActiveGuidance | None:
+    """One plan-static read through the seam; ``None`` when plans cannot be read at all."""
+    try:
+        from studyloop.planning.application import PlanApplication
+
+        return PlanApplication().get_active_guidance(today=today)
+    except Exception:
+        return None
+
+
+def _milestone_concept_keys(plan: ActivePlanGuidance) -> frozenset[str]:
+    if plan.next_milestone is None:
+        return frozenset()
+    return frozenset(_match_key(concept) for concept in plan.next_milestone.concepts) - {""}
+
+
+def _order_plans(plans: tuple[ActivePlanGuidance, ...]) -> list[ActivePlanGuidance]:
+    """Rule 7 order: target urgency, then most recent update, then plan id.
+
+    Three stable passes, least significant first, because ``updated`` is a
+    string that cannot be negated inside one key.
+    """
+    ordered = sorted(plans, key=lambda item: item.plan.plan_id)
+    ordered.sort(key=lambda item: item.plan.updated, reverse=True)
+    ordered.sort(key=lambda item: _URGENCY_RANK.get(item.target_urgency, len(_URGENCY_RANK)))
+    return ordered
+
+
+@dataclass(frozen=True)
+class _PlanContext:
+    """Everything one ``build_now_plan`` call derived from the active plans.
+
+    ``matchable`` are the plans that may bias and be referenced by a
+    candidate: every active plan except a fully-checked one, whose work is
+    done and which is represented by a completion action instead (rule 9).
+    ``synthesise`` are the plans whose next milestone may become a
+    candidate when nothing collected represents it (rule 6): ready, with a
+    next milestone, and within the energy capability (rule 3).
+    """
+
+    matchable: tuple[ActivePlanGuidance, ...]
+    synthesise: tuple[ActivePlanGuidance, ...]
+    match_keys: frozenset[str]
+    summaries: tuple[ActivePlanSummary, ...]
+    deferred: tuple[DeferredMilestone, ...]
+    completions: tuple[CompletionAction, ...]
+    warnings: tuple[str, ...]
+
+    @classmethod
+    def empty(cls, *warnings: str) -> _PlanContext:
+        return cls(
+            matchable=(),
+            synthesise=(),
+            match_keys=frozenset(),
+            summaries=(),
+            deferred=(),
+            completions=(),
+            warnings=tuple(warnings),
+        )
+
+    @classmethod
+    def build(cls, guidance: ActiveGuidance | None, *, energy: EnergyLevel) -> _PlanContext:
+        if guidance is None:
+            return cls.empty("study plans could not be read; recommending without them")
+        if not guidance.plans:
+            return cls.empty(*guidance.warnings)
+
+        capability = ENERGY_CAPABILITY[energy]
+        matchable: list[ActivePlanGuidance] = []
+        synthesise: list[ActivePlanGuidance] = []
+        keys: set[str] = set()
+        summaries: list[ActivePlanSummary] = []
+        deferred: list[DeferredMilestone] = []
+        completions: list[CompletionAction] = []
+        warnings: list[str] = list(guidance.warnings)
+
+        for plan in _order_plans(guidance.plans):
+            summary = plan.plan
+            warnings.extend(plan.warnings)
+            next_milestone = plan.next_milestone
+            ready = plan.readiness.ready
+            if not ready:
+                blockers = "; ".join(plan.readiness.blockers) or "not ready"
+                warnings.append(
+                    f"active plan {summary.plan_id!r} is not ready ({blockers}) — "
+                    "pause or repair it before recording milestones on it"
+                )
+
+            eligible = False
+            if plan.completion_action:
+                completions.append(
+                    CompletionAction(
+                        plan_id=summary.plan_id,
+                        plan_title=summary.title,
+                        action=plan.completion_action,
+                    )
+                )
+            else:
+                matchable.append(plan)
+                keys.update(plan.match_keys)
+                if next_milestone is not None and ready:
+                    if capability >= plan.energy_floor:
+                        eligible = True
+                        synthesise.append(plan)
+                    else:
+                        deferred.append(
+                            DeferredMilestone(
+                                plan_id=summary.plan_id,
+                                plan_title=summary.title,
+                                milestone_index=next_milestone.index,
+                                title=next_milestone.title,
+                                energy_floor=plan.energy_floor,
+                                energy_capability=capability,
+                                reason=(
+                                    f"{energy} energy carries {capability}/10; "
+                                    f"{summary.title!r} asks for at least "
+                                    f"{plan.energy_floor}/10 — plan-related review "
+                                    "and repair stay available"
+                                ),
+                            )
+                        )
+
+            summaries.append(
+                ActivePlanSummary(
+                    plan_id=summary.plan_id,
+                    title=summary.title,
+                    target_urgency=plan.target_urgency,
+                    days_until_target=summary.days_until_target,
+                    energy_floor=plan.energy_floor,
+                    eligible=eligible,
+                    next_milestone=next_milestone.title if next_milestone else "",
+                    next_milestone_index=next_milestone.index if next_milestone else None,
+                    milestone_done=summary.milestone_done,
+                    milestone_total=summary.milestone_total,
+                    ready=ready,
+                )
+            )
+
+        return cls(
+            matchable=tuple(matchable),
+            synthesise=tuple(synthesise),
+            match_keys=frozenset(keys),
+            summaries=tuple(summaries),
+            deferred=tuple(deferred),
+            completions=tuple(completions),
+            warnings=tuple(warnings),
+        )
+
+    def milestone_candidates(
+        self, candidates: list[_Candidate], time_minutes: int
+    ) -> list[_Candidate]:
+        """Rule 6: one candidate per eligible plan whose next milestone nothing represents."""
+        present = [_candidate_keys(candidate) for candidate in candidates]
+        synthesised: list[_Candidate] = []
+        for plan in self.synthesise:
+            milestone = plan.next_milestone
+            if milestone is None:  # pragma: no cover — ``synthesise`` only holds plans with one
+                continue
+            concept_keys = _milestone_concept_keys(plan)
+            if concept_keys and any(keys & concept_keys for keys in present):
+                continue
+            synthesised.append(_milestone_candidate(plan, milestone, time_minutes))
+        return synthesised
+
+    def attach_refs(self, candidate: _Candidate) -> _Candidate:
+        """Rule 7: every matching plan, most specific milestone per plan, in plan order."""
+        keys = _candidate_keys(candidate)
+        refs: dict[str, int | None] = {
+            ref.plan_id: ref.milestone_index for ref in candidate.plan_refs
+        }
+        for plan in self.matchable:
+            plan_id = plan.plan.plan_id
+            if not keys & frozenset(plan.match_keys):
+                continue
+            index = (
+                plan.next_milestone.index
+                if plan.next_milestone is not None and keys & _milestone_concept_keys(plan)
+                else None
+            )
+            if refs.get(plan_id) is None:
+                refs[plan_id] = index
+        if not refs:
+            return candidate
+        ordered = tuple(
+            PlanRef(plan.plan.plan_id, refs[plan.plan.plan_id])
+            for plan in self.matchable
+            if plan.plan.plan_id in refs
+        )
+        return dataclasses.replace(candidate, plan_refs=ordered)
+
+
+def _milestone_candidate(
+    plan: ActivePlanGuidance, milestone: MilestoneView, time_minutes: int
+) -> _Candidate:
+    """The synthesised candidate for a plan's next milestone (rule 6)."""
+    summary = plan.plan
+    concept = next((item.strip() for item in milestone.concepts if item.strip()), milestone.title)
+    topic = summary.topics[0] if summary.topics else "study"
+    source = f"{PLAN_SOURCE_PREFIX}{summary.plan_id}:{milestone.index}"
+    days = summary.days_until_target
+    if plan.target_urgency == "overdue":
+        target_note = "; the plan's target date has passed"
+    elif days == 0:
+        target_note = "; the plan's target date is today"
+    elif days is not None:
+        target_note = f"; target date in {days} day(s)"
+    else:
+        target_note = ""
+    reason = (
+        f"Next milestone {milestone.index + 1}/{summary.milestone_total} of plan "
+        f"{summary.title!r}: {milestone.title}{target_note}"
+    )
+    return _Candidate(
+        concept=concept,
+        topic=topic,
+        course=None,
+        reason=reason,
+        action_type="conversation",
+        estimated_minutes=_estimate_minutes("conversation", time_minutes, 20),
+        source=source,
+        evidence_command=_evidence_command("conversation", concept, topic, source),
+        score=MILESTONE_BASE_SCORE + _MILESTONE_URGENCY_BONUS.get(plan.target_urgency, 0),
+        metadata={
+            "plan_id": summary.plan_id,
+            "milestone_index": milestone.index,
+            "milestone": milestone.title,
+            "target_urgency": plan.target_urgency,
+            "energy_floor": plan.energy_floor,
+        },
+        plan_refs=(PlanRef(summary.plan_id, milestone.index),),
+    )
+
+
+def _guarantee_plan_backed(ranked: list[_Candidate], time_minutes: int) -> list[_Candidate]:
+    """Rule 8: ≥ 1 plan-backed action among primary + alternates when time permits.
+
+    Never re-ranks the primary: the best-ranked eligible plan-backed candidate
+    that fits the time window replaces the *last* alternate only. Deferred
+    milestones were never synthesised, so every plan-backed candidate here is
+    eligible on energy.
+    """
+    if len(ranked) <= 3 or any(candidate.plan_refs for candidate in ranked[:3]):
+        return ranked
+    for position in range(3, len(ranked)):
+        candidate = ranked[position]
+        if candidate.plan_refs and candidate.estimated_minutes <= time_minutes:
+            return [
+                *ranked[:2],
+                candidate,
+                *ranked[2:position],
+                *ranked[position + 1 :],
+            ]
+    return ranked
+
+
 def build_now_plan(
     *,
     energy: EnergyLevel = "medium",
@@ -539,8 +940,19 @@ def build_now_plan(
     modality: Modality = "recall",
     interleave: InterleaveMode = "off",
 ) -> NowPlan:
-    """Return the best current study action plus two alternatives."""
+    """Return the best current study action plus two alternatives.
+
+    Order of operations is design §3's: guidance is read once (1), candidates
+    are collected as before (2), the energy capability decides which next
+    milestones are eligible (3), matching is key equality (4), scoring is
+    today's plus the plan bias (5), an unrepresented eligible milestone is
+    synthesised (6), then de-duplication and reference attachment (7), the
+    plan-backed guarantee (8), with fully-checked plans reported as
+    completion actions rather than candidates (9).
+    """
     time_minutes = max(5, min(int(time_minutes), 180))
+    now = datetime.now(UTC)
+    plans = _PlanContext.build(_load_guidance(now.date()), energy=energy)

     candidates = [
         *_due_card_candidates(time_minutes),
@@ -551,6 +963,7 @@ def build_now_plan(
     ]
     if interleave == "adaptive" and energy != "low":
         candidates.extend(_transfer_candidates(time_minutes))
+    candidates.extend(plans.milestone_candidates(candidates, time_minutes))

     starter = False
     if not candidates:
@@ -563,8 +976,13 @@ def build_now_plan(
             energy=energy,
             modality=modality,
             interleave=interleave,
+            plan_keys=plans.match_keys,
         )
     )
+    if plans.matchable:
+        ranked = _guarantee_plan_backed(
+            [plans.attach_refs(candidate) for candidate in ranked], time_minutes
+        )
     primary = ranked[0].recommendation()
     alternates = [item.recommendation() for item in ranked[1:3]]
     return NowPlan(
@@ -572,9 +990,13 @@ def build_now_plan(
         time_minutes=time_minutes,
         modality=modality,
         interleave=interleave,
-        generated_at=datetime.now(UTC).isoformat(),
+        generated_at=now.isoformat(),
         starter=starter,
         primary=primary,
         alternates=alternates,
         interleave_ratio=INTERLEAVE_RATIOS[energy] if interleave == "adaptive" else {},
+        active_plans=plans.summaries,
+        energy_deferred=plans.deferred,
+        completion_actions=plans.completions,
+        warnings=plans.warnings,
     )
```

### `packages/studyloop/src/studyloop/cli/_now.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/cli/_now.py b/packages/studyloop/src/studyloop/cli/_now.py
index 27447f25..425a6785 100644
--- a/packages/studyloop/src/studyloop/cli/_now.py
+++ b/packages/studyloop/src/studyloop/cli/_now.py
@@ -13,16 +13,43 @@ from studyloop.learning import EnergyLevel, InterleaveMode, Modality, build_now_
 from studyloop.learning.voice import speak_text


+def _active_plans(plan) -> dict:
+    """``plan_id → ActivePlanSummary`` for every active plan the engine listed."""
+    return {entry.plan_id: entry for entry in getattr(plan, "active_plans", ())}
+
+
+def _plan_line(rec, plans: dict) -> str:
+    """One line naming every plan an action advances, in the engine's order.
+
+    Rendering only: the refs and their order come from the ranker; a
+    milestone is named when the ref points at one.
+    """
+    parts: list[str] = []
+    for ref in getattr(rec, "plan_refs", ()):
+        entry = plans.get(ref.plan_id)
+        label = entry.title if entry is not None else ref.plan_id
+        if ref.milestone_index is not None:
+            label += f" (milestone {ref.milestone_index + 1}"
+            if entry is not None and entry.next_milestone_index == ref.milestone_index:
+                label += f": {entry.next_milestone}"
+            label += ")"
+        parts.append(label)
+    return "; ".join(parts)
+
+
 def _render_plan(plan) -> None:
     primary = plan.primary
+    plans = _active_plans(plan)
+    plan_line = _plan_line(primary, plans)
     body = (
         f"[bold]{primary.concept}[/bold]\n"
         f"Topic: [cyan]{primary.topic}[/cyan]\n"
         f"Action: [yellow]{primary.action_type}[/yellow] for about "
         f"{primary.estimated_minutes} min\n"
         f"Why: {primary.reason}\n"
-        f"Source: [dim]{primary.source}[/dim]\n\n"
-        f"[bold]Record evidence:[/bold]\n{primary.evidence_command}"
+        f"Source: [dim]{primary.source}[/dim]\n"
+        + (f"Plan: [magenta]{plan_line}[/magenta]\n" if plan_line else "")
+        + f"\n[bold]Record evidence:[/bold]\n{primary.evidence_command}"
     )
     console.print(Panel(body, title="Study Now", border_style="cyan"))

@@ -30,14 +57,31 @@ def _render_plan(plan) -> None:
         ratio = " | ".join(f"{name}: {pct}%" for name, pct in plan.interleave_ratio.items())
         console.print(f"[dim]Adaptive interleave mix: {ratio}[/dim]")

+    for deferred in getattr(plan, "energy_deferred", ()):
+        console.print(
+            f"[yellow]Deferred for energy:[/yellow] {deferred.plan_title} — "
+            f"milestone {deferred.milestone_index + 1} “{deferred.title}” needs "
+            f"energy {deferred.energy_floor}/10; {plan.energy} energy carries "
+            f"{deferred.energy_capability}/10. Plan-related review and repair stay available."
+        )
+    for completion in getattr(plan, "completion_actions", ()):
+        console.print(f"[green]Plan complete:[/green] {completion.action}")
+    for warning in getattr(plan, "warnings", ()):
+        console.print(f"[dim]Plan warning: {warning}[/dim]")
+
     if plan.alternates:
         table = Table(title="Alternates")
         table.add_column("Concept", style="bold")
         table.add_column("Topic", style="cyan")
         table.add_column("Action")
         table.add_column("Why")
+        if plans:
+            table.add_column("Plan", style="magenta")
         for item in plan.alternates:
-            table.add_row(item.concept, item.topic, item.action_type, item.reason)
+            row = [item.concept, item.topic, item.action_type, item.reason]
+            if plans:
+                row.append(_plan_line(item, plans))
+            table.add_row(*row)
         console.print(table)


@@ -84,10 +128,12 @@ def now(
         _render_plan(plan)

     if speak:
+        plan_line = _plan_line(plan.primary, _active_plans(plan))
         spoken = (
             f"Study {plan.primary.concept}. "
             f"Use {plan.primary.action_type} for about {plan.primary.estimated_minutes} minutes. "
             f"{plan.primary.reason}."
+            + (f" This advances your plan {plan_line}." if plan_line else "")
         )
         if not speak_text(spoken):
             console.print(
```

### `packages/studyloop/src/studyloop/learning/recap.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/learning/recap.py b/packages/studyloop/src/studyloop/learning/recap.py
index 4b2c6af3..b9f995fd 100644
--- a/packages/studyloop/src/studyloop/learning/recap.py
+++ b/packages/studyloop/src/studyloop/learning/recap.py
@@ -12,17 +12,62 @@ class DailyRecap:
     due_item: str
     next_action: str
     has_data: bool
+    #: How the next action relates to the learner's active study plans, and
+    #: which plan milestones today's energy deferred — rendering of what the
+    #: decision engine already ranked, never a second ranking. Empty when no
+    #: plan is active, and then absent from :meth:`to_json_dict` and
+    #: :meth:`speakable_text` so a plan-less recap is what it always was.
+    plan_context: str = ""

     def to_json_dict(self) -> dict:
-        return asdict(self)
+        data = asdict(self)
+        if not self.plan_context:
+            del data["plan_context"]
+        return data

     def speakable_text(self) -> str:
-        return (
+        text = (
             f"Win: {self.win}. "
             f"Repair target: {self.repair_target}. "
             f"Due item: {self.due_item}. "
             f"Next action: {self.next_action}."
         )
+        if self.plan_context:
+            text += f" Plan: {self.plan_context}"
+        return text
+
+
+def _plan_context(plan) -> str:
+    """Describe the engine's plan guidance for the recap — show, do not re-rank.
+
+    Reads the additive ``NowPlan`` fields defensively so a plan object from
+    an older caller or a test double without them renders an empty context.
+    """
+    plans = {entry.plan_id: entry for entry in getattr(plan, "active_plans", ())}
+    sentences: list[str] = []
+
+    advances: list[str] = []
+    for ref in getattr(getattr(plan, "primary", None), "plan_refs", ()):
+        entry = plans.get(ref.plan_id)
+        label = entry.title if entry is not None else ref.plan_id
+        if ref.milestone_index is not None:
+            label += f" (milestone {ref.milestone_index + 1}"
+            if entry is not None and entry.next_milestone_index == ref.milestone_index:
+                label += f", {entry.next_milestone}"
+            label += ")"
+        advances.append(label)
+    if advances:
+        sentences.append(f"The next action advances {'; '.join(advances)}.")
+
+    for deferred in getattr(plan, "energy_deferred", ()):
+        sentences.append(
+            f"Milestone {deferred.milestone_index + 1} of {deferred.plan_title}, "
+            f"{deferred.title}, waits for more energy: it needs {deferred.energy_floor} of 10 "
+            f"and today's energy carries {deferred.energy_capability}."
+        )
+    for completion in getattr(plan, "completion_actions", ()):
+        sentences.append(completion.action)
+    return " ".join(sentences)


 def build_daily_recap() -> DailyRecap:
@@ -64,4 +109,5 @@ def build_daily_recap() -> DailyRecap:
         due_item=due_item,
         next_action=plan.primary.evidence_command,
         has_data=has_data,
+        plan_context=_plan_context(plan),
     )
```

### Today card — `web/static/index.html` and `web/static/js/components/today-panel.js` — diff vs `0a20a796` (JS test `tests/js/today-panel-plan.test.js`, 6 tests, not reproduced: `planLabel` names the plan and its milestone; keeps every referenced plan in engine order; `deferredNotes` one line per deferral; `completionNotes` verbatim; a payload without plan keys renders no plan text; a ref to a plan missing from `active_plans` falls back to the id, never throws)

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/index.html b/packages/studyloop/src/studyloop/web/static/index.html
index 6d35b6de..3d8032f5 100644
--- a/packages/studyloop/src/studyloop/web/static/index.html
+++ b/packages/studyloop/src/studyloop/web/static/index.html
@@ -1085,7 +1085,27 @@
             </p>
             <p class="today-reason">Why: <span x-text="plan?.primary?.reason"></span></p>
+            <!-- Plan relevance (#10): which active plan this action advances.
+                 Rendered from the engine's plan_refs; nothing here re-ranks. -->
+            <p class="today-meta today-plan" x-show="planLabel(plan?.primary)">
+              Advances plan: <span x-text="planLabel(plan?.primary)"></span>
+            </p>
             <button class="toggle-btn today-start-btn" @click="startPrimary()">Start →</button>
           </div>

+          <!-- Plan guidance the ranker set aside: milestones today's energy
+               cannot carry, and plans whose every milestone is checked.
+               Not a `.today-card` on purpose: the browser smoke test addresses
+               the single action card by that class. -->
+          <div x-show="!loading && plan && (deferredNotes().length > 0 || completionNotes().length > 0)"
+               class="today-plan-notes">
+            <p class="today-parked-label">Your plans</p>
+            <template x-for="(note, i) in deferredNotes()" :key="'d' + i">
+              <p class="today-meta">Deferred for energy: <span x-text="note"></span></p>
+            </template>
+            <template x-for="(note, i) in completionNotes()" :key="'c' + i">
+              <p class="today-meta">Plan complete: <span x-text="note"></span></p>
+            </template>
+          </div>
+
           <!-- Alternates, collapsed by default -->
           <div x-show="!loading && plan && !plan.starter && (plan.alternates || []).length > 0"
@@ -1099,5 +1119,5 @@
                 <li class="today-alt-item">
                   <button class="today-alt-btn" @click="startAction(alt)">
-                    <span x-text="alt.concept"></span>
+                    <span x-text="alt.concept + (planLabel(alt) ? ' — plan: ' + planLabel(alt) : '')"></span>
                     <span class="today-alt-meta" x-text="'~' + alt.estimated_minutes + ' min · ' + alt.action_type"></span>
                   </button>
```

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js b/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
index 00ea88b1..b113078c 100644
--- a/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
+++ b/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
@@ -118,4 +118,62 @@ export function todayPanel() {
     },

+    /* ---- Plan relevance (issue #10) — rendering of what /api/now ranked. ----
+       The engine attaches `plan_refs` to an action and lists `active_plans`,
+       `energy_deferred` and `completion_actions` beside it, each key present
+       only when non-empty. These helpers turn that into text; none of them
+       changes which action is primary. A payload without the keys — the shape
+       a learner with no active plan gets — yields empty strings and lists. */
+
+    _activePlan(planId) {
+      const plans = (this.plan && this.plan.active_plans) || [];
+      return plans.find((p) => p.plan_id === planId) || null;
+    },
+
+    /* "SQL Windows · milestone 2: Frames; Other Plan" — every referenced plan,
+       in the engine's order; the milestone is named when the ref points at
+       the plan's next milestone. A ref to a plan the payload does not list
+       falls back to its id rather than throwing mid-render. */
+    planLabel(rec) {
+      const refs = (rec && rec.plan_refs) || [];
+      return refs
+        .map((ref) => {
+          const plan = this._activePlan(ref.plan_id);
+          let label = plan ? plan.title : ref.plan_id;
+          if (
+            ref.milestone_index != null &&
+            plan &&
+            plan.next_milestone_index === ref.milestone_index &&
+            plan.next_milestone
+          ) {
+            label += ` \u00b7 milestone ${ref.milestone_index + 1}: ${plan.next_milestone}`;
+          }
+          return label;
+        })
+        .join('; ');
+    },
+
+    deferredNotes() {
+      const deferred = (this.plan && this.plan.energy_deferred) || [];
+      const energy = (this.plan && this.plan.energy) || 'current';
+      return deferred.map(
+        (d) =>
+          `${d.plan_title} \u2014 \u201c${d.title}\u201d waits for more energy `
+          + `(needs ${d.energy_floor}/10, ${energy} energy carries ${d.energy_capability}/10)`,
+      );
+    },
+
+    completionNotes() {
+      const actions = (this.plan && this.plan.completion_actions) || [];
+      return actions.map((a) => a.action);
+    },
+
+    get hasPlanContext() {
+      return (
+        this.planLabel(this.plan && this.plan.primary) !== ''
+        || this.deferredNotes().length > 0
+        || this.completionNotes().length > 0
+      );
+    },
+
     pickUpParked(p) {
       window.dispatchEvent(new CustomEvent('today-resume', {
```

### `packages/studyloop/tests/test_now_plan_guidance.py` (full source at `575e26ff`)

```python
"""Plan-aware ``now`` — issue #10 (design §3; decisions D-5, D-16).

The one non-negotiable in this module is the golden: with **no active plan**
the JSON ``studyloop now --json`` / ``GET /api/now`` emit must be byte for
byte what it was before any plan-awareness existed
(``tests/golden/now_plan_no_active.json``, captured on the pre-#10 tree). The
additive ``NowPlan`` keys and ``plan_refs`` are therefore emitted only when
non-empty (D-5).

Everything the engine reads is isolated here — an empty sessions database, an
empty plans directory, empty content roots, a config with no topics and no
focus — and the engine's clock is frozen, so the emit is a function of the
fixtures alone and the golden holds on any machine.

The ranking tests prove *ranking compliance* with the nine ordered rules of
design §3 — not learner benefit, which is a separate, later measurement
(D-16). Candidates are injected through the same collector monkeypatches
``test_learning_decision.py`` uses; plans are real documents written through
the store into the isolated plans directory and read back through
``PlanApplication().get_active_guidance()``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from studyloop.learning import decision
from studyloop.learning.decision import PlanRef, _Candidate, build_now_plan
from studyloop.planning import store
from studyloop.planning.models import Milestone, Mission, StudyPlan

if TYPE_CHECKING:
    from studyloop.learning.decision import NowPlan

GOLDEN = Path(__file__).parent / "golden" / "now_plan_no_active.json"

#: One frozen instant for ``generated_at`` and for every date derived from it.
FROZEN_NOW = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
TODAY = FROZEN_NOW.date()

OVERDUE = "2026-09-10"  # six days before TODAY
SOON = "2026-09-18"  # two days after TODAY
LATER = "2026-10-30"  # well past the seven-day "soon" window


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` always answers :data:`FROZEN_NOW`."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return FROZEN_NOW if tz is None else FROZEN_NOW.astimezone(tz)


def isolate_now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every input of ``build_now_plan`` at an empty world and freeze its clock.

    A plain function (not a fixture) so the golden capture script could call
    it the same way the tests do; the fixture below is its pytest face.
    """
    content = tmp_path / "content"
    study = tmp_path / "study"
    content.mkdir()
    study.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(
        "content:\n"
        f"  base_path: {content}\n"
        f"  study_paths: [{study}]\n"
        "review:\n"
        f"  directories: [{content}]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("STUDYLOOP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    monkeypatch.setattr(decision, "datetime", _FrozenDatetime)
    return tmp_path


@pytest.fixture(autouse=True)
def now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_now_world(tmp_path, monkeypatch)


def serialise(plan: NowPlan) -> bytes:
    """The exact bytes the golden file holds for a plan."""
    return (json.dumps(plan.to_json_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _candidate(
    concept: str,
    *,
    topic: str = "python",
    course: str | None = None,
    action_type: str = "recall",
    score: float = 50,
) -> _Candidate:
    return _Candidate(
        concept=concept,
        topic=topic,
        course=course,
        reason=f"reason for {concept}",
        action_type=action_type,  # type: ignore[arg-type]
        estimated_minutes=10,
        source=f"test:{concept}",
        evidence_command=f'studyloop progress "{concept}" -t "{topic}" -c learning',
        score=score,
    )


def _patch_collectors(monkeypatch: pytest.MonkeyPatch, *candidates: _Candidate) -> None:
    """Silence every collector; inject ``candidates`` as due-progress items."""
    for name in (
        "_due_card_candidates",
        "_due_progress_candidates",
        "_struggle_candidates",
        "_continuity_candidates",
        "_practice_candidates",
        "_transfer_candidates",
    ):
        monkeypatch.setattr(decision, name, lambda time_minutes: [])
    if candidates:
        monkeypatch.setattr(
            decision, "_due_progress_candidates", lambda time_minutes: list(candidates)
        )


def _plan(
    plan_id: str,
    *,
    title: str | None = None,
    topics: list[str] | None = None,
    milestones: list[Milestone] | None = None,
    target_date: str = "",
    energy_floor: int = 3,
    updated: str = "2026-09-01T00:00:00+00:00",
    status: str = "active",
) -> StudyPlan:
    """Write a ready plan document into the isolated plans directory."""
    plan = StudyPlan(
        plan_id=plan_id,
        title=title or plan_id.replace("-", " ").title(),
        status=status,
        created="2026-08-01T00:00:00+00:00",
        updated=updated,
        topics=topics if topics is not None else ["sql"],
        energy_floor=energy_floor,
        target_date=target_date,
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=(
            milestones
            if milestones is not None
            else [Milestone(title="Window basics", concepts=["window function"])]
        ),
    )
    store.create_plan(plan)
    return plan


def _all(plan: NowPlan):
    return [plan.primary, *plan.alternates]


# ---------------------------------------------------------------------------
# T3.1 — the golden: no active plans → the pre-#10 emit, byte for byte
# ---------------------------------------------------------------------------


def test_no_active_plans_json_byte_identical_to_golden() -> None:
    plan = build_now_plan()

    assert plan.starter is True, "an empty world must still yield the starter recommendation"
    assert serialise(plan) == GOLDEN.read_bytes()


# ---------------------------------------------------------------------------
# T3.2 — the nine ordered rules of design §3
# ---------------------------------------------------------------------------


def test_matching_due_concept_outranks_unrelated_same_urgency(monkeypatch) -> None:
    """Rule 5: within one urgency class, plan-related beats unrelated."""
    _plan("sql-windows")
    unrelated = _candidate("decorators", topic="python", score=102)
    matching = _candidate("window function", topic="sql", score=100)
    _patch_collectors(monkeypatch, unrelated, matching)

    plan = build_now_plan()

    assert plan.primary.concept == "window function"
    assert plan.primary.plan_refs == (PlanRef("sql-windows", 0),)
    assert plan.alternates[0].concept == "decorators"
    assert plan.alternates[0].plan_refs == ()


def test_unrelated_more_urgent_due_outranks_new_milestone(monkeypatch) -> None:
    """Rule 5 is a bias, not a filter: a globally more-urgent unrelated due item wins."""
    _plan("sql-windows")
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    assert plan.primary.concept == "decorators"
    assert plan.primary.plan_refs == ()
    synthesised = [r for r in plan.alternates if r.source == "study_plan:sql-windows:0"]
    assert len(synthesised) == 1
    assert synthesised[0].concept == "window function"
    assert synthesised[0].plan_refs == (PlanRef("sql-windows", 0),)
    assert synthesised[0].score < plan.primary.score


def test_one_action_keeps_every_matching_plan_ref_ordered(monkeypatch) -> None:
    """Rule 7: every matching ref is kept, ordered urgency → latest update → plan id."""
    _plan("later-plan", target_date=LATER, updated="2026-09-14T00:00:00+00:00")
    _plan("undated-c", updated="2026-09-10T00:00:00+00:00")
    _plan("undated-a", updated="2026-09-12T00:00:00+00:00")
    _plan("undated-b", updated="2026-09-10T00:00:00+00:00")
    _plan("soon-plan", target_date=SOON, updated="2026-08-01T00:00:00+00:00")
    _plan("overdue-plan", target_date=OVERDUE, updated="2026-07-01T00:00:00+00:00")
    _patch_collectors(monkeypatch, _candidate("window function", topic="sql", score=100))

    plan = build_now_plan()

    expected = ["overdue-plan", "soon-plan", "later-plan", "undated-a", "undated-b", "undated-c"]
    assert plan.primary.plan_refs == tuple(PlanRef(plan_id, 0) for plan_id in expected)
    assert [entry.plan_id for entry in plan.active_plans] == expected


def test_milestone_without_concepts_does_not_substring_match(monkeypatch) -> None:
    """Rule 4: equality on the normalised key — never a substring test."""
    _plan(
        "sql-windows",
        topics=["sql"],
        milestones=[Milestone(title="Window functions deep dive")],
    )
    superstring = _candidate("window functions deep dive tutorial", topic="python", score=100)
    substring = _candidate("window", topic="python", score=99)
    topic_match = _candidate("joins", topic="SQL", score=98)
    _patch_collectors(monkeypatch, superstring, substring, topic_match)

    plan = build_now_plan()

    by_concept = {rec.concept: rec for rec in _all(plan)}
    assert by_concept["window functions deep dive tutorial"].plan_refs == ()
    assert by_concept["window"].plan_refs == ()
    # A topic match is plan-related but names no milestone.
    assert by_concept["joins"].plan_refs == (PlanRef("sql-windows", None),)
    assert plan.primary.concept == "joins"


def test_energy_below_floor_defers_new_milestone_keeps_repair(monkeypatch) -> None:
    """Rule 3: below the floor new-milestone work is deferred; plan-related repair stays."""
    _plan(
        "sql-windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
    )
    repair = _candidate("window function", topic="sql", action_type="hands-on", score=82)
    _patch_collectors(monkeypatch, repair)

    low = build_now_plan(energy="low")

    assert low.primary.concept == "window function"
    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
    assert [
        (d.plan_id, d.milestone_index, d.energy_floor, d.energy_capability)
        for d in low.energy_deferred
    ] == [("sql-windows", 1, 5, 3)]
    assert not any(rec.source.startswith("study_plan:") for rec in _all(low))

    medium = build_now_plan(energy="medium")

    assert medium.energy_deferred == ()
    assert any(rec.source == "study_plan:sql-windows:1" for rec in medium.alternates)


def test_fully_checked_active_plan_emits_completion_not_candidate(monkeypatch) -> None:
    """Rule 9: a fully-checked plan yields a completion action, never a study candidate."""
    _plan(
        "done-plan",
        title="Done Plan",
        milestones=[
            Milestone(title="A", done=True, concepts=["alpha"]),
            Milestone(title="B", done=True, concepts=["beta"]),
        ],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    assert [action.plan_id for action in plan.completion_actions] == ["done-plan"]
    assert "Done Plan" in plan.completion_actions[0].action
    assert not any(rec.source.startswith("study_plan:") for rec in _all(plan))
    assert plan.active_plans[0].plan_id == "done-plan"
    assert plan.active_plans[0].next_milestone_index is None


def test_synthesizes_milestone_when_no_candidate_represents_it(monkeypatch) -> None:
    """Rule 6: an unrepresented eligible next milestone becomes a candidate."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        milestones=[Milestone(title="Frames", concepts=["window frame", "rows between"])],
    )
    _patch_collectors(monkeypatch)

    plan = build_now_plan()

    assert plan.starter is False
    assert plan.primary.concept == "window frame"
    assert plan.primary.topic == "sql"
    assert plan.primary.action_type == "conversation"
    assert plan.primary.source == "study_plan:sql-windows:0"
    assert plan.primary.plan_refs == (PlanRef("sql-windows", 0),)
    assert "SQL Windows" in plan.primary.reason
    assert "Frames" in plan.primary.reason
    assert plan.primary.evidence_command == (
        'studyloop progress "window frame" -t "sql" -c learning'
    )


def test_preserves_one_plan_backed_action_when_energy_allows(monkeypatch) -> None:
    """Rule 8: ≥ 1 eligible plan-backed action in primary + alternates when energy permits."""
    _plan(
        "sql-windows", energy_floor=5, milestones=[Milestone("Frames", concepts=["window frame"])]
    )
    unrelated = [_candidate(f"due {i}", topic="python", score=140 - 2 * i) for i in range(4)]
    _patch_collectors(monkeypatch, *unrelated)

    medium = build_now_plan(energy="medium")

    assert medium.primary.concept == "due 0"
    assert [rec.concept for rec in medium.alternates] == ["due 1", "window frame"]
    assert medium.alternates[1].plan_refs == (PlanRef("sql-windows", 0),)

    low = build_now_plan(energy="low")

    assert [rec.concept for rec in _all(low)] == ["due 0", "due 1", "due 2"]
    assert [d.milestone_index for d in low.energy_deferred] == [0]


def test_additive_keys_present_only_when_active_plans_exist(monkeypatch) -> None:
    """D-5: additive keys and ``plan_refs`` appear only when non-empty."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _plan("draft-plan", status="draft")
    _patch_collectors(monkeypatch)

    # A non-active plan changes nothing — byte for byte.
    assert serialise(build_now_plan()) == GOLDEN.read_bytes()

    _plan("sql-windows", milestones=[Milestone("Frames", concepts=["window frame"])])
    with_plan = build_now_plan().to_json_dict()

    assert list(with_plan) == [*golden, "active_plans"]
    assert list(with_plan["primary"]) == [*golden["primary"], "plan_refs"]
    assert with_plan["primary"]["plan_refs"] == [{"plan_id": "sql-windows", "milestone_index": 0}]
    assert with_plan["active_plans"][0]["plan_id"] == "sql-windows"
    for absent in ("energy_deferred", "completion_actions", "warnings"):
        assert absent not in with_plan


# ---------------------------------------------------------------------------
# Renderers show plan relevance and energy deferral — and never re-rank
# ---------------------------------------------------------------------------


def _deferral_world(monkeypatch) -> None:
    """One active plan whose next milestone is beyond low energy, plus plan-related repair."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
    )
    _patch_collectors(
        monkeypatch,
        _candidate("window function", topic="sql", action_type="hands-on", score=82),
    )


def test_cli_now_renders_plan_relevance_and_energy_deferral(monkeypatch) -> None:
    from click.testing import CliRunner

    from studyloop.cli import cli

    _deferral_world(monkeypatch)

    rich = CliRunner().invoke(cli, ["now", "--energy", "low"])
    as_json = CliRunner().invoke(cli, ["now", "--energy", "low", "--json"])

    assert rich.exit_code == 0, rich.output
    assert "window function" in rich.output  # the primary is unchanged
    assert "SQL Windows" in rich.output  # …and its plan relevance is shown
    assert "Deferred" in rich.output
    assert "Frames" in rich.output
    assert as_json.exit_code == 0, as_json.output
    payload = json.loads(as_json.output)
    assert payload["primary"]["concept"] == "window function"
    assert payload["primary"]["plan_refs"] == [{"plan_id": "sql-windows", "milestone_index": None}]
    assert payload["energy_deferred"][0]["milestone_index"] == 1
    assert payload["active_plans"][0]["title"] == "SQL Windows"


def test_cli_now_without_plans_prints_no_plan_lines(monkeypatch) -> None:
    from click.testing import CliRunner

    from studyloop.cli import cli

    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    rich = CliRunner().invoke(cli, ["now"])

    assert rich.exit_code == 0, rich.output
    assert "decorators" in rich.output
    for absent in ("Plan", "Deferred", "milestone"):
        assert absent not in rich.output


def test_api_now_carries_plan_guidance_end_to_end(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

    from studyloop.web.app import create_app

    _deferral_world(monkeypatch)
    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/now?energy=low")

    assert resp.status_code == 200
    data = resp.json()
    assert data["primary"]["concept"] == "window function"
    assert data["primary"]["plan_refs"] == [{"plan_id": "sql-windows", "milestone_index": None}]
    assert [item["plan_id"] for item in data["active_plans"]] == ["sql-windows"]
    assert data["energy_deferred"][0]["title"] == "Frames"
    assert "completion_actions" not in data
    assert "warnings" not in data


def test_api_now_without_plans_matches_golden_shape(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

    from studyloop.web.app import create_app

    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/now")

    assert resp.status_code == 200
    assert resp.json() == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_recap_shows_plan_context_without_reranking(monkeypatch) -> None:
    from studyloop.learning import recap

    _plan(
        "sql-windows",
        title="SQL Windows",
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _patch_collectors(monkeypatch)

    result = recap.build_daily_recap()

    # The next action is still the engine's primary — the synthesised milestone.
    assert result.next_action == 'studyloop progress "window frame" -t "sql" -c learning'
    assert "SQL Windows" in result.plan_context
    assert "Frames" in result.plan_context
    assert result.to_json_dict()["plan_context"] == result.plan_context
    assert "Plan:" in result.speakable_text()


def test_recap_without_plans_has_no_plan_context(monkeypatch) -> None:
    from studyloop.learning import recap

    _patch_collectors(monkeypatch)

    result = recap.build_daily_recap()

    assert result.plan_context == ""
    assert "plan_context" not in result.to_json_dict()
    assert "Plan:" not in result.speakable_text()
    assert result.speakable_text().endswith(f"Next action: {result.next_action}.")


def test_recap_names_energy_deferral(monkeypatch) -> None:
    from studyloop.learning import recap

    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=8,  # beyond the recap's default medium energy (6/10)
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    result = recap.build_daily_recap()

    assert result.next_action == 'studyloop progress "decorators" -t "python" -c learning'
    assert "Frames" in result.plan_context
    assert "energy" in result.plan_context
```

### `packages/studyloop/tests/golden/now_plan_no_active.json` (sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`)

```json
{
  "energy": "medium",
  "time_minutes": 25,
  "modality": "recall",
  "interleave": "off",
  "generated_at": "2026-09-16T09:30:00+00:00",
  "starter": true,
  "interleave_ratio": {},
  "primary": {
    "concept": "one tiny recall loop",
    "topic": "python",
    "reason": "No learning evidence found yet; start by creating one small retrieval signal",
    "action_type": "recall",
    "estimated_minutes": 10,
    "source": "starter",
    "evidence_command": "studyloop progress \"one tiny recall loop\" -t \"python\" -c learning",
    "score": 28,
    "course": "python",
    "metadata": {
      "display_name": "Python"
    }
  },
  "alternates": []
}
```

### `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md` (D-16 receipt, verbatim)

```markdown
# Plan-aware `now` — five-scenario human rubric (D-16) · 2026-09-16

**Status: owner verdicts PENDING.** This receipt was produced unattended
overnight. Every scenario below was *run* on frozen fixtures and the primary
and its rationale are recorded exactly as the engine emitted them; the
"would I do the primary?" column is a human judgement that only the owner can
give, so it is left `PENDING` rather than faked. Ranking compliance is proven
by `packages/studyloop/tests/test_now_plan_guidance.py`; this receipt is the
separate, cheaper pre-ship check D-16 asks for, and it proves nothing about
learning (D-16: "plan-aware guidance with tested ranking rules", never "better
learning").

- Tree: `feat/p3-now` at `df33690b` (engine `0f1b3d08`, renderers `df33690b`).
- Golden: `packages/studyloop/tests/golden/now_plan_no_active.json`,
  sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`,
  captured on the pre-#10 tree (`848f413b`).
- Clock frozen at `2026-09-16T09:30:00+00:00`; empty sessions DB, empty plans
  directory, empty content roots, no topics, no focus (the module's
  `isolate_now_world`). Defaults unless stated: energy `medium` (capability
  6/10), 25 minutes, modality `recall`, interleave `off`.
- Candidates are injected through the collector monkeypatches
  `test_learning_decision.py` uses (`_patch_collectors`), so scores are the
  fixtures' base scores plus today's scoring (+18 modality match on `recall`)
  plus the plan bias (+12) where a candidate is plan-related.

## Scenarios

| # | Scenario (D-16 list) | Frozen fixture | Primary emitted | Engine rationale (rule) | Owner verdict: "would I do the primary?" |
|---|---|---|---|---|---|
| 1 | Matching due | Active plan `sql-windows` ("SQL Windows", topics `[sql]`, next milestone 0 concepts `[window function]`). Due items: `decorators`/python base 102, `window function`/sql base 100. | **`window function`** (sql, recall, score 130, `plan_refs=[(sql-windows, 0)]`); alternate `decorators` (120, no refs). | Rule 5: both are due items two points apart — one urgency class — so the plan-related one takes the +12 bias and wins; the unrelated due item is *kept* as an alternate (bias, not filter). Rule 7 names the milestone the action advances. | **PENDING** |
| 2 | Urgent-unrelated wins | Same plan. One due item: `decorators`/python, base 100 (an overdue spaced-repetition review). Nothing represents milestone 0. | **`decorators`** (118, no refs); alternate `window function` (60, `source=study_plan:sql-windows:0`, `plan_refs=[(sql-windows, 0)]`, reason "Next milestone 1/1 of plan 'SQL Windows': Window basics"). | Rule 5: the unrelated candidate is in a more urgent class (due review) and wins outright — the bias cannot lift new-milestone work over it. Rule 6: the plan's next milestone was unrepresented, so it was synthesised at base 48 + bias 12 = 60 and appears as the plan-backed alternate (rule 8 satisfied without any swap). | **PENDING** |
| 3 | Energy-deferred | Plan `sql-windows` with `energy_floor: 5`; milestone 0 `Window basics` **done** (concepts `[window function]`), milestone 1 `Frames` (concepts `[window frame]`). One struggle-repair item `window function`/sql, `hands-on`, base 82. **Energy `low`** (capability 3/10). | **`window function`** (hands-on, score 80, `plan_refs=[(sql-windows, None)]`); no alternates; `energy_deferred=[(sql-windows, milestone 1, floor 5, capability 3)]`; JSON gains `energy_deferred`. | Rule 3: capability 3 < floor 5, so the *new* milestone (Frames) is deferred and named, not synthesised; the plan-related repair on a finished milestone's concept stays eligible and keeps its ref (`None`: plan-related repair, not the next milestone). Score = 82 + 12 bias − 14 (hands-on at low energy). | **PENDING** |
| 4 | Fully-checked | Plan `done-plan` ("Done Plan"), milestones A and B both done. One due item `decorators`/python base 100. | **`decorators`** (118, no refs); `completion_actions=[(done-plan, "Every milestone of 'Done Plan' is checked off — close the plan or extend it with a follow-on mission.")]`; no `study_plan:` candidate anywhere; JSON gains `active_plans` + `completion_actions`. | Rule 9: a fully-checked plan is reported as a completion action and is neither matched (no bias, no refs) nor synthesised. | **PENDING** |
| 5 | No-plan identical | No plan documents at all; no collector candidates. | **`one tiny recall loop`** (python, recall, 28, `source=starter`) — the starter. | D-5: `serialise(plan) == golden` → **byte-identical** (`True` in the run); the JSON key list is exactly the golden's — no additive key is present. | **PENDING** (nothing to judge: output unchanged) |

## How to re-run

```bash
uv run --group dev pytest packages/studyloop/tests/test_now_plan_guidance.py -q -p no:cacheprovider
```

The five rows correspond to
`test_matching_due_concept_outranks_unrelated_same_urgency`,
`test_unrelated_more_urgent_due_outranks_new_milestone`,
`test_energy_below_floor_defers_new_milestone_keeps_repair`,
`test_fully_checked_active_plan_emits_completion_not_candidate` and
`test_no_active_plans_json_byte_identical_to_golden`; the primaries above are
what those tests assert, printed from a throwaway driver over the same
fixtures.

## What the owner should do

Read each primary as if it were this morning's `studyloop now` and replace
`PENDING` with `yes` / `no` + one line. A `no` on rows 1–4 is a finding for
council review 3, not a reason to edit the ranking without one. Post-ship
accept/skip logging tagged `plan_backed|not` remains the follow-on ticket
D-16 names; it is not part of #10's DoD.
```

## 4. #11 — six MCP tools over the seam

### `packages/studyloop/src/studyloop/mcp/tools.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/mcp/tools.py b/packages/studyloop/src/studyloop/mcp/tools.py
index 8dc4caa8..cb0a5a31 100644
--- a/packages/studyloop/src/studyloop/mcp/tools.py
+++ b/packages/studyloop/src/studyloop/mcp/tools.py
@@ -22,6 +22,8 @@ from studyloop.settings import load_settings
 if TYPE_CHECKING:
     from pathlib import Path

+    from studyloop.planning import PlanError
+
 logger = logging.getLogger(__name__)


@@ -852,6 +854,274 @@ def register_tools(mcp: FastMCP, *, include_exercises: bool = False) -> None:
         row_id = park_topic(question, topic_tag=topic_tag, context=context, source="struggled")
         return {"status": "logged", "id": row_id}

+    # ── Study plans — discovery and authoring through the seam (D-4, D-8, D-9) ──
+    #
+    # Six thin adapters over ``studyloop.planning.PlanApplication`` (design §4):
+    # each call is one seam call with one intent, each success is the seam
+    # view's ``to_json_dict()`` (fresh containers), and each refusal is one
+    # ``ToolError`` from ``_plan_tool_error`` below. No plan policy lives here —
+    # the readiness gate, the status list, the id rules and the conflict check
+    # are the seam's, so the same refusal reads the same on the CLI, the Web
+    # and here. The three remaining tools of design §4 (milestone, evaluate,
+    # delete) land in Phase 4 (#12).
+
+    #: ``get_study_plan``'s ``history_limit`` range — the same 1..200 the Web
+    #: history route accepts (``GET /api/plans/{id}/history``, ``Query(20, ge=1,
+    #: le=200)``). Checked before the seam is called, so a refused limit costs
+    #: no database query (council review 1, hazard "Boundary validation").
+    plan_history_limit_range = (1, 200)
+
+    def _plan_tool_error(exc: PlanError) -> ToolError:
+        """Map one seam refusal to a ``ToolError`` an agent can act on.
+
+        The message is ``<kind>: <the seam's own message>``. The kind is
+        machine-readable — ``not_found``, ``invalid_id``, ``conflict``,
+        ``invalid``, ``not_ready``, ``invalid_milestone`` (``plan_error`` for a
+        ``PlanError`` this mapping has not met) — so a client can branch on it
+        without parsing prose; the rest is the domain's wording, unchanged, so
+        the refusal reads as it does on the CLI and the Web (design §2). A
+        not-ready refusal appends the blockers, and says "pause or repair"
+        when the plan is already active, so the agent can tell the learner
+        what to fix rather than that something is wrong.
+        """
+        from studyloop.planning import (
+            InvalidField,
+            InvalidMilestone,
+            InvalidPlanId,
+            PlanConflict,
+            PlanNotFound,
+            PlanNotReady,
+        )
+
+        if isinstance(exc, PlanNotReady):
+            blockers = "; ".join(exc.readiness.blockers)
+            hint = (
+                " — the plan is already active; pause it or repair the blockers before writing"
+                if exc.already_active
+                else ""
+            )
+            return ToolError(f"not_ready: {exc}: {blockers}{hint}")
+        kinds: tuple[tuple[type[Exception], str], ...] = (
+            (PlanNotFound, "not_found"),
+            (InvalidPlanId, "invalid_id"),
+            (PlanConflict, "conflict"),
+            (InvalidField, "invalid"),
+            (InvalidMilestone, "invalid_milestone"),
+        )
+        for error_type, kind in kinds:
+            if isinstance(exc, error_type):
+                return ToolError(f"{kind}: {exc}")
+        return ToolError(f"plan_error: {exc}")
+
+    @tool()
+    def list_study_plans(status: str | None = None) -> dict[str, Any]:
+        """List the learner's study plans (summaries), optionally one status only.
+
+        Active plans come first, then by last update. Use this before
+        proposing a new plan: a plan that already covers the topic should be
+        revised, not duplicated.
+
+        Args:
+            status: Filter to one lifecycle status (``draft``, ``active``,
+                ``paused``, ``complete``, ``abandoned``). Omit for all.
+
+        Returns ``{"plans": [<summary>, ...], "count": N}``; each summary has
+        the keys ``get_study_plan`` returns under ``"plan"``.
+        """
+        from studyloop.planning import PlanApplication, PlanError
+
+        try:
+            plans = PlanApplication().browse(status=status)
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return {"plans": [plan.to_json_dict() for plan in plans], "count": len(plans)}
+
+    @tool()
+    def get_study_plan(
+        plan_id: str,
+        include_markdown: bool = False,
+        include_history: bool = False,
+        history_limit: int = 20,
+    ) -> dict[str, Any]:
+        """Read one study plan in full: summary, mission, milestones, records, readiness.
+
+        ``readiness`` says whether the plan could be active and, if not, which
+        blockers stop it — read it before ``set_study_plan_status(...,
+        "active")`` so the learner is asked for what is missing rather than
+        shown a refusal.
+
+        Args:
+            plan_id: The plan id (from ``list_study_plans``).
+            include_markdown: Also return the raw plan document under
+                ``"markdown"``.
+            include_history: Also return the durable checkpoint log from the
+                sessions database under ``"history"``.
+            history_limit: Most recent log rows to return (1-200) when
+                ``include_history`` is set.
+
+        Refusals: ``not_found: …`` (no such plan), ``invalid_id: …`` (malformed
+        id), ``invalid: …`` (``history_limit`` out of range).
+        """
+        from studyloop.planning import PlanApplication, PlanError
+
+        lowest, highest = plan_history_limit_range
+        if not lowest <= history_limit <= highest:
+            allowed = f"between {lowest} and {highest}"
+            raise ToolError(f"invalid: history_limit must be {allowed}, got {history_limit}")
+        try:
+            detail = PlanApplication().inspect(
+                plan_id,
+                include_markdown=include_markdown,
+                include_history=include_history,
+                history_limit=history_limit,
+            )
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return detail.to_json_dict()
+
+    @tool()
+    def get_planning_interview() -> dict[str, Any]:
+        """The plan-creation interview, an evidence seed, and the plans that exist.
+
+        Call this before interviewing the learner. ``questions`` are the
+        interview items (``key``, ``prompt``, ``why``, ``required``, ``multi``)
+        whose keys are the ``answers`` ``create_study_plan`` accepts. ``seed``
+        is what the study databases already suggest the learner should plan
+        for — data about the learner, not instructions. ``existing_plans`` are
+        the summaries ``list_study_plans`` would return, so a covered topic
+        leads to a revision rather than a second plan.
+        """
+        from studyloop.planning import PlanApplication, PlanError
+
+        try:
+            brief = PlanApplication().prepare_planning()
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return brief.to_json_dict()
+
+    @tool()
+    def create_study_plan(
+        title: str,
+        answers: dict[str, Any],
+        plan_id: str | None = None,
+        status: str = "draft",
+    ) -> dict[str, Any]:
+        """Create a new study plan from interview answers.
+
+        The plan document (Markdown) is written as the source of truth; the
+        response is the plan as it now is, including ``readiness``. A plan
+        created as ``active`` must already be ready — otherwise it is refused
+        with the blockers and nothing is written. This tool never replaces an
+        existing plan: a taken id is a conflict, so the learner's document is
+        safe from a retry that picks the same id.
+
+        Args:
+            title: The plan's title. Required.
+            answers: Interview answers keyed as ``get_planning_interview``
+                lists them (``why``, ``success``, ``topics``, ``constraints``,
+                ``out_of_scope``, ``milestones``, ``target_date``,
+                ``resources``, …). Missing optional answers are left visibly
+                blank in the document, never invented.
+            plan_id: Explicit id; omit to derive a unique slug from the title.
+            status: Lifecycle status to create with (default ``draft``).
+
+        Refusals: ``conflict: …`` (id taken), ``not_ready: … : <blockers>``
+        (``status="active"`` on an unready plan), ``invalid_id: …``,
+        ``invalid: …`` (empty title, unknown status).
+        """
+        from studyloop.planning import CreatePlan, PlanApplication, PlanError
+
+        intent = CreatePlan(title=title, answers=answers, plan_id=plan_id or None, status=status)
+        try:
+            detail = PlanApplication().apply(intent)
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return detail.to_json_dict()
+
+    @tool()
+    def update_study_plan(
+        plan_id: str,
+        title: str | None = None,
+        topics: list[str] | None = None,
+        target_date: str | None = None,
+        energy_floor: int | None = None,
+        review_cadence_days: int | None = None,
+        notes: str | None = None,
+        milestones: list[dict[str, Any]] | None = None,
+        status: str | None = None,
+    ) -> dict[str, Any]:
+        """Revise a study plan in place — any combination of fields, judged as one document.
+
+        Only the arguments you pass change; an omitted argument leaves the
+        field as it is. Everything supplied is applied together and saved
+        once, so repairing the blockers and activating can be one call
+        (``milestones=[...], status="active"``): the readiness check judges
+        the document as it *would be saved*, whichever fields put it there.
+
+        Args:
+            plan_id: The plan id.
+            title: New title (cannot be blank).
+            topics: Full replacement topic list.
+            target_date: ISO date, or ``""`` to clear.
+            energy_floor: 1-10 (clamped).
+            review_cadence_days: 1-90 (clamped).
+            notes: Free-text notes.
+            milestones: Full replacement list; each item is ``{"title", ...}``
+                with optional ``done``, ``concepts``, ``notes``.
+            status: Lifecycle status to move to, alongside the edits.
+
+        Learning records are appended with ``record_plan_learning``, not here.
+        Refusals: ``not_found: …``, ``not_ready: … : <blockers>`` (the
+        resulting document would be active but is not ready), ``invalid: …``.
+        """
+        from studyloop.planning import PlanApplication, PlanError, RevisePlan
+
+        intent = RevisePlan(
+            plan_id=plan_id,
+            title=title,
+            topics=topics,
+            target_date=target_date,
+            energy_floor=energy_floor,
+            review_cadence_days=review_cadence_days,
+            notes=notes,
+            milestones=milestones,
+            status=status,
+        )
+        try:
+            detail = PlanApplication().apply(intent)
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return detail.to_json_dict()
+
+    @tool()
+    def set_study_plan_status(plan_id: str, status: str) -> dict[str, Any]:
+        """Move a study plan to another lifecycle status.
+
+        Activation is readiness-gated: ``status="active"`` on a plan that is
+        missing its mission, success criteria or milestones is refused with
+        ``not_ready: … : <blockers>`` and nothing is written — repair it with
+        ``update_study_plan`` first (or do both in one ``update_study_plan``
+        call). Pausing, completing or abandoning is never gated, so
+        ``paused`` is the way out of an active plan that has become unready.
+        Safe to retry: asking for the status a plan already has is not an
+        error.
+
+        Args:
+            plan_id: The plan id.
+            status: ``draft``, ``active``, ``paused``, ``complete`` or
+                ``abandoned``.
+
+        Refusals: ``not_found: …``, ``not_ready: … : <blockers>``,
+        ``invalid: …`` (unknown status), ``invalid_id: …``.
+        """
+        from studyloop.planning import PlanApplication, PlanError, TransitionLifecycle
+
+        try:
+            detail = PlanApplication().apply(TransitionLifecycle(plan_id=plan_id, status=status))
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return detail.to_json_dict()
+
     # ── Exercise sets — developer preview only ───────────────────────
     # Return after the complete production inventory has been registered.
     # This keeps exercise tools out of tools/list entirely unless the MCP
```

### `packages/studyloop/src/studyloop/mcp/tools.py` — the existing `get_next_action` tool (unchanged this phase; lines 706–743; the target of deliverable 6)

```python
    @tool()
    @consistent_read
    def get_next_action(
        energy: str = "medium",
        time_minutes: int = 25,
        modality: str = "recall",
    ) -> dict[str, Any]:
        """Get the recommended next study action ("what should I do now?").

        Delegates to the same decision engine the web ``/api/now`` endpoint
        uses, so agents and the browser get identical recommendations.

        Args:
            energy: "low", "medium", or "high".
            time_minutes: Minutes available for this study action.
            modality: "recall", "conversation", "hands-on", "visual", or "audio".
        """
        from typing import cast, get_args

        from studyloop.learning.decision import EnergyLevel, Modality, build_now_plan

        # MCP clients send plain strings; validate against the engine's
        # Literal types before forwarding so a typo ("LOW", "recal") fails
        # loudly here instead of flowing unvalidated into scoring.
        valid_energy = get_args(EnergyLevel)
        if energy not in valid_energy:
            raise ToolError(f"Invalid energy {energy!r}: choose one of {valid_energy}")
        valid_modality = get_args(Modality)
        if modality not in valid_modality:
            raise ToolError(f"Invalid modality {modality!r}: choose one of {valid_modality}")

        plan = build_now_plan(
            energy=cast("EnergyLevel", energy),
            time_minutes=time_minutes,
            modality=cast("Modality", modality),
        )
        return plan.to_json_dict()

```

### `packages/studyloop/tests/test_mcp_stdio_smoke.py` — the inventory assertion as it stands (lines 50–58)

```python
        # initialize + notifications/initialized handshake handled by SDK.
        init_result = await session.initialize()
        assert init_result.serverInfo.name == "studyloop"

        tools_result = await session.list_tools()
        names = {t.name for t in tools_result.tools}
        assert len(names) >= 21, f"expected >=21 tools, got {len(names)}: {names}"
        assert names >= CORE_TOOLS, f"missing core tools: {CORE_TOOLS - names}"

```

### `packages/studyloop/tests/test_mcp_plan_tools.py` (full source at `575e26ff`)

```python
"""The six study-plan MCP tools of design §4 (#11, T3.6/T3.7).

``list_study_plans``, ``get_study_plan``, ``get_planning_interview``,
``create_study_plan``, ``update_study_plan`` and ``set_study_plan_status`` are
thin adapters over :class:`studyloop.planning.PlanApplication`: each call is
one seam call with one intent, each success is the seam view's
``to_json_dict()`` (fresh containers, never a cached dict), and each refusal is
a ``ToolError`` whose message starts with a machine-readable prefix
(``not_found:``, ``invalid_id:``, ``conflict:``, ``invalid:``, ``not_ready:``,
``invalid_milestone:``) followed by the seam's own message — a not-ready
refusal names its blockers so the agent can tell the learner what to repair.

Two contracts the council fixed are pinned here rather than in prose: the
``create_study_plan`` schema exposes no ``overwrite`` (D-4 — an agent must not
be able to replace a learner's plan by picking the same id), and
``get_study_plan`` refuses a ``history_limit`` outside the range the Web
history route accepts *before* any read (review-1 hazard table, "Boundary
validation").

Delegation tests replace the seam's methods and forbid the store, so they
prove the adapter reaches nothing but ``PlanApplication``. The journey tests
at the end run the real seam on an isolated plans directory and database.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from studyloop.planning import (
    CreatePlan,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    Milestone,
    Mission,
    PlanApplication,
    PlanConflict,
    PlanDetail,
    PlanError,
    PlanningBrief,
    PlanNotFound,
    PlanNotReady,
    PlanSummary,
    ReadinessView,
    RevisePlan,
    StudyPlan,
    TransitionLifecycle,
    store,
)
from studyloop.planning import index as plan_index

SIX_TOOLS = (
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    """``store.create_plan`` refreshes the derived index in the sessions
    database; keep that off any developer database (council review 2, F10)."""
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def forbid_store(monkeypatch):
    """Make every store/index read or write an assertion failure.

    The delegation tests fake the seam's methods; with the store forbidden
    underneath, a tool that reached round the seam — or called a seam method
    the test did not fake — fails here instead of quietly touching files.
    """

    def _reached(name: str):
        def _fail(*args: Any, **kwargs: Any):
            msg = f"the adapter reached {name} instead of the seam"
            raise AssertionError(msg)

        return _fail

    for name in (
        "list_plans",
        "list_plan_ids",
        "load_plan",
        "load_plan_text",
        "create_plan",
        "save_plan",
        "delete_plan",
    ):
        monkeypatch.setattr(store, name, _reached(f"store.{name}"))
    monkeypatch.setattr(plan_index, "checkpoint_history", _reached("index.checkpoint_history"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry():
    from studyloop.mcp.server import mcp

    return mcp._tool_manager._tools


def _tool(name: str):
    tools = _registry()
    if name not in tools:
        msg = f"Tool {name!r} not registered. Available: {sorted(tools)}"
        raise KeyError(msg)
    return tools[name].fn


def _schema(name: str) -> dict[str, Any]:
    return _registry()[name].parameters


def _ready_plan(plan_id: str = "decorators", status: str = "draft") -> StudyPlan:
    return StudyPlan(
        plan_id=plan_id,
        title="Python Decorators",
        status=status,
        topics=["python"],
        mission=Mission(why="They keep appearing in code review.", success=["Explain them."]),
        milestones=[Milestone(title="Trace a decorated call", concepts=["wrapper"])],
    )


def _unready_plan(plan_id: str = "husk", status: str = "draft") -> StudyPlan:
    """No mission, no success criteria, no milestones — every blocker fires."""
    return StudyPlan(plan_id=plan_id, title="Husk", status=status)


def _brief() -> PlanningBrief:
    return PlanningBrief.build(
        interview=[
            {
                "key": "why",
                "prompt": "What changes once this is learned?",
                "why": "Mission first.",
                "required": True,
                "multi": False,
            }
        ],
        seed={"topics": ["python"], "struggles": [{"topic": "closures", "count": 2}]},
        existing_plans=[PlanSummary.from_plan(_ready_plan())],
    )


class _Spy:
    """Record every call to one faked seam method and hand back a canned view."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _fake(monkeypatch, method: str, result: object) -> _Spy:
    """Replace one ``PlanApplication`` method with a spy (bound like a method)."""
    spy = _Spy(result)

    def bound(_self: PlanApplication, *args: Any, **kwargs: Any) -> object:
        return spy(*args, **kwargs)

    monkeypatch.setattr(PlanApplication, method, bound)
    return spy


# ---------------------------------------------------------------------------
# Registration and schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIX_TOOLS)
def test_plan_tool_is_registered_with_a_schema(name: str) -> None:
    schema = _schema(name)
    assert schema["type"] == "object"
    assert "properties" in schema


def test_schemas_carry_the_design_signatures() -> None:
    """Design §4: the argument names, the required ones, and the defaults."""
    assert _schema("list_study_plans")["properties"].keys() == {"status"}
    assert "status" not in _schema("list_study_plans").get("required", [])

    get_props = _schema("get_study_plan")["properties"]
    assert get_props.keys() == {"plan_id", "include_markdown", "include_history", "history_limit"}
    assert _schema("get_study_plan")["required"] == ["plan_id"]
    assert get_props["include_markdown"]["default"] is False
    assert get_props["include_history"]["default"] is False
    assert get_props["history_limit"]["default"] == 20

    assert _schema("get_planning_interview")["properties"] == {}

    create = _schema("create_study_plan")
    assert set(create["properties"]) == {"title", "answers", "plan_id", "status"}
    assert set(create["required"]) == {"title", "answers"}
    assert create["properties"]["status"]["default"] == "draft"

    update = _schema("update_study_plan")
    assert set(update["properties"]) == {
        "plan_id",
        "title",
        "topics",
        "target_date",
        "energy_floor",
        "review_cadence_days",
        "notes",
        "milestones",
        "status",
    }
    assert update["required"] == ["plan_id"]

    status = _schema("set_study_plan_status")
    assert set(status["properties"]) == {"plan_id", "status"}
    assert set(status["required"]) == {"plan_id", "status"}


def test_create_study_plan_schema_exposes_no_overwrite() -> None:
    """D-4: ``overwrite`` stays on the intent for Web/CLI and never reaches an agent."""
    schema = _schema("create_study_plan")
    assert "overwrite" not in schema["properties"]
    assert "overwrite" not in (_registry()["create_study_plan"].description or "")


def test_no_learning_record_on_update_study_plan() -> None:
    """``record_plan_learning`` is the one record writer (D-9); the revision tool
    does not grow a second door to the same rule."""
    assert "learning_record" not in _schema("update_study_plan")["properties"]


# ---------------------------------------------------------------------------
# Delegation: one seam call, the view's JSON, nothing else
# ---------------------------------------------------------------------------


def test_list_study_plans_delegates_to_browse(monkeypatch, forbid_store) -> None:
    summaries = (PlanSummary.from_plan(_ready_plan()), PlanSummary.from_plan(_ready_plan("b")))
    browse = _fake(monkeypatch, "browse", summaries)

    payload = _tool("list_study_plans")()

    assert browse.calls == [((), {"status": None})]
    assert payload["plans"] == [summary.to_json_dict() for summary in summaries]
    assert payload["count"] == 2


def test_list_study_plans_passes_the_status_filter_through(monkeypatch, forbid_store) -> None:
    browse = _fake(monkeypatch, "browse", ())

    payload = _tool("list_study_plans")(status="active")

    assert browse.calls == [((), {"status": "active"})]
    assert payload == {"plans": [], "count": 0}


def test_get_study_plan_delegates_to_inspect_with_its_options(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan(), markdown="# doc", history=())
    inspect = _fake(monkeypatch, "inspect", detail)

    payload = _tool("get_study_plan")(
        "decorators", include_markdown=True, include_history=True, history_limit=5
    )

    assert inspect.calls == [
        (("decorators",), {"include_markdown": True, "include_history": True, "history_limit": 5})
    ]
    assert payload == detail.to_json_dict()
    assert payload["markdown"] == "# doc"
    assert payload["history"] == []


def test_get_study_plan_defaults_match_the_seam(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    inspect = _fake(monkeypatch, "inspect", detail)

    payload = _tool("get_study_plan")("decorators")

    defaults = {"include_markdown": False, "include_history": False, "history_limit": 20}
    assert inspect.calls == [(("decorators",), defaults)]
    assert "markdown" not in payload
    assert "history" not in payload
    assert payload["plan"]["plan_id"] == "decorators"


@pytest.mark.parametrize("limit", [0, -1, 201, 10_000], ids=["zero", "negative", "201", "huge"])
def test_get_study_plan_bounds_history_limit_before_any_read(
    monkeypatch, forbid_store, limit: int
) -> None:
    """Review-1 hazard, "Boundary validation": the Web history route accepts
    1..200; the tool refuses the rest itself, with no seam call and so no
    database query behind it."""
    inspect = _fake(monkeypatch, "inspect", PlanDetail.from_plan(_ready_plan()))

    with pytest.raises(ToolError, match=r"^invalid: history_limit") as caught:
        _tool("get_study_plan")("decorators", include_history=True, history_limit=limit)

    assert str(limit) in str(caught.value)
    assert inspect.calls == []


@pytest.mark.parametrize("limit", [1, 200])
def test_get_study_plan_accepts_the_history_limit_bounds(
    monkeypatch, forbid_store, limit: int
) -> None:
    inspect = _fake(monkeypatch, "inspect", PlanDetail.from_plan(_ready_plan(), history=()))

    _tool("get_study_plan")("decorators", include_history=True, history_limit=limit)

    assert inspect.calls[0][1]["history_limit"] == limit


def test_get_planning_interview_delegates_to_prepare_planning(monkeypatch, forbid_store) -> None:
    brief = _brief()
    prepare = _fake(monkeypatch, "prepare_planning", brief)

    payload = _tool("get_planning_interview")()

    assert prepare.calls == [((), {})]
    assert payload == brief.to_json_dict()
    assert set(payload) == {"questions", "seed", "existing_plans"}
    assert payload["questions"][0]["key"] == "why"
    assert payload["existing_plans"][0]["plan_id"] == "decorators"


def test_create_study_plan_applies_one_create_plan_without_overwrite(
    monkeypatch, forbid_store
) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    apply = _fake(monkeypatch, "apply", detail)
    answers = {"why": "Code review.", "success": ["Explain them."], "topics": ["python"]}

    payload = _tool("create_study_plan")(
        "Python Decorators", answers, plan_id="decorators", status="draft"
    )

    ((intent,), _kwargs) = apply.calls[0]
    assert len(apply.calls) == 1
    assert isinstance(intent, CreatePlan)
    assert intent.title == "Python Decorators"
    assert intent.answers == answers
    assert intent.plan_id == "decorators"
    assert intent.status == "draft"
    assert intent.overwrite is False, "D-4: the MCP door can never overwrite"
    assert payload == detail.to_json_dict()


def test_create_study_plan_defaults_leave_id_and_status_to_the_seam(
    monkeypatch, forbid_store
) -> None:
    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))

    _tool("create_study_plan")("Python Decorators", {"why": "Code review."})

    ((intent,), _kwargs) = apply.calls[0]
    assert isinstance(intent, CreatePlan)
    assert intent.plan_id is None, "the seam allocates the unique slug"
    assert intent.status == "draft"
    assert intent.overwrite is False


def test_update_study_plan_applies_one_revise_plan_with_explicit_fields(
    monkeypatch, forbid_store
) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    apply = _fake(monkeypatch, "apply", detail)
    milestones = [{"title": "Write one", "concepts": ["closure"], "done": False}]

    payload = _tool("update_study_plan")(
        "decorators",
        title="Decorators, properly",
        topics=["python", "closures"],
        target_date="2026-10-01",
        energy_floor=4,
        review_cadence_days=5,
        notes="Weekly.",
        milestones=milestones,
        status="active",
    )

    ((intent,), _kwargs) = apply.calls[0]
    assert len(apply.calls) == 1
    assert isinstance(intent, RevisePlan)
    assert intent.plan_id == "decorators"
    assert intent.title == "Decorators, properly"
    assert intent.topics == ["python", "closures"]
    assert intent.target_date == "2026-10-01"
    assert intent.energy_floor == 4
    assert intent.review_cadence_days == 5
    assert intent.notes == "Weekly."
    assert intent.milestones == milestones
    assert intent.status == "active"
    assert intent.learning_record is None
    assert payload == detail.to_json_dict()


def test_update_study_plan_omitted_fields_are_none_not_blank(monkeypatch, forbid_store) -> None:
    """``None`` is "leave as is" for the seam; a field the agent did not send
    must arrive as ``None``, never as ``""`` or ``[]`` that would wipe it."""
    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))

    _tool("update_study_plan")("decorators", notes="Only this.")

    ((intent,), _kwargs) = apply.calls[0]
    assert isinstance(intent, RevisePlan)
    assert intent.notes == "Only this."
    for field in (
        "title",
        "topics",
        "target_date",
        "energy_floor",
        "review_cadence_days",
        "milestones",
        "status",
        "learning_record",
    ):
        assert getattr(intent, field) is None, field


def test_set_study_plan_status_applies_one_transition(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan(status="active"))
    apply = _fake(monkeypatch, "apply", detail)

    payload = _tool("set_study_plan_status")("decorators", "active")

    assert apply.calls == [((TransitionLifecycle(plan_id="decorators", status="active"),), {})]
    assert payload == detail.to_json_dict()
    assert payload["plan"]["status"] == "active"


def test_set_study_plan_status_retry_is_idempotent(monkeypatch, forbid_store) -> None:
    """A retried transition is the same intent again, returns the same view,
    and raises nothing — the adapter holds no state a replay could trip on."""
    detail = PlanDetail.from_plan(_ready_plan(status="paused"))
    apply = _fake(monkeypatch, "apply", detail)

    first = _tool("set_study_plan_status")("decorators", "paused")
    second = _tool("set_study_plan_status")("decorators", "paused")

    assert first == second == detail.to_json_dict()
    assert first is not second, "fresh containers on every call"
    assert apply.calls == [
        ((TransitionLifecycle(plan_id="decorators", status="paused"),), {}),
        ((TransitionLifecycle(plan_id="decorators", status="paused"),), {}),
    ]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("list_study_plans", ()),
        ("get_study_plan", ("decorators",)),
        ("get_planning_interview", ()),
        ("create_study_plan", ("Python Decorators", {"why": "Code review."})),
        ("update_study_plan", ("decorators",)),
        ("set_study_plan_status", ("decorators", "paused")),
    ],
)
def test_responses_are_fresh_containers(monkeypatch, forbid_store, name: str, args) -> None:
    """Mutating one response must not change the next: the adapter returns the
    view's ``to_json_dict()`` each time, never a shared or cached dict."""
    detail = PlanDetail.from_plan(_ready_plan())
    _fake(monkeypatch, "browse", (PlanSummary.from_plan(_ready_plan()),))
    _fake(monkeypatch, "inspect", detail)
    _fake(monkeypatch, "prepare_planning", _brief())
    _fake(monkeypatch, "apply", detail)

    first = _tool(name)(*args)
    pristine = _tool(name)(*args)
    first.clear()
    first["tampered"] = True

    second = _tool(name)(*args)
    assert second == pristine
    assert second is not first


# ---------------------------------------------------------------------------
# Error mapping: every seam refusal is one prefixed ToolError
# ---------------------------------------------------------------------------


def _not_ready(already_active: bool = False) -> PlanNotReady:
    return PlanNotReady(ReadinessView.from_plan(_unready_plan()), already_active=already_active)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("create_study_plan", ("Husk", {}, "husk", "active")),
        ("update_study_plan", ("husk",)),
        ("set_study_plan_status", ("husk", "active")),
    ],
)
def test_not_ready_refusal_is_a_tool_error_naming_the_blockers(
    monkeypatch, forbid_store, name: str, args
) -> None:
    error = _not_ready()
    assert error.readiness.blockers, "the fixture must have something to name"
    _fake(monkeypatch, "apply", error)

    with pytest.raises(ToolError) as caught:
        _tool(name)(*args)

    message = str(caught.value)
    assert message.startswith("not_ready: plan is not ready to activate")
    for blocker in error.readiness.blockers:
        assert blocker in message


def test_not_ready_on_an_already_active_plan_says_pause_or_repair(
    monkeypatch, forbid_store
) -> None:
    _fake(monkeypatch, "apply", _not_ready(already_active=True))

    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause") as caught:
        _tool("update_study_plan")("husk", notes="x")

    assert "activate" in str(caught.value)


def test_duplicate_create_is_a_conflict_tool_error(monkeypatch, forbid_store) -> None:
    _fake(monkeypatch, "apply", PlanConflict("study plan 'decorators' already exists"))

    with pytest.raises(ToolError, match=r"^conflict: study plan 'decorators' already exists$"):
        _tool("create_study_plan")("Python Decorators", {}, plan_id="decorators")


@pytest.mark.parametrize(
    ("error", "prefix"),
    [
        (PlanNotFound("no study plan with id 'ghost'"), "not_found"),
        (InvalidPlanId("invalid plan id '../x'"), "invalid_id"),
        (PlanConflict("study plan 'x' already exists"), "conflict"),
        (InvalidField("status must be one of (...)"), "invalid"),
        (InvalidMilestone("No milestone at index 9 (plan has 1)"), "invalid_milestone"),
        (PlanError("something the mapping has not met"), "plan_error"),
    ],
    ids=["not_found", "invalid_id", "conflict", "invalid", "invalid_milestone", "fallback"],
)
@pytest.mark.parametrize("method", ["inspect", "apply"])
def test_every_seam_refusal_maps_to_one_prefixed_tool_error(
    monkeypatch, forbid_store, error: PlanError, prefix: str, method: str
) -> None:
    _fake(monkeypatch, method, error)
    call = (
        (lambda: _tool("get_study_plan")("ghost"))
        if method == "inspect"
        else (lambda: _tool("set_study_plan_status")("ghost", "paused"))
    )

    with pytest.raises(ToolError) as caught:
        call()

    assert str(caught.value) == f"{prefix}: {error}"
    assert caught.value.__cause__ is error


def test_browse_and_prepare_refusals_are_mapped_too(monkeypatch, forbid_store) -> None:
    _fake(monkeypatch, "browse", InvalidField("status must be one of (...)"))
    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("list_study_plans")(status="bogus")

    _fake(monkeypatch, "prepare_planning", PlanError("seed unavailable"))
    with pytest.raises(ToolError, match=r"^plan_error: seed unavailable$"):
        _tool("get_planning_interview")()


# ---------------------------------------------------------------------------
# The real seam, on an isolated directory: the spec's journey and its refusals
# ---------------------------------------------------------------------------


def test_discover_inspect_create_revise_activate_journey() -> None:
    """mcp-server delta, "Study-plan discovery and authoring tools", scenario 1."""
    interview = _tool("get_planning_interview")()
    assert {q["key"] for q in interview["questions"]} >= {"why", "success", "milestones"}
    assert interview["existing_plans"] == []
    assert _tool("list_study_plans")() == {"plans": [], "count": 0}

    created = _tool("create_study_plan")(
        "Python Decorators",
        {
            "why": "They keep appearing in code review.",
            "success": ["Explain the wrapper relationship."],
            "topics": ["python"],
        },
    )
    plan_id = created["plan"]["plan_id"]
    assert plan_id == "python-decorators"
    assert created["plan"]["status"] == "draft"
    assert created["readiness"]["ready"] is False, "no milestones yet"

    listed = _tool("list_study_plans")()
    assert [plan["plan_id"] for plan in listed["plans"]] == [plan_id]
    assert listed["count"] == 1

    revised = _tool("update_study_plan")(
        plan_id,
        topics=["python", "closures"],
        milestones=[{"title": "Trace a decorated call", "concepts": ["wrapper", "closure"]}],
    )
    assert revised["plan"]["topics"] == ["python", "closures"]
    assert revised["milestones"][0]["concepts"] == ["wrapper", "closure"]
    assert revised["readiness"]["ready"] is True

    activated = _tool("set_study_plan_status")(plan_id, "active")
    assert activated["plan"]["status"] == "active"

    shown = _tool("get_study_plan")(plan_id, include_markdown=True)
    assert shown["plan"]["status"] == "active"
    assert shown["markdown"].startswith("---")
    assert store.load_plan(plan_id).status == "active", "the document is the source of truth"
    assert _tool("list_study_plans")(status="active")["count"] == 1
    assert _tool("list_study_plans")(status="draft")["count"] == 0


def test_refused_activation_of_a_real_document_carries_blockers_and_writes_nothing() -> None:
    """Scenario 2: the refusal names the blockers; the document is byte-identical after."""
    created = _tool("create_study_plan")("Husk", {}, plan_id="husk")
    assert created["readiness"]["ready"] is False
    before = store.load_plan_text("husk")

    with pytest.raises(ToolError) as caught:
        _tool("set_study_plan_status")("husk", "active")

    message = str(caught.value)
    assert message.startswith("not_ready: plan is not ready to activate: ")
    for blocker in created["readiness"]["blockers"]:
        assert blocker in message
    assert store.load_plan_text("husk") == before
    assert store.load_plan("husk").status == "draft"


def test_create_with_active_status_is_gated_the_same_way() -> None:
    with pytest.raises(ToolError, match=r"^not_ready: "):
        _tool("create_study_plan")("Husk", {}, plan_id="husk", status="active")
    assert not store.plan_path("husk").exists(), "a refusal writes nothing"


def test_duplicate_create_through_the_real_seam_preserves_the_existing_plan() -> None:
    """Scenario 3: no overwrite — a second create on the same id is a conflict
    and the learner's document is untouched."""
    _tool("create_study_plan")("Python Decorators", {"why": "Original."}, plan_id="decorators")
    before = store.load_plan_text("decorators")

    with pytest.raises(ToolError, match=r"^conflict: "):
        _tool("create_study_plan")("Replacement", {"why": "Clobber."}, plan_id="decorators")

    assert store.load_plan_text("decorators") == before
    assert store.load_plan("decorators").mission.why == "Original."


def test_set_study_plan_status_retry_on_the_real_seam_is_not_refused() -> None:
    _tool("create_study_plan")("Python Decorators", {"why": "Code review."}, plan_id="decorators")

    first = _tool("set_study_plan_status")("decorators", "paused")
    second = _tool("set_study_plan_status")("decorators", "paused")

    assert first["plan"]["status"] == second["plan"]["status"] == "paused"
    assert store.load_plan("decorators").status == "paused"


def test_missing_plan_and_malformed_id_are_prefixed_tool_errors() -> None:
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("get_study_plan")("ghost")
    with pytest.raises(ToolError, match=r"^invalid_id: "):
        _tool("get_study_plan")("../escape")
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("set_study_plan_status")("ghost", "paused")


def test_unknown_status_is_the_seams_refusal_not_the_adapters() -> None:
    """The adapter carries no status list of its own (no policy in the adapter):
    the seam's ``InvalidField`` message, prefixed, is what the agent reads."""
    _tool("create_study_plan")("Python Decorators", {"why": "Code review."}, plan_id="decorators")

    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("set_study_plan_status")("decorators", "archived")
    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("list_study_plans")(status="archived")
    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("create_study_plan")("Other", {}, plan_id="other", status="archived")
    assert not store.plan_path("other").exists()


def test_get_study_plan_history_reads_the_isolated_log() -> None:
    _tool("create_study_plan")("Python Decorators", {"why": "Code review."}, plan_id="decorators")

    payload = _tool("get_study_plan")("decorators", include_history=True, history_limit=3)

    assert payload["history"] == []
    assert "markdown" not in payload
```

## 5. #13a — session `purpose`, one persona resolver, planning brief

### `packages/studyloop/src/studyloop/web/routes/session/_models.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/web/routes/session/_models.py b/packages/studyloop/src/studyloop/web/routes/session/_models.py
index b0c942e4..07a7024e 100644
--- a/packages/studyloop/src/studyloop/web/routes/session/_models.py
+++ b/packages/studyloop/src/studyloop/web/routes/session/_models.py
@@ -24,6 +24,18 @@ class StartSessionRequest(BaseModel):
             "focused on the safe path."
         ),
     )
+    purpose: Literal["focus", "planning"] = Field(
+        default="focus",
+        description=(
+            "What the session is for: 'focus' (default) is today's study "
+            "session; 'planning' launches the study-plan architect with a "
+            "planning brief as its own persona section. For 'planning' a blank "
+            "topic resolves to the fixed label 'Study plan'. Only the purpose is "
+            "persisted on the session state; no plan is created and no plan id "
+            "is stored (design §5, D-10/D-11). Any other value is rejected with "
+            "422."
+        ),
+    )


 _AGENT_INSTALL_HINTS: dict[str, str] = {
```

### `packages/studyloop/src/studyloop/agent_launcher.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/agent_launcher.py b/packages/studyloop/src/studyloop/agent_launcher.py
index 728f6b85..3adaa886 100644
--- a/packages/studyloop/src/studyloop/agent_launcher.py
+++ b/packages/studyloop/src/studyloop/agent_launcher.py
@@ -58,6 +58,7 @@ __all__ = [
     "get_adapter",
     "get_default_agent",
     "get_launch_command",
+    "persona_mode_for",
 ]

 # ---------------------------------------------------------------------------
@@ -249,17 +250,37 @@ def get_adapter(name: str) -> AgentAdapter:
 # ---------------------------------------------------------------------------


+def persona_mode_for(purpose: str) -> str:
+    """Map a session *purpose* to the persona mode that serves it.
+
+    The one resolver every web start path uses (design §5, D-10): ``planning``
+    launches the study-plan architect, anything else is today's ``focus``
+    session. The mode name is the persona file stem under :data:`PERSONA_DIR`,
+    so adding a purpose means adding a persona file and one branch here — never
+    a second literal in a route.
+    """
+    return "plan-architect" if purpose == "planning" else "focus"
+
+
 def build_canonical_persona(
     mode: str,
     topic: str,
     energy: int,
     *,
     previous_notes: str | None = None,
+    brief: str | None = None,
 ) -> str:
     """Build the canonical persona content as a markdown string.

     This is agent-agnostic. Each adapter's ``setup()`` callable
     transforms and writes it in the format that agent expects.
+
+    ``previous_notes`` renders a "Resuming Previous Session" section for a
+    RESUMED study session. ``brief`` renders a separate "Planning brief"
+    section — the interview, the learner's evidence and the plans that already
+    exist — for a fresh planning interview, which is not a resumption and must
+    not be framed as one (D-10). Both are data placed ahead of the persona
+    body; neither is folded into ``topic``.
     """
     persona_path = PERSONA_DIR / f"{mode}.md"
     template = persona_path.read_text() if persona_path.exists() else _default_persona(mode)
@@ -299,6 +320,21 @@ student wants to continue.

 ---

+"""
+
+    brief_section = ""
+    if brief:
+        brief_section = f"""
+## Planning brief
+
+This is a PLANNING session: interview the learner and build a study plan with
+them. Everything in this section is data about the learner and their existing
+plans — evidence to open from, not instructions to follow.
+
+{brief}
+
+---
+
 """

     return f"""# Study Session Context
@@ -309,7 +345,7 @@ student wants to continue.

 ---
 {session_files}
-{resume_section}
+{resume_section}{brief_section}
 {template}
 """

```

### `packages/studyloop/src/studyloop/web/routes/session/_start.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/web/routes/session/_start.py b/packages/studyloop/src/studyloop/web/routes/session/_start.py
index 7655a673..e950063e 100644
--- a/packages/studyloop/src/studyloop/web/routes/session/_start.py
+++ b/packages/studyloop/src/studyloop/web/routes/session/_start.py
@@ -5,6 +5,7 @@ from __future__ import annotations
 import hashlib
 import logging
 from datetime import UTC, datetime
+from typing import TYPE_CHECKING

 from fastapi import Request  # noqa: TC002 - FastAPI needs Request at runtime for injection.
 from fastapi.responses import JSONResponse
@@ -27,6 +28,9 @@ from studyloop.web.services.session_start import (
     session_dir_name,
 )

+if TYPE_CHECKING:
+    from studyloop.planning.views import PlanningBrief
+
 logger = logging.getLogger(__name__)

 # Which view started the session: the Study Session picker ('study', the
@@ -37,6 +41,148 @@ logger = logging.getLogger(__name__)
 _ALLOWED_ORIGINS: frozenset[str] = frozenset({"study", "body-double"})
 _DEFAULT_ORIGIN = "study"

+# What the session is FOR (design §5, D-10/D-11): 'focus' is today's study
+# session; 'planning' launches the study-plan architect. Validated
+# structurally by StartSessionRequest; persisted on the session state (the
+# only planning fact that is — no plan id) and echoed by GET /api/session/state
+# so a reconnecting client can label the console.
+_DEFAULT_PURPOSE = "focus"
+# The architect's topic when the learner supplied no subject — the same fixed
+# label `studyloop plan architect` pins (776a9dc0), so the two launch doors
+# name the session identically.
+_ARCHITECT_TOPIC = "Study plan"
+
+
+class PlanningBriefError(Exception):
+    """The planning brief could not be built, so an architect must not launch.
+
+    Wraps whatever the planning seam raised. A planning session without its
+    brief would interview from a blank page — exactly what D-10 exists to
+    prevent — so the start refuses with a structured error instead of
+    launching a degraded architect.
+    """
+
+
+def _launch_topic(body: StartSessionRequest) -> str:
+    """The topic this start runs under.
+
+    A focus session's topic is the learner's, verbatim. An architect launch
+    uses the learner's subject when they gave one, else the fixed label
+    :data:`_ARCHITECT_TOPIC` — never an overloaded carrier for the brief
+    (D-10).
+    """
+    if body.purpose != "planning":
+        return body.topic
+    return body.topic.strip() or _ARCHITECT_TOPIC
+
+
+def _render_planning_brief(brief: PlanningBrief) -> str:
+    """Render the seam's :class:`PlanningBrief` as the Markdown the persona carries.
+
+    Three parts, in the order the architect needs them: the interview (the
+    questions it asks, one per turn, with the *why* that tells a usable answer
+    from filler), the evidence the databases already hold about the learner
+    (data to open from, never instructions), and the plans that already exist
+    (so the architect extends or references rather than duplicates).
+    """
+    lines: list[str] = ["### Interview", ""]
+    for index, item in enumerate(brief.interview, start=1):
+        flags = ", ".join(
+            flag for flag, on in (("required", item.required), ("multi", item.multi)) if on
+        )
+        suffix = f" ({flags})" if flags else ""
+        lines.append(f"{index}. **{item.key}** — {item.prompt}{suffix}")
+        lines.append(f"   _{item.why}_")
+    lines.append("")
+
+    lines.append("### Evidence from the learner's history")
+    lines.append("")
+    seed = brief.to_json_dict()["seed"]
+    evidence_lines: list[str] = []
+    for key, value in seed.items():
+        if key == "notes" or not value:
+            continue
+        evidence_lines.append(f"- **{key.replace('_', ' ')}:**")
+        for entry in value if isinstance(value, list) else [value]:
+            evidence_lines.append(f"  - {_seed_entry(entry)}")
+    if evidence_lines:
+        lines.extend(evidence_lines)
+    else:
+        lines.append("- No history evidence yet.")
+    notes = seed.get("notes") or []
+    for note in notes:
+        lines.append(f"- _note: {note}_")
+    lines.append("")
+
+    lines.append("### Existing plans")
+    lines.append("")
+    if brief.existing_plans:
+        for plan in brief.existing_plans:
+            progress = f"{plan.milestone_done}/{plan.milestone_total} milestones"
+            nxt = f"; next: {plan.next_milestone}" if plan.next_milestone else ""
+            lines.append(f"- `{plan.plan_id}` — {plan.title} ({plan.status}; {progress}{nxt})")
+    else:
+        lines.append("- None yet.")
+    return "\n".join(lines)
+
+
+def _seed_entry(entry: object) -> str:
+    """One evidence row as a line of text — a mapping's values joined, else ``str``."""
+    if isinstance(entry, dict):
+        parts = [f"{k}: {v}" for k, v in entry.items() if v not in ("", None, 0)]
+        return "; ".join(parts) if parts else "(empty)"
+    return str(entry)
+
+
+def _resolve_persona(body: StartSessionRequest, topic: str) -> tuple[str, str]:
+    """The canonical persona and its 16-char hash for this start.
+
+    The ONE place both transports resolve the mode (design §5): the purpose
+    goes through :func:`studyloop.agent_launcher.persona_mode_for`, and a
+    planning start carries the seam's brief as the persona's own "Planning
+    brief" section — not ``previous_notes`` (D-10). Raises
+    :class:`PlanningBriefError` when the brief cannot be built.
+    """
+    from studyloop.agent_launcher import build_canonical_persona, persona_mode_for
+
+    mode = persona_mode_for(body.purpose)
+    brief: str | None = None
+    if body.purpose == "planning":
+        # Routes may import the seam's application and views (D-6), and
+        # nothing else from studyloop.planning.
+        from studyloop.planning.application import PlanApplication
+
+        try:
+            brief = _render_planning_brief(PlanApplication().prepare_planning())
+        except Exception as exc:
+            raise PlanningBriefError(str(exc)) from exc
+    canonical = build_canonical_persona(mode, topic, body.energy, brief=brief)
+    return canonical, hashlib.sha256(canonical.encode()).hexdigest()[:16]
+
+
+def _brief_unavailable_response(body: StartSessionRequest) -> JSONResponse:
+    """The 500 shared by both start paths when the planning brief cannot be built.
+
+    Structured (an ``error`` the UI can show, the ``purpose`` it belongs to, a
+    ``repair``) rather than a bare server error, and returned from inside the
+    claim's ``try`` so the ``finally`` frees the reserved slot: a refused
+    planning start must leave the next start unblocked.
+    """
+    return JSONResponse(
+        {
+            "error": (
+                "Failed to build the planning brief — the study-plan architect "
+                "cannot start without it."
+            ),
+            "purpose": body.purpose,
+            "repair": (
+                "Check that the plans directory is readable (`studyloop plan list`) "
+                "and try again, or start a focus session instead."
+            ),
+        },
+        status_code=500,
+    )
+

 def _active_session_topic(session_id: str) -> str | None:
     """The active session's topic from the IPC file, or None.
@@ -245,10 +391,14 @@ async def _start_pty_session(
        cross-process file claim, or atomically RESERVE the slot
        (``_session_conflict()``, R-01/C1).
     2. Resolve agent + check binary. 503 with ``install_hint`` on miss.
-    3. Persona + DB record creation (shared with legacy).
-    4. ``await active.acquire(config, factory)`` — atomic under asyncio.Lock.
-    5. Write IPC session_state only after the transport starts, then return
-       201 with ``ws_url`` for the client to open.
+    3. Resolve the persona through the one resolver (``_resolve_persona``:
+       ``persona_mode_for(body.purpose)``, plus the planning brief for
+       ``purpose=planning``). 500 with a structured error if the brief cannot
+       be built -- before any DB record exists (design §5).
+    4. DB record creation, session dir, persona file (shared with legacy).
+    5. ``await active.acquire(config, factory)`` — atomic under asyncio.Lock.
+    6. Write IPC session_state (with ``purpose``) only after the transport
+       starts, then return 201 with ``ws_url`` for the client to open.

     C1 (council): everything from step 2 onward runs with the slot already
     reserved (step 1's ``_session_conflict`` call claims it, not just
@@ -264,12 +414,13 @@ async def _start_pty_session(
     from studyloop.session import active as session_active
     from studyloop.session.transport import SessionAlreadyActiveError, SessionConfig

+    topic = _launch_topic(body)
     reservation = {
         "study_session_id": f"pending-{uuid.uuid4().hex[:12]}",
         "mode": "starting",
         "transport": "pty",
         "pid": os.getpid(),
-        "topic": body.topic,
+        "topic": topic,
         "started_at": datetime.now(UTC).isoformat(),
     }
     conflict = await _session_conflict(reservation)
@@ -311,6 +462,15 @@ async def _start_pty_session(
                 status_code=503,
             )

+        # --- Persona (one resolver for PTY and ACP; brief for planning) ---
+        # Built before the DB record so a planning start whose brief cannot be
+        # produced refuses with nothing to roll back but the reservation.
+        try:
+            canonical, persona_hash = _resolve_persona(body, topic)
+        except PlanningBriefError:
+            logger.exception("PTY start failed: planning brief unavailable")
+            return _brief_unavailable_response(body)
+
         # --- Topic resolution (optional) ---
         topic_config = None
         try:
@@ -319,7 +479,7 @@ async def _start_pty_session(

             settings = load_settings()
             if settings.topics:
-                result = resolve_topic(body.topic, settings.topics)
+                result = resolve_topic(topic, settings.topics)
                 topic_config = result.resolved or (result.matches[0] if result.matches else None)
         except Exception:
             pass
@@ -330,7 +490,7 @@ async def _start_pty_session(

         energy_label = energy_to_label(body.energy)
         study_id = start_study_session(
-            body.topic,
+            topic,
             energy_label,
             topic_slug=topic_config.slug if topic_config else None,
         )
@@ -340,15 +500,12 @@ async def _start_pty_session(
                 status_code=500,
             )

-        # --- Session dir + persona (no tmux) ---
-        session_dir = SESSION_DIR / "sessions" / session_dir_name(body.topic, study_id)
+        # --- Session dir + persona file (no tmux) ---
+        session_dir = SESSION_DIR / "sessions" / session_dir_name(topic, study_id)

-        from studyloop.agent_launcher import build_canonical_persona
         from studyloop.session.orchestrator import setup_session_dir

-        setup_session_dir(session_dir, body.topic)
-        canonical = build_canonical_persona("focus", body.topic, body.energy)
-        persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
+        setup_session_dir(session_dir, topic)

         from studyloop.history.sessions import update_persona_hash

@@ -406,7 +563,7 @@ async def _start_pty_session(
             _ensure_session_dir()
             pty_state = build_session_state_payload(
                 study_id=study_id,
-                topic=body.topic,
+                topic=topic,
                 energy=body.energy,
                 energy_label=energy_label,
                 agent=agent,
@@ -427,6 +584,11 @@ async def _start_pty_session(
             # build_session_state_payload (owned by another stage) so it flows
             # through write_session_state → read_session_state → /api/session/state.
             pty_state["origin"] = origin
+            # purpose is the only planning fact the session state carries
+            # (D-11): enough for the reconnect label, never a plan id. Always
+            # written, so a stale value can never be inherited through the
+            # read-merge-write.
+            pty_state["purpose"] = body.purpose
             write_session_state(pty_state)
             TOPICS_FILE.touch(mode=0o600, exist_ok=True)
             PARKING_FILE.touch(mode=0o600, exist_ok=True)
@@ -450,10 +612,11 @@ async def _start_pty_session(
     return JSONResponse(
         {
             "study_session_id": study_id,
-            "topic": body.topic,
+            "topic": topic,
             "energy": body.energy,
             "agent": agent,
             "transport": "pty",
+            "purpose": body.purpose,
             "ws_url": f"/api/session/ws?study_session_id={study_id}",
         },
         status_code=201,
@@ -467,18 +630,21 @@ async def _start_acp_session(

     Mirrors ``_start_pty_session`` but drops tmux and PTY-specific
     adapter steps. Persona and MCP files are NOT written here — ACP
-    agents receive context via ``session/prompt``, not argv; a future
-    refinement may inject the persona as the first prompt, but for
-    §2.2 we let the frontend send it.
+    agents receive context via ``session/prompt``, not argv; the persona
+    is returned inline (``persona_text``) for the frontend to send as the
+    first prompt.

     1. Reject if a session is already active -- in-process singleton OR a live
        cross-process file claim, or atomically RESERVE the slot
        (``_session_conflict()``, R-01/C1).
     2. Resolve agent + check binary. 503 with ``install_hint`` on miss.
-    3. DB record creation (no tmux metadata, no persona file).
-    4. ``await active.acquire(config, factory)`` — atomic under asyncio.Lock.
-    5. Write IPC session_state only after the transport starts, then return
-       201 with ``ws_url`` for the client to open.
+    3. Resolve the persona through the SAME resolver the PTY path uses
+       (``_resolve_persona``); 500 with a structured error if the planning
+       brief cannot be built (design §5).
+    4. DB record creation (no tmux metadata, no persona file).
+    5. ``await active.acquire(config, factory)`` — atomic under asyncio.Lock.
+    6. Write IPC session_state (with ``purpose``) only after the transport
+       starts, then return 201 with ``ws_url`` for the client to open.

     C1 (council): see ``_start_pty_session``'s identical structure and
     docstring note -- ``claim_finalized`` tracks whether the reservation
@@ -493,12 +659,13 @@ async def _start_acp_session(
     from studyloop.session import active as session_active
     from studyloop.session.transport import SessionAlreadyActiveError, SessionConfig

+    topic = _launch_topic(body)
     reservation = {
         "study_session_id": f"pending-{uuid.uuid4().hex[:12]}",
         "mode": "starting",
         "transport": "acp",
         "pid": os.getpid(),
-        "topic": body.topic,
+        "topic": topic,
         "started_at": datetime.now(UTC).isoformat(),
     }
     conflict = await _session_conflict(reservation)
@@ -564,6 +731,18 @@ async def _start_acp_session(
                 status_code=503,
             )

+        # --- Persona (one resolver for PTY and ACP; brief for planning) ---
+        # Built here and returned inline in the response so the browser can
+        # ship it as the first invisible session/prompt on WS open. No persona
+        # file is written to disk: ACP agents receive context via
+        # session/prompt, not via argv/env, so a file would just be dead
+        # weight. Before the DB record for the same reason as the PTY path.
+        try:
+            persona_text, persona_hash = _resolve_persona(body, topic)
+        except PlanningBriefError:
+            logger.exception("ACP start failed: planning brief unavailable")
+            return _brief_unavailable_response(body)
+
         # --- Topic resolution (optional, same as PTY) ---
         topic_config = None
         try:
@@ -572,7 +751,7 @@ async def _start_acp_session(

             settings = load_settings()
             if settings.topics:
-                result = resolve_topic(body.topic, settings.topics)
+                result = resolve_topic(topic, settings.topics)
                 topic_config = result.resolved or (result.matches[0] if result.matches else None)
         except Exception:
             pass
@@ -583,7 +762,7 @@ async def _start_acp_session(

         energy_label = energy_to_label(body.energy)
         study_id = start_study_session(
-            body.topic,
+            topic,
             energy_label,
             topic_slug=topic_config.slug if topic_config else None,
         )
@@ -594,21 +773,11 @@ async def _start_acp_session(
             )

         # --- Session dir (for cwd — no persona/MCP file written) ---
-        session_dir = (
-            SESSION_DIR / "sessions" / session_dir_name(body.topic, study_id, prefix="acp")
-        )
+        session_dir = SESSION_DIR / "sessions" / session_dir_name(topic, study_id, prefix="acp")

-        from studyloop.agent_launcher import build_canonical_persona
         from studyloop.session.orchestrator import setup_session_dir

-        setup_session_dir(session_dir, body.topic)
-
-        # Persona is built here and returned inline in the response so the
-        # browser can ship it as the first invisible session/prompt on WS open.
-        # No persona file is written to disk: ACP agents receive context via
-        # session/prompt, not via argv/env, so a file would just be dead weight.
-        persona_text = build_canonical_persona("focus", body.topic, body.energy)
-        persona_hash = hashlib.sha256(persona_text.encode()).hexdigest()[:16]
+        setup_session_dir(session_dir, topic)

         from studyloop.history.sessions import update_persona_hash

@@ -662,7 +831,7 @@ async def _start_acp_session(
             _ensure_session_dir()
             acp_state = build_session_state_payload(
                 study_id=study_id,
-                topic=body.topic,
+                topic=topic,
                 energy=body.energy,
                 energy_label=energy_label,
                 agent=agent,
@@ -673,8 +842,10 @@ async def _start_acp_session(
                 # C4 (council): see the PTY path's identical comment.
                 child_pid=getattr(active_session.transport, "pid", None),
             )
-            # See PTY path: origin merged here, not in build_session_state_payload.
+            # See PTY path: origin and purpose merged here, not in
+            # build_session_state_payload.
             acp_state["origin"] = origin
+            acp_state["purpose"] = body.purpose
             write_session_state(acp_state)
             TOPICS_FILE.touch(mode=0o600, exist_ok=True)
             PARKING_FILE.touch(mode=0o600, exist_ok=True)
@@ -699,10 +870,11 @@ async def _start_acp_session(
     return JSONResponse(
         {
             "study_session_id": study_id,
-            "topic": body.topic,
+            "topic": topic,
             "energy": body.energy,
             "agent": agent,
             "transport": "acp",
+            "purpose": body.purpose,
             "ws_url": f"/api/session/ws?study_session_id={study_id}",
             # persona_text is shipped inline so the browser can send it as
             # the first invisible session/prompt frame after WS open. ACP
```

### `packages/studyloop/src/studyloop/web/routes/session/_dashboard.py` — diff vs `0a20a796`

```diff
diff --git a/packages/studyloop/src/studyloop/web/routes/session/_dashboard.py b/packages/studyloop/src/studyloop/web/routes/session/_dashboard.py
index fdcb3b33..b1ff5385 100644
--- a/packages/studyloop/src/studyloop/web/routes/session/_dashboard.py
+++ b/packages/studyloop/src/studyloop/web/routes/session/_dashboard.py
@@ -39,7 +39,7 @@ async def get_session_state() -> dict:
     """
     from studyloop.session import active as session_active
     from studyloop.web.routes.session import _grace
-    from studyloop.web.routes.session._start import _DEFAULT_ORIGIN
+    from studyloop.web.routes.session._start import _DEFAULT_ORIGIN, _DEFAULT_PURPOSE

     state = _get_full_state()
     current = await session_active.current()
@@ -81,6 +81,11 @@ async def get_session_state() -> dict:
     # adopt the session. Default to the documented default rather than omitting
     # the key, so callers never have to special-case its absence.
     state.setdefault("origin", _DEFAULT_ORIGIN)
+    # What the session is for ('focus' | 'planning'), persisted by _start.py so a
+    # reconnecting client can label a planning console as one (design §5,
+    # D-11). Same reasoning as origin: the overlay branch rebuilds the dict and
+    # a CLI-started file predates the key, so default rather than omit.
+    state.setdefault("purpose", _DEFAULT_PURPOSE)
     return state


```

### `packages/studyloop/tests/test_session_start_purpose.py` (full source at `575e26ff`)

```python
"""``POST /api/session/start`` with ``purpose`` (design §5, D-10, D-11; T3.8).

A start request carries a *purpose*: ``focus`` (the default — today's study
session, byte-for-byte) or ``planning`` (a study-plan-architect interview).
One resolver, :func:`studyloop.agent_launcher.persona_mode_for`, maps the
purpose to the persona mode for BOTH transports, and a planning launch carries
the seam's :class:`PlanningBrief` rendered to Markdown as its own
``## Planning brief`` persona section — never as ``previous_notes`` (which
renders "Resuming Previous Session", wrong for a fresh interview) and never by
overloading ``topic`` (D-10). Only ``purpose`` is persisted on the live-session
state, for the reconnect label; no plan is created and no plan id is stored
(D-11).

Transport factories are swapped for :class:`StubTransport` exactly as the
sibling ``test_web_session_start_{pty,acp}.py`` files do, and the vendor-binary
preflight is bypassed through the ``STUDYLOOP_TEST_AGENT_CMD`` /
``STUDYLOOP_TEST_ACP_CMD`` hatch accessor, so nothing here spawns a real agent
or makes a paid call.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.planning import store
from studyloop.planning.application import PlanApplication
from studyloop.planning.intents import CreatePlan
from studyloop.session import active
from studyloop.session.transport import Started
from studyloop.web.app import create_app

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

# The persona file the ``plan-architect`` mode renders — the test reads the
# canonical body from the checkout so the assertion is about the mode being
# selected, not about any particular sentence in the persona.
_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "agents/manifest.json").exists():
    _REPO_ROOT = _REPO_ROOT.parent
_ARCHITECT_PERSONA = (_REPO_ROOT / "agents/shared/personas/plan-architect.md").read_text(
    encoding="utf-8"
)

# One of the interview prompts (planning/authoring.py INTERVIEW). The brief must
# carry the questions verbatim — the architect asks them, one per turn.
_FIRST_INTERVIEW_PROMPT = "What changes in your work or life once you have this skill?"

READY_ANSWERS: dict[str, object] = {
    "why": "Ship analytics queries without help",
    "success": ["Write a RANK() query unaided"],
    "topics": ["sql"],
    "milestones": [
        {"title": "OVER clause", "concepts": ["window function"]},
        {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_state():
    run_async(active.release())
    yield
    run_async(active.release())


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    from studyloop import session_state as ss
    from studyloop.web.routes.session import _start

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")
    monkeypatch.setattr(_start, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(_start, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(_start, "PARKING_FILE", tmp_path / "session-parking.md")


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    """A plans directory of this test's own, so "no plan was created" is a fact
    about the request under test, not about the developer's real plans."""
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]), raise_server_exceptions=False)


@pytest.fixture()
def personas(monkeypatch) -> list[str]:
    """Route both transports through StubTransport and record every canonical
    persona the PTY adapter's ``setup`` receives.

    The vendor binaries are declared present through the test hatch (the fake
    agent), not through ``shutil.which`` — same bypass the e2e harness uses.
    """
    seen: list[str] = []

    def _fake_hatch(name: str) -> str | None:
        if name == "STUDYLOOP_TEST_AGENT_CMD":
            return "test-agent {persona_file}"
        if name == "STUDYLOOP_TEST_ACP_CMD":
            return "python3 -m tests._stub_acp_agent"
        return None

    monkeypatch.setattr("studyloop.test_hatch_env", _fake_hatch)

    from studyloop.adapters._protocol import AgentAdapter
    from studyloop.agent_launcher import AGENTS

    def _record(canonical: str, session_dir: Path) -> Path:
        seen.append(canonical)
        return session_dir / "persona.md"

    for name in ("claude", "kiro"):
        real = AGENTS[name]
        monkeypatch.setitem(
            AGENTS,
            name,
            AgentAdapter(
                name=real.name,
                binary=real.binary,
                setup=_record,
                launch_cmd=lambda persona, resume: f"fake {persona}",
                teardown=None,
                mcp_setup=None,
            ),
        )

    def _pty_factory():
        return StubTransport(events=[Started(agent="claude")])

    def _acp_factory():
        return StubTransport(events=[Started(agent="kiro")])

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: _pty_factory,
        raising=False,
    )
    monkeypatch.setattr(
        "studyloop.web.routes.session._build_acp_transport",
        lambda config: _acp_factory,
        raising=False,
    )
    return seen


@pytest.fixture()
def _stub_db(monkeypatch):
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-purpose-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash",
        lambda study_id, persona_hash: None,
    )


def _start(client: TestClient, **body: object):
    payload: dict[str, object] = {"energy": 5, "agent": "claude", "transport": "pty"}
    payload.update(body)
    with patch("studyloop.web.routes.session.is_session_active", return_value=False):
        return client.post("/api/session/start", json=payload)


def _persona_for(client: TestClient, personas: list[str], **body: object) -> str:
    """The persona the launch shipped: the ACP response carries it inline, the
    PTY adapter received it through ``setup``."""
    resp = _start(client, **body)
    assert resp.status_code == 201, resp.text
    if body.get("transport") == "acp":
        return resp.json()["persona_text"]
    assert len(personas) == 1, "the PTY adapter must receive exactly one persona"
    return personas[0]


# ---------------------------------------------------------------------------
# The resolver and the brief section (agent_launcher)
# ---------------------------------------------------------------------------


class TestResolver:
    def test_persona_mode_for_maps_planning_to_plan_architect_and_else_to_focus(self) -> None:
        from studyloop.agent_launcher import persona_mode_for

        assert persona_mode_for("planning") == "plan-architect"
        assert persona_mode_for("focus") == "focus"

    def test_brief_renders_its_own_section_not_a_resume(self) -> None:
        from studyloop.agent_launcher import build_canonical_persona

        content = build_canonical_persona(
            "plan-architect", "Study plan", 5, brief="- interview item one"
        )

        assert "## Planning brief" in content
        assert "- interview item one" in content
        assert "Resuming Previous Session" not in content
        assert _ARCHITECT_PERSONA.strip() in content

    def test_no_brief_renders_no_brief_section(self) -> None:
        from studyloop.agent_launcher import build_canonical_persona

        assert "## Planning brief" not in build_canonical_persona("focus", "Python", 5)


# ---------------------------------------------------------------------------
# POST /session/start with purpose
# ---------------------------------------------------------------------------


class TestPlanningPurpose:
    def test_planning_purpose_selects_plan_architect_persona_with_brief_section(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        PlanApplication().apply(CreatePlan(title="SQL Window Functions", answers=READY_ANSWERS))

        persona = _persona_for(client, personas, topic="", purpose="planning")

        assert "**Mode:** plan-architect" in persona
        assert _ARCHITECT_PERSONA.strip() in persona, "the plan-architect persona is the mode"
        assert "## Planning brief" in persona, "the brief is its own section (D-10)"
        # The interview questions and the plans that already exist are the
        # brief's data; the architect asks the former and must not duplicate
        # the latter.
        assert _FIRST_INTERVIEW_PROMPT in persona
        assert "SQL Window Functions" in persona
        assert "sql-window-functions" in persona
        # Not previous_notes: that section is for a RESUMED study session.
        assert "Resuming Previous Session" not in persona
        # Not by overloading topic: the fixed architect label stands alone.
        assert "**Topic:** Study plan" in persona

    def test_planning_purpose_keeps_a_user_supplied_subject_as_the_topic(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        persona = _persona_for(client, personas, topic="Spark", purpose="planning")

        assert "**Topic:** Spark" in persona
        assert "**Mode:** plan-architect" in persona

        from studyloop.session_state import read_session_state

        assert read_session_state()["topic"] == "Spark"

    def test_default_purpose_is_focus_and_unchanged(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        """A request without ``purpose`` is today's focus session, byte for byte:
        same persona (so the same ``persona_hash``), same state ``mode``."""
        from studyloop.agent_launcher import build_canonical_persona
        from studyloop.web.routes.session._models import StartSessionRequest

        assert StartSessionRequest.model_fields["purpose"].default == "focus"

        persona = _persona_for(client, personas, topic="Python")

        expected = build_canonical_persona("focus", "Python", 5)
        assert persona == expected
        assert (
            hashlib.sha256(persona.encode()).hexdigest()[:16]
            == hashlib.sha256(expected.encode()).hexdigest()[:16]
        )
        assert "## Planning brief" not in persona
        assert "**Mode:** focus" in persona

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state["mode"] == "focus"
        assert state["purpose"] == "focus"

    def test_unknown_purpose_is_rejected_structurally(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        resp = _start(client, topic="Python", purpose="revision")

        assert resp.status_code == 422
        assert run_async(active.current()) is None

    def test_planning_launch_creates_no_plan_and_no_plan_id(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        PlanApplication().apply(CreatePlan(title="Existing", answers=READY_ANSWERS))
        before = store.list_plan_ids()
        assert before == ["existing"]

        resp = _start(client, topic="", purpose="planning")

        assert resp.status_code == 201, resp.text
        assert store.list_plan_ids() == before, "the architect creates plans, the launch does not"
        assert "plan_id" not in resp.json()

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state["study_session_id"] == "study-purpose-1"
        assert state["purpose"] == "planning", "this was a planning launch, not a downgraded focus"
        assert "plan_id" not in state, "no plan id is stored on the session (D-11)"

    def test_purpose_persisted_for_reconnect_label(
        self, client: TestClient, personas: list[str], _stub_db
    ) -> None:
        resp = _start(client, topic="", purpose="planning")
        assert resp.status_code == 201, resp.text

        from studyloop.session_state import read_session_state

        assert read_session_state()["purpose"] == "planning"

        # The dashboard/reconnect payload exposes it, overlaid on the live slot.
        state = client.get("/api/session/state").json()
        assert state["study_session_id"] == "study-purpose-1"
        assert state["purpose"] == "planning"
        assert state["topic"] == "Study plan"
        assert "plan_id" not in state

    def test_brief_failure_releases_session_claim(
        self, client: TestClient, personas: list[str], monkeypatch
    ) -> None:
        """If the brief cannot be built, the learner gets a structured error and
        the single-session slot is free again — no reservation, no live slot,
        no orphaned DB row."""

        def _boom(self):
            raise RuntimeError("plans directory unreadable")

        monkeypatch.setattr(PlanApplication, "prepare_planning", _boom)

        with (
            patch("studyloop.history.start_study_session") as mock_start,
            patch("studyloop.history.abort_study_session") as mock_abort,
        ):
            resp = _start(client, topic="", purpose="planning")

        assert resp.status_code == 500, resp.text
        body = resp.json()
        assert "error" in body
        assert "brief" in body["error"].lower()
        assert body.get("purpose") == "planning"

        from studyloop.session_state import read_session_state

        assert read_session_state() == {}, "the reservation must be cleared"
        assert run_async(active.current()) is None
        # The brief is built before the DB record exists, so there is nothing to
        # abort — and nothing was left behind either way.
        assert mock_start.call_count == mock_abort.call_count

        # And the slot really is free: a focus start now succeeds.
        with (
            patch("studyloop.history.start_study_session", return_value="study-after"),
            patch("studyloop.history.sessions.update_persona_hash"),
        ):
            again = _start(client, topic="Python")
        assert again.status_code == 201, again.text

    @pytest.mark.parametrize(
        ("transport", "agent"),
        [("pty", "claude"), ("acp", "kiro")],
    )
    def test_pty_and_acp_use_one_resolver(
        self,
        client: TestClient,
        personas: list[str],
        _stub_db,
        monkeypatch,
        transport: str,
        agent: str,
    ) -> None:
        """Both start paths resolve the persona mode through
        ``agent_launcher.persona_mode_for`` — one resolver, not two literals."""
        import studyloop.agent_launcher as launcher

        calls: list[str] = []
        real = launcher.persona_mode_for

        def _spy(purpose: str) -> str:
            calls.append(purpose)
            return real(purpose)

        monkeypatch.setattr(launcher, "persona_mode_for", _spy)

        persona = _persona_for(
            client, personas, topic="", purpose="planning", transport=transport, agent=agent
        )

        assert calls == ["planning"], f"{transport} must call persona_mode_for exactly once"
        assert "**Mode:** plan-architect" in persona
        assert "## Planning brief" in persona
        assert _FIRST_INTERVIEW_PROMPT in persona

        from studyloop.session_state import read_session_state

        state = read_session_state()
        assert state["transport"] == transport
        assert state["purpose"] == "planning"
```

## 6. Delta specs and public docs — diff vs `0a20a796` (one line of context)

### `openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md` — diff vs `0a20a796`

```diff
diff --git a/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md b/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md
index b166fa82..85d4bd90 100644
--- a/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md
+++ b/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md
@@ -183,3 +183,3 @@ not gated.

-### Requirement: Active-plan guidance is a deterministic read (not yet consumed)
+### Requirement: Active-plan guidance is a deterministic read
 `get_active_guidance(*, today=None)` SHALL return a frozen `ActiveGuidance`
@@ -211,6 +211,4 @@ date.

-This view exists so that the `now` decision engine (issue #10, Phase 3) has
-one plan-static read to consume. **Nothing consumes it yet**: `studyloop now`
-and the Today card are unchanged by this phase, and `docs/study-plans.md`'s
-"does not do yet" list stays as it is until #10 ships.
+This view is the one plan-static read the `now` decision engine consumes
+(issue #10, next requirement).

@@ -266,2 +264,116 @@ and the Today card are unchanged by this phase, and `docs/study-plans.md`'s

+### Requirement: The now engine is plan-aware with tested ranking rules
+`studyloop.learning.decision.build_now_plan` SHALL remain the only ranker of
+study actions and SHALL consume active plans through exactly one call to
+`PlanApplication().get_active_guidance(today=…)`, where `today` is the date
+of the same instant `generated_at` records. It SHALL apply these rules, in
+this order (design §3, D-5):
+
+1. Candidates are collected as before; a failure to read plans at all SHALL
+   degrade to a `warnings` entry, never a failed recommendation.
+2. The energy capability is `low|medium|high → 3|6|10`. For an active plan
+   whose `energy_floor` exceeds it, the next milestone SHALL be listed in
+   `energy_deferred` and SHALL NOT become a candidate; plan-related due recall
+   and struggle repair stay eligible and plan-related.
+3. A candidate is plan-related when `normalise_match_key` of its concept,
+   topic or course **equals** one of the plan's `match_keys`; no substring
+   test. It names the plan's next milestone when the key equals one of that
+   milestone's concepts; a topic or finished-milestone match carries
+   `milestone_index = None`.
+4. Scoring is today's scoring plus one bounded bias for plan-related
+   candidates: within one urgency class plan-related beats unrelated, and a
+   globally more-urgent unrelated candidate still wins — a bias, not a filter.
+5. When no collected candidate represents an eligible (ready, energy-permitted)
+   plan's next milestone, one `conversation` candidate SHALL be synthesised
+   for it (source `study_plan:<plan_id>:<index>`, concept = the milestone's
+   first concept or its title, topic = the plan's first topic), scored below
+   every due and repair class. A learner with an active plan and no evidence
+   is therefore sent to the plan, and `starter` is `false`.
+6. After de-duplication every matching `PlanRef(plan_id, milestone_index)`
+   SHALL be attached to each ranked action, ordered by target urgency
+   (`overdue`, `soon`, `later`, `undated`) → most recent `updated` → `plan_id`,
+   keeping the most specific milestone per plan.
+7. When primary + alternates hold no plan-backed action and an eligible one
+   whose estimate fits the requested time exists further down, it SHALL
+   replace the last alternate only; the primary is never re-ranked by plans.
+8. A fully-checked active plan SHALL appear in `completion_actions` and SHALL
+   be neither matched nor synthesised. An active-but-unready plan SHALL be
+   listed and matched but never synthesised, with a warning naming its
+   blockers.
+
+`NowPlan` gains `active_plans` (ordered as rule 6), `energy_deferred`,
+`completion_actions` and `warnings`; `LearningRecommendation` gains
+`plan_refs: tuple[PlanRef, ...] = ()`. `to_json_dict()` SHALL omit each of
+these when empty, so a learner with no active plan receives the pre-#10
+payload **byte for byte** — pinned by `tests/golden/now_plan_no_active.json`,
+captured before any of this shipped. Renderers (`studyloop now`, `GET
+/api/now`, the Today card, the daily recap) SHALL show plan relevance and
+energy deferral from these fields and SHALL NOT re-rank. Ranking tests prove
+ranking compliance, not learner benefit (D-16); a five-scenario human rubric
+receipt accompanies the change.
+
+#### Scenario: No active plan is byte-identical to the golden
+- **WHEN** no active plan exists (an empty plans directory, or only a draft)
+  and `build_now_plan()` runs with a frozen clock in an empty world
+- **THEN** the serialised `to_json_dict()` equals
+  `tests/golden/now_plan_no_active.json` byte for byte, and no
+  `active_plans`, `energy_deferred`, `completion_actions`, `warnings` or
+  `plan_refs` key is present
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
+  milestone is `Frames` and a struggle repair on a finished milestone's
+  concept is collected
+- **THEN** the repair is primary with `PlanRef(plan, None)`,
+  `energy_deferred` names `(plan, 1, 5, 3)`, and no `study_plan:` candidate
+  exists; at `medium` energy nothing is deferred and the milestone is
+  synthesised
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
+  the alternates are the unrelated items and `energy_deferred` names the
+  milestone
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
+  daily recap run against the energy-deferral fixture
+- **THEN** each names the primary the engine chose, the plan it advances, and
+  the deferred milestone; with no plan the CLI panel prints no plan lines,
+  `GET /api/now` equals the golden, and the recap's `plan_context` is absent
+
 ### Requirement: Adapters reach study plans only through the seam
```

### `openspec/changes/plan-application-seam/specs/mcp-server/spec.md` — diff vs `0a20a796`

```diff
diff --git a/openspec/changes/plan-application-seam/specs/mcp-server/spec.md b/openspec/changes/plan-application-seam/specs/mcp-server/spec.md
index 6cd1819e..ae0beb87 100644
--- a/openspec/changes/plan-application-seam/specs/mcp-server/spec.md
+++ b/openspec/changes/plan-application-seam/specs/mcp-server/spec.md
@@ -20,7 +20,8 @@ title/heading rule) SHALL render as their message.

-This is the **only** change to `mcp/tools.py` in this phase. The six read/
-write plan tools of design §4 (`list_study_plans` … `set_study_plan_status`)
-and the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
-`delete_study_plan`) are **not yet registered**; the stdio inventory is
-unchanged at this phase.
+This was the **only** change to `mcp/tools.py` in Phase 2. The six read/write
+plan tools of design §4 are registered in Phase 3 (#11, the requirement
+below); the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
+`delete_study_plan`) are **not yet registered**. The stdio smoke test pins a
+lower bound and the core-tool names, not an exact count, and is retargeted to
+the full inventory in #12 (D-9).

@@ -56 +57,103 @@ unchanged at this phase.
   added
+
+
+### Requirement: Study-plan discovery and authoring tools
+`register_tools(mcp)` SHALL register six study-plan tools in the production
+inventory, each a thin adapter that makes exactly one
+`studyloop.planning.PlanApplication` call and imports no storage, index,
+authoring or evaluation module (D-6):
+
+| Tool | Seam call |
+|---|---|
+| `list_study_plans(status=None)` | `browse(status=)` → `{"plans": [PlanSummary.to_json_dict()…], "count": N}` |
+| `get_study_plan(plan_id, include_markdown=False, include_history=False, history_limit=20)` | `inspect(...)` → `PlanDetail.to_json_dict()` (the `GET /api/plans/{id}` body) |
+| `get_planning_interview()` | `prepare_planning()` → `PlanningBrief.to_json_dict()` (`questions`, `seed`, `existing_plans`) |
+| `create_study_plan(title, answers, plan_id=None, status="draft")` | `apply(CreatePlan(...))` with `overwrite` always `False` → `PlanDetail.to_json_dict()` |
+| `update_study_plan(plan_id, title=None, topics=None, target_date=None, energy_floor=None, review_cadence_days=None, notes=None, milestones=None, status=None)` | `apply(RevisePlan(...))` — one intent, judged as one document → `PlanDetail.to_json_dict()` |
+| `set_study_plan_status(plan_id, status)` | `apply(TransitionLifecycle(...))` → `PlanDetail.to_json_dict()` |
+
+Every response SHALL be the seam view's `to_json_dict()` built on that call —
+fresh containers, never a cached or shared dict. The adapter SHALL carry no
+plan policy: the readiness gate, the lifecycle status list, the id rules and
+the conflict check are the seam's, and the adapter forwards its arguments
+unchanged (an omitted `update_study_plan` field SHALL reach the seam as `None`,
+"leave as is", never as `""` or `[]`).
+
+The `create_study_plan` schema SHALL NOT expose `overwrite` (D-4); an agent
+cannot replace an existing plan by picking its id, and a taken id is a
+conflict. `update_study_plan` SHALL NOT expose `learning_record`:
+`record_plan_learning` remains the one record writer (D-9).
+
+`get_study_plan` SHALL refuse a `history_limit` outside `1..200` — the range
+the Web history route accepts — with `invalid: history_limit must be between 1
+and 200, got <n>` **before** calling the seam, so a refused limit performs no
+database query.
+
+Every seam refusal SHALL be one `ToolError` whose message is
+`<kind>: <the seam's message>`, where `kind` is machine-readable:
+`PlanNotFound` → `not_found`, `InvalidPlanId` → `invalid_id`, `PlanConflict` →
+`conflict`, `InvalidField` → `invalid`, `PlanNotReady` → `not_ready` (rendered
+`not_ready: plan is not ready to activate: <blocker>; <blocker>…`, with the
+suffix `— the plan is already active; pause it or repair the blockers before
+writing` when the plan was already active), `InvalidMilestone` →
+`invalid_milestone`, and `plan_error` for any `PlanError` subclass this mapping
+has not met. The `ToolError` SHALL chain the domain error as its cause.
+
+#### Scenario: Discover, inspect, create, revise, activate
+- **WHEN** an agent calls `get_planning_interview()` (no plans exist), then
+  `create_study_plan("Python Decorators", {"why": …, "success": […],
+  "topics": ["python"]})`, then `list_study_plans()`, then
+  `update_study_plan(<id>, topics=[…], milestones=[{"title": …, "concepts":
+  […]}])`, then `set_study_plan_status(<id>, "active")`, then
+  `get_study_plan(<id>, include_markdown=True)`
+- **THEN** the interview lists the `why`, `success` and `milestones` keys with
+  `existing_plans: []`; the create returns a `draft` plan whose id is the
+  unique title slug and whose `readiness.ready` is `false` (no milestones yet);
+  the list shows that one plan; the revision returns `readiness.ready: true`
+  with the new topics and milestone concepts; the transition returns status
+  `active`; the inspection returns the active plan with its Markdown document,
+  and `list_study_plans(status="active")` counts it while
+  `list_study_plans(status="draft")` does not
+
+#### Scenario: Refused activation carries the blockers and writes nothing
+- **WHEN** `set_study_plan_status("husk", "active")` — or
+  `create_study_plan("Husk", {}, plan_id="husk", status="active")`, or an
+  `update_study_plan` whose resulting document would be active — is called
+  for a plan with no mission, success criteria or milestones
+- **THEN** a `ToolError` is raised whose message starts with `not_ready: plan
+  is not ready to activate: ` and contains every blocker string the plan's
+  `readiness` reports, the existing document is byte-identical afterwards
+  (still `draft`), and no document is created for the refused create
+
+#### Scenario: No overwrite through the MCP door
+- **WHEN** `create_study_plan` is called with a `plan_id` that already exists
+- **THEN** a `ToolError` starting `conflict: ` is raised, the existing
+  document is byte-identical afterwards, and the tool's input schema has no
+  `overwrite` property to ask for otherwise
+
+#### Scenario: Every refusal is one prefixed ToolError
+- **WHEN** the seam raises `PlanNotFound`, `InvalidPlanId`, `PlanConflict`,
+  `InvalidField`, `InvalidMilestone`, or an unmapped `PlanError` from
+  `browse`, `inspect`, `prepare_planning` or `apply`
+- **THEN** the tool raises exactly one `ToolError` reading `not_found: …`,
+  `invalid_id: …`, `conflict: …`, `invalid: …`, `invalid_milestone: …` or
+  `plan_error: …` respectively, followed by the seam's message, with the
+  domain error chained as `__cause__`
+
+#### Scenario: A retried status transition is not refused
+- **WHEN** `set_study_plan_status("decorators", "paused")` is called twice
+- **THEN** both calls apply the same `TransitionLifecycle`, both return the
+  plan with status `paused`, and neither raises
+
+#### Scenario: history_limit is bounded before any read
+- **WHEN** `get_study_plan("decorators", include_history=True,
+  history_limit=0)` (or `-1`, `201`, `10000`) is called
+- **THEN** a `ToolError` reading `invalid: history_limit must be between 1 and
+  200, got <n>` is raised and `PlanApplication.inspect` is never called; `1`
+  and `200` are accepted and forwarded unchanged
+
+#### Scenario: Responses are fresh containers
+- **WHEN** a response from any of the six tools is mutated by the caller and
+  the same call is repeated
+- **THEN** the second response is equal to an untouched first response and is
+  not the same object
```

### `openspec/changes/plan-application-seam/specs/live-session-orchestration/spec.md` — diff vs `0a20a796`

```diff
diff --git a/openspec/changes/plan-application-seam/specs/live-session-orchestration/spec.md b/openspec/changes/plan-application-seam/specs/live-session-orchestration/spec.md
new file mode 100644
index 00000000..109b18d1
--- /dev/null
+++ b/openspec/changes/plan-application-seam/specs/live-session-orchestration/spec.md
@@ -0,0 +1,72 @@
+## ADDED Requirements
+
+### Requirement: Session purpose
+A web session start (`POST /api/session/start`) SHALL carry a *purpose* —
+`focus` (the default) or `planning` — validated structurally by
+`StartSessionRequest` (`purpose: Literal["focus", "planning"] = "focus"`), so
+any other value is refused with `422` before the handler runs. A `focus` start
+SHALL be indistinguishable from a start that names no purpose: the same
+persona, the same `persona_hash`, the same session-state `mode`. A `planning`
+start SHALL launch the study-plan architect: the persona is the
+`plan-architect` mode carrying a `## Planning brief` section (the interview
+questions, the learner's history evidence and the existing plans), and the
+session's topic is the learner's subject when one was supplied, else the fixed
+label `Study plan` — the same label `studyloop plan architect` pins. The start
+SHALL NOT create a plan and SHALL NOT store a plan id anywhere; the architect
+creates plans through the plan tools during the session. The only planning
+fact the live-session state carries is `purpose`, written on every start
+(never inherited through the state file's read-merge-write), and
+`GET /api/session/state` SHALL expose it for the reconnect label, defaulting to
+`focus` when the state predates the key or the overlay branch rebuilt the
+payload. If the planning brief cannot be built, the start SHALL refuse with a
+structured error (`error`, `purpose`, `repair`; HTTP 500) and leave the
+single-session slot free — no reservation, no live slot, no study row. Both
+transports (`pty` and `acp`) SHALL follow this requirement identically.
+
+#### Scenario: Planning start launches the architect with a brief
+- **WHEN** `POST /api/session/start` is called with `{"purpose": "planning", "topic": "", ...}`
+- **THEN** the response is `201`, the persona the agent receives has
+  `**Mode:** plan-architect`, contains the plan-architect persona body and a
+  `## Planning brief` section naming the interview questions and every existing
+  plan by id and title, contains no `Resuming Previous Session` section, and
+  the session topic is `Study plan`
+
+#### Scenario: Planning start keeps a supplied subject
+- **WHEN** `POST /api/session/start` is called with `{"purpose": "planning", "topic": "Spark", ...}`
+- **THEN** the persona and the session state both carry the topic `Spark`
+
+#### Scenario: Default purpose is focus and unchanged
+- **WHEN** `POST /api/session/start` is called with no `purpose`
+- **THEN** the persona is byte-identical to `build_canonical_persona("focus", topic, energy)`,
+  the `persona_hash` is unchanged from before the purpose existed, the state's
+  `mode` is `focus` and its `purpose` is `focus`
+
+#### Scenario: Unknown purpose is refused structurally
+- **WHEN** `POST /api/session/start` is called with `{"purpose": "revision", ...}`
+- **THEN** the response is `422` and no session slot is held
+
+#### Scenario: Planning start creates no plan and stores no plan id
+- **WHEN** one plan exists and `POST /api/session/start` is called with `purpose: planning`
+- **THEN** the set of plan ids on disk is unchanged, the `201` body has no
+  `plan_id`, and the session state has no `plan_id` key
+
+#### Scenario: Purpose is persisted for the reconnect label
+- **WHEN** a `planning` session has started
+- **THEN** the session state's `purpose` is `planning` and
+  `GET /api/session/state` reports `purpose == "planning"` alongside the live
+  session's id and topic
+
+#### Scenario: Brief failure releases the session claim
+- **WHEN** `PlanApplication.prepare_planning` raises during a `planning` start
+- **THEN** the response is `500` with an `error` naming the brief and
+  `purpose == "planning"`, the session state file is empty, no in-process
+  session is held, no study row was created, and a following `focus` start
+  succeeds with `201`
+
+#### Scenario: PTY and ACP resolve the mode through one resolver
+- **WHEN** a `planning` start is made over `transport: pty` and, separately,
+  over `transport: acp`
+- **THEN** each start calls `agent_launcher.persona_mode_for` exactly once
+  with `planning`, each persona has `**Mode:** plan-architect` and a
+  `## Planning brief` section, and each state records its own `transport`
+  with `purpose == "planning"`
```

### `openspec/changes/plan-application-seam/specs/agent-adapters/spec.md` — diff vs `0a20a796`

```diff
diff --git a/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md b/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md
new file mode 100644
index 00000000..cd850ea2
--- /dev/null
+++ b/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md
@@ -0,0 +1,32 @@
+## ADDED Requirements
+
+### Requirement: Persona resolution by purpose
+`studyloop.agent_launcher` SHALL expose one resolver,
+`persona_mode_for(purpose: str) -> str`, mapping a session purpose to the
+persona mode that serves it: `planning` → `plan-architect`, anything else →
+`focus`. Every web start path (PTY and ACP alike) SHALL obtain its mode
+through this resolver; no route SHALL name a persona mode as a literal
+(`rg 'build_canonical_persona\("focus"' packages/studyloop/src/studyloop/web` → 0).
+`build_canonical_persona(mode, topic, energy, *, previous_notes=None,
+brief=None)` SHALL accept the planning brief through the `brief` keyword and
+render it as its own `## Planning brief` section — introduced as data about
+the learner, not instructions — placed with the other context sections ahead
+of the persona body. The brief SHALL NOT be carried through `previous_notes`
+(which renders `Resuming Previous Session`, the framing for a resumed study
+session) and SHALL NOT be folded into `topic`. With `brief=None` the output
+SHALL be byte-identical to the pre-`brief` output, so no existing session's
+`persona_hash` changes.
+
+#### Scenario: Resolver maps the two purposes
+- **WHEN** `persona_mode_for("planning")` and `persona_mode_for("focus")` are called
+- **THEN** they return `plan-architect` and `focus` respectively
+
+#### Scenario: Brief renders as its own section
+- **WHEN** `build_canonical_persona("plan-architect", "Study plan", 5, brief="- item")` is called
+- **THEN** the result contains `## Planning brief`, contains `- item`, contains
+  the plan-architect persona body, and does not contain `Resuming Previous Session`
+
+#### Scenario: No brief, no section
+- **WHEN** `build_canonical_persona("focus", "Python", 5)` is called
+- **THEN** the result contains no `## Planning brief` section and is
+  byte-identical to the output before the `brief` keyword existed
```

### `docs/agent-install.md` — diff vs `0a20a796`

```diff
diff --git a/docs/agent-install.md b/docs/agent-install.md
index 57a57c1c..b16df56d 100644
--- a/docs/agent-install.md
+++ b/docs/agent-install.md
@@ -206,2 +206,31 @@ reports only evidence-backed coding-harness integrations.

+## Study-plan tools over MCP
+
+The `studyloop` MCP server (the `studyloop-mcp` command; per-harness
+registration is in `agents/mcp/README.md`) exposes the learner's study plans
+to any connected agent. Every tool
+goes through the same plan application layer the CLI and Web UI use, so the
+readiness gate, the lifecycle statuses and the "the Markdown document is the
+source of truth" rule are identical on every surface. An agent that cannot
+reach the MCP server can do the same work with `studyloop plan …` at a shell.
+
+| Tool | Purpose |
+|---|---|
+| `list_study_plans(status=None)` | List plan summaries, active first; filter to one lifecycle status. |
+| `get_study_plan(plan_id, include_markdown=False, include_history=False, history_limit=20)` | Read one plan in full — mission, milestones, records, readiness — optionally with its Markdown and the checkpoint log (1–200 rows). |
+| `get_planning_interview()` | The interview questions, an evidence seed from the study databases, and the plans that already exist — call before interviewing. |
+| `create_study_plan(title, answers, plan_id=None, status="draft")` | Draft a new plan from interview answers; never replaces an existing plan (a taken id is a conflict). |
+| `update_study_plan(plan_id, …)` | Revise fields, topics, milestones and status together, judged as one document and saved once. |
+| `set_study_plan_status(plan_id, status)` | Move a plan between `draft`, `active`, `paused`, `complete`, `abandoned`; activation is readiness-gated. |
+| `record_plan_learning(plan_id, title, body="", status="active")` | Append a learning record to the plan — the wind-down's first write. |
+
+A refused call is a tool error whose message starts with a machine-readable
+kind — `not_found:`, `invalid_id:`, `conflict:`, `invalid:`,
+`invalid_milestone:` or `not_ready:` — followed by the plan layer's own
+message. A `not_ready:` refusal names every blocker, so the agent can ask the
+learner for what is missing instead of reporting that something is wrong.
+Milestone completion, checkpoint evaluation and deletion over MCP are not
+available yet; use `studyloop plan milestone`, `studyloop plan evaluate` and
+the Web UI for those.
+
 ## Data integrity
```

### `docs/study-plans.md` — diff vs `0a20a796`

```diff
diff --git a/docs/study-plans.md b/docs/study-plans.md
index 800bb01a..1b3109f2 100644
--- a/docs/study-plans.md
+++ b/docs/study-plans.md
@@ -122,4 +122,2 @@ conversation should work through. It does not itself start an agent.

-- An active plan does not currently bias the recommendation from `studyloop now`
-  or the Today card.
 - The Web UI does not launch a planning agent or automatically structure the
```

## 7. Reference facts you may rely on

- `InterleaveMode = Literal["off", "adaptive"]`, `INTERLEAVE_RATIOS` keyed by energy; `build_now_plan(*, energy, time_minutes, modality, interleave)` already accepts `interleave`; the CLI `studyloop now --interleave` and `GET /api/now?interleave=` expose it; the MCP tool does not (T3.5).
- `browse(status=None)` returns `PlanSummary` tuples in the store's `list_plans()` order, whose code is `out.sort(key=lambda p: (p.status != "active", p.updated))` — active first, then **ascending** `updated` (oldest edit first); the store's own comment says "then most recently updated" and `browse`'s docstring says "then ascending `updated`, ties broken by id". Pre-Phase-3 code, reproduced here only so you can judge the new tool description against it.
- `normalise_match_key`: NFKC → casefold → punctuation and `_` to spaces → collapse whitespace → strip (review-2 G3; sorted, de-duplicated tuple).
- `PlanNotReady(readiness, already_active=False)`; `ReadinessView.blockers` strings come from `authoring.readiness()` (e.g. `No mission why`, `No success criteria`, `No milestones`).
- Production MCP inventory: 23 tools at `0a20a796`, 29 at `575e26ff` (the six appended). `record_plan_learning` is among the 23.
- The CLI `studyloop plan architect` (commit `776a9dc0`) launches the plan-architect persona with the topic label `Study plan` and writes no `purpose` to the session state.


## 8. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for Phase 3 as the base of Phase 4, with the single
   sentence that decides it. If the three streams deserve different verdicts, say so per stream (#10, #11, #13a).
2. **Findings**, each with severity 🔴 defect (wrong behaviour or a bug), 🟡 must-fix-before-Phase-4
   (design/contract violation, missing test, unsafe pattern), 🔵 should-fix, 💡 note. For each: file:line or
   function, what is wrong, why it matters, the concrete fix, and the RED test that would pin it (name it). Check
   specifically:
   - **#10 engine** (a) the nine rules against `decision.py` line by line — is rule 5 really a bias (can `+12`
     ever lift a synthesised milestone over a due/repair item; can two plan-related candidates with different
     urgency invert)? Is rule 8's `_guarantee_plan_backed` correct when a *deferred* plan's topic-matched repair
     is the only plan-backed candidate (it carries `plan_refs` with `milestone_index=None` — does that satisfy
     "eligible plan-backed action")? (b) `_candidate_keys` matches on `course` too — the design says
     "topic/course or named milestone concepts"; is matching an unready plan's keys (bias + refs, never
     synthesise) right? (c) `_load_guidance`'s bare `except Exception → None → one warning`: acceptable
     resilience or a bug-hider? (d) the synthesised candidate: `MILESTONE_BASE_SCORE = 48` + urgency bonus +
     bias, `action_type="conversation"`, `topic = topics[0] or "study"`, `concept = first concept or title`,
     `evidence_command` from `_evidence_command` — what does `studyloop progress "<milestone title>" -t "study"`
     do to the learner's records? (e) `_order_plans` — three stable sorts; `updated` is an ISO string — is
     string order date order for every value the store writes? (f) `attach_refs` — `refs.get(plan_id) is None`
     upgrade rule; a candidate matching the next milestone's concept AND a finished one; (g) `_PlanContext.build`
     — `eligible`, `deferred`, `completions`, warnings for unready plans (message content: data or prompt?);
     (h) `to_json_dict` — `LearningRecommendation.to_json_dict` pops and re-adds `plan_refs` at the END of the
     dict; key order vs golden; `asdict` deep-copies `metadata` — fine? (i) frozen-clock coupling: the tests
     replace `decision.datetime` — is `today` derived from `now` the same instant the CLI/Web pass?
   - **#10 renderers** (j) `_now.py` `getattr(plan, "energy_deferred", ())` defensive reads — dead defensiveness
     or needed? The Rich panel prints `plan.energy` in the deferral line; the `Alternates` table grows a column
     only when plans exist; the spoken text. (k) `recap.py` — `plan_context` string built from the engine's
     fields, absent when empty; `cli/_recap.py`'s rich panel does not print it (reported) — acceptable? (l) the
     Today card: `planLabel`, `deferredNotes`, `completionNotes`, `hasPlanContext` (unused getter?); the HTML
     block "Your plans" not being a `.today-card`; Alpine `x-text` escaping — is any engine string rendered as
     HTML anywhere?
   - **#10 tests + rubric** (m) do the ten engine tests actually pin the nine rules, or the implementation
     (e.g. `score < primary.score` vs an exact score; 4 unrelated at 140 − 2i)? Hostile-content fixtures
     (titles/topics/milestone text) — required by review 2, present? (n) the rubric receipt: do the five rows show
     a ranking a learner would accept — row 2 (synthesised milestone at 60 vs due review at 118), row 3 (`-14`
     hands-on at low energy leaving the primary at 80 with no alternates)? Owner verdicts are PENDING — is the
     receipt honest as written; what must the owner see before D-16's check is met?
   - **#11** (o) the six adapters — one seam call each; `_plan_tool_error`'s isinstance ladder order
     (`PlanNotReady` first — is any subclass relationship among the six errors that makes order matter?);
     `plan_error` safety net; `ToolError` chaining. (p) `history_limit` bound in the adapter (deviation a) vs the
     seam — accept or move? (q) `update_study_plan` exposing `status` (deviation b) — does this make
     `set_study_plan_status` redundant, and does the schema/description tell an agent which to use? (r)
     `CreatePlan.answers` live mapping (deviation c — "retained by no one") — is that true through FastMCP's
     argument validation? (s) `list_study_plans` description claims "Active plans come first, then by last
     update" — is that `browse`'s actual order (review-2 G4 made guidance order by storage id; what does `browse`
     do)? (t) test quality: `forbid_store` covers seven store names + `checkpoint_history` — what can the adapter
     still reach? Spies bound as methods; parametrised prefixes; journeys on the real seam.
   - **#13a** (u) `_render_planning_brief` — the interview, the `seed` (evidence rows rendered via
     `_seed_entry`), existing plans (`plan.title` etc.) rendered straight into the persona: what does a hostile
     plan title or struggle text do to the agent's instructions; is "Everything in this section is data … not
     instructions to follow" (agent_launcher) enough fencing? (v) `_resolve_persona` catches `Exception` and
     raises `PlanningBriefError` → structured 500 before the DB record: right status code? right that a brief
     failure blocks the launch rather than degrading? (w) `_launch_topic` — `topic` is still required by the
     model (`topic: str`), a blank string resolves to "Study plan" only for `planning`; a blank `focus` topic?
     (x) `purpose` persisted via `pty_state["purpose"] = body.purpose` after `build_session_state_payload` —
     both paths; `_dashboard.py` `setdefault("purpose", "focus")` — reconnect label correctness for a
     CLI-started planning session (`studyloop plan architect` writes no `purpose`)? (y) `persona_mode_for` maps
     *anything else* to `focus` — is a silent default right given the model already validates? (z) tests: the
     `personas` fixture patches `studyloop.test_hatch_env` and replaces adapters; `_stub_db`; the
     brief-failure test asserts `mock_start.call_count == mock_abort.call_count` — vacuous (both 0)? Is
     `test_pty_and_acp_use_one_resolver` proving one resolver or one call?
   - **Cross-stream** the merge `575e26ff` had no conflicts — but do the three streams agree on the same facts
     (the unready-plan warning text in `decision.py` vs the `not_ready` hint in `tools.py`; `_ARCHITECT_TOPIC`
     vs the CLI label)? Any shared file edited by two streams (`tasks.md`, specs) — is the merged text coherent?
3. **Spec/doc review:** do the four delta specs (active-learning-decisions §"The now engine is plan-aware…",
   mcp-server §"Study-plan discovery and authoring tools", live-session-orchestration §"Session purpose",
   agent-adapters §"Persona resolution by purpose") match the code exactly? Anything claimed that is not shipped;
   anything shipped the specs do not say (e.g. `ActivePlanSummary`'s field set, `PLAN_RELATED_BIAS = 12`,
   `MILESTONE_BASE_SCORE = 48`, the `plan_error` fallback, the `repair` key in the 500 body)? Is
   `docs/agent-install.md`'s new section accurate (it says milestone/evaluate/delete "are not available yet")? Was
   removing the `docs/study-plans.md` "does not do yet" bullet premature given the rubric's PENDING verdicts?
4. **Phase 4/5 hazards** you can see from this base — be specific: (i) **#12's three tools**
   (`set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan`): what in `_plan_tool_error`, the
   `forbid_store` harness, `AssessmentResult`'s sink fields and the deviation-12 gate will they trip over; how
   should `evaluate_study_plan(record=False)` report `db_write`/`document_write`; should `delete_study_plan`
   require `confirmed=True` at the schema level? (ii) **the inventory pin**: T4.1's DoD says the stdio smoke test
   "lists 35" — with 23 at `0a20a796` and 29 now, the nine make **32**; what exactly should #12 assert (exact
   count? the nine names? both?) and should `record_plan_learning`'s inline `PlanNotReady` mapping be folded
   into `_plan_tool_error` then? (iii) **#13b/#14** — what do they need from the purpose plumbing that is not
   there: a way for the persona to name the nine tools (T4.2), the `purpose` in the `201` body and the state,
   the "Plan with architect" affordance, the reconnect label; is `persona_text` for ACP carrying the brief the
   right transport for a long brief; anything in `_resolve_persona` that #13b will have to change?
5. **Process finding:** three agents worked in parallel without seeing each other. Name the one judgment call
   across the three streams you would most want a human to have made instead, and why (candidates: the bias
   constant 12 and base 48; `update_study_plan` exposing `status`; the brief failure as a hard 500; the rubric
   shipped with PENDING verdicts and the docs bullet removed anyway).
6. **Interleave commit for `get_next_action` (D-8, T3.5)** — specify the exact last-writer change to
   `mcp/tools.py` for the arbiter to land TDD after your review: the new signature (`interleave: str = "off"`
   as a plain string like `energy`/`modality`, validated against `get_args(InterleaveMode)` → `ToolError` on
   anything else, then `cast` and forwarded to `build_now_plan(interleave=…)`), the docstring `Args:` line, and
   the test names — in `tests/test_mcp_plan_tools.py` or a new `tests/test_mcp_next_action.py` — that pin: the
   schema gains `interleave` with default `"off"`; `"adaptive"` is forwarded and the response carries a
   non-empty `interleave_ratio` at non-low energy; an invalid value is a `ToolError` naming the choices and
   `build_now_plan` is not called; the default call is byte-identical to today's (`interleave="off"` → the
   golden shape). State whether the tool's existing `energy`/`modality` validation pattern should be reused
   verbatim or factored, and whether `@consistent_read` stays. MCP `interleave` parity is #10's acceptance
   criterion; nothing else in `tools.py` may move in that commit.

Be concrete over complete: a file:line and a test name beat a paragraph.
