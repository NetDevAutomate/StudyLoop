# Task 7 report — durable confined planning conversations

## Outcome

Task 7 is implemented as a local, durable application boundary. It adds a
private SQLite conversation store, a bounded model/tool loop, crash recovery,
and one fixed-destination OpenAI-compatible adapter without adding any Task 8
route, CLI, browser, session-authentication, or learner-decision workflow.

The conversation database supplements the Task 3/4 JSON journal and
`private_runs`; it does not replace, compact, redact, migrate, or automatically
expire those artifacts.

## Delivered boundary

### Durable conversation truth

- `ConversationStore` owns a dedicated `planning-conversations.sqlite3` below
  `PlanningPaths.root`.
- The planning root is forced to mode `0700`; the database, WAL, and SHM are
  forced to mode `0600` whenever present.
- Migrations create conversations, ordered context attachments, frozen context
  snapshots, learner turns, ordered attempts, capability intents/results,
  finalized messages, decision intents/projections, proposal projections, and
  a monotonic per-conversation outbox.
- `BEGIN IMMEDIATE` transactions serialize attach/capture races and all CAS,
  result/outbox, finalized-message/outbox, and attempt-state transitions.
- One stable learner `turn_id` owns ordered, immutable attempt identities. The
  binding partial unique indexes enforce one non-terminal turn and one active
  attempt per conversation/turn.
- A first attempt and an interrupted retry are explicit compare-and-swap
  operations. Retry retains the learner turn, allocates the next sequence, and
  cannot start while any original capability intent is unresolved.
- An attempt cannot complete without both a durable finalized assistant message
  and fully reconciled capability intents.
- Exact capability/decision/result retries replay their stored projection;
  changed inputs conflict rather than fork durable truth.

### Confined runtime

- `PlanningConversationRuntime.accept_turn()` persists the inbound learner turn
  and frozen context before the first provider request.
- `retry_turn()` is explicit. It reconstructs the safe transcript and projected
  tool exchanges from durable records; it does not claim token-perfect provider
  continuation.
- The runtime enforces hard model-round, tool-call, output-token request,
  output-character, input-character, and wall-clock bounds.
- Unknown tools, forbidden tools, malformed/dynamic arguments, model authority,
  and out-of-sequence calls are normalized and rejected before a capability
  intent or lifecycle effect exists.
- Every allowed call commits the normalized original
  `(conversation_id, turn_id, attempt_id, run_id, tool_call_id)` scope, payload
  digest, and derived lifecycle idempotency key before dispatch.
- Recovery reconciles the original intent through the Task 3/4 lifecycle journal
  before interruption/retry allocation. Journal replay uses the original key.
- Capability result plus outbox and finalized assistant message plus outbox are
  atomic. Recovery completes an attempt with an already-finalized message
  without regenerating it; otherwise it durably marks the attempt retryable.
- Provider failures are exposed as generic public exceptions. Private
  interruption state retains only allowlisted domain detail or the exception
  class, not arbitrary provider diagnostics.

### Fixed model egress

- `OpenAICompatiblePlanningModel` derives the sole destination, model, headers,
  and capability catalogue from the configured profile and packaged contracts.
- The HTTP client disables proxy-environment inheritance and redirects.
  Loopback profiles additionally verify a loopback peer.
- The request contains the packaged prompt, bounded safe messages, and exactly
  the three planning capability schemas.
- Streamed OpenAI tool-call fragments are normalized into typed events.
  Malformed chunks, changed/duplicate tool identities, unfinished calls, and
  model-supplied transport/header/schema controls are rejected.
- Request-capture tests distinguish StudyLoop-owned metadata from verbatim
  learner content: configured sensitive values and internal/source-path labels
  are visibly redacted, while a learner-authored path or URL remains learner
  text.

### Capability and factory integration

- Capability calls can be fully normalized without side effects before their
  write-ahead intent.
- The dispatcher validates that the persisted lifecycle key matches the
  conversation/turn/attempt/run/tool-call scope and passes that exact key to
  prepare/submit/replay.
- `ModelRequest` carries the immutable output-token ceiling.
- Canonical runtime factories bind the dedicated store and existing lifecycle
  beneath the same planning root.
- Production Task 7 modules import no ACP, PTY, MCP/FastMCP, subprocess,
  browser, session-WebSocket, shell-wrapper, or general tool-registry runtime.

## TDD evidence

Implementation proceeded from focused failures. Representative RED results
included:

- conversation modules and contracts absent at initial collection;
- context-freeze replay and exact learner/request mismatches accepted before
  the store contract existed;
- the lifecycle seeing a newly derived rather than persisted capability key;
- adapter requests accepting destination/header/schema-shaped stream controls;
- retry missing durable tool-result reconstruction and permitting a second
  `prepare_plan` effect;
- internal endpoint labels reaching captured egress;
- provider diagnostic text having no private-store inspection seam;
- final-message crash points being treated only as interruption; and
- most recently, a direct store caller completing an active attempt without a
  finalized assistant message (`DID NOT RAISE`) before that invariant was moved
  into the transaction.

Each RED was run before the corresponding implementation change. The final
focused suite is green.

## Crash and concurrency evidence

Real spawned subprocesses exit at the following injected boundaries and are
then opened by a fresh process/runtime:

- before and after capability-intent commit;
- before and after lifecycle dispatch (including journal commit before SQLite
  projection);
- before and after capability result/outbox projection;
- before durable interruption;
- before and after retry CAS;
- before and after finalized-message/outbox commit; and
- before and after attempt completion.

The tests assert one original projection/outbox, monotonic attempt history, no
duplicate provider regeneration after a finalized message, and a durable
interruption otherwise. Separate two-process barrier tests prove exactly one
winner for both first-attempt and retry CAS. A spawned attach/capture race proves
the serialized winner yields either a wholly included or wholly excluded
context attachment.

## Coexistence and authority evidence

- A scripted prepare/submit/get round trip uses the real Task 3/4 lifecycle and
  leaves its typed journal and private artifacts readable.
- A stale brief-context digest is durably refused and creates no proposal.
- Proposal generation creates no active plan and no study/progress/confidence/
  completion state.
- Supplied context remains tier four and creates no trusted evidence.
- The plan decision store is present for Task 8 durability, but the model runtime
  has no learner authority and cannot approve, reject, or activate a plan.

## Final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_conversation_store.py \
  packages/studyloop/tests/test_planning_conversation_runtime.py \
  packages/studyloop/tests/test_planning_conversation_recovery.py \
  packages/studyloop/tests/test_planning_openai_compatible.py -q
# 55 passed in 2.96s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_model_config.py \
  packages/studyloop/tests/test_planning_capabilities.py \
  packages/studyloop/tests/test_planning_prompt_package.py \
  packages/studyloop/tests/test_planning_scripted_model.py \
  packages/studyloop/tests/test_doctor_planning.py -q
# 287 passed in 1.33s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning*.py \
  packages/studyloop/tests/test_plan_agent_harness.py \
  packages/studyloop/tests/test_doctor_planning.py \
  packages/studyloop/tests/e2e/test_plans_api.py -q
# 649 passed, 12 deselected in 8.65s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web_runtime_feedback.py -q
# 60 passed in 1.37s
```

Targeted Pyright reports `0 errors, 0 warnings, 0 informations`. Targeted Ruff
check and format check pass. Python compilation, `git diff --check`, and the
changed-file detect-secrets pre-commit hook pass.

## Deliberate limits

- No Task 8 HTTP/WebSocket route, browser UI, CLI adapter, session/CSRF/origin
  authority, capacity endpoint, or decision actor is implemented here.
- No live provider/model call is required or claimed. The adapter is exercised
  through an observable injected gateway transport and the runtime through the
  deterministic scripted model.
- Retry is semantic reconstruction from durable finalized records, never a
  token-perfect stream resume.
- There is no automatic expiry, retention migration, artifact compaction, or
  deletion policy.
- Rejected and superseded local recovery bodies may remain, consistent with the
  exact privacy notice.
- The existing SDD progress ledger was not edited or staged by Task 7.

## Fix round 1 — recovery, bounds, privacy, and containment hardening

The independent review of `87e6186` found seven Important issues. All seven
were reproduced before implementation and fixed within the Task 7 boundary.

### RED evidence

- The first store adversarial slice produced 12 failures: empty/shorter inbound
  source-reference prefixes replayed as identical, embedded paths/endpoints were
  persisted, database symlinks escaped, sidecar symlinks reached SQLite, and a
  symlinked planning parent was followed.
- The first runtime adversarial slice produced 13 failures: a leaky provider
  remained in `ModelAttemptError.__cause__`, cancellation left an active
  attempt, ordinary/cancelled post-finalization failures misclassified durable
  state, an infinite output stream reached the outer timeout, serialized tool
  arguments bypassed the input bound, oversized typed tool fields reached schema
  handling, and embedded metadata reached egress.
- The adapter slice produced five failures because stream/chunk, partial-name,
  partial-argument, and raw SSE line/aggregate bounds did not exist.
- The spawned live-provider race failed because recovery interrupted the live
  attempt, retry then reported only a stale version, and the original provider
  could no longer finalize.
- Follow-up mutation cases independently failed for unowned terminal writes,
  unowned message/capability writes, adapter output overflow, embedded IPv6
  loopback/private host:port metadata, and an infinite same-round tool stream.

### Ownership and terminal truth

- Attempts now persist an opaque runtime owner and wall-clock lease. The owner
  heartbeats while the provider task is alive. Recovery can only claim an
  expired attempt using a second durable CAS; a renewed/live attempt is read but
  not mutated.
- The real spawned race uses a `0.08` second lease and keeps the provider alive
  for `0.2` seconds. A second process performs both recovery and retry while the
  heartbeat renews: no interruption/outbox/version change occurs, retry is a
  read-only conflict, and the original provider completes once released.
- Retry no longer invokes recovery. It checks the caller's exact version and an
  already-durable interrupted latest attempt before its allocation CAS.
- Complete, interrupt, finalized-message, new capability-intent, active
  dispatch, and active projection writes require the current durable owner.
  Tests also expire and recovery-claim an attempt, then prove the former owner
  cannot write a response or capability intent.
- Cancellation is caught separately and terminalized synchronously. Ordinary
  exceptions and cancellation at all four final-message/attempt-complete
  boundaries classify from SQLite truth: a durable finalized message completes
  the attempt; absence interrupts it. A completed attempt is left unchanged.

The default lease is 30 seconds. This intentionally means a genuinely crashed
attempt is not guessed dead immediately; recovery becomes eligible only after
lease expiry. Subprocess crash tests use a short injected lease and wait for its
expiry before recovery.

### Incremental bounds and safe failures

- Runtime events are validated directly from the async iterator. Event, output,
  same-round/aggregate tool, tool-name, tool-ID, and serialized argument bounds
  stop and close the provider iterator at the first excess item.
- The input bound counts the complete canonical serialized messages, including
  assistant `tool_calls`, rather than only `content` strings.
- The OpenAI adapter separately bounds chunks, aggregate normalized bytes,
  emitted output/events, partial tool count/name/ID/arguments, and raw SSE
  line/aggregate bytes. Raw HTTP parsing uses bounded byte buffering instead of
  `aiter_lines()`.
- Generic provider errors are converted outside the provider exception handler,
  so the public exception has neither `__cause__` nor `__context__`. Repr,
  formatted traceback, and a formatted log record contain no provider secret,
  internal endpoint, or server path.

### Exact input, metadata, and filesystem containment

- Each turn stores the exact original inbound request JSON, domain-separated
  digest, and original reference count separately from the lifecycle request
  augmented with frozen StudyLoop attachments. Empty, shorter, longer,
  reordered, or changed references conflict; exact attachment-backed replay
  remains idempotent.
- StudyLoop metadata scanning covers embedded POSIX paths, Windows/UNC paths,
  `file:` forms, internal URLs, IPv4/IPv6 loopback/private host:port forms, and
  prose/punctuation. The metadata field is replaced before persistence and
  egress. Learner-authored URLs and paths remain verbatim in the learner channel.
- Before SQLite open, the store rejects a pre-existing symlinked database, WAL,
  SHM, planning parent, or resolved escape. Outside targets remain absent in
  those cases, while the root/database/live-sidecar `0700`/`0600` modes remain
  enforced. Fix round 2 narrows and strengthens the check/open claim below.

### Fix-round verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_conversation_store.py \
  packages/studyloop/tests/test_planning_conversation_runtime.py \
  packages/studyloop/tests/test_planning_conversation_recovery.py \
  packages/studyloop/tests/test_planning_openai_compatible.py -q
# 98 passed in 4.42s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning*.py \
  packages/studyloop/tests/test_plan_agent_harness.py \
  packages/studyloop/tests/test_doctor_planning.py \
  packages/studyloop/tests/e2e/test_plans_api.py -q
# 692 passed, 12 deselected in 9.39s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_model_config.py \
  packages/studyloop/tests/test_planning_capabilities.py \
  packages/studyloop/tests/test_planning_prompt_package.py \
  packages/studyloop/tests/test_planning_scripted_model.py \
  packages/studyloop/tests/test_doctor_planning.py -q
# 287 passed in 1.26s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web_runtime_feedback.py -q
# 60 passed in 1.29s
```

Targeted Pyright again reports `0 errors, 0 warnings, 0 informations`. Targeted
Ruff, format, Python compilation, changed-file secret scan, and diff checks are
rerun before the fix commit. No Task 8+ code is included. The separately
modified progress ledger is intentionally left unstaged.

## Fix round 2 — independent liveness, resumable migration, and honest containment

The independent review of `4f00a47` found four further Important issues. All
four were reproduced with adversarial tests before their production fixes.

### RED evidence

- A real second process held the repository's root lock beyond the `0.08`
  second attempt lease. Synchronous lifecycle dispatch starved the asyncio
  heartbeat; competing recovery stole and interrupted the live attempt, and the
  original owner then failed to finalize.
- Five independently missing hardening columns produced duplicate-column or
  missing-column SQLite failures. An attachment/source-reference ID collision
  was guessed to be an injected attachment, so reopening fabricated a different
  inbound projection and rejected the real replay as merely different input.
- StudyLoop-owned labels containing `/secret` or `~/secret` survived
  persistence/model egress, and a typed runtime diagnostic exposed both in its
  public error representation and traceback.
- Deterministic swaps between validation and SQLite open followed a database or
  planning-parent symlink. Deterministic swaps between existence check and
  `chmod` followed database/WAL/SHM targets, changing the outside file's mode.

### Lifecycle liveness and one logical outcome

- Potentially blocking lifecycle dispatch/reconciliation now runs through
  `asyncio.to_thread`, leaving the event loop available for durable lease
  renewal. Provider streaming remains on the bounded async path.
- Recovery starts a heartbeat for every expired attempt it successfully claims
  and keeps those heartbeats alive through journal reconciliation, result
  projection, and terminal classification.
- Two spawned-process tests hold the real `PlanningRepository` root lock longer
  than the lease. One covers an original live attempt; the other covers an
  expired attempt claimed by recovery. A competing recovery has zero effect in
  both cases, while the original/claiming owner records exactly one lifecycle
  result and one terminal outcome.

### Transactional, provenance-honest migration

- Every turn/attempt hardening column is checked and added independently inside
  one explicit `BEGIN IMMEDIATE` transaction. Schema and legacy-classification
  changes roll back together after process death and restart idempotently.
- Spawned crash tests terminate after each of six column additions and after
  legacy replay classification. Reopening restores a complete usable schema in
  every case. Separate partial-schema tests cover all five original grouped
  columns.
- New turns store `inbound_replay_state='exact'`. Existing/partial rows whose
  original inbound projection is not provable are classified `unavailable`;
  their augmented frozen request remains readable, but any replay fails closed
  with the explicit `exact replay unavailable for legacy learner turn`
  classification. Migration no longer subtracts snapshot IDs or guesses source
  provenance, including the attachment-ID collision case.
- A complete current schema returns from the hardening preflight without
  opening a write transaction or replay-classification hook, so constructing a
  second runtime does not needlessly contend with live lease renewal.

### Metadata and filesystem boundary

- Metadata-only path scanning now covers root-level absolute and home-relative
  paths as well as the existing multi-component, Windows, file-URI, and private
  endpoint forms. Persistence, captured model requests, interruption reasons,
  public exception repr/traceback, and separate learner-verbatim channels are
  exercised.
- The planning root and main database are opened with no-follow descriptors.
  Device/inode identity is checked before SQLite configuration and again after
  open; private modes use `fchmod` on verified descriptors. Deterministic
  database/parent open swaps and database/WAL/SHM mode-enforcement swaps fail
  closed without changing the outside target.
- The main-database anchor is closed before `sqlite3.connect`, and automatic
  mode enforcement runs only while this store has no live SQLite connection.
  This avoids POSIX's process-wide record-lock hazard where closing a second
  descriptor for the same SQLite file can release locks owned by the active
  connection. A benign WAL/SHM replacement or disappearance is tolerated while
  a no-follow symlink swap still fails closed. Repeated combined subprocess
  suites exercise this boundary.
- The binding design and implementation plan now state the precise limit
  prominently: this is protection for pre-existing and detected accidental
  substitutions, not integrity against hostile concurrent same-user pathname
  mutation. Python's standard `sqlite3` API exposes neither
  `SQLITE_OPEN_NOFOLLOW` nor a caller-controlled VFS for every SQLite-created
  database/WAL/SHM file. A privileged state owner or reviewed native VFS is a
  separate design if that threat model changes.

### Fix-round-2 verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_conversation_store.py \
  packages/studyloop/tests/test_planning_conversation_runtime.py \
  packages/studyloop/tests/test_planning_conversation_recovery.py \
  packages/studyloop/tests/test_planning_openai_compatible.py -q
# 124 passed in 6.85s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning*.py \
  packages/studyloop/tests/test_plan_agent_harness.py \
  packages/studyloop/tests/test_doctor_planning.py \
  packages/studyloop/tests/e2e/test_plans_api.py -q
# 718 passed, 12 deselected in 11.99s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_model_config.py \
  packages/studyloop/tests/test_planning_capabilities.py \
  packages/studyloop/tests/test_planning_prompt_package.py \
  packages/studyloop/tests/test_planning_scripted_model.py \
  packages/studyloop/tests/test_doctor_planning.py -q
# 287 passed in 1.27s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web_runtime_feedback.py -q
# 60 passed in 1.21s
```

Targeted Pyright, Ruff, format, Python compilation, diff, and changed-file
secret scans are rerun immediately before the fix commit. No Task 8 route,
adapter, CLI, UI, authority, or decision work is included, and the shared
progress ledger remains untouched and unstaged by Task 7.

## Fix round 3 — existing-only open and process-wide connection guard

The round-2 independent review found that the post-open identity check still
allowed SQLite to create an absent outside database before refusal, and that a
second store operation could close a descriptor and release another live
connection's process-wide POSIX locks. Both were reproduced before production
changes: the focused RED slice reported `5 failed, 1 passed`.

### Contained creation and configuration

- The main database is created, when absent, with `O_CREAT|O_EXCL` and
  `O_NOFOLLOW` relative to the verified planning-directory descriptor. Existing
  files are opened without a create flag. The anchor is mode-enforced and its
  device/inode identity captured before it is closed.
- SQLite then opens the pathname with URI `mode=rw`. A deterministic database
  or parent substitution to an initially absent outside database therefore
  cannot create the outside file. If open fails after substitution, anchored
  root/database validation converts the failure to the containment error.
- Directory and database identities are validated immediately after SQLite
  open, before row configuration or any PRAGMA, and again after configuration.
  Existing-outside swap tests retain their byte-for-byte unchanged assertion.

### Shared full-lifetime locking

- A process-local guard registry is keyed by the canonical database path and is
  shared by every `ConversationStore` instance. Its reentrant lock is held from
  descriptor anchoring through SQLite open, configuration, use, final close,
  and descriptor-based private-mode enforcement.
- Cross-thread operations on the same database serialize for the live
  connection's complete lifetime. Same-thread nested access leases and reuses
  that connection, avoiding both deadlock and an independent descriptor close;
  private-mode enforcement is deferred until its final lease closes.
- Real WAL-reader regressions prove an external process cannot change journal
  mode while either `list_turns()` or `ensure_private_modes()` is attempted by a
  second store. Separate nested-connect and nested-mode tests preserve the same
  lock, then prove it becomes available after the original reader closes.

The explicit threat boundary is unchanged: these controls cover deterministic
and accidental substitutions plus ordinary same-process store concurrency.
They do not claim integrity against a hostile concurrently racing same-user
process; that stronger boundary still requires a privileged owner or reviewed
native SQLite VFS.

### Fix-round-3 verification

```text
rtk uv run pytest \
  packages/studyloop/tests/test_planning_conversation_store.py \
  packages/studyloop/tests/test_planning_conversation_runtime.py \
  packages/studyloop/tests/test_planning_conversation_recovery.py \
  packages/studyloop/tests/test_planning_openai_compatible.py -q
# 130 passed in 10.60s
# 130 passed in 10.41s (independent second run)

rtk uv run pytest \
  packages/studyloop/tests/test_planning*.py \
  packages/studyloop/tests/test_plan_agent_harness.py \
  packages/studyloop/tests/test_doctor_planning.py \
  packages/studyloop/tests/e2e/test_plans_api.py -q
# 724 passed, 12 deselected in 16.40s

rtk uv run pytest \
  packages/studyloop/tests/test_planning_model_config.py \
  packages/studyloop/tests/test_planning_capabilities.py \
  packages/studyloop/tests/test_planning_prompt_package.py \
  packages/studyloop/tests/test_planning_scripted_model.py \
  packages/studyloop/tests/test_doctor_planning.py -q
# 287 passed in 1.46s

rtk uv run pytest \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web_runtime_feedback.py -q
# 60 passed in 1.50s
```

Targeted Pyright, Ruff, format, compilation, diff, secret, and orphan-process
checks are clean immediately before commit. No Task 8+ implementation is
included, and the separately modified progress ledger remains unstaged.
