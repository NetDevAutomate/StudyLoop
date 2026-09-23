# Arbitration — council review 9 (issue #38: the mentor writes, learning tier item 1)

**Reviewed tree:** `feat/learning-tier-fed` @ `3c175f78` (5 commits on `main` `c1a28de1`).
**Brief:** `brief-review9-2026-09-23.md` (sha256 `f2217677…`, 1212 lines: binding context, commits, the
protocol and S1-0 receipt verbatim, the full source/test/definition diff). **Receipts:** `review9/` — one
transcript per seat; the pre-commit whitespace hooks normalise trailing whitespace and final newlines, so
`git diff -w` against the originals is empty and the originals' sha256 prefixes are `b9c0f2bdab8956fa`
(grok-4.6), `cbf7e06937f97dd8` (openai.gpt-6-astra), `1245f34100fa4929` (qwen3-coder).
**Corrections landed on:** `ad6d1f9d`, `019624c3`, `2a4d4d1d`, `616fd1ed` (tree `616fd1ed`).

## Seats and verdicts

| Seat | Verdict | 🔴 | 🟡 |
|---|---|---|---|
| openai.gpt-6-astra | ACCEPT-WITH-CORRECTIONS | 0 | 5 |
| grok-4.6 | ACCEPT | 0 (two "🔴-shaped" S1-SIM gates, not merge gates) | 5 |
| qwen3-coder | REJECT | 2 | 1 |

### Method

Every 🔴/🟡 was checked against the tree before anything was changed — by running the code (`coerce_scores`
on bools and floats), reading the function bodies the finding cites (`record_teachback`'s `except` clauses,
`records.bind`/`_owner`, `observations.record`), or grepping the file the finding names. A finding whose
claim the tree contradicts is refuted below with the evidence; one that holds is landed one coherent commit
per concern (findings that share a file share a commit and are both named in its message). Deviation from
"one commit per finding" stated here on purpose.

### Findings and dispositions

- **grok Y5 — blank `concept`/`topic` accepted.** Verified: the columns are `NOT NULL` (`migrations.py:454,
  506`) and `""` satisfies `NOT NULL`. **Landed `019624c3`:** refused at the tool boundary before any write;
  three parametrised tests. The CLI has the same hole (a click argument can be `""`); left, as the finding
  says, "not the defect this branch is for".
- **grok Y1 — one `ToolError` for three failures.** Partially verified: `record_teachback` returns `False`
  for no connection, `sqlite3.IntegrityError` and `sqlite3.OperationalError` (lines 93, 201, 214) and does not
  say which. **Landed `019624c3`:** the message now states the three causes instead of claiming
  "unavailable". Not landed: a real split, which needs the writer to distinguish them — the CLI inherits the
  same collapse — and is out of this branch's scope. The finding's other clause ("swallows `ScopeError`") is
  **false**: `ScopeError` is not caught; it propagates.
- **grok Y2 — Grok's projection is asserted, not pinned.** Verified true as stated. **Landed `ad6d1f9d`:**
  `test_grok_projects_the_codex_definition` pins the adapter's documented projection and that `agents/grok/`
  does not exist (so a split fails loudly). Checking this finding's mechanism produced the coordinator's own
  finding below.
- **grok Y3 — the `consent` column is documentation, not a runtime check.** True by design and the seat says
  so; accepted as recorded. **Not code:** it becomes S1-SIM's refusal-path script (item 2 of the seat's list),
  which is the claim-blocker for "pipe open", not a merge blocker.
- **astra Y2 — the no-new-grant guards are weaker than their names.** Verified: the Kiro guard tested an exact
  intersection only (a `@studyloop/*` wildcard would pass it); the OpenCode guard was four substring checks
  (an added allow rule would pass). **Landed `ad6d1f9d`:** the Kiro guard also refuses any wildcard entry; the
  OpenCode block is parsed from the frontmatter and compared whole.
- **astra Y3 — "projected byte-identically" is not what the tests establish.** Verified: the receipt's §2
  wording overstated the mechanism; the implementation is one file, hashed, plus an identical reference
  sentence and the names in each definition. **Landed `ad6d1f9d`:** receipt §5(b) states the actual
  mechanism and marks installed-path resolution for Codex/Claude/OpenCode **UNVERIFIED** (a pre-existing
  question for all nine shared protocols) → S1-SIM. The seat's proposed six-adapter resolution test is not
  built here; it is the SIM stage.
- **astra Y4 — "each writer's row landed" exceeded the assertions.** Verified: the test stat'ed files.
  **Landed `616fd1ed`:** rows counted in the sandbox database (`teach_back_scores`, `parked_topics`), the
  topics file must carry the concept.
- **astra Y5 — no explicit unsuccessful-write path in the protocol.** Verified. **Landed `2a4d4d1d`:** a
  paragraph — say it in one line, continue, never retry silently, never claim a record that did not land.
- **qwen R2 — the `when:` strings are vague.** Partially accepted, not as a blocker: the trigger's
  observable part (five scores proposed in one sentence; the learner's next reply accepts them) is now in
  the `when:` text (`2a4d4d1d`). The consent column stays vocabulary, as grok Y3 argues.

### Coordinator's own finding (found while verifying grok Y2) — landed `ad6d1f9d`

`studyloop study` does not hand any adapter the installed definition. It renders
`agents/shared/personas/<mode>.md` through `agent_launcher.build_canonical_persona` and gives that string
to every adapter's `setup()` (`agent_launcher.py:76, 273–`; `adapters/_strategies.py`). So the six files
GREEN named the writers in are what a learner gets when opening a harness directly, and the **live** study
persona (`study.md`) named no writer — it told the mentor to *show the learner* a `studyloop topic` command
and never to write anything itself. That is the defect in its exact live form, and none of the three seats
saw it (grok's table says "Codex / pi / Grok — shared See-line on `AGENTS.md`", which is the installed
file). Fixed: `study.md` gains a Recording section and lists the writers; `co-study.md` names the same four
under its student-drives rule; `test_the_built_live_persona_names_each_writer` pins the **built** string for
both modes; the docs contract adds both live personas to `DEFINITIONS`; receipt §5(a) records the
correction. The RED as first written was **vacuous on this axis** — it pinned files no live session reads —
which is the kind of gap question (d) of the brief asked about, and the seats did not find it.

### Rejected or not taken, with reasons

- **grok Y4 — thread `study_session_id` into `observations.record(source_session_id=…)`.** The seat's
  mechanism is wrong. `observations.record` (`history/observations.py:66–74`) treats `source_session_id` as
  a *native* session with captured evidence: it calls `capture_session_input(conn, source_session_id)` and
  raises `ScopeError("Source-linked progress requires nonempty captured input")` when there is none. A study
  session id has no captured input, so the write would fail exactly as the RED's attempt did through
  `records.bind`. Rejected; N1's report-only resolution stands (astra: "Accept the correction for this
  patch"). Session-level provenance for a teach-back is a storage-layer question for its own issue.
- **qwen R1 — "the test still asserts the old expectation".** False. `test_mcp_teachback.py:166–184`
  asserts `result["study_session_id"] == "study-7"` and the row's `session_id` is `None`, which is the
  corrected expectation. The seat appears to have read the RED commit's text rather than the tree.
- **qwen Y — `tutor-checkpoint` residue in the Kiro persona.** False. `grep tutor-checkpoint
  agents/kiro/study-mentor/persona.md` returns nothing on `3c175f78`. The CLI examples the seat names
  (`studyloop teachback`, `session-query`) are the learner's own path, kept on purpose.
- **qwen's REJECT** rests on R1 and R2; R1 is refuted and R2 is a wording improvement. The verdict is not
  sustained.
- **astra Y1 (UNVERIFIED by the seat) — coercion may accept bools/floats.** Refuted by running it:
  `coerce_scores([True]*5)`, `[3.0,3,4,3,2]` and `[3.7,3,4,3,2]` all raise `ValueError("scores must be
  integers from 1 to 4")` — the `str()` round-trip makes `int("True")` and `int("3.0")` fail. Digit strings
  are accepted, which mirrors the CLI's shell input by design.

### Verification after fixes (tree `616fd1ed`)

RED files + install contracts + isolation + CLI + launcher + prompt contract + session-start-purpose +
plan-architect persona: **257 passed**. ruff, format, pyright clean on every touched file; mkdocs strict
clean; `agents/manifest.json` regenerated (only `shared/recording-protocol.md` changed hash);
`.secrets.baseline` via whole-repo scan (72 → 72 files, no entry moved).

### Process findings

- A second seat probe with `max_tokens=4` returned "empty content" for the two reasoning models — a budget
  artefact, not an auth failure; the real run (16 000) answered in 50 s / 42 s / 7 s.
- Verifying a seat's *mechanism* (grok Y2, grok Y4) rather than only its *claim* is what surfaced the live-
  persona gap and refuted the `source_session_id` proposal. Both would have passed a claim-level check.

## Gate decision

**ACCEPT** for merge at `616fd1ed`, subject to CI. The S1-SIM stage remains owner-gated and is the only
place the claim *"pipe open on {passed}; plumbing proven for all six definitions; noticing observed once"* can
be made; grok's ten-item SIM list (seat transcript §(e)) is adopted as that stage's checklist, with the
refusal path (item 2), Claude `tools:`-line reachability (item 7) and installed-path resolution of
`agents/shared/…` (astra Y3) as the three that decide whether a harness is in `{passed}`.
