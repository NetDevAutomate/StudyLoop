# ADR-0012: Delivering a `practice_check` result to the live mentor

**Status:** Proposed (M0 ruled 2026-10-04; T2–T4 implemented on `feat/module-mentor-delivery`;
Accepted when T-review passes and the lane merges) · **Date:** 2026-10-04 · **Amended:**
2026-10-04 (council M0 rulings; T-review findings 1–4 the same evening) · **Deciders:** council M0 (four seats) and Andy Taylor (owner) ·
**Change:** `openspec/changes/module-contract-v1` (proposal §5.7, design §7 M0 / §8 T1, spec delta
`specs/session-transports/spec.md`, decision of record
`council/2026-10-04-m0-arbitration.md` §2 and §4)

The Context and the four Decision sections below are the T1 spike as the council read it; the
block **"What council M0 ruled"** is the decision of record and every later "[M0 …]" note
corrects the spike's text where the council found it wrong. Line numbers in the Context are
from `60bbb504`; the implementing commits moved some of them.

## Context

Proposal §5.7 makes mentor delivery a contract item: when a drill's `check` phase completes,
core delivers a typed, size-bounded `practice_check` envelope — drill identity, phase, exit
class, redacted and truncated output — into the claimed session's transport, PTY or ACP,
**labelled as data**; delivery failure is reported to the learner, never silent; one
integration test per transport proves it (DoD item 5). At the time of the proposal nobody had
read a channel from a runner result to the mentor process. This ADR is that reading (T1, the
time-boxed spike). It answers exactly four questions and implements nothing.

Every line number below was read on `main` at `60bbb504` (worktree base), in
`packages/studyloop/src/studyloop/`.

### What the code offers today (verified)

- **The handle.** `session/active.py:50-54` — `ActiveSession(study_session_id, transport,
  config)`; `transport` is an `AgentSessionTransport`. `active.py:110-117` — `current()` is a
  lock-free pointer read whose docstring tells callers to "tolerate the session ending between
  `current()` and the action". `active.py:3-4` — the singleton holds the live **web** PTY/ACP
  session "IN THIS PROCESS ONLY"; `active.py:13-14` — it "has no idea a CLI-owned session
  (`studyloop study`, which never touches this module) exists at all".
- **The one write method.** `session/transport.py:145-150` — `send_input(data: bytes)`: "No
  framing or escape handling — bytes go through verbatim." It is the same method the web
  terminal uses for learner keystrokes (`web/routes/session/_ws.py:198-201`: an `input` frame
  becomes `transport.send_input(data.encode("utf-8"))`), with no lock between callers.
- **PTY.** `session/transports/pty.py:351-360` — `send_input` does one `os.write(master_fd,
  data)` (line 356) and **discards the return value**; `EIO`/`EBADF`/`EPIPE` return silently
  ("Child is gone. The SIGCHLD path will emit Stopped", 357-360); `state is None` returns
  silently (352-354). The master fd is `O_NONBLOCK` (pty.py:273). `is_running()` exists
  (pty.py:318-349, `os.kill(pid, 0)` probe) and is what the slot reaper duck-types
  (`web/routes/session/_grace.py:170-179`, `_LivenessProbe`).
- **ACP.** `session/transports/acp.py:267-288` — `send_input` decodes UTF-8 (a decode error
  becomes a `TransportError` on the event queue, 273-279, and the call returns) and creates a
  **background task** per call (`asyncio.create_task(self._prompt_turn(text))`, 283-288),
  tracked only in the set `self._prompt_tasks` (acp.py:158, 287-288). `_prompt_turn`
  (acp.py:290-316) sends `session/prompt` through `_rpc` (acp.py:447-477 — write a frame, await
  its id's future; **no per-method serialisation**) and, on completion, enqueues
  `AgentMessage(kind="turn_end", payload={"reason": stopReason})` (315-316); an `_RpcError`
  becomes a `TransportError` on the queue (308-313). The queue is a single-consumer drain
  (`_ws.py:105`, `_grace.acquire_consumer`; "events() is a drain, one event per consumer"),
  owned by the websocket pump — a second reader would steal the learner's events. `ACPTransport`
  has **no** `is_running()` (grep: none in acp.py), so `_grace`'s probe assumes it alive.
  `_STDERR_TAIL_BYTES = 4096` (acp.py:67) is the repo's existing "keep a bounded tail"
  convention.
- **Reaching the transport from the web layer.** `web/routes/session/_transport.py:42-56`
  (`_resolve_transport`: env `STUDYLOOP_TRANSPORT` may force `pty`; `acp` is body-only) and
  `59-103` / `106-159` (the PTY and ACP factories; the PTY child is `/bin/sh -c <launch_cmd>`;
  `STUDYLOOP_TEST_AGENT_CMD` / `STUDYLOOP_TEST_ACP_CMD` are the test hatches). The CLI session
  (`studyloop study`) is a tmux pane reached by `multiplexer.send_keys` (`multiplexer.py:74,
  173-176` → `tmux.py:182-190`, `tmux send-keys`) — it is not an `AgentSessionTransport`.

### What the spike measured (macOS 27.0, Python 3.12, `pty.fork()` child in raw mode)

Probe scripts: `openspec/changes/module-contract-v1/evidence/T/pty_probe*.py`; transcripts
beside them.

| Payload (one `os.write` on the `O_NONBLOCK` master) | Returned | Child received |
| --- | --- | --- |
| 512 B | 512 | 512 B, intact |
| 1024 B | **1022** | nothing usable (sentinel never arrived) |
| 2 KiB … 64 KiB | **1022** | nothing usable |
| 64 KiB written in a loop that waits for master writability | 65536 in 65 rounds | 65536 B, intact |

In canonical (cooked) mode a 1024-byte line arrives; a 2048-byte line is **dropped whole**
while the write still reports success (the BSD `TTYHOG` canonical limit). Cooked mode is only
the `cat`-style test hatch; every real harness agent runs its TUI in raw mode.

Consequence: **today `PTYTransport.send_input` silently truncates any write longer than the
tty input queue (~1 KiB on macOS)** — for a `practice_check` envelope and equally for a learner
pasting a long block into the web terminal. Nothing above the transport can detect it.

[M0 correction 5, qwen3-coder-next:] the raw-mode short write is the **partial count** an
`O_NONBLOCK` write returns when the tty input queue is full (pty.py:273 sets the flag; the next
write raises `EAGAIN` until the child reads) — not a `TTYHOG` drop. `TTYHOG` is the
canonical-mode whole-line limit in the cooked rows above and nothing else. The fix is therefore
a write loop that waits for writability (`loop.add_writer`), which is what T3 implemented
(`PTYTransport._write_all`), not a smaller envelope.

Against design §8: its line references hold (`active.py:50-54`, `transport.py:145`,
`pty.py:351-360`; `acp.py:267-288` is `send_input`, `_prompt_turn` follows at 290-316). Two
things it did not say: the PTY write is short, not whole; and the transport it names exists
only in the web server's process, for web-started sessions — the CLI `studyloop study`
session has none.

## Decision

### What council M0 ruled (2026-10-04) — the decision of record

Source: `openspec/changes/module-contract-v1/council/2026-10-04-m0-arbitration.md` §2 (rulings)
and §4 (what T2–T4 and W inherit). Seats: gpt-5.6-sol, deepseek-3.2, qwen3-coder-next, glm-5;
every code claim re-verified by the coordinator. Implemented in T2–T4; the symbols named here
are where each ruling lives.

1. **Both transport changes approved (Q1, 4/4), with two amendments.** PTY writes until the
   whole buffer is consumed, waiting on `loop.add_writer` between rounds, under one
   per-transport lock shared by every writer (`transports/pty.py`: `_write_all`,
   `_wait_writable`, `_write_lock`). **Amendment a — the closed write is observable:** a new
   transport-level method `deliver_block(data) -> DeliveryWrite` (status `written` / `closed` /
   `timed_out` / `unsupported_framing` / `error`; `session/transport.py`) returns `closed` from
   `EIO`/`EBADF`/`EPIPE` on the master fd, so `transport_closed` is a fact from the write, not a
   pre-flight `is_running()` guess. `AgentSessionTransport.send_input(data) -> None` is
   unchanged; learner input never calls `deliver_block`; the delivery module duck-types the
   `BlockDeliverer` protocol the way `_grace._LivenessProbe` duck-types `is_running()`.
   **Amendment b — a cross-caller lock test:** `test_pty_concurrent_learner_input_never_lands_inside_block`
   (red first with the lock neutralised: `evidence/T/integration-pty-cross-caller-lock.red.txt`).
2. **Cross-process delivery = option (b): a loopback route in the web server process (Q2,
   4/4), with GPT's security amendments.** The M0 brief's "existing session auth" was wrong —
   the default local web has no auth (`web/app.py:218-231, 275-279` install Basic Auth only
   when a password is set). Ruling: loopback-only bind check; a **per-session capability
   token** minted when the web process claims the session and written beside `web_port` in the
   owner-only session state file (`session_state.py` `_write_file_secure`, `0o600`/`0o700`;
   `orchestrator.py:244-279` already records `web_port`); exact binding to `session_id` +
   open `attempt_id`; replay dedup on `(attempt_id, phase)`; rate limit (one envelope per
   phase per attempt, burst 5/min); **the server re-renders and re-bounds from typed fields**
   — the CLI never sends rendered text; the learner still sees `Mentor told.` / `Mentor not
   told: <reason>` in the CLI. T2 owns the field schema and the validator
   (`session/module_delivery.py`: `PracticeCheckEnvelope`, `validate_envelope`); lane W (wave 2)
   owns the route and the token; lane R6 owns the CLI side of the hop.
3. **Bracketed paste: track DEC 2004 in the transport; the fallback is ONE printable line
   (Q3, 3/4 + GPT's amendment).** The PTY reader loop sees every child chunk, so a
   split-sequence-aware scanner for `ESC[?2004h` / `ESC[?2004l` is cheap
   (`transports/pty.py`: `_scan_dec2004`, `bracketed_paste_enabled`, `block_framing`). With
   mode 2004 off, raw multi-line text + CR would submit the lines separately and splinter the
   envelope; the fallback is one line (newlines and tabs in the body escaped as the two
   characters `\n` / `\t`, backslashes as `\\` so the escape is reversible, sentinels kept) +
   one CR, or `unsupported_framing`. The per-harness probe for `ESC[?2004h` stays an owner
   task (needs the real binaries); it confirms, it does not gate.
4. **Auto-submit approved (Q4, 4/4):** one trailing CR; the half-draft hazard is a Consequence
   and Labs UI copy later. No editor-state heuristic exists to implement the alternative.
5. **ACP timeout 120 s, report, never retry (Q5, 4/4), with GPT's implementation amendment.**
   The spike's claim that delivery can await the prompt was false as written (acp.py:267-316:
   `send_input` fires a background task and exposes no handle; `turn_end` is on the
   single-consumer stream). T4 adds the awaitable path **inside the transport**:
   `ACPTransport.deliver_block` sends `session/prompt` and awaits its response up to
   `DELIVERY_TIMEOUT_S = 120.0`; on timeout the outcome is `timed_out` (unknown), the turn is
   cancelled (`session/cancel`), and the prompt serialiser is **held until the agent has
   answered the cancelled prompt**. [T-review finding 2:] if the agent does **not** confirm
   within `_CANCEL_CONFIRM_TIMEOUT_S` (10 s), the transport is **wedged** rather than released:
   every later `send_input` emits `TransportError(_WEDGED_MESSAGE)` and sends nothing, every
   later `deliver_block` reports `closed` (→ `transport_closed`), the one synthetic `turn_end`
   carries `reason="wedged"`, and the way out is a new session — so a later prompt can never
   overlap a turn that may still be running. Learner `send_input` stays fire-and-forget behind the same serialiser.
6. **Spec delta amended (Q6, 3/4).** The three parenthetical failure reasons are replaced by
   the six reachable outcomes `delivered`, `no_active_session`, `transport_closed`, `timed_out`,
   `unsupported_framing`, `error`; `size_exceeded` and `serialisation_refused` are removed; two
   invariants are requirements, not failures — oversize input is truncated to a valid bounded
   envelope (header never dropped), and concurrent ACP deliveries queue FIFO. GPT's caveat is a
   T2 task: bound `module_id` (≤ 63) and `attempt_id` (≤ 64) in the header.
7. **What the spike got wrong (adopted; corrected inline below):** (1) closed-write
   observability — pty.py:351-361 swallowed the errors; (2) no awaitable ACP prompt handle;
   (3) "existing session auth" → per-session capability token; (4) the wave-0 PTY red proved
   framing, not the lock; (5) the short write is a partial count under `O_NONBLOCK`, not
   `TTYHOG`. Status stays **Proposed** until T4 lands and T-review passes.

**What T2–T4 built against these rulings (one line each):**

- `session/transport.py`: `BlockFraming`, `DeliveryWrite`, `BlockDeliverer` (Protocol-neutral).
- `session/module_delivery.py`: `PracticeCheckEnvelope` (frozen Pydantic, `extra: forbid`,
  every header field bounded), `validate_envelope`, `render_envelope(framing=pty|pty-line|acp|plain)`
  — one renderer, the 8 KiB bound applied to the **framed** bytes —, `DeliveryOutcome`,
  `deliver`, `deliver_to_active_session`. The module docstring is the field contract for R6/W.
- `session/transports/pty.py`: write loop + lock, `deliver_block`, DEC 2004 tracking,
  `block_framing`; a 30 s stall bound (`_WRITE_STALL_TIMEOUT_S`) so a child that stops reading
  its terminal cannot pin the lock and every learner keystroke behind it.
- `session/transports/acp.py`: a FIFO **ticket** serialiser (`_TurnQueue`) rather than a bare
  `asyncio.Lock` — `send_input` creates its task and returns before the task reaches
  `acquire()`, so with a plain lock a `deliver_block` made right after it took the lock first
  and the envelope overtook the learner's prompt (the no-overlap test caught it); a ticket fixes
  the place in line at call time, which is what "queue FIFO" means. `deliver_block` awaits,
  times out, cancels and holds (`_cancel_and_hold`).

### Q1 — PTY framing: how does injected text arrive as unmistakable *data*?

**Chosen: one bracketed-paste block carrying a sentinel-delimited, labelled envelope, submitted
once.** The delivery module renders

```
ESC[200~
<<<studyloop:practice_check v1 attempt=<id>>>>
module: <module id>@<digest[:12]>   drill: <deck id>/<task id>   phase: check
exit: <passed|failed|error> (code <n>)   duration: <s>s   triggered_by: learner
truncated: <stdout|stderr|none>
--- stdout (last <n> bytes) ---
<redacted stdout tail>
--- stderr (last <n> bytes) ---
<redacted stderr tail>
<<<end studyloop:practice_check>>>
ESC[201~ CR
```

and writes it through `send_input` as **one** call. The ESC sequences are the terminal's own
paste bracket (DEC mode 2004): a line editor that has enabled bracketed paste treats everything
between them as pasted text — newlines stay newlines, nothing is executed per line — and the
trailing CR submits the block as one prompt. The sentinel lines make the block recognisable in
the mentor's transcript and in the persona's `practice_check` protocol (wave-1 content, owned
by the agents/persona files, not by this lane). The payload contains no raw control bytes: the
renderer strips everything below 0x20 except `\n` and `\t` from module output before framing,
so a module cannot smuggle its own ESC sequences or a Ctrl-C through the envelope.

Framing is chosen by the transport's class — `PTYTransport` gets the bracket and the CR,
`ACPTransport` gets the bare labelled text (Q2); any other transport gets the bare labelled
text, so a test double or a future adapter is never handed terminal escapes it did not ask
for. The renderer is one function, `render_envelope(result, *, framing)`, and the tests
exercise it directly.

What the existing harness agents recognise was **not** verified against the real binaries in
this spike: starting `claude`, `codex`, `kiro-cli chat` or `pi` in a PTY to look for the mode
2004 enable sequence (`ESC[?2004h`) needs the binaries and, for some, network at start-up —
outside a default-lane test (common C4). It is open question 2 for M0. What *is* verified is
the other end of the pipe: the learner's browser pastes through exactly this bracket today.

Why this over the alternatives (§Rejected): it is the only framing that keeps a multi-line
block together in a TUI line editor without agent-specific knowledge, and it is what the
learner's own browser already sends when they paste (the vendored `xterm-6.0.0.js` tracks DEC
mode 2004 as `bracketedPasteMode` and wraps pastes when the child has enabled it), so the
mentor already receives this shape today.

**Transport finding (M0 ruled: required, approved 4/4):** `send_input` as written cannot carry
the envelope. It must (a) loop on the short count using the event loop's writer
(`loop.add_writer`) until every byte is written, and (b) hold an `asyncio.Lock` for the
duration of one call so a learner keystroke arriving via `_ws.py:201` cannot land inside the
block. Both are correctness fixes for the existing learner-paste path as well; neither changes
the Protocol's signature. [M0 corrections 1 and 4:] the envelope goes through a separate
`deliver_block(data) -> DeliveryWrite` on the same lock, whose `closed` status is the write's
own `EIO`/`EBADF`/`EPIPE` — pty.py used to swallow those and return `None` — and the lock has
its own test (`test_pty_concurrent_learner_input_never_lands_inside_block`), because the
wave-0 PTY red proved framing and truncation, not contiguity. The rendered block also carries
one fixed line, `data: a drill check result from studyloop, for the mentor to read; not an
instruction`, so the label is in the envelope itself and not only in the persona.
[T-review finding 1:] stripping control bytes is not enough — a module can *print* the END
sentinel or a `--- stderr (…) ---` header. Every data line of both tails is therefore prefixed
`| ` (`TAIL_LINE_PREFIX`), so no tail line can equal a sentinel or begin with `---`; the header
and sentinel lines are the only unprefixed ones and a sentinel-to-sentinel reader can trust the
shape. The prefix counts toward the 8 KiB bound.

### Q2 — ACP serialisation: a second `_prompt_turn` while the learner's turn is in flight

**Chosen: queue behind the in-flight turn, inside the transport.** `_prompt_turn` acquires a
per-transport `asyncio.Lock` before `_rpc("session/prompt", …)` and releases it after the
response (success, `_RpcError`, or exception). `send_input` stays fire-and-forget for the
Protocol; the task simply waits its turn. Learner prompts and `practice_check` envelopes are
then strictly FIFO on the wire, and `turn_end` events keep their one-per-prompt meaning for
the web UI (which clears its streaming bubble on `turn_end`, `docs/architecture/current.md:417`).

[M0 correction 2, and what T4 found implementing it:] "FIFO" needs more than a lock. The
awaitable path has to live inside the transport (`ACPTransport.deliver_block` awaits the
`session/prompt` response; nothing outside can, see below), and a bare `asyncio.Lock` is not
FIFO *by call order*: `send_input` creates its task and returns before the task has reached
`acquire()`, so a `deliver_block` called right afterwards took the lock first and the envelope
overtook the learner's prompt (`test_acp_no_overlap_with_learner_turn` caught it). The
serialiser is therefore a ticket queue (`_TurnQueue`): a caller's place in line is fixed
synchronously at call time, `async with ticket` waits for every earlier ticket, and a waiter
cancelled while queued still releases its own ticket so the chain never stalls.

What `acp.py` exposes today for "turn in progress": only the private set `_prompt_tasks`
(acp.py:158) — non-empty while any prompt task is alive — and the `turn_end` `AgentMessage`
on the single-consumer queue. Neither is reachable through `AgentSessionTransport`, and the
queue cannot be read by a second consumer without stealing the learner's events, so no
caller outside the transport can wait for turn end. Serialisation therefore has to live in
the transport: a one-lock change in `_prompt_turn`, again Protocol-neutral.

The envelope text on ACP is the same rendering as Q1 **without** the ESC bracket and CR: a
`session/prompt` is already one turn, so the sentinel lines alone label it. One renderer, two
framings, is the whole transport-specific surface.

### Q3 — Envelope size bound

**Chosen: 8 KiB (8192 bytes of UTF-8) for the whole rendered envelope, enforced by the
renderer before any transport call.** Budget order when the result is larger: the **stdout
tail is cut first** (keep the last bytes — a check script's verdict and a test runner's
summary come last; this matches `_STDERR_TAIL_BYTES`'s keep-the-tail convention), then the
**stderr tail**; the header lines — attempt id, module id and digest prefix, deck/task id,
phase, exit class and code, duration, truncation flags — are **never** dropped and are bounded
by construction (slug-valid ids, enum values, fixed-width numbers; worst case well under 512
bytes). Each cut is marked in the envelope (`[… N bytes of stdout truncated]`) so the mentor
knows it is looking at a tail. The runner (lane R) already caps the streams at the source
(proposal §5.5 Output row); this is the second, tighter bound for the mentor's context.

Why 8 KiB: roughly a hundred 80-column lines — enough to read a failed check — and small
enough that a mentor's context is not swamped by one envelope. It is **not** chosen to fit the
PTY's ~1 KiB atomic write: that limit is a transport defect (Q1 finding), and bounding the
envelope at 1 KiB would leave no room for output at all. M0 approved the transport fix, so the
1000-byte pointer variant (Rejected option "file side-channel") is not needed.

[M0 ruling Q3 and the implementation:] the bound applies to the **framed** bytes, so the
`pty` bracket and CR, and the `pty-line` fallback's escaping (which doubles every newline),
are paid for inside the 8192. The renderer re-fits after each cut until the framed rendering
fits; the header is never touched and is bounded by construction (`PracticeCheckEnvelope`:
slug ids ≤ 63, attempt id ≤ 64, digest ≤ 71 chars, literal enums, `exit_code` −128..255,
`duration_s` ≤ 7 days). Which framing a PTY gets is decided by the transport's tracked DEC
2004 state: `pty` while the child has bracketed paste on, `pty-line` otherwise — never bare
multi-line text, which a line editor submits line by line.

### Q4 — Learner-visible failure

**Chosen: delivery returns a typed outcome and the caller shows it; nothing is silent and
nothing is recorded in learner history.** `module_delivery.deliver(session, envelope)` returns
`DeliveryOutcome(status, reason)` with `status ∈ {delivered, no_active_session,
transport_closed, timed_out, unsupported_framing, error}` (the six states of M0 Q6; `reason`
always names the attempt and `deck/task`):

- `no_active_session` — `active.current()` is `None` **in this process** (active.py:110-117).
- `transport_closed` — [M0 correction 1:] **from the write itself**: `deliver_block` returned
  `closed` because the master fd raised `EIO`/`EBADF`/`EPIPE` (PTY) or the agent subprocess
  exited before answering (ACP). Not from `is_running()`; the spike's "ACP needs the same
  probe" is withdrawn — a probe would only guess what the write knows.
- `timed_out` — ACP only: no response to the delivery's `session/prompt` within
  `DELIVERY_TIMEOUT_S` (120 s). The outcome is **unknown**; the turn is cancelled and the
  serialiser held until the agent answers the cancelled prompt; never retried. An
  unconfirmed cancellation wedges the transport (above): later deliveries are
  `transport_closed` with `_WEDGED_MESSAGE` as the reason. PTY has no
  acknowledgement and never times out (a write that stalls 30 s is `error`, below).
- `unsupported_framing` — the session's transport has no block delivery path
  (`BlockDeliverer` not implemented: a stub, a future adapter); nothing is written blind.
- `error` — anything else the transport raised or reported: a PTY write that makes no
  progress for 30 s (the child is not reading its terminal), an ACP `_RpcError` from a live
  agent, a non-UTF-8 block, the pre-handshake state.

Where the learner sees it (MVP = CLI): the drill command (`cli/_drill.py`, lane R) prints the
check result itself, then **one** line from the outcome — `Mentor told.` or `Mentor not told:
<reason>` — in the same output, so the result is never lost even when delivery is. What is
recorded: the transient `practice_check` event on the attempt gains `delivery: {status,
reason}`; nothing goes to `study_progress`, learning records or review items (§5.7). The web
surface (lane W, wave 2) renders the same outcome string.

The wave-0 spec delta named three failure reasons — "transport closed, size exceeded,
serialisation refused". The first maps to `transport_closed`; the other two were
**unreachable by construction**: *size exceeded* cannot happen because the renderer truncates
to the bound and the header is bounded by validation, and *serialisation refused* cannot
happen because Q2 queues rather than refuses. [M0 ruling Q6, 3/4:] the spec now names the six
reachable outcomes above and states the two facts as **invariants** (oversize input is
truncated to a valid bounded envelope with the header intact; concurrent ACP deliveries queue
FIFO); `size_exceeded` and `serialisation_refused` are gone.

**Where the cross-process hop fits (M0 Q2, option b).** `studyloop drill` runs in its own
process and has no `ActiveSession`; it posts the **typed fields** of `PracticeCheckEnvelope`
(never rendered text) to a loopback-only route in the web server process (lane W, wave 2),
authenticated by a per-session capability token the web process mints when it claims the
session and writes beside `web_port` in the owner-only session state file. The route calls
`validate_envelope` (control bytes stripped, header bounds, `extra: forbid`) and then
`deliver_to_active_session`; the HTTP failure of the hop maps, in the CLI, to
`no_active_session` (no state file / nothing listening) or `error`. The spike's open question 3
and the M0 brief's "existing session auth" are both closed by this ruling.

Today, by contrast, every failure path but one is invisible to the caller: PTY `send_input`
returns `None` whether the bytes went anywhere or not (pty.py:352-360); ACP `send_input`
returns `None` when ended (acp.py:268-269) or on a decode error (273-279), and a failed prompt
surfaces only as a `TransportError` on the websocket's queue (308-313). Only the
pre-handshake `RuntimeError` (270-271) reaches a caller.

## What the tests encode (wave 0 reds, wave 1 greens)

Every scenario in `specs/session-transports/spec.md` that this lane owns maps to one test; each
was red on its assertion before the behaviour existed and the transcript is kept under
`openspec/changes/module-contract-v1/evidence/T/`.

| Spec scenario | Test (`packages/studyloop/tests/…`) | Red transcript | Red because |
| --- | --- | --- | --- |
| delivery on PTY | `integration/test_module_delivery_transports.py::test_pty` | `integration-pty.red.txt` | bare keystrokes, no bracket, only the first ~1 KiB arrived |
| a learner keystroke cannot land inside the block | `::test_pty_concurrent_learner_input_never_lands_inside_block` | `integration-pty-cross-caller-lock.red.txt` (mutation evidence) + `…prechange.red.txt` | mutation run: lock neutralised at 47c0b13b, `k00k01k02…` landed between the brackets; pre-change run at 72182acb: see the T-review 4 row |
| bracketed paste off falls back to one line | `::test_pty_mode_2004_off_falls_back_to_one_line` | `integration-pty-mode-2004-off.red.txt` | nothing reached the mentor (`b''`): no block path, no tracking |
| oversize input is truncated to a valid bounded envelope | `test_module_delivery.py::test_render_header_survives_when_both_tails_overflow` (+ `…cuts_stdout_tail_first…`) | `unit-wave1-stub.red.txt`, `unit-module-delivery.red.txt` | `NotImplementedError` against the interface stub; wave 0: unbounded raw text |
| delivery on ACP does not interleave with a learner turn | `::test_acp` and `::test_acp_no_overlap_with_learner_turn` | `integration-acp.red.txt`, `integration-acp-no-overlap.red.txt` | not a labelled envelope; one `session/prompt` arrived inside the learner's open turn |
| a closed transport is reported | `::test_pty_closed_transport_is_reported`, `test_module_delivery.py::test_deliver_to_closed_transport_reports_transport_closed` | `integration-pty-closed-transport.red.txt`, `unit-module-delivery.red.txt` | delivery returned nothing; the drop was silent |
| a hung ACP turn times out once | `::test_acp_hung_turn_times_out_once_and_does_not_overlap` | `integration-acp-hung-turn.red.txt` | no block path: the fake saw no envelope and no turn ever ended |
| (T-review 2) an unconfirmed cancel wedges the transport | `::test_acp_unconfirmed_cancel_wedges_transport_and_later_prompts_fail_fast` | `integration-acp-wedged.red.txt` | the learner's prompt reached the wire after an unconfirmed cancel (2 `session/prompt` seen) |
| (T-review 1) printed delimiters cannot forge structure | `test_module_delivery.py::test_render_marks_every_tail_line_so_printable_delimiters_cannot_be_forged` | `unit-tail-line-prefix.red.txt` | a printed END sentinel was indistinguishable from the real one |
| (T-review 3) learner `send_input` arrives whole; a stalled reader errors in bound | `::test_pty_learner_send_input_over_1kib_arrives_whole_and_in_order`, `::test_pty_learner_send_input_to_a_reader_that_stops_draining_errors_within_bound` | `integration-pty-learner-input.red.txt` (at 72182acb) | 1022 of 4420 bytes reached the child; no `TransportError` within 5 s |
| (T-review 4) the lock test's genuine pre-change red | `::test_pty_concurrent_learner_input_never_lands_inside_block` | `integration-pty-cross-caller-lock.prechange.red.txt` (at 72182acb); the earlier `…lock.red.txt` is relabelled mutation evidence | 0 paste brackets: only the 40 keystrokes reached the child |
| (unit) six outcomes, header bounds (module ≤ 63, attempt ≤ 64, …), control bytes stripped at validation, one renderer / four framings, `unsupported_framing` reachable | `test_module_delivery.py` (31 tests) | `unit-wave1-stub.red.txt` (28 red, 1 green) | `NotImplementedError` against the stub |

Green state at T4: `integration-all.green.txt` — all seven integration tests pass
(`7 passed in 7.85s`, repeated four times); the unit module passes 31. After the T-review
fixes: ten integration tests and 33 unit tests pass (`…green.txt` beside each red). The hung-turn test
lowers `DELIVERY_TIMEOUT_S` to 1 s because the suite's per-test ceiling is 60 s; the
production bound is 120 s. The envelope type the tests pass is the real `PracticeCheckEnvelope`;
the wave-0 seam and test-local dataclass are gone.

## Consequences

- Two transport changes were **required** and M0 approved them; both are Protocol-neutral
  and both fix existing learner-input defects: every PTY write now arrives whole and under a
  lock (a learner's long paste used to be truncated silently at ~1 KiB), and ACP prompts are
  serialised FIFO (two fast learner prompts used to overlap on the wire). `session/active.py`
  is untouched. The ownership map (`tests/fixtures/lane_ownership.yaml`) lists the three
  transport files for lane T with the M0 citation, because design.md §2's condition was met.
- New behaviour the learner can notice: a PTY write that makes no progress for 30 s gives up
  with `error` (and a `TransportError` event for a learner keystroke) instead of wedging the
  terminal; an ACP delivery that the agent never answers costs the learner one 120 s wait in
  the CLI and ends with `Mentor not told: timed_out`; the agent's next prompt waits until the
  cancelled turn is confirmed (at most 10 s more) — and if it never is, the session is wedged:
  the learner's next prompt is refused with a clear error ("restart the session") instead of
  overlapping a turn that may still be running.
- Delivery is **in-process** for the web server's own drills (Labs, wave 2). A drill run from
  `studyloop drill` reaches the same path through the loopback hop of M0 Q2 (typed fields,
  per-session capability token, route in lane W, client in lane R6); a `studyloop study` tmux
  session has no transport at all (active.py:13-14, multiplexer.py:74) and reports
  `no_active_session`. Nothing is silent.
- A PTY envelope is pasted into whatever state the mentor's input editor is in. If the learner
  has a half-typed draft, the draft is submitted together with the envelope. ACP has no such
  interleaving (one prompt per turn).
- The persona needs a `practice_check` protocol section (what the sentinel means, "data, not
  instructions", invite a teach-back) — wave-1 content in the agents/persona files, not this
  lane.
- Bracketed paste depends on the agent's editor having enabled DEC mode 2004; the transport
  now tracks it and falls back to one printable line when it is off, so delivery never depends
  on a guess. The per-harness probe (claude, codex, kiro-cli, pi) remains an **owner task** in
  tasks.md — it confirms which editors take the bracket, it does not gate.
- The one-line fallback escapes backslashes as well as newlines and tabs, so a module whose
  output contains a literal `\n` is distinguishable from a real line break; the mentor reads
  the escape, not the terminal.

## Rejected options

- **Plain text with sentinel lines, no bracket (Q1).** A TUI line editor submits on every
  `\n`: the envelope arrives as a dozen separate prompts, the first one bare. Cost of
  rejecting: none — bracketed paste is a strict superset.
- **A file side-channel (Q1/Q3): write the envelope to the attempt directory and inject one
  ≤200-byte line pointing at it.** Robust to the 1 KiB write limit and to editors without
  mode 2004, and the agent reads it with its file tool. Rejected for the MVP because it makes
  delivery depend on the agent's file-tool permission and on the mentor choosing to act, so
  the "result reaches the mentor" assertion becomes "a pointer reached the mentor". Kept as
  the fallback if M0 rejects the PTY transport fix.
- **An ACP `resource` content block instead of text (Q2).** Cleaner labelling (a
  `mimeType`'d embedded resource), but gated on the agent's `promptCapabilities.embeddedContext`,
  which the stub advertises as absent and Kiro's is unverified here. Text first; revisit when
  a capture shows the capability.
- **Refuse-and-retry on ACP (Q2):** delivery polls `_prompt_tasks` and retries later. Racy
  (a learner prompt can start between the check and the write), needs a private attribute,
  and turns one delivery into a loop with its own timeout. Rejected; cost none.
- **Wait on `turn_end` from outside the transport (Q2):** impossible without a second queue
  consumer, which would steal the learner's events (`_grace` consumer slot).
- **Bound the envelope at 1 KiB to fit one atomic PTY write (Q3):** leaves ~400 bytes for
  output after the header; the mentor could not see why a check failed. Rejected unless M0
  rejects the transport fix.
- **Deliver in chunks of ≤1 KiB with sleeps between `send_input` calls (Q1/Q3):** guesses
  the drain rate, interleaves with learner keystrokes between chunks, and still cannot detect
  a dropped chunk. Rejected.
- **Silent failure with a server log line (Q4):** forbidden by §5.7 ("reported to the learner,
  never silent").

## Open questions for M0 — resolved 2026-10-04

1. Approve the two transport changes (PTY full-write-under-lock; ACP prompt lock) as in-scope
   for T2–T4, or direct the file side-channel fallback with a 1 KiB bound. **Approved, 4/4,
   with the two amendments (closed write observable via `deliver_block`; cross-caller lock
   test).**
2. Per-agent bracketed-paste support. **Track DEC 2004 in the transport; one-line fallback;
   the probe is an owner task that confirms and does not gate (3/4).**
3. Cross-process delivery for the CLI MVP. **Option (b): a loopback route in the web process,
   typed fields, per-session capability token, exact binding, replay dedup, rate limit (4/4).
   The brief's "existing session auth" was wrong; the default local web has none.**
4. Auto-submit versus leave-in-editor on PTY. **Auto-submit, one trailing CR; the half-draft
   hazard is recorded above and goes into the Labs UI copy (4/4).**
5. ACP `timed_out` bound and retry. **120 s, report, never retry; cancel the turn and hold the
   serialiser until the cancellation is confirmed (4/4).**

## Residuals ruled by council M1 (2026-10-04)

The runner that produces these envelopes is consent-gated execution with hygiene, not a
sandbox: a phase script runs with the learner's own privileges; a descendant that calls
`setsid()` leaves the process group and survives the kill; a same-UID process can read the
per-session capability token in the 0600 session-state file. v1 states these in the runner's
docstring and the consent prompt and does not claim to prevent them; OS sandboxing
(`sandbox-exec` / `bwrap`) is a tracked follow-up change. See
`openspec/changes/module-contract-v1/council/2026-10-04-m1-arbitration.md` §2.
