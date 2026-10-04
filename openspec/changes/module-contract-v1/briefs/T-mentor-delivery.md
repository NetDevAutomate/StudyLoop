# Lane T — mentor delivery of a check result

Read `00-common.md` first. Then `proposal.md` §5.7 (the contract item: a bounded, labelled
result reaches the live mentor; module text is untrusted data), `design.md` §7 (M0) and §8
(what is already verified), and `docs/adr/0011-*.md` + `docs/adr/README.md` for the ADR format.

| | |
| --- | --- |
| Branch | `feat/module-mentor-delivery` |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/module-mentor-delivery` |
| Base | `git rev-parse HEAD` at start — record as `Base: <sha>` in your first commit body |
| Merge position | after S and **after council M0 has decided** the ADR; T2–T4 are wave 1 |
| DoD item | 5 |
| Wave-0 scope | **T1 only** — a time-boxed spike: read, trace, draft the ADR, write test doubles. **No production code.** Stop and report. |

## Owned globs (repo-relative)

- `docs/adr/0012-practice-check-delivery.md` (new) and **one new table row** in
  `docs/adr/README.md` — the single docs-lease exception (new content, no conflict with the
  other session's files). Nothing else under `docs/`.
- `packages/studyloop/tests/test_module_delivery.py` (doubles only this wave)
- `packages/studyloop/tests/integration/__init__.py` + `conftest.py` if needed, and
  `integration/test_module_delivery_transports.py` (marker `integration`; may be a skeleton)
- `packages/studyloop/src/studyloop/session/module_delivery.py` — **wave 1, not now**
- `openspec/changes/module-contract-v1/evidence/T/**`

## Forbidden

`session/transport.py`, `session/transports/*.py`, `session/active.py`, `web/**`, everything in
`modules/`, `content/schemas.py`, `mkdocs.yml`, `CHANGELOG.md`. If the spike concludes a
transport file **must** change, that is a finding for the ADR, not an edit.

## T1 — the spike (one commit: ADR draft + doubles; gate G applies — nothing here should turn tests red)

Read, in this order, and cite line numbers in the ADR:
`session/active.py` (`ActiveSession.transport`, ~50-54), `session/transport.py`
(`send_input`, ~145), `session/transports/pty.py` (~351-360 writes raw bytes to the master fd),
`session/transports/acp.py` (~267-290 decodes input and fires `_prompt_turn` as a background
task), `web/routes/session/_transport.py` (~42-103, how the web layer reaches the transport).
Verify every line reference you write; the numbers above are from the plan and may have drifted.

Answer **exactly four questions**, each with: the options considered, the one chosen, why, and
what was rejected and its cost:

1. **PTY framing.** Injected text arrives at the mentor as if typed. How is an envelope made
   unmistakably *data* to the agent (delimiters, a labelled block, size-limited, no learner
   keystrokes interleaved), and what do the existing harness agents already recognise?
2. **ACP serialisation.** A second `_prompt_turn` while the learner's turn is in flight is the
   hazard. Queue behind the in-flight turn, wait on a turn-end signal, or refuse-and-retry?
   Trace what `acp.py` exposes today for "turn in progress".
3. **Envelope size bound.** What is the bound, where is it enforced (before transport), and what
   is dropped first (stdout tail, then stderr, never identity/exit class)?
4. **Learner-visible failure.** If delivery fails (no active session, transport closed, turn
   never ends), what does the learner see, where (CLI for the MVP), and what is recorded?

Write `docs/adr/0012-practice-check-delivery.md` in the house format (header line with
Status: **Proposed** · Date · Deciders; Context; Decision per question; Consequences;
Rejected options; Open questions for M0). Add the README table row with Status `Proposed`.

Test doubles: `tests/test_module_delivery.py` with a `FakeTransport` recording `send_input`
calls and a `FakeActiveSession`, plus the skeleton integration module marked `integration`
whose two tests (`test_pty`, `test_acp`) are present and **skip with a reason naming the ADR
question they wait on** — this wave they are allowed to skip; wave 1 makes them red then green.
Deselection: `addopts` already excludes `integration`, so the default suite is unaffected.

Verification for the report: `git diff --stat` shows only the ADR, the README row and test
files; `env -u VIRTUAL_ENV just test` green; `env -u VIRTUAL_ENV just docs` green (ADRs are not
in `mkdocs.yml` nav — confirm strict build still passes with the new page); gate G.

## Report (in addition to common §6)

The four answers in one line each, the list of transport facts you verified with line numbers,
and anything in `design.md` §8 that turned out to be wrong. This report is M0's input.
