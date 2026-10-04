# Lane T — wave 1: delivery module, PTY and ACP delivery (T2–T4), under the M0 rulings

Read `00-common.md` first (its rules still bind), then `T-mentor-delivery.md` (globs, forbidden
list, your T1), then **`council/2026-10-04-m0-arbitration.md` §2 and §4 in full — they are the
decision**, then this file. Spec you implement: `specs/session-transports/spec.md` (amended
`1c787650` — every scenario maps to a test). Your ADR: `docs/adr/0012-practice-check-delivery.md`.

| | |
| --- | --- |
| Branch · worktree | `feat/module-mentor-delivery` · `/Users/ataylor/code/personal/tools/studyloop-wt/module-mentor-delivery` |
| Start | `git merge --no-edit main` first (main is at `4704fd3d`+; S merged; specs amended). Stop and report on any conflict. |
| Inherits | your T1: ADR-0012, four integration reds, seven unit reds + doubles, PTY probes |
| Transports | M0 ruled the change **required** (design.md §2 condition met): you may edit `session/transports/pty.py`, `session/transports/acp.py`, `session/transport.py` for exactly the changes below. `AgentSessionTransport.send_input(data) -> None` keeps its signature. |
| Done when | T2–T4 ticked, every T1 red green, the new scenarios green red-first, ADR amended, gate G green end to end (allowed red: virgin-HOME tmux), report filed |
| Merge | after T-review (one seat); the coordinator merges |

## What M0 changed in your ADR (amend the Decision section; status stays Proposed until T4 lands)

1. **Closed write must be observable.** `pty.py:351-361` swallows `EIO`/`EBADF`/`EPIPE`. Add a
   transport-level `deliver_block(data: bytes) -> DeliveryWrite` (a small typed result: written /
   closed / unsupported_framing / error) on both transports; ordinary learner input keeps using
   `send_input`. `transport_closed` comes from the write, not from a pre-flight `is_running()`.
2. **ACP has no awaitable prompt today** (`acp.py:267-288`). `deliver_block` on ACP acquires the
   per-transport prompt lock, sends `session/prompt`, and **awaits** the response up to 120 s; on
   timeout the outcome is `timed_out` (unknown), the turn is cancelled, and the lock is held until
   cancellation is confirmed. Never retry. `send_input` stays fire-and-forget behind the same lock.
3. **Fallback when DEC 2004 is off is ONE printable line**, not bare multi-line text: newlines in
   output escaped as `\n`, sentinels kept, one trailing CR — or `unsupported_framing`. Track
   `ESC[?2004h` / `ESC[?2004l` in `_reader_loop` with a split-sequence-aware scanner.
4. **The cross-process payload is typed fields, rendered server-side.** `PracticeCheckEnvelope` is
   the field schema (identity, attempt id, phase, exit class, code, duration, stdout tail, stderr
   tail, triggered_by); `render_envelope(envelope, *, framing)` and `validate_envelope(fields)`
   (control strip, 8 KiB, header bounds including module id ≤ 63 and attempt id ≤ 64 chars) live in
   `session/module_delivery.py` and are what lane W's route calls. Fix the ADR's "existing session
   auth" to the per-session capability token (minted at session claim, written beside `web_port`
   in the session state file — W's wave-2 work; you define the field names and the validator).
5. **Reasoning fix:** the short write is a partial count under `O_NONBLOCK` (pty.py:273), not a
   `TTYHOG` drop. The missing **cross-caller lock test** is yours (below).

## Tasks (one commit each minimum; red-first for every new scenario; `Base:` in the first body)

- **T2** `session/module_delivery.py`: `PracticeCheckEnvelope` (frozen dataclass or Pydantic,
  `extra: forbid`), `validate_envelope`, `render_envelope(…, framing="pty"|"acp"|"plain")`,
  `DeliveryOutcome(status ∈ {delivered, no_active_session, transport_closed, timed_out,
  unsupported_framing, error}, reason)`, `deliver(session, envelope) -> DeliveryOutcome` using
  `active.current()` and the transport's `deliver_block`. Unit reds green; new unit tests: header
  never dropped under truncation; module/attempt id bounds; control bytes stripped; one renderer,
  three framings.
- **T3** PTY: `deliver_block` writes the whole buffer via `loop.add_writer` under an
  `asyncio.Lock` shared with `send_input`; closed-write observable; DEC 2004 tracking; one-line
  fallback. Integration: `test_pty` green; **new** `test_pty_concurrent_learner_input_never_lands_inside_block`
  (red first) and `test_pty_mode_2004_off_falls_back_to_one_line` (red first);
  `test_pty_closed_transport_is_reported` green through the write path.
- **T4** ACP: prompt lock in `_prompt_turn`; `deliver_block` awaitable with the 120 s bound,
  cancel-and-hold; `test_acp`, `test_acp_no_overlap_with_learner_turn` green; **new**
  `test_acp_hung_turn_times_out_once_and_does_not_overlap` (red first; hung fake agent).
- **ADR** amended per the five points; `docs/adr/README.md` row text unchanged (status Proposed).
- Spec wording: if a scenario in `specs/session-transports/spec.md` cannot be met as written,
  amend the scenario in the same commit as the test that proves the replacement, and say so.

## Cross-lane facts

- Lane W (wave 2) builds the route to your `validate_envelope` + `deliver`; lane R6 posts typed
  fields from the CLI and reads the state file. You own the field names: document them in
  `module_delivery.py`'s module docstring and in your report.
- Never edit `web/`, `cli/`, `modules/`, `session/active.py`. Never run `just e2e`; while a red
  remains run gate G recipe-by-recipe, then `just preflight` end to end.

## Report (common §6 plus)

The final `PracticeCheckEnvelope` field list with bounds; one rendered PTY envelope and its ACP
twin (first 12 lines each); the integration summary line with all seven tests green; the ADR diff
stat; gate lines; gaps.
