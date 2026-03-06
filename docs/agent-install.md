# Agent Installation Guide

How to set up the AI mentor agents for kiro-cli and Claude Code.

## Table of Contents

- [What are AI Agents?](#what-are-ai-agents)
- [Automatic Installation](#automatic-installation)
- [Kiro CLI Setup](#kiro-cli-setup)
- [Claude Code Setup](#claude-code-setup)
- [Agent Descriptions](#agent-descriptions)
- [Skills Reference](#skills-reference)
- [Uninstalling](#uninstalling)

## What are AI Agents?

AI agents are custom personas you load into tools like kiro-cli or Claude Code. Instead of a generic assistant, you get a Socratic mentor that knows your learning style, tracks your progress, and teaches through questioning rather than lecturing.

This project ships three agents:
- **study-mentor** (kiro-cli) — full study pipeline with spaced repetition
- **socratic-mentor** (Claude Code) — Socratic questioning with Clean Code/GoF pedagogy
- **mentor-reviewer** (Claude Code) — autonomous code review with scoring

## Automatic Installation

The install script detects which AI tools you have and symlinks the agent definitions:

```bash
./scripts/install-agents.sh
```

It checks for `~/.kiro/` and `~/.claude/` directories. If found, it creates symlinks from the repo's `agents/` directory into the tool's config.

Options:

```bash
./scripts/install-agents.sh --kiro      # Kiro CLI only
./scripts/install-agents.sh --claude    # Claude Code only
./scripts/install-agents.sh --uninstall # Remove all agent links
```

## Kiro CLI Setup

### Prerequisites

- [kiro-cli](https://github.com/aws/kiro-cli) installed
- `~/.kiro/` directory exists

### What gets installed

The script creates symlinks for:

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/kiro/study-mentor.json` | `~/.kiro/agents/study-mentor.json` | Agent definition |
| `agents/kiro/study-mentor/` | `~/.kiro/agents/study-mentor/` | Agent persona and resources |
| `agents/kiro/skills/study-mentor/` | `~/.kiro/skills/study-mentor/` | Session workflow skill |
| `agents/kiro/skills/audhd-socratic-mentor/` | `~/.kiro/skills/audhd-socratic-mentor/` | Teaching methodology skill |
| `agents/kiro/skills/tutor-progress-tracker/` | `~/.kiro/skills/tutor-progress-tracker/` | Progress tracking skill |

### Starting a session

```bash
kiro-cli chat --agent study-mentor
```

The agent will automatically:
1. Run `studyctl status` to check sync state
2. Run `studyctl review` to find what's due for spaced repetition
3. Run `studyctl struggles` to identify recurring struggle areas
4. Ask your energy level to match session type

### Customizing

Edit the persona at `agents/kiro/study-mentor/persona.md` to adjust:
- Session start behaviour
- Teaching style preferences
- Which CLI commands run automatically

Edit skills in `agents/kiro/skills/` to modify:
- Socratic questioning patterns
- Network→Data Engineering bridges
- Progress tracking thresholds

## Claude Code Setup

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- `~/.claude/` directory exists

### What gets installed

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/claude/socratic-mentor.md` | `~/.claude/agents/socratic-mentor.md` | Socratic teaching agent |
| `agents/claude/mentor-reviewer.yaml` | `~/.claude/agents/mentor-reviewer.yaml` | Code review agent |

### Starting a session

```bash
# Socratic mentor — guided learning
/agent socratic-mentor

# Code reviewer — autonomous review with scoring
/agent mentor-reviewer
```

### Customizing

- **socratic-mentor**: Edit `agents/claude/socratic-mentor.md` — it's a markdown file with the full persona, questioning techniques, and learning session orchestration
- **mentor-reviewer**: Edit `agents/claude/mentor-reviewer.yaml` — configure output directories, scoring methodology, and review format

The mentor-reviewer supports environment variable configuration:
- `MENTOR_REVIEW_OUTPUT_DIR` — where review reports are saved (default: `./reviews`)
- `MENTOR_TUTORIAL_DIR` — where tutorials are generated (default: `./tutorials`)

## Agent Descriptions

### study-mentor (kiro-cli)

The primary study agent. Integrates with the full studyctl pipeline:

- Checks spaced repetition schedule before each session
- Detects struggle topics from your session history
- Syncs notes to NotebookLM and queries them during teaching
- Records progress via `tutor-checkpoint`
- Adapts session type to your energy level (deep study, light review, body doubling)
- Uses network→data engineering analogies for concept bridging

### socratic-mentor (Claude Code)

A focused Socratic teaching agent built around Clean Code and GoF Design Patterns:

- Teaches through progressive questioning (observation → pattern → principle → application)
- Embeds knowledge from Clean Code (Robert C. Martin) and GoF Design Patterns
- Adapts question difficulty based on demonstrated understanding
- Tracks principle mastery: discovered → applied → mastered
- Never gives direct answers unless explicitly asked (or after 4+ rounds stuck)

### mentor-reviewer (Claude Code)

An autonomous code reviewer that runs without prompting:

- Reads all code files, analyzes against SOLID/OWASP/testing standards
- Scores across 5 categories (1-10): Architecture, Testing, Code Quality, Security, Performance
- Generates detailed reports with critical issues, improvements, and learning opportunities
- Creates tutorials for concepts scoring below 5/10
- Tracks score trends across reviews with evidence-based assessments
- Brutally honest — no praise for mediocre code

## Skills Reference

Skills are modular knowledge packages that agents load for specific capabilities.

### audhd-socratic-mentor

The core teaching methodology skill. Defines:
- Socratic questioning framework (70% questions / 30% strategic info drops)
- AuDHD cognitive support patterns (executive function scaffolding, overload prevention)
- Network→Data Engineering concept bridges (BGP→event streaming, VLAN→data lake zones)
- The golden rule: never give direct answers, guide discovery through productive struggle

### study-mentor

Session workflow and pipeline integration. Defines:
- Session start protocol (status → review → struggles → energy check)
- Spaced repetition schedule and review types
- NotebookLM query integration
- Session type selection based on energy level

### tutor-progress-tracker

Cross-agent progress tracking. Provides:
- Shared assessment database for skill scores
- `tutor-checkpoint` CLI integration
- Score history and trend tracking
- Skill-specific progress queries

## Uninstalling

Remove all symlinks created by the installer:

```bash
./scripts/install-agents.sh --uninstall
```

This only removes symlinks that point into this repo. It won't touch agent files you've created manually or from other sources. Any existing files that were backed up during installation (with `.bak` suffix) remain untouched.
