# Architecture Decision Records

Short, immutable records of decisions that were *not* obvious — where a
reasonable engineer could have chosen differently, and where the reason
would otherwise be lost.

## Relationship to OpenSpec

| Artefact | Answers | Lifecycle |
|---|---|---|
| `openspec/specs/<cap>/spec.md` | What the system does, normatively | Living — updated on archive |
| `openspec/changes/<change>/design.md` | How this change is built | Archived with the change |
| `docs/adr/NNNN-*.md` | Why we chose X over Y | **Immutable** — superseded, never edited |

A `design.md` dies with its change. An ADR outlives it. When a design
decision will still be load-bearing in six months — when someone will read
the code and ask "why on earth is it done this way?" — it gets an ADR, and
`design.md` links to it rather than restating it.

## Conventions

- Filename: `NNNN-kebab-case-title.md`, zero-padded, never reused.
- Status: `Proposed` → `Accepted` → (`Superseded by ADR-NNNN` | `Deprecated`).
- An accepted ADR is **never edited** except to change its status line. A
  changed mind means a new ADR that supersedes it.
- Every ADR names the change that motivated it, so the full context is
  recoverable from `openspec/changes/` (or its archive).

## Index

| ADR | Title | Status | Change |
|---|---|---|---|
| [0001](0001-body-double-reuses-session-start-endpoint.md) | Body Double reuses `POST /api/session/start` | Proposed | `body-double-own-agent-picker` |
| [0002](0002-origin-scoped-live-agent-console.md) | Origin-scoped addressing for `liveAgentConsole()` | Proposed | `body-double-own-agent-picker` |
| [0003](0003-body-double-exempt-from-park-first-friction.md) | Body Double is exempt from park-first friction | Proposed | `body-double-own-agent-picker` |
| [0004](0004-retire-terminal-panel-from-body-double.md) | Unmount `terminalPanel()` without deleting it | Proposed | `body-double-own-agent-picker` |
