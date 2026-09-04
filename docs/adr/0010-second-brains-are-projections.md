# ADR-0010 — Second brains are projections; plan Markdown is the source of truth

**Status:** Proposed, 2026-09-03. Motivated by change `openspec/changes/second-brain/`
(R-84, 0.2.0). Contract: `docs/architecture/second-brain.md`.

## Context

Learners keep their thinking somewhere: an Obsidian vault, xTiles, a notebook.
StudyLoop already exports agent sessions into a vault (`AgentMemory/`) but its
study plans, next action and due reviews live only inside StudyLoop. The owner
wants a choice of "second brain" — a free, local option must exist beside any
paid one — and wants it to be invisible until chosen. Two ways to build it were
considered: two-way synchronisation (edits in the second brain flow back into
the plan) or one-way projection (the plan is rendered into the second brain;
notes come back only when the learner asks).

## Decision

1. The plan Markdown under `STUDYLOOP_PLANS_DIR` is the only source of truth.
   Backends render **projections** of it; **nothing in the second-brain layer
   writes it** — no backend, no `brain` command, no agent protocol.
   `studyloop plan …` is its only writer, and it writes through `render_plan`
   (parse → mutate the model → `save_plan`), so the document's shape stays the
   renderer's business. Pulling notes is an explicit command that returns text
   for the learner and agent to fold in through `studyloop plan …`.
   *(Amended 2026-09-04: the original clause said "nothing in a backend, the
   CLI or an agent protocol writes the plan file", which was untrue on the day
   it shipped — `plan new`, `plan milestone`, `plan status`, `plan evaluate
   --record` and `plan reindex` all write it, by design. The rule the code
   obeys, stated above, is what the clause always meant.)*
2. Providers hide behind a small runtime-checkable `SecondBrain` protocol
   (six methods), selected only from configuration (`second_brain.provider`,
   default `none`); no environment variable selects a provider. With `none`
   nothing is imported, written or offered.
3. A projection is StudyLoop's file: it carries a `studyloop:` frontmatter
   marker and is regenerated atomically and idempotently; a file without the
   marker is never overwritten. Every write resolves under the configured
   vault folder.
4. Obsidian is served by plain files and nothing else. An optional adapter for
   the official Obsidian CLI was built and withdrawn before release (see
   "Rejected alternatives"). xTiles is served in stage 1 by docs, prompts
   and an opt-in assistant skill; a programmatic client waits for a documented,
   versioned API.
5. No credential enters StudyLoop for this feature.

## Consequences

- Learners can edit projections, but edits are replaced on the next publish
  (with a warning); personal notes belong in the sibling `.notes.md` file.
- Two folders exist in a vault: `AgentMemory/` (session memory export) and
  `Study/` (projections). Docs explain the difference.
- Adding a provider means one module and one factory branch; the contract
  tests run against every backend.
- Writing plain files is the only Obsidian path, so there is no external
  program to probe, no unversioned command grammar to track, and no argv a
  second user on the machine could read.

## Rejected alternatives

- **Two-way sync.** Conflicts, silent plan changes from a tool the agent cannot
  see, and a second writer for the plan; violates the single-source rule.
- **StudyLoop as an MCP client to xTiles now.** Undocumented, unversioned tool
  contract behind a paid tier; StudyLoop would own someone else's API drift.
- **Writing projections into `AgentMemory/`.** Mixes machine session memory
  with study material the learner reads daily.
- **An environment-variable provider override** (as `STUDYLOOP_MULTIPLEXER`).
  Provider selection enables writes into the learner's files; it must be a
  deliberate config change.
- **An adapter for the official Obsidian CLI.** Built during development,
  withdrawn before release after a three-family model review: `obsidian-cli`
  resolves its target by vault *name*, so a machine with two vaults of the same
  name could receive the note in the wrong one, and the note body travelled as a
  command-line argument, readable by any other user on the machine. Writing the
  file directly is all this feature ever needed. The retired keys `use_cli`,
  `vault_name`, `template` and `daily_note` now raise a configuration error
  rather than being ignored, because `daily_note` used to append to the
  learner's own daily note and they have to be told it stopped.
- **A web-UI "send to second brain" button.** Pulls in e2e and frontend
  ownership for no new capability; the CLI is the agent's and the learner's path.
