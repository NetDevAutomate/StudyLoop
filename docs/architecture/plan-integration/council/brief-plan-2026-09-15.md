# Council brief — Plan integration programme (planning round)

**Date:** 2026-09-15 · **Repo:** StudyLoop (`github.com/NetDevAutomate/StudyLoop`, `main` @ `a0272a52`) ·
**Working branch:** `fix/plan-integration-bugs` @ `3a4f6b01` (RED tests committed, no fixes yet).
**You are one independent seat.** No other seat's answer is visible to you. Answer every numbered
deliverable in §6. Disagree with the brief where the evidence warrants it.

---

## 1. What StudyLoop is (enough to reason about the code)

AuDHD-aware Socratic study mentor. `uv` workspace, Python 3.13. Two packages:

- `packages/studyloop` — FastAPI + Alpine.js/HTMX web UI (no build step), Typer/Click CLI, FastMCP
  server at `src/studyloop/mcp/tools.py` (26 tools registered via a local `@tool()` decorator; a real
  stdio handshake test `tests/test_mcp_stdio_smoke.py::test_full_handshake_list_tools_and_call` pins
  the inventory).
- `packages/agent-session-tools` — cross-agent session export/import into a shared SQLite
  `sessions.db`, a `session-db-mcp` server, and an eval harness `agent_session_tools/eval/`
  (`arms.py` with arms `mcp|cli|hybrid|frozen`, `gold.py` loading a committed 91-item DEV gold set,
  `census.py`, `metrics.py`, `receipt.py`).

Conventions that bind every change: `uv run --group dev pytest` (whole suite, `just test`); `ruff check`
+ `ruff format --check` (`just lint`); `pyright` (`just typecheck`); pre-commit runs all three plus
detect-secrets and bandit and *rejects* the commit on any failure. Commits: conventional prefix, body
explains *why*, one logical change each. Type hints required. Tests assert through the highest public
seam, never private helpers. Spec-driven: `openspec/changes/<change>/{proposal,design,tasks}.md` +
delta specs under `openspec/changes/<change>/specs/<capability>/spec.md`; normative capability specs
live in `openspec/specs/<capability>/spec.md` — relevant ones here: `active-learning-decisions`,
`mcp-server`, `web-ui`, `agent-adapters`, `cli-surface`, `live-session-orchestration`. Evidence
convention: every measured claim has a committed receipt (JSON/MD) produced by a command, never prose.
Public docs in `docs/*.md` (mkdocs). Architecture diagrams are Archify JSON specs
(`*.architecture.json`) with delivered HTML next to them.

## 2. Study Plans — what exists today on `main`

Module `packages/studyloop/src/studyloop/planning/`:
`models.py` (StudyPlan, Mission, Milestone, Checkpoint, LearningRecord, Resource; PLAN_STATUSES =
draft|active|paused|complete|abandoned), `markdown.py` (parse_plan/render_plan — Markdown with YAML
frontmatter is the **source of truth**), `store.py` (create_plan/save_plan/load_plan/list_plans/
delete_plan/list_plan_ids; atomic replace of the canonical document; PLANS_DIR_ENV), `index.py`
(SQLite derived index: reindex_all, indexed_plans, checkpoint_history, `record_checkpoint(...) -> bool`),
`authoring.py` (draft_plan, interview_spec, seed_from_history, `readiness(plan) -> dict` with
`ready/blockers/nudges`), `evaluation.py` (evaluate_plan, `evaluate_and_record`), `multiplexer.py`.

Adapters that mutate plans **directly through the store today** (the duplication #7 targets):
- CLI `src/studyloop/cli/_plan.py` (`studyloop plan list|show|new|interview|evaluate|milestone|status|
  architect`; `_print_readiness` exists; `plan status X active` — whether it gates on readiness is
  *not established*, treat as unknown).
- Web `src/studyloop/web/routes/plans.py` (REST under `/api/plans`).
- MCP: exactly one plan-writing tool, `record_plan_learning` (`mcp/tools.py:129`).

Recommendation engine `src/studyloop/learning/decision.py`: `build_now_plan(*, energy, time_minutes,
modality, interleave) -> NowPlan` (frozen dataclass: energy, time_minutes, modality, interleave,
generated_at, primary: LearningRecommendation, alternates: list[LearningRecommendation],
interleave_ratio, starter; `to_json_dict()`). Candidate sources are private functions
(`_due_card_candidates`, `_due_progress_candidates`, `_struggle_candidates`, `_continuity_candidates`,
`_transfer_candidates`, `_practice_candidates`, `_starter_candidate`), then `_score_candidates` and
`_dedupe`. **The word "plan" (Study Plan sense) appears zero times in this file.** Consumers: CLI
`cli/_now.py`, Web `web/routes/now.py` (`build_now_plan(...).to_json_dict()`), MCP `get_next_action`
(`mcp/tools.py:688`, validates energy/modality Literals then delegates; no `interleave` parameter).

Web session launch `src/studyloop/web/routes/session/_start.py`: `StartSessionRequest{topic, energy,
agent, transport: pty|acp}`; after the one-session claim it calls
`build_canonical_persona("focus", body.topic, body.energy)` — **the persona mode is hard-coded to
"focus"**. `agent_launcher.build_canonical_persona(mode, topic, energy, *, previous_notes)` resolves
`agents/shared/personas/{mode}.md`; personas present: `co-study.md`, `plan-architect.md`, `study.md`
("focus" falls through to `_default_persona`). Commit `776a9dc0` (2026-09-14) added CLI-only
`studyloop plan architect` and `studyloop study --mode plan-architect` using that same resolver.

`docs/study-plans.md` §"What a plan does not do yet" states honestly: an active plan does not bias
`studyloop now` or Today; the Web UI does not launch a planning agent; `record_plan_learning` is the
only plan-write MCP tool.

## 3. Two confirmed bugs (RED tests committed at `3a4f6b01`)

Issue #7 "Further Notes" names both as things the seam migration *must* close first.

### Bug A — activation readiness bypass (`web/routes/plans.py`)

Only the PATCH `status` path is gated:

```python
    if "status" in payload:
        status = str(payload["status"]).strip().lower()
        if status not in PLAN_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
        if status == "active":
            check = readiness(plan)
            if not check["ready"]:
                raise HTTPException(status_code=422, detail={"message": "plan is not ready to activate", **check})
        plan.status = status
```

Two other doors are not. POST `/plans` (create):

```python
        status = str(payload.get("status", "draft")).strip().lower()
        if status not in PLAN_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
        plan = draft_plan(title, answers, plan_id=..., status=status)
    try:
        create_plan(plan, overwrite=bool(payload.get("overwrite", False)))
```

PATCH with `markdown` (whole-document replacement):

```python
    if "markdown" in payload:
        replacement = parse_plan(str(payload["markdown"]), plan_id=plan.plan_id)   # (try/except 400)
        replacement.plan_id = plan.plan_id
        replacement.created = plan.created
        save_plan(replacement)
        return {"updated": True, "plan": replacement.summary(), "readiness": readiness(replacement)}
```

Observed on `main`: `POST /api/plans {"title":"Vague","status":"active","answers":{}}` → **201** with body
`"status":"active"` *and* `"readiness":{"ready":false,"blockers":[3 items]}`.

### Bug B — silent partial checkpoint recording (`planning/evaluation.py` ↔ `planning/index.py`)

```python
def record_checkpoint(evaluation: PlanEvaluation, *, study_id: str = "") -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute("INSERT INTO study_plan_checkpoints ...", (...))
        conn.commit()
        return True
    except Exception:
        logger.debug("record_checkpoint failed for %s", evaluation.plan_id, exc_info=True)
        return False
```

```python
def evaluate_and_record(plan, phase="start", *, study_id="", append_to_plan=True) -> PlanEvaluation:
    evaluation = evaluate_plan(plan, phase, study_id=study_id)
    try:
        from .index import record_checkpoint
        record_checkpoint(evaluation, study_id=study_id)          # bool discarded
    except Exception:                                             # never fires: callee swallows
        evaluation.warnings.append("checkpoint not saved to the database")
    if append_to_plan:
        try:
            plan.checkpoints.append(evaluation.to_checkpoint()); save_plan(plan)
        except Exception:
            evaluation.warnings.append("checkpoint not appended to the plan document")
    return evaluation
```

Observed: with `record_checkpoint` returning `False`, `evaluate_and_record(...).warnings == []`.

### The RED tests (verbatim; 3 fail on `main`, 2 companions pass)

```python
# tests/test_web_plans.py
def test_create_refuses_an_active_status_on_an_unready_plan(client):
    refused = client.post("/api/plans", json={"title": "Vague", "status": "active", "answers": {}})
    assert refused.status_code == 422
    detail = refused.json()["detail"]; assert detail["ready"] is False and detail["blockers"]
    assert client.get("/api/plans", params={"status": "active"}).json()["count"] == 0

def test_markdown_replacement_refuses_an_unready_active_document(client):
    plan_id = _create(client); before = client.get(f"/api/plans/{plan_id}").json()["markdown"]
    head, _, _ = before.partition("\n## Milestones")
    unready_active = head.replace("status: draft", "status: active") + "\n"
    refused = client.patch(f"/api/plans/{plan_id}", json={"markdown": unready_active})
    assert refused.status_code == 422 and refused.json()["detail"]["ready"] is False
    after = client.get(f"/api/plans/{plan_id}").json()
    assert after["plan"]["status"] == "draft" and after["plan"]["milestone_total"] == 2

# tests/test_planning_evaluation.py
def test_failed_checkpoint_db_write_is_reported_as_a_warning(monkeypatch):
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)
    result = evaluate_and_record(_plan(), "start", append_to_plan=False)
    assert any("database" in w for w in result.warnings)

def test_successful_checkpoint_db_write_adds_no_warning(monkeypatch): ...   # passes today
```

Why the "comprehensive" suite missed both: `test_patch_refuses_to_activate_an_incomplete_plan` exists
and passes, so "readiness is enforced" *looked* covered — one test per feature, not one per door.
The suite encodes what the code does, not what the spec invariant says.

## 4. The open specification — GitHub issues #7 (parent) and #8–#15 (tracer-bullet tickets)

Created 2026-09-04, label `ready-for-agent`, **nothing implemented** on `main` (verified: zero
occurrences of `PlanApplication` or any of the nine MCP tool names; `decision.py` has no plan
awareness; no `planning` purpose in the web session start).

### #7 — design (condensed but faithful)

One deep **`PlanApplication`** module — the shared seam for every Study-Plan use case. CLI, Web, MCP
and the recommendation engine use its **immutable, serialization-ready views**, **domain errors**
(no CLI/HTTP/MCP types), lifecycle changes, assessments, planning briefs and active-plan guidance,
instead of mutating documents through the store. Six cohesive operations:

1. **Browse plans** — deterministic immutable summaries, optional lifecycle filter.
2. **Inspect a plan** — structured detail, readiness, optional canonical Markdown, optional checkpoint history.
3. **Prepare planning** — ordered interview, history-derived evidence seed, existing-plan summaries (the architect's brief).
4. **Get active guidance** — transport-neutral guidance from *every* active plan: next milestone,
   normalized matching keys, target urgency, energy eligibility, completion actions, malformed-plan warnings.
5. **Apply a plan change** — explicit intent: create | revise | validated document replacement |
   lifecycle transition | milestone set | confirmed delete → load, validate, persist, return new view.
6. **Assess a plan** — preview or record a start/mid/end checkpoint, optional study id, **explicit partial-write warnings**.

Do not expose the store or mutable domain objects to adapters. No generic "do anything" action interface.

**Invariants:** Markdown authoritative (success = canonical doc atomically replaced); index refresh
best-effort/recoverable; **activation readiness-gated on every entry path incl. create-and-activate
and raw import**; multiple active plans valid; milestone mutation = explicit boolean, idempotent
(existing toggle routes may translate); revision/replacement preserve id + created, app owns updated;
create refuses duplicate ids unless privileged overwrite; deletion retains checkpoint history;
**checkpoint DB history and Markdown append stay independent, result reports either failure and never
claims complete recording after a partial one**; domain errors: not-found, invalid id, conflict,
invalid field, not-ready, invalid milestone, partial-recording; **no operation binds a live study
session to a plan** (out of scope).

**Active-plan guidance and ranking:** the engine remains the only ranker. Guidance is cheap and
plan-static. Energy low/medium/high → capability 3/6/10 vs plan `energy_floor`; defer new milestone
work below floor but keep plan-related due recall/struggle repair eligible. Match by **normalized
topic/course equality or named milestone concepts** — no broad substring. Plan-related due review and
struggle repair outrank unrelated work in the same urgency class; globally urgent reviews/fresh
struggles may still outrank a new milestone (**bias, not filter**). Synthesize a recommendation from
an eligible next milestone when no candidate represents it. Preserve ≥1 eligible plan-backed action
among primary+alternates when time/energy permit. Dedupe before attaching plan references; one action
matching several plans keeps every reference, ordered by target urgency, most recent update, plan id.
Fully-checked active plan → lifecycle guidance, not a study candidate. **No active plans → output
byte-identical to today.** Extend `NowPlan` **additively**: top-level active-plan summaries,
energy-deferred milestones, completion actions, warnings; optional explicit plan reference
(plan id + milestone id) on each recommendation — not buried in open-ended metadata. MCP
`get_next_action` gains `interleave` for parity.

**Web architect launch:** "Plan with architect" beside manual New Plan. Reuse the existing
session-start endpoint, one-session claim, agent detection/selection, PTY/ACP launch, conflict
response, WebSocket transport, reconnect, live console. Add a `planning` **session purpose** (normal
focus stays default) resolving the `plan-architect` persona + shared protocol instead of the hard-coded
`"focus"`. Build the planning brief via *prepare planning* before launch. Starting a conversation
creates **no** plan. Architect uses MCP lifecycle tools when available, CLI as harness fallback.
Manual form retained. One console, one WebSocket; persist only the purpose for labeling/reconnect.

**MCP parity — nine thin adapters over `PlanApplication`:** `list_study_plans`, `get_study_plan`,
`get_planning_interview`, `create_study_plan`, `update_study_plan`, `set_study_plan_status`,
`set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan`. Raw Markdown replacement is
import/editor, not the default agent mutation. Deletion requires explicit confirmation.

**Delivery order (spec's own):** (1) seam + views + errors + interface tests → (2) migrate CLI/Web
through it, behaviour-preserving → (3) active guidance integrated once in the engine, renderers
additive → (4) MCP tools + registration + docs → (5) planning-purpose persona resolution + Web launch
affordance → (6) reconcile public docs/installer language. Update normative specs per slice. New ADR
only if the seam or planning-purpose semantics are load-bearing and not already captured.

**Testing decisions (spec):** assert external behaviour via the highest seam; never private helper
calls, file layout, framework internals, or model prose. Interface: isolated plan dir + DB; identical
refusal across create-and-activate / transition / replacement; id+created preserved; idempotent
milestone set; multiple active plans; deletion retains history; partial checkpoint → explicit warning;
malformed plans consistent with listing. Migration parity: existing CLI/Web suites unchanged; cross-
surface equivalence tests; **architecture test forbidding CLI/Web/MCP adapters from importing
mutable store operations**. Recommendation: exact no-plan back-compat; one plan + matching due
concept; unrelated more-urgent due outranks new milestone; multiple plans, one action matching
several; milestone without concepts; energy-blocked; fully checked; exact normalized matching
(short names don't match unrelated text); additive JSON; Web Now/Today/recap/MCP still delegate.
MCP: stdio tool list requires the nine; schemas, delegation, error mapping, idempotent retries,
preview-vs-record, confirmed deletion; no duplicated policy tests. Web architect: fake agent + browser
journey, no paid model calls; planning purpose selects persona + brief; one-question protocol without
exact wording; manual fallback, conflict, reconnect labeling, structured errors; no plan created, no
live-session plan id; one addressed launch, no duplicate listener.

**Out of scope (spec):** persisting a plan id on live session state; auto-selecting a plan at session
start; auto checkpoints from session events; auto-completing milestones; hard-blocking off-plan study;
enforcing one active plan; second session authority; second PTY/ACP/WS/terminal; wholesale merge of
the archived browser-architect branch; two-way second-brain editing; provider/model selection;
scheduled autonomous planning; replacing Markdown with SQLite.

### Child tickets and their dependency edges

| # | Title | Blocked by |
|---|---|---|
| 8 | Centralize reads and activation (seam, immutable views, CLI+Web list/inspect/activate through it, identical readiness on create-and-activate / transition / imported active doc) | — |
| 9 | Centralize mutations and checkpoints (create/revise/replace/milestone/lifecycle/evaluate/delete through seam; id+created survive; idempotent milestone set; complete-vs-partial checkpoint; **architecture test**) | 8 |
| 10 | Make Now plan-aware end to end (all guidance/ranking rules above; MCP `interleave` parity) | 9 |
| 11 | MCP discovery + authoring (6 tools: list/get/interview/create/update/set_status) | 9 |
| 12 | MCP progression + deletion (3 tools: milestone/evaluate/delete; stdio list shows all nine) | 11 |
| 13 | Launch planning-purpose agent sessions (purpose param, one purpose/persona resolver for PTY+ACP, no plan created, conflict/reconnect preserved, MCP-with-CLI-fallback) | 9, 11 |
| 14 | Web architect journey (Plans view action, console labeling, brief delivered, refresh/reconnect, manual fallback, one console/WS; browser tests) | 13 |
| 15 | Reconcile release contract and verify (docs/installer/specs agree; full suite; Web+MCP journeys independently and combined; no nested-event-loop regression; #7 fully mapped) | 10, 12, 14 |

Each ticket's DoD includes: relevant suites green, normative specs + public docs updated in the same
slice, working tree clean of temp artefacts.

## 5. Second stream — the surviving result from PR #19 (`feat/knowledge-proof`)

Independent of plans; shares only the repo. The knowledge-proof programme is closed (its OKF/
ontology/sidecar half was retired by ADR-0011 on 2026-09-10; the semantic-layer programme on `main`
ran Stages 1–5 and recorded its SEALED outcome on 2026-09-15). **One established result never
merged:** `plan_prose_query` — a phrase-token OR planner — measured **+0.142 recall@5 on DEV and
+0.168 on SEALED (CI95 lower bound +0.076)** over the shipped path. The semantic-layer plan-brief
committed to "evaluate lifting `plan_prose_query`'s OR arm as the fallback (measured, not assumed)";
Stage 2 explicitly *deferred* lexical tuning (stop-word list, AND-first vs OR-first) to Stage 4 "so
the change is attributable"; the Stage 4 record contains no lexical-tuning line. Never evaluated.

Branch function (verbatim, `learning_memory/store.py`):

```python
def plan_prose_query(query: str) -> str:
    tokens: list[str] = []
    for raw_token in query.split():
        token = "".join(char for char in raw_token if unicodedata.category(char) not in _UNSAFE)  # Cc/Cs
        if any(char.isalnum() for char in token):
            tokens.append(token)
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
```

`main`'s shipped planner (`agent_session_tools/query_planner.py`): drops a STOP set and tokens with
`len(token) <= 2`, quotes each term, tries AND first, widens to OR when AND finds nothing;
`retrieval.py:plan_query(query) -> QueryPlan` routes explicit FTS5 (`fts:` prefix / uppercase operator
outside quotes) verbatim, else natural-language planning. Two behavioural deltas of the branch
function: **no stop-words** (recall widens, precision narrows) and it **neutralises explicit FTS
syntax** (so `main`'s explicit door must stay in front of it). A golden file
`tests/golden/session_search_pre_planner.json` pins current planner output.

Also dangling: `main`'s `docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md` lines 6–7 say the
branch's claim-centric learning-memory decision "stands and will be renumbered when merged", and
lines 51–52 call the learning-memory claims/evidence store "the semantic layer's prerequisite" — but
the semantic-layer programme concluded without it, and the branch's own Stage F found a fused claims
arm *hurt* recall (−0.140). The ADR needs an amendment recording the actual disposition. The PR will
be closed and its tip tagged `archive/feat-knowledge-proof-2026-09-15`; primary receipts stay
reachable via the tag.

## 6. What this council must produce — numbered, in this order

Constraints for everything below: **TDD** (RED test named and its assertion stated *before* the
implementation step), a **definition of done per task** that is checkable by a command or a test id,
**data-driven** (any claim of "works"/"faster"/"better" names the receipt or test output that proves
it), parallel execution by independent sub-agents wherever the dependency edges permit, and every
slice updates normative specs + public docs + (where structure changes) the Archify architecture spec.

1. **High-level plan.** Phases, their goals, and the parallelisation map: which tickets/sub-tasks can
   run concurrently given the edges in §4, and what the critical path is. Include the two bugs (§3)
   and the §5 stream. State explicitly where you would *deviate* from #7's delivery order and why.
2. **Implementation plan** per phase: file-level changes (paths as given above), the public
   signatures you would introduce for `PlanApplication` (views, intents, errors, guidance), how
   Bugs A and B are closed *by the seam* rather than patched in the route (or argue the reverse),
   how `NowPlan` is extended additively, how the `planning` purpose threads through
   `StartSessionRequest` → `build_canonical_persona`, and how the nine MCP tools map to the six
   operations. Flag any place the spec is under-specified or self-contradictory.
3. **Test plan** per phase: test module names, the RED test list with one-line assertions, the
   architecture test's mechanism (how to forbid adapter→store imports mechanically), the data/
   fixtures needed, and which existing suites must remain byte-identical (name them).
4. **§5 plan** for `plan_prose_query`: the pre-registered measurement (arms, gold DEV, census, what
   counts as adopt/reject, how the explicit door and the golden file are protected), and the
   ADR-0011 amendment text outline.
5. **Definition of done** for the whole programme, as a checklist a reviewer can tick from command
   output alone.
6. **Risks and pushback.** Where #7–#15 is wrong, over-built, or should be cut; where fan-out will
   cause merge pain; what you would measure to know the plan-aware `now` actually helps a learner
   rather than just passing its tests.

Format: Markdown with those six numbered H2 sections. Be concrete over complete: a named file and a
named test beat a paragraph of principle.
