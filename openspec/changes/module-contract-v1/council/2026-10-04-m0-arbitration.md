# Arbitration — council M0, `practice_check` delivery (2026-10-04)

**Coordinator:** Kiro (default). **Brief:** `2026-10-04-m0-brief.md`. **Subject:** ADR-0012 (lane T,
`docs/adr/0012-practice-check-delivery.md` on `feat/module-mentor-delivery`). **Seats:**
gpt-5.6-sol (921 w, 26 cites, 3 UNVERIFIED, 4 findings) · deepseek-3.2 (824 w, 10 cites, 0
findings) · qwen3-coder-next (1,169 w, 13 cites, 1 finding) · glm-5 (850 w, 4 cites, 2 UNVERIFIED,
3 findings). Every code claim relied on below was re-verified by the coordinator against the tree
at `9083a518` and the T worktree at `c1b033eb`.

## 1. Seat reliability

| Seat | What held | What did not | Weight |
| --- | --- | --- | --- |
| gpt-5.6-sol | All four findings verified: `pty.py:351-361` swallows `EIO`/`EBADF`/`EPIPE` and returns `None` (closed-write unobservable); `acp.py:267-288` creates a background task and exposes no handle (no awaitable prompt); `app.py:218-231, 275-279` installs Basic Auth only when a password is set — the default local web has **no auth**; T's `test_pty` (integration 212-270) asserts framing and truncation, never a cross-caller lock. Also verified: `orchestrator.py:244-279` writes `web_port` to the session state; `session_state.py:93-118` creates the dir `0o700` and files `0o600`. | — | full |
| deepseek-3.2 | F1–F5 re-checked against the lines it cites | approved the ADR's `timed_out` and `transport_closed` as implementable, which the code contradicts (above) | agreement weight only |
| qwen3-coder-next | 13 cites, on budget; `pty.py:273` `O_NONBLOCK` verified; its one finding (short write = partial count under `O_NONBLOCK`, not a `TTYHOG` drop) is correct and precise | approved the same two contradicted claims | agreement weight only |
| glm-5 | its verdicts align with the majority | 4 cites; finding 1 is a phrasing quibble (an implicit return *is* `None`); findings 2–3 are honest UNVERIFIEDs that the coordinator has now verified (`xterm-6.0.0.js` tracks `bracketedPasteMode` for DEC mode 2004: 7 occurrences) | agreement weight only |

Pattern, third round running: the seat that reads the code finds what the others accept. GPT
predicted exactly which two claims the other three would "accept too readily", and they did.

## 2. Rulings

**Q1 — the two transport changes: APPROVED, 4/4.** T3 changes `PTYTransport.send_input` to write
until the whole buffer is consumed (`loop.add_writer` on the `O_NONBLOCK` master, pty.py:273) under
a per-transport `asyncio.Lock`; T4 adds a per-transport `asyncio.Lock` around
`_rpc("session/prompt")` in `_prompt_turn`. Protocol signatures unchanged (S6 satisfied: M0 says the
change is required). Two amendments from GPT, both adopted:
- A **cross-caller lock test** is missing: the PTY integration suite must prove a learner keystroke
  (`_ws.py:201` path) cannot land inside the block — concurrent `send_input` calls, assert the
  envelope bytes are contiguous in the fake child's input.
- `send_input` on PTY must make a closed write **observable**: return (or raise into) a typed
  outcome so `transport_closed` is a real state, not a pre-flight `is_running()` guess
  (`pty.py:351-361` today returns `None` on `EIO`/`EBADF`/`EPIPE`). The Protocol stays
  `send_input(data) -> None`; the delivery module uses a new transport-level method
  (`deliver_block(data) -> DeliveryWrite`) that both transports implement and ordinary learner input
  never calls. Qwen's precision fix to the ADR's reasoning (partial count, not `TTYHOG`) is adopted.

**Q2 — cross-process delivery: option (b), 4/4, with GPT's security amendments.** The brief's
"existing session auth" was **wrong** (coordinator error, found by GPT): there is none by default.
Ruling for the route (owned by W per design.md §2; T2 defines the envelope and the server-side
validator it calls):
1. Loopback only — bind check on the request's client address, not a header.
2. **Per-session capability**: when the web process claims a session it mints a random token and
   writes it to the session state file (`session_state.py` `_write_file_secure`, `0o600`, dir
   `0o700`), beside `web_port` which `orchestrator.py:244-279` already records; `studyloop drill`
   reads both from that file (same user, same machine) and presents the token in a header. No
   token → 401; wrong session → 403.
3. Exact binding: the request names `session_id` and `attempt_id`; the server checks the session
   is the active one and the attempt is open and unreported; **replay dedup** on
   `(attempt_id, phase)`; rate limit (one envelope per phase per attempt; burst 5/min per session).
4. The server **re-renders and re-bounds**: the CLI sends typed fields (identity, phase, exit
   class, code, duration, stdout tail, stderr tail), never rendered text; the server strips control
   bytes, renders the envelope, enforces 8 KiB, chooses the framing by transport class.
5. The learner still sees the outcome in the CLI (`Mentor told.` / `Mentor not told: <reason>`),
   where the hop's HTTP failure maps to `no_active_session` (no server / no state file) or `error`.
DeepSeek's note that (a) is arguable is recorded and rejected for the reason all four gave: (a)
ships a contract item nothing in the MVP can exercise.

**Q3 — bracketed paste: track DEC 2004 in the transport; fallback is ONE printable line.** 3/4 for
tracking; GPT's amendment adopted over the ADR's and the coordinator's "bare text + CR": with mode
2004 off, raw multi-line text plus CR submits the lines separately and splinters the envelope (S4).
Fallback = one line (newlines in output escaped as `\n`, sentinels kept) + CR, or
`DeliveryOutcome(unsupported_framing)` if the agent's editor rejects it. The PTY `_reader_loop`
(pty.py ≈441-449) sees every child chunk, so a split-sequence-aware scanner for `ESC[?2004h/l` is
cheap. The per-harness probe stays an **owner task** (needs the real binaries), recorded in
tasks.md; it confirms, it does not gate T3. F5 is now verified: the vendored
`xterm-6.0.0.js` tracks `bracketedPasteMode` for mode 2004.

**Q4 — auto-submit: APPROVED, 4/4.** Prefix a separator newline, submit once, document the
half-draft hazard in the ADR's Consequences and in the Labs UI copy later. No editor-state
heuristic exists to implement the alternative (transport.py:145-151, `_ws.py:192-201`).

**Q5 — ACP timeout: 120 s, report, never retry, 4/4 — with GPT's implementation amendment.** The
ADR's claim that delivery can await the prompt is false today (acp.py:267-316: no handle;
`turn_end` only on the single-consumer stream). T4 adds an ACP-only awaitable path inside the
transport (the `deliver_block` method above returns when the prompt's response arrives or the bound
expires); `send_input` for learner text stays fire-and-forget. Timeout semantics: outcome
**unknown**, the ACP turn is cancelled, and the prompt lock is held until cancellation is
confirmed so a later prompt cannot overlap a still-running timed-out one. New integration test:
hung fake ACP → one envelope, `timed_out` visible, no retry, no subsequent overlap.

**Q6 — the spec delta: AMEND (3/4 amend; GLM's "keep" rejected).** Replace the three parenthetical
reasons in `specs/session-transports/spec.md` with the reachable outcomes
(`delivered`, `no_active_session`, `transport_closed`, `timed_out`, `unsupported_framing`, `error`)
and two **invariants** stated as requirements, not failures: oversize input is truncated to a valid
bounded envelope (header never dropped); concurrent ACP deliveries queue FIFO. `size_exceeded` and
`serialisation_refused` are removed. GPT's caveat stands as a T2 task: bound `module id` and
`attempt id` in the header (deck/task ids are already ≤ 63 chars via `SlugId`).

**Q7 — what the ADR gets wrong (adopted corrections, T2 amends the ADR):** (1) closed-write
observability (pty.py:351-361); (2) no awaitable ACP prompt handle (acp.py:267-316); (3) "existing
session auth" → per-session capability; (4) the PTY red proves framing, not the lock; (5) short
write = partial count under `O_NONBLOCK`, not `TTYHOG`. ADR status stays **Proposed** until T4
lands; the Decision section records M0's rulings with this file as the source.

## 3. Catch-rate

Raised 8 (gpt 4, qwen 1, glm 3) · verified 5 (gpt 4, qwen 1) · acted 5 · discounted 3 (glm 1:
phrasing; glm 2–3: UNVERIFIED by the seat, now verified true by the coordinator — so not
findings). Coordinator's own call corrected on: the hop's authentication (wrong), the Q3 fallback
(incomplete). Confirmed: Q1, Q2 shape, Q4, Q5 bound.

## 4. What T2–T4 and W inherit (binding)

- T2: `session/module_delivery.py` — typed `PracticeCheckEnvelope` **fields** (not text) as the
  cross-process payload; `render_envelope(result, *, framing)`; server-side validator (control
  strip, 8 KiB, header bounds incl. module/attempt ids); `DeliveryOutcome` with the six states;
  ADR amendments above; spec amendment per Q6.
- T3: PTY `deliver_block` — full write under lock, closed-write observable, DEC 2004 tracking
  with the one-line fallback; the cross-caller lock integration test; mode-off fallback test.
- T4: ACP `deliver_block` — prompt lock, awaitable completion, 120 s timeout with cancel-and-hold,
  hung-fake test. Then T-review (one seat) before merge.
- W (wave 2): the loopback route per Q2 items 1–5, calling T2's validator; the capability token
  minted at session claim and written to the session state file; the CLI side of the hop belongs
  to R6 (`cli/_drill.py`) and reads the state file.
- Owner task (tasks.md): probe each PTY harness (claude, codex, kiro-cli, pi) for `ESC[?2004h` at
  start-up; result recorded, not gating.
