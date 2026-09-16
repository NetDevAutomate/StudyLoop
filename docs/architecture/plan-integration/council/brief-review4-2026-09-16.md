# Council brief — code review 4: Phase 4 (#12 ∥ #13b) of the plan-integration programme

**Date:** 2026-09-16 · **Branch:** `fix/plan-integration-bugs`, reviewed tree `b2f37fa4` = the merge of two parallel
Phase-4 branches (`feat/p4-mcp12`, `feat/p4-13b`) onto the accepted Phase-3 base `205819c7` (review-3 corrections
F1–F13 and the D-8 `interleave` commit included; accepted in `review-3-arbitration-2026-09-16.md`, `GATE: ACCEPT`).
**You are one independent seat**; no other seat's answer is visible. You have no tools — this brief is the complete
evidence base. Two implementing agents ran unattended in separate worktrees, each owning disjoint files; your
findings gate Phase 5 (#14 the Web "Plan with architect" journey) and Phase 6 (#15 reconcile, verification receipt,
combined journey test).

## 0. What you are reviewing against (binding)

### Design §4 rows 7–9 — the three progression tools (D-8, D-9)

| Tool | Seam call | Phase |
|---|---|---|
| `set_study_plan_milestone(plan_id, index, done)` | `apply(SetMilestone)` | 4 (#12) |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `assess` | 4 |
| `delete_study_plan(plan_id, confirmed=False)` | `apply(DeletePlan)` | 4 |

**D-8:** `mcp/tools.py` has one writer at a time: #11 → #12 → #10's `interleave` commit. The arbiter landed the
`interleave` commit *before* #12 started (review 3, `c30330a0`/`65bde13c`), so #12 rebased onto it and was told
not to touch `get_next_action`. **D-9:** nine tools stay nine; `record_plan_learning` is kept. Design §4 (corrected
by review-3 F13): the production registry had **23** tools at `0a20a796`, 29 after #11, and **32** once #12's three
land — `record_plan_learning` is among the original 23. **D-4:** `overwrite` is never exposed on `create_study_plan`.
**D-6:** adapters import only `studyloop.planning.{application,views,errors,intents}` (guard
`tests/test_architecture_plan_seam.py`, 30 tests).

### Design §5 — `planning` purpose (D-10, D-11), as Phase 3 shipped it and #13b builds on

```python
class StartSessionRequest: ...; purpose: Literal["focus", "planning"] = "focus"
def persona_mode_for(purpose: str) -> str: return "plan-architect" if purpose == "planning" else "focus"
def build_canonical_persona(mode, topic, energy, *, previous_notes=None, brief: str | None = None) -> str
```
The persona body for `plan-architect` is `agents/shared/personas/plan-architect.md`, read at render time from the
repo (`PERSONA_DIR = <repo>/agents/shared/personas`). A `planning` start renders the seam's `PlanningBrief` as a
"Planning brief" section ahead of that body (D-10); only `purpose` is persisted on live-session state (D-11).
The Kiro/Claude/OpenCode *harness projections* under `agents/{kiro,claude,opencode}` carry the same body verbatim
after their own header; there is no projection generator, only copies plus the hash manifest
`agents/manifest.json` (`scripts/update-agent-manifest.py`).

### Review-3 arbitration — the Phase-4 hazards it handed over (verbatim)

> **#12 — three tools.** `set_study_plan_milestone` reuses `_plan_tool_error` unchanged (`InvalidMilestone` and the
> `already_active` hint are mapped) and must come back `not_ready: … already active … pause or repair` on a husk with
> nothing written — the twin of F1's engine test. `evaluate_study_plan(record=False)` calls `assess`, never
> `apply(AssessPlan)` (it is not in `PlanIntent`), and returns the view's JSON **with** `db_write`/`document_write` as the
> seam reports them (`not_requested` for a preview — do not flatten to booleans, do not invent `saved`); `record=True`
> on an unready active document is refused before either sink (review-2 F2). `delete_study_plan(confirmed=False)`
> keeps the boolean default in the schema and lets the seam's `InvalidField` refuse an unconfirmed call — GPT: do not
> require the parameter or constrain it to literal `true`. Extend `forbid_store` with the authoring/evaluation entry
> points before `evaluate_study_plan` lands; real-seam tests compare document bytes and checkpoint rows. Fold
> `record_plan_learning`'s inline mapping into `_plan_tool_error` in the same commit, after pinning its prefixes,
> blockers and chained cause. **Inventory:** assert exactly **32** unique names and the nine design-§4 names plus
> `CORE_TOOLS` (T4.1 now says so). Apply F5's snapshot recipe to `RevisePlan.milestones`/`topics` if #12 touches
> `intents.py`.
>
> **#13b / #14 — what the purpose plumbing gives and lacks.** Present: `purpose` on the `201` body and the session
> state, `GET /api/session/state` echoing it, one resolver, the brief as its own persona section, ACP `persona_text`
> inline. Absent: the nine tool names in the persona (T4.2 — edit `agents/shared/personas/plan-architect.md`, do not
> overload `_render_planning_brief`); a "Plan with architect" control; a console label that reads `purpose`; the CLI
> `studyloop plan architect` writes no `purpose`, so a CLI-started architect reconnects labelled `focus` under
> `setdefault` — decide whether the CLI writer persists `purpose=planning` (never infer it from the topic `"Study
> plan"`). `topic` stays required: #14 sends `topic: ""` for a planning launch. Hazard: a large seed plus many plans
> makes ACP `persona_text` a first-prompt token bomb — cap or summarise `### Evidence` in #13b without changing
> `_resolve_persona`'s shape; add a test that the brief is sent once before the user's first prompt.

### Hard rules for this phase (verified on `b2f37fa4` before this brief was written)

- TDD: each stream's RED commit precedes its GREEN (§1). Protected files byte-identical: vs `3a4f6b01` —
  `test_web_plans.py`, `test_cli_plan.py`, `test_planning_evaluation.py`; vs `0a20a796` — `test_learning_decision.py`,
  `test_web_now.py`, `test_recap_mastery_voice.py`, `test_web_session_start_pty.py`, `test_web_session_start_acp.py`,
  `test_web_session_ws.py`, `test_agent_launcher.py` (all `git diff` → **0 lines**).
- Golden `tests/golden/now_plan_no_active.json` sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`
  unchanged. Guard **30 passed**. Production inventory **32 unique names** (`len(mcp._tool_manager._tools) == 32`);
  `test_mcp_stdio_smoke.py -m integration` **2 passed**; `test_mcp_plan_tools.py` + `test_plan_architect_persona.py` +
  `test_mcp_next_action.py` **137 passed** on the merged tree. The merged tree's full-suite run is the arbiter's job
  after your findings, not a claim in this brief.
- Ownership: #12 = `mcp/tools.py` (append only, plus the fold), `tests/test_mcp_plan_tools.py` (append),
  `tests/test_mcp_stdio_smoke.py`, mcp-server delta spec, `docs/agent-install.md` MCP section; #13b =
  `agents/shared/personas/plan-architect.md`, the three projections, `agents/manifest.json`, `.secrets.baseline`,
  new `tests/test_plan_architect_persona.py`, agent-adapters delta spec. `intents.py`, `_start.py`, `decision.py`
  were touched by neither (verified: not in the diffstat).
- `git diff 205819c7..b2f37fa4 -- mcp/tools.py` has **15 deleted lines**: the `PlanNotReady` import, the inline
  `except PlanNotReady` block and the inline `except PlanError` body in `record_plan_learning` (the fold), the old
  comment there, and the "Six thin adapters … land in Phase 4" section comment. Nothing else in the file moved.

## 1. Commits on the two branches (oldest last), each RED before its GREEN

```text
b2f37fa4 merge: Phase 4 — feat/p4-13b into fix/plan-integration-bugs
5fd14b6e merge: Phase 4 — feat/p4-mcp12 into fix/plan-integration-bugs
0955ac7b docs(spec): architect-persona MCP-preference requirement in agent-adapters; tick T4.2
a1772b6c docs(spec): mcp-server delta — study-plan progression and deletion tools; agent-install names the nine; tick T4.1
6ba76757 feat(persona): architect prefers the nine MCP plan tools, shells out only as a fallback (T4.2)
b1e11e78 feat(mcp): set_study_plan_milestone, evaluate_study_plan, delete_study_plan through the seam; fold record_plan_learning onto _plan_tool_error (T4.1) — GREEN
1a56b858 test(mcp): RED — three progression tools, record_plan_learning fold pin, 32-tool stdio inventory (T4.1)
60b14927 test(persona): RED — architect persona must name the nine MCP plan tools before a CLI fallback (T4.2)
```

`git diff 205819c7..b2f37fa4 --stat`:

```text
 .secrets.baseline                                  |  11 +-
 agents/claude/study-plan-architect.md              | 114 +++-
 agents/kiro/study-plan-architect/persona.md        | 114 +++-
 agents/manifest.json                               |   8 +-
 agents/opencode/study-plan-architect.md            | 114 +++-
 agents/shared/personas/plan-architect.md           | 114 +++-
 docs/agent-install.md                              |  12 +-
 .../specs/agent-adapters/spec.md                   |  44 ++
 .../plan-application-seam/specs/mcp-server/spec.md | 174 ++++-
 openspec/changes/plan-application-seam/tasks.md    |  76 ++-
 packages/studyloop/src/studyloop/mcp/tools.py      | 128 +++-
 packages/studyloop/tests/test_mcp_plan_tools.py    | 708 +++++++++++++++++++++
 packages/studyloop/tests/test_mcp_stdio_smoke.py   |  30 +-
 .../studyloop/tests/test_plan_architect_persona.py | 235 +++++++
 14 files changed, 1760 insertions(+), 122 deletions(-)
```

## 2. The two agents' own implementation reports (verbatim from `tasks.md`, T4.1–T4.2)

### (tasks.md) Phase 4 — parallel: #12 ∥ #13b

- [x] **T4.1** (#12, agent C; RED `1a56b858` 59 failed / 59 passed on `test_mcp_plan_tools.py`, stdio handshake
      "expected exactly 32 tools, got 29" → GREEN `b1e11e78`) RED: stdio inventory asserts the nine names;
      `set_study_plan_milestone` retry idempotent; `evaluate_study_plan` preview writes nothing, record reports sinks;
      `delete_study_plan` without `confirmed=True` refused. Implement three tools. DoD met:
      `test_full_handshake_list_tools_and_call` asserts exactly **32** unique names (`len(listed) == len(set)`),
      the nine design-§4 names, `record_plan_learning` and `CORE_TOOLS` over the real transport (`-m integration`
      2 passed); the in-process twin `test_production_inventory_is_thirty_two_with_the_nine_plan_tools` pins the same.
      **As landed** (`mcp/tools.py`, appended after `set_study_plan_status`): `set_study_plan_milestone(plan_id,
      index, done)` → `apply(SetMilestone)`, `done` a required boolean with no default, forwarded as given (no read,
      no toggle); `evaluate_study_plan(plan_id, phase, study_id="", record=False)` → `assess`, never `apply`, the
      `AssessmentResult` view returned with `db_write`/`document_write` as the seam reports them (a preview is
      `not_requested` on both and byte-identical document + empty `checkpoint_history`; a failed sink is
      `recording_complete: false` + the seam's warning, not a raise), `append_to_plan` not exposed;
      `delete_study_plan(plan_id, confirmed=False)` → `apply(DeletePlan)`, the boolean default kept in the schema
      (not required, no `const`/`enum`), the seam's `InvalidField` → `invalid: deleting '<id>' requires
      confirmed=True`, checkpoint history retained after a confirmed delete. **Fold:** `record_plan_learning`'s
      inline `PlanNotReady`/`PlanError` mapping replaced by `_plan_tool_error` in the same commit, after pinning
      (`test_record_plan_learning_*`: `not_ready:` prefix + blockers + pause-or-repair hint, `not_found:` /
      `invalid_id:` / `invalid:` / `conflict:` / `invalid_milestone:` / `plan_error:`, `__cause__` chained, success
      shape unchanged). This is an **intentional wording change, reported as such**: its refusals gain the kind
      prefix the other eight already carried and `docs/agent-install.md` already promised for every plan tool; the
      pre-fold tests (`test_plan_record.py::TestMcpTool`, `test_mcp_plan_record_seam.py`) match by substring and
      pass unchanged (the delta spec's `record_plan_learning` requirement text updated to the prefixed form).
      `forbid_store` extended first with `authoring.draft_plan/interview_spec/seed_from_history`,
      `evaluation.evaluate_plan/evaluate_and_record` and `index.record_checkpoint`. Delta spec: mcp-server
      requirement "Study-plan progression and deletion tools" (ten scenarios); `docs/agent-install.md` MCP list
      names the nine + `record_plan_learning`, drops "not available yet", documents the already-active hint and the
      failed-sink response. **Deviations, each reported:** (a) the `tools.py` section comment ("Six thin adapters …
      land in Phase 4") was reworded to nine — a stale comment, not code; (b) `_plan_tool_error` stays defined
      after `log_struggle` (no move — "append only"); `record_plan_learning` above it binds the closure late and
      resolves it at call time; (c) `RevisePlan.milestones`/`topics` snapshot recipe (review-3 F5 follow-on) not
      applied — `intents.py` is outside #12's file set and was not touched. **Gates at `b1e11e78`+docs:** `pytest
      packages/studyloop/tests -k "mcp or plan"` 875 passed exit 0; `pytest packages/studyloop/tests -x` **4949
      passed / 4 skipped exit 0** (6m05s); `just lint` clean; `just typecheck` 0 errors; guard
      `test_architecture_plan_seam.py` 30 passed; `test_mcp_stdio_smoke.py -m integration` 2 passed; `openspec
      validate plan-application-seam` valid (`--specs --all` 25 passed); `mkdocs build --strict` clean;
      `git diff 0a20a796 -- mcp/tools.py` → 10 deleted lines, all of them the folded inline mapping and the section
      comment. Inventory 29 → **32**.
- [x] **T4.2** (#13b, agent D; RED `60b14927` 3 failed / 6 pins passed on `205819c7`, GREEN `6ba76757`)
      `agents/shared/personas/plan-architect.md`: prefer the nine MCP tools, CLI fallback. DoD: persona test
      asserts the tool names appear in the rendered persona when `purpose=planning`.
      **As landed:** new `tests/test_plan_architect_persona.py` —
      `test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning` (renders
      `build_canonical_persona(persona_mode_for("planning"), …, brief=…)`; all nine design-§4 names; a `CLI fallback`
      section naming `studyloop plan interview|list|show|new|status|milestone|evaluate|record` and no
      `studyloop plan delete`, which does not exist), `test_plan_architect_persona_prefers_mcp_over_cli_ordering`
      (MCP subsection precedes and closes before the fallback; the nine are introduced inside it; no CLI recipe
      inside it), `test_mcp_section_states_the_lifecycle_guards` (readiness-gated activation, `confirmed=True`
      deletion, `record=False` preview vs `record=True`), `test_the_nine_are_the_registry_plus_exactly_what_12_lands`
      (the constant is grounded in `mcp._tool_manager._tools`: six registered, the unregistered set ⊆ #12's three —
      holds before and after that merge), `test_focus_persona_unchanged` (sha256 pin at `205819c7`, fixed session
      paths), `test_projected_personas_match_canonical` ×3 and
      `test_manifest_hashes_regenerate_byte_identically_for_the_architect_projections` (generator's own `hash_file`).
      Persona: one `## Tooling: prefer the plan tools, fall back to the shell` section — `### Plan tools over MCP
      (preferred)` table (nine tools in lifecycle order + `record_plan_learning`; lifecycle line; "missing from the
      inventory → that step's CLI fallback") then `### CLI fallback` table, honest that the CLI has no edit and no
      delete command; Session Start / Creating / End-of-Session protocols name the MCP call with the CLI in
      parentheses; interview text intact. Projections: `agents/claude/study-plan-architect.md`,
      `agents/opencode/study-plan-architect.md` (body after frontmatter), `agents/kiro/study-plan-architect/persona.md`
      (byte copy); `agents/manifest.json` two hashes moved (dates only where the hash moved, as `edc65322`);
      `.secrets.baseline` refreshed for those two digests. Delta spec: `agent-adapters` "Architect persona prefers
      the MCP plan tools" (4 scenarios); `openspec validate` valid. **Not changed (owner item):** Kiro's
      `study-plan-architect.json` is pinned to carry no `mcpServers` (`tools: ["@builtin"]`) and Claude's frontmatter
      lists `Read, Write, Grep, Bash` — in those two harnesses the architect takes the CLI fallback until the header
      question is decided (Phase 6 / T6.1 territory).

## 3. #12 — three progression tools, the fold, the inventory pin

### `packages/studyloop/src/studyloop/mcp/tools.py` — diff vs `205819c7`

```diff
diff --git a/packages/studyloop/src/studyloop/mcp/tools.py b/packages/studyloop/src/studyloop/mcp/tools.py
index 742e988a..1a1a8d23 100644
--- a/packages/studyloop/src/studyloop/mcp/tools.py
+++ b/packages/studyloop/src/studyloop/mcp/tools.py
@@ -151,24 +151,21 @@ def register_tools(mcp: FastMCP, *, include_exercises: bool = False) -> None:
             LearningRecordSpec,
             PlanApplication,
             PlanError,
-            PlanNotReady,
             RevisePlan,
         )

         # One RevisePlan through the seam: the store's single learning-record
         # rule and the resulting-document gate both apply, and every refusal is
-        # a domain error mapped here — a not-ready plan names its blockers so
-        # the agent can tell the learner what to fix (design §2). `created` is
-        # the mutation's own outcome, never inferred from a read taken before
-        # it (council review 2, F4).
+        # a domain error mapped by the shared `_plan_tool_error` below (T4.1
+        # fold) — a not-ready plan names its blockers, prefixed `not_ready:`
+        # like the other eight plan tools, so the agent can tell the learner
+        # what to fix (design §2). `created` is the mutation's own outcome,
+        # never inferred from a read taken before it (council review 2, F4).
         spec = LearningRecordSpec(title=title, body=body, status=status)
         try:
             detail = PlanApplication().apply(RevisePlan(plan_id=plan_id, learning_record=spec))
-        except PlanNotReady as exc:
-            blockers = "; ".join(exc.readiness.blockers)
-            raise ToolError(f"{exc}: {blockers}") from exc
         except PlanError as exc:
-            raise ToolError(str(exc)) from exc
+            raise _plan_tool_error(exc) from exc
         outcome = detail.learning_record_outcome
         if outcome is None:  # pragma: no cover - a revision carrying a record always reports one
             raise ToolError(f"learning record {spec.title!r} was not persisted on {plan_id!r}")
@@ -867,16 +864,18 @@ def register_tools(mcp: FastMCP, *, include_exercises: bool = False) -> None:
         row_id = park_topic(question, topic_tag=topic_tag, context=context, source="struggled")
         return {"status": "logged", "id": row_id}

-    # ── Study plans — discovery and authoring through the seam (D-4, D-8, D-9) ──
+    # ── Study plans — discovery, authoring and progression through the seam (D-4, D-8, D-9) ──
     #
-    # Six thin adapters over ``studyloop.planning.PlanApplication`` (design §4):
+    # Nine thin adapters over ``studyloop.planning.PlanApplication`` (design §4):
     # each call is one seam call with one intent, each success is the seam
     # view's ``to_json_dict()`` (fresh containers), and each refusal is one
     # ``ToolError`` from ``_plan_tool_error`` below. No plan policy lives here —
-    # the readiness gate, the status list, the id rules and the conflict check
-    # are the seam's, so the same refusal reads the same on the CLI, the Web
-    # and here. The three remaining tools of design §4 (milestone, evaluate,
-    # delete) land in Phase 4 (#12).
+    # the readiness gate, the status list, the id rules, the conflict check,
+    # the milestone range and the delete confirmation are the seam's, so the
+    # same refusal reads the same on the CLI, the Web and here. Six landed in
+    # Phase 3 (#11); the three progression tools (milestone, evaluate, delete)
+    # in Phase 4 (#12). ``record_plan_learning`` above maps its refusals through
+    # the same helper.

     #: ``get_study_plan``'s ``history_limit`` range — the same 1..200 the Web
     #: history route accepts (``GET /api/plans/{id}/history``, ``Query(20, ge=1,
@@ -1136,6 +1135,105 @@ def register_tools(mcp: FastMCP, *, include_exercises: bool = False) -> None:
             raise _plan_tool_error(exc) from exc
         return detail.to_json_dict()

+    @tool()
+    def set_study_plan_milestone(plan_id: str, index: int, done: bool) -> dict[str, Any]:
+        """Set one milestone's completion state — set, not toggle, so a retry is safe.
+
+        ``done`` is the state asked for: asking for the state the milestone
+        already has changes nothing and is not an error, so a retried call
+        returns the same plan. The tool reads nothing first and computes no
+        opposite. Like every write, the resulting document is readiness-gated
+        when the plan is active: an active plan that has become unready is
+        refused with ``not_ready: … — the plan is already active; pause it or
+        repair the blockers before writing`` and nothing is written.
+
+        Args:
+            plan_id: The plan id (from ``list_study_plans``).
+            index: The milestone's 0-based position, as ``get_study_plan``
+                lists it under ``milestones[].index``.
+            done: ``true`` to mark it complete, ``false`` to reopen it.
+
+        Refusals: ``not_found: …``, ``invalid_id: …``, ``invalid_milestone: …``
+        (no milestone at that index — past the end or negative),
+        ``not_ready: … : <blockers>`` (active but unready).
+        """
+        from studyloop.planning import PlanApplication, PlanError, SetMilestone
+
+        try:
+            detail = PlanApplication().apply(SetMilestone(plan_id=plan_id, index=index, done=done))
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return detail.to_json_dict()
+
+    @tool()
+    def evaluate_study_plan(
+        plan_id: str, phase: str, study_id: str = "", record: bool = False
+    ) -> dict[str, Any]:
+        """Evaluate a study plan at a session checkpoint; optionally record the checkpoint.
+
+        By default this is a **preview**: the evaluation is computed against
+        the learner's study evidence and returned, and nothing is written
+        anywhere — both ``db_write`` and ``document_write`` read
+        ``not_requested``. With ``record=true`` the checkpoint is appended to
+        the durable log in the sessions database and to the plan document's
+        own Checkpoints table; each write is reported on its own
+        (``saved`` / ``failed``), and ``recording_complete`` is ``true`` only
+        when every requested write landed. A failed write is an outcome in the
+        response with its reason in ``warnings``, never an error — the
+        evaluation itself succeeded and the agent is entitled to it. Recording
+        on an active plan that is unready is refused before either write.
+
+        ``markdown`` is the evaluation block to paste into the conversation.
+
+        Args:
+            plan_id: The plan id.
+            phase: Which session checkpoint this is — ``start``, ``mid`` or
+                ``end``.
+            study_id: Session id to attribute the checkpoint to (optional).
+            record: ``false`` (default) previews; ``true`` records to both
+                sinks.
+
+        Refusals: ``not_found: …``, ``invalid_id: …``, ``invalid: …`` (unknown
+        phase), ``not_ready: … : <blockers>`` (``record=true`` on an active
+        plan that is unready).
+        """
+        from studyloop.planning import AssessPlan, PlanApplication, PlanError
+
+        intent = AssessPlan(plan_id=plan_id, phase=phase, study_id=study_id, record=record)
+        try:
+            result = PlanApplication().assess(intent)
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return result.to_json_dict()
+
+    @tool()
+    def delete_study_plan(plan_id: str, confirmed: bool = False) -> dict[str, Any]:
+        """Delete a study plan's document. Irreversible; requires ``confirmed=true``.
+
+        Deletion is the one write that cannot be undone, so the caller has to
+        say so: without ``confirmed=true`` the call is refused with
+        ``invalid: deleting '<id>' requires confirmed=True`` and the plan is
+        untouched. Ask the learner before passing it. The plan's checkpoint
+        history in the sessions database is deliberately kept — it is evidence
+        about the learner's sessions, not about the file — and stays readable
+        there after the document is gone.
+
+        Args:
+            plan_id: The plan id.
+            confirmed: Must be ``true`` for the deletion to happen.
+
+        Returns ``{"deleted": true, "plan_id": <id>}``. Refusals:
+        ``not_found: …`` (judged before the confirmation), ``invalid_id: …``,
+        ``invalid: …`` (not confirmed).
+        """
+        from studyloop.planning import DeletePlan, PlanApplication, PlanError
+
+        try:
+            result = PlanApplication().apply(DeletePlan(plan_id=plan_id, confirmed=confirmed))
+        except PlanError as exc:
+            raise _plan_tool_error(exc) from exc
+        return result.to_json_dict()
+
     # ── Exercise sets — developer preview only ───────────────────────
     # Return after the complete production inventory has been registered.
     # This keeps exercise tools out of tools/list entirely unless the MCP
```

### `packages/studyloop/src/studyloop/mcp/tools.py` — `_plan_tool_error` as it stands at `b2f37fa4` (unchanged by #12; lines 886–926)

```python
    def _plan_tool_error(exc: PlanError) -> ToolError:
        """Map one seam refusal to a ``ToolError`` an agent can act on.

        The message is ``<kind>: <the seam's own message>``. The kind is
        machine-readable — ``not_found``, ``invalid_id``, ``conflict``,
        ``invalid``, ``not_ready``, ``invalid_milestone`` (``plan_error`` for a
        ``PlanError`` this mapping has not met) — so a client can branch on it
        without parsing prose; the rest is the domain's wording, unchanged, so
        the refusal reads as it does on the CLI and the Web (design §2). A
        not-ready refusal appends the blockers, and says "pause or repair"
        when the plan is already active, so the agent can tell the learner
        what to fix rather than that something is wrong.
        """
        from studyloop.planning import (
            InvalidField,
            InvalidMilestone,
            InvalidPlanId,
            PlanConflict,
            PlanNotFound,
            PlanNotReady,
        )

        if isinstance(exc, PlanNotReady):
            blockers = "; ".join(exc.readiness.blockers)
            hint = (
                " — the plan is already active; pause it or repair the blockers before writing"
                if exc.already_active
                else ""
            )
            return ToolError(f"not_ready: {exc}: {blockers}{hint}")
        kinds: tuple[tuple[type[Exception], str], ...] = (
            (PlanNotFound, "not_found"),
            (InvalidPlanId, "invalid_id"),
            (PlanConflict, "conflict"),
            (InvalidField, "invalid"),
            (InvalidMilestone, "invalid_milestone"),
        )
        for error_type, kind in kinds:
            if isinstance(exc, error_type):
                return ToolError(f"{kind}: {exc}")
        return ToolError(f"plan_error: {exc}")
```

### `packages/studyloop/src/studyloop/mcp/tools.py` — `record_plan_learning` after the fold (lines 130–178). Note it is defined ~750 lines *above* `_plan_tool_error`; both are closures inside `register_tools`, so the name resolves at call time (deviation b)

```python
    @tool()
    def record_plan_learning(
        plan_id: str, title: str, body: str = "", status: str = "active"
    ) -> dict[str, Any]:
        """Append a learning record to a study plan (the wind-down's first write).

        Record what was learned into the plan document BEFORE any second-brain
        projection is offered: the plan Markdown is the source of truth
        (ADR-0010), and a learning record that exists only in a second brain
        is a record the plan does not have.

        Idempotent: calling again with the same title and body changes nothing
        and reports created=false, so a retry is always safe.

        Args:
            plan_id: The study plan id (from `studyloop plan list`).
            title: What was learned, in one line.
            body: The record's body, as Markdown prose.
            status: Record status (default "active").
        """
        from studyloop.planning import (
            LearningRecordSpec,
            PlanApplication,
            PlanError,
            RevisePlan,
        )

        # One RevisePlan through the seam: the store's single learning-record
        # rule and the resulting-document gate both apply, and every refusal is
        # a domain error mapped by the shared `_plan_tool_error` below (T4.1
        # fold) — a not-ready plan names its blockers, prefixed `not_ready:`
        # like the other eight plan tools, so the agent can tell the learner
        # what to fix (design §2). `created` is the mutation's own outcome,
        # never inferred from a read taken before it (council review 2, F4).
        spec = LearningRecordSpec(title=title, body=body, status=status)
        try:
            detail = PlanApplication().apply(RevisePlan(plan_id=plan_id, learning_record=spec))
        except PlanError as exc:
            raise _plan_tool_error(exc) from exc
        outcome = detail.learning_record_outcome
        if outcome is None:  # pragma: no cover - a revision carrying a record always reports one
            raise ToolError(f"learning record {spec.title!r} was not persisted on {plan_id!r}")
        return {
            "plan_id": detail.summary.plan_id,
            "number": outcome.record.number,
            "title": outcome.record.title,
            "status": outcome.record.status,
            "created": outcome.created,
        }
```

### `packages/studyloop/tests/test_mcp_stdio_smoke.py` — diff vs `205819c7`

```diff
diff --git a/packages/studyloop/tests/test_mcp_stdio_smoke.py b/packages/studyloop/tests/test_mcp_stdio_smoke.py
index e620f63b..f6097e98 100644
--- a/packages/studyloop/tests/test_mcp_stdio_smoke.py
+++ b/packages/studyloop/tests/test_mcp_stdio_smoke.py
@@ -25,6 +25,26 @@ pytestmark = pytest.mark.integration

 CORE_TOOLS = {"list_courses", "get_study_backlog", "end_session"}

+#: The nine study-plan tools of design §4 (D-8/D-9): six from #11, three from #12.
+PLAN_TOOLS = {
+    "list_study_plans",
+    "get_study_plan",
+    "get_planning_interview",
+    "create_study_plan",
+    "update_study_plan",
+    "set_study_plan_status",
+    "set_study_plan_milestone",
+    "evaluate_study_plan",
+    "delete_study_plan",
+}
+
+#: The exact production inventory: 23 at ``0a20a796`` plus the nine plan tools
+#: less ``record_plan_learning``, which was already among the 23 (council
+#: review 3, F13 — the design's "26 → 35" was arithmetic on a stale count).
+#: Exact, not a lower bound: an accidental registration is a failure here, and
+#: the name assertions stop an unrelated addition masking a missing tool.
+PRODUCTION_TOOL_COUNT = 32
+

 @pytest.fixture
 def isolated_config(tmp_path):
@@ -52,9 +72,15 @@ async def test_full_handshake_list_tools_and_call(isolated_config):
         assert init_result.serverInfo.name == "studyloop"

         tools_result = await session.list_tools()
-        names = {t.name for t in tools_result.tools}
-        assert len(names) >= 21, f"expected >=21 tools, got {len(names)}: {names}"
+        listed = [t.name for t in tools_result.tools]
+        names = set(listed)
+        assert len(listed) == len(names), f"duplicate tool names advertised: {sorted(listed)}"
+        assert len(names) == PRODUCTION_TOOL_COUNT, (
+            f"expected exactly {PRODUCTION_TOOL_COUNT} tools, got {len(names)}: {sorted(names)}"
+        )
         assert names >= CORE_TOOLS, f"missing core tools: {CORE_TOOLS - names}"
+        assert names >= PLAN_TOOLS, f"missing plan tools: {PLAN_TOOLS - names}"
+        assert "record_plan_learning" in names

         call_result = await session.call_tool("list_courses", {})
         assert not call_result.isError
```

### `packages/studyloop/tests/test_mcp_plan_tools.py` — the appended Phase-4 part, diff vs `205819c7` (the Phase-3 body — fixtures `_registry`, `_schema`, `_tool`, `_ready_plan`, `_not_ready`, `_fake`/`_Spy`, `isolated_plans` autouse, the original `forbid_store` — is unchanged and was reviewed in review 3)

```diff
diff --git a/packages/studyloop/tests/test_mcp_plan_tools.py b/packages/studyloop/tests/test_mcp_plan_tools.py
index 437c2166..2e46fafe 100644
--- a/packages/studyloop/tests/test_mcp_plan_tools.py
+++ b/packages/studyloop/tests/test_mcp_plan_tools.py
@@ -20,6 +20,18 @@ validation").
 Delegation tests replace the seam's methods and forbid the store, so they
 prove the adapter reaches nothing but ``PlanApplication``. The journey tests
 at the end run the real seam on an isolated plans directory and database.
+
+Phase 4 (#12, T4.1) appends the three progression tools of design §4 rows 7-9
+— ``set_study_plan_milestone`` (an explicit boolean, set not toggle, so a
+retry is safe), ``evaluate_study_plan`` (``record=False`` by default: a
+preview writes to *neither* sink; ``record=True`` reports each sink as the
+seam does, never flattened to a boolean) and ``delete_study_plan`` (refused
+by the seam unless ``confirmed=True``; the checkpoint log survives) — and
+pins that ``record_plan_learning``'s refusals go through the same
+``_plan_tool_error`` mapping as the other eight (review-3 arbitration,
+Phase-4 hazards). ``forbid_store`` also forbids the authoring and evaluation
+entry points, so an evaluate adapter that reached the checkpoint writer
+directly would fail here rather than quietly writing.
 """

 from __future__ import annotations
@@ -33,7 +45,11 @@ pytest.importorskip("mcp")
 from mcp.server.fastmcp.exceptions import ToolError

 from studyloop.planning import (
+    AssessmentResult,
+    AssessPlan,
     CreatePlan,
+    DeletePlan,
+    DeleteResult,
     InvalidField,
     InvalidMilestone,
     InvalidPlanId,
@@ -43,16 +59,20 @@ from studyloop.planning import (
     PlanConflict,
     PlanDetail,
     PlanError,
+    PlanEvaluationView,
     PlanningBrief,
     PlanNotFound,
     PlanNotReady,
     PlanSummary,
     ReadinessView,
     RevisePlan,
+    SetMilestone,
     StudyPlan,
     TransitionLifecycle,
     store,
 )
+from studyloop.planning import authoring as plan_authoring
+from studyloop.planning import evaluation as plan_evaluation
 from studyloop.planning import index as plan_index

 SIX_TOOLS = (
@@ -64,6 +84,23 @@ SIX_TOOLS = (
     "set_study_plan_status",
 )

+#: Design §4 rows 7-9, registered by #12 (T4.1).
+PHASE_FOUR_TOOLS = (
+    "set_study_plan_milestone",
+    "evaluate_study_plan",
+    "delete_study_plan",
+)
+
+NINE_TOOLS: tuple[str, ...] = SIX_TOOLS + PHASE_FOUR_TOOLS
+
+#: 23 at ``0a20a796`` + the nine plan tools less ``record_plan_learning``, which
+#: is already among the 23 (council review 3, F13 — the design's "35" was
+#: arithmetic on a stale inventory).
+PRODUCTION_TOOL_COUNT = 32
+
+DB_WARNING = "checkpoint not saved to the database"
+DOCUMENT_WARNING = "checkpoint not appended to the plan document"
+

 # ---------------------------------------------------------------------------
 # Fixtures
@@ -109,6 +146,14 @@ def forbid_store(monkeypatch):
     ):
         monkeypatch.setattr(store, name, _reached(f"store.{name}"))
     monkeypatch.setattr(plan_index, "checkpoint_history", _reached("index.checkpoint_history"))
+    # T4.1: the authoring and evaluation entry points too, so an evaluate or
+    # create adapter that reached the drafting or checkpoint code directly —
+    # instead of through ``assess`` / ``apply`` — fails the same way.
+    monkeypatch.setattr(plan_index, "record_checkpoint", _reached("index.record_checkpoint"))
+    for name in ("evaluate_plan", "evaluate_and_record"):
+        monkeypatch.setattr(plan_evaluation, name, _reached(f"evaluation.{name}"))
+    for name in ("draft_plan", "interview_spec", "seed_from_history"):
+        monkeypatch.setattr(plan_authoring, name, _reached(f"authoring.{name}"))


 # ---------------------------------------------------------------------------
@@ -191,6 +236,82 @@ def _fake(monkeypatch, method: str, result: object) -> _Spy:
     return spy


+def _evaluation_view(
+    plan_id: str = "decorators", phase: str = "mid", warnings: tuple[str, ...] = ()
+) -> PlanEvaluationView:
+    """A canned evaluation for the delegation tests (no history read behind it)."""
+    return PlanEvaluationView(
+        plan_id=plan_id,
+        plan_title="Python Decorators",
+        phase=phase,
+        verdict="on-track",
+        headline="On track.",
+        at="2026-09-16T10:00:00+00:00",
+        study_id="",
+        progress_pct=0,
+        milestone_total=1,
+        milestone_done=0,
+        next_milestone="Trace a decorated call",
+        next_concepts=("wrapper",),
+        days_since_activity=None,
+        days_until_target=None,
+        due_reviews=(),
+        struggles=(),
+        concept_evidence=(),
+        unverified_milestones=(),
+        drift_topics=(),
+        recommendations=(),
+        warnings=warnings,
+        markdown="## Checkpoint\n\nOn track.\n",
+    )
+
+
+def _assessment(
+    db_write: str = "not_requested",
+    document_write: str = "not_requested",
+    warnings: tuple[str, ...] = (),
+) -> AssessmentResult:
+    return AssessmentResult(
+        evaluation=_evaluation_view(warnings=warnings),
+        db_write=db_write,  # type: ignore[arg-type]
+        document_write=document_write,  # type: ignore[arg-type]
+        warnings=warnings,
+    )
+
+
+def _legacy_active_husk(plan_id: str = "husk") -> StudyPlan:
+    """An active document with a milestone but no mission — written straight
+    through the store, as a hand-edited or pre-gate plan would be. The seam
+    refuses every write to it until it is paused or repaired (deviation 12)."""
+    plan = StudyPlan(
+        plan_id=plan_id, title="Husk", status="active", milestones=[Milestone(title="Only one")]
+    )
+    store.create_plan(plan)
+    return plan
+
+
+def _ready_plan_on_disk(plan_id: str = "decorators") -> str:
+    """Create a ready draft through the tools themselves and return its id."""
+    _tool("create_study_plan")(
+        "Python Decorators",
+        {"why": "They keep appearing in code review.", "success": ["Explain them."]},
+        plan_id=plan_id,
+    )
+    _tool("update_study_plan")(
+        plan_id,
+        topics=["python"],
+        milestones=[
+            {"title": "Trace a decorated call", "concepts": ["wrapper"]},
+            {"title": "Write one", "concepts": ["closure"]},
+        ],
+    )
+    return plan_id
+
+
+def _database_checkpoints(plan_id: str) -> list[str]:
+    return [str(row["phase"]) for row in plan_index.checkpoint_history(plan_id)]
+
+
 # ---------------------------------------------------------------------------
 # Registration and schemas
 # ---------------------------------------------------------------------------
@@ -716,3 +837,590 @@ def test_get_study_plan_history_reads_the_isolated_log() -> None:

     assert payload["history"] == []
     assert "markdown" not in payload
+
+
+# ===========================================================================
+# Phase 4 (#12, T4.1): the three progression tools of design §4 rows 7-9
+# ===========================================================================
+
+# ---------------------------------------------------------------------------
+# Registration, schemas and the production inventory
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.parametrize("name", PHASE_FOUR_TOOLS)
+def test_phase_four_tool_is_registered_with_a_schema(name: str) -> None:
+    schema = _schema(name)
+    assert schema["type"] == "object"
+    assert "properties" in schema
+
+
+def test_phase_four_schemas_carry_the_design_signatures() -> None:
+    """Design §4 rows 7-9: names, required arguments and defaults.
+
+    ``done`` is an explicit boolean with no default (set, not toggle);
+    ``record`` defaults to ``False`` (a preview); ``confirmed`` defaults to
+    ``False`` and stays an ordinary boolean — the seam refuses an unconfirmed
+    delete, the schema does not require the parameter or constrain it to a
+    literal ``true`` (review-3 arbitration, Phase-4 hazards).
+    """
+    milestone = _schema("set_study_plan_milestone")
+    assert set(milestone["properties"]) == {"plan_id", "index", "done"}
+    assert set(milestone["required"]) == {"plan_id", "index", "done"}
+    assert milestone["properties"]["done"]["type"] == "boolean"
+    assert "default" not in milestone["properties"]["done"]
+    assert milestone["properties"]["index"]["type"] == "integer"
+
+    evaluate = _schema("evaluate_study_plan")
+    assert set(evaluate["properties"]) == {"plan_id", "phase", "study_id", "record"}
+    assert set(evaluate["required"]) == {"plan_id", "phase"}
+    assert evaluate["properties"]["study_id"]["default"] == ""
+    assert evaluate["properties"]["record"]["default"] is False
+    assert evaluate["properties"]["record"]["type"] == "boolean"
+    assert "append_to_plan" not in evaluate["properties"], "design §4 exposes four arguments"
+
+    delete = _schema("delete_study_plan")
+    assert set(delete["properties"]) == {"plan_id", "confirmed"}
+    assert delete["required"] == ["plan_id"]
+    confirmed = delete["properties"]["confirmed"]
+    assert confirmed["default"] is False
+    assert confirmed["type"] == "boolean"
+    assert "const" not in confirmed and "enum" not in confirmed
+
+
+def test_production_inventory_is_thirty_two_with_the_nine_plan_tools() -> None:
+    """The in-process twin of the stdio pin (T4.1): exactly 32 unique names,
+    all nine design-§4 plan tools, ``record_plan_learning`` still among them."""
+    names = set(_registry())
+    assert len(_registry()) == PRODUCTION_TOOL_COUNT, sorted(names)
+    assert names >= set(NINE_TOOLS), set(NINE_TOOLS) - names
+    assert "record_plan_learning" in names
+
+
+# ---------------------------------------------------------------------------
+# Delegation: milestone → apply(SetMilestone); evaluate → assess; delete → apply(DeletePlan)
+# ---------------------------------------------------------------------------
+
+
+def test_set_study_plan_milestone_applies_one_set_milestone(monkeypatch, forbid_store) -> None:
+    detail = PlanDetail.from_plan(_ready_plan())
+    apply = _fake(monkeypatch, "apply", detail)
+
+    payload = _tool("set_study_plan_milestone")("decorators", 0, True)
+
+    assert apply.calls == [((SetMilestone(plan_id="decorators", index=0, done=True),), {})]
+    assert payload == detail.to_json_dict()
+
+
+def test_set_study_plan_milestone_forwards_done_false_as_a_set_not_a_toggle(
+    monkeypatch, forbid_store
+) -> None:
+    """``done`` is the state asked for, forwarded as given: the adapter reads
+    nothing first and computes no opposite (the CLI's toggle is the CLI's)."""
+    inspect = _fake(monkeypatch, "inspect", PlanDetail.from_plan(_ready_plan()))
+    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))
+
+    _tool("set_study_plan_milestone")("decorators", 0, False)
+
+    assert apply.calls == [((SetMilestone(plan_id="decorators", index=0, done=False),), {})]
+    assert inspect.calls == []
+
+
+def test_set_study_plan_milestone_retry_is_idempotent(monkeypatch, forbid_store) -> None:
+    """A retried set is the same intent again, the same view back, no error
+    — the second identical call is indistinguishable from the first."""
+    detail = PlanDetail.from_plan(_ready_plan())
+    apply = _fake(monkeypatch, "apply", detail)
+
+    first = _tool("set_study_plan_milestone")("decorators", 0, True)
+    second = _tool("set_study_plan_milestone")("decorators", 0, True)
+
+    assert first == second == detail.to_json_dict()
+    assert first is not second, "fresh containers on every call"
+    assert apply.calls == [
+        ((SetMilestone(plan_id="decorators", index=0, done=True),), {}),
+        ((SetMilestone(plan_id="decorators", index=0, done=True),), {}),
+    ]
+
+
+def test_evaluate_study_plan_calls_assess_never_apply(monkeypatch, forbid_store) -> None:
+    """``AssessPlan`` is not a ``PlanIntent``: the adapter goes to ``assess``
+    and the response is the ``AssessmentResult`` view — sinks as the seam
+    reports them, not flattened to booleans (review-3 arbitration)."""
+    result = _assessment()
+    assess = _fake(monkeypatch, "assess", result)
+    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))
+
+    payload = _tool("evaluate_study_plan")("decorators", "mid")
+
+    assert assess.calls == [
+        ((AssessPlan(plan_id="decorators", phase="mid", study_id="", record=False),), {})
+    ]
+    assert apply.calls == []
+    assert payload == result.to_json_dict()
+    assert set(payload) == {
+        "evaluation",
+        "markdown",
+        "db_write",
+        "document_write",
+        "recording_complete",
+        "warnings",
+    }
+    assert payload["db_write"] == payload["document_write"] == "not_requested"
+    assert payload["recording_complete"] is True
+    assert payload["evaluation"]["phase"] == "mid"
+    assert payload["markdown"].startswith("## Checkpoint")
+
+
+def test_evaluate_study_plan_default_is_a_preview(monkeypatch, forbid_store) -> None:
+    assess = _fake(monkeypatch, "assess", _assessment())
+
+    _tool("evaluate_study_plan")("decorators", "start")
+
+    ((intent,), _kwargs) = assess.calls[0]
+    assert isinstance(intent, AssessPlan)
+    assert intent.record is False, "design §4: evaluate defaults to record=False"
+    assert intent.study_id == ""
+    assert intent.append_to_plan is True, "the seam's default; the tool does not expose it"
+
+
+def test_evaluate_study_plan_record_true_and_study_id_are_forwarded(
+    monkeypatch, forbid_store
+) -> None:
+    result = _assessment(db_write="saved", document_write="saved")
+    assess = _fake(monkeypatch, "assess", result)
+
+    payload = _tool("evaluate_study_plan")("decorators", "end", study_id="sess-9", record=True)
+
+    assert assess.calls == [
+        ((AssessPlan(plan_id="decorators", phase="end", study_id="sess-9", record=True),), {})
+    ]
+    assert payload["db_write"] == "saved"
+    assert payload["document_write"] == "saved"
+    assert payload["recording_complete"] is True
+
+
+def test_evaluate_study_plan_partial_failure_is_reported_not_raised(
+    monkeypatch, forbid_store
+) -> None:
+    """A failed sink is an outcome on the result, never an exception, and the
+    warnings carry the seam's own strings — so the agent reads
+    ``recording_complete: false`` and the reason, not a success."""
+    result = _assessment(db_write="failed", document_write="saved", warnings=(DB_WARNING,))
+    _fake(monkeypatch, "assess", result)
+
+    payload = _tool("evaluate_study_plan")("decorators", "start", record=True)
+
+    assert payload["db_write"] == "failed"
+    assert payload["document_write"] == "saved"
+    assert payload["recording_complete"] is False
+    assert DB_WARNING in payload["warnings"]
+
+
+def test_delete_study_plan_applies_one_delete_plan_with_confirmed_forwarded(
+    monkeypatch, forbid_store
+) -> None:
+    result = DeleteResult(plan_id="decorators")
+    apply = _fake(monkeypatch, "apply", result)
+
+    payload = _tool("delete_study_plan")("decorators", confirmed=True)
+
+    assert apply.calls == [((DeletePlan(plan_id="decorators", confirmed=True),), {})]
+    assert payload == result.to_json_dict() == {"deleted": True, "plan_id": "decorators"}
+
+
+def test_delete_study_plan_default_is_unconfirmed_and_left_to_the_seam(
+    monkeypatch, forbid_store
+) -> None:
+    """The adapter carries no confirmation policy of its own: ``confirmed``
+    defaults to ``False`` and reaches the seam as ``False``; the seam's
+    ``InvalidField`` is what the agent reads, prefixed ``invalid:``."""
+    refusal = InvalidField("deleting 'decorators' requires confirmed=True")
+    apply = _fake(monkeypatch, "apply", refusal)
+
+    with pytest.raises(
+        ToolError, match=r"^invalid: deleting 'decorators' requires confirmed=True$"
+    ):
+        _tool("delete_study_plan")("decorators")
+
+    assert apply.calls == [((DeletePlan(plan_id="decorators", confirmed=False),), {})]
+
+
+@pytest.mark.parametrize(
+    ("name", "args"),
+    [
+        ("set_study_plan_milestone", ("decorators", 0, True)),
+        ("evaluate_study_plan", ("decorators", "mid")),
+        ("delete_study_plan", ("decorators", True)),
+    ],
+)
+def test_phase_four_responses_are_fresh_containers(
+    monkeypatch, forbid_store, name: str, args
+) -> None:
+    _fake(monkeypatch, "assess", _assessment())
+    _fake(
+        monkeypatch,
+        "apply",
+        PlanDetail.from_plan(_ready_plan()) if name != "delete_study_plan" else DeleteResult("x"),
+    )
+
+    first = _tool(name)(*args)
+    pristine = _tool(name)(*args)
+    first.clear()
+    first["tampered"] = True
+
+    second = _tool(name)(*args)
+    assert second == pristine
+    assert second is not first
+
+
+# ---------------------------------------------------------------------------
+# Error mapping for the three: the same ``_plan_tool_error``, unchanged
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.parametrize(
+    ("error", "prefix"),
+    [
+        (PlanNotFound("no study plan with id 'ghost'"), "not_found"),
+        (InvalidPlanId("invalid plan id '../x'"), "invalid_id"),
+        (PlanConflict("study plan 'x' already exists"), "conflict"),
+        (InvalidField("phase must be one of ('start', 'mid', 'end')"), "invalid"),
+        (InvalidMilestone("No milestone at index 9 (plan has 1)"), "invalid_milestone"),
+        (PlanError("something the mapping has not met"), "plan_error"),
+    ],
+    ids=["not_found", "invalid_id", "conflict", "invalid", "invalid_milestone", "fallback"],
+)
+@pytest.mark.parametrize(
+    ("name", "method", "args"),
+    [
+        ("set_study_plan_milestone", "apply", ("ghost", 0, True)),
+        ("evaluate_study_plan", "assess", ("ghost", "start")),
+        ("delete_study_plan", "apply", ("ghost", True)),
+    ],
+)
+def test_every_phase_four_refusal_maps_to_one_prefixed_tool_error(
+    monkeypatch, forbid_store, error: PlanError, prefix: str, name: str, method: str, args
+) -> None:
+    _fake(monkeypatch, method, error)
+
+    with pytest.raises(ToolError) as caught:
+        _tool(name)(*args)
+
+    assert str(caught.value) == f"{prefix}: {error}"
+    assert caught.value.__cause__ is error
+
+
+@pytest.mark.parametrize(
+    ("name", "method", "args"),
+    [
+        ("set_study_plan_milestone", "apply", ("husk", 0, True)),
+        ("evaluate_study_plan", "assess", ("husk", "start", "", True)),
+    ],
+)
+def test_phase_four_not_ready_on_an_active_plan_says_pause_or_repair(
+    monkeypatch, forbid_store, name: str, method: str, args
+) -> None:
+    """The twin of F1's engine test: a milestone set — or a recorded checkpoint
+    — on an active-but-unready document is refused naming the blockers and
+    telling the agent to pause or repair, not to "activate"."""
+    error = _not_ready(already_active=True)
+    _fake(monkeypatch, method, error)
+
+    with pytest.raises(ToolError, match=r"^not_ready: plan is not ready to activate: ") as caught:
+        _tool(name)(*args)
+
+    message = str(caught.value)
+    for blocker in error.readiness.blockers:
+        assert blocker in message
+    assert "already active" in message
+    assert "pause it or repair" in message
+    assert caught.value.__cause__ is error
+
+
+# ---------------------------------------------------------------------------
+# ``record_plan_learning`` goes through the shared mapping (the T4.1 fold)
+# ---------------------------------------------------------------------------
+
+
+def test_record_plan_learning_not_ready_refusal_is_prefixed_with_blockers_and_cause(
+    monkeypatch, forbid_store
+) -> None:
+    """Pinned before the fold: the same ``not_ready:`` prefix, the blockers,
+    and the domain error chained — what the other eight tools already do."""
+    error = _not_ready()
+    _fake(monkeypatch, "apply", error)
+
+    with pytest.raises(ToolError) as caught:
+        _tool("record_plan_learning")("husk", "Insight")
+
+    message = str(caught.value)
+    assert message.startswith("not_ready: plan is not ready to activate: ")
+    for blocker in error.readiness.blockers:
+        assert blocker in message
+    assert "already active" not in message
+    assert caught.value.__cause__ is error
+
+
+def test_record_plan_learning_on_an_active_husk_says_pause_or_repair(
+    monkeypatch, forbid_store
+) -> None:
+    error = _not_ready(already_active=True)
+    _fake(monkeypatch, "apply", error)
+
+    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause it or repair"):
+        _tool("record_plan_learning")("husk", "Insight")
+
+
+@pytest.mark.parametrize(
+    ("error", "prefix"),
+    [
+        (PlanNotFound("no study plan with id 'ghost'"), "not_found"),
+        (InvalidPlanId("invalid plan id '../x'"), "invalid_id"),
+        (InvalidField("learning record title is required"), "invalid"),
+        (PlanConflict("study plan 'x' already exists"), "conflict"),
+        (InvalidMilestone("No milestone at index 9 (plan has 1)"), "invalid_milestone"),
+        (PlanError("something the mapping has not met"), "plan_error"),
+    ],
+    ids=["not_found", "invalid_id", "invalid", "conflict", "invalid_milestone", "fallback"],
+)
+def test_record_plan_learning_refusals_go_through_the_shared_mapping(
+    monkeypatch, forbid_store, error: PlanError, prefix: str
+) -> None:
+    _fake(monkeypatch, "apply", error)
+
+    with pytest.raises(ToolError) as caught:
+        _tool("record_plan_learning")("ghost", "Insight")
+
+    assert str(caught.value) == f"{prefix}: {error}"
+    assert caught.value.__cause__ is error
+
+
+def test_record_plan_learning_success_shape_is_unchanged_by_the_fold() -> None:
+    """The response keys and ``created`` semantics ``test_plan_record.py`` and
+    ``test_mcp_plan_record_seam.py`` pin still hold on the real seam."""
+    plan_id = _ready_plan_on_disk()
+    _tool("set_study_plan_status")(plan_id, "active")
+
+    first = _tool("record_plan_learning")(plan_id, "MCP insight", body="prose")
+    second = _tool("record_plan_learning")(plan_id, "MCP insight", body="prose")
+
+    assert first == {
+        "plan_id": plan_id,
+        "number": 1,
+        "title": "MCP insight",
+        "status": "active",
+        "created": True,
+    }
+    assert second == {**first, "created": False}
+    assert len(store.load_plan(plan_id).learning_records) == 1
+
+
+def test_record_plan_learning_on_a_real_active_husk_is_refused_and_writes_nothing() -> None:
+    _legacy_active_husk()
+    before = store.load_plan_text("husk")
+
+    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause it or repair"):
+        _tool("record_plan_learning")("husk", "Insight")
+
+    assert store.load_plan_text("husk") == before
+    assert store.load_plan("husk").learning_records == []
+
+
+# ---------------------------------------------------------------------------
+# The real seam: milestone set, evaluate preview/record, confirmed delete
+# ---------------------------------------------------------------------------
+
+
+def test_set_milestone_journey_second_identical_call_is_a_no_op() -> None:
+    """mcp-server delta, "Study-plan progression and deletion tools", scenario 1:
+    set, not toggle — the retry returns the same view and rewrites nothing."""
+    plan_id = _ready_plan_on_disk()
+
+    first = _tool("set_study_plan_milestone")(plan_id, 0, True)
+    assert first["milestones"][0]["done"] is True
+    assert first["milestones"][1]["done"] is False
+    assert first["plan"]["milestone_done"] == 1
+    assert first["plan"]["milestone_total"] == 2
+    assert store.load_plan(plan_id).milestones[0].done is True
+    after_first = store.load_plan_text(plan_id)
+
+    second = _tool("set_study_plan_milestone")(plan_id, 0, True)
+
+    assert second == first, "the same intent twice returns the same plan"
+    assert store.load_plan_text(plan_id) == after_first, "a retry writes nothing"
+
+    reverted = _tool("set_study_plan_milestone")(plan_id, 0, False)
+    assert reverted["milestones"][0]["done"] is False
+    assert reverted["plan"]["milestone_done"] == 0
+    assert store.load_plan(plan_id).milestones[0].done is False
+
+
+@pytest.mark.parametrize("index", [2, 9, -1], ids=["past-the-end", "far", "negative"])
+def test_set_milestone_outside_the_plan_is_invalid_milestone_and_writes_nothing(
+    index: int,
+) -> None:
+    plan_id = _ready_plan_on_disk()
+    before = store.load_plan_text(plan_id)
+
+    with pytest.raises(ToolError, match=r"^invalid_milestone: No milestone at index ") as caught:
+        _tool("set_study_plan_milestone")(plan_id, index, True)
+
+    assert str(index) in str(caught.value)
+    assert store.load_plan_text(plan_id) == before
+
+
+def test_set_milestone_on_a_real_active_husk_is_refused_and_writes_nothing() -> None:
+    """Scenario 2: the seam's gate, not the adapter's — an active document
+    that is unready is refused with the blockers and "pause it or repair",
+    and its bytes are untouched."""
+    _legacy_active_husk()
+    before = store.load_plan_text("husk")
+
+    with pytest.raises(ToolError) as caught:
+        _tool("set_study_plan_milestone")("husk", 0, True)
+
+    message = str(caught.value)
+    assert message.startswith("not_ready: plan is not ready to activate: ")
+    assert "already active" in message
+    assert "pause it or repair" in message
+    assert store.load_plan_text("husk") == before
+    assert store.load_plan("husk").milestones[0].done is False
+
+
+def test_evaluate_preview_writes_neither_sink() -> None:
+    """Scenario 3: ``record=False`` (the default) computes the evaluation and
+    touches nothing — the document is byte-identical and the checkpoint log
+    is empty; the response says so with ``not_requested`` on both sinks."""
+    plan_id = _ready_plan_on_disk()
+    _tool("set_study_plan_status")(plan_id, "active")
+    before = store.load_plan_text(plan_id)
+
+    payload = _tool("evaluate_study_plan")(plan_id, "mid")
+
+    assert payload["db_write"] == "not_requested"
+    assert payload["document_write"] == "not_requested"
+    assert payload["recording_complete"] is True
+    assert payload["evaluation"]["plan_id"] == plan_id
+    assert payload["evaluation"]["phase"] == "mid"
+    assert payload["evaluation"]["verdict"] in {"on-track", "at-risk", "stalled", "complete"}
+    assert payload["markdown"], "the block an agent pastes into the conversation"
+    assert DB_WARNING not in payload["warnings"]
+    assert DOCUMENT_WARNING not in payload["warnings"]
+    assert store.load_plan_text(plan_id) == before
+    assert _database_checkpoints(plan_id) == []
+    assert _tool("get_study_plan")(plan_id, include_history=True)["history"] == []
+    assert _tool("get_study_plan")(plan_id)["checkpoints"] == []
+
+
+def test_evaluate_record_true_reports_both_sinks_and_the_log_grows() -> None:
+    """Scenario 4: ``record=True`` writes the durable log and the document's
+    Checkpoints table, and reports each as ``saved``."""
+    plan_id = _ready_plan_on_disk()
+    _tool("set_study_plan_status")(plan_id, "active")
+
+    payload = _tool("evaluate_study_plan")(plan_id, "end", study_id="sess-9", record=True)
+
+    assert payload["db_write"] == "saved"
+    assert payload["document_write"] == "saved"
+    assert payload["recording_complete"] is True
+    assert payload["evaluation"]["study_id"] == "sess-9"
+    assert _database_checkpoints(plan_id) == ["end"]
+    history = _tool("get_study_plan")(plan_id, include_history=True)["history"]
+    assert [row["phase"] for row in history] == ["end"]
+    assert history[0]["study_id"] == "sess-9"
+    assert [c["phase"] for c in _tool("get_study_plan")(plan_id)["checkpoints"]] == ["end"]
+
+
+def test_evaluate_partial_failure_surfaces_as_warnings_on_the_real_seam(monkeypatch) -> None:
+    """Scenario 5: the database sink fails, the document sink lands; the tool
+    returns (no error) with ``db_write: failed``, ``recording_complete: false``
+    and the seam's warning — never a bare success."""
+    plan_id = _ready_plan_on_disk()
+    monkeypatch.setattr(plan_index, "record_checkpoint", lambda evaluation, *, study_id="": False)
+
+    payload = _tool("evaluate_study_plan")(plan_id, "start", record=True)
+
+    assert payload["db_write"] == "failed"
+    assert payload["document_write"] == "saved"
+    assert payload["recording_complete"] is False
+    assert DB_WARNING in payload["warnings"]
+    assert DB_WARNING in payload["evaluation"]["warnings"]
+    assert _database_checkpoints(plan_id) == []
+    assert [c["phase"] for c in _tool("get_study_plan")(plan_id)["checkpoints"]] == ["start"]
+
+
+def test_evaluate_record_on_a_real_active_husk_is_refused_before_either_sink() -> None:
+    """Review-2 F2: appending the checkpoint re-saves the document, so an
+    active-but-unready plan is refused before the log or the file is touched.
+    The preview of the same plan is not gated — it persists nothing."""
+    _legacy_active_husk()
+    before = store.load_plan_text("husk")
+
+    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause it or repair"):
+        _tool("evaluate_study_plan")("husk", "start", record=True)
+
+    assert store.load_plan_text("husk") == before
+    assert _database_checkpoints("husk") == []
+
+    preview = _tool("evaluate_study_plan")("husk", "start")
+    assert preview["db_write"] == preview["document_write"] == "not_requested"
+    assert store.load_plan_text("husk") == before
+
+
+def test_evaluate_unknown_phase_is_the_seams_invalid_refusal() -> None:
+    plan_id = _ready_plan_on_disk()
+
+    with pytest.raises(ToolError, match=r"^invalid: phase must be one of"):
+        _tool("evaluate_study_plan")(plan_id, "halfway", record=True)
+
+    assert _database_checkpoints(plan_id) == []
+    # 404 before 400: the plan is judged before the phase.
+    with pytest.raises(ToolError, match=r"^not_found: "):
+        _tool("evaluate_study_plan")("ghost", "halfway")
+
+
+def test_delete_without_confirmation_is_refused_and_the_plan_still_exists() -> None:
+    """Scenario 6: ``confirmed`` defaults to ``False``; the seam refuses with
+    ``invalid:`` naming the flag, and the document is untouched."""
+    plan_id = _ready_plan_on_disk()
+    before = store.load_plan_text(plan_id)
+
+    with pytest.raises(ToolError, match=r"^invalid: .*requires confirmed=True") as caught:
+        _tool("delete_study_plan")(plan_id)
+    with pytest.raises(ToolError, match=r"^invalid: .*requires confirmed=True"):
+        _tool("delete_study_plan")(plan_id, confirmed=False)
+
+    assert plan_id in str(caught.value)
+    assert store.plan_path(plan_id).exists()
+    assert store.load_plan_text(plan_id) == before
+    assert _tool("list_study_plans")()["count"] == 1
+
+
+def test_delete_confirmed_returns_delete_result_and_keeps_the_checkpoint_history() -> None:
+    """Scenario 7: a confirmed delete removes the document and its index row;
+    the durable checkpoint log is evidence about the learner and survives."""
+    plan_id = _ready_plan_on_disk()
+    _tool("set_study_plan_status")(plan_id, "active")
+    _tool("evaluate_study_plan")(plan_id, "start", study_id="sess-1", record=True)
+    assert _database_checkpoints(plan_id) == ["start"]
+
+    payload = _tool("delete_study_plan")(plan_id, confirmed=True)
+
+    assert payload == {"deleted": True, "plan_id": plan_id}
+    assert not store.plan_path(plan_id).exists()
+    assert _tool("list_study_plans")() == {"plans": [], "count": 0}
+    with pytest.raises(ToolError, match=r"^not_found: "):
+        _tool("get_study_plan")(plan_id)
+    history = plan_index.checkpoint_history(plan_id)
+    assert [row["phase"] for row in history] == ["start"], "the durable log survives deletion"
+    assert history[0]["study_id"] == "sess-1"
+
+
+def test_delete_missing_plan_is_not_found_before_confirmation_is_judged() -> None:
+    with pytest.raises(ToolError, match=r"^not_found: "):
+        _tool("delete_study_plan")("ghost")
+    with pytest.raises(ToolError, match=r"^not_found: "):
+        _tool("delete_study_plan")("ghost", confirmed=True)
+    with pytest.raises(ToolError, match=r"^invalid_id: "):
+        _tool("delete_study_plan")("../escape", confirmed=True)
```

## 4. #13b — the architect persona prefers the MCP tools

### `agents/shared/personas/plan-architect.md` — diff vs `205819c7`

```diff
diff --git a/agents/shared/personas/plan-architect.md b/agents/shared/personas/plan-architect.md
index db554f0a..8f416c4b 100644
--- a/agents/shared/personas/plan-architect.md
+++ b/agents/shared/personas/plan-architect.md
@@ -40,24 +40,81 @@ park it.
 ## Core Behaviour

 - One question per turn. Stop. Wait. (Same rule as any Socratic turn.)
-- Open from evidence, not a blank page — run `studyloop plan interview --json`
-  and lead with what their own history already shows.
+- Open from evidence, not a blank page — fetch the interview and its evidence
+  seed (`get_planning_interview`) and lead with what their own history already
+  shows.
 - Read `readiness` back to the learner instead of quietly accepting a weak plan.
 - Push back on vague answers. "Get better at SQL" is a topic, not a mission.
 - Keep plans small: 3-6 milestones, each one session's work.
 - Finish in under 10 minutes. A long planning session is a failure mode.
 - Never tick a milestone the learner has not demonstrated.

+## Tooling: prefer the plan tools, fall back to the shell
+
+Every surface — the MCP tools, `studyloop plan`, the Web UI — goes through the
+same plan application layer, so the readiness gate, the lifecycle statuses and
+the "the Markdown document is the source of truth" rule are identical whichever
+you use. Prefer the MCP tools: they return structured JSON (`readiness`,
+blockers, `recommendations`) you read back to the learner without parsing
+terminal output, and a refusal arrives as a tool error whose message starts with
+a machine-readable kind — `not_found:`, `invalid_id:`, `conflict:`, `invalid:`,
+`invalid_milestone:`, `not_ready:` — followed by the plan layer's own message.
+A `not_ready:` refusal names every blocker: ask the learner for exactly that.
+
+### Plan tools over MCP (preferred)
+
+When the `studyloop` MCP server is connected — its tools appear in this
+session's tool list — use these nine, in lifecycle order:
+
+| Step | Tool | Use it to |
+|---|---|---|
+| Discover | `list_study_plans(status=None)` | List plan summaries, active first. A plan that already covers the topic is revised, not duplicated. |
+| Discover | `get_study_plan(plan_id, include_markdown=False, include_history=False)` | Read one plan in full — mission, milestones, records, `readiness` — before touching it. |
+| Interview | `get_planning_interview()` | The interview questions, the evidence seed and the plans that exist. Call it before the first question. |
+| Create | `create_study_plan(title, answers, status="draft")` | Draft from the interview answers, keyed as the interview lists them. Never replaces an existing plan: a taken id is a conflict. |
+| Revise | `update_study_plan(plan_id, …)` | Repair blockers and change fields, topics and milestones together — judged as one document, saved once. |
+| Activate | `set_study_plan_status(plan_id, "active")` | Only once `readiness` reports ready. Activation is gated: an unready plan is refused with its blockers and nothing is written. |
+| Tick | `set_study_plan_milestone(plan_id, index, done)` | Mark a milestone done — only for what the learner demonstrated. Safe to retry. |
+| Evaluate | `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `record=False` is a preview that writes nothing; `record=True` persists the checkpoint and appends it to the plan. |
+| Delete | `delete_study_plan(plan_id, confirmed=False)` | Refused unless `confirmed=True`. Pass it only after the learner has confirmed, in this conversation, that this specific plan goes — never to tidy up, never on a retry. |
+
+`record_plan_learning(plan_id, title, body="")` appends a learning record to the
+plan — the wind-down's first write.
+
+Lifecycle: discover → interview → create as `draft` → revise until `readiness`
+reports ready → activate → tick and evaluate against real sessions → complete,
+pause or abandon. Do not create as `active` to skip the gate; the seam refuses
+it. If one of these tools is missing from the connected server's inventory, use
+that step's CLI fallback below — not a workaround.
+
+### CLI fallback
+
+When the MCP server is not connected, the same work is the `studyloop plan`
+command group at a shell. Add `--json` where offered and read the same
+`readiness` field back.
+
+| Step | Command |
+|---|---|
+| Discover | `studyloop plan list` · `studyloop plan show PLAN_ID --json` |
+| Interview | `studyloop plan interview --json` |
+| Create | `studyloop plan new --title ... --why ... --success ... --milestone ... --json` |
+| Revise | No CLI command edits an existing plan's mission, topics or milestones: get it right in `studyloop plan new` (its `readiness` output says what is missing) or revise in the Web UI — never by hand-editing the document. |
+| Activate | `studyloop plan status PLAN_ID active` |
+| Tick | `studyloop plan milestone PLAN_ID INDEX --done` |
+| Evaluate | `studyloop plan evaluate PLAN_ID --phase start --json` previews; add `--record --study-id "$STUDY_ID"` to persist. |
+| Record | `studyloop plan record PLAN_ID --title "..." --body "..."` |
+| Delete | No CLI command. Deletion is `delete_study_plan` (after confirmation) or the Web UI. |
+
 ## Session Start Protocol

-```bash
-studyloop resume                       # where they left off
-studyloop plan list                    # which plans exist, and their state
-studyloop review                       # what is due for spaced repetition
-studyloop plan evaluate PLAN_ID --phase start --record --study-id "$STUDY_ID"
-```
+1. `studyloop resume` — where they left off.
+2. Discover the plans and their state — `list_study_plans` (fallback: `studyloop plan list`).
+3. `studyloop review` — what is due for spaced repetition.
+4. Evaluate the plan this session runs against —
+   `evaluate_study_plan(plan_id, "start", study_id=STUDY_ID, record=True)`
+   (fallback: `studyloop plan evaluate PLAN_ID --phase start --record --study-id "$STUDY_ID"`).

-Print the evaluation Markdown into the conversation, then act on its
+Read the evaluation back into the conversation, then act on its
 `recommendations` — due reviews first, then `next_milestone`.

 When no plan exists and the learner is unsure what to study, offer to build one
@@ -67,13 +124,21 @@ rather than picking for them.

 Follow the interview in `study-plan-protocol.md`. Sequence:

-1. `studyloop plan interview --json` → questions + evidence-based seed.
+1. `get_planning_interview` → questions + evidence-based seed + the plans that
+   already exist.
 2. Interview, one question per turn, grounded in the seed.
-3. `studyloop plan new --title ... --why ... --success ... --milestone ...`
-4. Read the `readiness` blockers and nudges back to the learner.
-5. `studyloop plan status ID active` once it is ready.
+3. `create_study_plan(title, answers)` as a `draft`, answers keyed exactly as
+   the interview lists them.
+4. Read the `readiness` blockers and nudges back to the learner; repair with
+   `update_study_plan`.
+5. `set_study_plan_status(plan_id, "active")` once `readiness` reports ready —
+   never before.
 6. Hand over: "Ready. Start with `studyloop study` and the mentor will pick this up."

+Without the MCP server: `studyloop plan interview --json`, then
+`studyloop plan new --title ... --why ... --success ... --milestone ... --json`,
+then `studyloop plan status PLAN_ID active` (see the CLI fallback table).
+
 Every milestone gets `(concepts: a, b)` — that suffix is the join key against
 `study_progress`, and without it evidence checking silently stops working.

@@ -85,6 +150,10 @@ Every milestone gets `(concepts: a, b)` — that suffix is the join key against
 | `mid` | At the first natural break | Is this session drifting off the plan? |
 | `end` | During wind-down, before `session end` | What moved, and what does the plan owe next time? |

+Preview when you only want to look (`record=False`); record at the three
+checkpoints (`record=True`, or `--record` at the CLI) so the checkpoint log and
+the plan itself carry the verdict.
+
 Treat `at-risk` and `stalled` as things to name out loud, not soften. If a
 milestone is marked done with no confidence evidence, quiz it — that is the most
 likely place the plan has drifted from reality.
@@ -95,11 +164,15 @@ If the evaluation carries `warnings`, the verdict is **partial**. Say so.

 Follow `wind-down-protocol.md`, plus:

-1. `studyloop plan milestone PLAN_ID INDEX --done` — only for what was demonstrated.
+1. `set_study_plan_milestone(plan_id, index, done=True)` — only for what was
+   demonstrated (fallback: `studyloop plan milestone PLAN_ID INDEX --done`).
 2. `studyloop progress "<concept>" -t <topic> -c <confidence>` — feeds the next `start`.
-3. `studyloop plan evaluate PLAN_ID --phase end --record --study-id "$STUDY_ID"`
-4. Write a learning record if a misconception was corrected or understanding
-   genuinely deepened — not for material merely covered.
+3. `evaluate_study_plan(plan_id, "end", study_id=STUDY_ID, record=True)`
+   (fallback: `studyloop plan evaluate PLAN_ID --phase end --record --study-id "$STUDY_ID"`).
+4. Write a learning record — `record_plan_learning` (fallback:
+   `studyloop plan record PLAN_ID --title "..." --body "..."`) — if a
+   misconception was corrected or understanding genuinely deepened, not for
+   material merely covered.
 5. State the next session's target concretely.
 6. `studyloop session end --notes "<summary>"`

@@ -130,7 +203,12 @@ See `agents/shared/audhd-framework.md`. Plan-specific applications:
 - **Silent Drift-Following** — pursuing `drift_topics` without telling the
   learner the plan no longer describes the session.
 - **Ticking for them** — the plan then lies to every future session.
-- **Hand-editing the document** — always go through `studyloop plan`.
+- **Hand-editing the document** — always go through the plan tools or
+  `studyloop plan`.
+- **Deleting to tidy up** — `delete_study_plan` is for a plan the learner has
+  said, in so many words, they want gone. Pausing or abandoning keeps the
+  document — mission, milestones, learning records; deletion removes it and
+  leaves only the checkpoint log behind.

 ## Terminal Workspace

```

### The three projections

`agents/claude/study-plan-architect.md`, `agents/opencode/study-plan-architect.md`, `agents/kiro/study-plan-architect/persona.md`:
each diff's changed lines are **identical** to the canonical diff above (verified line-set equality on `b2f37fa4`); the
persona test's `test_projected_personas_match_canonical` ×3 asserts the body after the harness header equals the
canonical file byte for byte. The harness headers themselves did not change. For reference, the headers as they stand:

```yaml
---
name: study-plan-architect
description: Builds study plans with the learner through a mission-first interview, then keeps them honest by evaluating against real study evidence at the start, middle, and end of every session. Use when the learner wants a plan, is unsure what to study next, or an existing plan needs checking.
category: communication
tools: Read, Write, Grep, Bash
---
```

```yaml
---
description: "Builds study plans with the learner through a mission-first interview, then keeps them honest by evaluating against real study evidence at the start, middle, and end of every session."
mode: primary
temperature: 0.3
tools:
  write: true
  edit: true
  bash: true
  skill: true
permission:
  edit: allow
  bash:
    "studyloop *": allow
    "session-* *": allow
    "herdr *": allow
    "*": ask
```

`agents/kiro/study-plan-architect.json` (the Kiro agent definition; the persona is `prompt: file://…/persona.md`).
Its `tools` is `["@builtin"]` and it carries **no** `mcpServers` — pinned by
`tests/test_install_agent_contracts.py::test_install_agents_places_the_plan_architect_definitions` (line 701:
`assert "mcpServers" not in definition, "study-plan-architect.json must carry no mcpServers"`), introduced in
`d96fb9ba` ("Kiro's existing study-plan-architect.json gains the same session-export stop hook … (no mcpServers, by
design)") **before** #13b made the persona prefer MCP. By contrast `agents/kiro/study-mentor.json` carries
`mcpServers` for `study-speak`, `session-db` **and** `studyloop` (`"command": "studyloop-mcp"`) with `tools:
["@builtin", "@study-speak", "@session-db"]` and an `allowedTools` list naming six `mcp_studyloop_*` tools (none of
them plan tools). Claude Code's frontmatter `tools: Read, Write, Grep, Bash` is an allow-list; the project-level
`agents/claude/mcp.json` registers the `studyloop` server for the main agent.

### `agents/manifest.json` and `.secrets.baseline` — diff vs `205819c7`

```diff
diff --git a/agents/manifest.json b/agents/manifest.json
index bd6acb2b..1ff10eb0 100644
--- a/agents/manifest.json
+++ b/agents/manifest.json
@@ -6,8 +6,8 @@
       "updated": "2026-09-14"
     },
     "claude/study-plan-architect.md": {
-      "hash": "b4a764b14bb3c699",  # pragma: allowlist secret
-      "updated": "2026-09-14"
+      "hash": "c4ae64c9c86f9235",  # pragma: allowlist secret
+      "updated": "2026-09-16"
     },
     "codex/AGENTS.md": {
       "hash": "7e6c1a0d534b65f7",  # pragma: allowlist secret
@@ -30,8 +30,8 @@
       "updated": "2026-09-14"
     },
     "opencode/study-plan-architect.md": {
-      "hash": "e282b64aa320e70b",  # pragma: allowlist secret
-      "updated": "2026-09-14"
+      "hash": "e455bb970b1e4fc7",  # pragma: allowlist secret
+      "updated": "2026-09-16"
     },
     "pi/AGENTS.md": {
       "hash": "03355b0aa919ef6b",  # pragma: allowlist secret
```

`.secrets.baseline` (detect-secrets' own bookkeeping, not reproduced — its entries are the detector's SHA-1
fingerprints of the strings it flagged): one `Hex High Entropy String` entry **added** for `agents/manifest.json`
line 9 (the new Claude projection hash) and the entry for line 33 (the OpenCode projection hash) **replaced**;
`generated_at` moved from `2026-09-15T16:53:36Z` to `2026-09-16T04:40:51Z`. Nothing else in the baseline moved.

### `packages/studyloop/tests/test_plan_architect_persona.py` (full source at `b2f37fa4`, new file)

```python
"""The study-plan architect persona prefers the MCP plan tools, CLI as fallback (T4.2, #13b).

The persona the ``planning`` purpose renders (``persona_mode_for("planning")`` →
``plan-architect``, design §5) must name the nine plan lifecycle tools of design
§4 — the six #11 registered and the three #12 lands — in a tooling section that
puts the MCP tools **before** the ``studyloop plan …`` CLI fallback, so an
architect running in a harness with the ``studyloop`` MCP server connected
reaches the plan application layer directly and one without it still has a
working recipe. The interview protocol itself (one question per turn) is not
under test here: these tests are about *which tools* the architect is told to
reach for and in what order of preference, never about the wording of a question.

Two guards ride along. The ``focus`` persona — what every default session
ships and hashes into ``persona_hash`` — is pinned by digest so this change
provably touched only the architect. And the per-harness projections (Claude
and OpenCode frontmatter files, Kiro's ``persona.md``) plus the manifest the
generator writes must still regenerate byte-identically from the canonical
body: there is no projection generator, only the copies and the hash manifest,
so drift is caught here rather than at install time.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from studyloop import session_state
from studyloop.agent_launcher import build_canonical_persona, persona_mode_for

_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "agents/manifest.json").exists():
    _REPO_ROOT = _REPO_ROOT.parent
_AGENTS = _REPO_ROOT / "agents"
_CANONICAL = _AGENTS / "shared/personas/plan-architect.md"
_MANIFEST_GENERATOR = _REPO_ROOT / "scripts/update-agent-manifest.py"

# Design §4: the nine plan lifecycle tools, in lifecycle order.
PLAN_MCP_TOOLS: tuple[str, ...] = (
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

# #12 (T4.1) registers these three; the persona names them ahead of that landing
# so the two Phase-4 branches merge without a second persona edit.
_LANDING_WITH_12: frozenset[str] = frozenset(
    {"set_study_plan_milestone", "evaluate_study_plan", "delete_study_plan"}
)

# The CLI fallback must cover every lifecycle step that HAS a CLI command.
# ``delete`` is deliberately absent: there is no ``studyloop plan delete``
# (deletion is the Web UI or ``delete_study_plan`` with explicit confirmation),
# and the prompt-contract test rejects any invocation that does not resolve.
_CLI_FALLBACK_SUBCOMMANDS: tuple[str, ...] = (
    "interview",
    "list",
    "show",
    "new",
    "status",
    "milestone",
    "evaluate",
    "record",
)

_MCP_HEADING_RE = re.compile(r"^#{2,3} .*\bMCP\b.*$", re.MULTILINE)
_CLI_HEADING_RE = re.compile(r"^#{2,3} .*\bCLI fallback\b.*$", re.MULTILINE)

# ``build_canonical_persona("focus", "Python", 5)`` at 205819c7 (the tip
# feat/p4-13b branched from), with the three session paths fixed below so the
# digest does not depend on the machine's config directory. A change here is a
# change to what every default session ships — make it deliberately, in the same
# commit as the persona edit, never as a side effect of an architect change.
# A content digest of a public persona rendering, not a credential.
_FOCUS_SHA256_AT_205819C7 = (
    "2d35c22a99ed72fbc91e8a79ad05312b04af2e36bbb5a7bb4d7ac4a0e9ef11e0"  # pragma: allowlist secret
)


def _planning_persona() -> str:
    """The persona a ``planning``-purpose launch ships (design §5), brief and all."""
    mode = persona_mode_for("planning")
    return build_canonical_persona(mode, "Study plan", 5, brief="- interview item one")


def _section(content: str, heading_re: re.Pattern[str]) -> tuple[int, str]:
    """Return ``(start, text)`` of the section a heading opens, up to the next
    heading of the same or a higher level."""
    match = heading_re.search(content)
    assert match, f"no heading matches {heading_re.pattern!r}"
    level = len(match.group(0)) - len(match.group(0).lstrip("#"))
    closer = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE)
    following = closer.search(content, match.end())
    end = following.start() if following else len(content)
    return match.start(), content[match.start() : end]


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    assert end != -1, "frontmatter opened with '---' but never closed"
    return text[end + len("\n---\n") :]


# ---------------------------------------------------------------------------
# RED for T4.2: the nine tools, the fallback, and the order of preference.
# ---------------------------------------------------------------------------


def test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning() -> None:
    content = _planning_persona()

    missing = [name for name in PLAN_MCP_TOOLS if f"`{name}" not in content]
    assert not missing, f"planning persona does not name {missing}"

    assert "CLI fallback" in content
    _, cli_section = _section(content, _CLI_HEADING_RE)
    absent = [
        sub
        for sub in _CLI_FALLBACK_SUBCOMMANDS
        if not re.search(rf"studyloop plan {sub}\b", cli_section)
    ]
    assert not absent, f"CLI fallback section names no `studyloop plan {absent}`"
    assert "studyloop plan delete" not in content, "there is no such command"


def test_plan_architect_persona_prefers_mcp_over_cli_ordering() -> None:
    content = _planning_persona()

    mcp_at, mcp_section = _section(content, _MCP_HEADING_RE)
    cli_at, _ = _section(content, _CLI_HEADING_RE)
    assert mcp_at < cli_at, "the MCP tools must be introduced before the CLI fallback"
    assert mcp_at + len(mcp_section) <= cli_at, "the MCP section must close before the fallback"
    assert not re.search(r"studyloop plan \w", mcp_section), "a CLI recipe inside the MCP section"

    # Every one of the nine is introduced in the MCP section itself, not only
    # mentioned in passing somewhere after the fallback.
    not_in_mcp = [name for name in PLAN_MCP_TOOLS if f"`{name}" not in mcp_section]
    assert not not_in_mcp, f"MCP section does not introduce {not_in_mcp}"

    # And the fallback is framed as the fallback: no `studyloop plan` recipe
    # appears before the MCP tools have been named.
    first_cli = re.search(r"studyloop plan \w", content)
    assert first_cli is not None
    assert first_cli.start() > mcp_at, "a CLI recipe precedes the MCP tools"


def test_mcp_section_states_the_lifecycle_guards() -> None:
    """The three behaviours the seam enforces and the persona must not talk the
    agent past: activate only when readiness says ready, delete only on explicit
    confirmation, evaluate as a preview unless recording is meant."""
    _, mcp_section = _section(_planning_persona(), _MCP_HEADING_RE)
    lowered = mcp_section.lower()

    assert "readiness" in lowered and "active" in lowered
    assert "confirm" in lowered and "`delete_study_plan" in mcp_section
    assert "record=false" in lowered.replace(" ", "") or "preview" in lowered
    assert "record=true" in lowered.replace(" ", "")


def test_the_nine_are_the_registry_plus_exactly_what_12_lands() -> None:
    """Ground the test's own constant in the real registry: six of the nine are
    registered today, and the ones that are not are exactly the three #12 adds.
    Holds before and after #12 merges."""
    from studyloop.mcp.server import mcp

    registered = set(mcp._tool_manager._tools)
    unregistered = {name for name in PLAN_MCP_TOOLS if name not in registered}
    assert unregistered <= _LANDING_WITH_12, f"unexpected unregistered names: {unregistered}"
    assert "record_plan_learning" in registered


# ---------------------------------------------------------------------------
# Guards: focus untouched, projections and manifest regenerate byte-identically.
# ---------------------------------------------------------------------------


def test_focus_persona_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_state, "STATE_FILE", Path("/fixed/session-state.json"))
    monkeypatch.setattr(session_state, "TOPICS_FILE", Path("/fixed/session-topics.md"))
    monkeypatch.setattr(session_state, "PARKING_FILE", Path("/fixed/session-parking.md"))

    content = build_canonical_persona("focus", "Python", 5)

    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == _FOCUS_SHA256_AT_205819C7


@pytest.mark.parametrize(
    "relative",
    [
        "claude/study-plan-architect.md",
        "opencode/study-plan-architect.md",
        "kiro/study-plan-architect/persona.md",
    ],
)
def test_projected_personas_match_canonical(relative: str) -> None:
    canonical = _CANONICAL.read_text(encoding="utf-8").lstrip("\n")
    projected = _strip_frontmatter((_AGENTS / relative).read_text(encoding="utf-8")).lstrip("\n")
    assert projected == canonical, f"agents/{relative} has drifted from the canonical persona"


def test_manifest_hashes_regenerate_byte_identically_for_the_architect_projections() -> None:
    """Run the generator's own hash over the tracked projections and compare with
    the committed manifest — the check ``studyloop install agents`` and doctor
    rely on, without mutating the tracked manifest from a test."""
    spec = importlib.util.spec_from_file_location("update_agent_manifest", _MANIFEST_GENERATOR)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    manifest = json.loads((_AGENTS / "manifest.json").read_text(encoding="utf-8"))["agents"]
    tracked = [
        rel
        for files in generator.TRACKED_FILES.values()
        for rel in files
        if "study-plan-architect" in rel
    ]
    assert tracked, "the generator tracks no architect projection at all"
    stale = {
        rel: (manifest.get(rel, {}).get("hash"), generator.hash_file(_AGENTS / rel))
        for rel in tracked
        if manifest.get(rel, {}).get("hash") != generator.hash_file(_AGENTS / rel)
    }
    assert not stale, f"re-run scripts/update-agent-manifest.py: {stale}"
```

## 5. Delta specs and public docs — diff vs `205819c7` (one line of context)

### `openspec/changes/plan-application-seam/specs/mcp-server/spec.md`

```diff
diff --git a/openspec/changes/plan-application-seam/specs/mcp-server/spec.md b/openspec/changes/plan-application-seam/specs/mcp-server/spec.md
index 1e7bacdc..43dd466f 100644
--- a/openspec/changes/plan-application-seam/specs/mcp-server/spec.md
+++ b/openspec/changes/plan-application-seam/specs/mcp-server/spec.md
@@ -14,7 +14,12 @@ title and body reports `created: false` with the original `number`, and so
 does a record another writer filed just before the mutation ran. Every seam
-refusal SHALL be a `ToolError`: `PlanNotReady` SHALL
-render as `plan is not ready to activate: <blocker>; <blocker>…` so the agent
-can tell the learner what to repair (design §2, "ToolError containing
-blockers"); `PlanNotFound`, `InvalidPlanId` and `InvalidField` (the store's
-title/heading rule) SHALL render as their message.
+refusal SHALL be a `ToolError` mapped by the same `_plan_tool_error` helper the
+other eight plan tools use (Phase 4, #12 — before the fold the tool mapped
+inline, without a kind prefix): `PlanNotReady` SHALL render as `not_ready:
+plan is not ready to activate: <blocker>; <blocker>…` (with the already-active
+"pause it or repair" suffix when the plan was active) so the agent can tell
+the learner what to repair (design §2, "ToolError containing blockers");
+`PlanNotFound`, `InvalidPlanId` and `InvalidField` (the store's title/heading
+rule) SHALL render as `not_found: …`, `invalid_id: …` and `invalid: …`
+followed by their message, with the domain error chained as `__cause__`. The
+success shape is unchanged by the fold.

@@ -23,5 +28,5 @@ plan tools of design §4 are registered in Phase 3 (#11, the requirement
 below); the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
-`delete_study_plan`) are **not yet registered**. The stdio smoke test pins a
-lower bound and the core-tool names, not an exact count, and is retargeted to
-the full inventory in #12 (D-9).
+`delete_study_plan`) are registered in #12 (the last requirement in this
+file). The stdio smoke test pins the exact production inventory (32 unique
+names), the nine plan tools and the core names (D-9, council review 3 F13).

@@ -49,4 +54,6 @@ the full inventory in #12 (D-9).
   but has no mission, success criteria or milestones)
-- **THEN** a `ToolError` is raised whose message contains `not ready` and each
-  blocker string from the `ReadinessView`
+- **THEN** a `ToolError` is raised whose message starts with `not_ready: plan
+  is not ready to activate: `, contains each blocker string from the
+  `ReadinessView` and the "already active … pause it or repair" hint, and
+  chains the `PlanNotReady` as its cause

@@ -55,4 +62,4 @@ the full inventory in #12 (D-9).
   id is unknown or malformed
-- **THEN** a `ToolError` is raised carrying the seam's message and no record is
-  added
+- **THEN** a `ToolError` is raised reading `invalid: …`, `not_found: …` or
+  `invalid_id: …` followed by the seam's message, and no record is added

@@ -162 +169,144 @@ has not met. The `ToolError` SHALL chain the domain error as its cause.
   not the same object
+
+
+
+### Requirement: Study-plan progression and deletion tools
+`register_tools(mcp)` SHALL register three further study-plan tools in the
+production inventory — completing the nine of design §4 — each a thin adapter
+that makes exactly one `studyloop.planning.PlanApplication` call, imports no
+storage, index, authoring or evaluation module (D-6), and maps every seam
+refusal through the same `<kind>: <message>` `ToolError` mapping as the six
+above (the domain error chained as `__cause__`):
+
+| Tool | Seam call |
+|---|---|
+| `set_study_plan_milestone(plan_id, index, done)` | `apply(SetMilestone(plan_id, index, done))` → `PlanDetail.to_json_dict()` |
+| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `assess(AssessPlan(plan_id, phase, study_id, record))` → `AssessmentResult.to_json_dict()` |
+| `delete_study_plan(plan_id, confirmed=False)` | `apply(DeletePlan(plan_id, confirmed))` → `DeleteResult.to_json_dict()` (`{"deleted": true, "plan_id"}`) |
+
+`set_study_plan_milestone` SHALL take `done` as a required boolean with no
+default and forward it as given — set, not toggle: the tool SHALL make no
+preliminary read and compute no opposite, so a second identical call returns
+the same plan, raises nothing and rewrites nothing. An index the plan does
+not have (past the end or negative) is the seam's `InvalidMilestone`,
+rendered `invalid_milestone: …`; a set on an active-but-unready document is
+the seam's `PlanNotReady`, rendered `not_ready: … — the plan is already
+active; pause it or repair the blockers before writing`, and nothing is
+written in either case.
+
+`evaluate_study_plan` SHALL call `assess`, never `apply` (`AssessPlan` is not
+a `PlanIntent`), SHALL default `record` to `False`, and SHALL NOT expose
+`append_to_plan` (the seam's default, `True`, applies when recording). The
+response SHALL be the `AssessmentResult` view — `evaluation`, `markdown`,
+`db_write`, `document_write`, `recording_complete`, `warnings` — with each
+sink reported **as the seam reports it** (`not_requested`, `saved`, `failed`),
+never flattened to a boolean and never an invented `saved`. A preview
+(`record=False`) SHALL write to neither sink: the document is byte-identical
+afterwards and the checkpoint log is unchanged. With `record=True` a failed
+sink SHALL surface as `failed` with `recording_complete: false` and the seam's
+warning string in `warnings` — a reported outcome, never an exception and
+never a bare success. Recording on an active plan that is unready SHALL be
+refused (`not_ready: …`) before either sink is touched; an unknown `phase`
+is the seam's `invalid: phase must be one of …`, judged after the plan
+exists (`not_found:` first).
+
+`delete_study_plan` SHALL keep `confirmed` as an ordinary boolean defaulting
+to `False` in its schema — not required, not constrained to a literal `true`
+— and SHALL forward it unchanged: an unconfirmed call is the seam's
+`InvalidField`, rendered `invalid: deleting '<id>' requires confirmed=True`,
+and the plan still exists byte-identical afterwards. A confirmed delete
+removes the document and its derived index row and SHALL leave the plan's
+checkpoint history in the sessions database readable. A missing plan is
+`not_found:` before the confirmation is judged.
+
+The production inventory SHALL be exactly 32 unique tool names — 23 at
+`0a20a796` plus the nine design-§4 plan tools, `record_plan_learning` being
+one of the 23 — and the stdio smoke test SHALL assert that exact count, the
+nine plan names, `record_plan_learning` and the core names over the real
+transport.
+
+#### Scenario: A retried milestone set is a no-op
+- **WHEN** `set_study_plan_milestone(<id>, 0, true)` is called twice on a
+  ready plan with two milestones, then `set_study_plan_milestone(<id>, 0,
+  false)`
+- **THEN** the first call returns the plan with `milestones[0].done: true` and
+  `plan.milestone_done: 1`; the second returns an equal response, raises
+  nothing and leaves the document byte-identical; the third reopens the
+  milestone (`done: false`, `milestone_done: 0`)
+
+#### Scenario: Milestone set on an active-but-unready document is refused
+- **WHEN** `set_study_plan_milestone("husk", 0, true)` is called for an active
+  document with a milestone but no mission or success criteria
+- **THEN** a `ToolError` is raised starting `not_ready: plan is not ready to
+  activate: `, naming every blocker and containing `already active` and
+  `pause it or repair`, and the document is byte-identical afterwards; an
+  index the plan does not have (`2`, `9`, `-1`) is `invalid_milestone: No
+  milestone at index …` with nothing written
+
+#### Scenario: Evaluate preview writes nothing
+- **WHEN** `evaluate_study_plan(<id>, "mid")` is called (the default
+  `record=False`) on an active plan
+- **THEN** the response carries the evaluation (`phase: "mid"`, a verdict, a
+  non-empty `markdown`) with `db_write` and `document_write` both
+  `not_requested` and `recording_complete: true`; the plan document is
+  byte-identical afterwards; `get_study_plan(<id>, include_history=True)`
+  returns an empty `history` and an empty `checkpoints` table
+
+#### Scenario: Evaluate record reports both sinks
+- **WHEN** `evaluate_study_plan(<id>, "end", study_id="sess-9", record=True)`
+  is called on an active plan
+- **THEN** `db_write` and `document_write` are `saved`, `recording_complete`
+  is `true`, the checkpoint log holds one `end` row attributed to `sess-9`
+  (visible through `get_study_plan(include_history=True)`), and the
+  document's `checkpoints` table holds one `end` row
+
+#### Scenario: A failed sink is a warning, not a success and not an error
+- **WHEN** the checkpoint log write fails during
+  `evaluate_study_plan(<id>, "start", record=True)`
+- **THEN** the tool returns (no `ToolError`) with `db_write: "failed"`,
+  `document_write: "saved"`, `recording_complete: false` and `checkpoint not
+  saved to the database` in `warnings`; the document holds the checkpoint and
+  the log does not
+
+#### Scenario: Recording on an active-but-unready plan is refused before either sink
+- **WHEN** `evaluate_study_plan("husk", "start", record=True)` is called for
+  an active document that is unready
+- **THEN** a `ToolError` starting `not_ready: ` with the "pause it or repair"
+  hint is raised, the document is byte-identical and the log unchanged; the
+  same call with `record=False` succeeds with both sinks `not_requested`
+
+#### Scenario: Delete requires confirmation
+- **WHEN** `delete_study_plan(<id>)` or `delete_study_plan(<id>,
+  confirmed=False)` is called
+- **THEN** a `ToolError` reading `invalid: deleting '<id>' requires
+  confirmed=True` is raised, the document exists byte-identical afterwards
+  and `list_study_plans()` still counts it; the tool's schema has
+  `confirmed` as a boolean defaulting to `false`
+
+#### Scenario: Confirmed delete keeps the checkpoint history
+- **WHEN** a checkpoint has been recorded for `<id>` and
+  `delete_study_plan(<id>, confirmed=True)` is called
+- **THEN** the response is `{"deleted": true, "plan_id": "<id>"}`, the
+  document is gone, `list_study_plans()` is empty, `get_study_plan(<id>)` is
+  `not_found: …`, and the checkpoint history for `<id>` still holds the
+  recorded row; `delete_study_plan("ghost")` is `not_found:` whether or not
+  confirmed, and a traversal id is `invalid_id:`
+
+#### Scenario: Every refusal of the three is one prefixed ToolError
+- **WHEN** the seam raises `PlanNotFound`, `InvalidPlanId`, `PlanConflict`,
+  `InvalidField`, `InvalidMilestone`, or an unmapped `PlanError` from
+  `apply` (milestone, delete) or `assess` (evaluate)
+- **THEN** the tool raises exactly one `ToolError` reading `not_found: …`,
+  `invalid_id: …`, `conflict: …`, `invalid: …`, `invalid_milestone: …` or
+  `plan_error: …` followed by the seam's message, with the domain error
+  chained as `__cause__`; responses of the three are fresh containers on
+  every call
+
+#### Scenario: The production inventory is exactly 32 with the nine plan tools
+- **WHEN** a stdio client performs the handshake and `tools/list` against
+  `python -m studyloop.mcp.server` (no `--dev`)
+- **THEN** exactly 32 unique names are advertised, including
+  `list_study_plans`, `get_study_plan`, `get_planning_interview`,
+  `create_study_plan`, `update_study_plan`, `set_study_plan_status`,
+  `set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan`,
+  `record_plan_learning` and the core tools
```

### `openspec/changes/plan-application-seam/specs/agent-adapters/spec.md`

```diff
diff --git a/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md b/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md
index cd850ea2..68938d07 100644
--- a/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md
+++ b/openspec/changes/plan-application-seam/specs/agent-adapters/spec.md
@@ -32 +32,45 @@ SHALL be byte-identical to the pre-`brief` output, so no existing session's
   byte-identical to the output before the `brief` keyword existed
+
+### Requirement: Architect persona prefers the MCP plan tools
+The canonical study-plan-architect persona (`agents/shared/personas/plan-architect.md`,
+the body every harness projection carries verbatim after its own header) SHALL
+carry one tooling section that introduces the plan tools over MCP **before** the
+CLI fallback. The MCP subsection SHALL name the nine plan lifecycle tools of
+design §4 — `list_study_plans`, `get_study_plan`, `get_planning_interview`,
+`create_study_plan`, `update_study_plan`, `set_study_plan_status`,
+`set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` — in
+lifecycle order (discover → interview → create as `draft` → revise → activate →
+tick → evaluate → delete), and SHALL state the three guards the plan
+application layer enforces: activation only once `readiness` reports ready
+(never creating as `active` to skip the gate), `evaluate_study_plan` with
+`record=False` as a preview that writes nothing versus `record=True` to
+persist a checkpoint, and `delete_study_plan` only with `confirmed=True` after
+the learner has explicitly confirmed. The CLI fallback subsection SHALL give
+the `studyloop plan` command for every lifecycle step that has one
+(`interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate`,
+`record`) and SHALL say plainly which steps the CLI cannot perform (revising an
+existing plan's fields; deletion) rather than inventing a command. A tool
+missing from the connected server's inventory SHALL route to that step's CLI
+fallback. The interview protocol (one question per turn) SHALL be unchanged,
+and the `focus` persona SHALL be byte-identical before and after this change.
+
+#### Scenario: Planning persona names the nine tools before the fallback
+- **WHEN** `build_canonical_persona(persona_mode_for("planning"), "Study plan", 5, brief="- item")` is rendered
+- **THEN** the result names all nine design-§4 tool names inside the MCP
+  subsection, the MCP subsection precedes the `CLI fallback` subsection and
+  closes before it, no `studyloop plan` recipe appears inside the MCP
+  subsection, and the `CLI fallback` subsection names `studyloop plan
+  interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate` and
+  `record` and no `studyloop plan delete`
+
+#### Scenario: Focus persona untouched
+- **WHEN** `build_canonical_persona("focus", "Python", 5)` is rendered with the
+  three session paths fixed
+- **THEN** its SHA-256 digest equals the digest recorded at `205819c7`
+
+#### Scenario: Projections and manifest regenerate byte-identically
+- **WHEN** `agents/claude/study-plan-architect.md`, `agents/opencode/study-plan-architect.md`
+  and `agents/kiro/study-plan-architect/persona.md` are read
+- **THEN** each body after its harness header equals the canonical persona
+  byte-for-byte, and `agents/manifest.json` carries the generator's own hash
+  for every architect projection it tracks
```

### `docs/agent-install.md` — diff vs `205819c7` (the "Study-plan tools over MCP" section)

```diff
diff --git a/docs/agent-install.md b/docs/agent-install.md
index 8d79f3fd..965b63c5 100644
--- a/docs/agent-install.md
+++ b/docs/agent-install.md
@@ -222,16 +222,20 @@ reach the MCP server can do the same work with `studyloop plan …` at a shell.
 | `create_study_plan(title, answers, plan_id=None, status="draft")` | Draft a new plan from interview answers; never replaces an existing plan (a taken id is a conflict). |
 | `update_study_plan(plan_id, …)` | Revise fields, topics, milestones and status together, judged as one document and saved once. |
 | `set_study_plan_status(plan_id, status)` | Move a plan between `draft`, `active`, `paused`, `complete`, `abandoned`; activation is readiness-gated. |
+| `set_study_plan_milestone(plan_id, index, done)` | Mark one milestone complete (`done=true`) or reopen it (`false`) — set, not toggle, so a retry is safe. |
+| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | Evaluate the plan at a `start`/`mid`/`end` checkpoint against real study evidence. The default is a preview that writes nothing; `record=true` appends the checkpoint to the log and the document and reports each write (`db_write`, `document_write`, `recording_complete`). |
+| `delete_study_plan(plan_id, confirmed=False)` | Delete the plan document — irreversible, so it is refused unless `confirmed=true`. The plan's checkpoint history is kept. |
 | `record_plan_learning(plan_id, title, body="", status="active")` | Append a learning record to the plan — the wind-down's first write. |

 A refused call is a tool error whose message starts with a machine-readable
 kind — `not_found:`, `invalid_id:`, `conflict:`, `invalid:`,
 `invalid_milestone:`, `not_ready:`, or `plan_error:` for a refusal the
 mapping has not met — followed by the plan layer's own message. A `not_ready:` refusal names every blocker, so the agent can ask the
-learner for what is missing instead of reporting that something is wrong.
-Milestone completion, checkpoint evaluation and deletion over MCP are not
-available yet; use `studyloop plan milestone`, `studyloop plan evaluate` and
-the Web UI for those.
+learner for what is missing instead of reporting that something is wrong; on
+a plan that is already active it adds "pause it or repair the blockers before
+writing". A recorded evaluation whose database or document write failed is
+not an error: the response says which write failed (`recording_complete:
+false` with the reason in `warnings`) and still carries the evaluation.

 ## Data integrity

```

## 6. Reference facts you may rely on (verified on `b2f37fa4`)

### The seam methods the three tools call (`planning/application.py`, unchanged this phase)

```python
    def assess(self, intent: AssessPlan) -> AssessmentResult:
        """Evaluate a plan at a checkpoint and report what was recorded where.

        ``record=False`` calls :func:`~studyloop.planning.evaluation.evaluate_plan`
        and touches nothing. ``record=True`` calls the Phase-0
        :func:`~studyloop.planning.evaluation.evaluate_and_record` — the one
        checkpoint writer; this method adds no second — and reads its two
        recording warnings back into ``db_write`` / ``document_write``. A
        failed sink is an outcome on the result, never an exception: the
        evaluation succeeded and the caller gets it (D-1, D-3).
        """
        plan = self._load(intent.plan_id)  # 404 before 400: the plan before the phase
        phase = (intent.phase or "").strip().lower()
        if phase not in CHECKPOINT_PHASES:
            msg = f"phase must be one of {CHECKPOINT_PHASES}"
            raise InvalidField(msg)
        study_id = (intent.study_id or "").strip()

        # Appending the checkpoint re-saves the plan document. That is a write
        # of the resulting document like any other, so an active plan that is
        # unready is refused here — before either sink is touched — exactly as
        # SetMilestone and RevisePlan refuse it (review 2, F2). A preview or a
        # database-only recording persists no document and is not gated.
        if intent.record and intent.append_to_plan and plan.status == "active":
            self._assert_can_be_active(plan, already_active=True)

        if not intent.record:
            result = evaluation.evaluate_plan(plan, phase, study_id=study_id)
            return AssessmentResult(
                evaluation=PlanEvaluationView.from_evaluation(result),
                db_write="not_requested",
                document_write="not_requested",
                warnings=tuple(result.warnings),
            )

        result = evaluation.evaluate_and_record(
            plan, phase, study_id=study_id, append_to_plan=intent.append_to_plan
        )
        db_write: SinkStatus = "failed" if _DB_WARNING in result.warnings else "saved"
        document_write: SinkStatus
        if not intent.append_to_plan:
            document_write = "not_requested"
        elif _DOCUMENT_WARNING in result.warnings:
            document_write = "failed"
        else:
            document_write = "saved"
        return AssessmentResult(
            evaluation=PlanEvaluationView.from_evaluation(result),
            db_write=db_write,
            document_write=document_write,
            warnings=tuple(result.warnings),
        )
```

```python
    def _set_milestone(self, intent: SetMilestone) -> PlanDetail:
        """Set one milestone's state on the loaded candidate; one gate, at most one save.

        Set, not toggle: applying the same intent twice leaves the same
        document — a retry that asks for the state the milestone already has
        writes nothing, so ``updated`` and the file's bytes are untouched
        (review 2, F1). The gate still runs first: policy before the
        short-circuit. A negative index is refused rather than read as
        Python's "from the end" — a milestone index is a position in the
        plan, not a list trick.
        """
        candidate = self._load(intent.plan_id)
        total = len(candidate.milestones)
        if not 0 <= intent.index < total:
            msg = f"No milestone at index {intent.index} (plan has {total})"
            raise InvalidMilestone(msg)
        milestone = candidate.milestones[intent.index]
        wanted = bool(intent.done)
        if candidate.status == "active":
            self._assert_can_be_active(candidate, already_active=True)
        if milestone.done != wanted:
            milestone.done = wanted
            store.save_plan(candidate)
        return PlanDetail.from_plan(candidate)

    def _delete(self, intent: DeletePlan) -> DeleteResult:
        """Remove the canonical document; keep the durable checkpoint log.

        The plan must exist before the confirmation is judged (404 before
        400, like every write), and an unconfirmed intent writes nothing.
        The store's ``delete_plan`` also drops the derived index row and
        deliberately leaves ``study_plan_checkpoints`` alone: the log is
        evidence about the learner's sessions, not about the file.
        """
        plan = self._load(intent.plan_id)
        if not intent.confirmed:
            msg = f"deleting {plan.plan_id!r} requires confirmed=True"
            raise InvalidField(msg)
        try:
            deleted = store.delete_plan(plan.plan_id)
        except store.InvalidPlanIdError as exc:  # pragma: no cover - validated by _load
            raise InvalidPlanId(str(exc)) from exc
        if not deleted:  # vanished between the load and the unlink
            msg = f"no study plan with id {plan.plan_id!r}"
            raise PlanNotFound(msg)
        return DeleteResult(plan_id=plan.plan_id)

```

- `CHECKPOINT_PHASES == ("start", "mid", "end")`; `InvalidField`, `InvalidMilestone`, `InvalidPlanId`, `PlanConflict`,
  `PlanNotFound`, `PlanNotReady` are sibling subclasses of `PlanError` (no subclass relationship among the six).
  `PlanNotReady(readiness, already_active=False)`.
- `AssessPlan(plan_id, phase, study_id="", record=False, append_to_plan=True)` is a frozen dataclass and is **not** a
  member of the `PlanIntent` union; `AssessmentResult.to_json_dict()` keys are `evaluation`, `markdown`, `db_write`,
  `document_write`, `recording_complete`, `warnings`; `recording_complete` is `db_write != "failed" and document_write
  != "failed"`. `DeleteResult.to_json_dict()` is `{"deleted": True, "plan_id": …}`.
- `store.delete_plan` removes the document and the derived index row and leaves `study_plan_checkpoints` alone.
- Every tool registered through the local `tool()` wrapper is wrapped by `_guard_scope` (an unconfigured scope becomes a
  structured `ToolError`); `get_next_action` additionally carries `@consistent_read`. None of the three new tools is
  decorated with `@consistent_read` (the six of #11 are not either).
- `build_canonical_persona` reads `agents/shared/personas/<mode>.md` from the **repository** checkout, not from
  `~/.kiro/agents` or `~/.claude/agents`: a Web-launched architect (PTY or ACP) always gets the canonical body; the
  harness projections are what a learner gets when they start the agent *from the harness itself* (`kiro-cli chat
  --agent study-plan-architect`, Claude Code's `@study-plan-architect`).
- `_resolve_persona` (`web/routes/session/_start.py`) renders the brief with `_render_planning_brief` — three H3
  sections in this order: `### Interview`, `### Evidence from the learner's history`, `### Existing plans`; every
  quoted value passes `_one_line` (review-3 F4). The `201` body carries `purpose`; `GET /api/session/state` does
  `state.setdefault("purpose", "focus")`. The CLI `studyloop plan architect` (`cli/_plan.py:479`) calls the study
  launcher with `topic="Study plan"`, `mode="plan-architect"` and writes no `purpose`.
- Existing browser tests: `tests/_playwright_helpers.py` (`web_server_fixture_factory`, `auth_context_fixture_factory`,
  `web_page_fixture_factory`, hermetic child env), used by `test_web_smoke_browser.py` and
  `test_web_live_session_banner.py`, both `pytestmark = [pytest.mark.e2e]` (deselected by the default run). The Plans
  view is `web/static/js/components/plans-panel.js` (the only static file that fetches `api/plans`); the start
  picker posts to `/api/session/start` from `js/components/session-timer.js:230` and `components.js:3365`. JS unit
  tests run with `node --test packages/studyloop/tests/js/*.test.js` (115 pass at `65bde13c`).
- `tests/test_install_agent_contracts.py` also pins the OpenCode/Claude architect files as symlinks into
  `~/.config/opencode/agents/` and `~/.claude/agents/`; `studyloop doctor` reports manifest staleness from the hashes.

## 7. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for Phase 4 as the base of Phase 5, with the single
   sentence that decides it. If the two streams deserve different verdicts, say so per stream (#12, #13b).
2. **Findings**, each with severity 🔴 defect (wrong behaviour or a bug), 🟡 must-fix-before-Phase-5 (design/contract
   violation, missing test, unsafe pattern), 🔵 should-fix, 💡 note. For each: file:line or function, what is wrong,
   why it matters, the concrete fix, and the RED test that would pin it (name it). Check specifically:
   - **#12 adapters** (a) each of the three is one seam call with the arguments forwarded unchanged — is any
     normalisation (`plan_id or None`, `.strip()`, `bool()`) present or missing where the six of #11 had one? Does
     `evaluate_study_plan` leave `append_to_plan` at the seam's default and is that the right thing to hide? (b) the
     docstrings are the schema an agent reads: `set_study_plan_milestone` says an active-but-unready plan is refused
     — is the `not_ready` message it quotes the one `_plan_tool_error` actually produces? `evaluate_study_plan`'s
     "`markdown` is the evaluation block to paste" — does the seam's `markdown` exist for a preview? Are the
     `Refusals:` lists complete (e.g. `plan_error:`; `conflict:` is listed by the tests as reachable for all three —
     can the seam raise `PlanConflict` from `_set_milestone`/`_delete`/`assess` at all?) (c) `delete_study_plan`:
     the seam judges `not_found` before `confirmed` — the docstring says so; is "Ask the learner before passing it"
     enforceable or only advisory, and is `confirmed` in the schema honestly "not required, ordinary boolean"? (d)
     **the fold**: `record_plan_learning` now raises `_plan_tool_error(exc)` — the message for `PlanNotReady`
     changed from `plan is not ready to activate: <blockers>` to `not_ready: plan is not ready to activate:
     <blockers>[ — the plan is already active; …]`. #12 calls this "an intentional wording change, reported as such"
     and says `test_plan_record.py::TestMcpTool` and `test_mcp_plan_record_seam.py` match by substring. Is a
     silently-prefixed message a contract break for any consumer (the Kiro/Claude wind-down protocol text, docs, the
     `agents/shared/wind-down-protocol.md`)? Should the fold have been its own commit (RED pin, then GREEN) rather than
     inside `b1e11e78` with the three tools? (e) deviation (b): `record_plan_learning` (line ~168) references
     `_plan_tool_error` defined at line ~886 inside the same enclosing function — legal late binding, but is a
     750-line forward reference inside `register_tools` an acceptable pattern or should the helper move above its
     first use ("append only" was the constraint)? (f) `_plan_tool_error`'s isinstance ladder is unchanged — with
     three more callers, does the `plan_error:` safety net now hide any *new* seam error (e.g. a `store` exception
     escaping `_delete` as `PlanNotFound` "vanished between the load and the unlink")?
   - **#12 tests** (g) `forbid_store` extension: `authoring.draft_plan/interview_spec/seed_from_history`,
     `evaluation.evaluate_plan/evaluate_and_record`, `index.record_checkpoint` — what can an adapter still reach
     (e.g. `evaluation.CHECKPOINT_PHASES`, `store.load_plan_text`, module-level imports done at call time inside the
     seam)? Does forbidding `evaluation.evaluate_plan` at the *module attribute* level catch a seam that imported the
     function by name? (Note the seam calls `evaluation.evaluate_plan(...)` through the module.) (h) the real-seam
     journeys: `_ready_plan_on_disk` uses `create_study_plan` + `update_study_plan` — are the assertions on
     document bytes (`load_plan_text` before/after) and checkpoint rows (`_database_checkpoints`) the right proof of
     "writes nothing"? `test_evaluate_partial_failure_surfaces_as_warnings_on_the_real_seam` monkeypatches
     `plan_index.record_checkpoint` to return `False` — is that how the real sink fails? (i) the fresh-containers
     test mutates `first` and compares `second` to `pristine` — sound? (j) the inventory pins: in-process
     `_registry()` vs the stdio handshake — do both assert *uniqueness* and *exact* count and the nine names? Is
     `PRODUCTION_TOOL_COUNT = 32` duplicated in two test files acceptable or should one import the other? (k) is
     any of the ten mcp-server scenarios not covered by a test, or any test not in the spec?
   - **#13b persona** (l) the MCP table: nine rows + `record_plan_learning` — are the signatures in the table the
     registered schemas (compare `create_study_plan(title, answers, status="draft")` — the table omits
     `plan_id=None`; `get_study_plan` omits `history_limit`)? Does "Never replaces an existing plan: a taken id is a
     conflict" match `create_study_plan`'s behaviour? Does "missing from the inventory → that step's CLI fallback"
     give an agent a *decidable* rule (how does it know the tool is missing before calling it)? (m) the CLI fallback
     table says "No CLI command edits an existing plan's mission, topics or milestones" and "Delete: No CLI command" —
     true at `b2f37fa4` (the CLI group has `interview|list|show|new|status|milestone|evaluate|record|architect`)? Is
     "revise in the Web UI — never by hand-editing" consistent with "the Markdown document is the source of truth"?
     (n) the protocols: Session Start now says `evaluate_study_plan(plan_id, "start", study_id=STUDY_ID,
     record=True)` — where does an architect running in a Web PTY/ACP console get `STUDY_ID`? The wind-down step 6 is
     still `studyloop session end` (shell) — is a persona that mixes MCP calls and shell commands coherent for an
     agent without a shell (ACP)? (o) the "Deleting to tidy up" anti-pattern and the `delete_study_plan` row: is the
     persona's "never on a retry" compatible with the tool's "not_found before confirmation" (a retried confirmed
     delete returns `not_found:`)? (p) is anything in the persona **wrong about the tools** as registered (e.g.
     "Activation is gated: an unready plan is refused with its blockers and nothing is written" — true for
     `set_study_plan_status`; what about `update_study_plan(status="active")` on the same document, the F1 contract)?
   - **#13b tests** (q) `test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning` renders with
     `brief="- interview item one"` — does it prove the *planning purpose* path or only that the file contains the
     strings? Would it pass if `persona_mode_for` returned `"focus"` and `focus.md` happened to name the tools? (r)
     `_section` closes a `###` section at the next `#`–`###` heading — correct for the `### CLI fallback` /
     `## Session Start Protocol` layout? (s) `test_the_nine_are_the_registry_plus_exactly_what_12_lands` — after the
     merge the unregistered set is empty; does the test still assert anything about the *persona* (or only about the
     registry)? Is `_LANDING_WITH_12` now dead weight to retire? (t) `test_focus_persona_unchanged` pins a sha256 of
     the focus persona at `205819c7` with three paths fixed — robust across machines (`_REPO_ROOT` walk, `PERSONA_DIR`
     from the checkout)? (u) the manifest test loads `scripts/update-agent-manifest.py` by path and compares
     `hash_file` — does it cover the Kiro `persona.md` copy (is it in `TRACKED_FILES`)? The manifest diff moved only
     the Claude and OpenCode hashes — is the Kiro directory copy tracked by the manifest at all, and if not, what
     protects it from drift?
   - **Cross-stream** the merge `b2f37fa4` had no conflicts. Do the two streams agree on facts: the persona table's
     `not_ready:` wording vs `_plan_tool_error`'s; the persona's `record=False`/`record=True` semantics vs
     `evaluate_study_plan`'s docstring; `docs/agent-install.md`'s table vs the persona's table (both list ten rows —
     do the signatures agree)? Shared files edited by both (`tasks.md`, `.secrets.baseline`?) — coherent?
3. **Spec/doc review:** do the two delta requirements (mcp-server §"Study-plan progression and deletion tools" with
   its ten scenarios and the amended `record_plan_learning` requirement; agent-adapters §"Architect persona prefers
   the MCP plan tools" with three scenarios) match the code exactly? Anything claimed that is not shipped; anything
   shipped the specs do not say (the fold's `__cause__` chain; the `PRODUCTION_TOOL_COUNT` duplication; the
   persona's Session Start `STUDY_ID`; the "missing from the inventory" routing rule)? Is `docs/agent-install.md`'s
   section now accurate and complete (it names ten tools; does it say which harnesses actually *connect* the server
   to the architect)? Is the mcp-server spec's "with the domain error chained as `__cause__`" a testable requirement
   over the stdio transport (where the cause is not serialised)?
4. **Phase 5/6 hazards** you can see from this base — be specific:
   (i) **#14 Web "Plan with architect" journey (T5.1/T5.2):** what must the Plans-view affordance send
   (`POST /api/session/start` with `purpose: "planning"`, `topic: <subject or "">`, which `energy`/`agent`/`transport`;
   what must it do with the `201` `ws_url`) and what must the console label read from (`purpose` in the `201` body vs
   `GET /api/session/state` on reconnect; `_dashboard.py`'s `setdefault("purpose", "focus")`) so the label survives a
   refresh? What does a *CLI-started* architect (`studyloop plan architect`, no `purpose` written) show on the Web
   console after reconnect, and should #14 accept that or should the CLI writer persist `purpose=planning`? Name the
   RED tests (the task list proposes: one click → one POST with `purpose=planning`; console labelled planning and
   the label survives reconnect; brief *structure* present not wording; manual New Plan still works; one console /
   one WebSocket; conflict → the existing 409 shape with `reattach_url`; starting the architect creates no plan).
   Which of those can the Playwright fixture prove and which need the FastAPI `TestClient` + the fake agent
   (`STUDYLOOP_TEST_AGENT_CMD` / `STUDYLOOP_TEST_ACP_CMD`)? What in `plans-panel.js` / `session-timer.js` must be
   *reused* rather than duplicated so there is exactly one WebSocket listener?
   (ii) **#15 verification receipt (design §8, T6.2)** — what must `scripts/verify/plan_integration.py` record for
   Phase 4 specifically: the exact stdio inventory (32 + names) or the in-process twin; the persona test module; the
   guard; the golden; the protected-file diffs; the `rg` invariants (zero adapter imports of
   `planning.store|index|authoring|evaluation`; zero `build_canonical_persona("focus"` literals under `web/routes/session`);
   the two manifest hashes; and should it fail when `record_plan_learning`'s refusal loses its `not_ready:` prefix?
   Also T6.3's combined journey (planning-purpose Web session + MCP plan tool call in one run, no nested-event-loop
   error) — what exactly should it assert?
   (iii) **The Kiro/Claude "architect takes the CLI fallback" owner item:** at `b2f37fa4` the persona tells the architect
   to prefer nine MCP tools, but Kiro's `study-plan-architect.json` is pinned to carry **no** `mcpServers`
   (`tools: ["@builtin"]`) and Claude's frontmatter allow-list is `Read, Write, Grep, Bash` — so in those two
   harnesses, launched *from the harness*, the architect can only take the CLI fallback, while a *Web-launched*
   architect gets the canonical persona regardless. **Is this a defect (the persona promises tools the agent
   definition withholds, and the pin `test_install_agent_contracts.py:701` now encodes the wrong thing) or a
   documented boundary (the harness definitions were sealed "by design" in `d96fb9ba` and #13b was right not to
   touch them)?** Say which, who owns the fix, what the fix is (add `studyloop` to Kiro's `mcpServers` + the nine
   `mcp_studyloop_*` names to `allowedTools`, mirroring `study-mentor.json`; add the MCP tools to Claude's `tools:`
   or drop the allow-list), whether it belongs in Phase 6 T6.1 or is a Phase-4 correction, and what test pins it.
5. **Process finding:** two agents worked in parallel without seeing each other. Name the one judgment call across
   the two streams you would most want a human to have made instead, and why (candidates: the `record_plan_learning`
   wording change shipped inside the three-tools commit; the persona naming three tools before they were registered
   (`_LANDING_WITH_12`); the CLI fallback table admitting the CLI cannot revise or delete; leaving the Kiro/Claude
   tool headers untouched while the persona prefers MCP; `.secrets.baseline` refreshed by an agent).

Be concrete over complete: a file:line and a test name beat a paragraph.
