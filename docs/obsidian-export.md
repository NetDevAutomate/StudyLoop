# Obsidian Vault Export

`session-export` can mirror your AI coding sessions into an Obsidian vault as
structured Markdown, alongside the usual SQLite export. The feature is **opt-in**
and shared across the supported harnesses — Kiro CLI, Codex, Claude Code,
OpenCode, and pi all flow into one folder, so your hand-written notes stay clean.

> Looking for the implementation spec or the GraphRAG follow-up? See
> `private-docs/obsidian-export.md` and `private-docs/obsidian-graphrag-roadmap.md`.

## What it produces

```
<vault>/
└── AgentMemory/
    ├── 2026-06-01-claude-code-myproject-1a2b3c4d.md   ← one note per session
    └── MOC/
        ├── _index.md                                  ← project index
        └── myproject.md                               ← per-project session list
```

Each note carries Dataview-ready YAML frontmatter:

```yaml
---
type: agent-memory
id: 2026-06-01-claude-code-myproject-1a2b3c4d
created: 2026-06-01
updated: 2026-06-01
status: active
source_tool: claude_code
source_project: myproject
session_id: <full id>
git_branch: main
tags: [agent-memory, claude_code]
date: 2026-06-01
about: []
content_hash: 39fa1138
---
```

The body holds a summary, key points, and a `## Related` section of
`[[wikilink]]` backlinks to vault topic notes whose titles or aliases match the
session. Per-project **MOC** (map-of-content) notes list every session for a
project in reverse-chronological order.

## How `AgentMemory/` differs from your study notes

`obsidian_base` (the flat config key) points StudyLoop at your **study sources** —
the notes you write and study from. The `obsidian:` section configures this
**export sink** — machine-generated session memory. Keeping them in a separate
`AgentMemory/` folder means hundreds of auto-generated notes never dilute your
curated `Sessions/`/`Study/` material, while Dataview can still query across both.

## Enabling it

Three ways, in order of convenience:

**1. Per run (no config needed):**

```bash
session-export --obsidian                      # sessions touched this run
session-export --obsidian --obsidian-backfill  # one-time: ALL history (idempotent)
session-export --obsidian --obsidian-dry-run   # preview counts, write nothing
session-export --obsidian --obsidian-vault ~/Obsidian/Personal  # override path
session-export --no-obsidian                   # force-off even if config enables it
```

**2. Config (always on):** add to `~/.config/studyloop/config.yaml`:

```yaml
obsidian:
  export_enabled: true            # turn the gate on
  vault_path: ~/Obsidian/Personal # defaults to obsidian_base if omitted
  memory_dir: AgentMemory
  moc_dir: AgentMemory/MOC
  backlinks: true
  granularity: both               # both | session
```

**3. Setup wizard:** `studyloop setup` asks whether to enable export at the
Obsidian step and writes the section for you.

## Incremental vs backfill

- A plain `--obsidian` run only writes sessions **added or updated in that run**
  (computed by diffing session timestamps before/after export). It does not
  re-scan your whole history every time.
- `--obsidian-backfill` writes a note for **every** session in the database — the
  one-time "import everything" path. It is idempotent: a `content_hash` in each
  note's frontmatter means unchanged notes are skipped on re-runs.

## Querying exported sessions with Dataview

Because every note shares the `type: agent-memory` frontmatter, a Dataview block
surfaces your session history anywhere in the vault:

````markdown
```dataview
TABLE source_project AS Project, source_tool AS Tool, date
FROM "AgentMemory"
WHERE type = "agent-memory"
SORT date DESC
```
````

## Health checks

`studyloop doctor` (category `config`) validates the setup:

- the vault path exists and is a directory;
- it contains an `.obsidian/` marker (warns if not — likely not a vault root);
- when export is enabled, the `AgentMemory/` directory is writable.

```bash
studyloop doctor --category config
```

## Safety notes

- Notes are written **after** the SQLite export commits, so an export failure
  never leaves the vault half-written.
- The writer is **path-traversal hardened**: untrusted session fields (e.g.
  timestamps) are sanitised and a containment guard refuses any write outside
  `AgentMemory/`.
- Re-exports never duplicate: the content hash drives idempotent skips.

## AgentMemory exports versus Study projections

If you also use the [second-brain layer](second-brain.md), your vault has two
StudyLoop folders. They hold different things and neither reads the other.

| | `AgentMemory/` (this page) | `Study/` ([Second Brain](second-brain.md)) |
| --- | --- | --- |
| What it contains | one note per AI coding session | your study plans, today's action, due reviews, learning records |
| Where it comes from | the sessions database, via `session-export --obsidian` | your plan Markdown documents |
| Written by | `agent-session-tools` | `studyloop brain publish` |
| Turned on with | `obsidian.export_enabled` | `second_brain.provider` |
| Your own notes | not applicable | `Study/Plans/<plan-id>.notes.md`, which StudyLoop only reads |

The split is deliberate: session memory is machine-generated history, while a study
plan is material you read and revise. Mixing them would put a wall of transcript
notes in the folder you open to decide what to study.

## Related

- [Second Brain](second-brain.md) — publishing plans and today's study into a vault
- [Setup Guide → Obsidian session-memory export](setup-guide.md#obsidian-session-memory-export)
- [CLI Reference → Obsidian Vault Export](cli-reference.md#obsidian-vault-export-opt-in)
- [Architecture Overview](architecture.md)
