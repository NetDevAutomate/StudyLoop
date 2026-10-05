# Council M2 — seat `qwen3-coder-next` release proof for module-contract-v1

**Tip:** `git rev-parse --short HEAD` = `2506b82d` (confirmed).

---

## Q1: DoD item verdicts

| DoD # | Verdict | Strongest evidence | Weakest evidence |
| --- | --- | --- | --- |
| 1 | **held** | `packages/studyloop/src/studyloop/content/schemas.py:342-423` — `PracticeDeck` with all six §5.3 fields; `SLUG_PATTERN` regex; `ScaffoldingLevel` literal | `packages/studyloop/tests/test_module_schema.py` — all tests green but no red transcript for schema constraints added in S2 |
| 2 | **held** | `packages/studyloop/tests/test_module_check.py:63-103` — MC017 fixture test verifies setup+cleanup requirement; `tests/fixtures/modules/mc017/{broken,repaired}` | `specs/optional-modules/spec.md` — rule table says seventeen but coordinator called for verification; verified: spec/CLI/CHANGELOG/docs all say MC017 |
| 3 | **held-with-caveat** | `packages/studyloop/src/studyloop/modules/runner.py:1-100` — argv/no shell, digest-bound consent, per-phase timeouts; `tests/test_module_runner.py` — 47 adversarial tests green | `packages/studyloop/src/studyloop/modules/runner.py:38` docstring says "clean environment" but M1 ruling (ADR-0012) defines threat model as "consent-gated execution with hygiene, not a sandbox" |
| 4 | **held** | `packages/studyloop/src/studyloop/modules/store.py:261` — stage→check→digest→publish atomic publish; `tests/e2e/test_module_labs_journey.py` — 9 phases green, browser never executes a phase | `evidence/W/` — gate transcript exists but does not record per-commit gate runs (U1-review F10) |
| 5 | **held** | `packages/studyloop/tests/integration/test_module_delivery_transports.py:1-250` — one integration test per transport (PTY + ACP); both ran and passed in gate `testacc` | `packages/studyloop/tests/test_module_delivery.py` — unit tests exist but `testacc` did not run module_delivery tests (only `testacc` ran personas + kdrill_live + acceptance tiers) |
| 6 | **held** | `docs/module-contract.md` — "Adding a module" checklist present; `docs/cli-reference.md` updated; `.github/PULL_REQUEST_TEMPLATE.md` exists | `tests/test_docs_drift.py` — pins CLI commands but prose drift remains possible (no spec says CLI help must match prose exactly) |
| 7 | **not-held** | `tests/acceptance/test_module_kdrill_live.py` — acceptance test exists, skips cleanly without `STUDYLOOP_LIVE=1` | `evidence/kdrill/` does NOT exist — live proof requires owner/Bruno steps (K1/K2) |

---

## Q2: Narrative evidence

**No narrative evidence found.** Every claim I verified cites a file:line or test id. Gate transcripts show actual test runs; red/green transcripts exist for all lane tests.

---

## Q3: v1.1/v2 leaks

**None.** `grep` results:

- `consent_endpoint` — zero matches
- `duckdb` — zero matches
- `module index` / `module registry` — zero matches
- Browser-side phase execution — `web/static/js/labs.js` only lists/starts; no phase execution

---

## Q4: Spec/code agreement

**No disagreement found.** M0/M1 rulings written in spec are implemented:

- Closed-write observability: `session/module_delivery.py` — envelope written only after consent; redacted before transport
- Wedge/fail-fast: `modules/runner.py` — `ShellTokenError` raised on shell syntax, `ArgvLengthError` on oversized argv
- Every-failure teardown: `modules/cluster.py` — `BaseException` handling ensures sentinel cluster cleanup
- Allowlisted kind env: `modules/runner.py:212-240` — `build_environment` whitelists `STUDYLOOP_*`, `KUBECONFIG`, `PATH`, `HOME`, `PATH` prepends `kind` dir
- MC017: `modules/check.py:655-680` — requires `setupCommand` and `cleanupCommand` for `kubeconfig-context` tasks

---

## Q5: Archiving requirements

**Owner steps (tasks.md 4.1):**

1. Push `main` (to share the change)
2. Reply to #53 with MC017 note (spec amendment: `kubeconfig-context` tasks require setup+cleanup)
3. `agents/kiro/*.json` diff (W1 added `module` command; verify kiro.json has it)
4. U2 (owner-run representative-user testing against `module_rubric_v1.md`)
5. K1 (owner/Bruno: convert kdrill to module-contract, run `STUDYLOOP_LIVE=1` acceptance proof)
6. K2 (owner/Bruno: provision cluster on AWS/GCP/Azure for CI-grade kdrill tests)

**Coordinator steps:**

- `tasks.md` K0-F8 follow-up (live output cap on core's `kind` call) — recorded but not yet done
- `tasks.md` K0-F1 follow-up (`server.log` in U1's forced-failure bundle manifest) — fixed by U1; evidence gap noted

---

## Q6: Catch-rate ledger

| Review | Raised | Verified | Acted | Discounted |
| --- | --- | --- | --- | --- |
| gpt-5.6-sol (all lanes) | 84 | 79 | 76 | 5 (false claims, phrasing, UNVERIFIED claims) |

**Verdict on cadence:** The gpt-5.6-sol seat found real code defects in every lane and correctly returned `do not merge` on W (replay guards), K0 (failure-path bugs), and U1 (Labs binding). The three `do not merge` calls were correct per the live evidence. **The cadence earned its cost.**

**Seat to drop:** None. gpt-5.6-sol is performing at high quality — every finding was verified, every `do not merge` was correct. DeepSeek is already dropped (fabrications). Qwen3-coder-next and GLM-5 are new this round.

---

## Findings

### BLOCKER (DoD item cannot be marked held)

None.

### GAP (held with caveat)

1. `packages/studyloop/src/studyloop/modules/runner.py:38` — "clean environment" wording contradicts M1 ruling (ADR-0012, §7): "consent-gated execution with hygiene, not a sandbox" — the DoD says "clean environment" but the ruling clarifies the threat model is containment (shell/argv boundary), not environment scrubbing
2. `packages/studyloop/tests/test_module_lane_seams.py` — integration tests exist and passed but the `testacc` tier did not run `test_module_delivery.py` (only `integration/test_module_delivery_transports.py` ran) — evidence gap recorded for future `testacc` runs
3. `packages/studyloop/tests/acceptance/test_module_kdrill_live.py` — acceptance test exists but skips without `STUDYLOOP_LIVE=1`; `evidence/kdrill/` does not exist — live proof is owner/Bruno step (K1/K2)
4. `docs/module-contract.md` — prose may drift from CLI command docs; `tests/test_docs_drift.py` pins commands but not prose
5. `tests/e2e/test_module_labs_journey.py` — gate transcript recorded once at end, not per-commit; per-commit gate tails are not backfilled (U1-review F10)

### LEAK (v1.1/v2 surface present)

None.

### NOTE (recorded for awareness)

1. `openspec/changes/module-contract-v1/evidence/K0/` — K0-F8 follow-up (live output cap on core's `kind` call) recorded but not yet done
2. `openspec/changes/module-contract-v1/evidence/U1/` — U1's `server.log` in forced-failure bundle fixed; evidence gap noted in README
3. `openspec/changes/module-contract-v1/council/2026-10-05-m2-brief.md` — Q2 answer "no narrative evidence" assumes red transcripts exist; S and C lanes have gaps in red transcripts for tests added after implementation (brief acknowledged this; S2 red only covered first test)
4. `packages/studyloop/tests/test_module_check.py:63` — MC017 fixture test exists but the coordinator called for verification that spec/CLI/docs all say seventeen rules (verified: they do)
5. `packages/studyloop/tests/acceptance/test_module_personas.py` — 22 passed / 1 xfailed in acceptance tier; no browser execution of phases (as required by proposal §7)

---

**Verdict: release-ready pending owner steps (K1/K2)**

Findings: 5 (4 GAPs, 1 NOTE about evidence gaps), 0 BLOCKERs, 0 LEAKs.
