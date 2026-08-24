# Task 5 report — lifecycle-only product writers

## Outcome

Migrated every normal CLI and existing REST plan mutation through
`PlanningLifecycle`. The legacy file store is now read-oriented in the public
package API; its three raw write implementations remain underscore-prefixed for
explicit maintenance/test fixtures only and are not imported, called, or
re-exported by normal product code.

One production factory now derives the repository root, lock, journal, private
run storage, and canonical Markdown directory from the same configured plans
directory. In particular, `STUDYLOOP_PLANS_DIR` remains the document directory;
the runtime never silently writes to `<configured-dir>/plans`.

## Delivered behavior

- Deprecated `studyloop plan new` creates a typed draft proposal but cannot
  approve it in the same invocation. `--confirm` is refused; a separate
  interactive-only `plan decide <proposal-id> <proposal-digest>` action
  redisplays the proposal and prompts for the decision and confirmation. It
  cannot activate or bypass three-plan capacity.
- Structured `POST /api/plans` returns an exact proposal preview with HTTP 202
  for every structured creation request. A later request can approve/reject
  only that persisted proposal ID and displayed digest; same-request approval
  is refused.
  Request JSON cannot select `ActorContext` and overwrite is refused.
- Raw Markdown POST is learner-only `ImportPlanDraft`: fresh IDs, draft status,
  incomplete milestones, regenerated Mermaid, canonical tier-4 import context,
  and no foreign evidence/completion/Mermaid or generic unknown-section notes.
- Structural and whole-Markdown PATCH return a revision proposal with exact
  target digests/revisions and do not mutate canonical Markdown. A later exact
  learner decision applies it; stale decisions conflict.
- Status-only PATCH/CLI status and normal DELETE use
  `TransitionPlanStatus`. DELETE now records terminal abandonment while keeping
  the Markdown and checkpoint history. Public hard deletion is absent.
- Evaluation computes first, records the checkpoint through
  `RecordCheckpoint`, then independently records DB history. A repository
  conflict has no raw fallback; DB failure still produces a visible warning.
- Milestone CLI/REST writes use `RecordMilestoneOutcome`. Bare toggle is gone;
  verified completion needs selected canonical tier-1 evidence, learner
  attestation needs selected canonical tier-3 evidence plus a milestone-specific
  reason and the exact confirmation sentence, and attestation remains visibly
  non-verified and does not check the milestone.
- Compatibility revision translation refuses more than three goals, duplicate
  identities, ambiguous goal/milestone links, and unresolved concept relations
  rather than truncating or cross-linking. Stable goal/concept/milestone IDs and
  explicit concept relations are preserved when the legacy structure is safe.
- Production evidence catalogues are built from evidence already carried by the
  canonical plan. JSON cannot supply source tiers or mint trusted evidence.
- An AST architecture test catches nested/top-level imports, aliases, direct or
  qualified calls/references, and public re-exports of all six raw writer names
  across CLI, web, MCP, session, agent, evaluation, and package public API code.

## TDD evidence

### RED

1. The new architecture/path test initially failed collection because the
   production runtime factory did not exist:

   ```text
   ModuleNotFoundError: No module named 'studyloop.planning.runtime'
   ```

2. After adding the AST gate it reported the public `create_plan`, `save_plan`,
   and `delete_plan` re-exports. Those exports and public wrappers were removed;
   normal adapters now contain no raw calls.

3. Compatibility regression tests initially found silent structural loss:

   ```text
   DID NOT RAISE LifecycleValidationError  # four goals were sliced to three
   assert 1 == 2                           # blank goal IDs collapsed in a dict
   ```

   Translation now preserves unambiguous blank identities and refuses
   over-limit, duplicate, or ambiguous structures with no canonical write.

4. The first migrated focused run exposed eight expected compatibility changes:
   old bare milestone toggles, immediate structural PATCH, hard deletion, and
   activation error shapes no longer matched the safe lifecycle contract. Tests
   were updated to assert proposals, evidence-backed outcomes, abandonment, and
   conflict semantics.

5. A strengthened import test caught forged Evidence prose surviving through
   generic parsed notes:

   ```text
   assert "forged" not in imported["markdown"].lower()
   # forged tier-1 evidence table was still rendered
   ```

   Import now canonicalises only recognised typed fields and clears generic
   notes/unknown sections, closing the evidence and foreign-Mermaid smuggling
   path.

### GREEN

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py -q
# 87 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 292 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 601 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright \
  packages/studyloop/src/studyloop/planning/runtime.py \
  packages/studyloop/src/studyloop/planning/compat.py \
  packages/studyloop/src/studyloop/planning/lifecycle.py \
  packages/studyloop/src/studyloop/planning/evaluation.py \
  packages/studyloop/src/studyloop/planning/store.py \
  packages/studyloop/src/studyloop/planning/__init__.py \
  packages/studyloop/src/studyloop/cli/_plan.py \
  packages/studyloop/src/studyloop/web/routes/plans.py
# 0 errors, 0 warnings, 0 informations
```

Ruff checks, Ruff formatting, Python compilation, the AST architecture gate,
and `git diff --check` also pass.

## Compatibility changes

- `plan new` never approves in the same command; deprecated `--confirm` and
  `--activate` are refused. `plan decide` is interactive-only with no JSON or
  flag-based approval surface.
- New structured REST plans default to draft, cannot overwrite, and require an
  explicit learner decision. Unconfirmed requests return 202 proposal previews.
- Structural PATCH is asynchronous proposal creation (202), not an immediate
  write. Mixed structural/status/completion authority is rejected.
- Bare milestone toggle and completion without evidence/attestation are gone.
- DELETE means audited abandonment, not file removal.
- `create_plan`, `save_plan`, and `delete_plan` are no longer public planning
  imports. Test/maintenance fixtures use underscore-prefixed helpers explicitly.
- `evaluate_and_record` no longer appends Markdown and emits a warning if an old
  caller requests that behavior; normal adapters use `RecordCheckpoint`.

## Honest limitations and deferrals

- The existing browser wizard/store has not yet been adapted to the proposal
  preview/decision DTO. The compatibility API is correct, but the end-to-end
  browser planning experience remains deliberately incomplete until Tasks 8-9;
  this task does not claim the old wizard works with the new 202 flow.
- The production evidence catalogue projects canonical plan evidence only.
  Sessions DB identity-bearing evidence integration belongs to Task 10; no
  Task-5 command claims notes, checkpoints, or arbitrary JSON as tier 1.
- Top-level free-form notes cannot be represented by the current typed proposal
  contract. Direct notes PATCH is refused, and raw import generic notes are
  stripped rather than silently trusted or lost during approval.
- CLI compatibility approval is deliberately a TTY-only, prompted,
  digest-bound command. Agent conversation and onboarding installation belong
  to Task 6.
- Planning workspace/ACP transport, new planning HTTP/WebSocket routes, browser
  Markdown/Mermaid rendering, stewardship, and aggregate release gates remain
  Tasks 7-12.

## Independent-review fix round 1

The first implementation passed its Task 5 suite but an independent adversarial
review found three Critical and five Important boundary defects. This round
closed all eight without beginning Task 6 or later transport/workspace work:

- Creation approval is now necessarily two-phase in CLI and REST. Both paths
  require the persisted proposal ID and exact displayed digest; the CLI
  `--confirm` shortcut and structured same-request REST decision are rejected.
- Structural revisions merge lifecycle-owned state by stable ID. Plan status,
  existing goal status, and verified milestone completion survive title-only
  and full structural proposals; completed/abandoned plans cannot be revised.
- CLI and browser learner input can record only explicit tier-3 attestation,
  never mint recorder authority. Internal verified completion additionally
  requires selected tier-1 evidence with a completion claim whose subject
  matches the target milestone (or its named concept).
- PATCH decisions inspect the persisted proposal before dispatch and reject a
  creation proposal or a revision targeting a different route plan.
- Raw imports reject foreign Mermaid fences, all raw HTML, HTML comments, and
  concealed markup before any recognised Mission/Milestone field is accepted.
  Canonical Mermaid remains renderer-generated. Ambiguous duplicate normalised
  legacy concept labels are refused rather than cross-linked.
- The architecture gate scans the real `session/`, `session_runtime/`, root
  session/agent modules, adapters, and MCP tree. Self-tests cover dynamic
  `importlib`, `__import__`, string `getattr`, aliases, nested calls, qualified
  calls, and public re-exports.
- Every plan-agent harness invocation receives a fresh private scratch root;
  caller-selected directories and their existing Markdown are never unlinked.
- Checkpoint DB history uses the same lifecycle command key with a partial
  unique index, so lifecycle replay cannot append a second history row. Both
  CLI and REST now surface the helper's `False` result as a warning.

### Fix-round RED evidence

The added regression slices reproduced each defect before production changes,
including immediate approval (`201` instead of `400`), state regression
(`active`/`paused` previewed as `draft`), cross-plan PATCH returning `200`,
irrelevant tier-1 evidence being accepted, concealed import markup returning
`201`, dynamic-writer self-tests returning no violation, the harness helper
being absent while direct unlink remained, and a replay producing two DB
history rows.

### Fix-round final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py \
  packages/studyloop/tests/test_plan_agent_harness.py -q
# 112 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 299 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 620 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright <changed Task 5 source and harness files>
# 0 errors, 0 warnings, 0 informations
```

Ruff check, Ruff formatting, Python compilation, the expanded AST architecture
gate, and `git diff --check` also passed on the final formatted tree.

## Independent-review fix round 2

The second adversarial review correctly identified that exact proposal IDs and
digests are CAS values, not learner authentication. It also found a remaining
legacy progress-loss case plus two identity/parser edge cases. All four are now
closed:

- CLI proposal decisions are unavailable to non-TTY and JSON/flag invocation.
  The command redisplays the exact proposal, prompts for approve/reject, and
  requires a second explicit confirmation. `plan new` shows the review values
  but never prints an immediately executable approval command.
- The web app now mints an expiring, bounded, application-local learner session
  only during same-site browser navigation. Authority-bearing plan writes
  require the HttpOnly session cookie, exact same Origin, `Sec-Fetch-Site:
  same-origin`, and a double-submit CSRF token tied to server-side session
  state. Configured HTTP Basic authentication remains the outer identity
  boundary; no learner session is minted until it succeeds.
- Proposal decisions, raw imports, status transitions, milestone outcomes, and
  abandonment all construct learner `ActorContext` only from that trusted
  browser boundary. Default/direct HTTP clients receive 403. Proposal
  preparation remains model-authorised and does not mint learner authority.
- Structural revision of a tolerated legacy plan with blank stable entity IDs
  is refused before any proposal or canonical write. Completed milestones and
  active/non-default plan state therefore remain intact until an explicit
  lossless identity repair exists.
- Import scans CommonMark backtick and tilde Mermaid fence openers across valid
  fence lengths, spacing, indentation, and case. Only renderer-generated
  canonical Mermaid is accepted.
- Tier-1 relevance contains no title/substring heuristic. Evidence must name
  the exact milestone ID or an exact canonical concept label/stable concept ID
  explicitly attached to that milestone; SQL/NoSQL and nested-label cases are
  rejected.

### Round-2 RED evidence

Before implementation, noninteractive CLI decisions succeeded, direct REST
approval returned 201, browser navigation minted no trusted session, tilde
Mermaid imports returned 201, the legacy completed-milestone PATCH returned
202, and SQL/NoSQL evidence completed the wrong milestone. Each regression now
fails closed at its public boundary.

### Round-2 final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py \
  packages/studyloop/tests/test_plan_agent_harness.py -q
# 129 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 301 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 637 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright <changed round-2 source files>
# 0 errors, 0 warnings, 0 informations
```

Ruff check, Ruff formatting, Python compilation, architecture tests, and
`git diff --check` passed on the final round-2 tree.

## Fix round 3 — authenticated learner authority

The round-2 review demonstrated that proposal compare-and-swap plus browser
cookies did not authenticate a learner: a local shell client could imitate
browser navigation and same-origin headers. Round 3 closes that boundary and
the remaining identity/parser gaps without adding Task 6+ transports.

### Changes

- Browser learner sessions are minted and accepted only when the existing
  outer BasicAuth password is configured and the request has successfully
  passed that middleware. Password-empty mode remains usable for proposal
  preparation and reads, while every learner-authority mutation fails with the
  stable `web_auth_required` code. Session expiry, same-origin checks, and CSRF
  remain additional defences after BasicAuth.
- CLI proposal decisions, status transitions, milestone outcomes, and
  abandonment now construct learner authority only inside a genuine TTY after
  redisplaying the exact target/effect and receiving explicit confirmation.
  Noninteractive, JSON, and flag-only calls cannot mint learner authority.
- Raw imports use the CommonMark parser's fence tokens. Mermaid fences are
  rejected inside blockquotes, lists, and nested containers for backticks or
  tildes, while ordinary four-space-indented literal code is preserved. The
  already-transitive `markdown-it-py` package is now an explicit production
  dependency because lifecycle validation imports it directly.
- Tier-1 milestone completion accepts only an exact milestone ID or an exact
  stable concept ID explicitly attached to the milestone. Display labels,
  case-folded aliases, substrings, and an unlinked concept with a colliding
  label cannot complete the target. Proposal validation also rejects ambiguous
  case/whitespace-normalised concept labels.
- Checkpoint compatibility replay reuses the canonical checkpoint timestamp
  for a supplied idempotency key, preventing a secondary evaluation timestamp
  from turning an exact retry into a false conflict.

### Regression coverage

Tests now cover password-empty scripted cookie/header forgery, wrong BasicAuth,
configured-auth success, each CLI learner mutation in non-TTY and interactive
contexts, blockquote/list/nested Mermaid fences and indented literals, exact
stable concept identity, unlinked label collisions, alias/case/display-label
rejection, and checkpoint replay across a wall-clock boundary.

### Round-3 final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py \
  packages/studyloop/tests/test_plan_agent_harness.py -q
# 136 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 303 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 644 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright <changed round-3 source files>
# 0 errors, 0 warnings, 0 informations
```

Ruff check and format-check, Python compilation, and `git diff --check` also
passed on the final round-3 tree.

## Fix round 4 — secret handoff and exact concept identity

Round 3 correctly required configured Basic Auth for browser learner
authority, but the same reusable credential then crossed agent-readable
session IPC, the background web-server command line, ttyd argv, and the
session-state response. It also left one exact-duplicate-label route from an
unlinked stable concept ID to verified milestone completion.

### Changes

- Background session launch now sends the resolved username/password to the
  web child through a bounded, one-shot anonymous pipe. Only the read
  descriptor number appears in argv; the child consumes and closes it before
  application construction, and the parent closes its copy immediately after
  spawn. No credential is added to an environment variable.
- Session-state reads, writes, and dashboard IPC defensively strip
  credential-bearing keys recursively. `start_session` no longer asks the IPC
  writer to persist `lan_password`, and the real `/api/session/state` response
  cannot return a legacy credential field.
- General FastAPI `app.state` retains only the non-secret username and a
  boolean `lan_auth_configured` marker. The reusable password is held only by
  `BasicAuthMiddleware`; learner-session policy reads the boolean marker after
  successful middleware authentication.
- ttyd is always loopback-only and receives no password in argv. LAN terminal
  access continues through StudyLoop's authenticated same-origin HTTP/WebSocket
  proxy, so this removes a credential copy without weakening the outer auth
  boundary.
- Raw import rejects a milestone label that matches multiple concept IDs. A
  unique missing import label receives one fresh stable concept ID so simple
  legacy imports remain lossless. Tolerated existing documents fail closed at
  verified-completion time when any milestone label resolves to zero or
  multiple stable IDs, including when evidence names the milestone directly.

### Round-4 RED evidence

The first evidence probes both reported `DID NOT RAISE`: a raw import accepted
two `SQL` concept IDs and an unlinked duplicate ID completed the milestone.
The credential probes showed the legacy password in `read_session_state()`,
the state response DTO, and the direct `lan_password` update emitted by the
actual `start_session` orchestration. The original web child accepted no
credential FD, and LAN ttyd still bound `0.0.0.0` with `-c user:password`.

### Round-4 final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py \
  packages/studyloop/tests/test_plan_agent_harness.py \
  packages/studyloop/tests/test_session_start.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_orchestrator.py \
  packages/studyloop/tests/test_web_session.py \
  packages/studyloop/tests/test_web_app.py \
  packages/studyloop/tests/test_lan_auth.py \
  packages/studyloop/tests/test_web_session_start_pty.py \
  packages/studyloop/tests/test_web_session_start_acp.py \
  packages/studyloop/tests/test_web_session_start_service.py -q
# 281 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 306 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 646 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_terminal_proxy.py \
  packages/studyloop/tests/test_orchestrator.py \
  packages/studyloop/tests/test_session_start.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web_session.py \
  packages/studyloop/tests/test_lan_auth.py -q
# 106 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright <changed round-4 source files>
# 0 errors, 0 warnings, 0 informations
```

Targeted Ruff check and format-check, Python compilation, the Task 5
architecture gate, and `git diff --check` also pass.

## Fix round 5 — sealed learner credential boundary

The final independent review showed that round 4 had moved the password rather
than removed it: public argv and plaintext config were still readable by the
same unsandboxed agent, Starlette retained another repr-visible copy, ttyd
received browser authority headers, and the browser-helper fork inherited the
credential read descriptor. Round 5 closes those sources without beginning the
Task 6 onboarding/agent-install work.

### Changes

- Public `studyloop web/study --password` no longer exists and is explicitly
  rejected by Click. LAN launch obtains a password only through a real human
  terminal before any agent detection/setup/launch; non-interactive fallback is
  refused. `studyloop config lan-password` provides a separate interactive way
  to persist LAN auth without putting the password in argv.
- Settings and config retain only a versioned, randomly salted scrypt verifier
  with fixed bounded work parameters. A legacy `lan_password` is hashed and
  removed by an owner-only, fsynced atomic config replacement. Invalid verifier
  data and failed migration stop startup rather than disabling auth. `Settings`
  has no plaintext password field.
- Valid and recognisably credential-bearing malformed legacy session-state
  files are scrubbed atomically during the read itself. An unwriteable state
  refuses session startup before agent detection with an actionable error.
- The session parent hands only the non-replayable verifier to the web child
  through the bounded pipe. Its read descriptor closes immediately after a
  successful `Popen`, before state writes or `_open_browser()` can fork, and it
  closes on every spawn failure path. ttyd receives no credential parameters.
- `create_app()` accepts only a verifier. Basic Auth checks the presented human
  password with scrypt; a bound middleware factory keeps password/verifier
  material out of `app.user_middleware`, generic app state, DTOs, logs, and
  exception values.
- The terminal proxy terminates StudyLoop authority. HTTP requests strip Basic
  Auth, proxy auth, cookies, Set-Cookie, CSRF/XSRF, and session-token headers;
  responses also strip authority/challenge headers. The WebSocket connection
  forwards no browser headers beyond the selected terminal subprotocol.
- User-facing CLI/setup/web docs now describe interactive auth, atomic legacy
  migration, the safe persistent-password command, and verifier-only config.

### Round-5 RED evidence

The new regressions first failed because the credential module did not exist,
legacy plaintext remained in raw config and session files, the public help
still advertised `--password`, `create_app` accepted no verifier, Starlette's
middleware kwargs exposed the credential, and the parent FD remained open at
the browser fork. Real loopback servers then captured `Authorization` over both
HTTP and WebSocket, while a fake ttyd response returned `Set-Cookie` and CSRF
headers to the browser. An unwriteable legacy state raised raw `OSError` only
after agent detection. Each test now observes the secure external behaviour,
not a mocked header builder or source-text assertion.

### Round-5 final verification

```text
rtk uv run --group dev pytest <Task 5 planning + session/auth/proxy/launch slice> -q
# 314 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 306 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 645 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_lifecycle_commands.py \
  packages/studyloop/tests/test_planning_lifecycle_evidence.py -q
# 37 passed (including the duplicate-label evidence regressions)

rtk uv run --group dev pyright <changed round-5 production modules>
# 0 errors, 0 warnings, 0 informations
```

Targeted Ruff check and format-check, Python compilation, `mkdocs build
--strict`, and `git diff --check` also pass. A real subprocess regression starts
the public LAN web command, observes HTTP 401 readiness, inspects its live `ps`
argv, and verifies the legacy config bytes were replaced without exposing the
password.

The full staged `rtk pre-commit run` passed every applicable hook except the
repo-wide `pyright (studyloop)` hook. It reports 30 existing errors confined to
unchanged `planning/repository.py` and `web/routes/session/_ws.py`; neither file
appears in this round's staged diff. The targeted Pyright command above covers
all changed round-5 production modules with zero errors. The scoped commit
therefore skips only `pyright-studyloop` rather than expanding Task 5 into that
unrelated type debt.

### Honest limitations

- HTTP Basic Auth on an ordinary LAN is still cleartext transport unless the
  deployment adds TLS or a trusted encrypted tunnel. This round prevents the
  local agent and ttyd from receiving reusable authority; it does not add HTTPS.
- A verifier migrated from an existing weak password remains guessable offline.
  New generated passwords are high entropy, but password-quality policy and
  transport hardening remain release-security decisions outside Task 5.
