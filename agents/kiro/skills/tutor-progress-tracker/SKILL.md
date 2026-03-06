---
name: tutor-progress-tracker
description: Read and write to the shared tutor assessment database for cross-agent progress tracking
---

## Shared Progress Database

**Location**: Configured in `~/.config/studyctl/config.yaml`

**Purpose**: Single source of truth for skill assessments across all agents and machines.

---

## Quick Commands

```bash
# View progress dashboard
uv run tutor-progress

# Run checkpoint (auto-selects weakest skill)
uv run tutor-checkpoint code

# Target specific skill
uv run tutor-checkpoint code --skill oop_design

# View skill history
uv run tutor-progress history --skill oop_design --limit 10
```

---

## Primary Skills to Track (Phase 0)

| Skill | Weight | Focus |
|-------|--------|-------|
| `python_idioms` | 0.8 | Pattern implementations |
| `oop_design` | 0.5 | Classes, composition |
| `code_architecture` | 0.7 | Module organization |
| `architectural_thinking` | 0.8 | System design |

---

## Independence Levels

- **L1 Prompted**: Needed significant guidance
- **L2 Assisted**: Started independently, needed some help
- **L3 Independent**: Completed with minimal assistance
- **L4 Teaching**: Could explain this to others

---

## Cross-Agent Workflow

1. **Machine A**: Complete exercise → Record assessment
2. **Database**: Progress saved to shared SQLite
3. **Machine B**: Check progress → Continue study → Record assessment
4. **Result**: Seamless progress tracking across environments

---

## Configuration

```yaml
# ~/.config/studyctl/config.yaml
tutor:
  db_path: ~/path/to/sessions.db
  checkpoint_cadence_days: 7
```

---

## Study Plan Integration

Check progress before each session:
```bash
uv run tutor-progress
```

This shows:
- Current scores and trends
- Skills needing attention
- Recommended next checkpoint

Study plan path is configured in `~/.config/studyctl/config.yaml`.
