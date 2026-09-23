## Findings

Reviewed the supplied source and diffs; no repository execution performed. Runtime conclusions below are marked **UNVERIFIED**.

- 🟡 **UNVERIFIED — `packages/studyloop/src/studyloop/mcp/tools.py:868–873`; `packages/studyloop/tests/test_mcp_teachback.py:47–51` — MCP input coercion may defeat the claimed CLI-equivalent integer validation.**
  Every new functional test calls the registered `.fn`, bypassing FastMCP argument validation. With `scores: list[int]`, transport validation may convert booleans or integral floats before `coerce_scores()` can reject them; the CLI rejects `"True"` and `"3.0"`.
  **Correction:** add `test_wire_validation_matches_cli` through the actual MCP invocation path, covering booleans, integral/fractional floats, numeric strings, malformed strings, wrong lengths and range violations. Assert rejection leaves storage unchanged. If coercion changes acceptance, make the boundary strict or preserve raw values for the shared validator. **Done:** documented acceptance agrees across both surfaces, including transport validation.

- 🟡 **`packages/studyloop/tests/test_adapter_parity.py:153–176` — the “no new pre-approval” guards do not establish what their names claim.**
  Kiro’s exact-name intersection would miss a newly granted server wildcard; OpenCode’s substring checks permit additional allow rules while all assertions remain green. The supplied implementation does not introduce those grants, but the regression contract is incomplete.
  **Correction:** compare the complete Kiro `allowedTools` and parsed OpenCode permission structure with the recorded baseline. Add mutation tests showing that an additional wildcard or writer-specific approval fails. Retain Claude’s prohibition on a `permissions` block.

- 🟡 **`packages/studyloop/tests/test_docs_harness_tier_contract.py:228–231`; `agents/codex/AGENTS.md:15` — reference presence is being treated as protocol projection.**
  The definitions add links; the test establishes only that the filename appears. This does not establish the receipt’s stronger assertion that the protocol is “projected byte-identically into every definition,” nor that an installed mentor can resolve it. Links are a valid implementation **if distribution and resolution work**; inlining is not inherently required.
  **Correction:** describe the actual reference-based mechanism in a GREEN addendum to the receipt. Add an installation/projection test, such as `test_recording_protocol_resolves_for_each_installed_harness`, which exercises all six adapters and compares the resolved file’s bytes with the canonical protocol. **UNVERIFIED:** actual installed-path resolution.

- 🟡 **`packages/studyloop/tests/test_writer_isolation.py:110–119` — “each writer’s row landed” exceeds the assertions.**
  A shared database file and successful-looking replies do not prove that both `record_teachback` and `log_struggle` persisted their intended rows. Likewise, a session-topics file does not prove the expected concept was recorded.
  **Correction:** query the sandbox database for exactly the expected teach-back and parked-topic records, and assert the session file contains the expected topic/status. Retain the decoy-home check. This remains an isolation **guard**, not retroactively a RED.

- 🟡 **`packages/studyloop/src/studyloop/mcp/tools.py:917–921`; `agents/shared/recording-protocol.md:54–56` — failure reporting needs an explicit unsuccessful-write path.**
  The writer’s verified `False` contract includes `sqlite3.IntegrityError`, so “the sessions database is unavailable” is not always a truthful diagnosis. The protocol also gives only a success acknowledgement, with no rule for denied or failed calls.
  **Correction:** use a generic “teach-back not recorded” error unless the underlying cause is distinguishable. In the protocol, require “Recorded” only after a successful result; denied/error results must say nothing was recorded. Do not automatically replay an ambiguously completed event write. Add a failure-path test and denial/error scenarios to S1-SIM.

## Required judgments

### Trigger coverage and consent

**Complete for the four specified writers, not yet behaviorally proven.**

- Teach-back scores require explicit agreement; the low-energy exception is preserved.
- Topic status requires confirmation.
- Plan-learning wording requires agreement.
- Struggle logging uses a learner-stated difficulty, not permission inferred from harness approval.

The struggle YAML `when` is weaker than its prose: “without a breakthrough” could describe the mentor’s inference. Align it with the prose: **the learner has stated continued difficulty across two rounds on the same point**. Require `when` in `TestRecordingProtocol.REQUIRED_KEYS` and test the intended consent values, not merely column existence.

Learner consent and harness tool approval are separate signals. A pre-approved Kiro `log_topic` call still requires confirmed status; approving an MCP invocation does not itself establish agreement with proposed scores.

### Decision 2

**Honoured in the supplied diff.** All six definitions name `W_auto`, with Grok using Codex’s canonical definition. Claude’s frontmatter makes the writers reachable without adding permissions. Kiro and OpenCode approval configuration is unchanged. No trigger selects `W_srs`.

The instruction “one prompt per call, on every harness” for `W_srs` cannot itself enforce external harness policy. Read it as intended behavior, not a demonstrated approval guarantee.

### N1

**Accept the correction for this patch.**

Passing a study-session ID as a native `sessions` owner is wrong. Scope-owned rows, matching the CLI, are a defensible resolution; returning `study_session_id` provides reply context, **not durable session provenance**.

**UNVERIFIED:** whether an observation’s `source_session_id` accepts study-session IDs. Its name is not evidence of compatibility. Do not move the same incompatible ID there speculatively. A future durable association needs a verified observation API/schema contract or an explicit supported study-session relationship, plus scope tests.

The supplied test documents the changed expectation. **UNVERIFIED:** the GREEN commit’s historical annotation, beyond the coordinator’s stated commit account.

### RED/GREEN claims

The positive persistence and explicit rejection tests are meaningful, not vacuous. The N1 expectation change is justified rather than a concealed relaxation. Inventory changes correctly retain exact counts.

The weak guards identified above over-claim coverage. **UNVERIFIED:** committed failing execution of every stated RED; no such execution was performed here.

No-trigger behavior is not exercised by the supplied additions. A test that merely refrains from calling a writer would be vacuous; this needs a mentor/harness execution.

## S1-SIM completion criteria

Before making the proposed plumbing claim, retain per-harness evidence for:

1. **Installed configuration:** canonical protocol resolves, all four writers are discoverable, and approval configuration matches the frozen baseline.
2. **Positive triggers:** a scripted learner causes each writer to persist the expected record—without manually selecting the writer on the mentor’s behalf.
3. **Negative triggers:** unagreed scores, a low-energy blank, unconfirmed status, declined plan text, and unrelated conversation produce no corresponding writes.
4. **Failure and replay:** denial/error causes no success acknowledgement; two deliberately submitted teach-back events produce two rows.
5. **Tomorrow’s read:** restart the session/server and show the teach-back is visible to the learning reader and reaches the recommendation’s input. The top recommendation need not necessarily change.
6. **Receipt:** list harness versions, approvals, tool calls, storage evidence and explicit pass/fail/unrun outcomes. Name only passed harnesses as “pipe open”; static definition checks do not prove six live pipes.

Keep S1-SIM owner-gated. Keep the first-real-session noticing episode scheduled after merge and observational, not an added merge gate.

## Verdict

**ACCEPT-WITH-CORRECTIONS** — the writer path and N1 resolution are sound on the supplied evidence; validation-boundary coverage, regression guarantees and evidence claims need tightening.
