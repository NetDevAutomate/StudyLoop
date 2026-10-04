# Council M0 seat qwen3-coder-next — answers

## 1. Transport changes (PTY loop+lock, ACP prompt lock)

**Approve both.**

**PTY `send_input` loop+lock (pty.py:351-360)**: The spike proves `os.write` returns short (≈1022 bytes) on macOS for payloads >1 KiB, silently dropping the remainder (evidence/T/pty-single-write.txt, pty-looped-write.txt). The ADR's requirement — `loop.add_writer` to complete the block and an `asyncio.Lock` to serialise with learner keystrokes — fixes a latent defect that also affects learner pastes. Without this fix, any `practice_check` envelope >1 KiB is truncated (the spec requires 8 KiB bounding per Q3), and long learner pastes are similarly corrupted. With it, both paths are robust. **Test**: `integration-pty.red.txt` shows the fake mentor received only the first ≈1 KiB; after the fix it must receive the full bracketed envelope.

**ACP `_prompt_turn` lock (acp.py:290-316)**: Today `_rpc("session/prompt")` has no per-transport serialisation; `_prompt_tasks` is only a set for GC. Two calls (`send_input` from a check, plus a learner keystroke via `_ws.py:201`) can interleave on the wire, breaking the one-turn-per-`turn_end` invariant. The ADR's fix — a lock around `_rpc` — enforces FIFO. **Test**: `integration-acp-no-overlap.red.txt` shows the fake mentor saw one `session/prompt` arrive inside the learner's open turn; after the fix the envelope must wait for `turn_end` before proceeding. Neither change touches `AgentSessionTransport` signatures (transport.py:145-150), only implementation.

---

## 2. Cross-process delivery (ADR open question 3)

**Approve (b): local hop to the running web server.**

**Security consequences** (as stated in the ADR): this is a text-injection endpoint into the mentor's terminal. It must be:
- loopback-only (127.0.0.1:PORT, never 0.0.0.0)
- authenticated (the existing session token from the CLI's `studyloop drill` invocation)
- validated (size bound on the server side, never trusting the CLI's rendering; envelope parsed as `PracticeCheckEnvelope`, rejected if over 8 KiB UTF-8 after rendering)
- rate-limited (one per claimed session per 10 seconds, or similar)

The route is owned by W (`web/routes/session/_ws.py` already handles session authentication; add `POST /api/session/delivery` using the same `session_from_token` guard). This is the minimal path that makes delivery reachable in the CLI MVP outside tests, because the web server's `ActiveSession` holds the live transport (active.py:110-117); the CLI process has no transport.

**Alternative (a)**: `no_active_session` is contractually unacceptable — §5.7 requires delivery and §8 says delivery failure is never silent, but `no_active_session` means nothing in the CLI MVP can exercise it outside tests. **Rejected**.

---

## 3. Bracketed-paste dependence (open question 2)

**Approve: track DEC 2004 in the transport and fall back to bare text + CR.**

**Implementation**: `PTYTransport` should record `ESC[?2004h` / `ESC[?2004l` from the child's output (xterm's mode change notifications) in its own state. On `send_input`, if mode 2004 is known to be enabled, wrap with `ESC[200~` and `ESC[201~`; otherwise send bare text followed by a trailing CR.

**Fallback failure mode**: When the agent's editor has not enabled mode 2004, the envelope arrives as a dozen separate prompts (one per `\n`), and the first line (`ESC[200~`) is executed as a shell command. This is a visible failure (the mentor sees "command not found: ESC[200~") rather than silent truncation, so it meets §5.7's "reported, never silent". The probe in §7 confirms agents support bracketed paste, but the fallback ensures robustness if a new agent is added later.

---

## 4. Auto-submit vs leave-in-editor (open question 4)

**Approve: auto-submit in v1 with documentation of the hazard.**

**Rationale**: The envelope is delivered in response to a `check` that the learner triggered seconds earlier; they are unlikely to be mid-draft when the check completes. A "hold until the input line is empty" heuristic requires editor state the transport does not have (PTY is a byte stream, not a TUI control). Auto-submit is the existing browser behaviour (vendored xterm tracks `bracketedPasteMode` and submits the whole block), so it is consistent. The hazard — a half-typed draft is submitted together with the envelope — must be documented in the mentor brief as a known limitation, but it is acceptable for v1.

---

## 5. ACP `timed_out` (open question 5)

**Approve: 120 s bound, report, no retry.**

**Rationale**: `acp.py` has no existing constant that bounds a prompt turn (the handshake timeout at acp.py:60-62 is for connection setup, not prompt execution). A 120 s bound matches the existing CLI timeout pattern. No retry is required because S4 forbids interleaving, and a retry would risk sending a duplicate envelope if the original turn completed after the timeout but before the client noticed. The transport can expose the pending task to a caller (via a new `pending_prompt_task` property) so a caller can await it and receive a `timed_out` outcome when the future never resolves.

---

## 6. Spec delta (three failure reasons)

**Amend the spec: two are unreachable by construction.**

The spec names three reasons: "transport closed, size exceeded, serialisation refused".
- **transport closed**: reachable (`is_running()` check before `send_input`, pty.py:352-354, 357-360; ACP needs the same probe).
- **size exceeded**: unreachable by construction — the renderer enforces the 8 KiB bound (Q3), and the header is bounded by slug validation (MC014) and enum values (≤512 bytes worst case), so there is no envelope >8 KiB to send.
- **serialisation refused**: unreachable by construction — Q2 queues instead of refusing; the nearest failure is `timed_out`, not refusal.

**Action**: Replace the spec text with: "Delivery failure is reported when the transport is closed or when ACP's prompt exceeds its bound. Size and serialisation refusal are unreachable by construction."

---

## 7. What the ADR gets wrong

**One verified error and two expected-to-be-accepted claims:**

1. **Error**: ADR cites `pty.py:351-360` for `send_input` "discards the return value" — this is correct. But it also states "the master fd is `O_NONBLOCK` (pty.py:273)" — verified: pty.py:273 sets `fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)`. However, the spike's measurement (evidence/T/pty-single-write.txt) shows a 1024-byte write returns 1022, not 1022 *and nothing else arrives*; the ADR's description of the short-count behavior is correct, but the consequence is that **any** payload >1022 bytes is partially lost, not just that "canonical mode drops whole lines". The ADR is right to call for a loop, but the reasoning should say "non-blocking `os.write` may return a short count, not that the BSD `TTYHOG` limit applies in raw mode (the spike used raw mode)".

2. **Expected to be accepted**: ADR says `active.py:110-117` proves "a CLI-owned session has no `ActiveSession`". Verified: `current()` returns the web server's singleton (`_active` at active.py:52), and the CLI's `studyloop study` runs in a tmux pane via `multiplexer.send_keys` (multiplexer.py:74) — not an `AgentSessionTransport` at all. This is correct and crucial for cross-process delivery.

3. **Expected to be accepted**: ADR says the web terminal's xterm already tracks DEC 2004 as `bracketedPasteMode`. This is a fact about the browser, not the mentor's agent; M0 should verify against real agents, but the ADR's reliance on it for the envelope framing is reasonable if the probe in Q3 confirms support.

---

**Verdicts:**
1. approve
2. approve
3. approve
4. approve
5. approve
6. approve (amend spec: two reasons unreachable)
7. approve (one verified correction, two expected-to-accepted claims)

Findings: 1 raised (the short-count behavior description in the ADR is imprecise; the spike measured non-blocking writes returning partial counts, not TTYHOG drops in raw mode).
