# Implementation Plan: v1.4 Features

**Date:** 2026-03-09
**Status:** In Progress
**Brainstorm:** [brainstorm-v1.4-features.md](brainstorm-v1.4-features.md)

---

## Implementation Order

1. Active Break Protocol (agent prompts + shared framework)
2. Session Wind-Down (agent prompts + shared framework)
3. Teach the Teacher (schema migration + CLI + agent prompts)
4. Dynamic Knowledge Bridging (schema migration + CLI + config + agent prompts)

---

## Feature 1: Active Break Protocol

### Files to Create
- `agents/shared/break-science.md` — Science-backed break protocol with tiered system

### Files to Modify
- `agents/shared/session-protocol.md` — Replace basic break reminders (lines 134-141) with references to break-science.md
- `agents/shared/audhd-framework.md` — Add ADHD break adaptations section
- `agents/claude/socratic-mentor.md` — Reference break-science.md
- `agents/kiro/skills/audhd-socratic-mentor/SKILL.md` — Reference break-science.md

### Design
- Three tiers: micro (2-3 min), short (5-10 min), long (15-20 min)
- Energy-adaptive intervals (high/medium/low energy → different frequencies)
- Wrap-up buffer for flow states (don't hard-stop mid-thought)
- "Just water" minimum when breaks are resisted
- Agent communicates the WHY (science) not just the instruction

---

## Feature 2: Session Wind-Down

### Files to Create
- `agents/shared/wind-down-protocol.md` — Post-session consolidation science and protocol

### Files to Modify
- `agents/shared/session-protocol.md` — Enhance end-of-session section (section 6) with wind-down references
- `agents/claude/socratic-mentor.md` — Reference wind-down protocol
- `agents/kiro/skills/study-mentor/SKILL.md` — Add wind-down to session end workflow

### Design
- Three phases: Session Wrap → Consolidation Guidance → Next Session Suggestion
- Based on NIH wakeful rest research (20x replay, 4x overnight consolidation)
- Time-of-day awareness for next session timing
- Voice mode support (spoken guidance for wind-down)

---

## Feature 3: Teach the Teacher

### Files to Create
- `agents/shared/teach-back-protocol.md` — Scoring rubric, detection probes, angle rotation

### Files to Modify
- `packages/agent-session-tools/src/agent_session_tools/migrations.py` — Migration v10: teach_back_scores table, study_progress extensions
- `packages/studyctl/src/studyctl/cli.py` — `studyctl teachback` and `studyctl teachback-history` commands
- `packages/studyctl/src/studyctl/history.py` — Teach-back score recording and querying
- `agents/shared/session-protocol.md` — Reference teach-back protocol in during-session section
- `agents/shared/socratic-engine.md` — Add teach-back questioning phase
- `agents/claude/socratic-mentor.md` — Reference teach-back protocol

### Database Migration v10
```sql
CREATE TABLE teach_back_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept TEXT NOT NULL,
    topic TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(id),
    score_accuracy INTEGER CHECK(score_accuracy BETWEEN 1 AND 4),
    score_own_words INTEGER CHECK(score_own_words BETWEEN 1 AND 4),
    score_structure INTEGER CHECK(score_structure BETWEEN 1 AND 4),
    score_depth INTEGER CHECK(score_depth BETWEEN 1 AND 4),
    score_transfer INTEGER CHECK(score_transfer BETWEEN 1 AND 4),
    total_score INTEGER GENERATED ALWAYS AS (
        score_accuracy + score_own_words + score_structure + score_depth + score_transfer
    ) STORED,
    review_type TEXT NOT NULL,
    question_angle TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

ALTER TABLE study_progress ADD COLUMN last_teachback_score INTEGER;
ALTER TABLE study_progress ADD COLUMN angles_used TEXT;
ALTER TABLE study_progress ADD COLUMN mastery_signals TEXT;
```

### CLI Commands
- `studyctl teachback CONCEPT -t TOPIC --score "3,3,4,3,2" --type structured --angle "apply_network_analogy"`
- `studyctl teachback-history CONCEPT` — Show score progression

---

## Feature 4: Dynamic Knowledge Bridging

### Files to Create
- `agents/shared/knowledge-bridging.md` — Configurable bridge framework, discovery protocol

### Files to Modify
- `packages/agent-session-tools/src/agent_session_tools/migrations.py` — Migration v11: knowledge_bridges table
- `packages/studyctl/src/studyctl/cli.py` — `studyctl bridge add/list/history` commands
- `packages/studyctl/src/studyctl/history.py` — Bridge recording and querying
- `packages/studyctl/src/studyctl/settings.py` — knowledge_domains config section
- `agents/shared/network-bridges.md` — Reframe as default instance of configurable bridges
- `agents/shared/audhd-framework.md` — Reference configurable bridges instead of hardcoded networking
- `agents/claude/socratic-mentor.md` — Reference knowledge-bridging.md, configurable domain

### Database Migration v11
```sql
CREATE TABLE knowledge_bridges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_concept TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    target_concept TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    structural_mapping TEXT,
    quality TEXT DEFAULT 'proposed',
    times_used INTEGER DEFAULT 0,
    times_helpful INTEGER DEFAULT 0,
    created_by TEXT DEFAULT 'agent',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### Config Addition
```yaml
# ~/.config/studyctl/config.yaml
knowledge_domains:
  primary: networking
  anchors:
    - concept: "ECMP load balancing"
      comfort: 10
  secondary:
    - domain: "cooking"
      anchors: ["mise en place"]
  bridges: []  # populated by studyctl bridge add
```
