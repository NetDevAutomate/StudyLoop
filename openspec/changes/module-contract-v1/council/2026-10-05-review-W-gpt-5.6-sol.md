# Lane W merge review — gpt-5.6-sol

## 1. Red first

Coverage is broad and the focused rerun is green (490 passed, 3 skipped): API listing/privacy/start/attach/cancel and Q2 status paths are named by the 21 tests in `test_web_modules.py`; all implementation-dependent cases failed in `w1-web-modules.red.txt`. The 17 `module-labs.test.js` tests cover scrub/list/store/start/reload/cancel/races and all failed in `w1-module-labs-js.red.txt`. CLI registration and prerequisite propagation are covered by the four named W3 tests and failed in `w3-registrations-prerequisites.red.txt`. E2E phases 1–8 cover hidden/list/start/keyboard/reload/cancel/delivery/remove and failed in `w4-labs-journey.red.txt`. Three red-record defects remain (findings 1–3).

Q2 implementation: peer-address loopback checking is correct for IPv4, IPv6 and IPv4-mapped loopback and reads no forwarding header; a proxy that does not preserve the originating peer necessarily appears loopback. Token comparison is constant-time. Typed validation/rendering delegation is correct, and HTTP 200 carrying a non-delivery `DeliveryOutcome` is intentional. The capability and exact-binding defects below are merge blockers.

## 2. Ownership

**Owned:** `CHANGELOG.md`; `docs/{cli-reference.md,module-contract.md,web-ui-guide.md}`; `mkdocs.yml`; `evidence/W/{w1-module-labs-js.green.txt,w1-module-labs-js.red.txt,w1-web-modules.green.txt,w1-web-modules.red.txt,w2-gate-g.txt,w3-gate-g.txt,w3-registrations-prerequisites.green.txt,w3-registrations-prerequisites.red.txt,w4-labs-journey.green.txt,w4-labs-journey.red.txt,w5-gate-g.txt}`; `tasks.md`; `cli/__init__.py`; `web/{app.py,routes/modules.py,routes/session/_options.py,static/index.html,static/js/labs.js,static/style.css}`; `tests/{acceptance/test_module_kdrill_live.py,acceptance/uat/data/module_rubric_registry.json,acceptance/uat/data/module_rubric_v1.md,e2e/test_module_labs_journey.py,js/module-labs.test.js,test_web_modules.py}`.

**Shared / explicitly brief-granted outside original globs:** `cli/_drill.py`, `session/orchestrator.py`, `tests/fixtures/lane_ownership.yaml`, `tests/test_module_cli.py`, `tests/test_module_lane_seams.py`, `tests/test_contributor_guide_drift.py`, `tests/test_docs_drift.py`. Each edit stays inside its W2/W3/W5 grant. No ungranted ownership violation found.

## 3. Scope and ruling

No registry/index, runtime dependency, hook, secrets baseline, pre-commit configuration, pragma, `SKIP=`, or `--no-verify` change exists. Labs does not execute a browser phase and exposes ids/prompts/success criteria/commands, not hint/solution/mentorNotes. However, `/api/session/state` breaks the owner-file-only capability design; Q2 exact active/open-attempt binding is incomplete; process-local guards evaporate on restart; and another browser view can overwrite/cancel the globally active drill. The `kubeconfig-context` security boundary is unwired while docs and the live test describe/work around it. Contributor prose and hash navigation also drift.

## 4. The next lane

1. `run_drill_phase` in `cli/_drill.py` always reaches `AttemptStore.open(... target=WORKDIR)`; K2 cannot prove the mandated core-created cluster or one-context `KUBECONFIG`.
2. `nav.init` in `static/js/nav-and-panel-stores.js` omits `labs`; Persona-A UAT reloads `#labs` into Today, bypassing the intended Labs reload journey.

## Findings

1. `openspec/changes/module-contract-v1/evidence/W/w1-web-modules.red.txt:1` -- W1 reports 20 failures and 1 pass; `test_options_carry_no_labs_entry_with_an_empty_lockfile` was never red -- classify it as characterization and stop claiming every W1 test was red.
2. `openspec/changes/module-contract-v1/evidence/W/w4-labs-journey.red.txt:1` -- phase 9 already passed in the red run -- classify that liveness guard as characterization, not red-first evidence.
3. `openspec/changes/module-contract-v1/evidence/W/w5-gate-g.txt:1` -- W5 has only green evidence for the new docs/rubric/live-test additions -- add reproducible pre-change failure transcripts or record the explicit DoD-7 exemption per test.
4. `packages/studyloop/src/studyloop/web/routes/session/_dashboard.py:44` -- the full state, including `practice_check_token`, is returned to browser clients (unauthenticated by default) -- strip capability/internal keys before every `/api/session/state` return.
5. `packages/studyloop/src/studyloop/web/routes/modules.py:457` -- a missing active session is accepted, and no open/unreported attempt is verified -- require an exact active-session match and validate the attempt sidecar/identity/open phase before delivery.
6. `packages/studyloop/src/studyloop/web/routes/modules.py:392` -- replay and burst state are process globals, so restart forgets both while the state-file token can survive -- persist guards per session/attempt or rotate/invalidate the token on process claim and reject stale state.
7. `packages/studyloop/src/studyloop/web/routes/modules.py:304` -- start/cancel carry no expected session or caller-bound nonce, so another browser view can replace or cancel the active drill -- bind mutations to the initiating view and exact claimed session/drill.
8. `packages/studyloop/src/studyloop/cli/_drill.py:280` -- manifest `target.kind` is ignored and every attempt defaults to `workdir` -- provision the disposable cluster, write one-context kubeconfig, and pass target+kubeconfig into `AttemptStore.open`.
9. `docs/contributor-modules.md:4` -- the site calls modules “not a shipped plugin API” after this change ships the contract -- rewrite as shipped module contract/no registry and link `module-contract.md` as authority.
10. `packages/studyloop/src/studyloop/web/static/js/nav-and-panel-stores.js:91` -- `labs` is absent from valid hash views -- add `labs` and an e2e reload assertion from `#labs`.

Unavailable MCP: `mochi` was declared but not configured; it was not needed.

Verdict: do not merge
Findings: 10 raised
