---
name: tutor-progress-tracker
description: Read and write to the shared tutor assessment database for cross-agent progress tracking
---

## Shared Progress Database

**Location**: The database StudyLoop resolves via `database.path` in
`~/.config/studyloop/config.yaml` (or `STUDYLOOP_DB` for a test/dev override).

**Purpose**: Single source of truth for skill checkpoints across all agents and
machines. `tutor-checkpoint` writes each checkpoint as a `study_mentor` session
in the shared sessions database — the same database every harness's
`session-export` writes to — so a checkpoint recorded on Machine A is visible
to Machine B through ordinary session search.

---

## Quick Commands

```bash
# Record a checkpoint for a skill, with free-text notes
uv run tutor-checkpoint oop_design --notes "Implemented composition over inheritance unprompted"

# Record a checkpoint with no notes
uv run tutor-checkpoint python_idioms

# Find prior checkpoints for a skill (checkpoints are ordinary sessions)
session-query search "oop_design" --project "$PWD"
```

`tutor-checkpoint --help` shows the full signature: `SKILL` is a required
positional argument; `--notes` is the only option.

---

## Primary Skills to Track (Phase 0)

Use these as the `SKILL` argument — they are naming conventions, not a
database-enforced enum:

| Skill | Focus |
|-------|-------|
| `python_idioms` | Pattern implementations |
| `oop_design` | Classes, composition |
| `code_architecture` | Module organization |
| `architectural_thinking` | System design |

---

## Independence Levels

Record the level in `--notes` — there is no separate scored field for it:

- **L1 Prompted**: Needed significant guidance
- **L2 Assisted**: Started independently, needed some help
- **L3 Independent**: Completed with minimal assistance
- **L4 Teaching**: Could explain this to others

---

## Cross-Agent Workflow

1. **Machine A**: Complete exercise → `uv run tutor-checkpoint <skill> --notes "<notes>"`
2. **Database**: Checkpoint saved as a `study_mentor` session in the shared SQLite database
3. **Machine B**: `session-query search "<skill>"` → continue study → record another checkpoint
4. **Result**: Seamless progress tracking across environments

---

## Study Plan Integration

Before each session, search prior checkpoints for the topic you are about to
teach:

```bash
session-query search "<skill>" --project "$PWD"
```

This surfaces past notes for that skill — recorded level, what was struggled
with, what to check next. There is no separate scored dashboard; the
checkpoint notes themselves are the record.
