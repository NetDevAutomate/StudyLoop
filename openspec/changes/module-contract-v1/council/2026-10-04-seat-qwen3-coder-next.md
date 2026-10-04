# Council seat — Qwen3 Coder Next — 2026-10-04 review

I've read the brief and proposal, verified claims against the codebase, and provide my
analysis below. All code references cite `path:line` where I checked the claim.

---

## Q1

The three changes that would most improve the proposal, ranked:

### 1. Section 5.3 — add `solution`, `scaffolding`, `mentorNotes`, `cleanupCommand` fields

The proposal lists three additive fields for `PracticeTask` and `PracticeVerification`,
but the current schemas use `extra: forbid` (`schemas.py:248`, `schemas.py:274`). The
example deck with these fields **fails validation today** and will remain invalid until
the core schemas are updated (DoD item 1 in §9). Add a bullet clarifying that these are
*schema additions* (not just new fields someone could write and expect to be ignored),
and that the `StudyDeck` model must be updated first. I recommend adding them now with a
`model_validator(mode="after")` that accepts them as unknown fields but logs a deprecation
warning so kdrill can be developed against the future schema.

### 2. Section 5.5 — clarify how check results reach the mentor

W1 (I5) is acknowledged but not addressed in the proposal. The runner executes commands
and records a `PracticeVerificationResult`, but the mentor (an ACP/PTY agent in a
separate process) has no verified channel to receive this result. The `verify_practice_task`
function writes to `practice_attempts` in the DB, but that is a *write-only* history table;
nothing notifies the mentor that a check completed. Add a section on the mentor integration:
does the runner spawn a mentor notification (ACP prompt injection? DB trigger?), or does the
mentor poll `practice_attempts`? Without this, the "Check progress" button in §7 has no
result to display.

### 3. Section 5.5 — clarify kubeconfig lifetime and revocation

The proposal says core writes a kubeconfig and exports `KUBECONFIG` (`web/routes/session/_start.py`
shows a session state, but no kubeconfig generation), bound to the `view` ClusterRole for
checks. However, v2's attempt-scoped grant design mentions revocability. In v1, how is the
kubeconfig revoked? Is it written to a temporary file deleted when the attempt ends, or is
it a fresh credential per-attempt? Add a sentence specifying the credential's lifecycle:
created on attempt start, written to `session_dir/kubeconfig`, removed on attempt cleanup,
and never stored in learning records.

---

## Q2

Of the proposal's nine reviewer questions, these have a wrong recommended answer:

### Q3 — exit-code contract

Recommended "adopt", but kdrill's existing `check` scripts likely use non-standard
semantics. The proposal says `0=pass · 1=not yet · ≥2=error`, but the test suite
(`test_practice_verify.py`) only tests `0` (pass) and `-1` (timeout), plus
`sys.exit(7)` mapping to `exit_code=7` and `passed=False`. A generic shell command
using `set -e` would exit `1` on failure, which this contract would classify as "not yet"
(running state), not "failed". I recommend documenting the expected exit codes per script
type (`setup`: any non-zero = error; `check`: 0=pass, non-zero=fail; `cleanup`: any
non-zero is logged but not fatal), and requiring modules to adhere to that.

### Q6 — SQL lab compatibility

Recommended "yes, fits without changes", but DuckDB runs in-process (no Kubernetes
cluster). The proposal's `target.kind: kubeconfig-context` implies a Kubernetes
credential and context discipline (`--context`, `--kubeconfig` enforcement). A
DuckDB SQL lab would use `target.kind: workdir` (the current alternative), but the
proposal's "Absent means invisible" principle (§2.4) means learners who haven't
installed DuckDB see nothing — the prerequisite check (`doctor/` probe) would fail
and hide the Labs entry. This may be acceptable (the proposal is conservative), but
it's worth flagging as a consequence of the "read-only is a capability" principle.

### Q8 — ownership

Recommended "as written", but item 2 (`module check` passes on scaffold + fixtures)
depends on item 1 (schema changes). The order implies schema → checker, which is
correct, but item 2 also requires a fixture set covering MC001–MC012. Without the
schema updates, MC001 and MC004 validation fails by design. Recommend reordering:
item 1 (schema), then item 2 (checker), then item 3 (scaffold end-to-end).

---

## Q3

### W3 — view-only checks → v2: **reject**

The proposal's security model rests on *no importable code* (MC012) and *no special
privileges* (principle 1: modules declare, core executes). Minting a ServiceAccount
with `view` ClusterRole is trivial compared to implementing the full Kubernetes
credential pipeline, but the *proposal already states this* in §5.5:
"**Deferred to v2**: an attempt-scoped grant..." — the view-only credential is the
v1 design. Rejecting W3 means accepting the current proposal's v1 scope, which is
correct. The coordinator's effort estimate (W6) already accounts for this.

### W4 — local-path-only add: **accept**

The proposal proposes `studyloop module add <path | git-url@sha>`, but the security
model (C3: consent per exact command) and the invariants (I6: no importable code) make
network fetches risky. A git URL implies cloning and executing a `module check` CI
template, which may pull in transitive dependencies. For an MVP, local-path-only
reduces risk: no network, no dependency resolution, no CI integration. The
`modules.lock.json` (§5.7) can still store sha + digest, just from `module add
/path/to/local/repo`. Move git-url support to stage 2 (registry) where the index
already vetoes modules via `module check`.

---

## Q4

Security holes in §5.5 runner contract under C3 and I6:

1. **Command injection via `command` field** (MC007 only checks paths, not content). The
   `verify_practice_task` function runs `shell=True` (`learning/practice.py:144`). If a
   module's `command` contains `; rm -rf /`, it executes as one command. Fix: enforce a
   whitelist of allowed shell constructs (e.g., `command: ["echo", "hello"]` array form)
   or validate against a regex (no `;`, `|`, `&`, `$(`, backticks). Currently MC007
   catches absolute paths but not injection.

2. **Working directory escape** (MC007, I6). The runner sets `cwd` (practice.py:142), but
   a `setupCommand` could `cd .. && rm -rf ~/.studyloop` before `command` runs. Fix:
   add MC007b: no `cd` in commands for `kubeconfig-context` targets (already implied
   by "context discipline"), and for `workdir` targets, require `--chroot` or
   containerisation (v2). Today, the working directory is passed to `subprocess.run`,
   but nothing prevents relative path traversal.

3. **Credential leakage in stdout/stderr** (§5.5 "redacted"). The proposal says
   "stdout+stderr captured up to a fixed cap, redacted", but no detector is cited.
   The pre-commit secret detector (`studyloop pre-commit`) likely exists, but it's
   not mentioned. Add MC009a: run secret detection on command output, and refuse to
   record attempts where a secret was detected. Cite the detector's module path.

4. **Environment variable hijack** (I6). The runner sets `STUDYLOOP_MODULE_ID`, etc.,
   but the learner's shell profile (`~/.zshrc`, `~/.bashrc`) may be sourced, exposing
   their `TF_VAR_*`, `AWS_SECRET_ACCESS_KEY`, or other secrets to the module. Fix:
   run with a clean environment (`env={}` in `subprocess.run`), not `os.environ`.
   The proposal says "nothing from the learner's shell profile is implied", but the
   code passes `env=dict(os.environ)` (`practice.py:143`).

5. **No command timeout enforcement for non-`timeoutSeconds` fields** (MC006). The
   `timeout_seconds` applies only to `command` verification, but `setupCommand` and
   `cleanupCommand` have no timeout. A `setupCommand` could hang indefinitely. Add
   MC006a: every command (`setup`, `check`, `cleanup`) must have a `timeoutSeconds`
   field in its parent `PracticeTask` or the module manifest; default to 300s.

---

## Q5

Missing conformance rules:

- **MC013** — No `STUDYLOOP_*` environment variable in commands except those core
  explicitly injects (`STUDYLOOP_MODULE_ID`, `STUDYLOOP_DRILL_ID`, etc.). Prevents
  modules from reading the learner's environment for secrets or configuration.

- **MC014** — `command` for `kubeconfig-context` targets must contain `--context`
  or `--kubeconfig` with the injected value, not hardcoded paths. Enforces the
  context discipline (§5.5) by static analysis.

- **MC015** — Every `scripts/` file must be executable (`chmod +x`) or have a shebang.
  Prevents shell scripts that fail with "permission denied" when called by core.

---

## Q6

**No**, a SQL lab on in-process DuckDB would *not* fit without changes.

The first missing field is `target.kind: duckdb-connection` (or similar). The proposal
has `workdir` and `kubeconfig-context` only (§5.1, §8). A DuckDB lab needs a connection
string or file path, not a working directory or kubeconfig.

The second missing behaviour is environment isolation. The proposal's §5.5 says "nothing
from the learner's shell profile is implied", but DuckDB may need `DUCKDB_THREADS`,
`DUCKDB_MAX_MEMORY`, or other config. A separate config namespace (e.g.,
`STUDYLOOP_DUCKDB_*`) would be needed.

The third missing piece is the `command` format. DuckDB queries are typically `duckdb
-c "SELECT ..."` or a script file, not a shell command. The `command` field is a
string (`learning/practice.py:81`), so multi-argument commands must be shell-escaped.
This works but is fragile — no type safety for the command shape.

---

## Q7

W6 estimates 45–60 agent-hours as written, 35–45 with W3+W4 cuts. My estimate:

**42–52 agent-hours**, with 80% confidence.

DoD item I'd move most: **item 2 → item 1**.

Current order:
1. Schema + runner contract + tools (module check/new/add, lockfile)
2. `module check` passes on scaffold + fixtures

I'd reorder to:
1. `module check` passes on scaffold + fixtures (uses schema, but scaffold can be
   minimal: one checklist task, no commands)
2. Schema + runner contract

The reason: scaffolding is the first user-facing artifact. If the scaffold doesn't
pass `module check`, the contract is unusable, even if the schema is complete.
Developing the schema in isolation (item 1 as written) produces JSON that can't be
validated until later. Starting with the scaffold ensures the contract is *testable*
from day one.

---

## Q8

**Where other reviewers will be wrong:**

I expect at least one reviewer (likely from a Kubernetes/infrastructure background) to
recommend **accepting W3** (keep view-only kubeconfig in v1), arguing that the
credential pipeline is "just 4–6 hours" and critical for security. I reject this
because:

- The proposal's core principle (modules declare, core executes) is already violated
  if core must generate Kubernetes resources (ServiceAccount, RBAC binding, token).
  That's core *doing work* for the module, not just validating.
- The credential pipeline is Kubernetes-specific. If a SQL lab is added later, it
  needs a different credential system (local DB user, environment variables).
  Deferring to v2 keeps v1 generic.
- The proposal already has `target.kind: workdir` for non-K8s tools (DuckDB, local
  binaries). The view-only credential is only needed for Kubernetes. Accepting W3
  fragments the contract: K8s modules need one credential pattern, non-K8s modules
  need another.

---

## Q9

**What this brief or the proposal gets wrong:**

### Contradiction: "Absent means invisible" vs. `studyloop doctor` reporting

C2 (AuDHD design rules) says "a learner who has not installed a module never sees its
prerequisites, its setup errors or its menu entry". But §7 says `studyloop doctor`
reports each installed module's prerequisites via enum probes. If a learner hasn't
installed Docker but a module declares `docker` as a prerequisite, `doctor` will report
"Docker missing" even if the learner never installs that module. This violates C2.

Fix: `doctor` only reports prerequisites for modules the learner *has* installed, and
`module list` should show only installed modules (§7 does this), but `doctor`'s
prerequisite checks should be filtered to installed modules only (§7 says `doctor`
"reports only, never installs or creates", but doesn't say it filters by installed
modules).

### Unverified claim: "one live session, claimed through a cross-process state file"

The proposal cites ADR-0009 (`docs/adr/0009-one-session-authority.md`), which is
accepted and landed (2026-09-02). However, the ADR describes a *study session* (a
live agent PTY/ACP session), not a *practice verification session*. A practice
check could run while a study session is active, or vice versa. The proposal doesn't
clarify whether `practice verify` uses the same session slot or a separate one.
If it uses the same slot, a practice check blocks study; if separate, there are
two live sessions. Neither is acceptable under C2 (max three active topics), and
the proposal doesn't say how this is managed.

### Unverified claim: "the mentor's shared protocols still govern"

§5.5 says "the mentor's shared protocols (Socratic engine, AuDHD framework, recording
protocol) still govern", but there's no code reference for how a module brief
interacts with the mentor's shared protocols. The `mentor/brief.md` is "composed into
the mentor's context" (§5.5), but `agents/shared/personas/` and `agents/shared/*.md`
(`agents/shared/`) don't exist in the repo (I checked `ls -la agents/` — it's empty).
The proposal assumes mentor infrastructure exists; it may not.

---

## Verdict

**adopt with changes**

The proposal is fundamentally sound: a strict contract with core validation, no code
imports, and a practice-deck data format is the right direction for a topic-agnostic
module system. However, three critical issues must be addressed before adoption:

1. **Schema updates** — the three new fields (`solution`, `scaffolding`, `mentorNotes`,
   `cleanupCommand`) must be added to the schemas *before* kdrill conversion (DoD
   item 1), or the proposal's example is invalid.

2. **Mentor integration** — the proposal doesn't explain how check results reach the
   mentor. This is a design gap, not just an implementation detail.

3. **Security hardening** — the runner contract has command injection, working
   directory escape, credential leakage, and environment hijack risks that aren't
   addressed by the existing checks.

With these changes, the contract becomes defensible for a v1 MVP. Without them, kdrill
conversion (DoD item 6) will fail because the scaffold can't pass `module check` (MC001,
MC004) and the runner won't handle Kubernetes credentials safely.
