# Module Contract v1 Implementation Plan — DeepSeek 3.2 seat

**Date:** 2026-10-04
**Repository:** `/Users/ataylor/code/personal/tools/studyloop`
**Proposal:** `openspec/changes/module-contract-v1/proposal.md` (commit 54d79e88)
**Verified facts:** F1-F9 confirmed via absolute path reads.

## Q1. Lanes

Propose **4 lanes**, sequenced by dependency:

| Lane | `feat/…` branch | Worktree prefix | Owned paths (fnmatch globs) | DoD items |
|------|-----------------|-----------------|---------------------------|-----------|
| **Core schema & validation** | `feat/module-contract-schema` | `mc-schema` | `packages/studyloop/src/studyloop/content/schemas.py`, `packages/studyloop/src/studyloop/cli/_module.py`, `packages/studyloop/tests/test_module_*.py`, `docs/module-contract.md` | 1, 2, 6 |
| **Runner & transient recording** | `feat/module-contract-runner` | `mc-runner` | `packages/studyloop/src/studyloop/module/runner.py`, `packages/studyloop/src/studyloop/cli/_drill.py`, `packages/studyloop/src/studyloop/doctor/*.py`, `packages/studyloop/tests/test_module_runner_*.py` | 3 |
| **Mentor delivery & transport** | `feat/module-contract-mentor-delivery` | `mc-mentor` | `packages/studyloop/src/studyloop/session/transport.py`, `packages/studyloop/src/studyloop/web/routes/session/_transport.py`, `packages/studyloop/tests/e2e/test_module_mentor_delivery.py`, `packages/studyloop/tests/integration/test_transport_integration.py` | 5 |
| **Web Labs UI & CLI install** | `feat/module-contract-web-labs` | `mc-web` | `packages/studyloop/src/studyloop/web/routes/session/_options.py`, `packages/studyloop/src/studyloop/web/static/index.html`, `packages/studyloop/src/studyloop/web/static/components.js`, `packages/studyloop/src/studyloop/web/static/js/**`, `packages/studyloop/tests/e2e/test_module_web_journey.py` | 4 (UI), 7 |

### Disjoint ownership & hotspot resolution

**F7 hotspot assignments:**
- `content/schemas.py` → **Core schema** (exclusive, not dual-owned)
- CLI registration (`cli/__init__.py`/Typer app) → **Core schema** (one registration line for `module` command group)
- `web/routes/session/_options.py` → **Web Labs UI** (adds module drills to session start options)
- Web trio (`index.html` + `components.js` + `style.css`) → **Web Labs UI** (adds Labs entry, conditional visibility)
- `mkdocs.yml`, `CHANGELOG.md`, `docs/` → **Shared** per F7 – all lanes may touch docs describing their slices; coordinator merges CHANGELOG conflicts
- `agents/kiro/*.json` → **Unchanged** (other session's edits continue)

**Avoiding F7 in-flight doc collisions:** Each lane creates worktree `mc-*` in **parent directory** of the main checkout (`/Users/ataylor/code/personal/tools/studyloop-mc-schema`), not sibling. Git config `core.worktree` points to that isolated copy. `CHANGELOG.md` and `docs/` are **copied once** at lane start via `git show HEAD:CHANGELOG.md > CHANGELOG.lane.md`. Lane commits to its copy; coordinator merges back at integration.

**Forbidden paths per lane:**
- Core schema: `packages/studyloop/src/studyloop/module/runner.py` (belongs to runner lane)
- Runner: `packages/studyloop/src/studyloop/web/static/js/**` (belongs to web lane)
- Mentor delivery: `packages/studyloop/src/studyloop/cli/_module.py` (belongs to core schema)
- Web Labs: `packages/studyloop/src/studyloop/content/schemas.py` (belongs to core schema)

## Q2. Merge DAG and strategic commits

**Dependency order:** Core schema → Runner → (Mentor delivery // Web Labs) → integration.

**Per-lane commit sequence (max 6 bisectable commits):**

### Core schema lane (`feat/module-contract-schema`)
1. **Add manifest `ModuleManifest` model + fields §5.2**
   Gate: `just lint typecheck`
   Evidence: `test_module_manifest_validation.py` passes on scaffold YAML
2. **Extend `PracticeDeck`/`PracticeTask`/`PracticeVerification` with ★ fields §5.3**
   Gate: `just lint typecheck test`
   Evidence: `test_content_schemas.py` validates new fields, `extra: forbid` maintained
3. **Implement `studyloop module check` MC001–MC016**
   Gate: `just lint typecheck test`
   Evidence: `test_module_check.py` passes on scaffold, fails on fixture violations
4. **Add `studyloop module new` scaffold**
   Gate: `just lint typecheck test`
   Evidence: `test_module_new.py` creates passing offline drill
5. **Write contract doc + PR template**
   Gate: `just docs spec-check`
   Evidence: `docs/module-contract.md` exists, `test_docs_drift.py` passes
6. **Integrate manifest into CLI registration & lockfile stub**
   Gate: `just preflight`
   Evidence: `studyloop module --help` shows subcommands, `modules.lock.json` schema defined

### Runner lane (`feat/module-contract-runner`)
1. **Implement `ModuleRunner` with argv+digest consent §5.5**
   Gate: `just lint typecheck`
   Evidence: `test_module_runner_argv.py` rejects shell operators (MC015)
2. **Add clean environment + per‑phase timeouts**
   Gate: `just lint typecheck test`
   Evidence: `test_module_runner_env.py` shows scrubbed env, timeout caps
3. **Wire `studyloop drill <phase>` CLI**
   Gate: `just lint typecheck test`
   Evidence: `test_cli_drill.py` runs echo‑based scaffold drill end‑to‑end
4. **Implement transient‑only recording path**
   Gate: `just lint typecheck test`
   Evidence: `test_module_runner_recording.py` proves no `confident`/`struggling` observation written
5. **Add k8s disposable cluster plumbing**
   Gate: `just lint typecheck test integration` (requires Docker)
   Evidence: `test_module_kind_integration.py` creates/destroys cluster
6. **Add prerequisite enum probes §5.4**
   Gate: `just lint typecheck test`
   Evidence: `test_doctor_module_prereqs.py` reports docker/kind/kubectl

### Mentor delivery lane (`feat/module-contract-mentor-delivery`)
1. **Design spike: read transport code (`_transport.py`, `transport.py`)**
   Gate: none (read‑only)
   Evidence: analysis document `docs/mentor-delivery-spike.md`
2. **Define `practice_check` envelope schema**
   Gate: `just lint typecheck`
   Evidence: Pydantic model in `packages/studyloop/src/studyloop/module/mentor.py`
3. **Implement PTY‑side delivery**
   Gate: `just lint typecheck test integration`
   Evidence: `test_transport_pty_delivery.py` shows envelope reaches mentor
4. **Implement ACP‑side delivery**
   Gate: `just lint typecheck test integration`
   Evidence: `test_transport_acp_delivery.py` shows envelope reaches mentor
5. **Integration test: both transports**
   Gate: `just test integration`
   Evidence: `test_module_mentor_delivery.py` passes for PTY and ACP
6. **Add failure reporting**
   Gate: `just lint typecheck test`
   Evidence: `test_module_delivery_failure.py` logs delivery errors

### Web Labs UI lane (`feat/module-contract-web-labs`)
1. **Extend session options API with module drills**
   Gate: `just lint typecheck test-js`
   Evidence: `test_web_session_options.py` includes `module` drills
2. **Add Labs entry hidden when no module installed**
   Gate: `just lint typecheck test-js`
   Evidence: `test_web_labs_visibility.js` shows/hides based on `modules.lock.json`
3. **Implement drill start/cancel in existing terminal**
   Gate: `just lint typecheck test-js`
   Evidence: `test_web_labs_start.js` triggers `studyloop drill setup`
4. **Playwright journey: list→start→cancel**
   Gate: `just e2e` (one journey)
   Evidence: `test_module_web_journey.py` passes with screenshots
5. **Integrate Bruno's kdrill conversion validation**
   Gate: `just lint typecheck test integration`
   Evidence: kdrill‑converted deck passes `module check`, fails missing‑field fixtures
6. **Live proof under `STUDYLOOP_LIVE=1`**
   Gate: `just testacc` (requires kind)
   Evidence: `test_module_kdrill_live.py` passes one live drill

## Q3. Test plan per DoD item 1–7

**Item 1: Schema fields**
- **Unit**: `test_content_schemas.py` – validates ★ fields, `extra: forbid`
- **CLI**: `test_cli_module_new.py` – scaffold validates
- **Acceptance**: `test_module_schema_acceptance.py` – manifest YAML round‑trip
- **R4 defeat**: `test_module_schema_fixtures.py` – fixture with missing `id` fails validation

**Item 2: `module check`**
- **Unit**: `test_module_check.py` – MC001–MC016 per rule
- **CLI**: `test_cli_module_check.py` – exit codes, `--json` output
- **Fixture set**: `tests/fixtures/module/invalid-*.yaml` – one file per violation
- **R4 defeat**: `test_module_check_fails_on_violation.py` – each fixture fails named rule

**Item 3: Runner**
- **Unit**: `test_module_runner_*.py` – argv, env, timeouts, consent
- **CLI**: `test_cli_drill.py` – `studyloop drill` phases
- **Integration**: `test_module_runner_integration.py` – full echo‑drill lifecycle
- **R4 defeat**: `test_module_runner_no_observation.py` – proves no `confident`/`struggling` row written

**Item 4: `module add` + Web listing**
- **CLI**: `test_cli_module_add.py` – copies, validates, writes lockfile
- **API**: `test_web_module_api.py` – `GET /api/modules` lists installed
- **E2E**: `test_module_web_journey.py` – Playwright: list→start→cancel
- **Acceptance**: `test_module_add_acceptance.py` – real directory copy

**Item 5: Mentor delivery**
- **Integration**: `test_transport_pty_delivery.py`, `test_transport_acp_delivery.py`
- **E2E**: `test_module_mentor_delivery.py` – both transports in hermetic server
- **R4 defeat**: `test_module_delivery_failure.py` – delivery error surfaced

**Item 6: Contract doc**
- **Unit**: `test_docs_drift.py` – examples resolve
- **Doc test**: `docs/module-contract.md` – `just docs` builds without warnings
- **PR template**: `/.github/pull_request_template/module-contract.md` exists

**Item 7: kdrill conversion proof**
- **CLI**: `test_module_kdrill_conversion.py` – converted deck passes `check`
- **Integration**: `test_module_kdrill_live.py` – `STUDYLOOP_LIVE=1` against disposable kind cluster
- **Acceptance**: `test_module_kdrill_acceptance.py` – full live drill, deletes only created resources

## Q4. Representative user testing

**Persona 1: AuDHD learner on tablet over `--lan`**
- Device: iPad Safari, touch interface, variable focus
- Journey: `test_journey_audhd_tablet.py`
- Steps:
  1. Load `/` – Labs hidden (no modules)
  2. SSH to host, `studyloop module add /path/to/kdrill`
  3. Refresh – Labs appears
  4. Tap Labs → list drills
  5. Start drill → terminal appears
  6. Type incorrect command → tap Check progress (v1.1 stub)
  7. Cancel → confirmation dialog
  8. Reload page – session recovers
- Marker: `e2e` (hermetic server, fake agent)
- Runtime budget: 90 seconds
- Artifacts: screenshot each step, console errors, HTML snapshot
- Pass: All steps complete, no JS errors, CSP headers present

**Persona 2: New contributor from clean machine**
- Context: Fresh Ubuntu VM, following docs
- Journey: `test_journey_new_contributor.py`
- Steps:
  1. `git clone`, `just sync-dev`
  2. `studyloop module new kubernetes-drills`
  3. `cd` into scaffold, edit `decks/pods.json`
  4. `studyloop module check .` – passes
  5. Add invalid YAML (missing `id`) – check fails with MC014
  6. Fix, `studyloop module add .`
  7. `studyloop drill setup kubernetes-drills/pods/pods‑01`
  8. Verify consent shows digest
- Marker: `integration` (real subprocess, no browser)
- Runtime budget: 120 seconds
- Artifacts: Command output, exit codes, `modules.lock.json` diff
- Pass: All commands exit 0, lockfile written, consent shown

**Persona 3: Keyboard‑centric power user**
- Context: Neovim user, prefers keyboard shortcuts
- Journey: `test_journey_keyboard_navigation.py`
- Steps:
  1. Load page, `Tab` to Labs (visible)
  2. `Enter` to expand, arrow keys navigate drill list
  3. `Enter` to start, focus moves to terminal
  4. Type `kubectl get pods`, `Ctrl+R` refresh
  5. `Esc` to focus management sidebar, `Tab` to cancel button
  6. `Enter` to cancel, confirm with `y`
- Marker: `e2e` + `accessibility` custom marker
- Runtime budget: 60 seconds
- Artifacts: Focus‑traversal log, ARIA attribute snapshot
- Pass: Focus never lost, all actions keyboard‑only, aria‑live regions announce changes

## Q5. Fan‑out and council schedule

**Concurrent agents:** 3 (implementer per lane, no dedicated test‑author/reviewer roles). Each lane's implementer writes its own tests.

**Agent briefs per role:**
- **Core schema implementer**: "Implement §5.2‑5.3 schema fields, `module check`, scaffold, docs. Follow F8 seam: `PracticeTask`/`PracticeVerification` are `extra: forbid`. Gate every commit with `just preflight`. Do not touch runner code."
- **Runner implementer**: "Implement §5.5 runner with argv‑only, clean env, per‑phase consent, transient recording. Use `session/transport.py` seam. Prove no observation written. After schema lane merges, rebase."
- **Mentor delivery implementer**: "Design spike first, then implement `practice_check` envelope delivery to PTY/ACP transports. Use `web/routes/session/_transport.py` and `session/transport.py`. Integration test both transports."
- **Web Labs implementer**: "Wait for runner + mentor delivery. Implement Labs UI: hidden when no module, list drills, start/cancel in existing terminal. One Playwright journey. Use `web/routes/session/_options.py`."

**Council‑of‑models review milestones:**
1. **Schema design review** – before Core schema commit 1
   Review: Manifest fields, ★‑field additive vs breaking, `extra: forbid` maintenance
   Not for: Implementation details, test coverage
   Evidence: Schema PR diff, fixture violation set

2. **Runner security review** – before Runner commit 1
   Review: argv‑without‑shell, digest‑bound consent, environment scrubbing, disposable k8s boundary
   Not for: UI polish, error messages
   Evidence: Runner code, `test_module_runner_security.py` adversarial probes

3. **Transport delivery review** – before Mentor delivery commit 3
   Review: `practice_check` envelope shape, PTY/ACP delivery paths, failure reporting
   Not for: Browser‑check consent (v1.1)
   Evidence: Spike analysis, integration test results

4. **Integration sign‑off** – after all lanes merge
   Review: End‑to‑end flow schema→check→runner→delivery→UI, kdrill conversion proof
   Not for: Individual bug fixes
   Evidence: Full test matrix results, Playwright traces, live‑drill evidence

## Q6. Risks

**Top 5 risks (R1‑R8):**

1. **R1 Mentor‑delivery transport unverified** – Design spike before implementation (Q5 milestone 3). Detection: Spike doc must answer "how does runner result reach mentor PTY/ACP?"
   Mitigation: Proof‑of‑concept integration test before any UI work.

2. **R4 Agent‑written tests pass trivially** – Fixture set `invalid-*.yaml` for each MC rule; test fails named rule. Detection: `test_module_check_fails_on_violation.py` asserts each fixture fails.
   Mitigation: Test‑first: write failing fixture, implement check, verify passes.

3. **R3 Hotspot collisions** – Worktree isolation (parent directory), copy‑at‑start for shared docs. Detection: Lane‑ownership guard re‑keyed to `feat/` prefix, not `lane/m`.
   Mitigation: Guard runs in CI, violations fail build.

4. **R2 Runner security** – Adversarial review before merge (Q5 milestone 2). Detection: `test_module_runner_security.py` probes argv injection, env leakage, digest mismatch.
   Mitigation: Council security review with dedicated adversarial prompt.

5. **R5 Playwright flakiness** – Use existing hermetic harness (`_env.py`), explicit timeouts per e2e module. Detection: Flaky test detection in CI, screenshot on failure.
   Mitigation: One journey per persona, not exhaustive UI coverage.

## Q7. Effort and critical path

**Agent‑hours per lane:**
- Core schema: 12 h (schema, validation, docs)
- Runner: 16 h (security‑sensitive, k8s integration)
- Mentor delivery: 10 h (spike + implementation)
- Web Labs: 8 h (UI, one journey)
- **Total: 46 h** (within proposal's 40‑50 h range)

**Critical path calendar days** (4 concurrent agents, 2 owner‑review hours/day):

```
Day 1‑3: Core schema (merge)
Day 4‑7: Runner (depends on schema)
Day 4‑6: Mentor delivery (parallel with runner)
Day 7‑9: Web Labs (depends on runner + mentor delivery)
Day 10: Integration, kdrill live proof
```
**Critical path: 10 calendar days**

**Cut for one‑week acceleration:** Web Labs UI slice (Labs entry, drill start) → defer to v1.1. MVP ships with CLI‑only execution; browser journey removed. Saves 8 h, reduces to **8 calendar days**.

## Q8. Where will the other planners be wrong?

**Expected divergence:** Over‑partitioning into 6‑7 micro‑lanes (e.g., separate `check` lane, separate lockfile lane). This adds coordination overhead without parallelization benefit – schema validation depends on manifest fields; lockfile depends on check passing. My 4‑lane structure maximizes parallel work while respecting true dependencies.

**Why I reject micro‑lanes:** The proposal's DoD items are intentionally sequenced (item 1 ships first). Splitting `check` from schema forces a "schema‑only" merge that cannot validate anything, breaking the "validate the day item 1 merges" promise to Bruno. My lanes deliver cohesive vertical slices.

## Q9. What does this brief get wrong?

**Fact F10 inaccurate:** `kiro-cli chat --list-models` is not a StudyLoop command (I verified). StudyLoop itself has no `--list-models`. Agent selection is via harness registry (`RELEASE_HARNESSES`), not model‑family enumeration. The constraint "at most four agents run concurrently" stands, but the model‑listing claim is wrong.

**Missing fact:** `web/routes/session/_options.py` already includes a `modules` key returning empty list – the seam exists, not new. File: `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/web/routes/session/_options.py:142` shows `"modules": []`.

**Contradiction:** C2 forbids `lane/…` but F4 says ownership guard keys off `lane/m<n>-`. The guard must be re‑keyed to `feat/…` prefixes – not mentioned in mitigation. This is a material implementation detail.

---
Critical path: 10 calendar days
Plan verdict: build as proposed – 4‑lane structure balances parallelism with dependency respect, delivers MVP in owner's bandwidth.
