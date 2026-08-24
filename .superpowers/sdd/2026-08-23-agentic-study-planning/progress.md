# SDD ledger — plan: docs/superpowers/plans/2026-08-23-agentic-study-planning.md

## Authority and baseline

- Spec: `docs/designs/agentic-study-planning.md` (reachable, binding).
- Plan: `docs/superpowers/plans/2026-08-23-agentic-study-planning.md`.
- Branch/worktree: `codex/agentic-planning` in the isolated agentic-planning worktree.
- Baseline: 3,701 unit tests passed; one grace-release race failed once and passed in isolation.
- Existing SPA boot defect is owned by Task 1.

## Pre-flight task consistency

| Task | Self-consistency check | Ruling |
|---|---|---|
| 1 | JS interfaces match the files and boot tests it names. | clean |
| 2 | v2 model fields, codec sections, and learning-map tests align. | clean |
| 3 | repository API covers lock, journal, recovery, and crash tests. | clean |
| 4 | lifecycle command union covers every normal mutation named in the spec. | clean |
| 5 | writer migration and forbidden-import test enforce Task 4's sole seam. | clean |
| 6 | packaged prompt/provider port/closed catalogue exclude learner decision and ambient tools. | redesigned; clean |
| 7 | SQLite runtime owns frozen turns, pre-dispatch capability intents, outbox, recovery, and retention. | fix round 1; clean |
| 8 | HTTP/WS/CLI/auth/context/decision adapters consume Task 7 without inventing a second loop/authority. | fix round 1; clean |
| 9 | browser/onboarding states consume Task 8 DTOs through an inert no-subresource renderer. | fix round 1; clean |
| 10 | stewardship uses frozen briefs, trusted evidence, and Task 8's decision adapter. | fix round 1; clean |
| 11 | replay/runtime gate covers intent ordering, auth, context races, retention, and server/browser egress. | fix round 1; clean |
| 12 | final verification rechecks every authority contract and cannot publish/merge. | fix round 1; clean |

## Pre-flight overlaps

| Tasks | Producer -> consumer / shared file | Finding and ruling |
|---|---|---|
| 1, 9 | Task 1 restores JS boot; Task 9 adds plan UI modules to that boot. | Sequential; Task 9 must retain AP-BOOT-01. |
| 2, 3 | Task 2 owns canonical bytes; Task 3 hashes and commits them. | Task 2 codec is authoritative; Task 3 must not add a second renderer. |
| 2, 4 | Task 2 domain types feed Task 4 contracts/policy. | Sequential; lifecycle references stable IDs, not labels. |
| 2, 9 | Task 2 derives Mermaid; Task 9 renders it. | Browser never authors or regenerates Mermaid. |
| 3, 4 | Task 3 commit/recovery supports Task 4 commands. | Lifecycle owns policy; repository owns persistence mechanics. |
| 4, 5 | Task 4 publishes the command seam; Task 5 migrates all old writers. | No raw store mutation remains outside repository after Task 5. |
| 4, 6 | Task 4 model-safe commands feed the closed dispatcher. | Runtime may prepare/submit/inspect only. |
| 4, 8 | Task 4 DTOs feed planning HTTP routes. | Route maps errors/status; no duplicated policy. |
| 4, 10 | Task 4 evidence/status commands feed Steward. | Steward is a responsibility, not a second persistence module. |
| 5, 10 | Both touch evaluation. | Task 5 first moves checkpoint writes; Task 10 adds adaptation only through lifecycle. |
| 6, 7 | Packaged prompt/provider/catalogue feed the conversation runtime. | No MCP/harness discovery; server fixes config. |
| 6, 8 | Server-owned model profile feeds conversation routes. | Browser supplies content, never endpoint/tools/credentials. |
| 7, 8 | Frozen-context/runtime/outbox APIs feed HTTP/WS/CLI and decisions. | Route/CLI adapters share one runtime; decision intent bridges journal/SQLite. |
| 7, 9 | Sequenced outbox DTOs feed plan panel. | Browser never adopts ACP/PTY/study state and never auto-fetches model output. |
| 8, 9 | API DTOs/auth/citations drive UI state. | JS/Playwright pin exact decisions and zero subresource egress. |
| 8, 10 | Revision conversations receive frozen Steward briefs. | Same decision state machine for create and revise. |
| 9, 11 | Browser tests become release-gate evidence. | Mermaid/tablet and no-subresource checks cannot skip/warn. |
| 6, 11 | Runtime manifest verifies prompt/profile/catalogue versions. | Scripted and live endpoint evidence both block release. |
| 2-11, 12 | Final docs consume verified behavior. | No capability promotion before aggregate gate. |

## Product rulings carried into execution

- Maximum three current plans counts draft, active, paused.
- Complete/abandoned plans do not count; ordinary hard deletion is removed.
- Planning does not use `AgentWorkspace`; PTY/ACP remain study-session
  integrations and their planning extraction is deferred.
- Manual Markdown editing is unsupported; external edits still trigger digest conflict.
- Imported harness activity may remain absent until one real identity-bearing adapter exists.
- Live and deterministic gates are distinct but both required for the confined
  runtime/public planning claim.
- The exact model catalogue is three tools: `prepare_plan`,
  `submit_plan_proposal`, and `get_plan_proposal`. The runtime has no ambient
  shell/filesystem/browser/arbitrary-network or learner/trusted-evidence tools.
- Browser session/CSRF is learner intent only under this confinement; there is
  no release-one integrity claim against hostile same-user software.
- Basic Auth/scrypt is LAN access control only. `--credential-fd` is transport
  plumbing and never learner authority; public LAN copy must warn about plain
  HTTP and weak-password verifier guessing.
- Release-one context is pasted or explicitly selected local text, tier four.
  Static public URL retrieval is a separate SSRF/rebinding-reviewed slice.
- `Resource.url` is inert citation data; tool schemas may carry it but never a
  fetch/destination/header field. Rich text cannot trigger subresource loads.
- Context freezes ordered IDs/digests and brief digest before attempt schedule;
  learner text may contain URLs/paths, while StudyLoop source metadata may not.
- Capability and decision intents commit before lifecycle dispatch and recover
  by original tuple/key before any new attempt or outbox projection.
- Private input has an injected-clock 29/30/31-day transactional purge with
  explicit accepted-plan provenance holds and owner-only modes.

## Task progress

- Task 1 observation: Node 26.7.0 does not discover `node --test <directory>`;
  focused verification uses `node --test packages/studyloop/tests/js/*.test.js`.
  Carry this command correction into Tasks 9 and 12.
- Task 1 observation: the broader render-validation file has one Mermaid
  error-SVG failure after SPA boot is restored. Task 9 owns plan-specific
  Mermaid and renderer release tests; do not treat the boot commit as proving
  AP-MERMAID-01.
- Mermaid root-cause observation: the lesson source parses and produces node
  shapes, but the rendered SVG has `viewBox="-8 -8 16 16"` because the reader
  is still hidden by `x-show` when Mermaid measures it. Task 9 must render only
  after the target is visibly laid out (and assert painted geometry), not just
  assert that an SVG exists.
- Task 1: minor (deferred): `session-timer.test.js` header still says
  THRESHOLDS is declared locally after it was changed to import production.
- Task 1: fix round 1/5 (2 addressed, 0 open — commits ed86705..3a2c37c).
- Task 1: complete (commits 6b111e5..3a2c37c, review clean).
- Task 2: initial review failed (1 Critical, 1 Important, 1 Minor).
- Task 2: minor (deferred): v2 table cells normalise intentional leading and
  trailing whitespace; decide and document canonical whitespace policy before
  the final codec gate.
- Task 2 council arbitration: digest/revision enforcement, lifecycle value
  validation, and v1 migration policy remain Tasks 3-5; milestone field loss
  and ambiguous learning-map identity are Task 2 defects and entered fix round
  1/5.
- Task 2: fix round 1/5 (2 addressed, 0 open — commits ce74065..04e67c9).
- Task 2: complete (commits 3a2c37c..04e67c9, review clean; whitespace Minor
  deferred to final codec gate).
- Task 3: initial review failed (2 Critical, 4 Important, 1 Minor).
- Task 3: minor (deferred): legacy raw writers are deprecated by docstring but
  do not emit caller-visible warnings; Task 5 owns migration/enforcement.
- Task 3 council arbitration: Windows portability, replacing the agreed
  journal design, compaction, and Task 5 writer migration are out of scope;
  torn-tail repair and recovery directory fsync are confirmed Task 3 defects.
- Task 3: entered fix round 1/5 for stale CAS, recovery durability, unsigned v2,
  torn journal tails, event consistency, and real subprocess-death evidence.
- Task 3: fix round 1/5 (5 addressed, 1 Important open — commits
  4b33e74..d30aecd). Terminal result validation still accepts forged document
  and structure revisions during idempotent replay.
- Task 3: entered fix round 2/5 for strict terminal revision validation.
- Task 3: fix round 2/5 (1 addressed, 0 open — commit d46510c).
- Task 3: complete (commits 04e67c9..d46510c, review clean; raw-writer
  warning Minor deferred to Task 5).
- Task 5 preflight: raw writers exist in CLI create/evaluate/milestone/status,
  REST create/patch/toggle/evaluate/delete, evaluation persistence, public
  store re-exports, and the scratch harness. Immediate overwrite, bare toggle,
  and public hard-delete semantics cannot survive the lifecycle boundary.
- Task 5 preflight: production must have one PlanningPaths factory. The legacy
  plans directory is already the document directory, while `in_root()` adds a
  `plans/` child; blindly composing them would lock and journal the wrong root.
- Task 4: initial review failed (0 Critical, 2 Important). Concurrent identical
  prepare/submit/approve/import/checkpoint commands can conflict after
  pre-lock ID/timestamp allocation, and stale proposal rejection bypasses the
  current-context guard.
- Task 4 council arbitration: adapter bypass and end-to-end evidence wiring
  remain Tasks 5/10/11; scale, Windows, and tier-research requests are outside
  this local release. Concurrent idempotency is confirmed Task 4 scope.
- Task 4: entered fix round 1/5 for concurrent deterministic replay and stale
  rejection refusal.
- Task 4: fix round 1/5 (stale rejection addressed; live semantic retry races
  addressed; 1 Important recovery gap open — commit 92149a9). After a
  recovered-before crash, an identical semantic retry can commit with a new
  raw payload digest and make later journal validation fail.
- Task 4: entered fix round 2/5 for recovered-before semantic replay history.
- Task 4: fix round 2/5 (recovered-before lifecycle retry addressed; 1 new
  Important pre-commit validation gap open — commit d373ca6). Repository commit
  can append an operation-incompatible semantic retry that the next read then
  correctly rejects as corrupt.
- Task 4: entered fix round 3/5 for pre-append semantic-lineage validation.
- Task 4: fix round 3/5 (1 addressed, 0 open — commit 3d9d671).
- Task 4: complete (commits d46510c..3d9d671, review clean after three fix
  rounds; adapter exclusivity intentionally remains Task 5).
- Task 6 preflight: architect auto-install coverage is currently zero. Claude,
  Kiro, Gemini, and OpenCode have orphaned legacy architect definitions;
  Codex/Pi/OMP have no planning responsibility. Grok/Amp/backend-only Ollama
  and LM Studio must not be claimed without a real certified harness path.
- Task 6 preflight: installer, setup detection, runtime adapters, doctor, and
  manifest describe different support sets. Introduce one typed harness-support
  descriptor, capability-scope the three model tools, and test every installed
  architect/resource/transport rather than one definition per harness.
- Task 5: initial review failed (3 Critical, 5 Important). The green adapter
  suites missed caller-minted learner/recorder authority, destructive revision
  defaults, cross-plan decisions, unsafe recognised-field imports, incomplete
  writer-surface guards, non-idempotent checkpoint indexing, and ambiguous
  duplicate-label legacy links.
- Task 5: entered fix round 1/5 for exact digest-bound decisions, trusted
  evidence ownership and subject matching, lifecycle-state-preserving revisions,
  plan-bound decisions, import sanitisation, writer-guard/harness safety,
  checkpoint idempotency, and ambiguous legacy concept refusal.
- Task 5: fix round 1/5 implementation reports all eight findings addressed in
  commit 4dfe511; independent re-review is required before Task 6 starts.
- Task 5: fix round 1/5 review left 2 Critical and 2 Important. Exact CAS
  binding still did not prove human learner authority; blank-ID v1 milestone
  completion could still be lost; tilde Mermaid fences crossed import; and
  substring concept matching could verify the wrong milestone.
- Task 5: entered fix round 2/5 for an interactive/CSRF-protected learner
  boundary, lossless legacy state handling, parsed fence rejection, and exact
  evidence identity matching.
- Task 5: fix round 2/5 implementation reports all four findings addressed in
  commit 55b5509; independent re-review is required before Task 6 starts.
- Task 5: fix round 2/5 review left 2 Critical and 2 Important. CSRF and fetch
  metadata can be forged by a local shell-capable model when web Basic Auth is
  disabled; CLI status/milestone still minted learner context noninteractively;
  CommonMark container fences escaped the import filter; and case-folded labels
  still allowed evidence identity aliasing.
- Task 5: entered fix round 3/5 for fail-closed authenticated web authority,
  interactive protection of every CLI learner mutation, CommonMark-aware fence
  rejection, and stable-ID-only evidence matching.
- Task 5: fix round 3/5 implementation reports all four findings addressed in
  commit 24a3d06; independent re-review is required before Task 6 starts.
- Task 5: fix round 3/5 review left 1 Critical and 1 Important. The configured
  learner password still crossed agent-readable session IPC, process argv, and
  session-state DTOs; duplicate concept display labels could still make an
  unlinked stable ID qualify as milestone evidence.
- Task 5: entered fix round 4/5 with a fresh implementer for end-to-end secret
  boundary enforcement and fail-closed duplicate-label evidence relations.
- Task 5: fix round 4/5 implementation reports both findings addressed in
  commit ec42007 via one-shot credential handoff, recursive redaction, and
  duplicate-label refusal; independent re-review is required before Task 6.
- Task 5: fix round 4/5 review left 1 Critical and 2 Important. Public password
  argv/plaintext config and unsanitised legacy state still exposed authority;
  middleware metadata and terminal proxy headers retained credentials; and the
  browser helper inherited the credential FD.
- Task 5: entered final fix round 5/5 with another fresh implementer. The gate
  now requires a non-reversible/non-agent-readable authority source, atomic
  legacy scrubbing before agent launch, proxy/middleware secret minimisation,
  and strictly bounded FD ownership.
- Task 5: fix round 5/5 implementation reports all three findings addressed in
  commit a323a7a with verifier-only storage/migration, interactive pre-agent
  secret collection, proxy stripping, and closed FD ownership. Independent
  final re-review is required; any remaining Critical/Important blocks Task 6
  and triggers redesign rather than a sixth patch loop.
- Task 5: final round-5 review remained blocked (2 Critical, 2 Important).
  Same-user callers could mint verifier/FD authority, non-mapping legacy JSON
  retained secrets, a plaintext feedback DTO remained, and public LAN security
  caveats were incomplete. No sixth patch loop is permitted.
- Authority redesign council: four providers responded (Anthropic, OpenAI, xAI,
  Moonshot). Privileged broker plus native user presence is the strongest
  literal hostile-process boundary but is disproportionate for this release;
  browser WebAuthn also requires trustworthy HTTPS/enrollment and does not
  protect a same-user writable verifier/state implementation.
- Authority redesign direction under validation: make the planning model a
  StudyLoop-owned capability-scoped runtime with no shell/filesystem/browser or
  arbitrary network access, expose only safe proposal tools, keep learner
  decisions outside that tool surface, and make harness support claims depend
  on enforceable confinement rather than persona instructions.
- Authority redesign arbitration accepted (2026-08-24): release one uses
  `PlanningConversationRuntime` over a fixed server-configured
  OpenAI-compatible endpoint, initially an auto-detected local LiteLLM gateway.
  The model sees the immutable three-tool catalogue only. External harnesses
  remain supported for study and unsupported for agentic planning.
- Authority redesign arbitration accepted: durable SQLite conversations,
  attempts, capability calls/results, and transactional outbox replace the
  proposed planning `AgentWorkspace`. Recovery restarts an interrupted logical
  turn and never pretends to resume provider tokens.
- Authority redesign arbitration accepted: course/note ingestion is learner/
  server-owned tier-four context. First slice is pasted/selected local text;
  public static URL retrieval is deferred behind a separate SSRF,
  DNS-rebinding, redirect, address, type, size, and timeout review.
- Authority redesign arbitration accepted: deterministic/live gates must
  capture the exact outbound tool catalogue and gateway destination, attempt
  every forbidden authority/ambient tool, prove zero side effects/non-gateway
  egress, exclude StudyLoop-injected secrets, internal endpoints, and source
  path metadata from model input while preserving verbatim learner URLs/paths,
  and pass vague
  no-notes, crash/replay, Mac/tablet, Mermaid-geometry, capacity, and
  no-progress journeys.
- Authority redesign rejected for release one: privileged daemon/native
  biometric broker and WebAuthn enrollment/TLS/recovery are disproportionate
  to the present local-first threat claim. They become required if the product
  later claims resistance to hostile same-user processes.
- Task 6 preflight support-matrix findings remain useful only for study-session
  support honesty. They no longer drive planning persona installation because
  no external harness is a release-one planning provider.
- Tasks 6-9 and Task 11 were rewritten in the binding plan. Task 5's writer
  migration evidence remains, while its broad human-provenance interpretation
  is explicitly superseded; no product code was changed by this arbitration.
- Authority redesign independent review blocked commit 5fe4907 with seven
  Important contract gaps: localhost learner-session ownership, missing CLI
  conversation delivery, no pre-dispatch capability intent, no write-ahead
  decision reconciliation, citation/browser egress ambiguity, unfrozen context
  plus overbroad input redaction, and non-executable private-input retention.
- Authority redesign docs fix round 1 assigns localhost/LAN session behavior and
  direct tests to Task 8. Loopback navigation may mint an expiring app-local
  session without Basic; LAN must verify Basic first. Both require exact origin,
  CSRF, and proposal binding; FD/model/wrong-auth/cross-origin paths cannot mint
  `ActorContext`.
- Fix round 1 retains `studyloop plan start` and assigns `_plan.py` plus CLI
  conversation tests to Task 8. CLI and web share store/runtime/dispatcher/
  decision adapter for turn, context, retry, stop, preview, and exact decision;
  no second loop or harness fallback is allowed.
- Fix round 1 gives Task 7 durable normalized capability intent with original
  tuple, payload digest, and lifecycle key committed before dispatch. Recovery
  reconciles that original journal operation before a new attempt. Task 8 uses
  the same write-ahead/reconcile/project pattern for learner decisions.
- Fix round 1 defines `Resource.url` as inert citation data and requires Task 9
  to neutralize all auto-fetching Markdown/HTML/SVG/CSS/media constructs.
  Playwright must observe zero automatic internet/private/link-local/loopback
  subresource requests; gateway detection is literal-loopback-only with proxies
  and redirects disabled before pinning.
- Fix round 1 makes context freeze transactional with the learner turn and
  snapshots ordered IDs/digests plus brief digest. Input minimisation tests
  separate StudyLoop metadata/secrets/endpoints from verbatim learner text,
  which may legitimately contain paths/URLs.
- Fix round 1 gives Task 7 an injected-clock, startup-triggered, idempotent
  transactional retention API. The gate covers 29/30/31 days, accepted plan
  provenance holds, rejected/superseded redaction, purge crash/retry, stable
  digests/audit/outbox, and `0600`/`0700` storage.
