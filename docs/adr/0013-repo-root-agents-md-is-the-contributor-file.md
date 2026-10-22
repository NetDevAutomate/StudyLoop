# ADR-0013: The repo-root `AGENTS.md` is the contributor file; the installer never links into the checkout

**Status:** Accepted, 2026-10-22 (proposed and implemented the same day; the owner accepted the
eight pass-3 records together at 16:36 BST) · **Date:** 2026-10-22 · **Deciders:** council pass 3
of the 2026-10-21 full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6,
deepseek-r1, mistral-large-3), arbitrated by argument by the review coordinator under the owner's
standing delegation; accepted by Andy Taylor (owner). · **Change:** 2026-10-22 council pass 3, ruling D1 (vote 5–0 for the option taken);
implemented in `309074c7` (lane F's patch, landed by the coordinator with the doctor and test
changes the lane did not own).

The council record (`reviews/2026-10-21-full-repo-review/`: brief §D1, `ARBITRATION-pass3.md` §D1,
lane log `lanes/F-3.md`) is gitignored and exists only on the owner's machine. Everything this
record relies on is restated here. Symbols were read at `309074c7`.

## Context

Two conventions met at one path. The `AGENTS.md` convention (Codex, Grok Build, pi and others)
means "instructions for an agent working in this directory". StudyLoop's Codex/Grok mentor
persona is also a file called `AGENTS.md`, because that is the only name those harnesses read.

Until this decision the repository root carried `AGENTS.md -> agents/codex/AGENTS.md`, a
git-tracked symlink (mode `120000`), and `installers.py` declared
`LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md")` for both Codex and Grok, so
`studyloop install agents --tool codex|grok` created that link and `--uninstall` removed it with
`unlink()`, leaving `git status` reporting `deleted: AGENTS.md` in the learner's checkout.

The verified facts that decided it:

- **The launch path never used the root link.** `adapters/codex.py`, `adapters/grok.py` and
  `adapters/pi.py` write the persona as `AGENTS.md` into the per-session directory
  `studyloop study` launches the harness in. The root link mattered only when Codex or Grok Build
  was opened *in the StudyLoop checkout itself*, which is what a contributor does and a learner
  does not.
- **The consequence was already live.** Every coding agent opened in this repository was told
  "You are a strict Socratic mentor, not a code assistant", and the review's lane 5 had just
  removed the one developer-tooling block from that persona (learners must not receive it), which
  also removed the only developer steering Codex and Grok had here.
- **An installer was mutating the tracked worktree.** Uninstall deleted a committed file.
- `studyloop doctor` hash-checked the root file for Codex and Grok, so a lane-scoped change to
  the root file alone would have told every contributor their Codex definition was outdated. The
  lane stopped at that ownership line and handed back a tested patch; the doctor change landed
  with it.

Not verified, and not relied on: whether Codex honours a user-global `~/.codex/AGENTS.md`, and
whether Grok Build has any global instruction location. pi does (`~/.pi/agent/AGENTS.md`, which
the installer already links).

## Decision

1. The repository root `AGENTS.md` is a **regular file for contributors and the coding agents
   they run**: what this repository is, where the gates live (`Justfile` recipes, the `uv run`
   prefix, the one-at-a-time e2e lock), the pointers (`CONTRIBUTING.md`, `docs/contributor-*.md`),
   and the two rules agents keep tripping on (`agents/manifest.json` hash update on any persona
   edit; `reviews/` is gitignored). It states plainly that the learner persona is not here.
2. **The installer never writes into the checkout.** The two `{repo_root}` `LinkSpec`s are gone;
   install and uninstall for Codex and Grok leave a committed checkout byte-identical.
3. **Persona delivery for Codex and Grok is per session only**: the adapter writes it into the
   session directory. `studyloop doctor` reports Codex and Grok as per-session personas (an info
   row; no hash check, because there is no installed file to hash) and never warns about a file
   nothing reads.
4. Option (c) below is **deferred, not rejected**: a user-global link adds value only if Codex
   honours a global `AGENTS.md`, which is unverified. The question is recorded, not guessed at.

Grounding adopted by the council: separation of concerns (the two audiences get two files), and
"tooling never mutates the tracked worktree".

## Alternatives considered

- **(a) Keep the dual use; make `--uninstall` skip git-tracked link targets and document that the
  checkout's `AGENTS.md` is the learner persona.** Rejected: it keeps telling every contributor's
  agent that it is a Socratic mentor, and it keeps a persona delivery path that the launcher does
  not use. The uninstall fix alone treats the symptom.
- **(c) As taken, plus link the persona to a user-global location where one exists.** Deferred
  (see Decision 4). Cheap to add later; wrong to add on an unverified assumption about Codex.

## Consequences

- A learner who opens Codex or Grok Build inside the clone *without* the launcher no longer gets
  the mentor there. `studyloop study` is the supported path and is unaffected.
- `agents/codex/AGENTS.md` remained tracked and hashed in `agents/manifest.json` but, once the root
  link was gone, was read by nothing at runtime: the launcher builds personas from
  `agents/shared/personas/`. *Resolved 2026-10-22 (remediation plan 4, item 2): the file and its
  manifest entry were retired; Codex and Grok Build have no tracked definition.*
- `docs/agent-install.md` no longer says Codex and Grok "read the StudyLoop `AGENTS.md`"; it says
  they read the per-session copy the launcher writes.
- Four doctor tests that pinned the old contract were rewritten to the new one; the text-contract
  test checks the sources learners actually receive (installed links plus
  `agents/shared/personas/`), not the repository root.

## Verification

`packages/studyloop/tests/test_repo_root_agents_md.py`: the root file is a regular file and does
not carry the Socratic-mentor identity line; it points at the gates and the two trip wires; no
install link targets the checkout; install-then-uninstall for Codex and Grok (sandboxed `HOME`,
copied repo) leaves the committed checkout clean. Doctor behaviour: `test_doctor_agents.py`.
The symlink became a regular file in one commit (`309074c7`) so history shows the type change.
