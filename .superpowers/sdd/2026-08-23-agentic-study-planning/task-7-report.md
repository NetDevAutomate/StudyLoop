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
