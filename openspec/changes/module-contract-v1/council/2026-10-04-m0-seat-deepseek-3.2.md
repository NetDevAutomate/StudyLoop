# Council M0 — transport decision (deepseek-3.2 seat)
**Date:** 2026-10-04
**Seat:** deepseek-3.2
**Scope:** module‑contract‑v1, ADR‑0012 `practice_check` delivery

---

## 1. The two transport changes

**Approve both**, as in‑scope for T3/T4. The Protocol signature does not change.

**PTY (`send_input` loop + lock):**
- **If we don't:** `send_input` silently truncates >1 KiB writes (`pty.py:351-360`; evidence `pty-single-write.txt`). For learner pastes and `practice_check` envelopes alike, the mentor receives a partial or empty block with no error.
- **If we do:** The envelope arrives whole, labelled as data; a concurrent learner keystroke cannot land inside the bracket. The fix matches the PTY’s existing `O_NONBLOCK` (`pty.py:273`) and corrects a latent defect in the learner‑paste path.
- **Test:** `test_pty` (integration red) will turn green only after the loop writes every byte; a lock test (`test_pty_no_interleave_with_learner_keystroke`) can reuse the same fake‑mentor setup.

**ACP (`_prompt_turn` lock):**
- **If we don't:** A `practice_check` envelope may interleave with a learner’s turn, violating spec scenario “delivery on ACP does not interleave with a learner turn” (evidence `integration-acp-no-overlap.red.txt`). The single‑consumer event queue (`_ws.py:105`) cannot be read twice, so external callers cannot wait for turn‑end.
- **If we do:** Prompts are FIFO; one `turn_end` per prompt retains its meaning for the web UI (`docs/architecture/current.md:417`). The lock lives inside the transport, fire‑and‑forget semantics unchanged (`acp.py:267-288`).
- **Test:** `test_acp_no_overlap_with_learner_turn` already red; will green with the lock.

File side‑channel (1 KiB pointer) is inferior: it shifts delivery from “data reaches the mentor” to “a pointer reaches the mentor”, adds a file‑tool permission dependency, and forces envelope truncation to ~400 bytes of output. Reject.

## 2. Cross‑process delivery (ADR open question 3)

**Choose (b), loopback‑only, authenticated, validated.**
- **Consequences:** A text‑injection endpoint into the mentor’s terminal. Must be loopback‑only (same‑origin check, `web/routes/…`); must validate envelope size (≤8 KiB) and structure on the server side (never trust CLI rendering); must rate‑limit; must bind to the active session (`study_session_id`). W owns `web/routes/`.
- **Why not (a):** MVP’s only execution surface is `studyloop drill` in a separate CLI process (`active.py:13-14`). Accepting `no_active_session` would make delivery unreachable in the MVP outside tests, shipping a contract item nothing can exercise.

## 3. Bracketed‑paste dependence (open question 2)

**Track mode in the transport and fall back.**
- **Why:** The web terminal already relies on DEC 2004 for learner pastes (`vendored xterm‑6.0.0.js`). A fallback to bare text + CR when the child has not sent `ESC[?2004h` preserves delivery, albeit without line‑editor protection.
- **Failure mode:** If the agent’s editor ignores mode 2004, the envelope arrives as multiple separate prompts (first line bare). That is still better than silent truncation.
- **Probe:** Owner‑run per‑harness probe to confirm before wave 1, not a gate.

## 4. Auto‑submit vs leave‑in‑editor (open question 4)

**Auto‑submit in v1, document the hazard.**
- **Bound:** A learner’s half‑typed draft is submitted together with the envelope. The learner triggered the check seconds earlier and is rarely mid‑draft.
- **Alternative (hold until empty) requires editor state the transport does not have.**
- **ACP has no interleaving:** one prompt per turn.

## 5. ACP `timed_out` (open question 5)

**120 s, report, no retry.**
- **Why:** No existing constant in `acp.py` bounds a prompt turn; handshake timeouts (`acp.py:60-62`) are the only precedent. A retry risks a duplicate envelope (forbidden by S4).
- **Implementation:** The Q2 lock change lets the transport hand back the prompt task’s completion to a caller that wants to await it; timeout on that await.

## 6. The spec delta

**Amend the spec:** remove “size exceeded” and “serialisation refused” as failure reasons.
- **Why:** Size exceeded cannot happen—the renderer truncates to 8 KiB before any transport call, header bounded by slug validation and enums (`module.yaml` validation). Serialisation refused cannot happen—Q2 queues rather than refuses; nearest failure is a prompt that never ends (`timed_out`).
- **Keep “transport closed”:** maps to `transport_closed` outcome (PTY `is_running()`, ACP needs same probe).

## 7. What the ADR gets wrong

**ADR is correct on the code facts checked.** Verified:
- F1: `PTYTransport.send_input` writes once, discards return value (`pty.py:356`). ✅
- F2: `ACPTransport.send_input` schedules `_prompt_turn` as a background task (`acp.py:283-288`); “turn in progress” visible only through `_prompt_tasks` set and single‑consumer queue. ✅
- F3: Learner keystrokes reach PTY through `_ws.py:201` with no lock. ✅
- F4: `active.current()` is per‑process (`active.py:110-117`); `studyloop drill` has no `ActiveSession`. ✅
- F5: Browser pastes through DEC 2004 brackets (vendored xterm). ✅

**Claim that may be accepted too readily:** That the MVP must have cross‑process delivery to be useful. The MVP could ship with `no_active_session` reported to the learner, making delivery a CLI‑only feature until v1.1 adds browser‑triggered checks. The council’s choice (b) is still the better path.

---

**One‑line verdicts:**
1. **approve** PTY loop+lock and ACP prompt lock
2. **amend:** loopback‑only authenticated POST, server‑side validation, W owns route
3. **approve** track mode 2004, fall back, owner probe
4. **approve** auto‑submit, document hazard
5. **approve** 120 s, report, no retry
6. **amend** spec: remove “size exceeded”, “serialisation refused”
7. **approve** ADR correct; cross‑process delivery necessity arguable

**Findings: 0 raised**
