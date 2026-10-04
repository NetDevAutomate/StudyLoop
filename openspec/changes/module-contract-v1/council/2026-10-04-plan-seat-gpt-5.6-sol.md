# Q1

Use five product lanes, not a separate test lane. Every lane owns its tests. Worktree bootstrap is `env -u VIRTUAL_ENV just sync-dev`; fresh worktrees lack a venv and exported `VIRTUAL_ENV` otherwise selects the wrong one (`/Users/ataylor/code/personal/tools/studyloop/docs/contributing.md:61-75`).

| Lane / branch / worktree | Owned fnmatch globs | Forbidden | DoD |
|---|---|---|---|
| S Schema + campaign guard; `feat/module-schema-contract`; `/Users/ataylor/code/personal/tools/studyloop-wt-module-schema` | `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/content/schemas.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_schema.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/_lane_ownership.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_lane_ownership.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/fixtures/lane_ownership.yaml` | all module runtime, CLI and Web paths | 1 |
| C Conformance + lifecycle; `feat/module-conformance-lifecycle`; `/Users/ataylor/code/personal/tools/studyloop-wt-module-conformance` | `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/modules/{manifest,check,scaffold,store}.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/cli/_module.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/{test_module_check.py,test_module_lifecycle.py,fixtures/modules/**}` | runner, session, Web, CLI registration | 2, 4-CLI |
| R Secure runner; `feat/module-secure-runner`; `/Users/ataylor/code/personal/tools/studyloop-wt-module-runner` | `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/modules/{runner,consent,attempt}.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/cli/_drill.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_{runner,drill_cli}.py` | schema, transport, Web, lifecycle store | 3 |
| T Mentor delivery; `feat/module-mentor-delivery`; `/Users/ataylor/code/personal/tools/studyloop-wt-module-delivery` | `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/session/module_delivery.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/{test_module_delivery.py,integration/test_module_delivery_transports.py}` | transport implementation until the spike proves a required change; all Web/static | 5 |
| W Labs + assembly; `feat/module-web-labs`; `/Users/ataylor/code/personal/tools/studyloop-wt-module-web` | `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/web/routes/modules/**`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/web/routes/session/_options.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/web/static/{index.html,components.js,style.css}`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/{test_web_modules.py,js/module-labs.test.js,e2e/test_module_labs_journey.py}`, and CLI registration | schemas, runner, delivery internals | 4-UI |

The committed campaign map must contain these full normalized paths. Re-key the existing guard to an exact branch-to-lane map while preserving legacy `lane/m<n>-` behavior: today it only recognizes `lane/m<n>-` (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/_lane_ownership.py:16-44`), uses fnmatch and permits unmapped files (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/_lane_ownership.py:50-96`). S owns this hotspot and merges before C/R/T/W.

`/Users/ataylor/code/personal/tools/studyloop/docs/**`, `/Users/ataylor/code/personal/tools/studyloop/CHANGELOG.md`, `/Users/ataylor/code/personal/tools/studyloop/mkdocs.yml`, and `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/cli/__init__.py` are serialized hotspots: S alone adds the contract page, PR template, navigation and first changelog entry; after S merges, W alone performs final surface/registration updates. Neither touches `/Users/ataylor/code/personal/tools/studyloop/docs/contributing.md` or `/Users/ataylor/code/personal/tools/studyloop/CONTRIBUTING.md`. Start S’s docs commit only after the other session lands, then rebase once; current branch rules explicitly forbid `lane/...` (`/Users/ataylor/code/personal/tools/studyloop/docs/contributing.md:174-180`). Item 7 is an external kdrill handoff, not a sixth core-writing lane.

# Q2

Common gate **G** after every commit: both pre-commit hooks and `env -u VIRTUAL_ENV just preflight`; preflight expands to lint, typecheck, unit, JS, docs, release consistency and spec validation (`/Users/ataylor/code/personal/tools/studyloop/Justfile:279`). Preserve a failing-test transcript in the commit body/evidence directory before making it green.

- **S:** S1 re-key guard with branch parsing tests; S2 add red/green six-field schema tests; S3 add contract doc, checklist, PR template, nav and changelog. Each G; evidence: `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_schema.py`, guard fixture, strict docs build.
- **C:** C1 valid and MC001–MC016 fixtures; C2 checker; C3 scaffold/new; C4 atomic add/list/remove and lock provenance; C5 CLI output/JSON. Each G; evidence: exact rule IDs and lock-before/after snapshots.
- **R:** R1 adversarial runner tests; R2 argv/path/environment boundary; R3 digest consent/TOCTOU; R4 exit classes, timeout, stream cap/redaction; R5 transient attempt plus drill CLI. Each G; evidence: subprocess spy and unchanged observation database.
- **T:** T1 design-spike ADR/test doubles only; council M0; T2 typed envelope and active-session adapter; T3 PTY integration; T4 ACP integration and delivery-failure surfacing. Each G. The live session currently retains its transport (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/session/active.py:50-54,110-117`), but implementation waits for serialization design.
- **W:** W1 TestClient hidden/visible/start API; W2 Labs JS/HTML/CSS; W3 CLI registrations; W4 Playwright journeys; W5 final docs/changelog reconciliation. Each G, plus serialized `just e2e` after W4 because e2e is machine-exclusive (`/Users/ataylor/code/personal/tools/studyloop/docs/contributing.md:67`).

Merge DAG: S → {C,R}; S → T-spike → T; {C,R,T} → W; {C,R,T,W} → kdrill proof → release. Merge C before R only if imports require C’s manifest types; otherwise C/R merge independently. W is always last.

# Q3

| DoD | Concrete tests and countable acceptance |
|---|---|
| 1 | Unit `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_schema.py`: one complete deck validates; each of six additions round-trips; missing/duplicate/invalid deck and task IDs fail. Existing models are strict (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/content/schemas.py:270-305`). |
| 2 | Unit + CliRunner `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_check.py`, `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_cli.py`: one valid scaffold returns 0/JSON; 16 single-fault fixtures each return nonzero and exactly MC001…MC016; repairing that one fault makes each pass. |
| 3 | Unit + CliRunner runner modules: assert `shell=False` argv, regular contained executable, four-variable clean env, digest/argv/phase/target consent binding, three exit classes, three phase timeouts, byte truncation/redaction, and zero learning observations. Show `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_module_runner.py::test_drill_writes_no_observation` red first against current verification, which records confident/struggling (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/learning/practice.py:179-187`) and uses `shell=True` (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/learning/practice.py:282-290`). |
| 4 | CliRunner lifecycle tests: failed check leaves lock byte-identical; successful add snapshots/digests; remove is idempotent. TestClient + JS assert Labs absent/visible and start payload. E2E asserts list/start/cancel. |
| 5 | Two integration tests, PTY and ACP, assert one bounded labelled envelope reaches the fake mentor and includes identity/exit class but redacted output; a third asserts delivery failure is learner-visible. PTY writes raw input (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/session/transports/pty.py:351-360`); ACP starts a prompt turn (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/session/transports/acp.py:267-290`), so concurrency must be tested, not assumed. |
| 6 | `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/test_docs_drift.py` plus a new docs-contract assertion checks checklist, four README headings, PR template and MC001–MC016 links. |
| 7 | Acceptance `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/acceptance/test_module_kdrill_live.py`, gated by `STUDYLOOP_ACC=1` and `STUDYLOOP_LIVE=1`: converted snapshot checks cleanly, setup/check/cleanup complete, created `studyloop-*` cluster disappears, pre-existing sentinel cluster remains. Acceptance already has its opt-in recipe (`/Users/ataylor/code/personal/tools/studyloop/Justfile:108-135`). |

R4 is defeated by preserving 17 red demonstrations: sixteen exact-rule failures plus the current observation-write failure. Tests also require repaired twins to pass, preventing always-fail validators.

# Q4

Use existing acceptance/UAT tiers, never a fourth tier: default pytest excludes e2e, acceptance and UAT (`/Users/ataylor/code/personal/tools/studyloop/pyproject.toml:96-130`), while UAT requires both opt-ins (`/Users/ataylor/code/personal/tools/studyloop/docs/acceptance-testing.md:19-42`). The shared harness already isolates a vault/server and captures screenshot, HTML and console (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/e2e/_env.py:1-14`).

1. **AuDHD learner, tablet over `--lan`** — acceptance automation budget 6 minutes; UAT human budget 12. At 820×1180: (1) load and assert no Labs/no prerequisite noise; (2) fixture invokes CLI add; reload and assert one Labs entry; (3) open module, start one drill inside the sole session; (4) assert focus enters the terminal and Tab/Shift-Tab/Escape remain usable; (5) cancel and assert clear recovery; (6) reload and reattach/no duplicate session; (7) install a fixture missing `kind`, assert concise prerequisite report and no resource creation; (8) CLI remove, reload, assert Labs disappears. Also assert no overdue counter, hint, solution or mentor notes in DOM.
2. **New contributor on a clean machine** — acceptance budget 8 minutes; UAT 15. (1) follow documented `uv` setup; (2) scaffold; (3) check; (4) repeat hidden/add/visible/start/keyboard/cancel/reload/missing-prerequisite/remove lifecycle at 1440×900; (5) inspect JSON failure and repair one fixture; (6) assert the docs’ commands and observed output agree.

On any failure retain screenshot, full HTML, console/page errors, server log, CLI transcript, lockfile diff and attempt envelope. Human sign-off means both personas complete twice without retry or facilitator explanation, all assertions pass, no high-severity console/server errors, and the learner can state where to start and stop without seeing an answer.

# Q5

Run four agents maximum. Wave 0: S implementer, C contract-test author, R adversarial-test author, T design-spike investigator. After S merges: C/R/T implement in parallel while W authors only its owned API/JS/e2e tests; W implementation waits for C/R/T. The owner reviews one bounded commit stack per day, not five interleaved diffs.

Every brief contains settled C1–C8, base SHA, branch/worktree, exact owned/forbidden paths, DoD tests, mandatory red evidence, G, dependencies, merge position, no-registry warning and stop/escalation conditions.

Council milestones:
- **M0 Transport decision:** review spike ADR, PTY/ACP traces, serialization and failure semantics. It must not write implementation or reopen contract decisions.
- **M1 Security boundary:** before R merge, review argv/env/path/digest/consent/TOCTOU, adversarial fixtures and redaction evidence. It must not judge naming or UI polish.
- **M2 Release proof:** after W and kdrill evidence, audit the seven-item DoD, UAT artifacts and scope exclusions. It must not add v1.1/v2 or registry features.

# Q6

1. **R2 runner security:** threat table plus M1; detect with shell-token, symlink/hardlink, inherited-secret, digest-race and consent-replay tests.
2. **R1 delivery:** time-box T1 to one day; detect with both transport integrations and concurrent-turn ACP test.
3. **R4 vacuous tests:** paired broken/repaired fixtures and preserved red logs; gate exact MC ID.
4. **R3 collisions:** exact feat-branch guard, single owners, docs lease and merge order; gate changed-file classification on every commit.
5. **R6 external live proof:** freeze the accepted kdrill SHA/interface by day 5 and reserve owner Docker time; detect with acceptance proof that preserves a sentinel cluster.

# Q7

Agent-hours: S 9, C 13, R 18, T 10, W 14 = **64**, plus roughly 6 correction hours after councils. Forty-to-fifty is not credible once adversarial evidence and representative UAT are included. Calendar: days 1–4 S + T spike/M0; days 5–10 C/R/T; days 11–15 W; days 16–17 owner UAT/fixes/M2; day 18 kdrill live proof/release. The owner’s two-hour review budget, not four-agent compute, is limiting.

To save a real week, cut DoD 4’s Web Labs slice to v1.1 and call the result a **CLI contract preview**, not the proposed MVP. Do not cut kdrill proof: that would ship an untested standard.

# Q8

I reject the likely “implementation lanes plus one broad test lane owning `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/**`” plan. It creates cross-lane coupling, permits tests written after behavior, and weakens R4 accountability. Tests belong with each implementation; W alone owns cross-surface journeys. I also reject starting Web work after schema alone: the proposal’s own transport dependency and ACP’s turn-based input make that speculative rework.

# Q9

Unavailable MCP servers: `@codegraph` and `@mochi:mochi` were declared but not configured; no claim below depends on them.

F1–F4 and F6–F8 are supported. F5 is stale but directionally close: a read-only count over the configured testpaths (`/Users/ataylor/code/personal/tools/studyloop/pyproject.toml:96-98`) found 4,669 test functions across 354 `/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/tests/**/test_*.py` files, not ~4,800/~330.

C3’s “pre-push stage runs pyright” is not represented in configuration: the pyright hook is defined without a pre-push stage (`/Users/ataylor/code/personal/tools/studyloop/.pre-commit-config.yaml:119-128`), while nearby explicit hooks say `stages: [pre-commit]` (`/Users/ataylor/code/personal/tools/studyloop/.pre-commit-config.yaml:84-119`). Treat `just preflight` as authoritative until configuration is corrected; do not invent a passing pre-push gate.

F9’s “unknown mechanism” is now narrower: there is a live transport handle and generic `send_input`, but no typed system-data delivery method or ACP turn-serialization contract (`/Users/ataylor/code/personal/tools/studyloop/packages/studyloop/src/studyloop/session/transport.py:118-172`). Therefore the design-first spike remains mandatory. F7’s claim about another session is operational, not verifiable from cited source; use an explicit docs lease rather than assuming status output proves ownership. No registry work is needed.

Critical path: 18 calendar days
Plan verdict: re-sequence first — merge schema/ownership and decide mentor-delivery serialization before parallel runner, lifecycle and Web integration work.
