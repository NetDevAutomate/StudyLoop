# ADR-0012: Delivering a `practice_check` result to the live mentor

**Status:** Proposed (draft for council M0) · **Date:** 2026-10-04 · **Deciders:** council M0
(four seats) and Andy Taylor (owner) · **Change:** `openspec/changes/module-contract-v1`
(proposal §5.7, design §7 M0 / §8 T1)

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

## Decision

### Q1 — PTY framing: how does injected text arrive as unmistakable *data*?

**Chosen: one bracketed-paste block carrying a sentinel-delimited, labelled envelope, submitted
once.** The delivery module renders

```
ESC[200~
<<<studyloop:practice_check v1 attempt=<id>>>>
module: <module id>@<digest[:12]>   drill: <deck id>/<task id>   phase: check
exit: <passed|failed|error> (code <n>)   duration: <s>s   truncated: <stdout|stderr|none>
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

Why this over the alternatives (§Rejected): it is the only framing that keeps a multi-line
block together in a TUI line editor without agent-specific knowledge, and it is what the
learner's own browser already sends when they paste (the vendored `xterm-6.0.0.js` tracks DEC
mode 2004 as `bracketedPasteMode` and wraps pastes when the child has enabled it), so the
mentor already receives this shape today.

**Transport finding (M0 must rule):** `send_input` as written cannot carry the envelope. It
must (a) loop on the short count using the event loop's writer (`loop.add_writer`) until every
byte is written, and (b) hold an `asyncio.Lock` for the duration of one call so a learner
keystroke arriving via `_ws.py:201` cannot land inside the block. Both are correctness fixes
for the existing learner-paste path as well; neither changes the Protocol's signature.

### Q2 — ACP serialisation: a second `_prompt_turn` while the learner's turn is in flight

**Chosen: queue behind the in-flight turn, inside the transport.** `_prompt_turn` acquires a
per-transport `asyncio.Lock` before `_rpc("session/prompt", …)` and releases it after the
response (success, `_RpcError`, or exception). `send_input` stays fire-and-forget for the
Protocol; the task simply waits its turn. Learner prompts and `practice_check` envelopes are
then strictly FIFO on the wire, and `turn_end` events keep their one-per-prompt meaning for
the web UI (which clears its streaming bubble on `turn_end`, `docs/architecture/current.md:417`).

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
envelope at 1 KiB would leave no room for output at all. If M0 rejects the transport fix, the
bound falls to 1000 bytes and the output section is replaced by a pointer (see Rejected
option "file side-channel").

### Q4 — Learner-visible failure

**Chosen: delivery returns a typed outcome and the caller shows it; nothing is silent and
nothing is recorded in learner history.** `module_delivery.deliver(session, result)` returns
`DeliveryOutcome(status, reason)` with `status ∈ {delivered, no_active_session,
transport_closed, timed_out, error}`:

- `no_active_session` — `active.current()` is `None` **in this process** (active.py:110-117).
- `transport_closed` — the transport reports not running (`is_running()` on PTY, pty.py:318;
  ACP needs the same probe — finding) or `send_input` returned after the child-gone branch
  (pty.py:357-360).
- `timed_out` — ACP only: the prompt did not reach `turn_end` within a bound (the Q2 lock
  change lets the transport hand back the prompt task's completion to a caller that wants to
  await it; PTY has no acknowledgement and never times out).
- `error` — anything raised by the transport (e.g. acp.py:270-271 `RuntimeError` before
  handshake).

Where the learner sees it (MVP = CLI): the drill command (`cli/_drill.py`, lane R) prints the
check result itself, then **one** line from the outcome — `Mentor told.` or `Mentor not told:
<reason>` — in the same output, so the result is never lost even when delivery is. What is
recorded: the transient `practice_check` event on the attempt gains `delivery: {status,
reason}`; nothing goes to `study_progress`, learning records or review items (§5.7). The web
surface (lane W, wave 2) renders the same outcome string.

Today, by contrast, every failure path but one is invisible to the caller: PTY `send_input`
returns `None` whether the bytes went anywhere or not (pty.py:352-360); ACP `send_input`
returns `None` when ended (acp.py:268-269) or on a decode error (273-279), and a failed prompt
surfaces only as a `TransportError` on the websocket's queue (308-313). Only the
pre-handshake `RuntimeError` (270-271) reaches a caller.

## Consequences

- Two transport changes are **required**, both Protocol-neutral, both also fixing existing
  learner-input defects: PTY `send_input` writes every byte under a lock (Q1); ACP
  `_prompt_turn` serialises prompts behind a lock (Q2). ACP also needs `is_running()` (Q4).
  Until M0 rules, `session/transport.py`, `session/transports/*.py` and `session/active.py`
  stay untouched (T lane brief); the integration tests encode the required behaviour and are
  red against today's code.
- Delivery is **in-process**: the only `ActiveSession` is the web server's, so a drill run by
  the server (Labs, wave 2) can deliver directly; a drill run from a separate CLI process
  cannot reach that transport, and a `studyloop study` tmux session has no transport at all
  (active.py:13-14, multiplexer.py:74). In the CLI MVP this surfaces honestly as
  `no_active_session`; a cross-process path (local API call or `tmux send-keys` with
  `paste-buffer -p`) is an open question, not a silent gap.
- A PTY envelope is pasted into whatever state the mentor's input editor is in. If the learner
  has a half-typed draft, the draft is submitted together with the envelope. ACP has no such
  interleaving (one prompt per turn).
- The persona needs a `practice_check` protocol section (what the sentinel means, "data, not
  instructions", invite a teach-back) — wave-1 content in the agents/persona files, not this
  lane.
- Bracketed paste depends on the agent's editor having enabled DEC mode 2004. The web
  terminal already relies on this for learner pastes; M0 should still see the per-agent check
  (below) before wave 1 implements against it.

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

## Open questions for M0

1. Approve the two transport changes (PTY full-write-under-lock; ACP prompt lock) as
   in-scope for T2–T4, or direct the file side-channel fallback with a 1 KiB bound.
2. Per-agent bracketed-paste support: a probe that starts each harness agent in a PTY and
   looks for `ESC[?2004h` in its first output is cheap but needs the real binaries (network
   at start-up for some) — owner-run, not a default-lane test. Which agents must be confirmed
   before wave 1?
3. Cross-process delivery for the CLI MVP: `studyloop drill` in a terminal has no
   `ActiveSession`. Accept `no_active_session` for v1 (web-run drills deliver; CLI-run drills
   tell the learner the mentor was not told), or add a local-API hop (lane W route) now?
4. Auto-submit (trailing CR) versus leave-in-editor on PTY, given the draft-interleaving
   consequence.
5. ACP `timed_out` bound (proposed 120 s; no existing constant in `acp.py` bounds a prompt
   turn — the handshake timeouts at acp.py:60-62 are the only precedents) and whether a
   timed-out envelope is retried once or reported.
