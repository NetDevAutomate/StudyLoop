# Lane T merge review — gpt-5.6-sol

Unavailable MCP server: `@mochi:mochi` (declared but not configured); it was not needed for this review.

## 1. Red first

1. Renderer/schema/outcome behaviours are covered by `test_module_delivery.py` (31 passing): PTY/ACP/plain/one-line framing, 8 KiB post-framing bound, UTF-8-safe tail cutting, stdout-before-stderr truncation, header bounds, control-byte stripping, six outcomes and active-session lookup. Reds: `unit-module-delivery.red.txt` (seven assertion reds) and `unit-wave1-stub.red.txt` (28 `NotImplementedError` reds, explicitly allowed for the red-only stub).
2. PTY delivery, closed-write reporting and mode-2004-off fallback are covered by `test_pty`, `test_pty_closed_transport_is_reported` and `test_pty_mode_2004_off_falls_back_to_one_line`; reds: `integration-pty.red.txt`, `integration-pty-closed-transport.red.txt`, `integration-pty-mode-2004-off.red.txt`. Split-sequence DEC-2004 state is covered by `test_dec2004_scanner_sees_a_sequence_split_across_reads`; its behavioural red is the mode-off transcript.
3. ACP delivery/FIFO/timeout are covered by `test_acp`, `test_acp_no_overlap_with_learner_turn` and `test_acp_hung_turn_times_out_once_and_does_not_overlap`; reds: `integration-acp.red.txt`, `integration-acp-no-overlap.red.txt`, `integration-acp-hung-turn.red.txt`.
4. Gaps are findings 1–4: printable delimiter injection is untested; cancel-confirmation expiry is untested; PTY learner `send_input` full-write/stall behaviour has probes but no red-first automated test; the cross-caller lock transcript was produced after implementation by disabling the lock, not before the change. Current verification: 31 unit and 7 integration tests pass.

The renderer never slices framed bytes: `_utf8_tail` drops only an incomplete leading UTF-8 fragment, then complete framing sequences are added, so the 8192-byte cap does not split a multibyte character or escape sequence. Raw C0/C1/ESC controls are stripped, but printable envelope delimiters are not.

## 2. Ownership

Owned/shared (22): `docs/adr/0012-practice-check-delivery.md`, `docs/adr/README.md`; `evidence/T/{integration-acp-hung-turn.red.txt,integration-acp-no-overlap.red.txt,integration-acp.red.txt,integration-all.green.txt,integration-all.red.txt,integration-pty-closed-transport.red.txt,integration-pty-cross-caller-lock.red.txt,integration-pty-mode-2004-off.red.txt,integration-pty.red.txt,preflight-T4-merged.txt,preflight-T4.txt,pty-looped-write.txt,pty-single-write.txt,pty_probe.py,pty_probe2.py,unit-module-delivery.red.txt,unit-wave1-stub.red.txt}`; `session/module_delivery.py`; `tests/integration/test_module_delivery_transports.py`; `tests/test_module_delivery.py`.

M0/brief-permitted (4): `session/transport.py`, `session/transports/pty.py`, `session/transports/acp.py` (M0 §2 Q1/§4); change-local `specs/session-transports/spec.md` (T2 brief’s explicit spec-amendment permission). Outside (1): `tests/fixtures/lane_ownership.yaml`; M0 justifies the three source ownership entries semantically, but does not authorize lane T to edit S’s fixture (finding 5).

## 3. Scope

No registry-shaped work, runtime dependency, allowlist pragma, hook/baseline/pre-commit edit, `SKIP=`, or `--no-verify` appears in the diff. Production work otherwise implements proposal §5.7 and M0. Findings 1–2 are contract/security defects, not requested scope; finding 5 is the only unjustified file touch.

## 4. Next lane W

1. `studyloop.session.module_delivery.PracticeCheckEnvelope` / `validate_envelope`: W’s route must pass exactly the eleven documented fields; `extra="forbid"`, slug/digest bounds and tail sanitisation make fixture shape and 4xx handling brittle.
2. `studyloop.session.module_delivery.deliver_to_active_session`: W must await it and preserve all six `DeliveryOutcome.status` values in the HTTP/learner surface; treating `timed_out` as delivered or retryable would violate M0.

## Findings

1. `packages/studyloop/src/studyloop/session/module_delivery.py:194` -- stdout/stderr is inserted verbatim after control stripping, so a hostile module can print the end sentinel or section/header lines and forge mentor-visible structure -- encode tails as JSON strings or escape/prefix every data line and add an adversarial test.
2. `packages/studyloop/src/studyloop/session/transports/acp.py:478` -- cancel-and-hold uses two sequential 10-second waits, then emits synthetic `turn_end` and releases FIFO even when the original prompt never confirms cancellation, allowing queued learner prompts to overlap a still-running turn -- use one cancellation deadline and close the transport/fail queued prompts if confirmation never arrives; test the no-response path red-first.
3. `packages/studyloop/src/studyloop/session/transports/pty.py:401` -- the new learner-input full-write and 30-second stall/error behaviour has no automated red-first test; spike probes exercise direct mechanics, not `send_input` assertions -- add a slow-reader >1 KiB learner-input test and a bounded-stall `TransportError` test with red transcripts.
4. `openspec/changes/module-contract-v1/evidence/T/integration-pty-cross-caller-lock.red.txt:2` -- the lock test was made red at the already-implemented `47c0b13b` by an uncommitted lock-neutralising patch, so it is mutation evidence, not the required pre-change red -- reproduce the unchanged test against the pre-lock parent and preserve that transcript.
5. `packages/studyloop/tests/fixtures/lane_ownership.yaml:238` -- lane T edited an S-owned fixture absent from T’s owned globs; M0 authorizes the three transport files but not this ownership-map edit -- move this hunk to S/coordinator ownership or record an explicit ownership exception before merge.

Verdict: merge after fixes
Findings: 5 raised
