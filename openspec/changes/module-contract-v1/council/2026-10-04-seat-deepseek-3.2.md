# Council review — DeepSeek 3.2 seat

**Brief read:** `/Users/ataylor/code/personal/tools/studyloop/openspec/changes/module-contract-v1/council/2026-10-04-review-brief.md`
**Proposal read:** `/Users/ataylor/code/personal/tools/studyloop/openspec/changes/module-contract-v1/proposal.md`
**Repository root:** `/Users/ataylor/code/personal/tools/studyloop`

## Q1
**Top three improvements to the proposal**

1. **Section 5.5 (runner contract)** — Add explicit consent requirement for `setupCommand` and `cleanupCommand`. The proposal mentions R-15 for the main `command` but doesn't extend it to setup/cleanup. Replace: "v1 keeps the existing per-command path: the exact resolved command is shown and confirmed" with "v1 keeps the existing per-command path for every command field (`command`, `setupCommand`, `cleanupCommand`): each exact resolved command is shown and confirmed independently before execution (R-15)."

2. **Section 5.3 (drill format)** — Clarify that `solution` is optional but recommended. The proposal's example includes `solution` but doesn't state whether it's required. Add after the table: "`solution` is optional but strongly recommended for mentor reference; a drill without one relies entirely on mentor notes and brief."

3. **Section 7 (CLI and Web UI)** — Specify failure behavior for `studyloop module add`. Add: "If `module check` fails, `module add` exits with non-zero and writes nothing to `modules.lock.json`. The lockfile is updated only after successful validation."

## Q2
**Wrong recommended answers in §10**

**Q4 (view-only checks):** Wrong recommendation. The proposal says "check scripts genuinely need to read Secrets" → "that drill is redesigned, not the credential." This violates the Socratic rule (C1) — if a CKA/CKAD/CKS drill genuinely requires reading Secrets to verify mastery, redesigning it may compromise the learning objective. Reality check: `packages/studyloop/src/studyloop/content/schemas.py:123` shows `PracticeVerification` has no security classification; `check` scripts are arbitrary shell. A better answer: "If a check genuinely needs read access to Secrets, that drill must be deferred to v2 where credential scoping can accommodate it, not redesigned to avoid the legitimate learning requirement."

**Q8 (ownership and order):** Wrong recommendation. The proposal says Bruno can start conversion "against the draft schema before `module check` exists." This violates I1 (schemas are `extra: forbid`) — kdrill's converted JSON will fail validation until core adds the ★ fields. The correct answer: "No, wait until DoD item 1 (schema changes) lands; otherwise the converted deck will be unloadable by core."

## Q3
**Scope cuts**

**W3 (view-only → v2): Accept.** Reason: Minting a view-only kubeconfig is 4–6 hours of plumbing that blocks the entire v1 MVP. The risk: v1 modules using `kubeconfig-context` target cannot be tested live until v2. This is acceptable because the contract stays the same — the credential shape changes, not the interface.

**W4 (local-path-only add): Reject.** Reason: Git pinning (`git-url@sha`) is essential for reproducibility and matches Terraform provider convention. The complexity (clone, sha validation) is less than the security risk of mutable local paths. Keep git pinning in v1.

## Q4
**Security holes in §5.5**

1. **Attack:** `setupCommand` could create a side channel (write to `/tmp`, open network connection) that `check` reads, bypassing view-only constraint. **Fix:** `setupCommand` runs with same credential as `check`, not admin, unless explicitly declared and separately consented.

2. **Attack:** Scripts in `scripts/` directory could be modified between `peek_verification_command` and execution (TOCTOU). **Fix:** Extend R-15b to scripts — hash script content and include hash in confirmed command string.

3. **Attack:** Environment variable leakage (`STUDYLOOP_MODULE_ID`, `STUDYLOOP_DRILL_ID`) could be exfiltrated via command output. **Fix:** Redact these values from captured stdout/stderr before storage.

4. **Attack:** `cleanupCommand` with destructive capability could be approved once then re-run without consent. **Fix:** Each `cleanupCommand` execution requires fresh confirmation, independent of earlier approvals for same script.

## Q5
**Missing conformance rules**

**MC013 — Timeout bounds check.** `timeoutSeconds` must be ≤300 for `check` commands, ≤60 for `setupCommand` and `cleanupCommand`. Prevents indefinite hangs.

**MC014 — Script dependency declaration.** Any script referenced in `command`/`setupCommand`/`cleanupCommand` must declare its shell dependencies (`#!/bin/bash`, `#!/bin/sh`) and not use `bash -c` with inline code.

**MC015 — No network calls in offline mode.** Commands must not contain `curl`, `wget`, `nc`, or similar when `STUDYLOOP_LIVE=0` is implied.

## Q6
**SQL lab on in-process DuckDB fit**

**No.** Missing field: `target.kind: inprocess-duckdb`. Current v1 kinds are `workdir` and `kubeconfig-context`. SQL lab needs a third kind that provides a DuckDB connection string (`:memory:` or file path) and ensures isolation between attempts.

Additional missing behavior: DuckDB doesn't have a credential system like kubeconfig's RBAC, so "view-only" capability doesn't map. Would need a `readonly: true` flag or similar.

## Q7
**Effort estimate credibility**

**My estimate: 55–70 agent-hours.** W6's 45–60 is optimistic.

**Item to move:** DoD item 4 (Web UI Labs entry + Playwright journey) should move to v2. Rationale: I3 states "web UI has no command-execution endpoint today." Building a secure endpoint with R-15 confirmation in the browser is a separate security review (new surface) that will consume 15–20 hours alone. v1 should keep installation and checking in CLI only; v2 adds the web integration.

## Q8
**Where other reviewers will be wrong**

Other models will likely recommend **adding a `difficulty` field to `PracticeTask`**. Wrong because: (1) violates "no field a module can use to ask for special treatment" principle; (2) `scaffolding` field (`guided`/`hinted`/`unaided`/`exam`) already encodes assistance level, which is what matters for Socratic pacing; (3) difficulty is subjective and module-specific — a Kubernetes "difficulty: hard" might be Python "difficulty: easy", creating false comparisons.

## Q9
**What the brief or proposal gets wrong**

**Contradiction:** Proposal §5.5 says "v1 keeps the existing per-command path" but the existing path (`packages/studyloop/src/studyloop/learning/practice.py:202-206`) only handles `command`, not `setupCommand` or `cleanupCommand`. The `peek_verification_command` function (`practice.py:119`) reads only `command` field. Brief I3 correctly identifies this gap.

**Unverified claim:** Proposal §4 says "Everything in §5–§8 is new" but `doctor/*.py` prerequisite probes don't exist for `docker`, `kind`, `kubectl`, `duckdb`. Checked: `packages/studyloop/src/studyloop/doctor/` contains only `__init__.py` and `checks.py` with generic checks, no tool-specific version probes.

**Constraint conflict:** Brief C3 (consent per exact command) conflicts with proposal's deferred v2 "attempt-scoped grant." If v2 allows repeated checks without re-confirming, that's a standing grant, violating C3's "no standing grants in v1." The proposal should clarify C3 applies only to v1, not forbid the v2 design.

**Code verification:** `packages/studyloop/src/studyloop/content/schemas.py:123-134` shows `PracticeVerification` has `setupCommand` field but no `cleanupCommand`. Proposal's ★ field `cleanupCommand` doesn't exist in current schema.

---

**Verdict: adopt with changes** — The contract is sound but needs clarification on security (Q4), schema gaps (Q9), and scope adjustment (Q7 move Web UI to v2).
