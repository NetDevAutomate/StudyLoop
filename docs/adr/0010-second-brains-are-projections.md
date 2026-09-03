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
   Backends render **projections** of it; nothing in a backend, the CLI or an
   agent protocol writes the plan file. Pulling notes is an explicit command
   that returns text for the learner and agent to fold in through
   `studyloop plan …`.
2. Providers hide behind a small runtime-checkable `SecondBrain` protocol
   (six methods), selected only from configuration (`second_brain.provider`,
   default `none`); no environment variable selects a provider. With `none`
   nothing is imported, written or offered.
3. A projection is StudyLoop's file: it carries a `studyloop:` frontmatter
   marker and is regenerated atomically and idempotently; a file without the
   marker is never overwritten. Every write resolves under the configured
   vault folder.
4. Obsidian is served by plain files; the official Obsidian CLI is an optional
   adapter that degrades to files. xTiles is served in stage 1 by docs, prompts
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
- The Obsidian CLI grammar is unversioned; a change costs one adapter file.

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
- **A web-UI "send to second brain" button.** Pulls in e2e and frontend
  ownership for no new capability; the CLI is the agent's and the learner's path.
