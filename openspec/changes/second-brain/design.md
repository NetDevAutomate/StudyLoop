## Context

Learners keep their thinking somewhere: an Obsidian vault, xTiles, a notebook.
StudyLoop already exports agent sessions into a vault (`AgentMemory/`), but its
study plans, next action and due reviews live only inside StudyLoop. The owner
wants a choice of second brain — a free, local option must exist beside any paid
one — and wants it to be invisible until chosen.

Two shapes were on the table. **Two-way synchronisation** would let edits in the
note system flow back into the plan; **one-way projection** renders the plan into
the note system and brings notes back only when the learner asks. This design
takes projection, and ADR-0010 records why: sync creates a second writer for the
plan that the agent cannot see, which breaks the one thing the whole product
relies on being true.

Everything below follows from three fixed points: the plan Markdown under
`STUDYLOOP_PLANS_DIR` is the only source of truth; an unconfigured feature must
be provably inert; and a write into a learner's own files must be refusable
before it happens rather than apologised for afterwards.

## Goals / Non-Goals

**Goals:**

- A provider-agnostic protocol with an exact, guarded method set.
- Projections of the plan and of "today" into Obsidian as plain files.
- Provable inertness when no provider is configured.
- A mechanical rule for "never overwrite the learner's own note".
- An explicit, read-only path for pulling the learner's notes back.
- xTiles served in stage 1 without a client and without a credential.

**Non-Goals:**

- Two-way synchronisation, or any second writer for the plan file.
- A programmatic xTiles client.
- A web-UI control or an MCP publish tool.
- Shipping or depending on third-party Obsidian MCP servers.

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D1 | `typing.Protocol` + `@runtime_checkable`, six methods | Follows the `multiplexer.py` precedent; an exact-method-set guard prevents the protocol growing silently. |
| D2 | Projections, not sync; plan Markdown is the only writer-of-record | Owner rule; recorded as ADR-0010 because it will still be load-bearing when someone asks why edits do not flow back. |
| D3 | Package layout `second_brain/{core,factory,obsidian,obsidian_cli,projection,backlinks,templates}`, with providers imported only inside `get_backend` | Makes "`none` imports nothing" provable with a `sys.modules` assertion rather than a code review. |
| D4 | The file writer is the fallback; the official Obsidian CLI is used when `use_cli` resolves to CLI — default `auto` means the binary is on PATH and the app answers a probe; `on` warns and falls back when it cannot; `off` never spawns | The Obsidian app must be running for its CLI to answer, and its grammar is unversioned; neither can be a precondition for publishing. |
| D5 | An ownership marker in frontmatter is the mechanical form of "never overwrite user notes" | Turns a policy into a refusal a test can assert. |
| D6 | Atomic temp-file plus `os.replace`; SHA-256 content hash excluding itself and any timestamp | Gives idempotence without reading a clock, so a republish is a no-op rather than a churned mtime. |
| D7 | Backlinks resolve through a lazy import of the export sink's matcher, with a warn-once fallback | That matcher lives in the other workspace package and is not in the wheel; a hard import would make backlinks a install-time dependency. |
| D8 | Templates ship as package data under `studyloop/data/templates/obsidian/`, with one shared heading constant | The wheel ships `src/studyloop` only, so a repo-root template directory would be absent at runtime. |
| D9 | A `live_obsidian` pytest marker, deselected by default in both pyproject files | The live CLI needs the app running against a dedicated test vault; that is one machine, not CI. |
| D10 | No environment-variable provider override | Selecting a provider enables writes into the learner's files; unlike a multiplexer choice, it must be a deliberate config change. |
| D11 | The wind-down offer is gated on `configured && supports_publish`, once per session | Autonomy rule: no repeated nudging. xTiles stage 1 cannot publish, so it must not be offered. |
| D12 | `daily:append` sits behind `daily_note: true` **and** an effective CLI mode, once per day | It is the only write into a note the learner owns outright, so it is double opt-in and rate-limited. |
| D13 | The xTiles wind-down skill is ONE shared body installed to every detected harness by `studyloop install agents`, self-gated on `provider: xtiles` plus a connected `xtiles` MCP server | One writer of the behaviour instead of per-harness copies; self-gating keeps it silent when unconfigured, so no conditional installation logic is needed. |

## Alternatives considered

- **Two-way synchronisation.** Rejected. Conflicts, silent plan changes from a
  tool the agent cannot see, and a second writer for the plan; it violates the
  single-source rule that everything else depends on.
- **StudyLoop as an MCP client to xTiles now.** Rejected. The tool contract is
  undocumented and unversioned behind a paid tier, so StudyLoop would own
  someone else's API drift. Stage 1 gets docs, prompts and an opt-in skill; a
  client waits for a documented, versioned API.
- **Writing projections into `AgentMemory/`.** Rejected. That folder is machine
  session memory; mixing it with study material the learner reads daily makes
  both harder to trust. Two folders, explained in the docs, is the cheaper
  answer.
- **An environment-variable provider override**, by analogy with
  `STUDYLOOP_MULTIPLEXER`. Rejected (D10). Choosing a multiplexer changes where
  a pane appears; choosing a provider enables writes into the learner's files.
- **A web-UI "send to second brain" button.** Rejected. It pulls e2e and
  frontend ownership into the change for no new capability; the CLI is both the
  agent's path and the learner's.
- **An MCP publish tool.** Rejected for the same reason plus one more: it would
  let a model publish without the learner asking, which is exactly the once-only
  offer gate in D11 being routed around.

## Consequences

- Learners can edit a projection, but the edit is replaced on the next publish
  with a warning; personal notes belong in the sibling `.notes.md` file.
- A vault ends up with two StudyLoop-adjacent folders, `AgentMemory/` and
  `Study/`; the docs have to explain the difference, and do.
- Adding a provider costs one module and one factory branch, because the shared
  contract test runs against every registered backend.
- The Obsidian CLI grammar is unversioned, so a change upstream costs one
  adapter file and nothing else.
