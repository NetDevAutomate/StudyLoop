# Council review — harness tier evidence (issue #21) — 2026-09-16T00:57:05+00:00

Seats: openai.gpt-6-astra, grok-4.6, claude-opus-5. Explicit no-tools contract; each seat saw the receipt `harness-evidence-2026-09-16.md` and the branch's commit list, nothing else. Answers verbatim.

## Seat: `openai.gpt-6-astra` (3744 in / 660 out, 17s)

1. **pi → core: ACCEPT-WITH-CONDITIONS.** Decisive reason: the receipt connects a real model reply with a working lifecycle and a current-session export containing assistant messages—not merely a green mechanical lane.
   Before merge, require the reply-aware rerun in #5; the existing lane can pass on authentication errors or prompt echoes.
   This supports the tested pi 0.65.0 CLI/tmux configuration, not every installation or transport.

2. **OpenCode stays preview: sound.** The current SQLite sessions are invisible to the legacy-only exporter; that independently blocks promotion.
   The quota error explains this run’s failure, but “environment, not integration” overstates what is established: successful authenticated integration remains untested.
   Fixing the exporter and changing providers must culminate in a completed model reply and a correlated user/assistant export—not another mechanical lane pass.

3. **Grok: HOLD preview.** Decisive reason: no completed assistant reply was captured, and the export contains only user messages.
   “Five green” follows the receipt’s permissive engagement rule; it does not establish a completed learning exchange or assistant-export fidelity.
   “Everything needed to flip” is therefore overstated. The DoD also favors holding; web credential filtering is a separate transport limitation, not something to disable casually.

4. **Gate first: `f0edce6a`, Grok’s automatic trust pre-write.** It silently grants trust and mutates persistent real-home security state; unit-suite isolation does not make production writes safe.
   Require explicit authorization, exact-directory scoping, preservation of unrelated entries, and tested cleanup/concurrent-write behavior.
   Real-auth mode is useful but exposes real credentials and writable harness homes; opt-in and redaction do not constitute isolation.
   Claude-only pre-trust correctly narrows an existing side effect, but does not itself validate automatic trust.
   The scratch pointer scrub is sensible; verify scratch overrides are restored and intended non-pointer controls survive. Commit titles cannot establish those implementation details.

5. **Single strongest additional measurement:** a reply-aware, real-auth pi run that resumes the same session, waits for a completed assistant turn, then exports.
   Measure whether that exact post-resume assistant response appears in the scratch DB under the correct session.
   This joins resume, actual model completion, and export fidelity while eliminating the known echo/spinner false positive.

6. **MERGE AFTER Grok automatic trust is gated or reverted and the correlated, completed post-resume pi reply/export check passes.**

## Seat: `grok-4.6` (3861 in / 1400 out, 9s)

(empty)

## Seat: `claude-opus-5` (5829 in / 1400 out, 26s)

(empty)
