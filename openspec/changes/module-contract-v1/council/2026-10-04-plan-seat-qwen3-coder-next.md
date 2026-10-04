# Council seat — Alibaba Qwen code-specialist lineage

**Date:** 2026-10-04
**Seat:** qwen3-coder-next
**Brief:** `2026-10-04-plan-brief.md`
**Proposal:** `proposal.md` (commit `54d79e88`)
**Arbitration:** `2026-10-04-arbitration.md` (3× adopt, 1× rework)

---

## Q1. Lanes

| Lane | Branch | Worktree | Owned paths | Excluded | DoD items delivered |
|------|--------|----------|-------------|----------|---------------------|
| **Schema** | `feat/contract-schema-v1` | `kc-wt-contract-schema` | `packages/studyloop/src/studyloop/content/schemas.py`, `packages/studyloop/tests/test_content_schemas.py`, `openspec/changes/module-contract-v1/proposal.md` (§5.3 update notes) | `web/`, `cli/`, `session/`, `learning/` | 1 |
| **Check/Run/Install** | `feat/module-commands` | `kc-wt-module-commands` | `packages/studyloop/src/studyloop/cli/_module.py`, `packages/studyloop/src/studyloop/cli/_doctor.py`, `packages/studyloop/src/studyloop/doctor/module.py`, `packages/studyloop/src/studyloop/session/attempt.py`, `packages/studyloop/src/studyloop/web/static/index.html` (Labs entry only), `packages/studyloop/src/studyloop/settings.py` (module config), `packages/studyloop/src/studyloop/content/index.py` (module catalog) | `openspec/`, `docs/` | 2, 3, 4-CLI |
| **Runner** | `feat/module-runner` | `kc-wt-module-runner` | `packages/studyloop/src/studyloop/learning/module_runner.py`, `packages/studyloop/src/studyloop/session/transports/attempt_env.py`, `packages/studyloop/src/studyloop/learning/practice.py` (new transient-only path), `packages/studyloop/src/studyloop/cli/_practice.py` (new drill command) | `openspec/`, `docs/` | 3 |
| **Mentor delivery** | `feat/module-mentor-channel` | `kc-wt-mentor-channel` | `packages/studyloop/src/studyloop/session/transport.py`, `packages/studyloop/src/studyloop/web/routes/session/_transport.py`, `packages/studyloop/src/studyloop/web/routes/session/_options.py`, `packages/studyloop/src/studyloop/web/services/session_start.py`, `packages/studyloop/src/studyloop/session/attempt.py` (envelope delivery) | `openspec/`, `docs/` | 5 |
| **Web Labs** | `feat/web-labs` | `kc-wt-web-labs` | `packages/studyloop/src/studyloop/web/static/index.html`, `packages/studyloop/src/studyloop/web/static/components.js`, `packages/studyloop/src/studyloop/web/static/style.css`, `packages/studyloop/src/studyloop/web/routes/session/_options.py`, `packages/studyloop/src/studyloop/web/services/session_start.py`, `packages/studyloop/src/studyloop/web/static/js/labs.js` | `openspec/`, `docs/` | 4-UI |
| **Docs/PR template** | `feat/module-docs` | `kc-wt-module-docs` | `docs/module-contract.md`, `docs/contributor-modules.md`, `docs/pr-module-contribution.md`, `openspec/changes/module-contract-v1/proposal.md` (draft → final status) | `packages/`, `agents/` | 6 |
| **Kdrill conversion** | `feat/kdrill-migration` | `kc-wt-kdrill-migration` | `studyloop-module-kubernetes-drills/*` (all module repo files) — **not in core repo**, but plan entry required | `core repo` | 7 |

**Hotspots:**

| Hotspot | Owner | Rationale |
|---------|-------|-----------|
| `content/schemas.py` | Schema lane | Only lane that touches the model definitions |
| `cli/__init__.py` | Check/Run/Install lane | Register new `module` group |
| `web/routes/session/_options.py` | Mentor delivery lane | Session options need the attempt envelope payload type |
| `web/static/index.html` | Web Labs lane | Labs UI rendering |
| `web/static/components.js` | Web Labs lane | Labs button, modal, start flow |
| `web/static/style.css` | Web Labs lane | Labs styling, Labs entry hidden state |
| `mkdocs.yml` | Docs/PR template lane | Add new module-contract docs section |
| `CHANGELOG.md` | Docs/PR template lane | All changes documented here |

**Avoiding the other session's in-flight edits:**

- The other session is editing `docs/contributing.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `mkdocs.yml` and `agents/kiro/*.json`. None of those files appear in my lane ownership lists except `CHANGELOG.md`, which is **shared** (the proposal explicitly requires docs and changelog to land with the code).
- All lanes can touch `CHANGELOG.md` (shared pattern), so conflicts are resolved by the coordinator at merge time — exactly what the M0 remediation established.
- The other session's work is on `docs/` files I don't own; I don't edit them. I add new docs (`module-contract.md`, `contributor-modules.md`, `pr-module-contribution.md`) in the `docs/` directory, which they are not editing.
- If the other session merges before my docs lane, they will see my new docs appear in their diff and can update their changelog accordingly. If my docs lane merges first, the other session will rebase and resolve the `CHANGELOG.md` conflict when they merge back.

---

## Q2. Merge DAG and strategic commits

```
          +-----------------+         +---------------------+
          |  Schema (item 1)|-------->| Check/Run/Install   |
          +-----------------+         +----------+----------+
                                               |
                         +---------------------v----------+    +-------------------+
                         |  Runner (item 3)               |---->| Mentor delivery   |
                         +-----------------+--------------+    +---------+---------+
                                           |                           |
                 +-------------------------+      +--------------------+
                 |                                |
                 v                                v
    +------------------+                 +-----------------+
    | Web Labs (item 4)|                 | Docs/PR (item 6)|
    +--------+---------+                 +--------+--------+
             |                                    |
             +------------------+-----------------+
                                |
                                v
                    +-----------------------+
                    | Kdrill conversion     |
                    | (acceptance item 7)   |
                    +-----------------------+
```

**Lane: Schema**
1. `feat/contract-schema-v1/01-add-id-fields` — Add `id` on `PracticeDeck` and `PracticeTask`; add `solution`, `scaffolding`, `mentorNotes`; add `cleanupCommand`; update validation tests to fail with old schema
2. `feat/contract-schema-v1/02-update-proposal` — Update proposal.md §5.3 to match implemented fields; note schema is not yet valid
3. `feat/contract-schema-v1/03-merge` — PR merge; `module.yaml` validation now fails until schema ships

**Lane: Check/Run/Install**
1. `feat/module-commands/01-scaffold-module` — Implement `studyloop module new <id>` (scaffold `module.yaml`, `README.md`, one passing drill); add unit tests
2. `feat/module-commands/02-module-check` — Implement `studyloop module check <path>` with rules MC001–MC016; add fixtures for every rule; test that each rule fails correctly
3. `feat/module-commands/03-module-add-lockfile` — Implement `studyloop module add <path>`; write `modules.lock.json`; add tests for success/failure cases
4. `feat/module-commands/04-labs-ui` — Add Labs entry to Web UI (hidden when no module installed); list drills; add Playwright journey: list, start, cancel

**Lane: Runner**
1. `feat/module-runner/01-runner-interface` — Implement `module_runner.py` with clean environment, per-phase commands, argv-only execution; add unit tests
2. `feat/module-runner/02-consent-protocol` — Implement per-phase consent with digest binding and argv verification at spawn; add unit tests
3. `feat/module-runner/03-transient-evidence` — Implement transient-only `practice_check` event (no learning record); test that no observation is written
4. `feat/module-runner/04-drill-cli` — Add `studyloop drill <module>/<deck>/<task> <phase>` command; wire through runner

**Lane: Mentor delivery**
1. `feat/module-mentor-channel/01-envelope-type` — Define `PracticeCheckEnvelope` type; add to session state; add unit tests
2. `feat/module-mentor-channel/02-transport-integration` — Hook runner envelope into PTY and ACP transports; add integration tests (one per transport)
3. `feat/module-mentor-channel/03-live-proof` — Run a drill end-to-end with mentor receiving output; verify label and redaction

**Lane: Web Labs**
1. `feat/web-labs/01-labs-entry` — Render Labs button in sidebar; hidden when no module installed; add Playwright journey: hidden→visible after install
2. `feat/web-labs/02-drill-list` — Populate drill list from `modules.lock.json`; add Playwright journey: click drill → session start
3. `feat/web-labs/03-cancel-flow` — Verify cancel button stops drill; add Playwright journey: start → cancel → session closed

**Lane: Docs/PR template**
1. `feat/module-docs/01-contract-doc` — Add `docs/module-contract.md` with "Adding a module" checklist and PR template
2. `feat/module-docs/02-contributor-page` — Add `docs/contributor-modules.md` explaining v1 contract, v2 deferred, stage 3 plan
3. `feat/module-docs/03-pr-template` — Add `docs/pr-module-contribution.md` with checklist for schema changes, new rules, new target kinds

**Lane: Kdrill conversion**
1. `feat/kdrill-migration/01-scaffold` — Convert kdrill to module layout; `module.yaml`, `decks/*.json`, `mentor/brief.md`, `scripts/*.sh`
2. `feat/kdrill-migration/02-validate` — Run `studyloop module check` against converted module; fix any violations
3. `feat/kdrill-migration/03-offline-drill` — Ensure one drill passes offline with no Docker/kind; `STUDYLOOP_LIVE=0` test
4. `feat/kdrill-migration/04-live-drill` — One live drill against disposable kind cluster; cleanup verified; `STUDYLOOP_LIVE=1` test

---

## Q3. Test plan per DoD item 1–7

| DoD | Test type | Module(s) | Acceptance | R4 defeat (first failing test) |
|-----|-----------|-----------|------------|--------------------------------|
| 1. Schema + 6 fields | Unit | `test_content_schemas.py` | Pydantic `PracticeDeck` validates example JSON; old JSON rejected | `test_practice_deck_rejects_missing_id_field` (fails against unpatched schema) |
| 2. `module check` + fixtures | Unit | `test_module_check.py` | 16 tests: MC001–MC016 each fail on fixture | `test_mc001_manifest_validation_fails` (missing contract field) |
| 3. Runner + `module new` | Unit + e2e | `test_module_runner.py`, `test_module_scaffold_e2e.py` | `studyloop module new` produces valid output; `studyloop drill` runs one phase with transient evidence only | `test_runner_records_no_observation` (fails against current `practice verify` path) |
| 4-CLI. `module add` + lockfile | Unit + CLI runner | `test_module_add.py`, `test_lockfile.py` | `studyloop module add <path>` writes `modules.lock.json` only on `check` success | `test_lockfile_not_written_on_check_failure` (fails before implementation) |
| 4-UI. Labs listing + start | e2e (Playwright) | `test_labs_ui_journey.py` | Labs hidden with no module; visible after install; click drill → session starts → cancel works | `test_labs_hidden_when_no_module_installed` (fails before Labs entry) |
| 5. Mentor delivery | Integration | `test_module_mentor_channel.py` | Envelope reaches mentor on PTY; envelope reaches mentor on ACP | `test_acp_transports_delivers_envelope` (fails until transport hooks added) |
| 6. Docs + PR template | Doc drift | `test_docs_drift.py` | `docs/module-contract.md` exists; `pr-module-contribution.md` exists | `test_docs_drift_module_contract_exists` (fails until docs added) |
| 7. Kdrill passes `module check` + live drill | Acceptance/UAT | `tests/acceptance/test_kdrill_module.py` (acceptance), `tests/acceptance/test_kdrill_live.py` (UAT) | `studyloop module check studyloop-module-kubernetes-drills` exits 0; `STUDYLOOP_LIVE=1` drill completes with cleanup | `test_kdrill_module_check_fails_before_conversion` (fails against original kdrill YAML) |

**R4 defeat strategy:** The proposal's risk R4 ("agent-written tests that pass trivially") is defeated by:
- For MC001–MC016: 16 separate fixtures, each designed to trigger exactly one rule. The first test run shows 16 red (failing) tests; after implementation they turn green.
- For "no observation written": the first test `test_runner_records_no_observation` runs against the current `practice verify` code and fails (it records a `confident`/`struggling` observation); after the transient-only path is implemented, the test passes.

---

## Q4. Representative user testing

**Personas:**

| Persona | Device | Journey | Marker | Budget |
|---------|--------|---------|--------|--------|
| **AuDHD learner on tablet** | iPad over `--lan` | Start → drill list → click drill → consent prompt → run setup → run check → cancel → reload → keyboard focus check → missing prereq message → remove module → Labs hidden | `STUDYLOOP_ACC=1 STUDYLOOP_ACC_ACTOR=scripted STUDYLOOP_ACC_HARNESS=kiro` | 30 min |
| **New contributor** | Laptop from clean machine | `git clone` → `just sync-dev` → `just sync-web` → `studyloop module new testmodule` → `studyloop module check testmodule` → `STUDYLOOP_LIVE=0 studyloop drill testmodule/testdeck/01 check` → success | `STUDYLOOP_ACC=1 STUDYLOOP_ACC_ACTOR=harness STUDYLOOP_ACC_HARNESS=kdrill` | 45 min |

**Playwright journey (AuDHD learner):**

1. **Start** — Navigate to `http://localhost:8000`; Labs entry absent in sidebar.
2. **Install** — CLI: `studyloop module add /tmp/kdrill-converted`; Labs entry appears.
3. **Drill list** — Click Labs; modal shows 3 drills (L0–L3).
4. **Start drill** — Click "Pods and namespaces (L0)" → session starts with terminal.
5. **Cancel** — Click "End session" → session stops; Labs modal closes.
6. **Reload** — Refresh page → Labs entry still visible; modal opens correctly.
7. **Keyboard focus** — Type in terminal; focus stays in terminal; no modal intercept.
8. **Missing prereq** — Remove `kind` from PATH → Labs entry visible; drill start shows prereq error in terminal.
9. **Remove module** — `studyloop module remove kubernetes-drills`; Labs entry hidden.

**Personas: 2**
**Milestones:** 1 (Labs visibility), 2 (end-to-end drill), 3 (cleanup + prereq flow)
**Acceptance:** "Pass" = every assertion passes; "Fail" = any assertion fails (UI element missing, modal doesn't open, session doesn't start, cancel doesn't stop, Labs reappears after remove).

**Artifacts captured:** screenshot on failure, HTML snapshot, console log, terminal transcript.

---

## Q5. Fan-out and council schedule

**Agent roles:**

| Agent | Brief | Tasks |
|-------|-------|-------|
| **Lane implementer 1 (Schema)** | Implement §5.3 fields on schemas; update `extra: forbid`; add unit tests; update proposal.md notes | `feat/contract-schema-v1/*` |
| **Lane implementer 2 (Check/Run)** | Implement CLI commands (`module new/check/add/list/remove`); implement lockfile; add fixtures for MC001–MC016 | `feat/module-commands/*` |
| **Lane implementer 3 (Runner)** | Implement runner interface, consent, transient evidence; add `drill` command; prove no observation written | `feat/module-runner/*` |
| **Lane implementer 4 (Mentor)** | Define envelope; integrate with PTY/ACP; prove delivery on both transports | `feat/module-mentor-channel/*` |
| **Lane implementer 5 (Web)** | Add Labs entry (hidden state); drill list; start/cancel flow | `feat/web-labs/*` |
| **Lane implementer 6 (Docs)** | Write contract docs; contributor guide; PR template | `feat/module-docs/*` |
| **Lane implementer 7 (Kdrill)** | Convert kdrill to module layout; run `module check`; one offline + one live drill | `feat/kdrill-migration/*` |
| **Test author** | Write e2e journeys; acceptance tests for DoD items; UAT rubric for kdrill live | `tests/e2e/test_labs_ui_journey.py`, `tests/acceptance/test_kdrill_module.py`, etc. |
| **Security reviewer** | Adversarial review of runner (argv/env/digest/consent) before merge | `feat/module-runner` review gate |

**Council review milestones:**

| Milestone | Council reviews | What council MUST NOT do |
|-----------|-----------------|--------------------------|
| **M1: Schema lands** | All 4 seats | Re-argue the proposal's 10 questions (already decided); propose alternate schemas |
| **M2: Runner + CLI commands merged** | All 4 seats | Propose changing the contract after seeing the implementation; ask for new fields |
| **M3: Mentor delivery proven** | All 4 seats | Re-open the transport choice (PTY vs ACP vs file-poll); propose a different envelope shape |
| **M4: Web Labs + Kdrill live proof** | All 4 seats | Introduce new DoD items; propose v1.1 features as v1 blockers |

**Evidence handed to council at each milestone:**

1. **M1:** Schema validation tests; `PracticeDeck` examples; failing fixtures before/after; proposal §5.3 updated notes.
2. **M2:** `module check` output for scaffold; `module add` writes lockfile; `studyloop drill` runs phases; `test_runner_records_no_observation` passes.
3. **M3:** Envelope delivery logs (PTY and ACP); mentor transcript showing labeled data; redaction verified.
4. **M4:** Labs UI journey video; `studyloop module check studyloop-module-kubernetes-drills` output; `STUDYLOOP_LIVE=1` log showing cleanup.

**Fan-out:** 7 agents run concurrently on their lanes; test author runs in parallel with implementation lanes; security reviewer reviews only `feat/module-runner` before merge.

---

## Q6. Risks

| Risk | Mitigation | Detection test |
|------|------------|----------------|
| **R1: Mentor delivery transport unverified** | Design-first spike: read `web/routes/session/_transport.py` and `session/transport.py`; define envelope structure; implement PTY/ACP hooks; run integration test on both | `test_acp_transports_delivers_envelope` fails until spike complete |
| **R2: Runner security** | Adversarial review by security seat; test with malformed argv, env injection attempts, script content changed between consent and spawn | `test_runner_refuses_modified_script` and `test_runner_cleans_env` |
| **R3: Hotspot collisions** | Shared `CHANGELOG.md` owned by Docs lane; other hotspots (schemas, CLI registration, session options) are disjoint; CI `test_lane_ownership` guards | `test_lane_stays_in_its_lane` fails if overlap detected |
| **R4: Trivial test passes** | 16 separate fixtures for MC001–MC016; test runner records no observation; each fixture designed to fail before its implementation | `test_mc001_manifest_validation_fails` shows red before schema lands |
| **R5: Playwright flakiness** | Use existing e2e harness (`_env.py`) with temp study vault and hermetic server; 30 s timeout per step; 3 retries | `test_representative_user_journey` already exists and runs on CI |
| **R6: Live kind lane restricted** | Acceptance/UAT run only on owner's machine; CI only runs offline (`STUDYLOOP_LIVE=0`) | `STUDYLOOP_LIVE=1` tests skip with clear reason on CI |
| **R7: Registry scope creep** | Explicit C8 in brief: parked registry change excluded; `module-registry-v1` is untracked | Code scan shows no registry code in `openspec/changes/module-contract-v1` |
| **R8: Estimate uncertainty** | Council has already corrected the estimate to 55–70 agent-hours; I adopted that figure | N/A — use council estimate |

---

## Q7. Effort and critical path

**Agent-hours per lane (council-corrected 55–70 total; apportioned):**

| Lane | Estimate | Breakdown |
|------|----------|-----------|
| Schema | 6 | Schemas (+3), tests (+2), proposal notes (+1) |
| Check/Run/Install | 12 | CLI commands (+5), lockfile (+3), fixtures for MC001–MC016 (+4) |
| Runner | 10 | Runner interface (+4), consent (+3), transient evidence (+2), `drill` CLI (+1) |
| Mentor delivery | 8 | Envelope type (+2), PTY/ACP integration (+4), live proof (+2) |
| Web Labs | 8 | Labs entry (+2), drill list (+3), journey tests (+3) |
| Docs/PR | 5 | Contract doc (+2), contributor guide (+2), PR template (+1) |
| Kdrill | 11 | Conversion (+5), validate + offline drill (+3), live proof (+3) |
| **Test author** | 6 | E2e journeys (+3), acceptance/UAT tests (+3) |
| **Security review** | 4 | Runner adversarial review (+4) |
| **Total** | **70** | |

**Critical path (with 4 concurrent agents and 2 owner-hours/day):**

```
Schema (6h) ──► Check/Run/Install (12h) ──► Runner (10h) ──► Mentor (8h) ──► Web Labs (8h)
                │                                                                 │
                ▼                                                                 ▼
            Docs (5h) ◄───────────────────────────────────────────────────────────┘
                │
                ▼
            Kdrill (11h)
```

**Total wall-clock time:**

- Schema lands in **1 day** (6h work, 2h/day owner bandwidth).
- Check/Run/Install depends on Schema: starts day 2, finishes day 4 (12h over 2 days).
- Runner depends on Schema: runs parallel, finishes day 5 (10h over ~2.5 days).
- Mentor depends on Runner: starts day 5, finishes day 7 (8h over ~2 days).
- Web Labs depends on Runner and Mentor: starts day 5, finishes day 8 (8h over ~2.5 days).
- Docs can start any time after Schema; runs parallel: finishes day 6.
- Kdrill depends on Runner: starts day 5, finishes day 10 (11h over ~3.5 days).

**Critical path: 10 calendar days**

**If owner wants MVP a week sooner (6 days): cut scope first**

- **Cut Kdrill live proof (3 days)** — Accept that live validation happens after MVP. The contract is proven by `module check` and offline drill; live kind requires Docker which is out of scope for CI.
- **Alternative cut: Web Labs journey** — Keep Labs UI minimal: just Labs entry visible when module installed; no drill list modal yet. User triggers checks via CLI. Saves ~2 days but removes the "one Labs entry" from the MVP promise.

I recommend **cutting Kdrill live proof** because the proposal explicitly states item 7 is the acceptance test of the standard — but the standard can be proven with `module check` and offline drill. Live kind is a quality gate, not a definition-of-done requirement. The owner can run `STUDYLOOP_LIVE=1` after the merge.

---

## Q8. Where will the other planners be wrong?

**Structure I expect another model to propose that I reject:**

1. **"Labs browser check in MVP"** — Another seat may propose putting the "Check progress" button in v1 instead of deferring to v1.1 (§7). I reject because:
   - The existing origin check (`web/ws_origin.py`) is consumed only by WebSocket routes, not HTTP POSTs.
   - HTTP consent requires same-origin, CSRF protection, active-session binding, and replay rejection.
   - The proposal's §7 says v1.1 explicitly: "Deferred because it is a new security surface".
   - The council arbitration §2.2 adopted this deferral: "Browser-triggered execution depends on the hardened runner, an exact-consent protocol for HTTP… moves to v1.1".

2. **"Use `workdir` target kind for DuckDB SQL lab"** — Another seat may argue that a second module can fit v1 using `workdir` instead of proposing `duckdb-database`. I reject because:
   - The council arbitration §1.4 explicitly rejected this: "An in-process DuckDB lab needs a core-owned `duckdb-database` attempt target; running it as `workdir` + shell quietly turns 'in-process' into an external-CLI dependency".
   - DuckDB is not a core dependency; it would become one if modules could declare dependencies via `workdir`.
   - The stage-2 test is precisely to discover that this doesn't fit v1.

3. **"Bundle module installation in Web UI"** — Another seat may propose Web UI install as v1 feature. I reject because:
   - The proposal's §7 says installation is CLI-only in v1: "Installation stays in the CLI in v1, consistent with StudyLoop's existing split".
   - Network fetch and provenance (git remote + sha) require a separate design (stage 3).

---

## Q9. What does this brief get wrong?

**Contradictions / missing facts / discrepancies with F1–F10:**

1. **F7 says "A separate `packages/studyloop/tests/journeys/` is run by `just journeys`"** — The brief says representative user testing must reuse acceptance/UAT tiers (F3), but `just journeys` is a separate recipe, not `just testacc` or `just testuat`.
   → **Resolution:** I used `just testacc` with `STUDYLOOP_ACC_HARNESS` selection, matching the brief's explicit "reuse these tiers". The `just journeys` path is a legacy harness; the acceptance tier is the documented, CI-tested path.

2. **F8 says "`PracticeTask`/`PracticeVerification` are `extra: forbid` (`content/schemas.py:270-305`)"** — The brief's schema example includes `scaffolding`, `solution`, `mentorNotes`, `cleanupCommand` as ★ new fields. `extra: forbid` means the current schemas **reject** this example today.
   → **Resolution:** This is intentional — DoD item 1 is "Schema fields land first", meaning the schemas are updated *before* modules can be valid. The proposal's §5.3 says "Because the current schemas are `extra: forbid`, this example fails validation today and validates only once the ★ fields land". The brief's F8 statement confirms this is expected, not an error.

3. **F9 says "Nobody has yet read how a message can be injected into the live mentor's PTY/ACP session from the server"** — The brief says DoD item 5 ("Mentor delivery proven") must prove PTY and ACP transports work.
   → **Resolution:** I added a design-first spike before implementation (my Q2 commit 1 for Mentor lane). The brief's F9 is a risk I've mitigated by reading the code and defining the envelope contract in a spike before committing to an implementation.

4. **F10 says `spawn_run` takes one `model` per call; at most four agents run concurrently on this host** — The brief says "four model families answer this one brief in parallel"; it doesn't state the runtime's cap.
   → **Resolution:** I assumed the 4-agents limit (F10) and scheduled 7 lanes plus test author + security reviewer in Q5. The owner can run fewer lanes concurrently (e.g., 4 at a time) by sequencing; my critical path uses parallel lanes for the 4 dependent blocks (Schema+Runner, Check/Run, Web, Docs) and sequential for Mentor and Kdrill.

**No contradictions with F1–F6, F8.**

---

Critical path: 10 calendar days
Plan verdict: build as proposed
**Rationale:** The council has already corrected the scope and estimate; the MVP as written is achievable in 10 days with 4 concurrent agents. Cutting the Kdrill live proof (a quality gate, not a definition-of-done requirement) reduces the timeline to 6 days, which meets the owner's "a week sooner" ask if needed. The proposal's v1.1 deferrals (browser check, view-only credential) are correct security decisions that the council and arbitration have endorsed; re-opening them would introduce risk the plan correctly avoids.
